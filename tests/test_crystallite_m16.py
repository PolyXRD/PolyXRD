"""
M16 晶粒尺寸估计测试 (Sprint 3)
===============================
"""
import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.services.crystallite import CrystalliteEstimator as CE


class TestScherrer:
    def test_manual_value(self):
        # λ=1.5406Å, K=0.9, fwhm=0.5° @ 2θ=30°
        # β=0.5·π/180 rad; D=0.9·1.5406/(β·cos15°) Å
        import math
        beta = math.radians(0.5)
        theta = math.radians(15.0)
        expect = 0.9 * 1.5406 / (beta * math.cos(theta)) / 10.0  # nm
        got = CE.scherrer_size(0.5, 30.0)
        assert abs(got - expect) < 1e-6, f"{got} vs {expect}"

    def test_broader_peak_smaller_crystal(self):
        s1 = CE.scherrer_size(0.2, 30.0)
        s2 = CE.scherrer_size(0.8, 30.0)
        assert s1 > s2, "展宽越大粒径越小"

    def test_zero_width_returns_zero(self):
        assert CE.scherrer_size(0.0, 30.0) == 0.0


class TestInstrumental:
    def test_gaussian_quadrature(self):
        beta = CE.subtract_instrumental_broadening(0.6, 0.4, method="gaussian")
        assert abs(beta - np.sqrt(0.6 ** 2 - 0.4 ** 2)) < 1e-9

    def test_lorentz_subtraction(self):
        beta = CE.subtract_instrumental_broadening(0.6, 0.4, method="lorentz")
        assert abs(beta - 0.2) < 1e-9

    def test_std_larger_returns_zero(self):
        assert CE.subtract_instrumental_broadening(0.3, 0.5) == 0.0


class TestEstimateFromPeaks:
    def test_end_to_end(self):
        peaks = PeakList(peaks=[
            Peak(two_theta=28.44, intensity=100, fwhm=0.30),
            Peak(two_theta=47.30, intensity=80, fwhm=0.34),
        ])
        out = CE.estimate_from_peaks(peaks, beta_std_deg=0.1)
        assert len(out) == 2
        assert all(r["size_nm"] > 0 for r in out)
        # 扣除仪器展宽后粒径应变大
        out_raw = CE.estimate_from_peaks(peaks, beta_std_deg=0.0)
        assert out[0]["size_nm"] > out_raw[0]["size_nm"]

    def test_skips_invalid(self):
        out = CE.estimate_from_peaks([Peak(two_theta=28.0, intensity=1)])  # fwhm=0
        assert out == []
