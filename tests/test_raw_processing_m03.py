"""
M03 原始数据处理管线测试 (Sprint 2)
===================================
覆盖: trim / SG 平滑 / Kα2 剥离 (Rachinger) / 分辨率插值。
"""
import numpy as np

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.raw_processing import RawProcessing as RP
from polyxrd.services.peak_finder import PeakFinder


def _gauss_xrd(centers_amps_sig, lo=15.0, hi=70.0, step=0.02, noise=0.0, seed=0):
    x = np.arange(lo, hi + step / 2, step)
    y = np.zeros_like(x)
    for c, a, s in centers_amps_sig:
        y += a * np.exp(-0.5 * ((x - c) / s) ** 2)
    if noise > 0:
        rng = np.random.default_rng(seed)
        y += rng.normal(0, noise, len(x))
    return XRDData(two_theta=x, intensity=np.maximum(y, 0))


class TestTrim:

    def test_basic(self):
        xrd = _gauss_xrd([(28.44, 100, 0.2)], lo=10, hi=60)
        out = RP.trim(xrd, 20, 40)
        assert out.two_theta[0] >= 20 and out.two_theta[-1] <= 40
        assert len(out) < len(xrd)

    def test_out_of_range_clips(self):
        xrd = _gauss_xrd([(28.44, 100, 0.2)], lo=10, hi=60)
        out = RP.trim(xrd, 5, 100)   # 超范围 → 截到端点
        assert abs(out.two_theta[0] - xrd.two_theta[0]) < 1e-9
        assert abs(out.two_theta[-1] - xrd.two_theta[-1]) < 1e-9

    def test_invalid_range_raises(self):
        xrd = _gauss_xrd([(28.44, 100, 0.2)])
        try:
            RP.trim(xrd, 40, 20)
            assert False, "应抛 ValueError"
        except ValueError:
            pass


class TestSmooth:

    def test_noise_reduced(self):
        y0 = _gauss_xrd([(30.0, 500, 0.2)], noise=20.0, seed=3)
        # 平滑后与无噪声真值更接近
        clean = _gauss_xrd([(30.0, 500, 0.2)], noise=0.0)
        smooth = RP.smooth_savitzky_golay(y0, window=11, polyorder=3)
        err_noisy = np.mean((y0.intensity - clean.intensity) ** 2)
        err_smooth = np.mean((smooth.intensity - clean.intensity) ** 2)
        assert err_smooth < err_noisy * 0.6, f"平滑应降噪: {err_smooth:.1f} vs {err_noisy:.1f}"

    def test_main_peak_area_preserved(self):
        xrd = _gauss_xrd([(30.0, 500, 0.2)], noise=0.0)
        smooth = RP.smooth_savitzky_golay(xrd, window=11, polyorder=3)
        m = (xrd.two_theta >= 28) & (xrd.two_theta <= 32)
        area_before = np.trapezoid(xrd.intensity[m], xrd.two_theta[m])
        area_after = np.trapezoid(smooth.intensity[m], xrd.two_theta[m])
        assert abs(area_after - area_before) / area_before < 0.02

    def test_window_validation(self):
        xrd = _gauss_xrd([(30.0, 500, 0.2)])
        try:
            RP.smooth_savitzky_golay(xrd, window=6)  # 偶数
            assert False
        except ValueError:
            pass


class TestStripKAlpha2:

    def _doublet(self, tt_ka1, amp=800.0, sig=0.06):
        """合成含 Kα2 的双峰谱 (强度比 2:1, 间距按公式)。"""
        sep = PeakFinder._kalpha_doublet_separation(tt_ka1, 1.5406, 1.5444)
        return _gauss_xrd([(tt_ka1, amp, sig), (tt_ka1 + sep, amp / 2, sig)],
                          lo=tt_ka1 - 5, hi=tt_ka1 + 5, step=0.01)

    def test_doublet_becomes_single(self):
        xrd = self._doublet(28.44)
        after = RP.strip_kalpha2(xrd)
        # 剥离后应与"纯 Kα1 谱"接近 (Kα1 高斯尾巴仍在, 但 Kα2 叠加被移除)
        pure = _gauss_xrd([(28.44, 800.0, 0.06)], lo=23.44, hi=33.44, step=0.01)
        m = (after.two_theta >= 28.40) & (after.two_theta <= 28.60)
        max_resid = float(np.max(np.abs(after.intensity[m] - pure.intensity[m])))
        assert max_resid < 0.25 * 800.0, \
            f"剥离后最大残差应 <25% 主峰 (近似插值), 实际 {max_resid:.1f}"
        # 主峰高度应≈800 (不再被 Kα2 前翼抬高)
        main = float(np.max(after.intensity[(after.two_theta >= 28.40)
                                            & (after.two_theta <= 28.48)]))
        assert 700 < main < 850, f"Kα1 主峰应≈800, 实际 {main:.1f}"

    def test_ka1_position_kept(self):
        xrd = self._doublet(28.44)
        after = RP.strip_kalpha2(xrd)
        i_main = int(np.argmax(after.intensity))
        assert abs(after.two_theta[i_main] - 28.44) < 0.02, \
            "剥离后主峰应回到 Kα1 位置 28.44"

    def test_input_not_mutated(self):
        xrd = self._doublet(28.44)
        y_orig = xrd.intensity.copy()
        RP.strip_kalpha2(xrd)
        assert np.allclose(xrd.intensity, y_orig)


class TestIncreaseResolution:

    def test_length_and_peak_position(self):
        xrd = _gauss_xrd([(28.44, 800, 0.2)], lo=20, hi=60, step=0.04)
        out = RP.increase_resolution(xrd, factor=2)
        assert len(out) == (len(xrd) - 1) * 2 + 1
        i = int(np.argmax(out.intensity))
        assert abs(out.two_theta[i] - 28.44) < 0.02

    def test_factor_limit(self):
        xrd = _gauss_xrd([(28.44, 800, 0.2)])
        try:
            RP.increase_resolution(xrd, factor=10)
            assert False
        except ValueError:
            pass


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
