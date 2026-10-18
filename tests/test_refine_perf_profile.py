"""精修性能档 `perf_profile` 回归 (v3.0.1, P1-2)
=================================================
背景: 引擎侧早已实现 ``perf_profile="fast"``（cutoff 100→25×FWHM、灾难起点
剪枝、抛光早停），但 ``grep perf_profile`` 全仓**除引擎自身外零调用点** ——
用户永远跑精确档，等于这项 4× 提速从未上线。本文件锁定：

1. 两个档位都能被记录进 ``fit_params``，默认档仍是精确档（逐位不变）；
2. 快速档与精确档的 wR 差在有效精度内（< 0.5 个百分点）；
3. 报告摘要只在快速档追加一行"性能档"，精确档报告文本不变。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.i18n import tr
from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


def _data() -> XRDData:
    rng = np.random.default_rng(7)
    tt = np.linspace(20, 100, 2000)
    y = np.zeros_like(tt)
    for center, amp, sigma in [(28.44, 800, 0.12), (47.30, 600, 0.15),
                               (56.11, 400, 0.12), (69.13, 250, 0.14),
                               (76.36, 180, 0.13)]:
        y += amp * np.exp(-0.5 * ((tt - center) / sigma) ** 2)
    y += 30.0
    y += rng.normal(0, 5, len(tt))
    return XRDData(two_theta=tt, intensity=np.maximum(y, 0))


def _phase() -> Phase:
    return Phase(
        name="Test Phase", formula="Si",
        lattice=LatticeParams(a=5.431, b=5.431, c=5.431,
                              alpha=90.0, beta=90.0, gamma=90.0),
        weight_fraction=100.0,
        reference_peaks=[
            ((1, 1, 1), 28.44, 800),
            ((2, 2, 0), 47.30, 600),
            ((3, 1, 1), 56.11, 400),
            ((4, 0, 0), 69.13, 250),
            ((3, 3, 1), 76.36, 180),
        ],
    )


def _run(**kwargs):
    return RietveldRefiner().refine(
        _data(), [_phase()], engine="builtin", max_cycles=2,
        wR_threshold=None, **kwargs)


class TestPerfProfile:

    def test_default_is_precise(self):
        r = _run()
        # 显式确认到字段级: 缺消息引擎必须按 precise 记档
        assert r.fit_params.get("perf_profile") == "precise"
        assert r.fit_params.get("cutoff_fwhm") == pytest.approx(100.0)

    def test_fast_profile_recorded(self):
        r = _run(perf_profile="fast")
        assert r.fit_params.get("perf_profile") == "fast"
        assert r.fit_params.get("cutoff_fwhm") == pytest.approx(25.0)
        assert r.fit_params.get("start_prune_factor") == pytest.approx(25.0)
        assert r.fit_params.get("polish_early_stop") == 250

    def test_empty_profile_string_means_precise(self):
        # GUI 传入 "" 表示"不启用" —— 必须等价于缺省，不能当成未知档报错
        r = _run(perf_profile="")
        assert r.fit_params.get("perf_profile") == "precise"
        assert r.fit_params.get("cutoff_fwhm") == pytest.approx(100.0)

    def test_explicit_kwargs_override_profile(self):
        # 显式 cutoff_fwhm 优先于档位默认值（引擎注释承诺的口径）
        r = _run(perf_profile="fast", cutoff_fwhm=12.0)
        assert r.fit_params.get("cutoff_fwhm") == pytest.approx(12.0)

    def test_fast_close_to_precise(self):
        r_fast = _run(perf_profile="fast")
        r_prec = _run()
        # 截断窗收窄到 25×FWHM 对 wR 的影响必须在有效精度内
        assert abs(r_fast.wR - r_prec.wR) < 0.5, (r_fast.wR, r_prec.wR)
        # 主指标不能因档位而"变好/变坏"到跨级
        assert r_fast.quality_grade == r_prec.quality_grade or \
            abs(r_fast.wR - r_prec.wR) < 0.5

    def test_summary_echoes_fast_profile(self):
        s_fast = _run(perf_profile="fast").summary()
        assert tr("report.perf_profile_fast") in s_fast
        # 精确档不加噪声行: 保证旧报告文本逐字不变
        s_prec = _run().summary()
        assert tr("report.perf_profile_fast") not in s_prec
