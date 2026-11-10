"""v5.4.0 谱图操作工具行（彩色图标 + 复位/框选/平移/步进缩放/十字线）。

覆盖:
- 9 个工具图标齐备且非空（纯 QPainter 绘制，零素材）
- 导航工具条换彩色图标（mpl-data SVG + QtSvg 着色）
- 工具行按钮数量/顺序与 TOOL_GROUPS 一致
- 模式工具单选互斥（sync）
- 十字线：定位/读数/清除
- 步进缩放 / 平移 / 复位
- 框选缩放 zoom_x / zoom_y / zoom_rect
- 未知工具名被拒绝
- 三语工具提示键齐备
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.models.xrd_data import XRDData
from polyxrd.views.widgets import plot_icons
from polyxrd.views.widgets.plot_toolbar import MODE_TOOLS, TOOL_GROUPS, PlotToolBar
from polyxrd.views.widgets.plot_widget import PlotWidget
from polyxrd.views.widgets.toolbar_icons import colorize_nav_toolbar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _xrd(lo=10.0, hi=80.0, n=3000):
    x = np.linspace(lo, hi, n)
    y = (100.0 * np.exp(-0.5 * ((x - 20.0) / 0.1) ** 2)
         + 60.0 * np.exp(-0.5 * ((x - 45.0) / 0.15) ** 2) + 5.0)
    return XRDData(two_theta=x, intensity=y)


_ALL_KEYS = tuple(k for g in TOOL_GROUPS for k in g)


# ----------------------------------------------------------------------
# 图标 / 导航条
# ----------------------------------------------------------------------

def test_all_plot_icons_present(qapp):
    assert len(_ALL_KEYS) == 9
    for key in _ALL_KEYS:
        icon = plot_icons.plot_icon(key)
        assert icon is not None and not icon.isNull(), key
    assert plot_icons.plot_icon("no_such_tool") is None


def test_nav_toolbar_colorized(qapp):
    w = PlotWidget()
    # 已在上线时着色一次；再调一次应幂等且覆盖全部可用动作
    n = colorize_nav_toolbar(w._toolbar)
    assert n >= 7  # home/back/forward/pan/zoom/subplots/edit/save


# ----------------------------------------------------------------------
# 工具行结构
# ----------------------------------------------------------------------

def test_toolbar_button_set_matches_groups(qapp):
    w = PlotWidget()
    tb = w._plot_toolbar
    assert isinstance(tb, PlotToolBar)
    assert tuple(tb.buttons) == _ALL_KEYS
    for key in MODE_TOOLS:
        assert tb.buttons[key].isCheckable()
    for key in _ALL_KEYS:
        if key not in MODE_TOOLS:
            assert not tb.buttons[key].isCheckable()


def test_mode_tools_exclusive_via_sync(qapp):
    w = PlotWidget()
    tb = w._plot_toolbar
    tb.sync("zoom_x")
    assert [k for k in MODE_TOOLS if tb.buttons[k].isChecked()] == ["zoom_x"]
    tb.sync("crosshair")
    assert [k for k in MODE_TOOLS if tb.buttons[k].isChecked()] == ["crosshair"]
    tb.sync(None)
    assert not any(tb.buttons[k].isChecked() for k in MODE_TOOLS)


# ----------------------------------------------------------------------
# 十字线
# ----------------------------------------------------------------------

def test_crosshair_sets_and_clears_cursor(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    w.set_plot_tool("crosshair")
    assert w._tool == "crosshair"
    w._update_cursor(20.0)
    assert w._cursor_line is not None and w._cursor_text is not None
    # 关闭工具后十字线应被清除
    w.set_plot_tool(None)
    assert w._cursor_line is None and w._cursor_x is None


def test_unknown_tool_rejected(qapp):
    w = PlotWidget()
    w.set_plot_tool("bogus")  # 静默拒绝
    assert w._tool is None


# ----------------------------------------------------------------------
# 步进缩放 / 平移 / 复位
# ----------------------------------------------------------------------

def test_zoom_scale_and_pan_and_reset(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    x0 = w._axes.get_xlim()
    span0 = x0[1] - x0[0]

    w.zoom_scale(0.8)
    x1 = w._axes.get_xlim()
    assert (x1[1] - x1[0]) < span0

    w.pan_x(0.25)
    x2 = w._axes.get_xlim()
    assert abs(x2[0] - x1[0]) > 1e-6

    w.reset_view()
    x3 = w._axes.get_xlim()
    assert abs((x3[1] - x3[0]) - span0) < 1e-6


# ----------------------------------------------------------------------
# 框选缩放
# ----------------------------------------------------------------------

def test_band_zoom_x(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    w.set_plot_tool("zoom_x")
    w._apply_band(18.0, 0.0, 22.0, 200.0)
    lo, hi = sorted(w._axes.get_xlim())
    assert lo <= 18.5 and hi >= 21.5


def test_band_zoom_y(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    w.set_plot_tool("zoom_y")
    w._apply_band(0.0, 10.0, 1.0, 70.0)
    lo, hi = sorted(w._axes.get_ylim())
    assert lo <= 10.5 and hi >= 69.5


def test_band_too_small_is_noop(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    w.set_plot_tool("zoom_x")
    before = w._axes.get_xlim()
    w._apply_band(20.0, 0.0, 20.0001, 1.0)  # 跨度远小于 2%
    assert w._axes.get_xlim() == before


# ----------------------------------------------------------------------
# i18n：三语工具提示键齐备
# ----------------------------------------------------------------------

def test_i18n_tool_keys_all_languages():
    from polyxrd.i18n.translations import en_US, ja_JP, zh_CN

    key_suffixes = [f"tool_{k}" for k in _ALL_KEYS]
    for mod in (zh_CN, ja_JP, en_US):
        blk = mod.translations["vw"]["plot_widget"]
        for suffix in key_suffixes:
            assert blk.get(suffix), f"{mod.__name__} 缺 {suffix}"
