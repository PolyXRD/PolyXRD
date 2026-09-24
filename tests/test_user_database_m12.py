"""
M12 参考库管理 / 用户库测试 (Sprint 3)
=======================================
"""
import numpy as np

from polyxrd.models.phase import Phase
from polyxrd.services.user_database import (
    UserDatabase, check_formula_sum, import_diffraction_peaks,
    import_from_cif, shift_reference_database,
)

SI_CIF = """# Silicon diamond (P1 cell, 8 sites)
data_silicon
_cell_length_a   5.4310
_cell_length_b   5.4310
_cell_length_c   5.4310
_cell_angle_alpha 90
_cell_angle_beta  90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0.0 0.0 0.0
Si2 Si 0.0 0.5 0.5
Si3 Si 0.5 0.0 0.5
Si4 Si 0.5 0.5 0.0
Si5 Si 0.25 0.25 0.25
Si6 Si 0.25 0.75 0.75
Si7 Si 0.75 0.25 0.75
Si8 Si 0.75 0.75 0.25
"""


def _mk_phase(name="ZnO"):
    return Phase(name=name, formula="ZnO", elements={"Zn", "O"},
                 reference_peaks=[((1, 0, 0), 31.8, 100.0),
                                  ((1, 1, 0), 56.6, 40.0)])


class TestUserDatabase:

    def test_save_load_roundtrip(self, tmp_path):
        db = UserDatabase()
        db.add_phase(_mk_phase("ZnO"))
        db.add_phase(_mk_phase("CaO"))
        p = tmp_path / "user.json"
        db.save(p)
        db2 = UserDatabase(path=p)
        assert len(db2.entries) == 2
        assert db2.entries[0].name == "ZnO"
        assert db2.entries[0].reference_peaks[0][1] == 31.8

    def test_add_replace_and_remove(self, tmp_path):
        db = UserDatabase()
        db.add_phase(_mk_phase("A"))
        idx = db.add_phase(_mk_phase("B"))
        assert idx == 1
        assert len(db.entries) == 2
        # 同名覆盖
        db.add_phase(_mk_phase("A"), replace_same_name=True)
        assert len(db.entries) == 2
        assert db.remove_phase(name="B") is True
        assert db.remove_phase(name="Nope") is False
        assert db.remove_phase(index=0) is True
        assert len(db.entries) == 0

    def test_find(self, tmp_path):
        db = UserDatabase()
        db.add_phase(_mk_phase("Zincite"))
        db.add_phase(Phase(name="Corundum", formula="Al2O3",
                           elements={"Al", "O"}))
        assert len(db.find(name="Zincite")) == 1
        assert len(db.find(elements=["Al"])) == 1
        assert len(db.find(name_contains="zinc")) == 1  # 大小写不敏感
        assert len(db.find(formula="ZnO")) == 1

    def test_export_txt_and_json(self, tmp_path):
        db = UserDatabase()
        db.add_phase(_mk_phase("ZnO"))
        out_txt = tmp_path / "z.txt"
        db.export_entry(0, out_txt, fmt="txt")
        lines = out_txt.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2 and lines[0].startswith("31.8")
        out_json = tmp_path / "z.json"
        db.export_entry("ZnO", out_json, fmt="json")
        data = __import__("json").loads(out_json.read_text(encoding="utf-8"))
        assert data["name"] == "ZnO"

    def test_missing_path_creates_empty(self, tmp_path):
        # 构造语义: 路径缺失 → 空库 (首次新建时常用)
        db = UserDatabase(path=tmp_path / "nope.json")
        assert len(db.entries) == 0


class TestFormulaCheck:
    def test_ok_and_bad(self):
        assert check_formula_sum(_mk_phase()) is True
        assert check_formula_sum(Phase(name="X", formula="", elements=set())) \
            is False
        assert check_formula_sum(Phase(name="X", formula="ZnO3",
                                       elements={"Zn", "O"})) is True


class TestImportPeaks:
    def test_two_theta_mode(self, tmp_path):
        p = tmp_path / "pk.txt"
        p.write_text("28.44 100\n47.3 60\n56.1 35\n", encoding="utf-8")
        ph = import_diffraction_peaks(_mk_phase(), p, angle="2theta")
        tts = [tt for _, tt, _ in ph.reference_peaks]
        assert tts == [28.44, 47.3, 56.1]

    def test_d_spacing_mode(self, tmp_path):
        p = tmp_path / "d.txt"
        p.write_text("3.138 100\n1.920 60\n", encoding="utf-8")  # 递减 → auto 判为 d
        ph = import_diffraction_peaks(_mk_phase(), p, angle="auto")
        tts = [tt for _, tt, _ in ph.reference_peaks]
        # d=3.138 (Cu Kα1) → 2θ≈28.42; d=1.920 → 2θ≈47.29
        assert abs(tts[0] - 28.42) < 0.15, tts
        assert abs(tts[1] - 47.30) < 0.15, tts


class TestShift:
    def test_shifts_copy_not_inplace(self):
        db = UserDatabase()
        db.add_phase(_mk_phase("A"))
        out = shift_reference_database(db, 0.05)
        assert abs(out.entries[0].reference_peaks[0][1] - 31.85) < 1e-6
        assert abs(db.entries[0].reference_peaks[0][1] - 31.8) < 1e-9


class TestImportCif:
    def test_si_cif(self, tmp_path):
        cif = tmp_path / "Si.cif"
        cif.write_text(SI_CIF, encoding="utf-8")
        ph = import_from_cif(cif)
        assert "Si" in ph.elements
        assert ph.lattice is not None and abs(ph.lattice.a - 5.431) < 0.01
        assert len(ph.atomic_sites) == 8
        assert ph.reference_peaks, "CIF 应能生成参考峰"
        # 金刚石 Si 最强峰 ≈28.44°
        tts = [tt for _, tt, i in ph.reference_peaks]
        best_tt = tts[int(np.argmax([i for _, _, i in ph.reference_peaks]))]
        assert abs(best_tt - 28.44) < 0.3, f"Si 最强峰应≈28.44°, 实际 {best_tt}"
