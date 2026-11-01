"""原子散射因子 —— Cromer–Mann 8 参数紧凑式（v5.0.0 口径）。

口径钉死（`docs/全谱拟合优化方案-v5.0.0.md` §2.1）::

    f_j(s) = Z_j − 41.78214·s² · Σ_{i=1..4} a_{j,i}·exp(−b_{j,i}·s²)
    s = sinθ/λ = g/2

这是 **8 参数紧凑式**（`f(0) = Z` 严格成立），**不是**教科书常见的 9 参数
`f = c + Σ a_i·exp(−b_i·s²)`；两者系数数值完全不同。系数取自
``pymatgen.analysis.diffraction.xrd.ATOMIC_SCATTERING_PARAMS``
（即 pymatgen 的 ``atomic_scattering_params.json``），与参考工具
（RutAna / LFP / NCA / NCM）逐字同源。

为什么不用 pymatgen 直接算：pymatgen 的 ``XRDCalculator`` 只给一次性静态峰表，
逐原子精修需要**每轮重算 F(hkl)** 并对其求导（阶段 C），必须自己持有系数表。
本模块只负责「系数 → f(s)」，不做反射枚举（见 ``refinement.structure``）。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, Iterable, Optional, Sequence

import numpy as np

# 4 组 (a_i, b_i) 的紧凑式系数个数
N_TERMS = 4
# Cromer–Mann 紧凑式的常数（pymatgen / 参考工具同值）
_CM_CONST = 41.78214


@lru_cache(maxsize=1)
def _periodic_table() -> tuple:
    """元素符号表（Z = 下标 + 1）。

    唯一真源 = ``polyxrd.services.polydb.ELEMENTS``（118 个，有守卫
    ``tests/test_polydb_elements.py``）；导入失败时退回内置表，保证服务层
    在裁剪环境（例如只装了 refinement 子包）里也能工作。
    """
    try:
        from polyxrd.services.polydb import ELEMENTS

        if len(ELEMENTS) == 118:
            return tuple(ELEMENTS)
    except Exception:  # noqa: BLE001 - 元素表缺失不该让精修整体不可用
        pass
    return _FALLBACK_ELEMENTS


# 兜底元素表（只在 polydb 不可导入时使用；数值顺序 = IUPAC 原子序数）
_FALLBACK_ELEMENTS = (
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)


@lru_cache(maxsize=1)
def _z_of() -> Dict[str, int]:
    """``{元素符号: 原子序数}``（大小写不敏感由调用方归一）。"""
    return {sym: i + 1 for i, sym in enumerate(_periodic_table())}


def normalize_element(symbol: object) -> str:
    """把 ``'fe'``/``'FE'``/``'Fe3+'``/``'O2-'`` 归一成 ``'Fe'``/``'O'``。

    只取字母前缀（最多 2 个字母）：电荷、氧化态、位点编号一律丢弃。
    """
    text = str(symbol or "").strip()
    letters = ""
    for ch in text:
        if ch.isalpha():
            letters += ch
            if len(letters) == 2:
                break
        elif letters:
            break
    if not letters:
        return ""
    return letters[0].upper() + letters[1:].lower()


def atomic_number(element: object) -> int:
    """原子序数；认不出返回 0（调用方据此跳过该位点）。"""
    sym = normalize_element(element)
    return _z_of().get(sym, 0)


@lru_cache(maxsize=1)
def _scattering_params() -> Dict[str, np.ndarray]:
    """``{元素: ndarray(4, 2)}`` —— ``[:, 0] = a_i``，``[:, 1] = b_i``。

    数据源：pymatgen 的 ``ATOMIC_SCATTERING_PARAMS``（99 个元素，含常见全部）。
    导入失败返回空表（此时散射因子退化为常数 ``Z``，见 :func:`atomic_form_factor`
    的降级说明）。
    """
    try:
        from pymatgen.analysis.diffraction.xrd import (  # type: ignore
            ATOMIC_SCATTERING_PARAMS,
        )
    except Exception:  # noqa: BLE001 - pymatgen 缺失时降级，不炸整个精修
        return {}
    params: Dict[str, np.ndarray] = {}
    for elem, coeffs in dict(ATOMIC_SCATTERING_PARAMS).items():
        try:
            arr = np.asarray(coeffs, dtype=float)
        except (TypeError, ValueError):
            continue
        if arr.shape != (N_TERMS, 2) or not np.all(np.isfinite(arr)):
            continue
        params[str(elem)] = arr
    return params


def has_scattering_params(element: object) -> bool:
    """该元素是否有 Cromer–Mann 系数（否则只能退化为常数 Z）。"""
    return normalize_element(element) in _scattering_params()


def scattering_coefficients(element: object) -> Optional[np.ndarray]:
    """返回 ``(4, 2)`` 系数数组；无系数返回 ``None``。"""
    return _scattering_params().get(normalize_element(element))


def atomic_form_factor(element: object, s) -> np.ndarray:
    """原子散射因子 ``f(s)``。

    :param element: 元素符号（``'Fe'`` / ``'fe'`` / ``'O2-'`` 均可）
    :param s: ``sinθ/λ``（与 λ 同单位，通常 Å⁻¹），标量或任意形状数组
    :return: 与 ``s`` 同形状的 ``f``；无系数时退化为常数 ``Z``（并置 0 依赖）

    降级行为：元素缺系数 → ``f ≡ Z``（相当于把原子当点电荷）。这会让高角
    强度偏高，故 :func:`has_scattering_params` 供调用方决定是否告警。
    """
    z = atomic_number(element)
    if z <= 0:
        return np.zeros_like(np.asarray(s, dtype=float))
    s_arr = np.asarray(s, dtype=float)
    coeffs = scattering_coefficients(element)
    if coeffs is None:
        return np.full(s_arr.shape, float(z)) if s_arr.ndim else float(z)
    s2 = s_arr * s_arr
    # Σ a_i·exp(−b_i·s²) —— 逐项累加（4 项，比 einsum 更快且更省内存）
    acc = np.zeros_like(s2, dtype=float)
    for a_i, b_i in coeffs:
        acc = acc + float(a_i) * np.exp(-float(b_i) * s2)
    return float(z) - _CM_CONST * s2 * acc


class ScatteringTable:
    """把一组元素的系数排成连续数组，便于对**全部位点**一次性求 ``f``。

    热路径用法::

        table = ScatteringTable(["Li", "Fe", "P", "O"])
        f = table.form_factors(s)      # (n_elem, *s.shape)
        f_sites = f[elem_index]        # (n_sites, *s.shape) —— 用位点的元素下标取

    这样每轮迭代只有 4 次 ``exp``，与位点数无关（位点数只影响后面的 ``exp(i·phase)``）。
    """

    __slots__ = ("elements", "z", "a", "b", "_index", "missing")

    def __init__(self, elements: Iterable[object]) -> None:
        uniq: list[str] = []
        seen: set[str] = set()
        for raw in elements:
            sym = normalize_element(raw)
            if not sym or sym in seen:
                continue
            seen.add(sym)
            uniq.append(sym)
        self.elements: tuple = tuple(uniq)
        n = len(uniq)
        self.z = np.zeros(n, dtype=float)
        self.a = np.zeros((n, N_TERMS), dtype=float)
        self.b = np.zeros((n, N_TERMS), dtype=float)
        self.missing: list[str] = []
        for i, sym in enumerate(uniq):
            self.z[i] = float(atomic_number(sym))
            coeffs = scattering_coefficients(sym)
            if coeffs is None:
                self.missing.append(sym)
                self.b[i] = np.inf  # exp(−inf·s²) = 0 → 退化为常数 Z
            else:
                self.a[i] = coeffs[:, 0]
                self.b[i] = coeffs[:, 1]
        self._index = {sym: i for i, sym in enumerate(uniq)}

    def index(self, element: object) -> int:
        """元素在表内的行号；不在表中返回 ``-1``。"""
        return self._index.get(normalize_element(element), -1)

    def form_factors(self, s) -> np.ndarray:
        """``(n_elem, *s.shape)`` 的 ``f`` 表。"""
        s_arr = np.asarray(s, dtype=float)
        s2 = s_arr * s_arr
        # (n_elem, 4) × s² → 逐项指数：用广播一次性算完
        shape = (self.z.shape[0],) + s2.shape
        acc = np.zeros(shape, dtype=float)
        for i in range(N_TERMS):
            # b[:, i] 形状 (n_elem,)；s2 形状 (*s2.shape,) → 广播成 (n_elem, *s2.shape)
            expo = np.exp(-self.b[:, i].reshape((self.z.shape[0],) + (1,) * s2.ndim) * s2)
            acc += self.a[:, i].reshape((self.z.shape[0],) + (1,) * s2.ndim) * expo
        return self.z.reshape((self.z.shape[0],) + (1,) * s2.ndim) - _CM_CONST * s2 * acc


def form_factors_for_elements(elements: Sequence[object], s) -> np.ndarray:
    """便捷函数：一次算一组元素的 ``f``（内部建表，适合非热路径）。"""
    return ScatteringTable(elements).form_factors(s)
