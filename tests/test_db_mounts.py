"""挂载注册表 db_mounts 单测 (v4.1.0)
=====================================
列表式多库挂载的**唯一真相源**是 ``polyxrd.services.db_mounts``; 对话框与
物相检索都只是它的视图。v4.1.0 把旧 sqlite 槽位 (cod_inorganics / cod_index /
xinmatch) 删掉后, 这里钉住现在的六件事:

1. **内置项零迁移** —— 内置 id 固定为 ``polydb:cod-inorg`` / ``polydb:cod-full``
   / ``pdf2`` / ``user``, 老字面量 (``cod_inorganics`` 等) 一律**别名**到
   语义等价的新库, 老配置不会报"库不存在";
2. **同类型多份共存** —— 用户自加项 id 为 ``<kind>:<路径摘要>``, 幂等;
3. **解析成 (kind, path)** —— 检索链路据此分发;
4. **卸载不清库文件** —— 内置 polyDB 卸载 = 取消挂载 (并记住别再自动发现),
   自加项卸载 = 删记录;
5. **探测只读** —— probe 不改任何配置, 失败原因原样返回;
6. **旧格式文件不再被接受** —— COD 的无机库 sqlite 已废弃, 挂载时报
   ``no_matching_schema`` 而不是静默挂上一个查不出东西的库。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config   # noqa: E402
from polyxrd.services import db_mounts             # noqa: E402

#: v4.1.0 之前那套 COD 无机物库的 DDL（**故意保留**: 用来证明旧格式被拒）
OLD_COD_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, n_peaks INTEGER,"
               " peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
OLD_COD_ROW = ("9001", "SiO2", 2, "3.34,4.26", "100,45", 4.913)

PDF2_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, name TEXT,"
            " pearson TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
PDF2_ROW = ("00-046-1045", "SiO2", "Quartz", "hP9", 2, "3.34,4.26", "100,22", 4.913)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """挂载表 + 槽位配置全部隔离。"""
    store = tmp_path / "db_mounts.json"
    monkeypatch.setattr(db_mounts, "_store_file", lambda: store)
    monkeypatch.setattr(AppConfig, "_user_db_paths_file",
                        lambda self: tmp_path / "user_db_paths.json")
    cfg = get_config()
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(cfg, "cif_db_path", empty)
    monkeypatch.setattr(cfg, "user_db_dir", lambda: empty)
    # 默认 polyDB 的自动发现也要隔离, 否则本机真实产物会让断言飘
    monkeypatch.setattr(cfg, "get_polydb_path", lambda *a, **k: None)
    monkeypatch.setattr(db_mounts, "_probe_user",
                        lambda p: {"ok": False, "rows": 0, "error": "user_db_empty"})
    db_mounts.clear_probe_cache()
    return store


def _sqlite(path: Path, ddl: str, row: tuple) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(ddl)
        marks = ",".join("?" * len(row))
        conn.execute(f"INSERT INTO phases VALUES ({marks})", row)
        conn.commit()
    finally:
        conn.close()
    return path


def _polydb(root: Path, name: str, variant: str = "cod-inorg",
            phases: int = 100) -> Path:
    """造一个"看起来合法"的 polyDB 目录 (只满足存在性与 meta 解析, 不开库)。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({
        "format": "polyDB", "schema_version": 1, "variant": variant,
        "counts": {"phases": phases, "k": 100, "peaks": 1000, "sites": 500},
    }), encoding="utf-8")
    (d / "index.sqlite").write_bytes(b"")
    return d


# ── 1. 内置项 ────────────────────────────────────────────────

def test_builtin_ids_and_order(isolated):
    ids = [m.id for m in db_mounts.all_mounts()]
    assert ids == ["polydb:cod-inorg", "polydb:cod-full", "pdf2", "user"]


def test_builtin_polydb_labels_are_distinct(isolated):
    by_id = {m.id: m for m in db_mounts.all_mounts()}
    assert (by_id["polydb:cod-inorg"].label_key
            != by_id["polydb:cod-full"].label_key)
    assert by_id["polydb:cod-inorg"].variant == "cod-inorg"
    assert by_id["polydb:cod-full"].variant == "cod-full"


@pytest.mark.parametrize("legacy,expected_kind", [
    ("cod_inorganics", "polydb"),
    ("xinmatch", "polydb"),
    ("cod_index", "polydb"),
    ("cod_full", "polydb"),
    ("cod_local", "polydb"),
    ("polydb", "polydb"),
    ("pdf2", "polydb"),
])
def test_legacy_aliases_resolve(isolated, legacy, expected_kind):
    m = db_mounts.resolve_mount(legacy)
    assert m is not None and m.kind == expected_kind


def test_legacy_inorg_aliases_land_on_the_inorg_variant(isolated):
    assert db_mounts.resolve_mount("cod_inorganics").variant == "cod-inorg"
    assert db_mounts.resolve_mount("xinmatch").variant == "cod-inorg"
    assert db_mounts.resolve_mount("cod_full").variant == "cod-full"


def test_unknown_source_resolves_to_none(isolated):
    assert db_mounts.resolve_mount("no-such-lib") is None
    assert db_mounts.resolve_source("builtin") == (None, None)


def test_configured_polydb_path_shows_up_as_builtin(isolated, tmp_path, monkeypatch):
    poly = _polydb(tmp_path / "libs", "COD-Inorg-20261021.polyDB")
    cfg = get_config()
    monkeypatch.setattr(cfg, "get_polydb_path",
                        lambda variant="cod-inorg": poly if variant == "cod-inorg" else None)
    m = db_mounts.get_mount("polydb:cod-inorg")
    assert m is not None and m.builtin and m.path == poly and m.exists


# ── 2. 用户自加项 ────────────────────────────────────────────

def test_add_mount_polydb_reads_variant(isolated, tmp_path):
    poly = _polydb(tmp_path / "libs", "Mine.polyDB", variant="cod-full")
    m = db_mounts.add_mount(poly)
    assert m.kind == "polydb" and m.builtin is False
    assert m.id.startswith("polydb:")
    stored = json.loads((tmp_path / "db_mounts.json").read_text(encoding="utf-8"))
    assert stored["mounts"][0]["variant"] == "cod-full"


def test_add_mount_is_idempotent(isolated, tmp_path):
    poly = _polydb(tmp_path / "libs", "A.polyDB")
    a = db_mounts.add_mount(poly)
    b = db_mounts.add_mount(poly)
    assert a.id == b.id
    stored = json.loads((tmp_path / "db_mounts.json").read_text(encoding="utf-8"))
    assert len(stored["mounts"]) == 1


def test_same_kind_multiple_mounts_are_distinct(isolated, tmp_path):
    a = db_mounts.add_mount(_polydb(tmp_path / "l", "A.polyDB"))
    b = db_mounts.add_mount(_polydb(tmp_path / "l", "B.polyDB"))
    assert a.id != b.id
    assert {a.id, b.id} <= {m.id for m in db_mounts.all_mounts()}


def test_add_mount_rejects_old_cod_sqlite(isolated, tmp_path):
    """旧格式 sqlite 库不再被接受（v5.2 删掉 sqlite 通道，只认 polyDB 目录）。"""
    old = _sqlite(tmp_path / "old.sqlite", OLD_COD_DDL, OLD_COD_ROW)
    with pytest.raises(ValueError) as ei:
        db_mounts.add_mount(old)
    # 报错必须**指向下一步**（改用 polyDB 目录），否则用户只看到"挂不上"
    assert "polyDB" in str(ei.value)
    assert db_mounts.detect_kind(old)[0] == ""


def test_add_mount_rejects_missing_path(isolated, tmp_path):
    with pytest.raises(ValueError):
        db_mounts.add_mount(tmp_path / "nope.polyDB")


# ── 3. 卸载 ─────────────────────────────────────────────────

def test_remove_custom_mount_keeps_file(isolated, tmp_path):
    poly = _polydb(tmp_path / "libs", "A.polyDB")
    m = db_mounts.add_mount(poly)
    db_mounts.remove_mount(m.id)
    assert poly.is_dir()
    assert m.id not in {x.id for x in db_mounts.all_mounts()}


def test_remove_builtin_polydb_disables_variant(isolated, monkeypatch):
    """卸载内置 polyDB = 取消挂载, 并且**记住别再自动发现**。"""
    seen: list[tuple] = []
    monkeypatch.setattr(AppConfig, "set_polydb_path",
                        lambda self, path, variant="cod-inorg": seen.append((path, variant)))
    db_mounts.remove_mount("polydb:cod-inorg")
    assert seen == [(None, "cod-inorg")]


def test_remove_builtin_pdf2_clears_slot(isolated, monkeypatch):
    """PDF2 现在也是 polyDB 变体：卸载 = 清 ``pdf2-2004`` 槽位。"""
    from polyxrd.config import get_config

    seen: list[tuple] = []
    monkeypatch.setattr(
        get_config(), "set_polydb_path",
        lambda path, variant="cod-inorg": seen.append((path, variant)))
    db_mounts.remove_mount("pdf2")
    assert seen == [(None, "pdf2-2004")]


def test_user_db_cannot_be_removed_here(isolated):
    with pytest.raises(ValueError):
        db_mounts.remove_mount("user")


def test_set_active_and_clear(isolated, tmp_path):
    poly = _polydb(tmp_path / "libs", "A.polyDB")
    m = db_mounts.add_mount(poly)
    db_mounts.set_active(m.id)
    assert db_mounts.active_id() == m.id
    assert db_mounts.active_mount().id == m.id
    db_mounts.set_active("")
    assert db_mounts.active_id() == ""
    assert db_mounts.active_mount() is None


# ── 4. 探测 ─────────────────────────────────────────────────

def test_probe_missing_file(isolated):
    m = db_mounts.Mount(id="pdf2", kind="polydb", path=Path("D:/no/such.polyDB"))
    res = db_mounts.probe(m)
    assert res["ok"] is False and res["error"] == "missing"


def test_probe_unmounted_builtin(isolated):
    res = db_mounts.probe(db_mounts.get_mount("polydb:cod-inorg"))
    assert res["ok"] is False and res["error"] == "unmounted"


def test_probe_never_writes_config(isolated, tmp_path):
    before = (tmp_path / "user_db_paths.json").exists()
    db_mounts.probe_all()
    assert (tmp_path / "user_db_paths.json").exists() == before


def test_source_entries_carry_mount_fields(isolated):
    rows = db_mounts.source_entries()
    assert {"id", "kind", "path", "ok", "rows", "label_key"} <= set(rows[0])
    assert [r["id"] for r in rows][:2] == ["polydb:cod-inorg", "polydb:cod-full"]


# ── 5. 类型判别 / 整目录挂载 ────────────────────────────────

def test_detect_kind_rejects_legacy_pdf2_sqlite(isolated, tmp_path):
    """v5.2: 旧 PDF2 sqlite 不再被识别，报错必须指向 polyDB 迁移。"""
    f = _sqlite(tmp_path / "PDF2_2004.sqlite", PDF2_DDL, PDF2_ROW)
    kind, why = db_mounts.detect_kind(f)
    assert kind == "" and "polyDB" in why


def test_detect_kind_rejects_plain_dir(isolated, tmp_path):
    d = tmp_path / "notalib"
    d.mkdir()
    kind, why = db_mounts.detect_kind(d)
    assert kind == "" and "polyDB" in why


def test_detect_kind_expect_mismatch(isolated, tmp_path):
    poly = _polydb(tmp_path / "libs", "A.polyDB")
    kind, why = db_mounts.detect_kind(poly, expect="user")
    assert kind == "" and "user" in why


def test_mount_any_folder_collects_polydb_and_skips_legacy(isolated, tmp_path):
    """混合文件夹：polyDB 全挂上，旧 sqlite 跳过并给出原因（不静默丢弃）。"""
    root = tmp_path / "drop"
    _polydb(root, "A.polyDB")
    _polydb(root, "B.polyDB", variant="cod-full")
    _sqlite(root / "PDF2_2004.sqlite", PDF2_DDL, PDF2_ROW)
    mounted, skipped = db_mounts.mount_any_report(root)
    assert sorted(m.kind for m in mounted) == ["polydb", "polydb"]
    assert len(skipped) == 1 and "v5.2" in skipped[0]


def test_mount_any_empty_folder_raises(isolated, tmp_path):
    d = tmp_path / "empty"          # 已由 isolated fixture 建好, 这里不再重复 mkdir
    d.mkdir(exist_ok=True)
    with pytest.raises(ValueError) as ei:
        db_mounts.mount_any(d)
    assert "没有" in str(ei.value)


def test_backup_files_are_ignored(isolated, tmp_path):
    d = tmp_path / "drop"
    d.mkdir()
    (d / "old.bak-20261011.db").write_bytes(b"")
    (d / "old~.sqlite").write_bytes(b"")
    assert db_mounts._iter_db_files(d) == []
