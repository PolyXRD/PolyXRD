"""
数据视图
========
数据显示和预处理的主界面。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QGroupBox,
    QComboBox,
    QSpinBox,
    QPushButton,
    QLabel,
    QFormLayout,
    QCheckBox,
)

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.widgets.plot_widget import PlotWidget
from polyxrd.views.widgets.peak_table import PeakTable


class DataView(QWidget):
    """数据显示和预处理视图

    左侧：交互绘图区
    右侧：数据列表面板 + 处理工具条
    """

    def __init__(self, vm: MainViewModel) -> None:
        super().__init__()
        self._vm = vm
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：绘图区
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._plot = PlotWidget()
        left_layout.addWidget(self._plot)

        # 右侧：控制面板
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # 数据处理组
        process_group = QGroupBox("数据预处理")
        process_layout = QFormLayout()

        self._bg_method = QComboBox()
        self._bg_method.addItems(["snip", "als", "polyfit", "median", "rolling"])
        process_layout.addRow("背景方法:", self._bg_method)

        self._btn_bg = QPushButton("执行背景扣除")
        self._btn_bg.clicked.connect(self._on_background)
        process_layout.addRow(self._btn_bg)

        self._smooth_method = QComboBox()
        self._smooth_method.addItems(["savgol", "gaussian", "moving", "median"])
        process_layout.addRow("平滑方法:", self._smooth_method)

        self._smooth_window = QSpinBox()
        self._smooth_window.setRange(3, 101)
        self._smooth_window.setValue(11)
        self._smooth_window.setSingleStep(2)
        process_layout.addRow("窗口大小:", self._smooth_window)

        self._btn_smooth = QPushButton("执行平滑")
        self._btn_smooth.clicked.connect(self._on_smooth)
        process_layout.addRow(self._btn_smooth)

        self._btn_strip_kalpha2 = QPushButton("Kα2剥离")
        process_layout.addRow(self._btn_strip_kalpha2)

        process_group.setLayout(process_layout)
        right_layout.addWidget(process_group)

        # 峰检测组
        peak_group = QGroupBox("峰检测")
        peak_layout = QFormLayout()

        self._peak_height = QSpinBox()
        self._peak_height.setRange(1, 100)
        self._peak_height.setValue(10)
        self._peak_height.setSuffix(" %")
        peak_layout.addRow("最小峰高:", self._peak_height)

        self._peak_distance = QSpinBox()
        self._peak_distance.setRange(1, 100)
        self._peak_distance.setValue(5)
        peak_layout.addRow("最小距离:", self._peak_distance)

        self._peak_hi = QCheckBox("高精度(背景扣除+亚步长)")
        self._peak_hi.setChecked(True)
        self._peak_hi.setToolTip(
            "启用高精度峰检测: 自动背景扣除 + 亚步长峰位精修 + 重叠峰联合拟合\n"
            "峰位精度可达 ~0.001°, 弱峰更易检出。取消则用传统高度阈值法。")
        peak_layout.addRow(self._peak_hi)

        self._btn_find_peaks = QPushButton("检测峰")
        self._btn_find_peaks.clicked.connect(self._on_find_peaks)
        peak_layout.addRow(self._btn_find_peaks)

        self._btn_fit_peaks = QPushButton("拟合峰")
        self._btn_fit_peaks.clicked.connect(self._on_fit_peaks)
        peak_layout.addRow(self._btn_fit_peaks)

        peak_group.setLayout(peak_layout)
        right_layout.addWidget(peak_group)

        # 峰列表
        self._peak_table = PeakTable()
        right_layout.addWidget(self._peak_table, stretch=1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([700, 300])

        main_layout.addWidget(splitter)

    def _setup_connections(self) -> None:
        self._vm.data_changed.connect(self._on_data_changed)
        self._vm.peaks_changed.connect(self._on_peaks_changed)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_data_changed(self, data) -> None:
        """数据变更"""
        self._plot.clear_plot()
        if data:
            self._plot.plot_data(data, label="实验数据")

    def _on_peaks_changed(self, peaks) -> None:
        """峰变更"""
        self._peak_table.set_peaks(peaks)
        self._plot.add_peak_annotations(peaks)

    def _on_background(self) -> None:
        """背景扣除"""
        self._vm.subtract_background(method=self._bg_method.currentText())

    def _on_smooth(self) -> None:
        """平滑"""
        self._vm.smooth_data(
            method=self._smooth_method.currentText(),
            window=self._smooth_window.value(),
        )

    def _on_find_peaks(self) -> None:
        """峰检测 (默认高精度; 取消勾选回退传统高度阈值法)"""
        if self._peak_hi.isChecked():
            self._vm.find_peaks_advanced()
        else:
            self._vm.find_peaks(
                height=self._peak_height.value() / 100.0,
                distance=self._peak_distance.value(),
            )

    def _on_fit_peaks(self) -> None:
        """峰拟合"""
        self._vm.fit_peaks(model="voigt")
