"""B-6: compute_fom zero_shift 参数回归测试。

zero_shift 对参考峰 2θ 做整体偏移, 用于 per-entry 零点校正
(仿 Match! Automatic zero point adaptation)。
默认 0.0 = 与历史行为完全一致; 非零时应能改善错位峰表的 FoM。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.services.foam import compute_fom


def _refs(peaks):
    return [((0, 0, 0), float(tt), float(ii)) for tt, ii in peaks]


def test_zero_shift_default_unchanged():
    """zero_shift=0.0 与不传该参数 → 分数完全一致。"""
    obs_tt = [10.0, 20.0, 30.0, 40.0]
    obs_i = [100.0, 80.0, 60.0, 40.0]
    refs = _refs([(10.0, 100.0), (20.0, 80.0), (30.0, 60.0)])
    a = compute_fom(obs_tt, obs_i, refs, tol=0.15)
    b = compute_fom(obs_tt, obs_i, refs, tol=0.15, zero_shift=0.0)
    assert a.score == pytest.approx(b.score)
    assert a.matched == b.matched
    assert a.missed == b.missed


def test_zero_shift_improves_misaligned():
    """参考峰整体右偏 +0.08° 时, 用 zero_shift=-0.08 补偿后 FoM 应变好。"""
    true_tt = [20.0, 35.0, 50.0, 65.0]
    true_i = [100.0, 80.0, 60.0, 40.0]
    # 参考峰整体右偏 0.08°
    shifted_refs = _refs([(t + 0.08, i) for t, i in zip(true_tt, true_i)])
    fom_no_shift = compute_fom(true_tt, true_i, shifted_refs, tol=0.15)
    fom_compensated = compute_fom(true_tt, true_i, shifted_refs, tol=0.15,
                                  zero_shift=-0.08)
    # 补偿后匹配偏差趋近 0, 分数应显著降低
    assert fom_compensated.score < fom_no_shift.score
    # 补偿后应匹配全部 4 条峰
    assert fom_compensated.matched == 4
    assert fom_compensated.missed == 0


def test_zero_shift_wrong_direction_worsens():
    """偏移方向错误时 FoM 应变差 (验证参数确实生效)。"""
    true_tt = [20.0, 35.0, 50.0]
    true_i = [100.0, 80.0, 60.0]
    refs = _refs([(t, i) for t, i in zip(true_tt, true_i)])
    fom_base = compute_fom(true_tt, true_i, refs, tol=0.15)
    fom_wrong = compute_fom(true_tt, true_i, refs, tol=0.15, zero_shift=0.20)
    assert fom_wrong.score > fom_base.score


def test_zero_shift_does_not_break_observability():
    """zero_shift 与 obs_range 同时使用时, 可观测性基于偏移后峰位判断。"""
    obs_tt = [20.0, 30.0]
    obs_i = [100.0, 50.0]
    # 一条峰在范围内, 一条偏移后超出范围
    refs = _refs([(20.0, 100.0), (80.0, 50.0)])
    fom = compute_fom(obs_tt, obs_i, refs, tol=0.15,
                      obs_range=(10.0, 70.0), zero_shift=0.0)
    # 80° 的峰在 [10,70] 外, 不计漏检
    assert fom.missed == 0
