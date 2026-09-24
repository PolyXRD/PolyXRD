"""M21 Request1: 数据文件菜单 — 开新自动清 + 显式清除数据 (VM 层 offscreen)。"""
import os
import tempfile

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.services.peak_finder import PeakFinder


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _write_synth(path: str, base: float) -> None:
    """写一个已知单峰 (base°) 谱到 .xy。"""
    x = np.arange(15.0, 60.0, 0.02)
    y = 20.0 + 1000.0 * np.exp(-((x - base) / 0.08) ** 2)
    with open(path, "w") as f:
        for a, b in zip(x, y):
            f.write(f"{a:.4f} {b:.3f}\n")


@pytest.fixture
def two_files(tmp_path):
    p1 = os.path.join(tmp_path, "a.xy")
    p2 = os.path.join(tmp_path, "b.xy")
    _write_synth(p1, 30.0)
    _write_synth(p2, 45.0)
    return p1, p2


def _load_and_detect(vm, path, qapp):
    vm.load_file(path)
    for _ in range(5):
        qapp.processEvents()
    pf = PeakFinder()
    vm._phase_vm._peaks = pf.find_peaks(vm.current_data, height=0.02, distance=3.0)
    vm._phase_vm._matched_phases = ["dummy_result"]
    # 模拟选中一相 + 精修
    vm._phase_vm._selected_phases = ["dummy_phase"]
    vm._refinement_vm._result = object()


class TestClearData:
    def test_load_sets_state(self, qapp, two_files):
        vm = MainViewModel()
        p1, _ = two_files
        _load_and_detect(vm, p1, qapp)
        assert vm.current_data is not None
        assert vm._phase_vm.peaks is not None
        assert vm._phase_vm.selected_phases
        assert vm._refinement_vm.result is not None

    def test_clear_all_data_resets_everything(self, qapp, two_files):
        vm = MainViewModel()
        p1, _ = two_files
        _load_and_detect(vm, p1, qapp)
        vm.clear_all_data()
        for _ in range(5):
            qapp.processEvents()
        assert vm.current_data is None
        assert vm._data_vm.file_path is None
        assert vm._phase_vm.peaks is None
        assert vm._phase_vm.fitted_peaks is None
        assert vm._phase_vm.matched_phases == []
        assert vm._phase_vm.selected_phases == []
        assert vm._refinement_vm.result is None
        assert vm._refinement_vm._selected_phases == []

    def test_open_second_file_auto_resets_old_analysis(self, qapp, two_files):
        """打开新文件应自动清掉旧文件的峰/物相/精修残留。"""
        vm = MainViewModel()
        p1, p2 = two_files
        _load_and_detect(vm, p1, qapp)
        assert vm._phase_vm.selected_phases  # 旧文件有分析
        # 打开第二个文件 (不同路径) → 应重置旧分析
        vm.load_file(p2)
        for _ in range(5):
            qapp.processEvents()
        assert vm.current_data is not None
        assert vm._phase_vm.peaks is None  # 旧峰已被清
        assert vm._phase_vm.matched_phases == []
        assert vm._phase_vm.selected_phases == []
        assert vm._refinement_vm.result is None
