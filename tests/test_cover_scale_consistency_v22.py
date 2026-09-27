"""v2.2 S14 回归测试: 覆盖度量 s* 尺度一致性 (coverage blanket 修复)
=====================================================================
- 退化输入 (无强度) → 旧布尔口径不变
- 尺度完全一致的真物相 → 覆盖不受损 (与 S02 口径一致)
- 密集弱线相"峰位全沾上但强度对不上" → 覆盖毯塌缩 (核心目标)
- B&B 联合覆盖: 一致性差的密集相不再压过真相相
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.phase import Phase
from polyxrd.services.phase_identifier import PhaseIdentifier


def _phase(name, refs):
    return Phase(name=name, formula=name, elements=set(),
                 reference_peaks=refs)


class TestCoverVectorScaleConsistency:
    TOL = 0.2

    def test_degenerate_no_intensity_boolean(self):
        """obs_int 全 0 → 布尔口径: 命中=1, 未命中=0。"""
        ph = _phase("P", [((1,), 10.0, 100.0), ((2,), 20.0, 50.0)])
        vec = PhaseIdentifier._phase_cover_vector(
            ph, [10.0, 15.0, 20.0], [0.0, 0.0, 0.0], self.TOL)
        assert vec.tolist() == [1.0, 0.0, 1.0]

    def test_consistent_scale_unchanged(self):
        """强度尺度一致的相: c≈1, 覆盖 = q·w (与 S02 相同)。"""
        # 观测 100/60/50, 参考 100/60/50 (同尺度) → s*=1, c=1
        ph = _phase("P", [((1,), 10.0, 100.0), ((2,), 20.0, 60.0),
                          ((3,), 30.0, 50.0)])
        obs_tt = [10.0, 20.0, 30.0]
        obs_i = [100.0, 60.0, 50.0]
        vec = PhaseIdentifier._phase_cover_vector(ph, obs_tt, obs_i, self.TOL)
        w = np.asarray(obs_i) / max(obs_i)
        assert vec == pytest.approx(w, abs=1e-9)

    def test_weak_line_blanket_collapses(self):
        """核心: 弱参考线配到强观测峰 → 该峰覆盖贡献被强压。

        密集相假设: 参考主强线 100 在别处, 另一条 I=2 的弱线恰好
        落在观测次强峰 (I=80) 上。S02 口径下该峰贡献 = q·0.8;
        S14 后 consist ≈ min(0.8, s*·0.02)/max(...) → 贡献塌缩。
        """
        ph = _phase("Dense", [((1,), 40.0, 100.0),   # 主线, 观测里没有
                              ((2,), 20.0, 2.0)])    # 弱线沾观测强峰
        obs_tt = [20.0]
        obs_i = [80.0]
        vec = PhaseIdentifier._phase_cover_vector(ph, obs_tt, obs_i, self.TOL)
        # s* 只能由这条命中对估: a=1.0, b=0.02 → s*=50, sb=1.0 → consist=1
        # (单对时 s* 恰好把弱线放大到观测强度 → 需要多峰才暴露失配)
        # 用双峰构造真正失配: 弱线+强线都命中, 但强度模式相反
        ph2 = _phase("Dense2", [((1,), 10.0, 100.0),  # 强线配到弱观测峰
                                ((2,), 20.0, 10.0)])  # 弱线配到强观测峰
        obs_tt2 = [10.0, 20.0]
        obs_i2 = [10.0, 100.0]
        vec2 = PhaseIdentifier._phase_cover_vector(ph2, obs_tt2, obs_i2, self.TOL)
        a = np.asarray(obs_i2) / 100.0            # [0.1, 1.0]
        b = np.asarray([100.0, 10.0]) / 100.0     # [1.0, 0.1]
        # s* ≈ Σ(w·a·b)/Σ(w·b²) = (0.1·0.1·1 + 1·1·0.1)/(0.1·1 + 1·0.01)
        #     = 0.11/0.11 = 1.0 → sb = [1.0, 0.1] vs a=[0.1,1.0] → consist≈0.1
        assert vec2[0] < 0.02, f"强线配弱峰贡献应塌缩, 实际 {vec2[0]}"
        assert vec2[1] < 0.15, f"弱线配强峰贡献应塌缩, 实际 {vec2[1]}"

    def test_unmatched_reference_only_no_crash(self):
        """参考峰全部不命中 → 零向量 (无命中对, s* 回退 1)。"""
        ph = _phase("Far", [((1,), 80.0, 100.0)])
        vec = PhaseIdentifier._phase_cover_vector(
            ph, [10.0, 20.0], [100.0, 50.0], self.TOL)
        assert vec.tolist() == [0.0, 0.0]


class TestBBScaleConsistency:
    def test_blanket_phase_loses_to_truth(self):
        """B&B: 尺度失配的密集相不再靠覆盖毯压过真相相。

        池: 真相 A (2 峰, 强度一致) vs 密集 B (同样命中这 2 峰但
        强度模式相反 + 一条独占弱命中)。S02 口径 B 靠 3 峰覆盖胜出;
        S14 后 B 的单峰贡献塌缩 → A 胜。
        """
        obs_tt = [10.0, 20.0, 30.0]
        obs_i = [50.0, 100.0, 10.0]
        # 真相 A: 命中 10/20, 强度一致 (a=[0.5,1.0], b=[0.5,1.0])
        a_cov = PhaseIdentifier._phase_cover_vector(
            _phase("A", [((1,), 10.0, 50.0), ((2,), 20.0, 100.0)]),
            obs_tt, obs_i, 0.2)
        # 密集 B: 反强度模式 + 独占 30 弱峰
        b_cov = PhaseIdentifier._phase_cover_vector(
            _phase("B", [((1,), 10.0, 100.0), ((2,), 20.0, 10.0),
                         ((3,), 30.0, 20.0)]),
            obs_tt, obs_i, 0.2)
        assert a_cov.sum() > b_cov.sum(), (
            f"真相覆盖应更高: A={a_cov.sum():.3f} B={b_cov.sum():.3f}")
        sel = PhaseIdentifier._branch_and_bound_select(
            [1, 1], [False, False], 3,
            size_targets=[1], cover_vectors=[a_cov, b_cov])
        assert sel == [0], f"应选真相 A, 实际 {sel}"
