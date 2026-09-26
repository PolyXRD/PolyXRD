"""v2.2 S09/S10/S11 回归测试: FoM 可观测性 + 强度尺度因子 + 陡降核
=====================================================
- 默认参数与 v2.1 行为完全一致 (默认关)
- s* 强线拟合对弱线离群对稳健
- scale='auto' 可见性: 微量相的"不该可见"弱线不计漏检
- 全部参考峰不可观测 → 不可判读 (999)
- scale_penalty 连续降权语义 (实测对微量相有害, 默认 0 = 关; 仅作展示/
  S14 标定备选 —— 端到端实证见 docs/基准报告-物相检索-v1.md 附录)
- S11 高斯陡降核: 位置偏差项由线性改 1-exp(-0.5·(2Δ/tol)²)
  (测试口径更新理由: 核函数变更后按新语义精确断言, 见手册 §S11)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.services.foam import compute_fom


def _refs(peaks):
    return [((0, 0, 0), float(tt), float(ii)) for tt, ii in peaks]


class TestDefaultsUnchanged:
    def test_default_matches_legacy_call(self):
        """不传新 kwargs 与显式传默认值 → 分数完全一致。"""
        obs_tt = [10.0, 20.0, 30.0]
        obs_i = [100.0, 50.0, 80.0]
        refs = _refs([(10.0, 100.0), (20.0, 60.0)])
        a = compute_fom(obs_tt, obs_i, refs, tol=0.2)
        b = compute_fom(obs_tt, obs_i, refs, tol=0.2,
                        obs_range=None, min_visible_frac=0.0,
                        scale=None, scale_penalty=0.0)
        assert a.score == pytest.approx(b.score)
        assert a.matched == b.matched and a.missed == b.missed

    def test_scale_fields_recorded_even_by_default(self):
        """默认调用也记录 s* / scale_rel (展示用, 不影响 score)。"""
        r = compute_fom([10.0, 20.0], [100.0, 50.0],
                        _refs([(10.0, 100.0), (20.0, 50.0)]), tol=0.2)
        assert r.scale == pytest.approx(1.0)
        assert r.scale_rel == pytest.approx(1.0)


class TestScaleStar:
    def test_strong_line_fit_robust_to_weak_outlier(self):
        """弱线参考峰被配到强实测峰 (离群) 不得拉爆 s*。

        场景: 全局最强实测峰 1000@20 属于别的相; 本相强线 100@10 (ratio 1),
        弱线 1@20 恰好吸到 1000@20 —— s* 必须由强线定为 1.0,
        scale_rel = 1.0·100/1000 = 0.1。
        """
        r = compute_fom([10.0, 20.0], [100.0, 1000.0],
                        _refs([(10.0, 100.0), (20.0, 1.0)]), tol=0.2,
                        scale="auto")
        assert r.scale == pytest.approx(1.0, rel=1e-6)
        assert r.scale_rel == pytest.approx(0.1)

    def test_scale_rel_equals_relative_height_of_strongest_line(self):
        """scale_rel = 该相最强线 (经 s* 缩放后) / 全局最强实测峰。"""
        # 自身就是全局最强: rel = 1
        r = compute_fom([10.0], [100.0],
                        _refs([(10.0, 100.0)]), tol=0.2, scale="auto")
        assert r.scale_rel == pytest.approx(1.0)
        # 全局最强 2000 属于别的相, 本相最强线只有 100 → rel = 0.05
        r2 = compute_fom([5.0, 10.0], [2000.0, 100.0],
                         _refs([(10.0, 100.0)]), tol=0.2, scale="auto")
        assert r2.scale_rel == pytest.approx(0.05)


class TestObservability:
    def test_out_of_range_refs_not_counted_as_missed(self):
        """扫描范围外的参考峰不计漏检 → bad 下降。"""
        obs_tt = [10.0]
        obs_i = [100.0]
        refs = _refs([(10.0, 100.0), (80.0, 50.0), (90.0, 40.0)])
        base = compute_fom(obs_tt, obs_i, refs, tol=0.2)
        rng = compute_fom(obs_tt, obs_i, refs, tol=0.2,
                          obs_range=(5.0, 20.0))
        assert rng.score < base.score
        assert rng.missed == 0 and rng.matched == 1

    def test_scale_visibility_excludes_unexplainable_weak_lines(self):
        """微量相场景: 强度上不可能出现的弱参考线不计漏检。

        全局最强实测峰 10000@5 属于别的相; 本相强线 100@10 → s*=1,
        scale_rel=0.01; 弱线 I_ref=1 → I_exp=1 < 1%·10000=100 → 不计漏检。
        """
        refs = _refs([(10.0, 100.0), (20.0, 1.0)])
        obs_tt = [5.0, 10.0]
        obs_i = [10000.0, 100.0]
        base = compute_fom(obs_tt, obs_i, refs, tol=0.2)
        vis = compute_fom(obs_tt, obs_i, refs, tol=0.2, scale="auto")
        assert base.missed == 1
        assert vis.missed == 0
        assert vis.score < base.score

    def test_min_visible_frac_conservative_fallback(self):
        """无 scale 时按 I_ref/Imax ≥ min_visible_frac 保守口径。"""
        refs = _refs([(10.0, 100.0), (20.0, 1.0)])
        base = compute_fom([10.0], [100.0], refs, tol=0.2)
        vis = compute_fom([10.0], [100.0], refs, tol=0.2,
                          min_visible_frac=0.05)
        assert base.missed == 1
        assert vis.missed == 0

    def test_all_refs_out_of_range_degenerates(self):
        """全部参考峰在扫描范围外 → 不可判读 (999)。"""
        r = compute_fom([10.0], [100.0],
                        _refs([(80.0, 100.0), (90.0, 50.0)]), tol=0.2,
                        obs_range=(5.0, 20.0))
        assert r.score == 999.0
        assert r.matched == 0


class TestScalePenalty:
    def test_penalty_monotonic_and_off_by_default(self):
        """scale_penalty>0 按连续函数降权; 默认 0 不影响分数。

        场景: rel=0.05 (2000 是别的相的主峰, 本相线只占 5%)。
        端到端实证连续惩罚对微量相有害 → 默认关闭, 仅作 S14 标定备选
        (docs/基准报告-物相检索-v1.md 附录)。
        """
        refs = _refs([(10.0, 100.0)])
        obs_tt = [5.0, 10.0]
        obs_i = [2000.0, 100.0]
        base = compute_fom(obs_tt, obs_i, refs, tol=0.2)
        pen = compute_fom(obs_tt, obs_i, refs, tol=0.2,
                          scale="auto", scale_penalty=0.5)
        assert pen.scale_rel == pytest.approx(0.05)
        assert pen.score > base.score
        assert pen.score == pytest.approx(
            base.score * (1 + 0.5 * (1 - 0.05)))


class TestSteepKernelS11:
    """S11 位置偏差高斯陡降核。

    单峰用例 matched=1 → intensity_score=0 (ic 需 matched>=2),
    score 即核函数值, 可精确断言。核: 1-exp(-0.5·(2Δ/tol)²)。
    """

    def test_half_window_kernel_value(self):
        """半窗偏差 (x=1): 核值 1-exp(-0.5)=0.3935 (线性核为 0.5)。"""
        refs = _refs([(10.0, 100.0)])
        r = compute_fom([10.1], [100.0], refs, tol=0.2)
        assert r.score == pytest.approx(1.0 - math.exp(-0.5), rel=1e-3)

    def test_edge_vs_half_discrimination_above_2x(self):
        """边缘 (x=2, 核值 0.865) vs 半窗 (0.393) 区分度 2.2× > 线性核的 2×。"""
        refs = _refs([(10.0, 100.0)])
        r_half = compute_fom([10.1], [100.0], refs, tol=0.2)
        r_edge = compute_fom([10.2], [100.0], refs, tol=0.2)
        assert r_edge.score / r_half.score > 2.0

    def test_near_zero_deviation_steep_drop(self):
        """近零偏差 (x=0.2): 核值 0.0198, 远小于线性核的 0.1 —— 陡降。"""
        refs = _refs([(10.0, 100.0)])
        r = compute_fom([10.02], [100.0], refs, tol=0.2)
        assert r.score == pytest.approx(1.0 - math.exp(-0.02), rel=1e-3)
        assert r.score < 0.1  # 线性核同偏差为 0.1

    def test_zero_bias_still_best(self):
        """零偏差位置项为 0 (分数取下限 1e-4), 任何偏差都更大。"""
        refs = _refs([(10.0, 100.0)])
        r0 = compute_fom([10.0], [100.0], refs, tol=0.2)
        r1 = compute_fom([10.05], [100.0], refs, tol=0.2)
        assert r0.score == pytest.approx(1e-4)
        assert r1.score > r0.score


class TestStrongMissS12:
    """S12 漏检分档: 强线 (I/Imax>=0.5) 被漏权重 x2, 弱线维持。"""

    def test_strong_miss_penalty_doubled(self):
        """强线被漏: 漏检项 2w 而非 w。

        refs: 强线 100@10 (w=1.0) + 弱线 10@20 (w=0.37), w_sum=1.37;
        实测只有 20 处弱峰 → strong miss, bad = 2.0/1.37 = 1.4599。
        """
        refs = _refs([(10.0, 100.0), (20.0, 10.0)])
        r = compute_fom([20.0], [10.0], refs, tol=0.2)
        assert r.missed == 1
        assert r.score == pytest.approx(2.0 / 1.37, rel=1e-3)

    def test_weak_miss_penalty_unchanged(self):
        """弱线被漏 (强线命中): 漏检项维持 w, 与旧口径一致。

        refs 同上; 实测只有 10 处强峰 → weak miss, bad = 0.37/1.37。
        """
        refs = _refs([(10.0, 100.0), (20.0, 10.0)])
        r = compute_fom([10.0], [100.0], refs, tol=0.2)
        assert r.missed == 1
        assert r.score == pytest.approx(0.37 / 1.37, rel=1e-3)

    def test_strong_matcher_ranks_above_weak_sniffer(self):
        """强线擦边命中 > 弱线全蹭到但强线缺席 (伪匹配被打下去)。"""
        refs = _refs([(10.0, 100.0), (20.0, 10.0)])
        # 相 A: 强线擦边命中 (x=2, 核值 0.865), 弱线漏 (w=0.37)
        ra = compute_fom([10.2], [100.0], refs, tol=0.2)
        # 相 B: 弱线精确命中, 强线缺席 (S12: 漏检 2.0)
        rb = compute_fom([20.0], [10.0], refs, tol=0.2)
        assert ra.score < rb.score

    def test_observability_filter_runs_before_split(self):
        """S09×S12 顺序: 被可观测性过滤掉的强线不进漏检分母 (不再 x2)。"""
        refs = _refs([(10.0, 100.0), (20.0, 10.0)])
        # 强线 10.0 在扫描范围外 → 只剩弱线口径: bad = 0/0.37 = 0
        r = compute_fom([20.0], [10.0], refs, tol=0.2,
                        obs_range=(15.0, 30.0))
        assert r.score == pytest.approx(0.0, abs=1e-3)
