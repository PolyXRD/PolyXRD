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


class PatternDisplayWidget(QWidget):
    """Match! 式双区谱图 (实验/计算/残差 + 逐相参考棒 + 归属标记)。"""

    peak_clicked = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._figure = Figure(figsize=(8, 5.2), dpi=100, tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setMinimumHeight(320)
        gs = GridSpec(2, 1, height_ratios=[4, 1], hspace=0.08)
        self._ax_main = self._figure.add_subplot(gs[0])
        self._ax_stick = self._figure.add_subplot(gs[1], sharex=self._ax_main)
        # 关闭棒区独立的 y 标签/刻度 (它是虚拟的相行)
        self._ax_stick.set_yticks([])
        self._ax_stick.set_ylim(-6.5, 0.6)   # 最多 6 行棒区基线 + 顶部留白
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
        """设置参考棒区: [(name, [(hkl,2θ,I)...], color), ...]。

        每相一行; 棒高 = min(1, I/100) × 行高; 基线逐行下移; 相名标在左侧。
        """
        self._clear_stick()
        row_h = 1.0
        for i, (name, refs, color) in enumerate(phase_sticks):
            base = -i * row_h
            for rp in refs:
                if len(rp) < 3:
                    continue
                tt = float(rp[1]); I = float(rp[2])
                h = 0.85 * row_h * min(1.0, I / 100.0)
                if h <= 0:
                    continue
                ln = self._ax_stick.plot([tt, tt], [base, base + h],
                                         color=color, linewidth=1.8,
                                         solid_capstyle="butt")[0]
                ln.set_gid("stick"); self._artists.append(ln)
            # 相名标在左侧 (只标前 6 行, 防拥挤)
            if i < 6:
                txt = self._ax_stick.text(
                    0.01, base + 0.5 * row_h, name,
                    fontsize=7, color=color, va="center", ha="left",
                    transform=self._ax_stick.transAxes)
                txt.set_gid("stick"); self._artists.append(txt)
        nrow = max(1, len(phase_sticks))
        self._ax_stick.set_ylim(-nrow * row_h - 0.5, 0.5)
        self._ax_stick.set_yticks([])
        self._ax_main.relim(); self._ax_main.autoscale_view()
        self._redraw()

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
        self._ax_main.set_title(text, fontsize=10, loc="left", pad=5)
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
        self._ax_stick.set_yticks([])
        self._ax_stick.set_ylim(-6.5, 0.6)
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
