"""``services/cif_utils`` 单测（v4.2 P1.1）。

覆盖：基础字段解析 / 空 & 坏 CIF / 缺字段 / 数值不确定度 / 化学式归一与可信判断 /
晶胞体积 / 原子位点（U_iso、B_iso 折算、默认值、非对称多 loop）/ 纯模块约束。
纯解析用例来自旧 ``test_cod_local`` / ``test_inorg_formula_fix`` /
``test_atomic_sites_normalize`` 的相关分支（v4.2 迁移）。
"""

from __future__ import annotations

import math

import polyxrd.services.cif_utils as cu

# ── 基础 CIF 文本 ─────────────────────────────────────────────
_BASIC = """data_Quartz
_chemical_formula_sum 'Si O2'
_symmetry_space_group_name_H-M 'P 21/c'
_symmetry_Int_Tables_number 14
_cell_length_a 5.0(2)
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_cell_formula_units_Z 2
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0.1 0.2 0.3 1.0
O1 O 0.4 0.5 0.6 0.95
"""


def test_parse_cif_text_basic():
    e = cu.parse_cif_text(_BASIC)
    assert e.cod_id == 0
    assert e.formula == "Si O2"
    assert e.formula_red == "O2Si"
    assert e.elements == "O,Si"
    assert e.space_group == "P 21/c"
    assert e.space_group_number == 14
    assert e.a == 5.0  # '5.0(2)' 剥离不确定度
    assert e.z_value == 2
    assert e.parse_ok == 1
    assert abs(e.volume - 125.0) < 1e-6  # 5^3


def test_parse_cif_text_empty_is_parse_fail():
    e = cu.parse_cif_text("")
    assert e.parse_ok == 0
    assert e.formula == ""


def test_parse_cif_text_garbage_no_crash():
    e = cu.parse_cif_text("data_X\n_not_a_tag some value\n")
    assert e.parse_ok == 0


def test_parse_cif_text_missing_cell_defaults():
    e = cu.parse_cif_text("data_X\n_chemical_formula_sum 'Na Cl'\n")
    assert e.alpha == 90.0 and e.beta == 90.0 and e.gamma == 90.0
    assert e.volume == 0.0
    assert e.parse_ok == 0  # 无晶胞


def test_parse_val_uncertainty_and_currency():
    assert cu._parse_val("0.144(10)") == 0.144
    assert cu._parse_val("'1.5'") == 1.5
    assert cu._parse_val("?") is None
    assert cu._parse_val("") is None


def test_cif_num_strips_uncertainty():
    assert cu._cif_num("0.144(10)") == 0.144
    assert cu._cif_num(".") is None
    assert cu._cif_num(None) is None
    assert cu._cif_num(3) == 3.0


def test_clean_elem_symbol():
    assert cu._clean_elem_symbol("Sn4+") == "Sn"
    assert cu._clean_elem_symbol("O-") == "O"
    assert cu._clean_elem_symbol("W+") == "W"


def test_formula_sum_from_cif_normalizes():
    assert cu.formula_sum_from_cif(_BASIC) == "O2 Si"
    assert cu.formula_sum_from_cif("data_X\n") == ""
    assert cu.formula_sum_from_cif("_chemical_formula_sum 'Si O2'\n") == "O2 Si"


def test_is_db_formula_trusted():
    assert cu.is_db_formula_trusted("Si O2") is True
    assert cu.is_db_formula_trusted("") is False
    assert cu.is_db_formula_trusted("P 21/c", "P 21/c") is False  # 与空间群同串
    assert cu.is_db_formula_trusted("   ") is False


def test_cell_volume():
    assert abs(cu._cell_volume(5, 5, 5, 90, 90, 90) - 125.0) < 1e-9
    assert cu._cell_volume(0, 5, 5, 90, 90, 90) == 0.0


def test_parse_float_csv_like_tolerance_is_not_here():
    # cif_utils 只管解析；容差/区间匹配属 phase_search（P1.2）
    assert not hasattr(cu, "_interval_hit")


def test_parse_atom_sites_u_iso_from_u():
    txt = """loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Si1 Si 0.1 0.2 0.3 1.0 0.02
"""
    s = cu.parse_atom_sites_from_cif(txt)
    assert len(s) == 1
    assert s[0]["u_iso"] == 0.02
    assert s[0]["u_iso_default"] is False


def test_parse_atom_sites_u_iso_from_b_is_inv_8pi2():
    b = 0.5
    txt = f"""loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_B_iso_or_equiv
O1 O 0.1 0.2 0.3 1.0 {b}
"""
    s = cu.parse_atom_sites_from_cif(txt)
    assert len(s) == 1
    assert abs(s[0]["u_iso"] - b / (8.0 * math.pi ** 2)) < 1e-12
    assert s[0]["u_iso_default"] is False


def test_parse_atom_sites_default_u_iso():
    txt = """loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0.1 0.2 0.3
"""
    s = cu.parse_atom_sites_from_cif(txt)
    assert len(s) == 1
    assert s[0]["u_iso"] == 0.005
    assert s[0]["u_iso_default"] is True


def test_parse_atom_sites_ignores_aniso_loop():
    txt = """loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
Si1 0.01
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0.1 0.2 0.3
"""
    s = cu.parse_atom_sites_from_cif(txt)
    assert len(s) == 1  # 只解析含 fract_x 的 loop


def test_cif_utils_is_pure_module():
    """纯模块约束：AST 层面不得 import sqlite3 / PySide6 / polyxrd.config。"""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(cu))
    forbidden_roots = {"sqlite3", "PySide6"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_roots, alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod.split(".")[0] not in forbidden_roots, mod
            assert not mod.startswith("polyxrd.config"), mod


def test_cif_entry_alias():
    assert cu.CIFEntry is cu.CODLocalEntry
