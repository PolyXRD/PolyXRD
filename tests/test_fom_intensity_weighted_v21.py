"""v2.1 P1-3: FoM 特异性项强度加权回归测试。

背景 (docs/代码评估与改进计划.md §五 P1-3): 峰检测默认无幅度下限 →
噪声峰 (数多、强度低) 把计数口径的未解释比推到 ~0.88, 特异性惩罚项
(权重 0.30) 被打满, FoM 区分力丧失 (ZnO score 0.132 → 0.312, 与次名
分差 5.9× 压缩到 2.2×)。修法 = 强度加权, 而非加峰高下限 (对照实验证明
后者会把微量相 Rutile 从第 2 名挤到第 3 名 —— 真实弱峰被一并删除)。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.services.foam import compute_fom, search_match
from polyxrd.models.phase import Phase
from polyxrd.models.search_options import SearchOptions

RNG = np.random.default_rng(20260924)


def _noisy_obs():
    """构造 P1-3 报告的典型场景: 10 条真峰 (强度 100~1000) + 90 条噪声峰 (强度 ≤ 45)。"""
    true_tt = np.linspace(20.0, 70.0, 10)
    true_i = np.linspace(1000.0, 200.0, 10)
    noise_tt = np.sort(RNG.uniform(15.0, 80.0, 90))
    # 保证噪声峰不与真峰重叠 (错开 0.3°)
    for t in true_tt:
        noise_tt = noise_tt[(np.abs(noise_tt - t) > 0.3)]
    noise_i = RNG.uniform(5.0, 45.0, noise_tt.size)
    tt = np.concatenate([true_tt, noise_tt])
    ii = np.concatenate([true_i, noise_i])
    order = np.argsort(tt)
    return tt[order], ii[order]


def _true_refs():
    true_tt = np.linspace(20.0, 70.0, 10)
    true_i = np.linspace(1000.0, 200.0, 10)
    return [((0, 0, 0), float(t), float(i)) for t, i in zip(true_tt, true_i)]


def test_noise_peaks_do_not_saturate_specificity():
    """90 条噪声峰不得把特异性惩罚推到 > 0.5 (强度加权后应 < 0.15)。"""
    tt, ii = _noisy_obs()
    fom = compute_fom(tt, ii, _true_refs(), tol=0.15)
    # 全部真峰都被解释 (matched=10, 漏检 0) → 位置项≈0; 特异性只来自噪声峰
    assert fom.matched == 10
    assert fom.missed == 0
    assert fom.unexplained_obs == fom.total_obs - 10
    # 强度加权: 噪声峰总强度占比 ~5%, 特异性贡献 0.30 × 0.05 ≪ 0.5
    assert fom.score < 0.5
    assert fom.score < 0.15


def test_strong_unexplained_peak_still_penalized():
    """强度加权不能放过"真强峰解释不了"的情形: 一条强度 1000 的未解释峰 ≈ 1/2 总强度。"""
    true_tt = np.linspace(20.0, 60.0, 5)
    refs = [((0, 0, 0), float(t), 500.0) for t in true_tt]
    obs_tt = np.concatenate([true_tt, [75.0]])
    obs_i = np.concatenate([np.full(5, 500.0), [1000.0]])
    fom = compute_fom(obs_tt, obs_i, refs, tol=0.15)
    # 未解释强度 1000 / 总 3500 ≈ 0.286 → 特异性贡献 ≈ 0.086, 明显非零
    assert fom.unexplained_obs == 1
    assert fom.score > 0.05


def test_trace_phase_recall_not_degraded():
    """微量相 (5% 强度) 在含噪峰表下仍应 Top-2 —— 不复现"加硬下限挤掉 Rutile"的退化。"""
    major = Phase(name="Major", formula="MX")
    major.reference_peaks = [((0, 0, 0), float(t), float(i))
                             for t, i in zip(np.linspace(20.0, 70.0, 10),
                                             np.linspace(1000.0, 200.0, 10))]
    major.elements = {"M", "X"}

    trace = Phase(name="Trace", formula="AB2")   # 模拟 Rutile 式微量相
    trace.reference_peaks = [((0, 0, 0), float(t), float(i))
                             for t, i in zip(np.linspace(25.0, 65.0, 6),
                                             np.linspace(50.0, 10.0, 6))]
    trace.elements = {"A", "B"}

    other = Phase(name="Other", formula="YZ")
    other.reference_peaks = [((0, 0, 0), float(t), float(i))
                             for t, i in zip(np.linspace(21.0, 71.0, 9),
                                             np.linspace(400.0, 100.0, 9))]
    other.elements = {"Y", "Z"}

    # 实验峰 = 主相 + 微量相真峰 + 噪声峰 (微量相峰强度 10~50, 混在噪声里)
    obs_tt = np.concatenate([
        [p[1] for p in major.reference_peaks],
        [p[1] for p in trace.reference_peaks],
        np.sort(RNG.uniform(15.0, 80.0, 80)),
    ])
    obs_i = np.concatenate([
        [p[2] for p in major.reference_peaks],
        [p[2] for p in trace.reference_peaks],
        RNG.uniform(5.0, 45.0, 80),
    ])
    order = np.argsort(obs_tt)
    results = search_match(obs_tt[order], obs_i[order], [major, trace, other],
                           options=SearchOptions(max_entries=3, check_three_strongest=False))
    names = [r.phase.name for r in results]
    assert "Trace" in names[:2], f"微量相被挤出 Top-2: {names}"
    assert names[0] == "Major"
    # 主相与次名的分差不应被噪声压缩到"几乎并列"
    if len(results) >= 2:
        assert results[1].score - results[0].score > 0.02
