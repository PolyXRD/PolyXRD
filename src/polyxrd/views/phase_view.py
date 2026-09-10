"""
物相分析视图
============
物相识别和匹配的界面。
支持两种识别方法:
  1. Search/Match (传统): 需要先寻峰，基于峰位匹配
  2. Profile Fitting (峰形拟合): 无需寻峰，直接匹配曲线形貌
元素周期表使用弹出对话框，不挤占谱图空间。
物相选择后在谱图上显示匹配峰与残差。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QSizePolicy,
    QMessageBox,
    QScrollArea,
    QFrame,
)

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.widgets.pattern_display import PatternDisplayWidget
from polyxrd.views.widgets.peak_match_table import PeakMatchTable
from polyxrd.views.widgets.element_filter_dialog import ElementFilterDialog
from polyxrd.services.peak_finder import PeakFinder
from polyxrd.services.phase_display import (combined_pattern,
                                            assign_peaks, phase_color,
                                            PeakAssignment)


class PhaseView(QWidget):
    """物相分析视图
    
    布局:
      上方: 衍射谱图 (主要区域，不被挤压)
      下方: 物相识别控制面板 (方法选择 + 过滤 + 结果)
    """

    phase_confirmed = Signal(object)

    def __init__(self, vm: MainViewModel) -> None:
        super().__init__()
        self._vm = vm
        self._current_method = "fom"
        self._filter_dict: dict = {}
        self._current_results: list = []
        self._element_dialog: Optional[ElementFilterDialog] = None
        # 数据库源: key 与 PhaseViewModel.identify_phases 的 db_source 对应
        self._db_source_keys = [
            "builtin", "cod_inorganics", "cod_full", "merged", "pdf2",
        ]
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # ====== 上部: 衍射谱图 (Match! 式双区: 主谱 + 参考棒) ======
        self._plot = PatternDisplayWidget()
        self._plot.setMinimumHeight(350)
        main_layout.addWidget(self._plot, stretch=3)

        # ====== 下部: 控制面板 (可滚动) ======
        control_group = QGroupBox("物相识别")
        control_layout = QHBoxLayout(control_group)
        control_layout.setSpacing(8)

        # 左侧: 元素过滤按钮 + 识别方法
        left_panel = QVBoxLayout()
        left_panel.setSpacing(6)

        # 元素过滤 - 弹出按钮 + 已选元素显示
        filter_row = QHBoxLayout()
        self._btn_open_filter = QPushButton("元素过滤 (周期表)")
        self._btn_open_filter.setFixedHeight(32)
        self._btn_open_filter.setStyleSheet(
            "QPushButton { background-color: #607d8b; color: white; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #455a64; }"
        )
        self._btn_open_filter.setToolTip("点击打开元素周期表过滤对话框")
        self._btn_open_filter.clicked.connect(self._open_element_dialog)
        filter_row.addWidget(self._btn_open_filter)

        self._btn_clear_filter = QPushButton("清除")
        self._btn_clear_filter.setFixedHeight(32)
        self._btn_clear_filter.setStyleSheet(
            "QPushButton { background-color: #9e9e9e; color: white; padding: 4px 8px; }"
            "QPushButton:hover { background-color: #757575; }"
        )
        self._btn_clear_filter.clicked.connect(self._clear_filter)
        filter_row.addWidget(self._btn_clear_filter)

        filter_row.addStretch()
        left_panel.addLayout(filter_row)

        # 已选元素摘要
        self._filter_summary = QLabel("未选择元素过滤")
        self._filter_summary.setWordWrap(True)
        self._filter_summary.setStyleSheet(
            "QLabel { color: #666; font-size: 11px; padding: 4px; "
            "background-color: #f5f5f5; border-radius: 3px; }"
        )
        self._filter_summary.setMinimumHeight(24)
        left_panel.addWidget(self._filter_summary)

        # 数据库源选择 (双库切换)
        db_row = QHBoxLayout()
        db_row.setSpacing(6)
        db_row.addWidget(QLabel("数据库源:"))
        self._db_combo = QComboBox()
        self._db_combo.addItems(self._db_source_labels())
        self._db_combo.setFixedHeight(28)
        self._db_combo.setToolTip(self._db_combo_tooltip())
        self._mark_unavailable_db_sources()
        db_row.addWidget(self._db_combo)
        db_row.addStretch()
        left_panel.addLayout(db_row)

        # 识别方法组
        method_layout = QHBoxLayout()
        method_layout.setSpacing(6)

        self._btn_profile_fitting = QPushButton("Profile Fitting (推荐)")
        self._btn_profile_fitting.setFixedHeight(32)
        self._btn_profile_fitting.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #1b5e20; }"
        )
        self._btn_profile_fitting.setToolTip(
            "基于峰形拟合的物相识别，无需事先寻峰。\n"
            "直接比较整个XRD曲线形貌，适用于峰重叠或背景复杂的情况。"
        )
        self._btn_profile_fitting.clicked.connect(self._on_profile_fitting)
        method_layout.addWidget(self._btn_profile_fitting)

        method_layout.addWidget(QLabel("FWHM:"))
        self._fwhm_spin = QDoubleSpinBox()
        self._fwhm_spin.setRange(0.05, 1.0)
        self._fwhm_spin.setValue(0.15)
        self._fwhm_spin.setSingleStep(0.01)
        self._fwhm_spin.setDecimals(2)
        self._fwhm_spin.setSuffix("°")
        self._fwhm_spin.setFixedWidth(80)
        method_layout.addWidget(self._fwhm_spin)

        method_layout.addWidget(QLabel("容差:"))
        self._tolerance_spin = QDoubleSpinBox()
        self._tolerance_spin.setRange(0.05, 1.0)
        self._tolerance_spin.setValue(0.2)
        self._tolerance_spin.setSingleStep(0.05)
        self._tolerance_spin.setDecimals(2)
        self._tolerance_spin.setSuffix("°")
        self._tolerance_spin.setFixedWidth(80)
        self._tolerance_spin.setToolTip("2θ 匹配容差：参考峰与实验峰的距离在此范围内视为匹配")
        method_layout.addWidget(self._tolerance_spin)

        self._btn_identify = QPushButton("传统 Search/Match")
        self._btn_identify.setFixedHeight(32)
        self._btn_identify.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; font-weight: bold; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #0d47a1; }"
        )
        self._btn_identify.setToolTip(
            "传统物相识别方法，需要先进行峰检测。\n"
            "基于FOM(Figure of Merit)算法匹配峰位。"
        )
        self._btn_identify.clicked.connect(self._on_traditional_identify)
        method_layout.addWidget(self._btn_identify)

        self._btn_quick_identify = QPushButton("快速 (无过滤)")
        self._btn_quick_identify.setFixedHeight(32)
        self._btn_quick_identify.setStyleSheet(
            "QPushButton { background-color: #757575; color: white; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #616161; }"
        )
        self._btn_quick_identify.clicked.connect(self._on_quick_identify)
        method_layout.addWidget(self._btn_quick_identify)

        left_panel.addLayout(method_layout)

        control_layout.addLayout(left_panel, stretch=2)

        # 右侧: 候选物相列表
        right_panel = QVBoxLayout()
        right_panel.setSpacing(4)

        self._method_label = QLabel("")
        self._method_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #666; padding: 2px; }"
        )
        right_panel.addWidget(self._method_label)

        self._candidate_list = QListWidget()
        self._candidate_list.setMaximumHeight(150)
        self._candidate_list.itemClicked.connect(self._on_candidate_clicked)
        # M21 v2: 支持勾选多选叠加 (Match! 式), itemChanged 驱动归属刷新
        self._candidate_list.itemChanged.connect(self._on_candidate_toggled)
        right_panel.addWidget(self._candidate_list, stretch=1)

        btn_row = QHBoxLayout()
        self._btn_select = QPushButton("选中物相 →")
        self._btn_select.setFixedHeight(28)
        self._btn_select.setStyleSheet(
            "QPushButton { background-color: #ff6f00; color: white; font-weight: bold; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #e65100; }"
        )
        self._btn_select.clicked.connect(self._on_select_phase)
        btn_row.addWidget(self._btn_select)

        self._btn_auto_mix = QPushButton("自动混合分析")
        self._btn_auto_mix.setFixedHeight(28)
        self._btn_auto_mix.setStyleSheet(
            "QPushButton { background-color: #00695c; color: white; font-weight: bold; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #004d40; }"
        )
        self._btn_auto_mix.setToolTip(
            "对当前候选物相进行多相线性组合拟合，\n"
            "自动计算各物相的权重比例（wt%）"
        )
        self._btn_auto_mix.clicked.connect(self._on_auto_mix)
        btn_row.addWidget(self._btn_auto_mix)

        self._btn_clear_sel = QPushButton("清空")
        self._btn_clear_sel.setFixedHeight(28)
        self._btn_clear_sel.clicked.connect(self._on_clear_selection)
        btn_row.addWidget(self._btn_clear_sel)

        right_panel.addLayout(btn_row)

        # 视图切换: 叠加计算谱 / 显示残差 (M21 v2)
        view_row = QHBoxLayout()
        self._btn_toggle_calc = QPushButton("叠加计算谱")
        self._btn_toggle_calc.setCheckable(True)
        self._btn_toggle_calc.setChecked(True)
        self._btn_toggle_calc.setFixedHeight(24)
        self._btn_toggle_calc.clicked.connect(self._refresh_overlay)
        view_row.addWidget(self._btn_toggle_calc)
        self._btn_toggle_resid = QPushButton("显示残差")
        self._btn_toggle_resid.setCheckable(True)
        self._btn_toggle_resid.setChecked(False)
        self._btn_toggle_resid.setFixedHeight(24)
        self._btn_toggle_resid.clicked.connect(self._refresh_overlay)
        view_row.addWidget(self._btn_toggle_resid)
        right_panel.addLayout(view_row)

        control_layout.addLayout(right_panel, stretch=1)

        main_layout.addWidget(control_group, stretch=1)

        # ====== 底部: 峰-物相归属表 (M21 v2) ======
        self._match_table = PeakMatchTable()
        self._match_table.setMinimumHeight(120)
        main_layout.addWidget(self._match_table, stretch=1)

    def _setup_connections(self) -> None:
        self._vm.phase_identified.connect(self._on_phases_updated)
        self._match_table.peak_row_clicked.connect(self._flash_peak)
        # M21: 选中相集合变更 → 刷新叠加
        pvm = self._vm._phase_vm
        pvm.selection_changed.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # 元素过滤对话框
    # ------------------------------------------------------------------

    def _open_element_dialog(self) -> None:
        """打开元素过滤对话框"""
        self._element_dialog = ElementFilterDialog(self, self._filter_dict)
        self._element_dialog.filter_changed.connect(self._on_filter_changed)
        
        if self._element_dialog.exec():
            self._filter_dict = self._element_dialog.get_filter_dict()
            self._update_filter_summary()

    def _on_filter_changed(self, filter_dict: dict) -> None:
        """对话框内实时更新过滤条件"""
        self._filter_dict = filter_dict
        self._update_filter_summary()

    def _update_filter_summary(self) -> None:
        """更新过滤条件摘要显示 (四态: 必有/含有/可能/没有)"""
        must_have = self._filter_dict.get("must_have", [])
        must = self._filter_dict.get("must", [])
        maybe = self._filter_dict.get("maybe", [])
        exclude = self._filter_dict.get("exclude", [])

        parts = []
        if must_have:
            parts.append(f"必有: {', '.join(must_have)}")
        if must:
            parts.append(f"含有: {', '.join(must)}")
        if maybe:
            parts.append(f"可能: {', '.join(maybe)}")
        if exclude:
            parts.append(f"没有: {', '.join(exclude)}")

        if not parts:
            self._filter_summary.setText("未选择元素过滤")
            return

        text = "过滤: " + " | ".join(parts)
        if must_have or must or maybe:
            text += " (未勾选元素默认排除)"
        self._filter_summary.setText(text)

    def _clear_filter(self) -> None:
        """清除元素过滤"""
        self._filter_dict = {}
        self._update_filter_summary()

    # ------------------------------------------------------------------
    # Profile Fitting (无需寻峰)
    # ------------------------------------------------------------------

    def _on_profile_fitting(self) -> None:
        """Profile Fitting 物相识别"""
        self._current_method = "profile_fitting"
        self._vm.identify_phases_profile_fitting(
            element_filter=self._filter_dict if self._filter_dict else None,
            top_n=10,
            fwhm=self._fwhm_spin.value(),
        )

    # ------------------------------------------------------------------
    # 传统 Search/Match (需要先寻峰)
    # ------------------------------------------------------------------

    def _current_db_source(self) -> str:
        """当前选择的数据库源 key"""
        idx = self._db_combo.currentIndex()
        if 0 <= idx < len(self._db_source_keys):
            return self._db_source_keys[idx]
        return "builtin"

    def _db_source_display(self) -> str:
        """当前数据库源的显示名"""
        return self._db_combo.currentText()

    # ── 数据源可用性 (2026-09-10: 补 PDF2-2004) ──────────────
    def _db_source_labels(self) -> list[str]:
        """各数据源的显示文案。PDF2 的物相数从库里实时读, 不写死。"""
        return [
            "内置库 (118 物相)",
            "COD 无机物库 (71,199)",
            "COD 全库 (113,223)",
            "内置+COD全库合并",
            self._pdf2_label(),
        ]

    def _pdf2_label(self) -> str:
        try:
            from polyxrd.services.pdf2_database import PDF2Database
            db = PDF2Database()
            if db.is_available():
                return f"PDF2-2004 库 ({db.phase_count():,})"
        except Exception:
            pass
        return "PDF2-2004 库 (未挂载)"

    def _db_combo_tooltip(self) -> str:
        return (
            "选择物相检索使用的数据库 (作用于传统 Search/Match 与快速识别):\n"
            "· 内置库: 程序自带 118 种常见物相 (最快)\n"
            "· COD 无机物库: 外挂 71,199 物相 (预计算 d-I 峰, Hanawalt 预筛)\n"
            "· COD 全库: 外挂 113,223 条 CIF 索引 (本地检索)\n"
            "· 合并: 内置库 + COD 全库结果合并排序\n"
            "· PDF2-2004: ICDD PDF-2 2004 版 163,834 物相, 自带空间群与晶胞\n"
            "  (晶胞 81.8% / 空间群 72.8%), 命中相可直接作为精修起始结构。\n"
            f"{self._pdf2_coverage_line()}"
            "库文件路径在设置中挂载 (cod_data/PDF2_2004.sqlite)。"
        )

    def _pdf2_coverage_line(self) -> str:
        """PDF2 库实际覆盖率 (可选行; 读取失败则省略)。"""
        try:
            from polyxrd.services.pdf2_database import PDF2Database
            db = PDF2Database()
            if not db.is_available():
                return "  当前未挂载 PDF2-2004 库。\n"
            cov = db.coverage()
            if not cov:
                return ""
            return (
                f"  本机库: {cov['total']:,} 相, 空间群 {cov['pct_space_group']}%, "
                f"晶胞 {cov['pct_cell']}%。\n"
            )
        except Exception:
            return ""

    def _mark_unavailable_db_sources(self) -> None:
        """未挂载的数据源在下拉里置灰, 避免选中后静默返回空结果。"""
        model = self._db_combo.model()

        def _disable(index: int, hint: str) -> None:
            item = model.item(index)
            if item is not None:
                item.setEnabled(False)
                item.setToolTip(hint)

        try:
            from polyxrd.services.pdf2_database import PDF2Database
            if not PDF2Database().is_available():
                _disable(4, "PDF2-2004 索引库未挂载 (库文件 cod_data/PDF2_2004.sqlite)")
        except Exception:
            _disable(4, "PDF2-2004 服务不可用")

    def _on_traditional_identify(self) -> None:
        """传统物相识别"""
        self._current_method = "fom"
        self._vm.identify_phases(
            element_filter=self._filter_dict if self._filter_dict else None,
            top_n=10,
            db_source=self._current_db_source(),
        )

    def _on_quick_identify(self) -> None:
        """快速识别（无元素过滤）"""
        self._current_method = "fom"
        self._vm.identify_phases(
            element_filter=None, top_n=10,
            db_source=self._current_db_source(),
        )

    # ------------------------------------------------------------------
    # 结果展示
    # ------------------------------------------------------------------

    def _on_phases_updated(self, phase_results: list) -> None:
        """物相列表更新 (新识别 → 清空勾选与叠加, 重新列出候选)"""
        # 阻断 itemChanged 在 clear/清勾选时触发的冗余刷新
        try:
            self._candidate_list.itemChanged.disconnect(self._on_candidate_toggled)
        except RuntimeError:
            pass
        self._candidate_list.clear()
        self._current_results = phase_results

        # 清空上次勾选, 避免旧叠加残留
        self._vm._phase_vm.clear_selection()

        if not phase_results:
            self._method_label.setText("未找到匹配物相")
            self._match_table.clear_table()
            self._refresh_overlay()
            try:
                self._candidate_list.itemChanged.connect(self._on_candidate_toggled)
            except RuntimeError:
                pass
            return

        method = phase_results[0].method if hasattr(phase_results[0], 'method') else "fom"
        db_src = self._db_source_display()
        if method == "profile_fitting":
            self._method_label.setText(
                f"Profile Fitting 结果 [{db_src}] (相关系数越接近100%越好)"
            )
        else:
            self._method_label.setText(
                f"Search/Match 结果 [{db_src}] (FOM值越低越好)"
            )

        for result in phase_results:
            phase = result.phase if hasattr(result, 'phase') else result
            score = result.score if hasattr(result, 'score') else 0.0
            r_factor = getattr(result, 'r_factor', 0.0)

            elem_info = ""
            if hasattr(phase, 'elements') and phase.elements:
                elem_info = " [" + ",".join(sorted(phase.elements)) + "]"

            method = getattr(result, 'method', 'fom')
            sg_txt = self._space_group_suffix(phase)
            if method == "profile_fitting":
                label = f"{phase.name} - 匹配度: {score:.1f}% (R={r_factor:.3f}){sg_txt}{elem_info}"
            else:
                label = f"{phase.name} - FOM: {score:.3f}{sg_txt}{elem_info}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, result)
            tip = self._phase_detail_text(phase)
            if tip:
                item.setToolTip(tip)
            # M21 v2: 可勾选 (勾选=叠加到谱图)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if self._vm._phase_vm.is_selected(phase)
                               else Qt.CheckState.Unchecked)
            self._candidate_list.addItem(item)

        # 恢复 itemChanged 连接 (屏蔽填充期间的冗余刷新)
        try:
            self._candidate_list.itemChanged.connect(self._on_candidate_toggled)
        except RuntimeError:
            pass
        self._refresh_overlay()

    # ── 候选列表的对称性信息 (空间群 / 晶胞) ─────────────────
    @staticmethod
    def _space_group_suffix(phase) -> str:
        """候选列表行尾的空间群短标记 (无则空串)。"""
        sg = (getattr(phase, "space_group", "") or "").strip()
        return f" · {sg}" if sg else ""

    @staticmethod
    def _phase_detail_text(phase) -> str:
        """候选行 tooltip: 化学式 / 空间群 / 晶胞 (有则显示)。"""
        lines: list[str] = []
        formula = (getattr(phase, "formula", "") or "").strip()
        if formula:
            lines.append(f"化学式: {formula}")
        sg = (getattr(phase, "space_group", "") or "").strip()
        if sg:
            lines.append(f"空间群: {sg}")
        lat = getattr(phase, "lattice", None)
        if lat is not None:
            lines.append(
                f"晶胞: a={lat.a:.4f} b={lat.b:.4f} c={lat.c:.4f} Å"
            )
            lines.append(
                f"      α={lat.alpha:.2f} β={lat.beta:.2f} γ={lat.gamma:.2f}°"
            )
            try:
                lines.append(f"      V={lat.volume:.2f} Å³")
            except Exception:
                pass
        refs = getattr(phase, "reference_peaks", None)
        if refs:
            lines.append(f"参考峰: {len(refs)} 条")
        return "\n".join(lines)

    def _on_candidate_clicked(self, item: QListWidgetItem) -> None:
        """单击候选 (非勾选框): 若未勾选则单选叠加该相 (Match! 浏览习惯)。"""
        if item.checkState() != Qt.CheckState.Checked:
            result = item.data(Qt.ItemDataRole.UserRole)
            phase = (result.phase if hasattr(result, 'phase') else result) if result else None
            if phase and not self._vm._phase_vm.is_selected(phase):
                item.setCheckState(Qt.CheckState.Checked)

    def _on_candidate_toggled(self, item: QListWidgetItem) -> None:
        """勾选框状态变更 → 更新选中集合 → 刷新叠加 (itemChanged 在 populate
        时也会触发, 用 guard 避免加载结果时重复刷新; 但 setCheckState 幂等可接受)。"""
        result = item.data(Qt.ItemDataRole.UserRole)
        if not result:
            return
        phase = result.phase if hasattr(result, 'phase') else result
        if not phase:
            return
        checked = item.checkState() == Qt.CheckState.Checked
        self._vm._phase_vm.update_selection(phase, checked)
        # update_selection 已 emit selection_changed → _on_selection_changed 刷新

    def _on_selection_changed(self, *_):
        """选中集合变更 → 重算归属并刷新谱图 + 峰表。"""
        self._refresh_overlay()

    def _refresh_overlay(self):
        """根据当前勾选相, 在 PatternDisplayWidget 上刷新:
        实验黑线 + 计算谱(可选) + 参考棒区 + 归属标记; 并刷新峰归属表。"""
        data = self._vm.current_data or self._vm.processed_data
        pvm = self._vm._phase_vm
        phases = list(pvm.selected_phases)
        if not data:
            self._plot.clear_plot()
            self._match_table.clear_table()
            return

        two_theta = np.asarray(data.two_theta, dtype=float)
        y_exp = np.asarray(data.intensity, dtype=float)
        # 实验谱始终重画
        self._plot.set_experiment(data)

        if not phases:
            # 无选中相: 只画实验, 清峰表与棒区
            self._plot.set_selected_phases([])
            self._plot.set_calculated(None, None)
            self._plot.set_peak_assignments([])
            self._match_table.clear_table()
            self._plot.set_info_text("<b>勾选候选物相叠加查看</b>")
            return

        tolerance = self._tolerance_spin.value()

        # 1) 归属计算 (双向: 参考峰命中表 + 实验峰归属)
        assignments, ref_hit = pvm.current_assignment(tolerance=tolerance)

        # 2) 参考棒区: [(name, refs, color), ...]
        sticks = []
        for i, phase in enumerate(phases):
            color = phase_color(i)
            refs = phase.get_reference_peaks() if hasattr(
                phase, "get_reference_peaks") else getattr(phase, "reference_peaks", [])
            sticks.append((phase.name, refs or [], color))
        self._plot.set_selected_phases(sticks)

        # 3) 归属标记 (峰顶相色圆点 / 未解释红▼)
        self._plot.set_peak_assignments(assignments)

        # 4) 计算谱 (可选) 与残差 (可选) — 用等权合成作显示参考
        if self._btn_toggle_calc.isChecked():
            y_calc = combined_pattern(two_theta, phases, y_exp=y_exp)
            self._plot.set_calculated(two_theta, y_calc)
        else:
            self._plot.set_calculated(None, None)

        if self._btn_toggle_resid.isChecked():
            y_calc = combined_pattern(two_theta, phases, y_exp=y_exp)
            from polyxrd.services.phase_display import residual
            self._plot.set_residual_curve(two_theta, residual(y_exp, y_calc))
        else:
            self._plot.set_residual_curve(None, None)

        # 5) 峰归属表
        self._match_table.set_assignments(assignments)

        # 6) 统计信息条: 逐相覆盖率 + 未解释峰
        info = self._coverage_summary(phases, ref_hit, assignments)
        self._plot.set_info_text(info)

    def _coverage_summary(self, phases, ref_hit, assignments):
        """拼一段 HTML: 逐相覆盖率 | 已解释/未解释峰数。"""
        parts = []
        for i, ph in enumerate(phases):
            hits = ref_hit[i]
            if hits:
                cov = 100.0 * sum(1 for h in hits if h) / len(hits)
            else:
                cov = 0.0
            parts.append(
                f"<span style='color:{phase_color(i)}'>■ {ph.name}: {cov:.0f}%</span>")
        explained = sum(1 for a in assignments if a.phase_index is not None)
        unexplained = len(assignments) - explained
        parts.append(f"峰 已解释 {explained} / 未解释 {unexplained}")
        return " | ".join(parts)

    def _flash_peak(self, two_theta: float) -> None:
        """峰表点击 → 谱图上闪示该峰位 (x 轴居中临时放大可不做, 仅高亮提示)。"""
        if not hasattr(self._plot, "_main_x") or self._plot._main_x.size == 0:
            return
        # 简单 x 轴移到该峰附近 (窗口宽 ±8°)
        self._plot.get_axes().set_xlim(two_theta - 8, two_theta + 8)
        self._plot.get_figure().canvas.draw_idle()

    # ------------------------------------------------------------------
    # 事件处理 - 报告
    # ------------------------------------------------------------------

    def _on_select_phase(self) -> None:
        """选中物相 - 确认后切换到结构精修"""
        current_item = self._candidate_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先在列表中选择一个物相")
            return
        
        result = current_item.data(Qt.ItemDataRole.UserRole)
        if not result:
            return
        
        phase = result.phase if hasattr(result, 'phase') else result
        if not phase:
            return
        
        reply = QMessageBox.question(
            self, "确认物相",
            f"已选择物相: <b>{phase.name}</b>\n\n"
            f"是否切换到结构精修页面进行 Rietveld 精修？\n\n"
            f"(点击\"否\"可继续选择其他物相)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.select_phase(phase)
            self.phase_confirmed.emit(phase)

    def _on_clear_selection(self) -> None:
        """清空已选物相 (取消全部勾选, 保留候选列表)"""
        self._vm._phase_vm.clear_selection()
        # 逐个取消勾选 (itemChanged → update_selection 幂等, 均未选则无副作用)
        try:
            self._candidate_list.itemChanged.disconnect(self._on_candidate_toggled)
        except RuntimeError:
            pass
        for i in range(self._candidate_list.count()):
            it = self._candidate_list.item(i)
            if it is not None:
                it.setCheckState(Qt.CheckState.Unchecked)
        try:
            self._candidate_list.itemChanged.connect(self._on_candidate_toggled)
        except RuntimeError:
            pass
        self._refresh_overlay()

    def reset_view(self) -> None:
        """外部数据被清除/替换时, 复位整个物相分析视图 (候选/方法标题/选中/表)。"""
        self._vm._phase_vm.reset_analysis()
        try:
            self._candidate_list.itemChanged.disconnect(self._on_candidate_toggled)
        except RuntimeError:
            pass
        self._candidate_list.clear()
        self._current_results = []
        try:
            self._candidate_list.itemChanged.connect(self._on_candidate_toggled)
        except RuntimeError:
            pass
        if hasattr(self, "_method_label"):
            self._method_label.setText("")
        if hasattr(self, "_match_table"):
            self._match_table.clear_table()
        self._refresh_overlay()

    def _on_auto_mix(self) -> None:
        """自动混合分析 - 多物相线性组合拟合

        算法:
        1. 取候选物相的前N个（最多5个）
        2. 为每个物相生成理论XRD图谱（Gaussian峰形）
        3. 用非负最小二乘(NNLS)求解各物相权重
        4. 归一化为重量百分比
        5. 绘制实验数据、混合拟合曲线、各物相贡献
        """
        if not self._current_results:
            QMessageBox.warning(self, "提示", "请先执行物相识别")
            return

        data = self._vm.current_data or self._vm.processed_data
        if not data:
            QMessageBox.warning(self, "提示", "请先加载 XRD 数据")
            return

        n_phases = min(5, len(self._current_results))
        phases = []
        for result in self._current_results[:n_phases]:
            phase = result.phase if hasattr(result, "phase") else result
            if phase:
                phases.append(phase)

        if not phases:
            QMessageBox.warning(self, "提示", "无可用物相进行混合分析")
            return

        from polyxrd.services.profile_fitting import ProfileFittingService
        from polyxrd.models.xrd_data import XRDData
        from scipy.optimize import nnls

        pf = ProfileFittingService()
        fwhm = self._fwhm_spin.value()
        two_theta = data.two_theta

        # 估计背景并扣除
        bg = pf._estimate_background(data, 50)
        y_exp = data.intensity - bg

        # 为每个物相生成理论图谱
        patterns = []
        for phase in phases:
            pattern = pf._generate_theoretical_profile(phase, two_theta, fwhm)
            patterns.append(pattern)

        # 构建系数矩阵 A (n_points x n_phases)
        A = np.column_stack(patterns)

        # 非负最小二乘: y_exp ≈ A @ w, w >= 0
        weights, residual_norm = nnls(A, y_exp)

        # 归一化为百分比
        total_weight = np.sum(weights)
        if total_weight > 0:
            weight_pcts = (weights / total_weight) * 100.0
        else:
            weight_pcts = np.zeros_like(weights)

        # 计算混合曲线和R因子
        combined = A @ weights
        r_factor = (
            float(np.sum(np.abs(y_exp - combined)) / np.sum(np.abs(y_exp)))
            if np.sum(np.abs(y_exp)) > 1e-10
            else 1.0
        )

        # 计算相关系数
        correlation = ProfileFittingService._pearson_correlation(
            ProfileFittingService._normalize(y_exp),
            ProfileFittingService._normalize(combined),
        )

        # 绘图 (v2 显示: 实验 + 加权计算谱 + 参考棒区)
        self._plot.set_experiment(data)
        # 加权计算谱 (含背景)
        calc_full = combined + bg
        self._plot.set_calculated(two_theta, calc_full)
        # 残差 (bg 后基线接近 0 的区域已由实验扣除; 直接 y_exp−(combined+bg))
        from polyxrd.services.phase_display import residual
        self._plot.set_residual_curve(two_theta, residual(
            np.asarray(data.intensity, float), calc_full))
        # 棒区: 按 NNLS 权重序画选中/混合相
        sticks = []
        sel = self._vm._phase_vm.selected_phases
        ordered = [ph for ph in sel if ph in phases] + \
                  [ph for ph in phases if ph not in sel]
        for i, ph in enumerate(ordered):
            refs = (ph.get_reference_peaks() if hasattr(ph, "get_reference_peaks")
                    else getattr(ph, "reference_peaks", []))
            w_i = next((w for p, w in zip(phases, weight_pcts)
                        if p.name == ph.name), 0.0)
            sticks.append((f"{ph.name} ({w_i:.0f}%)", refs or [],
                           phase_color(i)))
        self._plot.set_selected_phases(sticks)

        # 统计信息
        phase_info = " + ".join(
            f"{p.name}: {w:.1f}%" for p, w in zip(phases, weight_pcts)
        )
        info_text = (
            f"<b>多相混合分析</b> | "
            f"相关系数: {correlation * 100:.1f}% | "
            f"R={r_factor:.3f} | "
            f"{phase_info}"
        )
        self._plot.set_info_text(info_text)