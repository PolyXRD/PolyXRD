"""非晶/近非晶诊断测试 (P2-2)。

判定语义: **仅用于解释"匹配失败"**, 不用于抢先抑制匹配 (真实语料标定时
低对比度结晶谱 SILICA/NCM811 会被任何弥散启发式误判, 见模块 docstring)。
"""
from types import SimpleNamespace

import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.amorphous import (
    LEVEL_AMORPHOUS,
    LEVEL_CRYSTALLINE,
    LEVEL_PARTIAL,
    assess_amorphous,
)


def _grid(lo=10.0, hi=80.0, step=0.02):
    return np.arange(lo, hi + step, step)


def _gauss(x, center, amp, fwhm):
    sigma = fwhm / 2.3548
    return amp * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def test_sharp_peaks_judged_crystalline():
    """尖锐 Bragg 峰 + 平背景 → 结晶良好 (动态范围高)。"""
    x = _grid()
    y = np.full_like(x, 10.0)
    for c in (28.4, 47.3, 56.1, 69.1):
        y += _gauss(x, c, 1000.0, 0.15)
    info = assess_amorphous(XRDData(two_theta=x, intensity=y))
    assert info["level"] == LEVEL_CRYSTALLINE
    assert info["dynamic_range"] > 30.0
    assert info["sharp_content"] > 0.15


def test_broad_halo_judged_amorphous():
    """单一宽弥散包络 + 无匹配 → 近非晶。"""
    x = _grid()
    y = np.full_like(x, 5.0) + _gauss(x, 22.0, 100.0, 9.0)
    y += np.random.default_rng(0).normal(0, 1.5, x.size)  # 涟漪
    info = assess_amorphous(XRDData(two_theta=x, intensity=y))
    assert info["level"] == LEVEL_AMORPHOUS
    assert info["broad_hump"] == pytest.approx(22.0, abs=2.0)


def test_good_match_vetoes_amorphous():
    """同为弥散谱, 但若已获得可接受的结晶相匹配 → 不标非晶 (veto)。

    这是防止误判 SILICA / NCM811 这类低对比度结晶谱的关键护栏。
    """
    x = _grid()
    y = np.full_like(x, 5.0) + _gauss(x, 22.0, 100.0, 9.0)
    good = SimpleNamespace(confidence="良好匹配", score=0.30, matched_peaks=4)
    info = assess_amorphous(XRDData(two_theta=x, intensity=y), top_match=good)
    assert info["level"] != LEVEL_AMORPHOUS
    assert info["level"] == LEVEL_PARTIAL  # 弥散 + 有匹配 → 部分非晶


def test_weak_match_does_not_veto():
    """匹配质量差 ('可能不匹配') → 不 veto, 仍判近非晶。"""
    x = _grid()
    y = np.full_like(x, 5.0) + _gauss(x, 22.0, 100.0, 9.0)
    weak = SimpleNamespace(confidence="可能不匹配", score=0.9, matched_peaks=1)
    info = assess_amorphous(XRDData(two_theta=x, intensity=y), top_match=weak)
    assert info["level"] == LEVEL_AMORPHOUS


def test_zero_inflated_counts_not_amorphous():
    """计数型谱零值占多数时不得误判非晶 (Cu-007 实测回归)。

    全谱 median=0 会让"max/median"动态范围塌成 0 → 命中弥散阈值。
    本底必须取正值中位数。
    """
    x = _grid()
    y = np.zeros_like(x)
    rng = np.random.default_rng(1)
    # 大部分点为 0 (计数噪声), 少数点有高计数 → 真实结晶谱
    y = np.where(rng.random(x.size) < 0.8, 0.0, rng.integers(0, 3, x.size).astype(float))
    for c in (28.4, 47.3, 56.1, 69.1):
        y += _gauss(x, c, 1000.0, 0.15)
    info = assess_amorphous(XRDData(two_theta=x, intensity=y))
    assert info["dynamic_range"] > 30.0
    assert info["diffuse"] is False
    assert info["level"] == LEVEL_CRYSTALLINE


def test_diffuse_flag_exposed():
    """"diffuse" 是纯谱图形状判据, 不受匹配 veto 影响 (供下游统计用)。"""
    x = _grid()
    y = np.full_like(x, 5.0) + _gauss(x, 22.0, 100.0, 9.0)
    good = SimpleNamespace(confidence="良好匹配", score=0.30, matched_peaks=4)
    info = assess_amorphous(XRDData(two_theta=x, intensity=y), top_match=good)
    assert info["diffuse"] is True      # 谱图本身弥散
    assert info["level"] == LEVEL_PARTIAL  # 但被匹配 veto, 不标非晶


def test_tiny_data_safe():
    """数据点过少不应抛异常, 且不得据此判非晶。"""
    x = np.array([10.0, 10.5, 11.0])
    y = np.array([1.0, 5.0, 1.0])
    info = assess_amorphous(XRDData(two_theta=x, intensity=y))
    assert info["level"] == LEVEL_CRYSTALLINE
    assert info["diffuse"] is False
    assert "过少" in info["note"]
