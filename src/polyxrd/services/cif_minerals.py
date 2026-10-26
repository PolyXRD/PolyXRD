"""内置矿物 CIF 库（12 种矿物的内置 CIF 数据，不含 COD sqlite 运行时）。

v4.2 从 ``cif_database.py`` 抽出的 library 部分：只管理
"内置矿物 + 用户导入的外部 CIF" 两张表，**不碰任何 sqlite 库**。

对外接口（与原类同名，便于 P2 平滑切换）::

    lib = CifMineralLibrary()
    lib.get_phase_list()                # 内置 + 外部
    lib.search("quartz")                # 式子/名称/空间群综合搜索
    lib.get_phase("SiO2")               # -> Phase
    lib.load_cif_file("my.cif")         # 导入外部 CIF
    lib.export_cif("SiO2", "./out")     # 导出内置 CIF

约束
----
* 不 import sqlite3 / PySide6 / 不读配置路径（``~/.polyxrd`` 由调用方负责）。
* 依赖仅 ``polyxrd.models.phase``（Phase / LatticeParams）+ numpy。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.models.phase import LatticeParams, Phase


# ──────────────────────────────────────────────────────────────
# 12种常见矿物的内置CIF数据
# ──────────────────────────────────────────────────────────────

_BUILTIN_MINERALS: dict[str, dict] = {}


def _register(key: str, data: dict) -> None:
    data.setdefault("key", key)
    _BUILTIN_MINERALS[key] = data


# ── Silicon (Si) ──────────────────────────────────────────────
_register("Si", {
    "name": "Silicon",
    "formula": "Si",
    "space_group": "Fd-3m",
    "space_group_number": 227,
    "lattice": {"a": 5.431, "b": 5.431, "c": 5.431,
                "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "Si1", "element": "Si", "x": 0.0000, "y": 0.0000, "z": 0.0000, "occupancy": 1.0},
        {"label": "Si2", "element": "Si", "x": 0.2500, "y": 0.2500, "z": 0.2500, "occupancy": 1.0},
    ],
    "cif": """data_Silicon
_cell_length_a 5.431
_cell_length_b 5.431
_cell_length_c 5.431
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'Fd-3m'
_symmetry_Int_Tables_number 227
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,y+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y+1/2,-z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,-y+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,y+1/2,z'
_symmetry_equiv_pos_as_xyz '-z,x,y'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x+1/2,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,x,-y+1/2'
_symmetry_equiv_pos_as_xyz 'z,-x,y+1/2'
_symmetry_equiv_pos_as_xyz 'z,x,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,-x,y+1/2'
_symmetry_equiv_pos_as_xyz '-z,x+1/2,-y+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x+1/2,-y'
_symmetry_equiv_pos_as_xyz 'y,z,x'
_symmetry_equiv_pos_as_xyz '-y+1/2,-z,x+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,-z+1/2,x'
_symmetry_equiv_pos_as_xyz '-y,z+1/2,x+1/2'
_symmetry_equiv_pos_as_xyz '-y,-z,-x'
_symmetry_equiv_pos_as_xyz 'y+1/2,z,-x+1/2'
_symmetry_equiv_pos_as_xyz 'y,z+1/2,x+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,-z+1/2,-x'
_symmetry_equiv_pos_as_xyz '-x,-z,-y'
_symmetry_equiv_pos_as_xyz 'x+1/2,z,-y+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,-z+1/2,y'
_symmetry_equiv_pos_as_xyz 'x,z+1/2,y+1/2'
_symmetry_equiv_pos_as_xyz 'x,-z,-y'
_symmetry_equiv_pos_as_xyz '-x+1/2,z+1/2,y'
_symmetry_equiv_pos_as_xyz '-x,-z+1/2,-y+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,-z+1/2,-y'
_symmetry_equiv_pos_as_xyz '-y,-x,-z'
_symmetry_equiv_pos_as_xyz 'y+1/2,x,z+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,-x+1/2,z'
_symmetry_equiv_pos_as_xyz 'y,-x+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz 'y,x,z'
_symmetry_equiv_pos_as_xyz '-y+1/2,-x,z+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,-x+1/2,z'
_symmetry_equiv_pos_as_xyz '-y,x+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz '-z,-x,-y'
_symmetry_equiv_pos_as_xyz 'z+1/2,x+1/2,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,-x,y+1/2'
_symmetry_equiv_pos_as_xyz 'z,-x+1/2,y+1/2'
_symmetry_equiv_pos_as_xyz 'z,x,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,x+1/2,y'
_symmetry_equiv_pos_as_xyz '-z,-x+1/2,-y+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x,-y'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0.0000 0.0000 0.0000 1.00
Si2 Si 0.2500 0.2500 0.2500 1.00
"""
})


# ── α-Quartz (SiO2) ──────────────────────────────────────────
_register("SiO2", {
    "name": "α-Quartz",
    "formula": "SiO2",
    "space_group": "P3121",
    "space_group_number": 152,
    "lattice": {"a": 4.913, "b": 4.913, "c": 5.405,
                "alpha": 90.0, "beta": 90.0, "gamma": 120.0},
    "atomic_sites": [
        {"label": "Si1", "element": "Si", "x": 0.3333, "y": 0.6667, "z": 0.4650, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.4144, "y": 0.2785, "z": 0.4415, "occupancy": 1.0},
        {"label": "O2", "element": "O", "x": 0.2203, "y": 0.7862, "z": 0.4415, "occupancy": 1.0},
        {"label": "O3", "element": "O", "x": 0.4934, "y": 0.1108, "z": 0.4415, "occupancy": 1.0},
    ],
    "cif": """data_alpha_Quartz
_cell_length_a 4.913
_cell_length_b 4.913
_cell_length_c 5.405
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 120.0
_symmetry_space_group_name_H-M 'P3121'
_symmetry_Int_Tables_number 152
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+2/3'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/3'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+2/3'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0.3333 0.6667 0.4650 1.00
O1 O 0.4144 0.2785 0.4415 1.00
O2 O 0.2203 0.7862 0.4415 1.00
O3 O 0.4934 0.1108 0.4415 1.00
"""
})


# ── Halite (NaCl) ────────────────────────────────────────────
_register("NaCl", {
    "name": "Halite",
    "formula": "NaCl",
    "space_group": "Fm-3m",
    "space_group_number": 225,
    "lattice": {"a": 5.640, "b": 5.640, "c": 5.640,
                "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "Na1", "element": "Na", "x": 0.0000, "y": 0.0000, "z": 0.0000, "occupancy": 1.0},
        {"label": "Cl1", "element": "Cl", "x": 0.5000, "y": 0.5000, "z": 0.5000, "occupancy": 1.0},
    ],
    "cif": """data_Halite
_cell_length_a 5.640
_cell_length_b 5.640
_cell_length_c 5.640
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'Fm-3m'
_symmetry_Int_Tables_number 225
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x,-y,z'
_symmetry_equiv_pos_as_xyz '-x,y,-z'
_symmetry_equiv_pos_as_xyz 'x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,z,x'
_symmetry_equiv_pos_as_xyz '-y,-z,x'
_symmetry_equiv_pos_as_xyz '-y,z,-x'
_symmetry_equiv_pos_as_xyz 'y,-z,-x'
_symmetry_equiv_pos_as_xyz 'z,x,y'
_symmetry_equiv_pos_as_xyz '-z,-x,y'
_symmetry_equiv_pos_as_xyz '-z,x,-y'
_symmetry_equiv_pos_as_xyz 'z,-x,-y'
_symmetry_equiv_pos_as_xyz '-x+1/2,y+1/2,z'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y+1/2,z'
_symmetry_equiv_pos_as_xyz 'x+1/2,y+1/2,-z'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y+1/2,-z'
_symmetry_equiv_pos_as_xyz '-y+1/2,z+1/2,x'
_symmetry_equiv_pos_as_xyz 'y+1/2,-z+1/2,x'
_symmetry_equiv_pos_as_xyz 'y+1/2,z+1/2,-x'
_symmetry_equiv_pos_as_xyz '-y+1/2,-z+1/2,-x'
_symmetry_equiv_pos_as_xyz '-z+1/2,x+1/2,y'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x+1/2,y'
_symmetry_equiv_pos_as_xyz 'z+1/2,x+1/2,-y'
_symmetry_equiv_pos_as_xyz '-z+1/2,-x+1/2,-y'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,-z,x+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,z,x+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,-z,-x+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,z,-x+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x,y+1/2'
_symmetry_equiv_pos_as_xyz '-z+1/2,x,y+1/2'
_symmetry_equiv_pos_as_xyz '-z+1/2,-x,-y+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,x,-y+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,z+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,z+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,y,-z+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,z,x+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,-z,x+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,z,-x+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,-z,-x+1/2'
_symmetry_equiv_pos_as_xyz '-z+1/2,x,y+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x,y+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,x,-y+1/2'
_symmetry_equiv_pos_as_xyz '-z+1/2,-x,-y+1/2'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Na1 Na 0.0000 0.0000 0.0000 1.00
Cl1 Cl 0.5000 0.5000 0.5000 1.00
"""
})


# ── Corundum (Al2O3) ──────────────────────────────────────────
_register("Al2O3", {
    "name": "Corundum",
    "formula": "Al2O3",
    "space_group": "R-3c",
    "space_group_number": 167,
    "lattice": {"a": 4.752, "b": 4.752, "c": 12.982,
                "alpha": 90.0, "beta": 90.0, "gamma": 120.0},
    "atomic_sites": [
        {"label": "Al1", "element": "Al", "x": 0.0000, "y": 0.0000, "z": 0.3521, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.2604, "y": 0.0144, "z": 0.2425, "occupancy": 1.0},
    ],
    "cif": """data_Corundum
_cell_length_a 4.752
_cell_length_b 4.752
_cell_length_c 12.982
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 120.0
_symmetry_space_group_name_H-M 'R-3c'
_symmetry_Int_Tables_number 167
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-y,x-y,z'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/3'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/3'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+5/6'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+5/6'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+5/6'
_symmetry_equiv_pos_as_xyz 'x,y,z+2/3'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+2/3'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+2/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/3'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/3'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/2'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+2/3'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+2/3'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+2/3'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/6'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/6'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/6'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z'
_symmetry_equiv_pos_as_xyz 'x,y,z+5/6'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+5/6'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+5/6'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/2'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0.0000 0.0000 0.3521 1.00
O1 O 0.2604 0.0144 0.2425 1.00
"""
})


# ── Calcite (CaCO3) ──────────────────────────────────────────
_register("CaCO3", {
    "name": "Calcite",
    "formula": "CaCO3",
    "space_group": "R-3c",
    "space_group_number": 167,
    "lattice": {"a": 4.989, "b": 4.989, "c": 17.068,
                "alpha": 90.0, "beta": 90.0, "gamma": 120.0},
    "atomic_sites": [
        {"label": "Ca1", "element": "Ca", "x": 0.0000, "y": 0.0000, "z": 0.2500, "occupancy": 1.0},
        {"label": "C1", "element": "C", "x": 0.0000, "y": 0.0000, "z": 0.0000, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.2388, "y": 0.0000, "z": 0.0000, "occupancy": 1.0},
    ],
    "cif": """data_Calcite
_cell_length_a 4.989
_cell_length_b 4.989
_cell_length_c 17.068
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 120.0
_symmetry_space_group_name_H-M 'R-3c'
_symmetry_Int_Tables_number 167
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-y,x-y,z'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/3'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/3'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+5/6'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+5/6'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+5/6'
_symmetry_equiv_pos_as_xyz 'x,y,z+2/3'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+2/3'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+2/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/3'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/3'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/2'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+2/3'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+2/3'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+2/3'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/6'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/6'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/6'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z'
_symmetry_equiv_pos_as_xyz 'x,y,z+5/6'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+5/6'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+5/6'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/2'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ca1 Ca 0.0000 0.0000 0.2500 1.00
C1 C 0.0000 0.0000 0.0000 1.00
O1 O 0.2388 0.0000 0.0000 1.00
"""
})


# ── Hematite (Fe2O3) ──────────────────────────────────────────
_register("Fe2O3", {
    "name": "Hematite",
    "formula": "Fe2O3",
    "space_group": "R-3c",
    "space_group_number": 167,
    "lattice": {"a": 5.036, "b": 5.036, "c": 13.749,
                "alpha": 90.0, "beta": 90.0, "gamma": 120.0},
    "atomic_sites": [
        {"label": "Fe1", "element": "Fe", "x": 0.0000, "y": 0.0000, "z": 0.3550, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.2618, "y": 0.0000, "z": 0.2550, "occupancy": 1.0},
    ],
    "cif": """data_Hematite
_cell_length_a 5.036
_cell_length_b 5.036
_cell_length_c 13.749
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 120.0
_symmetry_space_group_name_H-M 'R-3c'
_symmetry_Int_Tables_number 167
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-y,x-y,z'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/3'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/3'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+5/6'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+5/6'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+5/6'
_symmetry_equiv_pos_as_xyz 'x,y,z+2/3'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+2/3'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+2/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/3'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/3'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/3'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/2'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+2/3'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+2/3'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+2/3'
_symmetry_equiv_pos_as_xyz 'x,y,z+1/6'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+1/6'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+1/6'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z'
_symmetry_equiv_pos_as_xyz 'x,y,z+5/6'
_symmetry_equiv_pos_as_xyz '-y,x-y,z+5/6'
_symmetry_equiv_pos_as_xyz '-x+y,-x,z+5/6'
_symmetry_equiv_pos_as_xyz '-x,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x+y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x-y,x,-z+1/2'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Fe1 Fe 0.0000 0.0000 0.3550 1.00
O1 O 0.2618 0.0000 0.2550 1.00
"""
})


# ── Anatase (TiO2) ────────────────────────────────────────────
_register("TiO2_anatase", {
    "name": "Anatase",
    "formula": "TiO2",
    "space_group": "I4/amd",
    "space_group_number": 141,
    "lattice": {"a": 3.785, "b": 3.785, "c": 9.514,
                "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "Ti1", "element": "Ti", "x": 0.0000, "y": 0.0000, "z": 0.0000, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.0000, "y": 0.0000, "z": 0.2081, "occupancy": 1.0},
    ],
    "cif": """data_Anatase
_cell_length_a 3.785
_cell_length_b 3.785
_cell_length_c 9.514
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'I4/amd'
_symmetry_Int_Tables_number 141
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'x+1/2,y+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz '-y,x,z'
_symmetry_equiv_pos_as_xyz 'y+1/2,-x+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x,-z'
_symmetry_equiv_pos_as_xyz '-y+1/2,x+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,y+1/2,z+1/4'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,z+3/4'
_symmetry_equiv_pos_as_xyz '-x,-y+1/2,-z+1/4'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,-z+3/4'
_symmetry_equiv_pos_as_xyz '-y,x+1/2,z+1/4'
_symmetry_equiv_pos_as_xyz 'y+1/2,-x,z+3/4'
_symmetry_equiv_pos_as_xyz 'y,-x+1/2,-z+1/4'
_symmetry_equiv_pos_as_xyz '-y+1/2,x,-z+3/4'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ti1 Ti 0.0000 0.0000 0.0000 1.00
O1 O 0.0000 0.0000 0.2081 1.00
"""
})


# ── Rutile (TiO2) ────────────────────────────────────────────
_register("TiO2_rutile", {
    "name": "Rutile",
    "formula": "TiO2",
    "space_group": "P4/mnm",
    "space_group_number": 136,
    "lattice": {"a": 4.594, "b": 4.594, "c": 2.958,
                "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "Ti1", "element": "Ti", "x": 0.0000, "y": 0.0000, "z": 0.0000, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.3047, "y": 0.3047, "z": 0.0000, "occupancy": 1.0},
        {"label": "O2", "element": "O", "x": 0.0000, "y": 0.0000, "z": 0.5000, "occupancy": 1.0},
    ],
    "cif": """data_Rutile
_cell_length_a 4.594
_cell_length_b 4.594
_cell_length_c 2.958
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'P4/mnm'
_symmetry_Int_Tables_number 136
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x,-y,z'
_symmetry_equiv_pos_as_xyz '-x+1/2,y+1/2,-z'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y+1/2,-z'
_symmetry_equiv_pos_as_xyz 'y,-x,z'
_symmetry_equiv_pos_as_xyz '-y,x,z'
_symmetry_equiv_pos_as_xyz '-y+1/2,-x+1/2,-z'
_symmetry_equiv_pos_as_xyz 'y+1/2,x+1/2,-z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'x,y,-z'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y+1/2,z'
_symmetry_equiv_pos_as_xyz '-x+1/2,y+1/2,z'
_symmetry_equiv_pos_as_xyz 'y,x,-z'
_symmetry_equiv_pos_as_xyz '-y,-x,-z'
_symmetry_equiv_pos_as_xyz '-y+1/2,x+1/2,z'
_symmetry_equiv_pos_as_xyz 'y+1/2,-x+1/2,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ti1 Ti 0.0000 0.0000 0.0000 1.00
O1 O 0.3047 0.3047 0.0000 1.00
O2 O 0.0000 0.0000 0.5000 1.00
"""
})


# ── Zircon (ZrSiO4) ───────────────────────────────────────────
_register("ZrSiO4", {
    "name": "Zircon",
    "formula": "ZrSiO4",
    "space_group": "I4/amd",
    "space_group_number": 141,
    "lattice": {"a": 6.434, "b": 6.434, "c": 6.017,
                "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "Zr1", "element": "Zr", "x": 0.0000, "y": 0.0000, "z": 0.0000, "occupancy": 1.0},
        {"label": "Si1", "element": "Si", "x": 0.0000, "y": 0.0000, "z": 0.5000, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.1970, "y": 0.0000, "z": 0.3140, "occupancy": 1.0},
    ],
    "cif": """data_Zircon
_cell_length_a 6.434
_cell_length_b 6.434
_cell_length_c 6.017
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'I4/amd'
_symmetry_Int_Tables_number 141
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'x+1/2,y+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz '-y,x,z'
_symmetry_equiv_pos_as_xyz 'y+1/2,-x+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz 'y,-x,-z'
_symmetry_equiv_pos_as_xyz '-y+1/2,x+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,y+1/2,z+1/4'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,z+3/4'
_symmetry_equiv_pos_as_xyz '-x,-y+1/2,-z+1/4'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,-z+3/4'
_symmetry_equiv_pos_as_xyz '-y,x+1/2,z+1/4'
_symmetry_equiv_pos_as_xyz 'y+1/2,-x,z+3/4'
_symmetry_equiv_pos_as_xyz 'y,-x+1/2,-z+1/4'
_symmetry_equiv_pos_as_xyz '-y+1/2,x,-z+3/4'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Zr1 Zr 0.0000 0.0000 0.0000 1.00
Si1 Si 0.0000 0.0000 0.5000 1.00
O1 O 0.1970 0.0000 0.3140 1.00
"""
})


# ── Perovskite (CaTiO3) ───────────────────────────────────────
_register("CaTiO3", {
    "name": "Perovskite",
    "formula": "CaTiO3",
    "space_group": "Pnma",
    "space_group_number": 62,
    "lattice": {"a": 5.437, "b": 7.639, "c": 5.322,
                "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "Ca1", "element": "Ca", "x": 0.4825, "y": 0.2500, "z": 0.5117, "occupancy": 1.0},
        {"label": "Ti1", "element": "Ti", "x": 0.0000, "y": 0.0000, "z": 0.5000, "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.0000, "y": 0.2500, "z": 0.0000, "occupancy": 1.0},
        {"label": "O2", "element": "O", "x": 0.5000, "y": 0.0000, "z": 0.5000, "occupancy": 1.0},
        {"label": "O3", "element": "O", "x": 0.0430, "y": 0.2500, "z": 0.7610, "occupancy": 1.0},
    ],
    "cif": """data_Perovskite
_cell_length_a 5.437
_cell_length_b 7.639
_cell_length_c 5.322
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'Pnma'
_symmetry_Int_Tables_number 62
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,y+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y+1/2,-z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,-y+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,y+1/2,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ca1 Ca 0.4825 0.2500 0.5117 1.00
Ti1 Ti 0.0000 0.0000 0.5000 1.00
O1 O 0.0000 0.2500 0.0000 1.00
O2 O 0.5000 0.0000 0.5000 1.00
O3 O 0.0430 0.2500 0.7610 1.00
"""
})


# ── Magnetite (Fe3O4) ─────────────────────────────────────────
_register("Fe3O4", {
    "name": "Magnetite",
    "formula": "Fe3O4",
    "space_group": "Fd-3m",
    "space_group_number": 227,
    "lattice": {"a": 8.397, "b": 8.397, "c": 8.397,
                "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "Fe1", "element": "Fe", "x": 0.1250, "y": 0.1250, "z": 0.1250, "occupancy": 1.0},
        {"label": "Fe2", "element": "Fe", "x": 0.5000, "y": 0.5000, "z": 0.5000, "occupancy": 0.5},
        {"label": "O1", "element": "O", "x": 0.2600, "y": 0.2600, "z": 0.2600, "occupancy": 1.0},
    ],
    "cif": """data_Magnetite
_cell_length_a 8.397
_cell_length_b 8.397
_cell_length_c 8.397
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'Fd-3m'
_symmetry_Int_Tables_number 227
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x,y+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y+1/2,-z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x,-y+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,y+1/2,z'
_symmetry_equiv_pos_as_xyz '-z,x,y'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x+1/2,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,x,-y+1/2'
_symmetry_equiv_pos_as_xyz 'z,-x,y+1/2'
_symmetry_equiv_pos_as_xyz 'z,x,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,-x,y+1/2'
_symmetry_equiv_pos_as_xyz '-z,x+1/2,-y+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x+1/2,-y'
_symmetry_equiv_pos_as_xyz 'y,z,x'
_symmetry_equiv_pos_as_xyz '-y+1/2,-z,x+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,-z+1/2,x'
_symmetry_equiv_pos_as_xyz '-y,z+1/2,x+1/2'
_symmetry_equiv_pos_as_xyz '-y,-z,-x'
_symmetry_equiv_pos_as_xyz 'y+1/2,z,-x+1/2'
_symmetry_equiv_pos_as_xyz 'y,z+1/2,x+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,-z+1/2,-x'
_symmetry_equiv_pos_as_xyz '-x,-z,-y'
_symmetry_equiv_pos_as_xyz 'x+1/2,z,-y+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,-z+1/2,y'
_symmetry_equiv_pos_as_xyz 'x,z+1/2,y+1/2'
_symmetry_equiv_pos_as_xyz 'x,-z,-y'
_symmetry_equiv_pos_as_xyz '-x+1/2,z+1/2,y'
_symmetry_equiv_pos_as_xyz '-x,-z+1/2,-y+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,-z+1/2,-y'
_symmetry_equiv_pos_as_xyz '-y,-x,-z'
_symmetry_equiv_pos_as_xyz 'y+1/2,x,z+1/2'
_symmetry_equiv_pos_as_xyz '-y+1/2,-x+1/2,z'
_symmetry_equiv_pos_as_xyz 'y,-x+1/2,z+1/2'
_symmetry_equiv_pos_as_xyz 'y,x,z'
_symmetry_equiv_pos_as_xyz '-y+1/2,-x,z+1/2'
_symmetry_equiv_pos_as_xyz 'y+1/2,-x+1/2,z'
_symmetry_equiv_pos_as_xyz '-y,x+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz '-z,-x,-y'
_symmetry_equiv_pos_as_xyz 'z+1/2,x+1/2,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,-x,y+1/2'
_symmetry_equiv_pos_as_xyz 'z,-x+1/2,y+1/2'
_symmetry_equiv_pos_as_xyz 'z,x,y'
_symmetry_equiv_pos_as_xyz '-z+1/2,x+1/2,y'
_symmetry_equiv_pos_as_xyz '-z,-x+1/2,-y+1/2'
_symmetry_equiv_pos_as_xyz 'z+1/2,-x,-y'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Fe1 Fe 0.1250 0.1250 0.1250 1.00
Fe2 Fe 0.5000 0.5000 0.5000 0.50
O1 O 0.2600 0.2600 0.2600 1.00
"""
})


# ── Orthoclase (KAlSi3O8) ────────────────────────────────────
_register("KAlSi3O8", {
    "name": "Orthoclase",
    "formula": "KAlSi3O8",
    "space_group": "C2/m",
    "space_group_number": 15,
    "lattice": {"a": 8.562, "b": 13.030, "c": 7.176,
                "alpha": 90.0, "beta": 116.0, "gamma": 90.0},
    "atomic_sites": [
        {"label": "K1", "element": "K", "x": 0.0000, "y": 0.2300, "z": 0.5000, "occupancy": 1.0},
        {"label": "Al1", "element": "Al", "x": 0.2840, "y": 0.0000, "z": 0.0500, "occupancy": 0.25},
        {"label": "Si1", "element": "Si", "x": 0.2840, "y": 0.0000, "z": 0.0500, "occupancy": 0.75},
        {"label": "Si2", "element": "Si", "x": 0.0000, "y": 0.0000, "z": 0.0000, "occupancy": 0.75},
        {"label": "O1", "element": "O", "x": 0.0000, "y": 0.1400, "z": 0.2100, "occupancy": 1.0},
        {"label": "O2", "element": "O", "x": 0.0000, "y": 0.0000, "z": 0.2800, "occupancy": 1.0},
        {"label": "O3", "element": "O", "x": 0.1600, "y": 0.1100, "z": 0.0000, "occupancy": 1.0},
    ],
    "cif": """data_Orthoclase
_cell_length_a 8.562
_cell_length_b 13.030
_cell_length_c 7.176
_cell_angle_alpha 90.0
_cell_angle_beta 116.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'C2/m'
_symmetry_Int_Tables_number 15
_symmetry_equiv_pos_as_xyz 'x,y,z'
_symmetry_equiv_pos_as_xyz '-x,y+1/2,-z'
_symmetry_equiv_pos_as_xyz '-x,-y,-z'
_symmetry_equiv_pos_as_xyz 'x,-y+1/2,z'
_symmetry_equiv_pos_as_xyz 'x+1/2,y,z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,y+1/2,-z+1/2'
_symmetry_equiv_pos_as_xyz '-x+1/2,-y,-z+1/2'
_symmetry_equiv_pos_as_xyz 'x+1/2,-y+1/2,z+1/2'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
K1 K 0.0000 0.2300 0.5000 1.00
Al1 Al 0.2840 0.0000 0.0500 0.25
Si1 Si 0.2840 0.0000 0.0500 0.75
Si2 Si 0.0000 0.0000 0.0000 0.75
O1 O 0.0000 0.1400 0.2100 1.00
O2 O 0.0000 0.0000 0.2800 1.00
O3 O 0.1600 0.1100 0.0000 1.00
"""
})


class CifMineralLibrary:
    """内置矿物 + 外部 CIF 的只读/可增删结构库。

    Usage:
        lib = CifMineralLibrary()
        lib.get_phase_list()
        quartz = lib.search_by_formula("SiO2")
        phase = lib.get_phase("SiO2")
        lib.export_cif("SiO2", "./output/")
    """

    def __init__(self) -> None:
        # 用户导入的外部 CIF（内置矿物不可增删）
        self._external_minerals: dict[str, dict] = {}

    def __len__(self) -> int:
        return len(_BUILTIN_MINERALS) + len(self._external_minerals)

    def __contains__(self, key: str) -> bool:
        return key in _BUILTIN_MINERALS or key in self._external_minerals

    # ── 查询方法 ──────────────────────────────────────────

    def get_phase_list(self) -> list[dict]:
        """获取所有可用矿物相列表

        Returns:
            矿物相信息列表，每项包含 key, name, formula, space_group, source
        """
        phases = []
        for key, data in _BUILTIN_MINERALS.items():
            phases.append({
                "key": key,
                "name": data["name"],
                "formula": data["formula"],
                "space_group": data["space_group"],
                "source": "builtin",
            })
        for key, data in self._external_minerals.items():
            phases.append({
                "key": key,
                "name": data["name"],
                "formula": data.get("formula", ""),
                "space_group": data.get("space_group", ""),
                "source": "external",
            })
        return phases

    def search_by_formula(self, formula: str) -> list[dict]:
        """按化学式搜索矿物

        Args:
            formula: 化学式，如 "SiO2", "Fe2O3"

        Returns:
            匹配的矿物列表
        """
        results: list[dict] = []
        formula_lower = formula.lower().strip()

        for key, data in _BUILTIN_MINERALS.items():
            if data["formula"].lower() == formula_lower:
                results.append(self._build_query_result(key, data, "builtin"))

        for key, data in self._external_minerals.items():
            if data.get("formula", "").lower() == formula_lower:
                results.append(self._build_query_result(key, data, "external"))

        return results

    def search_by_name(self, name: str) -> list[dict]:
        """按矿物名搜索（支持模糊匹配）

        Args:
            name: 矿物名，如 "Quartz", "Hematite"

        Returns:
            匹配的矿物列表
        """
        results: list[dict] = []
        name_lower = name.lower().strip()

        for key, data in _BUILTIN_MINERALS.items():
            if name_lower in data["name"].lower():
                results.append(self._build_query_result(key, data, "builtin"))

        for key, data in self._external_minerals.items():
            if name_lower in data.get("name", "").lower():
                results.append(self._build_query_result(key, data, "external"))

        return results

    def search_by_space_group(self, space_group: str) -> list[dict]:
        """按空间群搜索矿物

        Args:
            space_group: 空间群符号，如 "Fd-3m", "R-3c"

        Returns:
            匹配的矿物列表
        """
        results: list[dict] = []
        sg_lower = space_group.lower().strip()

        for key, data in _BUILTIN_MINERALS.items():
            if data["space_group"].lower() == sg_lower:
                results.append(self._build_query_result(key, data, "builtin"))

        for key, data in self._external_minerals.items():
            if data.get("space_group", "").lower() == sg_lower:
                results.append(self._build_query_result(key, data, "external"))

        return results

    def search(self, query: str) -> list[dict]:
        """综合搜索（化学式、矿物名、空间群）

        Args:
            query: 搜索关键词

        Returns:
            匹配的矿物列表（去重）
        """
        results: dict[str, dict] = {}
        for r in self.search_by_formula(query):
            results[r["key"]] = r
        for r in self.search_by_name(query):
            results[r["key"]] = r
        for r in self.search_by_space_group(query):
            results[r["key"]] = r
        return list(results.values())

    def get_cif_content(self, key: str) -> Optional[str]:
        """获取矿物的完整CIF内容

        Args:
            key: 矿物键名 (如 "SiO2", "NaCl")

        Returns:
            CIF格式字符串，若未找到返回None
        """
        if key in _BUILTIN_MINERALS:
            return _BUILTIN_MINERALS[key]["cif"]
        if key in self._external_minerals:
            return self._external_minerals[key].get("cif", "")
        return None

    def get_mineral_info(self, key: str) -> Optional[dict]:
        """获取矿物详细信息

        Args:
            key: 矿物键名

        Returns:
            矿物信息字典（包含 name, formula, space_group, lattice,
            atomic_sites, space_group_number, cif），未找到返回None
        """
        if key in _BUILTIN_MINERALS:
            data = _BUILTIN_MINERALS[key]
            return {
                "name": data["name"],
                "formula": data["formula"],
                "space_group": data["space_group"],
                "space_group_number": data.get("space_group_number", 0),
                "lattice": data["lattice"],
                "atomic_sites": data["atomic_sites"],
                "source": "builtin",
            }
        if key in self._external_minerals:
            data = self._external_minerals[key]
            return {
                "name": data["name"],
                "formula": data.get("formula", ""),
                "space_group": data.get("space_group", ""),
                "space_group_number": data.get("space_group_number", 0),
                "lattice": data.get("lattice", {}),
                "atomic_sites": data.get("atomic_sites", []),
                "source": "external",
            }
        return None

    def get_phase(self, key: str) -> Optional[Phase]:
        """获取矿物的Phase模型对象

        Args:
            key: 矿物键名

        Returns:
            Phase对象，未找到返回None
        """
        info = self.get_mineral_info(key)
        if info is None:
            return None

        lattice_data = info["lattice"]
        lattice = LatticeParams(
            a=lattice_data.get("a", 1.0),
            b=lattice_data.get("b", 1.0),
            c=lattice_data.get("c", 1.0),
            alpha=lattice_data.get("alpha", 90.0),
            beta=lattice_data.get("beta", 90.0),
            gamma=lattice_data.get("gamma", 90.0),
        )

        return Phase(
            name=info["name"],
            formula=info["formula"],
            space_group=info["space_group"],
            lattice=lattice,
            atomic_sites=info["atomic_sites"],
            cif_path=None,
        )

    # ── 外部文件操作 ──────────────────────────────────────

    def load_cif_file(self, path: str) -> dict:
        """从外部CIF文件加载矿物结构

        Args:
            path: CIF文件路径

        Returns:
            加载的矿物信息字典

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: CIF文件无效
        """
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"CIF文件不存在: {path}")

        content = path_obj.read_text(encoding="utf-8")
        mineral_data = self._parse_cif_content(content)
        if not mineral_data:
            raise ValueError(f"无效的CIF文件: {path}")

        key = mineral_data.get("key", path_obj.stem)
        mineral_data["key"] = key
        mineral_data["source"] = "external"
        self._external_minerals[key] = mineral_data
        return mineral_data

    def load_cif_directory(self, directory: str) -> list[dict]:
        """从目录加载所有CIF文件

        Args:
            directory: 包含CIF文件的目录

        Returns:
            加载的矿物信息列表
        """
        dir_path = Path(directory)
        results: list[dict] = []

        for cif_file in dir_path.glob("*.cif"):
            try:
                data = self.load_cif_file(str(cif_file))
                results.append(data)
            except (FileNotFoundError, ValueError) as exc:
                import warnings
                warnings.warn(f"跳过文件 {cif_file.name}: {exc}")

        return results

    def add_mineral(self, key: str, mineral_data: dict) -> None:
        """添加自定义矿物到数据库

        Args:
            key: 矿物键名
            mineral_data: 矿物数据字典，需包含 name, formula, cif 等字段
        """
        mineral_data["key"] = key
        mineral_data["source"] = "external"
        self._external_minerals[key] = mineral_data

    def remove_mineral(self, key: str) -> bool:
        """从数据库移除外部矿物

        Args:
            key: 矿物键名

        Returns:
            是否成功移除（内置矿物不可移除）
        """
        if key in self._external_minerals:
            del self._external_minerals[key]
            return True
        return False

    # ── 导出操作 ──────────────────────────────────────────

    def export_cif(self, key: str, output_dir: str) -> Optional[str]:
        """将矿物CIF内容导出为独立文件

        Args:
            key: 矿物键名
            output_dir: 输出目录路径

        Returns:
            导出文件的完整路径，未找到返回None
        """
        cif_content = self.get_cif_content(key)
        if cif_content is None:
            return None

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        info = self.get_mineral_info(key)
        mineral_name = info["name"] if info else key
        safe_name = re.sub(r"[^\w\s-]", "_", mineral_name)
        file_path = out_path / f"{safe_name}.cif"

        file_path.write_text(cif_content, encoding="utf-8")
        return str(file_path)

    def export_all(self, output_dir: str) -> list[str]:
        """导出所有内置矿物为独立.cif文件

        Args:
            output_dir: 输出目录路径

        Returns:
            导出文件路径列表
        """
        paths: list[str] = []
        for key in _BUILTIN_MINERALS:
            path = self.export_cif(key, output_dir)
            if path:
                paths.append(path)
        return paths

    # ── 内部辅助方法 ──────────────────────────────────────

    @staticmethod
    def _build_query_result(key: str, data: dict, source: str) -> dict:
        """构建搜索结果字典"""
        return {
            "key": key,
            "name": data["name"],
            "formula": data["formula"],
            "space_group": data["space_group"],
            "lattice": data.get("lattice", {}),
            "source": source,
        }

    @staticmethod
    def _parse_cif_content(content: str) -> dict:
        """解析CIF文件内容为矿物数据字典

        Args:
            content: CIF格式字符串

        Returns:
            解析出的矿物数据字典
        """
        data: dict = {}

        # 提取晶胞参数
        a = _extract_float(content, r"_cell_length_a\s+([\d.]+)")
        b = _extract_float(content, r"_cell_length_b\s+([\d.]+)")
        c = _extract_float(content, r"_cell_length_c\s+([\d.]+)")
        alpha = _extract_float(content, r"_cell_angle_alpha\s+([\d.]+)", 90.0)
        beta = _extract_float(content, r"_cell_angle_beta\s+([\d.]+)", 90.0)
        gamma = _extract_float(content, r"_cell_angle_gamma\s+([\d.]+)", 90.0)

        if a is not None:
            data["lattice"] = {
                "a": a, "b": b or a, "c": c or a,
                "alpha": alpha, "beta": beta, "gamma": gamma,
            }

        # 提取空间群
        sg_match = re.search(
            r"_symmetry_space_group_name_H-M\s+'([^']+)'", content
        )
        if sg_match:
            data["space_group"] = sg_match.group(1).strip()

        sg_num = _extract_int(
            content, r"_symmetry_Int_Tables_number\s+(\d+)"
        )
        if sg_num is not None:
            data["space_group_number"] = sg_num

        # 提取化学信息
        formula_match = re.search(
            r"_chemical_formula_sum\s+'([^']+)'", content
        )
        if formula_match:
            data["formula"] = formula_match.group(1).strip()

        name_match = re.search(r"data_([\w_]+)", content)
        if name_match:
            raw_name = name_match.group(1).replace("_", " ").strip()
            data["name"] = raw_name

        # 提取原子位点
        data["atomic_sites"] = _extract_atomic_sites(content)

        # 存储原始CIF内容
        data["cif"] = content

        return data


# ──────────────────────────────────────────────────────────────
# 外部 CIF 文本解析（正则，够用即可）
# ──────────────────────────────────────────────────────────────
#
# 注：``cif_utils.parse_atom_sites_from_cif`` 也能解析位点，但两者范式不同
# （那边是"首个 loop_ 全表扫描 + 补 u_iso"，这里是"按 _atom_site_ 列名顺序
# 逐行 split"）。v4.2 以**零行为变化**为先，故此处逐字搬移旧实现；
# 统一两套解析留待 P4（届时以 13 试样基准 + 位点回归守住）。


def _extract_float(content: str, pattern: str, default: Optional[float] = None) -> Optional[float]:
    """用正则提取浮点数"""
    m = re.search(pattern, content)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return default


def _extract_int(content: str, pattern: str) -> Optional[int]:
    """用正则提取整数"""
    m = re.search(pattern, content)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _extract_atomic_sites(content: str) -> list[dict]:
    """从CIF内容中提取原子位点

    解析 loop_ 后面的 _atom_site_* 数据块。
    """
    sites: list[dict] = []

    # 找到原子位点的loop块
    loop_pattern = re.compile(
        r"loop_\s*\n"
        r"(_atom_site_\w+\s*\n)+"
        r"((?:(?!loop_|_)[\s\S])*)",
        re.IGNORECASE,
    )

    # 先找列名
    col_pattern = re.compile(
        r"_atom_site_(\w+)\s*", re.IGNORECASE
    )
    columns = col_pattern.findall(content)

    if not columns:
        return sites

    # 找到数据部分（跳过列名后的内容）
    # 定位第一个 _atom_site_ 列名之后的数据
    first_col_idx = content.find("_atom_site_")
    if first_col_idx == -1:
        return sites

    # 找到所有列名结束位置（连续的 _atom_site_ 行之后）
    data_start = first_col_idx
    lines = content[data_start:].split("\n")
    header_ended = False
    data_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not header_ended:
            if stripped.startswith("_atom_site_"):
                continue
            elif stripped.startswith("loop_") or stripped.startswith("_"):
                header_ended = True
                continue
            else:
                header_ended = True
                if stripped and not stripped.startswith("loop_"):
                    data_lines.append(stripped)
        else:
            if stripped and not stripped.startswith("loop_") and not stripped.startswith("_"):
                data_lines.append(stripped)

    # 解析数据行
    for line in data_lines:
        parts = line.split()
        if len(parts) < 2:
            continue

        site: dict = {}
        for i, col in enumerate(columns):
            if i >= len(parts):
                break
            val = parts[i]
            if col in ("fract_x", "fract_y", "fract_z", "occupancy"):
                try:
                    site[col] = float(val)
                except ValueError:
                    site[col] = val
            else:
                site[col] = val

        if "fract_x" in site:
            site.setdefault("occupancy", 1.0)
            # ── v1.1.2 (W20): 统一键名 + 补 U_iso ───────────────────────
            # 下游 (phase_cif.phase_to_cif_text / rietveld_refiner._cif_reference_peaks
            # 的 pymatgen 直构 / 3D 结构视图) 一律读 x/y/z/element/label/occupancy/u_iso。
            # 本函数此前只产出 fract_x/fract_y/fract_z (且只把 4 个列转 float), 于是
            # 走 CIF 解析的物相在这些下游**静默失败**(KeyError 被 except 吞掉 → 回退旧峰表)。
            # 这里补出规范键, 同时**保留原始 fract_* 键**以兼容旧调用方。
            for _dst, _src in (("x", "fract_x"), ("y", "fract_y"),
                               ("z", "fract_z")):
                if _src in site and _dst not in site:
                    try:
                        site[_dst] = float(site[_src])
                    except (TypeError, ValueError):
                        pass
            # element: 优先 element 列, 其次 CIF 惯用的 type_symbol, 再从 label 取元素前缀
            if not site.get("element"):
                _el = str(site.get("element") or site.get("type_symbol") or "").strip()
                if not _el:
                    _m = re.match(r"[A-Za-z]{1,2}", str(site.get("label", "")))
                    _el = _m.group(0) if _m else ""
                if _el:
                    site["element"] = _el
            # u_iso: U_iso_or_equiv 优先; 否则 B_iso_or_equiv / (8π²); 都没有 → 0.005 Å²
            if "u_iso" not in site:
                _u_raw = site.get("U_iso_or_equiv", site.get("u_iso_or_equiv"))
                _b_raw = site.get("B_iso_or_equiv", site.get("b_iso_or_equiv"))
                _raw, _is_b = (None, False)
                if _u_raw is not None:
                    _raw, _is_b = _u_raw, False
                elif _b_raw is not None:
                    _raw, _is_b = _b_raw, True
                _val = None
                if _raw is not None:
                    try:
                        _val = float(str(_raw).split("(")[0])   # CIF 常带 esd 括号
                    except (TypeError, ValueError):
                        _val = None
                if _val is None:
                    site["u_iso"] = 0.005
                    site["u_iso_default"] = True
                else:
                    site["u_iso"] = (_val / (8.0 * np.pi ** 2)) if _is_b else _val
                    site["u_iso_default"] = False
            sites.append(site)

    return sites
