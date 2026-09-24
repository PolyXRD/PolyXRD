"""低角不对称 split-PV (实施手册 v3 / M5-W17)
============================================
 1. 关 (asymmetry=0) 时与旧行为逐点一致;
 2. 面积守恒: 单峰积分仍 = 强度 (与不对称强度无关);
 3. 方向正确: 低角侧比高角侧宽 → 同 |Δ| 处 I(c−Δ) > I(c+Δ);
 4. 只在低角显著: 同一不对称下 20° 处左右差异远大于 90° 处;
 5. 经精修接口可传入 (fit_params 记录).
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.phase_display import spectrum_from_refs
from polyxrd.services.rietveld_refiner import RietveldRefiner

STEP = 0.005


def _one_peak(tth=20.0, inten=100.0):
    return [((1, 0, 0), tth, inten)]


def _sim(tth=20.0, fwhm=0.15, eta=0.5, asym=0.0, span=(10.0, 30.0)):
    tt = np.arange(span[0], span[1], STEP)
    y = spectrum_from_refs(tt, [_one_peak(tth)], [1.0], fwhm, eta, 1.0,
                           "pseudo-voigt", None, cutoff_fwhm=100.0,
                           asymmetry=asym)
    return tt, y


class TestAsymmetry:

    def test_zero_is_identical_to_no_asymmetry(self):
        t1, y1 = _sim(asym=0.0)
        t2, y2 = _sim(asym=0.0, span=(10.0, 30.0))
        assert np.allclose(y1, y2, atol=0.0)
        # 与"不传该参数"的老调用完全一致
        tt = np.arange(10.0, 30.0, STEP)
        y_old = spectrum_from_refs(tt, [_one_peak()], [1.0], 0.15, 0.5, 1.0,
                                   "pseudo-voigt", None, cutoff_fwhm=100.0)
        assert np.max(np.abs(y_old - y1)) < 1e-12

    @pytest.mark.parametrize("asym", [0.2, 0.4])
    def test_area_preserved(self, asym):
        """面积与"不对称=0"相比变化 <1.5% (网格截断带来的小偏差允许)。

        注意: 若用旧的非面积归一峰形, 开不对称会让面积变化 40% 量级 —— 本断言能区分。
        """
        tt0, y0 = _sim(asym=0.0, span=(0.0, 40.0))
        tt, y = _sim(asym=asym, span=(0.0, 40.0))
        area0 = float(np.sum(y0) * STEP)
        area = float(np.sum(y) * STEP)
        assert area == pytest.approx(area0, rel=0.015), (area, area0)

    def test_low_angle_side_is_wider(self):
        tt, y = _sim(tth=20.0, asym=0.3)
        d = 0.10
        i_left = float(np.interp(20.0 - d, tt, y))
        i_right = float(np.interp(20.0 + d, tt, y))
        assert i_left > i_right, (i_left, i_right)

    def test_asymmetry_only_matters_at_low_angle(self):
        def ratio(tth):
            tt, y = _sim(tth=tth, asym=0.3, span=(tth - 10.0, tth + 10.0))
            d = 0.10
            lo = float(np.interp(tth - d, tt, y))
            hi = float(np.interp(tth + d, tt, y))
            return lo / max(hi, 1e-12)
        r20 = ratio(20.0)
        r90 = ratio(90.0)
        assert r20 > r90, (r20, r90)
        assert r20 > 1.3, f"低角应明显不对称: {r20}"
        assert r90 < 1.2, f"高角的不对称应弱得多: {r90}"


class TestRefinerWiring:

    def test_asymmetry_recorded_in_fit_params(self):
        ph = Phase(name="T", formula="T",
                   lattice=LatticeParams(a=4.0, b=4.0, c=4.0),
                   reference_peaks=[((1, 0, 0), 22.0, 100.0),
                                    ((1, 1, 0), 31.5, 60.0)])
        tt = np.arange(15.0, 45.0, 0.02)
        y = np.full_like(tt, 40.0)
        for _h, cen, amp in ph.reference_peaks:
            y = y + amp * 8.0 * np.exp(-0.5 * ((tt - cen) / 0.06) ** 2)
        data = XRDData(two_theta=tt, intensity=y)
        data.wavelength = 1.5406
        r = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=4,
                                     wR_threshold=None, detect_ka2=False,
                                     asymmetry=0.25)
        assert r.fit_params["asymmetry"] == pytest.approx(0.25)
        r0 = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=4,
                                      wR_threshold=None, detect_ka2=False)
        assert r0.fit_params["asymmetry"] == pytest.approx(0.0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
