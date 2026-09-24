"""Kα2 双线检测 (实施手册 v3 / M5-W19-a)
========================================
合成两组谱: ① 单线 (只有 Kα1) ② 双线 (Kα1 + 0.5×Kα2, Δ = 2(λ2/λ1−1)tanθ)。
检测器必须把 ① 判为"未标记"、② 判为"标记", 并在精修 warnings 里出现提示。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

LAM1 = 1.5406


def _gauss(x, cen, amp, fwhm):
    sig = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return amp * np.exp(-0.5 * ((x - cen) / sig) ** 2)


def _pattern(cen=36.2, fwhm=0.12, bg=80.0, with_ka2=False, seed=1,
             extra_peaks=((31.8, 300.0), (56.6, 180.0))):
    rng = np.random.default_rng(seed)
    tt = np.arange(20.0, 70.0, 0.01)
    y = np.full_like(tt, bg)
    for c, a in extra_peaks:
        y = y + _gauss(tt, c, a, 0.14)
    y = y + _gauss(tt, cen, 1000.0, fwhm)
    if with_ka2:
        theta = np.radians(cen / 2.0)
        delta = 2.0 * (1.544390 / 1.540560 - 1.0) * np.tan(theta) * 180.0 / np.pi
        y = y + _gauss(tt, cen + delta, 500.0, fwhm)
    return XRDData(two_theta=tt, intensity=y)


class TestKa2Detector:

    def test_singlet_not_flagged(self):
        info = RietveldRefiner().detect_ka2(_pattern(with_ka2=False))
        assert info is not None
        assert info["flagged"] is False, info
        assert info["ratio"] == pytest.approx(1.0, abs=0.15), info

    def test_doublet_flagged(self):
        info = RietveldRefiner().detect_ka2(_pattern(with_ka2=True, seed=3))
        assert info is not None
        assert info["flagged"] is True, info
        assert info["ratio"] > 1.35, info
        # Δ 的解析值 (Cu 靶 36.2° 处 ≈ 0.093°)
        assert info["delta"] == pytest.approx(0.093, abs=0.01)

    def test_warning_reaches_refinement_result(self):
        """双线数据跑一次精修 → result.diagnostics 出现 Kα2 结构化诊断,
        fit_params 带 ka2_detected (v2.1-B: 文案不再进 warnings)"""
        phase = Phase(name="ZnO", formula="ZnO",
                      lattice=LatticeParams(a=3.25, b=3.25, c=5.207,
                                            alpha=90, beta=90, gamma=120),
                      reference_peaks=[((1, 0, 0), 31.77, 57),
                                       ((1, 0, 1), 36.25, 100)])
        data = _pattern(with_ka2=True, seed=5)
        data.wavelength = LAM1
        r = RietveldRefiner().refine(data, [phase], engine="builtin",
                                     max_cycles=4, wR_threshold=None)
        codes = [d.get("code") for d in r.diagnostics]
        assert "diag.ka2_detected" in codes, r.diagnostics
        assert r.fit_params.get("ka2_detected") is True
        # Kα2 诊断条目带量化参数 (中心角/分离角/残差比)
        _ka2_entry = next(d for d in r.diagnostics if d["code"] == "diag.ka2_detected")
        assert _ka2_entry["params"]["center"] > 0
        assert _ka2_entry["params"]["delta"] > 0
        assert _ka2_entry["params"]["ratio"] > 0

    def test_detector_can_be_disabled(self):
        phase = Phase(name="ZnO", formula="ZnO",
                      lattice=LatticeParams(a=3.25, b=3.25, c=5.207,
                                            alpha=90, beta=90, gamma=120),
                      reference_peaks=[((1, 0, 0), 31.77, 57),
                                       ((1, 0, 1), 36.25, 100)])
        data = _pattern(with_ka2=True, seed=5)
        data.wavelength = LAM1
        r = RietveldRefiner().refine(data, [phase], engine="builtin",
                                     max_cycles=4, wR_threshold=None,
                                     detect_ka2=False)
        codes = [d.get("code") for d in r.diagnostics]
        assert "diag.ka2_detected" not in codes, r.diagnostics


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
