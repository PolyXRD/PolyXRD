"""样品位移项 (实施手册 v3 / M5-W16)
===================================
Δ(2θ) = −2·s·cosθ/R 与 zero_shift (常数偏移) 物理不同: 位移项随 cosθ 变化,
高角漂移大、低角几乎不动。本测试锁住:
 1. 变换本身的解析正确性 (含 s=0 时零开销/零改动);
 2. opt-in 打开后能从合成数据把 s 拟合回来 (符号正确、量级合理), 且 wR 不劣化;
 3. 默认关闭 (fit_params 记录 refine_displacement=False, 位移=0)。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

R_MM = 240.0
S_TRUE = 0.40          # mm


def _gauss(x, cen, amp, fwhm):
    sig = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return amp * np.exp(-0.5 * ((x - cen) / sig) ** 2)


class TestTransform:

    def test_analytic_shift_at_100deg(self):
        """100° 处 s=0.5mm, R=240mm → Δ = −2·0.5·cos50°/240 = −0.1535°"""
        refs = [[((4, 0, 0), 100.0, 100.0)]]
        out = RietveldRefiner._apply_displacement(refs, 0.5, R_MM)
        expect = 100.0 + math.degrees(-2.0 * 0.5 * math.cos(math.radians(50.0)) / R_MM)
        assert out[0][0][1] == pytest.approx(expect, abs=1e-6)
        assert out[0][0][0] == (4, 0, 0)          # hkl 保留
        assert out[0][0][2] == pytest.approx(100.0)  # 强度保留

    def test_zero_displacement_is_noop(self):
        refs = [[((1, 0, 0), 30.0, 50.0)]]
        assert RietveldRefiner._apply_displacement(refs, 0.0, R_MM) is refs

    def test_shift_scales_with_cos_theta(self):
        """Δ2θ ∝ cosθ → 同样的 s 在**低角**位移量更大 (标准 B-B 几何)。

        注意: 这与"高角更敏感"的直觉相反, 但正是 Δ(2θ)=−2s·cosθ/R 的形式。
        位移项与 zero_shift(常数) 因此互补: 前者低角大、后者处处相同。
        """
        lo = RietveldRefiner._apply_displacement([[((1, 0, 0), 20.0, 1.0)]], 0.5, R_MM)
        hi = RietveldRefiner._apply_displacement([[((4, 0, 0), 120.0, 1.0)]], 0.5, R_MM)
        d_lo = abs(lo[0][0][1] - 20.0)
        d_hi = abs(hi[0][0][1] - 120.0)
        assert d_lo > d_hi


def _si_phase() -> Phase:
    """立方 Si 的多峰参考表 (跨度大 → 位移的 cosθ 依赖可辨识)"""
    return Phase(
        name="Si", formula="Si",
        lattice=LatticeParams(a=5.431, b=5.431, c=5.431),
        reference_peaks=[
            ((1, 1, 1), 28.44, 100.0),
            ((2, 2, 0), 47.30, 60.0),
            ((3, 1, 1), 56.11, 35.0),
            ((4, 0, 0), 69.13, 15.0),
            ((3, 3, 1), 76.38, 10.0),
            ((4, 2, 2), 88.03, 8.0),
        ],
    )


def _si_pattern(displacement_mm: float = 0.0, seed: int = 2) -> XRDData:
    rng = np.random.default_rng(seed)
    tt = np.arange(20.0, 100.0, 0.02)
    y = np.full_like(tt, 60.0)
    for _hkl, cen, amp in _si_phase().reference_peaks:
        if displacement_mm:
            cen = cen + math.degrees(
                -2.0 * displacement_mm * math.cos(math.radians(cen / 2.0)) / R_MM)
        y = y + _gauss(tt, cen, amp * 12.0, 0.12)
    y = rng.poisson(np.maximum(y, 0.0)).astype(float)
    d = XRDData(two_theta=tt, intensity=y)
    d.wavelength = 1.5406
    return d


class TestFitting:

    def test_default_off(self):
        r = RietveldRefiner().refine(_si_pattern(), [_si_phase()],
                                     engine="builtin", max_cycles=6,
                                     wR_threshold=None)
        assert r.fit_params["refine_displacement"] is False
        assert r.fit_params["displacement_mm"] == pytest.approx(0.0)

    def test_recovers_displacement_and_does_not_worsen_wr(self):
        data = _si_pattern(S_TRUE)
        rr = RietveldRefiner()
        r_off = rr.refine(data, [_si_phase()], engine="builtin", max_cycles=6,
                          wR_threshold=None, detect_ka2=False)
        r_on = rr.refine(data, [_si_phase()], engine="builtin", max_cycles=6,
                         wR_threshold=None, detect_ka2=False,
                         refine_displacement=True)
        s_fit = float(r_on.fit_params["displacement_mm"])
        print(f"[displacement] s_true={S_TRUE} s_fit={s_fit:.3f} mm  "
              f"wR off={r_off.wR:.3f}% on={r_on.wR:.3f}%")
        assert r_on.fit_params["refine_displacement"] is True
        assert s_fit > 0.05, f"位移符号/量级不对: {s_fit}"
        assert s_fit < 1.0, f"位移超出物理范围: {s_fit}"
        assert r_on.wR <= r_off.wR * 1.05 + 1e-9, \
            f"开启位移后 wR 明显变差: off={r_off.wR:.3f} on={r_on.wR:.3f}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
