"""v2.1-D: 真实 Bragg R (回归测试)
==================================
Bragg R = Σ_hkl |I_obs,hkl − I_calc,hkl| / Σ I_obs,hkl × 100

验收口径 (docs/后续计划与已知问题-v2.1.md): 合成数据上 Bragg R 与解析值一致。
I_calc 口径 = scale × weight × I_ref (谱合成面积归一剖面 → 峰积分强度 = 振幅);
I_obs 用 Le Bail 式坐标 LS 提取。分离峰 + 已知强度扰动 → 解析值可算。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

FWHM = 0.15
ETA = 0.5


def _pv(d, amp_scale):
    """面积归一 pseudo-Voigt 值 × amp_scale (与谱合成同口径)。"""
    s = FWHM / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    g = np.exp(-0.5 * (d / s) ** 2) / (s * np.sqrt(2.0 * np.pi))
    lz = (FWHM / 2.0 / np.pi) / (d * d + (FWHM / 2.0) ** 2)
    return amp_scale * (ETA * g + (1.0 - ETA) * lz)


def test_bragg_r_matches_analytic_value():
    """分离峰 + 已知强度扰动 → Bragg R 与解析值一致 (<5% 相对)。"""
    t = np.arange(15.0, 70.0, 0.01)
    pos = np.array([25.0, 35.0, 50.0])
    iref = np.array([100.0, 50.0, 30.0])
    scale, weight = 2.0, 1.0
    i_calc = scale * weight * iref                      # [200, 100, 60]
    # 观测 = 模型强度 × 扰动 [1.05, 0.95, 1.00]
    factors = np.array([1.05, 0.95, 1.00])
    y = np.zeros_like(t)
    for p, ic, f in zip(pos, i_calc, factors):
        y += _pv(t - p, ic * f)
    peaks = [[((1, 0, 0), float(p), float(r))
              for p, r in zip(pos, iref)]]
    bragg = RietveldRefiner._bragg_r_from_fit(
        t, y, peaks, np.array([weight]), scale, FWHM, ETA)
    assert bragg is not None
    i_obs_true = i_calc * factors
    analytic = 100.0 * np.sum(np.abs(i_obs_true - i_calc)) / np.sum(i_obs_true)
    assert bragg == pytest.approx(analytic, rel=0.05), (bragg, analytic)


def test_bragg_r_penalizes_missing_reflection():
    """模型里有、观测里没有的反射 → 拉高 Bragg R (错相惩罚的本义)。"""
    t = np.arange(15.0, 70.0, 0.01)
    pos = np.array([25.0, 35.0, 50.0])
    iref = np.array([100.0, 50.0, 30.0])
    scale, weight = 2.0, 1.0
    i_calc = scale * weight * iref
    y = np.zeros_like(t)
    # 观测里缺 50° 峰 (只有前两条)
    for p, ic in zip(pos[:2], i_calc[:2]):
        y += _pv(t - p, ic)
    peaks = [[((1, 0, 0), float(p), float(r))
              for p, r in zip(pos, iref)]]
    bragg = RietveldRefiner._bragg_r_from_fit(
        t, y, peaks, np.array([weight]), scale, FWHM, ETA)
    assert bragg is not None
    # 全部强度对上时 ≈0, 缺一条 60/(200+100+60)≈16.7% 量级
    assert bragg > 5.0, bragg
    # 但不应爆炸 (分母 Σ I_obs 主导)
    assert bragg < 40.0, bragg


def test_bragg_r_none_when_no_reflections():
    t = np.arange(15.0, 70.0, 0.01)
    y = np.zeros_like(t)
    assert RietveldRefiner._bragg_r_from_fit(
        t, y, [], np.array([1.0]), 1.0, FWHM, ETA) is None


def test_builtin_refine_records_bragg_r():
    """精修主链路: result.Rb 与 fit_params['bragg_r'] 记录真实 Bragg R。"""
    tt = np.arange(20.0, 60.0, 0.02)
    y = np.full_like(tt, 60.0)
    y += 900.0 * np.exp(-0.5 * ((tt - 30.0) / 0.08) ** 2)
    y += 400.0 * np.exp(-0.5 * ((tt - 43.0) / 0.08) ** 2)
    data = XRDData(two_theta=tt, intensity=y)
    data.wavelength = 1.5406
    ph = Phase(name="T", formula="T",
               lattice=LatticeParams(a=4.0, b=4.0, c=4.0,
                                     alpha=90, beta=90, gamma=90),
               reference_peaks=[((1, 0, 0), 30.0, 100.0),
                                ((1, 1, 0), 42.5, 44.0)])
    r = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=2,
                                 wR_threshold=None, detect_ka2=False)
    assert r.Rb > 0, (r.Rb, r.fit_params.get("bragg_r"))
    assert r.fit_params.get("bragg_r") == pytest.approx(r.Rb)
    # 良好拟合的合成单相: Bragg R 应优于整体 wR (按积分强度对账更宽容)
    assert r.Rb < 60.0, (r.Rb, r.wR)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
