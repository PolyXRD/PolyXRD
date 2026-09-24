"""M21 S5: PhaseView v2 多相勾选叠加集成测试 (offscreen)。

验证: 载入数据 → 寻峰 → 识别 → 候选可勾选 → 勾选驱动
PatternDisplayWidget(实验/参考棒/计算谱/归属) + PeakMatchTable 刷新。
"""
import os
import tempfile

import numpy as np
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.phase_view import PhaseView
from polyxrd.services.peak_finder import PeakFinder


def _write_synth_quartz(path: str) -> None:
    """合成类石英谱 (主峰 ~26.6°) 到 .xy 文件。"""
    x = np.arange(15.0, 60.0, 0.02)
    y = np.zeros_like(x)
    for c, I in [(26.6, 1000), (20.9, 200), (36.5, 120), (39.5, 80),
                 (40.3, 50), (42.5, 60), (45.8, 70), (50.2, 100), (54.9, 60)]:
        y += I * np.exp(-((x - c) / 0.08) ** 2)
    y += 8.0
    with open(path, "w") as f:
        for a, b in zip(x, y):
            f.write(f"{a:.4f} {b:.3f}\n")


def _drive_identify(pv: PhaseView, vm: MainViewModel) -> None:
    """寻峰 + 识别 → 候选列表填充 (真实按钮路径的 service 层)。"""
    app = QApplication.instance()
    data = vm.current_data
    pf = PeakFinder()
    vm._phase_vm._peaks = pf.find_peaks(data, height=0.02, distance=3.0)
    vm.identify_phases(elements=None, top_n=8, db_source="builtin")
    for _ in range(10):
        app.processEvents()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def setup(qapp: QApplication):
    vm = MainViewModel()
    pv = PhaseView(vm)
    path = os.path.join(tempfile.gettempdir(), "polyxrd_qt_synth.xy")
    _write_synth_quartz(path)
    vm.load_file(path)
    for _ in range(5):
        qapp.processEvents()
    _drive_identify(pv, vm)
    assert pv._candidate_list.count() > 0
    return pv, vm


class TestPhaseViewV2:
    def test_candidates_checkable(self, setup):
        pv, _vm = setup
        item = pv._candidate_list.item(0)
        assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
        assert item.checkState() == Qt.CheckState.Unchecked

    def test_check_selects_and_draws_overlay(self, setup):
        pv, vm = setup
        item = pv._candidate_list.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        for _ in range(5):
            QApplication.instance().processEvents()
        # VM 选中集合含该相
        assert len(vm._phase_vm.selected_phases) == 1
        # 实验谱已画
        assert pv._plot._main_x.size > 0
        # 参考棒区有棒
        n_stick = sum(1 for l in pv._plot._ax_stick.lines
                      if l.get_gid() == "stick")
        assert n_stick > 0
        # 峰归属表已填充
        rows = pv._match_table._table.rowCount()
        assert rows > 0

    def test_uncheck_removes_from_overlay(self, setup):
        pv, vm = setup
        item = pv._candidate_list.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        for _ in range(3):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 1
        item.setCheckState(Qt.CheckState.Unchecked)
        for _ in range(3):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 0

    def test_clear_selection_unchecks_all(self, setup):
        pv, vm = setup
        for idx in range(min(2, pv._candidate_list.count())):
            pv._candidate_list.item(idx).setCheckState(Qt.CheckState.Checked)
        for _ in range(5):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 2
        pv._on_clear_selection()
        for _ in range(3):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 0
        # 候选列表仍保留 (未清空)
        assert pv._candidate_list.count() > 0

    def test_toggle_calc_shows_hides_calc(self, setup):
        pv, _vm = setup
        pv._candidate_list.item(0).setCheckState(Qt.CheckState.Checked)
        for _ in range(5):
            QApplication.instance().processEvents()
        # 默认叠加计算谱开启 → calc 线存在
        n_calc_on = sum(1 for l in pv._plot._ax_main.lines
                        if l.get_gid() == "calc")
        assert n_calc_on == 1
        pv._btn_toggle_calc.setChecked(False)
        pv._refresh_overlay()
        for _ in range(3):
            QApplication.instance().processEvents()
        n_calc_off = sum(1 for l in pv._plot._ax_main.lines
                         if l.get_gid() == "calc")
        assert n_calc_off == 0
