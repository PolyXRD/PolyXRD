"""
忙碌提示 / 防重入闸门测试
==========================
背景: 峰检测、峰拟合、物相检索、Rietveld 精修都在主线程**同步**执行。执行期间
界面既不重绘也不响应点击, 用户以为卡死便再点一次 —— 这些点击不会消失, 而是积压
在消息队列里, 等任务结束、按钮刚被重新启用的一瞬间被一次性投递, 于是叠起第二轮
长任务, 表现为"程序未响应"乃至崩溃。

本模块只测闸门本身的行为约束 (可解耦的部分):
  * `enter` / `leave` 的重入语义与计数归零;
  * `busy` 上下文管理器在异常路径上仍然释放闸门;
  * 没有 QApplication 时闸门依然生效 (纯逻辑调用场景);
  * `progress_tick` / `pump` 不抛异常;
  * 各长耗时入口确实挂了闸门 (源码级契约, 防回归到"忘了包")。
窗口置顶/模态的视觉效果与"点击不再堆积"的体感靠人工验收。
"""
import os

# 必须在 import 任何 PySide6 模块之前设好, 否则 offscreen 平台插件不生效
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import inspect

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from polyxrd.views.widgets.busy_indicator import (
    BusyIndicator,
    busy,
    busy_guard,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _clean_gate():
    """每个用例前后都把闸门归零, 避免用例之间互相污染 (类是全局单例)。"""
    BusyIndicator.reset()
    yield
    BusyIndicator.reset()


# ------------------------------------------------------------------
# 基础闸门语义
# ------------------------------------------------------------------
class TestGateSemantics:
    def test_initial_state_not_busy(self):
        """未进入闸门时 is_busy() 为 False。"""
        assert BusyIndicator.is_busy() is False

    def test_enter_first_time_acquires(self, qapp):
        assert BusyIndicator.enter(None, "工作中") is True
        assert BusyIndicator.is_busy() is True

    def test_enter_second_time_rejected(self, qapp):
        """闸门已被占用时, 第二次 enter 必须被拒 —— 这正是"多点几次"要挡的。"""
        assert BusyIndicator.enter(None, "工作中") is True
        assert BusyIndicator.enter(None, "工作中") is False
        # 被拒的那次不该把计数叠上去, 否则一次 leave 放不干净
        BusyIndicator.leave()
        assert BusyIndicator.is_busy() is False

    def test_leave_without_enter_is_noop(self, qapp):
        """空 leave 不该抛异常, 也不该弄坏状态。"""
        BusyIndicator.leave()
        assert BusyIndicator.is_busy() is False

    def test_leave_twice_is_safe(self, qapp):
        assert BusyIndicator.enter(None, "工作中") is True
        BusyIndicator.leave()
        BusyIndicator.leave()
        assert BusyIndicator.is_busy() is False

    def test_reset_clears_state(self, qapp):
        BusyIndicator.enter(None, "工作中")
        BusyIndicator.reset()
        assert BusyIndicator.is_busy() is False


# ------------------------------------------------------------------
# 上下文管理器
# ------------------------------------------------------------------
class TestBusyContextManager:
    def test_yields_true_when_acquired(self, qapp):
        with busy(None, "工作中") as acquired:
            assert acquired is True
            assert BusyIndicator.is_busy() is True
        assert BusyIndicator.is_busy() is False

    def test_yields_false_when_already_busy(self, qapp):
        """嵌套/重入时内层拿到 False, 且不该在外层结束前撤掉闸门。"""
        with busy(None, "外层") as outer:
            assert outer is True
            with busy(None, "内层") as inner:
                assert inner is False
            # 内层没拿到闸门, 也应原样把闸门留给外层
            assert BusyIndicator.is_busy() is True
        assert BusyIndicator.is_busy() is False

    def test_released_on_exception(self, qapp):
        """长任务抛异常时闸门必须释放 —— 否则整个程序后面再也点不动。"""
        with pytest.raises(RuntimeError):
            with busy(None, "工作中"):
                raise RuntimeError("boom")
        assert BusyIndicator.is_busy() is False

    def test_released_on_exception_even_if_reentrant(self, qapp):
        with busy(None, "外层"):
            with pytest.raises(ValueError):
                with busy(None, "内层") as inner:
                    assert inner is False
                    raise ValueError("nested boom")
            assert BusyIndicator.is_busy() is True
        assert BusyIndicator.is_busy() is False


# ------------------------------------------------------------------
# 无 GUI 环境 (纯逻辑调用): 闸门仍然生效, 只是不弹窗
# ------------------------------------------------------------------
class TestWithoutApplication:
    def test_gate_works_without_qapp(self, monkeypatch):
        monkeypatch.setattr(
            QApplication, "instance", staticmethod(lambda: None)
        )
        assert BusyIndicator.enter(None, "工作中") is True
        assert BusyIndicator.is_busy() is True
        assert BusyIndicator.enter(None, "工作中") is False
        BusyIndicator.leave()
        assert BusyIndicator.is_busy() is False

    def test_pump_without_qapp_is_noop(self, monkeypatch):
        monkeypatch.setattr(
            QApplication, "instance", staticmethod(lambda: None)
        )
        BusyIndicator.pump()  # 不抛异常即通过
        BusyIndicator.progress_tick(1, 10)


# ------------------------------------------------------------------
# 进度回调与事件泵
# ------------------------------------------------------------------
class TestProgressAndPump:
    def test_pump_never_raises(self, qapp):
        with busy(None, "工作中"):
            BusyIndicator.pump()
            BusyIndicator.pump()

    def test_progress_tick_updates_text(self, qapp):
        """progress_tick 应把 "第 n / 共 m" 之类文案写进弹窗, 且正常泵事件。"""
        with busy(None, "工作中"):
            BusyIndicator.progress_tick(2, 10)
            dlg = BusyIndicator._dialog
            assert dlg is not None
            assert "2" in dlg._label.text()

    def test_progress_tick_zero_total_keeps_working_text(self, qapp):
        """total 为 0 表示总数未知 → 回落成通用文案, 不该出现 "1 / 0"。"""
        from polyxrd.i18n import tr

        with busy(None, "工作中"):
            BusyIndicator.progress_tick(0, 0)
            assert BusyIndicator._dialog._label.text() == tr("busy.working")

    def test_set_text_without_dialog_is_noop(self, qapp):
        BusyIndicator.set_text("随便写")  # 无弹窗时不该抛异常


# ------------------------------------------------------------------
# 装饰器
# ------------------------------------------------------------------
class TestBusyGuard:
    def test_decorator_blocks_reentry(self, qapp):
        calls = []

        class Host(QWidget):
            @busy_guard("busy.working")
            def run(self):
                calls.append(1)
                return "done"

        host = Host()
        assert host.run() == "done"
        assert calls == [1]

    def test_decorator_returns_none_when_busy(self, qapp):
        calls = []

        class Host(QWidget):
            @busy_guard("busy.working")
            def run(self):
                calls.append(1)

        host = Host()
        with busy(None, "外层"):
            assert host.run() is None  # 静默忽略: 不弹错误框
        assert calls == []

    def test_decorator_releases_on_exception(self, qapp):
        class Host(QWidget):
            @busy_guard("busy.working")
            def run(self):
                raise RuntimeError("boom")

        host = Host()
        with pytest.raises(RuntimeError):
            host.run()
        assert BusyIndicator.is_busy() is False

    def test_decorator_custom_text_getter(self, qapp):
        captured = {}

        class Host(QWidget):
            @busy_guard("busy.working", text_getter=lambda self, flag: f"标志={flag}")
            def run(self, flag: bool):
                captured["text"] = BusyIndicator._dialog._label.text()

        Host().run(True)
        assert captured["text"] == "标志=True"


# ------------------------------------------------------------------
# 入口挂载契约 (源码级, 防回归到"新写了长任务却忘了包闸门")
# ------------------------------------------------------------------
class TestEntryPointsWired:
    """各长耗时入口的函数体里必须出现 busy(...)。

    只查 `busy` 而不是行为: 这些槽函数依赖完整 VM/DB, 端到端跑不动;
    但"忘了包闸门"这个回归是最容易发生的, 源码级断言足够挡住。
    """

    @staticmethod
    def _src(func) -> str:
        return inspect.getsource(func)

    @pytest.mark.parametrize(
        "module_name, cls_name, method",
        [
            ("polyxrd.views.data_view", "DataView", "_on_find_peaks"),
            ("polyxrd.views.data_view", "DataView", "_on_fit_peaks"),
            ("polyxrd.views.phase_view", "PhaseView", "_on_profile_fitting"),
            ("polyxrd.views.phase_view", "PhaseView", "_on_traditional_identify"),
            ("polyxrd.views.phase_view", "PhaseView", "_on_quick_identify"),
            ("polyxrd.views.refinement_view", "RefinementView", "_on_refine"),
            (
                "polyxrd.views.refinement_wizard",
                "RefinementWizard",
                "_on_start_refine",
            ),
        ],
    )
    def test_method_is_guarded(self, module_name, cls_name, method):
        import importlib

        mod = importlib.import_module(module_name)
        cls = getattr(mod, cls_name)
        src = self._src(getattr(cls, method))
        assert "busy(" in src, f"{cls_name}.{method} 缺少忙碌闸门"

    @pytest.mark.parametrize(
        "method",
        [
            "_on_find_peaks",
            "_on_identify",
            "_on_profile_fitting",
            "_on_refine",
            "_on_refine_wizard",
            "_on_quick_refine",
        ],
    )
    def test_main_window_method_is_guarded(self, method):
        from polyxrd.views.main_window import MainWindow

        src = self._src(getattr(MainWindow, method))
        assert "busy(" in src, f"MainWindow.{method} 缺少忙碌闸门"


# ------------------------------------------------------------------
# 精修引擎回吐进度
# ------------------------------------------------------------------
class TestRefinerProgressCallback:
    """`_refine_builtin` 必须把轮次回吐给 progress_cb, 否则弹窗一直停在首句文案。"""

    def _data(self):
        import numpy as np

        from polyxrd.models.xrd_data import XRDData

        two_theta = np.linspace(20, 100, 1200)
        intensity = np.zeros_like(two_theta)
        for center, amp, sigma in [
            (28.44, 800, 0.12),
            (47.30, 600, 0.15),
            (56.11, 400, 0.12),
        ]:
            intensity += amp * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)
        rng = np.random.default_rng(1234)
        intensity = np.maximum(intensity + rng.normal(0, 3, len(two_theta)), 0)
        return XRDData(two_theta=two_theta, intensity=intensity)

    def _phase(self):
        from polyxrd.models.phase import LatticeParams, Phase

        return Phase(
            name="Test Phase",
            formula="Si",
            lattice=LatticeParams(
                a=5.431, b=5.431, c=5.431,
                alpha=90.0, beta=90.0, gamma=90.0,
            ),
            weight_fraction=100.0,
            reference_peaks=[
                ((1, 1, 1), 28.44, 800),
                ((2, 2, 0), 47.30, 600),
                ((3, 1, 1), 56.11, 400),
            ],
        )

    def test_progress_callback_invoked(self):
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        ticks = []
        refiner = RietveldRefiner()
        refiner.refine(
            self._data(),
            [self._phase()],
            engine="builtin",
            max_cycles=2,
            progress_cb=lambda done, total: ticks.append((done, total)),
        )
        assert ticks, "精修引擎没有调用 progress_cb"
        # done 单调不减; total 为正 (弹窗据此显示"第 n / 共 m")
        assert all(t > 0 for _, t in ticks)
        assert [d for d, _ in ticks] == sorted(d for d, _ in ticks)

    def test_progress_callback_exception_does_not_break_refine(self):
        """回调内部炸掉不该影响精修本身 (回调只是 UI 装饰)。"""
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        def boom(done, total):
            raise RuntimeError("callback boom")

        refiner = RietveldRefiner()
        result = refiner.refine(
            self._data(),
            [self._phase()],
            engine="builtin",
            max_cycles=2,
            progress_cb=boom,
        )
        assert result.phases and result.wR > 0
