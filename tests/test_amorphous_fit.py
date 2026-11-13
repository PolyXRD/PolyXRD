# -*- coding: utf-8 -*-
"""非晶宽隆全谱分解（``refinement/amorphous_fit.py``）的行为锁。

判据都建在**合成谱**上：面积比是已知量，所以"分解出来的 DoC 对不对"可以
直接比，不需要外部真值。
"""
import numpy as np
import pytest

from polyxrd.refinement.amorphous_fit import (
    HumpSpec,
    absolute_amorphous_from_standard,
    decompose,
    hump_columns,
)


def _gauss(x, c, fwhm, h=1.0):
    return h * np.exp(-4.0 * np.log(2.0) * ((x - c) / fwhm) ** 2)


def _synthetic(amorphous_frac=0.35, seed=0):
    """两"相"窄峰 + 一个已知面积比的宽隆。返回 (x, y, basis, 真值面积比)。"""
    x = np.linspace(10.0, 70.0, 2401)
    b1 = _gauss(x, 26.6, 0.18) + 0.35 * _gauss(x, 36.5, 0.20)
    b2 = _gauss(x, 21.9, 0.22) + 0.55 * _gauss(x, 50.1, 0.24)
    crystal = np.column_stack([b1, b2])
    hump = HumpSpec(center=22.0, fwhm=9.0)
    H = hump_columns(x, [hump])
    area_c = 1.0 * np.trapezoid(b1, x) + 0.8 * np.trapezoid(b2, x)
    area_h = amorphous_frac * area_c / (1.0 - amorphous_frac)
    y = crystal @ np.array([1.0, 0.8]) + H[:, 0] * area_h
    rng = np.random.default_rng(seed)
    y = y + 0.0015 * float(y.max()) * rng.normal(size=x.size)
    return x, y, crystal, 1.0 - amorphous_frac


def test_hump_columns_are_unit_area():
    x = np.linspace(10.0, 70.0, 3001)
    H = hump_columns(x, [HumpSpec(25.0, 8.0), HumpSpec(45.0, 12.0, eta=0.9)])
    assert H.shape == (x.size, 2)
    areas = [float(np.trapezoid(H[:, i], x)) for i in range(2)]
    assert areas == pytest.approx([1.0, 1.0], abs=1e-6)


def test_recovers_known_crystalline_fraction():
    """合成谱没有背景 → 传常数背底，把"背景自由度抢宽隆"这条排除掉。"""
    x, y, crystal, truth = _synthetic(0.35)
    out = decompose(x, y, crystal, bg_basis=np.ones((x.size, 1)), max_humps=2)
    assert out.humps, "合成谱里有 9° 宽的宽隆，必须被分解出来"
    assert out.doc_area == pytest.approx(truth, abs=0.03)
    assert out.humps[0].center == pytest.approx(22.0, abs=1.5)
    assert out.humps[0].fwhm == pytest.approx(9.0, abs=3.0)
    assert out.rwp_after < out.rwp_before


def test_pure_crystalline_adds_no_hump():
    """没有宽隆时不许凭空加一个 —— 否则 DoC 会被无端拉低。"""
    x = np.linspace(10.0, 70.0, 2401)
    b1 = _gauss(x, 26.6, 0.18) + 0.35 * _gauss(x, 36.5, 0.20)
    b2 = _gauss(x, 21.9, 0.22) + 0.55 * _gauss(x, 50.1, 0.24)
    crystal = np.column_stack([b1, b2])
    rng = np.random.default_rng(3)
    y = crystal @ np.array([1.0, 0.8]) + 0.0015 * 1.0 * rng.normal(size=x.size)
    out = decompose(x, y, crystal, bg_basis=np.ones((x.size, 1)), max_humps=2)
    assert out.humps == ()
    assert out.doc_area > 0.99
    assert out.amorphous_area_share < 0.01


def test_doc_sensitivity_is_reported_and_stable_on_clean_synthetic():
    """两套背景下的 DoC 必须都报出来；无背景的真值谱上二者应一致。"""
    x, y, crystal, _ = _synthetic(0.35)
    out = decompose(x, y, crystal, bg_basis=np.ones((x.size, 1)), max_humps=1)
    assert len(out.doc_sensitivity) == 2
    assert out.doc_spread == pytest.approx(
        max(out.doc_sensitivity) - min(out.doc_sensitivity))
    assert out.doc_spread < 0.05
    assert out.doc_reliable is True


def test_unstable_doc_is_flagged():
    """摆动超阈值 → doc_reliable=False（不能当测量值用）。"""
    import dataclasses

    x, y, crystal, _ = _synthetic(0.35)
    out = decompose(x, y, crystal, bg_basis=np.ones((x.size, 1)), max_humps=1)
    bad = dataclasses.replace(out, doc_spread=0.32)
    assert bad.doc_reliable is False
    assert bad.as_dict()["doc_reliable"] is False


def test_absolute_from_internal_standard():
    # 内标把相对 60/40 定标到绝对 45/30，剩 25% 归非晶
    amor, abs_c, notes = absolute_amorphous_from_standard([60.0, 40.0], 0.75)
    assert abs_c == pytest.approx([45.0, 30.0])
    assert amor == pytest.approx(25.0)
    assert not notes


def test_absolute_must_subtract_the_standard_itself():
    """``refine_with_internal_standard`` 的返回不含内标 → 必须单列扣除。

    合成掺标样实测（Si 45 / NaCl 25 / Al 15 / 非晶 15）：定标本身完全正确
    （45.33 / 24.99），但漏扣 15% 内标会把非晶报成 29.7%（+14.7 pp）。
    """
    amor, abs_c, notes = absolute_amorphous_from_standard(
        [45.33, 24.99], 1.0, standard_wt_pct=15.0)
    assert abs_c == pytest.approx([45.33, 24.99])
    assert amor == pytest.approx(100.0 - 70.32 - 15.0, abs=1e-9)
    assert 13.0 < amor < 15.5, f"真值 15%，实得 {amor:.2f}%"
    assert any("已扣除内标" in n for n in notes)


def test_two_usage_modes_agree():
    """两种口径必须给同一个非晶量 —— 含内标(乘 scale) vs 不含内标(单列扣)。

    数字取自合成掺标样的实跑输出（Si 53.13 / NaCl 29.29 / Al 17.58 相对，
    内标绝对 15%）。
    """
    k = 15.0 / 17.58
    a, abs_a, _ = absolute_amorphous_from_standard([53.13, 29.29, 17.58], k)
    b, abs_b, _ = absolute_amorphous_from_standard(
        [53.13 * k, 29.29 * k], 1.0, standard_wt_pct=15.0)
    assert a == pytest.approx(b, abs=1e-9)
    assert a == pytest.approx(100.0 - sum(abs_a), abs=1e-9)
    assert abs_b == pytest.approx(abs_a[:2], abs=1e-9)


def test_absolute_over_100_is_flagged():
    amor, _, notes = absolute_amorphous_from_standard([60.0, 40.0], 1.2)
    assert amor < 0
    assert any("超过 100%" in n for n in notes)


def test_absolute_negative_args_raise():
    with pytest.raises(ValueError):
        absolute_amorphous_from_standard([50.0], 1.0, standard_wt_pct=-1.0)
    with pytest.raises(ValueError):
        absolute_amorphous_from_standard([50.0], 1.0, unidentified_wt_pct=-2.0)


def test_one_envelope_is_not_split_into_two():
    """同一个包络不许被拆成两个 hump（中心过近要合并掉）。"""
    x, y, crystal, _ = _synthetic(0.35)
    out = decompose(x, y, crystal, bg_basis=np.ones((x.size, 1)), max_humps=3)
    assert len(out.humps) == 1
    assert out.humps[0].center == pytest.approx(22.0, abs=1.5)


def test_basis_shape_mismatch_raises():
    x = np.linspace(10.0, 70.0, 100)
    with pytest.raises(ValueError):
        decompose(x, np.ones(100), np.ones((50, 2)))
