"""
精修向导
========
分步式Rietveld精修向导界面，引导用户完成从数据选择到精修执行的完整流程。

流程步骤:
1. 选择数据 - 显示已加载数据信息，选择精修范围
2. 选择物相 - 从CIF数据库或COD搜索选择物相，支持多相选择
3. 参数设置 - 背景方法、峰形模型、精修引擎、最大循环数
4. 预览确认 - 显示所有设置的预览
5. 执行精修 - 显示精修进度和结果摘要

本模块对外提供两个东西 (主窗口的"两条精修路径"中的分步那条):
- `RefinementWizard`: 向导本体 (QWidget), 可分步走完并**自己跑精修**;
- `RefinementWizardHostDialog`: 把向导装进对话框的最小宿主, 供主窗口一键弹出。

对比另一条路径 (`main_window.RefinementWizardDialog`, 简洁单页): 那个只收
几个参数就交给主 VM 去精修; 本向导多了模板管理 / CIF 导入 / COD 检索 / 预览,
且自带 refiner 独立执行 —— 所以结果要靠 `result_ready` 信号回灌主窗口。
"""
from __future__ import annotations

from typing import Optional
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QGroupBox,
    QFormLayout,
    QStackedWidget,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QTextEdit,
    QTabWidget,
    QLineEdit,
    QMessageBox,
    QAbstractItemView,
)

from polyxrd.i18n import tr
from polyxrd.models.phase import Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.cif_database import CIFDatabase
from polyxrd.services.cod_local import CODLocalDatabase
from polyxrd.services.cod_searcher import CODSearcher, CODEntry
from polyxrd.services.phase_cif import cif_to_phase
from polyxrd.services.refinement_templates import RefinementTemplateManager
from polyxrd.services.phase_structure_resolver import (
    PhaseStructureResolver,
    extract_cod_id,
)
from polyxrd.services.rietveld_refiner import RietveldRefiner
from polyxrd.views.widgets.busy_indicator import BusyIndicator, busy


class _StructureSearchWorker(QThread):
    """挂载数据库结构检索的后台线程。

    COD 库的 LIKE 查询在 7~11 万行上无索引全扫, 实测 3~4 s —— 不能在
    主线程跑 (窗口冻结)。结果按发起时的查询词回填, 迟到的旧结果丢弃。
    """

    done = Signal(str, list)

    def __init__(self, db, query: str, limit: int = 100,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._query = query
        self._limit = limit

    def run(self) -> None:
        try:
            results = self._db.search_structures(self._query, limit=self._limit)
        except Exception:
            results = []
        self.done.emit(self._query, results)


class _PhaseCifBrowseWorker(QThread):
    """为已勾选物相预填候选 CIF 列表 (向导物相页打开时)。

    主窗口勾了物相再进向导 → 上列表应立刻能看到「这些物相的可用 CIF」,
    同一物相在库里往往有多条 (不同实验来源/精修版本), 全部列出供挑选。
    逐相走 ``find_structure_candidates`` (公式精确 + 矿名模糊), 结果去重。
    """

    done = Signal(list)

    def __init__(self, db, phases: list, limit_per_phase: int = 12,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._phases = list(phases)
        self._limit = limit_per_phase

    def run(self) -> None:
        from polyxrd.utils.formula_parser import normalize_cod_formula

        out: list[dict] = []
        seen: set = set()
        for ph in self._phases:
            try:
                cands = self._db.find_structure_candidates(
                    normalize_cod_formula(getattr(ph, "formula", "") or ""),
                    getattr(ph, "name", "") or "",
                    limit=self._limit,
                )
            except Exception:
                cands = []
            for cand in cands:
                cid = cand.get("cod_id")
                if cid in seen:
                    continue
                seen.add(cid)
                item = dict(cand)
                item["_for_phase"] = getattr(ph, "name", "") or ""
                out.append(item)
        self.done.emit(out)


class RefinementWizard(QWidget):
    """精修向导

    分步引导用户完成Rietveld精修配置和执行。
    使用QStackedWidget实现页面切换，通过信号传递结果。

    Signals:
        wizard_completed: 向导完成，发射RefinementResult
        wizard_cancelled: 向导取消
        refinement_started: 精修开始，发射配置字典
        refinement_progress: 精修进度 (0-100)
        refinement_finished: 精修完成，发射RefinementResult
    """

    wizard_completed = Signal(object)
    wizard_cancelled = Signal()
    refinement_started = Signal(dict)
    refinement_progress = Signal(int)
    refinement_finished = Signal(object)

    def __init__(
        self,
        data: Optional[XRDData] = None,
        phases: Optional[list[Phase]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._data: Optional[XRDData] = data
        self._selected_phases: list[Phase] = phases or []
        self._template_mgr = RefinementTemplateManager()
        self._refiner = RietveldRefiner()
        self._cod_searcher = CODSearcher()
        self._cif_db = CIFDatabase()
        # 挂载的 COD 库 (含内嵌 CIF) —— 向导 CIF 列表/结构加载的数据源
        self._cod_db = CODLocalDatabase()
        self._structure_worker: Optional[_StructureSearchWorker] = None
        # 已勾选物相 → 候选 CIF 预填 (后台线程)
        self._browse_worker: Optional[_PhaseCifBrowseWorker] = None
        # 精修前置 CIF 自动匹配 (v0.12): 已选物相缺结构时查库补齐
        self._cif_resolver = PhaseStructureResolver()

        self._refinement_config: dict = {
            "engine": "builtin",
            "strategy": "sequential",
            "background_method": "snip",
            "peak_shape": "pseudo-voigt",
            "max_cycles": 20,
            "two_theta_min": 5.0,
            "two_theta_max": 80.0,
            "params": {},
        }

        self._setup_ui()
        # 带物相进向导 (主窗口勾选后打开) → 立刻回填下表并预填候选 CIF
        if self._selected_phases:
            self._refresh_selected_phases_table()
            self._browse_cifs_for_phases()
        self._apply_template(self._template_mgr.get_builtin_templates()[0])

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # 步骤指示
        self._step_label = QLabel()
        self._step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self._step_label)

        # 页面堆栈
        self._stack = QStackedWidget()
        self._page_indexes: dict[str, int] = {}

        self._page_indexes["data"] = self._stack.addWidget(
            self._create_data_page()
        )
        self._page_indexes["phase"] = self._stack.addWidget(
            self._create_phase_page()
        )
        self._page_indexes["params"] = self._stack.addWidget(
            self._create_params_page()
        )
        self._page_indexes["preview"] = self._stack.addWidget(
            self._create_preview_page()
        )
        self._page_indexes["execute"] = self._stack.addWidget(
            self._create_execute_page()
        )

        main_layout.addWidget(self._stack, stretch=1)

        # 导航按钮
        nav_layout = QHBoxLayout()

        self._btn_prev = QPushButton(tr("wizard.btn_prev"))
        self._btn_prev.clicked.connect(self._on_prev)
        nav_layout.addWidget(self._btn_prev)

        nav_layout.addStretch()

        self._btn_cancel = QPushButton(tr("wizard.btn_cancel"))
        self._btn_cancel.clicked.connect(self._on_cancel)
        nav_layout.addWidget(self._btn_cancel)

        self._btn_next = QPushButton(tr("wizard.btn_next"))
        self._btn_next.clicked.connect(self._on_next)
        nav_layout.addWidget(self._btn_next)

        self._btn_finish = QPushButton(tr("wizard.btn_finish"))
        self._btn_finish.clicked.connect(self._on_finish)
        self._btn_finish.setVisible(False)
        nav_layout.addWidget(self._btn_finish)

        main_layout.addLayout(nav_layout)

        self._update_step_display()

    # ------------------------------------------------------------------
    # 页面 1: 数据选择
    # ------------------------------------------------------------------

    def _create_data_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        info_group = QGroupBox(tr("wizard.data_page.info_title"))
        info_layout = QFormLayout()

        data_info = self._get_data_info()
        self._label_data_status = QLabel(data_info["status"])
        self._label_data_status.setStyleSheet(
            "color: green;" if self._data else "color: red;"
        )
        info_layout.addRow(tr("wizard.data_page.data_status"), self._label_data_status)

        self._label_data_points = QLabel(str(data_info["points"]))
        info_layout.addRow(tr("wizard.data_page.data_points"), self._label_data_points)

        self._label_two_theta_range = QLabel(data_info["two_theta_range"])
        info_layout.addRow(tr("wizard.data_page.two_theta_range"), self._label_two_theta_range)

        self._label_wavelength = QLabel(data_info["wavelength"])
        info_layout.addRow(tr("wizard.data_page.wavelength"), self._label_wavelength)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        range_group = QGroupBox(tr("wizard.data_page.range_title"))
        range_layout = QFormLayout()

        self._spin_two_theta_min = QDoubleSpinBox()
        self._spin_two_theta_min.setRange(0.0, 180.0)
        self._spin_two_theta_min.setSuffix(" °")
        self._spin_two_theta_min.setDecimals(2)
        self._spin_two_theta_min.setValue(
            self._data.two_theta.min() if self._data else 5.0
        )
        self._spin_two_theta_min.valueChanged.connect(self._on_range_changed)
        range_layout.addRow(tr("wizard.data_page.range_min"), self._spin_two_theta_min)

        self._spin_two_theta_max = QDoubleSpinBox()
        self._spin_two_theta_max.setRange(0.0, 180.0)
        self._spin_two_theta_max.setSuffix(" °")
        self._spin_two_theta_max.setDecimals(2)
        self._spin_two_theta_max.setValue(
            self._data.two_theta.max() if self._data else 80.0
        )
        self._spin_two_theta_max.valueChanged.connect(self._on_range_changed)
        range_layout.addRow(tr("wizard.data_page.range_max"), self._spin_two_theta_max)

        range_group.setLayout(range_layout)
        layout.addWidget(range_group)

        layout.addStretch()
        return page

    # ------------------------------------------------------------------
    # 页面 2: 物相选择
    # ------------------------------------------------------------------

    def _create_phase_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._phase_tabs = QTabWidget()

        cif_page = QWidget()
        cif_layout = QVBoxLayout(cif_page)

        # 结构检索: 化学式 / 矿物名 / COD 编号 (后台线程, 同一物相
        # 可能有多条 CIF, 全部列出供挑选)
        cif_search_layout = QHBoxLayout()
        self._cif_search_input = QLineEdit()
        self._cif_search_input.setPlaceholderText(
            tr("wizard.phase_page.cif_search_placeholder")
        )
        self._cif_search_input.returnPressed.connect(self._on_cif_search)
        cif_search_layout.addWidget(self._cif_search_input, stretch=1)

        self._btn_cif_search = QPushButton(tr("wizard.phase_page.btn_cod_search"))
        self._btn_cif_search.clicked.connect(self._on_cif_search)
        cif_search_layout.addWidget(self._btn_cif_search)
        cif_layout.addLayout(cif_search_layout)

        self._cif_hint = QLabel(tr("wizard.phase_page.cif_list_hint"))
        self._cif_hint.setWordWrap(True)
        self._cif_hint.setStyleSheet("color: #666;")
        cif_layout.addWidget(self._cif_hint)

        self._cif_count_label = QLabel("")
        self._cif_count_label.setStyleSheet("color: #666;")
        cif_layout.addWidget(self._cif_count_label)

        self._cif_list = QListWidget()
        self._cif_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._populate_cif_list()
        cif_layout.addWidget(self._cif_list)

        self._btn_cif_select = QPushButton(tr("wizard.phase_page.btn_add_cif"))
        self._btn_cif_select.clicked.connect(self._on_add_cif_phase)
        cif_layout.addWidget(self._btn_cif_select)

        self._phase_tabs.addTab(cif_page, tr("wizard.phase_page.tab_cif"))

        cod_page = QWidget()
        cod_layout = QVBoxLayout(cod_page)

        search_layout = QHBoxLayout()
        self._cod_search_input = QLineEdit()
        self._cod_search_input.setPlaceholderText(
            tr("wizard.phase_page.cod_search_placeholder")
        )
        search_layout.addWidget(self._cod_search_input)

        self._btn_cod_search = QPushButton(tr("wizard.phase_page.btn_cod_search"))
        self._btn_cod_search.clicked.connect(self._on_cod_search)
        search_layout.addWidget(self._btn_cod_search)

        cod_layout.addLayout(search_layout)

        self._cod_results_list = QListWidget()
        self._cod_results_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        cod_layout.addWidget(self._cod_results_list)

        self._btn_cod_add = QPushButton(tr("wizard.phase_page.btn_add_cod"))
        self._btn_cod_add.clicked.connect(self._on_add_cod_phases)
        cod_layout.addWidget(self._btn_cod_add)

        self._phase_tabs.addTab(cod_page, tr("wizard.phase_page.tab_cod"))

        layout.addWidget(self._phase_tabs, stretch=1)

        selected_group = QGroupBox(tr("wizard.phase_page.selected_title"))
        selected_layout = QVBoxLayout()

        self._selected_phases_table = QTableWidget(0, 5)
        self._selected_phases_table.setHorizontalHeaderLabels(
            [
                tr("wizard.phase_page.col_name"),
                tr("wizard.phase_page.col_formula"),
                tr("wizard.phase_page.col_space_group"),
                tr("wizard.phase_page.col_cif_source"),
                tr("wizard.phase_page.col_action"),
            ]
        )
        self._selected_phases_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        selected_layout.addWidget(self._selected_phases_table)

        self._btn_clear_phases = QPushButton(tr("wizard.phase_page.btn_clear"))
        self._btn_clear_phases.clicked.connect(self._on_clear_phases)
        selected_layout.addWidget(self._btn_clear_phases)

        selected_group.setLayout(selected_layout)
        layout.addWidget(selected_group, stretch=1)

        return page

    # ------------------------------------------------------------------
    # 页面 3: 参数设置
    # ------------------------------------------------------------------

    def _create_params_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        template_group = QGroupBox(tr("wizard.params_page.template_title"))
        template_layout = QHBoxLayout()

        template_layout.addWidget(QLabel(tr("wizard.params_page.template_label")))
        self._template_combo = QComboBox()
        self._populate_template_combo()
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        template_layout.addWidget(self._template_combo, stretch=1)

        self._btn_save_template = QPushButton(tr("wizard.params_page.btn_save_template"))
        self._btn_save_template.clicked.connect(self._on_save_as_template)
        template_layout.addWidget(self._btn_save_template)

        template_group.setLayout(template_layout)
        layout.addWidget(template_group)

        params_group = QGroupBox(tr("wizard.params_page.params_title"))
        params_layout = QFormLayout()

        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["auto", "gsas2", "maud", "builtin", "powerxrd"])
        self._engine_combo.currentTextChanged.connect(self._on_param_changed)
        params_layout.addRow(tr("wizard.params_page.engine"), self._engine_combo)

        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems(["sequential", "auto", "manual"])
        self._strategy_combo.currentTextChanged.connect(self._on_param_changed)
        params_layout.addRow(tr("wizard.params_page.strategy"), self._strategy_combo)

        self._background_combo = QComboBox()
        self._background_combo.addItems(
            ["snip", "als", "polynomial", "median", "rolling"]
        )
        self._background_combo.currentTextChanged.connect(self._on_param_changed)
        params_layout.addRow(tr("wizard.params_page.background"), self._background_combo)

        self._peak_shape_combo = QComboBox()
        self._peak_shape_combo.addItems(
            ["voigt", "pseudo-voigt", "lorentzian", "gaussian"]
        )
        self._peak_shape_combo.currentTextChanged.connect(self._on_param_changed)
        params_layout.addRow(tr("wizard.params_page.peak_shape"), self._peak_shape_combo)

        self._max_cycles_spin = QSpinBox()
        self._max_cycles_spin.setRange(1, 200)
        self._max_cycles_spin.setValue(20)
        self._max_cycles_spin.valueChanged.connect(self._on_param_changed)
        params_layout.addRow(tr("wizard.params_page.max_cycles"), self._max_cycles_spin)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        layout.addStretch()
        return page

    # ------------------------------------------------------------------
    # 页面 4: 预览确认
    # ------------------------------------------------------------------

    def _create_preview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        layout.addWidget(self._preview_text)

        return page

    # ------------------------------------------------------------------
    # 页面 5: 执行精修
    # ------------------------------------------------------------------

    def _create_execute_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        progress_group = QGroupBox(tr("wizard.execute_page.progress_title"))
        progress_layout = QVBoxLayout()

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        progress_layout.addWidget(self._progress_bar)

        self._progress_status = QLabel(tr("wizard.execute_page.status_idle"))
        progress_layout.addWidget(self._progress_status)

        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        result_group = QGroupBox(tr("wizard.execute_page.result_title"))
        result_layout = QFormLayout()

        self._label_wr = QLabel("--")
        result_layout.addRow(tr("wizard.execute_page.label_wr"), self._label_wr)

        self._label_rexp = QLabel("--")
        result_layout.addRow("Rexp:", self._label_rexp)

        self._label_rb = QLabel("--")
        result_layout.addRow("Rb:", self._label_rb)

        self._label_gof = QLabel("--")
        result_layout.addRow(tr("wizard.execute_page.label_gof"), self._label_gof)

        self._label_quality = QLabel("--")
        result_layout.addRow(tr("wizard.execute_page.label_quality"), self._label_quality)

        self._label_cycles_done = QLabel("--")
        result_layout.addRow(tr("wizard.execute_page.label_cycles"), self._label_cycles_done)

        self._label_time = QLabel("--")
        result_layout.addRow(tr("wizard.execute_page.label_time"), self._label_time)

        result_group.setLayout(result_layout)
        layout.addWidget(result_group)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setPlaceholderText(tr("wizard.execute_page.log_placeholder"))
        layout.addWidget(self._log_text, stretch=1)

        self._btn_start_refine = QPushButton(tr("wizard.execute_page.btn_start"))
        self._btn_start_refine.clicked.connect(self._on_start_refine)
        layout.addWidget(self._btn_start_refine)

        return page

    # ------------------------------------------------------------------
    # 步骤导航
    # ------------------------------------------------------------------

    def _current_step_name(self) -> str:
        for name, idx in self._page_indexes.items():
            if idx == self._stack.currentIndex():
                return name
        return "data"

    def _step_order(self) -> list[str]:
        return ["data", "phase", "params", "preview", "execute"]

    def _update_step_display(self) -> None:
        steps = self._step_order()
        current = self._current_step_name()
        current_idx = steps.index(current) if current in steps else 0

        step_title = tr(f"wizard.steps.{current}")
        step_hint = tr("wizard.step_hint", current=current_idx + 1, total=len(steps))
        self._step_label.setText(f"📋 {step_title}  |  {step_hint}")

        self._btn_prev.setEnabled(current_idx > 0)
        self._btn_next.setVisible(current_idx < len(steps) - 1)
        self._btn_finish.setVisible(current_idx == len(steps) - 1)

        if current == "execute":
            self._btn_next.setEnabled(False)

    def _on_prev(self) -> None:
        steps = self._step_order()
        current = self._current_step_name()
        idx = steps.index(current)
        if idx > 0:
            self._stack.setCurrentIndex(self._page_indexes[steps[idx - 1]])
            self._update_step_display()

    def _on_next(self) -> None:
        steps = self._step_order()
        current = self._current_step_name()
        idx = steps.index(current)
        if idx < len(steps) - 1:
            next_step = steps[idx + 1]

            if current == "data" and not self._validate_data_page():
                return
            if current == "phase" and not self._validate_phase_page():
                return
            if current == "params":
                self._sync_config_from_ui()
                self._update_preview()

            self._stack.setCurrentIndex(self._page_indexes[next_step])
            self._update_step_display()

    def _on_cancel(self) -> None:
        self.wizard_cancelled.emit()
        parent = self.parentWidget()
        if parent:
            parent.close()

    def _on_finish(self) -> None:
        if self._data is None:
            QMessageBox.warning(self, tr("dialog.warning"), tr("error.no_data"))
            return
        if not self._selected_phases:
            QMessageBox.warning(self, tr("dialog.warning"), tr("error.no_phase"))
            return
        self._on_start_refine()

    # ------------------------------------------------------------------
    # 页面 1 逻辑: 数据
    # ------------------------------------------------------------------

    def _get_data_info(self) -> dict[str, str]:
        if self._data is None:
            return {
                "status": tr("wizard.data_page.no_data"),
                "points": "0",
                "two_theta_range": "--",
                "wavelength": "--",
            }
        return {
            "status": tr("wizard.data_page.data_loaded"),
            "points": str(len(self._data)),
            "two_theta_range": f"{self._data.two_theta.min():.2f}° - {self._data.two_theta.max():.2f}°",
            "wavelength": f"{self._data.wavelength:.4f} Å",
        }

    def set_data(self, data: XRDData) -> None:
        self._data = data
        info = self._get_data_info()
        self._label_data_status.setText(info["status"])
        self._label_data_status.setStyleSheet("color: green;")
        self._label_data_points.setText(info["points"])
        self._label_two_theta_range.setText(info["two_theta_range"])
        self._label_wavelength.setText(info["wavelength"])
        self._spin_two_theta_min.setValue(data.two_theta.min())
        self._spin_two_theta_max.setValue(data.two_theta.max())

    def _on_range_changed(self) -> None:
        pass

    def _validate_data_page(self) -> bool:
        if self._data is None:
            QMessageBox.warning(self, tr("dialog.warning"), tr("error.no_data"))
            return False
        if self._spin_two_theta_min.value() >= self._spin_two_theta_max.value():
            QMessageBox.warning(
                self,
                tr("dialog.warning"),
                tr("wizard.data_page.range_invalid"),
            )
            return False
        return True

    # ------------------------------------------------------------------
    # 页面 2 逻辑: 物相
    # ------------------------------------------------------------------

    def _populate_cif_list(self) -> None:
        """默认列表: 内置矿物相 (加相时再按需匹配库内 CIF)。

        真正的 CIF 逐条列表在搜索后展示 —— 库里同一物相有多条 CIF,
        71k 条不可能一次性列出, 以搜代浏览 (回车即搜)。
        """
        self._cif_list.clear()
        try:
            phases = self._cif_db.get_phase_list()
        except Exception:
            phases = []
        for phase_info in phases:
            try:
                key = phase_info.get("key", "")
                mineral = self._cif_db.get_mineral_info(key)
                if mineral is None:
                    mineral = phase_info
                name = mineral.get("name", key)
                formula = mineral.get("formula", "")
                item = QListWidgetItem(
                    f"{name} ({formula})" if formula and formula != name else name
                )
                item.setData(Qt.ItemDataRole.UserRole, ("builtin", mineral))
                tip = tr("wizard.phase_page.cif_source_auto")
                item.setToolTip(tip)
                self._cif_list.addItem(item)
            except Exception:
                continue
        status = tr("wizard.phase_page.cif_list_count_builtin",
                    count=self._cif_list.count())
        try:
            if not self._cod_db.is_ready():
                status += "  " + tr("wizard.phase_page.cif_list_no_db")
        except Exception:
            pass
        self._set_cif_status(status)

    def _set_cif_status(self, text: str) -> None:
        """更新列表下方的一行状态 (条数 / 提示)。"""
        label = getattr(self, "_cif_count_label", None)
        if label is not None:
            label.setText(text)

    def _on_cif_search(self) -> None:
        """按化学式 / 矿物名 / COD 编号检索挂载数据库中的 CIF。

        LIKE 查询在 7~11 万行上要 3~4 s, 放后台线程跑; 迟到的旧结果
        按查询词丢弃。库不可用时提示并保留内置列表。
        """
        query = self._cif_search_input.text().strip()
        if not query:
            self._populate_cif_list()  # 清空 = 回到内置列表
            return
        if not self._cod_db.is_ready() and self._cod_db._inorg_db() is None:
            QMessageBox.information(
                self, tr("dialog.info"),
                tr("wizard.phase_page.cif_db_unavailable"),
            )
            return
        if self._structure_worker is not None and self._structure_worker.isRunning():
            return  # 上一轮还在跑, 忽略 (输入词以本轮为准)
        self._cif_list.clear()
        self._cif_list.addItem(QListWidgetItem(
            tr("wizard.phase_page.cif_list_searching")))
        self._set_cif_status(tr("wizard.phase_page.cif_list_searching"))
        self._btn_cif_search.setEnabled(False)
        self._structure_worker = _StructureSearchWorker(
            self._cod_db, query, limit=100, parent=self)
        self._structure_worker.done.connect(self._on_structure_search_done)
        self._structure_worker.start()

    def _on_structure_search_done(self, query: str, results: list) -> None:
        self._btn_cif_search.setEnabled(True)
        # 只接收最后一次发起的查询 (worker 防重入下基本不会出现旧结果)
        if self._cif_search_input.text().strip() != query:
            return
        self._fill_cif_list(results)
        if not results:
            self._set_cif_status(tr("wizard.phase_page.cod_no_results"))
        else:
            self._set_cif_status(tr("wizard.phase_page.cif_list_count",
                                    count=self._cif_list.count()))

    # ── 已选物相 → 候选 CIF 预填 ─────────────────────────────

    def _browse_cifs_for_phases(self) -> None:
        """按已勾选物相批量预填候选 CIF (后台线程)。

        上列表要能直接看到「这些物相在库里有哪些 CIF」(同一相常有多条),
        而不是只给一个空列表让用户自己搜。
        """
        if not self._selected_phases:
            self._populate_cif_list()
            return
        try:
            if not self._cod_db.is_ready() and self._cod_db._inorg_db() is None:
                self._set_cif_status(
                    tr("wizard.phase_page.cif_list_count_builtin",
                       count=self._cif_list.count())
                    + "  " + tr("wizard.phase_page.cif_list_no_db"))
                return
        except Exception:
            return
        if (self._browse_worker is not None
                and self._browse_worker.isRunning()):
            return
        self._cif_list.clear()
        self._cif_list.addItem(QListWidgetItem(
            tr("wizard.phase_page.cif_list_browsing")))
        self._set_cif_status(tr("wizard.phase_page.cif_list_browsing"))
        self._btn_cif_search.setEnabled(False)
        self._browse_worker = _PhaseCifBrowseWorker(
            self._cod_db, self._selected_phases, parent=self)
        self._browse_worker.done.connect(self._on_phase_cif_browse_done)
        self._browse_worker.start()

    def _on_phase_cif_browse_done(self, results: list) -> None:
        self._btn_cif_search.setEnabled(True)
        # 用户已切到手动搜索 → 丢弃迟到的预填结果
        if self._cif_search_input.text().strip():
            return
        if not results:
            # 库里没命中 → 退回内置列表 (加相时仍会自动匹配)
            self._populate_cif_list()
            return
        self._fill_cif_list(results)
        self._set_cif_status(
            tr("wizard.phase_page.cif_list_count", count=self._cif_list.count())
        )

    def _fill_cif_list(self, results: list) -> None:
        """把候选结构渲染进上列表 (搜索与预填共用)。"""
        self._cif_list.clear()
        if not results:
            self._cif_list.addItem(QListWidgetItem(
                tr("wizard.phase_page.cod_no_results")))
            return
        for cand in results:
            cod_id = cand["cod_id"]
            mineral = self._clean_mineral_name(cand.get("mineral_name"), cod_id)
            formula = cand.get("formula") or ""
            display = mineral or formula or f"COD {cod_id}"
            sg = cand.get("space_group") or ""
            cell = self._cell_summary(cand)
            cif_mark = "✓" if cand.get("has_cif") else "⤓"  # ⤓ = 需联网下载
            # 无机库多数条目没有矿名 (或矿名就是编号), display 退回 formula
            # → 此时不再追加 (式), 免得出现 "H2 Mg O2 (H2 Mg O2)"
            head = f"{display} ({formula})" if mineral and formula else display
            for_phase = cand.get("_for_phase") or ""
            if for_phase:
                head = tr("wizard.phase_page.cif_for_phase",
                          phase=for_phase, cif=head)
            parts = [head] + [p for p in (sg, cell) if p]
            label = f"{' · '.join(parts)} · COD {cod_id} {cif_mark}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ("cod", cand))
            self._cif_list.addItem(item)

    @staticmethod
    def _clean_mineral_name(mineral: Optional[str], cod_id) -> str:
        """过滤 COD 库里的「伪矿名」。

        全库索引的 mineral_name 取自 CIF 的 ``data_`` 行, 不少条目这一行
        就是 COD 编号本身 (如 "2101438") —— 当矿名展示毫无信息量, 还会
        让列表出现 "2101438 (H2 Mg O2)" 这种噪声。
        """
        name = (mineral or "").strip()
        if not name:
            return ""
        if name.isdigit() or name == str(cod_id):
            return ""
        if name.upper() in ("UNKNOWN", "N/A", "NA", "NONE"):
            return ""
        return name

    @staticmethod
    def _cell_summary(cand: dict) -> str:
        """候选条目的晶胞短摘要 (脏数据容错)。"""
        try:
            a, c = float(cand.get("a")), float(cand.get("c"))
            if 0.5 <= a <= 200 and 0.5 <= c <= 200:
                return f"a={a:.3f} c={c:.3f} Å"
        except (TypeError, ValueError):
            pass
        return "cell=?"

    def _on_add_cif_phase(self) -> None:
        items = self._cif_list.selectedItems()
        if not items:
            return
        with busy(self, tr("busy.cif_match")) as acquired:
            if not acquired:
                return
            for item in items:
                payload = item.data(Qt.ItemDataRole.UserRole)
                if not payload:
                    continue
                kind, data = payload
                if kind == "cod":
                    phase = self._load_cod_cif_phase(data)
                else:
                    phase = self._add_builtin_mineral_phase(data)
                if phase is not None:
                    self._add_phase(phase)

    # ------------------------------------------------------------------
    # CIF → Phase 装载 (库内优先, 官网下载兜底)
    # ------------------------------------------------------------------

    def _load_cod_cif_phase(self, cand: dict) -> Optional[Phase]:
        """把一条 COD 结构候选装载成带结构的 Phase。

        链路: 库内 cif_gz / cod 目录 CIF → 取不到再从 COD 官网下载
        (落盘 ~/.polyxrd/cif_cache) → cif_to_phase 解析位点。
        """
        cod_id = int(cand["cod_id"])
        mineral = self._clean_mineral_name(cand.get("mineral_name"), cod_id)
        formula = cand.get("formula") or ""
        display = mineral or formula or f"COD {cod_id}"
        name = f"{display} [COD {cod_id}]"

        phase = None
        try:
            phase = self._cod_db.get_phase(
                cod_id,
                wavelength=(float(self._data.wavelength)
                            if self._data is not None else 1.5406),
                two_theta_range=(5.0, 90.0),
                use_pymatgen_peaks=True,
            )
        except Exception:
            phase = None
        if phase is not None and phase.atomic_sites:
            phase.name = name
            return phase

        # 库里拿不到 (未挂库 / 无 cif_gz) → COD 官网下载
        return self._download_cif_phase(cod_id, name, formula)

    def _download_cif_phase(self, cod_id: int, name: str,
                            formula_hint: str = "") -> Optional[Phase]:
        """从 COD 官网下载 CIF 并构建带位点的 Phase (本地缓存落盘)。"""
        text = None
        try:
            text = self._cod_db.get_cif(cod_id)  # 内部含 REST 兜底
        except Exception:
            text = None
        if not text:
            try:
                text = self._cod_searcher.get_cif(cod_id)
            except Exception:
                text = None
        if not text:
            QMessageBox.warning(
                self, tr("dialog.warning"),
                tr("wizard.phase_page.cif_fetch_failed", error=f"COD {cod_id}"),
            )
            return None
        try:
            cache_dir = Path.home() / ".polyxrd" / "cif_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            out = cache_dir / f"COD{cod_id}.cif"
            out.write_text(text, encoding="utf-8")
        except OSError:
            out = None  # 落盘失败不阻断, 结构照样能用
        phase = cif_to_phase(text, fallback_name=name)
        phase.name = name
        if formula_hint and not phase.formula:
            phase.formula = formula_hint
        if out is not None:
            phase.cif_path = str(out)
        return phase

    def _add_builtin_mineral_phase(self, mineral_data: dict) -> Optional[Phase]:
        """内置矿物相: 先尝试按库内 CIF 匹配结构, 失败则按原样加入。

        后者不阻断 —— 执行页开始精修时 `_cif_resolver` 会再试一次。
        """
        phase = self._mineral_to_phase(mineral_data)
        try:
            resolved = self._cif_resolver.resolve(
                [phase],
                wavelength=(float(self._data.wavelength)
                            if self._data is not None else 1.5406),
                two_theta_range=(5.0, 90.0),
            )
            resolved_phase = resolved[0] if resolved else phase
        except Exception:
            resolved_phase = phase
        return resolved_phase

    def _mineral_to_phase(self, mineral_data: dict) -> Phase:
        lattice_data = mineral_data.get("lattice", {})
        from polyxrd.models.phase import LatticeParams

        lattice = LatticeParams(
            a=lattice_data.get("a", 1.0),
            b=lattice_data.get("b", 1.0),
            c=lattice_data.get("c", 1.0),
            alpha=lattice_data.get("alpha", 90.0),
            beta=lattice_data.get("beta", 90.0),
            gamma=lattice_data.get("gamma", 90.0),
        )
        return Phase(
            name=mineral_data.get("name", "Unknown"),
            formula=mineral_data.get("formula", ""),
            space_group=mineral_data.get("space_group", ""),
            lattice=lattice,
            atomic_sites=mineral_data.get("atomic_sites", []),
            weight_fraction=0.0,
        )

    def _on_cod_search(self) -> None:
        query = self._cod_search_input.text().strip()
        if not query:
            QMessageBox.information(
                self,
                tr("dialog.info"),
                tr("wizard.phase_page.cod_query_hint"),
            )
            return
        self._cod_results_list.clear()
        self._cod_results_list.addItem(
            QListWidgetItem(tr("wizard.phase_page.cod_searching"))
        )
        try:
            search_result = self._cod_searcher.search(formula=query)
            self._cod_results_list.clear()
            entries = search_result.entries
            if not entries:
                self._cod_results_list.addItem(
                    QListWidgetItem(tr("wizard.phase_page.cod_no_results"))
                )
            for entry in entries:
                mineral_name = entry.mineral_name or ""
                formula = entry.formula or ""
                head = (f"{mineral_name} ({formula})" if mineral_name and formula
                        else mineral_name or formula or "Unknown")
                item = QListWidgetItem(f"{head} - COD #{entry.cod_id}")
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self._cod_results_list.addItem(item)
        except Exception:
            self._cod_results_list.clear()
            self._cod_results_list.addItem(
                QListWidgetItem(tr("wizard.phase_page.cod_search_failed"))
            )

    def _on_add_cod_phases(self) -> None:
        items = self._cod_results_list.selectedItems()
        if not items:
            return
        with busy(self, tr("busy.cif_match")) as acquired:
            if not acquired:
                return
            for item in items:
                entry = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(entry, CODEntry):
                    phase = self._cod_entry_to_phase(entry)
                    if phase is not None:
                        self._add_phase(phase)

    def _cod_entry_to_phase(self, entry: CODEntry) -> Optional[Phase]:
        """在线搜索条目 → 带结构的 Phase。

        v0.12 修复: 旧实现把 ``entry.cif_url`` (网址!) 直接塞进
        cif_path, GSAS-II 桥拿到的是不存在的文件。现改为: 本地库
        (cod 目录 / cif_gz) 优先, 取不到再走 COD 官网下载并落盘缓存。
        """
        cod_id = int(entry.cod_id)
        display = entry.mineral_name or entry.formula or f"COD {cod_id}"
        name = f"{display} [COD {cod_id}]"
        phase = self._download_cif_phase(
            cod_id, name, formula_hint=entry.formula or ""
        )
        if phase is None:
            return None
        # 在线条目自带晶胞 → CIF 解析失败时也有基础晶胞可用
        if phase.lattice is None and entry.lattice_params:
            lat = entry.lattice_params or {}
            from polyxrd.models.phase import LatticeParams

            phase.lattice = LatticeParams(
                a=lat.get("a", 1.0), b=lat.get("b", 1.0), c=lat.get("c", 1.0),
                alpha=lat.get("alpha", 90.0), beta=lat.get("beta", 90.0),
                gamma=lat.get("gamma", 90.0),
            )
        if not phase.space_group and entry.space_group:
            phase.space_group = entry.space_group
        return phase

    def _add_phase(self, phase: Phase) -> None:
        existing_names = [p.name for p in self._selected_phases]
        if phase.name in existing_names:
            QMessageBox.information(
                self,
                tr("dialog.info"),
                tr("wizard.phase_page.phase_already_added", name=phase.name),
            )
            return
        self._selected_phases.append(phase)
        self._refresh_selected_phases_table()

    def _refresh_selected_phases_table(self) -> None:
        self._selected_phases_table.setRowCount(0)
        for phase in self._selected_phases:
            row = self._selected_phases_table.rowCount()
            self._selected_phases_table.insertRow(row)
            self._selected_phases_table.setItem(row, 0, QTableWidgetItem(phase.name))
            self._selected_phases_table.setItem(row, 1, QTableWidgetItem(phase.formula))
            self._selected_phases_table.setItem(
                row, 2, QTableWidgetItem(phase.space_group)
            )
            self._selected_phases_table.setItem(
                row, 3, QTableWidgetItem(self._cif_source_text(phase))
            )
            btn_remove = QPushButton(tr("common.delete"))
            btn_remove.clicked.connect(lambda _, r=row: self._remove_phase(r))
            self._selected_phases_table.setCellWidget(row, 4, btn_remove)

    @staticmethod
    def _cif_source_text(phase: Phase) -> str:
        """已选物相的 CIF 来源描述 (「CIF 来源」列)。"""
        cif_path = getattr(phase, "cif_path", None)
        if cif_path:
            # 缓存落盘是 COD<id>.cif, 本地 cod 库是 <cod_id>.cif —— 都归成 COD <id>
            stem = Path(cif_path).stem
            if stem.startswith("COD") and stem[3:].isdigit():
                return f"COD {stem[3:]}"
            if stem.isdigit():
                return f"COD {stem}"
            return Path(cif_path).name
        # 无落盘路径但有位点: 可能是从库内 cif_gz / tar 直接解析的 COD 结构,
        # 名字尾部带着 "[COD <id>]" → 仍应显示 COD 编号而非「内置结构」
        cod_id = extract_cod_id(getattr(phase, "name", "") or "")
        if cod_id and getattr(phase, "atomic_sites", None):
            return f"COD {cod_id}"
        if getattr(phase, "atomic_sites", None):
            return tr("wizard.phase_page.cif_source_builtin")
        return tr("wizard.phase_page.cif_source_auto")

    def _remove_phase(self, row: int) -> None:
        if 0 <= row < len(self._selected_phases):
            del self._selected_phases[row]
            self._refresh_selected_phases_table()
            if not self._selected_phases:
                self._populate_cif_list()

    def _on_clear_phases(self) -> None:
        self._selected_phases.clear()
        self._refresh_selected_phases_table()
        self._populate_cif_list()

    def set_phases(self, phases: list[Phase]) -> None:
        """设置已选物相 (下表), 并按这些物相预填上表的候选 CIF。"""
        self._cif_search_input.clear()
        self._selected_phases = list(phases)
        self._refresh_selected_phases_table()
        self._browse_cifs_for_phases()

    def _validate_phase_page(self) -> bool:
        if not self._selected_phases:
            QMessageBox.warning(
                self,
                tr("dialog.warning"),
                tr("error.no_phase"),
            )
            return False
        return True

    # ------------------------------------------------------------------
    # 页面 3 逻辑: 参数
    # ------------------------------------------------------------------

    def _populate_template_combo(self) -> None:
        self._template_combo.clear()
        templates = self._template_mgr.get_all_templates()
        for t in templates:
            label = (tr("vw.refinement_wizard.tpl_builtin",
                        name=self._template_display_name(t))
                     if t.is_builtin
                     else tr("vw.refinement_wizard.tpl_user", name=t.name))
            self._template_combo.addItem(label, t)

    @staticmethod
    def _template_display_name(template) -> str:
        """内置模板的**显示名**: 走 ``template.builtin.<key>`` 翻译键。

        模板的 ``name`` 字段不能本地化 —— 它同时是用户模板的文件名与
        ``get_template_by_name`` 的查找键, 一旦随语言漂移就会串味。所以内置
        模板另带一个稳定 ``key``, 只用来取显示名; 用户模板没有 key, 直接显示
        name (用户自己起的名, 不该被翻译)。
        """
        key = getattr(template, "key", "")
        if key:
            translated = tr(f"template.builtin.{key}")
            if translated != f"template.builtin.{key}":
                return translated
        return template.name

    def _on_template_changed(self, index: int) -> None:
        template = self._template_combo.itemData(index)
        if template:
            self._apply_template(template)

    def _apply_template(self, template) -> None:
        self._engine_combo.setCurrentText(template.engine)
        self._strategy_combo.setCurrentText(template.strategy)
        self._background_combo.setCurrentText(template.background_method)
        self._peak_shape_combo.setCurrentText(template.peak_shape)
        self._max_cycles_spin.setValue(template.max_cycles)
        self._refinement_config["params"] = dict(template.params)
        self._sync_config_from_ui()

    def _on_param_changed(self) -> None:
        self._sync_config_from_ui()

    def _sync_config_from_ui(self) -> None:
        self._refinement_config["engine"] = self._engine_combo.currentText()
        self._refinement_config["strategy"] = self._strategy_combo.currentText()
        self._refinement_config["background_method"] = self._background_combo.currentText()
        self._refinement_config["peak_shape"] = self._peak_shape_combo.currentText()
        self._refinement_config["max_cycles"] = self._max_cycles_spin.value()
        self._refinement_config["two_theta_min"] = self._spin_two_theta_min.value()
        self._refinement_config["two_theta_max"] = self._spin_two_theta_max.value()

    def _on_save_as_template(self) -> None:
        self._sync_config_from_ui()
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self,
            tr("wizard.template.save_title"),
            tr("wizard.template.save_name_prompt"),
        )
        if ok and name:
            template = self._template_mgr.create_from_config(
                self._refinement_config,
                name=name,
                description=tr("wizard.template.default_description"),
            )
            try:
                self._template_mgr.save_template(template)
                self._populate_template_combo()
                QMessageBox.information(
                    self,
                    tr("dialog.info"),
                    tr("wizard.template.save_success", name=name),
                )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    tr("dialog.error"),
                    tr("wizard.template.save_failed", error=str(e)),
                )

    # ------------------------------------------------------------------
    # 页面 4 逻辑: 预览
    # ------------------------------------------------------------------

    def _update_preview(self) -> None:
        self._sync_config_from_ui()
        config = self._refinement_config

        lines = []
        lines.append("═══ " + tr("wizard.preview.title") + " ═══\n")

        lines.append(f"📊 {tr('wizard.preview.data_section')}:")
        if self._data:
            lines.append(f"  • {tr('wizard.preview.data_points')}: {len(self._data)}")
            lines.append(
                f"  • {tr('wizard.preview.data_range')}: "
                f"{config['two_theta_min']:.2f}° - {config['two_theta_max']:.2f}°"
            )
            lines.append(
                f"  • {tr('wizard.preview.wavelength')}: {self._data.wavelength:.4f} Å"
            )
        else:
            lines.append(f"  • {tr('wizard.preview.no_data')}")

        lines.append(f"\n🔬 {tr('wizard.preview.phase_section')}:")
        if self._selected_phases:
            for i, phase in enumerate(self._selected_phases, 1):
                lat_info = ""
                if phase.lattice:
                    lat = phase.lattice
                    lat_info = (
                        f" (a={lat.a:.3f}, b={lat.b:.3f}, c={lat.c:.3f})"
                    )
                lines.append(
                    f"  {i}. {phase.name} [{phase.formula}]{lat_info}"
                )
        else:
            lines.append(f"  • {tr('wizard.preview.no_phase')}")

        lines.append(f"\n⚙️ {tr('wizard.preview.params_section')}:")
        lines.append(
            f"  • {tr('wizard.params_page.engine')}: {config['engine']}"
        )
        lines.append(
            f"  • {tr('wizard.params_page.strategy')}: {config['strategy']}"
        )
        lines.append(
            f"  • {tr('wizard.params_page.background')}: {config['background_method']}"
        )
        lines.append(
            f"  • {tr('wizard.params_page.peak_shape')}: {config['peak_shape']}"
        )
        lines.append(
            f"  • {tr('wizard.params_page.max_cycles')}: {config['max_cycles']}"
        )

        if config.get("params"):
            lines.append(f"\n📝 {tr('wizard.preview.advanced_section')}:")
            for key, value in config["params"].items():
                lines.append(f"  • {key}: {value}")

        lines.append("\n" + "═" * 40)

        self._preview_text.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # 页面 5 逻辑: 执行
    # ------------------------------------------------------------------

    def _on_start_refine(self) -> None:
        if self._data is None or not self._selected_phases:
            QMessageBox.warning(
                self,
                tr("dialog.warning"),
                tr("error.no_phase"),
            )
            return

        self._sync_config_from_ui()
        config = dict(self._refinement_config)
        self.refinement_started.emit(config)

        self._log_text.clear()
        self._log(tr("wizard.execute_page.log_start"))

        self._progress_bar.setValue(0)
        self._progress_status.setText(tr("wizard.execute_page.status_running"))
        self._btn_start_refine.setEnabled(False)

        # 裁剪数据范围
        data_to_refine = self._data
        tth_min = config["two_theta_min"]
        tth_max = config["two_theta_max"]
        if tth_min > self._data.two_theta.min() or tth_max < self._data.two_theta.max():
            data_to_refine = self._data.crop(tth_min, tth_max)
            self._log(
                tr("wizard.execute_page.log_cropped",
                    count=len(data_to_refine),
                    tth_min=f"{tth_min:.2f}",
                    tth_max=f"{tth_max:.2f}",
                )
            )

        # 精修是主线程同步长任务。不弹提示时用户会以为程序卡死而反复点击, 那些点击
        # 并不会消失, 而是积压在消息队列里, 等本轮结束、按钮刚被重新启用的瞬间被
        # 一次性投递 → 又叠起一轮精修 → "程序未响应" 乃至崩溃。闸门一直持到积压
        # 输入被排空为止 (排空逻辑见 BusyIndicator._drain_then_hide)。
        error_text: Optional[str] = None
        with busy(self, tr("busy.refine")) as acquired:
            if not acquired:  # 已有长任务在跑 → 忽略这次重复触发
                self._log(tr("busy.repeat_ignored"))
                return
            try:
                self._log(
                    tr("wizard.execute_page.log_engine", engine=config["engine"])
                )
                self._log(
                    tr("wizard.execute_page.log_strategy", strategy=config["strategy"])
                )

                self.refinement_progress.emit(10)
                self._progress_bar.setValue(10)
                BusyIndicator.pump()

                refine_kwargs = dict(config.get("params", {}))
                # 让多起点/抛光循环把轮次回吐给忙碌窗, 用户能看到"在动"
                refine_kwargs["progress_cb"] = BusyIndicator.progress_tick
                # v0.12.0: 引擎把过程数据逐行回吐到本页日志 (跑码式输出)
                refine_kwargs.setdefault("log_cb", self._log)

                # v0.12: 精修前置 —— 给已选物相自动匹配 CIF 基础结构。
                # 与主精修页 (main_vm.refine_structure) 同一解析器, 未命中
                # 的相原样保留 (回退剖面拟合), 不阻断精修。
                self._selected_phases = self._cif_resolver.resolve(
                    self._selected_phases,
                    wavelength=float(data_to_refine.wavelength),
                    two_theta_range=(
                        float(data_to_refine.two_theta[0]),
                        float(data_to_refine.two_theta[-1]),
                    ),
                    log_cb=self._log,
                )

                result = self._refiner.refine(
                    data_to_refine,
                    self._selected_phases,
                    strategy=config["strategy"],
                    engine=config["engine"],
                    max_cycles=config["max_cycles"],
                    **refine_kwargs,
                )

                self.refinement_progress.emit(90)
                self._progress_bar.setValue(90)
                BusyIndicator.pump()

                self._display_result(result)

                self._progress_bar.setValue(100)
                self._progress_status.setText(tr("wizard.execute_page.status_done"))
                self._log(tr("wizard.execute_page.log_done"))

                self.refinement_finished.emit(result)
                self.wizard_completed.emit(result)

            except Exception as e:
                self._progress_status.setText(tr("wizard.execute_page.status_failed"))
                self._log(tr("wizard.execute_page.log_failed", error=str(e)))
                # 弹窗推迟到闸门撤掉之后: 忙碌窗是置顶应用级模态, 此刻弹会被它盖住
                error_text = str(e)
            finally:
                self._btn_start_refine.setEnabled(True)

        if error_text is not None:
            QMessageBox.critical(
                self,
                tr("dialog.error"),
                tr("error.refine_failed", error=error_text),
            )

    def _display_result(self, result: RefinementResult) -> None:
        self._label_wr.setText(f"{result.Rwp:.3f} %")
        self._label_rexp.setText(f"{getattr(result, 'Rexp', 0.0):.3f} %")
        self._label_rb.setText(f"{getattr(result, 'Rb', 0.0):.3f} %")
        self._label_gof.setText(f"{result.GOF:.3f}")
        self._label_quality.setText(result.quality_grade)
        self._label_cycles_done.setText(str(result.num_cycles))
        self._label_time.setText(f"{result.time_seconds:.1f} s")

        self._log(tr("wizard.execute_page.log_result_wr", wr=f"{result.wR:.3f}"))
        self._log(tr("wizard.execute_page.log_result_gof", gof=f"{result.GOF:.3f}"))
        self._log(tr("wizard.execute_page.log_result_cycles", cycles=result.num_cycles))
        self._log(
            tr("wizard.execute_page.log_result_quality", quality=result.quality_grade)
        )
        if result.converged:
            self._log(tr("wizard.execute_page.log_converged"))
        else:
            self._log(tr("wizard.execute_page.log_not_converged"))

        for phase in result.phases:
            self._log(
                tr("wizard.execute_page.log_phase",
                    name=phase.name,
                    weight=f"{phase.weight_fraction:.2f}",
                )
            )

    def _log(self, message: str) -> None:
        self._log_text.append(message)

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def get_refinement_config(self) -> dict:
        self._sync_config_from_ui()
        return dict(self._refinement_config)

    def get_selected_phases(self) -> list[Phase]:
        return list(self._selected_phases)

    def set_current_step(self, step: str) -> None:
        if step in self._page_indexes:
            self._stack.setCurrentIndex(self._page_indexes[step])
            self._update_step_display()


# ======================================================================
# 宿主对话框 —— 供主窗口一键弹出分步向导
# ======================================================================

class RefinementWizardHostDialog(QDialog):
    """把 `RefinementWizard` 装进对话框的最小宿主。

    为什么需要它: 向导是 QWidget, 而 `_on_cancel` 会去 `parentWidget().close()`
    —— 它本就预期被装在一个容器里。没有这个宿主, 它就无法从菜单弹出。

    职责边界: 只做"装载 + 播种数据/物相 + 把完成结果转发出去", 不含任何精修
    逻辑 (精修全部由内部向导自己完成)。
    """

    result_ready = Signal(object)   # 精修完成, 携带 RefinementResult

    def __init__(
        self,
        data: Optional[XRDData] = None,
        phases: Optional[list[Phase]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("menu.structure_refinement.wizard_full"))
        # 向导有 5 个步骤页 + 结果表, 给足空间; 用户仍可自由缩放
        self.resize(1000, 740)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._wizard = RefinementWizard(data, phases, self)
        layout.addWidget(self._wizard)

        self._wizard.wizard_completed.connect(self._on_wizard_completed)
        self._wizard.wizard_cancelled.connect(self.reject)

    @property
    def wizard(self) -> RefinementWizard:
        """内部向导本体 (测试/二次开发用)。"""
        return self._wizard

    def _on_wizard_completed(self, result) -> None:
        """精修成功 → 先广播结果, 再关闭对话框。

        顺序很重要: 必须先 emit (主窗口据此登记结果并切到精修页), 再 accept,
        否则主窗口可能在对话框关闭过程中拿到已失效的上下文。
        """
        self.result_ready.emit(result)
        self.accept()
