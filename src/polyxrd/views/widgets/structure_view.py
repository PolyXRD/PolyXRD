"""
晶体结构 3D 视图控件 (M17)
==========================
StructureView(QWidget): matplotlib 3D 画布, set_phase(phase) 后渲染
晶胞线框 + 原子球 (自动按空间群展开非对称单元)。

用法:
    view = StructureView(parent)
    view.set_phase(phase)          # Phase 模型
    view.clear()
"""
from __future__ import annotations

from typing import Optional

from polyxrd.i18n import tr

from PySide6.QtWidgets import QVBoxLayout, QWidget

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from polyxrd.services.structure_viz import (
    apply_space_group_symmetry,
    build_atom_spheres,
    build_cell_mesh,
    render_structure,
)


class StructureView(QWidget):
    """晶体结构 3D 渲染控件 (CIF 详情 / 物相详情挂接点)。"""

    def __init__(self, parent: Optional[QWidget] = None,
                 height: int = 280) -> None:
        super().__init__(parent)
        self._figure = Figure(figsize=(4, 3), dpi=100)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setStyleSheet("background-color: transparent;")
        self._ax = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._canvas)
        self.setMinimumHeight(height)
        self.clear()

    # ── 公开接口 ──

    def clear(self) -> None:
        """显示占位提示 (无结构可选时)。"""
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.axis("off")
        ax.text(0.5, 0.5, tr("vw.structure_view.placeholder"), ha="center", va="center",
                fontsize=10, color="#808080", transform=ax.transAxes)
        self._ax = None
        self._canvas.draw_idle()

    def set_phase(self, phase) -> None:
        """渲染一个 Phase (晶胞 + 位点 + 空间群)。数据不全时显示占位。"""
        lat = getattr(phase, "lattice", None)
        sites = list(getattr(phase, "atomic_sites", []) or [])
        if lat is None or not lat.a:
            self.clear()
            return
        try:
            if sites:
                sites = apply_space_group_symmetry(
                    sites, getattr(phase, "space_group", ""))
        except Exception:  # noqa: BLE001 - 展开失败 → 用原始位点渲染
            sites = list(getattr(phase, "atomic_sites", []) or [])
        self._render(lat, sites)

    def set_structure(self, lattice, sites_frac: list[dict]) -> None:
        """直接给定晶胞与位点 (跳过对称展开)。"""
        if lattice is None or not sites_frac:
            self.clear()
            return
        self._render(lattice, sites_frac)

    # ── 内部 ──

    def _render(self, lattice, sites: list[dict]) -> None:
        self._figure.clear()
        ax = self._figure.add_subplot(projection="3d")
        try:
            render_structure(lattice, sites, ax=ax)
        except Exception:  # noqa: BLE001 - 渲染失败不崩 UI
            self.clear()
            return
        self._ax = ax
        self._canvas.draw_idle()

    def count_atoms(self) -> int:
        """当前画布上的原子球数 (测试/自检用)。"""
        if self._ax is None:
            return 0
        spheres = 0
        # scatter 命中的偏移集合数量
        for child in self._ax.collections:
            offsets = getattr(child, "get_offsets", None)
            if offsets is not None:
                spheres += len(offsets())
        return spheres
