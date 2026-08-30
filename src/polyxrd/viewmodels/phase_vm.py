"""
物相分析ViewModel
==================
峰检测、物相识别的状态管理。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from polyxrd.models.peak import Peak, PeakList
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

    def set_data_source(self, data):
        """设置数据源 (用于后续操作)"""
        self._current_data = data

    def find_peaks(
        self,
        data,
        height: float = 0.05,
        distance: float = 5.0,
        prominence: float = 0.01,
    ) -> None:
        """自动峰检测"""
        try:
            peaks = self._peak_finder.find_peaks(
                data,
                height=height,
                distance=distance,
                prominence=prominence,
            )
            self._peaks = peaks
            self.peaks_detected.emit(peaks)
        except Exception as e:
            self.error.emit(f"峰检测失败: {e}")

    def fit_peaks(
        self,
        data,
        model: str = "voigt",
    ) -> None:
        """峰拟合"""
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit("请先检测峰")
            return
        try:
            fitted, stats = self._peak_finder.fit_peaks(
                data, self._peaks, model=model
            )
            self._fitted_peaks = fitted
            self.peaks_fitted.emit(fitted, stats)
        except Exception as e:
            self.error.emit(f"峰拟合失败: {e}")

    def identify_phases(
        self,
        data,
        elements: Optional[list[str]] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        db_source: str = "builtin",
    ) -> None:
        """物相识别 (支持多数据库源)

        Args:
            db_source: 数据库源
                - "builtin": 内置 118 物相库 (默认)
                - "cod_inorganics": COD 无机物库 (71,199 物相, d-I Hanawalt)
                - "cod_full": COD 全库 (113,223 条 CIF, 本地索引)
                - "merged": 内置库 + COD 全库合并检索
        """
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit("请先检测峰")
            return
        try:
            if db_source == "cod_inorganics":
                results = self._identifier.identify_with_cod_inorganics(
                    data,
                    peaks=self._peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            elif db_source in ("cod_full", "merged"):
                if not getattr(self._identifier, "_cod_ready", False):
                    self._identifier.enable_cod_local()
                results = self._identifier.identify_with_cod_local(
                    data,
                    peaks=self._peaks,
                    elements=elements,
                    top_n=top_n,
                    tolerance=tolerance,
                    merge_with_builtin=(db_source == "merged"),
                )
            elif element_filter:
                results = self._identifier.identify_with_element_filter(
                    data,
                    peaks=self._peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            else:
                results = self._identifier.identify(
                    data,
                    peaks=self._peaks,
                    elements=elements,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            self._matched_phases = results
            self.phase_identified.emit(results)
        except Exception as e:
            self.error.emit(f"物相识别失败: {e}")

    def select_phase(self, phase: Phase) -> None:
        """选中物相"""
        if phase not in self._selected_phases:
            self._selected_phases.append(phase)
        self.phase_selected.emit(phase)

    def clear_selection(self) -> None:
        """清空选中物相"""
        self._selected_phases.clear()

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
