"""
数据预处理测试
"""
import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.data_preprocessor import DataPreprocessor


class TestDataPreprocessor:
    """数据预处理测试"""

    def _create_test_data(self):
        """创建测试数据"""
        np.random.seed(42)
        two_theta = np.linspace(5, 80, 500)
        intensity = np.zeros_like(two_theta)

        # 添加峰
        for center, amp, sigma in [(28.44, 800, 0.15), (47.30, 600, 0.20)]:
            intensity += amp * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)

        # 添加背景
        background = 50 + 10 * two_theta
        intensity += background

        # 添加噪声
        intensity += np.random.normal(0, 5, len(two_theta))
        intensity = np.maximum(intensity, 0)

        return XRDData(two_theta=two_theta, intensity=intensity)

    def test_snip_background(self):
        """测试SNIP背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="snip")
        assert result.method == "snip"
        assert len(result.background) == len(data.intensity)
        assert len(result.corrected.intensity) == len(data.intensity)

        # 校正后强度应小于原始强度
        assert np.max(result.corrected.intensity) <= np.max(data.intensity)

    def test_als_background(self):
        """测试ALS背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="als")
        assert result.method == "als"

    def test_polyfit_background(self):
        """测试多项式拟合背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="polyfit", degree=4)
        assert result.method == "polyfit"

    def test_median_background(self):
        """测试中值滤波背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="median")
        assert result.method == "median"

    def test_savgol_smooth(self):
        """测试Savitzky-Golay平滑"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="savgol", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_gaussian_smooth(self):
        """测试高斯平滑"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="gaussian", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_moving_average_smooth(self):
        """测试移动平均"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="moving", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_median_smooth(self):
        """测试中值平滑"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="median", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_invalid_method_raises(self):
        """测试无效方法"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        with pytest.raises(ValueError):
            preprocessor.subtract_background(data, method="invalid_method")

    def test_ka2_strip(self):
        """测试Kα2剥离"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        corrected = preprocessor.strip_ka_alpha2(data)
        assert len(corrected.intensity) == len(data.intensity)
