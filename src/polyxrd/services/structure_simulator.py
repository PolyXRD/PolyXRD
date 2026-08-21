"""
结构模拟服务
============
从晶体结构模拟XRD图谱，支持CIF文件和内置数据库结构。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.resources import get_resource_path


class StructureSimulator:
    """XRD结构模拟器

    基于pymatgen的XRDCalculator从晶体结构模拟XRD图谱。
    支持从内置参考数据库直接生成理论XRD图谱。

    Usage:
        simulator = StructureSimulator()
        pattern = simulator.simulate(structure, wavelength=1.5406)
        pattern = simulator.simulate_from_database("Silicon")
    """

    def __init__(self) -> None:
        self._cached_structures: dict[str, object] = {}
        self._reference_cache: dict[str, dict] = {}

    def simulate(
        self,
        structure,
        wavelength: float = 1.5406,
        two_theta_range: tuple[float, float] = (10.0, 90.0),
        peak_width: float = 0.15,
        include_kalpha2: bool = False,
    ) -> XRDData:
        """从晶体结构模拟XRD图谱

        Args:
            structure: pymatgen Structure 对象 或 CIF文件路径
            wavelength: X射线波长（Å）
            two_theta_range: 2θ范围 (min, max)
            peak_width: 峰宽（用于生成连续图谱）
            include_kalpha2: 是否包含Kα2峰

        Returns:
            模拟的XRDData

        Raises:
            ImportError: 当pymatgen不可用时
            ValueError: 当参数无效时
        """
        try:
            from pymatgen.core import Structure
            from pymatgen.analysis.diffraction.xrd import XRDCalculator
        except ImportError:
            raise ImportError("需要pymatgen库。请执行: pip install pymatgen")

        if isinstance(structure, str):
            struct = Structure.from_file(structure)
        elif isinstance(structure, Structure):
            struct = structure
        else:
            raise ValueError(f"不支持的结构类型: {type(structure)}")

        calculator = XRDCalculator(wavelength=wavelength)
        pattern = calculator.get_pattern(struct, two_theta_range=two_theta_range)

        return self._pattern_to_xrd_data(
            pattern, wavelength, two_theta_range, peak_width
        )

    def simulate_from_database(
        self,
        phase_name: str,
        wavelength: float = 1.5406,
        two_theta_range: tuple[float, float] = (10.0, 90.0),
        peak_width: float = 0.15,
    ) -> Optional[XRDData]:
        """从内置参考数据库直接生成理论XRD图谱

        不需要pymatgen，使用预置的峰位和强度数据。

        Args:
            phase_name: 物相名称 (如 "Silicon", "α-Quartz")
            wavelength: 目标波长 (用于从原始Cu数据换算)
            two_theta_range: 2θ范围
            peak_width: 峰宽

        Returns:
            模拟的XRDData，未找到返回None
        """
        ref_db = self._load_reference_database()
        if not ref_db:
            return None

        phase_data = self._find_phase(ref_db, phase_name)
        if not phase_data:
            return None

        orig_wl = ref_db.get("wavelength", 1.5406)
        peaks = phase_data.get("peaks", [])

        two_theta_min, two_theta_max = two_theta_range
        step = 0.01
        n_points = int((two_theta_max - two_theta_min) / step) + 1
        two_theta_grid = np.linspace(two_theta_min, two_theta_max, n_points)

        intensity = np.zeros(n_points)
        fwhm_to_sigma = 2.355

        for peak in peaks:
            orig_2theta = peak["two_theta"]
            orig_intensity = peak.get("intensity", 50)

            if wavelength != orig_wl:
                orig_2theta = self._convert_wavelength(orig_2theta, orig_wl, wavelength)
                if orig_2theta < two_theta_min or orig_2theta > two_theta_max:
                    continue

            if two_theta_min <= orig_2theta <= two_theta_max:
                sigma = peak_width / fwhm_to_sigma
                contribution = orig_intensity * np.exp(
                    -0.5 * ((two_theta_grid - orig_2theta) / sigma) ** 2
                )
                intensity += contribution

        if intensity.max() > 0:
            intensity = intensity / intensity.max() * 100.0

        return XRDData(
            two_theta=two_theta_grid,
            intensity=intensity,
            wavelength=wavelength,
        )

    def list_database_phases(self) -> list[str]:
        ref_db = self._load_reference_database()
        if not ref_db:
            return []
        return [p.get("name", p.get("key", "")) for p in ref_db.get("phases", [])]

    def _load_reference_database(self) -> dict:
        if self._reference_cache:
            return self._reference_cache

        db_path = get_resource_path("database/xrd_reference_database.json")
        if db_path and Path(db_path).exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._reference_cache = data
                return data
            except Exception:
                pass
        return {}

    def _find_phase(self, ref_db: dict, name: str) -> Optional[dict]:
        phases = ref_db.get("phases", [])
        name_lower = name.lower()
        for p in phases:
            if p.get("name", "").lower() == name_lower:
                return p
            if p.get("key", "").lower() == name_lower:
                return p
        for p in phases:
            if name_lower in p.get("name", "").lower():
                return p
            if name_lower in p.get("formula", "").lower():
                return p
        return None

    def _convert_wavelength(
        self, two_theta: float, orig_wl: float, new_wl: float
    ) -> float:
        """从原始波长的2θ换算到新波长的2θ

        使用Bragg定律: λ = 2d sin(θ)
        d间距不变: sin(θ1)/λ1 = sin(θ2)/λ2
        """
        theta_rad = np.radians(two_theta / 2.0)
        d_sin = np.sin(theta_rad) / orig_wl
        new_sin = d_sin * new_wl
        if new_sin <= 1.0 and new_sin >= 0:
            new_theta = np.arcsin(new_sin)
            return float(np.degrees(new_theta) * 2.0)
        return 0.0

    def _pattern_to_xrd_data(
        self, pattern, wavelength: float,
        two_theta_range: tuple[float, float], peak_width: float,
    ) -> XRDData:
        two_theta_min, two_theta_max = two_theta_range
        step = 0.01
        n_points = int((two_theta_max - two_theta_min) / step) + 1
        two_theta_grid = np.linspace(two_theta_min, two_theta_max, n_points)

        intensity = np.zeros(n_points)
        fwhm_to_sigma = 2.355

        for i, two_theta_pos in enumerate(pattern.x):
            if two_theta_min <= two_theta_pos <= two_theta_max:
                intensity_val = pattern.y[i] if i < len(pattern.y) else 100.0
                sigma = peak_width / fwhm_to_sigma
                contribution = intensity_val * np.exp(
                    -0.5 * ((two_theta_grid - two_theta_pos) / sigma) ** 2
                )
                intensity += contribution

        if intensity.max() > 0:
            intensity = intensity / intensity.max() * 100.0

        return XRDData(
            two_theta=two_theta_grid,
            intensity=intensity,
            wavelength=wavelength,
        )

    def compare_patterns(
        self,
        simulated: XRDData,
        experimental: XRDData,
        tolerance: float = 0.15,
    ) -> dict:
        """比较模拟与实验图谱

        Args:
            simulated: 模拟XRD数据
            experimental: 实验XRD数据
            tolerance: 峰位容差（度）

        Returns:
            比较结果字典
        """
        common_grid = experimental.two_theta
        sim_interp = np.interp(
            common_grid, simulated.two_theta, simulated.intensity
        )

        if np.std(sim_interp) > 0 and np.std(experimental.intensity) > 0:
            correlation = np.corrcoef(sim_interp, experimental.intensity)[0, 1]
        else:
            correlation = 0.0

        y_exp = experimental.intensity
        y_sim = sim_interp
        r_factor = np.sum(np.abs(y_exp - y_sim)) / np.sum(np.abs(y_exp)) * 100

        sim_peaks_2theta = self._get_peak_positions(simulated)
        exp_peaks_2theta = self._get_peak_positions(experimental)

        matched_peaks = 0
        for sim_peak in sim_peaks_2theta:
            for exp_peak in exp_peaks_2theta:
                if abs(sim_peak - exp_peak) <= tolerance:
                    matched_peaks += 1
                    break

        total_peaks = max(len(sim_peaks_2theta), len(exp_peaks_2theta))
        match_rate = matched_peaks / max(total_peaks, 1) * 100

        return {
            "correlation_coefficient": float(correlation),
            "r_factor": float(r_factor),
            "peak_match_rate": float(match_rate),
            "matched_peaks": matched_peaks,
            "total_simulated_peaks": len(sim_peaks_2theta),
            "total_experimental_peaks": len(exp_peaks_2theta),
        }

    def generate_reference_peaks(
        self,
        structure,
        wavelength: float = 1.5406,
        two_theta_range: tuple[float, float] = (10.0, 90.0),
    ) -> list[dict]:
        """生成参考峰列表

        Args:
            structure: 晶体结构
            wavelength: X射线波长
            two_theta_range: 2θ范围

        Returns:
            峰信息列表
        """
        try:
            from pymatgen.core import Structure
            from pymatgen.analysis.diffraction.xrd import XRDCalculator
        except ImportError:
            raise ImportError("需要pymatgen库")

        if isinstance(structure, str):
            struct = Structure.from_file(structure)
        else:
            struct = structure

        calculator = XRDCalculator(wavelength=wavelength)
        pattern = calculator.get_pattern(struct, two_theta_range=two_theta_range)

        peaks = []
        for i in range(len(pattern.x)):
            hkl_info = pattern.hkls[i] if i < len(pattern.hkls) else []
            hkl = (0, 0, 0)
            if hkl_info:
                if isinstance(hkl_info[0], dict):
                    raw_hkl = hkl_info[0].get("hkl", (0, 0, 0))
                    if len(raw_hkl) >= 4:
                        hkl = (int(raw_hkl[0]), int(raw_hkl[1]), int(raw_hkl[3]))
                    elif len(raw_hkl) >= 3:
                        hkl = (int(raw_hkl[0]), int(raw_hkl[1]), int(raw_hkl[2]))
                    else:
                        hkl = (int(raw_hkl[0]), 0, 0)
                else:
                    hkl = tuple(hkl_info[:3])

            peaks.append({
                "two_theta": float(pattern.x[i]),
                "intensity": float(pattern.y[i]) if i < len(pattern.y) else 0.0,
                "hkl": hkl,
                "d_spacing": float(pattern.d_hkls[i]) if i < len(pattern.d_hkls) else 0.0,
                "multiplicity": hkl_info[0].get("multiplicity", 1) if hkl_info and isinstance(hkl_info[0], dict) else 1,
            })

        return peaks

    def _get_peak_positions(self, data: XRDData, threshold: float = 0.1) -> list[float]:
        from scipy.signal import find_peaks

        max_intensity = data.intensity.max()
        if max_intensity <= 0:
            return []

        peaks, _ = find_peaks(data.intensity, height=threshold * max_intensity)
        return [float(data.two_theta[p]) for p in peaks]

    @staticmethod
    def _guess_source(wavelength: float) -> str:
        sources = {
            1.5406: "Cu Kα",
            0.7107: "Mo Kα",
            1.7889: "Co Kα",
            2.2897: "Cr Kα",
        }
        best = min(sources.keys(), key=lambda k: abs(k - wavelength))
        return sources[best] if abs(best - wavelength) < 0.01 else f"Custom ({wavelength:.4f} Å)"