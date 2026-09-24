"""
Profile Fitting 物相识别测试
"""
import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.models.phase import Phase, LatticeParams
from polyxrd.services.profile_fitting import ProfileFittingService


class TestProfileFittingService:
    """Profile Fitting 物相识别服务测试"""

    def _create_quartz_data(self):
        """创建模拟石英(α-SiO2)XRD数据"""
        two_theta = np.linspace(15, 80, 4000)
        intensity = np.zeros_like(two_theta)

        # 石英的主要衍射峰
        peaks = [
            (20.86, 100, 0.12),
            (26.64, 250, 0.12),
            (36.54, 80, 0.13),
            (39.47, 60, 0.13),
            (42.45, 50, 0.14),
            (45.79, 40, 0.14),
            (50.13, 30, 0.15),
            (54.86, 70, 0.15),
            (60.00, 35, 0.15),
        ]
        for center, amp, sigma in peaks:
            intensity += amp * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)

        # 添加背景和噪声
        intensity += 50 + 0.5 * two_theta
        intensity += np.random.normal(0, 3, len(two_theta))
        intensity = np.maximum(intensity, 0)

        return XRDData(two_theta=two_theta, intensity=intensity)

    def _create_test_phase(self):
        """创建测试物相（石英）"""
        return Phase(
            name="α-Quartz",
            formula="SiO2",
            space_group="P3221",
            lattice=LatticeParams(a=4.913, b=4.913, c=5.405),
            reference_peaks=[
                ((1, 0, 0), 20.86, 100),
                ((0, 1, 1), 26.64, 250),
                ((1, 1, 0), 36.54, 80),
                ((1, 0, 2), 39.47, 60),
                ((2, 0, 0), 42.45, 50),
                ((1, 1, 2), 45.79, 40),
                ((2, 1, 1), 50.13, 30),
                ((1, 0, 3), 54.86, 70),
                ((2, 1, 2), 60.00, 35),
            ],
            elements={"Si", "O"},
        )

    def test_service_creation(self):
        """测试服务创建"""
        service = ProfileFittingService()
        assert service is not None
        info = service.get_database_info()
        assert "total_phases" in info

    def test_identify_returns_results(self):
        """测试物相识别返回结果列表"""
        data = self._create_quartz_data()
        service = ProfileFittingService()

        results = service.identify(data, top_n=5, fwhm=0.15)

        assert isinstance(results, list)
        assert len(results) <= 5
        if results:
            assert hasattr(results[0], "phase")
            assert hasattr(results[0], "score")
            assert hasattr(results[0], "r_factor")
            assert hasattr(results[0], "method")
            assert results[0].method == "profile_fitting"

    def test_identify_sorted_by_score(self):
        """测试结果按分数降序排列"""
        data = self._create_quartz_data()
        service = ProfileFittingService()

        results = service.identify(data, top_n=10, fwhm=0.15)

        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score

    def test_element_filter(self):
        """测试元素过滤"""
        data = self._create_quartz_data()
        service = ProfileFittingService()

        # 必须含 Si
        results_must_si = service.identify(
            data, element_filter={"must": ["Si"]}, top_n=5, fwhm=0.15
        )
        for r in results_must_si:
            assert "Si" in r.phase.elements

        # 排除含 Fe 的物相
        results_no_fe = service.identify(
            data, element_filter={"exclude": ["Fe"]}, top_n=5, fwhm=0.15
        )
        for r in results_no_fe:
            assert "Fe" not in r.phase.elements

    def test_background_estimation(self):
        """测试背景估计"""
        two_theta = np.linspace(10, 80, 1000)
        # 纯背景数据（无峰）
        intensity = 50 + 0.3 * two_theta + np.random.normal(0, 2, 1000)
        data = XRDData(two_theta=two_theta, intensity=intensity)

        service = ProfileFittingService()
        bg = service._estimate_background(data, 50)

        assert len(bg) == len(intensity)
        assert np.all(bg >= 0)
        # 背景应大致跟随数据趋势
        assert abs(np.mean(bg) - np.mean(intensity)) < 20

    def test_theoretical_profile_generation(self):
        """测试理论图谱生成"""
        two_theta = np.linspace(15, 80, 2000)
        phase = self._create_test_phase()
        service = ProfileFittingService()

        profile = service._generate_theoretical_profile(phase, two_theta, fwhm=0.15)

        assert len(profile) == len(two_theta)
        assert np.any(profile > 0)  # 应该有非零值
        assert np.all(profile >= 0)  # 不应有负值

    def test_pearson_correlation(self):
        """测试Pearson相关系数计算"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([2, 4, 6, 8, 10])

        r = ProfileFittingService._pearson_correlation(x, y)
        assert abs(r - 1.0) < 0.001  # 完全正相关

        y_neg = np.array([-1, -2, -3, -4, -5])
        r_neg = ProfileFittingService._pearson_correlation(x, y_neg)
        assert abs(r_neg - (-1.0)) < 0.001  # 完全负相关

    def test_r_factor(self):
        """测试R因子计算"""
        exp = np.array([100, 200, 150, 300])
        calc = np.array([100, 200, 150, 300])

        r = ProfileFittingService._r_factor(exp, calc)
        assert r < 0.01  # 完全匹配时 R ≈ 0

        calc2 = np.array([50, 100, 75, 150])
        r2 = ProfileFittingService._r_factor(exp, calc2)
        assert r2 > 0.3  # 不匹配时 R 较大

    def test_normalize(self):
        """测试归一化"""
        arr = np.array([10, 20, 30, 40, 50])
        norm = ProfileFittingService._normalize(arr)

        assert abs(norm.min() - 0.0) < 0.01
        assert abs(norm.max() - 1.0) < 0.01

    def test_score_range(self):
        """测试分数范围 (0-100)"""
        data = self._create_quartz_data()
        service = ProfileFittingService()

        results = service.identify(data, top_n=5, fwhm=0.15)

        for r in results:
            assert 0 <= r.score <= 100
            assert r.r_factor >= 0

    def test_fwhm_effect(self):
        """测试不同FWHM的影响"""
        data = self._create_quartz_data()
        service = ProfileFittingService()

        narrow = service.identify(data, top_n=3, fwhm=0.08)
        wide = service.identify(data, top_n=3, fwhm=0.30)

        # 两种 FWHM 都应该返回结果
        assert len(narrow) > 0
        assert len(wide) > 0
