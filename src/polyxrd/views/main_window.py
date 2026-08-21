"""
PolyXRD 主窗口
==============
主应用程序界面。

Features:
- 国际化支持 (i18n)
- 多标签页布局（数据/物相/精修/报告）
- 停靠窗口（参数面板、物相列表）
- 完整菜单系统（文件/数据处理/物相分析/结构精修/视图/报告/帮助）
- 语言切换（中/英双语）
- 精修向导、COD在线搜索、CIF数据库浏览器入口
- QSettings 持久化
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QSettings
from PySide6.QtGui import QAction, QIcon, QKeySequence, QActionGroup
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QTabWidget,
    QDockWidget,
    QToolBar,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QLabel,
    QFormLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QGroupBox,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QDialog,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QMenu,
    QSizePolicy,
)

from polyxrd.config import AppConfig
from polyxrd.i18n import tr, I18nManager, Language
from polyxrd.utils.resources import get_app_icon_path, get_logo_horizontal_path, get_icon_path
from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.data_view import DataView
from polyxrd.views.phase_view import PhaseView
from polyxrd.views.refinement_view import RefinementView
from polyxrd.views.report_view import ReportView
from polyxrd.services import CIFDatabase, CODSearcher


class RefinementWizardDialog(QDialog):
    """精修向导对话框"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.refine_wizard_title"))
        self.setMinimumSize(500, 400)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        info_label = QLabel(tr("dialog.refine_wizard_intro"))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        param_group = QGroupBox(tr("params.refine_params"))
        form = QFormLayout(param_group)

        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["gsas2", "powerxrd", "builtin"])
        form.addRow(tr("params.engine_label"), self._engine_combo)

        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems(["sequential", "auto", "manual"])
        form.addRow(tr("params.strategy_label"), self._strategy_combo)

        self._max_cycles = QSpinBox()
        self._max_cycles.setRange(1, 100)
        self._max_cycles.setValue(20)
        form.addRow(tr("params.max_cycles_label"), self._max_cycles)

        self._wavelength_spin = QDoubleSpinBox()
        self._wavelength_spin.setRange(0.1, 10.0)
        self._wavelength_spin.setDecimals(4)
        self._wavelength_spin.setValue(1.5406)
        self._wavelength_spin.setSuffix(" Å")
        form.addRow(tr("params.wavelength_label"), self._wavelength_spin)

        self._two_theta_min = QDoubleSpinBox()
        self._two_theta_min.setRange(0.0, 180.0)
        self._two_theta_min.setValue(5.0)
        self._two_theta_min.setSuffix("°")
        form.addRow(tr("params.two_theta_min"), self._two_theta_min)

        self._two_theta_max = QDoubleSpinBox()
        self._two_theta_max.setRange(0.0, 180.0)
        self._two_theta_max.setValue(80.0)
        self._two_theta_max.setSuffix("°")
        form.addRow(tr("params.two_theta_max"), self._two_theta_max)

        layout.addWidget(param_group)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("common.ok"))
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_params(self) -> dict:
        return {
            "engine": self._engine_combo.currentText(),
            "strategy": self._strategy_combo.currentText(),
            "max_cycles": self._max_cycles.value(),
            "wavelength": self._wavelength_spin.value(),
            "two_theta_min": self._two_theta_min.value(),
            "two_theta_max": self._two_theta_max.value(),
        }


class CODSearchDialog(QDialog):
    """COD在线搜索对话框"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.cod_search_title"))
        self.setMinimumSize(700, 500)
        self._searcher = CODSearcher()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        search_group = QGroupBox(tr("dialog.cod_search_params"))
        form = QFormLayout(search_group)

        self._formula_edit = QLineEdit()
        self._formula_edit.setPlaceholderText(tr("dialog.cod_formula_placeholder"))
        form.addRow(tr("params.formula"), self._formula_edit)

        self._mineral_edit = QLineEdit()
        self._mineral_edit.setPlaceholderText(tr("dialog.cod_mineral_placeholder"))
        form.addRow(tr("params.mineral_name"), self._mineral_edit)

        self._space_group_edit = QLineEdit()
        self._space_group_edit.setPlaceholderText(tr("dialog.cod_sg_placeholder"))
        form.addRow(tr("params.space_group"), self._space_group_edit)

        btn_row = QHBoxLayout()
        self._search_btn = QPushButton(tr("common.search"))
        self._search_btn.clicked.connect(self._on_search)
        btn_row.addWidget(self._search_btn)

        self._clear_btn = QPushButton(tr("common.cancel"))
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        form.addRow(btn_row)

        layout.addWidget(search_group)

        result_group = QGroupBox(tr("dialog.cod_search_results"))
        result_layout = QVBoxLayout(result_group)

        self._result_table = QTableWidget(0, 5)
        self._result_table.setHorizontalHeaderLabels([
            tr("params.cod_id"),
            tr("params.mineral_name"),
            tr("params.formula"),
            tr("params.space_group"),
            tr("params.cif_url"),
        ])
        self._result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        result_layout.addWidget(self._result_table)

        self._status_label = QLabel("")
        result_layout.addWidget(self._status_label)

        layout.addWidget(result_group, stretch=1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        button_box.button(QDialogButtonBox.StandardButton.Close).setText(tr("common.close"))
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.reject)
        layout.addWidget(button_box)

    def _on_search(self) -> None:
        formula = self._formula_edit.text().strip() or None
        mineral = self._mineral_edit.text().strip() or None
        space_group = self._space_group_edit.text().strip() or None

        if not any([formula, mineral, space_group]):
            QMessageBox.warning(
                self, tr("dialog.warning"),
                tr("dialog.cod_search_empty")
            )
            return

        self._search_btn.setEnabled(False)
        self._status_label.setText(tr("dialog.cod_searching"))

        try:
            result = self._searcher.search(
                formula=formula,
                mineral_name=mineral,
                space_group=space_group,
            )
            self._populate_results(result)
            self._status_label.setText(
                tr("dialog.cod_search_done", count=result.total_count)
            )
        except Exception as e:
            QMessageBox.critical(
                self, tr("dialog.error"),
                tr("dialog.cod_search_failed", error=str(e))
            )
            self._status_label.setText("")
        finally:
            self._search_btn.setEnabled(True)

    def _populate_results(self, result) -> None:
        self._result_table.setRowCount(0)
        for entry in result.entries:
            row = self._result_table.rowCount()
            self._result_table.insertRow(row)
            self._result_table.setItem(row, 0, QTableWidgetItem(str(entry.cod_id)))
            self._result_table.setItem(row, 1, QTableWidgetItem(entry.mineral_name))
            self._result_table.setItem(row, 2, QTableWidgetItem(entry.formula))
            self._result_table.setItem(row, 3, QTableWidgetItem(entry.space_group))
            self._result_table.setItem(row, 4, QTableWidgetItem(entry.cif_url))

    def _on_clear(self) -> None:
        self._formula_edit.clear()
        self._mineral_edit.clear()
        self._space_group_edit.clear()
        self._result_table.setRowCount(0)
        self._status_label.setText("")


class CIFBrowserDialog(QDialog):
    """CIF数据库浏览器对话框"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.cif_browser_title"))
        self.setMinimumSize(800, 600)
        self._cif_db = CIFDatabase()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(tr("common.search") + ":"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(tr("dialog.cif_search_placeholder"))
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        search_row.addWidget(self._search_edit, stretch=1)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._phase_tree = QTreeWidget()
        self._phase_tree.setHeaderLabels([
            tr("params.mineral_name"),
            tr("params.formula"),
            tr("params.space_group"),
        ])
        self._phase_tree.itemClicked.connect(self._on_phase_clicked)
        left_layout.addWidget(self._phase_tree)

        splitter.addWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        detail_group = QGroupBox(tr("dialog.cif_detail"))
        detail_layout = QFormLayout(detail_group)
        self._info_labels: dict[str, QLabel] = {}
        for key, label_text in [
            ("name", tr("params.mineral_name")),
            ("formula", tr("params.formula")),
            ("space_group", tr("params.space_group")),
            ("a", "a (Å)"),
            ("b", "b (Å)"),
            ("c", "c (Å)"),
            ("alpha", "α (°)"),
            ("beta", "β (°)"),
            ("gamma", "γ (°)"),
        ]:
            lbl = QLabel("--")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail_layout.addRow(label_text + ":", lbl)
            self._info_labels[key] = lbl

        right_layout.addWidget(detail_group)

        btn_row = QHBoxLayout()
        self._export_btn = QPushButton(tr("common.export"))
        self._export_btn.clicked.connect(self._on_export_cif)
        btn_row.addWidget(self._export_btn)

        self._import_btn = QPushButton(tr("common.load"))
        self._import_btn.clicked.connect(self._on_import_cif)
        btn_row.addWidget(self._import_btn)

        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        right_layout.addStretch()
        splitter.addWidget(right_widget)

        splitter.setSizes([400, 400])
        layout.addWidget(splitter, stretch=1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        button_box.button(QDialogButtonBox.StandardButton.Close).setText(tr("common.close"))
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.reject)
        layout.addWidget(button_box)

        self._current_key: Optional[str] = None
        self._populate_phases()

    def _populate_phases(self, filter_text: str = "") -> None:
        self._phase_tree.clear()
        phases = self._cif_db.get_phase_list()
        filter_lower = filter_text.lower().strip()

        for p in phases:
            if filter_lower:
                if (filter_lower not in p.get("name", "").lower()
                    and filter_lower not in p.get("formula", "").lower()
                    and filter_lower not in p.get("space_group", "").lower()):
                    continue

            item = QTreeWidgetItem([
                p.get("name", ""),
                p.get("formula", ""),
                p.get("space_group", ""),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, p.get("key", ""))
            self._phase_tree.addTopLevelItem(item)

    def _on_search_text_changed(self, text: str) -> None:
        self._populate_phases(text)

    def _on_phase_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return

        self._current_key = key
        info = self._cif_db.get_mineral_info(key)
        if info:
            self._info_labels["name"].setText(info.get("name", "--"))
            self._info_labels["formula"].setText(info.get("formula", "--"))
            self._info_labels["space_group"].setText(info.get("space_group", "--"))
            lattice = info.get("lattice", {})
            self._info_labels["a"].setText(f"{lattice.get('a', '--'):.4f}")
            self._info_labels["b"].setText(f"{lattice.get('b', '--'):.4f}")
            self._info_labels["c"].setText(f"{lattice.get('c', '--'):.4f}")
            self._info_labels["alpha"].setText(f"{lattice.get('alpha', '--'):.2f}")
            self._info_labels["beta"].setText(f"{lattice.get('beta', '--'):.2f}")
            self._info_labels["gamma"].setText(f"{lattice.get('gamma', '--'):.2f}")

    def _on_export_cif(self) -> None:
        if not self._current_key:
            QMessageBox.information(
                self, tr("dialog.info"),
                tr("dialog.cif_select_first")
            )
            return

        export_dir = QFileDialog.getExistingDirectory(
            self, tr("dialog.export_dir_title")
        )
        if export_dir:
            path = self._cif_db.export_cif(self._current_key, export_dir)
            if path:
                QMessageBox.information(
                    self, tr("dialog.info"),
                    tr("dialog.cif_export_done", path=path)
                )
            else:
                QMessageBox.warning(
                    self, tr("dialog.warning"),
                    tr("dialog.cif_export_failed")
                )

    def _on_import_cif(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.open_file_title"),
            str(Path.home()),
            tr("dialog.cif_filter"),
        )
        if file_path:
            try:
                self._cif_db.load_cif_file(file_path)
                self._populate_phases(self._search_edit.text())
                QMessageBox.information(
                    self, tr("dialog.info"),
                    tr("dialog.cif_import_done")
                )
            except Exception as e:
                QMessageBox.critical(
                    self, tr("dialog.error"),
                    tr("dialog.cif_import_failed", error=str(e))
                )


class MainWindow(QMainWindow):
    """PolyXRD 主窗口

    Features:
    - 多标签页布局（数据/物相/精修/报告）
    - 停靠窗口（参数面板、物相列表）
    - 工具栏和菜单栏
    - 状态栏
    - 国际化支持
    - 语言切换
    - QSettings 持久化
    """

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._vm = MainViewModel()
        self._i18n = I18nManager()
        self._settings = QSettings(config.app_org, config.app_name)

        app_icon_path = get_app_icon_path()
        if app_icon_path:
            self.setWindowIcon(QIcon(app_icon_path))

        self._actions: dict[str, QAction] = {}
        self._language_actions: dict[str, QAction] = {}
        self._menus: dict[str, QMenu] = {}

        self._setup_ui()
        self._setup_actions()
        self._setup_connections()
        self._load_settings()

    # ------------------------------------------------------------------
    # UI 初始化
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self._update_window_title()
        self.resize(self._config.window_width, self._config.window_height)

        self._tab_widget = QTabWidget()
        self.setCentralWidget(self._tab_widget)

        self._data_view = DataView(self._vm)
        self._phase_view = PhaseView(self._vm)
        self._refinement_view = RefinementView(self._vm)
        self._report_view = ReportView(self._vm)

        self._tab_widget.addTab(self._data_view, tr("view.data.title"))
        self._tab_widget.addTab(self._phase_view, tr("view.phase.title"))
        self._tab_widget.addTab(self._refinement_view, tr("view.refinement.title"))
        self._tab_widget.addTab(self._report_view, tr("view.report.title"))

        # 连接物相确认信号 - 自动切换到结构精修
        self._phase_view.phase_confirmed.connect(self._on_phase_confirmed)

        self.setStatusBar(QStatusBar())
        self._status_lang_label = QLabel()
        self._status_wl_label = QLabel()
        self.statusBar().addPermanentWidget(self._status_lang_label)
        self.statusBar().addPermanentWidget(self._status_wl_label)
        self.statusBar().showMessage(tr("status.ready"))

        self._setup_toolbar()
        self._setup_docks()
        self._update_status_bar()

    def _setup_toolbar(self) -> None:
        toolbar = QToolBar(tr("toolbar.main"))
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        self._actions["open"] = QAction(tr("toolbar.open"), self)
        self._actions["open"].setShortcut(QKeySequence.Open)
        self._actions["open"].setToolTip(tr("toolbar.open_tip"))
        self._actions["open"].triggered.connect(self._on_open_file)
        self._set_action_icon(self._actions["open"], "open")
        toolbar.addAction(self._actions["open"])

        self._actions["save"] = QAction(tr("toolbar.save"), self)
        self._actions["save"].setShortcut(QKeySequence.Save)
        self._actions["save"].triggered.connect(self._on_save)
        self._set_action_icon(self._actions["save"], "save")
        toolbar.addAction(self._actions["save"])

        toolbar.addSeparator()

        self._actions["bg"] = QAction(tr("toolbar.background"), self)
        self._actions["bg"].triggered.connect(self._on_background_subtract)
        self._set_action_icon(self._actions["bg"], "background")
        toolbar.addAction(self._actions["bg"])

        self._actions["smooth"] = QAction(tr("toolbar.smooth"), self)
        self._actions["smooth"].triggered.connect(self._on_smooth)
        self._set_action_icon(self._actions["smooth"], "smooth")
        toolbar.addAction(self._actions["smooth"])

        self._actions["strip_kalpha2"] = QAction(tr("action.strip_kalpha2"), self)
        self._actions["strip_kalpha2"].triggered.connect(self._on_strip_kalpha2)
        self._set_action_icon(self._actions["strip_kalpha2"], "kalpha2")
        toolbar.addAction(self._actions["strip_kalpha2"])

        toolbar.addSeparator()

        self._actions["find_peaks"] = QAction(tr("toolbar.find_peaks"), self)
        self._actions["find_peaks"].triggered.connect(self._on_find_peaks)
        self._set_action_icon(self._actions["find_peaks"], "find_peaks")
        toolbar.addAction(self._actions["find_peaks"])

        self._actions["identify"] = QAction(tr("toolbar.identify"), self)
        self._actions["identify"].triggered.connect(self._on_identify)
        self._set_action_icon(self._actions["identify"], "identify")
        toolbar.addAction(self._actions["identify"])

        self._actions["profile_fitting"] = QAction(tr("toolbar.profile_fitting"), self)
        self._actions["profile_fitting"].setToolTip(tr("toolbar.profile_fitting_tip"))
        self._actions["profile_fitting"].triggered.connect(self._on_profile_fitting)
        self._set_action_icon(self._actions["profile_fitting"], "profile_fitting")
        toolbar.addAction(self._actions["profile_fitting"])

        toolbar.addSeparator()

        self._actions["refine"] = QAction(tr("toolbar.refine"), self)
        self._actions["refine"].triggered.connect(self._on_refine)
        self._set_action_icon(self._actions["refine"], "refine")
        toolbar.addAction(self._actions["refine"])

        self._actions["refine_wizard"] = QAction(tr("toolbar.refine_wizard"), self)
        self._actions["refine_wizard"].setToolTip(tr("dialog.refine_wizard_title"))
        self._actions["refine_wizard"].triggered.connect(self._on_refine_wizard)
        self._set_action_icon(self._actions["refine_wizard"], "refine_wizard")
        toolbar.addAction(self._actions["refine_wizard"])

        toolbar.addSeparator()

        self._actions["cod_search"] = QAction(tr("toolbar.cod_search"), self)
        self._actions["cod_search"].setToolTip(tr("dialog.cod_search_title"))
        self._actions["cod_search"].triggered.connect(self._on_cod_search)
        self._set_action_icon(self._actions["cod_search"], "cod_search")
        toolbar.addAction(self._actions["cod_search"])

        toolbar.addSeparator()

        self._actions["export"] = QAction(tr("toolbar.export"), self)
        self._actions["export"].triggered.connect(self._on_export)
        self._set_action_icon(self._actions["export"], "export")
        toolbar.addAction(self._actions["export"])

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        spacer.setMinimumWidth(0)
        toolbar.addWidget(spacer)

        # 强制左对齐
        toolbar_layout = toolbar.layout()
        if toolbar_layout:
            toolbar_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

    @staticmethod
    def _set_action_icon(action: QAction, icon_name: str) -> None:
        """为QAction设置图标"""
        icon_path = get_icon_path(icon_name)
        if icon_path:
            action.setIcon(QIcon(icon_path))

    def _setup_docks(self) -> None:
        self._params_dock = QDockWidget(tr("params.panel_title"), self)
        self._params_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        params_widget = QWidget()
        params_layout = QFormLayout(params_widget)
        params_layout.setContentsMargins(8, 8, 8, 8)

        self._wl_spin = QDoubleSpinBox()
        self._wl_spin.setRange(0.1, 10.0)
        self._wl_spin.setDecimals(4)
        self._wl_spin.setValue(self._config.default_wavelength)
        self._wl_spin.setSuffix(" Å")
        self._wl_spin.valueChanged.connect(self._on_wavelength_changed)
        params_layout.addRow(tr("params.wavelength_label"), self._wl_spin)

        self._two_theta_min_spin = QDoubleSpinBox()
        self._two_theta_min_spin.setRange(0.0, 180.0)
        self._two_theta_min_spin.setValue(self._config.default_two_theta_range[0])
        self._two_theta_min_spin.setSuffix("°")
        params_layout.addRow(tr("params.two_theta_min"), self._two_theta_min_spin)

        self._two_theta_max_spin = QDoubleSpinBox()
        self._two_theta_max_spin.setRange(0.0, 180.0)
        self._two_theta_max_spin.setValue(self._config.default_two_theta_range[1])
        self._two_theta_max_spin.setSuffix("°")
        params_layout.addRow(tr("params.two_theta_max"), self._two_theta_max_spin)

        params_layout.addRow(QLabel(""))
        params_layout.addRow(QLabel(tr("params.bg_method")))

        self._bg_method_combo = QComboBox()
        self._bg_method_combo.addItems([
            tr("params.bgm_snip"),
            tr("params.bgm_als"),
            tr("params.bgm_polyfit"),
            tr("params.bgm_median"),
            tr("params.bgm_rolling"),
        ])
        params_layout.addRow(tr("params.bg_method"), self._bg_method_combo)

        self._smooth_method_combo = QComboBox()
        self._smooth_method_combo.addItems([
            tr("params.smt_savgol"),
            tr("params.smt_gaussian"),
            tr("params.smt_moving"),
            tr("params.smt_median"),
        ])
        params_layout.addRow(tr("params.smooth_method"), self._smooth_method_combo)

        self._smooth_window_spin = QSpinBox()
        self._smooth_window_spin.setRange(3, 101)
        self._smooth_window_spin.setValue(self._config.default_smooth_window)
        self._smooth_window_spin.setSingleStep(2)
        params_layout.addRow(tr("params.smooth_window"), self._smooth_window_spin)

        params_layout.addRow(QLabel(""))
        params_layout.addRow(QLabel(tr("params.peak_detect")))

        self._peak_height_spin = QDoubleSpinBox()
        self._peak_height_spin.setRange(0.0, 100.0)
        self._peak_height_spin.setValue(self._config.default_peak_height * 100)
        self._peak_height_spin.setSuffix(" %")
        params_layout.addRow(tr("params.peak_height"), self._peak_height_spin)

        self._peak_distance_spin = QDoubleSpinBox()
        self._peak_distance_spin.setRange(0.0, 100.0)
        self._peak_distance_spin.setValue(self._config.default_peak_distance)
        params_layout.addRow(tr("params.peak_distance"), self._peak_distance_spin)

        self._params_dock.setWidget(params_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._params_dock)

        self._phases_dock = QDockWidget(tr("params.phases_title"), self)
        self._phases_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        phases_widget = QWidget()
        phases_layout = QVBoxLayout(phases_widget)
        phases_layout.setContentsMargins(0, 0, 0, 0)

        self._phase_tree = QTreeWidget()
        self._phase_tree.setHeaderLabels([
            tr("params.mineral_name"),
            tr("params.formula"),
            tr("params.space_group"),
            tr("params.match_score"),
        ])
        self._phase_tree.setAlternatingRowColors(True)
        self._phase_tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection
        )
        phases_layout.addWidget(self._phase_tree)

        btn_row = QHBoxLayout()
        self._btn_select_all = QPushButton(tr("common.select_all"))
        self._btn_select_all.clicked.connect(self._on_select_all_phases)
        btn_row.addWidget(self._btn_select_all)

        self._btn_clear_phases = QPushButton(tr("common.clear"))
        self._btn_clear_phases.clicked.connect(self._on_clear_phases)
        btn_row.addWidget(self._btn_clear_phases)

        phases_layout.addLayout(btn_row)

        self._phases_dock.setWidget(phases_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._phases_dock)

    def _setup_actions(self) -> None:
        self._setup_file_menu()
        self._setup_process_menu()
        self._setup_phase_menu()
        self._setup_refine_menu()
        self._setup_view_menu()
        self._setup_report_menu()
        self._setup_help_menu()

    def _setup_file_menu(self) -> None:
        file_menu = self.menuBar().addMenu(tr("menu.file.title"))
        self._menus["file"] = file_menu
        file_menu.addAction(self._actions["open"])
        file_menu.addAction(self._actions["save"])

        self._actions["save_as"] = QAction(tr("menu.file.save_as"), self)
        self._actions["save_as"].triggered.connect(self._on_save_as)
        self._set_action_icon(self._actions["save_as"], "save")
        file_menu.addAction(self._actions["save_as"])

        self._actions["export_file"] = QAction(tr("menu.report.export"), self)
        self._actions["export_file"].triggered.connect(self._on_export)
        self._set_action_icon(self._actions["export_file"], "export")
        file_menu.addAction(self._actions["export_file"])

        file_menu.addSeparator()

        self._recent_menu = file_menu.addMenu(tr("menu.file.recent_files"))
        self._update_recent_files_menu()

        file_menu.addSeparator()

        self._actions["exit"] = QAction(tr("menu.file.exit"), self)
        self._actions["exit"].setShortcut(QKeySequence.Quit)
        self._actions["exit"].triggered.connect(self.close)
        self._set_action_icon(self._actions["exit"], "exit")
        file_menu.addAction(self._actions["exit"])

    def _setup_process_menu(self) -> None:
        process_menu = self.menuBar().addMenu(tr("menu.data_processing.title"))
        self._menus["process"] = process_menu
        process_menu.addAction(self._actions["bg"])
        process_menu.addAction(self._actions["smooth"])

        self._actions["kalpha2"] = QAction(tr("menu.data_processing.kalpha2"), self)
        self._actions["kalpha2"].triggered.connect(self._on_strip_kalpha2)
        self._set_action_icon(self._actions["kalpha2"], "kalpha2")
        process_menu.addAction(self._actions["kalpha2"])

        self._actions["normalize"] = QAction(tr("menu.data_processing.normalize"), self)
        self._actions["normalize"].triggered.connect(self._on_normalize)
        self._set_action_icon(self._actions["normalize"], "smooth")
        process_menu.addAction(self._actions["normalize"])

    def _setup_phase_menu(self) -> None:
        phase_menu = self.menuBar().addMenu(tr("menu.phase_analysis.title"))
        self._menus["phase"] = phase_menu
        phase_menu.addAction(self._actions["find_peaks"])
        phase_menu.addAction(self._actions["identify"])

        self._actions["profile_fitting_menu"] = QAction(tr("menu.phase_analysis.profile_fitting"), self)
        self._actions["profile_fitting_menu"].triggered.connect(self._on_profile_fitting)
        self._set_action_icon(self._actions["profile_fitting_menu"], "profile_fitting")
        phase_menu.addAction(self._actions["profile_fitting_menu"])

        phase_menu.addSeparator()

        self._actions["cif_browser"] = QAction(tr("menu.phase_analysis.cif_browser"), self)
        self._actions["cif_browser"].triggered.connect(self._on_cif_browser)
        self._set_action_icon(self._actions["cif_browser"], "target")
        phase_menu.addAction(self._actions["cif_browser"])

        self._actions["cod_search_menu"] = QAction(tr("menu.phase_analysis.cod_search"), self)
        self._actions["cod_search_menu"].triggered.connect(self._on_cod_search)
        self._set_action_icon(self._actions["cod_search_menu"], "cod_search")
        phase_menu.addAction(self._actions["cod_search_menu"])

        phase_menu.addSeparator()

        self._actions["import_cod_db"] = QAction(
            tr("menu.phase_analysis.import_cod_db"), self
        )
        self._actions["import_cod_db"].setToolTip(
            tr("menu.phase_analysis.import_cod_db_tip")
        )
        self._actions["import_cod_db"].triggered.connect(self._on_import_cod_db)
        self._set_action_icon(self._actions["import_cod_db"], "target")
        phase_menu.addAction(self._actions["import_cod_db"])

        self._actions["cod_db_status"] = QAction(
            tr("menu.phase_analysis.cod_db_status"), self
        )
        self._actions["cod_db_status"].triggered.connect(self._on_cod_db_status)
        self._set_action_icon(self._actions["cod_db_status"], "view")
        phase_menu.addAction(self._actions["cod_db_status"])

    def _setup_refine_menu(self) -> None:
        refine_menu = self.menuBar().addMenu(tr("menu.structure_refinement.title"))
        self._menus["refine"] = refine_menu
        refine_menu.addAction(self._actions["refine"])

        self._actions["refine_wizard_menu"] = QAction(tr("menu.structure_refinement.wizard"), self)
        self._actions["refine_wizard_menu"].triggered.connect(self._on_refine_wizard)
        self._set_action_icon(self._actions["refine_wizard_menu"], "refine_wizard")
        refine_menu.addAction(self._actions["refine_wizard_menu"])

        self._actions["quick_refine"] = QAction(tr("menu.structure_refinement.quick_refine"), self)
        self._actions["quick_refine"].triggered.connect(self._on_quick_refine)
        self._set_action_icon(self._actions["quick_refine"], "refine")
        refine_menu.addAction(self._actions["quick_refine"])

        self._actions["template_mgmt"] = QAction(tr("menu.structure_refinement.templates"), self)
        self._actions["template_mgmt"].triggered.connect(self._on_template_management)
        self._set_action_icon(self._actions["template_mgmt"], "target")
        refine_menu.addAction(self._actions["template_mgmt"])

    def _setup_view_menu(self) -> None:
        view_menu = self.menuBar().addMenu(tr("menu.view.title"))
        self._menus["view"] = view_menu

        self._language_menu = view_menu.addMenu(tr("menu.view.language"))
        self._menus["language"] = self._language_menu

        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)

        for lang in Language:
            display = Language.display_names().get(lang, lang.value)
            action = QAction(display, self)
            action.setCheckable(True)
            action.setData(lang.value)
            action.triggered.connect(self._on_language_toggle)
            self._language_group.addAction(action)
            self._language_menu.addAction(action)
            self._language_actions[lang.value] = action

        current = self._i18n.current_language
        if current in self._language_actions:
            self._language_actions[current].setChecked(True)

        view_menu.addSeparator()

        self._actions["reset_layout"] = QAction(tr("menu.view.reset_layout"), self)
        self._actions["reset_layout"].triggered.connect(self._on_reset_layout)
        self._set_action_icon(self._actions["reset_layout"], "reset")
        view_menu.addAction(self._actions["reset_layout"])

        view_menu.addSeparator()

        self._actions["toggle_params"] = QAction(tr("params.panel_title"), self)
        self._actions["toggle_params"].setCheckable(True)
        self._actions["toggle_params"].setChecked(True)
        self._actions["toggle_params"].triggered.connect(self._params_dock.setVisible)
        self._params_dock.visibilityChanged.connect(
            self._actions["toggle_params"].setChecked
        )
        self._set_action_icon(self._actions["toggle_params"], "view")
        view_menu.addAction(self._actions["toggle_params"])

        self._actions["toggle_phases"] = QAction(tr("params.phases_title"), self)
        self._actions["toggle_phases"].setCheckable(True)
        self._actions["toggle_phases"].setChecked(True)
        self._actions["toggle_phases"].triggered.connect(self._phases_dock.setVisible)
        self._phases_dock.visibilityChanged.connect(
            self._actions["toggle_phases"].setChecked
        )
        self._set_action_icon(self._actions["toggle_phases"], "phase")
        view_menu.addAction(self._actions["toggle_phases"])

    def _setup_report_menu(self) -> None:
        report_menu = self.menuBar().addMenu(tr("menu.report.title"))
        self._menus["report"] = report_menu

        self._actions["generate_report"] = QAction(tr("menu.report.generate"), self)
        self._actions["generate_report"].triggered.connect(self._on_generate_report)
        self._set_action_icon(self._actions["generate_report"], "report")
        report_menu.addAction(self._actions["generate_report"])

        self._actions["export_report"] = QAction(tr("menu.report.export"), self)
        self._actions["export_report"].triggered.connect(self._on_export_report)
        self._set_action_icon(self._actions["export_report"], "export")
        report_menu.addAction(self._actions["export_report"])

    def _setup_help_menu(self) -> None:
        help_menu = self.menuBar().addMenu(tr("menu.help.title"))
        self._menus["help"] = help_menu

        self._actions["about"] = QAction(tr("menu.help.about"), self)
        self._actions["about"].triggered.connect(self._on_about)
        self._set_action_icon(self._actions["about"], "about")
        help_menu.addAction(self._actions["about"])

        self._actions["about_qt"] = QAction(tr("menu.help.about_qt"), self)
        self._actions["about_qt"].triggered.connect(self._on_about_qt)
        help_menu.addAction(self._actions["about_qt"])

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------

    def _setup_connections(self) -> None:
        self._vm.status_changed.connect(self._on_status_changed)
        self._vm.error_occurred.connect(self._on_error)
        self._vm.data_changed.connect(self._on_data_changed)
        self._vm.peaks_changed.connect(self._on_peaks_changed)
        self._vm.phase_identified.connect(self._on_phases_updated)
        self._vm.refinement_completed.connect(self._on_refinement_completed)

        self._i18n.languageChanged.connect(self._on_language_changed)

    # ------------------------------------------------------------------
    # 语言切换
    # ------------------------------------------------------------------

    def _on_language_toggle(self) -> None:
        action = self.sender()
        if isinstance(action, QAction) and action.isChecked():
            lang = action.data()
            if lang:
                self._i18n.set_language(lang)

    def _on_language_changed(self, language: str) -> None:
        self._retranslate_ui()
        self._save_settings()

    def _retranslate_ui(self) -> None:
        self._update_window_title()

        self._tab_widget.setTabText(0, tr("view.data.title"))
        self._tab_widget.setTabText(1, tr("view.phase.title"))
        self._tab_widget.setTabText(2, tr("view.refinement.title"))
        self._tab_widget.setTabText(3, tr("view.report.title"))

        self._params_dock.setWindowTitle(tr("params.panel_title"))
        self._phases_dock.setWindowTitle(tr("params.phases_title"))

        self._phase_tree.setHeaderLabels([
            tr("params.mineral_name"),
            tr("params.formula"),
            tr("params.space_group"),
            tr("params.match_score"),
        ])

        self._update_status_bar()
        self._update_recent_files_menu()

        self._retranslate_menus()
        self._retranslate_actions()

    def _retranslate_menus(self) -> None:
        menu_translations = {
            "file": "menu.file.title",
            "process": "menu.data_processing.title",
            "phase": "menu.phase_analysis.title",
            "refine": "menu.structure_refinement.title",
            "view": "menu.view.title",
            "report": "menu.report.title",
            "help": "menu.help.title",
        }
        for key, tr_key in menu_translations.items():
            if key in self._menus:
                self._menus[key].setTitle(tr(tr_key))

        if "language" in self._menus:
            self._menus["language"].setTitle(tr("menu.view.language"))

        if hasattr(self, "_recent_menu"):
            self._recent_menu.setTitle(tr("menu.file.recent_files"))

    def _retranslate_actions(self) -> None:
        action_translations = {
            "open": "toolbar.open",
            "save": "toolbar.save",
            "save_as": "menu.file.save_as",
            "export_file": "menu.report.export",
            "exit": "menu.file.exit",
            "bg": "toolbar.background",
            "smooth": "toolbar.smooth",
            "kalpha2": "menu.data_processing.kalpha2",
            "normalize": "menu.data_processing.normalize",
            "find_peaks": "toolbar.find_peaks",
            "identify": "toolbar.identify",
            "profile_fitting": "toolbar.profile_fitting",
            "profile_fitting_menu": "menu.phase_analysis.profile_fitting",
            "cif_browser": "menu.phase_analysis.cif_browser",
            "cod_search_menu": "menu.phase_analysis.cod_search",
            "import_cod_db": "menu.phase_analysis.import_cod_db",
            "cod_db_status": "menu.phase_analysis.cod_db_status",
            "refine": "toolbar.refine",
            "refine_wizard": "toolbar.refine_wizard",
            "refine_wizard_menu": "menu.structure_refinement.wizard",
            "quick_refine": "menu.structure_refinement.quick_refine",
            "template_mgmt": "menu.structure_refinement.templates",
            "reset_layout": "menu.view.reset_layout",
            "toggle_params": "params.panel_title",
            "toggle_phases": "params.phases_title",
            "generate_report": "menu.report.generate",
            "export_report": "menu.report.export",
            "about": "menu.help.about",
            "about_qt": "menu.help.about_qt",
            "cod_search": "toolbar.cod_search",
            "strip_kalpha2": "action.strip_kalpha2",
        }
        for key, tr_key in action_translations.items():
            if key in self._actions:
                self._actions[key].setText(tr(tr_key))

        if hasattr(self, "_toggle_params") and hasattr(self, "_actions"):
            pass

        self.statusBar().showMessage(tr("status.ready"))

    # ------------------------------------------------------------------
    # 状态栏
    # ------------------------------------------------------------------

    def _update_status_bar(self) -> None:
        lang_display = Language.display_names().get(
            self._i18n.current_language, self._i18n.current_language
        )
        self._status_lang_label.setText(
            tr("status.language_info", lang=lang_display)
        )
        self._status_wl_label.setText(
            tr("status.wavelength_info", wl=self._wl_spin.value())
        )

    def _update_window_title(self) -> None:
        self.setWindowTitle(
            tr("app.title", version=self._config.app_version)
        )

    def _on_wavelength_changed(self, value: float) -> None:
        self._update_status_bar()

    # ------------------------------------------------------------------
    # 事件处理 - 文件
    # ------------------------------------------------------------------

    def _on_open_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.open_file_title"),
            str(Path.home()),
            tr("dialog.file_filter"),
        )
        if file_path:
            self._vm.load_file(file_path)
            self._add_recent_file(file_path)

    def _on_save(self) -> None:
        QMessageBox.information(
            self,
            tr("dialog.info"),
            tr("dialog.save_not_implemented"),
        )

    def _on_save_as(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("dialog.save_as_title"),
            str(Path.home()),
            tr("dialog.file_filter"),
        )
        if file_path:
            QMessageBox.information(
                self,
                tr("dialog.info"),
                tr("dialog.save_not_implemented"),
            )

    def _on_export(self) -> None:
        export_dir = QFileDialog.getExistingDirectory(
            self, tr("dialog.export_dir_title")
        )
        if export_dir:
            self._vm.export_result(export_dir, format="all")
            self.statusBar().showMessage(tr("status.export_done"), 3000)

    # ------------------------------------------------------------------
    # 事件处理 - 数据处理
    # ------------------------------------------------------------------

    def _on_background_subtract(self) -> None:
        self._vm.subtract_background(
            method=self._bg_method_combo.currentText()
        )

    def _on_smooth(self) -> None:
        self._vm.smooth_data(
            method=self._smooth_method_combo.currentText(),
            window=self._smooth_window_spin.value(),
        )

    def _on_strip_kalpha2(self) -> None:
        self._vm.status_changed.emit(tr("status.kalpha2_strip"))

    def _on_normalize(self) -> None:
        self._vm.normalize_data()

    # ------------------------------------------------------------------
    # 事件处理 - 物相分析
    # ------------------------------------------------------------------

    def _on_find_peaks(self) -> None:
        self._vm.find_peaks(
            height=self._peak_height_spin.value() / 100.0,
            distance=self._peak_distance_spin.value(),
        )

    def _on_identify(self) -> None:
        self._tab_widget.setCurrentWidget(self._phase_view)
        self._vm.identify_phases()

    def _on_profile_fitting(self) -> None:
        self._tab_widget.setCurrentWidget(self._phase_view)
        self._vm.identify_phases_profile_fitting()

    def _on_cif_browser(self) -> None:
        dialog = CIFBrowserDialog(self)
        dialog.exec()

    def _on_cod_search(self) -> None:
        dialog = CODSearchDialog(self)
        dialog.exec()

    def _on_import_cod_db(self) -> None:
        """导入外部 COD 无机物数据库 (.sqlite)。

        数据库与 PolyXRD 主程序分离发布:用户通过此入口选择
        下载好的 .sqlite 文件,程序持久化路径到 ~/.polyxrd/,
        下次启动自动加载,无需重新导入。
        """
        # 默认打开用户主目录
        start_dir = str(Path.home())
        # 若已有自定义路径,定位到该目录
        current_path = self._config.get_cod_db_path()
        if current_path.exists():
            start_dir = str(current_path.parent)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.import_cod_db_title"),
            start_dir,
            tr("dialog.sqlite_filter"),
        )
        if not file_path:
            return

        try:
            db = CIFDatabase()
            ok = db.set_cod_db_path(file_path)
            if not ok:
                QMessageBox.critical(
                    self,
                    tr("dialog.error"),
                    tr("dialog.cod_db_import_failed",
                       error="文件不存在或不可读"),
                )
                return
            count = db.cod_phase_count()
            path_display = str(Path(file_path).resolve())
            QMessageBox.information(
                self,
                tr("dialog.info"),
                tr("dialog.cod_db_import_done",
                   count=count, path=path_display),
            )
            self.statusBar().showMessage(
                tr("status.database_ready", count=count), 5000
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("dialog.error"),
                tr("dialog.cod_db_import_failed", error=str(e)),
            )

    def _on_cod_db_status(self) -> None:
        """显示当前 COD 数据库的路径和物相数。"""
        db = CIFDatabase()
        path = self._config.get_cod_db_path()
        if not path.exists():
            QMessageBox.information(
                self,
                tr("dialog.info"),
                tr("dialog.cod_db_not_loaded"),
            )
            return
        count = db.cod_phase_count()
        user_path = self._config._load_user_cod_db_path()
        source = tr("dialog.cod_db_source_user") if user_path \
            else tr("dialog.cod_db_source_builtin")
        QMessageBox.information(
            self,
            tr("dialog.info"),
            tr("dialog.cod_db_status_info",
               path=str(path), count=count, source=source),
        )

    def _on_phase_confirmed(self, phase) -> None:
        """物相确认后自动切换到结构精修"""
        self._tab_widget.setCurrentWidget(self._refinement_view)
        # 传递物相到精修视图
        if hasattr(self._refinement_view, 'set_phase'):
            self._refinement_view.set_phase(phase)
        self.statusBar().showMessage(
            f"已确认物相: {phase.name}，切换到结构精修", 5000
        )

    # ------------------------------------------------------------------
    # 事件处理 - 结构精修
    # ------------------------------------------------------------------

    def _on_refine(self) -> None:
        self._tab_widget.setCurrentWidget(self._refinement_view)
        self._vm.refine_structure()

    def _on_refine_wizard(self) -> None:
        dialog = RefinementWizardDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            params = dialog.get_params()
            self._tab_widget.setCurrentWidget(self._refinement_view)
            self._vm.refine_structure(
                strategy=params["strategy"],
                max_cycles=params["max_cycles"],
            )

    def _on_quick_refine(self) -> None:
        data = self._vm.current_data
        if data is None:
            QMessageBox.warning(
                self, tr("dialog.warning"), tr("error.no_data")
            )
            return

        phases = self._vm.selected_phases
        if not phases:
            self._tab_widget.setCurrentWidget(self._phase_view)
            QMessageBox.information(
                self,
                tr("dialog.info"),
                tr("dialog.quick_refine_no_phases"),
            )
            return

        self._tab_widget.setCurrentWidget(self._refinement_view)
        self._vm.refine_structure(
            strategy="sequential",
            max_cycles=10,
        )

    def _on_template_management(self) -> None:
        QMessageBox.information(
            self,
            tr("dialog.template_mgmt_title"),
            tr("dialog.template_mgmt_info"),
        )

    # ------------------------------------------------------------------
    # 事件处理 - 视图
    # ------------------------------------------------------------------

    def _on_reset_layout(self) -> None:
        self._params_dock.setFloating(False)
        self._phases_dock.setFloating(False)
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self._params_dock
        )
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._phases_dock
        )
        self._params_dock.show()
        self._phases_dock.show()
        self.statusBar().showMessage(tr("status.layout_reset"), 3000)

    # ------------------------------------------------------------------
    # 事件处理 - 报告
    # ------------------------------------------------------------------

    def _on_generate_report(self) -> None:
        self._tab_widget.setCurrentWidget(self._report_view)
        if hasattr(self._report_view, "_on_preview"):
            self._report_view._on_preview()

    def _on_export_report(self) -> None:
        result = self._vm.refinement_result
        if result is None:
            QMessageBox.warning(
                self, tr("dialog.warning"), tr("error.no_refinement")
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("dialog.save_as_title"),
            str(Path.home() / "polyxrd_report.json"),
            tr("dialog.json_filter"),
        )
        if file_path:
            try:
                import json
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
                self.statusBar().showMessage(
                    tr("status.export_done"), 3000
                )
            except Exception as e:
                QMessageBox.critical(
                    self, tr("dialog.error"),
                    tr("error.export_failed", error=str(e)),
                )

    # ------------------------------------------------------------------
    # 事件处理 - 帮助
    # ------------------------------------------------------------------

    def _on_about(self) -> None:
        logo_path = get_logo_horizontal_path()
        about_html = tr("dialog.about_text", version=self._config.app_version)
        if logo_path:
            about_html = (
                f"<div style='text-align:center; margin-bottom:12px;'>"
                f"<img src='{logo_path}' style='max-width:300px;'/></div>"
                f"{about_html}"
            )
        QMessageBox.about(
            self,
            tr("dialog.about_title"),
            about_html,
        )

    def _on_about_qt(self) -> None:
        QMessageBox.aboutQt(self, tr("menu.help.about_qt"))

    # ------------------------------------------------------------------
    # 物相列表操作
    # ------------------------------------------------------------------

    def _on_select_all_phases(self) -> None:
        self._phase_tree.selectAll()

    def _on_clear_phases(self) -> None:
        self._phase_tree.clearSelection()

    # ------------------------------------------------------------------
    # ViewModel 事件响应
    # ------------------------------------------------------------------

    def _on_status_changed(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, tr("dialog.error"), message)

    def _on_data_changed(self, data) -> None:
        """数据变更 - 更新所有视图"""
        self._data_view._on_data_changed(data)
        self._phase_view._plot.clear_plot()
        if data:
            self._phase_view._plot.plot_data(data, label="实验数据")

    def _on_peaks_changed(self, peaks) -> None:
        """峰变更 - 更新峰列表和图标注"""
        self._data_view._on_peaks_changed(peaks)

    def _on_phases_updated(self, phase_results: list) -> None:
        """物相列表更新 - PhaseMatchResult 列表"""
        self._phase_tree.clear()
        for result in phase_results:
            phase = result.phase if hasattr(result, 'phase') else result
            score = result.score if hasattr(result, 'score') else getattr(result, 'match_score', 0.0)

            item = QTreeWidgetItem([
                phase.name,
                phase.formula,
                phase.space_group,
                f"{score:.1f}%",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, phase)
            self._phase_tree.addTopLevelItem(item)

    def _on_refinement_completed(self, result) -> None:
        self._tab_widget.setCurrentWidget(self._report_view)
        if hasattr(self._report_view, '_on_refinement_completed'):
            self._report_view._on_refinement_completed(result)

    # ------------------------------------------------------------------
    # 最近文件
    # ------------------------------------------------------------------

    def _update_recent_files_menu(self) -> None:
        self._recent_menu.clear()
        recent = self._get_recent_files()
        if not recent:
            action = QAction(tr("menu.file.no_recent"), self)
            action.setEnabled(False)
            self._recent_menu.addAction(action)
            return

        for file_path in recent:
            action = QAction(Path(file_path).name, self)
            action.setData(file_path)
            action.triggered.connect(self._on_open_recent_file)
            self._recent_menu.addAction(action)

        self._recent_menu.addSeparator()
        clear_action = QAction(tr("menu.file.clear_recent"), self)
        clear_action.triggered.connect(self._on_clear_recent_files)
        self._recent_menu.addAction(clear_action)

    def _on_open_recent_file(self) -> None:
        action = self.sender()
        if isinstance(action, QAction):
            file_path = action.data()
            if file_path and Path(file_path).exists():
                self._vm.load_file(file_path)
                self._add_recent_file(file_path)
            else:
                QMessageBox.warning(
                    self, tr("dialog.warning"),
                    tr("error.file_not_found", path=file_path),
                )

    def _on_clear_recent_files(self) -> None:
        self._settings.beginGroup("recent_files")
        self._settings.clear()
        self._settings.endGroup()
        self._update_recent_files_menu()

    def _get_recent_files(self) -> list[str]:
        self._settings.beginGroup("recent_files")
        size = self._settings.beginReadArray("files")
        files = []
        for i in range(size):
            self._settings.setArrayIndex(i)
            path = self._settings.value("path", "")
            if path:
                files.append(path)
        self._settings.endArray()
        self._settings.endGroup()
        return files

    def _add_recent_file(self, file_path: str) -> None:
        files = self._get_recent_files()
        file_path = str(file_path)
        if file_path in files:
            files.remove(file_path)
        files.insert(0, file_path)
        files = files[:10]

        self._settings.beginGroup("recent_files")
        self._settings.beginWriteArray("files")
        for i, path in enumerate(files):
            self._settings.setArrayIndex(i)
            self._settings.setValue("path", path)
        self._settings.endArray()
        self._settings.endGroup()
        self._update_recent_files_menu()

    # ------------------------------------------------------------------
    # 设置持久化
    # ------------------------------------------------------------------

    def _load_settings(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        state = self._settings.value("windowState")
        if state:
            self.restoreState(state)

        language = self._settings.value("language", Language.ZH_CN)
        if language and language != self._i18n.current_language:
            self._i18n.set_language(language)

        wavelength = self._settings.value("wavelength", self._config.default_wavelength)
        self._wl_spin.setValue(float(wavelength))

    def _save_settings(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())
        self._settings.setValue("language", self._i18n.current_language)
        self._settings.setValue("wavelength", self._wl_spin.value())

    def closeEvent(self, event) -> None:
        self._save_settings()
        super().closeEvent(event)