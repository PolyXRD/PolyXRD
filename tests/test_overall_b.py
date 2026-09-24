"""整体温度因子 B (实施手册 v3 / M6-W22a)
=======================================
物理: |F|² → |F|²·exp(−2B·s²), s = sinθ/λ。
这是"逐峰乘性、只依赖 2θ"的修正 → 可直接作用在参考峰表上, 无需重算结构因子,
是结构自由度里代价最低的一项 (真实 Rietveld 程序的标准自由度)。

本测试锁住: ① B=0 或关闭时零改动; ② 衰减随 2θ 单调加强 (高角掉得更多);
③ B 越大衰减越强; ④ 只改强度不改峰位; ⑤ 精修接口参数与默认值。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

LAM = 1.5406


def _peaks():
    return [[((1, 0, 0), 20.0, 100.0), ((4, 0, 0), 80.0, 100.0)]]


class TestTransform:

    def test_zero_b_is_noop(self):
        pk = _peaks()
        # B=0 → 逐相原样复用同一个峰表对象 (值完全不变)
        out = RietveldRefiner._apply_overall_b(pk, [0.0], LAM)
        assert out[0] is pk[0] and out == pk
        # 参数缺失 (None → numpy 视作 NaN) → 同样原样复用, 不改任何峰
        out2 = RietveldRefiner._apply_overall_b(pk, None, LAM)
        assert out2[0] is pk[0] and out2 == pk

    def test_high_angle_attenuates_more(self):
        out = RietveldRefiner._apply_overall_b(_peaks(), [3.0], LAM)[0]
        (h1, t1, i1), (h2, t2, i2) = out
        assert t1 == pytest.approx(20.0) and t2 == pytest.approx(80.0)  # 峰位不动
        assert i1 < 100.0 and i2 < i1, (i1, i2)
        # 解析核对: exp(-2B s^2)
        s2 = math.sin(math.radians(80.0 / 2.0)) / LAM
        assert i2 == pytest.approx(100.0 * math.exp(-2.0 * 3.0 * s2 * s2), rel=1e-9)

    def test_larger_b_attenuates_stronger(self):
        a = RietveldRefiner._apply_overall_b(_peaks(), [1.0], LAM)[0][1][2]
        b = RietveldRefiner._apply_overall_b(_peaks(), [8.0], LAM)[0][1][2]
        assert b < a < 100.0

    def test_negative_b_kept_as_is(self):
        """B<=0 视为"无修正", 不做反向增强 (防参数跑飞)"""
        pk = _peaks()
        out = RietveldRefiner._apply_overall_b(pk, [-2.0], LAM)
        assert out[0] is pk[0] and out == pk


class TestRefinerWiring:

    def _data(self):
        ph = Phase(name="T", formula="T",
                   lattice=LatticeParams(a=4.0, b=4.0, c=4.0),
                   reference_peaks=[((1, 0, 0), 31.7, 100.0),
                                    ((2, 0, 0), 65.4, 40.0)])
        tt = np.arange(25.0, 80.0, 0.02)
        y = np.full_like(tt, 40.0)
        # 生成时人为加 B=4 的衰减 (高角更弱) → 精修应把它找回来
        for _h, cen, amp in ph.reference_peaks:
            s = math.sin(math.radians(cen / 2.0)) / LAM
            y = y + amp * 8.0 * math.exp(-2.0 * 4.0 * s * s) * np.exp(
                -0.5 * ((tt - cen) / 0.08) ** 2)
        d = XRDData(two_theta=tt, intensity=y)
        d.wavelength = LAM
        return d, ph

    def test_default_on_and_recovers_b(self):
        data, ph = self._data()
        r = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=8,
                                     wR_threshold=None, detect_ka2=False)
        assert r.fit_params["refine_b_overall"] is True
        b = r.fit_params["b_overall"]
        assert len(b) == 1
        assert b[0] > 1.0, f"应识别出正的整体 B: {b}"

    def test_can_be_disabled(self):
        data, ph = self._data()
        r = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=5,
                                     wR_threshold=None, detect_ka2=False,
                                     refine_b_overall=False)
        assert r.fit_params["refine_b_overall"] is False
        assert r.fit_params["b_overall"] == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
