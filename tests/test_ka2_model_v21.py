"""v2.1-E: Kα2 建模 (opt-in) 回归测试
====================================
物理: Kα1/Kα2 双线 (Cu λ2/λ1 = 1.00249, 强度比 ≈ 0.5)。模型加 Kα2 伴峰
(解析 Δ2θ, 强度比 = ratio, 与主峰共享尺度/权重/峰宽, 不新增自由度)。

验收口径 (docs/后续计划与已知问题-v2.1.md):
  - 合成 Kα2 数据回收强度比 0.5±0.05 (按反射积分强度提取);
  - 开启建模后双线数据的 wR 显著低于单峰模型 (高角残差消除)。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

FWHM = 0.12
ETA = 0.5
A2 = 1.00249   # λ2/λ1 (Cu)


def _pv(d, amp):
    s = FWHM / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    g = np.exp(-0.5 * (d / s) ** 2) / (s * np.sqrt(2.0 * np.pi))
    lz = (FWHM / 2.0 / np.pi) / (d * d + (FWHM / 2.0) ** 2)
    return amp * (ETA * g + (1.0 - ETA) * lz)


def _ka2_tt(tt1):
    return 2.0 * np.degrees(np.arcsin(A2 * np.sin(np.radians(tt1 / 2.0))))


# ── 伴峰扩展 ─────────────────────────────────────────────────

def test_expand_ka2_satellites_analytic():
    """Δ2θ 与强度比解析正确; 原峰列表不变 (返回新列表)。"""
    peaks = [[((1, 0, 0), 36.2, 100.0), ((1, 0, 1), 50.0, 60.0)]]
    out = RietveldRefiner._expand_ka2_satellites(peaks, 1.54056)
    assert out is not peaks and out[0] is not peaks[0]
    assert len(out[0]) == 4
    (hkl1, tt1, i1), (sat1, tt1b, isat1), (hkl2, tt2, i2), (sat2, tt2b, isat2) = out[0]
    # 主峰原样, 伴峰 = 解析 Δ2θ + 0.5×强度
    assert tt1b == pytest.approx(_ka2_tt(36.2), abs=1e-6)
    assert tt1b - tt1 == pytest.approx(0.093, abs=0.01)   # 36.2° 处 ≈0.093°
    assert isat1 == pytest.approx(50.0)
    assert tt2b > tt2
    assert isat2 == pytest.approx(30.0)


def test_expand_ka2_skips_unreachable():
    """sinθ2 > 1 (伴峰超出可测区) → 丢弃伴峰, 主峰保留。"""
    lam = 1.54056
    # 2θ 接近 180° 的峰: sinθ2 = A2·sinθ1 > 1
    tt = 2.0 * np.degrees(np.arcsin(0.9998))
    peaks = [[((1, 1, 1), tt, 80.0)]]
    out = RietveldRefiner._expand_ka2_satellites(peaks, lam)
    assert len(out[0]) == 1 and out[0][0][1] == tt


# ── 强度比回收 (验收口径) ─────────────────────────────────────

def test_ka2_intensity_ratio_recovered():
    """合成 Kα2 数据 (比率 0.5) → 按反射提取的 I_obs 伴峰/主峰 = 0.5±0.05。"""
    t = np.arange(15.0, 70.0, 0.005)
    mains = [(25.0, 100.0), (36.2, 45.0), (50.0, 60.0)]
    y = np.zeros_like(t)
    for tt1, i1 in mains:
        tt2 = _ka2_tt(tt1)
        y += _pv(t - tt1, i1)
        y += _pv(t - tt2, 0.5 * i1)
    peaks = [[
        ((1, 0, 0), 25.0, 100.0), ((1, 0, 0), _ka2_tt(25.0), 50.0),
        ((1, 0, 1), 36.2, 45.0), ((1, 0, 1), _ka2_tt(36.2), 22.5),
        ((2, 0, 0), 50.0, 60.0), ((2, 0, 0), _ka2_tt(50.0), 30.0),
    ]]
    res = RietveldRefiner._bragg_r_from_fit(
        t, y, peaks, np.array([1.0]), 1.0, FWHM, ETA,
        return_intensities=True)
    assert res is not None
    _bragg, i_obs, i_calc, pos = res
    # 分离峰对 (最强组) 逐对回收: I_obs(sat) / I_obs(main) ≈ 0.5±0.05
    for main_tt, sat_tt, ratio_true in [
        (25.0, _ka2_tt(25.0), 0.5),
        (50.0, _ka2_tt(50.0), 0.5),
    ]:
        im = next(i for p, i in zip(pos, i_obs)
                  if abs(p - main_tt) < 0.01)
        isat = next(i for p, i in zip(pos, i_obs)
                    if abs(p - sat_tt) < 0.01)
        assert isat / im == pytest.approx(ratio_true, abs=0.05), (
            main_tt, sat_tt, isat, im)


# ── 精修链路: 双线数据上建模显著降 wR ─────────────────────────

def _ka2_data():
    tt = np.arange(15.0, 70.0, 0.02)
    y = np.full_like(tt, 60.0)
    for tt1, i1 in [(30.0, 900.0), (36.2, 300.0), (50.0, 500.0)]:
        tt2 = float(_ka2_tt(tt1))
        y += _pv(tt - tt1, i1 / 100.0 * 900.0 / 9.0)
        y += _pv(tt - tt2, 0.5 * i1 / 100.0 * 900.0 / 9.0)
    data = XRDData(two_theta=tt, intensity=y)
    data.wavelength = 1.54056
    return data


def _ka2_phase():
    """参考峰表只含 Kα1 主峰 (伴峰由 model_ka2 自动扩展, 不可手放)。"""
    return Phase(name="T", formula="T",
                 lattice=LatticeParams(a=4.0, b=4.0, c=4.0,
                                       alpha=90, beta=90, gamma=90),
                 reference_peaks=[
                     ((1, 0, 0), 30.0, 100.0),
                     ((1, 0, 1), 36.2, 33.3),
                     ((2, 0, 0), 50.0, 55.6),
                 ])


def test_model_ka2_reduces_wr_on_doublet_data():
    data = _ka2_data()
    ph = _ka2_phase()
    r_off = RietveldRefiner().refine(data, [ph], engine="builtin",
                                     max_cycles=3, wR_threshold=None,
                                     detect_ka2=False, model_ka2=False)
    r_on = RietveldRefiner().refine(data, [ph], engine="builtin",
                                    max_cycles=3, wR_threshold=None,
                                    detect_ka2=False, model_ka2=True)
    assert r_on.fit_params.get("model_ka2") is True
    assert r_on.wR < 0.6 * r_off.wR, (r_off.wR, r_on.wR)


def test_model_ka2_off_by_default():
    """opt-in 默认关: 不传 kwargs 时模型不含伴峰。"""
    data = _ka2_data()
    r = RietveldRefiner().refine(data, [_ka2_phase()], engine="builtin",
                                 max_cycles=2, wR_threshold=None,
                                 detect_ka2=False)
    assert r.fit_params.get("model_ka2") is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
