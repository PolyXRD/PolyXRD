"""CIF → Phase 解析健壮性守护测试 (v5.3.0, 2026-11-06)。

背景：本机 7 组 MAUD 对标试样（``D:/Project/XRDdata/ShiJK-Refinement``）的
CIF 全部由 Match! 从 COD 导出，具备两个与我们旧解析器不兼容的特征 ——

1. 空间群写在 ``_symmetry_space_group_name_H-M``（非 IUCr 首选字段名
   ``_space_group_name_H-M_alt``）→ 旧解析器读出 ``space_group=''``；
2. 原子环只有 ``_atom_site_label``（无 ``_atom_site_type_symbol``）且 label
   **全小写**（``mg`` / ``c`` / ``o``）→ ``_element_from_label`` 的
   ``[A-Z][a-z]?`` 匹配不到 → ``element=''``。

两者任一发生，:func:`expand_sites_by_symmetry` 都会原样返回非对称单元
（方解石 3 个位点而非 30 个），模拟峰整体失真、Rwp 虚高到 60% 量级 —— 但
**没有任何报错**。这组测试把这三条链路（字段名 / 元素大小写 / 非标准设置）
全部锁住。
"""
from __future__ import annotations

import pytest

from polyxrd.models.phase import Phase
from polyxrd.refinement.structure import StructureModel
from polyxrd.services.phase_cif import (
    _kv_value,
    _normalise_element,
    _symbol_is_standard,
    cif_to_phase,
    expand_sites_by_symmetry,
)

# ---------------------------------------------------------------- 最小 CIF 样本
# 方解石型 R-3c 非对称单元 (Ca 6b / C 6a / O 18e)，坐标取 magnesite 96-900-1850
_R3C_LOWER = """data_test
_chemical_name_common  'Magnesite'
_chemical_formula_sum  'C Mg O3'
_symmetry_space_group_name_H-M  'R -3 c'
_cell_length_a  4.6330
_cell_length_b  4.6330
_cell_length_c  15.0150
_cell_angle_alpha  90.0
_cell_angle_beta   90.0
_cell_angle_gamma 120.0
loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
mg  0.0     0.0     0.0   1.0
c   0.0     0.0     0.25  1.0
o   0.2564  0.0     0.25  1.0
"""

# 石英 P 32 2 1 **S 设置**（移位原点）：自带显式对称操作，与标准 P3221 不等价
_QUARTZ_SHIFTED = """data_test
_chemical_name_common  'Quartz low'
_chemical_formula_sum  'O2 Si'
_symmetry_space_group_name_H-M  'P 32 2 1 S'
loop_
_symmetry_equiv_pos_as_xyz
   'x, y, z'
   'y, x, -z+2/3'
   '-y, x-y, z+2/3'
   '-x, -x+y, -z+1/3'
   '-x+y, -x, z+1/3'
   'x-y, -y, -z'
_cell_length_a  4.90000
_cell_length_b  4.90000
_cell_length_c  5.40000
_cell_angle_alpha  90.0
_cell_angle_beta   90.0
_cell_angle_gamma 120.0
loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
si  0.469  0.0    0.0    1.0
o   0.403  0.253  0.122  1.0
"""

# 标准设置的石英（COD 96-710-3015 原始坐标，Si 在 3a: z=1/6）——
# 与上面那份只差原点沿 z 的平移，符号可直接识别 → 不应启用显式 ops
_QUARTZ_STANDARD = """data_test
_chemical_name_common  'Quartz low'
_chemical_formula_sum  'O2 Si'
_symmetry_space_group_name_H-M  'P 32 2 1'
_cell_length_a  4.90000
_cell_length_b  4.90000
_cell_length_c  5.40000
_cell_angle_alpha  90.0
_cell_angle_beta   90.0
_cell_angle_gamma 120.0
loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
si  0.470  0.000  0.167  1.0
o   0.413  0.267  0.285  1.0
"""


class TestSpaceGroupFieldNames:
    def test_alt_field_still_works(self):
        cif = _R3C_LOWER.replace("_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt")
        assert cif_to_phase(cif).space_group == "R -3 c"

    def test_legacy_symmetry_field_is_parsed(self):
        ph = cif_to_phase(_R3C_LOWER)
        assert ph.space_group == "R -3 c"

    def test_both_present_alt_wins(self):
        cif = _R3C_LOWER.replace(
            "_symmetry_space_group_name_H-M  'R -3 c'",
            "_space_group_name_H-M_alt  'R -3 c'\n"
            "_symmetry_space_group_name_H-M  'P 1'",
        )
        assert cif_to_phase(cif).space_group == "R -3 c"

    def test_key_without_value_does_not_raise(self):
        cif = _R3C_LOWER.replace("_chemical_formula_sum  'C Mg O3'", "_chemical_formula_sum")
        ph = cif_to_phase(cif)
        assert ph.space_group == "R -3 c"  # 后面字段照常解析


class TestElementFromLowercaseLabel:
    @pytest.mark.parametrize("raw,expect", [
        ("mg", "Mg"), ("MG", "Mg"), ("Mg1", "Mg"), ("mg1", "Mg"),
        ("c", "C"), ("o2", "O"), ("si1", "Si"), ("ca1a", "Ca"),
        ("Mg2+", "Mg"), ("", ""), ("Ow1", ""), ("X1", ""), ("1a", ""),
    ])
    def test_normalise(self, raw, expect):
        assert _normalise_element(raw) == expect

    def test_missing_type_symbol_lowercase_parsed(self):
        ph = cif_to_phase(_R3C_LOWER)
        assert [s["element"] for s in ph.atomic_sites] == ["Mg", "C", "O"]

    def test_type_symbol_still_preferred(self):
        cif = _R3C_LOWER.replace(
            "_atom_site_label\n", "_atom_site_label\n_atom_site_type_symbol\n"
        ).replace("mg  0.0", "mg  Mg  0.0").replace("c   0.0", "c   C  0.0") \
         .replace("o   0.2564", "o   O  0.2564")
        ph = cif_to_phase(cif)
        assert [s["element"] for s in ph.atomic_sites] == ["Mg", "C", "O"]


class TestExpansionAfterFix:
    def test_r3c_lowercase_expands_to_full_cell(self):
        """回归线：修复前这里返回 3（非对称单元），Rwp 因此虚高数倍。"""
        ph = cif_to_phase(_R3C_LOWER)
        exp = expand_sites_by_symmetry(ph.atomic_sites, ph.space_group,
                                       ops=ph.symmetry_ops)
        assert len(exp) == 30
        from collections import Counter
        c = Counter(s["element"] for s in exp)
        assert (c["Mg"], c["C"], c["O"]) == (6, 6, 18)

    def test_structure_model_gets_full_cell(self):
        m = StructureModel.from_phase(cif_to_phase(_R3C_LOWER), expand=True)
        assert m is not None and len(m.sites) == 30


class TestNonStandardSetting:
    def test_symbol_not_standard(self):
        assert _symbol_is_standard("R -3 c")
        assert _symbol_is_standard("P 32 2 1")
        assert not _symbol_is_standard("P 32 2 1 S")
        assert not _symbol_is_standard("")

    def test_shifted_setting_uses_explicit_ops(self):
        ph = cif_to_phase(_QUARTZ_SHIFTED)
        assert ph.space_group == "P 32 2 1 S"
        assert ph.symmetry_ops is not None and len(ph.symmetry_ops) == 6
        exp = expand_sites_by_symmetry(ph.atomic_sites, ph.space_group,
                                       ops=ph.symmetry_ops)
        from collections import Counter
        c = Counter(s["element"] for s in exp)
        # SiO2, Z=3 → 3 Si + 6 O。按标准 P3221 展开会得到 6 Si（轨道错一倍）
        assert (c["Si"], c["O"]) == (3, 6)

    def test_standard_setting_ignores_explicit_ops(self):
        ph = cif_to_phase(_QUARTZ_STANDARD)
        assert ph.symmetry_ops is None
        m = StructureModel.from_phase(ph, expand=True)
        assert m is not None and len(m.sites) == 9

    def test_explicit_ops_kwarg_overrides_symbol(self):
        sites = [{"label": "si", "element": "Si", "x": 0.469, "y": 0.0, "z": 0.0,
                  "occupancy": 1.0}]
        ph = cif_to_phase(_QUARTZ_SHIFTED)
        from_symbol = expand_sites_by_symmetry(sites, "P 32 2 1")
        from_ops = expand_sites_by_symmetry(sites, "P 32 2 1", ops=ph.symmetry_ops)
        assert len(from_ops) != len(from_symbol)  # 设置不同 → 轨道数不同


class TestMiscHelpers:
    @pytest.mark.parametrize("line,expect", [
        ("_cell_length_a  4.9", "4.9"),
        ("_chemical_name_common  'Quartz low'", "Quartz low"),
        ("_cell_length_a", ""),
        ("_cell_length_a   ", ""),
    ])
    def test_kv_value(self, line, expect):
        assert _kv_value(line) == expect

    def test_phase_defaults_no_ops(self):
        assert Phase().symmetry_ops is None
