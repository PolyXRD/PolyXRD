# -*- coding: utf-8 -*-
"""P0-G 第②件：微吸收「反推等效半径」只做诊断展示的守护。

口径（与 `docs/待办清单.md` P0-G 一致）
--------------------------------------
* τ 只进 Hill–Howard 定量、**不进拟合向量**，所以颗粒半径无法从单张谱反解。
  这里给的是诊断量：当前半径把份额搬了多少（``delta_wt_pp``）、每加 1 µm 还会
  再搬多少（``sensitivity_pp_per_um``）、要搬 ``target_pp`` 需要多大半径
  （``equivalent_radius_um``）。**绝不写回 wt%**。
* "反推只能给区间"：Brindley 表只覆盖 ``|(μ_j−μ̄)·R_j| ≤ 0.5``，越界 τ 被截成
  常数 —— 那么大的半径"也能解释"，但不是解，是截断。所以搜索上界收到表内
  （``radius_limit_um``），并用 ``delta_wt_at_limit_pp`` 给出表内能搬动的上限。
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
from polyxrd.refinement.intensity import BRINDLEY_X_LIMIT, mean_linear_mu
from polyxrd.refinement.quantitative import hill_howard
from polyxrd.services.rietveld_refiner import _radius_sweep_table

_CUT = 25.0
_PROFILE = ProfileParams(u=0.02, v=-0.01, w=0.012, x=0.01)
_BG = BackgroundParams("tent", 8)


def _cubic(element: str, a: float) -> StructureModel:
    sites = (AtomSite(element, 0.0, 0.0, 0.0, 1.0, 0.5, element),)
    return StructureModel(sites=sites, cell=Cell(a, a, a, 90.0, 90.0, 90.0),
                          space_group="P 1", name=element)


def _problem(n_phases: int, mu=None, scales=(4000.0, 3000.0, 2000.0)):
    """n 相合成谱 + 参数书（只用于拿到"同一轮"的标度与结构）。"""
    elems = [("Fe", 3.0), ("Al", 4.0), ("Si", 5.0)][:n_phases]
    structs = [_cubic(el, a) for el, a in elems]
    tt = np.linspace(15.0, 120.0, 1051)
    tabs = [build_reflections(st, two_theta_range=(13.0, 122.0))
            for st in structs]
    basis = design_matrix(tt, [PhaseSpec(t) for t in tabs], _PROFILE,
                          cutoff_fwhm=_CUT)
    amp = np.array([s / basis[:, i].max() for i, s in enumerate(scales[:n_phases])])
    y = (basis @ amp + background_basis(tt, _BG) @ np.linspace(50.0, 30.0, 8))
    prob = PatternProblem(
        tt, y,
        [PhaseBlock(el, st, index=i) for i, (el, _a, st)
         in enumerate([(e, a, s) for (e, a), s in zip(elems, structs)])],
        profile=_PROFILE, bg=_BG, weights=1.0 / np.maximum(y, 1.0),
        cutoff_fwhm=_CUT, wavelength=1.5406, mu_linear=mu, grain_radius_um=0.0)
    prob.apply()
    return prob, structs


def _table(mu, radii=None, *, n_phases=2, target_pp=1.0):
    prob, structs = _problem(n_phases, mu=mu)
    quant = prob.quantitative()
    table = _radius_sweep_table(prob, quant, list(mu),
                                radii if radii is not None else [0.0] * n_phases,
                                target_pp=target_pp)
    return prob, quant, structs, table


# ── 1. 基本形状与物理符号 ───────────────────────────────────────────
def test_reports_sensitivity_with_physical_sign():
    """高吸收相 R↑ ⇒ τ↓ ⇒ 份额↑；低吸收相相反。符号反了一切都反了。"""
    _p, _q, _s, table = _table([100.0, 900.0])
    assert len(table) == 2
    low, high = table[0], table[1]
    assert high["sensitivity_pp_per_um"] > 0.0
    assert low["sensitivity_pp_per_um"] < 0.0
    # 各自的"相对不修正"位移与灵敏度同号（同一段单调函数）
    assert high["delta_wt_pp"] == pytest.approx(0.0, abs=1e-9)
    for item in table:
        assert item["radius_um"] == 0.0
        assert np.isfinite(item["mu"])


def test_applied_radius_moves_fraction_towards_absorbing_phase():
    """当前半径>0 时，``delta_wt_pp`` 就是"已搬动量"，高吸收相为正。"""
    mu = [100.0, 900.0]
    prob, quant, _s, table = _table(mu, radii=[0.0, 4.0])
    high = table[1]
    assert high["radius_um"] == 4.0
    assert high["delta_wt_pp"] > 0.5          # 4 µm 已经搬了半个点以上

    # 与直接算的定量对照：delta 就是 "R=4" 与 "R=0" 两个定量结果的差
    labels = [b.label for b in prob.phases]
    scales = [float(v) for v in quant.scales]
    sts = [b.structure for b in prob.phases]

    def w_at(radii):
        q = hill_howard(labels, scales, sts, mu=mu, radius_um=list(radii))
        return 100.0 * np.asarray(q.fractions, dtype=float)

    expect = w_at([0.0, 4.0])[1] - w_at([0.0, 0.0])[1]
    assert high["delta_wt_pp"] == pytest.approx(expect, abs=1e-6)


# ── 2. 等效半径必须真的把份额搬到 target_pp ─────────────────────────
def test_equivalent_radius_reproduces_target_shift():
    mu = [100.0, 900.0]
    prob, quant, structs, table = _table(mu, target_pp=1.0)
    labels = [b.label for b in prob.phases]
    scales = [float(v) for v in quant.scales]
    sts = [b.structure for b in prob.phases]

    def w_at(radii):
        q = hill_howard(labels, scales, sts, mu=mu, radius_um=list(radii))
        return 100.0 * np.asarray(q.fractions, dtype=float)

    w0 = w_at([0.0, 0.0])
    for j, item in enumerate(table):
        need = item["equivalent_radius_um"]
        if need is None:
            continue
        rr = [0.0, 0.0]
        rr[j] = need
        moved = abs(w_at(rr)[j] - w0[j])
        # 二分容差：24 次在 10 µm 量级上 < 1e-6 µm；这里放宽到 0.02 pp
        assert moved == pytest.approx(1.0, abs=0.02)


def test_unreachable_target_returns_none_and_interval_width():
    """表内搬不到 target ⇒ ``None``（不是硬给一个表外的假解）。"""
    mu = [100.0, 900.0]
    _p, _q, _s, table = _table(mu, target_pp=50.0)
    assert table
    for item in table:
        assert item["equivalent_radius_um"] is None
        assert abs(item["delta_wt_at_limit_pp"]) < 50.0


# ── 3. 表内上限：越界靠截断换来的"吻合"不算解 ───────────────────────
def test_search_is_capped_by_brindley_table():
    mu = [10.0, 3000.0]
    _p, _q, _s, table = _table(mu, target_pp=0.2)
    prob, _structs = _problem(2, mu=mu)
    quant = prob.quantitative()
    mu_bar = mean_linear_mu(mu, [float(v) for v in quant.fractions])

    high = table[1]
    expect = BRINDLEY_X_LIMIT * 1e4 / abs(mu[1] - mu_bar)
    assert high["limited_by_table"] is True
    assert high["radius_limit_um"] == pytest.approx(expect, rel=1e-6)
    if high["equivalent_radius_um"] is not None:
        assert high["equivalent_radius_um"] <= expect + 1e-9


def test_no_table_limit_flag_for_small_contrast():
    """μ 反差小 ⇒ 表内上限远超默认搜索上界（50 µm），不该报"被表限住"。"""
    _p, _q, _s, table = _table([100.0, 120.0])
    assert table
    for item in table:
        assert item["limited_by_table"] is False
        assert item["radius_limit_um"] is None or item["radius_limit_um"] > 50.0


# ── 4. 不写回 wt%（诊断与结果的边界）────────────────────────────────
def test_diagnostics_never_write_back_fractions():
    """诊断只读：算完一轮，报告用的定量结果一位都不能变。"""
    mu = [100.0, 900.0]
    prob, quant, _s, table = _table(mu, radii=[0.0, 6.0])
    assert table
    before = tuple(quant.fractions)

    # 再跑一次，并把表里的 delta 加起来 —— 界面拿到的 wt% 仍是"当前半径"的解，
    # 不是"等效半径"的解（后者只用于显示，绝不参与结果）。
    _radius_sweep_table(prob, prob.quantitative(), mu, [0.0, 6.0])
    after = tuple(prob.quantitative().fractions)
    assert after == before
    drift = sum(abs(item["delta_wt_pp"]) for item in table)
    assert drift > 0.0            # 诊断确实算出了位移
    assert 100.0 * sum(after) == pytest.approx(100.0, abs=1e-6)   # 仍归一


# ── 5. 退化输入 ─────────────────────────────────────────────────────
def test_equal_mu_yields_no_rows():
    """μ 全相同 ⇒ τ≡1，没有任何可搬动的东西，不刷屏。"""
    _p, _q, _s, table = _table([300.0, 300.0])
    assert table == []


def test_single_phase_and_bad_mu_length_return_empty():
    prob, _structs = _problem(1, mu=[100.0])
    quant = prob.quantitative()
    assert _radius_sweep_table(prob, quant, [100.0], [0.0]) == []
    prob2, _s2 = _problem(2, mu=[100.0, 900.0])
    assert _radius_sweep_table(prob2, prob2.quantitative(), [100.0],
                               [0.0, 0.0]) == []
