"""D2: phase_vm.search_residual_peaks 残差峰提取逻辑测试。

验证:
  - 无选中相 → 不触发检索 (emit error);
  - 选中相解释了所有峰 → 不触发检索 (emit info);
  - 选中相只解释部分峰 → 仅用未解释峰调用 identify_phases(marked_peaks=...)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.phase import Phase
from polyxrd.models.peak import Peak, PeakList
from polyxrd.viewmodels.phase_vm import PhaseViewModel


def _phase(name, tt):
    return Phase(
        name=name, formula="SiO2",
        reference_peaks=[((1, 0, 0), float(tt), 100.0)],
        elements={"Si", "O"},
    )


def _peaks(tts):
    return PeakList(peaks=[Peak(two_theta=float(t), intensity=100.0,
                                d_spacing=1.0) for t in tts], source="test")


def test_residual_no_selected_phase_emits_error():
    vm = PhaseViewModel()
    vm._peaks = _peaks([30.0, 60.0])
    vm._selected_phases = []
    vm.error = MagicMock()
    vm.info = MagicMock()
    vm.identify_phases = MagicMock()
    vm.search_residual_peaks(data=MagicMock())
    vm.error.emit.assert_called_once()
    vm.identify_phases.assert_not_called()


def test_residual_all_explained_emits_info():
    vm = PhaseViewModel()
    vm._peaks = _peaks([30.0])
    vm._selected_phases = [_phase("Q", 30.0)]
    vm.error = MagicMock()
    vm.info = MagicMock()
    vm.identify_phases = MagicMock()
    vm.search_residual_peaks(data=MagicMock())
    vm.info.emit.assert_called_once()
    vm.identify_phases.assert_not_called()


def test_residual_only_unexplained_passed():
    vm = PhaseViewModel()
    # 实测峰: 30° (被 Quartz 解释) + 60° (残差)
    vm._peaks = _peaks([30.0, 60.0])
    vm._selected_phases = [_phase("Quartz", 30.0)]
    vm.error = MagicMock()
    vm.info = MagicMock()
    vm.identify_phases = MagicMock()
    vm.search_residual_peaks(data=MagicMock(), tolerance=0.30)
    vm.identify_phases.assert_called_once()
    kwargs = vm.identify_phases.call_args.kwargs
    assert kwargs["marked_peaks"] == pytest.approx([60.0], abs=0.01)
