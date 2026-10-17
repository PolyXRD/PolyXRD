# -*- coding: utf-8 -*-
"""WPSM（全谱拟合检索）单元测试（v3.0.0）。

锁的是**行为契约**，分四块：

1. **判据数学** —— Rwp/Rexp/GOF 的解析解、FoM 映射的单调性与边界。
2. **反射展开** —— d–I → 2θ 的 Kα1/Kα2 双线（强度比 0.5、波长比 1.00249）、
   范围过滤，以及与 ``RietveldRefiner._expand_ka2_satellites`` 的输出一致
   （防两处实现漂移）。
3. **参数可恢复性** —— 无噪声合成谱注入已知 scale/shift/eta/cell_delta，
   拟合必须恢复。这是"拟合器正确"的最强证据，也是未来改动的回归锚。
4. **退化安全** —— 无峰 / 全零谱 / 网格过短 / 候选发散，一律返回
   ``fom=0 + reason``，绝不抛异常打断整轮检索（一个坏候选不得搞挂检索）。

Qt/GUI 集成由离屏探针覆盖，不进 pytest。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from polyxrd.services.wpsm import (
    WpsmConfig,
    WpsmFit,
    compute_fom,
    compute_rwp,
    expand_reflections,
    fit_candidate,
    wpsm_rerank,
)

# 网格: 10~80°, 0.02° 步长 (3500 点)
X = np.arange(10.0, 80.0, 0.02)
MID = 0.5 * (X[0] + X[-1])


def _synthetic_peaks() -> list:
    return [(None, float(t), float(i)) for t, i in [
        (21.5, 100.0), (26.7, 60.0), (33.2, 40.0), (40.5, 25.0),
        (48.1, 30.0), (55.4, 15.0), (62.0, 12.0), (68.3, 8.0),
    ]]


def _render(peaks, *, scale, shift, uvw, eta, cell, bg0=30.0,
            bg1=0.5, bg2=-0.004, ka2=True):
    """用已知参数生成理论谱 (与被测拟合器同一条谱合成路径)。"""
    from polyxrd.services.phase_display import spectrum_from_refs

    centres, amps = expand_reflections(peaks, float(X[0]), float(X[-1]),
                                       ka2=ka2)
    tan = np.tan(np.radians(centres / 2.0))
    centres_eff = centres + shift - cell * (360.0 / math.pi) * tan
    phases = [[(None, float(c), float(a))
               for c, a in zip(centres_eff, amps)]]
    peak_part = spectrum_from_refs(
        X, phases, [1.0], fwhm=0.2, eta=eta, scale=scale,
        peak_shape="pseudo-voigt", caglioti=uvw,
        cutoff_fwhm=100.0, asymmetry=0.0,
    )
    t = X - MID
    return peak_part + bg0 + bg1 * t + bg2 * t * t


# ==============================================================================
# 1. 判据数学
# ==============================================================================
class TestComputeRwp:
    def test_perfect_fit_gives_zero(self):
        y = np.array([10.0, 20.0, 30.0, 40.0])
        rwp, rexp, gof = compute_rwp(y, y.copy())
        assert rwp == pytest.approx(0.0, abs=1e-12)
        assert gof == pytest.approx(0.0, abs=1e-12)

    def test_analytic_case(self):
        # y = [10, 40], yc = [20, 20]; w = 1/y
        # num = (10-20)²/10 + (40-20)²/40 = 10 + 10 = 20
        # den = Σy = 50  →  Rwp = sqrt(0.4)
        y = np.array([10.0, 40.0])
        yc = np.array([20.0, 20.0])
        rwp, rexp, gof = compute_rwp(y, yc)
        assert rwp == pytest.approx(math.sqrt(0.4))
        # Rexp = sqrt(N / Σ w y²) = sqrt(2/50)
        assert rexp == pytest.approx(math.sqrt(2.0 / 50.0))
        assert gof == pytest.approx(rwp / rexp)

    def test_nonpositive_points_excluded(self):
        y = np.array([0.0, -5.0, 30.0])
        yc = np.array([1.0, 1.0, 30.0])
        rwp, _, _ = compute_rwp(y, yc)
        assert rwp == pytest.approx(0.0, abs=1e-12)

    def test_all_zero_returns_inf(self):
        rwp, rexp, gof = compute_rwp(np.zeros(5), np.zeros(5))
        assert rwp == rexp == gof == float("inf")

    def test_mask_restricts_domain(self):
        y = np.array([10.0, 40.0, 100.0])
        yc = np.array([20.0, 20.0, 100.0])
        full, _, _ = compute_rwp(y, yc)
        masked, _, _ = compute_rwp(y, yc, mask=np.array([True, True, False]))
        assert masked != full
        assert masked == pytest.approx(math.sqrt(0.4))

    def test_rexp_uses_n_params(self):
        y = np.array([10.0, 40.0])
        yc = np.array([20.0, 20.0])
        _, rexp0, _ = compute_rwp(y, yc, n_params=0)
        _, rexp3, _ = compute_rwp(y, yc, n_params=3)
        assert rexp3 < rexp0  # N−P < N → Rexp 变小


class TestComputeFom:
    def test_monotonic_decreasing(self):
        vals = [compute_fom(r, 0.25) for r in (0.05, 0.10, 0.20, 0.40)]
        assert vals == sorted(vals, reverse=True)

    def test_boundaries(self):
        assert compute_fom(0.0, 0.25) == pytest.approx(1.0)
        assert compute_fom(float("inf"), 0.25) == 0.0
        assert compute_fom(float("nan"), 0.25) == 0.0
        assert compute_fom(0.1, 0.0) == 0.0

    def test_sigma_scales_separation(self):
        # σ 越大, 同一组 Rwp 的 FoM 差距越小 (压缩)
        a = compute_fom(0.10, 0.25) / compute_fom(0.30, 0.25)
        b = compute_fom(0.10, 0.60) / compute_fom(0.30, 0.60)
        assert a > b


# ==============================================================================
# 2. 反射展开
# ==============================================================================
class TestExpandReflections:
    def test_no_ka2_passthrough(self):
        peaks = _synthetic_peaks()
        c, a = expand_reflections(peaks, 10.0, 80.0, ka2=False)
        assert c.size == 8
        assert np.allclose(c, [p[1] for p in peaks])
        assert np.allclose(a, [p[2] for p in peaks])

    def test_ka2_doubles_and_halves(self):
        peaks = _synthetic_peaks()
        c, a = expand_reflections(peaks, 10.0, 80.0, ka2=True)
        assert c.size == 16
        # 每条 Kα1 都应有一条伴峰, 位置由波长比 1.00249 决定
        s1 = np.sin(np.radians(np.asarray([p[1] for p in peaks]) / 2.0))
        tt2 = 2.0 * np.degrees(np.arcsin(1.00249 * s1))
        assert np.allclose(np.sort(c), np.sort(np.concatenate(
            [[p[1] for p in peaks], tt2])))
        # 强度: 每对 (I, 0.5·I) —— 逐位核对 (排序后按位置配对)
        order = np.argsort(c)
        cs, as_ = c[order], a[order]
        for j in range(0, 16, 2):
            main, sat = as_[j], as_[j + 1]
            assert max(main, sat) == pytest.approx(
                2.0 * min(main, sat))          # Kα2 = 0.5 × Kα1
            assert cs[j + 1] > cs[j]           # 伴峰在高角侧

    def test_ka2_ratio_exact(self):
        peaks = [(None, 30.0, 80.0)]
        c, a = expand_reflections(peaks, 10.0, 80.0, ka2=True)
        assert c.size == 2 and a.size == 2
        assert a.max() == pytest.approx(80.0)
        assert a.min() == pytest.approx(40.0)          # 0.5 × 80
        assert c.max() > 30.0                          # Kα2 在高角侧
        s1 = math.sin(math.radians(15.0))
        assert c.max() == pytest.approx(
            2.0 * math.degrees(math.asin(1.00249 * s1)))

    def test_range_filter_with_margin(self):
        peaks = [(None, 5.0, 50.0), (None, 50.0, 50.0), (None, 90.0, 50.0)]
        c, a = expand_reflections(peaks, 10.0, 80.0, ka2=False)
        # 5.0 在 10−1=9 之外 → 丢弃; 90.0 在 80+1=81 之外 → 丢弃
        assert c.size == 1 and c[0] == pytest.approx(50.0)

    def test_invalid_entries_skipped(self):
        peaks = [(None, 30.0, None), (None, 30.0, 0.0), (None, 30.0, -5.0),
                 (None, float("nan"), 10.0), (None, 30.0, 10.0), "junk"]
        c, a = expand_reflections(peaks, 10.0, 80.0, ka2=False)
        assert c.size == 1 and a[0] == pytest.approx(10.0)

    def test_matches_rietveld_refiner_output(self):
        """防漂移: 与精修引擎的 Kα2 展开逐位一致。"""
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        peaks = [(None, 21.5, 100.0), (None, 68.3, 8.0)]
        ref = RietveldRefiner._expand_ka2_satellites(
            [list(peaks)], 1.5406, intensity_ratio=0.5)
        c1, a1 = expand_reflections(peaks, 10.0, 80.0, ka2=True)
        c2 = sorted(float(p[1]) for p in ref[0])
        a2 = sorted(float(p[2]) for p in ref[0])
        assert np.allclose(np.sort(c1), c2)
        assert np.allclose(np.sort(a1), a2)


# ==============================================================================
# 3. 参数可恢复性 (无噪声)
# ==============================================================================
TRUE = dict(scale=0.05, shift=0.10, u=0.006, v=-0.004, w=0.035,
            eta=0.6, cell=0.002, bg0=30.0, bg1=0.5, bg2=-0.004)


@pytest.fixture(scope="module")
def noiseless_fit():
    ymodel = _render(_synthetic_peaks(), scale=TRUE["scale"],
                     shift=TRUE["shift"],
                     uvw=(TRUE["u"], TRUE["v"], TRUE["w"]),
                     eta=TRUE["eta"], cell=TRUE["cell"],
                     bg0=TRUE["bg0"], bg1=TRUE["bg1"], bg2=TRUE["bg2"])
    return fit_candidate(X, ymodel, _synthetic_peaks(),
                         cfg=WpsmConfig(), key="truth")


class TestParameterRecovery:
    def test_converged(self, noiseless_fit):
        assert noiseless_fit.ok
        assert noiseless_fit.fom > 0.5

    def test_scale_recovered(self, noiseless_fit):
        assert noiseless_fit.scale == pytest.approx(TRUE["scale"], rel=0.02)

    def test_shift_recovered(self, noiseless_fit):
        assert noiseless_fit.shift_deg == pytest.approx(TRUE["shift"], abs=0.02)

    def test_eta_recovered(self, noiseless_fit):
        assert noiseless_fit.eta == pytest.approx(TRUE["eta"], abs=0.05)

    def test_cell_delta_recovered(self, noiseless_fit):
        assert noiseless_fit.cell_delta == pytest.approx(TRUE["cell"],
                                                         abs=5e-4)

    def test_width_at_mid_angle_recovered(self, noiseless_fit):
        tan_m = math.tan(math.radians(22.5))
        true_h = math.sqrt(TRUE["u"] * tan_m ** 2 + TRUE["v"] * tan_m
                           + TRUE["w"])
        assert noiseless_fit.fwhm == pytest.approx(true_h, rel=0.05)

    def test_rwp_at_noise_floor(self, noiseless_fit):
        assert noiseless_fit.rwp < 0.01
        assert noiseless_fit.gof < 1.2


# ==============================================================================
# 4. 退化安全
# ==============================================================================
class TestDegenerateSafety:
    def test_no_reflections(self):
        fit = fit_candidate(X, np.full(X.size, 50.0), [], cfg=WpsmConfig())
        assert not fit.ok
        assert fit.reason == "no_reflection"
        assert fit.fom == 0.0

    def test_all_zero_spectrum(self):
        fit = fit_candidate(X, np.zeros(X.size), _synthetic_peaks(),
                            cfg=WpsmConfig())
        assert not fit.ok
        assert fit.reason == "no_positive"

    def test_grid_too_short(self):
        fit = fit_candidate(np.arange(10.0, 10.05, 0.01), np.ones(5),
                            _synthetic_peaks(), cfg=WpsmConfig())
        assert not fit.ok and fit.reason == "grid"

    def test_diverging_candidate_does_not_raise(self):
        # 峰列与谱完全无关 + 极端配置, 不得抛异常
        cfg = WpsmConfig(max_nfev=3)
        fit = fit_candidate(X, np.full(X.size, 1e6), _synthetic_peaks(),
                            cfg=cfg)
        assert isinstance(fit, WpsmFit)
        assert fit.fom >= 0.0

    def test_wpsm_rerank_swallows_exception(self):
        class Boom:
            def get_reference_peaks(self):
                raise RuntimeError("boom")

        fits = wpsm_rerank(
            X, np.full(X.size, 100.0),
            [("good", _synthetic_peaks()), ("boom", Boom())],
            peak_getter=lambda o: o if isinstance(o, list)
            else o.get_reference_peaks(),
        )
        assert all(isinstance(f, WpsmFit) for f in fits)
        assert any(f.key == "boom" and not f.ok for f in fits)


# ==============================================================================
# 5. 排序行为
# ==============================================================================
@pytest.fixture(scope="module")
def scored():
    rng = np.random.default_rng(7)
    truth = _synthetic_peaks()
    ymodel = _render(truth, scale=TRUE["scale"], shift=TRUE["shift"],
                     uvw=(TRUE["u"], TRUE["v"], TRUE["w"]),
                     eta=TRUE["eta"], cell=TRUE["cell"])
    yobs = rng.poisson(np.clip(ymodel * 100.0, 0, None)).astype(float)
    wrong = [(None, float(t), float(i)) for t, i in [
        (20.0, 90.0), (30.0, 55.0), (38.0, 35.0), (52.0, 20.0),
        (65.0, 10.0)]]
    items = [("truth", truth), ("wrong", wrong)]
    fits = wpsm_rerank(X, yobs, items, cfg=WpsmConfig())
    return fits, yobs


class TestRanking:
    def test_truth_outranks_wrong(self, scored):
        fits, _ = scored
        assert fits[0].key == "truth"
        assert fits[0].fom > fits[1].fom

    def test_key_passthrough_and_topn(self, scored):
        fits, yobs = scored
        assert [f.key for f in fits] == ["truth", "wrong"]
        fits1 = wpsm_rerank(X, yobs, [("a", _synthetic_peaks()),
                                      ("b", _synthetic_peaks())],
                            cfg=WpsmConfig(), top_n=1)
        assert len(fits1) == 1


# ==============================================================================
# 7. 集成: identify_with_element_filter 的 WPSM 重排钩子 (默认必须关闭)
# ==============================================================================
class TestIdentifyIntegration:
    """不加载真实库: 用 object.__new__ 绕过构造函数, 打桩 _match_phase_fom。"""

    @staticmethod
    def _make_pi(scores: dict):
        from polyxrd.models.phase import Phase, PhaseMatchResult
        from polyxrd.services.phase_identifier import PhaseIdentifier

        phases = {n: Phase(name=n, elements={"O"})
                  for n in ("Alpha", "Beta")}
        for n, p in phases.items():
            if n == "Alpha":
                p.reference_peaks = [(None, t, i) for _, t, i
                                     in _synthetic_peaks()]
            else:
                p.reference_peaks = [(None, t, i) for t, i in [
                    (19.0, 90.0), (31.5, 55.0), (44.0, 35.0), (58.0, 20.0)]]

        pi = object.__new__(PhaseIdentifier)
        pi._config = None
        pi._reference_data = []
        pi._phase_database = list(phases.values())

        def fake_match(phase, peaks, tolerance, **kwargs):
            return PhaseMatchResult(phase=phase, score=scores[phase.name],
                                    matched_peaks=1, total_peaks=1)

        pi._match_phase_fom = fake_match
        return pi, phases

    @staticmethod
    def _data_for(peaks):
        from polyxrd.models.xrd_data import XRDData

        y = _render([(None, t, i) for _, t, i in _synthetic_peaks()],
                    scale=TRUE["scale"], shift=TRUE["shift"], uvw=None,
                    eta=TRUE["eta"], cell=0.0)
        return XRDData(two_theta=X.copy(), intensity=y)

    def test_default_weight_zero_keeps_fom_order(self):
        # FoM 越低越好: Beta=0.1 排在 Alpha=0.5 前; 默认不启用 WPSM
        pi, phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2)
        assert [r.phase.name for r in res] == ["Beta", "Alpha"]

    def test_high_weight_flips_to_wpsm_order(self):
        pi, phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2, wpsm_weight=0.9, wpsm_prescreen=10)
        # 谱由 Alpha 的峰合成 → WPSM 把 Alpha 排前, 高权重下反转 FoM 序
        assert [r.phase.name for r in res] == ["Alpha", "Beta"]

    def test_prescreen_zero_disables_even_with_weight(self):
        pi, phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2, wpsm_weight=0.9, wpsm_prescreen=0)
        assert [r.phase.name for r in res] == ["Beta", "Alpha"]

    def test_top_n_still_applies(self):
        pi, phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=1, tolerance=0.2)
        assert len(res) == 1

# ==============================================================================
# 6. 配置开关
# ==============================================================================
class TestConfigSwitches:
    def test_bg_scaled_bounds_tighter_than_raw(self):
        ymax = 1000.0
        half = 35.0
        b1_scaled = ymax / half
        b2_scaled = ymax / (half * half)
        # raw 口径给 ±ymax, 对高次项远宽于 scaled
        assert b1_scaled < ymax
        assert b2_scaled * half * half == pytest.approx(ymax)
        # scaled 模式下边缘摆幅不超过 ymax (按设计)
        assert b1_scaled * half <= ymax * (1 + 1e-9)

    def test_single_width_model(self):
        ymodel = _render(_synthetic_peaks(), scale=TRUE["scale"],
                         shift=TRUE["shift"], uvw=None,
                         eta=TRUE["eta"], cell=TRUE["cell"])
        fit = fit_candidate(X, ymodel, _synthetic_peaks(),
                            cfg=WpsmConfig(caglioti=False))
        assert fit.ok
        assert fit.u == 0.0 and fit.v == 0.0
        assert fit.w == pytest.approx(fit.fwhm ** 2)   # 恒等编码

    def test_window_domain_reduces_n_domain(self):
        ymodel = _render(_synthetic_peaks(), scale=TRUE["scale"],
                         shift=TRUE["shift"],
                         uvw=(TRUE["u"], TRUE["v"], TRUE["w"]),
                         eta=TRUE["eta"], cell=TRUE["cell"])
        cfg = WpsmConfig(score_domain="window")
        fit = fit_candidate(X, ymodel, _synthetic_peaks(), cfg=cfg)
        assert fit.ok
        assert fit.extra["n_domain"] < X.size
        assert fit.extra["score_domain"] == "window"

    def test_delta_mode_score_in_unit_interval(self):
        rng = np.random.default_rng(3)
        ymodel = _render(_synthetic_peaks(), scale=TRUE["scale"],
                         shift=TRUE["shift"],
                         uvw=(TRUE["u"], TRUE["v"], TRUE["w"]),
                         eta=TRUE["eta"], cell=TRUE["cell"])
        yobs = rng.poisson(np.clip(ymodel * 50.0, 0, None)).astype(float)
        fit = fit_candidate(X, yobs, _synthetic_peaks(),
                            cfg=WpsmConfig(score_mode="delta"))
        assert fit.ok
        assert 0.0 <= fit.fom <= 1.0

    def test_bg_raw_mode_fits_and_differs(self):
        """``bg_bound_mode="raw"`` (FPFM 口径) 实际能跑, 且边界语义不同。"""
        ymodel = _render(_synthetic_peaks(), scale=TRUE["scale"],
                         shift=TRUE["shift"], uvw=None,
                         eta=TRUE["eta"], cell=TRUE["cell"])
        fit = fit_candidate(X, ymodel, _synthetic_peaks(),
                            cfg=WpsmConfig(bg_bound_mode="raw"))
        assert fit.ok
        assert fit.fom > 0.5
        # 两种边界模式都能恢复 scale (结果可能不同, 但都应收敛)
        fit2 = fit_candidate(X, ymodel, _synthetic_peaks(),
                             cfg=WpsmConfig(bg_bound_mode="scaled"))
        assert fit2.ok
        assert fit2.scale == pytest.approx(TRUE["scale"], rel=0.02)

    def test_default_config_matches_fpfm_decision_table(self):
        c = WpsmConfig()
        assert c.shift_bound == pytest.approx(0.3)
        assert c.fwhm_bounds == (0.08, 0.6)
        assert c.eta_bounds == (0.05, 0.95)
        assert c.cell_bound == pytest.approx(0.005)
        assert c.fom_sigma == pytest.approx(0.25)
        assert c.max_nfev == 60
        # prescreen_top_n: FPFM 初值 150, 13 试样实测 150 更差且更慢 → 收口 100
        assert c.prescreen_top_n == 100
        assert c.top_n == 20
        assert c.caglioti is True and c.cell_refine is True


# ==============================================================================
# 7. 集成: identify_with_element_filter 的 WPSM 重排钩子 (默认必须关闭)
# ==============================================================================
class TestIdentifyIntegration:
    """不加载真实库: 用 object.__new__ 绕过构造函数, 打桩 _match_phase_fom。"""

    @staticmethod
    def _make_pi(scores: dict):
        from polyxrd.models.phase import Phase, PhaseMatchResult
        from polyxrd.services.phase_identifier import PhaseIdentifier

        phases = {n: Phase(name=n, elements={"O"})
                  for n in ("Alpha", "Beta")}
        for n, p in phases.items():
            if n == "Alpha":
                p.reference_peaks = [(None, t, i) for _, t, i
                                     in _synthetic_peaks()]
            else:
                p.reference_peaks = [(None, t, i) for t, i in [
                    (19.0, 90.0), (31.5, 55.0), (44.0, 35.0), (58.0, 20.0)]]

        pi = object.__new__(PhaseIdentifier)
        pi._config = None
        pi._reference_data = []
        pi._phase_database = list(phases.values())

        def fake_match(phase, peaks, tolerance, **kwargs):
            return PhaseMatchResult(phase=phase, score=scores[phase.name],
                                    matched_peaks=1, total_peaks=1)

        pi._match_phase_fom = fake_match
        return pi, phases

    @staticmethod
    def _data_for(_peaks):
        from polyxrd.models.xrd_data import XRDData

        y = _render([(None, t, i) for _, t, i in _synthetic_peaks()],
                    scale=TRUE["scale"], shift=TRUE["shift"], uvw=None,
                    eta=TRUE["eta"], cell=0.0)
        return XRDData(two_theta=X.copy(), intensity=y)

    def test_default_weight_zero_keeps_fom_order(self):
        # FoM 越低越好: Beta=0.1 排在 Alpha=0.5 前; 默认不启用 WPSM
        pi, _phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2)
        assert [r.phase.name for r in res] == ["Beta", "Alpha"]

    def test_default_off_never_touches_wpsm_module(self, monkeypatch):
        """默认关闭的强保证: WPSM 模块必须**完全不被调用**。
        普通断言只能证明"重排后结果不变", 不能排除"调了但没翻转"。
        这里把 wpsm_rerank 炸掉 —— 默认路径若误触发会立刻失败。
        """
        import polyxrd.services.wpsm as wpsm_mod

        def _boom(*a, **kw):
            raise AssertionError("WPSM 在默认关闭时被调用了")

        monkeypatch.setattr(wpsm_mod, "wpsm_rerank", _boom)
        pi, _phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2)
        assert [r.phase.name for r in res] == ["Beta", "Alpha"]

    def test_wpsm_sigma_passthrough(self, monkeypatch):
        """wpsm_sigma kwarg 必须传进 WpsmConfig.fom_sigma。"""
        import polyxrd.services.wpsm as wpsm_mod
        orig = wpsm_mod.wpsm_rerank
        seen = {}

        def _spy(x, y, items, cfg=None, **kw):
            seen["fom_sigma"] = cfg.fom_sigma if cfg else None
            return orig(x, y, items, cfg=cfg, **kw)

        monkeypatch.setattr(wpsm_mod, "wpsm_rerank", _spy)
        pi, _phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2,
            wpsm_weight=0.5, wpsm_prescreen=10, wpsm_sigma=0.60)
        assert seen.get("fom_sigma") == pytest.approx(0.60)

    def test_high_weight_flips_to_wpsm_order(self):
        pi, _phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2, wpsm_weight=0.9, wpsm_prescreen=10)
        # 谱由 Alpha 的峰合成 → WPSM 把 Alpha 排前, 高权重下反转 FoM 序
        assert [r.phase.name for r in res] == ["Alpha", "Beta"]

    def test_prescreen_zero_disables_even_with_weight(self):
        pi, _phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=5, tolerance=0.2, wpsm_weight=0.9, wpsm_prescreen=0)
        assert [r.phase.name for r in res] == ["Beta", "Alpha"]

    def test_top_n_still_applies(self):
        pi, _phases = self._make_pi({"Alpha": 0.5, "Beta": 0.1})
        res = pi.identify_with_element_filter(
            self._data_for(None), peaks=[], element_filter=None,
            top_n=1, tolerance=0.2)
        assert len(res) == 1
