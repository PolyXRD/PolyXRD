"""
测试 RefinementWizardDialog 的 R-C5 改进:
- 引擎下拉多含 'maud'
- 状态标签 (可用/未安装) 反映 RietveldRefiner.get_engine_status()
- 选了不可用引擎时弹 fallback 提示

v0.11.0 增补 (验收前修的静默失效):
- 引擎下拉必须有 'auto' 且为默认 (验收用例就是"向导引擎选 auto")
- '_on_refine_wizard' 必须把 engine 真正下传 (曾漏传 → 选什么引擎都跑 builtin)
- wavelength / 2θ 窗口必须经 viewmodel 落到数据副本 (传 kwargs 会被引擎忽略)
"""
from __future__ import annotations

import inspect
import os

# 必须在 import 任何 PySide6 模块之前设好, 否则 offscreen 平台插件不生效
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from polyxrd.services.phase_structure_resolver import PhaseStructureResolver
from polyxrd.views.main_window import MainWindow, RefinementWizardDialog


# ====================================================================
# fixtures
# ====================================================================

@pytest.fixture(scope="session")
def qapp():
    a = QApplication.instance() or QApplication([])
    yield a
    # 不要 quit, 可能其它测试还要用


@pytest.fixture
def wizard(qapp, monkeypatch):
    """构造一个 wizard, 把 RietveldRefiner.get_engine_status 替换成可控 mock"""
    # 默认 mock 状态
    fake_status = {
        "builtin": {"available": True, "note": "内置 (始终可用)"},
        "auto": {"available": True, "resolves_to": "gsas2",
                 "note": "自动择引擎: 全相有结构 CIF 且 GSAS-II 可用 → gsas2; 否则 builtin"},
        "gsas2": {"available": True, "python": "C:/gsas2/python.exe",
                  "note": "GSAS-II 已装"},
        "powerxrd": {"available": False, "note": "未安装 powerxrd"},
        "maud": {"available": True, "maud_root": "C:/MAUD3",
                 "note": "MAUD3 已装"},
    }

    def _fake_status(self):
        return fake_status

    monkeypatch.setattr(
        "polyxrd.services.rietveld_refiner.RietveldRefiner.get_engine_status",
        _fake_status,
    )
    w = RefinementWizardDialog()
    yield w, fake_status


# ====================================================================
# 引擎下拉
# ====================================================================

class TestEngineCombo:
    def test_combo_includes_maud(self, wizard):
        w, _ = wizard
        items = [w._engine_combo.itemText(i) for i in range(w._engine_combo.count())]
        assert "maud" in items
        # 历史引擎也都还在
        assert "gsas2" in items
        assert "powerxrd" in items
        assert "builtin" in items

    def test_combo_includes_auto_and_defaults_to_auto(self, wizard):
        """验收用例就是"向导里引擎选 auto", 所以 auto 必须在且为默认值。"""
        w, _ = wizard
        items = [w._engine_combo.itemText(i) for i in range(w._engine_combo.count())]
        assert "auto" in items
        assert w._engine_combo.currentText() == "auto"
        assert w.get_params()["engine"] == "auto"

    def test_auto_status_is_available_not_a_fake_miss(self, wizard):
        """auto 不是"没装的引擎"; 若它显示 ✗ 未安装, 用户会被吓退。"""
        w, _ = wizard
        w._engine_combo.setCurrentText("auto")
        assert "#2a8c2a" in w._engine_status_label.styleSheet()
        assert w._engine_status_label.toolTip()  # 说明会走谁


class TestRealEngineStatusContract:
    """不被 mock 的真实现: get_engine_status() 必须覆盖下拉里的每个键。

    这条断言是"界面下拉 vs 服务状态键集合"的一致性闸门 —— 缺一个就会出现
    "选了却显示未安装"的假不可用。
    """

    def test_status_keys_cover_combo_items(self, qapp, monkeypatch):
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        # 真跑一次 (只探测环境, 不精修)
        status = RietveldRefiner().get_engine_status()
        assert "auto" in status
        assert status["auto"]["available"] is True
        assert status["auto"].get("resolves_to") in ("gsas2", "builtin")

        # 下拉项 ⊆ 状态键
        dialog = RefinementWizardDialog()
        items = {
            dialog._engine_combo.itemText(i)
            for i in range(dialog._engine_combo.count())
        }
        missing = items - set(status)
        assert not missing, f"下拉里有但 get_engine_status 未报告: {sorted(missing)}"


class TestAllEngineCombosAreConsistent:
    """四个界面的引擎下拉必须给同一组选项。

    历史问题: 向导没有 auto、批量/精修视图没有 maud, 各自缺一个 →
    用户在 A 处能选、在 B 处选不到, 且没有任何报错。

    这里对两个"构造代价高"的视图 (RefinementView 需要 MainViewModel,
    RefinementWizard 会 new CODSearcher/CIFDatabase) 走 **AST 取字面量**,
    既避开重量级初始化, 又比字符串匹配更抗改格式。
    """

    EXPECTED = {"auto", "gsas2", "powerxrd", "maud", "builtin"}

    @staticmethod
    def _combo_items_from_source(module_path: str) -> set[str]:
        import ast
        from pathlib import Path

        src = Path(module_path).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "addItems"):
                continue
            # 目标必须是 self._engine_combo
            tgt = fn.value
            if not (isinstance(tgt, ast.Attribute) and tgt.attr == "_engine_combo"):
                continue
            if not node.args or not isinstance(node.args[0], (ast.List, ast.Tuple)):
                continue
            out = set()
            for elt in node.args[0].elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    out.add(elt.value)
            if out:
                return out
        raise AssertionError(f"{module_path} 里找不到 _engine_combo.addItems([...])")

    def test_batch_dialog_combo(self, qapp):
        from polyxrd.views.batch_refinement_dialog import BatchRefinementDialog

        d = BatchRefinementDialog([])
        items = {
            d._engine_combo.itemText(i) for i in range(d._engine_combo.count())
        }
        assert items == self.EXPECTED
        assert d._engine_combo.currentText() == "auto"

    def test_wizard_dialog_combo(self, qapp):
        d = RefinementWizardDialog()
        items = {
            d._engine_combo.itemText(i) for i in range(d._engine_combo.count())
        }
        assert items == self.EXPECTED
        assert d._engine_combo.currentText() == "auto"

    def test_refinement_view_combo(self):
        import polyxrd.views.refinement_view as m

        items = self._combo_items_from_source(m.__file__)
        assert items == self.EXPECTED

    def test_multipage_wizard_widget_combo(self):
        import polyxrd.views.refinement_wizard as m

        items = self._combo_items_from_source(m.__file__)
        assert items == self.EXPECTED


# ====================================================================
# 状态标签
# ====================================================================

class TestEngineStatusLabel:
    def test_status_available_label(self, wizard):
        w, fake_status = wizard
        w._engine_combo.setCurrentText("builtin")
        # builtin 在 mock 里是 available
        text = w._engine_status_label.text()
        assert "可用" in text or "Available" in text  # i18n
        # 检查样式: 绿色
        assert "#2a8c2a" in w._engine_status_label.styleSheet()

    def test_status_unavailable_label(self, wizard):
        w, fake_status = wizard
        w._engine_combo.setCurrentText("powerxrd")
        text = w._engine_status_label.text()
        assert "未安装" in text or "Not installed" in text
        # 检查样式: 橙色
        assert "#c25a2a" in w._engine_status_label.styleSheet()

    def test_status_updates_on_combo_change(self, wizard):
        w, _ = wizard
        w._engine_combo.setCurrentText("gsas2")
        assert "#2a8c2a" in w._engine_status_label.styleSheet()
        w._engine_combo.setCurrentText("powerxrd")
        assert "#c25a2a" in w._engine_status_label.styleSheet()

    def test_status_unknown_engine_defaults_unavailable(self, wizard):
        w, fake_status = wizard
        # 模拟状态里没有的引擎 → 默认 unavailable
        fake_status.pop("powerxrd")
        w._engine_combo.setCurrentText("powerxrd")
        assert "#c25a2a" in w._engine_status_label.styleSheet()


# ====================================================================
# Fallback 提示
# ====================================================================

class TestFallbackPrompt:
    def test_maud_unavailable_shows_warning_and_fallback(self, wizard, monkeypatch):
        w, fake_status = wizard
        # 切到 MAUD 不可用状态
        fake_status["maud"] = {
            "available": False, "maud_root": None,
            "note": "未检测到 MAUD (C:\\MAUD2 / C:\\MAUD3)",
        }
        w._refresh_engine_status()
        w._engine_combo.setCurrentText("maud")

        # 拦截 QMessageBox.warning
        warnings: list[tuple] = []
        monkeypatch.setattr(
            "polyxrd.views.main_window.QMessageBox.warning",
            lambda *a, **kw: warnings.append((a, kw)) or QMessageBox.StandardButton.Ok,
        )

        # accept() 应: 弹 warning, 把 combo 改回 builtin, return 而不调 super().accept()
        # 用直接调用 accept() (不弹真正的 dialog)
        with patch.object(w, "super_accept", create=True) as mock_super:
            # accept 内调 super().accept() = QDialog.accept() — patch 即可
            with patch.object(type(w).__mro__[1], "accept",
                              lambda self: mock_super()):
                w.accept()
                # fallback 应改回 builtin
                assert w._engine_combo.currentText() == "builtin"
                # warning 应被调用
                assert len(warnings) == 1

    def test_maud_available_accepts_normally(self, wizard, monkeypatch):
        w, fake_status = wizard
        # 默认 fake_status 中 maud.available=True
        w._refresh_engine_status()
        w._engine_combo.setCurrentText("maud")

        accepted = []
        with patch.object(type(w).__mro__[1], "accept",
                          lambda self: accepted.append(True)):
            w.accept()
            assert len(accepted) == 1

    def test_non_maud_engine_does_not_prompt(self, wizard, monkeypatch):
        """用户选了 gsas2 (available) → 不弹 fallback"""
        w, _ = wizard
        w._engine_combo.setCurrentText("gsas2")
        warnings: list = []
        monkeypatch.setattr(
            "polyxrd.views.main_window.QMessageBox.warning",
            lambda *a, **kw: warnings.append((a, kw)),
        )
        accepted = []
        with patch.object(type(w).__mro__[1], "accept",
                          lambda self: accepted.append(True)):
            w.accept()
            assert len(warnings) == 0
            assert len(accepted) == 1

    def test_unavailable_gsas2_also_prompts(self, wizard, monkeypatch):
        """gsas2 不可用时也必须提示 —— 否则会静默回退内置引擎, 选与不选一个样。"""
        w, fake_status = wizard
        fake_status["gsas2"] = {"available": False, "python": None,
                                "note": "未检测到 GSAS-II"}
        w._refresh_engine_status()
        w._engine_combo.setCurrentText("gsas2")

        warnings: list = []
        monkeypatch.setattr(
            "polyxrd.views.main_window.QMessageBox.warning",
            lambda *a, **kw: warnings.append((a, kw)),
        )
        accepted: list = []
        with patch.object(type(w).__mro__[1], "accept",
                          lambda self: accepted.append(True)):
            w.accept()
            assert len(warnings) == 1
            assert not accepted  # 未确认, 让用户重选
            assert w._engine_combo.currentText() == "builtin"

    def test_auto_never_prompts_even_without_gsas2(self, wizard, monkeypatch):
        """auto 的回退是设计行为 (结果里会记 fallback 原因), 不该拦用户。"""
        w, fake_status = wizard
        fake_status["gsas2"] = {"available": False, "python": None,
                                "note": "未检测到 GSAS-II"}
        w._refresh_engine_status()
        w._engine_combo.setCurrentText("auto")

        warnings: list = []
        monkeypatch.setattr(
            "polyxrd.views.main_window.QMessageBox.warning",
            lambda *a, **kw: warnings.append((a, kw)),
        )
        accepted: list = []
        with patch.object(type(w).__mro__[1], "accept",
                          lambda self: accepted.append(True)):
            w.accept()
            assert len(warnings) == 0
            assert len(accepted) == 1


# ====================================================================
# 引擎参数是否真的下传 (静默失效回归闸门)
# ====================================================================

class TestRefineWizardPlumbsParams:
    """`_on_refine_wizard` 曾把 params['engine'] 丢掉 → 选什么引擎都跑 builtin。

    这里用源码级断言守住: 一旦有人再把它删掉, 测试立刻红。
    (不实例化 MainWindow: 它要拉 COD 库/建整套标签页, 太重。)
    """

    def test_engine_is_forwarded(self):
        src = inspect.getsource(MainWindow._on_refine_wizard)
        assert 'engine=params["engine"]' in src, (
            "精修向导必须把选中的引擎传给 refine_structure, "
            "否则用户选 gsas2/maud 会静默跑内置引擎"
        )

    def test_wavelength_and_window_are_forwarded(self):
        src = inspect.getsource(MainWindow._on_refine_wizard)
        assert "wavelength=params[" in src
        assert "two_theta_range=" in src, (
            "波长/2θ 窗口必须经 viewmodel 落到数据副本上; "
            "传成 two_theta_min=... 这种 kwargs 会被引擎忽略 (纯装饰控件)"
        )


# --------------------------------------------------------------------
# _apply_data_overrides: 波长 / 2θ 窗口真正落到数据对象上
# --------------------------------------------------------------------

class _FakeVM:
    """只为借 MainViewModel._apply_data_overrides 用 (它只碰 self.error_occurred)。"""

    class _Sig:
        def __init__(self, sink: list) -> None:
            self._sink = sink

        def emit(self, msg, *a, **k) -> None:
            self._sink.append(msg)

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.error_occurred = self._Sig(self.errors)


class TestApplyDataOverrides:
    def _apply(self, data, wavelength=None, window=None):
        from polyxrd.viewmodels.main_vm import MainViewModel

        vm = _FakeVM()
        out = MainViewModel._apply_data_overrides(
            vm, data, wavelength, window  # type: ignore[arg-type]
        )
        return out, vm.errors

    def test_wavelength_override(self):
        """波长要真的写进数据对象 (引擎只读 data.wavelength)。"""
        from polyxrd.models.xrd_data import XRDData

        d = XRDData(two_theta=np.linspace(10, 80, 200),
                    intensity=np.ones(200), wavelength=1.5406)
        out, errs = self._apply(d, 1.7889, None)
        assert out is not None and not errs
        assert abs(out.wavelength - 1.7889) < 1e-9
        assert abs(d.wavelength - 1.5406) < 1e-9  # 原始未被改

    def test_clips_two_theta_window(self):
        from polyxrd.models.xrd_data import XRDData

        d = XRDData(two_theta=np.linspace(10, 80, 701),
                    intensity=np.ones(701), wavelength=1.5406)
        out, errs = self._apply(d, None, (20.0, 60.0))
        assert out is not None and not errs
        assert out.two_theta[0] >= 20.0 - 1e-6
        assert out.two_theta[-1] <= 60.0 + 1e-6
        assert len(out.two_theta) < len(d.two_theta)

    def test_rejects_too_narrow_window(self):
        """窗口内 <3 点时必须给明确错误, 而不是让引擎抛难懂的异常。"""
        from polyxrd.models.xrd_data import XRDData

        d = XRDData(two_theta=np.linspace(10, 80, 701),
                    intensity=np.ones(701), wavelength=1.5406)
        out, errs = self._apply(d, None, (50.0, 50.02))
        assert out is None
        assert errs and "2θ 窗口" in errs[0]

    def test_rejects_window_outside_data_range(self):
        """请求窗口与数据范围完全不相交 → 报"没有交集"(而不是空集边界, 更好懂)。"""
        from polyxrd.models.xrd_data import XRDData

        d = XRDData(two_theta=np.linspace(20, 80, 601),
                    intensity=np.ones(601), wavelength=1.5406)
        out, errs = self._apply(d, None, (5.0, 10.0))
        assert out is None
        assert errs and "没有交集" in errs[0]

    def test_noop_when_params_match_data(self):
        """参数与数据一致时不该白白复制一份。"""
        from polyxrd.models.xrd_data import XRDData

        d = XRDData(two_theta=np.linspace(10, 80, 200),
                    intensity=np.ones(200), wavelength=1.5406)
        out, errs = self._apply(d, 1.5406, (10.0, 80.0))
        assert out is d
        assert not errs


# --------------------------------------------------------------------
# refine_structure: engine 真的走到引擎 (VM 层 spy 验证)
# --------------------------------------------------------------------

class _SpyVM:
    """借 MainViewModel.refine_structure 跑一遍, 记录最终传给引擎的实参。"""

    def __init__(self, data) -> None:
        import types

        from polyxrd.viewmodels.main_vm import MainViewModel

        self.current_data = data
        self.calls: list[dict] = []
        self.errors: list[str] = []
        self.statuses: list[str] = []
        # 复用真实实现 (含 2θ 裁剪/波长覆盖), 只替换掉 QObject 依赖
        self._apply_data_overrides = types.MethodType(
            MainViewModel._apply_data_overrides, self
        )

        vm = self

        class _Sig:
            def __init__(self, sink) -> None:
                self._sink = sink

            def emit(self, *a, **k) -> None:
                self._sink.append(a[0] if a else None)

        self.error_occurred = _Sig(self.errors)
        self.status_changed = _Sig(self.statuses)
        self.refinement_log = _Sig([])  # v0.12: CIF 匹配日志走这里

        # v0.12: refine_structure 现在会先做 CIF 匹配。测试桩里禁用真实
        # 库探测 (_db_ready=False → resolve 原样返回), 保持本组测试专注
        # "参数转发" 语义, 不依赖本机是否装了 COD 库。
        resolver = PhaseStructureResolver()
        resolver._db_ready = False
        self._cif_resolver = resolver

        class _PhaseVM:
            selected_phases = [object()]  # 非空即通过"必须选物相"检查
            matched_phases: list = []

        class _RefVM:
            def refine(self, data, phases, **kw):
                vm.calls.append({"data": data, "phases": phases, **kw})

        self._phase_vm = _PhaseVM()
        self._refinement_vm = _RefVM()


class TestRefineStructureForwarding:
    def _run(self, engine, **kw):
        from polyxrd.models.xrd_data import XRDData
        from polyxrd.viewmodels.main_vm import MainViewModel

        d = XRDData(two_theta=np.linspace(10, 80, 400),
                    intensity=np.ones(400), wavelength=1.5406)
        spy = _SpyVM(d)
        MainViewModel.refine_structure(spy, engine=engine, **kw)  # type: ignore[arg-type]
        return spy

    def test_engine_reaches_engine_layer(self):
        """向导里选的引擎必须原样传到 refinement_vm.refine(engine=...)。"""
        spy = self._run("gsas2")
        assert len(spy.calls) == 1
        assert spy.calls[0]["engine"] == "gsas2"
        assert not spy.errors

    def test_auto_engine_is_accepted(self):
        """auto 是验收要用的选项, 不能被当成未知值拒掉。"""
        spy = self._run("auto")
        assert spy.calls and spy.calls[0]["engine"] == "auto"

    def test_wavelength_and_window_land_on_data(self):
        """波长/2θ 窗口必须落到 data 上 (而不是飘在 kwargs 里被忽略)。"""
        spy = self._run("builtin", wavelength=1.7889,
                        two_theta_range=(20.0, 60.0))
        assert len(spy.calls) == 1
        d = spy.calls[0]["data"]
        assert abs(d.wavelength - 1.7889) < 1e-9
        assert d.two_theta[0] >= 20.0 - 1e-6
        assert d.two_theta[-1] <= 60.0 + 1e-6

    def test_aborts_before_engine_when_no_data(self):
        from polyxrd.viewmodels.main_vm import MainViewModel

        spy = _SpyVM(None)
        MainViewModel.refine_structure(spy, engine="gsas2")  # type: ignore[arg-type]
        assert spy.errors and "请先加载数据" in spy.errors[0]
        assert not spy.calls  # 不该调引擎


# ====================================================================
# get_params 仍返回正确字段
# ====================================================================

class TestGetParams:
    def test_get_params_returns_maud_when_selected(self, wizard):
        w, _ = wizard
        w._engine_combo.setCurrentText("maud")
        p = w.get_params()
        assert p["engine"] == "maud"
        assert p["strategy"] in ("sequential", "auto", "manual")
        assert isinstance(p["max_cycles"], int)
        assert p["max_cycles"] >= 1