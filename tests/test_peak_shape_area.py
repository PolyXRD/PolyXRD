"""峰形面积归一 (实施手册 v3 / M3-W11)
=====================================
Rietveld 要求峰的**积分强度** ∝ m·LP·|F|²·S, 与峰宽、η 无关。
旧实现把高斯/洛伦兹写成"峰高=1", 于是:
  - 积分面积 ∝ FWHM;
  - η 从 0→1 让面积变化 ~47% (η 不再是混合比);
  - Caglioti 一开, 峰宽参数就被拟合到错误值。

本测试锁住"面积归一"这一契约: 单峰的积分面积 = 该峰的相对强度 (× scale × weight),
与 FWHM、η、峰形类型都无关。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.services.phase_display import spectrum_from_refs

STEP = 0.005
TT = np.arange(20.0, 60.0, STEP)


def _area(sim: np.ndarray) -> float:
    return float(np.sum(sim) * STEP)


@pytest.mark.parametrize("fwhm", [0.06, 0.15, 0.30])
@pytest.mark.parametrize("eta", [0.0, 0.5, 1.0])
def test_pv_area_independent_of_fwhm_and_eta(fwhm, eta):
    """伪 Voigt: 单峰面积 = 强度 (100), 与 FWHM/η 无关。"""
    refs = [((1, 0, 0), 30.0, 100.0)]
    sim = spectrum_from_refs(TT, [refs], [1.0], fwhm, eta, 1.0,
                             "pseudo-voigt", None, cutoff_fwhm=100.0)
    assert _area(sim) == pytest.approx(100.0, rel=0.01), \
        f"fwhm={fwhm} eta={eta}: 面积={_area(sim):.3f} (期望 100)"


@pytest.mark.parametrize("shape", ["gaussian", "lorentzian"])
def test_pure_shapes_area_independent_of_fwhm(shape):
    """纯高斯 / 纯洛伦兹: 同样面积守恒 (与 FWHM 无关)。"""
    refs = [((1, 0, 0), 30.0, 100.0)]
    areas = []
    for fwhm in (0.08, 0.15, 0.30):
        sim = spectrum_from_refs(TT, [refs], [1.0], fwhm, 0.5, 1.0,
                                 shape, None, cutoff_fwhm=100.0)
        areas.append(_area(sim))
    assert max(areas) == pytest.approx(min(areas), rel=0.01), areas
    assert areas[0] == pytest.approx(100.0, rel=0.01), areas


def test_area_scales_with_intensity_scale_and_weight():
    """面积 ∝ (参考峰强度 × scale × 该相 weight)。"""
    refs = [((1, 0, 0), 30.0, 37.0)]
    sim = spectrum_from_refs(TT, [refs], [2.5], 0.13, 0.5, 4.0,
                             "pseudo-voigt", None, cutoff_fwhm=100.0)
    assert _area(sim) == pytest.approx(37.0 * 2.5 * 4.0, rel=0.01)


def test_peak_height_is_no_longer_normalized():
    """反证: 面积归一后"峰高"随 FWHM 变化 (旧实现峰高恒等于强度)。"""
    refs = [((1, 0, 0), 30.0, 100.0)]
    h = []
    for fwhm in (0.08, 0.30):
        sim = spectrum_from_refs(TT, [refs], [1.0], fwhm, 0.5, 1.0,
                                 "pseudo-voigt", None, cutoff_fwhm=100.0)
        h.append(float(np.max(sim)))
    # 峰高 ∝ 1/FWHM → 宽峰显著更矮
    assert h[0] > h[1] * 2.0, h


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
