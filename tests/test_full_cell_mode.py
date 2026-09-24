"""全晶胞参数模式 (实施手册 v3 / M5-W18)
=======================================
isotropic 模式每相只有 1 个各向同性缩放 (只能整体平移峰位);
full 模式每相 6 个比例 (a,b,c,α,β,γ), 由 hkl 反算 d → 2θ, 能修各向异性失配。

本测试锁住: ① 变换的物理方向正确 (a 变大 → d 变大 → 2θ 变小);
② isotropic 与 full 在"六参数全为 1"时都零改动; ③ full 模式能吸收各向异性畸变
且 wR 不劣化; ④ 默认仍是 isotropic (不改变既有行为)。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


def _gauss(x, cen, amp, fwhm):
    sig = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return amp * np.exp(-0.5 * ((x - cen) / sig) ** 2)


def _tth_from_cell(a, b, c, h, k, l, lam=1.5406):
    d = RietveldRefiner._calc_d_spacing_from_hkl(a, b, c, 90.0, 90.0, 90.0, h, k, l)
    return 2.0 * math.degrees(math.asin(lam / (2.0 * d)))


def _tetragonal_phase() -> Phase:
    """四方相 (a=b=5.0, c=7.0): 各向异性畸变对 (hkl) 的影响不同, 可被 full 模式区分"""
    # 峰位由晶胞 + hkl **现算**, 避免手写近似值导致夹具与模型不同源
    refs = [((1, 0, 0), 60.0), ((1, 1, 0), 100.0), ((2, 0, 0), 45.0),
            ((2, 1, 0), 25.0), ((0, 0, 2), 20.0), ((2, 1, 2), 15.0)]
    return Phase(
        name="T", formula="T",
        lattice=LatticeParams(a=5.0, b=5.0, c=7.0),
        reference_peaks=[(hkl, _tth_from_cell(5.0, 5.0, 7.0, *hkl), amp)
                         for hkl, amp in refs],
    )


class TestTransform:

    def test_unity_scales_are_noop(self):
        ph = _tetragonal_phase()
        peaks = [ph.reference_peaks]
        out = RietveldRefiner._apply_full_cell(peaks, [1.0] * 6, [ph], 1.5406)
        assert out[0] is peaks[0]

    def test_larger_a_lowers_two_theta(self):
        """a 变大 → d 变大 → 2θ 变小 (同一 hkl)"""
        ph = _tetragonal_phase()
        peaks = [ph.reference_peaks]
        out = RietveldRefiner._apply_full_cell(peaks, [1.01, 1.01, 1.0, 1, 1, 1],
                                               [ph], 1.5406)
        t_old = dict((p[0], p[1]) for p in ph.reference_peaks)
        for hkl, tth, _i in out[0]:
            if hkl in ((2, 0, 0), (2, 1, 0)):
                assert tth < t_old[hkl], f"{hkl}: {tth} 应小于 {t_old[hkl]}"
        # 00l 不受 a 变化影响 (只依赖 c) —— 与"基准晶胞算出的 002"逐位相同
        d = dict((p[0], p[1]) for p in out[0])
        assert d[(0, 0, 2)] == pytest.approx(_tth_from_cell(5.0, 5.0, 7.0, 0, 0, 2),
                                            abs=1e-9)

    def test_larger_c_lowers_00l(self):
        ph = _tetragonal_phase()
        out = RietveldRefiner._apply_full_cell([ph.reference_peaks],
                                               [1.0, 1.0, 1.01, 1, 1, 1],
                                               [ph], 1.5406)
        d = dict((p[0], p[1]) for p in out[0])
        assert d[(0, 0, 2)] < _tth_from_cell(5.0, 5.0, 7.0, 0, 0, 2)
        # 200 只依赖 a → c 变化不影响它
        assert d[(2, 0, 0)] == pytest.approx(_tth_from_cell(5.0, 5.0, 7.0, 2, 0, 0),
                                             abs=1e-9)


def _anisotropic_pattern(a_scale: float = 1.0, c_scale: float = 1.0,
                         seed: int = 4) -> XRDData:
    """按各向异性畸变生成"实测谱" (先算出畸变后的峰位再叠峰)"""
    rng = np.random.default_rng(seed)
    ph = _tetragonal_phase()
    shifted = RietveldRefiner._apply_full_cell(
        [ph.reference_peaks], [a_scale, a_scale, c_scale, 1, 1, 1], [ph], 1.5406)[0]
    tt = np.arange(12.0, 60.0, 0.02)
    y = np.full_like(tt, 70.0)
    for hkl, cen, amp in shifted:
        y = y + _gauss(tt, cen, amp * 15.0, 0.13)
    y = rng.poisson(np.maximum(y, 0.0)).astype(float)
    d = XRDData(two_theta=tt, intensity=y)
    d.wavelength = 1.5406
    return d


class TestFitting:

    def test_default_is_isotropic(self):
        r = RietveldRefiner().refine(_anisotropic_pattern(), [_tetragonal_phase()],
                                     engine="builtin", max_cycles=5,
                                     wR_threshold=None, detect_ka2=False)
        assert r.fit_params["cell_mode"] == "isotropic"
        assert len(r.fit_params["cell_scale"]) == 1

    def test_full_mode_absorbs_anisotropy(self):
        data = _anisotropic_pattern(a_scale=1.008, c_scale=1.0)
        rr = RietveldRefiner()
        r_iso = rr.refine(data, [_tetragonal_phase()], engine="builtin",
                          max_cycles=6, wR_threshold=None, detect_ka2=False)
        r_full = rr.refine(data, [_tetragonal_phase()], engine="builtin",
                           max_cycles=6, wR_threshold=None, detect_ka2=False,
                           cell_mode="full")
        sc = list(r_full.fit_params["cell_scale"])
        print(f"[full cell] scales={[round(x, 5) for x in sc]}  "
              f"wR iso={r_iso.wR:.3f}% full={r_full.wR:.3f}%")
        assert r_full.fit_params["cell_mode"] == "full"
        assert len(sc) == 6
        # a 方向的畸变被识别出来 (符号正确: 真值 a×1.008 → sa > 1)
        assert sc[0] > 1.0, f"sa 应为 >1: {sc}"
        assert r_full.wR <= r_iso.wR * 1.02 + 1e-9, \
            f"full 模式 wR 不应明显变差: iso={r_iso.wR:.3f} full={r_full.wR:.3f}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
