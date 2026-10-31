"""
序贯（迭代式）多相鉴定测试 (v4.7.0)
==================================
三层验证:

* 服务层 :class:`SequentialPhaseIdentifier` —— 残差扣减 / 已解释判定 /
  低强度峰忽略 / 撤销与重放 (纯 numpy, 无 GUI);
* VM 层 —— 确认一相后是否**只把剩余峰**交给引擎、是否剔除已确认相、
  是否重置账本;
* 视图层 (offscreen) —— 按钮/状态条存在, 确认路径真的推进了序贯状态,
  且残差检索不会把已确认相从叠加里清掉。

关键不变量: 状态恒等于 ``(原始峰表, 相序列)`` 的纯函数 —— 每次变更都从
原始峰重算, 所以撤销后必须回到与"从未确认过该相"逐字相同的残差。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.services.sequential import (
    SequentialPhaseIdentifier,
    phase_key,
    residual_peak_list,
)
from polyxrd.viewmodels.phase_vm import PhaseViewModel


# ── 构造工具 ────────────────────────────────────────────────
def _obs(pairs) -> PeakList:
    return PeakList(peaks=[Peak(two_theta=float(t), intensity=float(i))
                          for t, i in pairs], source="test")


def _phase(name, refs, db_id=None, formula=None) -> Phase:
    return Phase(
        name=name,
        formula=formula or name,
        reference_peaks=[((1, 0, 0), float(tt), float(i)) for tt, i in refs],
        db_id=db_id,
    )


def _result(phase: Phase, score: float = 1.0) -> PhaseMatchResult:
    return PhaseMatchResult(phase=phase, score=score, matched_peaks=2,
                            total_peaks=2, method="fom")


# ── 服务层 ─────────────────────────────────────────────────
class TestResidualBookkeeping:
    def test_two_phase_chain_explains_everything(self):
        """确认 A 后残差只剩 B 的独立峰; 确认 B 后残差清空、覆盖率到 100%。"""
        obs = _obs([(20, 1000), (30, 600), (40, 400), (50, 300), (60, 5)])
        A = _phase("A", [(20, 100), (40, 40)], db_id=1)
        B = _phase("B", [(30, 100), (50, 50)], db_id=2)
        seq = SequentialPhaseIdentifier(obs)

        assert seq.n_residual_peaks == 4        # 60° 太弱, 不计
        assert seq.n_ignored == 1
        assert seq.covered_fraction == 0.0

        sel_a = seq.select(A)
        assert sel_a.explained == [0, 2]
        assert seq.residual_two_thetas == pytest.approx([30.0, 50.0])
        assert 0.55 < seq.covered_fraction < 0.65

        sel_b = seq.select(B)
        assert seq.n_residual_peaks == 0
        assert seq.covered_fraction == pytest.approx(1.0)
        assert sel_b.gain > 0.3                 # B 确实解释了新强度
        assert residual_peak_list(seq).peaks == []

    def test_first_phase_does_not_touch_second_phase_intensity(self):
        """A 只扣自己的配对峰, 其余峰强度原样传给下一轮检索。"""
        obs = _obs([(20, 1000), (40, 400)])
        A = _phase("A", [(20, 100)], db_id=1)
        seq = SequentialPhaseIdentifier(obs)
        seq.select(A)
        residual = residual_peak_list(seq)
        assert [p.two_theta for p in residual.peaks] == pytest.approx([40.0])
        assert residual.peaks[0].intensity == pytest.approx(400.0)
        assert residual.source == "residual"

    def test_partially_explained_peak_keeps_leftover(self):
        """只解释一部分的峰留在残差里, 强度是扣减后的剩余计数。

        A 的两条参考线按最小二乘拟合出 scale≈896.6: 20° 只被解释掉
        89.7%, 残差 103 counts 仍高于阈值 (5% × 1000) → 该峰不能被算作
        "已解释", 也就不能从残差集合里消失。
        """
        obs = _obs([(20, 1000), (40, 100)])
        A = _phase("A", [(20, 100), (40, 40)], db_id=1)
        seq = SequentialPhaseIdentifier(obs)
        seq.select(A)
        assert seq.n_residual_peaks >= 1
        leftover = {round(p.two_theta): p.intensity
                    for p in residual_peak_list(seq).peaks}
        assert leftover[20.0] == pytest.approx(103.4, abs=1.0)

    def test_weak_peaks_are_ignored_not_residual(self):
        """低于 1% 最强峰的线既不参与检索, 也不拖低覆盖率分母。"""
        obs = _obs([(20, 1000), (60, 5)])
        A = _phase("A", [(20, 100)], db_id=1)
        seq = SequentialPhaseIdentifier(obs)
        seq.select(A)
        assert seq.n_ignored == 1
        assert seq.n_residual_peaks == 0
        assert seq.covered_fraction == pytest.approx(1.0)

    def test_tolerance_bounds_matching(self):
        """峰位偏差超容差的参考线不参与配对。"""
        obs = _obs([(20.0, 1000)])
        near = _phase("near", [(20.25, 100)], db_id=1)
        far = _phase("far", [(20.60, 100)], db_id=2)
        seq = SequentialPhaseIdentifier(obs, tolerance=0.30)
        assert seq.select(near).matched == [(0, 0)]
        seq2 = SequentialPhaseIdentifier(obs, tolerance=0.30)
        assert seq2.select(far).matched == []
        assert seq2.covered_fraction == 0.0


class TestStateMachine:
    def test_repeated_select_is_idempotent(self):
        obs = _obs([(20, 1000)])
        A = _phase("A", [(20, 100)], db_id=1)
        seq = SequentialPhaseIdentifier(obs)
        first = seq.select(A)
        second = seq.select(A)
        assert first is second
        assert len(seq) == 1

    def test_undo_restores_previous_state_exactly(self):
        obs = _obs([(20, 1000), (30, 600), (40, 400)])
        A = _phase("A", [(20, 100)], db_id=1)
        B = _phase("B", [(30, 100)], db_id=2)
        seq = SequentialPhaseIdentifier(obs)
        seq.select(A)
        before = seq.residual_intensity
        seq.select(B)
        assert seq.residual_intensity[1] == pytest.approx(0.0)
        seq.undo()
        assert len(seq) == 1
        assert np.allclose(seq.residual_intensity, before)
        assert seq.n_residual_peaks == 2

    def test_remove_middle_phase_rebuilds_dependents(self):
        """中间相被移除后, 后续相的比例因子按剩余残差重算 (顺序无关移除)。"""
        obs = _obs([(20, 1000), (30, 600)])
        A = _phase("A", [(20, 100)], db_id=1)
        B = _phase("B", [(30, 100)], db_id=2)
        seq = SequentialPhaseIdentifier(obs)
        seq.select(A)
        seq.select(B)
        scale_b = seq.selections[1].scale
        assert seq.remove(A) is True
        assert len(seq) == 1
        # A 不再扣减 20° → B 只见 30°, 其 scale 仍是 600 (未受影响)
        assert seq.selections[0].scale == pytest.approx(scale_b)
        assert seq.n_residual_peaks == 1

    def test_clear_and_reset(self):
        obs = _obs([(20, 1000)])
        seq = SequentialPhaseIdentifier(obs)
        seq.select(_phase("A", [(20, 100)], db_id=1))
        seq.clear()
        assert len(seq) == 0 and seq.n_residual_peaks == 1
        seq.select(_phase("A", [(20, 100)], db_id=1))
        seq.reset(_obs([(20, 500), (30, 400)]))
        assert len(seq) == 0 and seq.n_peaks == 2

    def test_contains_uses_db_id(self):
        """同名同式但条目不同 → 不同相; 同条目重复出现 → 同一相。"""
        a1 = _phase("Q", [(20, 100)], db_id=101, formula="SiO2")
        a2 = _phase("Q", [(20, 100)], db_id=102, formula="SiO2")
        assert phase_key(a1) != phase_key(a2)
        seq = SequentialPhaseIdentifier(_obs([(20, 100)]))
        seq.select(a1)
        assert seq.contains(a1) is True
        assert seq.contains(a2) is False

    def test_invalid_parameters_rejected(self):
        obs = _obs([(20, 100)])
        with pytest.raises(ValueError):
            SequentialPhaseIdentifier(obs, explained_frac=1.5)
        with pytest.raises(ValueError):
            SequentialPhaseIdentifier(obs, tolerance=0.0)


# ── VM 层 ──────────────────────────────────────────────────
class TestViewModelSequence:
    def _vm(self):
        vm = PhaseViewModel()
        vm._peaks = _obs([(20, 1000), (30, 600), (40, 400)])
        return vm

    def test_confirm_only_searches_residual_peaks(self):
        vm = self._vm()
        A = _phase("A", [(20, 100)], db_id=1)
        B = _phase("B", [(30, 100)], db_id=2)
        calls = []

        def fake_identify(data, **kwargs):
            calls.append(kwargs)
            return [_result(A), _result(B)]

        vm._identify_with_source = fake_identify
        payloads = []
        vm.sequence_changed.connect(payloads.append)

        kept = vm.confirm_phase_sequence(object(), _result(A),
                                         tolerance=0.30, db_source="builtin")

        assert len(calls) == 1
        sent = calls[0]["peaks"]
        # 只把 A 解释不到的峰交下去 (20° 已解释)
        assert [p.two_theta for p in sent.peaks] == pytest.approx([30.0, 40.0])
        assert calls[0]["db_source"] == "builtin"
        # 已确认相从下一轮候选里剔除
        assert [r.phase.name for r in kept] == ["B"]
        # 已确认相留在勾选集合里 (谱图叠加要能持续看到)
        assert [p.name for p in vm.selected_phases] == ["A"]
        assert payloads[-1]["n_phases"] == 1
        assert payloads[-1]["active"] is True

    def test_duplicate_confirm_is_noop(self):
        vm = self._vm()
        A = _phase("A", [(20, 100)], db_id=1)
        vm._identify_with_source = lambda data, **kw: []
        vm.confirm_phase_sequence(object(), _result(A), tolerance=0.30)
        infos = []
        vm.info.connect(infos.append)
        again = vm.confirm_phase_sequence(object(), _result(A), tolerance=0.30)
        assert again is None
        assert len(vm.sequence) == 1
        assert infos and "已在已确认列表" in infos[-1]

    def test_confirm_with_no_residual_clears_candidates(self):
        vm = PhaseViewModel()
        vm._peaks = _obs([(20, 1000)])
        A = _phase("A", [(20, 100)], db_id=1)
        vm._identify_with_source = lambda data, **kw: pytest.fail(
            "无剩余峰时不该再检索")
        emitted = []
        vm.phase_identified.connect(emitted.append)
        infos = []
        vm.info.connect(infos.append)

        kept = vm.confirm_phase_sequence(object(), _result(A), tolerance=0.30)

        assert kept == []
        assert emitted[-1] == []
        assert infos and "没有剩余峰" in infos[-1]

    def test_undo_returns_to_full_pattern_search(self):
        vm = self._vm()
        A = _phase("A", [(20, 100)], db_id=1)
        vm._identify_with_source = lambda data, **kw: [_result(A)]
        vm.confirm_phase_sequence(object(), _result(A), tolerance=0.30)
        assert vm.sequence_active is True

        full_calls = []

        def fake_identify(data, **kwargs):
            full_calls.append(kwargs)
            return [_result(A)]

        vm._identify_with_source = fake_identify
        vm.undo_phase_sequence(object(), tolerance=0.30)

        # 撤到 0 相 → 走整谱检索 (identify_phases 内部会作废账本)
        assert vm.sequence_active is False
        assert full_calls, "撤到 0 相应走整谱检索"
        assert len(full_calls[0]["peaks"].peaks) == 3   # 原始全部峰

    def test_identify_phases_resets_sequence(self):
        vm = self._vm()
        A = _phase("A", [(20, 100)], db_id=1)
        vm._identify_with_source = lambda data, **kw: [_result(A)]
        vm.confirm_phase_sequence(object(), _result(A), tolerance=0.30)
        assert vm.sequence is not None
        # 新一轮整谱检索 = 新起点
        vm.identify_phases(object())
        assert vm.sequence is None

    def test_sequence_payload_inactive_shape(self):
        vm = PhaseViewModel()
        payload = vm.sequence_payload()
        assert payload["active"] is False
        assert payload["n_phases"] == 0


# ── 视图层 (offscreen) ─────────────────────────────────────
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestPhaseViewSequence:
    def _view(self, qapp):
        from polyxrd.viewmodels.main_vm import MainViewModel
        from polyxrd.views.phase_view import PhaseView
        vm = MainViewModel()
        return PhaseView(vm), vm

    def test_controls_exist_and_start_disabled(self, qapp):
        pv, _vm = self._view(qapp)
        assert pv._btn_confirm_next.text()
        assert pv._btn_confirm_next.isEnabled() is False
        assert pv._btn_undo_seq.isEnabled() is False
        assert pv._seq_label.isHidden() is True

    def test_sequence_signal_updates_status_label(self, qapp):
        pv, vm = self._view(qapp)
        A = _phase("A", [(20, 100)], db_id=1)
        seq = SequentialPhaseIdentifier(_obs([(20, 1000), (30, 600)]))
        seq.select(A)
        vm._phase_vm._sequence = seq
        vm._phase_vm.sequence_changed.emit(vm._phase_vm.sequence_payload())
        assert "1" in pv._seq_label.text()
        assert pv._btn_undo_seq.isEnabled() is True
        assert pv._seq_label.isHidden() is False

    def test_residual_refresh_keeps_confirmed_selection(self, qapp):
        """序贯进行中刷新候选列表, 不得清空已确认相的勾选 (谱图叠加不回退)。"""
        pv, vm = self._view(qapp)
        A = _phase("A", [(20, 100)], db_id=1)
        seq = SequentialPhaseIdentifier(_obs([(20, 1000), (30, 600)]))
        seq.select(A)
        vm._phase_vm._sequence = seq
        vm._phase_vm.update_selection(A, True)

        pv._on_phases_updated([_result(_phase("B", [(30, 100)], db_id=2))])

        assert [p.name for p in vm.selected_phases] == ["A"]
        assert pv._candidate_list.count() == 1
        assert pv._btn_confirm_next.isEnabled() is True

    def test_plain_identify_still_clears_selection(self, qapp):
        """非序贯 (普通检索) 仍按原行为清空勾选, 避免旧叠加残留。"""
        pv, vm = self._view(qapp)
        A = _phase("A", [(20, 100)], db_id=1)
        vm._phase_vm._sequence = None
        vm._phase_vm.update_selection(A, True)

        pv._on_phases_updated([_result(_phase("B", [(30, 100)], db_id=2))])

        assert vm.selected_phases == []

    def test_clear_selection_resets_sequence_too(self, qapp):
        """「清空选择」必须连带作废序贯账本, 否则状态条与叠加图会互相矛盾。"""
        pv, vm = self._view(qapp)
        A = _phase("A", [(20, 100)], db_id=1)
        seq = SequentialPhaseIdentifier(_obs([(20, 1000), (30, 600)]))
        seq.select(A)
        vm._phase_vm._sequence = seq
        vm._phase_vm.update_selection(A, True)
        vm._phase_vm.sequence_changed.emit(vm._phase_vm.sequence_payload())
        assert pv._btn_undo_seq.isEnabled() is True

        pv._on_clear_selection()

        assert vm._phase_vm.sequence is None
        assert vm.selected_phases == []
        assert pv._btn_undo_seq.isEnabled() is False
        assert pv._seq_label.isHidden() is True

    def test_clear_selection_resets_sequence_too(self, qapp):
        """「清空选择」必须连带作废序贯账本, 否则状态条与叠加图会互相矛盾。"""
        pv, vm = self._view(qapp)
        A = _phase("A", [(20, 100)], db_id=1)
        seq = SequentialPhaseIdentifier(_obs([(20, 1000), (30, 600)]))
        seq.select(A)
        vm._phase_vm._sequence = seq
        vm._phase_vm.update_selection(A, True)
        vm._phase_vm.sequence_changed.emit(vm._phase_vm.sequence_payload())
        assert pv._btn_undo_seq.isEnabled() is True

        pv._on_clear_selection()

        assert vm._phase_vm.sequence is None
        assert vm.selected_phases == []
        assert pv._btn_undo_seq.isEnabled() is False
        assert pv._seq_label.isHidden() is True
