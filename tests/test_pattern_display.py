"""
M21 PatternDisplayWidget 双区谱图控件测试 (offscreen Qt)
=======================================================
验证: 主区实验/计算/残差, 棒区逐相参考棒, 归属标记, 清除行为。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from polyxrd.models.xrd_data import XRDData
from polyxrd.models.peak import Peak
from polyxrd.services.phase_display import (COLOR_CALC, COLOR_EXP,
                                            COLOR_RESIDUAL, COLOR_UNMATCHED,
                                            PeakAssignment, phase_color)
from polyxrd.views.widgets.pattern_display import PatternDisplayWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _xrd():
    x = np.arange(20, 80, 0.2)
    y = np.zeros_like(x)
    for c in (30.0, 42.0, 56.0):
        y += 1000 * np.exp(-0.5 * ((x - c) / 0.15) ** 2)
    return XRDData(two_theta=x, intensity=y)


def _sticks(n=2):
    """[(name, refs, color), ...]"""
    sticks = []
    for i in range(n):
        color = phase_color(i)
        sticks.append((f"Phase{i}", [((1, 0, 0), 30 + i * 10, 100.0),
                                     ((2, 0, 0), 40 + i * 10, 60.0)], color))
    return sticks


class TestExperiment:
    def test_single_black_line(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_experiment(_xrd())
        ax = pd.get_axes()
        # 主区应含实验谱线 (黑)
        exp_lines = [l for l in ax.lines if l.get_gid() == "exp"]
        assert len(exp_lines) == 1
        assert exp_lines[0].get_color() == COLOR_EXP

    def test_empty_experiment_no_crash(self, qapp):
        # XRDData 强制 ≥3 点; "无数据"由调用方传空标量处理, 此处仅验证非空小数据
        pd = PatternDisplayWidget()
        x = np.arange(20, 22, 0.5)   # 4 点
        pd.set_experiment(XRDData(two_theta=x, intensity=np.ones_like(x)))
        assert pd._main_x.size == 4

    def test_experiment_replace_clears_old(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_experiment(_xrd())
        pd.set_experiment(_xrd())
        exp_lines = [l for l in pd.get_axes().lines if l.get_gid() == "exp"]
        assert len(exp_lines) == 1   # 旧实验线已被清


class TestCalculatedResidual:
    def test_calculated_line(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_experiment(_xrd())
        x = _xrd().two_theta
        pd.set_calculated(x, x * 0 + 100.0)
        calc = [l for l in pd.get_axes().lines if l.get_gid() == "calc"]
        assert len(calc) == 1 and calc[0].get_color() == COLOR_CALC

    def test_calculated_none_removes(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_experiment(_xrd())
        pd.set_calculated(_xrd().two_theta, np.ones_like(_xrd().two_theta))
        pd.set_calculated(None, None)
        assert not [l for l in pd.get_axes().lines if l.get_gid() == "calc"]

    def test_residual_line(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_experiment(_xrd())
        x = _xrd().two_theta
        pd.set_residual_curve(x, np.zeros_like(x))
        resid = [l for l in pd.get_axes().lines if l.get_gid() == "resid"]
        assert len(resid) >= 1   # 曲线 + 零基线
        assert all(l.get_color() == COLOR_RESIDUAL for l in resid)


class TestSticks:
    def test_two_phases_two_stick_groups(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_selected_phases(_sticks(2))
        # 每相 2 条棒 → 4 条 stick 线
        stick_lines = [l for l in pd._ax_stick.lines if l.get_gid() == "stick"]
        assert len(stick_lines) == 4

    def test_stick_rows_have_different_baseline(self, qapp):
        pd = PatternDisplayWidget()
        # 用非重叠峰: 相0 在 30/40, 相1 在 60/70 (避免 x 重影混淆行归属)
        pd.set_selected_phases([
            ("Phase0", [((1, 0, 0), 30.0, 100.0), ((2, 0, 0), 40.0, 60.0)],
             phase_color(0)),
            ("Phase1", [((1, 0, 0), 60.0, 100.0), ((2, 0, 0), 70.0, 60.0)],
             phase_color(1)),
        ])
        lines = [l for l in pd._ax_stick.lines if l.get_gid() == "stick"]
        ydata = {}
        for l in lines:
            xd = round(float(l.get_xdata()[0]), 1)
            ydata.setdefault(xd, []).append(l.get_ydata())
        ys30 = ydata[30.0][0]   # 相0 行: 基线 0 → 顶 0.85
        ys60 = ydata[60.0][0]   # 相1 行: 基线 -1 → 顶 -0.15
        assert ys30[0] == 0.0 and ys60[0] == -1.0     # 不同基线
        assert abs(ys30[1] - ys60[1]) > 0.5

    def test_stick_name_labels(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_selected_phases(_sticks(2))
        texts = [t.get_text() for t in pd._ax_stick.texts]
        assert "Phase0" in texts and "Phase1" in texts

    def test_clear_sticks(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_selected_phases(_sticks(2))
        pd.set_selected_phases([])
        assert not [l for l in pd._ax_stick.lines if l.get_gid() == "stick"]


class TestAssignments:
    def _assigns(self):
        return [
            PeakAssignment(30.0, 1000.0, 3.13, 0, "Phase0", 30.0, 0.0),
            PeakAssignment(42.0, 600.0, 2.15, 1, "Phase1", 42.0, 0.0),
            PeakAssignment(68.0, 200.0, 1.37, None, "", None, None),
        ]

    def test_markers_match_count(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_experiment(_xrd())
        pd.set_peak_assignments(self._assigns())
        # 2 相色圆点 + 1 红▼
        o_marks = [m for m in pd._ax_main.lines if m.get_gid() == "assign"
                   and m.get_marker() == "o"]
        v_marks = [m for m in pd._ax_main.lines if m.get_gid() == "assign"
                   and m.get_marker() == "v"]
        assert len(o_marks) == 2
        assert len(v_marks) == 1
        assert v_marks[0].get_color() == COLOR_UNMATCHED


class TestClearAll:
    def test_clear_all_empty(self, qapp):
        pd = PatternDisplayWidget()
        pd.set_experiment(_xrd())
        pd.set_selected_phases(_sticks(2))
        pd.set_calculated(_xrd().two_theta, np.ones_like(_xrd().two_theta))
        pd.clear_all()
        assert not pd._artists
        assert not pd.get_axes().lines
        assert not pd._ax_stick.lines
