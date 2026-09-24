"""质量分数定量 W ∝ S·(ZMV) (实施手册 v3 / M6-W23)
=================================================
本引擎的参考峰表按"每相 max=100"归一化, 拟合幅值 amp_p 是相对该图谱的;
要得到**质量分数**, 必须先把幅值还原到物理标度 S_p = amp_p·k_p/100,
再乘 ZMV (= 晶胞内质量 × 晶胞体积): W_p ∝ S_p·(ZMV)_p。

本测试锁住该换算 (含信息不足时的回落)。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.services.rietveld_refiner import RietveldRefiner


class TestMassFractions:

    def test_identical_k_and_zmv_gives_amplitude_ratio(self):
        """k 与 ZMV 都相同时, 质量分数 = 幅值比 (退化为相对定量)"""
        w = RietveldRefiner._mass_fractions([3.0, 1.0], [100.0, 100.0], [50.0, 50.0])
        assert w == pytest.approx([75.0, 25.0])

    def test_k_correction_compensates_normalization(self):
        """两相幅值相同但归一化标尺 k 不同 → 物理标度不同, 质量分数随之改变

        标度还原关系: 归一化图谱 = 100·raw/k ⇒ S = amp·100/k。
        A: amp=1, k=200 → S=0.5 ; B: amp=1, k=100 → S=1 ; ZMV 相同 → 1:2
        """
        w = RietveldRefiner._mass_fractions([1.0, 1.0], [200.0, 100.0], [10.0, 10.0])
        assert w == pytest.approx([33.3333, 66.6667], rel=1e-4)

    def test_zmv_correction_direction(self):
        """ZMV 大的相质量分数更高 (同幅值同 k)"""
        w = RietveldRefiner._mass_fractions([1.0, 1.0], [100.0, 100.0],
                                            [200.0, 100.0])
        assert w[0] > w[1]
        assert w == pytest.approx([66.6667, 33.3333], rel=1e-4)

    def test_hand_computed_case(self):
        """手算校核: amp=(2,1), k=(150,300), ZMV=(20,10)
           S = (2*100/150, 1*100/300) = (4/3, 1/3)
           W ∝ (4/3*20, 1/3*10) = (26.667, 3.333) → 8:1 (88.89 / 11.11)"""
        w = RietveldRefiner._mass_fractions([2.0, 1.0], [150.0, 300.0], [20.0, 10.0])
        assert w == pytest.approx([88.8889, 11.1111], rel=1e-4)

    @pytest.mark.parametrize("k,zmv", [
        ([None, 100.0], [10.0, 10.0]),      # 缺 k
        ([100.0, 100.0], [None, 10.0]),     # 缺 ZMV
        ([0.0, 100.0], [10.0, 10.0]),       # k 非法
        ([100.0, 100.0], [10.0, -1.0]),     # ZMV 非法
        ([100.0], [10.0, 10.0]),            # 长度不一致
    ])
    def test_falls_back_when_info_missing(self, k, zmv):
        assert RietveldRefiner._mass_fractions([1.0, 1.0], k, zmv) is None

    def test_zero_amplitudes_fall_back(self):
        assert RietveldRefiner._mass_fractions([0.0, 0.0], [100.0, 100.0],
                                               [10.0, 10.0]) is None


class TestRefinerWiring:

    def test_weight_basis_reported(self):
        """精修结果必须标明定量口径 (mass / relative)"""
        from polyxrd.models.phase import LatticeParams, Phase
        from polyxrd.models.xrd_data import XRDData
        ph = Phase(name="Si", formula="Si",
                   lattice=LatticeParams(a=5.431, b=5.431, c=5.431),
                   reference_peaks=[((1, 1, 1), 28.442, 100.0),
                                    ((2, 2, 0), 47.303, 60.0)])
        tt = np.arange(20.0, 60.0, 0.02)
        y = np.full_like(tt, 50.0)
        for _h, cen, amp in ph.reference_peaks:
            y = y + amp * 6.0 * np.exp(-0.5 * ((tt - cen) / 0.08) ** 2)
        data = XRDData(two_theta=tt, intensity=y)
        data.wavelength = 1.5406
        r = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=4,
                                     wR_threshold=None, detect_ka2=False)
        # 该相无 CIF/atomic_sites → 拿不到 k/ZMV → 必须是 relative 口径
        assert r.fit_params["weight_basis"] == "relative"
        assert abs(sum(p.weight_fraction for p in r.phases) - 100.0) < 0.01


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
