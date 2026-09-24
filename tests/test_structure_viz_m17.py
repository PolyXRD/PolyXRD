"""M17 晶体结构可视化 - 单元测试 (structure_viz + StructureView 离屏)"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib

matplotlib.use("Agg")

import numpy as np

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.services.structure_viz import (
    apply_space_group_symmetry,
    build_atom_spheres,
    build_cell_mesh,
    render_structure,
)

SI_A = 5.4309


def _si_phase():
    """金刚石结构 Si: Fd-3m, 8a 位点 (0,0,0) 为非对称单元。"""
    return Phase(
        name="Si", formula="Si", space_group="Fd-3m",
        lattice=LatticeParams(a=SI_A, b=SI_A, c=SI_A,
                              alpha=90, beta=90, gamma=90),
        atomic_sites=[{"element": "Si", "label": "Si1",
                       "x": 0.0, "y": 0.0, "z": 0.0,
                       "occupancy": 1.0}],
        elements={"Si"},
    )


# ── 对称展开 (路线图验收: Si → 8 原子金刚石晶胞) ──

def test_apply_symmetry_si_diamond_8_atoms():
    phase = _si_phase()
    expanded = apply_space_group_symmetry(phase.atomic_sites, "Fd-3m")
    assert len(expanded) == 8
    # 8 个 Si 全部在 [0,1)³ 内且互不重合
    pts = {(round(s["x"], 3), round(s["y"], 3), round(s["z"], 3))
           for s in expanded}
    assert len(pts) == 8
    for s in expanded:
        assert 0 <= s["x"] < 1 and 0 <= s["y"] < 1 and 0 <= s["z"] < 1


def test_apply_symmetry_idempotent():
    phase = _si_phase()
    once = apply_space_group_symmetry(phase.atomic_sites, "Fd-3m")
    twice = apply_space_group_symmetry(once, "Fd-3m")
    assert len(twice) == 8  # 全胞再展开不变 (幂等)


def test_apply_symmetry_p1_and_garbage():
    sites = [{"element": "Si", "x": 0.0, "y": 0.0, "z": 0.0}]
    assert apply_space_group_symmetry(sites, "P 1") == sites
    assert apply_space_group_symmetry(sites, "??垃圾??") == sites  # 解析失败原样


# ── 晶胞线框 / 原子球 ──

def test_build_cell_mesh_cubic():
    lat = LatticeParams(a=SI_A, b=SI_A, c=SI_A, alpha=90, beta=90, gamma=90)
    edges = build_cell_mesh(lat)
    assert len(edges) == 12
    seg = edges[0]
    length = np.linalg.norm(seg[1] - seg[0])
    assert length == pytest.approx(SI_A)  # 立方棱长 = a


def test_build_atom_spheres_wraps_and_colors():
    phase = _si_phase()
    expanded = apply_space_group_symmetry(phase.atomic_sites, "Fd-3m")
    spheres = build_atom_spheres(expanded, phase.lattice)
    assert len(spheres) == 8
    assert all(s["element"] == "Si" for s in spheres)
    assert all(0 <= s["xyz"][0] < SI_A for s in spheres)
    assert all(s["radius"] > 0 for s in spheres)


# ── 渲染 (Agg 离屏) ──

def test_render_structure_axes_content():
    phase = _si_phase()
    expanded = apply_space_group_symmetry(phase.atomic_sites, "Fd-3m")
    ax = render_structure(phase.lattice, expanded)
    # 12 条棱 = ax.lines 的 Line3D; 8 原子 = scatter (Path3DCollection) 点数
    line_segs = sum(
        len(getattr(c, "get_segments", lambda: [None])())
        for c in ax.lines
    ) if ax.lines else len(ax.lines)
    assert len(ax.lines) == 12
    n_pts = sum(len(c.get_offsets()) for c in ax.collections
                if hasattr(c, "get_offsets"))
    assert n_pts == 8


# ── Qt 控件 (离屏) ──

def test_structure_view_widget():
    from PySide6.QtWidgets import QApplication
    from polyxrd.views.widgets.structure_view import StructureView
    app = QApplication.instance() or QApplication([])
    view = StructureView()
    assert view.count_atoms() == 0  # 初始占位
    view.set_phase(_si_phase())
    assert view.count_atoms() == 8  # Si 金刚石晶胞 8 原子
    view.clear()
    assert view.count_atoms() == 0


def test_structure_view_no_lattice_falls_back():
    from PySide6.QtWidgets import QApplication
    from polyxrd.views.widgets.structure_view import StructureView
    app = QApplication.instance() or QApplication([])
    view = StructureView()
    view.set_phase(Phase(name="empty"))
    assert view.count_atoms() == 0  # 无晶胞 → 占位, 不崩
