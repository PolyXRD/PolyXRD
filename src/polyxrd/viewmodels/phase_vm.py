"""
物相分析ViewModel
==================
峰检测、物相识别的状态管理。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from polyxrd.i18n import tr
from polyxrd.models.peak import PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.services.peak_finder import PeakFinder
from polyxrd.services.phase_identifier import PhaseIdentifier
from polyxrd.services.profile_fitting import ProfileFittingService


class PhaseViewModel(QObject):
    """物相分析ViewModel

    Signals:
        peaks_detected: 峰检测完成
        peaks_fitted: 峰拟合完成
        phase_identified: 物相识别完成
        phase_selected: 选中物相
        error: 错误发生
    """

    peaks_detected = Signal(object)
    peaks_fitted = Signal(object, object)
    phase_identified = Signal(list)
    phase_selected = Signal(object)
    error = Signal(str)
    # M21: 勾选集合变更 (Match! 式多相叠加)
    selection_changed = Signal(list)
    assignment_changed = Signal(object, object)   # (assignments, ref_hit)

    def __init__(self) -> None:
        super().__init__()
        self._peak_finder = PeakFinder()
        self._identifier = PhaseIdentifier()
        self._profile_fitting = ProfileFittingService()

        self._peaks: Optional[PeakList] = None
        self._fitted_peaks: Optional[PeakList] = None
        self._matched_phases: list[PhaseMatchResult] = []
        self._selected_phases: list[Phase] = []

    @property
    def peaks(self) -> Optional[PeakList]:
        return self._peaks

    @property
    def fitted_peaks(self) -> Optional[PeakList]:
        return self._fitted_peaks

    @property
    def matched_phases(self) -> list[PhaseMatchResult]:
        return self._matched_phases

    @property
    def selected_phases(self) -> list[Phase]:
        return self._selected_phases

    def reload_databases(self) -> None:
        """外挂数据库被导入/取消挂载后, 丢掉持有旧路径的缓存。

        `PhaseIdentifier` 会把 COD 全库连接与 "已就绪" 标志缓存下来
        (`_cod_db` / `_cod_ready`), 不清掉的话用户换了 cod_index.sqlite
        之后仍然查的是旧库。其余几个库里没有跨调用的缓存 (每次现开连接),
        但 PDF2 侧有模块级实例, 一并让 `db_import.reload_caches` 处理。
        """
        from polyxrd.services import db_import
        self._identifier._cod_ready = False
        self._identifier._cod_db = None
        db_import.reload_caches()

    def set_data_source(self, data):
        """设置数据源 (用于后续操作)"""
        self._current_data = data

    def find_peaks(
        self,
        data,
        height: float = 0.05,
        distance: float = 0.5,
        prominence: float = 0.01,
        detect_shoulders: bool = False,
        sensitivity: Optional[float] = None,
    ) -> None:
        """自动峰检测 (M20: 支持 M05 增强参数)"""
        try:
            peaks = self._peak_finder.find_peaks(
                data,
                height=height,
                distance=distance,
                prominence=prominence,
                detect_shoulders=detect_shoulders,
                sensitivity=sensitivity,
            )
            self._peaks = peaks
            self.peaks_detected.emit(peaks)
        except Exception as e:
            self.error.emit(tr("error.peak_finder_failed", error=e))

    def find_peaks_advanced(
        self,
        data,
        sigma_threshold: float = 3.0,
        distance_deg: float = 0.12,
        bg_window_deg: float = 2.0,
        refine_mode: str = "fit",
        **kwargs,
    ) -> None:
        """M21: 高精度峰检测 (背景扣除 + 亚步长峰位 + 联合拟合精修)。

        替代 find_peaks 的低精度网格峰位; 旧方法保留。产出自带背景扣除,
        峰位可到 ~0.001°。
        """
        from polyxrd.services.peak_detection import (
            PeakDetectOptions,
            detect_peaks_from_data,
        )
        try:
            opts = PeakDetectOptions(
                sigma_threshold=sigma_threshold,
                distance_deg=distance_deg,
                bg_window_deg=bg_window_deg,
                refine_mode=refine_mode,
                wavelength=getattr(data, "wavelength", None) or 1.5406,
            )
            for k, v in kwargs.items():
                if hasattr(opts, k):
                    setattr(opts, k, v)
            peaks = detect_peaks_from_data(data, opts)
            self._peaks = peaks
            self.peaks_detected.emit(peaks)
        except Exception as e:
            self.error.emit(tr("error.peak_finder_hi_failed", error=e))

    def fit_peaks(
        self,
        data,
        model: str = "voigt",
    ) -> None:
        """峰拟合"""
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit(tr("error.no_peaks"))
            return
        try:
            fitted, stats = self._peak_finder.fit_peaks(
                data, self._peaks, model=model
            )
            self._fitted_peaks = fitted
            self.peaks_fitted.emit(fitted, stats)
        except Exception as e:
            self.error.emit(tr("error.peak_fit_failed", error=e))

    def identify_phases(
        self,
        data,
        elements: Optional[list[str]] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        db_source: str = "builtin",
        marked_peaks: Optional[list[float]] = None,
    ) -> None:
        """物相识别 (支持多数据库源)

        Args:
            db_source: 数据库源
                - "builtin": 内置 118 物相库 (默认)
                - "cod_inorganics": COD 无机物库 (71,199 物相, d-I Hanawalt)
                - "cod_full": COD 全库 (113,223 条 CIF, 本地索引)
                - "merged": 内置库 + COD 全库合并检索
                - "pdf2": ICDD PDF-2 2004 库 (163,834 物相, 带空间群/晶胞)
            marked_peaks: 标记峰 2θ 序列 (v2.2 S13)。None → 全部实测峰;
                传入时仅保留与标记位最近 (≤0.30°) 的实测峰参与检索,
                用于残差相/微量相追查 (候选列表右键"仅对标记峰再匹配")。
        """
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit(tr("error.no_peaks"))
            return
        use_peaks = self._peaks
        if marked_peaks is not None:
            from polyxrd.services.foam import marked_peak_indices

            all_peaks = list(self._peaks.peaks)
            keep = marked_peak_indices(
                [p.two_theta for p in all_peaks], marked_peaks)
            if not keep:
                self.error.emit(tr("error.no_peaks"))
                return
            use_peaks = PeakList(peaks=[all_peaks[k] for k in keep],
                                 source=self._peaks.source)
        try:
            if db_source == "pdf2":
                results = self._identifier.identify_with_pdf2(
                    data,
                    peaks=use_peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            elif db_source == "cod_inorganics":
                results = self._identifier.identify_with_cod_inorganics(
                    data,
                    peaks=use_peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            elif db_source in ("cod_full", "merged"):
                if not getattr(self._identifier, "_cod_ready", False):
                    self._identifier.enable_cod_local()
                results = self._identifier.identify_with_cod_local(
                    data,
                    peaks=use_peaks,
                    elements=elements,
                    top_n=top_n,
                    tolerance=tolerance,
                    merge_with_builtin=(db_source == "merged"),
                )
            elif element_filter:
                results = self._identifier.identify_with_element_filter(
                    data,
                    peaks=use_peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            else:
                results = self._identifier.identify(
                    data,
                    peaks=use_peaks,
                    elements=elements,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            self._matched_phases = results
            self.phase_identified.emit(results)
        except Exception as e:
            self.error.emit(tr("error.identify_failed", error=e))

    def select_phase(self, phase: Phase) -> None:
        """选中物相"""
        if phase not in self._selected_phases:
            self._selected_phases.append(phase)
        self.phase_selected.emit(phase)

    def clear_selection(self) -> None:
        """清空选中物相"""
        self._selected_phases.clear()

    def reset_analysis(self) -> None:
        """清空全部分析状态 (峰/拟合峰/匹配结果/选中相), 换新数据时调用。

        不发信号 (由主 VM 统一在数据切换后发 data_changed/peaks_changed/
        phase_identified 空集通知各视图重绘)。"""
        self._peaks = None
        self._fitted_peaks = None
        self._matched_phases = []
        self._selected_phases = []

    def restore_state(
        self,
        peaks: Optional[PeakList] = None,
        results: Optional[list[PhaseMatchResult]] = None,
        selected: Optional[list[Phase]] = None,
    ) -> None:
        """从项目文件恢复分析状态 (v2.1 P0-1)。

        调用时机: 数据已恢复之后 (restore_data 触发的 reset_analysis 已执行完)。
        发峰/物相/勾选三类信号让各视图按"有数据"路径重绘。
        """
        self._peaks = peaks
        self._matched_phases = list(results or [])
        self._selected_phases = list(selected or [])
        if self._peaks is not None:
            self.peaks_detected.emit(self._peaks)
        self.phase_identified.emit(list(self._matched_phases))
        self.selection_changed.emit(list(self._selected_phases))

    # ── M21: 多选集合管理 (Match! 式勾选叠加) ───────────────
    MAX_SELECTED = 8

    def update_selection(self, phase: Phase, checked: bool) -> None:
        """勾选/取消一个物相, 维持有序集合 (去重按 name+formula)。

        勾选时若达上限则忽略 (提示由视图层负责)。变更后 emit selection_changed。
        """
        key = (getattr(phase, "name", ""), getattr(phase, "formula", ""))
        idx = next((i for i, p in enumerate(self._selected_phases)
                    if (getattr(p, "name", ""), getattr(p, "formula", "")) == key),
                   None)
        if checked:
            if idx is None:
                if len(self._selected_phases) >= self.MAX_SELECTED:
                    return
                self._selected_phases.append(phase)
        else:
            if idx is not None:
                del self._selected_phases[idx]
        self.selection_changed.emit(list(self._selected_phases))

    def is_selected(self, phase: Phase) -> bool:
        key = (getattr(phase, "name", ""), getattr(phase, "formula", ""))
        return any((getattr(p, "name", ""), getattr(p, "formula", "")) == key
                   for p in self._selected_phases)

    def current_assignment(self, tolerance: float = 0.30):
        """当前选中相 + 实测峰 → (assignments, ref_hit)。无峰/无选中 → ([], 空)。"""
        from polyxrd.services.phase_display import assign_peaks

        if not self._selected_phases or not self._peaks:
            return [], [[] for _ in self._selected_phases]
        return assign_peaks(self._peaks.peaks, self._selected_phases,
                            tolerance=tolerance)

    def add_custom_phase(self, phase: Phase) -> None:
        """添加自定义物相"""
        self._identifier.add_phase(phase)

    def identify_phases_profile_fitting(
        self,
        data,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        fwhm: float = 0.15,
    ) -> None:
        """基于峰形拟合的物相识别 (无需寻峰)"""
        try:
            results = self._profile_fitting.identify(
                data,
                element_filter=element_filter,
                top_n=top_n,
                fwhm=fwhm,
            )
            # 标记方法
            for r in results:
                r.method = "profile_fitting"
            self._matched_phases = results
            self.phase_identified.emit(results)
        except Exception as e:
            self.error.emit(f"Profile Fitting 物相识别失败: {e}")
