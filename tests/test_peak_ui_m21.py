"""M21 Request2 UI 接线: 高精度寻峰通过 DataView 按钮驱动 + PeakTable/plot 不崩。"""
import os
import tempfile

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.data_view import DataView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def dv_vm(qapp):
    vm = MainViewModel()
    dv = DataView(vm)
    # 真实 ZnO 谱 (已知多峰/双峰) 写临时 .xy
    x = np.arange(15.0, 90.0, 0.02)
    y = np.zeros_like(x)
    # 若干峰 + Kα1/Kα2 双峰 + 一个弱峰
    for c, amp in [(31.77, 5000), (34.42, 2000), (36.25, 8000),
                   (36.55, 3500), (47.54, 4000), (56.60, 3000),
                   (56.90, 1200), (62.86, 2000), (63.20, 900),
                   (67.96, 3000), (69.10, 700)]:  # 末尾弱峰
        y += amp * np.exp(-((x - c) / 0.08) ** 2)
    y += 40.0
    path = os.path.join(tempfile.gettempdir(), "polyxrd_ui_peak.xy")
    with open(path, "w") as f:
        for a, b in zip(x, y):
            f.write(f"{a:.4f} {b:.3f}\n")
    vm.load_file(path)
    for _ in range(5):
        qapp.processEvents()
    return dv, vm


class TestDataViewAdvancedFindPeaks:
    def test_button_uses_advanced_engine(self, dv_vm):
        dv, vm = dv_vm
        assert dv._peak_hi.isChecked()  # 默认高精度开
        dv._btn_find_peaks.click()
        for _ in range(8):
            QApplication.instance().processEvents()
        assert vm.peaks is not None
        assert vm.peaks.source == "advanced"
        # 峰位亚步长 (非 0.02 网格): 36.25 峰应还原到 <0.01 内且非精确网格
        centers = [p.two_theta for p in vm.peaks.peaks]
        hit = [c for c in centers if abs(c - 36.25) < 0.01]
        assert hit
        # 弱峰 69.10 检出
        assert any(abs(c - 69.1) < 0.02 for c in centers)

    def test_table_and_plot_survive_peaklist(self, dv_vm):
        """峰表 + 绘图区在 PeakList 输入下不抛 (回归: .clear()/.copy 曾崩)。"""
        dv, vm = dv_vm
        dv._btn_find_peaks.click()
        for _ in range(8):
            QApplication.instance().processEvents()
        assert dv._peak_table._table.rowCount() > 0
        # 再触发一次清除 (plot.clear_plot 走 .clear, 曾因 PeakList 崩)
        vm.clear_all_data()
        for _ in range(5):
            QApplication.instance().processEvents()
        assert dv._peak_table._table.rowCount() == 0
