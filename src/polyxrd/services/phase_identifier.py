"""
物相识别服务
============
基于FOM (Figure of Merit) 算法的物相识别。
支持离线XRD参考数据库匹配和COD在线搜索。
支持三态元素过滤: 必须/可能/不含。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.formula_parser import parse_formula, elements_match_filter
from polyxrd.utils.resources import get_resource_path


class PhaseIdentifier:
    """物相识别服务

    基于实验峰与参考数据库峰的匹配进行物相识别。
    使用FOM (Figure of Merit) 算法评估匹配质量。

    FOM = Σ|2θ_obs - 2θ_calc| / Σ(2θ_calc) × N_matched × 100

    FOM越低匹配越好:
    - FOM < 0.1: 极好匹配
    - FOM < 0.3: 良好匹配
    - FOM < 0.5: 一般匹配
    - FOM > 0.5: 可能不匹配
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._phase_database: list[Phase] = []
        self._reference_data: list[dict] = []
        self._load_reference_database()

    def _load_reference_database(self) -> None:
        db_path = get_resource_path("database/xrd_reference_database.json")
        if db_path and Path(db_path).exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._reference_data = data.get("phases", [])
                self._phase_database = self._build_phases_from_db(self._reference_data)
                print(f"[PhaseIdentifier] 已加载 {len(self._phase_database)} 种参考物相")
            except Exception as e:
                print(f"[PhaseIdentifier] 加载参考数据库失败: {e}")
                self._load_default_phases()
        else:
            print("[PhaseIdentifier] 参考数据库不存在，使用默认物相")
            self._load_default_phases()

    def _build_phases_from_db(self, ref_data: list[dict]) -> list[Phase]:
        phases = []
        for entry in ref_data:
            peaks = []
            for p in entry.get("peaks", []):
                hkl = tuple(p["hkl"])
                two_theta = p["two_theta"]
                intensity = p.get("intensity", 50)
                peaks.append((hkl, two_theta, intensity))

            lattice_data = entry.get("lattice", {})
            from polyxrd.models.phase import LatticeParams
            lattice = LatticeParams(
                a=lattice_data.get("a", 1.0),
                b=lattice_data.get("b", 1.0),
                c=lattice_data.get("c", 1.0),
                alpha=lattice_data.get("alpha", 90.0),
                beta=lattice_data.get("beta", 90.0),
                gamma=lattice_data.get("gamma", 90.0),
            )

            formula = entry.get("formula", "")
            elements = parse_formula(formula) if formula else set()

            phase = Phase(
                name=entry.get("name", entry.get("key", "")),
                formula=formula,
                space_group=entry.get("space_group", ""),
                lattice=lattice,
                reference_peaks=peaks,
                elements=elements,
            )
            phases.append(phase)
        return phases

    def _load_default_phases(self) -> None:
        wavelength = self._config.default_wavelength
        phases = []

        si = Phase(
            name="Silicon", formula="Si", space_group="Fd-3m", lattice=None,
            reference_peaks=[
                ((1, 1, 1), 28.44, 100), ((2, 2, 0), 47.30, 60),
                ((3, 1, 1), 56.11, 35), ((4, 0, 0), 69.13, 15),
                ((3, 3, 1), 76.36, 12), ((4, 2, 2), 88.04, 10),
            ],
            elements={"Si"},
        )
        phases.append(si)

        sio2 = Phase(
            name="α-Quartz", formula="SiO2", space_group="P3121", lattice=None,
            reference_peaks=[
                ((0, 1, 0), 20.85, 88), ((1, 0, 0), 26.64, 100),
                ((0, 1, 1), 36.50, 55), ((1, 0, 1), 39.33, 12),
                ((1, 1, 0), 50.14, 14), ((1, 1, 2), 59.95, 14),
            ],
            elements={"Si", "O"},
        )
        phases.append(sio2)

        nacl = Phase(
            name="Halite", formula="NaCl", space_group="Fm-3m", lattice=None,
            reference_peaks=[
                ((1, 1, 1), 27.45, 100), ((2, 0, 0), 31.97, 55),
                ((2, 2, 0), 45.68, 65), ((3, 1, 1), 54.93, 15),
            ],
            elements={"Na", "Cl"},
        )
        phases.append(nacl)

        al2o3 = Phase(
            name="Corundum", formula="Al2O3", space_group="R-3c", lattice=None,
            reference_peaks=[
                ((0, 1, 2), 25.58, 100), ((1, 0, 4), 35.16, 85),
                ((1, 1, 3), 43.36, 75), ((0, 2, 4), 52.56, 90),
            ],
            elements={"Al", "O"},
        )
        phases.append(al2o3)

        self._phase_database = phases

    def identify(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        elements: Optional[list[str]] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
    ) -> list[PhaseMatchResult]:
        """执行物相识别

        Args:
            data: XRD数据
            peaks: 峰列表 (可选，自动检测如未提供)
            elements: 已知元素过滤 (可选，逗号分隔的元素列表)
            top_n: 返回候选数量
            tolerance: 2θ匹配容差 (度)

        Returns:
            匹配结果列表，按FOM升序排列 (FOM越低越好)
        """
        element_filter = None
        if elements:
            element_filter = {
                "must": elements,
                "maybe": [],
                "exclude": [],
            }
        return self.identify_with_element_filter(
            data=data, peaks=peaks,
            element_filter=element_filter,
            top_n=top_n, tolerance=tolerance,
        )

    def identify_with_element_filter(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
    ) -> list[PhaseMatchResult]:
        """执行物相识别（支持三态元素过滤）

        Args:
            data: XRD数据
            peaks: 峰列表 (可选，自动检测如未提供)
            element_filter: 元素过滤条件 {"must": [...], "maybe": [...], "exclude": [...]}
            top_n: 返回候选数量
            tolerance: 2θ匹配容差 (度)

        Returns:
            匹配结果列表，按FOM升序排列 (FOM越低越好)
        """
        if peaks is None:
            from polyxrd.services.peak_finder import PeakFinder
            pf = PeakFinder()
            peaks = pf.find_peaks(data)

        must = element_filter.get("must", []) if element_filter else []
        maybe = element_filter.get("maybe", []) if element_filter else []
        exclude = element_filter.get("exclude", []) if element_filter else []

        results = []
        for phase in self._phase_database:
            if element_filter and (must or exclude):
                if not elements_match_filter(phase.elements, must, maybe, exclude):
                    continue

            match_result = self._match_phase_fom(
                phase, peaks, tolerance
            )
            results.append(match_result)

        results.sort(key=lambda r: r.score)
        return results[:top_n]

    def _match_phase_fom(
        self,
        phase: Phase,
        peaks: PeakList,
        tolerance: float,
    ) -> PhaseMatchResult:
        """基于FOM算法匹配单个物相

        FOM (Figure of Merit):
        FOM = Σ|2θ_obs - 2θ_calc| / Σ(2θ_calc) × N_matched × 100

        Args:
            phase: 候选物相
            peaks: 实验峰列表
            tolerance: 容差

        Returns:
            PhaseMatchResult (score为FOM值，越低越好)
        """
        reference_peaks = phase.get_reference_peaks()
        total_ref_peaks = len(reference_peaks)

        if total_ref_peaks == 0:
            return PhaseMatchResult(
                phase=phase, score=999.0, matched_peaks=0,
                total_peaks=0, confidence="无参考数据", method="fom"
            )

        matched = 0
        sum_deviation = 0.0
        sum_ref_2theta = 0.0
        total_intensity_score = 0.0

        for hkl, ref_2theta, ref_intensity in reference_peaks:
            min_dist = float("inf")
            matched_intensity = 0.0

            for peak in peaks:
                dist = abs(peak.two_theta - ref_2theta)
                if dist < min_dist:
                    min_dist = dist
                    matched_intensity = peak.intensity

            if min_dist <= tolerance:
                matched += 1
                sum_deviation += min_dist
                sum_ref_2theta += ref_2theta

                if ref_intensity > 0 and matched_intensity > 0:
                    int_ratio = min(matched_intensity, ref_intensity) / max(matched_intensity, ref_intensity)
                    total_intensity_score += int_ratio

        if matched == 0 or sum_ref_2theta == 0:
            return PhaseMatchResult(
                phase=phase, score=999.0, matched_peaks=0,
                total_peaks=total_ref_peaks, confidence="不匹配", method="fom"
            )

        fom = (sum_deviation / sum_ref_2theta) * matched * 100.0
        match_ratio = matched / total_ref_peaks
        avg_intensity_score = total_intensity_score / matched if matched > 0 else 0

        combined_score = fom * (1.0 - match_ratio * 0.3) * (1.0 - avg_intensity_score * 0.1)
        combined_score = max(combined_score, 0.01)

        if combined_score < 0.1:
            confidence = "极好匹配"
        elif combined_score < 0.3:
            confidence = "良好匹配"
        elif combined_score < 0.5:
            confidence = "一般匹配"
        else:
            confidence = "可能不匹配"

        return PhaseMatchResult(
            phase=phase,
            score=round(combined_score, 4),
            matched_peaks=matched,
            total_peaks=total_ref_peaks,
            confidence=confidence,
            method="fom",
        )

    def add_phase(self, phase: Phase) -> None:
        self._phase_database.append(phase)

    def load_custom_database(self, path: str) -> None:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        for phase_data in data.get("phases", []):
            phase = Phase.from_dict(phase_data)
            self._phase_database.append(phase)

    def get_database_info(self) -> dict:
        return {
            "total_phases": len(self._phase_database),
            "has_reference_db": len(self._reference_data) > 0,
            "reference_count": len(self._reference_data),
        }