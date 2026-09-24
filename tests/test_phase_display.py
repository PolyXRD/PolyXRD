"""
M21 物相显示服务测试 (Sprint 3 收尾/物相分析 v2)
===============================================
覆盖 phase_display.py 纯逻辑: 色板 / 双向归属 / 谱合成 / 残差。
"""
import numpy as np

from polyxrd.models.peak import Peak
from polyxrd.models.phase import Phase
from polyxrd.services.phase_display import (PHASE_PALETTE, COLOR_UNMATCHED,
                                            assign_peaks, combined_pattern,
                                            phase_color, residual,
                                            spectrum_from_refs, PeakAssignment)


def _phase(name, refs, elements=("A",)):
    return Phase(name=name, formula=name, elements=set(elements),
                 reference_peaks=refs)


class TestColor:
    def test_first_color(self):
        assert phase_color(0) == PHASE_PALETTE[0]

    def test_modulo_cycle(self):
        n = len(PHASE_PALETTE)
        for i in range(3 * n):
            assert phase_color(i) == PHASE_PALETTE[i % n]

    def test_negative_modulo(self):
        assert phase_color(-1) == PHASE_PALETTE[-1]


class TestAssignPeaks:
    """双向归属: 正向布尔表 + 反向残差峰。"""

    def _phases(self):
        # 相A 在 30/42, 相B 在 42/56
        A = _phase("A", [((1, 0, 0), 30.0, 100.0), ((1, 1, 0), 42.0, 50.0)])
        B = _phase("B", [((1, 0, 0), 42.0, 80.0), ((2, 0, 0), 56.0, 40.0)],
                   elements=("B",))
        return [A, B]

    def _exp(self, tts):
        return [Peak(two_theta=t, intensity=1000.0) for t in tts]

    def test_basic_assignment(self):
        A, B = self._phases()
        exp = self._exp([30.0, 42.0, 68.0])   # 68 未被解释
        assigns, hit = assign_peaks(exp, [A, B], tolerance=0.3)
        assert len(assigns) == 3
        # 30→A, 42→A(Δ0 先于 B 同样 Δ0 时取小相下标), 68→None
        assert assigns[0].phase_index == 0 and assigns[0].phase_name == "A"
        assert assigns[1].phase_index == 0
        assert assigns[2].phase_index is None and assigns[2].phase_name == ""
        # 布尔表: A 两条参考峰全命中; B 的 42 命中、56 未命中
        assert hit[0] == [True, True]
        assert hit[1] == [True, False]

    def test_empty_phases_all_unexplained(self):
        exp = self._exp([30.0, 42.0])
        assigns, hit = assign_peaks(exp, [], tolerance=0.3)
        assert hit == []
        assert all(a.phase_index is None for a in assigns)

    def test_empty_exp_peaks(self):
        A, B = self._phases()
        assigns, hit = assign_peaks([], [A, B], tolerance=0.3)
        assert assigns == []
        assert hit == [[False, False], [False, False]]

    def test_tolerance_boundary(self):
        A = _phase("A", [((0, 0, 1), 30.0, 100.0)])
        # Δ=0.299 ≤ tol 0.30 → 命中
        assigns, _ = assign_peaks(self._exp([30.299]), [A], tolerance=0.30)
        assert assigns[0].phase_index == 0
        # Δ=0.301 > tol 0.30 → 未解释 (浮点: 用 >0.30 若干保证不踩边界)
        assigns2, _ = assign_peaks(self._exp([30.301]), [A], tolerance=0.30)
        assert assigns2[0].phase_index is None

    def test_tie_prefers_smaller_phase_index(self):
        # A 在 30.0, B 也在 30.0, 实验峰 30.0 → 归属 A (小下标)
        A = _phase("A", [((1, 0, 0), 30.0, 100.0)])
        B = _phase("B", [((1, 0, 0), 30.0, 100.0)], elements=("B",))
        assigns, _ = assign_peaks(self._exp([30.0]), [A, B], tolerance=0.3)
        assert assigns[0].phase_index == 0

    def test_closer_ref_wins_over_other_phase(self):
        # A 30.0, B 30.1; 实验 30.02 → A (更近), 即使都 ≤tol
        A = _phase("A", [((1, 0, 0), 30.0, 100.0)])
        B = _phase("B", [((1, 0, 0), 30.1, 100.0)], elements=("B",))
        assigns, _ = assign_peaks(self._exp([30.02]), [A, B], tolerance=0.3)
        assert assigns[0].phase_index == 0
        # 实验 30.08 → B
        assigns2, _ = assign_peaks(self._exp([30.08]), [A, B], tolerance=0.3)
        assert assigns2[0].phase_index == 1

    def test_one_ref_can_hit_multiple_exp(self):
        A = _phase("A", [((0, 0, 1), 30.0, 100.0)])
        exp = self._exp([30.0, 30.05, 40.0])
        assigns, hit = assign_peaks(exp, [A], tolerance=0.3)
        # 两条近峰都归属 A; 布尔表这条参考峰命中
        assert assigns[0].phase_index == 0
        assert assigns[1].phase_index == 0
        assert assigns[2].phase_index is None
        assert hit == [[True]]


class TestSpectrum:
    def test_empty_returns_zero(self):
        x = np.linspace(20, 80, 600)
        y = spectrum_from_refs(x, [[]], [1.0], 0.15, 0.5, 1.0)
        assert np.all(y == 0)

    def test_single_phase_peak_position(self):
        x = np.arange(20, 60, 0.1)
        refs = [((1, 0, 0), 30.0, 100.0)]
        y = spectrum_from_refs(x, [refs], [1.0], 0.15, 0.5, 1.0)
        idx = int(np.argmax(y))
        assert abs(x[idx] - 30.0) <= 0.1

    def test_two_phases_additive(self):
        x = np.arange(20, 70, 0.1)
        A = _phase("A", [((1, 0, 0), 30.0, 100.0)])
        B = _phase("B", [((1, 0, 0), 45.0, 100.0)], elements=("B",))
        yA = spectrum_from_refs(x, [A.get_reference_peaks()], [1.0], 0.15, 0.5, 1.0)
        yB = spectrum_from_refs(x, [B.get_reference_peaks()], [1.0], 0.15, 0.5, 1.0)
        yAB = spectrum_from_refs(x, [A.get_reference_peaks(),
                                     B.get_reference_peaks()], [1.0, 1.0],
                                 0.15, 0.5, 1.0)
        assert np.allclose(yAB, yA + yB, atol=1e-9)

    def test_caglioti_path_runs(self):
        x = np.arange(20, 70, 0.1)
        refs = [((1, 0, 0), 30.0, 100.0)]
        y = spectrum_from_refs(x, [refs], [1.0], 0.15, 0.5, 1.0,
                               caglioti=(0.005, -0.001, 0.0225))
        assert np.any(y > 0)


class TestCombinedAndResidual:
    def test_combined_empty_phases_zero(self):
        x = np.arange(20, 60, 0.1)
        assert np.all(combined_pattern(x, []) == 0)

    def test_combined_scale_to_exp(self):
        x = np.arange(20, 60, 0.1)
        A = _phase("A", [((1, 0, 0), 30.0, 100.0)])
        y_exp = np.zeros_like(x); y_exp[150] = 500.0   # 人为峰
        y = combined_pattern(x, [A], y_exp=y_exp, scale_to_exp=True)
        assert np.isclose(np.max(y), 500.0, atol=1.0)

    def test_residual_basic(self):
        a = np.array([1.0, 2.0, 3.0]); b = np.array([0.5, 1.0, 2.0])
        assert np.allclose(residual(a, b), np.array([0.5, 1.0, 1.0]))

    def test_residual_mismatch_raises(self):
        import pytest
        with pytest.raises(ValueError):
            residual(np.ones(3), np.ones(4))
