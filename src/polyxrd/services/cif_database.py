"""
CIF数据库服务
============
提供内置矿物CIF数据支持，包括常见矿物的晶体结构数据、
外部CIF文件加载、COD在线搜索等功能。
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from polyxrd.config import get_config
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


# ──────────────────────────────────────────────────────────────
# CIFDatabase 类
# ──────────────────────────────────────────────────────────────

class CIFDatabase:
    """CIF晶体结构数据库

    提供内置矿物CIF结构数据、外部CIF文件加载、
    COD在线搜索和矿物结构导出等功能。

    Usage:
        db = CIFDatabase()
        phases = db.get_phase_list()
        quartz = db.search_by_formula("SiO2")
        cif_text = db.get_cif_content("SiO2")
        db.export_cif("SiO2", "./output/")
    """

    def __init__(self, enable_cod_local: bool = True) -> None:
        self._config = get_config()
        self._external_minerals: dict[str, dict] = {}
        self._ensure_db_dir()
        # 本地 COD 全库数据库 (懒加载, cod_index.sqlite)
        self._cod_db = None  # type: ignore[var-annotated]
        self._cod_enabled = enable_cod_local

    def _ensure_db_dir(self) -> None:
        db_path = self._config.get_cif_db_path()
        db_path.mkdir(parents=True, exist_ok=True)

    # ── 本地 COD 全库数据库 (cod_index.sqlite) 懒加载 ──────────
    def _get_cod_db(self):
        """Lazy load local COD full database (cod_index.sqlite).

        通过 cod_local.py 的 CODLocalDatabase 类操作,支持
        cod_entries + cod_atomic_sites 表,可动态生成 reference_peaks。
        与上方 _get_cod_conn() 操作的 COD_inorganics.sqlite 互补:
          - COD_inorganics.sqlite: COD 无机物库, 预计算 d-I 峰
          - cod_index.sqlite: crystallography.net 全库, 含原子位点, 可精修
        """
        if self._cod_db is None and self._cod_enabled:
            try:
                from polyxrd.services.cod_local import CODLocalDatabase
                self._cod_db = CODLocalDatabase()
            except Exception:
                self._cod_db = None
        return self._cod_db

    @property
    def cod_ready(self) -> bool:
        """COD 全库是否可用"""
        db = self._get_cod_db()
        return bool(db and db.is_ready())

    @property
    def cod_db(self):
        """COD 全库实例 (CODLocalDatabase)"""
        return self._get_cod_db()

    def cod_stats(self) -> dict:
        """COD 全库统计信息"""
        db = self._get_cod_db()
        if db is None:
            return {"ready": False}
        return db.stats()

    def __len__(self) -> int:
        total = len(_BUILTIN_MINERALS) + len(self._external_minerals)
        db = self._get_cod_db()
        if db is not None:
            try:
                total += int(db.stats().get("total", 0))
            except Exception:
                pass
        return total

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

    # ── COD 在线搜索 ──────────────────────────────────────

    def search_cod(
        self,
        formula: Optional[str] = None,
        mineral_name: Optional[str] = None,
        space_group: Optional[str] = None,
        timeout: int = 15,
    ) -> list[dict]:
        """从Crystallography Open Database (COD)在线搜索矿物

        Args:
            formula: 化学式 (如 "SiO2")
            mineral_name: 矿物名 (如 "quartz")
            space_group: 空间群 (如 "Fd-3m")
            timeout: 请求超时秒数

        Returns:
            搜索结果列表，每项包含 cod_id, name, formula, 等信息
        """
        if not any([formula, mineral_name, space_group]):
            return []

        params: dict[str, str] = {"format": "json"}
        if formula:
            params["formula"] = formula
        if mineral_name:
            params["name"] = mineral_name
        if space_group:
            params["sg"] = space_group

        base_url = "https://www.crystallography.net/cod/search.html"
        query_string = urllib.parse.urlencode(params)
        url = f"{base_url}?{query_string}"

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "PolyXRD-CIFDatabase/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return self._parse_cod_response(raw)
        except Exception:
            return []

    def fetch_cod_cif(self, cod_id: int, timeout: int = 15) -> Optional[str]:
        """从COD下载指定条目的CIF文件内容

        Args:
            cod_id: COD数据库条目ID
            timeout: 请求超时秒数

        Returns:
            CIF文件内容字符串，失败返回None
        """
        url = f"https://www.crystallography.net/cod/{cod_id}.cif"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "PolyXRD-CIFDatabase/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            return None

    def load_from_cod(self, cod_id: int) -> Optional[dict]:
        """从COD加载矿物到本地数据库

        Args:
            cod_id: COD数据库条目ID

        Returns:
            加载的矿物信息，失败返回None
        """
        cif_content = self.fetch_cod_cif(cod_id)
        if not cif_content:
            return None

        mineral_data = self._parse_cif_content(cif_content)
        if not mineral_data:
            return None

        key = mineral_data.get("key", f"cod_{cod_id}")
        mineral_data["key"] = key
        mineral_data["source"] = "cod"
        mineral_data["cod_id"] = cod_id
        mineral_data["cif"] = cif_content
        self._external_minerals[key] = mineral_data
        return mineral_data

    # ── COD 离线数据库查询 ────────────────────────────

    _cod_conn = None  # type: ignore[assignment]

    def _get_cod_conn(self):
        """懒加载 COD SQLite 连接。若数据库不存在返回 None。"""
        if self._cod_conn is not None:
            return self._cod_conn
        import sqlite3
        db_path = self._config.get_cod_db_path()
        if not db_path.exists():
            return None
        # read-only, 多线程安全
        self._cod_conn = sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, check_same_thread=False
        )
        self._cod_conn.row_factory = sqlite3.Row
        return self._cod_conn

    def set_cod_db_path(self, path: str | Path) -> bool:
        """设置并切换到用户导入的 COD 数据库。

        Args:
            path: 外部 SQLite 数据库文件路径

        Returns:
            True 表示切换成功;False 表示文件不存在或不可读
        """
        path = Path(path)
        if not path.exists() or not path.is_file():
            return False
        # 先持久化到配置(下次启动自动加载)
        self._config.set_cod_db_path(path)
        # 关闭旧连接,触发懒加载重建
        self.reload_cod_db()
        return self.cod_db_available()

    def reload_cod_db(self) -> None:
        """关闭当前 COD 数据库连接,下次访问时按最新路径重新连接。"""
        if self._cod_conn is not None:
            try:
                self._cod_conn.close()
            except Exception:
                pass
            self._cod_conn = None

    def cod_db_available(self) -> bool:
        """COD 离线数据库是否可用"""
        return self._config.get_cod_db_path().exists()

    def cod_phase_count(self) -> int:
        """COD 数据库中的物相总数"""
        conn = self._get_cod_conn()
        if conn is None:
            return 0
        cur = conn.execute("SELECT COUNT(*) FROM phases")
        return int(cur.fetchone()[0])

    def search_cod_phases(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """在 COD 离线数据库中搜索物相(按化学式 / 空间群 / COD ID)。

        化学式在 COD 数据库中按字母排序存储(如 SiO2 存为 "O2 Si"),
        因此查询时会把化学式规范化(按元素符号排序)后再匹配。

        Args:
            query: 搜索关键词(化学式片段、空间群符号、或 COD ID 数字)
            limit: 返回结果上限

        Returns:
            匹配的物相列表,每项含 cod_id, formula, space_group,
            cell_a/b/c/alpha/beta/gamma, n_peaks
        """
        conn = self._get_cod_conn()
        if conn is None:
            return []
        q = query.strip()
        if not q:
            return []
        # 如果 query 是纯数字,按 COD ID 搜索;也支持 97-XXXXXXX / 96-XXX-YYYY 格式
        q_dash = q.replace(" ", "")
        if q_dash.lower().startswith("97-") and len(q_dash) == 15:  # "97-1011097"
            cur = conn.execute(
                "SELECT cod_id, ref_id, display_id, formula, space_group, "
                "cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, n_peaks "
                "FROM phases WHERE display_id = ? LIMIT ?",
                (q_dash, limit),
            )
        elif q_dash.lower().startswith("96-"):  # "96-101-1097" (COD 风格)
            cur = conn.execute(
                "SELECT cod_id, ref_id, display_id, formula, space_group, "
                "cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, n_peaks "
                "FROM phases WHERE ref_id = ? LIMIT ?",
                (q_dash, limit),
            )
        elif q.isdigit():
            # 可能是 7 位 COD ID, 也可能是 display_id 省略前缀(或部分编码)
            num = int(q)
            cur = conn.execute(
                "SELECT cod_id, ref_id, display_id, formula, space_group, "
                "cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, n_peaks "
                "FROM phases WHERE cod_id = ? OR display_id = ? OR ref_id LIKE ? "
                "LIMIT ?",
                (num, f"97-{num:07d}", f"%{q_dash}%", limit),
            )
        else:
            # 规范化查询化学式:按空格分割并排序元素组
            # 例如 "Si O2" -> "O2 Si" (匹配数据库存储格式)
            norm_q = " ".join(sorted(q.split()))
            cur = conn.execute(
                "SELECT cod_id, ref_id, display_id, formula, space_group, "
                "cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, n_peaks "
                "FROM phases "
                "WHERE formula = ? OR formula = ? "
                "OR formula LIKE ? OR space_group LIKE ? "
                "OR display_id LIKE ? OR ref_id LIKE ? "
                "ORDER BY n_peaks DESC LIMIT ?",
                (q, norm_q, f"{norm_q}%", f"%{q}%",
                 f"%{q_dash}%", f"%{q_dash}%", limit),
            )
        return [dict(row) for row in cur.fetchall()]

    def get_cod_phase(self, cod_id: int) -> Optional[dict]:
        """获取 COD 数据库中指定 COD ID 的物相详情(含 d-I 峰)。

        Args:
            cod_id: COD 数据库条目 ID

        Returns:
            物相详情字典,含 peaks_d / peaks_i 列表;未找到返回 None
        """
        conn = self._get_cod_conn()
        if conn is None:
            return None
        cur = conn.execute(
            "SELECT cod_id, ref_id, display_id, formula, space_group, "
            "cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, "
            "n_peaks, peaks_d, peaks_i "
            "FROM phases WHERE cod_id = ?",
            (cod_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        data = dict(row)
        # 把逗号分隔的字符串解析成 float 列表,方便上层使用
        if data.get("peaks_d"):
            data["peaks_d_list"] = [float(x) for x in data["peaks_d"].split(",") if x.strip()]
        else:
            data["peaks_d_list"] = []
        if data.get("peaks_i"):
            data["peaks_i_list"] = [float(x) for x in data["peaks_i"].split(",") if x.strip()]
        else:
            data["peaks_i_list"] = []
        data["source"] = "match"
        return data

    def search_cod_by_d_peaks(
        self,
        measured_d: list[float],
        measured_i: list[float] | None = None,
        *,
        tolerance: float = 0.02,
        min_match: int = 3,
        limit: int = 50,
        max_ref_peaks: int = 40,
        elements_allowed: set | None = None,
    ) -> list[dict]:
        """用测得的 d 值列表在 COD 数据库中搜索匹配物相。

        为避免高密度物相(含数百个弱峰)产生误匹配,只取每个物相中
        I 值最高的前 max_ref_peaks 个主要峰参与匹配。统计双向匹配:
          - recall(meas_ratio):测量峰中被主要参考峰(前 max_ref_peaks)覆盖的比例
          - top_recall:取物相最强的少数峰(去重后,前 n_top 个独立峰),
            统计测量峰中有多少落在这些"物相最强峰"内。
            低对称物相会产出大量近重复 d 值(同一 d 的多个 hkl),
            去重后只看独立强峰,可避免此类物相因重复峰虚高得分。
          - top_precision:物相最强的前 K(=5)个去重峰中有多少"被观察到"
            (Hanawalt 思想:最强线必须出现在样品中)。混合样品中,只有真
            主物相的最强线会全部出现在测量峰里,故 top_precision 可有效
            区分真物相与"碰巧覆盖多个测量峰"的密集杂相。
          - intensity_weighted_top_recall: 若传入 measured_i,按测量峰
            强度加权的 top_recall,即"物相最强去重峰覆盖的测量峰强度之和
            / 测量峰总强度"。当 top_precision 并列时,真主物相(其最强峰
            解释了样品最强峰)会因加权召回率高而胜出,可有效避免密集低强度
            峰物相(如 MgCO3)误抢占 CaCO3 主峰位置。
          - main_peak_match: 若传入 measured_i,等于 1.0 当物相最强去重峰
            落在样品最强峰(I 最大)±tolerance 内,否则 0.0。Hanawalt 主峰
            原则:主物相的最强线应对上样品的最强线。

        排序主键(默认):main_peak_match → top_precision →
        intensity_weighted_top_recall → top_recall → meas_ratio → score,
        均降序。把 main_peak_match 放在最前是 Hanawalt 主峰原则的体现,
        确保"物相主峰对上样品最强峰"的物相优先于"次峰密集但主峰不对位"
        的杂相。当 measured_i 未提供时,main_peak_match 与
        intensity_weighted_top_recall 均为 0,排序退化为按
        (top_precision, top_recall, meas_ratio, score)。
        score = top_precision*100 + top_recall*10 + recall,仅作次级参考。
        返回前 limit 个。

        Args:
            measured_d: 测得的 d 值列表(Å)
            measured_i: 测得峰强度列表(可选,与 measured_d 等长平行)。
                传入后启用强度加权召回率与主峰匹配判据,显著提升混合
                样品中主物相识别正确率。None 时退化为仅按 d 值覆盖度排序。
            tolerance: d 值匹配容差(Å),同时用作去重阈值
            min_match: 最少反向匹配测量峰数,低于此数的物相被丢弃
            limit: 返回结果上限
            max_ref_peaks: 每个物相参与匹配的最大主要峰数(I 值最高的)

        Returns:
            匹配物相列表,每项含 cod_id, formula, space_group, n_peaks,
            n_ref_used, n_matched_ref, n_matched_meas,
            n_meas_in_top, n_top_unique, n_top_observed, n_top_k,
            top_recall, top_precision,
            match_ratio(正向), meas_ratio(反向 recall), score,
            intensity_weighted_top_recall(measured_i 提供时),
            main_peak_match(measured_i 提供时)
        """
        conn = self._get_cod_conn()
        if conn is None or not measured_d:
            return []
        import bisect
        # 预排序测量 d 值,用 bisect 加速区间匹配
        meas_sorted = sorted(measured_d)
        n_meas = len(meas_sorted)
        # 若提供 measured_i,做强度加权召回与主峰匹配。需保持 d↔I 对应关系。
        use_intensity = (
            measured_i is not None and len(measured_i) == n_meas
        )
        if use_intensity:
            # 按 d 升序的 (d, I) 对,与 meas_sorted 对齐
            di_pairs = sorted(zip(measured_d, measured_i),
                              key=lambda p: p[0])
            meas_i_sorted = [p[1] for p in di_pairs]
            total_i = sum(meas_i_sorted)
            # 样品最强峰:d↔I 对齐中 I 最大的索引(在 meas_sorted 中的位置)
            main_meas_i_in_sorted = max(range(n_meas),
                                         key=lambda k: meas_i_sorted[k])
            main_meas_d = meas_sorted[main_meas_i_in_sorted]
        else:
            meas_i_sorted = None
            total_i = 0.0
            main_meas_d = None
        results: list[dict] = []
        cur = conn.execute(
            "SELECT cod_id, ref_id, display_id, formula, space_group, n_peaks, "
            "peaks_d, peaks_i FROM phases"
        )
        # 元素约束下推 (化学过滤在扫描层完成, 避免候选名额被无效化学
        # 成分占用)。COD 公式为空格分隔 "元素+系数" 组 (如 "O4 Zr3")。
        import re as _re
        _tok_re = _re.compile(r"^([A-Z][a-z]?)(\d*\.?\d*)$")
        for row in cur:
            if elements_allowed is not None:
                f_str = row["formula"] or ""
                els = {
                    m.group(1)
                    for tok in f_str.split()
                    if (m := _tok_re.match(tok))
                }
                if not els or not els.issubset(elements_allowed):
                    continue
            peaks_d_str = row["peaks_d"]
            peaks_i_str = row["peaks_i"]
            if not peaks_d_str or not peaks_i_str:
                continue
            ref_d_all = [float(x) for x in peaks_d_str.split(",") if x.strip()]
            ref_i_all = [float(x) for x in peaks_i_str.split(",") if x.strip()]
            n_peaks = row["n_peaks"]
            # 取 I 值最高的前 max_ref_peaks 个峰(用于广覆盖反向匹配)
            indexed = sorted(
                range(len(ref_i_all)),
                key=lambda k: ref_i_all[k],
                reverse=True,
            )[:max_ref_peaks]
            ref_d = [ref_d_all[k] for k in indexed if k < len(ref_d_all)]
            n_ref_used = len(ref_d)
            # 反向匹配:测量峰中被主要参考峰(前 max_ref_peaks)覆盖的数量
            matched_meas_idx: set[int] = set()
            for d in ref_d:
                lo = d - tolerance
                hi = d + tolerance
                idx = bisect.bisect_left(meas_sorted, lo)
                if idx < len(meas_sorted) and meas_sorted[idx] <= hi:
                    matched_meas_idx.add(idx)
            n_matched_meas = len(matched_meas_idx)
            if n_matched_meas < min_match:
                continue
            # ── top_recall:取最强的少数峰(去重后),看测量峰是否就是物相最强峰 ──
            # 低对称物相会产出大量近重复 d 值(同一 d 的多个 hkl),
            # 用去重后的"最强 N_top 个独立峰"判断:测得峰是否落在物相最强峰里。
            n_top = min(len(ref_i_all), max(n_meas + 2, 8), 12)
            top_idx = sorted(
                range(len(ref_i_all)),
                key=lambda k: ref_i_all[k],
                reverse=True,
            )[:n_top]
            # 按 I 降序处理,保留强度更高者,丢弃 ±tolerance 内的近重复
            top_pairs = sorted(
                ((ref_d_all[k], ref_i_all[k]) for k in top_idx if k < len(ref_d_all)),
                key=lambda p: -p[1],
            )
            unique_top_d: list[float] = []
            for d, _i in top_pairs:
                if not any(abs(d - ud) <= tolerance for ud in unique_top_d):
                    unique_top_d.append(d)
            # 测量峰中有多少落在"物相最强去重峰"内
            n_meas_in_top = 0
            # 强度加权召回率:被物相最强去重峰覆盖的测量峰强度之和
            covered_i_sum = 0.0
            for k_md, md in enumerate(meas_sorted):
                lo = md - tolerance
                hi = md + tolerance
                hit = False
                for ud in unique_top_d:
                    if lo <= ud <= hi:
                        hit = True
                        break
                if hit:
                    n_meas_in_top += 1
                    if use_intensity:
                        covered_i_sum += meas_i_sorted[k_md]
            top_recall = n_meas_in_top / n_meas if n_meas else 0.0
            # 强度加权 top_recall:加权和/总强度(0..1)
            intensity_weighted_top_recall = (
                covered_i_sum / total_i if (use_intensity and total_i > 0) else 0.0
            )
            # main_peak_match:物相最强去重峰是否落在样品最强峰 ±tolerance 内
            if use_intensity and unique_top_d:
                phase_main_d = unique_top_d[0]
                main_peak_match = 1.0 if abs(phase_main_d - main_meas_d) <= tolerance else 0.0
            else:
                main_peak_match = 0.0
            # top_precision:物相最强的前 K 个去重峰中有多少"被观察到"
            # (Hanawalt 思想:最强线必须出现在样品中)。低对称/含近重复峰的
            # 物相若最强线不在样品中,precision 低 → 不应被选为主物相。
            top_k_d = unique_top_d[:5]
            n_top_observed = 0
            for ud in top_k_d:
                lo = ud - tolerance
                hi = ud + tolerance
                idx = bisect.bisect_left(meas_sorted, lo)
                if idx < len(meas_sorted) and meas_sorted[idx] <= hi:
                    n_top_observed += 1
            top_precision = n_top_observed / len(top_k_d) if top_k_d else 0.0
            recall = n_matched_meas / n_meas if n_meas else 0.0
            # 正向匹配率(前 max_ref_peaks 中匹配测量峰的比例,仅参考)
            n_matched_ref = 0
            for d in ref_d:
                lo = d - tolerance
                hi = d + tolerance
                idx = bisect.bisect_left(meas_sorted, lo)
                if idx < len(meas_sorted) and meas_sorted[idx] <= hi:
                    n_matched_ref += 1
            ref_ratio = n_matched_ref / n_ref_used if n_ref_used else 0.0
            # 主得分:top_precision(物相最强线被观察到?)占主导,top_recall 次之
            score = top_precision * 100.0 + top_recall * 10.0 + recall
            results.append({
                "cod_id": row["cod_id"],
                "ref_id": row["ref_id"],
                "display_id": row["display_id"],
                "formula": row["formula"],
                "space_group": row["space_group"],
                "n_peaks": n_peaks,
                "n_ref_used": n_ref_used,
                "n_matched_ref": n_matched_ref,
                "n_matched_meas": n_matched_meas,
                "n_meas_in_top": n_meas_in_top,
                "n_top_unique": len(unique_top_d),
                "n_top_observed": n_top_observed,
                "n_top_k": len(top_k_d),
                "top_recall": top_recall,
                "top_precision": top_precision,
                "intensity_weighted_top_recall": intensity_weighted_top_recall,
                "main_peak_match": main_peak_match,
                "match_ratio": ref_ratio,
                "meas_ratio": recall,
                "score": score,
            })
        # 排序主键:
        #   main_peak_match → top_precision → intensity_weighted_top_recall
        #   → top_recall → meas_ratio → score,均降序。
        # 把 main_peak_match 放在最前:Hanawalt 主峰原则 —— 物相主峰
        # 应对上样品最强峰。即便物相次峰未全部被观察到(如弱含量物相),
        # 主峰对上即可优先。这避免了像 SiO2-quartz(top_p=0.2,主峰对上)
        # 被挤出 top-200,而让密集杂相(top_p=1.0,主峰不对位)误排前列。
        # 当 measured_i 未提供时,main_peak_match/intensity_weighted_top_recall
        # 均为 0,等价于原 (top_precision, top_recall, ...) 排序。
        results.sort(
            key=lambda r: (
                r["main_peak_match"],
                r["top_precision"],
                r["intensity_weighted_top_recall"],
                r["top_recall"],
                r["meas_ratio"],
                r["score"],
            ),
            reverse=True,
        )
        return results[:limit]

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

    @staticmethod
    def _parse_cod_response(raw: str) -> list[dict]:
        """解析COD搜索响应"""
        results: list[dict] = []

        # 尝试按JSON解析
        try:
            import json as _json
            parsed = _json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    results.append({
                        "cod_id": item.get("filetype", {}).get("id", 0)
                        if isinstance(item.get("filetype"), dict)
                        else item.get("id", 0),
                        "name": item.get("mineralname", ""),
                        "formula": item.get("formula", ""),
                        "space_group": item.get("symmetry", ""),
                    })
            elif isinstance(parsed, dict):
                results.append(parsed)
        except Exception:
            pass

        return results

    # ── 本地 COD 全库查询 (cod_index.sqlite) ──────────────────

    def search_cod_local(
        self,
        formula: Optional[str] = None,
        mineral_name: Optional[str] = None,
        space_group: Optional[str] = None,
        elements: Optional[list[str]] = None,
        cod_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict]:
        """从本地 COD 全库 SQLite 索引搜索 (cod_index.sqlite)。

        与 search_cod_phases() 互补:
          - search_cod_phases(): 查 COD_inorganics.sqlite (COD 无机物库, 预计算 d-I 峰)
          - search_cod_local():  查 cod_index.sqlite (crystallography.net 全库, 含原子位点)

        Args:
            formula: 化学式, 如 "SiO2"
            mineral_name: 矿物名 (模糊匹配)
            space_group: 空间群 (模糊匹配)
            elements: 必须包含的元素列表, 如 ["Si","O"]
            cod_id: COD 编号
            limit: 最大返回数

        Returns:
            [{cod_id, name, formula, space_group, a, volume, source="cod_local"}, ...]
        """
        db = self._get_cod_db()
        if db is None:
            return []
        entries = db.search(
            formula=formula, mineral_name=mineral_name,
            space_group=space_group, elements=elements,
            cod_id=cod_id, limit=limit,
        )
        return [
            {
                "cod_id": e.cod_id,
                "key": f"cod_{e.cod_id}",
                "name": e.mineral_name or f"COD_{e.cod_id}",
                "formula": e.formula,
                "formula_red": e.formula_red,
                "space_group": e.space_group,
                "space_group_number": e.space_group_number,
                "a": e.a, "b": e.b, "c": e.c,
                "alpha": e.alpha, "beta": e.beta, "gamma": e.gamma,
                "volume": e.volume,
                "file": e.file,
                "source": "cod_local",
            } for e in entries
        ]

    def get_cif_from_cod_local(self, cod_id: int) -> Optional[str]:
        """获取本地 COD 全库的 CIF 原文 (四级回退: 目录→BLOB→tar→REST)"""
        db = self._get_cod_db()
        if db is None:
            return None
        return db.get_cif(cod_id)

    def load_from_cod_local(self, cod_id: int) -> Optional[Phase]:
        """把本地 COD 全库条目加载为 Phase 对象 (含 reference_peaks + atomic_sites)。

        与 get_cod_phase() 互补:
          - get_cod_phase():     从 COD_inorganics.sqlite 取预计算 d-I 峰
          - load_from_cod_local(): 从 cod_index.sqlite 取原子位点, 动态计算 XRD 峰

        Returns:
            Phase 对象，失败返回 None
        """
        db = self._get_cod_db()
        if db is None:
            return None
        return db.get_phase(cod_id)


# ──────────────────────────────────────────────────────────────
# 模块级辅助函数
# ──────────────────────────────────────────────────────────────

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
            sites.append(site)

    return sites