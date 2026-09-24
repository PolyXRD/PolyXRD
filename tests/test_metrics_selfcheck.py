"""指标自检 (改进手册 v3 / M0-W00)
=================================
把"评价指标公式对不对"变成可自动断言。目标口径 (全谱含背景, 原始计数):

    w_i      = 1/σ_i²              (未归一化; poisson: σ² = max(y,1))
    Rwp      = 100·sqrt(Σw(y_o-y_c)² / Σw·y_o²)     ← 与 w 的整体尺度无关
    Rexp     = 100·sqrt((N-P) / Σw·y_o²)
    GOF      = Rwp / Rexp = sqrt(chi2_red)
    chi2     = Σw(y_o-y_c)² ; chi2_red = chi2/(N-P)
    Rp       = 100·Σ|y_o-y_c| / Σ y_o              ← 轮廓R (旧代码误称 Rb)

本文件是 M1 (W02/W03) 的验收基准:
  - W00 时: 断言 1 应通过 (Rwp 本就与权重尺度无关), 2~6 应失败。
  - W02/W03 之后: 6 条全绿。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.services.rietveld_refiner import RietveldRefiner


def _metrics(observed, simulated, sigma2=None, n_params=0) -> dict:
    """按目标签名调用；旧签名 (无 sigma2) 时回退，便于 W00 观察真实失败面。"""
    fn = RietveldRefiner._calc_profile_metrics
    try:
        return fn(observed, simulated, sigma2=sigma2, n_params=n_params)
    except TypeError:
        return fn(observed, simulated, n_params=n_params)


def _poisson_var(y) -> np.ndarray:
    return np.maximum(np.asarray(y, dtype=float), 1.0)


def _synthetic(seed: int = 3, n: int = 2000, bg: float = 120.0):
    """背景 + 两个高斯峰的"真值"谱 (计数)。返回 (tt, y_true, y_obs)。"""
    rng = np.random.default_rng(seed)
    tt = np.linspace(20.0, 80.0, n)
    y_true = np.full_like(tt, bg)
    for c, a, w in ((28.44, 900.0, 0.12), (47.30, 500.0, 0.14)):
        y_true = y_true + a * np.exp(-0.5 * ((tt - c) / w) ** 2)
    y_obs = rng.poisson(np.maximum(y_true, 0.0)).astype(float)
    return tt, y_true, y_obs


class TestRwp:

    def test_rwp_is_scale_invariant(self):
        """y→c·y 时 Rwp 不变 (Rwp 与权重/强度的整体尺度无关)。"""
        _, _, y = _synthetic(seed=1)
        sim = y * 0.9 + 5.0
        for c in (0.37, 1.0, 12.5):
            base = _metrics(y, sim, sigma2=None)["Rwp"]
            scaled = _metrics(c * y, c * sim, sigma2=None)["Rwp"]
            assert abs(base - scaled) < 1e-6, f"c={c}: {base} vs {scaled}"


class TestRexp:

    def test_rexp_matches_analytic_value_with_poisson_weights(self):
        """完美拟合 + Poisson 权 + P=0 → Rexp = 100·sqrt(N/Σy)。"""
        _, _, y = _synthetic(seed=2)
        n = y.size
        expect = 100.0 * np.sqrt(n / float(np.sum(y)))
        got = _metrics(y, y.copy(), sigma2=_poisson_var(y), n_params=0)["Rexp"]
        assert abs(got - expect) / expect < 1e-3, f"Rexp={got} 期望≈{expect}"

    def test_rexp_follows_inverse_sqrt_of_count_scale(self):
        """计数标尺 y→c·y (σ² 同步放大) → Rexp → Rexp/sqrt(c)。"""
        _, _, y = _synthetic(seed=4)
        sim = y * 0.95
        base = _metrics(y, sim, sigma2=_poisson_var(y))["Rexp"]
        for c in (4.0, 25.0):
            scaled = _metrics(c * y, c * sim, sigma2=_poisson_var(c * y))["Rexp"]
            assert abs(scaled - base / np.sqrt(c)) / base < 1e-2, \
                f"c={c}: {scaled} vs {base / np.sqrt(c)}"


class TestGof:

    def test_gof_near_one_when_model_is_truth(self):
        """模型=真值 + Poisson 噪声 + Poisson 权 → GOF ≈ 1。"""
        _, y_true, y_obs = _synthetic(seed=5)
        m = _metrics(y_obs, y_true, sigma2=_poisson_var(y_obs))
        assert 0.8 <= m["GOF"] <= 1.3, f"GOF={m['GOF']:.3f} 超出 [0.8, 1.3]"

    def test_chi2_red_equals_gof_squared(self):
        _, y_true, y_obs = _synthetic(seed=6)
        m = _metrics(y_obs, y_true, sigma2=_poisson_var(y_obs))
        assert "chi2_red" in m, "缺少 chi2_red 键 (W02 需实现)"
        assert abs(m["chi2_red"] - m["GOF"] ** 2) < 1e-9
        assert m["chi2_red"] > 0


class TestProfileR:

    def test_rp_matches_formula(self):
        """Rp = 100·Σ|y_o-y_c| / Σ y_o (不加权, 单位权下与权重无关)。"""
        y_o = np.array([10.0, 20.0, 30.0, 40.0])
        y_c = np.array([12.0, 18.0, 33.0, 37.0])
        expect = 100.0 * np.sum(np.abs(y_o - y_c)) / np.sum(y_o)
        m = _metrics(y_o, y_c, sigma2=None)
        assert "Rp" in m, "缺少 Rp 键 (W02 需实现)"
        assert abs(m["Rp"] - expect) < 1e-9, f"Rp={m.get('Rp')} 期望 {expect}"


class TestQualityGrade:
    """W07: 质量分级统一到一处 (实验室粉末 XRD 口径)"""

    def test_thresholds_lab_xrd(self):
        from polyxrd.models.refinement import RefinementResult, quality_grade_for
        # 阈值: <5 优秀 / <10 良好 / <15 一般 / <25 差 / >=25 需改进
        assert quality_grade_for(3.0) == quality_grade_for(4.99)
        assert quality_grade_for(4.99) != quality_grade_for(5.0)
        assert quality_grade_for(9.99) != quality_grade_for(10.0)
        assert quality_grade_for(14.99) != quality_grade_for(15.0)
        assert quality_grade_for(24.99) != quality_grade_for(25.0)
        # 与属性一致 (单一入口, 不允许两套分级)
        for wr in (3.0, 7.0, 12.0, 20.0, 40.0):
            assert RefinementResult(wR=wr).quality_grade == quality_grade_for(wr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
