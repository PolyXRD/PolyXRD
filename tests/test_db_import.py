"""sqlite 外挂库探测单测 (v4.1.0: 只剩 PDF2 一类)
================================================

v4.1.0 把旧的 COD sqlite 槽位（``cod_inorganics`` / ``cod_index``）与
XinMatch 兼容槽位一并删除, ``db_import.DB_KINDS`` 只保留 PDF2-2004。本文件钉住:

1. **只认 PDF2** —— 声明表里就一项; 旧 COD ``phases`` 库(缺 pearson/name)
   必须被拒, 而不是静默挂上一个查不出东西的库;
2. **探测只读** —— ``inspect_db_file`` 用 ``mode=ro`` 打开, 不改文件、不生 -wal;
3. **失败要能说清原因** —— 表名对不上 / 列不对 / 行数不足 三种 hint 分开报;
4. **PDF2 永不随发布包分发** —— ``release_package_name`` 恒空串 (ICDD 版权),
   ``PKG_FILENAME`` 仍要对得上实际文件名, 否则界面提示是空的。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config          # noqa: E402
from polyxrd.services import db_import                    # noqa: E402

PDF2_DB = ROOT / "cod_data" / "PDF2_2004.sqlite"

#: v4.1.0 之前那套 COD 无机物库的列（**故意保留**: 用来证明旧格式被拒）
OLD_COD_COLS = """
    cod_id TEXT PRIMARY KEY, formula TEXT, space_group TEXT, n_peaks INTEGER,
    peaks_d TEXT, peaks_i TEXT, cell_a REAL, cell_b REAL, cell_c REAL,
    cell_alpha REAL, cell_beta REAL, cell_gamma REAL
"""
OLD_COD_ROW = ("9001", "SiO2", "P3_121", 2, "3.34,4.26", "100,45",
               4.913, 4.913, 5.405, 90.0, 90.0, 120.0)

PDF2_COLS = """
    cod_id TEXT PRIMARY KEY, formula TEXT, name TEXT, mineral TEXT,
    pearson TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT, cell_a REAL
"""
PDF2_ROW = ("00-046-1045", "SiO2", "Quartz, syn", "Quartz", "hP9", 2,
            "3.34,4.26", "100,22", 4.913)


def _make_db(path: Path, ddl: str, rows: list[tuple] = (),
             insert: str = "") -> Path:
    conn = sqlite3.connect(path)
    try:
        conn.execute(ddl)
        if insert and rows:
            conn.executemany(insert, rows)
        conn.commit()
    finally:
        conn.close()
    return path


def _make_pdf2_db(path: Path, rows: int = 1) -> Path:
    return _make_db(path, f"CREATE TABLE phases ({PDF2_COLS})",
                    [PDF2_ROW] * rows,
                    "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?)")


def _make_old_cod_db(path: Path) -> Path:
    return _make_db(path, f"CREATE TABLE phases ({OLD_COD_COLS})", [OLD_COD_ROW],
                    "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")


@pytest.fixture
def tmp_cfg(tmp_path, monkeypatch):
    """把 user_db_paths.json 重定向到临时目录, 不碰用户真实配置。"""
    target = tmp_path / "user_db_paths.json"
    monkeypatch.setattr(AppConfig, "_user_db_paths_file", lambda self: target)
    return target


# ── 1. 声明表 ────────────────────────────────────────────────

def test_only_pdf2_kind_is_declared():
    assert [k.key for k in db_import.DB_KINDS] == ["pdf2"]
    assert set(db_import.KIND_BY_KEY) == {"pdf2"}


def test_pdf2_notice_key_resolves_in_all_languages():
    from polyxrd.i18n.translations import en_US, ja_JP, zh_CN

    key = db_import.KIND_BY_KEY["pdf2"].notice_key
    assert key
    for mod in (zh_CN, en_US, ja_JP):
        node = mod.translations
        for part in key.split("."):
            assert isinstance(node, dict) and part in node, (mod.__name__, key)
            node = node[part]
        assert str(node).strip()


# ── 2. 探测: 真实库 ──────────────────────────────────────────

@pytest.mark.skipif(not PDF2_DB.exists(), reason="PDF2 库不在本机")
def test_inspect_real_pdf2():
    ins = db_import.inspect_db_file(PDF2_DB)
    assert ins.ok and ins.kind == "pdf2"
    assert ins.rows == 163_834
    # PDF2 自带的 peaks_d 只有 ~64 个/相, 不需要 top-N 列
    assert ins.has_top_peaks is False
    assert ins.error == ""


# ── 3. 旧格式必须被拒 ────────────────────────────────────────

def test_old_cod_sqlite_is_rejected(tmp_path):
    """表名同为 phases, 但缺 pearson/name → 不该被当成 PDF2。"""
    p = _make_old_cod_db(tmp_path / "old_cod.sqlite")
    ins = db_import.inspect_db_file(p)
    assert not ins.ok
    assert ins.kind is None
    assert ins.error == "no_matching_schema"


def test_old_cod_sqlite_hint_is_absent_not_misleading(tmp_path):
    """拒收时 hint 为空 —— 没有"缺列"可提示, 别把用户往改列名的方向带。"""
    p = _make_old_cod_db(tmp_path / "old_cod2.sqlite")
    assert db_import.inspect_db_file(p).hint == ""


def test_pdf2_shaped_file_is_accepted(tmp_path):
    p = _make_pdf2_db(tmp_path / "fake_pdf2.sqlite")
    ins = db_import.inspect_db_file(p)
    assert ins.ok and ins.kind == "pdf2" and ins.rows == 1


# ── 4. 失败原因 ──────────────────────────────────────────────

def test_missing_required_column_reports_hint(tmp_path):
    """有签名列(name)但缺 peaks_d/peaks_i → schema_mismatch + 缺列清单。"""
    p = _make_db(
        tmp_path / "no_peaks.sqlite",
        "CREATE TABLE phases (cod_id TEXT, formula TEXT, name TEXT, n_peaks INTEGER)",
    )
    ins = db_import.inspect_db_file(p)
    assert not ins.ok
    assert ins.error == "schema_mismatch"
    assert "peaks_d" in ins.hint and "peaks_i" in ins.hint


def test_empty_pdf2_table_rejected(tmp_path):
    p = _make_pdf2_db(tmp_path / "empty_pdf2.sqlite", rows=0)
    ins = db_import.inspect_db_file(p)
    assert not ins.ok
    assert ins.error == "schema_mismatch"
    assert ins.hint.startswith("too_few_rows:")


def test_empty_sqlite_no_matching_table(tmp_path):
    p = _make_db(tmp_path / "empty.sqlite", "CREATE TABLE unrelated (x INTEGER)")
    ins = db_import.inspect_db_file(p)
    assert not ins.ok and ins.error == "no_matching_table"


def test_non_sqlite_file_rejected(tmp_path):
    p = tmp_path / "notdb.sqlite"
    p.write_text("this is plain text, not sqlite", encoding="utf-8")
    ins = db_import.inspect_db_file(p)
    assert not ins.ok and ins.error == "not_sqlite"


def test_missing_file_and_directory(tmp_path):
    assert db_import.inspect_db_file(tmp_path / "nope.sqlite").error == "file_not_found"
    assert db_import.inspect_db_file(tmp_path).error == "not_a_file"


def test_inspect_is_read_only(tmp_path):
    """探测过程绝不能改动被测文件 (mode=ro)。"""
    p = _make_pdf2_db(tmp_path / "ro.sqlite")
    before = (p.stat().st_size, p.stat().st_mtime_ns)
    db_import.inspect_db_file(p)
    assert (p.stat().st_size, p.stat().st_mtime_ns) == before
    assert not (tmp_path / "ro.sqlite-wal").exists()


# ── 5. 槽位清除 ──────────────────────────────────────────────

def test_clear_import_resets_pdf2_slot(tmp_cfg, tmp_path):
    cfg = get_config()
    p = _make_pdf2_db(tmp_path / "pdf2.sqlite")
    cfg.set_pdf2_db_path(p)
    assert cfg.get_pdf2_db_path() == p.resolve()

    db_import.clear_import("pdf2")
    assert cfg.user_db_path("pdf2_db_path") is None
    assert cfg.get_pdf2_db_path() != p.resolve()


def test_clear_import_unknown_key(tmp_cfg):
    for bad in ("cod_inorganics", "cod_index", "xinmatch", "no_such_kind"):
        with pytest.raises(KeyError):
            db_import.clear_import(bad)


def test_reload_caches_is_idempotent():
    db_import.reload_caches()
    db_import.reload_caches()          # 没有 PDF2Database 实例时也不能抛


# ── 6. 发布包口径 ────────────────────────────────────────────

def test_pdf2_never_has_release_package():
    """PDF2-2004 是 ICDD 商业库, 恒无发布包 (空串); 传错 key 仍要 KeyError。"""
    assert db_import.release_package_name("pdf2", "4.1.0") == ""
    assert db_import.release_package_name("pdf2", "9.9.9") == ""
    for bad in ("cod_inorganics", "cod_index", "xinmatch"):
        with pytest.raises(KeyError):
            db_import.release_package_name(bad, "4.1.0")


def test_pkg_filename_matches_declared_kinds():
    assert db_import.PKG_FILENAME["pdf2"] == "PDF2_2004.sqlite"
    for k in db_import.DB_KINDS:
        assert db_import.PKG_FILENAME.get(k.key), k.key
