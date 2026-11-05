"""外挂数据库管理对话框测试 (offscreen, v5.2)
==============================================

界面是**列表式多库挂载**: 一行 = 一个已挂载的数据库, 想挂几份挂几份, 选中
某行「设为当前」就用它检索。v5.2 之后可挂的只有两类:

* ``polydb`` —— 目录容器 (有 ``meta.json`` + ``index.sqlite``), **默认参考库**;
  COD-Inorg / COD-Full / PDF2-2004 都是它的**变体**, 同一套 reader 与打分;
* ``user``   —— 用户自建库 (由「导入 CIF」维护)。

PDF2-2004 不再是独立的 ``pdf2`` 类型: 旧 sqlite 通道 (``db_import`` /
``PDF2Database``) 已随旧格式一并删除, 现在它是一份 ``variant="pdf2-2004"``
的 polyDB。**版权提示改按变体判** —— 类型合并了, 但"这份数据要用户自己负责
授权"这条合规要求没变。

本文件钉住四条契约:

1. **一个库一行, 同类型也能挂多份** —— 两份 polyDB (无机库 + 全库) 必须能共存,
   且各自可独立卸载;
2. **选中哪行就用哪行** —— 「设为当前」写进注册表, 并发出 ``databases_changed``
   让物相页下拉跟着换; 不可用的库不能设为当前;
3. **下载包 / 授权提示要讲清** —— COD 类 polyDB 指明随 PolyXRD-DataBase 仓库
   发布; PDF2-2004 是 ICDD 商业库, 提示必须出现在用户挂载它的地方且**不得**
   提示下载;
4. **卸载不删库文件** —— 这只是"从列表里去掉一行"; 旧格式 sqlite 库不再能挂。
"""
from __future__ import annotations

import json
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
from polyxrd.services import db_mounts  # noqa: E402
from polyxrd.views.widgets import database_dialog  # noqa: E402
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
    monkeypatch.setattr(cfg, "get_polydb_path", lambda *a, **k: None)
    monkeypatch.setattr(db_mounts, "_probe_user",
                        lambda p: {"ok": False, "rows": 0, "error": "user_db_empty"})

    # polyDB 的相数改从 meta.json 读: 本文件测的是**对话框契约**, 不该被
    # 读取器能否 mmap 8 个段牵制 (真实容器由 test_db_mounts / polydb 单测覆盖)。
    def _fake_probe_polydb(p):
        meta_file = Path(p) / "meta.json"
        if not meta_file.is_file():
            return {"ok": False, "rows": 0, "error": "polydb_not_ready",
                    "detail": str(p)}
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
        build = raw.get("build")
        built = ""
        if isinstance(build, dict):
            built = str(build.get("date") or build.get("started_at") or "")
        elif build:
            built = str(build)
        built = built or str(raw.get("built") or "")
        try:
            schema = int(raw.get("schema_version") or 0)
        except (TypeError, ValueError):
            schema = 0
        # v4.6: 真 probe 还会带归一化的 polyDB 元数据 (meta/dataset/built/
        # schema_version, 见 db_mounts._read_polydb_meta)。这里按同一契约伪造,
        # 让对话框元数据行的用例不被"读取器能不能开库"牵制。
        meta = {
            "format": str(raw.get("format") or ""),
            "schema_version": schema,
            "variant": str(raw.get("variant") or ""),
            "dataset": str(raw.get("name") or raw.get("dataset") or ""),
            "built": built,
            "counts": raw.get("counts") or {},
        }
        return {"ok": True, "rows": int((meta.get("counts") or {}).get("phases", 0)),
                "size_mb": 1.0, "detail": f"variant={meta.get('variant', '?')}",
                "meta": meta,
                "dataset": meta["dataset"],
                "built": meta["built"],
                "schema_version": meta["schema_version"]}

    monkeypatch.setattr(db_mounts, "_probe_polydb", _fake_probe_polydb)
    # 消息框静音 (测试里不弹窗)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    # critical 也要静音: 它在 offscreen 下是**模态**的, 一旦某条异常路径
    # 走到这里, 测试会卡死在 exec() 里而不是红掉 —— 这比失败更难查。
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    db_mounts.clear_probe_cache()
    return store


# ── 造库 ─────────────────────────────────────────────────────

#: v4.1.0 之前那套 COD 无机物库的 DDL（**故意保留**: 用来证明旧格式被拒）
OLD_COD_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, n_peaks INTEGER,"
               " peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
OLD_COD_ROW = ("9001", "SiO2", 2, "3.34,4.26", "100,45", 4.913)
OLD_COD_INS = "INSERT INTO phases VALUES (?,?,?,?,?,?)"


def _make_db(path: Path, ddl: str, row: tuple, insert: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(ddl)
    conn.executemany(insert, [row])
    conn.commit()
    conn.close()
    return path


def _make_polydb(root: Path, name: str, variant: str = "cod-inorg",
                 phases: int = 100) -> Path:
    """最小"看起来合法"的 polyDB 目录 (探测只读 meta.json, 不开库)。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({
        "format": "polyDB", "schema_version": 1, "variant": variant,
        "counts": {"phases": phases, "k": 100, "peaks": 1000, "sites": 500},
    }), encoding="utf-8")
    (d / "index.sqlite").write_bytes(b"")
    return d


def _make_pdf2_polydb(root: Path, phases: int = 163834) -> Path:
    """PDF2-2004 的 polyDB 变体 (v5.2 起 PDF2 就是这个形态, 不再是独立 sqlite)。"""
    return _make_polydb(root, "PDF2-2004.polyDB", variant="pdf2-2004",
                        phases=phases)


def _set_polydb_meta(path: Path, **fields) -> None:
    """改写 polyDB 的 meta.json (给元数据行用例造数据集名/构建日期)。"""
    f = path / "meta.json"
    meta = json.loads(f.read_text(encoding="utf-8"))
    meta.update(fields)
    f.write_text(json.dumps(meta), encoding="utf-8")


def _row_by_id(dlg: DatabaseManagerDialog, mount_id: str) -> dict | None:
    for r in dlg._rows:
        if r["id"] == mount_id:
            return r
    return None


def _select(dlg: DatabaseManagerDialog, mount_id: str) -> None:
    dlg._table.selectRow(next(i for i, r in enumerate(dlg._rows) if r["id"] == mount_id))


# ── 1. 列表模型 ──────────────────────────────────────────────

def test_starts_empty_when_nothing_mounted(qapp, isolated):
    """一个库都没挂时列表为空 —— 但两个 polyDB 内置行仍在 (未挂载态)。"""
    dlg = DatabaseManagerDialog()
    assert [r for r in dlg._rows if r["ok"]] == []
    assert "尚未指定" in dlg._current_lbl.text()


def test_mount_adds_one_row_per_database(qapp, isolated, tmp_path):
    """挂一个 polyDB 目录 = 列表里多一行, 状态当场刷新。"""
    db = _make_polydb(tmp_path / "elsewhere" / "deep", "Mine.polyDB", phases=7)
    dlg = DatabaseManagerDialog()
    seen: list[int] = []
    dlg.databases_changed.connect(lambda: seen.append(1))

    assert dlg.mount_path(str(db)) is True
    assert seen, "挂载成功后必须发 databases_changed (物相源下拉才会刷新)"

    row = next(r for r in dlg._rows if r["path"] == str(db))
    assert row["kind"] == "polydb" and row["rows"] == 7
    assert dlg._table.rowCount() == len(dlg._rows)


def test_two_databases_of_same_kind_coexist(qapp, isolated, tmp_path):
    """核心能力: 同类型可挂多份 (无机库 + 全库), 各自一行、各自独立卸载。"""
    a = _make_polydb(tmp_path / "a", "COD-Inorg-Mine.polyDB", phases=2)
    b = _make_polydb(tmp_path / "b", "COD-Full-Mine.polyDB",
                     variant="cod-full", phases=5)
    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(a)) is True
    assert dlg.mount_path(str(b)) is True

    rows = [r for r in dlg._rows if r["kind"] == "polydb" and r["ok"]]
    assert len(rows) == 2, [r["id"] for r in rows]
    assert {r["path"] for r in rows} == {str(a), str(b)}
    assert len({r["id"] for r in rows}) == 2, "两份库必须是两个不同的数据源 id"

    _select(dlg, next(r["id"] for r in rows if r["path"] == str(a)))
    dlg._on_unmount()
    left = [r for r in dlg._rows if r["kind"] == "polydb" and r["ok"]]
    assert [r["path"] for r in left] == [str(b)]
    assert a.exists(), "卸载只应去掉挂载记录, 不能删库文件"


def test_each_row_shows_its_own_package(qapp, isolated, tmp_path):
    """详情区写明该行对应哪个下载包 / 解压出什么。

    v4.1.1 政策: 数据库由独立仓库 PolyXRD-DataBase 发布 (主仓库 Release 只发程序),
    COD 类 polyDB 行必须指到该仓库 Releases; PDF2-2004 受 ICDD 版权限制,
    永不随任何包发布 —— 即便它现在也是 polyDB 变体, 提示文案仍要分开。
    """
    poly = _make_polydb(tmp_path, "COD-Inorg-Mine.polyDB")
    pdf = _make_pdf2_polydb(tmp_path)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(poly))
    dlg.mount_path(str(pdf))

    poly_row = next(r for r in dlg._rows
                    if r["kind"] == "polydb" and r["ok"]
                    and r.get("variant") != "pdf2-2004")
    pdf_row = next(r for r in dlg._rows
                   if r.get("variant") == "pdf2-2004" and r["ok"])
    poly_pkg = dlg._pkg_hint(poly_row)
    pdf_pkg = dlg._pkg_hint(pdf_row)

    assert "PolyXRD-DataBase" in poly_pkg
    assert "releases" in poly_pkg.lower()
    assert ".zip" not in poly_pkg, "数据库包不再从主仓库下载, 不应给 zip 文件名"
    assert ".zip" not in pdf_pkg, "PDF2 不得提示下载 —— 该库不上传 Release"
    assert "PDF2-2004.polyDB" in pdf_pkg
    assert poly_pkg != pdf_pkg, "各行文案不能雷同, 否则用户看不出区别"


def test_unmount_keeps_file_and_clears_active(qapp, isolated, tmp_path):
    """卸载当前库后: 文件仍在, 「当前」回退为未指定。"""
    db = _make_polydb(tmp_path / "x", "Mine.polyDB")
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))

    _select(dlg, mid)
    dlg._on_set_active()
    assert db_mounts.active_id() == mid

    dlg._on_unmount()
    assert db.exists()
    assert db_mounts.active_id() == ""
    assert _row_by_id(dlg, mid) is None


# ── 2. 选中即检索源 ──────────────────────────────────────────

def test_set_active_marks_row_and_emits(qapp, isolated, tmp_path):
    """「设为当前」= 写注册表 + 行首打标记 + 通知物相页刷新。"""
    db = _make_polydb(tmp_path / "x", "Mine.polyDB")
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))

    seen: list[int] = []
    dlg.databases_changed.connect(lambda: seen.append(1))
    _select(dlg, mid)
    dlg._on_set_active()

    assert seen, "换数据源后必须通知物相页 (否则下拉还指着旧库)"
    assert db_mounts.active_id() == mid
    row_idx = next(i for i, r in enumerate(dlg._rows) if r["id"] == mid)
    assert dlg._table.item(row_idx, 0).text() == tr("db_manager.active_mark")
    assert "Mine.polyDB" in dlg._current_lbl.text()


def test_cannot_set_active_for_unavailable_db(qapp, isolated, tmp_path):
    """库文件被挪走的那一行不能设为当前 (否则检索只会得到空结果)。"""
    db = _make_polydb(tmp_path / "x", "Mine.polyDB")
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))
    (db / "meta.json").unlink()       # 挂完就把它弄成残目录
    dlg.reload()

    row = _row_by_id(dlg, mid)
    assert row is not None and not row["ok"]
    _select(dlg, mid)
    dlg._on_set_active()
    assert db_mounts.active_id() == "", "不可用的库不能被设为检索数据源"


# ── 3. 自动判别与失败提示 ────────────────────────────────────

def test_mount_folder_picks_up_every_variant(qapp, isolated, tmp_path):
    """指到文件夹时, 该目录下各变体的 polyDB 要一次全挂上。

    v5.2 起"不同类"就是 polyDB 的不同变体: COD 无机库 + PDF2-2004 都要进列表,
    且各自带自己的变体/文案 (不能因为共用 kind 就合并成一项)。
    """
    folder = tmp_path / "data"
    _make_polydb(folder, "COD-Inorg-Mine.polyDB")
    _make_pdf2_polydb(folder)

    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(folder)) is True
    variants = {r.get("variant") for r in dlg._rows if r["ok"]}
    assert {"cod-inorg", "pdf2-2004"} <= variants


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


def test_old_cod_sqlite_cannot_be_mounted(qapp, isolated, tmp_path, monkeypatch):
    """旧格式 sqlite 库 (无论 COD 还是 PDF2) 一律拒绝, 并给出迁移指引。

    v5.2 删掉了 sqlite 物相库通道: 只认 polyDB 目录。用户手里还留着老库时,
    光说"挂不上"会让他以为程序坏了 —— 提示必须指向"改用 polyDB 目录"。
    """
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a[2]) or None)
    old = _make_db(tmp_path / "old.sqlite", OLD_COD_DDL, OLD_COD_ROW, OLD_COD_INS)

    dlg = DatabaseManagerDialog()
    before = len(dlg._rows)
    assert dlg.mount_path(str(old)) is False
    assert shown
    assert len(dlg._rows) == before
    assert all(r["kind"] != "pdf2" for r in dlg._rows), "旧 pdf2 类型不该复活"


def test_old_sqlite_in_folder_is_skipped_with_reason(qapp, isolated, tmp_path,
                                                     monkeypatch):
    """混合文件夹: polyDB 照挂, 同目录的旧 sqlite 被跳过但要说明原因。"""
    folder = tmp_path / "data"
    good = _make_polydb(folder, "COD-Inorg-Mine.polyDB")
    _make_db(folder / "PDF2_2004.sqlite", OLD_COD_DDL, OLD_COD_ROW, OLD_COD_INS)

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a[2]) or None)
    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(folder)) is True
    paths = [r["path"] for r in dlg._rows if r["ok"]]
    assert str(good) in paths
    assert not any(p.endswith(".sqlite") for p in paths)
    assert shown and "polyDB" in shown[0], "跳过的旧库必须说明为什么"


def test_backup_dirs_are_ignored(qapp, isolated, tmp_path):
    """目录里的备份不能被当成库挂上 (与 sqlite 时代同一口径)。

    备份目录同样带 meta.json + index.sqlite, 单看内容分辨不出来 —— 挂上了
    用户会在数据源下拉里看到两个同名库, 分不清哪份是备份。
    """
    folder = tmp_path / "data"
    good = _make_polydb(folder, "Good.polyDB")
    for name in ("Good.polyDB.bak", "Good~.polyDB", "Good.polyDB.tmp"):
        _make_polydb(folder, name)

    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(folder)) is True
    paths = [r["path"] for r in dlg._rows if r["ok"]]
    assert str(good) in paths
    assert not any(".bak" in p for p in paths), paths
    assert not any("~" in p for p in paths), paths
    assert not any(p.endswith(".tmp") for p in paths), paths


# ── 4. 商业库授权提示 ────────────────────────────────────────

def test_licence_notice_only_on_pdf2_variant(qapp, isolated, tmp_path):
    """只有 PDF2-2004 变体带授权提示 —— v5.2 合并了 kind, 提示改按变体判。

    这是合规要求: 若跟着旧 kind 一起消失, 商业库就会在界面上"看起来可以被
    随便分发"。所以这里钉住"COD 变体没有提示 / PDF2 变体有提示"。
    """
    cod = _make_polydb(tmp_path, "COD-Inorg-Mine.polyDB")
    pdf = _make_pdf2_polydb(tmp_path)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(cod))
    dlg.mount_path(str(pdf))

    notices = {r.get("variant"): dlg._notice_of(r) for r in dlg._rows
               if r.get("variant")}
    assert notices["pdf2-2004"], "PDF2-2004 必须带授权提示"
    assert not notices.get("cod-inorg"), "COD 库不该出现商业授权提示"


def test_pdf2_notice_shown_when_selected(qapp, isolated, tmp_path):
    """选中 PDF2 行才显示授权提示; 选中 COD polyDB 时不该出现。"""
    pdf = _make_pdf2_polydb(tmp_path)
    poly = _make_polydb(tmp_path, "COD-Inorg-Mine.polyDB")
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(pdf))
    dlg.mount_path(str(poly))

    pdf_idx = next(i for i, r in enumerate(dlg._rows)
                   if r.get("variant") == "pdf2-2004")
    dlg._table.selectRow(pdf_idx)
    assert "正版授权" in dlg._detail_notice.text()

    poly_idx = next(i for i, r in enumerate(dlg._rows)
                    if r["kind"] == "polydb" and r["ok"]
                    and r.get("variant") != "pdf2-2004")
    dlg._table.selectRow(poly_idx)
    assert dlg._detail_notice.text() == ""


def test_notice_keys_resolve_in_all_languages(qapp, isolated):
    """提示文案键拼错会**静默退化成原始键名**显示给用户, 所以三语都得查得到。"""
    for mod in (zh_CN, en_US, ja_JP):
        assert _resolve(mod.translations, "db_manager.notice.pdf2"), (
            f"db_manager.notice.pdf2 在 {mod.__name__} 中缺失"
        )


# ── 5. 多库规模 / 元数据 / 重命名 ─────────────────────────────

def test_polydb_type_column_shows_variant(qapp, isolated, tmp_path):
    """类型列带变体: 同类型挂多份时, 光写 "polyDB 库" 分不清是哪一份。"""
    db = _make_polydb(tmp_path, "Mine.polyDB", variant="cod-full")
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    idx = next(i for i, r in enumerate(dlg._rows) if r["path"] == str(db))
    assert dlg._table.item(idx, 2).text() == tr(
        "db_manager.type_variant", variant="cod-full")

    # v5.2: PDF2-2004 也是 polyDB 变体 → 同样走 "polyDB · pdf2-2004" 文案,
    # 不再有独立的 "PDF2-2004 库" 类型名。
    pdf = _make_pdf2_polydb(tmp_path)
    dlg.mount_path(str(pdf))
    pdf_idx = next(i for i, r in enumerate(dlg._rows)
                   if r.get("variant") == "pdf2-2004" and r["path"] == str(pdf))
    assert dlg._table.item(pdf_idx, 2).text() == tr(
        "db_manager.type_variant", variant="pdf2-2004")


def test_detail_meta_line_shows_polydb_metadata(qapp, isolated, tmp_path):
    """详情区要讲清这份 polyDB 的数据集 / 变体 / 格式版本 / 构建日期。"""
    db = _make_polydb(tmp_path, "Mine.polyDB", variant="cod-inorg")
    _set_polydb_meta(db, name="COD-Inorg 2026.10",
                     build={"date": "2026-10-21"}, schema_version=2)
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))
    _select(dlg, mid)

    text = dlg._detail_meta.text()
    assert "COD-Inorg 2026.10" in text
    assert tr("db_manager.meta_line", variant="cod-inorg", schema="2",
              built="2026-10-21") in text
    assert not dlg._detail_meta.isHidden(), "有元数据时这一行必须显示"

    # 没有库位置的行 (内置项未挂载 / 用户库未建) 取不到 meta: 整行隐藏,
    # 不能留下空占位。v5.2 起所有能挂的库都是 polyDB, "非 polyDB" 只剩这些。
    _select(dlg, "user")
    assert dlg._detail_meta.isHidden()


def test_rename_custom_mount_persists_and_emits(qapp, isolated, tmp_path,
                                                monkeypatch):
    """自加库可以重命名: 立即刷新列表 + 落盘 + 通知下游刷新数据源。"""
    db = _make_polydb(tmp_path, "Mine.polyDB")
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))
    _select(dlg, mid)
    assert dlg._btn_rename.isEnabled(), "用户自加项应当可以重命名"

    monkeypatch.setattr(database_dialog.QInputDialog, "getText",
                        lambda *a, **k: ("My Library", True))
    seen: list[int] = []
    dlg.databases_changed.connect(lambda: seen.append(1))
    dlg._on_rename()

    assert seen, "改名后要通知物相页刷新数据源下拉"
    assert db_mounts.get_mount(mid).label == "My Library"
    persisted = json.loads(isolated.read_text(encoding="utf-8"))
    rec = next(m for m in persisted["mounts"] if m["id"] == mid)
    assert rec["label"] == "My Library", "改名必须落盘, 重开对话框还在"
    row = _row_by_id(dlg, mid)
    assert row is not None and "My Library" in dlg._display_name(row)


def test_rename_disabled_for_builtin_mount(qapp, isolated):
    """内置项的显示名由类型/变体决定, 不允许改名。"""
    dlg = DatabaseManagerDialog()
    idx = next(i for i, r in enumerate(dlg._rows) if r["builtin"])
    dlg._table.selectRow(idx)
    assert not dlg._btn_rename.isEnabled()


def test_rename_rejects_empty_name(qapp, isolated, tmp_path, monkeypatch):
    """输入框留空 = 手滑, 拒绝并提示; 不能静默恢复默认名或写成空串。"""
    db = _make_polydb(tmp_path, "Mine.polyDB")
    dlg = DatabaseManagerDialog()
    dlg.mount_path(str(db))
    mid = next(r["id"] for r in dlg._rows if r["path"] == str(db))
    _select(dlg, mid)
    monkeypatch.setattr(database_dialog.QInputDialog, "getText",
                        lambda *a, **k: ("   ", True))
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a[2]) or None)
    dlg._on_rename()
    assert warnings and tr("db_manager.rename_empty") in warnings[0]
    assert db_mounts.get_mount(mid).label == "Mine.polyDB"


def test_thirty_mounts_one_row_each_and_footer_counts(qapp, isolated, tmp_path):
    """挂 30 份库: 一行一份不合并, footer 讲清"挂了几份 / 用哪份"。"""
    folder = tmp_path / "many"
    for i in range(30):
        _make_polydb(folder, f"db-{i:02d}.polyDB", phases=i + 1)
    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(folder)) is True

    usable = [r for r in dlg._rows if r.get("kind") == "polydb" and r["ok"]]
    assert len(usable) == 30
    assert len({r["id"] for r in usable}) == 30, "每份库必须有自己的数据源 id"
    assert dlg._table.rowCount() == len(dlg._rows)
    assert tr("db_manager.mounted_count", n=30, active="—") in dlg._current_lbl.text()


def test_new_keys_resolve_in_all_languages(qapp, isolated):
    """列表 / 详情 / 包提示文案三语齐全 (缺键会直接显示成键名)。"""
    keys = [
        "db_manager.list_intro", "db_manager.col_name", "db_manager.col_status",
        "db_manager.btn_mount_file", "db_manager.btn_set_active",
        "db_manager.btn_unmount", "db_manager.current_source",
        "db_manager.current_source_none", "db_manager.set_active_unavailable",
        "db_manager.pkg_hint", "db_manager.pkg_hint_local",
        "db_mounts.kind.polydb_inorg", "db_mounts.kind.polydb_full",
        "db_mounts.type.polydb", "db_mounts.pkg_free",
        "status.internal_tooltip",
        # v5.2: PDF2-2004 并入 polyDB 后, 版权提示按**变体**判
        "db_manager.notice.pdf2", "db_manager.kind.pdf2",
        # v4.6 多库体验 / 重命名 / 元数据 / 物相页接线用的新键
        "db_manager.btn_rename", "db_manager.rename_title",
        "db_manager.rename_empty", "db_manager.rename_done",
        "db_manager.meta_line", "db_manager.type_variant",
        "db_manager.mounted_count",
        "vw.phase_view.btn_manage_db", "vw.phase_view.tip_manage_db",
        "vw.phase_view.db_profile_external", "error.db_unusable",
    ]
    for mod in (zh_CN, en_US, ja_JP):
        for k in keys:
            assert _resolve(mod.translations, k), f"{k} 在 {mod.__name__} 中缺失"
