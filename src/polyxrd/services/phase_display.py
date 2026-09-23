"""
物相显示服务 (M21)
==================
Match! 式多相叠加展示所需的纯逻辑层 (与 GUI 解耦, 可单测)。

模块组成:
  - phase_color(i)          : 相位色板 (取模循环)
  - assign_peaks()          : 双向峰归属 → 每实验峰的 PeakAssignment + 参考峰命中表
  - spectrum_from_refs()    : 从参考峰合成谱内核 (与 RietveldRefiner 共用)
  - combined_pattern()      : 选中相的联合计算谱 (显示/残差用)
  - residual()              : 残差 (实验 − 计算)

不依赖任何 Qt / matplotlib, 纯 numpy + 数据模型。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from polyxrd.models.peak import Peak
from polyxrd.models.phase import Phase

# ── 相位色板 ──────────────────────────────────────────────
# 高区分度 8 色, 顺序稳定 (先选相取索引小者)。
PHASE_PALETTE: tuple[str, ...] = (
    "#E53935",  # 红
    "#1E88E5",  # 蓝
    "#43A047",  # 绿
    "#FB8C00",  # 橙
    "#8E24AA",  # 紫
    "#00ACC1",  # 青
    "#6D4C41",  # 棕
    "#546E7A",  # 蓝灰
)

# 视觉元素固定色 (不随相数变化)
COLOR_EXP = "#1a1a1a"      # 实验谱 (黑)
COLOR_CALC = "#D32F2F"     # 计算谱 (红)
COLOR_RESIDUAL = "#9E9E9E" # 残差 (灰)
COLOR_UNMATCHED = "#F44336"  # 未解释峰 (红▼)


def phase_color(i: int) -> str:
    """第 i 个选中相的显示颜色; i<0 或超界取模循环, 恒返回色板成员。"""
    return PHASE_PALETTE[i % len(PHASE_PALETTE)]


# ── 双向峰归属 ────────────────────────────────────────────

@dataclass
class PeakAssignment:
    """一个实验峰在"选中相集合"中的归属结果。

    phase_index=None ⇔ 未被任何选中相解释 → 残差峰 (未匹配)。
    """
    two_theta: float
    intensity: float
    d_spacing: float
    phase_index: Optional[int]
    phase_name: str
    ref_two_theta: Optional[float]
    delta_2theta: Optional[float]
    hkl: Optional[tuple] = None


def _ref_peak_list(phase: Phase) -> list:
    """取一相的参考峰 ([(hkl, 2θ, I), ...]); 无方法/为空则容错为空。"""
    refs = phase.get_reference_peaks() if hasattr(phase, "get_reference_peaks") else []
    if not refs:
        refs = getattr(phase, "reference_peaks", [])
    return refs or []


def assign_peaks(
    exp_peaks: list[Peak],
    phases: list[Phase],
    tolerance: float = 0.30,
) -> tuple[list[PeakAssignment], list[list[bool]]]:
    """双向峰归属。

    正向 (沿用现有语义, 供参考峰命中布尔表): 每个选中相的每条参考峰 →
      是否存在 |Δ2θ|≤tolerance 的实验峰。
    反向 (残差峰判定): 每个实验峰 → 在所有选中相的参考峰里取 |Δ2θ|≤tolerance
      且最小者归属; 一个实验峰只归属一个相。

    返回:
      assignments : 每实验峰一个 PeakAssignment (顺序与 exp_peaks 一致)
      ref_hit     : ref_hit[p][r] = 第 p 个选中相的第 r 条参考峰是否被任一实验峰命中

    边界:
      - phases 为空 → 全部实验峰 phase_index=None
      - exp_peaks 为空 → ([], [ [] for _ in phases ])
      - 并列最近 → 取 |Δ| 更小; 仍并列取相下标小者 (确定性)
      - 同一条参考峰可被多个实验峰命中 (布尔表只记"是否")
    """
    if not phases:
        return [
            PeakAssignment(p.two_theta, p.intensity, p.d_spacing,
                           None, "", None, None)
            for p in exp_peaks
        ], []

    # 收集所有参考峰: (phase_idx, order, ref_2θ, hkl, ref_I)
    all_refs: list = []
    refs_per_phase: list = []
    for p_idx, phase in enumerate(phases):
        refs = _ref_peak_list(phase)
        refs_per_phase.append(refs)
        for r_idx, rp in enumerate(refs):
            if len(rp) < 3:
                continue
            hkl = rp[0] if isinstance(rp[0], tuple) else None
            tt = float(rp[1])
            all_refs.append((p_idx, r_idx, tt, hkl, float(rp[2])))

    # 参考峰命中布尔表
    ref_hit: list[list[bool]] = [
        [False] * len(refs_per_phase[p]) for p in range(len(phases))
    ]
    assignments: list[PeakAssignment] = []

    for exp in exp_peaks:
        et = exp.two_theta
        # 找所有选中相中距离最近且 ≤tolerance 的参考峰
        best = None
        best_abs = float("inf")
        best_delta = 0.0
        for p_idx, r_idx, rtt, hkl, _i in all_refs:
            delta = et - rtt
            if abs(delta) > tolerance:
                continue
            if abs(delta) < best_abs or (
                    abs(delta) == best_abs and best is not None
                    and p_idx < best[0]):
                best = (p_idx, r_idx, rtt, hkl)
                best_abs = abs(delta)
                best_delta = delta
        if best is None:
            assignments.append(PeakAssignment(et, exp.intensity, exp.d_spacing,
                                              None, "", None, None))
        else:
            p_idx, _r_idx, rtt, hkl = best
            assignments.append(PeakAssignment(
                et, exp.intensity, exp.d_spacing,
                p_idx, phases[p_idx].name, rtt, float(best_delta), hkl))

    # 布尔表: 每条参考峰只要与任一实验峰 |Δ|≤tol 即命中
    for exp in exp_peaks:
        et = exp.two_theta
        for p_idx, refs in enumerate(refs_per_phase):
            for r_idx, rp in enumerate(refs):
                if len(rp) >= 3 and abs(et - float(rp[1])) <= tolerance:
                    ref_hit[p_idx][r_idx] = True
    return assignments, ref_hit


# ── 谱合成内核 (与 RietveldRefiner._compute_spectrum_from_ref 共用) ──

def spectrum_from_refs(
    two_theta: np.ndarray,
    phase_peaks: list,
    weights,
    fwhm: float,
    eta: float,
    scale: float,
    peak_shape: str = "pseudo-voigt",
    caglioti=None,
    cutoff_fwhm: Optional[float] = 100.0,
) -> np.ndarray:
    """从每相的参考峰合成模拟谱 (峰距截断窗口化)。

    与 RietveldRefiner._compute_spectrum_from_ref 原实现数学等价
    (见该处 v8 说明): 展平参考峰 → 逐峰固定/Caglioti FWHM →
    逐峰在 ``cutoff_fwhm × FWHM`` 窗口内累加 pseudo-voigt/lorentzian/
    gaussian 贡献 → scale×(basis @ weights)。

    v0.15.2 性能改造: 原实现对全部 (点 × 峰) 做全矩阵 (7251 点 ×
    ~3000 峰 ≈ 2×10⁷ 点运算/次评估, 精修雅可比每迭代 21 次评估 →
    小时级)。截断依据: lorentz 分量在 |Δ| = 50×FWHM 处贡献
    g²/Δ² = 2.5×10⁻⁵ (相对峰高), 高斯分量 exp(-0.5×(50×2.355)²) ≈ 0,
    截断误差远低于 wR 的有效精度。``cutoff_fwhm=None`` 退回全矩阵
    路径 (等价旧行为, 供数值一致性验证)。

    参数
    ----
    phase_peaks : list[list[(hkl, 2θ, I)]]  每相的参考峰
    weights     : 每相权重 (长度 = len(phase_peaks), 会逐相广播乘到其贡献上)
    caglioti    : (U,V,W) 或 None; None → 所有峰用固定 fwhm
    cutoff_fwhm : 截断半窗宽 (单位: FWHM 倍数); None → 全矩阵
    """
    n_phases = len(phase_peaks)
    simulated = np.zeros_like(two_theta, dtype=float)
    peak_tt: list[float] = []
    peak_int: list[float] = []
    peak_phase: list[int] = []
    for i, peaks in enumerate(phase_peaks):
        for peak_data in peaks:
            if len(peak_data) < 3:
                continue
            p_2theta = peak_data[1]
            if p_2theta < two_theta[0] or p_2theta > two_theta[-1]:
                continue
            peak_tt.append(p_2theta)
            peak_int.append(peak_data[2])
            peak_phase.append(i)
    if not peak_tt:
        return simulated

    peak_tt = np.asarray(peak_tt, dtype=float)
    peak_int = np.asarray(peak_int, dtype=float)

    if caglioti is not None and any(caglioti):
        U, V, W = caglioti
        tan_p = np.tan(np.radians(peak_tt / 2.0))
        fw_p = np.sqrt(np.clip(U * tan_p * tan_p + V * tan_p + W, 0.0001, None))
    else:
        fw_p = np.full_like(peak_tt, fwhm)

    sigma_all = fw_p / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    gamma2_all = (fw_p / 2.0) ** 2
    # v1.1.2 (W11 面积归一): Rietveld 要求峰**积分强度** ∝ m·LP·|F|²·S, 与峰宽/η 无关。
    # 旧实现的高斯/洛伦兹都是"峰高=1"的写法 → 积分面积 ∝ FWHM, 且 η 从 0→1 让面积
    # 变化 ~47% (η 不再是混合比); Caglioti 一开, 峰宽参数就会被拟合到错误数值。
    # 面积归一后: ∫G = ∫L = 1, ∫PV = η + (1-η) = 1。
    #   G = exp(-Δ²/2σ²)/(σ√(2π));  L = (γ/π)/(Δ²+γ²),  γ = FWHM/2
    #   ∫L = 1 要求 L = (1/π)·γ/(Δ²+γ²) = (1/(π·γ))·(γ²/(Δ²+γ²))
    inv_gauss_norm = 1.0 / (sigma_all * np.sqrt(2.0 * np.pi))
    inv_lorentz_norm = 1.0 / (np.pi * np.sqrt(gamma2_all))
    n_points = len(two_theta)
    basis = np.zeros((n_points, n_phases))
    is_gauss = peak_shape == "gaussian"
    is_lorentz = peak_shape == "lorentzian"
    one_minus_eta = 1.0 - eta

    if cutoff_fwhm is None:
        # 全矩阵路径 (旧行为, 分块向量化), 供一致性验证/兜底
        chunk = 16
        offset = 0
        for i, peaks in enumerate(phase_peaks):
            n_i = 0
            for peak_data in peaks:
                if (len(peak_data) >= 3
                        and two_theta[0] <= peak_data[1] <= two_theta[-1]):
                    n_i += 1
            if n_i == 0:
                continue
            sl = slice(offset, offset + n_i)
            pts_p = peak_tt[sl]
            sigma_p = sigma_all[sl]
            gamma2_p = gamma2_all[sl]
            inten_p = peak_int[sl]
            for s in range(0, n_i, chunk):
                e = min(s + chunk, n_i)
                delta = two_theta[:, None] - pts_p[None, s:e]
                if is_gauss:
                    prof = (np.exp(-0.5 * (delta / sigma_p[None, s:e]) ** 2)
                            * inv_gauss_norm[sl][None, s:e])
                elif is_lorentz:
                    g2 = gamma2_p[None, s:e]
                    prof = (g2 / (delta * delta + g2)) * inv_lorentz_norm[sl][None, s:e]
                else:  # pseudo-voigt
                    gauss = (np.exp(-0.5 * (delta / sigma_p[None, s:e]) ** 2)
                             * inv_gauss_norm[sl][None, s:e])
                    g2 = gamma2_p[None, s:e]
                    lorentz = (g2 / (delta * delta + g2)) * inv_lorentz_norm[sl][None, s:e]
                    prof = eta * gauss + one_minus_eta * lorentz
                prof *= inten_p[None, s:e]
                basis[:, i] += prof.sum(axis=1)
            offset += n_i
        return scale * (basis @ np.asarray(weights, dtype=float))

    # ── 窗口化路径: 逐峰 searchsorted 截断累加 ──
    for j in range(len(peak_tt)):
        t0 = peak_tt[j]
        fw = fw_p[j]
        cut = cutoff_fwhm * fw
        lo = int(np.searchsorted(two_theta, t0 - cut))
        hi = int(np.searchsorted(two_theta, t0 + cut, side="right"))
        if hi <= lo:
            continue
        delta = two_theta[lo:hi] - t0
        if is_gauss:
            prof = (np.exp(-0.5 * (delta / sigma_all[j]) ** 2)
                    * inv_gauss_norm[j])
        elif is_lorentz:
            prof = (gamma2_all[j] / (delta * delta + gamma2_all[j])) * inv_lorentz_norm[j]
        else:  # pseudo-voigt
            gauss = (np.exp(-0.5 * (delta / sigma_all[j]) ** 2)
                     * inv_gauss_norm[j])
            lorentz = (gamma2_all[j] / (delta * delta + gamma2_all[j])) * inv_lorentz_norm[j]
            prof = eta * gauss + one_minus_eta * lorentz
        basis[lo:hi, peak_phase[j]] += peak_int[j] * prof
    return scale * (basis @ np.asarray(weights, dtype=float))


def combined_pattern(
    two_theta: np.ndarray,
    phases: list[Phase],
    weights: Optional[list[float]] = None,
    fwhm: float = 0.15,
    eta: float = 0.5,
    peak_shape: str = "pseudo-voigt",
    scale_to_exp: bool = True,
    y_exp: Optional[np.ndarray] = None,
) -> np.ndarray:
    """选中相的联合计算谱。

    weights None → 等权 1/n。scale_to_exp=True → 峰高对齐 y_exp 最强峰
    (仅显示用; y_exp 缺省时 scale_to_exp 忽略)。

    边界:
      - phases 空 → 全 0
      - two_theta 空 → 空数组
    """
    two_theta = np.asarray(two_theta, dtype=float)
    if two_theta.size == 0 or not phases:
        return np.zeros_like(two_theta)
    n = len(phases)
    if weights is None:
        weights = [1.0 / n] * n
    phase_peaks = [_ref_peak_list(ph) for ph in phases]
    y = spectrum_from_refs(two_theta, phase_peaks, weights,
                           fwhm, eta, 1.0, peak_shape)
    if scale_to_exp and y_exp is not None and len(y_exp) == len(y):
        my = float(np.max(y)) if y.size else 0.0
        me = float(np.max(y_exp)) if y_exp.size else 0.0
        if my > 0 and me > 0:
            y = y * (me / my)
    return y


def residual(y_exp: np.ndarray, y_calc: np.ndarray) -> np.ndarray:
    """残差 = y_exp − y_calc。长度不一致 → ValueError。"""
    y_exp = np.asarray(y_exp, dtype=float)
    y_calc = np.asarray(y_calc, dtype=float)
    if y_exp.shape[0] != y_calc.shape[0]:
        raise ValueError(
            f"长度不一致: y_exp={y_exp.shape[0]}, y_calc={y_calc.shape[0]}")
    return y_exp - y_calc
