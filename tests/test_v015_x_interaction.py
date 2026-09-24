"""v0.15.0 M22 图谱横坐标自适应缩放测试 (offscreen Qt)
=====================================================
覆盖:
- fit_x_to_data: 首屏贴合数据 2θ 范围 (1% 边距) / 多数据集并集 / 空数据 no-op
- 滚轮缩放: 以鼠标位置为中心 ±15%/格, clamp 到数据范围外扩 20%
- 左键拖动平移: 位移 >3px 生效且 clamp; 峰点击 (<3px) 仍触发 peak_clicked
- reset_view / toolbar Home 回到数据范围
- clear_plot 后缩放基准失效
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.models.peak import Peak
from polyxrd.models.xrd_data import XRDData
from polyxrd.views.widgets.plot_widget import PlotWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Ev:
    """最小鼠标/滚轮事件替身。"""

    def __init__(self, x=0.0, y=0.0, button=1, inaxes=None, xdata=None, step=0):
        self.x = x
        self.y = y
        self.button = button
        self.inaxes = inaxes
        self.xdata = xdata
        self.step = step


def _xrd(lo=10.0, hi=80.0, n=2000):
    x = np.linspace(lo, hi, n)
    y = 1000 * np.exp(-0.5 * ((x - 20.1) / 0.08) ** 2) + 5.0
    return XRDData(two_theta=x, intensity=y)


def _xdata_at(w, px, py):
    """像素坐标 → 数据坐标。"""
    inv = w._axes.transData.inverted()
    return float(inv.transform((px, py))[0])


# ----------------------------------------------------------------------
# M22-1 / M22-2: fit_x_to_data
# ----------------------------------------------------------------------

def test_first_screen_fits_data_range(qapp):
    w = PlotWidget()
    w.plot_data(_xrd(5.0, 150.0))
    lo, hi = w._axes.get_xlim()
    # 1% 边距: 数据宽 145 → 边距 1.45
    assert 3.0 < lo < 5.0, lo
    assert 150.0 < hi < 152.0, hi
    assert w._data_xlim == pytest.approx((3.55, 151.45))
    w.close()


def test_multi_dataset_takes_union(qapp):
    w = PlotWidget()
    w.plot_data(_xrd(10.0, 60.0))
    w.plot_data(_xrd(20.0, 90.0))
    lo, hi = w._axes.get_xlim()
    assert lo < 10.0 and hi > 90.0
    w.close()


def test_empty_and_nan_noop(qapp):
    w = PlotWidget()
    before = w._axes.get_xlim()
    w.fit_x_to_data()  # 空数据 no-op
    assert w._axes.get_xlim() == before
    assert w._data_xlim is None
    # 全 NaN 数据也不抛异常
    x = np.linspace(10, 80, 100)
    w._data_list.append(
        XRDData(two_theta=x, intensity=np.full_like(x, 5.0))
    )
    w._data_list[-1].two_theta = np.full_like(x, np.nan)
    w.fit_x_to_data()
    assert w._data_xlim is None
    w.close()


def test_clear_resets_zoom_base(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    assert w._data_xlim is not None
    w.clear_plot()
    assert w._data_xlim is None
    w.close()


# ----------------------------------------------------------------------
# M22-3: 滚轮缩放
# ----------------------------------------------------------------------

def test_scroll_zoom_centered_and_clamped(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    w.get_figure().canvas.draw()
    l0, r0 = w._axes.get_xlim()

    # 放大: 以中心为锚, 宽度缩 15%
    xc = (l0 + r0) / 2.0
    w._on_scroll(_Ev(inaxes=w._axes, xdata=xc, step=1))
    l1, r1 = w._axes.get_xlim()
    assert (r1 - l1) == pytest.approx((r0 - l0) * 0.85, rel=1e-6)
    assert (l1 + r1) / 2.0 == pytest.approx(xc, abs=(r0 - l0) * 1e-3)

    # 缩小: 宽度扩 15% (0.85 × 1.15 = 0.9775, 非对称缩放)
    w._on_scroll(_Ev(inaxes=w._axes, xdata=xc, step=-1))
    l2, r2 = w._axes.get_xlim()
    assert (r2 - l2) == pytest.approx((r0 - l0) * 0.85 * 1.15, rel=1e-6)

    # 非数据区滚轮无效
    w._on_scroll(_Ev(inaxes=None, xdata=30.0, step=1))
    assert w._axes.get_xlim() == (l2, r2)

    # 连续放大 50 格 → 被 clamp 在数据范围外扩 20% 内
    for _ in range(50):
        w._on_scroll(_Ev(inaxes=w._axes, xdata=l2 + 1.0, step=1))
    lo, hi = w._axes.get_xlim()
    blo, bhi = w._x_bounds()
    assert lo >= blo - 1e-9 and hi <= bhi + 1e-9
    assert hi - lo > 0  # 永不为零宽
    w.close()


def test_scroll_inactive_in_toolbar_mode(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    l0, r0 = w._axes.get_xlim()
    w._toolbar.mode = "pan/zoom"  # 工具栏平移模式下滚轮交给 mpl
    w._on_scroll(_Ev(inaxes=w._axes, xdata=45.0, step=1))
    assert w._axes.get_xlim() == (l0, r0)
    w._toolbar.mode = ""
    w.close()


# ----------------------------------------------------------------------
# M22-3: 拖动平移与峰点击兼容
# ----------------------------------------------------------------------

def test_drag_pans_and_clamps(qapp):
    w = PlotWidget()
    w.resize(800, 600)
    w.show()
    w.plot_data(_xrd())
    w.get_figure().canvas.draw()
    bb = w._axes.get_window_extent()
    py = (bb.y0 + bb.y1) / 2.0
    px = bb.x0 + (bb.x1 - bb.x0) * 0.5
    l0, r0 = w._axes.get_xlim()

    w._on_mouse_press(_Ev(x=px, y=py, inaxes=w._axes, xdata=_xdata_at(w, px, py)))
    # 位移 60px (>3px) → 平移
    px2 = px + 60
    w._on_mouse_move(_Ev(x=px2, y=py, button=1, inaxes=w._axes,
                         xdata=_xdata_at(w, px2, py)))
    l1, r1 = w._axes.get_xlim()
    assert (r1 - l1) == pytest.approx(r0 - l0)
    assert l1 != l0  # 视图确实平移了
    blo, bhi = w._x_bounds()
    assert l1 >= blo - 1e-9 and r1 <= bhi + 1e-9

    w._on_mouse_release(_Ev(x=px2, y=py, button=1, inaxes=w._axes,
                            xdata=_xdata_at(w, px2, py)))
    assert w._pan_state is None
    w.close()


def test_small_move_is_click_not_pan(qapp):
    """位移 <3px → 不平移, 且峰点击照常发射 (M22 兼容性验收)。"""
    w = PlotWidget()
    w.resize(800, 600)
    w.show()
    w.plot_data(_xrd())
    w.get_figure().canvas.draw()
    got = []
    w.peak_clicked.connect(got.append)
    peak = Peak(two_theta=20.1, intensity=1000.0)
    w._peaks = [peak]

    bb = w._axes.get_window_extent()
    py = (bb.y0 + bb.y1) / 2.0
    x_at_peak = bb.x0 + (bb.x1 - bb.x0) * (20.1 - w._data_xlim[0]) / (
        w._data_xlim[1] - w._data_xlim[0])
    xd = _xdata_at(w, x_at_peak, py)

    w._on_mouse_press(_Ev(x=x_at_peak, y=py, inaxes=w._axes, xdata=xd))
    w._on_mouse_move(_Ev(x=x_at_peak + 2, y=py, button=1, inaxes=w._axes,
                         xdata=xd + 0.01))
    l0 = w._axes.get_xlim()  # 2px 不平移
    w._on_mouse_release(_Ev(x=x_at_peak + 2, y=py, button=1, inaxes=w._axes,
                            xdata=xd + 0.01))
    assert w._axes.get_xlim() == l0
    assert len(got) == 1  # 峰点击仍触发
    w.close()


def test_drag_past_threshold_suppresses_peak_click(qapp):
    w = PlotWidget()
    w.plot_data(_xrd())
    got = []
    w.peak_clicked.connect(got.append)
    w._peaks = [Peak(two_theta=20.1, intensity=1000.0)]
    w._on_mouse_press(_Ev(x=100.0, y=100.0, inaxes=w._axes, xdata=20.1))
    w._on_mouse_move(_Ev(x=200.0, y=100.0, button=1, inaxes=w._axes, xdata=25.0))
    w._on_mouse_release(_Ev(x=200.0, y=100.0, button=1, inaxes=w._axes, xdata=25.0))
    assert got == []  # 拖动 → 不算点击
    w.close()


# ----------------------------------------------------------------------
# M22-4: 重置 / Home
# ----------------------------------------------------------------------

def test_reset_and_home_return_to_data_range(qapp):
    w = PlotWidget()
    w.resize(800, 600)
    w.show()
    w.plot_data(_xrd())
    w.get_figure().canvas.draw()
    home_xlim = w._axes.get_xlim()

    # 滚轮缩放 10 格
    for _ in range(10):
        w._on_scroll(_Ev(inaxes=w._axes, xdata=45.0, step=1))
    assert w._axes.get_xlim() != home_xlim

    w.reset_view()
    assert w._axes.get_xlim() == pytest.approx(home_xlim)

    # toolbar Home 也接到 reset_view
    w._on_scroll(_Ev(inaxes=w._axes, xdata=45.0, step=1))
    assert w._axes.get_xlim() != home_xlim
    home_action = w._toolbar._actions["home"]
    home_action.trigger()
    assert w._axes.get_xlim() == pytest.approx(home_xlim)
    w.close()
