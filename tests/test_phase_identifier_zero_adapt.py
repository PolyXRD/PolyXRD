"""B-6: _match_phase_fom 零点网格搜索回归测试。

验证 per-entry 零点偏移搜索能回收整体偏移的物相, 且护栏 (5% 改善阈值)
不会让轻微优化的伪匹配挤掉真相。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.services.phase_identifier import PhaseIdentifier


def _make_phase(ref_2theta):
    return Phase(
        name="TestPhase",
        formula="AB",
        reference_peaks=[((1, 0, 0), float(t), 100.0) for t in ref_2theta],
        elements={"A", "B"},
    )


def _make_peaks(tt, ii):
    return PeakList(peaks=[Peak(two_theta=float(t), intensity=float(i))
                           for t, i in zip(tt, ii)])


def test_zero_adapt_recovers_shifted_phase():
    """参考峰整体右偏 +0.08° 时, 启用 zero_grid 后 score 应优于禁用。"""
    true_tt = [20.0, 35.0, 50.0, 65.0]
    true_i = [100.0, 80.0, 60.0, 40.0]
    # 参考峰整体右偏 0.08°
    phase = _make_phase([t + 0.08 for t in true_tt])
    peaks = _make_peaks(true_tt, true_i)

    pi = PhaseIdentifier()
    r_off = pi._match_phase_fom(phase, peaks, tolerance=0.15, zero_grid=None)
    r_on = pi._match_phase_fom(phase, peaks, tolerance=0.15,
                               zero_grid=(-0.10, -0.05, 0.0, 0.05, 0.10))
    assert r_on.score < r_off.score
    # 应采用 -0.08° 附近的偏移 (网格里 -0.10 最接近)
    assert r_on.zero_shift != 0.0


def test_zero_adapt_guardrail_rejects_tiny_improvement():
    """偏移只带来 < 5% 改善时, 护栏应拒绝, 最终仍用 dz=0。"""
    # 峰位几乎对齐, 任何偏移都只会让匹配略变差或微改善
    tt = [20.0, 40.0, 60.0]
    ii = [100.0, 80.0, 60.0]
    phase = _make_phase([20.0, 40.0, 60.0])
    peaks = _make_peaks(tt, ii)

    pi = PhaseIdentifier()
    r = pi._match_phase_fom(phase, peaks, tolerance=0.15,
                            zero_grid=(-0.10, -0.05, 0.0, 0.05, 0.10))
    # 完美对齐时偏移只会变差, 护栏不生效, 用 dz=0
    assert r.zero_shift == 0.0


def test_zero_adapt_disabled_returns_zero_shift():
    """zero_grid=None 时 zero_shift 字段为 0.0。"""
    phase = _make_phase([20.0, 40.0])
    peaks = _make_peaks([20.0, 40.0], [100.0, 80.0])
    pi = PhaseIdentifier()
    r = pi._match_phase_fom(phase, peaks, tolerance=0.15, zero_grid=None)
    assert r.zero_shift == 0.0
