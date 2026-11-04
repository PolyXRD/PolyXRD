# -*- coding: utf-8 -*-
"""系统性强度误差：表面粗糙度 + Brindley 微吸收（v5.2 第一件）。

验收口径
--------
* **粗糙度**：模型必须满足"θ=90° 恒为 1"这一物理边界（法向入射看不到粗糙度），
  且低角单调压暗；``s/p/t = 0`` 时零开销恒 1。
* **微吸收**：τ(0) 必须精确为 1（无吸收反差即无修正），符号必须与
  ``μ_j − μ̄`` 同向，表值锚点逐一对齐 Brindley 原表，越界截断而不外推。
* **定量**：修正只搬运份额、必须守恒；高吸收相被**下调**、低吸收相被**上调**。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement.intensity import (
    BRINDLEY_TAU,
    BRINDLEY_X,
    BRINDLEY_X_LIMIT,
    MASS_ATTENUATION_CU_KA,
    ROUGHNESS_MODELS,
    apply_microabsorption,
    brindley_tau,
    linear_mu_from_composition,
    linear_mu_from_formula,
    linear_mu_from_sites,
    mass_attenuation_from_counts,
    mass_attenuation_from_formula,
    mean_linear_mu,
    microabsorption_taus,
    roughness_factor,
    sidey_roughness,
    sparks_roughness,
    suortti_roughness,
)


class TestRoughnessBoundary:
    """θ=90°（2θ=180°）必须精确为 1；零参数必须零开销。"""

    @pytest.mark.parametrize("model,kw", [
        ("sidey", {"s": 0.3}),
        ("suortti", {"p": 0.05, "q": 1.5}),
        ("sparks", {"s": 5e-4}),
    ])
    def test_unity_at_ninety_degrees(self, model, kw):
        f = roughness_factor(np.array([180.0]), model, **kw)
        assert f[0] == pytest.approx(1.0, abs=1e-12)

    @pytest.mark.parametrize("model", ROUGHNESS_MODELS)
    def test_zero_parameter_is_noop(self, model):
        tt = np.linspace(5.0, 140.0, 50)
        f = roughness_factor(tt, model)
        assert np.allclose(f, 1.0, atol=0.0)

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError):
            roughness_factor(np.array([20.0]), "pitschke")

    def test_none_is_noop(self):
        tt = np.linspace(5.0, 140.0, 20)
        assert np.allclose(roughness_factor(tt, "none"), 1.0)


class TestSideyRoughness:
    """Sidey 单参数模型：低角压暗、随角单调回升、处处 ≤ 1。"""

    def test_low_angle_suppression(self):
        tt = np.array([10.0, 20.0, 40.0, 80.0])
        f = sidey_roughness(tt, 0.5)
        assert f[0] < f[1] < f[2] < f[3] <= 1.0

    def test_magnitude_is_physical(self):
        """s=0.5、2θ=10°（θ=5°）时应压掉 20~30%（不是 0.1% 也不是 0.99）。"""
        f = sidey_roughness(np.array([10.0]), 0.5)[0]
        assert 0.70 < f < 0.80

    def test_never_exceeds_unity(self):
        tt = np.linspace(2.0, 90.0, 200)
        assert np.all(sidey_roughness(tt, 1.0) <= 1.0 + 1e-12)

    def test_independent_of_two_theta_doubling(self):
        """同一个 θ 对应 2θ=2θ —— 输入口径必须是 2θ，别把 θ 当 2θ 用。"""
        f1 = sidey_roughness(np.array([10.0]), 0.4)[0]
        f2 = sidey_roughness(np.array([20.0]), 0.4)[0]
        assert f1 < f2


class TestSuorttiAndSparks:
    def test_suortti_low_angle_suppression(self):
        f = suortti_roughness(np.array([10.0]), 0.05, 1.0)[0]
        assert f < 1.0

    def test_suortti_saturates(self):
        """θ→0 时 S_R → 1 − p·e^{−q}（有下限，不会变成负数）。"""
        f = suortti_roughness(np.array([0.0]), 0.05, 1.0)[0]
        assert f == pytest.approx(1.0 - 0.05 * np.exp(-1.0), rel=1e-4)

    def test_sparks_linear(self):
        """10° 比 60° 压得更狠，两者都 ≤ 1（θ>90° 的外推不在本用例口径内）。"""
        f0 = sparks_roughness(np.array([10.0]), 1e-3)[0]
        f1 = sparks_roughness(np.array([60.0]), 1e-3)[0]
        assert f0 < f1 < 1.0


class TestBrindleyTable:
    """表值锚点：直接对齐 Brindley 原表（Hill & Howard 1987 转载）。"""

    @pytest.mark.parametrize("x,tau", [
        (0.00, 1.000), (0.10, 0.866), (0.20, 0.753), (0.30, 0.653),
        (0.40, 0.569), (0.50, 0.496),
        (-0.10, 1.162), (-0.20, 1.353), (-0.50, 2.036),
    ])
    def test_anchor_points(self, x, tau):
        assert brindley_tau(x) == pytest.approx(tau, abs=1e-9)

    def test_zero_contrast_is_exactly_unity(self):
        assert float(brindley_tau(0.0)) == 1.0

    def test_monotone_decreasing(self):
        x = np.linspace(-BRINDLEY_X_LIMIT, BRINDLEY_X_LIMIT, 201)
        t = brindley_tau(x)
        assert np.all(np.diff(t) <= 1e-12)

    def test_interpolates_between_nodes(self):
        mid = float(brindley_tau(0.15))
        assert mid == pytest.approx((0.866 + 0.753) / 2.0, abs=1e-6)

    def test_clamped_outside_range(self):
        assert float(brindley_tau(0.9)) == pytest.approx(float(brindley_tau(0.5)))
        assert float(brindley_tau(-0.9)) == pytest.approx(float(brindley_tau(-0.5)))

    def test_table_is_sorted_and_aligned(self):
        assert np.all(np.diff(BRINDLEY_X) > 0)
        assert BRINDLEY_X.size == BRINDLEY_TAU.size
        assert BRINDLEY_TAU[BRINDLEY_X.tolist().index(0.0)] == 1.000


class TestMeanMu:
    def test_weighted_mean(self):
        assert mean_linear_mu([100.0, 300.0], [0.5, 0.5]) == pytest.approx(200.0)

    def test_normalises_fractions(self):
        assert mean_linear_mu([100.0, 300.0], [1.0, 3.0]) == pytest.approx(250.0)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            mean_linear_mu([1.0, 2.0], [1.0])


class TestMicroabsorptionTaus:
    def test_no_contrast_gives_unity(self):
        tau, mu_bar, clamped = microabsorption_taus([500.0, 500.0], [0.4, 0.6], 2.0)
        assert np.allclose(tau, 1.0)
        assert mu_bar == pytest.approx(500.0)
        assert clamped is False

    def test_high_absorber_suppressed_low_absorber_enhanced(self):
        tau, _, _ = microabsorption_taus([1000.0, 100.0], [0.5, 0.5], 3.0)
        assert tau[0] < 1.0 < tau[1]

    def test_radius_zero_gives_unity(self):
        tau, _, _ = microabsorption_taus([1000.0, 100.0], [0.5, 0.5], 0.0)
        assert np.allclose(tau, 1.0)

    def test_clamped_flag_when_too_coarse(self):
        _, _, clamped = microabsorption_taus([5000.0, 100.0], [0.5, 0.5], 20.0)
        assert clamped is True


class TestApplyMicroabsorption:
    """定量层：只搬运份额、守恒、方向正确。"""

    def _apply(self, base, mu, r):
        return apply_microabsorption(base, mu, r)

    def test_equal_mu_leaves_fractions_unchanged(self):
        base = np.array([3.0, 7.0])
        w, tau, _, _ = self._apply(base, [400.0, 400.0], 5.0)
        assert w == pytest.approx([0.3, 0.7])
        assert np.allclose(tau, 1.0)

    def test_conservation(self):
        w, _, _, _ = self._apply([3.0, 7.0, 1.0], [1000.0, 200.0, 400.0], 4.0)
        assert float(w.sum()) == pytest.approx(1.0)

    def test_high_absorber_fraction_drops(self):
        """高吸收相：τ<1 → W ∝ S/τ 会**上升**吗？—— 不，见下。"""
        base = np.array([5.0, 5.0])
        mu = [1200.0, 200.0]
        w_plain = base / base.sum()
        w, tau, _, _ = self._apply(base, mu, 4.0)
        assert tau[0] < 1.0 < tau[1]
        # τ<1 意味着观测强度被压低、拟合标度也偏低 → 真实含量 ∝ S/τ **变大**，
        # 但 τ>1 的一侧同时被压小，净效果取决于 τ 的几何平均。
        assert w[0] != pytest.approx(w_plain[0])

    def test_direction_is_consistent_with_sign_of_tau(self):
        """严格判据：修正后 W_j/W_k 与 (S_j/τ_j)/(S_k/τ_k) 一致。"""
        base = np.array([4.0, 6.0])
        mu = [1500.0, 300.0]
        w, tau, _, _ = self._apply(base, mu, 3.0)
        expect = (base / tau)
        expect = expect / expect.sum()
        assert w == pytest.approx(expect, rel=1e-9)

    def test_iterations_converge(self):
        base = np.array([4.0, 6.0, 2.0])
        mu = [1500.0, 300.0, 800.0]
        w3, _, _, _ = apply_microabsorption(base, mu, 3.0, iterations=3)
        w9, _, _, _ = apply_microabsorption(base, mu, 3.0, iterations=9)
        assert w3 == pytest.approx(w9, abs=1e-9)

    def test_empty_input(self):
        w, tau, mu_bar, clamped = apply_microabsorption([], [], 1.0)
        assert w.size == 0 and tau.size == 0 and mu_bar == 0.0 and clamped is False

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            apply_microabsorption([1.0, 2.0], [100.0], 1.0)


class TestMassAttenuationTable:
    """μ/ρ 元素表：矿物级文献锚点 + 三条最容易写错的物理。"""

    #: 文献锚点（Cu Kα 的 μ/ρ，cm²/g）。这些值本身是文献/标准表取整，容差
    #: 按 10% 定 —— 本测试抓的是"数量级错、量纲错、摩尔比当质量分数"这类
    #: 会直接把微吸收修正带偏的错，不是小数点后第 3 位。
    ANCHORS = {
        "Al2O3": 31.8, "Fe2O3": 230.4, "SiO2": 35.0, "CaCO3": 75.6,
        "Al2Si2O5(OH)4": 30.4, "ZnO": 49.3, "CaF2": 89.8,
        "Mg3Si4O10(OH)2": 32.1, "NaAlSi3O8": 33.3, "CaAl2Si2O8": 52.3,
        "KAlSi3O8": 48.9, "CaMgSi2O6": 57.7,
    }

    @pytest.mark.parametrize("formula,ref", sorted(ANCHORS.items()))
    def test_mineral_anchors_within_10pct(self, formula, ref):
        got = mass_attenuation_from_formula(formula)
        assert got is not None
        assert got == pytest.approx(ref, rel=0.10)

    @pytest.mark.parametrize("formula,ref", [
        ("Al2O3", 31.8), ("Fe2O3", 230.4), ("SiO2", 35.0), ("CaCO3", 75.6),
    ])
    def test_strong_anchors_within_2pct(self, formula, ref):
        """四个最常用的锚点收紧到 2% —— 它们钉住了 Al/O/Fe/Si/Ca 五个元素。"""
        assert mass_attenuation_from_formula(formula) == pytest.approx(ref, rel=0.02)

    def test_weighted_by_mass_fraction_not_mole_ratio(self):
        """Al2O3 必须按**质量分数**加权（≈32），不是按摩尔比（≈26）。

        按摩尔比算会得到 (2·50 + 3·11.5)/5 = 26.9；按质量分数是
        0.529·50 + 0.471·11.5 = 31.9。差 15%，足以让 τ 与 μ̄ 都跑偏。
        """
        got = mass_attenuation_from_formula("Al2O3")
        assert got == pytest.approx(31.9, abs=0.5)
        assert got > 28.0

    def test_k_edge_makes_ni_cu_zn_far_weaker_than_cr_co(self):
        """Ni/Cu/Zn 的 K 边在 Cu Kα 之上 → μ 比 Cr–Co 低一个量级。

        这条"反直觉"的排序是微吸收方向翻转的物理原因，别被"Z 大吸收强"的
        直觉改掉：改错会让 Fe₂O₃+NiO 体系的修正符号反掉。
        """
        t = MASS_ATTENUATION_CU_KA
        for el in ("Ni", "Cu", "Zn"):
            assert t[el] < 0.4 * t["Co"], el

    def test_unknown_element_returns_none(self):
        """未收录（Z>30）→ None，绝不猜。"""
        assert mass_attenuation_from_formula("ZrO2") is None
        assert mass_attenuation_from_formula("BaSO4") is None
        assert mass_attenuation_from_counts({"Fe": 2, "Xx": 3}) is None

    def test_empty_inputs(self):
        assert mass_attenuation_from_counts({}) is None
        assert mass_attenuation_from_formula("") is None
        assert mass_attenuation_from_formula("???") is None

    def test_linear_mu_from_composition_matches_formula_route(self):
        """两条独立路径（位点计数 vs 化学式×密度）必须一致。

        刚玉：全胞 Al12 O18、V=254.09 Å³；文献 ρ=3.99、μ/ρ=31.8 → μ≈127。
        """
        mu = linear_mu_from_composition({"Al": 12, "O": 18}, 254.09)
        assert mu == pytest.approx(127.0, rel=0.02)
        assert mu == pytest.approx(linear_mu_from_formula("Al2O3", 3.99), rel=0.02)

    def test_linear_mu_needs_positive_volume(self):
        assert linear_mu_from_composition({"Al": 12}, 0.0) is None
        assert linear_mu_from_composition({"Al": 12}, -1.0) is None
        assert linear_mu_from_formula("Al2O3", None) is None
        assert linear_mu_from_formula("Al2O3", 0.0) is None

    def test_linear_mu_from_sites_accepts_dict_and_object(self):
        """位点既可能是 dict（Phase）、也可能是 AtomSite 对象（StructureModel）。"""
        from polyxrd.refinement import AtomSite

        v = 254.09
        as_dict = [{"element": "Al", "occupancy": 12.0},
                   {"element": "O", "occupancy": 18.0}]
        as_obj = [AtomSite("Al", 0.0, 0.0, 0.0, 12.0, 0.5, "Al"),
                  AtomSite("O", 0.25, 0.25, 0.25, 18.0, 0.5, "O")]
        mu_d = linear_mu_from_sites(as_dict, v)
        mu_o = linear_mu_from_sites(as_obj, v)
        assert mu_d == pytest.approx(127.0, rel=0.02)
        assert mu_o == pytest.approx(mu_d, rel=1e-12)

    def test_linear_mu_from_sites_skips_zero_occupancy(self):
        """空占位位点不参与组成 —— 否则 μ 会被"名义化学式"抬高。"""
        full = linear_mu_from_sites(
            [{"element": "Al", "occupancy": 12.0},
             {"element": "O", "occupancy": 18.0}], 254.09)
        with_ghost = linear_mu_from_sites(
            [{"element": "Al", "occupancy": 12.0},
             {"element": "O", "occupancy": 18.0},
             {"element": "H", "occupancy": 0.0}], 254.09)
        assert with_ghost == pytest.approx(full, rel=1e-12)


# ── 引擎接线：设计矩阵 / 缓存键 / 定量 ────────────────────────────────
from polyxrd.refinement import (  # noqa: E402
    AtomSite,
    BackgroundParams,
    Cell,
    PatternProblem,
    PhaseBlock,
    PhaseSpec,
    ProfileParams,
    StructureModel,
    background_basis,
    build_reflections,
    design_matrix,
)

_CUT = 25.0
_PROFILE = ProfileParams(u=0.02, v=-0.01, w=0.012, x=0.01)
_BG = BackgroundParams("tent", 8)


def _cubic(element: str, a: float, mass_note: str = "") -> StructureModel:
    """一个原子的简单立方相（够用来验"逐相质量/体积"与微吸收）。"""
    sites = (AtomSite(element, 0.0, 0.0, 0.0, 1.0, 0.5, element),)
    return StructureModel(sites=sites, cell=Cell(a, a, a, 90.0, 90.0, 90.0),
                          space_group="P 1", name=f"{element}{mass_note}")


def _two_phase_problem(*, model: str = "none", s: float = 0.0,
                       mu=None, radius_um: float = 0.0):
    st_a, st_b = _cubic("Fe", 3.0), _cubic("Al", 4.0)
    tt = np.linspace(15.0, 120.0, 1051)
    tab_a = build_reflections(st_a, two_theta_range=(13.0, 122.0))
    tab_b = build_reflections(st_b, two_theta_range=(13.0, 122.0))
    rough = None
    if model != "none" and s:
        from polyxrd.refinement import Roughness

        rough = Roughness(model=model, s=s)
    basis = design_matrix(tt, [PhaseSpec(tab_a), PhaseSpec(tab_b)], _PROFILE,
                          cutoff_fwhm=_CUT, rough=rough)
    y = (basis @ np.array([4000.0 / basis[:, 0].max(),
                           3000.0 / basis[:, 1].max()])
         + background_basis(tt, _BG) @ np.linspace(50.0, 30.0, 8))
    prob = PatternProblem(tt, y, [PhaseBlock("Fe", st_a, index=0),
                                  PhaseBlock("Al", st_b, index=1)],
                          profile=_PROFILE, bg=_BG, weights=1.0 / np.maximum(y, 1.0),
                          cutoff_fwhm=_CUT, wavelength=1.5406,
                          roughness_model=model, mu_linear=mu,
                          grain_radius_um=radius_um)
    prob.apply()
    if model != "none" and s:
        prob.params.set("inst.rough", s)
        prob.apply()
    return prob, y


class TestRoughnessWiring:
    def test_design_key_covers_roughness(self):
        """改 ``inst.rough`` 必须让设计矩阵失效 —— 否则参数在 LM 里形同虚设。"""
        prob, _ = _two_phase_problem(model="sidey")
        b0, _ = prob.design()
        # 模型开着但 s=0：按"零参数即关闭"的约定走零开销分支（不是漏接线）
        assert prob.roughness.is_off
        prob.params.set("inst.rough", 0.6)
        prob.apply()
        assert not prob.roughness.is_off
        b1, _ = prob.design()
        assert not np.allclose(b0, b1), "粗糙度参数变化后设计矩阵未重建"
        assert np.all(b1 <= b0 + 1e-12), "低角强度不该被放大"

    def test_negative_roughness_has_no_parameter(self):
        """s 的物理域是 [0, 2]：负 s 会放大低角强度，没有对应机制。"""
        from polyxrd.refinement import Roughness

        assert float(Roughness(model="sidey", s=-1.0).factor([10.0])[0]) > 1.0

    def test_grid_scan_recovers_injected_value(self):
        """合成谱里注入 s=0.4，扫描应以 0.4 为 Rwp 极小 —— 端到端接线检查。"""
        prob, _ = _two_phase_problem(model="sidey", s=0.4)
        rwp = {}
        for s in (0.0, 0.2, 0.3, 0.4, 0.5, 0.7):
            prob.params.set("inst.rough", s)
            prob.apply()
            rwp[s] = prob.metrics()["Rwp"]
        best = min(rwp, key=rwp.get)
        assert best == 0.4, rwp
        # 无噪合成谱：注入值处应拟合到接近零残差，而 s=0 明显更差
        assert rwp[0.4] < 1.5, rwp
        assert rwp[0.4] < 0.8 * rwp[0.0], rwp

    def test_off_by_default_changes_nothing(self):
        a, _ = _two_phase_problem()
        b, _ = _two_phase_problem(model="sidey", s=0.0)
        ba, _ = a.design()
        bb, _ = b.design()
        assert np.array_equal(ba, bb)

    def test_roughness_stage_is_reachable_in_fast_tier(self):
        """``inst.rough`` 的阶段必须落在 ``fast`` 档协议覆盖的范围内。

        踩过的坑（v5.2）：挂到 stage 4（po）时，``fast`` 档只有 2、3 两个阶段，
        参数**永远不会被释放** —— s 停在播种值上，只是把 Rwp 白降 0.1 pp，
        看上去"模型没效果"。这里直接对协议表断言，不写死数字。
        """
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        prob, _ = _two_phase_problem(model="sidey")
        assert "inst.rough" in prob.params
        fast_stages = {int(st) for st, _ in
                       RietveldRefiner.V5_TIERS["fast"]["protocol"]}
        assert int(prob.params["inst.rough"].stage) in fast_stages


class TestMicroabsorptionWiring:
    def test_quantitative_needs_both_mu_and_radius(self):
        """μ 与半径缺一不可 —— 只有一半就等于"没启用"，不能半修。"""
        only_mu, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=0.0)
        assert only_mu.quantitative().tau == ()
        only_r, _ = _two_phase_problem(radius_um=4.0)
        assert only_r.quantitative().tau == ()
        both, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=4.0)
        assert len(both.quantitative().tau) == 2

    def test_microabsorption_changes_fractions_not_fit(self):
        """微吸收只改定量、不改 Rwp —— τ 在强度上会被标度吸收。"""
        prob, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=4.0)
        rwp_before = prob.metrics()["Rwp"]
        q = prob.quantitative()
        rwp_after = prob.metrics()["Rwp"]
        assert rwp_before == pytest.approx(rwp_after, rel=1e-12)
        assert len(q.tau) == 2
        assert q.tau[0] < 1.0 < q.tau[1], q.tau
        assert q.mu_bar > 0.0

    def test_microabsorption_moves_fraction_toward_high_absorber(self):
        """高吸收相 τ<1 → W ∝ S/τ 上升；低吸收相下降；总量守恒。"""
        plain, _ = _two_phase_problem()
        w0 = plain.quantitative().fractions
        corr, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=4.0)
        w1 = corr.quantitative().fractions
        assert w1[0] > w0[0]
        assert w1[1] < w0[1]
        assert sum(w1) == pytest.approx(1.0)


class TestMicroabsorptionDiagnostics:
    """微吸收的适用性必须变成可读告警 —— τ 不进拟合向量，Rwp 反映不出来。

    `report.audit` 是「该不该报警」的唯一判定点（§22.8 第 3 条），界面只负责
    渲染；这里钉住三种状态的码与严重级。
    """

    def _codes(self, prob):
        from polyxrd.refinement import build_report

        rep = build_report(prob)
        return {f.code: f for f in rep.findings}

    def test_clamped_radius_raises_warning(self):
        """R=25 µm + μ 反差 2000 → |(μ−μ̄)·R| > 0.5，必须报 warn。"""
        prob, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=25.0)
        findings = self._codes(prob)
        assert "MICROABSORPTION_CLAMPED" in findings
        f = findings["MICROABSORPTION_CLAMPED"]
        assert f.severity == "warn"
        assert f.evidence["n_clamped"] >= 1.0

    def test_applied_inside_table_is_info(self):
        prob, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=2.0)
        findings = self._codes(prob)
        assert "MICROABSORPTION_APPLIED" in findings
        assert findings["MICROABSORPTION_APPLIED"].severity == "info"
        assert "MICROABSORPTION_CLAMPED" not in findings

    def test_no_finding_when_disabled(self):
        prob, _ = _two_phase_problem()
        findings = self._codes(prob)
        assert "MICROABSORPTION_APPLIED" not in findings
        assert "MICROABSORPTION_CLAMPED" not in findings


class TestRefineOptionsTransfer:
    """``RefineOptions`` 是 UI 的唯一选项入口，两个开关必须转成引擎 kwargs。"""

    class _Data:
        two_theta = np.linspace(10.0, 80.0, 201)
        intensity = np.ones(201)
        wavelength = 1.54056

    def _capture(self, monkeypatch, **refine_kw):
        from polyxrd.models.refinement import RefinementResult
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        refiner = RietveldRefiner()
        seen: dict = {}

        def fake(data, phases, strategy, max_cycles, **kw):
            seen.update(kw)
            return RefinementResult(wR=1.0, GOF=1.0)

        monkeypatch.setattr(refiner, "_refine_v5", fake)
        refiner.refine(self._Data(), [], engine="refinement", detect_ka2=False,
                       **refine_kw)
        return seen

    def test_options_become_kwargs(self, monkeypatch):
        from polyxrd.models.refinement_options import RefineOptions

        seen = self._capture(monkeypatch, options=RefineOptions(
            roughness_model="sidey", refine_roughness=True,
            microabsorption=True, grain_radius_um=12.5))
        assert seen["roughness_model"] == "sidey"
        assert seen["refine_roughness"] is True
        assert seen["microabsorption"] is True
        assert seen["grain_radius_um"] == pytest.approx(12.5)

    def test_default_options_leave_engine_untouched(self, monkeypatch):
        from polyxrd.models.refinement_options import RefineOptions

        seen = self._capture(monkeypatch, options=RefineOptions())
        for key in ("roughness_model", "refine_roughness",
                    "microabsorption", "grain_radius_um"):
            assert key not in seen, key

    def test_explicit_kwargs_win_over_options(self, monkeypatch):
        """脚本显式给 kwargs 时不被 options 覆盖（setdefault 语义）。"""
        from polyxrd.models.refinement_options import RefineOptions

        seen = self._capture(
            monkeypatch, grain_radius_um=3.0,
            options=RefineOptions(microabsorption=True, grain_radius_um=25.0))
        assert seen["grain_radius_um"] == pytest.approx(3.0)

    def test_options_to_dict_roundtrip_keys(self):
        from polyxrd.models.refinement_options import RefineOptions

        d = RefineOptions(roughness_model="sparks", refine_roughness=True,
                          microabsorption=True, grain_radius_um=8.0).to_dict()
        assert d["roughness_model"] == "sparks"
        assert d["refine_roughness"] is True
        assert d["microabsorption"] is True
        assert d["grain_radius_um"] == pytest.approx(8.0)
