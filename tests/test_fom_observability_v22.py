"""v2.2 S09/S10 回归测试: FoM 可观测性 + 强度尺度因子
=====================================================
- 默认参数与 v2.1 行为完全一致 (默认关)
- s* 强线拟合对弱线离群对稳健
- scale='auto' 可见性: 微量相的"不该可见"弱线不计漏检
- 全部参考峰不可观测 → 不可判读 (999)
- scale_penalty 连续降权语义 (实测对微量相有害, 默认 0 = 关; 仅作展示/
  S14 标定备选 —— 端到端实证见 docs/基准报告-物相检索-v1.md 附录)
"""
from __future__ import annotations

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
