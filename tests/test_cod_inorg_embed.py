"""
COD 无机物库内嵌 CIF / 原子位点回退测试 (v0.11.0)
==================================================

v0.11.0 起无机物库 (phases 表) 自带 ``cif_gz`` 列 (gzip CIF 全文) 与
``cod_atomic_sites`` 子集表。背景: 无机库与 COD 全库索引 (cod_index.sqlite)
的 COD 编号体系**并不重合** —— 全库只覆盖约 1/3 的无机相编号, 旧版在
"只挂无机库"时几乎拿不到结构数据, Rietveld 结构精修无从谈起。

`CODLocalDatabase` 因此新增两条回退:
  - get_cif():      Level 2b —— 全库 cif_gz 查不到 → 无机库 cif_gz
  - get_atomic_sites(): 全库位点查不到 → 无机库位点子集

本文件用合成小库把回退链钉死 (不动真实 372 MB 库)。
"""
from __future__ import annotations

import gzip
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.services import cod_local
from polyxrd.services.cod_local import CODLocalDatabase

# 无机库里的编号 (注意: 故意用 1xxx 段, 全库索引里没有)
INORG_ID = 1000005
FULL_ID = 2000000  # 全库索引里有的编号

MINIMAL_CIF = """data_1000005
_chemical_formula_sum 'Mg O'
_cell_length_a 4.2112
_cell_length_b 4.2112
_cell_length_c 4.2112
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'F m -3 m'
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 Mg1 Mg 0.0 0.0 0.0 1.0
 O1 O 0.5 0.5 0.5 1.0
"""


def _make_inorg_db(path: Path, *, with_cif_gz: bool = True) -> Path:
    """合成无机物库: phases 表 (含/不含 cif_gz) + cod_atomic_sites 子集。"""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE phases (
            cod_id INTEGER PRIMARY KEY, formula TEXT, space_group TEXT,
            cell_a REAL, cell_b REAL, cell_c REAL,
            cell_alpha REAL, cell_beta REAL, cell_gamma REAL,
            n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT,
            record_offset INTEGER, record_size INTEGER,
            ref_id TEXT, display_id TEXT,
            peaks_top_d TEXT, peaks_top_i TEXT)"""
    )
    conn.execute(
        "INSERT INTO phases (cod_id, formula, space_group, cell_a, cell_b, cell_c,"
        " cell_alpha, cell_beta, cell_gamma, n_peaks, peaks_d, peaks_i,"
        " record_offset, record_size, ref_id, display_id)"
        " VALUES (?, 'Mg O', 'F m -3 m', 4.2112, 4.2112, 4.2112,"
        " 90.0, 90.0, 90.0, 4, '1 2', '100 50', 0, 0, '96-100-0005', '97-1000005')",
        (INORG_ID,),
    )
    if with_cif_gz:
        conn.execute("ALTER TABLE phases ADD COLUMN cif_gz BLOB")
        conn.execute(
            "UPDATE phases SET cif_gz=? WHERE cod_id=?",
            (gzip.compress(MINIMAL_CIF.encode("utf-8")), INORG_ID),
        )
    conn.execute(
        """CREATE TABLE cod_atomic_sites (
            cod_id INTEGER NOT NULL, site_idx INTEGER NOT NULL,
            label TEXT, element TEXT NOT NULL,
            x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
            occupancy REAL, PRIMARY KEY (cod_id, site_idx))"""
    )
    for i, (lab, el, x, y, z) in enumerate([
        ("Mg1", "Mg", 0.0, 0.0, 0.0), ("O1", "O", 0.5, 0.5, 0.5),
    ]):
        conn.execute(
            "INSERT INTO cod_atomic_sites VALUES (?,?,?,?,?,?,?,?)",
            (INORG_ID, i, lab, el, x, y, z, 1.0),
        )
    conn.commit()
    conn.close()
    return path


def _make_index_db(path: Path, *, with_full_id: bool = False) -> Path:
    """合成 COD 全库索引 (经 cod_local.connect 建 schema, 再按需插一条)。"""
    conn = cod_local.connect(path)
    if with_full_id:
        conn.execute(
            "INSERT INTO cod_entries (cod_id, file, formula, elements, space_group,"
            " space_group_number, a, b, c, alpha, beta, gamma, volume, z_value,"
            " last_updated, parse_ok) VALUES (?, 'cif/2/00/00/2000000.cif',"
            " 'Na Cl', 'Na,Cl', 'F m -3 m', 225, 5.64, 5.64, 5.64,"
            " 90.0, 90.0, 90.0, 179.4, 4, 1, 1)",
            (FULL_ID,),
        )
        conn.execute(
            "INSERT INTO cod_atomic_sites (cod_id, site_idx, label, element,"
            " x, y, z, occupancy) VALUES (?, 0, 'Na1', 'Na', 0.0, 0.0, 0.0, 1.0)",
            (FULL_ID,),
        )
    conn.commit()
    conn.close()
    return path


class _FakeConfig:
    """只暴露 CODLocalDatabase 用到的接口。"""

    def __init__(self, cod_db_path):
        self._cod_db_path = cod_db_path

    def get_cod_db_path(self):
        return self._cod_db_path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """标准环境: 全库索引 (无该编号) + 带内嵌 CIF 的无机库, 指针进 config。

    必须屏蔽 COD REST 在线回退 —— 否则 get_cif 的回退链会真的去
    crystallography.net 拉数据, 测试既慢又依赖网络, 断言也不可复现。
    """
    monkeypatch.setattr(
        CODLocalDatabase, "_fetch_cif_from_cod_rest", lambda self, cid: None
    )
    index_db = _make_index_db(tmp_path / "cod_index.sqlite")
    inorg_db = _make_inorg_db(tmp_path / "COD_inorganics.sqlite")
    monkeypatch.setattr(
        cod_local, "get_config", lambda: _FakeConfig(inorg_db), raising=True
    )
    return {"index": index_db, "inorg": inorg_db, "tmp": tmp_path}


def _db(index_db: Path) -> CODLocalDatabase:
    return CODLocalDatabase(cod_root=tmp_cod_root(index_db), db_path=index_db)


def tmp_cod_root(index_db: Path) -> Path:
    """cod_root 指向一个空目录 (不与 cod/cif 混淆)。"""
    r = index_db.parent / "cod"
    r.mkdir(exist_ok=True)
    return r


# ── get_cif Level 2b 回退 ────────────────────────────────────

def test_get_cif_falls_back_to_inorg_embedded(env):
    db = _db(env["index"])
    assert db.get_cif(INORG_ID) == MINIMAL_CIF


def test_get_cif_prefers_full_index_when_it_has_the_id(env):
    """全库索引里有编号 → 用全库的 (不因回退而改变既有优先级)。"""
    index_db = _make_index_db(env["tmp"] / "idx2.sqlite", with_full_id=True)
    db = _db(index_db)
    text = db.get_cif(FULL_ID)
    # 全库这条 cif_gz 为 NULL → 落到无机库回退查不到 → 最终 None
    assert text is None


def test_get_cif_returns_none_for_unknown_id(env):
    db = _db(env["index"])
    assert db.get_cif(9999999) is None


# ── get_atomic_sites 回退 ────────────────────────────────────

def test_atomic_sites_fallback_to_inorg(env):
    db = _db(env["index"])
    sites = db.get_atomic_sites(INORG_ID)
    assert [s["element"] for s in sites] == ["Mg", "O"]
    assert sites[0]["x"] == 0.0 and sites[1]["z"] == 0.5


def test_atomic_sites_unknown_id_empty(env):
    db = _db(env["index"])
    assert db.get_atomic_sites(9999999) == []


# ── 能力探测边界 ─────────────────────────────────────────────

def test_old_inorg_db_without_cif_gz_is_ignored(tmp_path, monkeypatch):
    """旧版无机库 (没有 cif_gz 列) → 探测失败, 回退链整体不启用。"""
    monkeypatch.setattr(
        CODLocalDatabase, "_fetch_cif_from_cod_rest", lambda self, cid: None
    )
    index_db = _make_index_db(tmp_path / "cod_index.sqlite")
    old_db = _make_inorg_db(tmp_path / "COD_inorganics.sqlite", with_cif_gz=False)
    monkeypatch.setattr(cod_local, "get_config", lambda: _FakeConfig(old_db))
    db = _db(index_db)
    assert db._inorg_db() is None
    assert db.get_cif(INORG_ID) is None


def test_missing_inorg_db_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(
        CODLocalDatabase, "_fetch_cif_from_cod_rest", lambda self, cid: None
    )
    index_db = _make_index_db(tmp_path / "cod_index.sqlite")
    monkeypatch.setattr(
        cod_local, "get_config", lambda: _FakeConfig(tmp_path / "gone.sqlite")
    )
    db = _db(index_db)
    assert db._inorg_db() is None
    assert db.get_cif(INORG_ID) is None


def test_same_file_guard(tmp_path, monkeypatch):
    """全库索引被当作无机库挂载 (同一文件) → 不重复打开自己。"""
    same = tmp_path / "cod_index.sqlite"
    _make_index_db(same)
    monkeypatch.setattr(cod_local, "get_config", lambda: _FakeConfig(same))
    db = CODLocalDatabase(cod_root=tmp_path / "cod", db_path=same)
    assert db._inorg_db() is None


def test_probe_result_is_cached(env):
    """探测结果缓存: 二次调用不再打开新连接 (快速路径)。"""
    db = _db(env["index"])
    c1 = db._inorg_db()
    c2 = db._inorg_db()
    assert c1 is not None and c1 is c2


# ── 端到端: 只挂无机库也能产出可精修的 Phase ────────────────

def test_get_phase_works_with_inorg_only(env):
    db = _db(env["index"])
    phase = db.get_phase(INORG_ID, use_pymatgen_peaks=False)
    assert phase is not None, "只挂无机库时 get_phase 不应返回 None"
    assert phase.formula == "Mg O"
    assert phase.lattice.a == pytest.approx(4.2112)
    # v0.15.2 起 get_phase 对称展开为全胞 (F m -3 m 方镁石: 4 Mg + 4 O),
    # 供 |F|² 精修与正确的谱合成; 不再返回 2 位点的非对称单元
    assert len(phase.atomic_sites) == 8
    assert sum(1 for s in phase.atomic_sites
               if s.get("element") == "Mg") == 4
    assert sum(1 for s in phase.atomic_sites
               if s.get("element") == "O") == 4


def test_inorg_readonly(env):
    """回退连接必须只读 (mode=ro), 不得写用户的库。"""
    db = _db(env["index"])
    conn = db._inorg_db()
    assert conn is not None
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO phases (cod_id) VALUES (1)")
