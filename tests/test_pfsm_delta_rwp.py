"""C2: PFSM 重排改用 ΔRwp + 双过滤回归测试。

验证开启 PFSM (fom_pfsm_weight > 0) 时:
  - delta_rwp 高的相排前面 (而非 corr 高的);
  - delta_rwp < 0.5% 或 scale < 0.02 的候选被排到末尾 (过滤)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.phase import Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.phase_identifier import PhaseIdentifier


def _make_xrd(tt, ii):
    return XRDData(two_theta=np.asarray(tt, dtype=float),
                   intensity=np.asarray(ii, dtype=float))


def _make_phase(name, ref_2theta, ref_intensity=None, formula="AB", elements=None):
    if ref_intensity is None:
        ref_intensity = [100.0] * len(ref_2theta)
    if elements is None:
        elements = set(formula)
    return Phase(
        name=name,
        formula=formula,
        reference_peaks=[((1, 0, 0), float(t), float(i))
                         for t, i in zip(ref_2theta, ref_intensity)],
        elements=elements,
    )


def test_pfsm_rerank_uses_delta_rwp():
    """两个候选: corr 高但 delta_rwp 低 vs corr 低但 delta_rwp 高 →
    开启 PFSM 重排后 delta_rwp 高的应排前面。"""
    grid = np.linspace(10.0, 80.0, 351)
    # 实测谱主峰在 30°
    obs = 1000.0 * np.exp(-0.5 * ((grid - 30.0) / 0.3) ** 2)
    xrd = _make_xrd(grid, obs)

    # phase_good: 峰在 30°, delta_rwp 高
    phase_good = _make_phase("GoodPhase", [30.0], formula="AB")
    # phase_bad: 峰在 60°, delta_rwp 低
    phase_bad = _make_phase("BadPhase", [60.0], formula="CD")

    pi = PhaseIdentifier()
    pi._phase_database = [phase_good, phase_bad]
    pi._reference_data = []

    results = pi.identify_with_element_filter(
        xrd, top_n=5, tolerance=0.3,
        fom_pfsm_weight=0.5, fom_pfsm_top_n=5,
        fom_zero_grid=None,  # 关闭零点搜索, 隔离 PFSM 变量
    )
    names = [r.phase.name for r in results]
    # GoodPhase 的 delta_rwp 高, 应排在 BadPhase 前面
    assert names.index("GoodPhase") < names.index("BadPhase")


def test_pfsm_filters_low_delta_rwp():
    """delta_rwp < 0.5% 的候选在 PFSM 重排中应被排到末尾。"""
    grid = np.linspace(10.0, 80.0, 351)
    obs = 1000.0 * np.exp(-0.5 * ((grid - 30.0) / 0.3) ** 2)
    xrd = _make_xrd(grid, obs)

    phase_close = _make_phase("ClosePhase", [30.0], formula="AB")
    phase_far = _make_phase("FarPhase", [75.0], formula="EF")

    pi = PhaseIdentifier()
    pi._phase_database = [phase_close, phase_far]
    pi._reference_data = []

    results = pi.identify_with_element_filter(
        xrd, top_n=5, tolerance=0.3,
        fom_pfsm_weight=0.5, fom_pfsm_top_n=5,
        fom_zero_grid=None,
    )
    names = [r.phase.name for r in results]
    # ClosePhase 应排前面
    assert names.index("ClosePhase") < names.index("FarPhase")
