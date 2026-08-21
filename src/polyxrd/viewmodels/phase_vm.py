"""
物相分析ViewModel
==================
峰检测、物相识别的状态管理。
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QObject, Signal

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.services.cif_database import CIFDatabase
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
        self._cif_db: Optional[CIFDatabase] = None

        self._peaks: Optional[PeakList] = None
        self._fitted_peaks: Optional[PeakList] = None
        self._matched_phases: list[PhaseMatchResult] = []
        self._selected_phases: list[Phase] = []

    def _get_cif_db(self) -> Optional[CIFDatabase]:
        """懒加载 CIFDatabase(含 COD 离线库)。"""
        if self._cif_db is None:
            self._cif_db = CIFDatabase()
        return self._cif_db

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
    ) -> None:
        """物相识别"""
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit("请先检测峰")
            return
        try:
            if element_filter:
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

    def identify_multi_phase(
        self,
        data,
        element_filter: Optional[dict] = None,
        max_phases: int = 5,
        tolerance: float = 0.03,
        precision_min: float = 0.6,
        wavelength: float = 1.5406,
    ) -> None:
        """多物相(混合)分析 - 残差剥离法。

        流程:
          1. 用测得 d 峰在 COD 离线库(71199 物相)中搜索最强匹配物相;
          2. 把该物相所"解释"的测量峰从列表中剥离,留下残差峰;
          3. 对残差峰重复搜索,直到残差峰过少、无新匹配或达到 max_phases。
        返回的每个物相带 weight_fraction(按被解释测量峰强度估算的相对比例)。

        主判据为 top_precision(物相最强的前 5 个去重峰中被观察到的比例):
        真主物相的最强线必须出现在测量峰里,可有效排除"碰巧覆盖多个测量峰"
        的密集杂相。

        Args:
            data: XRDData(用于读取波长)
            element_filter: 元素三态过滤 {"must","maybe","exclude"};
                must 中的元素必须出现在物相化学式中。
            max_phases: 最多识别的物相数
            tolerance: d 值匹配容差(Å)
            precision_min: 单轮候选物相 top_precision 下限,低于此停止
            wavelength: 用于 d→2θ 转换的波长(Å)
        """
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit("请先检测峰")
            return

        try:
            cif_db = self._get_cif_db()
            if cif_db is None or not cif_db.cod_db_available():
                self.error.emit(
                    "COD 离线数据库不可用,无法进行多物相分析。\n"
                    "请先运行 scripts/match_build_sqlite.py 生成数据库。"
                )
                return

            # 元素过滤:must 列表(必须出现的元素符号)
            must_elements: set[str] = set()
            if element_filter:
                must_elements = {
                    str(e).strip().capitalize()
                    for e in (element_filter.get("must") or [])
                    if str(e).strip()
                }

            # 测量峰:(d, two_theta, intensity) 按强度降序(强峰优先解释)
            wl = getattr(data, "wavelength", None) or wavelength
            measured = sorted(
                (
                    (p.d_spacing, p.two_theta, p.intensity)
                    for p in self._peaks.peaks
                    if p.d_spacing and p.d_spacing > 0
                ),
                key=lambda t: t[2],
                reverse=True,
            )
            if not measured:
                self.error.emit("测得峰中无有效 d 值,无法分析")
                return

            remaining = list(measured)
            results: list[PhaseMatchResult] = []
            seen_cod_ids: set[int] = set()
            total_intensity = sum(it for _, _, it in measured)

            for _ in range(max_phases):
                if len(remaining) < 3:
                    break
                d_vals = [d for d, _, _ in remaining]
                i_vals = [it for _, _, it in remaining]
                cand = cif_db.search_cod_by_d_peaks(
                    d_vals,
                    i_vals,
                    tolerance=tolerance,
                    min_match=3,
                    limit=10,
                )
                # 跳过已识别物相 + 元素过滤 + top_precision 阈值
                # top_precision(物相最强线被观察到)是主判据:真主物相的最强线
                # 必须出现在测量峰里;"碰巧覆盖多个测量峰"的密集杂相会被排除。
                pick = None
                for c in cand:
                    if c["cod_id"] in seen_cod_ids:
                        continue
                    if c.get("top_precision", 0.0) < precision_min:
                        continue
                    if must_elements:
                        formula = c.get("formula", "") or ""
                        # 化学式形如 "O2 Si",提取元素符号
                        elems = self._formula_elements(formula)
                        if not must_elements.issubset(elems):
                            continue
                    pick = c
                    break
                if pick is None:
                    break

                seen_cod_ids.add(pick["cod_id"])
                detail = cif_db.get_cod_phase(pick["cod_id"])
                if detail is None:
                    continue

                ref_d = detail.get("peaks_d_list") or []
                ref_i = detail.get("peaks_i_list") or []
                # 只剥离"该物相最强去重峰"所解释的测量峰(定义性强线),
                # 而非前 40 个强峰(后者会误伤与残差相弱线偶然重合的测量峰,
                # 导致残差过少、下一相误判)。
                n_top = min(len(ref_i), max(len(remaining) + 2, 8), 12)
                idx_top = sorted(
                    range(len(ref_i)), key=lambda k: ref_i[k], reverse=True
                )[:n_top]
                top_pairs = sorted(
                    ((ref_d[k], ref_i[k]) for k in idx_top if k < len(ref_d)),
                    key=lambda p: -p[1],
                )
                strong_d: list[float] = []
                for d, _i in top_pairs:
                    if not any(abs(d - ud) <= tolerance for ud in strong_d):
                        strong_d.append(d)

                # 找出被该物相"定义性强线"解释的测量峰
                explained = []
                leftover = []
                for d_m, t_m, it_m in remaining:
                    if any(abs(d_m - rd) <= tolerance for rd in strong_d):
                        explained.append((d_m, t_m, it_m))
                    else:
                        leftover.append((d_m, t_m, it_m))
                if not explained:
                    # 未解释任何峰,停止避免死循环
                    break

                # 构建 Phase(含 reference_peaks, hkl 未知用 (0,0,0))
                reference_peaks = []
                for k in range(min(len(ref_d), len(ref_i))):
                    try:
                        two_t = 2.0 * math.degrees(math.asin(wl / (2.0 * ref_d[k])))
                    except (ValueError, ZeroDivisionError):
                        two_t = 0.0
                    reference_peaks.append(((0, 0, 0), two_t, ref_i[k]))

                phase = Phase(
                    name=f"COD-{pick['cod_id']}",
                    formula=detail.get("formula", ""),
                    space_group=detail.get("space_group", "") or "",
                    reference_peaks=reference_peaks,
                    weight_fraction=0.0,
                    match_score=float(pick.get("top_precision", 0.0)),
                    elements=set(self._formula_elements(detail.get("formula", ""))),
                )
                # 权重:被解释峰强度之和(粗略,非真实质量分数)
                w_frac = sum(it for _, _, it in explained) / total_intensity if total_intensity else 0.0
                phase.weight_fraction = w_frac

                results.append(
                    PhaseMatchResult(
                        phase=phase,
                        score=round(w_frac * 100.0, 2),  # 用作显示"相对占比%"
                        matched_peaks=len(explained),
                        total_peaks=len(measured),
                        confidence=f"top_precision={pick.get('top_precision', 0.0):.2f}",
                        r_factor=0.0,
                        method="auto_mix",
                    )
                )

                remaining = leftover

            if not results:
                self.error.emit(
                    "多物相分析未找到匹配物相(可尝试放宽元素过滤或重新寻峰)"
                )
                return

            # 归一化权重
            wsum = sum(r.phase.weight_fraction for r in results)
            if wsum > 0:
                for r in results:
                    r.phase.weight_fraction = r.phase.weight_fraction / wsum
                    r.score = round(r.phase.weight_fraction * 100.0, 2)

            # 按权重降序
            results.sort(key=lambda r: r.phase.weight_fraction, reverse=True)
            self._matched_phases = results
            self.phase_identified.emit(results)
        except Exception as e:
            self.error.emit(f"多物相分析失败: {e}")

    @staticmethod
    def _formula_elements(formula: str) -> set[str]:
        """从 COD 化学式(如 'O2 Si','Fe2 O3')提取元素符号集合。"""
        import re

        if not formula:
            return set()
        elems: set[str] = set()
        for token in formula.split():
            m = re.match(r"([A-Z][a-z]?)", token)
            if m:
                elems.add(m.group(1).capitalize())
        return elems
