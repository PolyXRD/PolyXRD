"""v0.15.0 M24 结构精修页布局重构测试 (offscreen Qt)
====================================================
- 残差改细条: 布局 stretch 5:1, 与主图 X 轴双向同步
- 精修日志移到左栏 (残差条下方), 整页底部分栏取消
- 右栏新增「已勾选物相」列表 (selection_changed 驱动, 右键导出 CIF)
- 外部精修程序容器存在 (M25 填充)
- _WINDOW_STATE_VERSION 升到 3

v2.6.0 目标 3 再度重排 (向 GSAS-II / MAUD 看齐):
- 残差条由「1/6 高度的独立大图」→ 固定高度 (60~130px) 紧凑条,
  stretch=0, 无标题无工具栏, 主图 stretch=5 独占纵向余量
- 外部精修程序面板由「右栏底部」→「左栏日志下方」, 右栏得以松绑
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.models.phase import Phase
from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.refinement_view import RefinementView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def view(qapp):
    v = RefinementView(MainViewModel())
    yield v
    v.close()
    v.deleteLater()


def _left_column(view):
    """左栏容器 (对比图 / 残差条 / 日志 / 外部程序 的共同父级)。"""
    return view._compare_plot.parentWidget()


def _left_slots(view):
    """左栏里各关键控件的槽位: 名字 → 布局索引。"""
    left = _left_column(view)
    assert left is not None
    lay = left.layout()
    assert lay is not None
    slots: dict[str, int] = {}
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is view._compare_plot:
            slots["compare"] = i
        elif w is view._residual_plot:
            slots["residual"] = i
        elif w is view._ext_group:
            slots["ext"] = i
        elif w is view._log_view.parentWidget():
            slots["log"] = i
    return lay, slots


def test_residual_is_thin_strip(view):
    """v2.6.0: 残差条 = 固定高度紧凑条 (stretch=0), 主图 stretch=5 拿全部余量。

    旧版是 5:1 均分且残差带标题+工具栏 —— 残差白占约 1/4 高度;
    新版向 GSAS-II / MAUD 看齐: 主图下一条残差, 高度锁在 60~130px。
    """
    lay, slots = _left_slots(view)
    assert {"compare", "residual"} <= set(slots), "两张图必须同属左栏"

    assert lay.stretch(slots["compare"]) == 5
    # 不参与拉伸: 布局把富余高度全给主图
    assert lay.stretch(slots["residual"]) == 0

    res = view._residual_plot
    assert res._compact is True
    assert res._toolbar is None, "紧凑条不该带 matplotlib 工具栏"
    assert res._canvas.minimumHeight() == 60
    assert res._canvas.maximumHeight() <= 130, "残差条要真的『一条』那么高"


def test_external_group_sits_below_log_in_left_column(view):
    """v2.6.0: 外部精修程序面板从右栏底部移到左栏 (日志正下方)。"""
    _lay, slots = _left_slots(view)
    assert "ext" in slots, "外部精修程序面板必须在左栏 (不再挂右栏)"
    assert {"compare", "residual", "log", "ext"} <= set(slots)
    # 自上而下: 对比图 → 残差条 → 精修日志 → 外部程序
    assert slots["compare"] < slots["residual"] < slots["log"] < slots["ext"]


def test_residual_follows_compare_xlim(view):
    cax = view._compare_plot.get_axes()
    rax = view._residual_plot.get_axes()
    cax.set_xlim(20.0, 30.0)
    assert rax.get_xlim() == pytest.approx((20.0, 30.0))
    # 反向: 残差条平移 → 主图跟随
    rax.set_xlim(22.0, 26.0)
    assert cax.get_xlim() == pytest.approx((22.0, 26.0))


def test_log_panel_moved_into_left_column(view):
    """日志面板的父级应与对比图同属左栏 (不再挂整页底部分栏)。"""
    log_parent = view._log_view.parentWidget()  # QGroupBox 内
    assert log_parent is not None
    # 左栏 widget 是 compare_plot 的父容器
    left = view._compare_plot.parentWidget()
    assert left is not None
    # 日志GroupBox的父级 == 左栏 widget
    group = log_parent  # QGroupBox
    assert group.parentWidget() is left


def test_no_full_page_splitter(view):
    """整页不应再有 Vertical QSplitter 包住日志 (旧布局已拆除)。"""
    from PySide6.QtWidgets import QSplitter
    splitters = view.findChildren(QSplitter)
    assert splitters == []


def test_selected_phase_list_driven_by_vm(view):
    from PySide6.QtCore import Qt

    p1 = Phase(name="Calcite", formula="CaCO3")
    p2 = Phase(name="ZnO", formula="ZnO")
    view._vm._phase_vm.selection_changed.emit([p1, p2])
    assert view._selected_phase_list.count() == 2
    assert "Calcite" in view._selected_phase_list.item(0).text()
    assert view._selected_phase_list.item(0).data(
        Qt.ItemDataRole.UserRole
    ) is p1
    view._vm._phase_vm.selection_changed.emit([])
    assert view._selected_phase_list.count() == 0


def test_external_program_container_exists(view):
    assert view._ext_group is not None
    assert "外部精修程序" in view._ext_group.title()


def test_window_state_version_bumped():
    from polyxrd.views.main_window import MainWindow

    assert MainWindow._WINDOW_STATE_VERSION >= 3


def test_context_menu_handler_exists(view):
    assert hasattr(view, "_selected_phase_context_menu")
