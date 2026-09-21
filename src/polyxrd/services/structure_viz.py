"""
晶体结构可视化 (M17)
====================
从 Phase (晶胞 + 原子位点 + 空间群) 生成 3D 结构渲染所需的纯数据:

- apply_space_group_symmetry : 非对称单元 → P1 全胞 (复用 phase_cif 的
  向量化展开实现, 幂等安全)
- build_cell_mesh            : 晶胞 12 条棱的笛卡尔线段
- build_atom_spheres         : 原子球 (元素/笛卡尔坐标/共价半径/CPK 颜色)
- render_structure           : 画进 matplotlib 3D Axes (Axes3D)

原子球用散点近似 (尺寸 ∝ 半径²), 不建真实球面网格 —— 离线可测、
渲染开销低, 对"查看晶胞内原子排布"的用途足够。
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

# 常用元素共价半径 (Å, Cordero 2008 常用子集)
COVALENT_RADII: dict[str, float] = {
    "H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07,
    "S": 1.05, "Cl": 1.02, "K": 2.03, "Ca": 1.76, "Ti": 1.60,
    "Cr": 1.39, "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24,
    "Cu": 1.32, "Zn": 1.22, "Ga": 1.22, "Ge": 1.20, "As": 1.19,
    "Se": 1.20, "Br": 1.20, "Rb": 2.20, "Sr": 1.95, "Y": 1.90,
    "Zr": 1.75, "Nb": 1.64, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42,
    "Pd": 1.39, "Ag": 1.45, "Cd": 1.44, "In": 1.42, "Sn": 1.39,
    "Sb": 1.39, "Te": 1.38, "I": 1.39, "Cs": 2.44, "Ba": 2.15,
    "La": 2.07, "Ce": 2.04, "W": 1.62, "Pt": 1.36, "Au": 1.36,
    "Hg": 1.32, "Pb": 1.46, "Bi": 1.48,
}

# CPK 常用配色 (matplotlib 可识别的颜色串)
CPK_COLORS: dict[str, str] = {
    "H": "#FFFFFF", "C": "#333333", "N": "#3050F8", "O": "#FF0D0D",
    "F": "#90E050", "Cl": "#1FF01F", "Br": "#A62929", "I": "#940094",
    "S": "#FFFF30", "P": "#FF8000", "Si": "#F0C8A0", "Al": "#BFA6A6",
    "Na": "#AB5CF2", "K": "#8F40D4", "Ca": "#3DFF00", "Fe": "#E06633",
    "Cu": "#C88033", "Zn": "#7D80B0", "Mg": "#8AFF00", "Ti": "#BFC2C7",
    "Mn": "#9C7AC7", "Co": "#F090A0", "Ni": "#50D050", "Pb": "#575961",
    "Sn": "#668080", "Ba": "#00C900", "Zr": "#78BA00", "W": "#2194D6",
}

_DEFAULT_RADIUS = 1.2
_DEFAULT_COLOR = "#C8C8C8"
_FALLBACK_PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52",
                     "#8172B3", "#937860", "#DA8BC3"]


def apply_space_group_symmetry(sites: list[dict], space_group) -> list[dict]:
    """非对称单元 → P1 全胞。phase_cif.expand_sites_by_symmetry 的薄壳,
    幂等 (已是全胞则不变), 解析失败原样返回。"""
    from polyxrd.services.phase_cif import expand_sites_by_symmetry
    return expand_sites_by_symmetry(sites, space_group)


def _frac_to_cart_matrix(lattice) -> np.ndarray:
    """分数坐标 → 笛卡尔坐标的 3×3 矩阵 (行向量约定: cart = frac @ M)。

    M 的列即三条基矢: a=(a,0,0), b=(b cosα, b sinα, 0),
    c=(c cosβ, c(cosα-cosβ cosγ)/sinα, V/(a b sinα))
    """
    a, b, c = float(lattice.a), float(lattice.b), float(lattice.c)
    al = math.radians(float(lattice.alpha))
    be = math.radians(float(lattice.beta))
    ga = math.radians(float(lattice.gamma))
    ca, cb, cg = math.cos(al), math.cos(be), math.cos(ga)
    sa = math.sin(al)
    c_x = c * cb
    c_y = c * (ca - cb * cg) / sa
    c_z2 = c * c - c_x * c_x - c_y * c_y
    c_z = math.sqrt(max(c_z2, 0.0))
    return np.array([
        [a, 0.0, 0.0],
        [b * cg, b * sa, 0.0],
        [c_x, c_y, c_z],
    ])


def build_cell_mesh(lattice) -> list[tuple[np.ndarray, np.ndarray]]:
    """晶胞 12 条棱 (笛卡尔 (start, end) 线段列表)。"""
    M = _frac_to_cart_matrix(lattice)
    corners_frac = np.array([
        [0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
        [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1],
    ], dtype=float)
    corners = corners_frac @ M
    edges = [
        (0, 1), (0, 2), (0, 3), (1, 4), (1, 5), (2, 4),
        (2, 6), (3, 5), (3, 6), (4, 7), (5, 7), (6, 7),
    ]
    return [(corners[i], corners[j]) for i, j in edges]


def build_atom_spheres(sites_frac: list[dict], lattice) -> list[dict]:
    """原子球列表: [{element, xyz, radius, color}, ...]。

    - 位点分数坐标 wrap 到 [0, 1) (边界原子不重复绘制)
    - 半径取共价半径 (未知元素 1.2 Å 兜底)
    - 颜色取 CPK (未知元素按序取备用色板, 同元素同色)
    """
    M = _frac_to_cart_matrix(lattice)
    fallback_idx = 0
    out: list[dict] = []
    for s in sites_frac:
        try:
            frac = np.array([float(s["x"]), float(s["y"]), float(s["z"])])
        except (KeyError, TypeError, ValueError):
            continue
        frac = frac - np.floor(frac)
        elem = str(s.get("element") or "").strip()
        if not elem:
            from polyxrd.services.phase_cif import _element_from_label
            elem = _element_from_label(str(s.get("label") or ""))
        radius = COVALENT_RADII.get(elem, _DEFAULT_RADIUS)
        if elem in CPK_COLORS:
            color = CPK_COLORS[elem]
        else:
            color = _FALLBACK_PALETTE[fallback_idx % len(_FALLBACK_PALETTE)]
            fallback_idx += 1
        out.append({
            "element": elem or "?",
            "xyz": frac @ M,
            "radius": radius,
            "color": color,
        })
    return out


def render_structure(lattice, sites_frac: list[dict],
                     ax=None, *, expand: bool = True):
    """把晶胞 + 原子渲染到 matplotlib 3D Axes 并返回该 Axes。

    Args:
        lattice: LatticeParams
        sites_frac: 原子位点 (dict: x/y/z 分数坐标 + element/label)
        ax: 已有 Axes3D; None 时新建 (调用方负责 figure 生命周期)
        expand: True 时先按空间群展开 (phase.space_group 由调用方传入
                前置完成; 本函数只对给定 sites 做几何渲染)
    """
    if ax is None:
        import matplotlib.pyplot as plt
        fig = plt.figure()
        ax = fig.add_subplot(projection="3d")
    for seg_start, seg_end in build_cell_mesh(lattice):
        xs = [seg_start[0], seg_end[0]]
        ys = [seg_start[1], seg_end[1]]
        zs = [seg_start[2], seg_end[2]]
        ax.plot(xs, ys, zs, color="#606060", linewidth=1.0, zorder=1)
    spheres = build_atom_spheres(sites_frac, lattice)
    if spheres:
        ax.scatter(
            [s["xyz"][0] for s in spheres],
            [s["xyz"][1] for s in spheres],
            [s["xyz"][2] for s in spheres],
            s=[max(20.0, 900.0 * s["radius"] ** 2) for s in spheres],
            c=[s["color"] for s in spheres],
            edgecolors="#404040", linewidths=0.5, depthshade=True,
            zorder=2,
        )
    box = max(float(lattice.a), float(lattice.b), float(lattice.c))
    ax.set_xlim(0, box)
    ax.set_ylim(0, box)
    ax.set_zlim(0, box)
    try:
        ax.set_box_aspect((1, 1, 1))
    except AttributeError:  # 旧版 matplotlib 无 set_box_aspect
        pass
    ax.set_xlabel("x (Å)")
    ax.set_ylabel("y (Å)")
    ax.set_zlabel("z (Å)")
    return ax
