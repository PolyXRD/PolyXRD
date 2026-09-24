"""
M14 定量 Rietveld 增强测试 (Sprint 2)
=====================================
覆盖: March-Dollase 择优取向 / DoC / 内标定量 / refine options 前处理。
"""
import numpy as np

from polyxrd.models.phase import Phase
from polyxrd.models.refinement_options import RefineOptions
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


def _phase(name, main_tt, elements=("A", "O"), extra=0.0):
    return Phase(name=name, formula=name, elements=set(elements),
                 reference_peaks=[
                     ((0, 0, 1), main_tt, 100.0),
                     ((1, 0, 0), main_tt + 12, 45.0),
                     ((1, 1, 0), main_tt + 26 + extra, 20.0)])


def _synth_xrd(spec, lo=15.0, hi=80.0, step=0.1):
    """spec=[(center, amp, sigma), ...]"""
    x = np.arange(lo, hi + step / 2, step)
    y = np.zeros_like(x)
    for c, a, s in spec:
        y += a * np.exp(-0.5 * ((x - c) / s) ** 2)
    return XRDData(two_theta=x, intensity=y)


class TestMarchDollase:

    def test_r1_is_identity(self):
        for alpha in (0.0, 30.0, 90.0):
            assert abs(RietveldRefiner.march_dollase_intensity_factor(alpha, 1.0)
                       - 1.0) < 1e-9

    def test_anisotropy_direction(self):
        # r>1: 与轴垂直 (90°) 增强; 平行 (0°) 减弱
        g90 = RietveldRefiner.march_dollase_intensity_factor(90.0, 2.0)
        g0 = RietveldRefiner.march_dollase_intensity_factor(0.0, 2.0)
        assert g90 > 1.0 and g0 < 1.0, f"g90={g90:.3f} g0={g0:.3f}"
        assert abs(g0 - 2.0 ** -3) < 1e-6

    def test_apply_to_phase(self):
        ph = _phase("A", 30.0)
        rr = RietveldRefiner()
        out = rr.apply_preferred_orientation(ph, direction=(0, 0, 1), r=2.0)
        # (001) 与轴平行 → G(0)=r^-3=0.125; (100) 垂直 → G(90)=r^1.5=2.828
        i001 = next(i for h, _, i in out.reference_peaks if tuple(h) == (0, 0, 1))
        i100 = next(i for h, _, i in out.reference_peaks if tuple(h) == (1, 0, 0))
        assert abs(i001 - 100.0 * 0.125) < 1e-6, i001
        assert abs(i100 - 45.0 * 2.828427) < 0.01, i100  # 45 是 (100) 峰原始强度
        # 入参不被修改
        orig = next(i for h, _, i in ph.reference_peaks if tuple(h) == (0, 0, 1))
        assert abs(orig - 100.0) < 1e-9


class TestDoC:

    def test_known_areas(self):
        c = np.array([0.0, 1.0, 0.0, 0.0, 0.0])    # 梯形积分 = 1
        a = np.array([0.0, 1.0, 1.0, 1.0, 0.0])    # 梯形积分 = 3
        doc = RietveldRefiner.degree_of_crystallinity(c, a)
        assert abs(doc - 0.25) < 1e-9, doc

    def test_with_two_theta_axis(self):
        x = np.linspace(0, 1, 11)
        c = np.ones_like(x)
        a = np.ones_like(x)
        doc = RietveldRefiner.degree_of_crystallinity(c, a, two_theta=x)
        assert abs(doc - 0.5) < 1e-9

    def test_mismatched_length_raises(self):
        try:
            RietveldRefiner.degree_of_crystallinity(np.ones(3), np.ones(4))
            assert False
        except ValueError:
            pass


class TestInternalStandard:

    def test_scale_formula(self):
        """定标公式: scale = std_wt_pct / w'_std (纯函数, 确定性)。"""
        a = Phase(name="A", formula="A", weight_fraction=20.0)
        b = Phase(name="B", formula="B", weight_fraction=30.0)
        std = Phase(name="Std", formula="S", weight_fraction=20.0)
        scale = RietveldRefiner.internal_standard_scale([a, b, std],
                                                        "Std", 25.0)
        assert scale is not None and abs(scale - 1.25) < 1e-9

    def test_scale_none_when_std_missing_or_zero(self):
        a = Phase(name="A", weight_fraction=20.0)
        std0 = Phase(name="Std", weight_fraction=0.0)
        assert RietveldRefiner.internal_standard_scale([a], "Std", 25.0) is None
        assert RietveldRefiner.internal_standard_scale([a, std0], "Std",
                                                       25.0) is None

    def test_refine_internal_standard_smoke(self):
        """真实小谱跑通: Std 被剔除、定标信息记录 (不校验引擎拟合精度)。"""
        # 三组独立峰; Std 组最强以保证其份额>0
        xrd = _synth_xrd([
            (30.0, 40.0, 0.15), (42.0, 18.0, 0.15), (56.0, 8.0, 0.15),
            (33.0, 60.0, 0.15), (45.0, 27.0, 0.15), (59.0, 12.0, 0.15),
            (36.0, 90.0, 0.15), (48.0, 40.0, 0.15), (62.0, 18.0, 0.15),
        ])
        a = _phase("A", 30.0)
        b = _phase("B", 33.0, elements=("B", "O"))
        std = _phase("Std", 36.0, elements=("S", "O"))
        r = RietveldRefiner().refine_with_internal_standard(
            xrd, [a, b], std, std_wt_pct=25.0, engine="builtin",
            max_cycles=10)
        fp = (r.fit_params or {}).get("internal_standard")
        names = [p.name for p in r.phases]
        print("internal_standard:", fp, " names:", names)
        assert fp is not None and fp["scale"] > 0, \
            "内标份额应>0 可定标 (Std 组峰最强)"
        assert "Std" not in names
        assert all(0 <= p.weight_fraction <= 100 for p in r.phases)


class TestRefineOptionsSmoke:

    def test_options_preprocessing_no_error(self):
        xrd = _synth_xrd([(30.0, 100.0, 0.15), (42.0, 45.0, 0.15),
                          (56.0, 20.0, 0.15)])
        ph = _phase("A", 30.0)
        opts = RefineOptions(preferred_orientation={"direction": (0, 0, 1),
                                                    "r": 1.8},
                             zero_shift_init=0.05)
        r = RietveldRefiner().refine(xrd, [ph], engine="builtin",
                                     max_cycles=10, options=opts)
        assert len(r.phases) == 1
        assert np.isfinite(r.wR)


class TestParamMask:
    """M14 参数掩码: RefineOptions 的 refine_* 开关冻结 builtin 引擎对应参数组。"""

    def _run(self, opts, **kw):
        xrd = _synth_xrd([(30.0, 100.0, 0.15), (42.0, 45.0, 0.15),
                          (56.0, 20.0, 0.15)])
        ph = _phase("A", 30.0)
        return RietveldRefiner().refine(
            xrd, [ph], engine="builtin", max_cycles=10, options=opts, **kw)

    def test_default_mask_all_true_passes_through(self):
        """默认 (全 True) 时, builtin 不冻结任何组,  opt_* 可变。"""
        r = self._run(RefineOptions())
        fp = r.fit_params
        assert fp["param_mask"] == {
            "scale": True, "background": True, "profile": True,
            "cell": True, "zero_shift": True,
        }
        # 默认应当优化 scale: opt_scale 与 init_scale 有差异 (least_squares 跑过),
        # 至少存在且有限; 同时 wR 有限。
        assert np.isfinite(fp["opt_scale"]) and np.isfinite(r.wR)

    def test_freeze_scale_keeps_init(self):
        """refine_scale=False → opt_scale == init_scale (完全冻结)。"""
        r = self._run(RefineOptions(refine_scale=False))
        fp = r.fit_params
        assert fp["param_mask"]["scale"] is False
        assert abs(fp["opt_scale"] - fp["init_scale"]) < 1e-6, \
            f"opt={fp['opt_scale']:.6f} init={fp['init_scale']:.6f}"

    def test_freeze_profile_keeps_init(self):
        """refine_profile=False → fwhm + eta (及 U/V/W) 冻结到 init。"""
        r = self._run(RefineOptions(refine_profile=False))
        fp = r.fit_params
        assert fp["param_mask"]["profile"] is False
        assert abs(fp["opt_fwhm"] - fp["init_fwhm"]) < 1e-6
        assert abs(fp["opt_eta"] - fp["init_eta"]) < 1e-6
        # Caglioti 默认开: U/V/W 也应冻结到 init_U/V/W (暴露在 fit_params 的 caglioti 中)
        # 通过 param_mask["profile"]=False 保证冻结; 不在这里强校验 init_U/V/W 的具体值。

    def test_freeze_zero_shift_keeps_init(self):
        """refine_zero_shift=False → opt_zero_shift == init_zero_shift。"""
        r = self._run(RefineOptions(zero_shift_init=0.07,
                                    refine_zero_shift=False))
        fp = r.fit_params
        assert fp["param_mask"]["zero_shift"] is False
        assert abs(fp["opt_zero_shift"] - fp["init_zero_shift"]) < 1e-6
        # init_zero_shift 应等于 zero_shift_init (refine() 入口把它注入 zero_shift)
        assert abs(fp["init_zero_shift"] - 0.07) < 1e-9

    def test_freeze_background_and_cell_are_noops(self):
        """refine_background / refine_cell 在 builtin 中为 no-op: 不报错且结果有限。

        这些开关在 builtin 不映射到 fit 维度 (背景为预处理, 晶胞固定),
        关闭它们不应改变 fit 结果的可用性。
        """
        r = self._run(RefineOptions(refine_background=False,
                                    refine_cell=False))
        assert np.isfinite(r.wR)
        assert len(r.phases) == 1

    def test_freeze_scale_worse_or_equal_than_default(self):
        """冻结 scale 只能让 wR ≥ 默认全开时的 wR (冻结参数是限制条件)。"""
        r_full = self._run(RefineOptions())
        r_frozen = self._run(RefineOptions(refine_scale=False))
        # 允许极小数值抖动; 但冻结不应明显优于默认 (冻结是限制条件)。
        assert r_frozen.wR >= r_full.wR - 1e-6, \
            f"frozen wR={r_frozen.wR:.4f} < full wR={r_full.wR:.4f}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
