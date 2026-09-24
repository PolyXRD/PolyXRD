"""
测试 polyxrd.services.phase_cif (路线 B / R-B1)

覆盖:
- phase_to_cif_text: 必填字段 / 原子位点 loop / 体积 / 空间群 / fallback
- phase_to_cif_file: 写盘 + 父目录创建
- cif_to_phase: 双向 round-trip (Phase → CIF → Phase 字段一致)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.services.phase_cif import (
    _element_from_label,
    cif_to_phase,
    expand_sites_by_symmetry,
    phase_to_cif_file,
    phase_to_cif_text,
)


# ====================================================================
# fixtures
# ====================================================================

@pytest.fixture
def al2o3_phase() -> Phase:
    return Phase(
        name="corundum",
        formula="Al2 O3",
        space_group="R -3 c :H",
        lattice=LatticeParams(a=4.758, b=4.758, c=12.991, alpha=90, beta=90, gamma=120),
        atomic_sites=[
            {"label": "Al1", "element": "Al", "x": 0.0, "y": 0.0, "z": 0.352, "occupancy": 1.0},
            # 18e 真实位置 (x, 0, 1/4) — 轨道 18, 展开后 12 Al + 18 O = 30 位点
            {"label": "O1", "element": "O", "x": 0.306, "y": 0.0, "z": 0.25, "occupancy": 1.0},
        ],
    )


@pytest.fixture
def zn_phase() -> Phase:
    return Phase(
        name="zincite",
        formula="Zn O",
        space_group="P 63 m c :H",
        lattice=LatticeParams(a=3.249, b=3.249, c=5.207, alpha=90, beta=90, gamma=120),
        atomic_sites=[
            {"label": "Zn1", "element": "Zn", "x": 0.333, "y": 0.667, "z": 0.0, "occupancy": 1.0},
            {"label": "O1", "element": "O", "x": 0.333, "y": 0.667, "z": 0.5, "occupancy": 1.0},
        ],
    )


# ====================================================================
# _element_from_label
# ====================================================================

class TestElementFromLabel:
    def test_two_letter_element(self):
        assert _element_from_label("Al1") == "Al"

    def test_one_letter_element(self):
        assert _element_from_label("O2") == "O"

    def test_label_with_letter_suffix(self):
        assert _element_from_label("Ca1a") == "Ca"

    def test_unknown_falls_back_to_first_two(self):
        assert _element_from_label("Xy") == "Xy"

    def test_empty_returns_empty(self):
        assert _element_from_label("") == ""


# ====================================================================
# phase_to_cif_text
# ====================================================================

class TestPhaseToCifText:
    def test_requires_lattice(self):
        p = Phase(name="x", lattice=None)
        with pytest.raises(ValueError, match="没有 lattice"):
            phase_to_cif_text(p)

    def test_required_fields_present(self, al2o3_phase: Phase):
        txt = phase_to_cif_text(al2o3_phase)
        # 必填
        assert "data_corundum" in txt
        assert "_chemical_name_common 'corundum'" in txt
        assert "_chemical_formula_sum 'Al2 O3'" in txt
        assert "_cell_length_a 4.7580" in txt
        assert "_cell_length_b 4.7580" in txt
        assert "_cell_length_c 12.9910" in txt
        assert "_cell_angle_alpha 90.0000" in txt
        assert "_cell_angle_beta 90.0000" in txt
        assert "_cell_angle_gamma 120.0000" in txt
        # setting 后缀 (:H/:R) 会被剥离 — MAUD 3 的空间群查找不认带冒号的记号,
        # 见 phase_cif._space_group_to_hall_or_hm 的说明
        assert "_space_group_name_H-M_alt 'R -3 c'" in txt
        assert ":H" not in txt
        assert "_cell_formula_units_Z 1" in txt

    def test_volume_included(self, al2o3_phase: Phase):
        txt = phase_to_cif_text(al2o3_phase)
        # 体积应在 (约 254.5)
        assert "_cell_volume" in txt
        import re
        m = re.search(r"_cell_volume (\d+\.\d+)", txt)
        assert m
        vol = float(m.group(1))
        assert 200 < vol < 300, f"Al2O3 体积应在 250~260, 实测 {vol}"

    def test_atom_loop_present(self, al2o3_phase: Phase):
        txt = phase_to_cif_text(al2o3_phase)
        assert "loop_" in txt
        assert "_atom_site_label" in txt
        assert "_atom_site_type_symbol" in txt
        assert "_atom_site_fract_x" in txt
        assert "_atom_site_fract_y" in txt
        assert "_atom_site_fract_z" in txt
        assert "_atom_site_occupancy" in txt
        # 数据行
        assert "Al1 Al" in txt
        assert "O1 O" in txt

    def test_no_atoms_uses_dummy_sites(self):
        """没 atomic_sites 但有 elements → 用 dummy 占位 (退化路径)"""
        p = Phase(
            name="zincite",
            formula="Zn O",
            lattice=LatticeParams(a=3.249, b=3.249, c=5.207, alpha=90, beta=90, gamma=120),
            atomic_sites=[],
            elements={"Zn", "O"},
        )
        txt = phase_to_cif_text(p)
        assert "Zn1" in txt
        assert "O1" in txt  # sorted → O first
        # 验证顺序: O < Zn
        idx_o = txt.index("O1")
        idx_zn = txt.index("Zn1")
        assert idx_o < idx_zn, f"O 应在 Zn 前 (字母序): O@{idx_o}, Zn@{idx_zn}"

    def test_no_atoms_no_elements_no_loop(self):
        """既没 atomic_sites 又没 elements → 不写 atom loop"""
        p = Phase(
            name="bare",
            lattice=LatticeParams(a=1.0, b=1.0, c=1.0, alpha=90, beta=90, gamma=90),
            atomic_sites=[],
            elements=set(),
        )
        txt = phase_to_cif_text(p)
        assert "_atom_site_label" not in txt

    def test_crlf_line_endings(self, al2o3_phase: Phase):
        """CIF 习惯 CRLF"""
        txt = phase_to_cif_text(al2o3_phase)
        assert "\r\n" in txt
        # 首尾应是 CRLF 包裹
        assert txt.endswith("\r\n")

    def test_space_group_optional(self):
        """没空间群时不写 _space_group_* 行"""
        p = Phase(
            name="x",
            lattice=LatticeParams(a=1.0, b=1.0, c=1.0, alpha=90, beta=90, gamma=90),
            atomic_sites=[{"label": "Fe1", "element": "Fe", "x": 0, "y": 0, "z": 0,
                          "occupancy": 1.0}],
        )
        txt = phase_to_cif_text(p)
        assert "_space_group" not in txt


# ====================================================================
# phase_to_cif_file
# ====================================================================

class TestPhaseToCifFile:
    def test_writes_file(self, al2o3_phase: Phase, tmp_path: Path):
        dest = tmp_path / "sub" / "corundum.cif"
        out = phase_to_cif_file(al2o3_phase, dest)
        assert out == dest
        assert dest.exists()
        content = dest.read_text(encoding="utf-8")
        assert "data_corundum" in content

    def test_creates_parent_dirs(self, al2o3_phase: Phase, tmp_path: Path):
        dest = tmp_path / "a" / "b" / "c" / "phase.cif"
        phase_to_cif_file(al2o3_phase, dest)
        assert dest.exists()


# ====================================================================
# cif_to_phase
# ====================================================================

class TestCifToPhase:
    def test_basic_roundtrip(self, al2o3_phase: Phase):
        txt = phase_to_cif_text(al2o3_phase)
        back = cif_to_phase(txt)
        assert back.name == "corundum"
        assert back.formula == "Al2 O3"
        # 往返后 setting 后缀不保留 (写 CIF 时已剥离 :H)
        assert back.space_group == "R -3 c"
        assert back.lattice.a == pytest.approx(4.758, abs=0.01)
        assert back.lattice.c == pytest.approx(12.991, abs=0.01)
        assert back.lattice.gamma == pytest.approx(120.0)
        # v0.15.2: 非对称单元按 R-3c 对称展开成完整晶胞 (刚玉 Z=6: 12 Al + 18 O)
        assert len(back.atomic_sites) == 30
        # 原子位点: 12c Al 轨道必含 (0, 0, ±0.352) 类位置
        al_sites = [s for s in back.atomic_sites if s["element"] == "Al"]
        assert len(al_sites) == 12
        assert any(
            s["x"] == pytest.approx(0.0, abs=0.01)
            and s["z"] == pytest.approx(0.352, abs=0.01)
            for s in al_sites
        )

    def test_handles_minimal_cif(self):
        """只含 _cell_* + _atom_site_* 的 CIF 也能解析"""
        cif = """\
data_test
_cell_length_a 4.0
_cell_length_b 5.0
_cell_length_c 6.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Fe1 Fe 0 0 0 1.0
"""
        p = cif_to_phase(cif, fallback_name="test")
        assert p.lattice.a == 4.0
        assert p.lattice.b == 5.0
        assert p.lattice.c == 6.0
        assert len(p.atomic_sites) == 1
        assert p.atomic_sites[0]["element"] == "Fe"

    def test_handles_uncertainty_notation(self):
        """CIF 不确定度标记 '0.352(8)' 也能解析"""
        cif = """\
data_t
_cell_length_a 1.0
_cell_length_b 1.0
_cell_length_c 1.0
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
X1 X 0.123(8) 0.456(7) 0.789(6) 1.0
"""
        p = cif_to_phase(cif, fallback_name="t")
        assert p.atomic_sites[0]["x"] == pytest.approx(0.123, abs=0.01)
        assert p.atomic_sites[0]["y"] == pytest.approx(0.456, abs=0.01)

    def test_element_inferred_from_label(self):
        """没 _atom_site_type_symbol 时, 从 label 推断元素"""
        cif = """\
data_t
_cell_length_a 1.0
_cell_length_b 1.0
_cell_length_c 1.0
loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Na1 0 0 0 1.0
"""
        p = cif_to_phase(cif)
        assert p.atomic_sites[0]["element"] == "Na"

    def test_round_trip_zn(self, zn_phase: Phase):
        txt = phase_to_cif_text(zn_phase)
        back = cif_to_phase(txt)
        assert back.name == "zincite"
        assert back.lattice.a == pytest.approx(3.249, abs=0.01)
        # setting 后缀不保留 (写 CIF 时已剥离 :H, 兼容 MAUD 3 空间群查找)
        assert back.space_group == "P 63 m c"

# ====================================================================
# expand_sites_by_symmetry (v0.15.2 新增)
# ====================================================================

class TestExpandSitesBySymmetry:
    CALCITE_ASYMU = [
        {"label": "Ca", "element": "Ca", "x": 0.0, "y": 0.0, "z": 0.0,
         "occupancy": 1.0},
        {"label": "C", "element": "C", "x": 0.0, "y": 0.0, "z": 0.25,
         "occupancy": 1.0},
        {"label": "O", "element": "O", "x": 0.2596, "y": 0.0, "z": 0.25,
         "occupancy": 1.0},
    ]

    def test_r3c_expands_to_full_cell(self):
        e = expand_sites_by_symmetry(self.CALCITE_ASYMU, "R -3 c :H")
        # 方解石 Z=6: 6 Ca + 6 C + 18 O = 30
        assert len(e) == 30
        elems = sorted(s["element"] for s in e)
        assert elems.count("Ca") == 6 and elems.count("C") == 6
        assert elems.count("O") == 18

    def test_idempotent_on_expanded_sites(self):
        e1 = expand_sites_by_symmetry(self.CALCITE_ASYMU, "R -3 c")
        e2 = expand_sites_by_symmetry(e1, "R -3 c")
        assert len(e2) == len(e1) == 30

    def test_p1_and_missing_sg_noop(self):
        assert len(expand_sites_by_symmetry(self.CALCITE_ASYMU, "P 1")) == 3
        assert len(expand_sites_by_symmetry(self.CALCITE_ASYMU, "")) == 3

    def test_dirty_sites_noop(self):
        dirty = [{"label": "X", "x": "bad", "y": 0, "z": 0}]
        assert expand_sites_by_symmetry(dirty, "R -3 c") == dirty

    def test_bad_sg_noop(self):
        assert len(expand_sites_by_symmetry(
            self.CALCITE_ASYMU, "No Such Group XYZ")) == 3
