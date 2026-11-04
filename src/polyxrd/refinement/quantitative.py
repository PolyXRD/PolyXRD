"""定量相分析：Hill–Howard 权重分数 + 酸检（合成混合物的重量分数回收）。

公式（Hill & Howard, 1987, J. Appl. Cryst. 20, 467）
-------------------------------------------------
    W_p ∝ S_p · M_cell,p / V_p        （= S_p · 密度）

``S`` Rietveld 标度、``M_cell`` 每胞摩尔质量、``V`` 胞体积。**不是**文献里
常见的 ``S·Z·M·V``，也**不是** ``S·M`` —— 这两者差一个 ``V`` 的正负号，
取决于强度的体积归一方式（推导见 :func:`phase_weight_factor`）。本包按
``I ∝ m|F|²·LP/V²`` 算强度，配套因子是 ``M/V``。

实测：2-1（ZnO+CaCO₃ 标称 50/50）用 ``S·M·V`` 得 ZnO 30%、用 ``S·M`` 得 11%、
用 ``S·M/V`` 得 48%。

**这条公式为什么成立**：Rietveld 里 ``I_hkl ∝ N·m·|F|²·LP/V²``，而
``N_p ∝ W_p/M_cell,p``（N 是晶胞个数）。两式一合并，``V²`` 消掉、``M_cell``
留下 —— 这就是为什么**不需要绝对标定**就能给出重量分数。前提是各相用的是
同一套 ``f(s)`` 与 LP，本包满足。

**三个已知陷阱**（都在 :func:`hill_howard` 的 docstring 里写清）：

1. 标度必须来自**同一轮**线性层求解（不同轮的标度不可比）；
2. 微量相（<1%）的相对误差会被放大到几十个百分点 —— 此时改报"检出上限"
   而不是硬给一个数；
3. 择优取向未修正时会系统性偏袒某个相 —— 必须先精修 ``po.r``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .intensity import apply_microabsorption

__all__ = [
    "ATOMIC_MASS",
    "atomic_mass",
    "formula_mass",
    "mass_per_cell",
    "phase_zmv",
    "phase_weight_factor",
    "hill_howard",
    "QuantResult",
]

#: 标准原子量（IUPAC 2021 常用值；放射性元素取最长寿命同位素质量数）
ATOMIC_MASS: Dict[str, float] = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974,
    "S": 32.06, "Cl": 35.45, "Ar": 39.948, "K": 39.098, "Ca": 40.078,
    "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904,
    "Kr": 83.798, "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224,
    "Nb": 92.906, "Mo": 95.95, "Tc": 98.0, "Ru": 101.07, "Rh": 102.91,
    "Pd": 106.42, "Ag": 107.87, "Cd": 112.41, "In": 114.82, "Sn": 118.71,
    "Sb": 121.76, "Te": 127.60, "I": 126.90, "Xe": 131.29, "Cs": 132.91,
    "Ba": 137.33, "La": 138.91, "Ce": 140.12, "Pr": 140.91, "Nd": 144.24,
    "Pm": 145.0, "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93,
    "Dy": 162.50, "Ho": 164.93, "Er": 167.26, "Tm": 168.93, "Yb": 173.05,
    "Lu": 174.97, "Hf": 178.49, "Ta": 180.95, "W": 183.84, "Re": 186.21,
    "Os": 190.23, "Ir": 192.22, "Pt": 195.08, "Au": 196.97, "Hg": 200.59,
    "Tl": 204.38, "Pb": 207.2, "Bi": 208.98, "Po": 209.0, "At": 210.0,
    "Rn": 222.0, "Fr": 223.0, "Ra": 226.0, "Ac": 227.0, "Th": 232.04,
    "Pa": 231.04, "U": 238.03, "Np": 237.0, "Pu": 244.0, "Am": 243.0,
    "Cm": 247.0, "Bk": 247.0, "Cf": 251.0, "Es": 252.0, "Fm": 257.0,
    "Md": 258.0, "No": 259.0, "Lr": 266.0, "Rf": 267.0, "Db": 268.0,
    "Sg": 269.0, "Bh": 270.0, "Hs": 269.0, "Mt": 278.0, "Ds": 281.0,
    "Rg": 282.0, "Cn": 285.0, "Nh": 286.0, "Fl": 289.0, "Mc": 290.0,
    "Lv": 293.0, "Ts": 294.0, "Og": 294.0,
}


def atomic_mass(element: object) -> float:
    """原子量；认不出返回 0（调用方据此跳过该位点）。"""
    from .scattering import normalize_element

    return ATOMIC_MASS.get(normalize_element(element), 0.0)


def formula_mass(counts: Dict[str, float]) -> float:
    """``{'Li': 1, 'Fe': 1, ...}`` → 摩尔质量 (g/mol)。"""
    return float(sum(atomic_mass(el) * float(n) for el, n in counts.items()))


def mass_per_cell(sites: Iterable) -> float:
    """胞内质量（g/mol 单位，即每摩尔晶胞）。按占位加权。"""
    total = 0.0
    for s in sites:
        el = getattr(s, "element", None) or (s[0] if isinstance(s, (tuple, list)) else None)
        occ = float(getattr(s, "occupancy", 1.0))
        total += atomic_mass(el) * occ
    return float(total)


def _site_counts(sites: Iterable, tol: float = 0.05) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for s in sites:
        el = getattr(s, "element", "")
        occ = float(getattr(s, "occupancy", 1.0))
        out[el] = out.get(el, 0.0) + occ
    return out


def _integer_z(counts: Dict[str, float], tol: float = 0.08) -> int:
    """由逐元素计数反推每胞化学式单元数 Z（取计数的最大公约数）。"""
    ints: List[int] = []
    for el, n in counts.items():
        k = int(round(n))
        if k < 1 or abs(n - k) > max(tol * k, 1e-6):
            return 1
        ints.append(k)
    if not ints:
        return 1
    z = ints[0]
    for k in ints[1:]:
        z = math.gcd(z, k)
    return max(z, 1)


@dataclass(frozen=True)
class QuantResult:
    """定量结果。

    :param tau: 各相 Brindley 微吸收系数 τ（未启用时全 1）
    :param mu_bar: 样品平均线吸收系数（1/cm，未启用时 0）
    :param mu_clamped: 有相的 ``|(μ−μ̄)·R|`` 超出 Brindley 表的适用范围
        （> 0.5）—— 此时 τ 已按边界值截断，定量结果只能定性参考
    :param mu: 各相线吸收系数（1/cm，未启用时为空）—— 误差棒要把 τ 的
        依赖一起传播，而 τ 只由 ``mu`` / ``radius_um`` 决定，所以必须存下来
    :param radius_um: 施加微吸收时用的颗粒半径（µm，未启用时 0）
    """

    labels: Tuple[str, ...]
    fractions: Tuple[float, ...]          # 重量分数（0~1，和为 1）
    scales: Tuple[float, ...]
    factor: Tuple[float, ...]             # 定相因子 M/V（见 phase_weight_factor）
    z: Tuple[int, ...]
    mass_per_cell: Tuple[float, ...]
    volume: Tuple[float, ...]
    detectable: Tuple[bool, ...]          # False = 含量低于可检出水平
    tau: Tuple[float, ...] = ()           # Brindley τ（空 = 未启用微吸收）
    mu_bar: float = 0.0
    mu_clamped: bool = False
    mu: Tuple[float, ...] = ()            # 各相线吸收系数（空 = 未启用微吸收）
    radius_um: float = 0.0

    def percent(self) -> Tuple[float, ...]:
        return tuple(100.0 * f for f in self.fractions)

    def as_dict(self) -> Dict[str, float]:
        return {lab: 100.0 * f for lab, f in zip(self.labels, self.fractions)}

    def table(self) -> List[Tuple[str, float, int]]:
        """``[(相名, 重量%, Z)]``，供 UI 直接铺表。"""
        return [(lab, 100.0 * f, z)
                for lab, f, z in zip(self.labels, self.fractions, self.z)]


def phase_zmv(structure) -> Tuple[int, float, float, float]:
    """``(Z, 每胞质量, 体积, Z·M·V)``；``Z·M`` 即每胞质量。

    ⚠️ 这里的 ``Z·M·V`` 是**诊断量**（复核化学式、胞体积是否离谱），不是定量
    因子。Hill–Howard 用的因子见 :func:`phase_weight_factor` —— 两者的差别是
    一个 ``V``，取决于强度里有没有 ``1/V²``（本项目有）。
    """
    sites = tuple(getattr(structure, "sites", ()) or ())
    m_cell = mass_per_cell(sites)
    vol = float(structure.cell.volume())
    z = _integer_z(_site_counts(sites))
    return z, m_cell, vol, float(m_cell * vol)


def phase_weight_factor(structure) -> float:
    """定相因子 ``M_cell/V``（∝ 密度，单位 g/mol per Å³）。

    推导（必须与 ``build_reflections`` 的强度口径配套）：

    .. code-block:: text

        I_p ∝ φ_p · m|F|²·LP / V_p²     ← 单位样品体积、φ 为体积分数
        ⇒ S_p ∝ φ_p                     ← 拟合出的标度就是体积分数
        W_p ∝ φ_p·ρ_p,  ρ_p = M_cell,p/V_p
        ⇒ W_p ∝ S_p · M_cell,p / V_p    ← 本函数返回的量

    数值上正好是密度：ZnO 162.8/47.6 = 3.42 → ×1.66 = 5.68 g/cm³（实测 5.61），
    方解石 600.5/367.9 = 1.63 → 2.71 g/cm³（实测 2.71）。这个自洽本身就是
    对公式的一个强校验。

    历史上的两种写法都错：``Z·M·V``（多两个 V）让大胞相吃掉全部权重，
    ``Z·M``（少一个 V）让 ZnO 这种小胞高密度相被压到 10%。
    """
    sites = tuple(getattr(structure, "sites", ()) or ())
    vol = float(structure.cell.volume())
    if vol <= 0.0:
        return 0.0
    return float(max(mass_per_cell(sites), 0.0) / vol)


def hill_howard(
    labels: Sequence[str],
    scales: Sequence[float],
    structures: Sequence,
    *,
    min_fraction: float = 0.0,
    mu: Optional[Sequence[float]] = None,
    radius_um: float = 0.0,
    mu_iterations: int = 3,
) -> QuantResult:
    """Hill–Howard 重量分数。

    :param labels: 相名
    :param scales: **同一轮**线性层解出的标度（不同轮的不可比）
    :param structures: 各相 ``StructureModel``（取位点、占位、胞体积）
    :param min_fraction: 低于该重量分数的相标记为"不可检出"
    :param mu: 各相线吸收系数（1/cm）。给齐且 ``radius_um > 0`` 时施加
        Brindley 微吸收修正（见 :mod:`polyxrd.refinement.intensity`）
    :param radius_um: 颗粒半径（µm），只对微吸收有意义
    :param mu_iterations: μ̄ ↔ W 的不动点迭代轮数

    三步：
      1. 每相算 ``Z``（各元素计数的最大公约数）与每胞质量 ``M_cell=Z·M``；
      2. 定相因子 ``f_p = M_cell,p/V_p``（见 :func:`phase_weight_factor` 的推导）；
      3. ``W_p = S_p·f_p / Σ``（启用微吸收时先把 ``f_p`` 除以 ``τ_p``）。

    **陷阱**：``S`` 与 ``|F|²`` 的绝对标定无关（比例常数在归一化里消掉），
    但要求所有相用同一套散射因子与 LP，**且强度口径与定相因子配套**
    （``I∝|F|²/V²`` 配 ``M/V``；``I∝|F|²`` 配 ``M·V``；``I∝|F|²/V³`` 配 ``M``）。

    微吸收口径：``τ`` 作用在"该相强度"上（``I_obs = τ·I_true``），拟合出的
    ``S`` 已含 ``τ``，真实含量 ∝ ``S/τ`` —— 这里是**除**，不是乘。
    """
    labels = list(labels)
    scales = [float(s) for s in scales]
    if not (len(labels) == len(scales) == len(structures)):
        raise ValueError("labels / scales / structures 长度必须一致")
    if not labels:
        return QuantResult((), (), (), (), (), (), (), ())

    zs, masses, vols, factors = [], [], [], []
    for st in structures:
        sites = tuple(getattr(st, "sites", ()) or ())
        m_cell = mass_per_cell(sites)
        vol = float(st.cell.volume())
        z = _integer_z(_site_counts(sites))
        zs.append(z)
        masses.append(m_cell)
        vols.append(vol)
        factors.append(phase_weight_factor(st))

    base = [max(s, 0.0) * f for s, f in zip(scales, factors)]

    taus: Tuple[float, ...] = ()
    mu_bar = 0.0
    mu_clamped = False
    if mu is not None and len(mu) == len(labels) and float(radius_um) > 0.0:
        fracs_arr, tau_arr, mu_bar, mu_clamped = apply_microabsorption(
            base, mu, float(radius_um), iterations=mu_iterations)
        fracs = [float(v) for v in fracs_arr]
        taus = tuple(float(v) for v in tau_arr)
    else:
        total = float(sum(base))
        if total <= 0.0:
            n = len(labels)
            fracs = [1.0 / n] * n
        else:
            fracs = [w / total for w in base]

    detectable = [bool(f >= min_fraction and s > 0.0)
                  for f, s in zip(fracs, scales)]
    applied = bool(taus)
    return QuantResult(
        labels=tuple(labels), fractions=tuple(fracs), scales=tuple(scales),
        factor=tuple(factors), z=tuple(zs), mass_per_cell=tuple(masses),
        volume=tuple(vols), detectable=tuple(detectable),
        tau=taus, mu_bar=float(mu_bar), mu_clamped=bool(mu_clamped),
        mu=(tuple(float(v) for v in mu) if applied else ()),
        radius_um=(float(radius_um) if applied else 0.0),
    )
