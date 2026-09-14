"""
Rietveld精修视图
================
Rietveld结构精修的界面。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QLabel,
    QTabWidget,
)

from polyxrd.i18n import tr
from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.widgets.busy_indicator import BusyIndicator, busy
from polyxrd.views.widgets.plot_widget import PlotWidget


class RefinementView(QWidget):
    """Rietveld精修视图

    左侧：精修前后对比图 + 残差图
    右侧：参数编辑器 + 收敛诊断 + 物相含量
    """

    def __init__(self, vm: MainViewModel) -> None:
        super().__init__()
        self._vm = vm
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)

        # 左侧：图表区
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 对比图
        self._compare_plot = PlotWidget()
        left_layout.addWidget(QLabel("精修对比图"))
        left_layout.addWidget(self._compare_plot)

        # 残差图
        self._residual_plot = PlotWidget()
        left_layout.addWidget(QLabel("残差图"))
        left_layout.addWidget(self._residual_plot)

        # 右侧：控制区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # 精修控制
        ctrl_group = QGroupBox("精修控制")
        ctrl_layout = QFormLayout()

        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["auto", "builtin", "gsas2", "powerxrd"])
        ctrl_layout.addRow("引擎:", self._engine_combo)

        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems(["sequential", "auto", "manual"])
        ctrl_layout.addRow("策略:", self._strategy_combo)

        self._max_cycles = QSpinBox()
        self._max_cycles.setRange(1, 100)
        self._max_cycles.setValue(20)
        ctrl_layout.addRow("最大循环:", self._max_cycles)

        # 峰形参数
        self._peak_shape_combo = QComboBox()
        self._peak_shape_combo.addItems(["pseudo-voigt", "voigt", "gaussian", "lorentzian"])
        ctrl_layout.addRow("峰形:", self._peak_shape_combo)

        self._fwhm_spin = QDoubleSpinBox()
        self._fwhm_spin.setRange(0.05, 2.0)
        self._fwhm_spin.setValue(0.15)
        self._fwhm_spin.setSingleStep(0.01)
        self._fwhm_spin.setDecimals(2)
        self._fwhm_spin.setSuffix("°")
        ctrl_layout.addRow("初始 FWHM:", self._fwhm_spin)

        # 背景参数
        self._bg_combo = QComboBox()
        self._bg_combo.addItems(["snip", "als", "polynomial", "median", "rolling"])
        ctrl_layout.addRow("背景方法:", self._bg_combo)

        # 仪器参数
        self._zero_shift_spin = QDoubleSpinBox()
        self._zero_shift_spin.setRange(-2.0, 2.0)
        self._zero_shift_spin.setValue(0.0)
        self._zero_shift_spin.setSingleStep(0.01)
        self._zero_shift_spin.setDecimals(3)
        self._zero_shift_spin.setSuffix("°")
        ctrl_layout.addRow("零点偏移:", self._zero_shift_spin)

        self._btn_refine = QPushButton("开始精修")
        self._btn_refine.clicked.connect(self._on_refine)
        ctrl_layout.addRow(self._btn_refine)

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setEnabled(False)
        ctrl_layout.addRow(self._btn_cancel)

        ctrl_group.setLayout(ctrl_layout)
        right_layout.addWidget(ctrl_group)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        right_layout.addWidget(self._progress)

        # 精修结果
        result_group = QGroupBox("精修结果")
        result_layout = QFormLayout()

        self._label_rwp = QLabel("--")
        result_layout.addRow("Rwp:", self._label_rwp)

        self._label_gof = QLabel("--")
        result_layout.addRow("GOF:", self._label_gof)

        self._label_quality = QLabel("--")
        result_layout.addRow("质量:", self._label_quality)

        self._label_cycles = QLabel("--")
        result_layout.addRow("循环次数:", self._label_cycles)

        result_group.setLayout(result_layout)
        right_layout.addWidget(result_group)

        # 物相含量表
        phase_group = QGroupBox("物相含量")
        phase_layout = QVBoxLayout()

        self._phase_table = QTableWidget(0, 5)
        self._phase_table.setHorizontalHeaderLabels(
            ["物相", "质量分数(%)", "a(Å)", "b(Å)", "c(Å)"]
        )
        self._phase_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        phase_layout.addWidget(self._phase_table)

        phase_group.setLayout(phase_layout)
        right_layout.addWidget(phase_group, stretch=1)

        main_layout.addWidget(left_widget, stretch=2)
        main_layout.addWidget(right_widget, stretch=1)

    def _setup_connections(self) -> None:
        self._vm.refinement_completed.connect(self._on_refinement_completed)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_refine(self) -> None:
        """开始精修"""
        # 注意: 这里原本就禁用了按钮, 但挡不住"迟到的点击" —— 精修结束时会
        # refinement_completed 同步重启用按钮, 而阻塞期间积压的点击正好在那一刻
        # 被投递, 于是又起一轮精修 (用户看到的就是"多点几下就未响应/崩溃")。
        # 必须由忙碌闸门一直持有到积压输入被排空为止。
        with busy(self, tr("busy.refine")) as acquired:
            if not acquired:
                return
            self._btn_refine.setEnabled(False)
            self._btn_cancel.setEnabled(True)
            self._progress.setVisible(True)
            self._progress.setValue(0)

            # 把进度回调交给精修引擎: 多起点 + 稀疏抛光都是纯 Python 嵌套循环,
            # 借它周期性泵事件, 窗口才不会在几十秒里被系统标成"未响应"。
            self._vm.refine_structure(
                strategy=self._strategy_combo.currentText(),
                engine=self._engine_combo.currentText(),
                max_cycles=self._max_cycles.value(),
                peak_shape=self._peak_shape_combo.currentText(),
                fwhm=self._fwhm_spin.value(),
                bg_method=self._bg_combo.currentText(),
                zero_shift=self._zero_shift_spin.value(),
                progress_cb=BusyIndicator.progress_tick,
            )

    def _on_refinement_completed(self, result) -> None:
        """精修完成"""
        self._btn_refine.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._progress.setValue(100)

        # 更新结果显示
        self._label_rwp.setText(f"{result.wR:.3f} %")
        self._label_gof.setText(f"{result.GOF:.3f}")
        self._label_quality.setText(result.quality_grade)
        self._label_cycles.setText(str(result.num_cycles))

        # 更新物相表
        self._phase_table.setRowCount(0)
        for phase in result.phases:
            row = self._phase_table.rowCount()
            self._phase_table.insertRow(row)
            self._phase_table.setItem(row, 0, QTableWidgetItem(phase.name))
            self._phase_table.setItem(
                row, 1, QTableWidgetItem(f"{phase.weight_fraction:.2f}")
            )
            lat = phase.lattice
            a_val = f"{lat.a:.4f}" if lat is not None else "-"
            b_val = f"{lat.b:.4f}" if lat is not None else "-"
            c_val = f"{lat.c:.4f}" if lat is not None else "-"
            self._phase_table.setItem(
                row, 2, QTableWidgetItem(a_val)
            )
            self._phase_table.setItem(
                row, 3, QTableWidgetItem(b_val)
            )
            self._phase_table.setItem(
                row, 4, QTableWidgetItem(c_val)
            )

        # 更新对比图
        self._compare_plot.clear_plot()
        if result.observed_data:
            obs_x, obs_y = result.observed_data
            self._compare_plot.plot_data(
                type("Data", (), {"two_theta": obs_x, "intensity": obs_y})(),
                label="实验",
            )
        if result.simulated_data:
            sim_x, sim_y = result.simulated_data
            self._compare_plot.plot_data(
                type("Data", (), {"two_theta": sim_x, "intensity": sim_y})(),
                label="模拟",
                color="red",
            )

        # 更新残差图
        self._residual_plot.clear_plot()
        if result.residual_data:
            res_x, res_y = result.residual_data
            self._residual_plot.plot_data(
                type("Data", (), {"two_theta": res_x, "intensity": res_y})(),
                label="残差",
                color="green",
            )
