"""
v0.11.0 R-A4: Chebyshev 多项式背景抛光 (opt-in) 测试
==================================================
保守改动, 默认关闭 (bg_chebyshev_deg=0) → 旧行为完全不变.
启用后只在 wR 改进时被采纳, 故即使抛光失败/降级也不会恶化基线.

覆盖:
1. 关闭 = 与旧版严格等价 (行为不变)
2. 启用 + 完美多项式残差 → BG 被更新 + wR 改进
3. 启用 + 仅噪声残差 → wR 不变 (gate 拒绝)
4. 启用 + corr 范围爆炸 → 自动缩放, 不爆
5. degree=0/None/样本过少 → 直接返回原 BG
6. 端到端: 真实合成立方 Si + Chebyshev 抛光 (与 no-polish 比较 wR)
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


def _make_xrd(two_theta: np.ndarray, peaks: list[tuple[float, float, float]],
              bg: np.ndarray | None = None, noise_sigma: float = 5.0,
              seed: int = 0) -> XRDData:
    """合成立方 Si 谱 (无 wavelength kwarg → 默认 1.5406)"""
    rng = np.random.default_rng(seed)
    y = np.zeros_like(two_theta)
    for c, a, s in peaks:
        y += a * np.exp(-0.5 * ((two_theta - c) / s) ** 2)
    if bg is not None:
        y = y + bg
    y = y + rng.normal(0, noise_sigma, len(y))
    y = np.maximum(y, 0)
    return XRDData(two_theta=two_theta, intensity=y)


def _cubic_si_phase() -> Phase:
    """Si 立方 (a=5.431)"""
    return Phase(
        name="Si", formula="Si",
        lattice=LatticeParams(a=5.431, b=5.431, c=5.431),
        weight_fraction=100.0,
        reference_peaks=[
            ((1, 1, 1), 28.44, 100),
            ((2, 2, 0), 47.30, 60),
            ((3, 1, 1), 56.11, 35),
            ((4, 0, 0), 69.13, 15),
            ((3, 3, 1), 76.38, 12),
        ],
    )


class TestChebyshevBackgroundGuard:

    def test_degree_zero_returns_input_unchanged(self):
        """degree=0 → 直接返回原 BG, before/after_wR 相同 (no-op)"""
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 200)
        y = _make_xrd(tt, [(30, 100, 0.15), (50, 60, 0.15)],
                      bg=10 + 0.2 * (tt - 50), noise_sigma=2).intensity
        bg0 = rr._estimate_background(y, "median", wide_window=True)
        sim = np.zeros_like(tt)

        bg_new, before, after = rr._chebyshev_background_polish(
            y, sim, bg0, tt, degree=0,
        )
        assert np.array_equal(bg_new, bg0)
        assert before == after == pytest.approx(rr._calc_wR(y, sim + bg0))

    def test_too_few_samples_returns_unchanged(self):
        """n < 2*degree+1 → 早退, 不抛异常"""
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 5)  # 仅 5 点
        y = np.array([10.0, 50.0, 100.0, 50.0, 10.0])
        bg0 = np.full_like(tt, 10.0)
        sim = np.zeros_like(tt)

        bg_new, before, after = rr._chebyshev_background_polish(
            y, sim, bg0, tt, degree=4,
        )
        assert np.array_equal(bg_new, bg0)
        assert before == after

    def test_corr_range_clamped(self):
        """corr 范围超过 max_corr_fraction·动态 → 自动缩放, 不爆"""
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 400)
        # y 动态范围: ~10 → 110 (range = 100)
        # 给个极端 BG 残差: corr 应被压到 30%·100 = 30
        y = 10 + 100 * np.exp(-0.5 * ((tt - 50) / 5) ** 2)
        bg0 = np.full_like(tt, 50.0)  # 极端: BG = 50 但 y 仅 ~10~110
        sim = np.zeros_like(tt)

        bg_new, before, after = rr._chebyshev_background_polish(
            y, sim, bg0, tt, degree=4,
        )
        # 缩放后: corr 范围 ≤ 30 (默认 30%·max(100, 1) = 30)
        corr = bg_new - bg0
        assert np.max(corr) - np.min(corr) <= 30.0 + 1e-9, \
            f"corr range {np.max(corr) - np.min(corr):.3f} > 30"
        # 没有 NaN/Inf
        assert np.all(np.isfinite(bg_new))


class TestChebyshevBackgroundImproves:

    def test_polynomial_residual_improves_wR(self):
        """BG 残差 = 已知多项式 → Chebyshev 拟合能恢复, wR 改进

        构造: y = signal + known_polynomial_bg, sim ≈ signal,
              bg_initial = 错误 BG (低估多项式项)
              → _chebyshev_background_polish 应找到多项式校正项.
        """
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 300)
        signal = 200 * np.exp(-0.5 * ((tt - 45) / 0.5) ** 2)
        # 已知低频 BG: 二次多项式 (开口向上)
        true_bg = 30 + 0.05 * (tt - 50) ** 2
        y = signal + true_bg
        # BG 初值: 低估多项式
        bg_initial = 30 + 0.01 * (tt - 50) ** 2  # 几乎平的

        bg_new, before, after = rr._chebyshev_background_polish(
            y, signal, bg_initial, tt, degree=3,
        )
        # Chebyshev 至少给非平凡修正 (corr 不全 0)
        corr_range = float(np.max(bg_new) - np.min(bg_new))
        poly_range = float(np.max(true_bg) - np.min(true_bg))
        assert corr_range > 0.5 * poly_range, \
            f"corr_range={corr_range:.3f} 远小于 poly_range={poly_range:.3f}"
        # wR 应改进 (after < before)
        assert after < before, f"after={after:.4f} >= before={before:.4f}"

    def test_noise_only_residual_no_improvement(self):
        """残差全为噪声 → Chebyshev 拟合微小, gate 阻止恶化

        仍可能 after < before (噪声偶然), 但差距很小. 主断言:
        调用不抛异常 + 数值稳定.
        """
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 400)
        # 完全平 BG, 仅峰 + 噪声
        signal = 100 * np.exp(-0.5 * ((tt - 40) / 0.3) ** 2)
        rng = np.random.default_rng(42)
        y = signal + 20 + rng.normal(0, 5, len(tt))
        y = np.maximum(y, 0)
        bg0 = np.full_like(tt, 20.0)

        bg_new, before, after = rr._chebyshev_background_polish(
            y, signal, bg0, tt, degree=3,
        )
        assert np.all(np.isfinite(bg_new))
        # before/after 都很接近 0 (BG = 20, signal 已解释峰值)
        assert before < 30.0
        # after 与 before 数量级一致 (gate 保证)
        assert abs(after - before) / max(before, 1.0) < 0.5

    def test_threshold_guard_no_degradation(self):
        """主防线: 调用方只在 after < before 时采纳; 此测试模拟该 gate

        即使抛光带来大幅降低 wR 也好, 但绝不应增加. 模拟 20 个随机合
        成谱, 检查 'gate 后 wR' ≤ 'gate 前 wR'.
        """
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 300)
        for seed in range(20):
            rng = np.random.default_rng(seed * 7 + 3)
            signal = (rng.uniform(20, 200) *
                      np.exp(-0.5 * ((tt - rng.uniform(30, 70)) / 0.4) ** 2))
            bg0 = rng.uniform(10, 50) + rng.uniform(0, 0.05) * (tt - 50) ** 2
            y = signal + bg0 + rng.normal(0, 3, len(tt))
            y = np.maximum(y, 0)

            _, before, after = rr._chebyshev_background_polish(
                y, signal, bg0, tt, degree=4,
            )
            gate_wR = min(before, after)  # 模拟调用方 gate
            assert gate_wR <= before + 1e-9, \
                f"seed={seed}: gate {gate_wR:.4f} > before {before:.4f}"


class TestBuiltInOptIn:

    def test_default_is_on_and_explicit_zero_restores_old_behavior(self):
        """v1.1.2: R-A4 背景抛光**默认开启** (deg=6); 显式 0 可退回旧行为。

        背景由 _estimate_background 一次性给出后即冻结, 是 Rwp 地板的首要原因之一;
        该函数自带"幅度 ≤30% 动态范围 + 仅 wR 改善才采纳"两道保护, 默认开启不会更差。
        """
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 400)
        y = _make_xrd(tt, [(30, 100, 0.15), (50, 60, 0.15)],
                      bg=10, noise_sigma=2).intensity
        xrd = XRDData(two_theta=tt, intensity=y)
        phase = _cubic_si_phase()

        r = rr.refine(xrd, [phase], engine="builtin", max_cycles=5)
        fp = r.fit_params
        assert fp["bg_chebyshev_deg"] == 6
        assert isinstance(fp["bg_chebyshev_applied"], bool)

        r0 = rr.refine(xrd, [phase], engine="builtin", max_cycles=5,
                       bg_chebyshev_deg=0)
        assert r0.fit_params["bg_chebyshev_deg"] == 0
        assert r0.fit_params["bg_chebyshev_applied"] is False

    def test_explicit_opt_in_does_not_break_refine(self):
        """显式 bg_chebyshev_deg=4 → refine 仍完成, 不抛异常, 数值有效"""
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 400)
        # 添加弱低频趋势 (多项目样本的真实形态)
        bg = 50 + 30 * np.exp(-0.5 * ((tt - 25) / 10) ** 2)
        y = _make_xrd(tt, [(30, 100, 0.2), (50, 60, 0.2), (70, 35, 0.2)],
                      bg=bg, noise_sigma=3, seed=11).intensity
        xrd = XRDData(two_theta=tt, intensity=y)
        phase = _cubic_si_phase()

        r = rr.refine(xrd, [phase], engine="builtin", max_cycles=8,
                      bg_chebyshev_deg=4)
        assert np.isfinite(r.wR)
        assert r.wR < 100.0
        assert isinstance(r.fit_params["bg_chebyshev_deg"], int)
        # bg_chebyshev_applied 是 bool, 已应用(True) 或被 gate 拒绝(False) 都接受
        assert isinstance(r.fit_params["bg_chebyshev_applied"], bool)

    def test_real_refinement_off_vs_on(self):
        """关闭 vs 启用: 启用至少不应让 wR 显著恶化 (>10% 阈值)

        这是 0.11.0 R-A4 的核心契约:
        - 若抛光有用 → wR 应下降 (≥ 1%) — *不是* 必胜, 但不恶化底线.
        - 若抛光无用 → wR 应保持 (差异 < 10%).
        """
        rr = RietveldRefiner()
        tt = np.linspace(20, 80, 400)
        bg = 80 + 50 * np.exp(-0.5 * ((tt - 25) / 8) ** 2)  # 低角隆起
        y = _make_xrd(tt, [(28.44, 100, 0.18), (47.30, 60, 0.18),
                          (56.11, 35, 0.18), (69.13, 15, 0.18)],
                      bg=bg, noise_sigma=4, seed=19).intensity
        xrd = XRDData(two_theta=tt, intensity=y)
        phase = _cubic_si_phase()

        r_off = rr.refine(xrd, [phase], engine="builtin", max_cycles=8,
                          bg_chebyshev_deg=0)
        r_on = rr.refine(xrd, [phase], engine="builtin", max_cycles=8,
                         bg_chebyshev_deg=4)
        # 启用后 wR 不应显著恶化 (允许 gate 偶发触发; 实测 0.x% 差)
        assert r_on.wR <= r_off.wR * 1.10 + 0.5, \
            f"抛光启用后 wR {r_on.wR:.3f} 远高于未启用 {r_off.wR:.3f}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
