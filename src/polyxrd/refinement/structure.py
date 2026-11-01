"""结构模型与反射表 —— 自写结构因子（v5.0.0 阶段 A1）。

职责：``位点 → 对称展开 → 倒易枚举 → |F(hkl)|² → ×LP → 2θ 归并`` 得到
**强度已知、峰形未知**的反射表。峰形（pV / Caglioti / 择优取向 / 尺寸应变）
在 :mod:`polyxrd.refinement.profile` 里施加，两者严格分离 —— 这正是
「缓存键不含峰形参数」的实现基础（方案 §2.2）。

口径（钉死，见方案 §2.1）::

    F(hkl) = Σ_j f_j(s)·occ_j·exp(−B_j·s²)·exp(2πi(h·x_j + k·y_j + l·z_j))
    |F|²   = Re(F)² + Im(F)²
    s      = sinθ/λ = g/2 = 1/(2d)     ← 注意与波长无关
    I_hkl  = |F|² · LP(2θ) · w_λ       ← w_λ 为 Kα 分量权重
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import numpy as np

from polyxrd.refinement.cell import (
    Cell,
    cell_angle_cosines,
    d_spacings,
    lorentz_polarization,
    reciprocal_magnitudes,
    two_theta_from_g,
)
from polyxrd.refinement.scattering import (
    ScatteringTable,
    atomic_number,
    normalize_element,
)

# 峰合并容差（度）：同 2θ 内的反射强度相加（RutAna / LFP 同值）
TWO_THETA_MERGE_TOL = 1e-3
# 缺 Biso 时的默认值（Å²）—— 对应 U_iso ≈ 0.0063，接近常见无机物量级
B_ISO_DEFAULT = 0.5
# 反射枚举的最小半宽（防止极小晶胞时 H 过小漏反射）
MIN_H = 6


@dataclass(frozen=True)
class AtomSite:
    """一个（已完成对称展开的）原子位点。"""

    element: str
    x: float
    y: float
    z: float
    occupancy: float = 1.0
    b_iso: float = B_ISO_DEFAULT
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label or self.element,
            "element": self.element,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "occupancy": self.occupancy,
            "b_iso": self.b_iso,
        }


def _as_float(value, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def site_from_dict(raw: dict) -> Optional[AtomSite]:
    """把 ``phase.atomic_sites`` 里的 dict 归一成 :class:`AtomSite`。

    容错：缺 ``element`` 时从 ``label`` 推断；``occupancy`` 缺省 1.0；
    ``b_iso`` 优先 ``b_iso`` → ``biso`` → ``u_iso``（``B = 8π²U``）→ 默认 0.5。
    坐标非有限 → 返回 ``None``（调用方跳过该位点）。
    """
    if not isinstance(raw, dict):
        return None
    element = normalize_element(raw.get("element") or raw.get("label") or "")
    if not element or atomic_number(element) <= 0:
        return None
    x = _as_float(raw.get("x"), float("nan"))
    y = _as_float(raw.get("y"), float("nan"))
    z = _as_float(raw.get("z"), float("nan"))
    if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(z)):
        return None
    occ = _as_float(raw.get("occupancy", raw.get("occ", 1.0)), 1.0)
    if occ < 0.0:
        occ = 0.0
    b_raw = raw.get("b_iso", raw.get("biso", None))
    if b_raw is None:
        u_raw = raw.get("u_iso", raw.get("uiso", None))
        b_iso = float(8.0 * np.pi ** 2 * _as_float(u_raw, 0.0)) if u_raw is not None else B_ISO_DEFAULT
    else:
        b_iso = _as_float(b_raw, B_ISO_DEFAULT)
    return AtomSite(
        element=element, x=x, y=y, z=z, occupancy=occ, b_iso=float(b_iso),
        label=str(raw.get("label") or element),
    )


@dataclass
class StructureModel:
    """精修用的最小结构模型（已展开为 P1 全胞）。"""

    sites: tuple = ()
    cell: Cell = field(default_factory=lambda: Cell(1.0, 1.0, 1.0))
    space_group: str = ""
    name: str = ""
    formula: str = ""
    missing_scattering: tuple = ()

    # ---- 构造 ------------------------------------------------------------
    @classmethod
    def from_phase(cls, phase, *, expand: bool = True, default_b_iso: float = B_ISO_DEFAULT,
                   **_) -> Optional["StructureModel"]:
        """从 ``Phase`` 构造；无晶胞或无位点返回 ``None``。

        ``expand=True`` 时按空间群把非对称单元展开成 P1 全胞
        （复用 ``phase_cif.expand_sites_by_symmetry``，幂等安全）。
        """
        lat = getattr(phase, "lattice", None)
        if lat is None:
            return None
        cell = Cell(
            a=_as_float(getattr(lat, "a", 0.0)),
            b=_as_float(getattr(lat, "b", 0.0)),
            c=_as_float(getattr(lat, "c", 0.0)),
            alpha=_as_float(getattr(lat, "alpha", 90.0), 90.0),
            beta=_as_float(getattr(lat, "beta", 90.0), 90.0),
            gamma=_as_float(getattr(lat, "gamma", 90.0), 90.0),
        )
        if min(cell.a, cell.b, cell.c) <= 0.0:
            return None
        raw_sites = list(getattr(phase, "atomic_sites", None) or [])
        if not raw_sites:
            return None
        if expand:
            try:
                from polyxrd.services.phase_cif import expand_sites_by_symmetry

                expanded = expand_sites_by_symmetry(
                    raw_sites, getattr(phase, "space_group", None)
                )
                if expanded:
                    raw_sites = list(expanded)
            except Exception:  # noqa: BLE001 - 展开失败就用原样（幂等安全）
                pass
        sites: list[AtomSite] = []
        for raw in raw_sites:
            site = site_from_dict(raw) if isinstance(raw, dict) else None
            if site is None:
                continue
            if default_b_iso != B_ISO_DEFAULT and "b_iso" not in raw and "biso" not in raw \
                    and "u_iso" not in raw and "uiso" not in raw:
                site = AtomSite(site.element, site.x, site.y, site.z,
                                site.occupancy, float(default_b_iso), site.label)
            sites.append(site)
        if not sites:
            return None
        return cls(
            sites=tuple(sites),
            cell=cell,
            space_group=str(getattr(phase, "space_group", "") or ""),
            name=str(getattr(phase, "name", "") or ""),
            formula=str(getattr(phase, "formula", "") or ""),
        )

    # ---- 派生量 ----------------------------------------------------------
    def elements(self) -> tuple:
        """去重后的元素序列（保序）。"""
        out: list[str] = []
        for s in self.sites:
            if s.element not in out:
                out.append(s.element)
        return tuple(out)

    def __len__(self) -> int:
        return len(self.sites)

    def site_arrays(self):
        """``(xyz (M,3), occ (M,), b_iso (M,), elem_idx (M,))``，元素下标对
        :meth:`scattering_table` 的行号。"""
        table = self.scattering_table()
        xyz = np.array([[s.x, s.y, s.z] for s in self.sites], dtype=float)
        occ = np.array([s.occupancy for s in self.sites], dtype=float)
        b_iso = np.array([s.b_iso for s in self.sites], dtype=float)
        idx = np.array([table.index(s.element) for s in self.sites], dtype=int)
        return xyz, occ, b_iso, idx

    def scattering_table(self) -> ScatteringTable:
        """元素散射因子表（按元素去重；每次调用重建，调用方可自行缓存）。"""
        return ScatteringTable(self.elements())

    def f_reference_sq(self) -> float:
        """``(Σ Z_j·occ_j)²`` —— s=0 处 |F|² 的理论上限，用于噪声峰阈值。"""
        return float(sum(atomic_number(s.element) * s.occupancy for s in self.sites) ** 2)

    def composition(self) -> dict:
        """``{元素: 全胞原子数(含占位)}``。"""
        out: dict = {}
        for s in self.sites:
            out[s.element] = out.get(s.element, 0.0) + s.occupancy
        return out

    # ---- 结构因子 --------------------------------------------------------
    def structure_factor_sq(self, hkl: np.ndarray, *, table: Optional[ScatteringTable] = None,
                            xyz=None, occ=None, b_iso=None, elem_idx=None) -> np.ndarray:
        """``|F(hkl)|²`` 批量计算。

        :param hkl: ``(N, 3)``
        :param table/xyz/occ/b_iso/elem_idx: 可选预取（热循环里避免重复构造）
        :return: ``(N,)``

        逐原子 occ / b_iso 从这里进入模型 —— 阶段 C 把它们变成可精修参数后，
        只需在每次评估时传入新的 ``occ``/``b_iso``/``xyz``，无需改本函数。
        """
        hkl = np.asarray(hkl, dtype=float).reshape(-1, 3)
        if hkl.shape[0] == 0:
            return np.zeros(0, dtype=float)
        if table is None or xyz is None or occ is None or b_iso is None or elem_idx is None:
            xyz, occ, b_iso, elem_idx = self.site_arrays()
            table = self.scattering_table()
        # s = 1/(2d) 与波长无关
        g_mag = reciprocal_magnitudes(hkl, self.cell)
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where(g_mag > 1e-12, g_mag / 2.0, 0.0)
        s2 = s * s
        # f: (n_elem, N) → 取位点行 (M, N)
        f_elem = table.form_factors(s)
        f_sites = f_elem[elem_idx]                            # (M, N)
        amp = f_sites * occ[:, None] * np.exp(-b_iso[:, None] * s2[None, :])  # (M, N)
        phase = 2.0 * np.pi * (hkl @ xyz.T)                   # (N, M)
        cos_p, sin_p = np.cos(phase), np.sin(phase)
        re = np.einsum("nm,mn->n", cos_p, amp)                # (N,)
        im = np.einsum("nm,mn->n", sin_p, amp)
        return re * re + im * im


# ---------------------------------------------------------------------------
# 反射枚举与归并
# ---------------------------------------------------------------------------
def enumerate_hkl(cell: Cell, two_theta_range: Sequence[float],
                  wavelengths: Sequence[float]) -> np.ndarray:
    """枚举落在 2θ 窗口内的全部 hkl（含等价反射，即自动含多重性）。

    每个轴的半宽按该轴倒易基矢模长反算（比参考实现的统一 H 更稳）::

        H_i = ceil(max_g / |b_i|) + 1,  且 H_i >= MIN_H
        max_g = 2·sin(θ_max)/λ_min,  min_g = 2·sin(θ_min)/λ_max
    """
    tmin, tmax = float(two_theta_range[0]), float(two_theta_range[1])
    lams = [float(w) for w in wavelengths if float(w) > 0]
    if not lams or tmax <= 0:
        return np.zeros((0, 3), dtype=int)
    max_g = 2.0 * np.sin(np.radians(max(tmax, 0.0)) / 2.0) / min(lams)
    min_g = 2.0 * np.sin(np.radians(max(tmin, 0.0)) / 2.0) / max(lams)

    B = cell.reciprocal_vectors()
    b_mag = np.linalg.norm(B, axis=1)
    b_mag = np.where(b_mag > 1e-12, b_mag, 1e-12)
    H = np.maximum(np.ceil(max_g / b_mag).astype(int) + 1, MIN_H)

    h = np.arange(-H[0], H[0] + 1)
    k = np.arange(-H[1], H[1] + 1)
    l = np.arange(-H[2], H[2] + 1)
    grid = np.stack(np.meshgrid(h, k, l, indexing="ij"), axis=-1).reshape(-1, 3)
    g_all = reciprocal_magnitudes(grid, cell)
    mask = (g_all >= min_g * 0.999) & (g_all <= max_g * 1.001) & (g_all > 1e-12)
    return grid[mask]


@dataclass
class ReflectionTable:
    """一个物相在给定波长/窗口下的反射表（**峰形未知**）。

    ``intensity`` 是 ``|F|²·LP·w_λ`` 归并求和后的值（未乘标度、未施择优取向）。
    ``po_detail`` 保存每个归并峰的逐反射贡献，供择优取向 ``r`` 变化时做
    O(峰数) 重加权（避免重算整张表）::

        detail_value[offsets[i]:offsets[i+1]]  # 该峰各反射的 |F|²·LP·w_λ
        detail_cos[offsets[i]:offsets[i+1]]    # 对应反射的 cosα
    """

    hkl: np.ndarray
    d: np.ndarray
    two_theta: np.ndarray
    intensity: np.ndarray
    n_merged: np.ndarray
    f_ref_sq: float
    po_detail: Optional[tuple] = None    # (values, cos_alpha, offsets)
    wavelength_tag: float = 0.0

    def __len__(self) -> int:
        return int(self.two_theta.shape[0])

    def reweight_po(self, r: float) -> np.ndarray:
        """按 March–Dollase ``r`` 重加权并返回新的 ``intensity``。

        ``r == 1`` 或无明细时直接返回原数组（零开销）。
        """
        if self.po_detail is None or not np.isfinite(r) or abs(float(r) - 1.0) < 1e-12:
            return self.intensity
        values, cos_a, offsets = self.po_detail
        weight = march_dollase_weight(cos_a, r)
        seg = values * weight
        return np.add.reduceat(seg, offsets[:-1]) if seg.size else self.intensity


def march_dollase_weight(cos_alpha, r: float) -> np.ndarray:
    """March–Dollase 择优取向权重 ``W=(r²cos²α + r⁻¹sin²α)^(−3/2)``。

    ``r = 1`` → 1.0（无择优）；``r < 1`` 片状/板状惯习；``r > 1`` 针状/柱状。
    """
    cos_a = np.asarray(cos_alpha, dtype=float)
    rr = float(r)
    if not np.isfinite(rr) or rr <= 0.0:
        return np.ones_like(cos_a)
    c2 = cos_a * cos_a
    s2 = 1.0 - c2
    base = rr * rr * c2 + s2 / rr
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.power(np.where(base > 1e-12, base, 1e-12), -1.5)
    return np.where(np.isfinite(out), out, 1.0)


def normalize_wavelengths(wavelengths) -> tuple:
    """把波长输入归一成 ``((λ, 权重), ...)``。

    支持三种写法：
      * 单个 float → 单色 ``((λ, 1.0),)``
      * ``[(λ1, w1), (λ2, w2)]`` → 原样（权重自动归一）
      * ``[λ1, λ2]`` → 等权
    """
    if wavelengths is None:
        return ()
    if isinstance(wavelengths, (int, float)):
        w = float(wavelengths)
        return ((w, 1.0),) if w > 0 else ()
    items = list(wavelengths)
    pairs: list[tuple] = []
    for it in items:
        if isinstance(it, (int, float)):
            lam, wgt = float(it), 1.0
        elif isinstance(it, (tuple, list)) and len(it) >= 2:
            lam, wgt = float(it[0]), float(it[1])
        else:
            continue
        if lam > 0 and wgt > 0:
            pairs.append((lam, wgt))
    if not pairs:
        return ()
    total = sum(w for _, w in pairs)
    return tuple((lam, w / total) for lam, w in pairs)


def build_reflections(
    structure: StructureModel,
    *,
    two_theta_range: Sequence[float] = (5.0, 120.0),
    wavelengths=(1.54056,),
    po_direction: Optional[Sequence[float]] = None,
    noise_ratio: float = 1e-9,
) -> ReflectionTable:
    """构造反射表（峰形未施加）。

    :param wavelengths: 见 :func:`normalize_wavelengths`；Kα2 双线在此拆开
    :param po_direction: 择优面法向（笛卡尔）。给定则计算 ``cosα`` 并保存明细，
        供后续 ``ReflectionTable.reweight_po(r)`` 廉价重加权
    :param noise_ratio: 强度低于 ``noise_ratio · f_ref²`` 的反射丢弃
        （相消干涉的浮点残差峰）
    """
    comps = normalize_wavelengths(wavelengths)
    if not comps:
        raise ValueError("build_reflections: 波长无效")
    tmin, tmax = float(two_theta_range[0]), float(two_theta_range[1])
    hkl = enumerate_hkl(structure.cell, (tmin, tmax), [lam for lam, _ in comps])
    if hkl.shape[0] == 0:
        return ReflectionTable(
            hkl=np.zeros((0, 3), dtype=int), d=np.zeros(0), two_theta=np.zeros(0),
            intensity=np.zeros(0), n_merged=np.zeros(0, dtype=int),
            f_ref_sq=structure.f_reference_sq(),
        )

    xyz, occ, b_iso, elem_idx = structure.site_arrays()
    table = structure.scattering_table()
    fsq = structure.structure_factor_sq(
        hkl, table=table, xyz=xyz, occ=occ, b_iso=b_iso, elem_idx=elem_idx
    )
    g_mag = reciprocal_magnitudes(hkl, structure.cell)
    d_all = np.where(g_mag > 1e-12, 1.0 / np.maximum(g_mag, 1e-12), np.inf)

    # 逐波长分量：各自算 2θ（LP 随 2θ 略变，必须分量单独算）
    #
    # **1/V² 不能漏**：Bragg–Brentano 的积分强度是
    #     I_hkl = (λ³/64π)·(m/V²)·|F_hkl|²·LP·…
    # 少掉 V² 时单相精修毫无察觉（标度把常数全吃掉了），但**多相之间强度就
    # 不可比** —— 方解石 V=368 Å³、ZnO V=47.6 Å³，差 (368/47.6)²≈60 倍，
    # Hill–Howard 的 W∝S·M·V 会直接跑偏（实测 2-1 给出 0% / 0%）。
    # 酸检用例发现不了：它按 ``s = w/zmv`` 反解再合成，验的是代数自洽而非物理。
    vol_sq = float(structure.cell.volume()) ** 2
    norm = 1.0 / vol_sq if vol_sq > 1e-20 else 1.0
    tth_parts, int_parts, hkl_parts, d_parts = [], [], [], []
    for lam, wgt in comps:
        tth = two_theta_from_g(g_mag, lam)
        mask = np.isfinite(tth) & (tth >= tmin - 1e-9) & (tth <= tmax + 1e-9)
        if not np.any(mask):
            continue
        lp = lorentz_polarization(tth[mask])
        inten = fsq[mask] * lp * float(wgt) * norm
        tth_parts.append(tth[mask])
        int_parts.append(inten)
        hkl_parts.append(hkl[mask])
        d_parts.append(d_all[mask])
    if not tth_parts:
        return ReflectionTable(
            hkl=np.zeros((0, 3), dtype=int), d=np.zeros(0), two_theta=np.zeros(0),
            intensity=np.zeros(0), n_merged=np.zeros(0, dtype=int),
            f_ref_sq=structure.f_reference_sq(),
        )

    tth_all = np.concatenate(tth_parts)
    int_all = np.concatenate(int_parts)
    hkl_all = np.concatenate(hkl_parts)
    d_all = np.concatenate(d_parts)

    # 噪声峰阈值
    f_ref_sq = float(structure.f_reference_sq())
    thr = max(f_ref_sq * float(noise_ratio), 0.0)
    keep = np.isfinite(int_all) & (int_all > thr)
    tth_all, int_all, hkl_all, d_all = tth_all[keep], int_all[keep], hkl_all[keep], d_all[keep]
    if tth_all.size == 0:
        return ReflectionTable(
            hkl=np.zeros((0, 3), dtype=int), d=np.zeros(0), two_theta=np.zeros(0),
            intensity=np.zeros(0), n_merged=np.zeros(0, dtype=int), f_ref_sq=f_ref_sq,
        )

    # 按 2θ 归并（容差 1e-3°）：强度求和、记合并数、代表 hkl 取最强贡献
    order = np.argsort(tth_all, kind="stable")
    tth_s, int_s, hkl_s, d_s = tth_all[order], int_all[order], hkl_all[order], d_all[order]
    keys = np.round(tth_s / TWO_THETA_MERGE_TOL).astype(np.int64)
    # 相邻 key 变化处切段（已排序，等价于 groupby）
    if keys.size == 1:
        starts = np.array([0])
        n_merged = np.array([1])
    else:
        change = np.empty(keys.size, dtype=bool)
        change[0] = True
        change[1:] = keys[1:] != keys[:-1]
        starts = np.flatnonzero(change)
        n_merged = np.diff(np.append(starts, keys.size))

    int_merged = np.add.reduceat(int_s, starts)
    tth_merged = np.add.reduceat(tth_s * int_s, starts) / np.maximum(int_merged, 1e-300)
    # 代表 hkl / d：段内最强贡献
    seg_max_idx = []
    for i, st in enumerate(starts):
        en = st + int(n_merged[i])
        seg_max_idx.append(st + int(np.argmax(int_s[st:en])))
    seg_max_idx = np.array(seg_max_idx, dtype=int)
    hkl_merged = hkl_s[seg_max_idx].astype(int)
    d_merged = d_s[seg_max_idx]

    po_detail = None
    if po_direction is not None:
        cos_a = cell_angle_cosines(hkl_s, po_direction, structure.cell)
        po_detail = (int_s.astype(float), cos_a.astype(float),
                     np.append(starts, keys.size).astype(int))

    return ReflectionTable(
        hkl=hkl_merged,
        d=d_merged,
        two_theta=tth_merged,
        intensity=int_merged,
        n_merged=n_merged.astype(int),
        f_ref_sq=f_ref_sq,
        po_detail=po_detail,
        wavelength_tag=float(comps[0][0]),
    )


def po_direction_from_hkl(hkl: Sequence[float], cell: Cell) -> np.ndarray:
    """把择优面 hkl 换成笛卡尔单位法向（倒易空间）。"""
    hkl_arr = np.asarray(hkl, dtype=float).reshape(1, 3)
    # 与 cell.d_spacings 同口径：B 的行即倒易基矢，故 g = hkl @ B（不转置）
    g = hkl_arr @ cell.reciprocal_vectors()
    v = g.reshape(3)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])
