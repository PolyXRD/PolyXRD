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
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel

from polyxrd.i18n import tr
from polyxrd.models.peak import Peak
from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.mpl_font import ensure_cjk_font
from polyxrd.views.widgets.y_scale import YScaleController, hint_text

# 图上标题/图例含中文 → 建图前先插系统中文字体, 否则画成豆腐块。
ensure_cjk_font()


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

    # M22: X 轴交互参数
    _X_MARGIN_RATIO = 0.01   # 首屏边距 (数据宽度的 1%)
    _X_ZOOM_STEP = 0.15      # 每格滚轮缩放幅度
    _X_OVERSCAN = 0.20       # 允许越出数据范围的比例

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ylabel_base = "Intensity"
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
        self._figure = Figure(figsize=(8, 5), dpi=100, tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setMinimumHeight(300)
        self._canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self._canvas.mpl_connect("motion_notify_event", self._on_mouse_move)

        # Toolbar
        self._toolbar = NavigationToolbar2QT(self._canvas, self)

        # 操作按钮
        btn_layout = QHBoxLayout()

        self._btn_add_peak = QPushButton(tr("vw.plot_widget.add_peak_btn"))
        self._btn_add_peak.clicked.connect(self._on_add_peak_mode)
        btn_layout.addWidget(self._btn_add_peak)

        self._btn_reset = QPushButton(tr("vw.plot_widget.reset_view_btn"))
        self._btn_reset.clicked.connect(self.reset_view)
        btn_layout.addWidget(self._btn_reset)

        self._btn_export = QPushButton(tr("vw.plot_widget.export_img_btn"))
        self._btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self._btn_export)

        # 纵坐标模式提示 (随切换实时更新)
        self._y_scale_hint = QLabel()
        self._y_scale_hint.setStyleSheet("QLabel { color: #555; font-size: 11px; }")
        self._y_scale_hint.setToolTip(tr("vw.plot_widget.y_scale_hint_tip"))
        btn_layout.addWidget(self._y_scale_hint)

        btn_layout.addStretch()

        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas)

        btn_widget = QWidget()
        btn_widget.setLayout(btn_layout)
        layout.addWidget(btn_widget)

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
        self._btn_add_peak.setText(tr("vw.plot_widget.add_peak_btn"))
        self._btn_reset.setText(tr("vw.plot_widget.reset_view_btn"))
        self._btn_export.setText(tr("vw.plot_widget.export_img_btn"))
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
        self._axes.relim()
        self._axes.autoscale_view()
        self.fit_x_to_data()
        self._y_scale.set_mode(self._y_scale.mode(), refit=True)
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
