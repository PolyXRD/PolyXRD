"""
Le Bail 晶胞参数精修单元测试 (P4)
================================
验证 rietveld_refiner.RietveldRefiner.refine_le_bail 的 Le Bail 代码路径:
1. 合成立方试样上精修晶胞参数 a, 结果应收敛到真值附近
2. 初始晶胞偏离真值时仍能恢复 (尺度因子搜索)
3. 数据与初始晶胞一致时不应漂移 (best_scale ≈ 1.0)

Le Bail 特点: 强度不需要结构模型, 各衍射峰积分强度按最小二乘从
观测谱动态提取, 仅精修晶胞几何参数。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

WAVELENGTH = 1.5406
A_TRUE = 5.431  # Si (立方)

# 立方 Si 型 hkl → 相对积分强度 (任意但固定, Le Bail 不依赖结构模型)
HKL_INTENSITIES = [
    ((1, 1, 1), 100.0),
    ((2, 0, 0), 60.0),
    ((2, 2, 0), 35.0),
    ((3, 1, 1), 40.0),
    ((2, 2, 2), 10.0),
    ((4, 0, 0), 8.0),
    ((3, 3, 1), 6.0),
]


def _make_synthetic_cubic(
    a_true: float = A_TRUE,
    n_points: int = 3000,
    two_theta_range: tuple[float, float] = (10.0, 80.0),
    background: float = 50.0,
    noise: float = 0.0,
) -> XRDData:
    """从立方晶胞 + 固定 hkl 列表合成无结构依赖的 XRD 图谱"""
    tt = np.linspace(two_theta_range[0], two_theta_range[1], n_points)
    fwhm = 0.15
    sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    y = np.full_like(tt, background)
    for (h, k, l), inten in HKL_INTENSITIES:
        d = a_true / np.sqrt(h * h + k * k + l * l)
        sin_theta = WAVELENGTH / (2.0 * d)
        if sin_theta > 1.0:
            continue
        peak_tt = 2.0 * float(np.degrees(np.arcsin(sin_theta)))
        if two_theta_range[0] <= peak_tt <= two_theta_range[1]:
            y += inten * np.exp(-0.5 * ((tt - peak_tt) / sigma) ** 2)
    if noise > 0:
        rng = np.random.default_rng(42)
        y = y + rng.normal(0.0, noise, size=tt.shape)
    return XRDData(two_theta=tt, intensity=y, wavelength=WAVELENGTH)


def _make_phase(a: float) -> Phase:
    """构造待精修物相 (Le Bail 不需要参考峰/原子占位)"""
    return Phase(
        name="Si-test",
        formula="Si",
        space_group="Fd-3m",
        lattice=LatticeParams(a=a, b=a, c=a, alpha=90.0, beta=90.0, gamma=90.0),
    )


class TestLeBailRefinement:

    def test_le_bail_refines_lattice_a_to_truth(self):
        """1. 合成数据上精修 a: 应收敛到真值 ±0.3%, 且 Rwp 不变差"""
        data = _make_synthetic_cubic(noise=1.0)
        refiner = RietveldRefiner()
        result = refiner.refine_le_bail(
            data, _make_phase(A_TRUE),
            refine_param="a",
            scale_range=(0.98, 1.02),
            n_scan=41,
            eta=1.0,  # 合成谱为纯高斯峰形
        )

        fp = result.fit_params
        assert fp["engine"] == "le_bail"
        assert result.wR < 20.0, f"精修后 Rwp={result.wR:.2f}% 过高"
        assert fp["rwp_refined"] <= fp["rwp_initial"] + 1e-6, (
            f"精修后 Rwp {fp['rwp_refined']:.3f}% 未优于初始 {fp['rwp_initial']:.3f}%"
        )

        refined_a = fp["refined_value"]
        assert abs(refined_a - A_TRUE) / A_TRUE < 0.003, (
            f"精修 a={refined_a:.4f} 偏离真值 {A_TRUE} 超过 0.3%"
        )
        assert len(result.phases) == 1
        assert abs(result.phases[0].lattice.a - refined_a) < 1e-9

    def test_le_bail_recovers_from_offset_initial_cell(self):
        """2. 初始晶胞偏小 1%: 尺度因子搜索应把 a 拉回真值 ±0.5%"""
        a_init = A_TRUE * 0.99
        data = _make_synthetic_cubic(noise=1.0)
        refiner = RietveldRefiner()
        result = refiner.refine_le_bail(
            data, _make_phase(a_init),
            refine_param="a",
            scale_range=(0.995, 1.02),  # 需覆盖 1/0.99 ≈ 1.0101
            n_scan=51,
            eta=1.0,
        )

        fp = result.fit_params
        refined_a = fp["refined_value"]
        assert abs(refined_a - A_TRUE) / A_TRUE < 0.005, (
            f"偏移初值 a₀={a_init:.4f} 未恢复到真值: 精修 a={refined_a:.4f}"
        )
        assert fp["rwp_refined"] <= fp["rwp_initial"], (
            "精修 Rwp 应不劣于偏移初值 Rwp"
        )
        assert result.converged, "偏移初值下精修应改善拟合 (converged=True)"

    def test_le_bail_no_drift_when_initial_is_truth(self):
        """3. 初始晶胞即真值 (无噪声): best_scale 应停在 1.0 附近, 不漂移"""
        data = _make_synthetic_cubic(noise=0.0)
        refiner = RietveldRefiner()
        result = refiner.refine_le_bail(
            data, _make_phase(A_TRUE),
            refine_param="a",
            scale_range=(0.98, 1.02),
            n_scan=41,
            eta=1.0,
        )

        best_scale = result.fit_params["scale"]
        # 网格步长 ≈ 0.001, 允许一个步长内的停留误差
        assert abs(best_scale - 1.0) <= 0.002, (
            f"真值初值下 scale 漂移到 {best_scale:.4f} (应≈1.0)"
        )
        assert result.wR < 15.0, f"无噪声合成数据 Rwp={result.wR:.2f}% 过高"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
