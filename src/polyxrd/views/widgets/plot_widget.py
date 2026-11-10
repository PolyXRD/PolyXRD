"""
XRD绘图控件
===========
基于matplotlib的可交互XRD绘图控件。

纵坐标支持 **线性 / 对数 / 方根** 三种显示 (v0.12.0):
左键点击 Y 轴区域循环切换, 右键点击弹出菜单精确选择。数值换算由 matplotlib
的 log / function 刻度完成, 刻度标签上仍是真实强度。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from polyxrd.i18n import tr
from polyxrd.models.peak import Peak
from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.mpl_font import ensure_cjk_font
from polyxrd.views.widgets.plot_toolbar import PlotToolBar
from polyxrd.views.widgets.toolbar_icons import colorize_nav_toolbar
from polyxrd.views.widgets.y_scale import (
    Y_SCALE_LOG,
    Y_SCALE_SQRT,
    YScaleController,
    hint_text,
)

# 图上标题/图例含中文 → 建图前先插系统中文字体, 否则画成豆腐块。
ensure_cjk_font()

#: 可激活的谱图操作工具（与 PlotToolBar.MODE_TOOLS 对应）
_PLOT_TOOLS = ("zoom_x", "zoom_y", "zoom_rect", "crosshair")


class PlotWidget(QWidget):
    """XRD交互绘图控件

    Features:
    - 绘制单个/多个XRD图谱
    - 峰标注
    - 图例
    - 坐标信息
    - 框选区域
    - 重置视图
    - 导出图片
    - 纵坐标线性/对数/方根切换 (左键点 Y 轴循环, 右键菜单选择)

    Signals:
        peak_clicked: 点击峰
        range_selected: 框选范围
    """

    peak_clicked = Signal(object)
    range_selected = Signal(float, float)
    cursor_info = Signal(str)

    # M22: X 轴交互参数
    _X_MARGIN_RATIO = 0.01   # 首屏边距 (数据宽度的 1%)
    _X_ZOOM_STEP = 0.15      # 每格滚轮缩放幅度
    _X_OVERSCAN = 0.20       # 允许越出数据范围的比例

    def __init__(self, parent: Optional[QWidget] = None, *, compact: bool = False) -> None:
        super().__init__(parent)
        self._ylabel_base = "Intensity"
        # v5.4.0: 谱图操作工具状态（复位/框选缩放/平移/步进缩放/十字线）
        self._tool: Optional[str] = None
        self._band = None                     # 拖拽中的橡皮筋 (matplotlib Rectangle)
        self._band_start: Optional[tuple[float, float]] = None
        self._cursor_line = None              # 十字线竖线 artist
        self._cursor_text = None              # 角度标注 artist
        self._cursor_x: Optional[float] = None
        # v2.6.0: compact 模式 —— 无工具栏/按钮行/标题的扁条形图,
        # 供精修页残差条使用 (GSAS-II/MAUD 风格: 主图下一条残差, 不独立成区)
        self._compact = compact
        self._setup_ui()
        self._data_list: list[XRDData] = []
        self._peaks: list[Peak] = []
        self._peak_artists: list = []
        self._match_artists: list = []
        self._span_selector: Optional[SpanSelector] = None
        # M22: X 轴交互状态
        self._data_xlim: Optional[tuple[float, float]] = None  # 数据范围(含边距), Home/缩放 clamp 基准
        self._pan_state: Optional[dict] = None                 # 左键拖动平移状态
        self._pending_peak: Optional[Peak] = None              # 按下命中的峰, 位移 <3px 才算点击
        # 纵坐标刻度控制器 (必须在 _axes 建好之后挂)
        self._y_scale = YScaleController(
            self._canvas,
            axes_getter=lambda: [self._axes],
            label_getter=lambda _ax: self._ylabel_base,
            repaint=self._canvas.draw_idle,
            on_change=self._on_y_scale_changed,
            parent=self,
        )
        self._install_x_interaction()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # matplotlib Figure
        fig_h = 1.4 if self._compact else 5
        self._figure = Figure(figsize=(8, fig_h), dpi=100, tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setMinimumHeight(60 if self._compact else 300)
        self._canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self._canvas.mpl_connect("motion_notify_event", self._on_mouse_move)

        if self._compact:
            # 紧凑残差条: 只有画布本身。无工具栏/按钮/标题/Y 轴交互面板,
            # 高度锁定在一条的量级, 让主对比图拿走全部纵向空间。
            self._toolbar = None
            # hint 标签仍要存在: _on_y_scale_changed 会写它 (compact 下无右键
            # 菜单入口, 该回调理论上不触发, 但不能因缺属性而崩)
            self._y_scale_hint = QLabel()
            self._y_scale_hint.hide()
            layout.addWidget(self._canvas)
            self._axes = self._figure.add_subplot(111)
            self._axes.set_xlabel("2θ (°)")
            self._axes.set_ylabel("Δ")
            self._axes.grid(True, alpha=0.3)
            self._canvas.setMinimumHeight(60)
            self._canvas.setMaximumHeight(130)
            return

        # 导航工具条（matplotlib 原生，换彩色图标）
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        colorize_nav_toolbar(self._toolbar, chip=30)

        # 谱图操作行（v5.4.0：复位 / 框选缩放 / 平移 / 步进缩放 / 十字线）
        self._plot_toolbar = PlotToolBar(self, self)
        self.cursor_info.connect(self._on_cursor_info)

        # 纵坐标模式提示 (随切换实时更新，保持在谱图下方一行)
        self._y_scale_hint = QLabel()
        self._y_scale_hint.setStyleSheet("QLabel { color: #555; font-size: 11px; }")
        self._y_scale_hint.setToolTip(tr("vw.plot_widget.y_scale_hint_tip"))

        layout.addWidget(self._toolbar)
        layout.addWidget(self._plot_toolbar)
        layout.addWidget(self._canvas)

        hint_row = QHBoxLayout()
        hint_row.addWidget(self._y_scale_hint)
        hint_row.addStretch()
        layout.addLayout(hint_row)

        # 初始空白图
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("2θ (°)")
        self._axes.set_ylabel(self._ylabel_base)
        self._axes.set_title("XRD Pattern")
        self._axes.grid(True, alpha=0.3)

    # ------------------------------------------------------------------
    # 纵坐标刻度
    # ------------------------------------------------------------------

    def _on_y_scale_changed(self, _mode: str) -> None:
        self._y_scale_hint.setText(hint_text(self._y_scale.mode()))

    def retranslate(self) -> None:
        """切语言时重设本控件的静态文案 (纵坐标提示的正文也跟着刷)。"""
        if getattr(self, "_plot_toolbar", None) is not None:
            self._plot_toolbar.retranslate()
        self._y_scale_hint.setToolTip(tr("vw.plot_widget.y_scale_hint_tip"))
        # 提示正文由 hint_text() 生成, 换语言不会自动重算 → 这里按当前模式重设一次
        self._on_y_scale_changed(self._y_scale.mode())

    def set_y_scale_mode(self, mode: str) -> None:
        """外部设定纵坐标模式 (linear/log/sqrt)。"""
        self._y_scale.set_mode(mode)

    def get_y_scale_mode(self) -> str:
        """当前纵坐标模式。"""
        return self._y_scale.mode()

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def plot_data(
        self,
        data: XRDData,
        label: Optional[str] = None,
        color: Optional[str] = None,
    ) -> None:
        """绘制XRD数据

        Args:
            data: XRD数据
            label: 图例标签
            color: 线条颜色
        """
        self._data_list.append(data)
        lbl = label or f"Data {len(self._data_list)}"

        self._axes.plot(
            data.two_theta,
            data.intensity,
            label=lbl,
            color=color,
            linewidth=1.2,
        )
        self._axes.legend(loc="best")
        self._axes.relim()
        self._axes.autoscale_view()
        # M22: 横轴贴合数据实际 2θ 范围 (autoscale 默认 5% 边距对 XRD 过宽)
        self.fit_x_to_data()
        # 对数/方根模式下重新按新数据取正数据范围 (autoscale 已对 y 失效)
        self._y_scale.set_mode(self._y_scale.mode(), refit=True)
        # v5.4.0: 十字线工具激活时把竖线贴回新视场
        if self._tool == "crosshair" and self._cursor_x is not None:
            self._update_cursor(self._cursor_x)
        self._canvas.draw_idle()

    def clear_plot(self) -> None:
        """清除所有数据"""
        self._axes.clear()
        self._axes.set_xlabel("2θ (°)")
        self._axes.grid(True, alpha=0.3)
        self._data_list.clear()
        self._peaks.clear()
        self._peak_artists.clear()
        self._data_xlim = None  # M22: 数据没了, 缩放基准一并失效
        self._hide_cursor()     # v5.4.0: 十字线 artist 随 clear() 失效
        for artist in getattr(self, '_match_artists', []):
            artist.remove()
        self._match_artists = []
        # clear() 会把刻度与轴标题一起重置 → 按当前模式重新贴回去
        self._y_scale.set_mode(self._y_scale.mode(), refit=True)
        self._canvas.draw_idle()

    def set_info_text(self, text: str) -> None:
        """设置图信息文本（显示在标题或角落）"""
        self._axes.set_title(text, fontsize=10, loc='left', pad=5)
        self._canvas.draw_idle()

    def add_peak_annotations(self, peaks: list[Peak]) -> None:
        """添加峰标注

        Args:
            peaks: 峰列表
        """
        # 清除现有峰标注
        for artist in self._peak_artists:
            artist.remove()
        self._peak_artists.clear()
        if hasattr(peaks, "peaks"):
            peaks = peaks.peaks
        self._peaks = list(peaks)

        for peak in peaks:
            # 垂直虚线
            line = self._axes.axvline(
                peak.two_theta,
                color="red",
                linestyle="--",
                linewidth=0.8,
                alpha=0.7,
            )
            self._peak_artists.append(line)

            # 峰标注
            hkl_str = peak.hkl_str if peak.hkl else ""
            label = f"{peak.two_theta:.2f}°"
            if hkl_str:
                label += f"\n{hkl_str}"

            annotation = self._axes.annotate(
                label,
                xy=(peak.two_theta, peak.intensity),
                fontsize=7,
                ha="center",
                va="bottom",
                xytext=(0, 10),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="yellow", alpha=0.7),
            )
            self._peak_artists.append(annotation)

        self._canvas.draw_idle()

    def plot_fit_result(
        self,
        two_theta: np.ndarray,
        simulated: np.ndarray,
        residuals: Optional[np.ndarray] = None,
    ) -> None:
        """绘制拟合结果（实验+模拟+残差）

        Args:
            two_theta: 2θ数组
            simulated: 模拟强度
            residuals: 残差
        """
        # 模拟曲线
        self._axes.plot(
            two_theta,
            simulated,
            "r-",
            linewidth=1.5,
            alpha=0.7,
            label="Simulated",
        )

        # 残差（如果有）
        if residuals is not None and len(residuals) == len(two_theta):
            # 偏移显示残差
            y_min = np.min(simulated)
            residual_offset = y_min - 0.1 * (np.max(simulated) - y_min)
            self._axes.plot(
                two_theta,
                residuals + residual_offset,
                "k-",
                linewidth=0.8,
                alpha=0.5,
                label="Residuals",
            )
            self._axes.axhline(y=residual_offset, color="k", linewidth=0.5, alpha=0.3)

        self._axes.legend(loc="best")
        self._y_scale.set_mode(self._y_scale.mode(), refit=True)
        self._canvas.draw_idle()

    def set_x_range(self, x_min: float, x_max: float) -> None:
        """设置x轴范围"""
        self._axes.set_xlim(x_min, x_max)
        self._canvas.draw_idle()

    def set_y_range(self, y_min: float, y_max: float) -> None:
        """设置y轴范围"""
        self._axes.set_ylim(y_min, y_max)
        self._canvas.draw_idle()

    def reset_view(self) -> None:
        """重置视图 (保持当前纵坐标刻度模式)

        M22: X 回到数据实际范围而非 matplotlib 默认边距。
        """
        self._cancel_nav_mode()
        self._hide_cursor()
        self._axes.relim()
        self._axes.autoscale_view()
        self.fit_x_to_data()
        self._y_scale.set_mode(self._y_scale.mode(), refit=True)
        self._canvas.draw_idle()

    # ------------------------------------------------------------------
    # v5.4.0: 谱图操作工具（复位 / 框选缩放 / 平移 / 步进缩放 / 十字线）
    # ------------------------------------------------------------------

    def set_plot_tool(self, tool: Optional[str]) -> None:
        """切换谱图操作工具；``None`` = 恢复默认点击语义。

        与导航工具条的平移/框选互斥：开工具前先关掉它们，避免两套拖拽
        同时抢鼠标事件。
        """
        if tool is not None and tool not in _PLOT_TOOLS:
            return
        if tool is not None:
            self._cancel_nav_mode()
        self._tool = tool
        self._band = None
        self._band_start = None
        if tool == "crosshair":
            self._canvas.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._canvas.unsetCursor()
            self._hide_cursor()
            pb = getattr(self, "_plot_toolbar", None)
            if pb is not None:
                pb.set_hint("")
        self._canvas.draw_idle()

    def _cancel_nav_mode(self) -> None:
        """关掉导航工具条已激活的平移/框选。"""
        tb = getattr(self, "_toolbar", None)
        if tb is None:
            return
        acts = getattr(tb, "_actions", {})
        for key in ("pan", "zoom"):
            act = acts.get(key)
            if act is not None and act.isChecked():
                try:
                    getattr(tb, key)()
                except Exception:  # noqa: BLE001
                    act.setChecked(False)

    def pan_x(self, frac: float) -> None:
        """整体水平平移（``frac > 0`` 向右移，即视场往大角度走）。"""
        if not self._data_list:
            return
        lo, hi = sorted(self._axes.get_xlim())
        shift = (hi - lo) * float(frac)
        nl, nr = self._clamp_xlim(lo + shift, hi + shift)
        self._axes.set_xlim(nl, nr)
        self._scale_y_to_view()
        self._canvas.draw_idle()

    def zoom_scale(self, factor: float) -> None:
        """以视场中心为锚点整体缩放（``factor < 1`` 放大）。"""
        if not self._data_list or factor is None or factor <= 0:
            return
        lo, hi = sorted(self._axes.get_xlim())
        centre = 0.5 * (lo + hi)
        half = 0.5 * (hi - lo) * float(factor)
        nl, nr = self._clamp_xlim(centre - half, centre + half)
        self._axes.set_xlim(nl, nr)
        self._scale_y_to_view()
        self._canvas.draw_idle()

    def _scale_y_to_view(self) -> None:
        """按当前横向视场内的数据重设 y 范围（放大/平移后不留空屏）。"""
        if not self._data_list:
            return
        lo, hi = sorted(self._axes.get_xlim())
        ys = []
        for d in self._data_list:
            x = np.asarray(d.two_theta, dtype=float)
            y = np.asarray(d.intensity, dtype=float)
            m = (x >= lo) & (x <= hi) & np.isfinite(y)
            if m.any():
                ys.append(y[m])
        if not ys:
            return
        allv = np.concatenate(ys)
        mode = self._y_scale.mode()
        if mode == Y_SCALE_LOG:
            pos = allv[allv > 0]
            if pos.size == 0:
                return
            bottom = max(float(pos.min()) * 0.5, 1e-12)
            top = float(pos.max()) * 1.6
        elif mode == Y_SCALE_SQRT:
            bottom = 0.0
            top = float(np.clip(allv, 0.0, None).max()) * 1.15
            if top <= bottom:
                top = bottom + 1.0
        else:
            vmax = float(allv.max())
            bottom = min(0.0, float(allv.min()))
            top = vmax * 1.08 if vmax > 0 else 1.0
        try:
            self._axes.set_ylim(bottom, top)
        except (ValueError, TypeError):  # pragma: no cover - 极端数据兜底
            pass

    def _make_band(self, x: float, y: float):
        """创建/重置拖拽橡皮筋矩形。"""
        from matplotlib.patches import Rectangle

        if self._band is not None:
            try:
                self._band.remove()
            except Exception:  # noqa: BLE001
                pass
        self._band = Rectangle(
            (x, y), 0.0, 0.0, facecolor="#d32f2f", alpha=0.12,
            edgecolor="#d32f2f", lw=1.0, ls="--", zorder=6,
        )
        self._axes.add_patch(self._band)
        return self._band

    def _apply_band(self, x0, y0, x1, y1) -> None:
        """按工具语义把框选范围变成新的视场。"""
        span_x = abs(x1 - x0)
        span_y = abs(y1 - y0)
        cur_x = abs(self._axes.get_xlim()[1] - self._axes.get_xlim()[0])
        cur_y = abs(self._axes.get_ylim()[1] - self._axes.get_ylim()[0])
        if self._tool == "zoom_x":
            if span_x <= cur_x * 0.02:
                return
            lo, hi = sorted((x0, x1))
            nl, nr = self._clamp_xlim(lo, hi)
            self._axes.set_xlim(nl, nr)
            self._scale_y_to_view()
        elif self._tool == "zoom_y":
            if span_y <= cur_y * 0.02:
                return
            lo, hi = sorted((y0, y1))
            self._axes.set_ylim(lo, hi)
        elif self._tool == "zoom_rect":
            if span_x <= cur_x * 0.02 and span_y <= cur_y * 0.02:
                return
            if span_x > cur_x * 0.02:
                lo, hi = sorted((x0, x1))
                nl, nr = self._clamp_xlim(lo, hi)
                self._axes.set_xlim(nl, nr)
            if span_y > cur_y * 0.02:
                lo, hi = sorted((y0, y1))
                self._axes.set_ylim(lo, hi)

    def _update_cursor(self, x: float) -> None:
        """把红色十字竖线定位到 ``x`` 并报角度/强度。"""
        self._cursor_x = float(x)
        for a in (self._cursor_line, self._cursor_text):
            if a is not None:
                try:
                    a.remove()
                except Exception:  # noqa: BLE001
                    pass
        self._cursor_line = self._axes.axvline(
            x, color="#d32f2f", lw=1.0, ls="--", alpha=0.85, zorder=5,
        )
        self._cursor_text = self._axes.text(
            x, 0.98, f"{x:.3f}°", transform=self._axes.get_xaxis_transform(),
            ha="center", va="top", fontsize=8, color="#d32f2f", zorder=5,
        )
        intensity = 0.0
        if self._data_list:
            try:
                d = self._data_list[-1]
                idx = int(np.argmin(abs(np.asarray(d.two_theta, float) - x)))
                intensity = float(d.intensity[idx])
            except (IndexError, ValueError, TypeError):
                pass
        self.cursor_info.emit(f"2θ={x:.3f}°  I={intensity:.1f}")
        self._canvas.draw_idle()

    def _hide_cursor(self) -> None:
        """移除十字竖线与标注。"""
        for a in (self._cursor_line, self._cursor_text):
            if a is not None:
                try:
                    a.remove()
                except Exception:  # noqa: BLE001
                    pass
        self._cursor_line = None
        self._cursor_text = None
        self._cursor_x = None

    def _on_cursor_info(self, text: str) -> None:
        """十字线读数 → 操作行右侧提示（仅十字线工具激活时显示）。"""
        pb = getattr(self, "_plot_toolbar", None)
        if pb is not None:
            pb.set_hint(text if self._tool == "crosshair" else "")

    def _tool_press(self, event) -> None:
        """当前谱图操作工具下的按下动作。

        - ``crosshair``：左键定位竖线；
        - ``zoom_x`` / ``zoom_y`` / ``zoom_rect``：左键起拖画橡皮筋。
        """
        if self._tool == "crosshair":
            if event.button == 1 and event.xdata is not None:
                self._update_cursor(float(event.xdata))
            return
        if event.button != 1:
            return
        if event.xdata is None or event.ydata is None:
            return
        self._band_start = (float(event.xdata), float(event.ydata))
        self._make_band(*self._band_start)
        self._canvas.draw_idle()

    def export_image(self, path: str, dpi: int = 300) -> None:
        """导出图片"""
        self._figure.savefig(path, dpi=dpi, bbox_inches="tight")

    def get_figure(self) -> Figure:
        """获取matplotlib Figure对象"""
        return self._figure

    def get_axes(self):
        """获取matplotlib Axes对象"""
        return self._axes

    # ------------------------------------------------------------------
    # M22: X 轴自适应与滚轮/拖动交互
    # ------------------------------------------------------------------

    def fit_x_to_data(self, margin_ratio: float = _X_MARGIN_RATIO) -> None:
        """横轴贴合数据实际 2θ 范围 (默认 1% 边距)。

        多数据集取并集; `_data_list` 为空 / 全 NaN / 范围无效时 no-op。
        同时记录该范围作为滚轮缩放 clamp 与 Home / 重置的基准。
        """
        lo = hi = None
        for d in self._data_list:
            x = np.asarray(d.two_theta, dtype=float)
            x = x[np.isfinite(x)]
            if x.size == 0:
                continue
            dlo, dhi = float(x.min()), float(x.max())
            lo = dlo if lo is None else min(lo, dlo)
            hi = dhi if hi is None else max(hi, dhi)
        if lo is None or hi is None or not (hi > lo):
            return
        pad = (hi - lo) * margin_ratio
        self._data_xlim = (lo - pad, hi + pad)
        self._axes.set_xlim(*self._data_xlim)

    def _install_x_interaction(self) -> None:
        """注册滚轮缩放 / 拖动平移, 并让 toolbar Home 回到数据范围。"""
        self._canvas.mpl_connect("scroll_event", self._on_scroll)
        self._canvas.mpl_connect("button_release_event", self._on_mouse_release)
        # NavigationToolbar2QT.home 默认回到 nav_stack 底 (空白图的 0–1 视图),
        # 改接到 reset_view; _actions 是 mpl Qt toolbar 的既有字典。
        home_action = getattr(self._toolbar, "_actions", {}).get("home")
        if home_action is not None:
            try:
                home_action.triggered.disconnect()
            except (RuntimeError, TypeError):  # noqa: BLE001
                pass
            home_action.triggered.connect(self.reset_view)
        # save_figure 默认弹 mpl 保存框；改接到本控件的导出（带自定义对话框）
        save_action = getattr(self._toolbar, "_actions", {}).get("save_figure")
        if save_action is not None:
            try:
                save_action.triggered.disconnect()
            except (RuntimeError, TypeError):  # noqa: BLE001
                pass
            save_action.triggered.connect(self._on_export)

    def _x_bounds(self) -> Optional[tuple[float, float]]:
        """允许的 xlim 硬边界: 数据范围外扩 20% (clamp)。"""
        if self._data_xlim is None:
            return None
        lo, hi = self._data_xlim
        pad = (hi - lo) * self._X_OVERSCAN
        return lo - pad, hi + pad

    def _clamp_xlim(self, lo: float, hi: float) -> tuple[float, float]:
        """把目标 xlim 收进硬边界内, 且不允许缩到无穷小。"""
        bounds = self._x_bounds()
        if bounds is None:
            return lo, hi
        blo, bhi = bounds
        width = hi - lo
        min_w = max(0.1, (bhi - blo) * 0.002)
        if width > (bhi - blo):
            c = (lo + hi) / 2.0
            lo, hi = c - (bhi - blo) / 2.0, c + (bhi - blo) / 2.0
        elif width < min_w:
            c = (lo + hi) / 2.0
            lo, hi = c - min_w / 2.0, c + min_w / 2.0
        if lo < blo:
            hi += blo - lo
            lo = blo
        if hi > bhi:
            lo -= hi - bhi
            hi = bhi
        return lo, hi

    def _on_scroll(self, event) -> None:
        """滚轮: 以鼠标 x 位置为中心 ±15%/格 缩放 X 轴。"""
        if getattr(self._toolbar, "mode", ""):  # 工具栏 zoom/pan 模式下不插手
            return
        if event.inaxes != self._axes or event.xdata is None:
            return
        l, r = self._axes.get_xlim()
        step = self._X_ZOOM_STEP if event.step > 0 else -self._X_ZOOM_STEP
        factor = 1.0 - step
        nl = event.xdata - (event.xdata - l) * factor
        nr = event.xdata + (r - event.xdata) * factor
        nl, nr = self._clamp_xlim(nl, nr)
        if (nl, nr) == (l, r):
            return
        self._axes.set_xlim(nl, nr)
        self._canvas.draw_idle()

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_mouse_press(self, event) -> None:
        """鼠标按下: 记录峰命中与拖动起点 (M22)。

        右键 / Y 轴竖条仍留给纵坐标刻度控制器; 峰点击延迟到释放且
        位移 <3px 时才发射, 以兼容左键拖动平移。
        """
        self._pending_peak = None
        if getattr(event, "button", 1) != 1:
            return
        if event.inaxes != self._axes:
            return
        if getattr(self._toolbar, "mode", ""):  # 工具栏 zoom/pan 模式下不插手
            return

        # v5.4.0: 谱图操作工具优先（框选缩放 / 十字线）
        if self._tool is not None:
            self._tool_press(event)
            return

        # 检查是否点击了峰 (暂存, 释放时未拖动才发射)
        if self._peaks and event.xdata is not None:
            for peak in self._peaks:
                if abs(event.xdata - peak.two_theta) < 0.3:
                    self._pending_peak = peak
                    break

        self._pan_state = {
            "x0": event.xdata,
            "xlim": self._axes.get_xlim(),
            "x_px": event.x,
            "moved": False,
        }

    def _on_mouse_move(self, event) -> None:
        """鼠标移动: 坐标读数 + 左键拖动 X 平移 (M22)。"""
        # v5.4.0: 框选拖拽中 → 只更新橡皮筋
        if self._band is not None and self._band_start is not None:
            if (event.inaxes == self._axes and event.xdata is not None
                    and event.ydata is not None):
                x0, y0 = self._band_start
                self._band.set_width(float(event.xdata) - x0)
                self._band.set_height(float(event.ydata) - y0)
                self._canvas.draw_idle()
            return
        # v5.4.0: 十字线工具 → 跟随鼠标并报读数
        if self._tool == "crosshair" and event.inaxes == self._axes:
            if event.xdata is not None:
                self._update_cursor(float(event.xdata))
            return

        pan = self._pan_state
        if (
            pan is not None
            and getattr(event, "button", None) == 1
            and event.inaxes == self._axes
            and event.xdata is not None
            and not getattr(self._toolbar, "mode", "")
        ):
            if abs(event.x - pan["x_px"]) > 3:
                pan["moved"] = True
            if pan["moved"]:
                dx = pan["x0"] - event.xdata
                l0, r0 = pan["xlim"]
                nl, nr = self._clamp_xlim(l0 + dx, r0 + dx)
                self._axes.set_xlim(nl, nr)
                self._canvas.draw_idle()
                return

        if event.inaxes == self._axes and event.xdata is not None:
            intensity_val = 0
            if self._data_list:
                try:
                    idx = np.argmin(abs(self._data_list[-1].two_theta - event.xdata))
                    intensity_val = self._data_list[-1].intensity[idx]
                except (IndexError, ValueError):
                    pass
            self._toolbar.set_message(
                f"2θ={event.xdata:.3f}°, I={intensity_val:.1f}"
            )

    def _on_mouse_release(self, event) -> None:
        """鼠标释放: 未拖动 (<3px) 且按下时命中峰 → 发射 peak_clicked (M22)。"""
        # v5.4.0: 结束框选，按工具语义应用新视场
        if self._band_start is not None:
            x0, y0 = self._band_start
            self._band_start = None
            band, self._band = self._band, None
            if band is not None:
                try:
                    band.remove()
                except Exception:  # noqa: BLE001
                    pass
            if event.xdata is not None and event.ydata is not None:
                self._apply_band(x0, y0, float(event.xdata), float(event.ydata))
            self._canvas.draw_idle()
            return

        pan = self._pan_state
        self._pan_state = None
        peak = self._pending_peak
        self._pending_peak = None
        if getattr(event, "button", 1) != 1:
            return
        if pan is None or pan["moved"]:
            return
        if peak is not None:
            self.peak_clicked.emit(peak)

    def _on_add_peak_mode(self) -> None:
        """添加峰模式"""
        # TODO: 实现交互式添加峰
        pass

    def _on_export(self) -> None:
        """导出图片"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("vw.plot_widget.export_img_dlg_title"),
            "xrd_pattern.png",
            tr("vw.plot_widget.export_img_filter"),
        )
        if path:
            dpi = 300
            if path.endswith((".png", ".jpg")):
                dpi = 300
            self.export_image(path, dpi=dpi)
