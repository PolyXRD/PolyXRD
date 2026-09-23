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
    QListWidget,
    QListWidgetItem,
    QMenu,
    QFileDialog,
    QMessageBox,
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

        # 对比图 (M24: 拉大)
        self._compare_plot = PlotWidget()
        self._label_compare = QLabel(tr("view.refinement.label_compare"))
        left_layout.addWidget(self._label_compare)
        left_layout.addWidget(self._compare_plot, stretch=5)

        # 残差图 (M24: 改细条, X 轴与主图双向同步)
        self._residual_plot = PlotWidget()
        self._label_residual = QLabel(tr("view.refinement.label_residual"))
        left_layout.addWidget(self._label_residual)
        left_layout.addWidget(self._residual_plot, stretch=1)
        self._install_x_sync()

        # 精修过程日志 (M24: 从整页底栏移到左栏残差条下方)
        left_layout.addWidget(self._build_log_panel(), stretch=2)

        # 右侧：控制区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # 精修控制
        self._group_ctrl = QGroupBox(tr("view.refinement.group_control"))
        ctrl_layout = QFormLayout()
        self._form_ctrl = ctrl_layout

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
        ctrl_layout.addRow(tr("vw.refinement_view.peak_shape"), self._peak_shape_combo)

        self._fwhm_spin = QDoubleSpinBox()
        self._fwhm_spin.setRange(0.05, 2.0)
        self._fwhm_spin.setValue(0.15)
        self._fwhm_spin.setSingleStep(0.01)
        self._fwhm_spin.setDecimals(2)
        self._fwhm_spin.setSuffix("°")
        ctrl_layout.addRow(tr("vw.refinement_view.init_fwhm"), self._fwhm_spin)

        # 背景参数
        self._bg_combo = QComboBox()
        self._bg_combo.addItems(["snip", "als", "polynomial", "median", "rolling"])
        ctrl_layout.addRow(tr("vw.refinement_view.bg_method"), self._bg_combo)

        # 仪器参数
        self._zero_shift_spin = QDoubleSpinBox()
        self._zero_shift_spin.setRange(-2.0, 2.0)
        self._zero_shift_spin.setValue(0.0)
        self._zero_shift_spin.setSingleStep(0.01)
        self._zero_shift_spin.setDecimals(3)
        self._zero_shift_spin.setSuffix("°")
        ctrl_layout.addRow(tr("vw.refinement_view.zero_shift"), self._zero_shift_spin)

        self._btn_refine = QPushButton(tr("view.refinement.btn_start_refine"))
        self._btn_refine.clicked.connect(self._on_refine)
        ctrl_layout.addRow(self._btn_refine)

        self._btn_cancel = QPushButton(tr("vw.refinement_view.cancel"))
        self._btn_cancel.setEnabled(False)
        ctrl_layout.addRow(self._btn_cancel)

        self._group_ctrl.setLayout(ctrl_layout)
        right_layout.addWidget(self._group_ctrl)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        right_layout.addWidget(self._progress)

        # 精修结果
        self._group_result = QGroupBox(tr("view.refinement.group_result"))
        result_layout = QFormLayout()
        self._form_result = result_layout

        self._label_rwp = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_rwp"), self._label_rwp)

        self._label_rexp = QLabel("--")
        result_layout.addRow("Rexp:", self._label_rexp)

        self._label_rb = QLabel("--")
        result_layout.addRow("Rb:", self._label_rb)

        self._label_gof = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_gof"), self._label_gof)

        self._label_quality = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_quality"), self._label_quality)

        self._label_cycles = QLabel("--")
        result_layout.addRow(tr("view.refinement.label_cycles"), self._label_cycles)

        self._label_time = QLabel("--")
        result_layout.addRow(tr("vw.refinement_view.time_spent"), self._label_time)

        self._group_result.setLayout(result_layout)
        right_layout.addWidget(self._group_result)

        # 物相含量表
        self._group_phases = QGroupBox(tr("view.refinement.group_phases"))
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

        self._group_phases.setLayout(phase_layout)
        right_layout.addWidget(self._group_phases, stretch=1)

        # 已勾选物相 (M24: 继承物相分析页勾选集合, 右键导出 CIF)
        self._group_selected = QGroupBox(tr("vw.refinement_view.selected_phases"))
        sel_layout = QVBoxLayout()
        self._selected_phase_list = QListWidget()
        self._selected_phase_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._selected_phase_list.customContextMenuRequested.connect(
            self._selected_phase_context_menu
        )
        sel_layout.addWidget(self._selected_phase_list)
        self._group_selected.setLayout(sel_layout)
        right_layout.addWidget(self._group_selected, stretch=1)

        # 外部精修程序区 (M25-2: GSAS-II / MAUD / FullProf 配置与启动)
        from polyxrd.views.widgets.external_engines_group import (
            ExternalEnginesGroup,
        )

        self._ext_engines = ExternalEnginesGroup()
        self._ext_engines.set_context_provider(self._external_context)
        self._ext_engines.log_message.connect(self._append_log)
        self._ext_engines.fullprof_requested.connect(self._on_external_fullprof)
        self._ext_group = self._ext_engines
        right_layout.addWidget(self._ext_group)

        main_layout.addWidget(left_widget, stretch=2)
        main_layout.addWidget(right_widget, stretch=1)

        outer.addWidget(top_widget)

    def _install_x_sync(self) -> None:
        """残差条与主图 X 轴双向同步 (两个独立 canvas, 手动互抄 xlim)。"""
        self._compare_plot.get_axes().callbacks.connect(
            "xlim_changed", self._sync_residual_xlim
        )
        self._residual_plot.get_axes().callbacks.connect(
            "xlim_changed", self._sync_compare_xlim
        )

    def _sync_residual_xlim(self, ax) -> None:
        try:
            rax = self._residual_plot.get_axes()
            if rax.get_xlim() != ax.get_xlim():
                rax.set_xlim(*ax.get_xlim())
                self._residual_plot._canvas.draw_idle()
        except (RuntimeError, AttributeError):  # 控件已销毁
            pass

    def _sync_compare_xlim(self, ax) -> None:
        try:
            cax = self._compare_plot.get_axes()
            if cax.get_xlim() != ax.get_xlim():
                cax.set_xlim(*ax.get_xlim())
                self._compare_plot._canvas.draw_idle()
        except (RuntimeError, AttributeError):
            pass

    def _build_log_panel(self) -> QWidget:
        """精修过程日志面板 (跑码式输出)。"""
        self._group_log = QGroupBox(tr("view.refinement.group_log"))
        group = self._group_log
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
        # M24: 勾选集合 → 右栏「已勾选物相」列表
        self._vm._phase_vm.selection_changed.connect(
            self._on_selected_phases_changed
        )

    def retranslate(self) -> None:
        """按当前语言重设本页构造期写死的文案 (不碰精修结果/日志内容)。

        页面里还有两行刻意不翻的标签: ``Rexp:`` 与 ``Rb:`` —— 它们是 IUCr
        通用记号, 与轴标题上的 ``log`` / ``sqrt`` 同源。
        """
        # 分组标题
        self._group_ctrl.setTitle(tr("view.refinement.group_control"))
        self._group_result.setTitle(tr("view.refinement.group_result"))
        self._group_phases.setTitle(tr("view.refinement.group_phases"))
        self._group_selected.setTitle(tr("vw.refinement_view.selected_phases"))
        self._group_log.setTitle(tr("view.refinement.group_log"))

        # 图上方的小标题
        self._label_compare.setText(tr("view.refinement.label_compare"))
        self._label_residual.setText(tr("view.refinement.label_residual"))

        # 表单行标签 (布局内部造的 QLabel, 用 labelForField 反查)
        ctrl_rows = (
            (self._engine_combo, "view.refinement.label_engine"),
            (self._strategy_combo, "view.refinement.label_strategy"),
            (self._max_cycles, "view.refinement.label_max_cycles"),
            (self._peak_shape_combo, "vw.refinement_view.peak_shape"),
            (self._fwhm_spin, "vw.refinement_view.init_fwhm"),
            (self._bg_combo, "vw.refinement_view.bg_method"),
            (self._zero_shift_spin, "vw.refinement_view.zero_shift"),
        )
        for field, key in ctrl_rows:
            label = self._form_ctrl.labelForField(field)
            if label is not None:
                label.setText(tr(key))

        result_rows = (
            (self._label_rwp, "view.refinement.label_rwp"),
            (self._label_gof, "view.refinement.label_gof"),
            (self._label_quality, "view.refinement.label_quality"),
            (self._label_cycles, "view.refinement.label_cycles"),
            (self._label_time, "vw.refinement_view.time_spent"),
        )
        for field, key in result_rows:
            label = self._form_result.labelForField(field)
            if label is not None:
                label.setText(tr(key))

        # 按钮 / 复选框 / 占位文本
        self._chk_wizard.setText(tr("view.refinement.wizard_style"))
        self._chk_wizard.setToolTip(tr("view.refinement.wizard_style_tip"))
        self._btn_refine.setText(tr("view.refinement.btn_start_refine"))
        self._btn_cancel.setText(tr("vw.refinement_view.cancel"))
        self._btn_clear_log.setText(tr("view.refinement.btn_clear_log"))
        self._btn_save_log.setText(tr("view.refinement.btn_save_log"))
        self._log_view.setPlaceholderText(tr("view.refinement.log_placeholder"))

        # 物相含量表表头
        self._phase_table.setHorizontalHeaderLabels([
            tr("view.refinement.col_phase"),
            tr("view.refinement.col_weight"),
            tr("view.refinement.col_a"),
            tr("view.refinement.col_b"),
            tr("view.refinement.col_c"),
        ])

    # ------------------------------------------------------------------
    # M24: 已勾选物相列表
    # ------------------------------------------------------------------

    def _on_selected_phases_changed(self, phases: list) -> None:
        """物相分析页勾选变更 → 重建右栏列表。"""
        self._selected_phase_list.clear()
        for p in phases:
            item = QListWidgetItem(
                f"{getattr(p, 'name', '')}  {getattr(p, 'formula', '')}".strip()
            )
            item.setData(Qt.ItemDataRole.UserRole, p)
            self._selected_phase_list.addItem(item)

    def _selected_phase_context_menu(self, pos) -> None:
        """已勾选物相右键 → 导出 CIF 文件 (与主窗/物相页共用服务)。"""
        item = self._selected_phase_list.itemAt(pos)
        if item is None:
            return
        phase = item.data(Qt.ItemDataRole.UserRole)
        if phase is None:
            return
        menu = QMenu(self)
        act_export = menu.addAction(tr("vw.refinement_view.export_cif"))
        chosen = menu.exec(self._selected_phase_list.viewport().mapToGlobal(pos))
        if chosen is not act_export:
            return
        from polyxrd.services.phase_cif_export import (
            CifUnavailableError,
            default_cif_filename,
            export_phase_cif,
            resolve_cod_id,
        )

        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("vw.refinement_view.export_cif_title"),
            default_cif_filename(phase, resolve_cod_id(phase)),
            tr("vw.refinement_view.cif_filter"),
        )
        if not path:
            return
        try:
            export_phase_cif(phase, path)
        except CifUnavailableError as exc:
            QMessageBox.warning(
                self, tr("vw.refinement_view.export_cif_warn_title"), str(exc)
            )
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("vw.refinement_view.export_cif_warn_title"),
                tr("vw.refinement_view.export_cif_write_failed", exc=exc),
            )

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

    def _external_context(self):
        """外部引擎启动面板的数据/物相提供者 (M25-2)。"""
        return self._vm.current_data, list(self._vm._phase_vm.selected_phases)

    def _on_external_fullprof(self, fp_exe: str) -> None:
        """FullProf 批处理精修 (M25-6): 忙碌闸门内跑 auto_refine 并回写日志。"""
        from polyxrd.services.fullprof.runner import auto_refine, new_run_dir

        data = self._vm.current_data
        phases = list(self._vm._phase_vm.selected_phases)
        if data is None:
            self._append_log("[fullprof] 请先加载数据")
            return
        if not phases:
            self._append_log("[fullprof] 请先在物相分析页勾选物相")
            return

        self._append_log("[fullprof] ====== FullProf 精修开始 ======")
        with busy(self, tr("vw.refinement_view.fullprof_busy")) as acquired:
            if not acquired:
                return
            wd = new_run_dir("fullprof")
            self._append_log(f"[fullprof] 工作目录: {wd}")
            wavelength = float(getattr(data, "wavelength", 1.54056) or 1.54056)
            try:
                res = auto_refine(
                    data, phases, wd,
                    fp_exe=fp_exe, stem="polyxrd",
                    on_log=self._append_log, wavelength=wavelength,
                )
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[fullprof] 运行失败: {exc}")
                return
        if res.ok:
            self._append_log(
                f"[fullprof] 完成: Rwp={res.rwp:.2f}%  Rexp={res.rexp:.2f}%  "
                f"Rp={res.rp:.2f}%  GoF²={res.chi2:.2f}"
            )
            self._append_log(f"[fullprof] 结果文件: {res.sum_path}")
        else:
            self._append_log(f"[fullprof] 未收敛: {res.error}")

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
        self._label_rwp.setText(f"{result.Rwp:.3f} %")
        self._label_rexp.setText(f"{getattr(result, 'Rexp', 0.0):.3f} %")
        self._label_rb.setText(f"{getattr(result, 'Rb', 0.0):.3f} %")
        self._label_gof.setText(f"{result.GOF:.3f}")
        self._label_quality.setText(result.quality_grade)
        self._label_cycles.setText(str(result.num_cycles))
        self._label_time.setText(f"{getattr(result, 'time_seconds', 0.0):.1f} s")

        self._append_log(
            tr(
                "view.refinement.log_result",
                wr=f"{result.Rwp:.3f}",
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
