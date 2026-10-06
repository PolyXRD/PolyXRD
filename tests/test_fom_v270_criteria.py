"""v2.7.0 C-1: FoM 判据解耦 (峰位项 / 漏检项独立加权) + 判据可观测性。

红线: **默认参数下必须与 v2.6.0 行为完全一致** (_FOM_MISS_WEIGHT = 1.0),
解耦只是把 bad 拆成可独立标定的两项, 不改变数值。
"""
from __future__ import annotations

import math

import pytest

from polyxrd.models.fom import FoMResult
from polyxrd.services import foam


def _run(refs, obs_tt, obs_i, **kw):
    """refs 用 (2θ, I) 二元组书写; compute_fom 实际要 (label, 2θ, I) 三元组。"""
    refs3 = [(None, float(tt), float(i)) for tt, i in refs]
    return foam.compute_fom(obs_tt, obs_i, refs3, **kw)


# ── 1. 默认值恒定: 解耦不得改变 v2.6.0 数值 ──────────────────
def test_default_miss_weight_is_one():
    assert foam._FOM_MISS_WEIGHT == 1.0


def test_spec_weight_locked_to_tuned_value():
    """0.50 是 13 试样消融实测最优点, 锁定以防被无意改回。

    0.30 = v2.6.0 旧值 (B top10 44/49); 0.55 起组合相级退化到 44/49。
    """
    assert foam._FOM_SPEC_WEIGHT == 0.50


def test_spec_weight_actually_scales_score(monkeypatch):
    """特异性权重必须真的影响 score (否则调参是空转)"""
    refs = [(10.0, 100.0)]
    obs = ([10.0, 30.0], [100.0, 60.0])   # 30° 那条无参考峰 → 未解释
    monkeypatch.setattr(foam, "_FOM_SPEC_WEIGHT", 0.30)
    lo = _run(refs, *obs, tol=0.15, min_visible_frac=0.0).score
    monkeypatch.setattr(foam, "_FOM_SPEC_WEIGHT", 0.50)
    hi = _run(refs, *obs, tol=0.15, min_visible_frac=0.0).score
    assert hi > lo    # 权重越大 → 未解释的惩罚越重 → 分越差


def test_bad_equals_pos_plus_miss_at_default():
    """position_penalty == position_dev + 1.0 * miss_penalty (v2.6.0 口径)"""
    r = _run([(10.0, 100.0), (20.0, 50.0), (30.0, 20.0), (40.0, 80.0)],
             [10.0, 20.0, 30.0], [100.0, 50.0, 20.0],
             tol=0.15, min_visible_frac=0.0)
    assert r.position_penalty == pytest.approx(
        r.position_dev + 1.0 * r.miss_penalty, abs=1e-12)


def test_decoupling_reproduces_v26_numbers():
    """手算核对: 3 命中 + 1 条强线漏检。

    w = 0.3 + 0.7*I/Imax, Imax=100 → [1.0, 0.65, 0.44, 0.86]; w_sum=2.95
    命中偏差 0 → bad_pos = 0
    漏检 (40,80): I/Imax=0.8 ≥ 0.5 → 强线 ×2 → 1.72 → bad_miss = 1.72/2.95
    """
    r = _run([(10.0, 100.0), (20.0, 50.0), (30.0, 20.0), (40.0, 80.0)],
             [10.0, 20.0, 30.0], [100.0, 50.0, 20.0],
             tol=0.15, min_visible_frac=0.0)
    assert r.matched == 3 and r.missed == 1
    assert r.position_dev == pytest.approx(0.0, abs=1e-9)
    assert r.miss_penalty == pytest.approx(1.72 / 2.95, abs=1e-9)
    assert r.position_penalty == pytest.approx(1.72 / 2.95, abs=1e-9)
    # 强度余弦=1 (完全成比例) → score = bad * (1 - 0.20)
    assert r.intensity_score == pytest.approx(1.0, abs=1e-9)
    assert r.score == pytest.approx(1.72 / 2.95 * 0.8, abs=1e-9)


# ── 2. 漏检权重生效且单调 ────────────────────────────────────
def test_lower_miss_weight_reduces_score(monkeypatch):
    refs = [(10.0, 100.0), (20.0, 50.0), (30.0, 20.0), (40.0, 80.0)]
    obs = ([10.0, 20.0, 30.0], [100.0, 50.0, 20.0])
    base = _run(refs, *obs, tol=0.15, min_visible_frac=0.0)

    scores = {}
    for w in (1.0, 0.8, 0.6, 0.4):
        monkeypatch.setattr(foam, "_FOM_MISS_WEIGHT", w)
        scores[w] = _run(refs, *obs, tol=0.15,
                         min_visible_frac=0.0).score
    assert scores[1.0] == pytest.approx(base.score, abs=1e-12)
    # 漏检惩罚越轻 → 分越低 (越好); 且严格单调
    assert scores[1.0] > scores[0.8] > scores[0.6] > scores[0.4]


def test_miss_weight_zero_removes_only_miss_term(monkeypatch):
    """权重 0 → 只剩峰位项 (漏检项归零, 但峰位项不受影响)"""
    refs = [(10.0, 100.0), (20.0, 50.0), (30.0, 20.0), (40.0, 80.0)]
    obs = ([10.0, 20.0, 30.0], [100.0, 50.0, 20.0])
    monkeypatch.setattr(foam, "_FOM_MISS_WEIGHT", 0.0)
    r = _run(refs, *obs, tol=0.15, min_visible_frac=0.0)
    assert r.miss_penalty > 0.0            # 分项仍如实上报
    assert r.position_penalty == pytest.approx(r.position_dev, abs=1e-12)


# ── 3. 峰位项不受漏检权重影响 (两项真正解耦) ──────────────────
def test_position_dev_independent_of_miss_weight(monkeypatch):
    refs = [(10.0, 100.0), (20.05, 50.0), (30.0, 20.0), (40.0, 80.0)]
    obs = ([10.0, 20.0, 30.0], [100.0, 50.0, 20.0])
    devs = set()
    for w in (1.0, 0.5, 0.0):
        monkeypatch.setattr(foam, "_FOM_MISS_WEIGHT", w)
        devs.add(round(_run(refs, *obs, tol=0.15,
                            min_visible_frac=0.0).position_dev, 12))
    assert len(devs) == 1
    assert devs.pop() > 0.0     # 20.05 vs 20.0 → 确有位置偏差


# ── 4. 可观测性: 三个分项都如实上报 ───────────────────────────
def test_criteria_fields_populated():
    r = _run([(10.0, 100.0), (20.0, 50.0), (40.0, 80.0)],
             [10.0, 20.0, 30.0], [100.0, 50.0, 20.0],
             tol=0.15, min_visible_frac=0.0)
    assert 0.0 <= r.position_dev <= 1.0
    assert r.miss_penalty > 0.0
    # 30° 的实验峰没有参考峰对应 → 未解释强度比 > 0
    assert r.spec_penalty > 0.0


def test_spec_penalty_matches_intensity_weighted_unexplained():
    """spec_penalty = 未解释实验峰强度 / 总实验峰强度 (强度加权口径)"""
    r = _run([(10.0, 100.0)], [10.0, 30.0], [100.0, 60.0],
             tol=0.15, min_visible_frac=0.0)
    assert r.spec_penalty == pytest.approx(60.0 / 160.0, abs=1e-9)


# ── 5. FoMResult 序列化往返含新字段 ───────────────────────────
def test_fom_result_roundtrip_includes_v270_fields():
    r = FoMResult(score=0.5, matched=3, missed=1, position_penalty=0.4,
                  position_dev=0.1, miss_penalty=0.3, spec_penalty=0.25)
    d = r.to_dict()
    assert d["position_dev"] == 0.1
    assert d["miss_penalty"] == 0.3
    assert d["spec_penalty"] == 0.25
    back = FoMResult.from_dict(d)
    assert back.position_dev == 0.1
    assert back.miss_penalty == 0.3
    assert back.spec_penalty == 0.25


def test_fom_result_backward_compatible_defaults():
    """旧调用点不传新字段时不得炸, 且默认 0"""
    r = FoMResult(score=0.5)
    assert r.position_dev == 0.0
    assert r.miss_penalty == 0.0
    assert r.spec_penalty == 0.0
    assert FoMResult.from_dict({"score": 0.5}).position_dev == 0.0


# ── 6. 常量已提升为模块级 (可消融/可标定) ─────────────────────
def test_inline_magic_numbers_are_module_constants():
    assert foam._FOM_SCALE_STRONG_FRAC == 0.2
    assert foam._FOM_VISIBLE_INT_FRAC == 0.01
    assert foam._FOM_STRONG_MISS_FRAC == 0.5
    assert foam._FOM_STRONG_MISS_MULT == 2.0


def test_strong_miss_mult_effective():
    """强线 (I/Imax ≥ 0.5) 漏检代价 ×2"""
    weak = _run([(10.0, 100.0), (20.0, 50.0), (40.0, 10.0)],
                [10.0, 20.0], [100.0, 50.0],
                tol=0.15, min_visible_frac=0.0)
    strong = _run([(10.0, 100.0), (20.0, 50.0), (40.0, 90.0)],
                  [10.0, 20.0], [100.0, 50.0],
                  tol=0.15, min_visible_frac=0.0)
    # 两条漏检线强度不同: 90/100 → 强线 ×2; 10/100 → 弱线 ×1
    assert strong.miss_penalty > weak.miss_penalty


def test_no_nan_when_all_refs_matched():
    r = _run([(10.0, 100.0), (20.0, 50.0)], [10.0, 20.0], [100.0, 50.0],
             tol=0.15, min_visible_frac=0.0)
    assert math.isfinite(r.score)
    assert r.position_dev == pytest.approx(0.0, abs=1e-12)
    assert r.miss_penalty == pytest.approx(0.0, abs=1e-12)
