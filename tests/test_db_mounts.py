"""挂载注册表 db_mounts 单测 (v4.0.0)
=====================================
列表式多库挂载的**唯一真相源**是 ``polyxrd.services.db_mounts``; 对话框与
物相检索都只是它的视图。这里钉住它对外承诺的六件事:

1. **内置项零迁移** —— 老用户升级后, 配置里挂着的库自动出现在列表里
   (id 就是类型名), 历史 ``db_source="pdf2"`` 一类字面量继续有效;
2. **同类型多份共存** —— 用户自加项 id 为 ``<kind>:<路径摘要>``, 幂等;
3. **解析成 (kind, path)** —— 检索链路据此分发; 库被挪走时给出"按配置解析"
   或"不可用", 不能静默指向另一份库;
4. **卸载不清库文件** —— 内置项卸载 = 清配置槽位, 自加项卸载 = 删记录;
5. **探测只读** —— probe 不改任何配置, 失败原因原样返回;
6. **挂载不改配置** —— mount_any 只写挂载表 (旧 db_import 是"每类覆盖槽位"
   语义, 会在同类型第二份库上把第一份顶掉)。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config   # noqa: E402
from polyxrd.services import db_mounts             # noqa: E402

COD_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, n_peaks INTEGER,"
           " peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
COD_INS = "INSERT INTO phases VALUES (?,?,?,?,?,?)"
COD_ROW = ("9001", "SiO2", 2, "3.34,4.26", "100,45", 4.913)

PDF2_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, name TEXT,"
            " pearson TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
PDF2_INS = "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)"
PDF2_ROW = ("00-046-1045", "SiO2", "Quartz", "hP9", 2, "3.34,4.26", "100,22", 4.913)

XM_DDL = (
    "CREATE TABLE entries (entry_id TEXT PRIMARY KEY, formula TEXT,"
    " mineral_name TEXT, space_group TEXT, crystal_system TEXT, a REAL, b REAL,"
    " c REAL, alpha REAL, beta REAL, gamma REAL, volume REAL, density REAL,"
    " color TEXT, year INTEGER, author TEXT, journal TEXT, quality TEXT,"
    " elements TEXT)",
    "CREATE TABLE peaks (entry_id TEXT NOT NULL, d REAL NOT NULL,"
    " intensity REAL, h INTEGER, k INTEGER, l INTEGER)",
    "CREATE TABLE elements (entry_id TEXT NOT NULL, element TEXT NOT NULL,"
    " PRIMARY KEY (entry_id, element))",
    "CREATE TABLE element_combo (element_set_hash TEXT PRIMARY KEY,"
    " entry_ids TEXT NOT NULL)",
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """挂载表 + 槽位配置全部隔离。"""
    store = tmp_path / "db_mounts.json"
    monkeypatch.setattr(db_mounts, "_store_file", lambda: store)
    monkeypatch.setattr(AppConfig, "_user_db_paths_file",
                        lambda self: tmp_path / "user_db_paths.json")
    # 内置项指向不存在的默认位置 (改字段而不是改 get_*_db_path: 后者被
    # set_cod_db_path 写进配置后要能立刻读到, 换了实现就读不到了)
    cfg = get_config()
    empty = tmp_path / "empty"
    monkeypatch.setattr(cfg, "cod_db_path", empty / "n_cod.sqlite")
    monkeypatch.setattr(cfg, "pdf2_db_path", empty / "n_pdf2.sqlite")
    monkeypatch.setattr(cfg, "cif_db_path", empty)
    monkeypatch.setattr(cfg, "user_db_dir", lambda: empty)
    monkeypatch.setattr(cfg, "get_xinmatch_db_path", lambda: None)
    monkeypatch.setattr(cfg, "get_polydb_path", lambda *a, **k: None)
    monkeypatch.setattr(db_mounts, "_cod_index_path", lambda: None)
    monkeypatch.setattr(db_mounts, "_probe_user",
                        lambda p: {"ok": False, "rows": 0, "error": "user_db_empty"})
    db_mounts.clear_probe_cache()
    return store


def _db(path: Path, ddl: str, row: tuple, insert: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(ddl)
    conn.executemany(insert, [row])
    conn.commit()
    conn.close()
    return path


def _xm(path: Path, rows: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    for ddl in XM_DDL:
        conn.execute(ddl)
    for i in range(rows):
        eid = f"XM-{i:03d}"
        conn.execute(
            "INSERT INTO entries (entry_id, formula, space_group, crystal_system,"
            " a, b, c, alpha, beta, gamma, elements) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "O Zn", "P 63 m c", "hexagonal", 3.2495, 3.2495, 5.2069,
             90.0, 90.0, 120.0, "O,Zn"))
        conn.execute("INSERT INTO peaks VALUES (?,?,?,?,?,?)",
                     (eid, 2.4759 + i * 0.01, 570.0, 1, 0, 1))
        conn.execute("INSERT INTO elements VALUES (?,?)", (eid, "Zn"))
    conn.commit()
    conn.close()
    return path


# ── 1. 内置项与老字面量 ─────────────────────────────────────

def test_builtin_mounts_have_kind_as_id(isolated):
    """内置项 id 就用类型名 → 历史 ``db_source`` 字面量继续有效。"""
    ids = [m.id for m in db_mounts.default_mounts()]
    assert ids == ["cod_inorganics", "cod_index", "pdf2", "xinmatch",
                   "polydb:cod-inorg", "polydb:cod-full", "user"]


def test_legacy_aliases_resolve(isolated, tmp_path):
    """``cod_full`` / ``polydb`` / ``polydb_full`` 这些老写法必须还能解析。"""
    assert db_mounts.resolve_mount("cod_full").kind == "cod_index"
    assert db_mounts.resolve_mount("polydb").id == "polydb:cod-inorg"
    assert db_mounts.resolve_mount("polydb_full").id == "polydb:cod-full"
    assert db_mounts.resolve_mount("pdf2").kind == "pdf2"
    # 内置库/合并不是"某个具体的库", 交给原有分支
    assert db_mounts.resolve_mount("builtin") is None
    assert db_mounts.resolve_mount("merged") is None


def test_configured_path_shows_up_as_builtin_and_passes_path(isolated, tmp_path, monkeypatch):
    """配置里挂着的库自动出现在列表里, 且解析出的路径就是它。"""
    cod = _db(tmp_path / "cod.sqlite", COD_DDL, COD_ROW, COD_INS)
    get_config().set_cod_db_path(cod)
    m = db_mounts.resolve_mount("cod_inorganics")
    assert m.path == cod and m.builtin
    kind, path = db_mounts.resolve_source("cod_inorganics")
    assert (kind, path) == ("cod_inorganics", cod)


# ── 2. 同类型多份 ───────────────────────────────────────────

def test_same_kind_multiple_mounts_are_distinct(isolated, tmp_path):
    a = _xm(tmp_path / "a" / "cod_inorganics.db", 2)
    b = _xm(tmp_path / "b" / "cod_full.db", 5)
    ma = db_mounts.add_mount(a)
    mb = db_mounts.add_mount(b)
    assert ma.id != mb.id
    assert ma.kind == mb.kind == "xinmatch"
    assert not ma.builtin
    rows = [r for r in db_mounts.probe_all() if r["kind"] == "xinmatch" and r["ok"]]
    assert {r["path"] for r in rows} == {str(a), str(b)}
    # 各自解析到各自的文件 (同类型挂多份的全部意义)
    assert db_mounts.resolve_source(ma.id)[1] == a
    assert db_mounts.resolve_source(mb.id)[1] == b


def test_add_mount_is_idempotent(isolated, tmp_path):
    """同一路径反复添加 → 同一个 id, 列表里不会出现两行一样的库。"""
    a = _xm(tmp_path / "a" / "cod_inorganics.db")
    first = db_mounts.add_mount(a)
    again = db_mounts.add_mount(a)
    assert first.id == again.id
    assert [m.id for m in db_mounts.all_mounts()].count(first.id) == 1


def test_mount_any_does_not_touch_slot_config(isolated, tmp_path):
    """挂载只写挂载表: 不能像旧 mount_databases 那样把别人的槽位顶掉。"""
    store_cfg = Path.home() / ".polyxrd" / "user_db_paths.json"
    before = store_cfg.read_text(encoding="utf-8") if store_cfg.exists() else ""
    _xm(tmp_path / "a" / "cod_inorganics.db")
    db_mounts.mount_any(tmp_path / "a")
    after = store_cfg.read_text(encoding="utf-8") if store_cfg.exists() else ""
    assert before == after


def test_rejects_wrong_kind_when_expect_given(isolated, tmp_path):
    """显式声明类型时不做"猜": 拿错库必须报错, 而不是静默改判。"""
    cod = _db(tmp_path / "cod.sqlite", COD_DDL, COD_ROW, COD_INS)
    with pytest.raises(ValueError):
        db_mounts.add_mount(cod, kind="pdf2")


def test_detects_kind_automatically(isolated, tmp_path):
    cod = _db(tmp_path / "cod.sqlite", COD_DDL, COD_ROW, COD_INS)
    pdf = _db(tmp_path / "pdf.sqlite", PDF2_DDL, PDF2_ROW, PDF2_INS)
    assert db_mounts.add_mount(cod).kind == "cod_inorganics"
    assert db_mounts.add_mount(pdf).kind == "pdf2"


# ── 3. 当前库与卸载 ─────────────────────────────────────────

def test_set_active_and_clear(isolated, tmp_path):
    a = _xm(tmp_path / "a" / "cod_inorganics.db")
    m = db_mounts.add_mount(a)
    db_mounts.set_active(m.id)
    assert db_mounts.active_id() == m.id
    assert db_mounts.active_mount().path == a
    db_mounts.set_active("")
    assert db_mounts.active_mount() is None


def test_remove_custom_mount_keeps_file(isolated, tmp_path):
    a = _xm(tmp_path / "a" / "cod_inorganics.db")
    m = db_mounts.add_mount(a)
    db_mounts.set_active(m.id)
    db_mounts.remove_mount(m.id)
    assert a.exists()
    assert db_mounts.get_mount(m.id) is None
    assert db_mounts.active_id() == ""


def test_remove_builtin_clears_slot_config(isolated, tmp_path):
    """内置项卸载 = 清配置槽位 (与旧「取消挂载」等价)。"""
    cod = _db(tmp_path / "cod.sqlite", COD_DDL, COD_ROW, COD_INS)
    get_config().set_cod_db_path(cod)
    assert db_mounts.resolve_mount("cod_inorganics").path == cod
    db_mounts.remove_mount("cod_inorganics")
    assert get_config().user_db_path("cod_db_path") is None


def test_user_db_cannot_be_removed_here(isolated):
    """用户自建库由它自己的管理界面负责, 这里只显示不给卸载。"""
    with pytest.raises(ValueError):
        db_mounts.remove_mount("user")


# ── 4. 探测 ─────────────────────────────────────────────────

def test_probe_reports_rows_and_never_writes(isolated, tmp_path):
    a = _xm(tmp_path / "a" / "cod_inorganics.db", 4)
    m = db_mounts.add_mount(a)
    res = db_mounts.probe(m)
    assert res["ok"] and res["rows"] == 4
    # probe 不应产生任何挂载表改动
    assert [x.id for x in db_mounts.all_mounts()].count(m.id) == 1


def test_probe_missing_file(isolated, tmp_path):
    a = _xm(tmp_path / "a" / "cod_inorganics.db")
    m = db_mounts.add_mount(a)
    a.unlink()
    res = db_mounts.probe(m)
    assert res["ok"] is False and res["error"] == "missing"


def test_missing_custom_mount_resolves_to_no_path(isolated, tmp_path):
    """库被挪走后不能"按配置解析"到另一份库 —— 必须解析成不可用。"""
    a = _xm(tmp_path / "a" / "cod_inorganics.db")
    m = db_mounts.add_mount(a)
    a.unlink()
    kind, path = db_mounts.resolve_source(m.id)
    assert kind == "xinmatch" and path is None


def test_mount_any_folder_collects_all_kinds(isolated, tmp_path):
    folder = tmp_path / "data"
    _xm(folder / "cod_inorganics.db")
    _db(folder / "p.sqlite", PDF2_DDL, PDF2_ROW, PDF2_INS)
    mounted = db_mounts.mount_any(folder)
    assert {m.kind for m in mounted} == {"xinmatch", "pdf2"}


def test_mount_any_rejects_empty_folder(isolated, tmp_path):
    folder = tmp_path / "nothing"
    folder.mkdir()
    (folder / "readme.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        db_mounts.mount_any(folder)
    # 失败说明要讲清"什么才算合格库", 否则用户不知道该往目录里放什么
    assert "polyDB" in str(ei.value)
