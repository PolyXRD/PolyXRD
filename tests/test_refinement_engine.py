"""v5.0.0 阶段 B 验收：参数系统 / 变量投影线性层 / LM / round-trip 回收。

核心断言是**统计上的**而不是"参数逐个对得上"：
* 线性层必须精确回收（无噪时 1e-10）；
* LM 必须与 ``scipy.optimize.least_squares(trf)`` 收敛到同一点；
* round-trip 必须把 **GOF 压到 1**（= 到达噪声底），而不是把每个参数都对上。

最后一条是刻意设计的：峰形参数 ``X·tanθ`` 与 ``Y/cosθ`` 在中等角域近共线，
单参数不可辨识 —— 拟合会给出等价但数值不同的组合（实测 x 可从 0.004 漂到
0.022 而 GOF 仍是 1.00）。物理上可辨识的是**总 FWHM 曲线**，所以断言它。
"""

from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement import (
    BackgroundParams,
    Cell,
    AtomSite,
    ProfileParams,
    StructureModel,
    Parameter,
    ParameterSet,
    PhaseBlock,
    PatternProblem,
    Kalpha2,
    build_reflections,
    design_matrix,
    PhaseSpec,
    reflection_centers_and_intensities,
    background_basis,
    levenberg_marquardt,
    scipy_least_squares,
    solve_linear,
    linear_covariance,
    pattern_metrics,
    tch_widths,
)


# ── 参数系统 ──────────────────────────────────────────────────

class TestParameter:
    def test_bounds_clamp_initial(self):
        assert Parameter("a", 20.0, 0.0, 5.0).value == 5.0

    def test_min_gt_max_raises(self):
        with pytest.raises(ValueError):
            Parameter("a", 1.0, 10.0, 1.0)

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            Parameter("", 1.0)

    def test_at_bound(self):
        assert Parameter("a", 5.0, 0.0, 5.0).at_bound()
        assert Parameter("b", 2.0, 0.0, 5.0).at_bound() is False
        assert Parameter("c", 1.0).at_bound() is False

    def test_clip(self):
        p = Parameter("a", 1.0, 0.0, 5.0)
        assert p.clip(9.0) == 5.0 and p.clip(-1.0) == 0.0

    def test_serialization(self):
        p = Parameter("a", 2.0, 0.0, 5.0, stage=3, sigma=0.1, label="A")
        q = Parameter(**p.as_dict())
        assert (q.name, q.value, q.stage, q.sigma, q.label) == \
               (p.name, p.value, p.stage, p.sigma, p.label)


class TestParameterSet:
    def _ps(self):
        return ParameterSet([
            Parameter("a", 1.0, 0.0, 10.0, stage=1),
            Parameter("b", 2.0, stage=2),
            Parameter("c", 3.0, fixed=True, stage=1),
            Parameter("d", 4.0, stage=3),
        ])

    def test_free_indices_cumulative(self):
        ps = self._ps()
        assert list(ps.free_indices(1)) == [0]
        assert list(ps.free_indices(2)) == [0, 1]
        assert list(ps.free_indices(3)) == [0, 1, 3]

    def test_none_excludes_fixed(self):
        assert list(self._ps().free_indices(None)) == [0, 1, 3]

    def test_bounds(self):
        lo, hi = self._ps().bounds(2)
        assert np.allclose(lo, [0.0, -np.inf])
        assert np.allclose(hi, [10.0, np.inf])

    def test_assign_roundtrip(self):
        ps = self._ps()
        ps.assign([5.0, 7.0], 2)
        assert np.allclose(ps.to_vector(2), [5.0, 7.0])

    def test_assign_length_mismatch(self):
        with pytest.raises(ValueError):
            self._ps().assign([1.0], 2)

    def test_set_clips(self):
        ps = self._ps()
        ps.set("a", 99.0)
        assert ps["a"].value == 10.0

    def test_duplicate_name_raises(self):
        with pytest.raises(ValueError):
            ParameterSet([Parameter("a", 1.0), Parameter("a", 2.0)])

    def test_copy_independent(self):
        ps = self._ps()
        ps.set("a", 10.0)
        ps2 = ps.copy()
        ps2.set("a", 1.0)
        assert ps["a"].value == 10.0 and ps2["a"].value == 1.0

    def test_fix_prefix(self):
        ps = self._ps()
        assert ps.fix_prefix("a", True) == 1
        assert "a" not in [ps.names()[i] for i in ps.free_indices(None)]

    def test_snapshot_restore(self):
        ps = self._ps()
        ps.set("a", 7.0)
        snap = ps.snapshot()
        ps.set("a", 9.0)
        ps.restore(snap)
        assert ps["a"].value == 7.0

    def test_dict_roundtrip(self):
        ps = self._ps()
        assert ParameterSet.from_dict(ps.as_dict()).names() == ps.names()

    def test_sigmas(self):
        ps = self._ps()
        ps.set_sigmas([0.1, 0.2], 2)
        assert np.allclose(ps.sigmas(2), [0.1, 0.2])


# ── 线性层 ────────────────────────────────────────────────────

class TestLinearLayer:
    N = 400

    def _setup(self):
        x = np.linspace(0.0, 10.0, self.N)
        A = np.column_stack([np.exp(-((x - 3) ** 2)), np.exp(-((x - 7) ** 2))])
        G = np.column_stack([np.ones(self.N), np.linspace(-1.0, 1.0, self.N)])
        return A, G

    def test_exact_recovery(self):
        A, G = self._setup()
        s_true, c_true = np.array([2.5, 1.2]), np.array([0.8, 0.3])
        y = A @ s_true + G @ c_true
        sol = solve_linear(A, y, bg_basis=G)
        assert np.allclose(sol.scales, s_true, atol=1e-10)
        assert np.allclose(sol.bg_coefs, c_true, atol=1e-10)
        assert np.max(np.abs(sol.resid)) < 1e-10

    def test_nonneg_scales_clipped(self):
        A, G = self._setup()
        y = A[:, 0] * 3.0 + G @ np.array([0.8, 0.3]) - A[:, 1] * 2.0
        sol = solve_linear(A, y, bg_basis=G, nonneg_scales=True)
        assert sol.scales[1] == 0.0 and sol.scales[0] > 0
        assert 1 in sol.clipped
        # 约束解必须是"锁住该列后"的最优：背景列不能被 NNLS 一起丢掉，
        # 应与直接用 A[:, :1] 求得的解一致。
        ref = solve_linear(A[:, :1], y, bg_basis=G, nonneg_scales=False)
        assert np.allclose(sol.bg_coefs, ref.bg_coefs, atol=1e-9)
        assert abs(sol.scales[0] - ref.scales[0]) < 1e-9

    def test_no_constraint_keeps_negative(self):
        A, G = self._setup()
        y = A[:, 0] * 3.0 + G @ np.array([0.8, 0.3]) - A[:, 1] * 2.0
        sol = solve_linear(A, y, bg_basis=G, nonneg_scales=False)
        assert sol.scales[1] < 0

    def test_weighted(self):
        A, G = self._setup()
        s_true = np.array([2.5, 1.2])
        y = A @ s_true + G @ np.array([0.8, 0.3])
        w = np.linspace(0.5, 2.0, self.N)
        sol = solve_linear(A, y, weights=w, bg_basis=G)
        assert np.allclose(sol.scales, s_true, atol=1e-9)

    def test_rank_and_cond(self):
        A, G = self._setup()
        y = A @ np.array([1.0, 1.0]) + G @ np.array([0.5, 0.0])
        sol = solve_linear(A, y, bg_basis=G)
        assert sol.rank == 4 and np.isfinite(sol.cond) and sol.cond > 0

    def test_shape_mismatch_raises(self):
        A, _ = self._setup()
        with pytest.raises(ValueError):
            solve_linear(A, np.zeros(self.N - 1))

    def test_covariance(self):
        A, G = self._setup()
        cov = linear_covariance(A, np.ones(self.N), bg_basis=G, reduced_chi2=1.0)
        assert cov.shape == (4, 4)
        assert np.allclose(cov, cov.T)
        assert np.all(np.diag(cov) > 0)


# ── LM ────────────────────────────────────────────────────────

def _rosen(x):
    return np.array([10 * (x[1] - x[0] ** 2), 1 - x[0]])


class TestLevenbergMarquardt:
    def test_rosenbrock(self):
        res = levenberg_marquardt(_rosen, [-1.2, 1.0])
        assert np.allclose(res.x, [1.0, 1.0], atol=1e-6)
        assert res.cost < 1e-12

    def test_matches_scipy(self):
        a = levenberg_marquardt(_rosen, [-1.2, 1.0])
        b = scipy_least_squares(_rosen, [-1.2, 1.0])
        assert np.allclose(a.x, b.x, atol=1e-5)

    def test_bounds_give_constrained_optimum(self):
        """[0,0.5]² 内 Rosenbrock 的约束最优是角点 (0.5, 0.25)，cost=0.125。"""
        res = levenberg_marquardt(_rosen, [-1.2, 1.0],
                                  bounds=([0.0, 0.0], [0.5, 0.5]))
        assert np.allclose(res.x, [0.5, 0.25], atol=1e-4)
        assert abs(res.cost - 0.125) < 1e-4

    def test_reduced_chi2_and_rms(self):
        res = levenberg_marquardt(_rosen, [0.0, 0.0])
        assert res.n_data == 2 and res.n_params == 2
        assert np.isfinite(res.rms) and np.isfinite(res.reduced_chi2)

    def test_zero_dim(self):
        res = levenberg_marquardt(lambda x: np.array([1.0, 2.0]), [])
        assert res.status == "converged" and res.cost == 2.5

    def test_callback_called(self):
        seen = []
        levenberg_marquardt(_rosen, [-1.2, 1.0],
                            callback=lambda i, x, c: seen.append((i, float(c))))
        assert seen and seen[-1][1] < seen[0][1]

    def test_analytic_jacobian(self):
        def jac(x):
            return np.array([[-20 * x[0], 10], [-1.0, 0.0]])

        res = levenberg_marquardt(_rosen, [-1.2, 1.0], jac=jac)
        assert np.allclose(res.x, [1.0, 1.0], atol=1e-6)


class TestMetrics:
    def test_perfect_fit(self):
        y = np.array([10.0, 20.0, 30.0])
        m = pattern_metrics(y, y, np.ones(3), n_params=0)
        assert m["Rwp"] == 0.0 and m["Rp"] == 0.0

    def test_goF_consistency(self):
        rng = np.random.default_rng(0)
        y = np.full(500, 1000.0)
        yc = y + rng.normal(0.0, np.sqrt(1000.0), y.size)
        m = pattern_metrics(y, yc, 1.0 / y, n_params=2)
        assert 0.7 < m["GOF"] < 1.4, m

    def test_empty(self):
        m = pattern_metrics(np.zeros(0), np.zeros(0))
        assert np.isnan(m["Rwp"])


# ── round-trip ───────────────────────────────────────────────

CUT = 25.0
TRUE_CELL = (10.33, 6.01, 4.69)
TRUE_PROFILE = dict(w=0.02, x=0.004, y=0.002)
BG_TRUE = np.linspace(30.0, 80.0, 8)


def _lfp() -> StructureModel:
    return StructureModel(
        sites=(
            AtomSite("Li", 0.0, 0.0, 0.0, 1.0, 0.5),
            AtomSite("Fe", 0.2821, 0.25, 0.9745, 1.0, 0.5),
            AtomSite("P", 0.0947, 0.25, 0.4183, 1.0, 0.5),
            AtomSite("O", 0.0966, 0.25, 0.7427, 1.0, 0.5),
            AtomSite("O", -0.0966, 0.75, 0.2573, 1.0, 0.5),
            AtomSite("O", 0.3466, 0.75, 0.2427, 1.0, 0.5),
        ),
        cell=Cell(*TRUE_CELL), name="LiFePO4",
    )


def _scale_for_peak(peak: float = 3000.0) -> float:
    """把"最强峰 ≈ ``peak`` counts"折算成标度。

    强度口径含 ``1/V²``（见 ``build_reflections``），绝对标度随胞体积剧烈变化，
    所以**不能写死** ``3e-3`` —— 换一个晶胞这个数就没意义了。这里按整数口径
    反推，测试要的是"能不能把标度原样找回来"，不是某个具体数值。
    """
    grid = np.linspace(15.0, 75.0, 2001)
    tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
    basis = design_matrix(grid, [PhaseSpec(tab)], ProfileParams(**TRUE_PROFILE),
                          cutoff_fwhm=CUT)
    return float(peak / basis.max())


SCALE_TRUE = _scale_for_peak()


@pytest.fixture(scope="module")
def roundtrip():
    """合成谱（泊松噪声）→ 从错起点精修 → 返回 (problem, summary)。"""
    rng = np.random.default_rng(7)
    # 步长必须 ≤ FWHM/5：FWHM≈0.14° → 步长 ≤0.028°，否则峰形参数
    # 被欠采样（实测 0.0425°/点 时 FWHM 回收误差从 0.7% 涨到 4%）。
    grid = np.linspace(15.0, 75.0, 2001)
    prof_true = ProfileParams(**TRUE_PROFILE)
    bg = BackgroundParams("tent", 8)
    tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
    basis = design_matrix(grid, [PhaseSpec(tab)], prof_true, cutoff_fwhm=CUT)
    y_true = basis @ np.array([SCALE_TRUE]) + background_basis(grid, bg) @ BG_TRUE
    y_obs = y_true + rng.normal(0.0, np.sqrt(np.maximum(y_true, 1.0)))

    init = StructureModel(sites=_lfp().sites,
                          cell=Cell(10.36, 6.04, 4.72), name="LiFePO4")
    prob = PatternProblem(
        grid, y_obs, [PhaseBlock("LFP", init)],
        profile=ProfileParams(w=0.03, x=0.006, y=0.0), bg=bg,
        weights=1.0 / np.maximum(y_obs, 1.0), cutoff_fwhm=CUT,
    )
    rwp0 = prob.metrics()["Rwp"]
    summary = prob.fit(stages=(2, 3), max_iter_per_stage=80)
    return prob, summary, rwp0, grid, prof_true


class TestRoundTrip:
    def test_reaches_noise_floor(self, roundtrip):
        """Rwp 必须落到 Rexp 量级 —— 这才是"拟合成功"的定义。"""
        prob, summary, rwp0, _g, _p = roundtrip
        m = summary.metrics
        assert rwp0 > 30.0, f"起点 Rwp 应很差，实测 {rwp0:.1f}%"
        assert m["Rwp"] < 1.2 * m["Rexp"], (
            f"Rwp={m['Rwp']:.3f}% 应 ≤1.2×Rexp={m['Rexp']:.3f}%")

    def test_gof_near_one(self, roundtrip):
        _p, summary, _r0, _g, _pf = roundtrip
        assert 0.85 < summary.metrics["GOF"] < 1.2

    def test_cell_recovered(self, roundtrip):
        prob, _s, _r0, _g, _p = roundtrip
        for tag, ref in zip(("a", "b", "c"), TRUE_CELL):
            got = prob.params.get(f"phase0.cell.{tag}")
            assert abs(got - ref) < 2e-3, f"{tag}: {got:.6f} vs {ref}"

    def test_fwhm_curve_recovered(self, roundtrip):
        """单参数不可辨识（X/Y 近共线），但总 FWHM 曲线必须对上。

        判据用**绝对误差 <0.01°**：FWHM 本身 0.14°，0.01° 在任何图上都看不出
        差别；相对误差在这里不合适 —— 泊松噪声下 0.004° 的偏移就有 3% 的
        相对量，而它完全在统计不确定度之内（GOF 已经 =1 证明到了噪声底）。
        """
        prob, _s, _r0, grid, prof_true = roundtrip
        fw_t, _ = tch_widths(grid, 1.54056, prof_true)
        fw_f, _ = tch_widths(grid, 1.54056, prob.profile)
        err = np.max(np.abs(fw_f - fw_t))
        assert err < 0.01, f"FWHM 最大绝对偏差 {err:.5f}°（>0.01°）"

    def test_scale_recovered(self, roundtrip):
        prob, _s, _r0, _g, _p = roundtrip
        assert abs(prob.params.get("phase0.scale") / SCALE_TRUE - 1.0) < 5e-3

    def test_background_curve_recovered(self, roundtrip):
        prob, _s, _r0, grid, _p = roundtrip
        bg = BackgroundParams("tent", 8)
        basis = background_basis(grid, bg)
        rec = basis @ np.array([prob.params.get(f"bg.c{k}") for k in range(8)])
        ref = basis @ BG_TRUE
        assert np.max(np.abs(rec - ref)) / np.mean(ref) < 0.10

    def test_stage_log(self, roundtrip):
        _p, summary, _r0, _g, _pf = roundtrip
        assert [s["stage"] for s in summary.stages] == [2, 3]
        assert summary.stages[0]["n_params"] == 6 + 2     # 晶胞 6 + 零位 1 + 位移 1
        assert summary.stages[1]["Rwp"] <= summary.stages[0]["Rwp"] + 1e-9


class TestMetricsFreshness:
    """``metrics()`` 不能复用上一次线性解。

    曾经的写法是 ``lin = self.last_linear or solve_linear(...)``：外部改了非线性
    参数（手工设 size、``restore`` 快照、换峰宽）而没有重解时，``last_linear``
    里的 ``y_calc`` 还是旧的 —— 现象是"把 size 从 0 拖到 500 nm，Rwp 一位小数
    都不变"，而模型本身完全正常。这类"静默报旧值"比报错危险得多，故立此守卫。
    """

    @staticmethod
    def _direct_rwp(prob) -> float:
        """绕开 metrics()：残差自算 Rwp（residual() 内部必然重解）。"""
        r = prob.residual(None)
        return float(100.0 * np.sqrt(np.sum(r ** 2)
                                     / np.sum(prob.weights * prob.y_obs ** 2)))

    def _problem(self):
        grid = np.linspace(15.0, 75.0, 1201)
        tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
        basis = design_matrix(grid, [PhaseSpec(tab)],
                              ProfileParams(**TRUE_PROFILE), cutoff_fwhm=CUT)
        bg = BackgroundParams("tent", 8)
        y = (basis @ np.array([SCALE_TRUE]) + background_basis(grid, bg) @ BG_TRUE)
        return PatternProblem(
            grid, y, [PhaseBlock("LFP", _lfp())],
            profile=ProfileParams(w=0.03, x=0.006, y=0.0), bg=bg,
            weights=1.0 / np.maximum(y, 1.0), cutoff_fwhm=CUT,
        )

    def test_matches_residual_after_manual_change(self):
        prob = self._problem()
        prob.residual(None)                     # 先制造一个 last_linear
        r0 = prob.metrics()["Rwp"]
        assert r0 == pytest.approx(self._direct_rwp(prob), rel=1e-8)

        prob.params.set("phase0.size", 150.0)   # 手工改动，不经过拟合器
        prob.apply()
        r1 = prob.metrics()["Rwp"]
        assert r1 == pytest.approx(self._direct_rwp(prob), rel=1e-8)
        assert r1 > r0 + 0.5, "size 改变后 Rwp 必须跟着动（否则就是吃了旧解）"

    def test_tracks_strain_change(self):
        prob = self._problem()
        prob.residual(None)
        r0 = prob.metrics()["Rwp"]
        prob.params.set("phase0.strain", 0.004)
        prob.apply()
        assert prob.metrics()["Rwp"] > r0 + 0.5


class TestCaching:
    def test_table_cached_until_cell_changes(self):
        grid = np.linspace(12.0, 60.0, 601)
        prob = PatternProblem(
            grid, np.full(grid.size, 100.0),
            [PhaseBlock("LFP", _lfp())], bg=BackgroundParams("none"),
        )
        prob.residual(None)
        key = prob.phases[0]._table_key
        prob.residual(None)
        assert prob.phases[0]._table_key is key or \
            prob.phases[0]._table_key == key
        prob.params.set("phase0.cell.a", 10.35)
        prob.apply()
        prob.residual(None)
        assert prob.phases[0]._table_key != key

    def test_design_cache_key_covers_profile(self):
        grid = np.linspace(12.0, 60.0, 601)
        prob = PatternProblem(
            grid, np.full(grid.size, 100.0),
            [PhaseBlock("LFP", _lfp())], bg=BackgroundParams("none"),
        )
        prob.apply()
        k0 = prob._make_design_key()
        prob.params.set("inst.w", 0.05)
        prob.apply()
        assert prob._make_design_key() != k0


class TestDisp:
    """``inst.disp``：样品位移项 ``Δ2θ = disp·cosθ``（v5.1，P1-8 第 1 件）。

    与零位的分野必须**可辨识**：zero 是常数、disp 随角衰减（cos15°=0.966 →
    cos75°=0.259）。只测位移场景就能把两者分开 —— 纯 cosθ 偏移的谱，只放
    零位补不掉（低角补上了高角就偏），零位 + 位移一起放才收得干净。
    """

    GRID = np.linspace(15.0, 75.0, 1201)
    DISP_TRUE = 0.12

    def _problem(self):
        tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
        prof = ProfileParams(**TRUE_PROFILE)
        basis = design_matrix(self.GRID, [PhaseSpec(tab)], prof,
                              cutoff_fwhm=CUT, disp=self.DISP_TRUE)
        y_obs = basis @ np.array([SCALE_TRUE])       # 无噪：回收精度不受统计限制
        prob = PatternProblem(
            self.GRID, y_obs, [PhaseBlock("LFP", _lfp())],
            profile=prof, bg=BackgroundParams("none"),
            weights=1.0 / np.maximum(y_obs, 1.0), cutoff_fwhm=CUT,
        )
        # 只考察峰位：与位移无关的阶段全部推到 9（不进 stage 2）
        prob.params = prob.build_parameters(
            stages={"cell": 9, "po": 9, "sample": 9, "asym": 9, "profile": 9})
        prob.apply()
        prob.invalidate()
        return prob

    def test_shift_is_costheta_shaped(self):
        """位移量必须严格是 ``disp·cosθ``，而不是另一个常数平移。"""
        tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
        c0, _, _ = reflection_centers_and_intensities(tab)
        c1, _, _ = reflection_centers_and_intensities(tab, disp=self.DISP_TRUE)
        got = c1 - c0
        want = self.DISP_TRUE * np.cos(np.radians(c0) / 2.0)
        assert np.max(np.abs(got - want)) < 1e-9

    def test_ka2_shifts_together(self):
        """位移作用于 Kα2 拆分之前 → Kα1/Kα2 两条线同步平移。"""
        tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
        ka2 = Kalpha2()
        c0, _, _ = reflection_centers_and_intensities(tab, ka2)
        c1, _, _ = reflection_centers_and_intensities(tab, ka2,
                                                      disp=self.DISP_TRUE)
        assert c0.shape == c1.shape
        d = c1 - c0
        # Kα2 线的 2θ 略大、cosθ 略小：位移项按各自 2θ 取 cosθ，与用 Kα1 位置
        # 估计的 want 差二阶小量（实测 ≤1.4e-4°，远低于峰位精度）
        want = self.DISP_TRUE * np.cos(np.radians(c0) / 2.0)
        assert np.max(np.abs(d - want)) < 3e-4

    def test_zero_alone_cannot_fix(self):
        """纯 cosθ 偏移只放零位：低角补上、高角就偏，Rwp 收不下去。"""
        prob = self._problem()
        prob.params["inst.disp"].stage = 9      # 把位移推出 stage 2
        summary = prob.fit(stages=(2,), max_iter_per_stage=60)
        # 实测只放零位收到 4.8%（无噪底 ~0%）：低角补上、高角就偏，收不干净。
        # 别把阈值写太高 —— zero 能吸收 cosθ 曲线的加权平均，剩余不是零。
        assert summary.metrics["Rwp"] > 2.0, (
            f"只放零位竟能收到 {summary.metrics['Rwp']:.2f}% —— "
            "zero 与 disp 已不可分辨，测试场景失效")

    def test_disp_recovered(self):
        prob = self._problem()
        summary = prob.fit(stages=(2,), max_iter_per_stage=60)
        got = float(prob.params.get("inst.disp"))
        assert abs(got - self.DISP_TRUE) < 0.02, f"disp 回收 {got:.4f}"
        assert summary.metrics["Rwp"] < 0.5

    def test_design_cache_key_covers_disp(self):
        """disp 改了设计矩阵必须跟着改（否则就是吃了旧基，v5.0 的老坑）。"""
        prob = self._problem()
        prob.residual(None)
        yc0 = prob.calc_pattern().copy()
        k0 = prob._make_design_key()
        prob.params.set("inst.disp", self.DISP_TRUE + 0.08)
        prob.apply()
        assert prob._make_design_key() != k0
        assert prob.disp == pytest.approx(self.DISP_TRUE + 0.08)
        # 加权 Rwp 对"偏多少"不单调（0.20 离真值 0.12 比全偏 0.12 还近），
        # 所以这里断言**计算谱本身变了**，而不是 Rwp 变差
        yc1 = prob.calc_pattern()
        assert np.max(np.abs(yc1 - yc0)) > 1e-6 * max(yc0.max(), 1.0)
