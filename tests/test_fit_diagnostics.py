"""拟合后诊断 (实施手册 v3 / M7-W28; v2.1-B 结构化改造)
====================================================
不改模型, 只回答"模型缺了什么":
  - 分段轮廓 R (低角/中角/高角) → 定位问题区域;
  - Durbin-Watson → 残差是白噪声 (≈2) 还是逐点相关 (<<2, 说明模型不完备);
  - diagnoses → 结构化建议 [{code, params}] (v2.1-B 起, 文案由 UI tr() 渲染;
    仅在整体 R 高于阈值时给)。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.i18n.diag_texts import render_entry
from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


def _gauss(x, cen, amp, fwhm):
    sig = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return amp * np.exp(-0.5 * ((x - cen) / sig) ** 2)


class TestDiagnosticsMath:

    def test_perfect_fit_has_dw_near_two_and_no_advice(self):
        tt = np.linspace(10.0, 90.0, 800)
        y = 100.0 + 50.0 * np.sin(tt / 5.0)
        d = RietveldRefiner._fit_diagnostics(tt, y, y.copy())
        assert d["durbin_watson"] == pytest.approx(2.0, abs=0.05)
        assert d["R_all_unweighted"] < 1e-9
        assert d["diagnoses"] == []

    def test_systematic_offset_triggers_low_dw(self):
        """整体系统性偏差 (逐点相关) → DW 明显 <2 且给出"模型不完备"建议"""
        tt = np.linspace(10.0, 90.0, 800)
        y = 200.0 + 100.0 * np.sin(tt / 3.0)
        c = y - 60.0          # 恒定偏差: 残差完全相关
        d = RietveldRefiner._fit_diagnostics(tt, y, c)
        assert d["durbin_watson"] < 0.5, d["durbin_watson"]
        assert any(e["code"] == "diag.dw_correlated" for e in d["diagnoses"]), d["diagnoses"]

    def test_high_angle_bias_diagnosis(self):
        """只在高角有偏差 → 给出"高角区残差偏大"建议 (并指向 B/峰宽/位移)"""
        tt = np.linspace(10.0, 90.0, 800)
        y = np.full_like(tt, 100.0)
        c = y.copy()
        c[tt > 60.0] -= 30.0
        d = RietveldRefiner._fit_diagnostics(tt, y, c)
        assert d["R_high_unweighted"] > d["R_low_unweighted"]
        assert any(e["code"] == "diag.high_angle_residual" for e in d["diagnoses"]), d["diagnoses"]

    def test_low_angle_bias_diagnosis(self):
        tt = np.linspace(10.0, 90.0, 800)
        y = np.full_like(tt, 100.0)
        c = y.copy()
        # 偏差要足够大: 低角段 −60 → 整体 R 才会超过 8% 的建议阈值
        c[tt < 30.0] -= 60.0
        d = RietveldRefiner._fit_diagnostics(tt, y, c)
        assert any(e["code"] == "diag.low_angle_residual" for e in d["diagnoses"]), d["diagnoses"]

    def test_good_fit_gives_no_advice_even_with_small_dw_deviation(self):
        """整体 R 低于阈值时不给建议 (避免好拟合上瞎提示)"""
        tt = np.linspace(10.0, 90.0, 800)
        y = np.full_like(tt, 1000.0)
        c = y - 1.0     # 0.1% 的恒定偏差
        d = RietveldRefiner._fit_diagnostics(tt, y, c)
        assert d["diagnoses"] == []

    def test_degenerate_inputs_safe(self):
        assert RietveldRefiner._fit_diagnostics(np.ones(3), np.ones(3),
                                                np.ones(3)) == {}


class TestRefinerWiring:

    def test_diagnostics_recorded_and_warning_visible(self):
        ph = Phase(name="T", formula="T",
                   lattice=LatticeParams(a=4.0, b=4.0, c=4.0),
                   reference_peaks=[((1, 0, 0), 22.0, 100.0),
                                    ((2, 0, 0), 45.9, 40.0)])
        tt = np.arange(15.0, 70.0, 0.02)
        # 故意造一个"缺相"的谱: 多一个模型里没有的峰 → 残差必然有系统结构
        y = np.full_like(tt, 60.0)
        for _h, cen, amp in ph.reference_peaks:
            y = y + amp * 9.0 * _gauss(tt, cen, 1.0, 0.09)
        # 未建模的**宽而强**的杂峰: 单相模型无法吸收 → 残差必然带系统结构
        y = y + 2500.0 * _gauss(tt, 33.0, 1.0, 0.40)
        data = XRDData(two_theta=tt, intensity=y)
        data.wavelength = 1.5406
        r = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=6,
                                     wR_threshold=None, detect_ka2=False)
        diag = r.fit_params.get("diagnostics") or {}
        assert "durbin_watson" in diag
        assert diag["durbin_watson"] < 1.5, diag
        assert diag["diagnoses"], diag
        # v2.1-B: 诊断进 result.diagnostics (结构化), 且能渲染为本地化文案
        codes = [d.get("code") for d in r.diagnostics]
        assert any(e["code"] in codes for e in diag["diagnoses"][:1]), (diag, codes)
        rendered = [render_entry(d) for d in r.diagnostics]
        assert rendered, rendered


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
