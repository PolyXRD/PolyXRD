"""外挂数据库管理对话框测试 (offscreen)
========================================
v4.0.0 把界面从"按类型一个槽位"改成**列表式多库挂载**: 一行 = 一个已挂载的
数据库, 想挂几份挂几份, 选中某行「设为当前」就用它检索。这里钉住四条契约:

1. **一个库一行, 同类型也能挂多份** —— 用户明确要求"多个数据库挂载都可以,
   搞成列表的形式"; 两份同类型库必须能共存, 且各自可独立卸载。
2. **选中哪行就用哪行** —— 「设为当前」写进注册表, 并发出 ``databases_changed``
   让物相页下拉跟着换; 卸载当前库后不能还留着指向它的数据源。
3. **下载包 / 授权提示仍要讲清** —— 拆包后用户得知道"这行该下哪个包"; PDF2-2004
   是 ICDD 商业库, 提示必须出现在用户挂载它的地方。
4. **卸载不删库文件** —— 这只是"从列表里去掉一行"。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config   # noqa: E402
from polyxrd.i18n import tr                        # noqa: E402
from polyxrd.i18n.translations import en_US, ja_JP, zh_CN  # noqa: E402
from polyxrd.services import db_import, db_mounts  # noqa: E402
from polyxrd.views.widgets.database_dialog import (  # noqa: E402
    DatabaseManagerDialog,
)


def _resolve(tree: dict, dotted: str):
    """按点分路径取翻译值; 任一层缺失返回 None。"""
    node = tree
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """把挂载表与库槽位配置都指到临时目录 (与开发机真实挂载状态无关)。"""
    store = tmp_path / "db_mounts.json"
    monkeypatch.setattr(db_mounts, "_store_file", lambda: store)
    # 槽位配置 (user_db_paths.json) 也隔离, 免得"卸载内置库"改到真配置
    monkeypatch.setattr(AppConfig, "_user_db_paths_file",
                        lambda self: tmp_path / "user_db_paths.json")
    # 内置项一律指到不存在的路径: 列表内容完全由本用例自己挂
    empty = tmp_path / "empty"
    cfg = get_config()
    for name in ("get_cod_db_path", "get_pdf2_db_path"):
        monkeypatch.setattr(cfg, name, lambda *a, _e=empty, **k: _e / "none.sqlite")
    monkeypatch.setattr(cfg, "get_xinmatch_db_path", lambda: None)
    monkeypatch.setattr(cfg, "get_polydb_path", lambda *a, **k: None)
    monkeypatch.setattr(db_mounts, "_cod_index_path", lambda: None)
    # 消息框静音 (测试里不弹窗)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    db_mounts.clear_probe_cache()
    return store


# ── 造库 ─────────────────────────────────────────────────────

COD_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, n_peaks INTEGER,"
           " peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
COD_ROW = ("9001", "SiO2", 2, "3.34,4.26", "100,45", 4.913)
COD_INS = "INSERT INTO phases VALUES (?,?,?,?,?,?)"

PDF2_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, name TEXT,"
            " pearson TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
PDF2_ROW = ("00-046-1045", "SiO2", "Quartz", "hP9", 2, "3.34,4.26", "100,22", 4.913)
PDF2_INS = "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)"

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


def _make_db(path: Path, ddl: str, row: tuple, insert: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(ddl)
    conn.executemany(insert, [row])
    conn.commit()
    conn.close()
    return path


def _make_xinmatch_db(path: Path, rows: int = 3) -> Path:
    """最小合法 XinMatch 格式库 (挂载入口用)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    for ddl in XM_DDL:
        conn.execute(ddl)
    for i in range(rows):
        eid = f"XM-{i:03d}"
        conn.execute(
            "INSERT INTO entries (entry_id, formula, space_group, crystal_system,"
            " a, b, c, alpha, beta, gamma, elements)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "O Zn", "P 63 m c", "hexagonal", 3.2495, 3.2495, 5.2069,
             90.0, 90.0, 120.0, "O,Zn"))
        conn.execute("INSERT INTO peaks VALUES (?,?,?,?,?,?)",
                     (eid, 2.4759 + i * 0.01, 570.0, 1, 0, 1))
        conn.execute("INSERT INTO elements VALUES (?,?)", (eid, "Zn"))
        conn.execute("INSERT INTO element_combo VALUES (?,?)", (f"h{i}", eid))
    conn.commit()
    conn.close()
    return path


def _row_by_id(dlg: DatabaseManagerDialog, mount_id: str) -> dict | None:
    for r in dlg._rows:
        if r["id"] == mount_id:
            return r
    return None


# ── 1. 列表模型 ──────────────────────────────────────────────

def test_starts_empty_when_nothing_mounted(qapp, isolated):
    """一个库都没挂时列表为空 —— 不再有"四行空槽位"。"""
    dlg = DatabaseManagerDialog()
    mounted = [r for r in dlg._rows if r["ok"]]
    assert mounted == []
    assert "尚未指定" in dlg._current_lbl.text()


def test_mount_adds_one_row_per_database(qapp, isolated, tmp_path):
    """挂一个文件 = 列表里多一行, 相数/大小/状态当场刷新。"""
    db = _make_xinmatch_db(tmp_path / "elsewhere" / "deep" / "cod_inorganics.db", 7)
    dlg = DatabaseManagerDialog()
    seen: list[int] = []
    dlg.databases_changed.connect(lambda: seen.append(1))

    assert dlg.mount_path(str(db)) is True
    assert seen, "挂载成功后必须发 databases_changed (物相源下拉才会刷新)"

    row = next(r for r in dlg._rows if r["path"] == str(db))
    assert row["ok"] and row["rows"] == 7
    # 表格里能找到这一行 (表格行数 = 列表行数)
    assert dlg._table.rowCount() == len(dlg._rows)


def test_two_databases_of_same_kind_coexist(qapp, isolated, tmp_path):
    """核心新能力: 同一类型可以挂多份, 各自一行、各自独立卸载。

    这是列表式挂载相对旧"一类型一槽位"的**唯一实质增益** —— 手里既有无机
    子集又有全库时, 必须能同时挂上再按项目切换。
    """
    a = _make_xinmatch_db(tmp_path / "a" / "cod_inorganics.db", 2)
    b = _make_xinmatch_db(tmp_path / "b" / "cod_full.db", 5)
    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(a)) is True
    assert dlg.mount_path(str(b)) is True

    rows = [r for r in dlg._rows if r["kind"] == "xinmatch" and r["ok"]]
    assert len(rows) == 2, [r["id"] for r in rows]
    assert {r["path"] for r in rows} == {str(a), str(b)}
    assert len({r["id"] for r in rows}) == 2, "两份库必须是两个不同的数据源 id"

    # 卸载其中一份, 另一份必须还在
    dlg._table.selectRow(next(i for i, r in enumerate(dlg._rows) if r["path"] == str(a)))
    dlg._on_unmount()
    left = [r for r in dlg._rows if r["kind"] == "xinmatch" and r["ok"]]
    assert [r["path"] for r in left] == [str(b)]
    assert a.exists(), "卸载只应去掉挂载记录, 不能删库文件"


def test_each_row_shows_its_own_package(qapp, isolated, tmp_path):
    """详情区要写明该行对应哪个下载包 / 解压出哪个文件。

    拆包后这行提示是关键 UX: 用户面对一列库只能靠它知道该下哪个包。
    而 PDF2-2004 受 ICDD 版权限制永不随 Release 发布 —— 绝不能提示下载。
    """
    cod = _make_db(tmp_path / "c.sqlite", COD_DDL, COD_ROW, COD_INS)
    pdf = _make_db(tmp_path / "p.sqlite", PDF2_DDL, PDF2_ROW, PDF2_INS)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(cod))
    dlg.mount_path(str(pdf))

    cod_row = next(r for r in dlg._rows if r["kind"] == "cod_inorganics")
    pdf_row = next(r for r in dlg._rows if r["kind"] == "pdf2")
    cod_pkg = dlg._pkg_hint(cod_row)
    pdf_pkg = dlg._pkg_hint(pdf_row)

    assert "Databases-COD-inorg-index.zip" in cod_pkg
    assert "COD_inorganics_index.sqlite" in cod_pkg
    assert "Databases-PDF2.zip" not in pdf_pkg, "PDF2 不得提示下载 —— 该库不上传 Release"
    assert "PDF2_2004.sqlite" in pdf_pkg
    assert cod_pkg != pdf_pkg, "各行文案不能雷同, 否则用户看不出区别"


def test_unmount_keeps_file_and_clears_active(qapp, isolated, tmp_path):
    """卸载当前库后: 文件仍在, 「当前」回退为未指定。"""
    db = _make_xinmatch_db(tmp_path / "x" / "cod_inorganics.db", 3)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))

    dlg._table.selectRow(next(i for i, r in enumerate(dlg._rows) if r["id"] == mid))
    dlg._on_set_active()
    assert db_mounts.active_id() == mid

    dlg._on_unmount()
    assert db.exists()
    assert db_mounts.active_id() == ""
    assert _row_by_id(dlg, mid) is None


# ── 2. 选中即检索源 ──────────────────────────────────────────

def test_set_active_marks_row_and_emits(qapp, isolated, tmp_path):
    """「设为当前」= 写注册表 + 行首打标记 + 通知物相页刷新。"""
    db = _make_xinmatch_db(tmp_path / "x" / "cod_inorganics.db", 3)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))

    seen: list[int] = []
    dlg.databases_changed.connect(lambda: seen.append(1))
    dlg._table.selectRow(next(i for i, r in enumerate(dlg._rows) if r["id"] == mid))
    dlg._on_set_active()

    assert seen, "换数据源后必须通知物相页 (否则下拉还指着旧库)"
    assert db_mounts.active_id() == mid
    # 行首列出现"使用中"标记, 且页脚点名当前库
    row_idx = next(i for i, r in enumerate(dlg._rows) if r["id"] == mid)
    assert dlg._table.item(row_idx, 0).text() == tr("db_manager.active_mark")
    assert "cod_inorganics.db" in dlg._current_lbl.text()


def test_cannot_set_active_for_unavailable_db(qapp, isolated, tmp_path):
    """库文件被挪走的那一行不能设为当前 (否则检索只会得到空结果)。"""
    db = _make_xinmatch_db(tmp_path / "x" / "cod_inorganics.db", 3)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))
    db.unlink()                      # 挂完就把文件挪走
    dlg.reload()

    row = _row_by_id(dlg, mid)
    assert row is not None and not row["ok"]
    dlg._table.selectRow(next(i for i, r in enumerate(dlg._rows) if r["id"] == mid))
    dlg._on_set_active()
    assert db_mounts.active_id() == "", "不可用的库不能被设为检索数据源"


# ── 3. 自动判别与失败提示 ────────────────────────────────────

def test_mount_folder_picks_up_every_kind(qapp, isolated, tmp_path):
    """指到文件夹时, 该目录下不同类的库要一次全挂上。"""
    folder = tmp_path / "data"
    _make_xinmatch_db(folder / "cod_inorganics.db")
    _make_db(folder / "c.sqlite", COD_DDL, COD_ROW, COD_INS)

    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(folder)) is True
    kinds = {r["kind"] for r in dlg._rows if r["ok"]}
    assert {"xinmatch", "cod_inorganics"} <= kinds


def test_mount_reports_failure_without_touching_list(qapp, isolated, tmp_path, monkeypatch):
    """不合格的路径要弹提示, 且列表里什么都不该多出来。"""
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a[2]) or None)
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a db")

    dlg = DatabaseManagerDialog()
    before = len(dlg._rows)
    assert dlg.mount_path(str(junk)) is False
    assert shown, "失败时必须提示原因"
    assert len(dlg._rows) == before


def test_backup_files_are_ignored(qapp, isolated, tmp_path):
    """目录里的 .bak 备份不能被当成库挂上 (XinMatch data 目录常年有备份)。"""
    folder = tmp_path / "data"
    good = _make_xinmatch_db(folder / "cod_inorganics.db", 2)
    _make_xinmatch_db(folder / "cod_inorganics.bak-20261011.db", 9)

    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(folder))
    paths = [r["path"] for r in dlg._rows if r["ok"]]
    assert str(good) in paths
    assert not any(".bak" in p for p in paths), paths


# ── 4. 商业库授权提示 ────────────────────────────────────────

def test_licence_notice_only_on_non_free_db(qapp, isolated):
    """只有"数据本身要用户自己负责授权"的库带提示。"""
    kinds_with_notice = {k.key for k in db_import.DB_KINDS if k.notice_key}
    assert kinds_with_notice == {"pdf2", "xinmatch"}


def test_pdf2_notice_shown_when_selected(qapp, isolated, tmp_path):
    """选中 PDF2 行才显示授权提示; 选中开放库时不该出现。"""
    pdf = _make_db(tmp_path / "p.sqlite", PDF2_DDL, PDF2_ROW, PDF2_INS)
    cod = _make_db(tmp_path / "c.sqlite", COD_DDL, COD_ROW, COD_INS)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(pdf))
    dlg.mount_path(str(cod))

    pdf_idx = next(i for i, r in enumerate(dlg._rows) if r["kind"] == "pdf2")
    dlg._table.selectRow(pdf_idx)
    assert dlg._detail_notice.isVisibleTo(dlg) or dlg._detail_notice.text()
    assert "正版授权" in dlg._detail_notice.text()

    cod_idx = next(i for i, r in enumerate(dlg._rows) if r["kind"] == "cod_inorganics")
    dlg._table.selectRow(cod_idx)
    assert dlg._detail_notice.text() == ""


def test_notice_keys_resolve_in_all_languages(qapp, isolated):
    """notice_key 拼错会**静默退化成原始键名**显示给用户, 所以三语都得查得到。"""
    for kind in db_import.DB_KINDS:
        if not kind.notice_key:
            continue
        for mod in (zh_CN, en_US, ja_JP):
            assert _resolve(mod.translations, kind.notice_key), (
                f"{kind.key}: {kind.notice_key} 在 {mod.__name__} 中缺失"
            )


def test_new_keys_resolve_in_all_languages(qapp, isolated):
    """v4.0.0 新增的列表 / 详情文案三语齐全 (缺键会直接显示成键名)。"""
    keys = [
        "db_manager.list_intro", "db_manager.col_name", "db_manager.col_status",
        "db_manager.btn_mount_file", "db_manager.btn_set_active",
        "db_manager.btn_unmount", "db_manager.current_source",
        "db_manager.current_source_none", "db_manager.set_active_unavailable",
        "db_mounts.kind.polydb_inorg", "db_mounts.kind.polydb_full",
        "db_mounts.type.polydb", "db_mounts.pkg_free",
    ]
    for mod in (zh_CN, en_US, ja_JP):
        for k in keys:
            assert _resolve(mod.translations, k), f"{k} 在 {mod.__name__} 中缺失"
