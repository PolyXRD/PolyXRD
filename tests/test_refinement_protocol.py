"""v5.0.0 阶段 D 验收：分阶段协议 / 起点种子化 / 诚实诊断 / 产品分层 + GOAL。

四块对应方案 §4 的 D1–D4。断言的取向与前几个阶段一致：**只断言物理上可辨识
的量**，不锁死数值实现细节。

* 协议：断「Rwp 单调不升、日志字段齐、没跑的阶段不出现在日志里」，不断具体
  Rwp 小数（LM 的路径依赖会让它在 0.01% 量级抖动）。
* 种子：断「估计值落在可接受的误差带内」，其中零位/晶胞分离的容差是实测打出来
  的（0.03°），不是拍的。
* 诊断：断「该报的 code 一定在、不该报的一定不在」，不断 message 文案。
* 分层：断「没释放结构自由度就绝不能报真 Rietveld」—— 这是 D4 的核心承诺。
"""

from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement import (
    DEFAULT_PROTOCOL,
    PROTOCOLS,
    STAGE_LABELS,
    AtomSite,
    BackgroundParams,
    Cell,
    FitResult,
    PhaseBlock,
    PhaseSpec,
    PatternProblem,
    ProfileParams,
    QuantResult,
    StageSpec,
    StructureModel,
    Tier,
    ZeroSeed,
    audit,
    background_basis,
    build_reflections,
    build_report,
    classify_tier,
    design_matrix,
    design_stack,
    diagnose,
    evaluate_goals,
    find_observed_peaks,
    fraction_sigmas,
    full_covariance,
    linear_covariance,
    linear_sigmas,
    refined_stage,
    residual_stats,
    resolve_protocol,
    run_protocol,
    scale_correlations,
    seed_caglioti,
    seed_problem,
    seed_zero,
    snip_baseline,
)

CUT = 25.0
TRUE_CELL = (10.33, 6.01, 4.69)


def _lfp(cell=TRUE_CELL, name="LiFePO4") -> StructureModel:
    return StructureModel(
        sites=(
            AtomSite("Li", 0.0, 0.0, 0.0, 1.0, 0.5),
            AtomSite("Fe", 0.2821, 0.25, 0.9745, 1.0, 0.5),
            AtomSite("P", 0.0947, 0.25, 0.4183, 1.0, 0.5),
            AtomSite("O", 0.0966, 0.25, 0.7427, 1.0, 0.5),
            AtomSite("O", -0.0966, 0.75, 0.2573, 1.0, 0.5),
            AtomSite("O", 0.3466, 0.75, 0.2427, 1.0, 0.5),
        ),
        cell=Cell(*cell), name=name,
    )


def _synth_problem(seed: int = 11) -> PatternProblem:
    """LFP 合成谱（泊松噪声）+ 故意给错 0.3% 的晶胞 —— 未精修。"""
    rng = np.random.default_rng(seed)
    grid = np.linspace(15.0, 75.0, 2001)
    bg = BackgroundParams("tent", 8)
    tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
    basis = design_matrix(grid, [PhaseSpec(tab)],
                          ProfileParams(w=0.02, x=0.004, y=0.002),
                          cutoff_fwhm=CUT)
    # 强度口径含 1/V²，标度不能写死：按"最强峰 3000 counts"反推
    y_true = (basis @ np.array([3000.0 / basis.max()])
              + background_basis(grid, bg) @ np.linspace(30.0, 80.0, 8))
    y_obs = y_true + rng.normal(0.0, np.sqrt(np.maximum(y_true, 1.0)))
    init = _lfp(cell=(10.36, 6.04, 4.72))
    return PatternProblem(
        grid, y_obs, [PhaseBlock("LFP", init)],
        profile=ProfileParams(w=0.03, x=0.006, y=0.0), bg=bg,
        weights=1.0 / np.maximum(y_obs, 1.0), cutoff_fwhm=CUT,
    )


@pytest.fixture(scope="module")
def quick_fit():
    """合成谱（泊松噪声）→ 种子化 → quick 协议精修。返回 (problem, summary)。"""
    prob = _synth_problem()
    rwp0 = prob.metrics()["Rwp"]
    seed_problem(prob, apply=True)
    summary = run_protocol(prob, protocol="quick", max_iter_per_stage=40)
    return prob, summary, rwp0


# ── D1 分阶段协议 ─────────────────────────────────────────────

class TestStageProtocol:
    def test_labels_cover_all_stages(self):
        assert sorted(STAGE_LABELS) == list(range(1, 8))

    def test_labels_unique(self):
        assert len(set(STAGE_LABELS.values())) == len(STAGE_LABELS)

    def test_default_protocol_increasing(self):
        stages = [s.stage for s in DEFAULT_PROTOCOL]
        assert stages == sorted(stages) and len(set(stages)) == len(stages)

    def test_default_protocol_does_not_release_atoms(self):
        """默认协议必须止步于样品展宽（stage 5），结构自由度是显式选择。"""
        assert max(s.stage for s in DEFAULT_PROTOCOL) < 6

    def test_structure_protocol_releases_atoms(self):
        assert max(s.stage for s in PROTOCOLS["structure"]) >= 6

    def test_spec_label_defaults_to_stage_label(self):
        assert StageSpec(3).label == STAGE_LABELS[3]

    def test_spec_rejects_bad_stage(self):
        with pytest.raises(ValueError):
            StageSpec(0)

    def test_spec_rejects_bad_max_iter(self):
        with pytest.raises(ValueError):
            StageSpec(2, max_iter=0)

    def test_resolve_none_is_default(self):
        assert resolve_protocol(None) is DEFAULT_PROTOCOL

    def test_resolve_name(self):
        assert resolve_protocol("quick") is PROTOCOLS["quick"]

    def test_resolve_unknown_name(self):
        with pytest.raises(ValueError, match="未知协议"):
            resolve_protocol("nope")

    def test_resolve_ints(self):
        specs = resolve_protocol([2, 3])
        assert [s.stage for s in specs] == [2, 3]

    def test_resolve_decreasing_raises(self):
        with pytest.raises(ValueError, match="递增"):
            resolve_protocol([3, 2])

    def test_resolve_empty_raises(self):
        with pytest.raises(ValueError):
            resolve_protocol([])

    def test_resolve_bad_type(self):
        with pytest.raises(TypeError):
            resolve_protocol(["a"])

    def test_atom_params_stage_numbering(self):
        """build_parameters 的阶段号必须与 STAGE_LABELS 对齐。"""
        prob = PatternProblem(
            np.linspace(10.0, 60.0, 200), np.full(200, 10.0),
            [PhaseBlock("P", _lfp())])
        assert prob.params["phase0.po.r"].stage == 4
        assert prob.params["phase0.sizec"].stage == 5
        assert prob.params["phase0.atom0.occ"].stage == 6


class TestRunProtocol:
    def test_reaches_noise_floor(self, quick_fit):
        _p, summary, rwp0 = quick_fit
        assert rwp0 > 30.0
        assert summary.metrics["Rwp"] < 1.3 * summary.metrics["Rexp"]

    def test_gof_near_one(self, quick_fit):
        _p, summary, _r = quick_fit
        assert 0.85 < summary.metrics["GOF"] < 1.3

    def test_log_follows_protocol(self, quick_fit):
        _p, summary, _r = quick_fit
        assert [e["stage"] for e in summary.stages] == \
            [s.stage for s in PROTOCOLS["quick"]]

    def test_log_has_extra_fields(self, quick_fit):
        _p, summary, _r = quick_fit
        for e in summary.stages:
            for key in ("label", "rolled_back", "Rwp_before", "seconds"):
                assert key in e
            assert e["label"] in STAGE_LABELS.values()

    def test_rwp_monotone(self, quick_fit):
        _p, summary, _r = quick_fit
        vals = [e["Rwp"] for e in summary.stages]
        assert all(b <= a + 1e-9 for a, b in zip(vals, vals[1:]))

    def test_atoms_not_released(self, quick_fit):
        prob, summary, _r = quick_fit
        stage = refined_stage(summary)
        names = [prob.params.names()[i]
                 for i in prob.params.free_indices(stage)]
        assert names and not any(".atom" in n for n in names)

    def test_p_counts_only_released(self, quick_fit):
        """``metrics(stage=)`` 不能把没跑的自由度算进 P（否则 GOF 虚高）。"""
        prob, summary, _r = quick_fit
        stage = refined_stage(summary)
        assert prob.metrics(stage=stage)["n_params"] < \
            prob.metrics()["n_params"]


class TestRollback:
    def test_bad_stage_is_rolled_back(self, monkeypatch):
        """某段把 Rwp 弄差 > 阈值 → 撤回该段，参数与 Rwp 保持原样。"""
        from polyxrd.refinement import optimize

        # 必须是"有峰的谱"：全平谱上把晶胞搞烂只会让相基消失、背景独撑，
        # Rwp 反而更小（tent 基的单位分解可以精确表出常数），测不出回滚。
        prob = _synth_problem(seed=21)
        rwp_before = prob.metrics()["Rwp"]

        calls = {"n": 0}

        def fake(fun, x0, *, bounds=None, method="auto", max_iter=100,
                 callback=None, jac=None):
            # 第一段原样返回（Rwp 不变，建立"之前的 Rwp"），第二段跑飞
            calls["n"] += 1
            x = np.asarray(x0, dtype=float).copy()
            if calls["n"] > 1:
                x = np.full_like(x, 500.0)
            r = np.asarray(fun(x), dtype=float)
            return FitResult(x=x, cost=0.5 * float(r @ r), resid=r,
                             n_data=r.size, n_params=x.size, method="fake")

        monkeypatch.setattr(optimize, "minimize_residual", fake)
        summary = run_protocol(prob, protocol=[StageSpec(2), StageSpec(3)])
        assert summary.stages[0]["rolled_back"] is False
        assert summary.stages[1]["rolled_back"] is True
        assert abs(summary.metrics["Rwp"] - rwp_before) < 1e-9


# ── D2 起点种子化 ─────────────────────────────────────────────

def _gauss_pattern(centers, widths, heights, *, bg_scale=200.0, n=3001):
    x = np.linspace(5.0, 80.0, n)
    base = bg_scale * np.exp(-x / 20.0) + 30.0
    y = base.copy()
    for c, w, h in zip(centers, widths, heights):
        y = y + h * np.exp(-4.0 * np.log(2.0) * ((x - c) / w) ** 2)
    return x, y, base


class TestAmorphousHumps:
    """非晶宽隆进线性层（v5.5）：只扩 residual 用的基，不污染 design()。"""

    def test_humps_join_only_the_linear_layer(self):
        from polyxrd.refinement.amorphous_fit import HumpSpec

        prob = _synth_problem()
        seed_problem(prob, apply=True)
        rwp0 = prob.metrics()["Rwp"]
        q0 = prob.quantitative()
        n0 = prob.design()[0].shape[1]

        prob.set_amorphous_humps([HumpSpec(32.0, 6.0)])
        basis, _bg = prob._linear_basis()
        assert basis.shape[1] == n0 + 1
        # design() 必须还是晶体相 —— 协方差/Hill–Howard 都靠这一条
        assert prob.design()[0].shape[1] == n0
        rwp1 = prob.metrics()["Rwp"]
        assert rwp1 <= rwp0 + 1e-9          # 多一列自由度的最小二乘不会更差

        # 定量只认晶体相标度：宽隆列不能被算成一个"相"
        q1 = prob.quantitative()
        assert len(q1.fractions) == len(q0.fractions)
        assert float(sum(q1.fractions)) == pytest.approx(1.0, abs=1e-6)

        # 关掉后逐位回到原状（opt-in 不能留下任何残迹）
        prob.set_amorphous_humps(())
        assert prob.metrics()["Rwp"] == pytest.approx(rwp0, abs=1e-9)


class TestPeakFinding:
    def test_positions_and_widths(self):
        x, y, _b = _gauss_pattern((20.0, 35.0, 60.0), (0.12, 0.15, 0.18),
                                  (3000.0, 1500.0, 800.0))
        peaks = find_observed_peaks(x, y, baseline="snip")
        assert len(peaks) == 3
        for p, c, w in zip(peaks, (20.0, 35.0, 60.0), (0.12, 0.15, 0.18)):
            assert abs(p.two_theta - c) < 0.02
            assert abs(p.fwhm - w) / w < 0.05

    def test_survives_noise(self):
        rng = np.random.default_rng(3)
        x, y, _b = _gauss_pattern((18.0, 25.0, 40.0, 55.0),
                                  (0.10, 0.12, 0.14, 0.16),
                                  (2000.0, 800.0, 600.0, 400.0))
        y = y + rng.normal(0.0, np.sqrt(np.maximum(y, 1.0)))
        peaks = sorted(find_observed_peaks(x, y, baseline="snip"),
                       key=lambda p: -p.height)[:4]
        got = sorted(p.two_theta for p in peaks)
        for g, c in zip(got, (18.0, 25.0, 40.0, 55.0)):
            assert abs(g - c) < 0.05

    def test_flat_pattern_has_no_peaks(self):
        x = np.linspace(10.0, 80.0, 1000)
        assert find_observed_peaks(x, np.full(1000, 100.0)) == []

    def test_too_short_returns_empty(self):
        assert find_observed_peaks(np.linspace(10, 20, 10),
                                   np.ones(10)) == []


class TestSnip:
    def test_recovers_curved_baseline(self):
        x, y, base = _gauss_pattern((20.0, 35.0, 60.0), (0.12, 0.15, 0.18),
                                    (3000.0, 1500.0, 800.0))
        b = snip_baseline(x, y, window_deg=6.0)
        assert np.max(np.abs(b - base) / base) < 0.02

    def test_never_exceeds_data(self):
        rng = np.random.default_rng(2)
        x = np.linspace(10.0, 70.0, 1200)
        y = np.maximum(rng.normal(500.0, 20.0, 1200), 0.0)
        assert np.all(snip_baseline(x, y) <= y + 1e-9)

    def test_flat_input(self):
        x = np.linspace(10.0, 20.0, 200)
        b = snip_baseline(x, np.full(200, 50.0))
        assert np.allclose(b, 50.0, atol=1e-6)


class TestCagliotiSeed:
    def test_exact_recovery(self):
        u, v, w = 0.02, 0.01, 0.002
        angles = np.linspace(20.0, 70.0, 8)
        tan = np.tan(np.radians(angles / 2.0))
        fw = np.sqrt(u * tan ** 2 + v * tan + w)
        from polyxrd.refinement import PeakSeed

        peaks = [PeakSeed(float(a), 1000.0, float(f)) for a, f in zip(angles, fw)]
        seed = seed_caglioti(peaks)
        assert seed.ok
        assert seed.u == pytest.approx(u, abs=1e-9)
        assert seed.v == pytest.approx(v, abs=1e-9)
        assert seed.w == pytest.approx(w, abs=1e-9)

    def test_rejects_negative_constant_term(self):
        """外推 W<0 → 参数域外，必须退回只定常数项（否则会被 set 静默夹到 1e-9）。"""
        from polyxrd.refinement import PeakSeed

        # 三点抛物线 U=-0.195 V=+0.133 W=-0.0116：W<0 落在 inst.w 的下界之外
        angles = np.array([15.0, 30.0, 45.0])
        fw = np.array([0.05, 0.10, 0.10])
        peaks = [PeakSeed(float(a), 1000.0, float(f)) for a, f in zip(angles, fw)]
        seed = seed_caglioti(peaks)
        assert seed.ok is False
        assert seed.u == 0.0 and seed.v == 0.0
        assert seed.w > 0.0

    def test_too_few_peaks(self):
        from polyxrd.refinement import PeakSeed

        peaks = [PeakSeed(20.0, 100.0, 0.10), PeakSeed(30.0, 90.0, 0.20)]
        seed = seed_caglioti(peaks)
        assert seed.ok is False and seed.n_peaks == 2
        assert seed.w == pytest.approx(0.15 ** 2)

    def test_no_peaks(self):
        seed = seed_caglioti([])
        assert seed.ok is False and seed.n_peaks == 0


class TestZeroSeed:
    @staticmethod
    def _tables(cell):
        return build_reflections(_lfp(cell=cell), two_theta_range=(14.0, 76.0))

    def test_separates_cell_error_from_zero(self):
        """晶胞偏 0.29% 造成的线性偏差不能被当成零位。"""
        truth = self._tables(TRUE_CELL)
        calc = self._tables((10.36, 6.04, 4.72))
        obs = truth.two_theta[(truth.two_theta > 15) & (truth.two_theta < 75)]
        seed = seed_zero(obs, calc.two_theta)
        assert abs(seed.shift) < 0.03, seed
        assert seed.tilt > 0.2, seed

    def test_recovers_pure_offset(self):
        calc = self._tables(TRUE_CELL)
        obs = calc.two_theta[(calc.two_theta > 15) & (calc.two_theta < 75)] + 0.15
        seed = seed_zero(obs, calc.two_theta)
        assert seed.shift == pytest.approx(0.15, abs=0.03)

    def test_no_match_returns_zero(self):
        seed = seed_zero([10.0, 20.0], [100.0, 200.0], max_shift=0.1)
        assert seed == ZeroSeed()

    def test_empty_input(self):
        assert seed_zero([], [1.0, 2.0]) == ZeroSeed()

    def test_cell_scale_hint_sign(self):
        seed = seed_zero([20.0, 30.0, 40.0], [20.0, 30.0, 40.0])
        seed = ZeroSeed(0.0, 0.332, 3)
        assert seed.cell_scale_hint < 0.0
        assert seed.cell_scale_hint == pytest.approx(-0.0029, abs=2e-4)


class TestSeedProblem:
    def test_applies_to_params(self):
        rng = np.random.default_rng(5)
        grid = np.linspace(15.0, 75.0, 2001)
        tab = build_reflections(_lfp(), two_theta_range=(14.0, 76.0))
        basis = design_matrix(grid, [PhaseSpec(tab)], ProfileParams(w=0.02),
                              cutoff_fwhm=CUT)
        y = (basis @ np.array([3000.0 / basis.max()])
             + 40.0 + rng.normal(0.0, 1.0, grid.size))
        prob = PatternProblem(grid, y, [PhaseBlock("LFP", _lfp())],
                              profile=ProfileParams(w=0.05),
                              bg=BackgroundParams("tent", 6), cutoff_fwhm=CUT)
        bundle = seed_problem(prob, apply=True)
        assert bundle.peaks
        assert bundle.profile is not None
        assert prob.params.get("inst.w") != 0.05
        for tag in ("u", "v", "w", "zero"):
            val = prob.params.get(f"inst.{tag}")
            assert np.isfinite(val)
            lo, hi = prob.params[f"inst.{tag}"].min, prob.params[f"inst.{tag}"].max
            assert lo - 1e-9 <= val <= hi + 1e-9
        assert bundle.notes

    def test_no_peaks_keeps_defaults(self):
        grid = np.linspace(15.0, 75.0, 800)
        prob = PatternProblem(grid, np.full(800, 10.0),
                              [PhaseBlock("LFP", _lfp())])
        bundle = seed_problem(prob, apply=True)
        assert bundle.peaks == []
        assert any("未检出峰" in n for n in bundle.notes)


# ── D3 诚实诊断 ───────────────────────────────────────────────

class TestResidualStats:
    def test_white_noise_dw_near_two(self):
        rng = np.random.default_rng(1)
        x = np.linspace(10.0, 80.0, 2000)
        y = np.full(2000, 1000.0)
        yc = y + rng.normal(0.0, 10.0, 2000)
        st = residual_stats(x, y, yc)
        assert 1.8 < st.durbin_watson < 2.2

    def test_serial_correlation_low_dw(self):
        x = np.linspace(10.0, 80.0, 2000)
        y = np.full(2000, 1000.0)
        yc = y + 20.0 * np.sin(2.0 * np.pi * (x - 10.0) / 12.0)
        st = residual_stats(x, y, yc)
        assert st.durbin_watson < 1.0

    def test_perfect_fit_dw_nan(self):
        x = np.linspace(10.0, 20.0, 100)
        y = np.full(100, 5.0)
        st = residual_stats(x, y, y.copy())
        assert np.isnan(st.durbin_watson)

    def test_segments_split(self):
        x = np.linspace(10.0, 80.0, 1401)
        y = np.full(1401, 100.0)
        yc = y.copy()
        yc[x < 30.0] += 10.0
        st = residual_stats(x, y, yc)
        assert len(st.segment_rwp) == 3
        assert st.segment_rwp[0] > st.segment_rwp[2]

    def test_negative_calc_counted(self):
        x = np.linspace(10.0, 20.0, 50)
        yc = np.full(50, 10.0)
        yc[:4] = -1.0
        st = residual_stats(x, np.full(50, 10.0), yc)
        assert st.n_negative_calc == 4

    def test_empty(self):
        st = residual_stats([], [], [])
        assert st.n_points == 0 and np.isnan(st.durbin_watson)


class TestAudit:
    X = np.linspace(10.0, 80.0, 1000)

    def _base(self, y, yc):
        return audit(self.X, y, yc, 1.0 / np.maximum(y, 1.0),
                     kalph2_modeled=True, atoms_freed=True)

    def test_clean_fit_no_errors(self):
        y = np.full(1000, 100.0)
        findings = self._base(y, y.copy())
        assert [f for f in findings if f.severity == "error"] == []

    def test_gof_high_error(self):
        y = np.full(1000, 100.0)
        metrics = {"Rwp": 12.0, "Rp": 9.0, "Rexp": 1.0, "GOF": 12.0, "chi2": 144.0}
        findings = audit(self.X, y, y.copy(), metrics=metrics,
                         kalph2_modeled=True, atoms_freed=True)
        codes = {f.code: f.severity for f in findings}
        assert codes.get("GOF_HIGH") == "error"

    def test_gof_warn_tier(self):
        y = np.full(1000, 100.0)
        metrics = {"Rwp": 5.0, "Rp": 4.0, "Rexp": 1.0, "GOF": 5.0, "chi2": 25.0}
        findings = audit(self.X, y, y.copy(), metrics=metrics,
                         kalph2_modeled=True, atoms_freed=True)
        assert {f.code: f.severity for f in findings}["GOF_HIGH"] == "warn"

    def test_negative_calc_error(self):
        y = np.full(1000, 100.0)
        yc = y.copy()
        yc[500] = -5.0
        findings = self._base(y, yc)
        assert "NEGATIVE_CALC" in {f.code for f in findings}

    def test_ka2_info_when_unmodelled(self):
        y = np.full(1000, 100.0)
        findings = audit(self.X, y, y.copy(), kalph2_modeled=False,
                         atoms_freed=True)
        assert "KA2_UNMODELLED" in {f.code for f in findings}

    def test_unidentified_peak_reported(self):
        y = np.full(1000, 100.0)
        centre = 47.3
        y = y + 400.0 * np.exp(-4.0 * np.log(2.0) * ((self.X - centre) / 0.3) ** 2)
        findings = audit(self.X, y, np.full(1000, 100.0),
                         1.0 / np.maximum(y, 1.0), calc_centers=[20.0, 40.0, 60.0],
                         kalph2_modeled=True, atoms_freed=True)
        hits = [f for f in findings if f.code == "UNIDENTIFIED_PEAKS"]
        assert hits and abs(hits[0].evidence["first_at"] - centre) < 0.3

    def test_unidentified_skipped_without_calc_centers(self):
        y = np.full(1000, 100.0)
        centre = 47.3
        y = y + 400.0 * np.exp(-4.0 * np.log(2.0) * ((self.X - centre) / 0.3) ** 2)
        findings = self._base(y, np.full(1000, 100.0))
        assert "UNIDENTIFIED_PEAKS" not in {f.code for f in findings}

    def test_rank_deficient_passthrough(self):
        rng = np.random.default_rng(4)
        base = rng.normal(size=(300, 1))
        J = np.hstack([base, base * 1.0 + rng.normal(scale=1e-9, size=(300, 1))])
        diag = diagnose(J, ["a", "b"])
        y = np.full(1000, 100.0)
        findings = audit(self.X, y, y.copy(), diagnostics=diag,
                         kalph2_modeled=True, atoms_freed=True)
        assert "RANK_DEFICIENT" in {f.code for f in findings}

    def test_phase_not_detected(self):
        q = QuantResult(("A", "B"), (1.0, 0.0), (5.0, 0.0),
                        (1.0, 1.0), (1, 1), (1.0, 1.0), (1.0, 1.0),
                        (True, False))
        y = np.full(1000, 100.0)
        findings = audit(self.X, y, y.copy(), quant=q, kalph2_modeled=True,
                         atoms_freed=True)
        assert "PHASE_NOT_DETECTED" in {f.code for f in findings}

    def test_findings_sorted_by_severity(self):
        y = np.full(1000, 100.0)
        yc = y.copy()
        yc[10] = -1.0
        findings = audit(self.X, y, yc, kalph2_modeled=False, atoms_freed=False)
        order = {"error": 0, "warn": 1, "info": 2}
        ranks = [order[f.severity] for f in findings]
        assert ranks == sorted(ranks)


# ── D4 产品分层 + GOAL ────────────────────────────────────────

class TestTier:
    def _prob(self, sites=True):
        st = _lfp() if sites else StructureModel(sites=(), cell=Cell(*TRUE_CELL))
        return PatternProblem(np.linspace(10.0, 60.0, 200), np.full(200, 10.0),
                              [PhaseBlock("P", st)])

    def test_structure_free(self):
        assert classify_tier(self._prob(sites=False)) is Tier.STRUCTURE_FREE

    def test_le_bail_when_atoms_not_released(self):
        prob = self._prob()
        assert classify_tier(prob, stage=5) is Tier.LE_BAIL

    def test_rietveld_when_atoms_released(self):
        prob = self._prob()
        assert classify_tier(prob, stage=6) is Tier.RIETVELD

    def test_refined_stage_ignores_skipped(self):
        class _S:
            stages = ({"stage": 2, "status": "converged"},
                      {"stage": 3, "status": "skipped"})

        assert refined_stage(_S()) == 2

    def test_refined_stage_none(self):
        assert refined_stage(None) is None


class TestFractionSigma:
    @staticmethod
    def _quant(s0=2.0, s1=1.0):
        z = 1.0
        total = s0 * 2.0 * z + s1 * 1.0 * z
        f0 = s0 * 2.0 * z / total
        return QuantResult(("A", "B"), (f0, 1.0 - f0), (s0, s1),
                           (2.0, 1.0), (1, 1), (2.0, 1.0), (1.0, 1.0),
                           (True, True))

    def test_matches_finite_difference(self):
        q = self._quant()
        sig = np.array([0.05, 0.03])
        got = fraction_sigmas(q, sig)
        # 数值导数
        eps = 1e-6
        num = []
        for k in range(2):
            sp = list(q.scales)
            sm = list(q.scales)
            sp[k] += eps
            sm[k] -= eps
            def f(s):
                tot = sum(x * y for x, y in zip(s, q.factor))
                return s[0] * q.factor[0] / tot
            num.append((f(sp) - f(sm)) / (2 * eps))
        want = float(np.sqrt(sum((n * s) ** 2 for n, s in zip(num, sig))))
        assert got[0] == pytest.approx(want, rel=1e-5)

    def test_sum_of_sigmas_consistent(self):
        q = self._quant()
        got = fraction_sigmas(q, [0.05, 0.03])
        assert len(got) == 2 and all(np.isfinite(g) for g in got)

    def test_length_mismatch_gives_nan(self):
        q = self._quant()
        got = fraction_sigmas(q, [0.05])
        assert all(np.isnan(g) for g in got)


class TestGoals:
    def test_fraction_goal_present(self, quick_fit):
        prob, summary, _r = quick_fit
        goals = evaluate_goals(prob, summary, goals=("fraction",))
        assert len(goals) == 1
        assert goals[0].name == "fraction"
        assert goals[0].value == pytest.approx(100.0, abs=1e-6)
        assert np.isfinite(goals[0].sigma)

    def test_unreleased_goal_marked_unreliable(self, quick_fit):
        prob, summary, _r = quick_fit
        goals = {g.name: g for g in evaluate_goals(prob, summary,
                                                   goals=("size", "strain"))}
        assert goals["size"].reliable is False
        assert "未释放" in goals["size"].note

    def test_goal_text_marks_unreliable(self):
        from polyxrd.refinement import GoalResult

        g = GoalResult("size", "晶粒", 0.0, 0.0, "nm", False, "未释放")
        assert "⚠" in g.text()


class TestLinearUncertainty:
    def test_matches_linear_covariance_without_jac(self):
        rng = np.random.default_rng(9)
        n = 300
        x = np.linspace(0.0, 10.0, n)
        A = np.column_stack([np.exp(-((x - 3) ** 2)),
                             np.exp(-((x - 7) ** 2))])
        G = np.column_stack([np.ones(n), np.linspace(-1.0, 1.0, n)])
        w = np.full(n, 0.5)
        cov = linear_covariance(A, w, bg_basis=G, reduced_chi2=1.7)
        want = np.sqrt(np.diag(cov))[:2]
        got, bg_sig = linear_sigmas(None, A, w, bg_basis=G, reduced_chi2=1.7)
        assert np.allclose(got, want)
        assert bg_sig.size == 2
        assert rng is not None

    def test_full_covariance_shape(self):
        n = 200
        A = np.ones((n, 1))
        J = np.linspace(0.0, 1.0, n)[:, None]
        cov = full_covariance(J, A, np.ones(n))
        assert cov.shape == (2, 2)
        assert np.all(np.isfinite(cov))

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError):
            full_covariance(np.ones((10, 1)), np.ones((20, 1)))

    def test_scale_block_skips_nonlinear_columns(self):
        """带 jac 时相标度块必须从第 ``P_nonlin`` 列起，不能从第 0 列起。

        构造方式让判据**无容差争议**：把 J 投影到 A 的正交补上（``JᵀW A = 0``），
        于是 Schur 补 ``(AᵀWA − AᵀWJ(JᵀWJ)⁺JᵀWA)⁻¹`` 恰好等于 ``(AᵀWA)⁻¹`` ——
        带 jac 与不带 jac 的解必须逐元素相同。旧写法 ``cov[:n]`` 取到的是 J 的
        前 n 个参数，二者差出数量级（实测 ShiJK-4：0.004 vs 0.192）。
        """
        rng = np.random.default_rng(11)
        m, p, n, nb = 400, 6, 3, 2
        A = rng.normal(size=(m, n))
        G = rng.normal(size=(m, nb))
        w = rng.uniform(0.5, 2.0, m)
        Aw = design_stack(A, G)
        sw = np.sqrt(w)[:, None]
        # J ⟂ 加权后的 A（最小二乘投影残差）
        J0 = rng.normal(size=(m, p))
        Aw_w = Aw * sw
        J = J0 - Aw @ np.linalg.pinv(Aw_w.T @ Aw_w) @ (Aw_w.T @ (J0 * sw))
        assert np.allclose(J.T @ (Aw * w[:, None]), 0.0, atol=1e-10)

        want, _ = linear_sigmas(None, A, w, bg_basis=G)
        got, got_bg = linear_sigmas(J, A, w, bg_basis=G)
        assert np.allclose(got, want, rtol=1e-3, atol=1e-12)
        assert got_bg.size == nb

        c_none = scale_correlations(None, A, w, bg_basis=G)
        c_jac = scale_correlations(J, A, w, bg_basis=G)
        assert np.allclose(c_jac, c_none, rtol=5e-3, atol=5e-3)


class TestBuildReport:
    def test_report_fields(self, quick_fit):
        prob, summary, _r = quick_fit
        rep = build_report(prob, summary)
        assert rep.tier == Tier.LE_BAIL.value
        assert rep.metrics["Rwp"] > 0
        assert rep.residual is not None
        assert rep.goals
        d = rep.as_dict()
        assert d["tier"] == Tier.LE_BAIL.value
        assert isinstance(d["findings"], list)

    def test_text_renders(self, quick_fit):
        prob, summary, _r = quick_fit
        text = build_report(prob, summary).text()
        assert "Rwp" in text and "问题清单" in text

    def test_healthy_means_no_errors(self, quick_fit):
        prob, summary, _r = quick_fit
        rep = build_report(prob, summary)
        assert rep.healthy == (len(rep.errors) == 0)


class TestOneClick:
    """D4 的「一键入口」：run_tiered + build_report 一句话跑完。"""

    def test_one_click_runs_and_reports(self):
        from polyxrd.refinement import run_tiered

        prob = _synth_problem(seed=31)
        summary = run_tiered(prob, max_iter_per_stage=40)
        assert summary.metrics["Rwp"] < 1.3 * summary.metrics["Rexp"]
        rep = build_report(prob, summary)
        assert rep.tier == Tier.LE_BAIL.value      # 结构自由度没释放
        assert rep.goals

    def test_tier_selects_protocol(self):
        from polyxrd.refinement import protocol_for_tier

        assert protocol_for_tier(Tier.RIETVELD) == "structure"
        assert protocol_for_tier(Tier.LE_BAIL) == "default"

    def test_explicit_tier_overrides(self):
        from polyxrd.refinement import run_tiered

        prob = _synth_problem(seed=32)
        called = []
        summary = run_tiered(prob, tier=Tier.RIETVELD, seed=False,
                             callback=lambda e: called.append(e["stage"]),
                             max_iter_per_stage=8)
        # structure 协议 = 2,3,5,6,7；至少跑到结构阶段（6）
        assert 6 in called
        assert refined_stage(summary) is not None


class TestSampleBroadeningSeed:
    """stage 5 的尺寸起点必须是**非边界**值（基准报告 §十七）。

    ``{p}.sizec = 0`` 是参数边界。实测 2-2：从 0 出发停在 5e-7（Rwp 14.936），
    从 300 nm 等价出发收敛到 261.6 nm（Rwp 14.814）—— 差 0.12 pp 全丢在
    "LM 从边界迈不出步"上。
    """

    def test_seeded_when_stage5_present(self):
        prob = _synth_problem()
        run_protocol(prob, protocol=[StageSpec(5, 3)])
        assert float(prob.params["phase0.sizec"].value) > 0.0
        assert prob.phases[0].size_nm > 100.0

    def test_not_seeded_without_stage5(self):
        """fast 档没有 stage 5，塞一个展宽项进去等于偷自由度。"""
        prob = _synth_problem()
        run_protocol(prob, protocol=[StageSpec(2, 3)])
        assert float(prob.params["phase0.sizec"].value) == 0.0
        assert prob.phases[0].size_nm == 0.0

    def test_explicit_size_is_not_overwritten(self):
        """用户给了尺寸就不许被 500 nm 种子盖掉。"""
        from polyxrd.refinement.protocol import seed_sample_broadening

        prob = _synth_problem()
        prob.params.set("phase0.sizec", 0.06)      # ≙ 20 nm
        assert seed_sample_broadening(prob) == []
        assert float(prob.params["phase0.sizec"].value) == pytest.approx(0.06)
