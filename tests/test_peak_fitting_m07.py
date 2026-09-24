"""
M07 轮廓拟合测试 (Sprint 2)
===========================
覆盖: 单峰拟合 / 重叠双峰联合拟合 / 拟合优度。
"""
import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.peak_fitting import ProfileFitter


def _gauss_xrd(peaks_spec, lo=20.0, hi=40.0, step=0.01, noise=0.0, seed=0):
    x = np.arange(lo, hi + step / 2, step)
    y = np.zeros_like(x)
    for c, a, s in peaks_spec:            # (center, amp, sigma)
        y += a * np.exp(-0.5 * ((x - c) / s) ** 2)
    if noise > 0:
        rng = np.random.default_rng(seed)
        y += rng.normal(0, noise, len(x))
    return XRDData(two_theta=x, intensity=np.maximum(y, 0))


class TestPseudoVoigt:
    def test_shape_sane(self):
        x = np.linspace(0, 10, 101)
        y = ProfileFitter.pseudo_voigt(x, height=100.0, center=5.0,
                                       fwhm=1.0, eta=0.5)
        assert abs(float(np.max(y)) - 100.0) < 1e-6
        assert y[0] < 1.0

    def test_eta_limits(self):
        x = np.linspace(-3, 3, 61)
        g = ProfileFitter.pseudo_voigt(x, 10, 0, 1.0, eta=1.0)   # 纯高斯
        l = ProfileFitter.pseudo_voigt(x, 10, 0, 1.0, eta=0.0)   # 纯洛伦兹
        assert np.all(np.isfinite(g)) and np.all(np.isfinite(l))


class TestFitSingle:
    def test_noiseless_recovery(self):
        xrd = _gauss_xrd([(30.0, 800.0, 0.15)])
        f = ProfileFitter().fit_single_peak(xrd, center=29.95, width=0.3)
        assert abs(f.two_theta - 30.0) < 0.01, f"峰位应≈30.0, 实际 {f.two_theta:.4f}"
        assert 700 < f.intensity < 900, f"峰高应≈800, 实际 {f.intensity:.1f}"
        # 高斯 FWHM=2.355*0.15≈0.353; PV 拟合在 ±0.12 内
        assert abs(f.fwhm - 0.353) < 0.12, f"FWHM 应≈0.353, 实际 {f.fwhm:.3f}"
        assert f.area > 0


class TestFitProfile:
    def test_overlapped_doublet_recovered(self):
        # 两个重叠高斯: 30.0(500) 与 30.35(300), sigma 0.08
        xrd = _gauss_xrd([(30.0, 500.0, 0.08), (30.35, 300.0, 0.08)])
        seeds = PeakList(peaks=[
            Peak(two_theta=29.97, intensity=500, fwhm=0.2),
            Peak(two_theta=30.38, intensity=300, fwhm=0.2)])
        fitted = ProfileFitter().fit_profile(xrd, peaks=seeds)
        centers = sorted(p.two_theta for p in fitted)
        print("fitted centers:", [round(c, 4) for c in centers])
        assert len(fitted) == 2
        assert abs(centers[0] - 30.0) < 0.03, f"低角峰位偏差过大: {centers[0]}"
        assert abs(centers[1] - 30.35) < 0.03, f"高角峰位偏差过大: {centers[1]}"
        # 高度也应大体恢复
        by_pos = {round(p.two_theta, 1): p.intensity for p in fitted}
        main = max(by_pos.values())
        assert 400 < main < 650, f"主峰高应≈500, 实际 {main:.0f}"

    def test_distant_peaks_kept(self):
        xrd = _gauss_xrd([(25.0, 400.0, 0.15), (33.0, 300.0, 0.15)])
        seeds = PeakList(peaks=[
            Peak(two_theta=25.0, intensity=400, fwhm=0.3),
            Peak(two_theta=33.0, intensity=300, fwhm=0.3)])
        fitted = ProfileFitter().fit_profile(xrd, peaks=seeds)
        centers = sorted(p.two_theta for p in fitted)
        assert len(fitted) == 2
        assert abs(centers[0] - 25.0) < 0.01 and abs(centers[1] - 33.0) < 0.01


class TestGoodness:
    def test_noiseless_high_r2(self):
        spec = [(30.0, 500.0, 0.15), (33.0, 300.0, 0.15)]
        xrd = _gauss_xrd(spec)
        seeds = PeakList(peaks=[
            Peak(two_theta=30.0, intensity=500, fwhm=0.3),
            Peak(two_theta=33.0, intensity=300, fwhm=0.3)])
        fitted = ProfileFitter().fit_profile(xrd, peaks=seeds)
        model = ProfileFitter.model_spectrum(xrd.two_theta, fitted)
        g = ProfileFitter.goodness_of_fit(xrd, model)
        print("goodness:", {k: round(v, 3) for k, v in g.items()})
        assert {"rwp", "chi2", "r2"} <= set(g)
        assert g["r2"] > 0.98


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
