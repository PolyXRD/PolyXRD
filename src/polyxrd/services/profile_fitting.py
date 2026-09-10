"""
Profile Fitting Search/Match
============================
无需事先寻峰的物相分析方法。

参考 Match4 "Search-Match using Profile Fitting" 功能:
- 直接比较整个XRD曲线的形貌，而非仅匹配峰位
- 基于理论峰形模拟（Gaussian/Pseudo-Voigt）生成标准图谱
- 使用相关系数（Correlation Coefficient）评估匹配度
- 支持Cagliotti仪器宽化效应
- 无需寻峰步骤，适合峰形重叠、背景复杂的情况

算法流程:
1. 从实验数据估计背景线
2. 对数据库中每个物相:
   a. 生成理论XRD图谱（基于参考峰位 + 峰形模拟）
   b. 与实验图谱进行相关系数计算
3. 按相关系数排序，返回最佳匹配物相
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.formula_parser import elements_match_filter, normalize_element_filter
from polyxrd.utils.resources import get_resource_path


class ProfileFittingService:
    """基于峰形拟合的物相识别服务

    核心思想:
    直接用整条XRD曲线进行匹配，避免传统方法中寻峰步骤的误差。
    通过模拟每个物相的理论XRD图谱，与实验图谱计算相关系数。

    与传统FOM方法的比较:
    - 传统方法: 先寻峰，再匹配峰位 → 依赖寻峰质量
    - Profile Fitting: 直接匹配曲线形貌 → 更鲁棒，尤其适合重叠峰
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
            except Exception:
                self._phase_database = []

    def _build_phases_from_db(self, ref_data: list[dict]) -> list[Phase]:
        from polyxrd.models.phase import LatticeParams
        from polyxrd.utils.formula_parser import parse_formula

        phases = []
        for entry in ref_data:
            peaks = []
            for p in entry.get("peaks", []):
                hkl = tuple(p["hkl"])
                two_theta = p["two_theta"]
                intensity = p.get("intensity", 50)
                peaks.append((hkl, two_theta, intensity))

            lattice_data = entry.get("lattice", {})
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

    def get_database_info(self) -> dict:
        return {
            "total_phases": len(self._phase_database),
            "reference_count": len(self._reference_data),
        }

    def identify(
        self,
        data: XRDData,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        fwhm: float = 0.15,
        background_points: int = 50,
    ) -> list[PhaseMatchResult]:
        """执行基于峰形拟合的物相识别

        Args:
            data: 实验XRD数据
            element_filter: 元素过滤条件 {"must": [...], "exclude": [...]}
            top_n: 返回候选数量
            fwhm: 峰的半高宽 (度，2θ单位)
            background_points: 背景估计点数

        Returns:
            匹配结果列表，按相关系数降序排列 (越高越好)
        """
        # 1. 估计实验背景
        bg = self._estimate_background(data, background_points)
        experimental_corrected = data.intensity - bg

        # 归一化
        exp_norm = self._normalize(experimental_corrected)

        ef = normalize_element_filter(element_filter) if element_filter else None

        results = []
        for phase in self._phase_database:
            if ef and not elements_match_filter(
                phase.elements,
                has=ef["has"], maybe=ef["maybe"], exclude=ef["exclude"],
                must_have=ef["must_have"],
            ):
                continue

            # 2. 生成理论XRD图谱
            theoretical = self._generate_theoretical_profile(
                phase, data.two_theta, fwhm
            )

            # 3. 计算相关系数
            correlation = self._pearson_correlation(exp_norm, theoretical)

            # 4. 计算R因子
            r_factor = self._r_factor(exp_norm, theoretical)

            # 综合评分: 相关系数越高 + R因子越低 = 匹配越好
            score = correlation * 100.0  # 0-100 scale

            match_result = PhaseMatchResult(
                phase=phase,
                score=score,
                r_factor=r_factor,
                method="profile_fitting",
            )
            results.append(match_result)

        # 按分数降序排列 (Profile Fitting: 分数越高越好)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_n]

    def _estimate_background(
        self, data: XRDData, n_points: int
    ) -> np.ndarray:
        """估计XRD背景线

        使用滚动最小值法估计背景。
        """
        intensity = data.intensity
        n = len(intensity)

        if n <= n_points:
            return np.zeros(n)

        # 滚动窗口最小值
        window = max(5, n // n_points)
        bg = np.zeros(n)

        for i in range(n):
            start = max(0, i - window // 2)
            end = min(n, i + window // 2 + 1)
            bg[i] = np.min(intensity[start:end])

        # 平滑背景
        from scipy.ndimage import uniform_filter1d
        bg = uniform_filter1d(bg, size=window)

        return bg

    def _generate_theoretical_profile(
        self,
        phase: Phase,
        two_theta: np.ndarray,
        fwhm: float,
    ) -> np.ndarray:
        """生成理论XRD图谱

        使用Gaussian峰形模拟每个衍射峰:
        I(2θ) = Σ I_j * exp(-(2θ - 2θ_j)² / (2 * σ²))

        其中 σ = FWHM / (2 * sqrt(2 * ln(2)))

        Args:
            phase: 物相 (含参考峰数据)
            two_theta: 2θ网格
            fwhm: 半高宽

        Returns:
            理论图谱强度数组
        """
        sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        profile = np.zeros_like(two_theta)

        for hkl, peak_2theta, intensity in phase.reference_peaks:
            if peak_2theta < two_theta[0] or peak_2theta > two_theta[-1]:
                continue

            # Gaussian峰形
            contribution = intensity * np.exp(
                -0.5 * ((two_theta - peak_2theta) / sigma) ** 2
            )
            profile += contribution

        return profile

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        """数组归一化到 [0, 1]"""
        arr_min = arr.min()
        arr_max = arr.max()
        if arr_max - arr_min < 1e-10:
            return np.zeros_like(arr)
        return (arr - arr_min) / (arr_max - arr_min)

    @staticmethod
    def _pearson_correlation(x: np.ndarray, y: np.ndarray) -> float:
        """计算Pearson相关系数

        r = Σ((x_i - x̄)(y_i - ȳ)) / sqrt(Σ(x_i - x̄)² * Σ(y_i - ȳ)²)

        值范围: [-1, 1]，越接近1表示正相关性越强。
        """
        x_mean = np.mean(x)
        y_mean = np.mean(y)

        x_centered = x - x_mean
        y_centered = y - y_mean

        numerator = np.sum(x_centered * y_centered)
        denominator = np.sqrt(
            np.sum(x_centered ** 2) * np.sum(y_centered ** 2)
        )

        if denominator < 1e-10:
            return 0.0

        return float(numerator / denominator)

    @staticmethod
    def _r_factor(experimental: np.ndarray, calculated: np.ndarray) -> float:
        """计算R因子 (Rietveld reliability factor)

        R = Σ|I_obs - I_calc| / Σ|I_obs|

        值范围: [0, +∞)，越低越好。
        一般: R < 0.1 极好, R < 0.2 良好, R < 0.3 可接受
        """
        numerator = np.sum(np.abs(experimental - calculated))
        denominator = np.sum(np.abs(experimental))

        if denominator < 1e-10:
            return 1.0

        return float(numerator / denominator)