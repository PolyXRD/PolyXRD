"""
峰检测测试
"""
import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.peak_finder import PeakFinder


class TestPeakFinder:
    """峰检测和拟合测试"""

    def _create_synthetic_data(self, two_theta_range=(5, 80), num_points=500):
        """创建合成XRD数据 (含高斯峰)"""
        np.random.seed(42)
        two_theta = np.linspace(two_theta_range[0], two_theta_range[1], num_points)

        # 添加一些高斯峰
        intensity = np.zeros_like(two_theta)
        peaks = [
            (28.44, 800, 0.15),   # Si (111)
            (47.30, 600, 0.20),   # Si (220)
            (56.11, 400, 0.15),   # Si (311)
            (69.13, 300, 0.20),   # Si (400)
        ]
        for center, amp, sigma in peaks:
            intensity += amp * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)

        # 添加噪声
        intensity += np.random.normal(0, 5, len(two_theta))
        intensity = np.maximum(intensity, 0)

        return XRDData(two_theta=two_theta, intensity=intensity)

    def test_find_peaks(self):
        """测试峰检测"""
        data = self._create_synthetic_data()
        pf = PeakFinder()

        peaks = pf.find_peaks(data, height=0.05, distance=3.0)
        assert len(peaks) > 0
        assert len(peaks) <= 10

    def test_peak_properties(self):
        """测试峰属性"""
        data = self._create_synthetic_data()
        pf = PeakFinder()

        peaks = pf.find_peaks(data, height=0.05)

        for peak in peaks:
            assert peak.two_theta > 0
            assert peak.intensity > 0
            assert peak.fwhm >= 0
            assert peak.d_spacing > 0

    def test_fit_gaussian(self):
        """测试高斯峰拟合"""
        data = self._create_synthetic_data()
        pf = PeakFinder()

        peaks = pf.find_peaks(data, height=0.05)
        fitted, stats = pf.fit_peaks(data, peaks, model="gaussian")

        assert len(fitted) == len(peaks)
        assert "r_squared" in stats
        assert stats["r_squared"] > 0

    def test_fit_lorentzian(self):
        """测试洛伦兹峰拟合"""
        data = self._create_synthetic_data()
        pf = PeakFinder()

        peaks = pf.find_peaks(data, height=0.05)
        fitted, stats = pf.fit_peaks(data, peaks, model="lorentzian")

        assert len(fitted) == len(peaks)

    def test_fit_voigt(self):
        """测试Voigt峰拟合"""
        data = self._create_synthetic_data()
        pf = PeakFinder()

        peaks = pf.find_peaks(data, height=0.05)
        fitted, stats = pf.fit_peaks(data, peaks, model="voigt")

        assert len(fitted) == len(peaks)

    def test_fit_pseudo_voigt(self):
        """测试pseudo-Voigt峰拟合"""
        data = self._create_synthetic_data()
        pf = PeakFinder()

        peaks = pf.find_peaks(data, height=0.05)
        fitted, stats = pf.fit_peaks(data, peaks, model="pseudo_voigt")

        assert len(fitted) == len(peaks)

    def test_peak_list_operations(self):
        """测试峰列表操作"""
        from polyxrd.models.peak import PeakList, Peak

        pl = PeakList()
        pl.add(Peak(two_theta=28.44, intensity=800))
        pl.add(Peak(two_theta=47.30, intensity=600))
        pl.add(Peak(two_theta=56.11, intensity=400))

        assert len(pl) == 3
        pl.sort_by_two_theta()
        assert pl.peaks[0].two_theta <= pl.peaks[-1].two_theta

        by_phase = pl.get_by_phase("Si")
        assert len(by_phase) == 0  # 没有设置phase
