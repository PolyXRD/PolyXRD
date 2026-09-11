"""
Match! 式双区衍射谱绘图控件 (M21)
================================
上区: 实验谱 (黑) + 计算谱 (红) + 残差 (灰, 底部偏移)
下区: 逐相参考棒区 (每相一行, 颜色由 phase_display 色板)
峰归属: 实验峰顶画"归属相颜色圆点"; 未解释峰画红色▼。

布局用 matplotlib GridSpec(2,1, height_ratios=[4,1], sharex=True) —
上下 x 轴联动缩放; 棒区叠加在主区下方 (Match! 风格)。

Signals:
    peak_clicked : 点中某实验峰 → 发出该峰 two_theta
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.phase_display import (
    COLOR_CALC, COLOR_EXP, COLOR_RESIDUAL, COLOR_UNMATCHED,
    PeakAssignment, phase_color,
)
from polyxrd.utils.mpl_font import ensure_cjk_font

# 图上标题/行标含中文 → 必须在建图前把系统中文字体插进字体栈, 否则画成豆腐块。
ensure_cjk_font()


class PatternDisplayWidget(QWidget):
    """Match! 式双区谱图 (实验/计算/残差 + 逐相参考棒 + 归属标记)。"""

    peak_clicked = Signal(object)

    #: 棒区每行的数据空间高度。行距恒等于它 ⇒ 各行高度一致 (不随相数变化)。
    ROW_H = 1.0

    #: 棒最大高度占行高的比例 (行内 0..ROW_H 的空间里, 棒只占下面 85%)。
    _STICK_MAX = 0.85

    #: 主区与棒区的 GridSpec 基准比 (主区固定占 4 份)。
    _MAIN_RATIO = 4.0

    #: 每行目标像素高度 —— 占整块绘图区的比例 (0.0707 ≈ 单相时原始观感)。
    #: 定死它 → 相数增加时反解棒区占比, 使各行实际像素高度保持恒定。
    _ROW_FRAC = 0.0707

    #: 棒区占比上限 (r 值)。超过它才封顶, 之后行高才缓慢压缩,
    #: 避免 8 个相时棒区把主谱挤成一条缝。
    _STICK_RATIO_MAX = 3.4

    #: 相名过长时的截断长度。
    _LABEL_MAX = 16

    #: 只剥真正的 HTML 标签 (保留 "2θ < 20" 这类含尖括号的普通文本)。
    _HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._figure = Figure(figsize=(8, 5.2), dpi=100, tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setMinimumHeight(320)
        gs = GridSpec(2, 1, height_ratios=[self._MAIN_RATIO, 1], hspace=0.08)
        self._gridspec = gs
        self._ax_main = self._figure.add_subplot(gs[0])
        self._ax_stick = self._figure.add_subplot(gs[1], sharex=self._ax_main)
        # 关闭棒区独立的 y 标签/刻度 (它是虚拟的相行)
        self._ax_stick.set_yticks([])
        self._apply_stick_ylim(1)
        self._ax_main.set_ylabel("Intensity")
        self._ax_stick.set_xlabel("2θ (°)")

        self._canvas.mpl_connect("button_press_event", self._on_click)
        self._canvas.mpl_connect("scroll_event", self._sync_limits)

        self._artists: list = []   # 本控件创建的 artist, 便于整组清除
        self._main_x: np.ndarray = np.array([])
        self._main_ymax: float = 1.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._canvas)
        self.clear_all()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _drop(self):
        for a in self._artists:
            try:
                a.remove()
            except Exception:
                pass
        self._artists = []

    def _redraw(self):
        self._canvas.draw_idle()

    def _sync_limits(self, *_):
        # 棒区 x 跟随主区 (sharex 已处理); 只需保持主区 y 有界性
        self._redraw()

    def _on_click(self, event):
        if event.inaxes is not self._ax_main or event.xdata is None:
            return
        # 命中最近的实验峰 (仅在已设实验数据时)
        if self._main_x.size == 0:
            return
        idx = int(np.argmin(np.abs(self._main_x - event.xdata)))
        if idx < self._main_x.size and abs(self._main_x[idx] - event.xdata) < 0.5:
            self.peak_clicked.emit(float(self._main_x[idx]))

    # ------------------------------------------------------------------
    # 公共设置
    # ------------------------------------------------------------------
    def set_experiment(self, data: XRDData) -> None:
        """主区画实验谱 (黑线); 重置归属/计算/残差覆盖。"""
        self._clear_main()
        x = np.asarray(data.two_theta, dtype=float)
        y = np.asarray(data.intensity, dtype=float)
        self._main_x = x
        self._main_y = y
        if x.size:
            self._main_ymax = float(np.max(y)) if np.max(y) > 0 else 1.0
            ln = self._ax_main.plot(x, y, color=COLOR_EXP, linewidth=1.1,
                                    label="实验数据")[0]
            ln.set_gid("exp"); self._artists.append(ln)
        self._ax_main.relim(); self._ax_main.autoscale_view()
        self._redraw()

    def set_calculated(self, two_theta, y_calc) -> None:
        """计算谱红线; None → 清除。"""
        self._remove_tag("calc")
        if two_theta is None or y_calc is None:
            self._redraw(); return
        ln = self._ax_main.plot(np.asarray(two_theta), np.asarray(y_calc),
                                color=COLOR_CALC, linewidth=1.0, alpha=0.85,
                                label="计算谱")[0]
        ln.set_gid("calc"); self._artists.append(ln)
        self._redraw()

    def set_residual_curve(self, two_theta, y_res) -> None:
        """残差灰线 (主区底部偏移), None → 清除。"""
        self._remove_tag("resid")
        if two_theta is None or y_res is None:
            self._redraw(); return
        off = -0.15 * self._main_ymax
        yr = np.asarray(y_res, dtype=float) + off
        ln = self._ax_main.plot(np.asarray(two_theta), yr, color=COLOR_RESIDUAL,
                                linewidth=0.8, alpha=0.6, label="残差")[0]
        ln.set_gid("resid"); self._artists.append(ln)
        zero = self._ax_main.axhline(off, color=COLOR_RESIDUAL, linewidth=0.5,
                                     alpha=0.3)
        zero.set_gid("resid"); self._artists.append(zero)
        self._redraw()

    def set_selected_phases(self, phase_sticks) -> None:
        """设置参考棒区。

        Args:
            phase_sticks: ``[(name, [(hkl, 2θ, I), ...], color[, coverage]), ...]``
                第 4 项可选 (覆盖率 / 质量分数, 数字或 None)。旧的三元组仍兼容。

        每相一行: 行内画该相参考棒, **本行左端**在 row 内写 ``相名 (+百分比)``。
        三条约定 ——

        1. **颜色一致**: 行标颜色与竖线颜色同为 ``color`` (即 ``phase_color(i)``),
           与峰顶归属圆点、峰匹配表的颜色也同源, 同一个相到哪都是这个色;
        2. **高度一致**: 行距恒为 ``ROW_H``, 行标一律垂直居中于本行 → 所有行
           等高、等间距, 不随相数或棒高变化;
        3. **在框内**: 行标画在棒区坐标轴**内部**的左端 (x 取轴分数 0.006),
           与相棒同处一个框里; 行标带一块与轴底色同色的无边框衬底, 万一有
           低角度相棒落在同一位置也不会互相糊住。

        行标之所以在这里而不是主区标题: matplotlib 不解析 HTML, 以前把
        ``<span style='color:...'>`` 塞进 ``set_info_text`` 会原样显示成
        ``<span style='color:#E53935'>■ Brucite: 0%</span> | ...`` 一串乱码。
        """
        self._clear_stick()
        for i, row in enumerate(phase_sticks):
            name = row[0]
            refs = row[1]
            color = row[2]
            coverage = row[3] if len(row) > 3 else None

            base = -i * self.ROW_H
            for rp in refs:
                if len(rp) < 3:
                    continue
                tt = float(rp[1]); I = float(rp[2])
                h = self._STICK_MAX * self.ROW_H * min(1.0, I / 100.0)
                if h <= 0:
                    continue
                ln = self._ax_stick.plot([tt, tt], [base, base + h],
                                         color=color, linewidth=1.8,
                                         solid_capstyle="butt")[0]
                ln.set_gid("stick"); self._artists.append(ln)

            label = str(name)
            if coverage is not None:
                label = f"{label}  {float(coverage):.0f}%"
            if len(label) > self._LABEL_MAX:
                label = label[: self._LABEL_MAX - 1] + "…"

            # x 用轴分数、y 用数据坐标: 行标贴在框内左端, 且随行一起移动
            txt = self._ax_stick.annotate(
                label,
                xy=(0.006, base + 0.5 * self.ROW_H),
                xycoords=self._ax_stick.get_yaxis_transform(),
                xytext=(0, 0), textcoords="offset points",
                fontsize=7.5, color=color, alpha=0.95,
                ha="left", va="center",
                clip_on=False, annotation_clip=False,
            )
            # 衬底与轴底色同色 (不透明) → 干净地盖住可能穿过的相棒与网格,
            # 浅色背景下等于"隐形底板", 不会有突兀的色块; 深色主题下同理。
            txt.set_bbox({
                "facecolor": self._ax_stick.get_facecolor(),
                "edgecolor": "none", "alpha": 1.0, "pad": 1.0,
            })
            txt.set_gid("stick"); self._artists.append(txt)

        nrow = max(1, len(phase_sticks))
        self._apply_stick_ylim(nrow)
        self._update_stick_ratio(nrow)
        self._ax_main.relim(); self._ax_main.autoscale_view()
        self._redraw()

    def _stick_span(self, n_rows: int) -> float:
        """棒区所需的数据空间跨度 (行基线 + 棒顶 + 上下留白)。"""
        n = max(1, n_rows)
        return ((n - 1) * self.ROW_H            # 末行基线到首行基线的距离
                + self._STICK_MAX * self.ROW_H  # 首行棒顶
                + 1.10)                         # 上下各 0.55 行留白

    def _apply_stick_ylim(self, n_rows: int) -> None:
        """按行数设定棒区 y 范围。

        ⚠️ 上限必须盖住**首行的棒顶** (``_STICK_MAX * ROW_H``), 不能只到行基线
        之上一点点 —— 否则第一相最高的那根棒会被轴线裁掉一截, 看上去"变矮",
        在各相之间造成假的相对强度差。
        """
        n = max(1, n_rows)
        bottom = -(n - 1) * self.ROW_H - 0.55
        top = self._STICK_MAX * self.ROW_H + 0.55
        self._ax_stick.set_ylim(bottom, top)
        self._ax_stick.set_yticks([])

    def _update_stick_ratio(self, n_rows: int) -> None:
        """反解棒区占比, 目标是**每行像素高度恒定**。

        固定 4:1 时, 6 个相挤在 1/5 的图高里, 行被压扁成几条线, 行标互相重叠
        —— 视觉上就是"高度不一致"。这里按下面的关系反解 GridSpec 的 ``r``:

            行高 / 绘图区高 = panel_frac × (ROW_H / span) ≡ _ROW_FRAC

        其中 ``panel_frac = r / (M + r)`` (M = ``_MAIN_RATIO``)。于是

            panel_frac = _ROW_FRAC × span / ROW_H
            r          = M × panel_frac / (1 − panel_frac)

        ⚠️ matplotlib 的坑 (3.10.9 实测): ``GridSpec.set_height_ratios`` 在 Axes
        建好之后**不会自动生效**。原因有两层 ——

        1. 各 Axes 的 position 是上一次布局时锁定的, 改 ratio 再 draw 毫无变化;
        2. 想靠 ``fig.get_layout_engine().execute(fig)`` 重跑一遍也不行: Qt 画布
           下 ``get_tight_layout_figure`` 认为不需要再调边距, 返回空 dict, 于是
           ``subplots_adjust()`` 不带任何参数 ⇒ 位置依旧不动。

        所以这里**不依赖 layout engine**, 直接按比例把两个 Axes 摆回去 (见
        ``_relayout``)。同时仍然更新 ratio, 这样以后窗口缩放触发真正的重排时,
        引擎算出来的比例也是对的。
        """
        n = max(1, n_rows)
        span = self._stick_span(n)
        panel_frac = self._ROW_FRAC * span / self.ROW_H
        panel_frac = min(panel_frac, 1.0 - 1e-6)
        r = self._MAIN_RATIO * panel_frac / (1.0 - panel_frac)
        r = min(r, self._STICK_RATIO_MAX)
        try:
            self._gridspec.set_height_ratios([self._MAIN_RATIO, r])
        except Exception:  # noqa: BLE001 - 老版本 matplotlib 无此 API
            pass
        self._relayout(self._MAIN_RATIO, r)

    def _relayout(self, main_ratio: float, stick_ratio: float) -> None:
        """按 ``main_ratio : stick_ratio`` 重新分配两个 Axes 的高度。

        边距不自己发明, 而是**从当前 Axes 位置读回来** —— 这样 tight_layout
        已经算好的左边距/下边距 (留给 y 轴标签、2θ 轴标题) 原样保留, 只在
        上下方向上按比例重分, 并保持两区之间的间隙不变。

        由于 ``top``、``bottom``、``gap`` 三个量在一次重排前后守恒, 本函数是
        幂等的: 反复调用 (每次勾选物相都会调) 不会让布局逐次漂移。
        """
        if main_ratio + stick_ratio <= 0:
            return
        try:
            mp = self._ax_main.get_position()
            sp = self._ax_stick.get_position()
        except Exception:  # noqa: BLE001
            return

        left = min(mp.x0, sp.x0)
        right = max(mp.x1, sp.x1)
        top = max(mp.y1, sp.y1)
        bottom = min(mp.y0, sp.y0)
        gap = abs(mp.y0 - sp.y1) if mp.y0 >= sp.y1 else 0.0

        avail = (top - bottom) - gap
        if avail <= 0:
            return
        width = right - left
        total = main_ratio + stick_ratio
        main_h = avail * main_ratio / total
        stick_h = avail * stick_ratio / total

        self._ax_stick.set_position([left, bottom, width, stick_h])
        self._ax_main.set_position([left, bottom + stick_h + gap, width, main_h])

    def set_peak_assignments(self, assignments) -> None:
        """在主区峰顶画归属标记: 圆点(相色) / 红▼(未解释)。"""
        self._remove_tag("assign")
        if not self._main_x.size:
            return
        for a in assignments:
            if not isinstance(a, PeakAssignment):
                continue
            ix = int(np.argmin(np.abs(self._main_x - a.two_theta)))
            y_top = float(np.max(self._main_y_vals(ix, window=3)))
            if a.phase_index is None:
                mk = self._ax_main.plot([a.two_theta], [y_top],
                                        marker="v", color=COLOR_UNMATCHED,
                                        markersize=7, linestyle="None")[0]
            else:
                mk = self._ax_main.plot([a.two_theta], [y_top],
                                        marker="o", color=phase_color(a.phase_index),
                                        markersize=5, linestyle="None")[0]
            mk.set_gid("assign"); self._artists.append(mk)
        self._redraw()

    def _main_y_vals(self, idx, window=1):
        # 返回主区谱在 idx 附近的值 (用于确定峰顶 y) — 缓存实验 y
        if not hasattr(self, "_main_y") or len(self._main_y) == 0:
            return [self._main_ymax]
        lo = max(0, idx - window); hi = min(len(self._main_y), idx + window + 1)
        return list(self._main_y[lo:hi])

    def set_info_text(self, text: str) -> None:
        """主区标题 —— **纯文本**。

        ⚠️ matplotlib 的文本只认 mathtext (``$...$``), **不解析 HTML**。传进
        ``<span style='color:#E53935'>`` 这类标记会被原样画出来, 变成标题栏里
        一串 ``<span style='color:...'>■ 相名: 0%</span> | ...`` 的乱码。
        逐相的彩色信息请走 ``set_selected_phases`` 的第 4 个字段 (棒区行标);
        这里再做一次兜底剥离, 防止以后又有人把 HTML 拼进标题。
        """
        plain = self._HTML_TAG_RE.sub("", text or "").strip()
        self._ax_main.set_title(plain, fontsize=10, loc="left", pad=5)
        self._redraw()

    # ------------------------------------------------------------------
    # 清除
    # ------------------------------------------------------------------
    def _remove_tag(self, tag: str) -> None:
        keep = []
        for a in self._artists:
            try:
                if a.get_gid() == tag:
                    a.remove(); continue
            except Exception:
                pass
            keep.append(a)
        self._artists = keep

    def _clear_main(self):
        # 清主区带标记元素 (实验/计算/残差/归属), 保留手动图例等
        for gid in ("exp", "calc", "resid", "assign"):
            self._remove_tag(gid)

    def _clear_stick(self):
        # 清棒区全部 (带 "stick" gid 的棒与相名)
        self._remove_tag("stick")

    def clear_all(self) -> None:
        self._drop()
        self._ax_main.clear()
        self._ax_stick.clear()
        self._ax_main.grid(True, alpha=0.3)
        self._ax_stick.grid(True, alpha=0.3)
        self._ax_main.set_ylabel("Intensity")
        self._ax_stick.set_xlabel("2θ (°)")
        self._apply_stick_ylim(1)
        self._update_stick_ratio(0)
        self._artists = []
        self._main_x = np.array([])
        self._main_y = np.array([])
        self._main_ymax = 1.0
        self._redraw()

    def export_image(self, path: str, dpi: int = 300) -> None:
        self._figure.savefig(path, dpi=dpi, bbox_inches="tight")

    # ── 向后兼容别名 (供外部 main_window._on_data_changed 等调用) ──
    def clear_plot(self) -> None:
        """清空整个图 (含实验/棒区/标记)。"""
        self.clear_all()

    def plot_data(self, data: XRDData, label: Optional[str] = None,
                  color: Optional[str] = None) -> None:
        """兼容旧接口: 重置并画实验谱 (黑线)。"""
        self.set_experiment(data)
        if label:
            self._ax_main.set_title(label, fontsize=10, loc="left", pad=5)

    def get_figure(self):
        return self._figure

    def get_axes(self):
        return self._ax_main
