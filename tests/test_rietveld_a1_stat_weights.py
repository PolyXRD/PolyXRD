"""
v0.11.0 R-A1: 统计权重 (目标函数与 wR 自洽, opt-in) 测试
======================================================
v1.1.2 起**默认启用 poisson** (指标口径修正: Rexp/GOF 需统计权才有意义);
显式传 stat_weights="none" 可退回旧的单位权行为.
启用后 residual 乘 sqrt(w), 全部 _calc_wR 调用带同一组 w —
即 docs/精修算法改进方案.md A1 的"同一组权重、同一 y 基准"自洽要求.

覆盖:
1. 默认启用 → fit_params["stat_weights"] == "poisson"
2. 非法 mode 字符串 → 静默回退 "none"
3. poisson/poirier 启用 → 拟合完成, wR 有限, mode 记录正确
4. 权重真实生效: 同一拟合结果下 weighted wR ≠ unweighted wR
5. 异方差噪声 (σ∝√y) 合成数据: poirier 相对 none 不显著恶化
6. 与 R-A4 组合 (stat_weights + bg_chebyshev_deg) 数值稳定
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


def _cubic_si_phase() -> Phase:
    return Phase(
        name="Si", formula="Si",
        lattice=LatticeParams(a=5.431, b=5.431, c=5.431),
        weight_fraction=100.0,
        reference_peaks=[
            ((1, 1, 1), 28.44, 100),
            ((2, 2, 0), 47.30, 60),
            ((3, 1, 1), 56.11, 35),
            ((4, 0, 0), 69.13, 15),
        ],
    )


def _heteroscedastic_si(seed: int = 7, bg_level: float = 20.0) -> XRDData:
    """立方 Si 谱 + 泊松型噪声 (σ ∝ √y) — 统计权的目标场景"""
    rng = np.random.default_rng(seed)
    tt = np.linspace(20, 80, 500)
    y_true = np.full_like(tt, bg_level)
    for c, a in [(28.44, 400), (47.30, 240), (56.11, 140), (69.13, 60)]:
        y_true += a * np.exp(-0.5 * ((tt - c) / 0.12) ** 2)
    # Poisson 噪声: σ = sqrt(y)
    y = rng.poisson(np.maximum(y_true, 0)).astype(float)
    return XRDData(two_theta=tt, intensity=y)


class TestStatWeightsDefaults:

    def test_default_is_poisson(self):
        """v1.1.2: 默认统计权改为 poisson (Rexp/GOF 需统计权才可解读)"""
        r = RietveldRefiner().refine(_heteroscedastic_si(), [_cubic_si_phase()],
                                     engine="builtin", max_cycles=5)
        assert r.fit_params["stat_weights"] == "poisson"
        assert r.metrics_valid is True
        assert np.isfinite(r.wR)

    def test_explicit_none_marks_metrics_invalid(self):
        """显式单位权 → Rexp/GOF 不可解读 (指标有效性标志)"""
        r = RietveldRefiner().refine(_heteroscedastic_si(), [_cubic_si_phase()],
                                     engine="builtin", max_cycles=5,
                                     stat_weights="none")
        assert r.fit_params["stat_weights"] == "none"
        assert r.metrics_valid is False
        assert r.metric_note

    def test_invalid_mode_falls_back_to_none(self):
        r = RietveldRefiner().refine(_heteroscedastic_si(), [_cubic_si_phase()],
                                     engine="builtin", max_cycles=5,
                                     stat_weights="bogus")
        assert r.fit_params["stat_weights"] == "none"

    @pytest.mark.parametrize("mode", ["poisson", "poirier"])
    def test_enabled_modes_complete(self, mode):
        r = RietveldRefiner().refine(_heteroscedastic_si(), [_cubic_si_phase()],
                                     engine="builtin", max_cycles=5,
                                     stat_weights=mode)
        assert r.fit_params["stat_weights"] == mode
        assert np.isfinite(r.wR)
        assert len(r.phases) == 1
        assert 0 <= r.phases[0].weight_fraction <= 100


class TestStatWeightsTakeEffect:

    def test_weighted_wr_differs_from_unweighted(self):
        """同一模拟谱下 weighted wR ≠ unweighted wR → 证明权重真的进了 wR"""
        rr = RietveldRefiner()
        data = _heteroscedastic_si()
        tt, y = data.two_theta, data.intensity
        sim = np.full_like(tt, 25.0)  # 任意非峰谱
        bg = rr._estimate_background(y, "median", wide_window=True)

        var = np.maximum(y, 1.0) + np.maximum(bg, 0.0)
        w = 1.0 / var
        w = w / float(np.mean(w))

        wr_u = rr._calc_wR(y, sim + bg)
        wr_w = rr._calc_wR(y, sim + bg, weight=w)
        assert abs(wr_w - wr_u) > 0.5, \
            f"weighted ({wr_w:.3f}) 与 unweighted ({wr_u:.3f}) 几乎相同 — 权重未生效?"

    def test_poisson_and_poirier_differ(self):
        """两种 mode 的 wR 不同 (poirier 在低强度区权更低)"""
        data = _heteroscedastic_si(seed=11)
        r_p = RietveldRefiner().refine(data, [_cubic_si_phase()],
                                       engine="builtin", max_cycles=5,
                                       stat_weights="poisson")
        r_q = RietveldRefiner().refine(data, [_cubic_si_phase()],
                                       engine="builtin", max_cycles=5,
                                       stat_weights="poirier")
        assert abs(r_p.wR - r_q.wR) > 1e-6


class TestStatWeightsQuality:

    def test_poirier_not_worse_on_heteroscedastic(self):
        """异方差噪声数据上 poirier 拟合质量不显著劣化

        注意口径: poirier 报告的 wR 是加权 wR, 与 none 的非加权 wR
        不可直接比较. 公平做法 = 对两者的 simulated_data 都算
        **非加权** wR 再对比 (容忍 ≤ +30%: 统计权刻意偏重弱点的
        基线噪声区, 非加权指标略升是设计内行为, 大幅上升才是 bug).
        """
        rr = RietveldRefiner()
        r_off = RietveldRefiner().refine(_heteroscedastic_si(seed=3),
                                         [_cubic_si_phase()],
                                         engine="builtin", max_cycles=8,
                                         stat_weights="none")
        r_on = RietveldRefiner().refine(_heteroscedastic_si(seed=3),
                                        [_cubic_si_phase()],
                                        engine="builtin", max_cycles=8,
                                        stat_weights="poirier")
        y = np.asarray(r_off.observed_data[1])
        wr_off_u = rr._calc_wR(y, np.asarray(r_off.simulated_data[1]))
        wr_on_u = rr._calc_wR(y, np.asarray(r_on.simulated_data[1]))
        assert wr_on_u <= wr_off_u * 1.30 + 3.0, \
            f"poirier 非加权 wR={wr_on_u:.2f} 显著差于 none={wr_off_u:.2f}"

    def test_stat_weights_plus_chebyshev_stable(self):
        """R-A1 与 R-A4 同时启用: 数值稳定, 不抛异常"""
        r = RietveldRefiner().refine(_heteroscedastic_si(seed=5),
                                     [_cubic_si_phase()],
                                     engine="builtin", max_cycles=6,
                                     stat_weights="poirier",
                                     bg_chebyshev_deg=4)
        assert np.isfinite(r.wR)
        assert r.fit_params["stat_weights"] == "poirier"
        assert isinstance(r.fit_params["bg_chebyshev_applied"], bool)

    def test_freeze_scale_still_works_with_weights(self):
        """M14 参数冻结与统计权正交: 冻结 scale 时 opt==init"""
        from polyxrd.models.refinement_options import RefineOptions
        r = RietveldRefiner().refine(_heteroscedastic_si(seed=9),
                                     [_cubic_si_phase()],
                                     engine="builtin", max_cycles=6,
                                     stat_weights="poisson",
                                     options=RefineOptions(refine_scale=False))
        fp = r.fit_params
        assert abs(fp["opt_scale"] - fp["init_scale"]) < 1e-6
        assert np.isfinite(r.wR)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
