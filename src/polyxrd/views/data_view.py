"""
数据视图
========
数据显示和预处理的主界面。
"""
from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QGroupBox,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QLabel,
    QFormLayout,
    QCheckBox,
)

from polyxrd.i18n import tr
from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.widgets.busy_indicator import busy
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
        process_group = QGroupBox(tr("vw.data_view.data_preprocess"))
        process_layout = QFormLayout()

        self._bg_method = QComboBox()
        self._bg_method.addItems(["snip", "als", "polyfit", "median", "rolling"])
        process_layout.addRow(tr("vw.data_view.bg_method"), self._bg_method)

        self._btn_bg = QPushButton(tr("vw.data_view.exec_bg_subtract"))
        self._btn_bg.clicked.connect(self._on_background)
        process_layout.addRow(self._btn_bg)

        self._smooth_method = QComboBox()
        self._smooth_method.addItems(["savgol", "gaussian", "moving", "median"])
        process_layout.addRow(tr("vw.data_view.smooth_method"), self._smooth_method)

        self._smooth_window = QSpinBox()
        self._smooth_window.setRange(3, 101)
        self._smooth_window.setValue(11)
        self._smooth_window.setSingleStep(2)
        process_layout.addRow(tr("vw.data_view.window_size"), self._smooth_window)

        self._btn_smooth = QPushButton(tr("vw.data_view.exec_smooth"))
        self._btn_smooth.clicked.connect(self._on_smooth)
        process_layout.addRow(self._btn_smooth)

        self._btn_strip_kalpha2 = QPushButton(tr("vw.data_view.strip_kalpha2"))
        process_layout.addRow(self._btn_strip_kalpha2)

        process_group.setLayout(process_layout)
        right_layout.addWidget(process_group)

        # 峰检测组
        peak_group = QGroupBox(tr("vw.data_view.peak_detection"))
        peak_layout = QFormLayout()

        self._peak_height = QSpinBox()
        self._peak_height.setRange(1, 100)
        self._peak_height.setValue(10)
        self._peak_height.setSuffix(" %")
        peak_layout.addRow(tr("vw.data_view.min_peak_height"), self._peak_height)

        self._peak_distance = QDoubleSpinBox()
        self._peak_distance.setRange(0.0, 100.0)
        self._peak_distance.setDecimals(2)
        self._peak_distance.setSingleStep(0.1)
        # 0.5° 而非旧值 5°: XRD 峰 FWHM 仅 0.05~0.5°, 5° 会丢弃相邻强线
        self._peak_distance.setValue(0.5)
        self._peak_distance.setToolTip(
            tr("vw.data_view.peak_distance_tip"))
        peak_layout.addRow(tr("vw.data_view.min_distance"), self._peak_distance)

        self._peak_hi = QCheckBox(tr("vw.data_view.high_precision"))
        self._peak_hi.setChecked(True)
        self._peak_hi.setToolTip(
            tr("vw.data_view.peak_hi_tip"))
        peak_layout.addRow(self._peak_hi)

        self._btn_find_peaks = QPushButton(tr("vw.data_view.detect_peaks"))
        self._btn_find_peaks.clicked.connect(self._on_find_peaks)
        peak_layout.addRow(self._btn_find_peaks)

        self._btn_fit_peaks = QPushButton(tr("vw.data_view.fit_peaks"))
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
            self._plot.plot_data(data, label=tr("vw.data_view.experimental_data"))

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
        high_precision = self._peak_hi.isChecked()
        text = (tr("busy.peak_search_hi") if high_precision
                else tr("busy.peak_search"))
        # 峰检测在数据点多时要跑几秒, 期间界面不刷新; 不给反馈用户就会再点一次
        with busy(self, text) as acquired:
            if not acquired:
                return
            if high_precision:
                self._vm.find_peaks_advanced()
            else:
                self._vm.find_peaks(
                    height=self._peak_height.value() / 100.0,
                    distance=self._peak_distance.value(),
                )

    def _on_fit_peaks(self) -> None:
        """峰拟合"""
        with busy(self, tr("busy.peak_fit")) as acquired:
            if not acquired:
                return
            self._vm.fit_peaks(model="voigt")
