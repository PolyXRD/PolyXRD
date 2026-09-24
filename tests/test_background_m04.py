"""
M04 背景估计测试 (Sprint 3)
===========================
"""
import numpy as np

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.background import BackgroundEstimator as BE


def _synth(background_fn=None):
    x = np.linspace(10, 60, 501)
    bg = np.full_like(x, 40.0) + 5.0 * np.sin(x / 8.0)
    y = bg.copy()
    for c, a in [(28.44, 800.0), (47.3, 600.0), (56.1, 400.0)]:
        y += a * np.exp(-0.5 * ((x - c) / 0.15) ** 2)
    return x, y, bg


class TestSnip:
    def test_peaks_removed_background_kept(self):
        x, y, bg = _synth()
        est = BE.snip_background(y, iterations=25)
        # 峰顶处背景应远低于峰
        i1 = int(np.argmin(np.abs(x - 28.44)))
        assert est[i1] < 0.3 * y[i1], "背景在峰区应低于峰顶的 30%"
        # 背景平滑区应接近真背景
        i0 = int(np.argmin(np.abs(x - 15.0)))
        assert abs(est[i0] - bg[i0]) < 15.0, f"无峰区背景应贴合: {est[i0]:.1f} vs {bg[i0]:.1f}"

    def test_returns_same_length(self):
        est = BE.snip_background(np.random.default_rng(0).normal(0, 1, 200))
        assert len(est) == 200 and np.all(np.isfinite(est))


class TestPoly:
    def test_smooth_signal_approximated(self):
        x = np.linspace(0, 10, 101)
        y = 3 + 2 * x - 0.5 * x ** 2          # 二次背景
        bg = BE.poly_background(x, y, degree=3)
        assert np.max(np.abs(bg - y)) < 0.5

    def test_anchors_forced(self):
        x = np.linspace(0, 10, 101)
        y = 5 + 0.1 * x + np.sin(x * 3) * 100  # 有峰
        idx = np.array([10, 50, 90])
        bg = BE.poly_background(x, y, degree=2, anchor_indices=idx)
        # 锚点位置背景≈原始 (锚点被强制贴近)
        assert abs(bg[10] - y[10]) < 20.0


class TestControlPoint:
    def test_passes_through_anchors(self):
        x = np.linspace(10, 60, 501)
        anchors = [(15.0, 35.0), (30.0, 45.0), (50.0, 55.0)]
        bg = BE.control_point_background(x, anchors)
        for ax, ay in anchors:
            j = int(np.argmin(np.abs(x - ax)))
            assert abs(bg[j] - ay) < 1e-6, f"应严格过锚点 {(ax, ay)}"

    def test_too_few_anchors_raises(self):
        try:
            BE.control_point_background(np.linspace(0, 1, 10), [(0.0, 1.0)])
            assert False
        except ValueError:
            pass


class TestSubtract:
    def test_subtraction_and_floor(self):
        x, y, _ = _synth()
        xrd = XRDData(two_theta=x, intensity=y)
        bg = np.full_like(y, 40.0)
        out = BE.subtract_background(xrd, bg)
        assert np.max(out.intensity) < np.max(y)
        # 低区 (10° 附近 y≈bg) 不出现负值
        assert out.intensity.min() >= 0.0

    def test_length_mismatch_raises(self):
        xrd = XRDData(two_theta=np.linspace(1, 2, 100),
                      intensity=np.ones(100))
        try:
            BE.subtract_background(xrd, np.ones(99))
            assert False
        except ValueError:
            pass
