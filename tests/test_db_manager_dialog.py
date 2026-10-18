"""外挂数据库管理对话框测试 (offscreen)
========================================
钉住 0.10.0 拆包后的两条 UI 契约:

1. **三个槽位可独立挂载** —— 每一行有自己的「导入…/取消挂载」, 挂 A 不影响 B,
   取消 A 也不影响 B。用户明确要求"gui上挂载也可以单独挂载", 这里守住它。
2. **每个槽位写清对应哪个下载包** —— 拆成三个 zip 之后, 用户必须能从对话框直接
   看出"这一行该下哪个包、解压出哪个文件", 否则只能靠猜。
3. **商业库必须带授权提示** —— PDF2-2004 是 ICDD 的商业数据库, 提示要摆在
   「导入…」按钮旁边 (用户是在这里点的导入), 且 COD 这类开放库不该被误加。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config      # noqa: E402
from polyxrd.i18n import tr                            # noqa: E402
from polyxrd.i18n.translations import en_US, ja_JP, zh_CN  # noqa: E402
from polyxrd.services import db_import                # noqa: E402
from polyxrd.views.widgets.database_dialog import DatabaseManagerDialog  # noqa: E402


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
def tmp_cfg(tmp_path, monkeypatch):
    target = tmp_path / "user_db_paths.json"
    monkeypatch.setattr(AppConfig, "_user_db_paths_file", lambda self: target)
    # 默认位置也指到空目录, 让三个槽位都处于"未挂载"的可控状态
    empty = tmp_path / "empty"
    cfg = get_config()
    monkeypatch.setattr(cfg, "_resolve_db_path",
                        lambda key, default, alts: empty / f"{key}.sqlite")
    return target


def _make_db(path: Path, ddl: str, row: tuple, insert: str) -> Path:
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute(ddl)
    conn.executemany(insert, [row])
    conn.commit()
    conn.close()
    return path


COD_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, n_peaks INTEGER,"
           " peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
COD_ROW = ("9001", "SiO2", 2, "3.34,4.26", "100,45", 4.913)
COD_INS = "INSERT INTO phases VALUES (?,?,?,?,?,?)"

PDF2_DDL = ("CREATE TABLE phases (cod_id TEXT, formula TEXT, name TEXT,"
            " pearson TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT, cell_a REAL)")
PDF2_ROW = ("00-046-1045", "SiO2", "Quartz", "hP9", 2, "3.34,4.26", "100,22", 4.913)
PDF2_INS = "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)"


def test_every_kind_has_a_row(qapp, tmp_cfg):
    """每种库一行 (3.1.0 起多了 XinMatch 格式库)。"""
    dlg = DatabaseManagerDialog()
    assert set(dlg._rows) == {k.key for k in db_import.DB_KINDS}
    assert "xinmatch" in dlg._rows


def test_each_row_shows_its_own_package(qapp, tmp_cfg):
    """能下载的槽位要写明下载包与解压文件名; PDF2 必须写明"不提供下载"。

    拆包后这行提示是关键 UX: 用户面对三个槽位只能靠它知道该下哪个包。
    而 PDF2-2004 受 ICDD 版权限制永不随 Release 发布 —— 行里绝不能出现
    `Databases-PDF2.zip`, 否则用户去 Release 找一个不存在的文件。
    """
    dlg = DatabaseManagerDialog()
    texts = {k: r["pkg"].text() for k, r in dlg._rows.items()}

    # v0.14.0: 无机物库发布包改发瘦身索引式
    assert "Databases-COD-inorg-index.zip" in texts["cod_inorganics"]
    assert "COD_inorganics_index.sqlite" in texts["cod_inorganics"]
    assert "Databases-COD-full-index.zip" in texts["cod_index"]
    assert "cod_index.sqlite" in texts["cod_index"]

    assert "Databases-PDF2.zip" not in texts["pdf2"], (
        "PDF2 不得提示下载 —— 该库不上传 Release"
    )
    # 仍需告诉用户"这个槽位要的是哪个文件"
    assert "PDF2_2004.sqlite" in texts["pdf2"]

    # v3.1.0: XinMatch 格式库同样不随本项目发布, 且要写清该去对方那找哪个文件
    assert "cod_inorganics.db" in texts["xinmatch"]
    assert "cod_full.db" in texts["xinmatch"]
    assert "Databases-" not in texts["xinmatch"]

    # 各行文案不能雷同 (否则用户看不出区别)
    assert len(set(texts.values())) == len(texts)


def test_mounting_one_slot_leaves_others_untouched(qapp, tmp_cfg, tmp_path, monkeypatch):
    """核心契约: 只挂 COD 无机物库, 另外两个槽位必须仍是未挂载。"""
    codes = _make_db(tmp_path / "c.sqlite", COD_DDL, COD_ROW, COD_INS)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = DatabaseManagerDialog()
    monkeypatch.setattr(dlg, "_pick_file", lambda kind: str(codes), raising=False)

    dlg._import_path("cod_inorganics", str(codes))

    assert db_import.is_user_imported("cod_inorganics") is True
    assert db_import.is_user_imported("pdf2") is False
    assert db_import.is_user_imported("cod_index") is False
    # 取消挂载也必须是单槽位的
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg._on_clear("cod_inorganics")
    assert db_import.is_user_imported("cod_inorganics") is False


def test_importing_two_kinds_stays_independent(qapp, tmp_cfg, tmp_path, monkeypatch):
    """挂两个不同库, 两个槽位各自生效且互不覆盖。

    这里断言 `is_user_imported` 与落盘的 json, 而**不**用 `get_*_db_path()` ——
    本用例的 fixture 把 `_resolve_db_path` 换成了空目录实现 (模拟"三个库都不在
    默认位置"), 而用户导入路径正是由那个函数读取的, 用 `get_*_db_path()` 会
    把这个 fixture 自身的桩当成被测行为。
    """
    import json

    cod = _make_db(tmp_path / "c.sqlite", COD_DDL, COD_ROW, COD_INS)
    pdf = _make_db(tmp_path / "p.sqlite", PDF2_DDL, PDF2_ROW, PDF2_INS)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    dlg = DatabaseManagerDialog()
    dlg._import_path("cod_inorganics", str(cod))
    dlg._import_path("pdf2", str(pdf))

    assert db_import.is_user_imported("cod_inorganics") is True
    assert db_import.is_user_imported("pdf2") is True
    assert db_import.is_user_imported("cod_index") is False

    data = json.loads(tmp_cfg.read_text(encoding="utf-8"))
    assert data["cod_db_path"] == str(cod.resolve())
    assert data["pdf2_db_path"] == str(pdf.resolve())
    assert "cod_index_db_path" not in data


def test_datasources_changed_signal_emitted_on_import(qapp, tmp_cfg, tmp_path, monkeypatch):
    """导入后必须发信号, 否则物相分析下拉不会刷新 (不重启就不生效)。"""
    cod = _make_db(tmp_path / "c.sqlite", COD_DDL, COD_ROW, COD_INS)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = DatabaseManagerDialog()
    seen = []
    dlg.databases_changed.connect(lambda: seen.append(1))

    dlg._import_path("cod_inorganics", str(cod))
    assert seen, "导入成功后未发出 databases_changed"


# ── 商业库授权提示 ────────────────────────────────────────────────

def test_pdf2_row_shows_licence_notice(qapp, tmp_cfg):
    """PDF2-2004 是 ICDD 商业库 → 它那一行必须挂着"请确认正版授权"提示。"""
    key = db_import.KIND_BY_KEY["pdf2"].notice_key
    assert key, "PDF2 槽位应配置 notice_key"

    dlg = DatabaseManagerDialog()
    texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert tr(key) in texts, "对话框上没有渲染出授权提示"
    # 中文文案必须点名"正版授权", 不能只写成含糊的"请遵守许可"
    assert "正版授权" in _resolve(zh_CN.translations, key)


def test_licence_notice_only_on_non_free_db(qapp, tmp_cfg):
    """只有"数据本身要用户自己负责授权"的库带提示。

    COD 是开放数据, 加提示会误导用户以为也要授权; PDF2-2004 是 ICDD 商业库,
    XinMatch 格式库是本项目不掌握来源的第三方数据载体 —— 这两个必须提示。
    """
    kinds_with_notice = {k.key for k in db_import.DB_KINDS if k.notice_key}
    assert kinds_with_notice == {"pdf2", "xinmatch"}


def test_notice_keys_resolve_in_all_languages(qapp, tmp_cfg):
    """notice_key 拼错会**静默退化成原始键名**显示给用户, 所以三语都得查得到。"""
    for kind in db_import.DB_KINDS:
        if not kind.notice_key:
            continue
        for mod in (zh_CN, en_US, ja_JP):
            assert _resolve(mod.translations, kind.notice_key), (
                f"{kind.key}: {kind.notice_key} 在 {mod.__name__} 中缺失"
            )


# ── 任意位置挂载 (v3.1.0) ────────────────────────────────────────

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


def _make_xinmatch_db(path: Path, rows: int = 3) -> Path:
    """最小合法 XinMatch 格式库 (v3.1.0 挂载入口用)。"""
    import sqlite3

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


def test_mount_any_path_from_foreign_folder(qapp, tmp_cfg, tmp_path, monkeypatch):
    """需求核心: 库文件放在别的文件夹里, 在界面上指过去就能挂上。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    db = _make_xinmatch_db(tmp_path / "elsewhere" / "deep" / "cod_inorganics.db")

    dlg = DatabaseManagerDialog()
    seen = []
    dlg.databases_changed.connect(lambda: seen.append(1))

    assert dlg.mount_path(str(db)) is True
    assert db_import.is_user_imported("xinmatch") is True
    assert seen, "自动挂载成功后必须发 databases_changed (下拉才会刷新)"
    # 行内状态同步刷新到"已挂载"
    assert "已挂载" in dlg._rows["xinmatch"]["status"].text()


def test_mount_any_path_accepts_folder(qapp, tmp_cfg, tmp_path, monkeypatch):
    """指到文件夹时, 该目录下多类库要一次全挂上。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    folder = tmp_path / "data"
    _make_xinmatch_db(folder / "cod_inorganics.db")
    _make_db(folder / "c.sqlite", COD_DDL, COD_ROW, COD_INS)

    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(folder)) is True
    assert db_import.is_user_imported("xinmatch") is True
    assert db_import.is_user_imported("cod_inorganics") is True


def test_mount_any_path_reports_failure(qapp, tmp_cfg, tmp_path, monkeypatch):
    """不合格的路径要弹提示且不改动任何已挂载配置。"""
    seen = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: seen.append(a[2]) or None)
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a db")

    dlg = DatabaseManagerDialog()
    assert dlg.mount_path(str(junk)) is False
    assert seen, "失败时必须提示原因"
    assert db_import.is_user_imported("xinmatch") is False
