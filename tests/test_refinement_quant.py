"""v5.0.0 阶段 C 验收：约束系统 / Hill–Howard 定量（酸检）/ 奇异诊断。

酸检（acid test）指：**先合成、再回收**。给定目标重量分数反解标度 → 合成两相
混合物 → 从错起点精修 → 用 Hill–Howard 算回重量分数，容差 1.5 个百分点。
这比"参数逐个对上"更能说明定量链路是否真的通。
"""

from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement import (
    AtomSite,
    BackgroundParams,
    Cell,
    Constraint,
    ConstraintSystem,
    Parameter,
    ParameterSet,
    PatternProblem,
    PhaseBlock,
    PhaseSpec,
    ProfileParams,
    StructureModel,
    atomic_form_factor,
    atomic_mass,
    background_basis,
    build_reflections,
    correlation_matrix,
    design_matrix,
    diagnose,
    formula_mass,
    hill_howard,
    make_equal,
    make_ratio,
    lorentz_polarization,
    make_sum_to,
    mass_per_cell,
    phase_weight_factor,
    phase_zmv,
)


# ── 约束系统 ──────────────────────────────────────────────────

class TestConstraint:
    def test_self_reference_raises(self):
        with pytest.raises(ValueError):
            Constraint("p", {"p": 1.0})

    def test_single_constraint_accepted(self):
        assert len(ConstraintSystem(make_ratio("b", "a", 2.0))) == 1

    def test_cycle_raises(self):
        cs = ConstraintSystem([Constraint("p", {"q": 1.0}),
                               Constraint("q", {"p": 1.0})])
        with pytest.raises(ValueError):
            cs.order()

    def test_topological_order(self):
        cs = ConstraintSystem([make_equal("b", "a"),
                               make_equal("c", "b")])
        assert cs.order() == ["b", "c"]


class TestConstraintOnParams:
    def test_dependent_excluded_from_free(self):
        ps = ParameterSet([Parameter("a", 0.3), Parameter("b", 0.4),
                           Parameter("c", 0.3), Parameter("d", 0.5)])
        ps.set_constraints(ConstraintSystem(make_sum_to(["a", "b", "c"], 1.0)))
        assert [ps.names()[i] for i in ps.free_indices()] == ["a", "b", "d"]

    def test_assign_updates_dependent(self):
        ps = ParameterSet([Parameter("a", 0.3), Parameter("b", 0.4),
                           Parameter("c", 0.3)])
        ps.set_constraints(ConstraintSystem(make_sum_to(["a", "b", "c"], 1.0)))
        ps.assign([0.2, 0.5])
        assert abs(ps["c"].value - 0.3) < 1e-12

    def test_chain_equality(self):
        ps = ParameterSet([Parameter("x1", 0.1), Parameter("x2", 0.2),
                           Parameter("x3", 0.3)])
        ps.set_constraints(ConstraintSystem([make_equal("x2", "x1"),
                                             make_equal("x3", "x2", 2.0)]))
        ps.assign([0.25])
        assert abs(ps["x2"].value - 0.25) < 1e-12
        assert abs(ps["x3"].value - 0.5) < 1e-12

    def test_ratio(self):
        ps = ParameterSet([Parameter("b1", 0.5), Parameter("b2", 0.5)])
        ps.set_constraints(ConstraintSystem(make_ratio("b2", "b1", 1.5)))
        ps.assign([0.4])
        assert abs(ps["b2"].value - 0.6) < 1e-12

    def test_describe(self):
        cs = ConstraintSystem(make_ratio("b2", "b1", 1.5))
        assert "b2" in cs.describe()[0] and "1.5" in cs.describe()[0]

    def test_dict_roundtrip_keeps_constraints(self):
        ps = ParameterSet([Parameter("a", 0.5), Parameter("b", 0.5)])
        ps.set_constraints(ConstraintSystem(make_equal("b", "a")))
        back = ParameterSet.from_dict(ps.as_dict())
        assert back.constrained_names() == ["b"]


# ── 定量基础量 ────────────────────────────────────────────────

def _si() -> StructureModel:
    frac = [(0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
            (.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25)]
    return StructureModel(sites=tuple(AtomSite("Si", *f) for f in frac),
                          cell=Cell(5.431, 5.431, 5.431), name="Si")


def _nacl() -> StructureModel:
    na = [(0, 0, 0), (.5, .5, 0), (.5, 0, .5), (0, .5, .5)]
    cl = [(.5, 0, 0), (0, .5, 0), (0, 0, .5), (.5, .5, .5)]
    return StructureModel(
        sites=tuple([AtomSite("Na", *f) for f in na]
                    + [AtomSite("Cl", *f) for f in cl]),
        cell=Cell(5.64, 5.64, 5.64), name="NaCl")


class TestQuantBasics:
    def test_atomic_mass(self):
        assert abs(atomic_mass("Si") - 28.085) < 1e-9
        assert atomic_mass("Xx") == 0.0

    def test_formula_mass(self):
        m = formula_mass({"Li": 1, "Fe": 1, "P": 1, "O": 4})
        assert abs(m - 157.757) < 0.01

    def test_z_and_cell_mass(self):
        z, m_cell, vol, zmv = phase_zmv(_si())
        assert z == 8
        assert abs(m_cell - 8 * 28.085) < 1e-6
        assert abs(vol - 5.431 ** 3) < 1e-9
        assert abs(zmv - m_cell * vol) < 1e-6

    def test_nacl_z(self):
        z, m_cell, _v, _z = phase_zmv(_nacl())
        assert z == 4
        assert abs(m_cell - 4 * (22.99 + 35.45)) < 0.02


# ── 强度口径守卫（1/V² 与定相因子必须配套） ──────────────────


class TestIntensityConvention:
    """守卫 ``I ∝ m|F|²·LP/V²`` 与 ``W ∝ S·M_cell`` 的**配对关系**。

    这两处只要有一边被单独改回"老口径"，多相定量就会系统性偏袒大胞相
    （方解石 V=368 Å³、ZnO V=47.6 Å³，差 60 倍），而单相精修完全看不出来
    —— 标度会把常数全吃掉。实测踩过：2-1 两相各给 0%。

    用"单原子 P1 胞"做解析对拍：F² = f(s)²，等效点数就是合并数，没有任何
    模型自由度可以遮掩。
    """

    def _tab(self):
        st = StructureModel(
            sites=(AtomSite("Si", 0.0, 0.0, 0.0, 1.0, 0.0, "Si1"),),
            cell=Cell(5.0, 5.0, 5.0), name="Si-P1",
        )
        return st, build_reflections(st, two_theta_range=(10, 60), noise_ratio=0.0)

    def test_intensity_carries_inverse_volume_sq(self):
        st, tab = self._tab()
        vol_sq = float(st.cell.volume()) ** 2
        assert tab.hkl.shape[0] > 3
        for i in range(tab.hkl.shape[0]):
            two_theta = float(tab.two_theta[i])
            s = 0.5 / float(tab.d[i])
            f = float(atomic_form_factor("Si", s))
            lp = float(lorentz_polarization(two_theta))
            expect = tab.n_merged[i] * f * f * lp / vol_sq
            assert abs(float(tab.intensity[i]) / expect - 1.0) < 1e-9, (
                f"{tuple(int(v) for v in tab.hkl[i])}: "
                f"{float(tab.intensity[i]):.6g} vs {expect:.6g}")

    def test_quant_factor_is_density(self):
        """定相因子 = 每胞质量/胞体积 ∝ 密度。

        ``Z·M·V`` / ``Z·M`` 都与上面的强度口径错配，会让 ZnO 这类小胞高密度相
        被压到 10%（实测 2-1）。
        """
        for st in (_si(), _nacl()):
            assert phase_weight_factor(st) == pytest.approx(
                mass_per_cell(st.sites) / st.cell.volume(), rel=1e-12)
        # ×1.66 就该是真实密度：Si 2.33 g/cm³
        assert 1.66 * phase_weight_factor(_si()) == pytest.approx(2.33, abs=0.02)

    def test_hill_howard_reports_that_factor(self):
        s = np.array([0.65, 0.35]) / np.array(
            [phase_weight_factor(_si()), phase_weight_factor(_nacl())])
        q = hill_howard(["Si", "NaCl"], s, [_si(), _nacl()])
        assert q.factor == pytest.approx(
            (phase_weight_factor(_si()), phase_weight_factor(_nacl())))
        assert np.allclose(q.percent(), [65.0, 35.0], atol=1e-6)


class TestHillHoward:
    ZMV = None

    def _zmv(self):
        # 定相因子是 M_cell（强度口径含 1/V²），不是 Z·M·V
        return np.array([phase_weight_factor(_si()),
                         phase_weight_factor(_nacl())])

    def test_recovers_target_fractions(self):
        zmv = self._zmv()
        w = np.array([0.65, 0.35])
        s = (w / zmv)
        q = hill_howard(["Si", "NaCl"], s, [_si(), _nacl()])
        assert np.allclose(q.percent(), [65.0, 35.0], atol=1e-6)

    def test_scale_invariant(self):
        zmv = self._zmv()
        s = np.array([0.65, 0.35]) / zmv
        a = hill_howard(["Si", "NaCl"], s, [_si(), _nacl()])
        b = hill_howard(["Si", "NaCl"], s * 1e6, [_si(), _nacl()])
        assert np.allclose(a.percent(), b.percent())

    def test_single_phase(self):
        q = hill_howard(["Si"], [1.0], [_si()])
        assert abs(q.percent()[0] - 100.0) < 1e-12

    def test_zero_scale(self):
        q = hill_howard(["Si", "NaCl"], [0.0, 1.0], [_si(), _nacl()])
        assert abs(q.percent()[0]) < 1e-12

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            hill_howard(["Si"], [1.0, 2.0], [_si()])

    def test_empty(self):
        q = hill_howard([], [], [])
        assert q.fractions == ()

    def test_table_and_dict(self):
        q = hill_howard(["Si", "NaCl"], [1.0, 1.0], [_si(), _nacl()])
        assert len(q.table()) == 2 and len(q.table()[0]) == 3
        assert abs(sum(q.as_dict().values()) - 100.0) < 1e-9


# ── 酸检 ─────────────────────────────────────────────────────

CUT = 25.0
W_TARGET = (65.0, 35.0)


@pytest.fixture(scope="module")
def acid():
    """合成两相混合物 → 精修 → 返回 (problem, summary)。"""
    rng = np.random.default_rng(11)
    grid = np.linspace(20.0, 80.0, 2001)
    prof = ProfileParams(w=0.015, x=0.003, y=0.001)
    bg = BackgroundParams("tent", 8)
    bg_coefs = np.linspace(40.0, 70.0, 8)

    si, nacl = _si(), _nacl()
    zmv = np.array([phase_weight_factor(si), phase_weight_factor(nacl)])
    b_si = design_matrix(grid, [PhaseSpec(build_reflections(
        si, two_theta_range=(18.0, 82.0)))], prof, cutoff_fwhm=CUT)[:, 0]
    b_nacl = design_matrix(grid, [PhaseSpec(build_reflections(
        nacl, two_theta_range=(18.0, 82.0)))], prof, cutoff_fwhm=CUT)[:, 0]

    w = np.array(W_TARGET) / 100.0
    s = w / zmv
    s = s / max(b_si.max() * s[0], b_nacl.max() * s[1]) * 3000.0
    y_true = b_si * s[0] + b_nacl * s[1] + background_basis(grid, bg) @ bg_coefs
    y_obs = y_true + rng.normal(0.0, np.sqrt(np.maximum(y_true, 1.0)))

    prob = PatternProblem(
        grid, y_obs,
        [PhaseBlock("Si", si, index=0), PhaseBlock("NaCl", nacl, index=1)],
        profile=ProfileParams(w=0.03), bg=bg,
        weights=1.0 / np.maximum(y_obs, 1.0), cutoff_fwhm=CUT,
    )
    rwp0 = prob.metrics()["Rwp"]
    summary = prob.fit(stages=(2, 3), max_iter_per_stage=80)
    return prob, summary, rwp0


class TestAcidTest:
    def test_reaches_noise_floor(self, acid):
        _p, s, rwp0 = acid
        m = s.metrics
        assert rwp0 > 10.0, f"起点 Rwp 应明显更差，实测 {rwp0:.2f}%"
        assert m["Rwp"] < 1.15 * m["Rexp"]
        assert 0.85 < m["GOF"] < 1.15

    def test_weight_fractions(self, acid):
        _p, s, _r = acid
        pct = s.quant.percent()
        assert abs(pct[0] - W_TARGET[0]) < 1.5, f"Si {pct[0]:.3f}%"
        assert abs(pct[1] - W_TARGET[1]) < 1.5, f"NaCl {pct[1]:.3f}%"
        assert abs(sum(pct) - 100.0) < 1e-9

    def test_z_reported(self, acid):
        _p, s, _r = acid
        assert s.quant.z == (8, 4)

    def test_quant_matches_linear_scales(self, acid):
        prob, s, _r = acid
        assert np.allclose(s.quant.scales, prob.last_linear.scales)


# ── 诊断 ─────────────────────────────────────────────────────

class TestDiagnostics:
    def test_flags_cubic_angle_degeneracy(self, acid):
        """Si / NaCl 都是立方相：逐参数放开 a,b,c 与 α,β,γ 必然退化。

        这不是拟合坏了，而是诊断**正确工作**的证据 —— 立方相的角度自由度
        零信息量，必须靠对称性约束固定（否则 JᵀJ 奇异）。
        """
        _p, s, _r = acid
        d = s.diagnostics
        assert d is not None
        assert d.rank_deficient, f"应检出秩亏，SVD0={d.svd0_ratio:.2e}"
        assert any("alpha" in n or "beta" in n or "gamma" in n for n in d.psing)

    def test_flagged_degeneracy_does_not_break_quant(self, acid):
        """退化发生在角度自由度上，不影响定量结果（峰位仍被正确拟合）。"""
        _p, s, _r = acid
        pct = s.quant.percent()
        assert abs(pct[0] - W_TARGET[0]) < 1.5

    def test_sigmas_written_back(self, acid):
        prob, s, _r = acid
        d = s.diagnostics
        assert len(d.sigmas) == len(d.names)
        for i in prob.params.free_indices(3)[:3]:
            name = prob.params.names()[i]
            assert prob.params[name].sigma == pytest.approx(d.sigmas[name])
        assert all(v > 0 for v in list(d.sigmas.values())[:5])

    def test_synthetic_collinear_columns(self):
        rng = np.random.default_rng(3)
        J = rng.normal(size=(200, 4))
        bad = J.copy()
        bad[:, 2] = J[:, 1] * 2.0
        d = diagnose(bad, ["a", "b", "c", "d"])
        assert d.rank_deficient
        assert set(d.psing) == {"b", "c"}

    def test_healthy_jacobian_not_flagged(self):
        rng = np.random.default_rng(3)
        d = diagnose(rng.normal(size=(200, 4)), ["a", "b", "c", "d"])
        assert not d.rank_deficient
        assert d.svd0_ratio > 1e-3

    def test_correlation_matrix(self):
        corr = correlation_matrix(np.array([[4.0, 3.6], [3.6, 4.0]]))
        assert np.allclose(np.diag(corr), 1.0)
        assert abs(corr[0, 1] - 0.9) < 1e-12

    def test_correlation_clipped(self):
        """病态时 inv(JᵀJ) 会给 |ρ|>1，必须夹回 [-1,1]。"""
        corr = correlation_matrix(np.array([[4.0, 4.4], [4.4, 4.0]]))
        assert np.max(np.abs(corr)) <= 1.0 + 1e-12

    def test_high_corr_detected(self):
        rng = np.random.default_rng(5)
        base = rng.normal(size=(200, 1))
        J = np.hstack([base, base * 1.0 + rng.normal(scale=1e-6, size=(200, 1))])
        d = diagnose(J, ["a", "b"], highcorr=0.9)
        assert d.high_corr or d.rank_deficient

    def test_at_bounds_in_report(self):
        rng = np.random.default_rng(3)
        d = diagnose(rng.normal(size=(200, 4)), list("abcd"), at_bounds=["c"])
        assert "贴边界" in d.report()
        assert d.at_bounds == ["c"]

    def test_no_jacobian(self):
        d = diagnose(None, ["a"], at_bounds=["a"])
        assert d.at_bounds == ["a"] and d.rank == 0
        assert d.warnings

    def test_report_healthy(self):
        rng = np.random.default_rng(3)
        d = diagnose(rng.normal(size=(200, 4)), list("abcd"))
        assert "未发现病态" in d.report()
