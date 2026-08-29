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
    QSizePolicy,
    QMessageBox,
    QScrollArea,
    QFrame,
)

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.widgets.plot_widget import PlotWidget
from polyxrd.views.widgets.element_filter_dialog import ElementFilterDialog
from polyxrd.services.peak_finder import PeakFinder


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
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # ====== 上部: 衍射谱图 (占据主要空间) ======
        self._plot = PlotWidget()
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

        control_layout.addLayout(right_panel, stretch=1)

        main_layout.addWidget(control_group, stretch=1)

    def _setup_connections(self) -> None:
        self._vm.phase_identified.connect(self._on_phases_updated)

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
        """更新过滤条件摘要显示"""
        must = self._filter_dict.get("must", [])
        maybe = self._filter_dict.get("maybe", [])
        exclude = self._filter_dict.get("exclude", [])
        
        parts = []
        if must:
            parts.append(f"必须: {', '.join(must)}")
        if maybe:
            parts.append(f"可能: {', '.join(maybe)}")
        if exclude:
            parts.append(f"不含: {', '.join(exclude)}")
        
        if parts:
            self._filter_summary.setText("过滤: " + " | ".join(parts))
        else:
            self._filter_summary.setText("未选择元素过滤")

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

    def _on_traditional_identify(self) -> None:
        """传统物相识别"""
        self._current_method = "fom"
        self._vm.identify_phases(
            element_filter=self._filter_dict if self._filter_dict else None,
            top_n=10,
        )

    def _on_quick_identify(self) -> None:
        """快速识别（无元素过滤）"""
        self._current_method = "fom"
        self._vm.identify_phases(
            element_filter=None, top_n=10
        )

    # ------------------------------------------------------------------
    # 结果展示
    # ------------------------------------------------------------------

    def _on_phases_updated(self, phase_results: list) -> None:
        """物相列表更新"""
        self._candidate_list.clear()
        self._current_results = phase_results

        if not phase_results:
            self._method_label.setText("未找到匹配物相")
            return

        method = phase_results[0].method if hasattr(phase_results[0], 'method') else "fom"
        if method == "profile_fitting":
            self._method_label.setText(
                "Profile Fitting 结果 (相关系数越接近100%越好)"
            )
        else:
            self._method_label.setText(
                "Search/Match 结果 (FOM值越低越好)"
            )

        for result in phase_results:
            phase = result.phase if hasattr(result, 'phase') else result
            score = result.score if hasattr(result, 'score') else 0.0
            r_factor = getattr(result, 'r_factor', 0.0)

            elem_info = ""
            if hasattr(phase, 'elements') and phase.elements:
                elem_info = " [" + ",".join(sorted(phase.elements)) + "]"

            method = getattr(result, 'method', 'fom')
            if method == "profile_fitting":
                label = f"{phase.name} - 匹配度: {score:.1f}% (R={r_factor:.3f}){elem_info}"
            else:
                label = f"{phase.name} - FOM: {score:.3f}{elem_info}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, result)
            self._candidate_list.addItem(item)

    def _on_candidate_clicked(self, item: QListWidgetItem) -> None:
        """选中候选物相 - 在谱图上显示匹配情况"""
        result = item.data(Qt.ItemDataRole.UserRole)
        if not result:
            return
        
        phase = result.phase if hasattr(result, 'phase') else result
        if not phase:
            return

        data = self._vm.current_data or self._vm.processed_data
        if not data:
            QMessageBox.warning(self, "提示", "请先加载 XRD 数据")
            return

        # 清除并绘制实验数据
        self._plot.clear_plot()
        self._plot.plot_data(data, label="实验数据", color="#2196f3")

        # 获取实验峰位 (如果有)
        exp_peaks = []
        if self._vm.phase_vm and self._vm.phase_vm.peaks:
            exp_peaks = self._vm.phase_vm.peaks.peaks
        
        # 获取参考峰
        ref_peaks_data = phase.get_reference_peaks()
        
        # 对每个参考峰，判断是否在实验中匹配到
        matched_peaks = []
        unmatched_peaks = []
        tolerance = self._tolerance_spin.value()  # 2θ 容差 (度)
        
        for hkl, two_theta, ref_intensity in ref_peaks_data:
            from polyxrd.models.peak import Peak
            peak = Peak(two_theta=two_theta, intensity=ref_intensity, hkl=hkl, phase=phase.name)
            
            # 查找最近的实验峰
            is_matched = False
            if exp_peaks:
                for ep in exp_peaks:
                    if abs(ep.two_theta - two_theta) <= tolerance:
                        is_matched = True
                        peak.intensity = ep.intensity
                        break
            
            if is_matched:
                matched_peaks.append(peak)
            else:
                unmatched_peaks.append(peak)
        
        # 显示匹配峰 (绿色) 和未匹配峰 (红色)
        all_peaks = matched_peaks + unmatched_peaks
        
        # 为不同峰类型设置颜色
        for peak in matched_peaks:
            peak._match_type = "matched"
        for peak in unmatched_peaks:
            peak._match_type = "unmatched"
        
        # 使用 PlotWidget 的标注功能来显示
        self._add_match_annotations(matched_peaks, unmatched_peaks)
        
        # 显示统计信息
        total = len(ref_peaks_data)
        matched_count = len(matched_peaks)
        coverage = (matched_count / total * 100) if total > 0 else 0
        
        info_text = (
            f"<b>{phase.name}</b> | "
            f"匹配: {matched_count}/{total} ({coverage:.0f}%) | "
            f"<span style='color:#4caf50'>● 已匹配</span> "
            f"<span style='color:#f44336'>● 未匹配</span>"
        )
        self._plot.set_info_text(info_text)

    def _add_match_annotations(self, matched_peaks, unmatched_peaks) -> None:
        """在谱图上添加匹配/未匹配峰标注"""
        from matplotlib.lines import Line2D
        from matplotlib.text import Text
        
        # 清除旧的标注
        for artist in getattr(self._plot, '_match_artists', []):
            artist.remove()
        self._plot._match_artists = []
        
        axes = self._plot._axes
        
        # 已匹配峰 - 绿色实线
        for peak in matched_peaks:
            line = axes.axvline(
                peak.two_theta,
                color="#4caf50",
                linestyle="-",
                linewidth=1.2,
                alpha=0.8,
            )
            self._plot._match_artists.append(line)
            
            hkl_str = peak.hkl_str if peak.hkl else ""
            if hkl_str:
                annotation = axes.annotate(
                    f"{peak.two_theta:.2f}\n{hkl_str}",
                    xy=(peak.two_theta, peak.intensity),
                    fontsize=6,
                    ha="center",
                    va="bottom",
                    xytext=(0, 8),
                    textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#c8e6c9", alpha=0.8),
                    color="#2e7d32",
                )
                self._plot._match_artists.append(annotation)
        
        # 未匹配峰 - 红色虚线
        for peak in unmatched_peaks:
            line = axes.axvline(
                peak.two_theta,
                color="#f44336",
                linestyle="--",
                linewidth=1.0,
                alpha=0.6,
            )
            self._plot._match_artists.append(line)
            
            hkl_str = peak.hkl_str if peak.hkl else ""
            if hkl_str:
                annotation = axes.annotate(
                    f"{peak.two_theta:.2f}\n{hkl_str}",
                    xy=(peak.two_theta, 0),
                    fontsize=6,
                    ha="center",
                    va="bottom",
                    xytext=(0, 4),
                    textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffcdd2", alpha=0.7),
                    color="#c62828",
                )
                self._plot._match_artists.append(annotation)
        
        # 添加图例
        legend_elements = [
            Line2D([0], [0], color="#4caf50", linewidth=1.5, label=f"已匹配 ({len(matched_peaks)})"),
            Line2D([0], [0], color="#f44336", linewidth=1.0, linestyle="--", label=f"未匹配 ({len(unmatched_peaks)})"),
        ]
        legend = axes.legend(handles=legend_elements, loc="upper right", fontsize=8)
        self._plot._match_artists.append(legend)
        
        self._plot._canvas.draw_idle()

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
        """清空已选物相"""
        self._candidate_list.clear()
        self._method_label.setText("")
        self._plot.clear_plot()
        self._vm._phase_vm.clear_selection()

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

        # 绘图
        self._plot.clear_plot()
        self._plot.plot_data(data, label="实验数据", color="#2196f3")

        # 绘制混合拟合曲线
        combined_data = XRDData(
            two_theta=two_theta.copy(),
            intensity=combined + bg,
            wavelength=data.wavelength,
        )
        self._plot.plot_data(combined_data, label="混合拟合", color="#ff5722")

        # 绘制各物相贡献
        colors = ["#4caf50", "#9c27b0", "#ff9800", "#795548", "#607d8b"]
        for i, (phase, pattern) in enumerate(zip(phases, patterns)):
            color = colors[i % len(colors)]
            weighted = pattern * weights[i]
            phase_data = XRDData(
                two_theta=two_theta.copy(),
                intensity=weighted,
                wavelength=data.wavelength,
            )
            self._plot.plot_data(
                phase_data,
                label=f"{phase.name} ({weight_pcts[i]:.1f}%)",
                color=color,
            )

        # 显示统计信息
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