"""
v0.14.0 瘦身索引式无机库兼容测试
================================

v0.14.0 起运行时默认挂 ``COD_inorganics_index.sqlite`` (瘦身索引式):
``phases.cif_gz`` 全为 NULL, CIF 原文由 ``cod/cif`` 四级分片目录按需读取
(本地缺失时 COD REST 在线下载兜底), 与 COD 全库索引同形态。

风险点 (本文件钉死):
  - 搜索/结构候选查询里 ``cif_gz IS NOT NULL`` 过滤在瘦身库上会把结果清空
  - ``has_cif`` 判定必须按"可获取"处理, 而不是看 BLOB 是否非空
  - config 路径解析必须优先瘦身版 (用户导入 > 瘦身 > 完整内嵌)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.config import AppConfig
from polyxrd.services import cod_local
from polyxrd.services.cod_local import CODLocalDatabase

INORG_ID = 1000005


def _make_phases_table(conn: sqlite3.Connection, *, with_cif_gz: bool) -> None:
    conn.execute(
        """CREATE TABLE phases (
            cod_id INTEGER PRIMARY KEY, formula TEXT, space_group TEXT,
            cell_a REAL, cell_b REAL, cell_c REAL,
            cell_alpha REAL, cell_beta REAL, cell_gamma REAL,
            n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT,
            record_offset INTEGER, record_size INTEGER,
            ref_id TEXT, display_id TEXT,
            peaks_top_d TEXT, peaks_top_i TEXT,
            cif_gz BLOB)"""
    )
    conn.execute(
        "INSERT INTO phases (cod_id, formula, space_group, cell_a, cell_b, cell_c,"
        " cell_alpha, cell_beta, cell_gamma, n_peaks, peaks_d, peaks_i,"
        " record_offset, record_size, ref_id, display_id, cif_gz)"
        " VALUES (?, 'Mg O', 'F m -3 m', 4.2112, 4.2112, 4.2112,"
        " 90.0, 90.0, 90.0, 4, '1 2', '100 50', 0, 0, '96-100-0005',"
        " '97-1000005', NULL)",
        (INORG_ID,),
    )
    if not with_cif_gz:
        return


def _make_slim_db(path: Path) -> Path:
    """合成瘦身索引式无机库: cif_gz 全 NULL + meta.variant=slim-index。"""
    conn = sqlite3.connect(str(path))
    _make_phases_table(conn, with_cif_gz=False)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO meta VALUES ('variant',"
        " 'slim-index: cif_gz 全部置 NULL, CIF 由 cod/cif 目录按需读取')"
    )
    conn.commit()
    conn.close()
    return path


def _make_embedded_db(path: Path) -> Path:
    """合成完整内嵌式无机库 (无 meta.variant, cif_gz 非空)。"""
    conn = sqlite3.connect(str(path))
    _make_phases_table(conn, with_cif_gz=True)
    conn.execute(
        "UPDATE phases SET cif_gz = x'1f8b0000000000000000' WHERE cod_id = ?",
        (INORG_ID,),
    )
    conn.commit()
    conn.close()
    return path


class _FakeConfig:
    def __init__(self, cod_db_path):
        self._cod_db_path = cod_db_path

    def get_cod_db_path(self):
        return self._cod_db_path


def _db(tmp_path: Path, inorg_db: Path) -> CODLocalDatabase:
    index_db = tmp_path / "cod_index.sqlite"
    cod_local.connect(index_db).close()
    cod_root = tmp_path / "cod"
    cod_root.mkdir(exist_ok=True)
    return CODLocalDatabase(cod_root=cod_root, db_path=index_db)


@pytest.fixture
def slim_env(tmp_path, monkeypatch):
    """瘦身库挂进 config; 屏蔽 REST 在线回退。"""
    monkeypatch.setattr(
        CODLocalDatabase, "_fetch_cif_from_cod_rest", lambda self, cid: None
    )
    slim = _make_slim_db(tmp_path / "COD_inorganics_index.sqlite")
    monkeypatch.setattr(cod_local, "get_config", lambda: _FakeConfig(slim))
    return {"db": _db(tmp_path, slim), "slim": slim, "tmp": tmp_path}


# ── 瘦身库判定 ───────────────────────────────────────────────

def test_slim_variant_detected(slim_env):
    assert slim_env["db"]._inorg_is_slim() is True


def test_embedded_db_not_slim(tmp_path, monkeypatch):
    emb = _make_embedded_db(tmp_path / "COD_inorganics.sqlite")
    monkeypatch.setattr(cod_local, "get_config", lambda: _FakeConfig(emb))
    assert _db(tmp_path, emb)._inorg_is_slim() is False


def test_slim_probe_missing_db_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        CODLocalDatabase, "_fetch_cif_from_cod_rest", lambda self, cid: None
    )
    monkeypatch.setattr(
        cod_local, "get_config", lambda: _FakeConfig(tmp_path / "gone.sqlite")
    )
    assert _db(tmp_path, tmp_path / "gone.sqlite")._inorg_is_slim() is False


# ── 查询兼容: 瘦身库上不再被 cif_gz IS NOT NULL 清空 ─────────

def test_find_structure_candidates_on_slim(slim_env):
    rows = slim_env["db"].find_structure_candidates("Mg O")
    assert len(rows) == 1
    assert rows[0]["cod_id"] == INORG_ID
    assert rows[0]["has_cif"] is True, "瘦身库 has_cif 应按可获取处理"


def test_structure_like_formula_on_slim(slim_env):
    """旧代码 WHERE ... AND cif_gz IS NOT NULL 在瘦身库上必返回空 —— 回归钉死。"""
    rows = slim_env["db"]._structure_like("Mg%", like_field="formula", limit=10)
    assert len(rows) == 1
    assert rows[0]["has_cif"] is True


def test_structure_by_id_on_slim(slim_env):
    got = slim_env["db"]._structure_by_id(INORG_ID)
    assert got is not None
    assert got["has_cif"] is True
    assert got["formula"] == "Mg O"


def test_embedded_db_unchanged(tmp_path, monkeypatch):
    """原内嵌库行为不回归: has_cif 仍由 cif_gz 决定。"""
    monkeypatch.setattr(
        CODLocalDatabase, "_fetch_cif_from_cod_rest", lambda self, cid: None
    )
    emb = _make_embedded_db(tmp_path / "COD_inorganics.sqlite")
    monkeypatch.setattr(cod_local, "get_config", lambda: _FakeConfig(emb))
    db = _db(tmp_path, emb)
    rows = db.find_structure_candidates("Mg O")
    assert len(rows) == 1 and rows[0]["has_cif"] is True
    assert db._inorg_has_cif_expr() == "(cif_gz IS NOT NULL)"


# ── config 路径解析: 瘦身版优先 ──────────────────────────────

def _fresh_config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.cod_db_path = tmp_path / "cod_data" / "COD_inorganics.sqlite"
    return cfg


def test_config_prefers_index_variant(tmp_path, monkeypatch):
    (tmp_path / "cod_data").mkdir()
    (tmp_path / "cod_data" / "COD_inorganics_index.sqlite").write_bytes(b"x")
    cfg = _fresh_config(tmp_path)
    monkeypatch.setattr(cfg, "user_db_path", lambda key: None, raising=True)
    monkeypatch.setattr(
        cfg, "user_db_dir", lambda: tmp_path / "user", raising=True
    )
    assert cfg.get_cod_db_path().name == "COD_inorganics_index.sqlite"


def test_config_falls_back_to_embedded(tmp_path, monkeypatch):
    (tmp_path / "cod_data").mkdir()
    (tmp_path / "cod_data" / "COD_inorganics.sqlite").write_bytes(b"x")
    cfg = _fresh_config(tmp_path)
    monkeypatch.setattr(cfg, "user_db_path", lambda key: None, raising=True)
    monkeypatch.setattr(
        cfg, "user_db_dir", lambda: tmp_path / "user", raising=True
    )
    assert cfg.get_cod_db_path().name == "COD_inorganics.sqlite"


def test_config_user_import_wins(tmp_path, monkeypatch):
    """用户显式导入的库仍然最高优先 (不被瘦身版顶掉)。"""
    (tmp_path / "cod_data").mkdir()
    (tmp_path / "cod_data" / "COD_inorganics_index.sqlite").write_bytes(b"x")
    imported = tmp_path / "imported" / "my_inorg.sqlite"
    imported.parent.mkdir()
    imported.write_bytes(b"x")
    cfg = _fresh_config(tmp_path)
    monkeypatch.setattr(cfg, "user_db_path", lambda key: imported, raising=True)
    assert cfg.get_cod_db_path() == imported


def test_config_user_dir_prefers_index(tmp_path, monkeypatch):
    """用户目录兜底同样瘦身版优先。"""
    cfg = _fresh_config(tmp_path)
    monkeypatch.setattr(cfg, "user_db_path", lambda key: None, raising=True)
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (user_dir / "COD_inorganics_index.sqlite").write_bytes(b"x")
    (user_dir / "COD_inorganics.sqlite").write_bytes(b"x")
    monkeypatch.setattr(cfg, "user_db_dir", lambda: user_dir, raising=True)
    assert cfg.get_cod_db_path().name == "COD_inorganics_index.sqlite"
