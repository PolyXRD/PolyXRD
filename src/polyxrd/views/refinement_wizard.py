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
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
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
from polyxrd.services.cod_searcher import CODSearcher, CODEntry
from polyxrd.services.refinement_templates import RefinementTemplateManager
from polyxrd.services.rietveld_refiner import RietveldRefiner


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

        self._selected_phases_table = QTableWidget(0, 4)
        self._selected_phases_table.setHorizontalHeaderLabels(
            [
                tr("wizard.phase_page.col_name"),
                tr("wizard.phase_page.col_formula"),
                tr("wizard.phase_page.col_space_group"),
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
        self._engine_combo.addItems(["gsas2", "powerxrd", "builtin"])
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
                item = QListWidgetItem(f"{name} ({formula})")
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setData(Qt.ItemDataRole.UserRole + 1, mineral)
                self._cif_list.addItem(item)
            except Exception:
                continue

    def _on_add_cif_phase(self) -> None:
        items = self._cif_list.selectedItems()
        for item in items:
            mineral_data = item.data(Qt.ItemDataRole.UserRole + 1)
            if mineral_data:
                phase = self._mineral_to_phase(mineral_data)
                self._add_phase(phase)

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
                mineral_name = entry.mineral_name or entry.formula or "Unknown"
                item = QListWidgetItem(
                    f"{mineral_name} ({entry.formula or 'N/A'}) - COD #{entry.cod_id}"
                )
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self._cod_results_list.addItem(item)
        except Exception:
            self._cod_results_list.clear()
            self._cod_results_list.addItem(
                QListWidgetItem(tr("wizard.phase_page.cod_search_failed"))
            )

    def _on_add_cod_phases(self) -> None:
        items = self._cod_results_list.selectedItems()
        for item in items:
            entry = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, CODEntry):
                phase = self._cod_entry_to_phase(entry)
                self._add_phase(phase)

    def _cod_entry_to_phase(self, entry: CODEntry) -> Phase:
        from polyxrd.models.phase import LatticeParams

        lat = entry.lattice_params or {}
        lattice = LatticeParams(
            a=lat.get("a", 1.0),
            b=lat.get("b", 1.0),
            c=lat.get("c", 1.0),
            alpha=lat.get("alpha", 90.0),
            beta=lat.get("beta", 90.0),
            gamma=lat.get("gamma", 90.0),
        )
        return Phase(
            name=entry.mineral_name or entry.formula or f"COD#{entry.cod_id}",
            formula=entry.formula or "",
            space_group=entry.space_group or "",
            lattice=lattice,
            weight_fraction=0.0,
            cif_path=entry.cif_url,
        )

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
            btn_remove = QPushButton(tr("common.delete"))
            btn_remove.clicked.connect(lambda _, r=row: self._remove_phase(r))
            self._selected_phases_table.setCellWidget(row, 3, btn_remove)

    def _remove_phase(self, row: int) -> None:
        if 0 <= row < len(self._selected_phases):
            del self._selected_phases[row]
            self._refresh_selected_phases_table()

    def _on_clear_phases(self) -> None:
        self._selected_phases.clear()
        self._refresh_selected_phases_table()

    def set_phases(self, phases: list[Phase]) -> None:
        self._selected_phases = list(phases)
        self._refresh_selected_phases_table()

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
            label = f"[内置] {t.name}" if t.is_builtin else f"[用户] {t.name}"
            self._template_combo.addItem(label, t)

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

        try:
            self._log(
                tr("wizard.execute_page.log_engine", engine=config["engine"])
            )
            self._log(
                tr("wizard.execute_page.log_strategy", strategy=config["strategy"])
            )

            self.refinement_progress.emit(10)
            self._progress_bar.setValue(10)

            result = self._refiner.refine(
                data_to_refine,
                self._selected_phases,
                strategy=config["strategy"],
                engine=config["engine"],
                max_cycles=config["max_cycles"],
                **config.get("params", {}),
            )

            self.refinement_progress.emit(90)
            self._progress_bar.setValue(90)

            self._display_result(result)

            self._progress_bar.setValue(100)
            self._progress_status.setText(tr("wizard.execute_page.status_done"))
            self._log(tr("wizard.execute_page.log_done"))

            self.refinement_finished.emit(result)
            self.wizard_completed.emit(result)

        except Exception as e:
            self._progress_status.setText(tr("wizard.execute_page.status_failed"))
            self._log(tr("wizard.execute_page.log_failed", error=str(e)))
            QMessageBox.critical(
                self,
                tr("dialog.error"),
                tr("error.refine_failed", error=str(e)),
            )
        finally:
            self._btn_start_refine.setEnabled(True)

    def _display_result(self, result: RefinementResult) -> None:
        self._label_wr.setText(f"{result.wR:.3f} %")
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