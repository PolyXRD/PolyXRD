"""前向模型装配：反射表 × 峰形 × 背景 → 计算谱 / 设计矩阵。

这层只做"给定参数算谱"，不含任何拟合逻辑。它同时给拟合器两样东西：

* ``design_matrix`` —— ``(N, n_phase)`` 的列即"该相单位标度下的谱形"。
  变量投影里 ``y_calc = basis @ scales + bg @ coefs``，两层的线性系数
  一次性 ``lstsq`` 解掉，非线性层只管峰位/峰宽/占位。
* ``synthesize`` —— 直接给完整 ``y_calc``（含背景），供可视化与残差。

性能约定
--------
窗口化累加：每个峰只在 ``±cutoff_fwhm × FWHM`` 内落值，Lorentz 分量在
``|Δ| = 25×FWHM`` 处贡献约 ``2.5e-5``（相对峰高），远低于 wR 的有效精度
（`phase_display` v0.15.2 已论证同档截断不影响 wR）。``cutoff_fwhm=None``
退回全矩阵分块路径，仅供数值一致性验证。

Kα2 的处理顺序：**先**把每条反射裂成 Kα1/Kα2 两条（权重按强度比归一，
总面积守恒），**再**算峰宽。若反过来先合成峰形再位移，峰形会在两条线之间
被重复利用，导致总面积偏大。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

import numpy as np

from .background import BackgroundParams, background_basis
from .profile import (
    Kalpha2,
    ProfileParams,
    area_normalized_profile,
    profile_centers,
    split_asymmetry_factor,
    tch_widths,
)
from .structure import ReflectionTable

__all__ = [
    "PhaseSpec",
    "PhasePattern",
    "phase_pattern",
    "design_matrix",
    "synthesize",
    "reflection_centers_and_intensities",
]

DEFAULT_CUTOFF_FWHM = 25.0


@dataclass(frozen=True)
class PhaseSpec:
    """一相在装配里需要的全部信息（结构表 + 样品层峰形）。

    :param table: ``build_reflections`` 产出的反射表（已含 |F|²·LP·多重性）
    :param size_nm: 该相相干域尺寸（nm），0 = 不限
    :param strain: 该相微观应变 ε，0 = 无
    :param po_r: March–Dollase ``r``，1 = 无择优（走零开销分支）
    """

    table: ReflectionTable
    size_nm: float = 0.0
    strain: float = 0.0
    po_r: float = 1.0

    @property
    def n_reflections(self) -> int:
        return len(self.table)


@dataclass
class PhasePattern:
    """单相峰形评估的中间结果（缓存友好的载体）。"""

    two_theta: np.ndarray
    fwhm: np.ndarray
    eta: np.ndarray
    centers: np.ndarray
    weights: np.ndarray
    is_ka2: np.ndarray
    intensities: np.ndarray
    pattern: np.ndarray = field(default=None)  # type: ignore[assignment]

    @property
    def n_peaks(self) -> int:
        return int(self.centers.size)


def reflection_centers_and_intensities(
    table: ReflectionTable,
    kalph2: Optional[Kalpha2] = None,
    po_r: float = 1.0,
    *,
    shift: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把反射表展开成 ``(centers, intensities, is_ka2)``。

    ``intensities`` 已按 Kα1/Kα2 权重（``w1+w2=1``）与 March–Dollase 重加权，
    **面积守恒**。``po_r=1`` 时走 ``reweight_po`` 的零开销分支。

    :param shift: 整体 2θ 平移（度），用于仪器零位 ``inst.zero``。先平移再拆
        Kα2 —— 零位误差是**仪器**偏移，对 Kα1/Kα2 两条线同等生效。
    """
    tt = np.asarray(table.two_theta, dtype=float)
    if shift:
        tt = tt + float(shift)
    inten = np.asarray(table.reweight_po(po_r), dtype=float)
    if kalph2 is None or not kalph2.separation:
        return tt, inten, np.zeros(tt.shape, dtype=bool)
    w1, w2 = kalph2.component_weights()
    if w2 <= 0.0:
        return tt, inten, np.zeros(tt.shape, dtype=bool)
    centers, split_w, is2 = profile_centers(tt, kalph2)
    # profile_centers 返回的是"面积权重"，乘回强度即得两条线的面积
    out_i = np.concatenate([inten * w1, inten * w2])
    return centers, out_i, is2


def _accumulate(two_theta: np.ndarray, centers: np.ndarray, areas: np.ndarray,
                fwhm: np.ndarray, eta: np.ndarray, params: ProfileParams,
                cutoff_fwhm: Optional[float]) -> np.ndarray:
    """把 ``(centers, areas, fwhm, eta)`` 累加成谱（窗口化）。"""
    n = two_theta.size
    y = np.zeros(n, dtype=float)
    if n == 0 or centers.size == 0:
        return y

    asym = float(params.asymmetry)
    if asym > 1e-12:
        fac = split_asymmetry_factor(centers, asym)
        fw_lo = fwhm * (1.0 + fac)
        fw_hi = fwhm * (1.0 - fac)
    else:
        fw_lo = fw_hi = None

    t_lo = float(two_theta[0])
    t_hi = float(two_theta[-1])

    if cutoff_fwhm is None:
        # 全矩阵分块（一致性验证用）
        chunk = 32
        for s in range(0, centers.size, chunk):
            e = min(s + chunk, centers.size)
            delta = two_theta[:, None] - centers[None, s:e]
            prof = area_normalized_profile(
                delta, fwhm[None, s:e], eta[None, s:e], params.kind,
                None if fw_lo is None else fw_lo[None, s:e],
                None if fw_hi is None else fw_hi[None, s:e],
            )
            y += (prof * areas[None, s:e]).sum(axis=1)
        return y

    for j in range(centers.size):
        c = centers[j]
        if c < t_lo - 50.0 * fwhm[j] or c > t_hi + 50.0 * fwhm[j]:
            continue
        cut = cutoff_fwhm * fwhm[j]
        lo = int(np.searchsorted(two_theta, c - cut))
        hi = int(np.searchsorted(two_theta, c + cut, side="right"))
        if hi <= lo:
            continue
        delta = two_theta[lo:hi] - c
        prof = area_normalized_profile(
            delta, fwhm[j], eta[j], params.kind,
            None if fw_lo is None else fw_lo[j],
            None if fw_hi is None else fw_hi[j],
        )
        y[lo:hi] += areas[j] * prof
    return y


def phase_pattern(
    two_theta,
    spec: PhaseSpec,
    profile: ProfileParams,
    *,
    wavelength: float = 1.54056,
    kalph2: Optional[Kalpha2] = None,
    cutoff_fwhm: Optional[float] = DEFAULT_CUTOFF_FWHM,
    shift: float = 0.0,
    return_detail: bool = False,
):
    """单相"单位标度"计算谱（``scale = 1``）。

    :param two_theta: 采样 2θ 网格（度，须单调递增）
    :param spec: 相描述
    :param profile: 仪器峰形（样品层由 ``spec`` 覆盖）
    :param kalph2: Kα2 描述；None → 只用 Kα1
    :param cutoff_fwhm: 窗口半宽（FWHM 倍数）；None → 全矩阵
    :param shift: 整体 2θ 平移（度），用于仪器零位
    :param return_detail: 为 True 时返回 ``(pattern, PhasePattern)``
    """
    tt = np.asarray(two_theta, dtype=float)
    if tt.size == 0:
        return (np.zeros(0), None) if return_detail else np.zeros(0)

    centers, areas, is2 = reflection_centers_and_intensities(
        spec.table, kalph2, spec.po_r, shift=shift)

    # 样品层（尺寸/应变）叠加到仪器层之上
    p_eff = profile.with_samples(size_nm=spec.size_nm, strain=spec.strain)
    lam = float(wavelength)
    fwhm, eta = tch_widths(centers, lam, p_eff)

    y = _accumulate(tt, centers, areas, fwhm, eta, p_eff, cutoff_fwhm)

    if not return_detail:
        return y
    detail = PhasePattern(
        two_theta=tt, fwhm=fwhm, eta=eta, centers=centers,
        weights=areas, is_ka2=is2, intensities=areas, pattern=y,
    )
    return y, detail


def design_matrix(
    two_theta,
    specs: Sequence[PhaseSpec],
    profile: ProfileParams,
    *,
    wavelength: float = 1.54056,
    kalph2: Optional[Kalpha2] = None,
    cutoff_fwhm: Optional[float] = DEFAULT_CUTOFF_FWHM,
    shift: float = 0.0,
) -> np.ndarray:
    """``(N, n_phase)`` 设计矩阵；列 = 各相单位标度谱。

    变量投影的线性层用它：``y = basis @ scales + bg_basis @ coefs``。
    """
    tt = np.asarray(two_theta, dtype=float)
    n_ph = len(specs)
    out = np.zeros((tt.size, n_ph), dtype=float)
    for i, sp in enumerate(specs):
        out[:, i] = phase_pattern(
            tt, sp, profile, wavelength=wavelength, kalph2=kalph2,
            cutoff_fwhm=cutoff_fwhm, shift=shift,
        )
    return out


def synthesize(
    two_theta,
    specs: Sequence[PhaseSpec],
    scales: Sequence[float],
    profile: ProfileParams,
    *,
    wavelength: float = 1.54056,
    kalph2: Optional[Kalpha2] = None,
    bg_params: Optional[BackgroundParams] = None,
    bg_coefs: Optional[Sequence[float]] = None,
    cutoff_fwhm: Optional[float] = DEFAULT_CUTOFF_FWHM,
    basis: Optional[np.ndarray] = None,
    shift: float = 0.0,
) -> np.ndarray:
    """完整 ``y_calc`` = Σ scale_p·(该相谱) + 背景。

    :param basis: 已算好的设计矩阵（避免重复计算）；列序须与 ``specs`` 一致
    :param shift: 整体 2θ 平移（度），仪器零位
    """
    tt = np.asarray(two_theta, dtype=float)
    n = tt.size
    if n == 0:
        return np.zeros(0)
    y = np.zeros(n, dtype=float)

    if specs:
        b = basis if basis is not None else design_matrix(
            tt, specs, profile, wavelength=wavelength, kalph2=kalph2,
            cutoff_fwhm=cutoff_fwhm, shift=shift)
        sc = np.asarray(scales, dtype=float).reshape(-1)
        if sc.size != b.shape[1]:
            raise ValueError(f"标度个数 {sc.size} 与相数 {b.shape[1]} 不一致")
        y += b @ sc

    if bg_params is not None and bg_params.uses_background and bg_coefs is not None:
        c = np.asarray(bg_coefs, dtype=float).reshape(-1)
        if c.size:
            bg = background_basis(tt, bg_params)
            y += bg @ c
    return y
