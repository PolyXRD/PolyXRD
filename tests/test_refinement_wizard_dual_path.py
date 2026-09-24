"""
精修向导的双路径合并 (v0.11.0)。

背景: 项目里曾长期并存两个向导, 但只有简洁版被主窗口挂载, 功能更全的分步版
(`refinement_wizard.RefinementWizard`) 是**死代码** —— 无挂载、无测试, 只被
`views/__init__.py` 导出。

现在合并为「两条路径都保留, 用户在菜单里挑」:
- 路径 A 快速: `main_window.RefinementWizardDialog` (单页参数 → 主 VM 精修)
- 路径 B 分步: `refinement_wizard.RefinementWizardHostDialog` (5 页向导,
  **自带 refiner 独立执行**, 结果经 `adopt_refinement_result` 回灌主窗口)

本文件守住合并后的三个关键契约:
1. 两个入口都在, 且指向不同实现;
2. 分步向导能被宿主对话框正确装载与播种 (数据/物相/默认引擎);
3. 分步向导的结果**必须回灌**到精修 VM —— 否则用户在向导里跑完会看到
   精修页/报告页空着, 与快速路径行为不一致 (这就是"合并"最容易漏掉的一环)。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.models.phase import Phase
from polyxrd.models.xrd_data import XRDData


@pytest.fixture(scope="session")
def qapp():
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture
def data() -> XRDData:
    return XRDData(
        two_theta=np.linspace(10.0, 80.0, 700),
        intensity=np.ones(700),
        wavelength=1.5406,
    )


@pytest.fixture
def phases() -> list[Phase]:
    return [Phase(name="Zincite", formula="ZnO")]


@pytest.fixture
def host(qapp, data, phases):
    from polyxrd.views.refinement_wizard import RefinementWizardHostDialog

    d = RefinementWizardHostDialog(data, phases)
    yield d
    d.deleteLater()


# ====================================================================
# 1. 宿主对话框: 装载与播种
# ====================================================================

class TestHostDialogSeeding:
    def test_wraps_the_multipage_wizard(self, host):
        from polyxrd.views.refinement_wizard import RefinementWizard

        assert isinstance(host.wizard, RefinementWizard)

    def test_has_all_five_pages(self, host):
        assert host.wizard._stack.count() == 5

    def test_phase_dropdown_defaults_to_auto(self, host):
        """分步向导默认引擎应为 auto, 与快速向导/批量精修/精修视图一致。

        实现方式: 内置模板首位是「自动选择（推荐）」(engine=auto),
        向导构造时套用第一个模板。别让这个默认悄悄退回某个具体引擎。
        """
        assert host.wizard._engine_combo.currentText() == "auto"
        assert host.wizard.get_refinement_config()["engine"] == "auto"

    def test_seeds_current_data_and_phases(self, host, phases):
        """不播种的话用户一进来就是空白, 得手动重选一遍已有的数据/物相。"""
        assert host.wizard._data is not None
        names = [p.name for p in host.wizard.get_selected_phases()]
        assert names == [p.name for p in phases]

    def test_works_without_seed(self, qapp):
        """允许空启动 (从菜单打开时还没数据) —— 不能崩。"""
        from polyxrd.views.refinement_wizard import RefinementWizardHostDialog

        d = RefinementWizardHostDialog(None, None)
        assert d.wizard._data is None
        assert d.wizard.get_selected_phases() == []
        d.deleteLater()


# ====================================================================
# 2. 结果回灌 (合并最易漏的一环)
# ====================================================================

class TestHostBridgesResult:
    def test_completion_emits_result_ready(self, host):
        sentinel = object()
        got: list = []
        host.result_ready.connect(got.append)

        host._on_wizard_completed(sentinel)

        assert got == [sentinel]

    def test_completion_also_accepts_dialog(self, host):
        """结果发出去之后要关窗, 否则用户得再点一次关闭。"""
        accepted: list = []
        host.accepted.connect(lambda: accepted.append(True))

        host._on_wizard_completed(object())

        assert accepted, "精修完成后对话框应自动 accept 关闭"

    def test_cancel_rejects_dialog(self, host):
        rejected: list = []
        host.rejected.connect(lambda: rejected.append(True))

        host.wizard.wizard_cancelled.emit()

        assert rejected, "向导取消应关闭宿主对话框"


class TestRefinementVMAdoptResult:
    """`adopt_result` 是回灌的落点: 只登记状态 + 广播, 不触发任何计算。"""

    @pytest.fixture
    def vm(self, qapp):
        from polyxrd.viewmodels.refinement_vm import RefinementViewModel

        return RefinementViewModel()

    def test_sets_result_and_broadcasts(self, vm):
        sentinel = object()
        done: list = []
        prog: list = []
        vm.refinement_completed.connect(done.append)
        vm.refinement_progress.connect(prog.append)

        vm.adopt_result(sentinel)

        assert vm.result is sentinel
        assert done == [sentinel]
        assert prog == [100], "应广播 100% 进度, 让进度条归位"

    def test_none_is_ignored(self, vm):
        """别把 None 塞进结果位 (否则报告页会拿到空对象去渲染)。"""
        done: list = []
        vm.refinement_completed.connect(done.append)
        vm.adopt_result(None)
        assert vm.result is None
        assert done == []

    def test_reset_clears_adopted_result(self, vm):
        vm.adopt_result(object())
        vm.reset()
        assert vm.result is None


class TestMainVMPassthrough:
    def test_adopt_refinement_result_delegates(self, qapp):
        """MainViewModel 只是转发; 顺便守住它别把结果丢了。"""
        import inspect

        from polyxrd.viewmodels.main_vm import MainViewModel

        src = inspect.getsource(MainViewModel.adopt_refinement_result)
        assert "adopt_result" in src

    def test_matched_phases_property_exists(self):
        """兜底取"匹配分最高的物相"要用它; 之前 MainViewModel 上没有这个属性,
        导致向导的兜底分支永远拿不到东西 (静默变成死代码)。"""
        from polyxrd.viewmodels.main_vm import MainViewModel

        assert isinstance(MainViewModel.matched_phases, property)


# ====================================================================
# 3. 两个入口都在, 且指向不同实现
# ====================================================================

class TestTwoEntryPoints:
    def test_main_window_registers_both_wizard_actions(self):
        """源码级断言: 不实例化 MainWindow (要拉 COD 库/建全部标签页, 太重)。"""
        import inspect

        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._setup_refine_menu)
        assert '"refine_wizard_menu"' in src, "缺少快速向导入口"
        assert '"refine_wizard_full"' in src, "缺少分步向导入口"
        assert "_on_refine_wizard" in src and "_on_refine_wizard_full" in src

    def test_full_handler_uses_host_dialog_and_bridges(self):
        import inspect

        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._on_refine_wizard_full)
        assert "RefinementWizardHostDialog" in src, "分步入口应使用宿主对话框"
        assert "result_ready" in src, "必须接上结果回灌信号"

    def test_result_handler_adopts_and_switches_tab(self):
        import inspect

        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._on_wizard_result_ready)
        assert "adopt_refinement_result" in src, "结果必须登记进 VM"
        assert "setCurrentWidget" in src, "应切到精修页让用户看到结果"

    def test_full_handler_guards_missing_data_and_phases(self):
        """没数据/没物相时要给明确提示, 而不是弹一个空向导让人困惑。"""
        import inspect

        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._on_refine_wizard_full)
        assert "current_data" in src and "refine_wizard_need_data" in src
        assert "selected_phases" in src and "refine_wizard_need_phase" in src

    def test_full_handler_does_not_mutate_selected_phases(self):
        """向导会把精修结果写回物相 (晶胞/wt%), 必须 deepcopy 隔离。"""
        import inspect

        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._on_refine_wizard_full)
        assert "deepcopy" in src


class TestToolbarPathPicker:
    """工具栏按钮上也要能选路径 (不只是藏在菜单里)。"""

    @pytest.fixture
    def win(self, qapp):
        from polyxrd.config import get_config
        from polyxrd.views.main_window import MainWindow

        w = MainWindow(get_config())
        yield w
        w.deleteLater()

    def test_toolbar_button_has_both_paths(self, win):
        from PySide6.QtWidgets import QToolButton

        btn = win._toolbar.widgetForAction(win._actions["refine_wizard"])
        assert btn is not None, "工具栏上应能找到精修向导按钮"
        assert isinstance(btn, QToolButton)
        menu = btn.menu()
        assert menu is not None, "应挂下拉菜单"
        texts = [a.text() for a in menu.actions()]
        assert len(texts) == 2, f"下拉应有两条路径, 实际: {texts}"

    def test_popup_mode_is_menu_button_not_instant(self, win):
        """必须是 MenuButtonPopup。

        用 InstantPopup 的话, 每次点按钮都先弹菜单 → 原本一步的操作变成两步,
        属于体验倒退。MenuButtonPopup 保持"点主体=快速向导"的旧习惯。
        """
        from PySide6.QtWidgets import QToolButton

        btn = win._toolbar.widgetForAction(win._actions["refine_wizard"])
        assert btn.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup

    def test_menu_bar_lists_both_wizards(self, win):
        texts = [
            a.text() for a in win._menus["refine"].actions() if not a.isSeparator()
        ]
        joined = " | ".join(texts)
        assert "快速" in joined and "分步" in joined, f"菜单里两条路径缺失: {joined}"

    def test_quick_action_still_wired_to_quick_handler(self, win):
        """别在接线时把主体按钮指错到分步版 (那会让老用户每次多点几步)。"""
        import inspect

        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._setup_toolbar)
        assert '_actions["refine_wizard"].triggered.connect(self._on_refine_wizard)' in src
        assert "_on_refine_wizard_full" not in src, \
            "工具栏主体按钮不应直接绑分步向导"


# ====================================================================
# 4. 模板: auto 预设
# ====================================================================

class TestAutoTemplate:
    def test_first_builtin_template_is_auto(self):
        from polyxrd.services.refinement_templates import RefinementTemplateManager

        first = RefinementTemplateManager().get_builtin_templates()[0]
        assert first.engine == "auto"
        assert first.is_builtin is True

    def test_template_engine_is_selectable_in_wizard(self, host):
        """模板给的引擎必须能在下拉里选中, 否则 setCurrentText 会静默失败
        (留在旧值上), 用户看到"模板选了但引擎没变"。"""
        from polyxrd.services.refinement_templates import RefinementTemplateManager

        combo = {
            host.wizard._engine_combo.itemText(i)
            for i in range(host.wizard._engine_combo.count())
        }
        engines = {t.engine for t in RefinementTemplateManager().get_all_templates()}
        assert engines <= combo, f"模板里的引擎不在下拉里: {sorted(engines - combo)}"
