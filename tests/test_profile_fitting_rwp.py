"""C1: profile_fitting_score baseline_rwp / delta_rwp 回归测试。

delta_rwp = baseline_rwp - rwp, 即加入该相后的 Rwp 降幅 (Match! 口径)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.phase import Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.foam import profile_fitting_score


def _make_xrd(tt, ii):
    return XRDData(two_theta=np.asarray(tt, dtype=float),
                   intensity=np.asarray(ii, dtype=float))


def _make_phase(ref_2theta, ref_intensity=None):
    if ref_intensity is None:
        ref_intensity = [100.0] * len(ref_2theta)
    return Phase(
        name="TestPhase",
        formula="AB",
        reference_peaks=[((1, 0, 0), float(t), float(i))
                         for t, i in zip(ref_2theta, ref_intensity)],
        elements={"A", "B"},
    )


def test_delta_rwp_positive_for_good_fit():
    """能解释实测峰的相, delta_rwp 应 > 0。"""
    grid = np.linspace(10.0, 80.0, 351)
    # 实测谱: 在 20° 和 40° 有峰
    obs = (1000.0 * np.exp(-0.5 * ((grid - 20.0) / 0.3) ** 2)
           + 800.0 * np.exp(-0.5 * ((grid - 40.0) / 0.3) ** 2))
    xrd = _make_xrd(grid, obs)
    phase = _make_phase([20.0, 40.0], [100.0, 80.0])
    r = profile_fitting_score(xrd, phase, baseline_rwp=100.0)
    assert "delta_rwp" in r
    assert r["delta_rwp"] > 0.0
    assert r["rwp"] < 100.0


def test_delta_rwp_near_zero_for_noise_phase():
    """与实测谱无关的相, delta_rwp 应 ≈ 0 (几乎不降低 Rwp)。"""
    grid = np.linspace(10.0, 80.0, 351)
    obs = 1000.0 * np.exp(-0.5 * ((grid - 20.0) / 0.3) ** 2)
    xrd = _make_xrd(grid, obs)
    # 参考峰在完全不同的位置
    phase = _make_phase([60.0, 70.0], [100.0, 80.0])
    r = profile_fitting_score(xrd, phase, baseline_rwp=100.0)
    # 无关相对 Rwp 降幅极小
    assert r["delta_rwp"] < 5.0


def test_no_baseline_rwp_omits_delta_rwp():
    """不传 baseline_rwp 时, 返回 dict 不含 delta_rwp (向后兼容)。"""
    grid = np.linspace(10.0, 80.0, 351)
    obs = np.exp(-0.5 * ((grid - 20.0) / 0.3) ** 2)
    xrd = _make_xrd(grid, obs)
    phase = _make_phase([20.0])
    r = profile_fitting_score(xrd, phase)
    assert "delta_rwp" not in r
    assert "corr" in r and "scale" in r and "rwp" in r
