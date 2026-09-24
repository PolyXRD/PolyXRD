"""
v0.12.0 纵坐标 线性/对数/方根 刻度测试 (offscreen Qt)
=====================================================
覆盖:
- y_scale 纯逻辑: 模式常量/规范化/循环/标签后缀
- apply_y_scale: 对数/方根真实生效 + y 范围只取正数据点 (残差负债不污染范围)
- 回线性后自动缩放恢复
- PlotWidget / PatternDisplayWidget: 左键点 Y 轴竖条循环、右键命中数据区、
  数据区左键不误触发切换
- 数值换算是真的: 方根刻度下 y 轴刻度值仍是真实强度量级
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.models.xrd_data import XRDData
from polyxrd.views.widgets.plot_widget import PlotWidget
from polyxrd.views.widgets.pattern_display import PatternDisplayWidget
from polyxrd.views.widgets.y_scale import (
    Y_SCALE_CYCLE,
    Y_SCALE_LINEAR,
    Y_SCALE_LOG,
    Y_SCALE_SQRT,
    Y_SCALE_TOKENS,
    apply_y_scale,
    current_y_scale,
    hint_text,
    next_y_scale,
    normalize_y_scale,
    scaled_ylabel,
    y_scale_label,
)


@pytest.fixture(scope="module")
def qapp():
    from polyxrd.i18n import I18nManager, Language

    app = QApplication.instance() or QApplication([])
    # 断言里写了中文标签 → 固定成 zh_CN, 免得上一个测试模块把语言改掉
    try:
        I18nManager().set_language(Language.ZH_CN)
    except Exception:  # noqa: BLE001
        pass
    yield app


class _Ev:
    """最小鼠标事件替身 (只需要控制器用到的几个字段)。"""

    def __init__(self, x, y, button=1, inaxes=None, xdata=1.0):
        self.x = x
        self.y = y
        self.button = button
        self.inaxes = inaxes
        self.xdata = xdata


def _xrd(n=2000, bg=5.0):
    x = np.linspace(10.0, 80.0, n)
    y = (1000 * np.exp(-0.5 * ((x - 20.1) / 0.08) ** 2)
         + 300 * np.exp(-0.5 * ((x - 35.0) / 0.09) ** 2)
         + 30 * np.exp(-0.5 * ((x - 60.0) / 0.10) ** 2)
         + bg)
    return XRDData(two_theta=x, intensity=y)


# ----------------------------------------------------------------------
# 纯逻辑
# ----------------------------------------------------------------------

def test_cycle_order_and_normalize():
    assert Y_SCALE_CYCLE == (Y_SCALE_LINEAR, Y_SCALE_LOG, Y_SCALE_SQRT)
    assert next_y_scale(Y_SCALE_LINEAR) == Y_SCALE_LOG
    assert next_y_scale(Y_SCALE_LOG) == Y_SCALE_SQRT
    assert next_y_scale(Y_SCALE_SQRT) == Y_SCALE_LINEAR
    # 非法值收敛成线性, 不抛异常
    assert normalize_y_scale("bogus") == Y_SCALE_LINEAR
    assert normalize_y_scale(None) == Y_SCALE_LINEAR


def test_labels_and_suffix():
    # 菜单/提示等界面控件照常本地化
    assert y_scale_label(Y_SCALE_LOG) == "对数"
    assert y_scale_label(Y_SCALE_SQRT) == "方根"
    # 轴标题后缀走技术记号: 任何语言下都是 log / sqrt, 不翻译
    assert Y_SCALE_TOKENS == {Y_SCALE_LINEAR: "", Y_SCALE_LOG: "log",
                              Y_SCALE_SQRT: "sqrt"}
    assert scaled_ylabel("Intensity", Y_SCALE_LINEAR) == "Intensity"
    assert scaled_ylabel("Intensity", Y_SCALE_LOG) == "Intensity (log)"
    assert scaled_ylabel("Intensity", Y_SCALE_SQRT) == "Intensity (sqrt)"
    assert "log" in hint_text(Y_SCALE_LOG)
    assert "sqrt" in hint_text(Y_SCALE_SQRT)
    assert "linear" in hint_text(Y_SCALE_LINEAR)


def test_apply_y_scale_on_axes(qapp):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure()
    ax = fig.add_subplot(111)
    x = np.linspace(0, 10, 500)
    ax.plot(x, 1000 * np.exp(-x) + 3)
    # 残差曲线整体为负 (模拟扣背景残差的展示偏移)
    ax.plot(x, -0.15 * 1000 + 5 * np.sin(x))

    assert current_y_scale(ax) == Y_SCALE_LINEAR

    apply_y_scale(ax, Y_SCALE_LOG)
    assert ax.get_yscale() == "log"
    assert current_y_scale(ax) == Y_SCALE_LOG
    lo, hi = ax.get_ylim()
    # 只取正数据点: 下限应贴近真实正数据 (≈3 的一半), 而不是被裁到 1e-308
    assert lo > 0.1, lo
    assert hi < 4000, hi
    assert ax.get_autoscaley_on() is False

    apply_y_scale(ax, Y_SCALE_SQRT)
    assert ax.get_yscale() != "linear"
    lo, hi = ax.get_ylim()
    assert lo >= 0.0
    assert hi > 0

    apply_y_scale(ax, Y_SCALE_LINEAR)
    assert ax.get_yscale() == "linear"
    assert ax.get_autoscaley_on() is True
    lo, _ = ax.get_ylim()
    assert lo < 0  # 线性下负残差重新进入视野


def test_apply_y_scale_survives_all_negative(qapp):
    """整条曲线都是负值 → 对数/方根无意义, 但绝不允许抛异常。"""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure()
    ax = fig.add_subplot(111)
    x = np.linspace(0, 10, 100)
    ax.plot(x, -np.abs(np.sin(x)) - 1.0)

    apply_y_scale(ax, Y_SCALE_LOG)
    apply_y_scale(ax, Y_SCALE_SQRT)
    apply_y_scale(ax, Y_SCALE_LINEAR)
    assert ax.get_yscale() == "linear"


# ----------------------------------------------------------------------
# PlotWidget
# ----------------------------------------------------------------------

def test_plot_widget_cycle_and_strip_hit(qapp):
    w = PlotWidget()
    w.resize(800, 600)
    w.show()
    w.plot_data(_xrd(), label="t")
    w.get_figure().canvas.draw()

    assert w.get_y_scale_mode() == Y_SCALE_LINEAR
    w.set_y_scale_mode(Y_SCALE_LOG)
    assert w._axes.get_yscale() == "log"
    assert w._axes.get_ylabel() == "Intensity (log)"
    assert "log" in w._y_scale_hint.text()

    bb = w._axes.get_window_extent()
    mid = (bb.y0 + bb.y1) / 2.0
    # 左键落在 Y 轴竖条 → 命中
    assert w._y_scale._axes_at(_Ev(bb.x0 - 30, mid), inaxes_ok=False) is w._axes
    # 左键落在数据区中间 → 不命中 (交给峰点击)
    assert w._y_scale._axes_at(_Ev((bb.x0 + bb.x1) / 2, mid), inaxes_ok=False) is None
    # 左键离 Y 轴太远 → 不命中
    assert w._y_scale._axes_at(_Ev(bb.x0 - 400, mid), inaxes_ok=False) is None
    # 右键在数据区 → 命中 (弹菜单)
    assert w._y_scale._axes_at(_Ev((bb.x0 + bb.x1) / 2, mid), inaxes_ok=True) is w._axes

    # 循环: log → sqrt → linear
    w._y_scale.cycle()
    assert w.get_y_scale_mode() == Y_SCALE_SQRT
    w._y_scale.cycle()
    assert w.get_y_scale_mode() == Y_SCALE_LINEAR
    w.close()


def test_plot_widget_log_survives_clear_and_replot(qapp):
    w = PlotWidget()
    w.set_y_scale_mode(Y_SCALE_LOG)
    w.plot_data(_xrd(), label="t")
    assert w._axes.get_yscale() == "log"
    # clear_plot 会重置刻度 → 必须按当前模式贴回
    w.clear_plot()
    assert w._axes.get_yscale() == "log"
    assert w._axes.get_ylabel() == "Intensity (log)"
    w.close()


def test_plot_widget_right_click_does_not_emit_peak(qapp):
    from polyxrd.models.peak import Peak

    w = PlotWidget()
    w.plot_data(_xrd(), label="t")
    got = []
    w.peak_clicked.connect(got.append)
    peak = Peak(two_theta=20.1, intensity=1000.0)
    w._peaks = [peak]
    bb = w._axes.get_window_extent()
    y = (bb.y0 + bb.y1) / 2
    x = bb.x0 + (bb.x1 - bb.x0) * (20.1 - 10) / 70.0
    w._on_mouse_press(_Ev(x, y, button=3, inaxes=w._axes, xdata=20.1))
    w._on_mouse_release(_Ev(x, y, button=3, inaxes=w._axes, xdata=20.1))
    assert got == []  # 右键不触发峰点击
    # M22: 峰点击改为「按下命中 + 释放未拖动」才发射
    w._on_mouse_press(_Ev(x, y, button=1, inaxes=w._axes, xdata=20.1))
    assert got == []  # 仅按下不发射
    w._on_mouse_release(_Ev(x, y, button=1, inaxes=w._axes, xdata=20.1))
    assert len(got) == 1
    w.close()


# ----------------------------------------------------------------------
# PatternDisplayWidget
# ----------------------------------------------------------------------

def test_pattern_display_log_and_sqrt(qapp):
    p = PatternDisplayWidget()
    p.resize(800, 600)
    p.show()
    data = _xrd()
    p.set_experiment(data)
    # 残差整体压在 0 以下 (主区底部偏移) —— 对数轴不能被它拖垮
    p.set_residual_curve(data.two_theta,
                         data.intensity - float(np.mean(data.intensity)))
    p.get_figure().canvas.draw()

    p.set_y_scale_mode(Y_SCALE_LOG)
    assert p._ax_main.get_yscale() == "log"
    lo, hi = p._ax_main.get_ylim()
    assert lo > 0.1, lo
    assert hi < 5000, hi
    assert p._ax_main.get_ylabel() == "Intensity (log)"
    # 棒区不受影响 (虚拟行坐标)
    assert p._ax_stick.get_yscale() == "linear"

    p.set_y_scale_mode(Y_SCALE_SQRT)
    assert p._ax_main.get_yscale() != "linear"

    # 清除整图后模式与轴标题都应保留
    p.clear_all()
    assert p._ax_main.get_yscale() != "linear"
    assert p._ax_main.get_ylabel() == "Intensity (sqrt)"
    p.close()


def test_pattern_display_left_click_data_area_not_scale(qapp):
    p = PatternDisplayWidget()
    p.resize(800, 600)
    p.show()
    p.set_experiment(_xrd())
    p.get_figure().canvas.draw()
    bb = p._ax_main.get_window_extent()
    assert p._y_scale._axes_at(
        _Ev((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2), inaxes_ok=False
    ) is None
    assert p.get_y_scale_mode() == Y_SCALE_LINEAR
    p.close()
