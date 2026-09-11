"""
XRD绘图控件
===========
基于matplotlib的可交互XRD绘图控件。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton

from polyxrd.models.peak import Peak
from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.mpl_font import ensure_cjk_font

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

    Signals:
        peak_clicked: 点击峰
        range_selected: 框选范围
    """

    peak_clicked = Signal(object)
    range_selected = Signal(float, float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._data_list: list[XRDData] = []
        self._peaks: list[Peak] = []
        self._peak_artists: list = []
        self._match_artists: list = []
        self._span_selector: Optional[SpanSelector] = None

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

        self._btn_add_peak = QPushButton("添加峰")
        self._btn_add_peak.clicked.connect(self._on_add_peak_mode)
        btn_layout.addWidget(self._btn_add_peak)

        self._btn_reset = QPushButton("重置视图")
        self._btn_reset.clicked.connect(self.reset_view)
        btn_layout.addWidget(self._btn_reset)

        self._btn_export = QPushButton("导出图片")
        self._btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self._btn_export)

        btn_layout.addStretch()

        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas)

        btn_widget = QWidget()
        btn_widget.setLayout(btn_layout)
        layout.addWidget(btn_widget)

        # 初始空白图
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("2θ (°)")
        self._axes.set_ylabel("Intensity")
        self._axes.set_title("XRD Pattern")
        self._axes.grid(True, alpha=0.3)

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
        self._canvas.draw_idle()

    def clear_plot(self) -> None:
        """清除所有数据"""
        self._axes.clear()
        self._axes.set_xlabel("2θ (°)")
        self._axes.set_ylabel("Intensity")
        self._axes.grid(True, alpha=0.3)
        self._data_list.clear()
        self._peaks.clear()
        self._peak_artists.clear()
        for artist in getattr(self, '_match_artists', []):
            artist.remove()
        self._match_artists = []
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
        """重置视图"""
        self._axes.relim()
        self._axes.autoscale_view()
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
    # 事件处理
    # ------------------------------------------------------------------

    def _on_mouse_press(self, event) -> None:
        """鼠标按下事件"""
        if event.inaxes != self._axes:
            return

        # 检查是否点击了峰
        if self._peaks:
            for peak in self._peaks:
                if abs(event.xdata - peak.two_theta) < 0.3:
                    self.peak_clicked.emit(peak)
                    break

    def _on_mouse_move(self, event) -> None:
        """鼠标移动事件"""
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

    def _on_add_peak_mode(self) -> None:
        """添加峰模式"""
        # TODO: 实现交互式添加峰
        pass

    def _on_export(self) -> None:
        """导出图片"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出图片",
            "xrd_pattern.png",
            "图片文件 (*.png *.pdf *.svg *.eps)",
        )
        if path:
            dpi = 300
            if path.endswith((".png", ".jpg")):
                dpi = 300
            self.export_image(path, dpi=dpi)
