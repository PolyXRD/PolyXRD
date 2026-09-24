"""v0.15.0 M24 结构精修页布局重构测试 (offscreen Qt)
====================================================
- 残差改细条: 布局 stretch 5:1, 与主图 X 轴双向同步
- 精修日志移到左栏 (残差条下方), 整页底部分栏取消
- 右栏新增「已勾选物相」列表 (selection_changed 驱动, 右键导出 CIF)
- 外部精修程序容器存在 (M25 填充)
- _WINDOW_STATE_VERSION 升到 3
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


def test_residual_is_thin_strip(view):
    """残差条 stretch=1, 主图 stretch=5 (原为均分)。"""
    lay = view._compare_plot.parentWidget().layout() \
        if view._compare_plot.parentWidget() else None
    # 直接查左栏布局的 stretch
    from PySide6.QtWidgets import QVBoxLayout
    left_layout = None
    p = view._compare_plot.parentWidget()
    if p is not None:
        lay = p.layout()
        if lay is not None:
            for i in range(lay.count()):
                w = lay.itemAt(i).widget()
                if w is view._compare_plot:
                    assert lay.stretch(i) == 5
                if w is view._residual_plot:
                    assert lay.stretch(i) == 1


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
