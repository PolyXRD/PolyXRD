"""
v0.12.0 精修过程日志 + 精修向导方式默认勾选 测试
================================================
覆盖:
- ``RietveldRefiner.make_logger``: 无回调静默、回调异常被吞
- 内置引擎实跑时逐行回吐过程数据 (start/data/phase/bg/init/start N/multistart/
  polish/result/done)
- ``RefinementViewModel.refinement_log`` 信号 + ``MainViewModel`` 转发
- ``RefinementView``: 复选框默认勾选、勾选时锁参数、日志面板收到过程行
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


@pytest.fixture(scope="module")
def qapp():
    from polyxrd.i18n import I18nManager, Language

    app = QApplication.instance() or QApplication([])
    try:
        I18nManager().set_language(Language.ZH_CN)
    except Exception:  # noqa: BLE001
        pass
    yield app


def _data(n=1500):
    x = np.linspace(10.0, 80.0, n)
    rng = np.random.RandomState(1)

    def g(c, w, a):
        return a * np.exp(-0.5 * ((x - c) / w) ** 2)

    y = (g(20.1, 0.08, 1000) + g(32.5, 0.09, 480) + g(45.9, 0.10, 320)
         + g(26.6, 0.08, 600) + g(38.2, 0.09, 300) + 12.0 + 1.5 * rng.rand(n))
    return XRDData(two_theta=x, intensity=y, wavelength=1.54056)


def _phases():
    p1 = Phase(name="A", formula="AO2", lattice=LatticeParams(a=4.9, b=4.9, c=4.9),
               reference_peaks=[((1, 0, 1), 20.1, 100),
                               ((1, 1, 0), 32.5, 48),
                               ((2, 0, 0), 45.9, 32)])
    p2 = Phase(name="B", formula="B2O3", lattice=LatticeParams(a=5.4, b=5.4, c=5.4),
               reference_peaks=[((1, 0, 0), 26.6, 100),
                               ((1, 1, 0), 38.2, 50),
                               ((1, 1, 1), 52.4, 30)])
    return [p1, p2]


# ----------------------------------------------------------------------
# make_logger
# ----------------------------------------------------------------------

def test_make_logger_silent_without_callback():
    log = RietveldRefiner.make_logger({})
    log("noop")          # 不应抛异常
    log(None)            # 容错: 非字符串也行


def test_make_logger_swallows_callback_errors():
    def boom(_msg):
        raise RuntimeError("日志渲染炸了")

    log = RietveldRefiner.make_logger({"log_cb": boom})
    log("x")             # 回调异常必须被吞掉


# ----------------------------------------------------------------------
# 引擎过程日志
# ----------------------------------------------------------------------

def test_builtin_engine_streams_process_log():
    lines: list[str] = []
    res = RietveldRefiner().refine(
        _data(), _phases(), strategy="sequential", engine="builtin",
        max_cycles=20, peak_shape="pseudo-voigt", fwhm=0.15,
        bg_method="median", zero_shift=0.0, log_cb=lines.append,
    )
    joined = "\n".join(lines)
    # 起点信息
    assert "[start] engine=builtin" in joined
    assert "[data] n=" in joined
    assert "[phase] 2 phase(s): A, B" in joined
    # 过程数据
    assert any("[start 1/" in l for l in lines), lines
    assert any("wR=" in l and "nfev=" in l for l in lines), lines
    assert any("[multistart]" in l for l in lines), lines
    assert any("[polish]" in l for l in lines), lines
    assert any("[result] Rwp=" in l for l in lines), lines
    assert "[done]" in joined
    # 至少要有 8 行过程输出, 保证"跑码"观感
    assert len(lines) >= 8, lines
    assert res.wR > 0


def test_log_absent_when_no_callback():
    """不传 log_cb 时完全静默 (旧行为不变)。"""
    res = RietveldRefiner().refine(
        _data(800), _phases(), strategy="sequential", engine="builtin",
        max_cycles=20, peak_shape="pseudo-voigt", fwhm=0.15,
        bg_method="median", zero_shift=0.0,
    )
    assert res.wR > 0


def test_fallback_logs_warning():
    """engine=gsas2 但环境不可用 → 日志里应出现回退说明, 而不是静默。"""
    lines: list[str] = []
    RietveldRefiner().refine(
        _data(800), _phases(), strategy="sequential", engine="gsas2",
        max_cycles=10, peak_shape="pseudo-voigt", fwhm=0.15,
        bg_method="median", zero_shift=0.0, log_cb=lines.append,
    )
    joined = "\n".join(lines)
    assert "[done]" in joined
    # 要么 gsas2 跑通, 要么留下明确的回退痕迹
    assert "[gsas2]" in joined or "[warn]" in joined, joined


# ----------------------------------------------------------------------
# ViewModel 信号
# ----------------------------------------------------------------------

def test_refinement_vm_emits_log_signal(qapp):
    from polyxrd.viewmodels.refinement_vm import RefinementViewModel

    vm = RefinementViewModel()
    got: list[str] = []
    vm.refinement_log.connect(got.append)
    vm.refine(_data(700), _phases(), strategy="sequential", engine="builtin",
              max_cycles=10, peak_shape="pseudo-voigt", fwhm=0.15,
              bg_method="median", zero_shift=0.0)
    assert got, "refinement_log 没有发出任何行"
    assert any("[done]" in l for l in got), got


def test_main_vm_forwards_log(qapp):
    from polyxrd.viewmodels.main_vm import MainViewModel

    vm = MainViewModel()
    got: list[str] = []
    vm.refinement_log.connect(got.append)
    vm._data_vm._raw_data = _data(700)
    vm._phase_vm._selected_phases = _phases()
    vm.refine_structure(strategy="sequential", engine="builtin", max_cycles=10,
                        peak_shape="pseudo-voigt", fwhm=0.15,
                        bg_method="median", zero_shift=0.0)
    assert any("[start] engine=builtin" in l for l in got), got


# ----------------------------------------------------------------------
# RefinementView
# ----------------------------------------------------------------------

def test_refinement_view_wizard_default_and_log_panel(qapp):
    from polyxrd.viewmodels.main_vm import MainViewModel
    from polyxrd.views.refinement_view import RefinementView

    vm = MainViewModel()
    view = RefinementView(vm)

    # 1) 默认勾选"按精修向导的方式"
    assert view._chk_wizard.isChecked() is True
    assert view.is_wizard_style() is True
    # 勾选状态下手动参数控件被向导预设接管 (置灰)
    assert view._engine_combo.isEnabled() is False
    assert view._max_cycles.isEnabled() is False
    # 预设值来自内置精修模板 (与精修向导同源)
    preset = view._wizard_params()
    assert view._strategy_combo.currentText() == preset["strategy"]
    assert view._max_cycles.value() == preset["max_cycles"]
    assert view._bg_combo.currentText() == preset["bg_method"]

    # 2) 取消勾选 → 手动可调
    view._chk_wizard.setChecked(False)
    assert view.is_wizard_style() is False
    assert view._engine_combo.isEnabled() is True

    # 3) 日志面板存在且能收到过程行
    vm._data_vm._raw_data = _data(800)
    vm._phase_vm._selected_phases = _phases()
    vm.refine_structure(strategy="sequential", engine="builtin", max_cycles=10,
                        peak_shape="pseudo-voigt", fwhm=0.15,
                        bg_method="median", zero_shift=0.0)
    text = view._log_view.toPlainText()
    assert "[start 1/" in text, text
    assert "[done]" in text, text
    assert view._label_rwp.text() != "--"


def test_refinement_view_log_clear(qapp):
    from polyxrd.viewmodels.main_vm import MainViewModel
    from polyxrd.views.refinement_view import RefinementView

    view = RefinementView(MainViewModel())
    view._append_log("hello")
    assert "hello" in view._log_view.toPlainText()
    view._on_clear_log()
    assert view._log_view.toPlainText() == ""
