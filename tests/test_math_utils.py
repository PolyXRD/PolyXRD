"""
数学工具测试
"""
import numpy as np
import pytest

from polyxrd.utils.math_utils import (
    two_theta_to_d,
    d_to_two_theta,
    two_theta_to_q,
    scherrer_formula,
    lattice_volume,
    fwhm_to_sigma,
    sigma_to_fwhm,
    gaussian,
    lorentzian,
)


class TestMathUtils:
    """数学工具函数测试"""

    def test_two_theta_to_d(self):
        """测试2θ转d-spacing"""
        # Cu Kα = 1.5406 Å, Si (111) = 28.44° -> d = 3.135 Å
        d = two_theta_to_d(28.44, wavelength=1.5406)
        assert abs(d - 3.135) < 0.01

    def test_d_to_two_theta(self):
        """测试d-spacing转2θ"""
        two_theta = d_to_two_theta(3.135, wavelength=1.5406)
        assert abs(two_theta - 28.44) < 0.1

    def test_roundtrip_conversion(self):
        """测试往返转换"""
        original_2theta = 45.0
        d = two_theta_to_d(original_2theta)
        restored_2theta = d_to_two_theta(d)
        assert abs(restored_2theta - original_2theta) < 0.01

    def test_two_theta_to_q(self):
        """测试2θ转散射矢量q"""
        q = two_theta_to_q(28.44, wavelength=1.5406)
        assert q > 0

    def test_scherrer_formula(self):
        """测试Scherrer公式"""
        # 晶粒100Å, 2θ=30°, k=0.9
        fwhm = scherrer_formula(100, two_theta=30.0)
        assert fwhm > 0

    def test_lattice_volume(self):
        """测试晶胞体积"""
        # 立方晶胞 a=5.431 Å
        volume = lattice_volume(5.431, 5.431, 5.431)
        assert abs(volume - 5.431**3) < 0.01

    def test_triclinic_volume(self):
        """测试三斜晶胞体积"""
        volume = lattice_volume(5.0, 6.0, 7.0, 70.0, 80.0, 85.0)
        assert volume > 0
        assert volume < 5 * 6 * 7  # 应小于正交晶胞体积

    def test_fwhm_sigma_conversion(self):
        """测试FWHM/sigma转换"""
        fwhm = 0.2
        sigma = fwhm_to_sigma(fwhm)
        assert abs(sigma_to_fwhm(sigma) - fwhm) < 1e-10

    def test_gaussian(self):
        """测试高斯函数"""
        x = np.linspace(-5, 5, 1000)
        y = gaussian(x, 1.0, 0.0, 1.0)

        # 峰值在中心
        assert abs(np.max(y) - 1.0) < 0.001
        # 半高宽 ≈ 2.355
        half_max = 0.5
        above_half = x[y >= half_max]
        fwhm_approx = above_half[-1] - above_half[0]
        assert abs(fwhm_approx - 2.355) < 0.1

    def test_lorentzian(self):
        """测试洛伦兹函数"""
        x = np.linspace(-5, 5, 1000)
        y = lorentzian(x, 1.0, 0.0, 1.0)

        # 峰值在中心
        assert abs(np.max(y) - 1.0) < 0.001
