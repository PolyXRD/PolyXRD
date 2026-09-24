"""
XRDData 模型测试
"""
import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData, BackgroundResult


class TestXRDData:
    """XRDData 数据模型测试"""

    def test_create_valid_data(self):
        """测试创建有效数据"""
        two_theta = np.linspace(5, 80, 100)
        intensity = np.random.rand(100) * 1000
        data = XRDData(two_theta=two_theta, intensity=intensity)

        assert len(data) == 100
        assert data.wavelength == 1.5406
        assert data.two_theta[0] == 5.0
        assert data.two_theta[-1] == 80.0

    def test_unequal_lengths_raises(self):
        """测试长度不匹配"""
        two_theta = np.linspace(5, 80, 100)
        intensity = np.random.rand(50) * 1000

        with pytest.raises(ValueError):
            XRDData(two_theta=two_theta, intensity=intensity)

    def test_too_few_points_raises(self):
        """测试数据点过少（少于3个点应抛出异常）"""
        two_theta = np.array([5, 6])
        intensity = np.array([10, 20])

        with pytest.raises(ValueError):
            XRDData(two_theta=two_theta, intensity=intensity)

    def test_d_spacing_calculation(self):
        """测试d-spacing计算"""
        # Cu Kα = 1.5406 Å, Si (111) = 28.44° -> d = 3.135 Å
        two_theta = np.array([27.0, 28.44, 30.0])
        intensity = np.array([10, 100, 10])
        data = XRDData(two_theta=two_theta, intensity=intensity)

        d = data.d_spacing
        assert abs(d[1] - 3.135) < 0.01

    def test_normalize(self):
        """测试归一化"""
        two_theta = np.linspace(5, 80, 100)
        intensity = np.array([100, 200, 300] * 33 + [100])
        data = XRDData(two_theta=two_theta, intensity=intensity)

        normalized = data.normalize()
        assert np.max(normalized.intensity) <= 1.0
        assert np.min(normalized.intensity) >= 0.0

    def test_crop(self):
        """测试裁剪"""
        two_theta = np.linspace(5, 80, 100)
        intensity = np.ones(100)
        data = XRDData(two_theta=two_theta, intensity=intensity)

        cropped = data.crop(10, 50)
        assert cropped.two_theta[0] >= 10
        assert cropped.two_theta[-1] <= 50

    def test_copy(self):
        """测试副本"""
        two_theta = np.linspace(5, 80, 100)
        intensity = np.random.rand(100) * 1000
        data = XRDData(two_theta=two_theta, intensity=intensity)

        copy = data.copy()
        assert len(copy) == len(data)
        assert copy.wavelength == data.wavelength

        # 确保修改副本不影响原数据
        copy.intensity[0] = 0
        assert data.intensity[0] != 0

    def test_to_dict_from_dict(self):
        """测试序列化/反序列化"""
        two_theta = np.linspace(5, 80, 100)
        intensity = np.random.rand(100) * 1000
        data = XRDData(two_theta=two_theta, intensity=intensity)

        d = data.to_dict()
        restored = XRDData.from_dict(d)

        assert len(restored) == len(data)
        assert restored.wavelength == data.wavelength
        np.testing.assert_array_almost_equal(restored.two_theta, data.two_theta)
        np.testing.assert_array_almost_equal(restored.intensity, data.intensity)
