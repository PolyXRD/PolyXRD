# -*- coding: utf-8 -*-
"""用户自建数据库 (v2.6.0) 单测
===============================
覆盖 services/user_db.py 的三层位点择优判据、导入/去重/导出/挂载,
以及检索 (identify_with_user_db) 与 CIF 导出两条下游链路。

关键回归点 (都是实测踩过的坑, 见 user_db._entry_from_cif docstring):
  · pymatgen 把非 P1 结构误判成 P1 → 位点数 == 不对称单元数 (未展开)
  · ``R -3 c :R`` 菱形设置被按六方操作展开 → 整胞等倍放大
  · pymatgen 合并同坐标无序位点 → 少数占据元素被吞
  · CIF ``_atom_site_type_symbol`` 带氧化态 → element 列被污染
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.services import user_db

# ── CIF 样本 ─────────────────────────────────────────────────

# 正确 α-石英: 不对称单元 Si 3a + O 6c, P3121 → 全胞 3 Si + 6 O = 9
QUARTZ_CIF = """data_alpha_quartz
_cell_length_a 4.9134
_cell_length_b 4.9134
_cell_length_c 5.4052
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_chemical_formula_sum 'O2 Si'
_symmetry_space_group_name_H-M 'P 31 2 1'
loop_
_symmetry_equiv_pos_as_xyz
'x,y,z'
'-y,x-y,z+2/3'
'-x+y,-x,z+1/3'
'-x,-y,-z'
'y,-x+y,-z+1/3'
'x-y,x,-z+2/3'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0.4697 0.0000 0.3333 1.0
O1 O 0.4135 0.2669 0.1191 1.0
"""

# 金刚石 Si: 手写 CIF 只列 2 个不对称位点但带 4 条对称操作 (pymatgen 会当 P1)
SI_CIF = """data_Silicon
_cell_length_a 5.431
_cell_length_b 5.431
_cell_length_c 5.431
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_chemical_formula_sum 'Si'
_symmetry_space_group_name_H-M 'Fd-3m'
loop_
_symmetry_equiv_pos_as_xyz
'x,y,z'
'-x+1/2,-y,z+1/2'
'-x,y+1/2,-z+1/2'
'x+1/2,-y+1/2,-z'
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

# 无序位点: Cr 0.117 / Ni 0.883 同坐标 (Fd-3m)。少数占据不能被吞掉,
# 否则元素配比与 _chemical_formula_sum 'Ce Cr0.234 Ni1.766' 对不上。
DISORDER_CIF = """data_ce_ni_cr
_cell_length_a 7.21
_cell_length_b 7.21
_cell_length_c 7.21
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_chemical_formula_sum 'Ce Cr0.234 Ni1.766'
_symmetry_space_group_name_H-M 'F d -3 m'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ce1 Ce 0 0 0 1
Cr1 Cr 0.625 0.625 0.625 0.117
Ni1 Ni 0.625 0.625 0.625 0.883
"""

# 带氧化态的 type_symbol (COD 常见): Ca2+ / F1-
CHARGED_CIF = """data_fluorite
_cell_length_a 5.463
_cell_length_b 5.463
_cell_length_c 5.463
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_chemical_formula_sum 'Ca F2'
_symmetry_space_group_name_H-M 'F m -3 m'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ca1 Ca2+ 0 0 0 1
F1 F1- 0.25 0.25 0.25 1
"""

# 无晶胞 → 必须判废
NO_CELL_CIF = """data_broken
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
X1 O 0.1 0.2 0.3
"""


@pytest.fixture()
def tmp_user_db(tmp_path, monkeypatch):
    """把用户库重定向到临时目录 (不碰 ~/.polyxrd)。"""
    p = tmp_path / "user_phases.sqlite"
    monkeypatch.setattr(user_db, "user_db_path", lambda: p)
    yield p
    for suffix in ("", "-wal", "-shm", "-bak"):
        q = Path(str(p) + suffix)
        if q.exists():
            q.unlink()


def _write(tmp_path: Path, name: str, text: str) -> str:
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return str(f)


# ── 1. 元素符号与配比工具 ────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("Ca2+", "Ca"), ("F1-", "F"), ("V+3", "V"), ("O-2", "O"),
    ("Si", "Si"), ("Oi", "Oi"), ("Ba+2", "Ba"), ("", ""),
])
def test_plain_symbol_strips_charge(raw, expect):
    assert user_db._plain_symbol(raw) == expect


def test_fractions_from_formula_handles_decimals():
    f = user_db._fractions_from_formula("Ce Cr0.234 Ni1.766")
    assert f["Cr"] < f["Ce"] < f["Ni"]
    assert abs(sum(f.values()) - 1.0) < 1e-9


def test_formula_from_sites_reduces_by_gcd():
    si8 = [{"element": "Si"}] * 8
    quartz = [{"element": "Si"}] * 3 + [{"element": "O"}] * 6
    assert user_db._formula_from_sites(si8) == "Si"
    assert user_db._formula_from_sites(quartz) == "O2 Si"


def test_comp_distance_exact_and_far():
    ref = user_db._fractions_from_formula("O2 Si")
    good = [{"element": "Si", "occupancy": 1.0}] * 3 + \
           [{"element": "O", "occupancy": 1.0}] * 6
    bad = [{"element": "Si", "occupancy": 1.0}] + \
          [{"element": "O", "occupancy": 1.0}] * 3
    assert user_db._comp_distance(good, ref) < user_db._COMP_TOL
    assert user_db._comp_distance(bad, ref) > user_db._COMP_TOL


# ── 2. 位点择优 (_pick_sites 三层判据) ──────────────────────

def test_pick_prefers_shorter_when_composition_equal():
    """均匀过度展开时 (元素配比不变), 必须取位点数少的那个。"""
    raw = [{"element": "O", "x": 0.0, "y": 0.0, "z": 0.0}]
    big = [{"element": "O", "x": 0.0, "y": 0.0, "z": 0.0}] * 24
    small = [{"element": "O", "x": 0.0, "y": 0.0, "z": 0.0}] * 6
    cell = (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)   # 125 Å³ → 24 个超标, 6 个合理
    got = user_db._pick_sites(raw, big, small, cell, formula="", space_group="")
    assert len(got) == 6


def test_pick_drops_overexpanded_by_density_fuse():
    raw = [{"element": "Ba", "x": 0.0, "y": 0.0, "z": 0.0}]
    huge = [{"element": "Ba", "x": 0.0, "y": 0.0, "z": 0.0}] * 400
    cell = (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)
    got = user_db._pick_sites(raw, huge, [], cell, formula="", space_group="")
    assert len(got) <= 1          # 退回原子环原样, 而不是留 400 个垃圾位点


def test_pick_empty_when_raw_itself_absurd():
    raw = [{"element": "Ba", "x": 0.0, "y": 0.0, "z": 0.0}] * 400
    cell = (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)
    assert user_db._pick_sites(raw, [], [], cell, formula="", space_group="") == []


def test_pick_rejects_candidate_missing_atoms():
    """位点数比原子环还少 = 丢了原子, 无论配比如何都不能选。"""
    raw = [{"element": "O", "x": i * 0.01, "y": 0.0, "z": 0.0} for i in range(8)]
    lossy = raw[:2]
    full = raw
    cell = (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)
    got = user_db._pick_sites(raw, full, lossy, cell, formula="", space_group="")
    assert len(got) == 8


def test_orbit_closed_detects_unexpanded_set():
    """Si 手写 CIF: 2 个不对称位点在 Fd-3m 下未闭合。"""
    two = [{"element": "Si", "x": 0.0, "y": 0.0, "z": 0.0},
           {"element": "Si", "x": 0.25, "y": 0.25, "z": 0.25}]
    assert user_db._orbit_closed(two, "Fd-3m") is False
    eight = [{"element": "Si", "x": x, "y": y, "z": z} for x, y, z in (
        (0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
        (.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25))]
    assert user_db._orbit_closed(eight, "Fd-3m") is True


# ── 3. CIF → 条目 ───────────────────────────────────────────

def test_entry_quartz_full_cell():
    entry, sites, cell = user_db._entry_from_cif(QUARTZ_CIF, "quartz.cif")
    assert len(sites) == 9
    assert sum(1 for s in sites if s["element"] == "Si") == 3
    assert sum(1 for s in sites if s["element"] == "O") == 6
    assert user_db._formula_from_sites(sites) == "O2 Si"
    assert cell[0] == pytest.approx(4.9134)


def test_entry_silicon_uses_self_chain_when_pymatgen_loses_symmetry():
    """手写 Si CIF 带对称操作表但 pymatgen 判 P1 → 必须由自研链展开成 8 位点。"""
    _entry, sites, _cell = user_db._entry_from_cif(SI_CIF, "si.cif")
    assert len(sites) == 8
    assert all(s["element"] == "Si" for s in sites)


def test_entry_keeps_minority_occupancy_species():
    """Cr0.117 / Ni0.883 同坐标 → 两个元素都必须保留。"""
    _entry, sites, _cell = user_db._entry_from_cif(DISORDER_CIF, "d.cif")
    els = {s["element"] for s in sites}
    assert {"Ce", "Cr", "Ni"} <= els
    comp = user_db._sites_fractions(sites)
    assert 0.05 < comp["Cr"] < 0.10


def test_entry_strips_oxidation_state():
    _entry, sites, _cell = user_db._entry_from_cif(CHARGED_CIF, "f.cif")
    els = {s["element"] for s in sites}
    assert els == {"Ca", "F"}
    assert user_db._formula_from_sites(sites) == "Ca F2"


def test_entry_raises_without_cell():
    with pytest.raises(ValueError, match="no_cell_params"):
        user_db._entry_from_cif(NO_CELL_CIF, "bad.cif")


# ── 4. 导入 / 去重 / 文件夹 ─────────────────────────────────

def test_import_and_peak_table(tmp_user_db, tmp_path):
    rep = user_db.import_cif_files([_write(tmp_path, "q.cif", QUARTZ_CIF)])
    assert rep.imported == ["q.cif"] and not rep.failed
    entries = user_db.list_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["formula"] == "O2 Si"
    assert e["n_peaks"] > 10
    d = np.frombuffer(
        sqlite3.connect(str(tmp_user_db)).execute(
            "SELECT peaks_top_d FROM phases").fetchone()[0], dtype=np.float64)
    # 石英最强线是 (101) d ≈ 3.3434 Å; (100) 4.255 Å 是第二强
    assert d[0] == pytest.approx(3.3434, abs=0.01)
    assert any(abs(v - 4.255) < 0.01 for v in d[:4])


def test_import_is_content_deduplicated(tmp_user_db, tmp_path):
    a = _write(tmp_path, "a.cif", QUARTZ_CIF)
    b = _write(tmp_path, "b.cif", QUARTZ_CIF)      # 同内容换名
    rep = user_db.import_cif_files([a, b])
    assert rep.imported == ["a.cif"] and rep.skipped_dup == ["b.cif"]
    assert user_db.user_stats()["rows"] == 1


def test_import_empty_and_broken_files_reported(tmp_user_db, tmp_path):
    empty = _write(tmp_path, "empty.cif", "   \n")
    broken = _write(tmp_path, "broken.cif", NO_CELL_CIF)
    good = _write(tmp_path, "good.cif", QUARTZ_CIF)
    rep = user_db.import_cif_files([empty, broken, good])
    assert rep.imported == ["good.cif"]
    reasons = dict(rep.failed)
    assert reasons["empty.cif"] == "empty_file"
    assert reasons["broken.cif"] == "no_cell_params"


def test_import_folder_case_insensitive_no_duplicate(tmp_user_db, tmp_path):
    d = tmp_path / "cifs"
    d.mkdir()
    (d / "a.cif").write_text(QUARTZ_CIF, encoding="utf-8")
    (d / "b.CIF").write_text(SI_CIF, encoding="utf-8")
    rep = user_db.import_cif_folder(d)
    assert len(rep.imported) == 2 and not rep.skipped_dup and not rep.failed


def test_import_folder_not_a_directory(tmp_user_db, tmp_path):
    f = tmp_path / "x.cif"
    f.write_text(QUARTZ_CIF, encoding="utf-8")
    rep = user_db.import_cif_folder(f)
    assert rep.failed and rep.failed[0][1] == "not_a_directory"


# ── 5. 列表 / 取用 / 删除 / 导出 / 挂载 ─────────────────────

def test_list_get_remove_clear(tmp_user_db, tmp_path):
    user_db.import_cif_files([_write(tmp_path, "q.cif", QUARTZ_CIF),
                              _write(tmp_path, "si.cif", SI_CIF)])
    entries = user_db.list_entries()
    assert len(entries) == 2
    first = entries[0]
    assert first["display_id"].startswith("USER-")
    assert user_db.display_id_of(first["cod_id"]) == first["display_id"]
    assert user_db.is_user_id(first["cod_id"]) is True
    assert user_db.is_user_id(1234567) is False

    assert user_db.get_user_cif(first["cod_id"]).strip().startswith("data_")
    assert user_db.get_user_atomic_sites(first["cod_id"])
    assert user_db.remove_entries([first["cod_id"]]) == 1
    assert len(user_db.list_entries()) == 1
    user_db.clear_user_db()
    assert user_db.user_stats()["rows"] == 0
    assert user_db.list_entries() == []


def test_export_inspect_mount_roundtrip(tmp_user_db, tmp_path):
    user_db.import_cif_files([_write(tmp_path, "q.cif", QUARTZ_CIF)])
    out = tmp_path / "exported.sqlite"
    user_db.export_user_db(out)
    assert out.exists()

    ok, info = user_db.inspect_user_db_file(out)
    assert ok and info == "1"
    assert user_db.mount_user_db(out) == user_db.user_db_path()
    assert user_db.user_stats()["rows"] == 1

    bad = tmp_path / "notadb.sqlite"
    bad.write_bytes(b"definitely not sqlite")
    ok2, why2 = user_db.inspect_user_db_file(bad)
    assert not ok2
    with pytest.raises(ValueError):
        user_db.mount_user_db(bad)


def test_inspect_missing_file(tmp_user_db, tmp_path):
    ok, why = user_db.inspect_user_db_file(tmp_path / "nope.sqlite")
    assert not ok and why == "file_not_found"


# ── 6. 检索链路 (identify_with_user_db) ─────────────────────

def _pattern_of(tmp_user_db, source_name: str) -> XRDData:
    conn = sqlite3.connect(str(tmp_user_db))
    td, ti = conn.execute(
        "SELECT peaks_top_d, peaks_top_i FROM phases WHERE source_file=?",
        (source_name,)).fetchone()
    conn.close()
    d = np.frombuffer(td, dtype=np.float64)
    i = np.frombuffer(ti, dtype=np.float64)
    lam = 1.5406
    tt = 2.0 * np.degrees(np.arcsin(lam / (2.0 * d)))
    x = np.arange(5.0, 100.0, 0.02)
    y = np.zeros_like(x)
    for t, iv in zip(tt, i):
        if 5.0 <= t <= 100.0:
            y += iv * np.exp(-0.5 * ((x - t) / 0.03) ** 2)
    return XRDData(two_theta=x, intensity=y)


def test_identify_with_user_db_finds_own_phase(tmp_user_db, tmp_path):
    user_db.import_cif_files([_write(tmp_path, "q.cif", QUARTZ_CIF),
                              _write(tmp_path, "si.cif", SI_CIF)])
    from polyxrd.services.phase_identifier import PhaseIdentifier

    ident = PhaseIdentifier()
    got = ident.identify_with_user_db(_pattern_of(tmp_user_db, "q.cif"), top_n=3)
    assert got, "用户库检索应有结果"
    top = got[0].phase
    assert top.formula == "O2 Si"
    # 精修可直接使用: 晶胞 + 全胞原子坐标 + 库内 ID 都在
    assert top.lattice is not None
    assert len(top.atomic_sites) == 9
    assert top.db_id is not None and user_db.is_user_id(top.db_id)


def test_identify_with_user_db_empty_library(tmp_user_db):
    """空库必须直接返回 [] 而不是抛异常 (UI 侧置灰兜底之外的第二道防线)。"""
    from polyxrd.services.phase_identifier import PhaseIdentifier

    x = np.arange(5.0, 100.0, 0.02)
    y = np.exp(-0.5 * ((x - 20.0) / 0.03) ** 2)
    data = XRDData(two_theta=x, intensity=y)
    assert PhaseIdentifier().identify_with_user_db(data, top_n=3) == []


# ── 7. CIF 导出 (下游) ─────────────────────────────────────

def test_phase_cif_export_reads_user_db(tmp_user_db, tmp_path):
    user_db.import_cif_files([_write(tmp_path, "q.cif", QUARTZ_CIF)])
    from polyxrd.services.phase_cif_export import (
        get_phase_cif_text, resolve_cod_id,
    )
    from polyxrd.services.phase_identifier import PhaseIdentifier

    got = PhaseIdentifier().identify_with_user_db(
        _pattern_of(tmp_user_db, "q.cif"), top_n=1)
    assert got
    phase = got[0].phase
    assert resolve_cod_id(phase) == phase.db_id
    text, cid = get_phase_cif_text(phase)
    assert cid == phase.db_id
    assert "Si" in text and "cell_length_a" in text


# ── 8. Phase 序列化带 db_id ─────────────────────────────────

def test_phase_db_id_roundtrip():
    from polyxrd.models.phase import Phase

    p = Phase(name="X", formula="O2 Si", db_id=900000007)
    back = Phase.from_dict(p.to_dict())
    assert back.db_id == 900000007
    assert Phase.from_dict({"name": "old"}).db_id is None
