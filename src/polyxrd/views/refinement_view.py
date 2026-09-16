"""
Rietveld精修视图
================
Rietveld结构精修的界面。

v0.12.0 新增
------------
- **按精修向导的方式** 复选框 (默认勾选): 勾上即采用精修向导那套推荐配置
  (引擎 builtin / 策略 sequential / 峰形 pseudo-voigt / 背景 snip / 最大循环 20),
  手动参数控件随之置灰接管, 避免两处参数打架; 取消勾选即可自由调参。
- **精修过程日志**: 引擎把过程数据 (引擎选择/背景估计/每个起点的 wR·nfev·耗时/
  抛光评估数/最终指标) 逐行回吐到这个面板, 像终端跑码一样实时滚动。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QLabel,
    QPlainTextEdit,
    QSplitter,
)

from polyxrd.i18n import tr
from polyxrd.services.refinement_templates import RefinementTemplateManager
from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.widgets.busy_indicator import BusyIndicator, busy
from polyxrd.views.widgets.plot_widget import PlotWidget


class RefinementView(QWidget):
    """Rietveld精修视图

    左侧：精修前后对比图 + 残差图
    右侧：参数编辑器 + 收敛诊断 + 物相含量
    下方：精修过程日志 (可与上方拖动分栏)
    """

    #: 日志面板最多保留的行数 (避免长跑把内存吃光)
    _LOG_MAX_BLOCKS = 4000

    def __init__(self, vm: MainViewModel) -> None:
        super().__init__()
        self._vm = vm
        # 向导推荐配置直接取自内置精修模板 —— 与精修向导同源, 不会各写一份而漂移
        self._template_mgr = RefinementTemplateManager()
        templates = self._template_mgr.get_builtin_templates()
        self._wizard_template = templates[0] if templates else None
        self._setup_ui()
        self._setup_connections()
        # 默认按向导方式启动 (勾选 → 同步一次预设到控件并置灰)
        self._chk_wizard.setChecked(True)
        self._apply_wizard_style(True)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        top_widget = QWidget()
        main_layout = QHBoxLayout(top_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 左侧：图表区
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 对比图
        self._compare_plot = PlotWidget()
        left_layout.addWidget(QLabel(tr("view.refinement.label_compare")))
        left_layout.addWidget(self._compare_plot)

        # 残差图
        self._residual_plot = PlotWidget()
        left_layout.addWidget(QLabel(tr("view.refinement.label_residual")))
        left_layout.addWidget(self._residual_plot)

        # 右侧：控制区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # 精修控制
        ctrl_group = QGroupBox(tr("view.refinement.group_control"))
        ctrl_layout = QFormLayout()

        # ── 精修方式: 向导式 (默认) / 手动 ─────────────────────
        self._chk_wizard = QCheckBox(tr("view.refinement.wizard_style"))
        self._chk_wizard.setToolTip(tr("view.refinement.wizard_style_tip"))
        ctrl_layout.addRow(self._chk_wizard)

        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["auto", "gsas2", "maud", "builtin", "powerxrd"])
        ctrl_layout.addRow(tr("view.refinement.label_engine"), self._engine_combo)

        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems(["sequential", "auto", "manual"])
        ctrl_layout.addRow(tr("view.refinement.label_strategy"), self._strategy_combo)

        self._max_cycles = QSpinBox()
        self._max_cycles.setRange(1, 100)
        self._max_cycles.setValue(20)
        ctrl_layout.addRow(tr("view.refinement.label_max_cycles"), self._max_cycles)

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

        self._btn_refine = QPushButton(tr("view.refinement.btn_start_refine"))
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
        result_group = QGroupBox(tr("view.refinement.group_result"))
        result_layout = QFormLayout()

        self._label_rwp = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_rwp"), self._label_rwp)

        self._label_gof = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_gof"), self._label_gof)

        self._label_quality = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_quality"), self._label_quality)

        self._label_cycles = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_cycles"), self._label_cycles)

        self._label_time = QLabel("--")
        result_layout.addRow("耗时:", self._label_time)

        result_group.setLayout(result_layout)
        right_layout.addWidget(result_group)

        # 物相含量表
        phase_group = QGroupBox(tr("view.refinement.group_phases"))
        phase_layout = QVBoxLayout()

        self._phase_table = QTableWidget(0, 5)
        self._phase_table.setHorizontalHeaderLabels(
            [
                tr("view.refinement.col_phase"),
                tr("view.refinement.col_weight"),
                tr("view.refinement.col_a"),
                tr("view.refinement.col_b"),
                tr("view.refinement.col_c"),
            ]
        )
        self._phase_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        phase_layout.addWidget(self._phase_table)

        phase_group.setLayout(phase_layout)
        right_layout.addWidget(phase_group, stretch=1)

        main_layout.addWidget(left_widget, stretch=2)
        main_layout.addWidget(right_widget, stretch=1)

        # 下方: 过程日志 (可拖动分栏)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top_widget)
        splitter.addWidget(self._build_log_panel())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

    def _build_log_panel(self) -> QWidget:
        """精修过程日志面板 (跑码式输出)。"""
        group = QGroupBox(tr("view.refinement.group_log"))
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(self._LOG_MAX_BLOCKS)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self._log_view.setFont(font)
        self._log_view.setPlaceholderText(tr("view.refinement.log_placeholder"))
        layout.addWidget(self._log_view, stretch=1)

        btn_row = QHBoxLayout()
        self._btn_clear_log = QPushButton(tr("view.refinement.btn_clear_log"))
        self._btn_clear_log.clicked.connect(self._on_clear_log)
        btn_row.addWidget(self._btn_clear_log)

        self._btn_save_log = QPushButton(tr("view.refinement.btn_save_log"))
        self._btn_save_log.clicked.connect(self._on_save_log)
        btn_row.addWidget(self._btn_save_log)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        return group

    def _setup_connections(self) -> None:
        self._vm.refinement_completed.connect(self._on_refinement_completed)
        self._vm.refinement_log.connect(self._append_log)
        self._chk_wizard.toggled.connect(self._apply_wizard_style)

    # ------------------------------------------------------------------
    # 精修方式 (向导式 / 手动)
    # ------------------------------------------------------------------

    def _wizard_params(self) -> dict:
        """向导推荐配置 (来自内置精修模板, 与精修向导同源)。"""
        t = self._wizard_template
        if t is None:  # 模板异常缺失时的兜底 (与 RefinementTemplate 默认值一致)
            return {
                "name": "builtin", "engine": "builtin", "strategy": "sequential",
                "max_cycles": 20, "peak_shape": "pseudo-voigt",
                "bg_method": "snip", "fwhm": 0.15, "zero_shift": 0.0,
                "params": {},
            }
        return {
            "name": getattr(t, "name", ""),
            "engine": getattr(t, "engine", "builtin"),
            "strategy": getattr(t, "strategy", "sequential"),
            "max_cycles": int(getattr(t, "max_cycles", 20)),
            "peak_shape": getattr(t, "peak_shape", "pseudo-voigt"),
            "bg_method": getattr(t, "background_method", "snip"),
            "fwhm": 0.15,
            "zero_shift": 0.0,
            "params": dict(getattr(t, "params", {}) or {}),
        }

    def _apply_wizard_style(self, enabled: bool) -> None:
        """勾选 = 采用向导推荐参数并锁住手动控件; 取消 = 交还手动控制。"""
        if enabled:
            p = self._wizard_params()
            self._engine_combo.setCurrentText(p["engine"])
            self._strategy_combo.setCurrentText(p["strategy"])
            self._max_cycles.setValue(p["max_cycles"])
            self._peak_shape_combo.setCurrentText(p["peak_shape"])
            self._bg_combo.setCurrentText(p["bg_method"])
            self._fwhm_spin.setValue(p["fwhm"])
            self._zero_shift_spin.setValue(p["zero_shift"])

        for w in (
            self._engine_combo,
            self._strategy_combo,
            self._max_cycles,
            self._peak_shape_combo,
            self._bg_combo,
            self._fwhm_spin,
            self._zero_shift_spin,
        ):
            w.setEnabled(not enabled)

    def is_wizard_style(self) -> bool:
        """当前是否按精修向导的方式执行。"""
        return bool(self._chk_wizard.isChecked())

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------

    def _append_log(self, message: str) -> None:
        try:
            self._log_view.appendPlainText(str(message))
        except Exception:  # noqa: BLE001 - 日志显示失败不该影响精修
            pass

    def _on_clear_log(self) -> None:
        self._log_view.clear()

    def _on_save_log(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, tr("view.refinement.btn_save_log"),
            "refinement_log.txt", "文本文件 (*.txt *.log);;所有文件 (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._log_view.toPlainText())
        except OSError as e:
            self._append_log(tr("view.refinement.log_save_failed", error=str(e)))

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

            wizard_style = self.is_wizard_style()
            preset = self._wizard_params()
            engine = self._engine_combo.currentText()
            strategy = self._strategy_combo.currentText()

            self._log_view.clear()
            self._append_log(tr("view.refinement.log_start"))
            if wizard_style:
                self._append_log(
                    tr(
                        "view.refinement.log_wizard_style",
                        name=preset["name"],
                        engine=engine,
                        strategy=strategy,
                    )
                )
            else:
                self._append_log(tr("view.refinement.log_manual_style"))
            self._append_log(
                tr(
                    "view.refinement.log_params",
                    engine=engine,
                    strategy=strategy,
                    cycles=self._max_cycles.value(),
                    shape=self._peak_shape_combo.currentText(),
                    bg=self._bg_combo.currentText(),
                )
            )
            BusyIndicator.pump()

            # 向导方式: 把模板自带的额外参数一并带上 (与精修向导执行页一致)
            extra = dict(preset.get("params", {})) if wizard_style else {}

            # 把进度回调交给精修引擎: 多起点 + 稀疏抛光都是纯 Python 嵌套循环,
            # 借它周期性泵事件, 窗口才不会在几十秒里被系统标成"未响应"。
            # 顺带也让过程日志可以随事件泵一起刷到界面上 (跑码观感)。
            try:
                self._vm.refine_structure(
                    strategy=strategy,
                    engine=engine,
                    max_cycles=self._max_cycles.value(),
                    peak_shape=self._peak_shape_combo.currentText(),
                    fwhm=self._fwhm_spin.value(),
                    bg_method=self._bg_combo.currentText(),
                    zero_shift=self._zero_shift_spin.value(),
                    progress_cb=BusyIndicator.progress_tick,
                    **extra,
                )
            except Exception as e:  # noqa: BLE001 - 兜底: VM 已吞异常, 这里防串出
                self._append_log(tr("view.refinement.log_failed", error=str(e)))
                self._btn_refine.setEnabled(True)
                self._btn_cancel.setEnabled(False)

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
        self._label_time.setText(f"{getattr(result, 'time_seconds', 0.0):.1f} s")

        self._append_log(
            tr(
                "view.refinement.log_result",
                wr=f"{result.wR:.3f}",
                gof=f"{result.GOF:.3f}",
                quality=result.quality_grade,
                cycles=result.num_cycles,
                time=f"{getattr(result, 'time_seconds', 0.0):.1f}",
            )
        )
        for phase in result.phases:
            self._append_log(
                tr(
                    "view.refinement.log_phase",
                    name=phase.name,
                    weight=f"{phase.weight_fraction:.2f}",
                )
            )
        self._append_log(tr("view.refinement.log_done"))

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
            self._phase_table.setItem(row, 2, QTableWidgetItem(a_val))
            self._phase_table.setItem(row, 3, QTableWidgetItem(b_val))
            self._phase_table.setItem(row, 4, QTableWidgetItem(c_val))

        # 更新对比图
        self._compare_plot.clear_plot()
        if result.observed_data:
            obs_x, obs_y = result.observed_data
            self._compare_plot.plot_data(
                type("Data", (), {"two_theta": obs_x, "intensity": obs_y})(),
                label=tr("view.refinement.label_observed"),
            )
        if result.simulated_data:
            sim_x, sim_y = result.simulated_data
            self._compare_plot.plot_data(
                type("Data", (), {"two_theta": sim_x, "intensity": sim_y})(),
                label=tr("view.refinement.label_simulated"),
                color="red",
            )

        # 更新残差图
        self._residual_plot.clear_plot()
        if result.residual_data:
            res_x, res_y = result.residual_data
            self._residual_plot.plot_data(
                type("Data", (), {"two_theta": res_x, "intensity": res_y})(),
                label=tr("view.refinement.label_residual"),
                color="green",
            )
