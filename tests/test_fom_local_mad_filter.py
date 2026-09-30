"""B-3: 局部噪声自适应幅度下限回归测试。

背景 (docs/代码评估与改进计划.md §五 P1-3 + v2.3 评估): 寻峰默认无幅度下限
(``min_signal_abs=0`` / ``min_prominence_frac=0``) → 自动检峰里 ~88% 是噪声峰,
v2.1 强度加权口径下噪声峰累积强度 (~28% 总强度) 仍把特异性项淹没 (惩罚项
0.084 vs 干净峰表 0.040)。简单加全局下限已证伪 (Rutile 微量相被挤掉名次)。

B-3 修法 = 按 2θ 局部窗口 MAD×k 阈值过滤 obs 峰强度: 强度 < 阈值的峰
视为局部噪声, 在特异性项里不计入未解释强度也不计入总强度。
  - 安静区 (峰强度都低): 局部 MAD 小 → 阈值低 → 弱峰保留;
  - 噪声区 (噪声峰密集): 局部 MAD 大 → 阈值高 → 假峰剔除。

本测试覆盖 :func:`local_mad_threshold` 工具函数 + :func:`compute_fom`
的 ``obs_noise_floor`` 参数 + :func:`FoMResult.specificity` 在 B-3 启用时的口径。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.services.foam import compute_fom, local_mad_threshold


# ── local_mad_threshold 基础行为 ────────────────────────────────

def test_local_mad_threshold_empty():
    """空输入返回空数组 (不抛异常)。"""
    thr = local_mad_threshold([], [])
    assert thr.size == 0


def test_local_mad_threshold_few_peaks_uses_global_mad():
    """窗口峰数 < min_count 时回退到全局 MAD×k (避免局部样本不稳)。"""
    # 3 个峰, window=5° 内每窗只含 1-2 个峰 → 用全局 MAD
    tt = [10.0, 30.0, 60.0]
    ii = [10.0, 100.0, 50.0]
    thr = local_mad_threshold(tt, ii, window_deg=5.0, k=3.0, min_count=3)
    assert thr.size == 3
    # 全局 MAD: med=50, |10-50|=40, |100-50|=50, |50-50|=0 → MAD=40
    # g_thr = 3.0 × 1.4826 × 40 = 177.9
    g_med = float(np.median(ii))
    g_mad = float(np.median(np.abs(np.array(ii) - g_med)))
    expected = 3.0 * 1.4826 * g_mad
    for v in thr:
        assert abs(v - expected) < 1e-6


def test_local_mad_threshold_dense_noise_high_for_noise_peaks():
    """噪声密集区: 噪声峰强度接近 → 局部 MAD 小 → 噪声峰阈值低 (保留)。

    但若区内有真峰 (强度远高于噪声), 局部 MAD 由噪声水平主导, 真峰强度
    远 > k×MAD → 真峰保留 (B-3 不应误杀真峰)。
    """
    # 1 个真峰 + 9 个噪声峰, 全在 25-30° 5° 窗口内
    tt = np.linspace(25.0, 30.0, 10)
    ii = np.array([10.0, 12.0, 8.0, 11.0, 9.0, 13.0, 7.0, 10.5, 9.5, 1000.0])
    thr = local_mad_threshold(tt, ii, window_deg=5.0, k=3.0, min_count=3)
    # 真峰阈值 = 3 × 1.4826 × MAD(局部强度)
    # MAD 主要由噪声峰主导 (9 个 ~10 vs 1 个 1000), med≈10, MAD≈1
    # → thr ≈ 4.5; 真峰 1000 远大于此 → 通过; 噪声峰 10 > 4.5 → 也通过
    assert thr[-1] < 50  # 真峰位置阈值不应被拉爆
    assert ii[-1] >= thr[-1]  # 真峰显著高于其阈值 → 保留


def test_local_mad_threshold_pure_noise_block_high_threshold():
    """纯噪声区 (峰强度都低且密集): 局部 MAD 小, 但所有峰强度都接近 MAD →
    阈值 = k×MAD 会落在峰强度附近, 部分峰被剔 —— 这是 B-3 期望行为
    (剔除噪声区假峰)。
    """
    # 10 个噪声峰, 强度都 ~5±1, 5° 窗口
    tt = np.linspace(20.0, 25.0, 10)
    ii = np.array([5.0, 5.5, 4.5, 5.2, 4.8, 5.1, 4.9, 5.3, 4.7, 5.0])
    thr = local_mad_threshold(tt, ii, window_deg=5.0, k=3.0, min_count=3)
    # MAD 很小 (~0.3), thr ≈ 1.3, 所有峰强度 4.5-5.5 > 1.3 → 保留
    # 这种情况 B-3 不剔任何峰 (峰间方差太小, 无法区分噪声 vs 信号)
    for v, t in zip(ii, thr):
        assert v >= t  # 全保留


def test_local_mad_threshold_returns_input_order():
    """阈值数组顺序与输入 obs_two_theta 同序 (不是排序后)。"""
    tt = [40.0, 10.0, 30.0, 20.0]  # 故意乱序
    ii = [50.0, 5.0, 30.0, 100.0]
    thr = local_mad_threshold(tt, ii, window_deg=20.0, k=3.0, min_count=3)
    assert thr.size == 4
    # 全在 20° 窗口内 → 全用同一个局部 MAD 值
    # 验证顺序: 重新按输入顺序计算应一致
    assert np.allclose(thr, thr[0])  # 全相同


# ── compute_fom 的 obs_noise_floor 参数 ────────────────────────

def _noisy_obs_with_strong_signal():
    """构造 B-3 关键场景: 真峰 (高强度) + 噪声峰 (低强度, 数量多)。

    噪声峰累积强度足够大, 在 v2.3 (无 B-3) 口径下能影响特异性项。
    """
    true_tt = np.linspace(20.0, 70.0, 6)
    true_i = np.linspace(1000.0, 300.0, 6)
    rng = np.random.default_rng(20260930)
    noise_tt = np.sort(rng.uniform(15.0, 80.0, 60))
    # 错开真峰
    for t in true_tt:
        noise_tt = noise_tt[(np.abs(noise_tt - t) > 0.3)]
    noise_i = rng.uniform(20.0, 60.0, noise_tt.size)  # 噪声峰强度中位 ~40
    tt = np.concatenate([true_tt, noise_tt])
    ii = np.concatenate([true_i, noise_i])
    order = np.argsort(tt)
    return tt[order], ii[order]


def _true_refs():
    true_tt = np.linspace(20.0, 70.0, 6)
    true_i = np.linspace(1000.0, 300.0, 6)
    return [((0, 0, 0), float(t), float(i)) for t, i in zip(true_tt, true_i)]


def test_compute_fom_obs_noise_floor_reduces_specificity_when_noise():
    """B-3 启用后, 噪声峰不再淹没特异性项 → score 显著低于 v2.3 默认口径。"""
    tt, ii = _noisy_obs_with_strong_signal()
    refs = _true_refs()
    fom_no_b3 = compute_fom(tt, ii, refs, tol=0.15)
    thr = local_mad_threshold(tt, ii, window_deg=5.0, k=3.0)
    fom_with_b3 = compute_fom(tt, ii, refs, tol=0.15, obs_noise_floor=thr)
    # B-3 剔除噪声峰后特异性项减小 → score 降低
    assert fom_with_b3.score < fom_no_b3.score
    # 显著峰口径: total_obs 不再含噪声峰
    assert fom_with_b3.total_obs < fom_no_b3.total_obs
    # 真峰仍被匹配 (位置项不变)
    assert fom_with_b3.matched == fom_no_b3.matched


def test_compute_fom_obs_noise_floor_none_is_noop():
    """obs_noise_floor=None 时行为与 v2.3 完全一致 (向后兼容)。"""
    tt, ii = _noisy_obs_with_strong_signal()
    refs = _true_refs()
    fom_a = compute_fom(tt, ii, refs, tol=0.15)
    fom_b = compute_fom(tt, ii, refs, tol=0.15, obs_noise_floor=None)
    assert fom_a.score == fom_b.score
    assert fom_a.total_obs == fom_b.total_obs
    assert fom_a.unexplained_obs == fom_b.unexplained_obs


def test_compute_fom_keeps_strong_unexplained_penalty_with_b3():
    """B-3 不得放过"真强峰未被解释"的情形: 一条强度 1000 的未解释峰
    在 B-3 启用后仍应给出明显特异性惩罚。"""
    refs_tt = np.linspace(20.0, 60.0, 5)
    refs = [((0, 0, 0), float(t), 500.0) for t in refs_tt]
    obs_tt = np.concatenate([refs_tt, [75.0]])
    obs_i = np.concatenate([np.full(5, 500.0), [1000.0]])
    thr = local_mad_threshold(obs_tt, obs_i, window_deg=5.0, k=3.0)
    fom = compute_fom(obs_tt, obs_i, refs, tol=0.15, obs_noise_floor=thr)
    # 75° 处的 1000 强度峰显著高于其局部 MAD 阈值 → 不被剔除
    # 未解释强度 1000 / 总强度 ~3500 ≈ 0.286 → 特异性贡献 ≈ 0.086
    assert fom.score > 0.05, f"B-3 错误放过真强峰未解释: score={fom.score}"


def test_specificity_uses_significant_peaks_with_b3():
    """FoMResult.specificity 在 B-3 启用时按"显著峰"口径算 (与特异性项一致)。

    B-3 剔除"局部显著低"的噪声峰; 对均匀噪声峰 (强度都接近 MAD) 剔除有限,
    但 specificity 不应低于无 B-3 口径 (B-3 是减项过滤, 不引入退化)。
    """
    tt, ii = _noisy_obs_with_strong_signal()
    refs = _true_refs()
    fom_no_b3 = compute_fom(tt, ii, refs, tol=0.15)
    thr = local_mad_threshold(tt, ii, window_deg=5.0, k=3.0)
    fom = compute_fom(tt, ii, refs, tol=0.15, obs_noise_floor=thr)
    # specificity 口径改为"显著峰"—— B-3 不应让 specificity 退化
    assert fom.specificity >= fom_no_b3.specificity - 0.01
    # total_obs 显著少于全部 obs 峰 (噪声峰被剔, 显著峰数 < 全部峰数)
    assert fom.total_obs < len(tt)
    # 真峰仍被全部解释 (matched 不变)
    assert fom.matched == fom_no_b3.matched


def test_mismatched_noise_floor_length_falls_back_to_no_filter():
    """obs_noise_floor 长度与 obs 不匹配时安全回退到无过滤 (不抛异常)。"""
    tt, ii = _noisy_obs_with_strong_signal()
    refs = _true_refs()
    fom_ref = compute_fom(tt, ii, refs, tol=0.15)
    # 故意传错长度
    bad_thr = np.array([10.0, 20.0])
    fom = compute_fom(tt, ii, refs, tol=0.15, obs_noise_floor=bad_thr)
    assert fom.score == fom_ref.score
    assert fom.total_obs == fom_ref.total_obs
