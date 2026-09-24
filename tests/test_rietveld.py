"""
Rietveld精修测试
"""
import numpy as np
import pytest

from polyxrd.i18n import tr
from polyxrd.models.xrd_data import XRDData
from polyxrd.models.phase import Phase, LatticeParams
from polyxrd.services.rietveld_refiner import RietveldRefiner


class TestRietveldRefiner:
    """Rietveld精修测试"""

    def _create_test_data(self):
        """创建测试数据"""
        two_theta = np.linspace(20, 100, 2000)
        intensity = np.zeros_like(two_theta)

        # 添加一些峰
        peaks = [
            (28.44, 800, 0.12),
            (47.30, 600, 0.15),
            (56.11, 400, 0.12),
        ]
        for center, amp, sigma in peaks:
            intensity += amp * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)

        intensity += np.random.normal(0, 5, len(two_theta))
        intensity = np.maximum(intensity, 0)

        return XRDData(two_theta=two_theta, intensity=intensity)

    def _create_test_phase(self):
        """创建测试物相"""
        return Phase(
            name="Test Phase",
            formula="Si",
            lattice=LatticeParams(
                a=5.431, b=5.431, c=5.431,
                alpha=90.0, beta=90.0, gamma=90.0,
            ),
            weight_fraction=100.0,
            reference_peaks=[
                ((1, 1, 1), 28.44, 800),
                ((2, 2, 0), 47.30, 600),
                ((3, 1, 1), 56.11, 400),
            ],
        )

    def test_builtin_refinement(self):
        """测试内置精修引擎"""
        data = self._create_test_data()
        phase = self._create_test_phase()
        refiner = RietveldRefiner()

        result = refiner.refine(
            data, [phase], engine="builtin", max_cycles=3
        )

        assert len(result.phases) == 1
        assert result.phases[0].name == "Test Phase"
        assert result.wR > 0
        assert len(result.observed_data[0]) == len(data.two_theta)
        assert result.simulated_data is not None

    def test_refinement_result_summary(self):
        """测试精修结果摘要"""
        data = self._create_test_data()
        phase = self._create_test_phase()
        refiner = RietveldRefiner()

        result = refiner.refine(data, [phase], engine="builtin", max_cycles=2)

        summary = result.summary()
        # v1.1.1: 报告标题改走 i18n (`report.title`), 文案会随语言变 —— 直接
        # 硬编码中文字符串会因多加一个空格就红, 这里改为校验"摘要用的是本地化标题"。
        assert tr("report.title") in summary
        assert "Rwp" in summary
        assert "Test Phase" in summary

    def test_refinement_result_serialization(self):
        """测试精修结果序列化"""
        data = self._create_test_data()
        phase = self._create_test_phase()
        refiner = RietveldRefiner()

        result = refiner.refine(data, [phase], engine="builtin", max_cycles=2)

        d = result.to_dict()
        restored = type(result).from_dict(d)

        assert len(restored.phases) == len(result.phases)
        assert restored.wR == result.wR

    def test_d_spacing_calculation(self):
        """测试d-spacing计算"""
        a = 5.431  # Si晶格常数
        h, k, l = 1, 1, 1

        refiner = RietveldRefiner()
        d = refiner._calc_d_spacing_from_hkl(a, a, a, 90, 90, 90, h, k, l)

        # Si (111) d-spacing ≈ 3.135 Å
        assert abs(d - 3.135) < 0.01

    def test_wR_calculation(self):
        """测试wR计算"""
        observed = np.array([100, 200, 150, 300])
        simulated = np.array([95, 195, 160, 290])

        refiner = RietveldRefiner()
        wR = refiner._calc_wR(observed, simulated)

        assert wR > 0
        assert wR < 100  # 合理的R因子范围

    def test_builtin_with_peak_shape(self):
        """测试内置引擎支持不同峰形"""
        data = self._create_test_data()
        phase = self._create_test_phase()
        refiner = RietveldRefiner()

        for shape in ["pseudo-voigt", "gaussian", "lorentzian", "voigt"]:
            result = refiner.refine(
                data, [phase], engine="builtin", max_cycles=3,
                peak_shape=shape, fwhm=0.12,
            )
            assert result.wR > 0
            assert result.fit_params["peak_shape"] == shape

    def test_builtin_with_background_method(self):
        """测试内置引擎支持不同背景方法"""
        data = self._create_test_data()
        phase = self._create_test_phase()
        refiner = RietveldRefiner()

        for bg in ["snip", "median", "rolling"]:
            result = refiner.refine(
                data, [phase], engine="builtin", max_cycles=3,
                bg_method=bg,
            )
            assert result.wR > 0
            assert result.fit_params["bg_method"] == bg

    def test_builtin_multi_phase(self):
        """测试内置引擎多物相精修"""
        data = self._create_test_data()
        phase1 = self._create_test_phase()

        phase2 = Phase(
            name="Second Phase",
            formula="SiO2",
            lattice=LatticeParams(a=4.9, b=4.9, c=5.4),
            weight_fraction=50.0,
            reference_peaks=[
                ((1, 0, 0), 20.0, 300),
                ((1, 1, 0), 33.0, 200),
            ],
        )

        refiner = RietveldRefiner()
        result = refiner.refine(
            data, [phase1, phase2], engine="builtin", max_cycles=5,
        )

        assert len(result.phases) == 2
        assert result.wR > 0
        for p in result.phases:
            assert p.weight_fraction >= 0

    def test_builtin_quality_grade(self):
        """测试内置引擎质量等级"""
        data = self._create_test_data()
        phase = self._create_test_phase()
        refiner = RietveldRefiner()

        result = refiner.refine(
            data, [phase], engine="builtin", max_cycles=3,
        )
        # v1.1.2: 质量分级统一到 models.refinement.quality_grade_for
        # (实验室粉末 XRD 口径: 优秀/良好/一般/差/很差), 引擎内部不再另写一套
        from polyxrd.models.refinement import quality_grade_for
        assert result.quality == quality_grade_for(result.wR)
        assert result.quality in ["优秀", "良好", "一般", "差", "很差"]

class TestExternalEngines:
    """外部引擎测试 (powerxrd v4 已装; GSAS-II 需独立安装)"""

    def _make_cubic_si(self):
        """合成立方 Si 单相谱 (a=5.431)"""
        import numpy as np
        from polyxrd.models.xrd_data import XRDData

        wl, a0 = 1.5406, 5.431
        tt = np.linspace(15, 90, 3000)
        sigma = 0.15 / 2.3548
        y = np.full_like(tt, 40.0)
        for hkl, inten in [((1, 1, 1), 100), ((2, 2, 0), 60),
                           ((3, 1, 1), 35), ((4, 0, 0), 15), ((3, 3, 1), 12)]:
            d = a0 / np.sqrt(sum(h * h for h in hkl))
            p = 2 * np.degrees(np.arcsin(wl / (2 * d)))
            y += inten * np.exp(-0.5 * ((tt - p) / sigma) ** 2)
        return XRDData(two_theta=tt, intensity=y, wavelength=wl)

    def test_powerxrd_engine_cubic_si(self):
        """powerxrd v4 引擎: 立方 Si 单相精修 a 应收敛到真值"""
        import pytest
        try:
            from powerxrd.refine import refine  # noqa: F401
        except ImportError:
            pytest.skip("powerxrd 未安装")
        from polyxrd.models.phase import LatticeParams, Phase
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        data = self._make_cubic_si()
        phase = Phase(name="Silicon", formula="Si",
                      lattice=LatticeParams(a=5.431, b=5.431, c=5.431))
        result = RietveldRefiner().refine(data, [phase], engine="powerxrd", max_cycles=20)

        assert result.fit_params.get("engine") == "powerxrd", "应真实调用 powerxrd 而非回退内置"
        refined_a = result.fit_params.get("refined_a", 0.0)
        assert abs(refined_a - 5.431) < 0.01, f"a={refined_a:.4f} 偏离真值"
        assert result.wR < 30.0

    def test_powerxrd_fallback_non_cubic(self):
        """powerxrd 不支持非立方: 应自动回退内置引擎 (不抛异常)"""
        from polyxrd.models.phase import LatticeParams, Phase
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        data = self._make_cubic_si()
        # 六方晶胞 (非立方) → powerxrd 不可用 → 回退内置
        phase = Phase(name="Hex", formula="AB",
                      lattice=LatticeParams(a=3.2, b=3.2, c=5.2,
                                            alpha=90.0, beta=90.0, gamma=120.0))
        result = RietveldRefiner().refine(data, [phase], engine="powerxrd", max_cycles=3)
        assert result.fit_params.get("engine") == "builtin", "非立方应回退内置引擎"
        assert result.wR >= 0

    def test_gsas2_engine_cubic_si_recovery(self):
        """GSAS-II 桥: 立方 Si 从 a=5.30 (偏离真值 2.4%) 应恢复收敛到 a≈5.431。

        桥 v2 具备: 数据 FWHM -> 匹配仪器峰形; 峰位定种 (立方, 空间群
        消光序列对齐); 尺度网格多起点评分; 4x10 轮 Cell 精修。此测试
        走完整 PolyXRD 子进程链路 (engine='gsas2'), GSAS-II 缺失时跳过。
        """
        refiner = RietveldRefiner()
        py = refiner._find_gsas2_python()
        if py is None:
            pytest.skip("GSAS-II 未安装")
        phase = Phase(name="Silicon", formula="Si", space_group="F d -3 m",
                      lattice=LatticeParams(a=5.30, b=5.30, c=5.30))
        result = refiner.refine(self._make_cubic_si(), [phase],
                                engine="gsas2", max_cycles=40)

        assert result.fit_params.get("engine") == "gsas2", "应真实调用 GSAS-II 而非回退内置"
        refined_a = result.phases[0].lattice.a
        assert abs(refined_a - 5.431) < 0.01, f"a={refined_a:.4f} 偏离真值"
        assert result.wR < 15.0, f"wR={result.wR:.2f} 过高"
        assert result.quality in ("优秀", "良好"), result.quality
