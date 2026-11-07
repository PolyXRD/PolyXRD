# -*- coding: utf-8 -*-
"""P0-G：逐相颗粒半径（per-phase grain radius）。

验收口径
--------
* **逐相半径是物理必需**：Brindley τ 的自变量是 ``(μ_j − μ̄)·R_j``，混合样各相
  粒度可以差一个量级（IUCr CPD：刚玉 28 µm vs 锌矿 1.4 µm）。同一个 R 套所有相
  等于把大颗粒相的吸收偏差按小颗粒相算。
* **向后兼容是硬约束**：标量半径的行为必须与 v5.2 逐位一致；"全相同值的序列"
  必须折回标量口径（``radius_um`` 有值、``radius_um_per_phase`` 空）。
* **逐相口径要一路通到定量与误差棒**：``hill_howard`` /
  ``PatternProblem.quantitative`` / ``fraction_sigmas`` 三层都要认。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement import (
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
from polyxrd.refinement.goal import fraction_sigmas
from polyxrd.refinement.intensity import (
    apply_microabsorption,
    microabsorption_taus,
    radius_per_phase,
)
from polyxrd.refinement.quantitative import hill_howard

_CUT = 25.0
_PROFILE = ProfileParams(u=0.02, v=-0.01, w=0.012, x=0.01)
_BG = BackgroundParams("tent", 8)


def _cubic(element: str, a: float) -> StructureModel:
    sites = (AtomSite(element, 0.0, 0.0, 0.0, 1.0, 0.5, element),)
    return StructureModel(sites=sites, cell=Cell(a, a, a, 90.0, 90.0, 90.0),
                          space_group="P 1", name=element)


def _two_phase_problem(*, mu=None, radius_um=0.0):
    st_a, st_b = _cubic("Fe", 3.0), _cubic("Al", 4.0)
    tt = np.linspace(15.0, 120.0, 1051)
    tab_a = build_reflections(st_a, two_theta_range=(13.0, 122.0))
    tab_b = build_reflections(st_b, two_theta_range=(13.0, 122.0))
    basis = design_matrix(tt, [PhaseSpec(tab_a), PhaseSpec(tab_b)], _PROFILE,
                          cutoff_fwhm=_CUT)
    y = (basis @ np.array([4000.0 / basis[:, 0].max(),
                           3000.0 / basis[:, 1].max()])
         + background_basis(tt, _BG) @ np.linspace(50.0, 30.0, 8))
    prob = PatternProblem(tt, y, [PhaseBlock("Fe", st_a, index=0),
                                  PhaseBlock("Al", st_b, index=1)],
                          profile=_PROFILE, bg=_BG,
                          weights=1.0 / np.maximum(y, 1.0),
                          cutoff_fwhm=_CUT, wavelength=1.5406,
                          mu_linear=mu, grain_radius_um=radius_um)
    prob.apply()
    return prob, y


class TestRadiusPerPhase:
    def test_scalar_broadcasts(self):
        r = radius_per_phase(3.0, 4)
        assert r.shape == (4,) and np.all(r == 3.0)

    def test_sequence_passthrough(self):
        assert list(radius_per_phase([1.0, 2.0], 2)) == [1.0, 2.0]

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError):
            radius_per_phase([1.0, 2.0], 3)

    def test_negative_and_nan_raise(self):
        with pytest.raises(ValueError):
            radius_per_phase([1.0, -0.1], 2)
        with pytest.raises(ValueError):
            radius_per_phase([1.0, float("nan")], 2)


class TestMicroabsorptionTaus:
    MU = [1000.0, 100.0]

    def test_scalar_equals_full_sequence(self):
        t1, mb1, c1 = microabsorption_taus(self.MU, [0.5, 0.5], 3.0)
        t2, mb2, c2 = microabsorption_taus(self.MU, [0.5, 0.5], [3.0, 3.0])
        assert np.allclose(t1, t2) and mb1 == pytest.approx(mb2)
        assert c1 == c2

    def test_bigger_radius_stronger_correction(self):
        """R 越大 |τ−1| 越大（同 μ 反差下）。"""
        t_small, _, _ = microabsorption_taus(self.MU, [0.5, 0.5], 1.0)
        t_big, _, _ = microabsorption_taus(self.MU, [0.5, 0.5], 10.0)
        assert abs(t_big[0] - 1.0) > abs(t_small[0] - 1.0)

    def test_zero_radius_phase_is_identity(self):
        """某相给 0 → 该相 τ=1（不修正），另一相照常。"""
        tau, _, _ = microabsorption_taus(self.MU, [0.5, 0.5], [5.0, 0.0])
        assert tau[1] == pytest.approx(1.0)
        assert tau[0] != pytest.approx(1.0)

    def test_per_phase_differs_from_any_uniform(self):
        """逐相 R ≠ 任何单一标量 R 的解（自由度真的多了）。"""
        mu = [1200.0, 200.0]
        w = [0.5, 0.5]
        t_pp, _, _ = microabsorption_taus(mu, w, [10.0, 0.5])
        for r in (0.5, 10.0, 5.0):
            t_u, _, _ = microabsorption_taus(mu, w, r)
            assert not np.allclose(t_pp, t_u)


class TestHillHoward:
    """定量层：均匀序列折回标量口径，逐相序列走 per_phase 字段。"""

    LABELS = ("Fe", "Al")
    SCALES = (0.6, 0.4)
    MU = [2200.0, 300.0]

    def _structures(self):
        return [_cubic("Fe", 3.0), _cubic("Al", 4.0)]

    def test_uniform_list_folds_back_to_scalar(self):
        q1 = hill_howard(self.LABELS, self.SCALES, self._structures(),
                         mu=self.MU, radius_um=3.0)
        q2 = hill_howard(self.LABELS, self.SCALES, self._structures(),
                         mu=self.MU, radius_um=[3.0, 3.0])
        assert q1.radius_um == pytest.approx(3.0)
        assert q2.radius_um == pytest.approx(3.0)
        assert q2.radius_um_per_phase == ()
        assert q1.fractions == q2.fractions and q1.tau == q2.tau

    def test_per_phase_recorded_and_scalar_zeroed(self):
        q = hill_howard(self.LABELS, self.SCALES, self._structures(),
                        mu=self.MU, radius_um=[8.0, 2.0])
        assert q.radius_um == 0.0
        assert q.radius_um_per_phase == (8.0, 2.0)
        assert len(q.tau) == 2 and q.tau[0] != q.tau[1]

    def test_per_phase_changes_fractions(self):
        """逐相 R 不是化妆品：份额必须与任何单一 R 不同。"""
        q_pp = hill_howard(self.LABELS, self.SCALES, self._structures(),
                           mu=self.MU, radius_um=[8.0, 2.0])
        for r in (2.0, 5.0, 8.0):
            q_u = hill_howard(self.LABELS, self.SCALES, self._structures(),
                              mu=self.MU, radius_um=r)
            assert not np.allclose(q_pp.fractions, q_u.fractions)

    def test_partial_zero_radius_still_applies(self):
        """[5, 0]：相 A 修正、相 B 恒等 —— 仍算"启用"（tau 非全 1）。"""
        q = hill_howard(self.LABELS, self.SCALES, self._structures(),
                        mu=self.MU, radius_um=[5.0, 0.0])
        assert q.radius_um_per_phase == (5.0, 0.0)
        assert q.tau[0] != pytest.approx(1.0)
        assert q.tau[1] == pytest.approx(1.0)

    def test_no_mu_ignores_radius(self):
        q = hill_howard(self.LABELS, self.SCALES, self._structures(),
                        mu=None, radius_um=[8.0, 2.0])
        assert q.tau == () and q.radius_um_per_phase == ()
        q0 = hill_howard(self.LABELS, self.SCALES, self._structures())
        assert q.fractions == q0.fractions

    def test_all_zero_radius_is_noop(self):
        q = hill_howard(self.LABELS, self.SCALES, self._structures(),
                        mu=self.MU, radius_um=[0.0, 0.0])
        q0 = hill_howard(self.LABELS, self.SCALES, self._structures())
        assert q.fractions == q0.fractions and q.tau == ()

    def test_apply_microabsorption_accepts_sequence(self):
        base = [0.6 * 80.0, 0.4 * 75.0]
        w, tau, _, _ = apply_microabsorption(base, self.MU, [4.0, 1.0])
        assert abs(sum(w) - 1.0) < 1e-12 and len(tau) == 2


class TestProblemWiring:
    def test_scalar_unchanged(self):
        prob, _ = _two_phase_problem(mu=self._mu(), radius_um=5.0)
        assert prob.grain_radius_um == pytest.approx(5.0)
        assert prob.grain_radii_um == ()
        q = prob.quantitative()
        assert q.radius_um == pytest.approx(5.0) and q.radius_um_per_phase == ()

    def _mu(self):
        return [2200.0, 300.0]

    def test_uniform_sequence_folds_to_scalar(self):
        prob, _ = _two_phase_problem(mu=self._mu(), radius_um=[5.0, 5.0])
        assert prob.grain_radius_um == pytest.approx(5.0)
        assert prob.grain_radii_um == ()

    def test_per_phase_stored_and_used(self):
        prob, _ = _two_phase_problem(mu=self._mu(), radius_um=[6.0, 1.0])
        assert prob.grain_radius_um == 0.0
        assert prob.grain_radii_um == (6.0, 1.0)
        q = prob.quantitative()
        assert q.radius_um == 0.0 and q.radius_um_per_phase == (6.0, 1.0)
        assert q.tau[0] != pytest.approx(1.0) or q.tau[1] != pytest.approx(1.0)

    def test_wrong_length_raises(self):
        st_a, st_b = _cubic("Fe", 3.0), _cubic("Al", 4.0)
        tt = np.linspace(15.0, 120.0, 101)
        with pytest.raises(ValueError):
            PatternProblem(tt, np.ones_like(tt),
                           [PhaseBlock("Fe", st_a, index=0),
                            PhaseBlock("Al", st_b, index=1)],
                           grain_radius_um=[1.0, 2.0, 3.0])


class TestFractionSigmasWithPerPhase:
    """误差棒：per_phase 半径要真的进 τ 的数值雅可比（不能只在展示层好看）。"""

    def test_per_phase_path_finite_and_differs_from_noop(self):
        prob, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=[3.0, 0.5])
        q = prob.quantitative()
        got = fraction_sigmas(q, [0.02, 0.02])
        assert all(np.isfinite(v) and v > 0 for v in got)
        # 不开 MA 的闭式值 —— 开了逐相 MA 后必须不同（τ 反馈进了导数）
        plain, _ = _two_phase_problem()
        base = fraction_sigmas(plain.quantitative(), [0.02, 0.02])
        assert any(abs(a - b) > 1e-9 for a, b in zip(got, base))

    def test_uniform_path_identical_to_scalar(self):
        qa, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=3.0)
        qb, _ = _two_phase_problem(mu=[2200.0, 300.0], radius_um=[3.0, 3.0])
        sa = fraction_sigmas(qa.quantitative(), [0.02, 0.02])
        sb = fraction_sigmas(qb.quantitative(), [0.02, 0.02])
        assert sa == pytest.approx(sb)
