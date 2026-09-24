"""M21 Request2: 高精度峰检测引擎 — 合成已知峰位精度 / 弱峰 / 背景稳健测试。"""
import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.peak_detection import (
    PeakDetectOptions,
    detect_peaks_from_data,
    detect_peaks_advanced,
    estimate_background,
)


def _pv(x, amp, center, fwhm, eta=0.6):
    sigma = fwhm / 2.35482
    gamma = fwhm / 2.0
    return eta * amp * np.exp(-0.5 * ((x - center) / sigma) ** 2) + \
        (1 - eta) * amp * gamma ** 2 / ((x - center) ** 2 + gamma ** 2)


def _synth(trues, fwhm=0.18, step=0.02, base_curve=None, noise=0.0, seed=0):
    """trues: 峰位列表 (2θ), 故意不在 0.02 网格上以验证亚步长。"""
    rng = np.random.default_rng(seed)
    x = np.arange(15.0, 60.0, step)
    y = np.zeros_like(x)
    for i, c in enumerate(trues):
        amp = 1000.0 * (1 - 0.08 * i)  # 逐渐变弱
        y += _pv(x, amp, c, fwhm)
    if base_curve is not None:
        y += base_curve(x)
    if noise > 0:
        y += rng.normal(0, noise, y.size)
    return x, y


class TestSubsamplePrecision:
    def test_peak_positions_offgrid_recovered(self):
        """峰位不在 0.02 网格上, 新引擎须还原到 ~0.002° 内 (旧算法只能到 0.02)。"""
        trues = [25.013, 31.047, 36.221, 47.533, 56.609]  # 任意小数峰位
        x, y = _synth(trues, noise=0.5, seed=1)
        opts = PeakDetectOptions(sigma_threshold=5.0)
        centers, _, _, _ = detect_peaks_advanced(x, y, opts)
        # 数量与位置都接近
        assert len(centers) == len(trues), f"检出 {len(centers)} 峰, 期望 {len(trues)}"
        for got, want in zip(sorted(centers), sorted(trues)):
            assert abs(got - want) < 0.005, f"峰位误差 {got - want:.4f} > 0.005"

    def test_old_gridlock_broken(self):
        """对照: 旧 find_peaks 峰位锁在 0.02 网格 (此处仅证明引擎能亚步长)。"""
        trues = [25.013]
        x, y = _synth(trues, noise=0.3, seed=2)
        centers, _, _, _ = detect_peaks_advanced(x, y,
                                                 PeakDetectOptions(sigma_threshold=8.0))
        assert len(centers) == 1
        # 网格最近点
        grid_quant = x[np.argmin(np.abs(x - 25.013))]
        assert abs(grid_quant - 25.013) > abs(centers[0] - 25.013)
        assert abs(centers[0] - 25.013) < 0.005


class TestWeakAndOverlap:
    def test_weak_peak_still_detected(self):
        """强峰旁 20 倍弱的峰, 仍应检出。"""
        x = np.arange(20.0, 40.0, 0.02)
        y = _pv(x, 1000.0, 30.0, 0.18) + _pv(x, 50.0, 33.5, 0.15)
        y += np.random.default_rng(3).normal(0, 0.8, y.size)
        centers, _, _, _ = detect_peaks_advanced(x, y,
                                                 PeakDetectOptions(sigma_threshold=5.0))
        # 33.5 弱峰应被检出 (与 30.0 分离 3.5° 远大于 distance)
        cw = [c for c in centers if abs(c - 33.5) < 0.3]
        assert cw, f"弱峰未检出: centers={np.round(centers,3)}"
        assert abs(cw[0] - 33.5) < 0.01

    def test_curved_background_no_false_positive(self):
        """强弯曲基线 (无峰) → 不应误报峰; 有峰时仍能检出。"""
        x = np.arange(10.0, 80.0, 0.02)
        # 纯弯曲背景 + 一点噪声
        bg = 200.0 + 0.5 * (x - 10) ** 1.4
        y_flat = bg + np.random.default_rng(5).normal(0, 1.0, x.size)
        centers0, _, _, _ = detect_peaks_advanced(
            x, y_flat, PeakDetectOptions(sigma_threshold=5.0))
        assert len(centers0) == 0, f"纯背景误报 {len(centers0)} 峰"
        # 背景上叠一峰
        y_peak = bg + _pv(x, 800.0, 45.013, 0.2) + \
            np.random.default_rng(6).normal(0, 1.0, x.size)
        centers, _, _, _ = detect_peaks_advanced(
            x, y_peak, PeakDetectOptions(sigma_threshold=5.0))
        hit = [c for c in centers if abs(c - 45.013) < 0.01]
        assert hit, f"弯曲背景上的峰未检出: {np.round(centers,3)}"


class TestDataAPI:
    def test_detect_from_data_returns_peaklist(self):
        x = np.arange(15.0, 60.0, 0.02)
        y = _pv(x, 1000.0, 36.221, 0.2) + 50.0
        data = XRDData(two_theta=x, intensity=y, wavelength=1.5406)
        pl = detect_peaks_from_data(data)
        assert len(pl) == 1
        p = pl.peaks[0]
        assert abs(p.two_theta - 36.221) < 0.01
        assert p.d_spacing > 0
        assert p.fwhm > 0.05


class TestEstimateBackground:
    def test_background_tracks_curve(self):
        x = np.arange(10.0, 80.0, 0.02)
        bg = 200.0 + 0.5 * (x - 10) ** 1.4
        # 稀疏强峰
        y = bg.copy()
        for c in [25.0, 35.5, 50.2, 66.1]:
            y += _pv(x, 1500.0, c, 0.2)
        est = estimate_background(x, y, window_deg=4.0)
        # 背景估计应接近真实背景 (误差 < 20)
        resid = np.abs(est - bg)
        # 排除峰心附近 (峰区背景估计略偏)
        assert float(np.median(resid)) < 15.0, f"背景中位误差 {np.median(resid):.1f}"
