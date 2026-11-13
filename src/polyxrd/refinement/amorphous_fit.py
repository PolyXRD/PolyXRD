# -*- coding: utf-8 -*-
"""非晶含量：全谱分解（宽隆 hump）+ 绝对量换算。

## 为什么需要它

引擎（v5 变量投影）的相标度是**线性层**的自由度，但非晶相没有 Bragg 反射、
也没有结构因子，进不了 ``PhaseSpec`` —— 所以含玻璃/气相 SiO₂ 的试样里，非晶
散射只能被晶体相的峰宽与背景**摊掉**，晶体 wt% 因此系统性偏高（ShiJK 2/3
含普通玻璃、6/7 含沉淀法气相 SiO₂，就是这个情形）。

这里不去改最小二乘的结构（那会把非晶塞进 Hill–Howard，而 Hill–Howard 对非晶
**没有定义**），而是给一个**同层线性**的分解：在收敛后的模型上，把

    [晶体相基列 | 非晶宽隆列 | 背景列]

拼成一个线性最小二乘再解一次。宽隆列按**单位面积**归一化，于是解出的系数
**就是积分面积**，DoC 与面积占比不需要任何额外标定。

## 口径（必须说清楚，否则数字会被误用）

* ``doc_area``：面积口径结晶度 ``A_crystal / (A_crystal + A_amorphous)``。
  **不是质量分数**：非晶与晶体的质量吸收系数不同、且非晶散射的角依赖
  （POLARIS/PDF 意义上的 reduced intensity）与 Bragg 强度不可直接比。
  同一化学组成（如 SiO₂ 玻璃 vs 石英）时二者近似相等，这才是它可用的场合。
* ``amorphous_wt_pct``：只在**有内标定标**时给出（见
  :func:`absolute_amorphous_from_standard`）。原理与结晶度面积比无关：
  内标把每个晶体相的 wt% 定标到"占整个试样"的绝对口径，于是

      W_amorphous = 100 − Σ W_crystal,absolute

  前提是**没有未识别的晶相**（有的话它也落在"非晶"里）。
## 已知边界（实测，别拿它当自动检测器）

* **贪心自动搜索不可信**：ShiJK 的 3 个**全晶**对照（1/4/5，真值无任何非晶）
  用 ``max_humps`` 自动搜索分别"检出" 23.4% / 5.1% / 38.7% 非晶 —— 晶体模型
  的系统失配（峰形、低角背底）足以撑起一条宽隆。所以服务层默认
  ``amorphous_auto=False``，只接受**用户显式给定**的中心/FWHM（``Humps``）。
* **14° 处那条包络是仪器的**：7 个试样（同一台 Rigaku）里有 6 个在 14±1°、
  FWHM 5~6° 长处出现同一条宽隆，全晶样也不例外 → 属于低角背底/气散，不是
  样品非晶。它会稳定地偷走 4~6% 的面积占比。
* **包络压在晶峰上时无法分离**：玻璃包络常与某晶相主峰重合（ShiJK-6 的气相
  SiO₂ 22° ↔ 方石英 21.9°）。事后分解拿不到它（晶体已吸收），必须并进精修
  （``Problem.set_amorphous_humps``）；即便如此，面积仍受晶峰峰形共线影响，
  此时结果里会带一条 "与某晶相强峰重合" 的 note。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "HumpSpec",
    "AmorphousDecomposition",
    "hump_columns",
    "decompose",
    "absolute_amorphous_from_standard",
]

#: 宽隆候选 FWHM（度）。玻璃在 5–15° 量级；太小会去抢晶峰，太大等于改背景
DEFAULT_FWHM_GRID = (5.0, 8.0, 12.0)
#: 候选中心网格步长（度）
CENTER_STEP_DEG = 2.0
#: 接受一个宽隆所需的最小 SSR 相对下降（相对当前模型 SSR）
MIN_GAIN_FRAC = 2.0e-3
#: 宽隆在数据里的峰高至少要是噪声 σ 的多少倍（挡住"完美模型也长宽隆"）
NOISE_K = 3.0
#: 背景缺省多项式阶数（未给 bg_basis 时用 Legendre，避免宽隆抢基线）。
#: 不宜再高：实测同一合成谱上 1 阶→doc 0.652、4 阶→0.640、8 阶→0.584
#: （真值 0.650）—— 背景越灵活，宽隆越会被"抬起来"，DoC 系统性偏低。
#: 真实使用请传精修时的 ``bg_basis``，让两边背景模型一致。
DEFAULT_BG_ORDER = 6
#: 新宽隆与已有宽隆的最小间隔（相对 FWHM）：防止同一包络被拆成两个
MIN_SEP_FWHM = 0.75
#: 宽隆 FWHM 下限（度）。玻璃的第一锐衍射峰（FSDP）通常在 5–10°，低于 4°
#: 就不再是"非晶包络"而是去抢某个晶峰的峰宽 —— 实测 ShiJK-7 无下限时收敛到
#: 3.0°，正好压在方石英 21.9° 主峰上。
MIN_FWHM = 4.0
#: 宽隆中心若落在某晶相强峰的这个相对高度之上（窗口 ±0.6·FWHM），面积不可信
CRYSTAL_COINCIDENCE_REL = 0.15
#: 背景敏感性检验的两个 Legendre 阶数（按 2θ 跨度折算：span/10 与 span/5）。
#: 同一组宽隆在两套背景下的 DoC 之差超过 DOC_SENS_TOL 就判定"不可当结论"——
#: 实测 ShiJK-1（全晶）在两套背景下 DoC 从 0.98 掉到 0.44，说明这个分解在
#: 背景与晶体峰形之间本来就没有唯一解。
DOC_SENS_TOL = 0.05


@dataclass
class HumpSpec:
    """一个非晶宽隆：中心 / FWHM / 混合因子。"""

    center: float
    fwhm: float
    eta: float = 0.5

    def as_dict(self) -> Dict[str, float]:
        return {"center": float(self.center), "fwhm": float(self.fwhm),
                "eta": float(self.eta)}


@dataclass
class AmorphousDecomposition:
    """全谱分解结果。面积均为**窗口内数值积分**，与输入 2θ 轴同口径。"""

    humps: Tuple[HumpSpec, ...]
    hump_areas: Tuple[float, ...]
    crystal_areas: Tuple[float, ...]
    crystal_scales: Tuple[float, ...]
    doc_area: float
    amorphous_area_share: float
    crystal_area_total: float
    hump_area_total: float
    rwp_before: float
    rwp_after: float
    y_crystal: np.ndarray
    y_amorphous: np.ndarray
    y_background: np.ndarray
    notes: List[str] = field(default_factory=list)
    #: 两套背景（Legendre，阶数按跨度折算）下的 DoC；差异大说明分解不唯一
    doc_sensitivity: Tuple[float, ...] = ()
    doc_spread: float = 0.0

    @property
    def rwp_gain_pp(self) -> float:
        return float(self.rwp_before - self.rwp_after)

    @property
    def doc_reliable(self) -> bool:
        """背景敏感性给出的"能不能当结论"判据（没有宽隆时恒 True）。"""
        return bool(self.doc_spread <= DOC_SENS_TOL)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "humps": [h.as_dict() for h in self.humps],
            "hump_areas": [float(v) for v in self.hump_areas],
            "crystal_areas": [float(v) for v in self.crystal_areas],
            "doc_area": float(self.doc_area),
            "amorphous_area_share": float(self.amorphous_area_share),
            "crystal_area_total": float(self.crystal_area_total),
            "hump_area_total": float(self.hump_area_total),
            "rwp_before": float(self.rwp_before),
            "rwp_after": float(self.rwp_after),
            "rwp_gain_pp": float(self.rwp_gain_pp),
            "doc_sensitivity": [float(v) for v in self.doc_sensitivity],
            "doc_spread": float(self.doc_spread),
            "doc_reliable": bool(self.doc_reliable),
            "notes": list(self.notes),
        }


def _pseudo_voigt(x: np.ndarray, center: float, fwhm: float,
                  eta: float) -> np.ndarray:
    """峰高归一的伪 Voigt。"""
    f = max(float(fwhm), 1e-6)
    t = (np.asarray(x, float) - float(center)) / f
    g = np.exp(-4.0 * np.log(2.0) * t * t)
    lor = 1.0 / (1.0 + 4.0 * t * t)
    e = float(np.clip(eta, 0.0, 1.0))
    return e * lor + (1.0 - e) * g


def hump_columns(two_theta, humps: Sequence[HumpSpec],
                 *, unit_area: bool = True) -> np.ndarray:
    """宽隆基矩阵 ``(N, k)``；``unit_area=True`` 时每列在数据窗口内积分为 1。

    单位面积是关键：系数 == 面积，DoC 就不必再乘任何换算因子。
    """
    x = np.asarray(two_theta, dtype=float).reshape(-1)
    cols: List[np.ndarray] = []
    for h in humps:
        col = _pseudo_voigt(x, h.center, h.fwhm, h.eta)
        if unit_area:
            area = float(np.trapezoid(col, x)) if x.size > 1 else 0.0
            if area <= 0.0:
                raise ValueError(f"宽隆中心 {h.center} 落在数据窗口外，无法归一化")
            col = col / area
        cols.append(col)
    if not cols:
        return np.zeros((x.size, 0))
    return np.column_stack(cols)


def _legendre_basis(x: np.ndarray, order: int) -> np.ndarray:
    """归一化到 [-1, 1] 的 Legendre 多项式基（无 numpy.polynomial 依赖问题）。"""
    x = np.asarray(x, float)
    lo, hi = float(x.min()), float(x.max())
    u = 2.0 * (x - lo) / max(hi - lo, 1e-12) - 1.0
    cols = [np.ones_like(u)]
    if order >= 1:
        cols.append(u.copy())
    for n in range(1, int(order)):
        p_prev, p_cur = cols[n - 1], cols[n]
        cols.append(((2 * n + 1) * u * p_cur - n * p_prev) / (n + 1))
    return np.column_stack(cols[: max(1, int(order) + 1)])


def _rwp(y, yc, w) -> float:
    w = np.maximum(np.asarray(w, float), 0.0)
    den = float(np.sum(w * np.asarray(y, float) ** 2))
    if den <= 0.0:
        return 0.0
    return float(100.0 * np.sqrt(np.sum(w * (np.asarray(y, float) - yc) ** 2) / den))


def _solve(crystal, humps, bg, y, w):
    """联合线性解；返回 ``(coef_crystal, coef_hump, y_calc)``。"""
    from .linear import solve_linear

    basis = np.hstack([crystal, humps]) if humps.shape[1] else crystal
    lin = solve_linear(basis, y, weights=w, bg_basis=bg,
                       nonneg_scales=True, diagnose=False)
    coef = np.asarray(lin.scales, float)
    n_c = crystal.shape[1]
    return coef[:n_c], coef[n_c:], np.asarray(lin.y_calc, float)


def decompose(
    two_theta,
    y_obs,
    crystal_basis: np.ndarray,
    *,
    bg_basis: Optional[np.ndarray] = None,
    weights: Optional[np.ndarray] = None,
    crystal_labels: Optional[Sequence[str]] = None,
    max_humps: int = 2,
    fwhm_grid: Sequence[float] = DEFAULT_FWHM_GRID,
    center_step: float = CENTER_STEP_DEG,
    min_gain_frac: float = MIN_GAIN_FRAC,
    bg_order: int = DEFAULT_BG_ORDER,
    humps: Optional[Sequence[HumpSpec]] = None,
) -> AmorphousDecomposition:
    """在**固定晶体峰形**的前提下，把宽隆从全谱里分解出来。

    :param crystal_basis: ``(N, n_phase)`` 晶体相基列（``problem.design()[0]``）
    :param bg_basis: ``(N, n_bg)`` 背景基；``None`` 时内部用 ``bg_order`` 阶
        Legendre（否则宽隆会把整个基线抬起来，DoC 失真）
    :param humps: 直接给定宽隆（跳过贪心搜索；用于复现/固定模型）
    :param max_humps: 贪心最多加几个宽隆
    """
    x = np.asarray(two_theta, dtype=float).reshape(-1)
    y = np.asarray(y_obs, dtype=float).reshape(-1)
    if x.size != y.size:
        raise ValueError("two_theta 与 y_obs 长度必须一致")
    A_c = np.asarray(crystal_basis, dtype=float)
    if A_c.ndim != 2 or A_c.shape[0] != x.size:
        raise ValueError(f"crystal_basis 形状 {A_c.shape} 与数据点 {x.size} 不符")
    w = np.ones_like(y) if weights is None else np.asarray(weights, float).reshape(-1)
    if w.size != y.size:
        raise ValueError("weights 长度与 y_obs 不一致")
    bg = (_legendre_basis(x, bg_order) if bg_basis is None
          else np.asarray(bg_basis, dtype=float))
    if bg.ndim != 2 or bg.shape[0] != x.size:
        raise ValueError(f"bg_basis 形状 {bg.shape} 与数据点 {x.size} 不符")

    notes: List[str] = []
    if bg_basis is None:
        notes.append(
            f"未给背景基，内部用 {bg_order} 阶 Legendre；背景越灵活宽隆越被抬高、"
            f"DoC 系统性偏低 —— 结论性数字请传精修时的 bg_basis")

    # ① 不含任何宽隆的基线（晶体 + 背景）
    c0, _, yc0 = _solve(A_c, np.zeros((x.size, 0)), bg, y, w)
    rwp0 = _rwp(y, yc0, w)
    ssr0 = float(np.sum(np.maximum(w, 0.0) * (y - yc0) ** 2))

    chosen: List[HumpSpec] = list(humps or ())
    # 噪声底：无宽隆模型的稳健 σ（1.4826·MAD）。用**相对**下降判据时，
    # 完美模型（SSR 只剩噪声）会把 0.001% 的下降也算成"显著"，从而凭空
    # 加宽隆 —— 所以还要过一道"峰高 ≥ NOISE_K·σ"的绝对判据。
    _r0 = y - yc0
    sigma_n = float(1.4826 * np.median(np.abs(_r0 - np.median(_r0))))
    if humps is None and max_humps > 0:
        # ② 贪心：在中心网格 × FWHM 网格里挑 SSR 下降最多的一个，再局部精修
        lo, hi = float(x.min()), float(x.max())
        centers = np.arange(lo + 2.0, max(hi - 2.0, lo + 2.0) + 1e-9, center_step)
        best_ssr = ssr0
        for _ in range(int(max_humps)):
            cand = None
            grid_f = tuple(max(float(v), MIN_FWHM) for v in fwhm_grid)
            for c in centers:
                for f in grid_f:
                    # 与已有宽隆太近的候选直接跳过：同一个包络被拆成两个会让
                    # 面积在两个 hump 间来回搬，参数不可解释（面积和是对的，
                    # 但每个 hump 的中心/FWHM 变成噪声）
                    if any(abs(float(c) - h.center)
                           < MIN_SEP_FWHM * min(float(f), h.fwhm)
                           for h in chosen):
                        continue
                    trial = list(chosen) + [HumpSpec(float(c), float(f))]
                    H = hump_columns(x, trial)
                    _, ch, yc = _solve(A_c, H, bg, y, w)
                    ssr = float(np.sum(np.maximum(w, 0.0) * (y - yc) ** 2))
                    if cand is None or ssr < cand[0]:
                        cand = (ssr, float(c), float(f),
                                float(np.max(H[:, -1]) * ch[-1]))
            if cand is None:
                break
            ssr, c_best, f_best, _amp = cand
            # 局部精修：中心 ±步长、FWHM 上下各一档
            for _it in range(2):
                for dc in (-center_step / 2, 0.0, center_step / 2):
                    for df in (-f_best / 4, 0.0, f_best / 4):
                        cc = float(np.clip(c_best + dc, lo + 1.0, hi - 1.0))
                        ff = float(max(f_best + df, MIN_FWHM))
                        trial = list(chosen) + [HumpSpec(cc, ff)]
                        H = hump_columns(x, trial)
                        _, _, yc = _solve(A_c, H, bg, y, w)
                        s = float(np.sum(np.maximum(w, 0.0) * (y - yc) ** 2))
                        if s < ssr - 1e-12:
                            ssr, c_best, f_best = s, cc, ff
            # 相对当前模型 SSR 的下降不够 → 这个宽隆是噪声，不加
            if ssr0 <= 0.0 or (best_ssr - ssr) / ssr0 < float(min_gain_frac):
                break
            # 峰高判据：宽隆在数据里的**绝对**高度必须显著高于噪声。
            # 只有相对判据时，完美模型（SSR 只剩噪声）也会吃进千分之几的
            # 假下降，凭空长出一个宽隆把 DoC 拉低。
            trial = list(chosen) + [HumpSpec(c_best, f_best)]
            Ht = hump_columns(x, trial)
            _, cht, _ = _solve(A_c, Ht, bg, y, w)
            amp = float(np.max(np.abs(Ht[:, -1] * cht[-1])))
            if sigma_n > 0.0 and amp < NOISE_K * sigma_n:
                break
            chosen.append(HumpSpec(c_best, f_best))
            best_ssr = ssr

    H = hump_columns(x, chosen) if chosen else np.zeros((x.size, 0))
    coef_c, coef_h, yc = _solve(A_c, H, bg, y, w)
    rwp1 = _rwp(y, yc, w)

    # ③ 面积：晶体基列按自身积分，宽隆系数即面积（列已单位化）
    a_c = tuple(float(c * np.trapezoid(np.maximum(A_c[:, i], 0.0), x))
                for i, c in enumerate(coef_c))
    a_h = tuple(float(v) for v in coef_h)
    tot_c = float(sum(a_c))
    tot_h = float(sum(a_h))
    denom = tot_c + tot_h
    doc = tot_c / denom if denom > 0 else 1.0

    y_cr = np.asarray(A_c @ coef_c, float)
    y_am = np.asarray(H @ coef_h, float) if H.shape[1] else np.zeros_like(y)

    # ④ 背景敏感性：**同一组宽隆**换两套 Legendre 背景重解，看 DoC 摆多少。
    #    这一步是诚实的核心 —— 宽隆与"背景形状 + 晶体峰宽"本来就共线，换背景
    #    就换答案（实测 S1：0.98 ↔ 0.44）。摆动超过 DOC_SENS_TOL 时调用方必须
    #    把 DoC 当区间/量级，不能当测量值。
    doc_sens: Tuple[float, ...] = ()
    doc_spread = 0.0
    if chosen:
        span = float(x[-1] - x[0]) if x.size > 1 else 0.0
        for order in (max(6, int(round(span / 10.0))),
                      max(10, int(round(span / 5.0)))):
            bg_s = _legendre_basis(x, order)
            c_s, h_s, _yc_s = _solve(A_c, H, bg_s, y, w)
            a_c_s = float(sum(c * np.trapezoid(np.maximum(A_c[:, i], 0.0), x)
                              for i, c in enumerate(c_s)))
            a_h_s = float(sum(h_s))
            doc_sens = doc_sens + ((a_c_s / (a_c_s + a_h_s))
                                   if (a_c_s + a_h_s) > 0 else 1.0,)
        doc_spread = float(max(doc_sens) - min(doc_sens))
        if doc_spread > DOC_SENS_TOL:
            notes.append(
                f"DoC 在不同背景模型下摆动 {100 * doc_spread:.1f} pp"
                f"（{', '.join(f'{100 * v:.0f}%' for v in doc_sens)}）："
                f"宽隆与背景/峰宽共线，这个分解不唯一，只能当量级参考")

    if not chosen:
        notes.append("未找到显著宽隆：残余弥散可由背景/峰形解释，未引入非晶相")
    if doc < 0.05:
        notes.append("晶相面积占比 <5%：以非晶为主，晶体定量不可信")
    if tot_h > tot_c:
        notes.append("非晶面积超过晶相：峰形/背底可能已被宽隆吸收，核对 hump 位置")
    # 包络压在晶峰上：那里"宽隆"可能只是晶峰的峰宽失配被摊出来，面积不可信
    _peak = float(np.max(np.abs(y_cr))) if y_cr.size else 0.0
    for h in chosen:
        m = np.abs(x - h.center) <= 0.6 * h.fwhm
        if not np.any(m) or _peak <= 0.0:
            continue
        rel = float(np.max(np.abs(y_cr[m]))) / _peak
        if rel >= CRYSTAL_COINCIDENCE_REL:
            notes.append(
                f"宽隆 {h.center:.1f}°/FWHM {h.fwhm:.1f}° 与某晶相强峰重合（该处"
                f"晶峰高度为最强晶峰的 {100 * rel:.0f}%）：面积可能被晶峰吸收或"
                f"反吸收，DoC 只能当量级参考")
    return AmorphousDecomposition(
        humps=tuple(chosen),
        hump_areas=a_h,
        crystal_areas=a_c,
        crystal_scales=tuple(float(v) for v in coef_c),
        doc_area=float(doc),
        amorphous_area_share=float(1.0 - doc),
        crystal_area_total=tot_c,
        hump_area_total=tot_h,
        rwp_before=rwp0,
        rwp_after=rwp1,
        doc_sensitivity=doc_sens,
        doc_spread=doc_spread,
        y_crystal=y_cr,
        y_amorphous=y_am,
        y_background=np.asarray(yc - y_cr - y_am, float),
        notes=notes,
    )


def absolute_amorphous_from_standard(
    crystal_wt_pct: Sequence[float],
    scale_factor: float,
    *,
    standard_wt_pct: float = 0.0,
    unidentified_wt_pct: float = 0.0,
) -> Tuple[float, List[float], List[str]]:
    """内标定标后求**绝对**非晶含量 ``W_amorphous = 100 − ΣW_crystal``。

    两种用法，取决于 ``crystal_wt_pct`` 里是否含内标：

    * **含内标**（原始精修输出，各相相对 wt% 合计 100）：``scale_factor`` =
      ``std_wt_pct / w'_std``，``standard_wt_pct`` 留 0 —— 定标后内标自己也在
      ``ΣW_crystal`` 里，不能再扣一次。
    * **不含内标**（``RietveldRefiner.refine_with_internal_standard`` 的返回：
      各相已是绝对 wt%）：``scale_factor=1.0``，**必须**给 ``standard_wt_pct``。
      内标也占试样质量，忘了扣会**系统性高估非晶**：合成掺标样实测（Si 45 /
      NaCl 25 / Al 15 / 非晶 15）漏扣 15% 内标 → 报 29.7% 非晶（+14.7 pp）。

    :param crystal_wt_pct: 各晶相 wt%（相对或绝对，见上）
    :param scale_factor: 内标系数；若传入值已是绝对口径则给 1.0
    :param standard_wt_pct: 内标在**试样里**的绝对 wt%；仅当
        ``crystal_wt_pct`` 不含内标时需要
    :param unidentified_wt_pct: 已知未识别晶相的量（若为 0 则全部计入非晶）

    返回 ``(amorphous_wt_pct, absolute_crystal_wt_pct_list, notes)``。
    前提：**没有其它未识别晶相**；否则这个差值把未识别晶相也算成非晶
    （这是内标法本身的边界，不是实现问题）。
    """
    k = float(scale_factor)
    abs_c = [float(v) * k for v in crystal_wt_pct]
    total_c = float(sum(abs_c))
    std = float(standard_wt_pct)
    unident = float(unidentified_wt_pct)
    if std < 0.0:
        raise ValueError("standard_wt_pct 不能为负")
    if unident < 0.0:
        raise ValueError("unidentified_wt_pct 不能为负")
    amor = 100.0 - total_c - std - unident
    notes: List[str] = []
    if total_c + std + unident > 100.5:
        notes.append(
            f"晶体相 + 内标合计 {total_c + std + unident:.2f}% 已超过 100%，"
            f"非晶量算不出来 —— 内标含量或标定系数不对"
            f"（W_amorphous={amor:.2f}%）")
    elif amor > 99.0:
        notes.append("非晶量 ≈100%：确认内标是否真的混进了试样")
    if std > 0.0:
        notes.append(f"已扣除内标 {std:.2f}%（它同样占试样质量）")
    if unident > 0.0:
        notes.append(f"已扣除已知未识别晶相 {unident:.2f}%")
    return float(amor), abs_c, notes
