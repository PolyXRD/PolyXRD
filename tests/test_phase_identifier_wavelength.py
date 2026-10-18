"""波长口径收口回归 (v3.0.1, P0-4)
=====================================
背景: 四条检索链（内置库 / COD 全库 / COD 无机 / 用户库 / PDF2）此前一律用
``config.default_wavelength``（Cu Kα1 1.5406）把实验 2θ 换算成 d 值，
而 ``data_loader`` 早已从文件头/靶材解析出 ``XRDData.wavelength``（Co 1.78897、
Fe 1.93604、Mo 0.7093 …）。两者脱钩 → ``d = λ/(2sinθ)`` 整体错位 → 真物相被
判不匹配。同时内置参考库的峰表是 Cu 基准硬编码，非 Cu 靶必须按 d 值不变
换算（``sinθ_new = sinθ_ref · λ_new/λ_ref``）。

本例用同一组 d 值合成 Cu / Co / Fe / Mo 四种靶的 Si 谱，要求四条链路都能
把 Silicon 认成 Top-1。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.phase_identifier import PhaseIdentifier

#: Si 六条主要反射的 Cu Kα1 2θ
SI_CU_TWO_THETA = [28.44, 47.30, 56.11, 69.13, 76.36, 88.04]
SI_INTENSITY = [1000.0, 600.0, 400.0, 200.0, 150.0, 100.0]
CU = 1.5406
ANODES = {
    "Cu": 1.5406,
    "Co": 1.78897,
    "Fe": 1.93604,
    "Cr": 2.28970,
    "Mo": 0.70930,
}


def _d_spacings(lam: float = CU) -> list[float]:
    return [lam / (2.0 * math.sin(math.radians(tt / 2.0)))
            for tt in SI_CU_TWO_THETA]


def _two_theta_at(d_list, lam: float) -> list[float]:
    out = []
    for d in d_list:
        s = lam / (2.0 * d)
        if s >= 1.0:
            continue
        out.append(2.0 * math.degrees(math.asin(s)))
    return out


def _pattern(lam: float, sigma: float = 0.12) -> XRDData:
    d = _d_spacings()
    tt_peaks = _two_theta_at(d, lam)
    two_theta = np.linspace(max(5.0, min(tt_peaks) - 6.0),
                            min(120.0, max(tt_peaks) + 6.0), 4000)
    intensity = np.zeros_like(two_theta)
    for tt, amp in zip(tt_peaks, SI_INTENSITY[:len(tt_peaks)]):
        intensity += amp * np.exp(-0.5 * ((two_theta - tt) / sigma) ** 2)
    intensity += 5.0
    return XRDData(two_theta=two_theta, intensity=intensity, wavelength=lam)


@pytest.fixture(scope="module")
def identifier():
    return PhaseIdentifier()


class TestEffectiveWavelength:

    def test_prefers_data_wavelength(self, identifier):
        data = XRDData(two_theta=np.linspace(10, 80, 100),
                       intensity=np.ones(100), wavelength=1.78897)
        assert identifier._effective_wavelength(data) == pytest.approx(1.78897)

    @pytest.mark.parametrize("bad", [None, 0.0, -1.0, "abc"])
    def test_falls_back_to_config(self, identifier, bad):
        data = XRDData(two_theta=np.linspace(10, 80, 100),
                       intensity=np.ones(100))
        data.wavelength = bad      # 模拟加载器未解析出靶材
        assert identifier._effective_wavelength(data) == pytest.approx(
            identifier._config.default_wavelength)

    def test_none_data_falls_back(self, identifier):
        assert identifier._effective_wavelength(None) == pytest.approx(
            identifier._config.default_wavelength)


class TestPhasesAtWavelength:

    def test_cu_returns_original_list(self, identifier):
        """Cu 基准 → 零开销直接返回原列表（保证 Cu 结果逐位不变）。"""
        assert identifier._phases_at_wavelength(CU) is identifier._phase_database

    @pytest.mark.parametrize("lam", [1.78897, 1.93604, 0.70930])
    def test_conversion_preserves_d(self, identifier, lam):
        """换算后每条峰的 d 值必须与 Cu 基准一致。"""
        ref = identifier._phase_database
        conv = identifier._phases_at_wavelength(lam)
        assert conv, "参考库非空"
        by_name = {p.name: p for p in conv}
        checked = 0
        for phase in ref:
            target = by_name.get(phase.name)
            if target is None:
                continue
            for (_, tt_ref, _), (_, tt_new, _) in zip(
                    phase.reference_peaks, target.reference_peaks):
                d_ref = CU / (2.0 * math.sin(math.radians(tt_ref / 2.0)))
                s = math.sin(math.radians(tt_new / 2.0))
                if s <= 0:
                    continue
                d_new = lam / (2.0 * s)
                assert d_new == pytest.approx(d_ref, rel=1e-6)
                checked += 1
            if checked > 100:
                break
        assert checked > 50, "至少校验 50 条峰"

    def test_conversion_is_cached(self, identifier):
        a = identifier._phases_at_wavelength(1.78897)
        b = identifier._phases_at_wavelength(1.78897)
        assert a is b

    def test_unreachable_peaks_dropped(self, identifier):
        """短波长下 sinθ 全部可达；超长波长应丢弃不可达峰而非留 NaN。"""
        conv = identifier._phases_at_wavelength(6.0)
        for phase in conv:
            for _, tt, _ in phase.reference_peaks:
                assert 0.0 < tt <= 180.0


class TestIdentifyNonCuTarget:
    """端到端: 非 Cu 靶合成谱必须把 Silicon 认成 Top-1。"""

    @pytest.mark.parametrize("anode", ["Cu", "Co", "Fe", "Cr", "Mo"])
    def test_silicon_top1(self, identifier, anode):
        lam = ANODES[anode]
        data = _pattern(lam)
        results = identifier.identify(data, top_n=5, tolerance=0.20)
        assert results, f"{anode} 靶: 无任何候选"
        names = [r.phase.name for r in results]
        assert "Silicon" in names, f"{anode} 靶: Silicon 不在候选 {names[:5]}"
        assert results[0].phase.name == "Silicon", (
            f"{anode} 靶: Top-1 是 {results[0].phase.name}，期望 Silicon")
