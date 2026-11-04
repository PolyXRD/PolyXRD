"""系统性强度误差：表面粗糙度 + 微吸收（Brindley）。

为什么要单独一层
----------------
Rietveld 的强度残差里有两类**系统性**误差是结构/峰形参数无法表达的：

1. **表面粗糙度（surface roughness, SR）**：Bragg–Brentano 反射几何下，粗颗粒
   样品的表面凹凸让入射束在低角掠射时被"阴影"掉一部分，**低角反射强度系统性
   偏低**。它随 2θ 变化，因此**不能被标度吸收** —— 不修它，拟合器只能用
   Biso / 占位 / 择优去凑，最后得到"结构对、定量错"。
2. **微吸收（microabsorption）**：多相样品中各相线吸收系数 μ 不同，粗颗粒时
   高吸收相只在表层衍射（强度被低估）、低吸收相能"体积衍射"（强度被高估）。
   对**每一相**是一个近似常数的强度因子 τ，因此它**只影响定量、几乎不影响
   Rwp** —— 拟合出的标度会自己把 τ 吸收掉，必须单独在 Hill–Howard 里除回去。

这两个模型的区别决定了接线方式的不同（见 ``problem.py`` / ``quantitative.py``）：
SR 进前向模型（可精修），微吸收进定量因子（不可精修，由 μ 与粒度确定）。

表面粗糙度：三个模型
--------------------
全部是 DBWS 里的经典实现（Young et al. 1999），公式与符号照抄：

* **Sidey (2004)** — 单参数，本文档**默认**：``S_R = (θ/90)^(s/θ)``（θ 用度）。
  原论文（Sidey, *J. Appl. Cryst.* 37 (2004) 962）明确指出 Suortti / Pitschke
  两个双参数模型与标度、Biso、占位**强相关**，单参数版本显著改善稳定性 ——
  在这条拟合链里"稳定性"比"多一个自由度"更值钱。
* **Suortti (1972)**：``S_R = 1 − p·exp(−q) + p·exp(−q/sinθ)``，θ=90° 时恒为 1。
* **Sparks (1992)**：``S_R = 1 − t·(θ_rad − π/2)``，线性，只在低角降幅 1~2% 时可靠。
* **Pitschke (1993)** 有意**不实现**：``S_R`` 在 θ=90° 处不等于 1（论文自己也
  指出了这个缺陷），会把系统误差漏进标度。

微吸收：Brindley τ
------------------
``τ_j = τ((μ_j − μ̄)·R)``，R 为颗粒半径、μ̄ 为样品平均线吸收系数。表值取自
Brindley (1945) 的经典计算，按 Hill & Howard (*J. Appl. Cryst.* 20 (1987) 467)
的表格形式被 FullProf 手册原样转载（2θ = 0°/90°/180° 三列）。本模块只用
**90° 那一列**：三列在 |x|=0.5 处相差约 13%，取中列与各工具（FullProf 亦然）
的惯例一致，且 90° 列在 x ∈ [−0.5, 0.5] 上单调，插值稳定。

适用边界（务必别越界用）：

* 表只覆盖 ``|(μ_j − μ̄)·R| ≤ 0.5`` —— 超出即"颗粒太粗，Rietveld 定量已失效"
  （细粉 ``μr ≪ 1`` 时 τ→1，粗粉 ``μr ≫ 0.5`` 时 τ 表本身就没有意义了）。
  本模块对越界值做**截断**并置 ``clamped=True``，不静默外推。
* ``τ > 1``（低吸收相被高估）与 ``τ < 1``（高吸收相被低估）都正常，符号由
  ``μ_j − μ̄`` 决定。
* 迭代：μ̄ 依赖重量分数、重量分数又依赖 τ，故需 2~3 轮不动点迭代（FullProf
  的做法也是"先取 τ=1 的分数、再迭代"）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "ROUGHNESS_MODELS",
    "Roughness",
    "sidey_roughness",
    "suortti_roughness",
    "sparks_roughness",
    "roughness_factor",
    "BRINDLEY_X",
    "BRINDLEY_TAU",
    "BRINDLEY_X_LIMIT",
    "brindley_tau",
    "mean_linear_mu",
    "microabsorption_taus",
    "apply_microabsorption",
    "MASS_ATTENUATION_CU_KA",
    "CU_KA_KEV",
    "mass_attenuation_from_counts",
    "mass_attenuation_from_formula",
    "linear_mu_from_composition",
    "linear_mu_from_formula",
    "linear_mu_from_sites",
]

#: 支持（并已实现）的表面粗糙度模型；``none`` = 不修正。
ROUGHNESS_MODELS: Tuple[str, ...] = ("none", "sidey", "suortti", "sparks")


def _theta_deg(two_theta) -> np.ndarray:
    """2θ(度) → θ(度)，并夹到 (0, 180) 防除零。"""
    tt = np.asarray(two_theta, dtype=float)
    th = 0.5 * tt
    return np.clip(th, 1e-3, 179.999)


@dataclass(frozen=True)
class Roughness:
    """表面粗糙度描述（**整样品一个**，不分相）。

    作为前向模型的一个可选乘子挂进 ``phase_pattern``：``intensity *= S_R(2θ)``。
    与择优取向的区别：PO 是"某一相的晶粒取向分布"（逐相、依赖 hkl），SR 是
    "样品表面形貌"（全局、只依赖 2θ）。

    ``model="none"``（默认）时 :meth:`factor` 返回全 1 —— 调用方不需要为
    "关掉"付任何代价，也不会改变既有结果。
    """

    model: str = "none"
    s: float = 0.0
    p: float = 0.0
    q: float = 0.0

    @property
    def is_off(self) -> bool:
        name = (self.model or "none").strip().lower()
        if name in ("", "none", "off", "0"):
            return True
        return not any(abs(float(v)) > 0.0 for v in (self.s, self.p, self.q))

    def factor(self, two_theta) -> np.ndarray:
        """``S_R`` 数组；关闭时全 1（零开销分支）。"""
        tt = np.asarray(two_theta, dtype=float)
        if self.is_off:
            return np.ones_like(tt)
        return roughness_factor(tt, self.model, s=self.s, p=self.p, q=self.q)

    def key(self) -> tuple:
        """缓存键片段 —— 值变了设计矩阵就必须重建。"""
        if self.is_off:
            return ("none",)
        return (self.model.strip().lower(), float(self.s), float(self.p), float(self.q))


def sidey_roughness(two_theta, s: float) -> np.ndarray:
    """Sidey (2004) 单参数表面粗糙度因子 ``S_R = (θ/90)^(s/θ)``。

    :param two_theta: 2θ（度）
    :param s: 可精修参数（度）。``s = 0`` → 恒 1（零开销）；``s > 0`` → 低角
        强度被压低，θ=90° 处恒为 1（法向入射看不到粗糙度）。

    极限行为：θ→0 时 ``exp((s/θ)·ln(θ/90)) → 1``，即本模型在极低角不产生
    "无限压暗"，这与 Suortti 的 ``exp(−q/sinθ)`` 不同（后者在 θ→0 更陡）。
    """
    th = _theta_deg(two_theta)
    ss = float(s)
    if ss == 0.0 or not np.isfinite(ss):
        return np.ones_like(th)
    ratio = th / 90.0
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.exp((ss / th) * np.log(np.maximum(ratio, 1e-12)))
    # θ=90° 必须精确为 1（ln 1 = 0），θ 越界产生的 nan/inf 一律退回 1
    out = np.where(np.isfinite(out), out, 1.0)
    return np.where(th >= 90.0, 1.0, out)


def suortti_roughness(two_theta, p: float, q: float) -> np.ndarray:
    """Suortti (1972) 双参数模型 ``S_R = 1 − p·e^{−q} + p·e^{−q/sinθ}``。

    θ=90° 时 ``sinθ=1`` → ``S_R = 1``（严格），满足"法向入射无粗糙度"的
    物理边界。``p = 0`` → 恒 1。
    """
    th = _theta_deg(two_theta)
    pp, qq = float(p), float(q)
    if pp == 0.0 or not np.isfinite(pp):
        return np.ones_like(th)
    sin_th = np.maximum(np.sin(np.radians(th)), 1e-6)
    with np.errstate(over="ignore", invalid="ignore"):
        out = 1.0 - pp * np.exp(-qq) + pp * np.exp(-qq / sin_th)
    return np.where(np.isfinite(out), out, 1.0)


def sparks_roughness(two_theta, t: float) -> np.ndarray:
    """Sparks (1992) 线性模型，θ=90° 处为 1、低角线性压暗。

    原始文献写作 ``S_R = 1 − t·(θ_rad − π/2)``，其中 ``t`` 在实现里取**负值**
    表示压暗。本函数把符号收进参数，口径统一为"``t > 0`` 即压暗"：

    .. code-block:: text

        S_R = 1 + t·(θ_rad − π/2) = 1 − t·(π/2 − θ_rad)

    只有单参数且是直线，**仅当低角强度降幅在 1~2% 时可靠**（原始文献自己
    也这么说）。留给对照实验用，生产默认用 Sidey。

    注意：模型对 θ > 90° 会给出略大于 1 的值（±t·0.35 量级）。这是解析式的
    固有外推，不是 bug —— 该区间本来就没有粗糙度效应，实际影响 < 0.04%。
    """
    th = _theta_deg(two_theta)
    tt = float(t)
    if tt == 0.0 or not np.isfinite(tt):
        return np.ones_like(th)
    out = 1.0 + tt * (np.radians(th) - np.pi / 2.0)
    return np.where(np.isfinite(out), out, 1.0)


def roughness_factor(two_theta, model: str = "none", *, s: float = 0.0,
                     p: float = 0.0, q: float = 0.0) -> np.ndarray:
    """按模型名分派；``none`` / 未知模型 → 全 1（零开销）。"""
    name = (model or "none").strip().lower()
    tt = np.asarray(two_theta, dtype=float)
    if name in ("", "none", "off", "0"):
        return np.ones_like(tt)
    if name == "sidey":
        return sidey_roughness(tt, s)
    if name == "suortti":
        return suortti_roughness(tt, p, q)
    if name == "sparks":
        return sparks_roughness(tt, s)
    raise ValueError(f"未知表面粗糙度模型: {model!r}（支持 {ROUGHNESS_MODELS}）")


# ── Brindley 微吸收 ──────────────────────────────────────────────────
#: ``x = (μ_j − μ̄)·R`` 的表值（R 用 cm、μ 用 cm⁻¹，x 无量纲）
BRINDLEY_X: np.ndarray = np.array([
    -0.50, -0.40, -0.30, -0.20, -0.10, -0.09, -0.08, -0.07, -0.06, -0.05,
    -0.04, -0.03, -0.02, -0.01, 0.00, 0.01, 0.02, 0.03, 0.04, 0.05,
    0.06, 0.07, 0.08, 0.09, 0.10, 0.20, 0.30, 0.40, 0.50,
], dtype=float)

#: Brindley 系数 τ(x)（2θ = 90° 列）。来源：Brindley 1945；表值经
#: Hill & Howard, J. Appl. Cryst. 20 (1987) 467 整理、FullProf 手册转载。
BRINDLEY_TAU: np.ndarray = np.array([
    2.036, 1.807, 1.573, 1.353, 1.162, 1.143, 1.125, 1.108, 1.091, 1.073,
    1.058, 1.042, 1.027, 1.014, 1.000, 0.986, 0.973, 0.960, 0.946, 0.933,
    0.919, 0.906, 0.893, 0.879, 0.866, 0.753, 0.653, 0.569, 0.496,
], dtype=float)

#: 表值覆盖范围；越界截断（不外推）——见模块 docstring 的"适用边界"。
BRINDLEY_X_LIMIT: float = 0.5


def brindley_tau(delta_mu_r) -> np.ndarray:
    """``x = (μ_j − μ̄)·R`` → Brindley τ（线性插值，越界截断）。

    ``x = 0``（该相吸收系数等于样品平均）→ 1.000，恰好无修正；``x > 0``（高
    吸收相）→ τ < 1；``x < 0`` → τ > 1。这三条同时成立是本式自洽性的硬检查。
    """
    x = np.asarray(delta_mu_r, dtype=float)
    xc = np.clip(x, -BRINDLEY_X_LIMIT, BRINDLEY_X_LIMIT)
    # np.interp 要求升序，表本身已升序
    return np.interp(xc, BRINDLEY_X, BRINDLEY_TAU)


def mean_linear_mu(mu: Sequence[float] | np.ndarray,
                   fractions: Sequence[float] | np.ndarray) -> float:
    """样品平均线吸收系数 ``μ̄ = Σ w_j·μ_j / Σ w_j``（1/cm）。"""
    m = np.asarray(mu, dtype=float).reshape(-1)
    f = np.asarray(fractions, dtype=float).reshape(-1)
    if m.size != f.size:
        raise ValueError("mu 与 fractions 长度必须一致")
    f = np.maximum(f, 0.0)
    tot = float(f.sum())
    if tot <= 0.0:
        return float(m.mean()) if m.size else 0.0
    return float((m * f).sum() / tot)


def microabsorption_taus(mu: Sequence[float], fractions: Sequence[float],
                         radius_um: float) -> Tuple[np.ndarray, float, bool]:
    """由 μ 与重量分数算各相 τ。

    :param mu: 各相线吸收系数（1/cm）
    :param fractions: 各相重量分数（内部归一，允许未归一的权重）
    :param radius_um: 颗粒半径 R（µm）
    :return: ``(tau, mu_bar, clamped)`` —— ``clamped`` 表示有 |x| 超过 0.5

    单位换算：R 由 µm → cm 乘 1e-4；μ 用 cm⁻¹，故 ``x = Δμ·R`` 无量纲。
    """
    m = np.asarray(mu, dtype=float).reshape(-1)
    f = np.asarray(fractions, dtype=float).reshape(-1)
    r_cm = float(radius_um) * 1e-4
    mu_bar = mean_linear_mu(m, f)
    x = (m - mu_bar) * r_cm
    clamped = bool(np.any(np.abs(x) > BRINDLEY_X_LIMIT + 1e-12))
    return brindley_tau(x), mu_bar, clamped


def apply_microabsorption(
    base_weights: Sequence[float],
    mu: Sequence[float],
    radius_um: float,
    *,
    iterations: int = 3,
) -> Tuple[np.ndarray, np.ndarray, float, bool]:
    """把 Brindley τ 施加到"Hill–Howard 原始权重"上，返回修正后的重量分数。

    输入 ``base_weights`` 是 ``S_j·f_j``（``f_j = M_cell/V``，见
    :func:`polyxrd.refinement.quantitative.phase_weight_factor`）。修正形式为

    .. code-block:: text

        W_j ∝ S_j·f_j / τ_j        （τ 把"标度已吸收掉的那部分强度偏差"除回去）

    为什么是"除"而不是"乘"：τ<1 表示该相**真实**强度本该更高，拟合时标度被
    压低来匹配观测，于是真实含量 ∝ S/τ。FullProf 的 ``ATZ = Z·M·f²/τ`` 是同一
    种写法（只是它的强度里没有 1/V²）。

    μ̄ 依赖 W、W 又依赖 τ，故做 ``iterations`` 轮不动点迭代（默认 3 轮，实测
    2 轮已收敛到 1e-6）。

    :return: ``(fractions, taus, mu_bar, clamped)``
    """
    base = np.maximum(np.asarray(base_weights, dtype=float).reshape(-1), 0.0)
    m = np.asarray(mu, dtype=float).reshape(-1)
    if base.size != m.size:
        raise ValueError("base_weights 与 mu 长度必须一致")
    if base.size == 0:
        return np.zeros(0), np.zeros(0), 0.0, False

    tot = float(base.sum())
    w = (base / tot) if tot > 0.0 else np.full(base.size, 1.0 / base.size)
    taus = np.ones_like(w)
    mu_bar = mean_linear_mu(m, w)
    clamped = False

    for _ in range(max(1, int(iterations))):
        taus, mu_bar, clamped = microabsorption_taus(m, w, radius_um)
        taus = np.where(np.isfinite(taus) & (taus > 1e-9), taus, 1.0)
        raw = base / taus
        s = float(raw.sum())
        w = (raw / s) if s > 0.0 else np.full(base.size, 1.0 / base.size)

    # 收尾再算一次 τ（与最后一次 w 对应），保证返回值与分数自洽
    taus, mu_bar, clamped = microabsorption_taus(m, w, radius_um)
    return w, taus, float(mu_bar), clamped


# ── 线吸收系数 μ（Cu Kα）─────────────────────────────────────────────
#: Cu Kα 的加权能量（keV）：Kα1 8.0478 / Kα2 8.0280，按 2:1 加权 ≈ 8.041
CU_KA_KEV: float = 8.041

#: 元素 → Cu Kα 处的**质量衰减系数** μ/ρ（cm²/g）。
#:
#: 口径
#: ----
#: 取自标准 μ/ρ 表（International Tables for Crystallography Vol. C / NIST
#: XCOM）在 8.05 keV 处的值，保留 3 位有效数字。**不追求 4 位精度**：
#: Brindley τ 的自变量是 ``x = (μ_j − μ̄)·R``，τ 在 |x| ≤ 0.5 上分段近似线性，
#: μ 表值 5% 的误差只让 x 差 5%，落到定量上是千分位级别。真正不能错的是
#: **数量级与符号**（Fe 325 vs Al 50 差 6.5 倍，"谁被低估、谁被高估"全看它）。
#:
#: 只收录 **Z ≤ 30（H…Zn）**：XRD 常见无机体系（硅酸盐 / 碳酸盐 / 氧化物 /
#: 磷酸盐 / 硫化物 / 正极材料）都在这个范围。更重的元素（Zr / Ba / 稀土 / W /
#: Pb…）**返回 None** —— 与其猜一个错的 μ 静默生效，不如让调用方显式给
#: ``mu_linear``。表是"覆盖常见体系"而不是"覆盖全周期表"，别偷偷补猜的值。
#:
#: K 吸收边（重要，不是笔误）
#: --------------------------
#: Ni(8.333 keV) / Cu(8.979) / Zn(9.659) 的 K 边都在 Cu Kα **之上**，所以它们的
#: μ/ρ（47.6 / 50.4 / 58.5）比 Cr–Co（254.7 / 285.4 / 325.0）**低一个量级**，
#: 与"Z 越大吸收越强"的朴素直觉相反。这与"Ni 滤片能压 Cu Kβ 却几乎不压 Kα"
#: 是同一个物理。后果很实际：Fe₂O₃ + NiO 体系里两相 μ 可以反号，微吸收方向
#: 也随之翻转 —— 别把"高原子序数相一定被低估"当定论。
MASS_ATTENUATION_CU_KA: Dict[str, float] = {
    "H": 0.391, "He": 0.196, "Li": 0.717, "Be": 1.03, "B": 2.00,
    "C": 4.60, "N": 7.52, "O": 11.5, "F": 16.1, "Ne": 21.7,
    "Na": 30.1, "Mg": 47.0, "Al": 50.0, "Si": 62.0, "P": 75.0,
    "S": 89.1, "Cl": 106.4, "Ar": 123.0, "K": 131.0, "Ca": 174.0,
    "Sc": 186.0, "Ti": 208.0, "V": 232.0, "Cr": 254.7, "Mn": 285.4,
    "Fe": 325.0, "Co": 331.0, "Ni": 47.6, "Cu": 50.4, "Zn": 58.5,
}

#: 阿伏伽德罗常数（SI 2019 定义值，精确）
_AVOGADRO: float = 6.02214076e23


def mass_attenuation_from_counts(counts: Dict[str, float]) -> Optional[float]:
    """化学组成 → 混合物 μ/ρ（cm²/g）。

    ``counts`` 是 ``{元素: 原子数}``（**任意统一倍数**，摩尔比或全胞计数都行）。
    混合物按**质量分数**加权 —— 不是摩尔比加权，这是最常见的一处错：

    .. code-block:: text

        μ/ρ = Σ w_i·(μ/ρ)_i,   w_i = n_i·M_i / Σ n_j·M_j

    :return: μ/ρ；``counts`` 为空或有元素不在表里 → ``None``（不猜）。
    """
    from .quantitative import atomic_mass

    if not counts:
        return None
    total_m, accum = 0.0, 0.0
    for el, n in counts.items():
        n = float(n or 0.0)
        if n <= 0.0:
            continue
        mu_rho = MASS_ATTENUATION_CU_KA.get(str(el))
        if mu_rho is None:
            return None                      # 未收录元素 → 整体不猜
        m = atomic_mass(el)
        if m <= 0.0:
            return None
        total_m += n * m
        accum += n * m * mu_rho
    if total_m <= 0.0:
        return None
    return float(accum / total_m)


def mass_attenuation_from_formula(formula: str) -> Optional[float]:
    """化学式字符串 → μ/ρ（cm²/g）。解析失败或含未收录元素 → ``None``。"""
    try:
        from polyxrd.utils.formula_parser import parse_formula_detailed
    except Exception:                        # pragma: no cover - 极早导入期
        return None
    try:
        counts = parse_formula_detailed(formula or "")
    except Exception:
        return None
    return mass_attenuation_from_counts(counts)


def linear_mu_from_composition(counts: Dict[str, float],
                               cell_volume: float) -> Optional[float]:
    """``{元素: 全胞原子数}`` + 晶胞体积(Å³) → μ（1/cm）。

    推导（``M_cell`` 在中间被约掉，所以不需要密度输入）：

    .. code-block:: text

        ρ       = Σ n_i·M_i / (N_A·V)
        μ = (μ/ρ)·ρ = Σ n_i·M_i·(μ/ρ)_i / (N_A·V)

    与 :func:`linear_mu_from_formula` 是同一个量的两条路：这条用位点计数
    （Rietveld 现场就有），那条用化学式 + 实测密度。位点路更可信 —— 库里的
    formula 字段与实际位点常不一致（缺氢、写成空间群记号、水合物简写）。
    """
    if not counts or not cell_volume or cell_volume <= 0:
        return None
    from .quantitative import atomic_mass

    accum = 0.0
    for el, n in counts.items():
        n = float(n or 0.0)
        if n <= 0.0:
            continue
        mu_rho = MASS_ATTENUATION_CU_KA.get(str(el))
        if mu_rho is None:
            return None
        m = atomic_mass(el)
        if m <= 0.0:
            return None
        accum += n * m * mu_rho
    v_cm3 = float(cell_volume) * 1e-24         # Å³ → cm³
    if v_cm3 <= 0.0:
        return None
    return float(accum / (_AVOGADRO * v_cm3))


def linear_mu_from_formula(formula: str,
                           density: Optional[float]) -> Optional[float]:
    """化学式 + 密度(g/cm³) → μ（1/cm）。任一缺失/未收录 → ``None``。"""
    if density is None or float(density) <= 0.0:
        return None
    mu_rho = mass_attenuation_from_formula(formula)
    if mu_rho is None:
        return None
    return float(mu_rho * float(density))


def _site_element_occ(site) -> Tuple[str, float]:
    """位点 → ``(元素, 占位数)``；兼容 dataclass / dict / tuple 三种写法。"""
    if isinstance(site, dict):
        el = site.get("element") or site.get("symbol") or ""
        occ = site.get("occupancy", site.get("occ", 1.0))
    elif isinstance(site, (tuple, list)):
        el = site[0] if site else ""
        occ = 1.0
    else:
        el = getattr(site, "element", "") or ""
        occ = getattr(site, "occupancy", getattr(site, "occ", 1.0))
    try:
        occ = float(occ)
    except (TypeError, ValueError):
        occ = 1.0
    return str(el), occ


def linear_mu_from_sites(sites: Iterable, cell_volume: float
                         ) -> Optional[float]:
    """全胞位点列表 + 晶胞体积(Å³) → μ（1/cm）。

    ``sites`` 必须已是**全胞**计数（含占位、已做对称展开）—— ``Phase`` /
    ``StructureModel`` 的位点都是这个口径（见 ``StructureModel.composition``）。
    """
    counts: Dict[str, float] = {}
    for s in sites or ():
        el, occ = _site_element_occ(s)
        if not el or occ <= 0.0:
            continue
        counts[el] = counts.get(el, 0.0) + occ
    return linear_mu_from_composition(counts, cell_volume)
