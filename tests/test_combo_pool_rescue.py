"""v2.6 E2: 池保底回收回归测试。

验证: matched_peaks >= _COMBO_KEEP_MATCHED 的候选即使 FoM 排名在 pool_top_n
之外, 也会被回收到 B&B 池 (不被裁剪丢弃)。通过 log_cb 捕获回收日志验证。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.peak import Peak
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.services.phase_identifier import (
    PhaseIdentifier,
    _COMBO_KEEP_MATCHED,
)


def _phase(name, tt):
    return Phase(
        name=name, formula="AB",
        reference_peaks=[((1, 0, 0), float(tt), 100.0)],
        elements={"A", "B"},
    )


def _match(phase, score, matched):
    return PhaseMatchResult(
        phase=phase, score=score, matched_peaks=matched,
        total_peaks=max(matched, 1),
    )


def test_pool_rescues_high_matched_phase():
    """pool_top_n=3 时, 排第 4 但 matched>=2 的相应被保底回收。"""
    pi = PhaseIdentifier()
    # 5 个相各匹配一个不同的观测峰 (避免被同成分去重合并)
    phases = [_phase(f"P{i}", 20.0 + i * 5.0) for i in range(5)]
    matches = [
        _match(phases[0], 0.1, 1),
        _match(phases[1], 0.2, 1),
        _match(phases[2], 0.3, 1),
        _match(phases[3], 0.4, 5),   # 排第 4, matched=5 >= 2 → 应回收
        _match(phases[4], 0.5, 1),
    ]
    peaks = [Peak(two_theta=20.0 + i * 5.0, intensity=100.0, d_spacing=1.0)
             for i in range(5)]
    logs: list[str] = []
    pi.build_refinement_combination(
        matches, expected_count=2, peaks=peaks, tolerance=0.5,
        pool_top_n=3, log_cb=logs.append,
    )
    rescued = [l for l in logs if "池保底回收" in l]
    assert rescued, "应出现池保底回收日志"
    assert "P3" in rescued[0]


def test_pool_does_not_rescue_low_matched_phase():
    """matched < _COMBO_KEEP_MATCHED 的排外相不应被回收。"""
    pi = PhaseIdentifier()
    phases = [_phase(f"P{i}", 20.0 + i * 5.0) for i in range(5)]
    matches = [_match(phases[i], 0.1 * (i + 1), 1) for i in range(5)]
    peaks = [Peak(two_theta=20.0 + i * 5.0, intensity=100.0, d_spacing=1.0)
             for i in range(5)]
    logs: list[str] = []
    pi.build_refinement_combination(
        matches, expected_count=2, peaks=peaks, tolerance=0.5,
        pool_top_n=3, log_cb=logs.append,
    )
    rescued = [l for l in logs if "池保底回收" in l]
    assert not rescued, "matched=1 的相不应被保底回收"
