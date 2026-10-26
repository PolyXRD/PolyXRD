# -*- coding: utf-8 -*-
"""v4.2.1 回归守卫：验收报告 P1 修复（MCP 旧名兼容 / 向导死 UI）+ 补回被删覆盖。"""
from __future__ import annotations

import inspect
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from polyxrd.services.polydb import PolyDatabase  # noqa: E402
from polyxrd.utils.formula_parser import (  # noqa: E402
    elements_from_db_formula,
)

REAL_DB = Path(
    r"D:\Project\XRD\PolyXRD-DataBase\polydb\COD-Inorg-20261021.polyDB")


# ── 1. MCP 旧名兼容 ─────────────────────────────────────────

def test_get_cod_phase_details_keeps_old_arg_name():
    from polyxrd.mcp_server.server import get_cod_phase_details

    assert list(inspect.signature(get_cod_phase_details).parameters) == ["cod_id"]


@pytest.mark.parametrize("q,expected", [
    ("1011097", 1011097),
    ("97-1011097", 1011097),
    ("96-101-1097", 1011097),
    ("97 1011097", 1011097),
    ("96_101_1097", 1011097),
    ("quartz", None),
    ("97-", None),
])
def test_parse_eid_query_compat(q, expected):
    assert PolyDatabase._parse_eid_query(q) == expected


@pytest.mark.skipif(not REAL_DB.is_dir(), reason="本机无实测 polyDB 库")
def test_search_entries_id_formats_and_fields():
    db = PolyDatabase(str(REAL_DB))
    assert db.is_ready()
    ref = db.search_entries("1011097", limit=3)
    assert len(ref) == 1
    row = ref[0]
    assert row["cod_id"] == 1011097
    assert row["mineral_name"] == "Quartz low"
    assert row["display_id"] == "97-1011097"
    assert row["ref_id"] == "96-101-1097"
    for q in ("97-1011097", "96-101-1097"):
        got = db.search_entries(q, limit=3)
        assert [r["cod_id"] for r in got] == [1011097], q


@pytest.mark.skipif(not REAL_DB.is_dir(), reason="本机无实测 polyDB 库")
def test_search_entries_formula_and_spacegroup_normalized():
    db = PolyDatabase(str(REAL_DB))
    # SiO2 归一化为 O2 Si，应能命中石英/二氧化硅
    formulas = {r["formula"].replace(" ", "") for r in db.search_entries("SiO2", limit=5)}
    assert "O2Si" in formulas
    # Fd-3m ↔ 库内 "F d -3 m"
    assert db.search_entries("Fd-3m", limit=5), "空间群查询应忽略空格"
    assert db.search_entries("F d -3 m", limit=5)


def _mock_online(monkeypatch):
    import polyxrd.services.cod_searcher as cs

    def boom(*_a, **_k):
        raise ConnectionError("offline-for-test")

    monkeypatch.setattr(cs.CODSearcher, "search", boom)


def test_search_cod_online_returns_json_on_network_error(monkeypatch):
    from polyxrd.mcp_server.server import search_cod_online

    _mock_online(monkeypatch)
    out = json.loads(search_cod_online(formula="SiO2", timeout=3))
    assert out["n_results"] == 0
    assert out["entries"] == []
    assert "offline-for-test" in out["error"]
    assert "hint" in out


def test_search_phases_polydb_reports_corrupted_layout(monkeypatch):
    from polyxrd.mcp_server import server

    class _Fake:
        available = True
        is_ready = lambda self: False  # noqa: E731

    monkeypatch.setattr("polyxrd.services.polydb.PolyDatabase", _Fake)
    out = json.loads(server.search_phases_polydb("quartz", 3))
    assert out["mounted"] is True and out["n_results"] == 0
    assert "corrupted" in out["error"].lower()


# ── 2. 被删覆盖补回：fail-open / elements 契约 ──────────────

def _fail_open_conn(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE phases (cod_id TEXT, ref_id TEXT, display_id TEXT, "
        "formula TEXT, space_group TEXT, n_peaks INTEGER, "
        "peaks_d TEXT, peaks_i TEXT)"
    )
    conn.executemany(
        "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def _search(conn, elements_allowed):
    from polyxrd.services.phase_search import search_phases_by_d_peaks

    return search_phases_by_d_peaks(
        conn, [2.0, 2.5, 3.0], [100, 90, 80],
        min_match=3, elements_allowed=elements_allowed)


def test_fail_open_when_formula_looks_like_space_group():
    conn = _fail_open_conn([
        ("SG_OVERWRITTEN", "x", "x", "P 63 m c", "P 63 m c", 3,
         "2.0,2.5,3.0", "100,90,80"),
    ])
    got = _search(conn, {"Zn", "O"})
    assert [r["cod_id"] for r in got] == ["SG_OVERWRITTEN"], \
        "formula 与空间群相同 → 不可信 → 必须放行（真 ZnO 被误杀的历史 bug）"


def test_trusted_but_wrong_elements_still_rejected():
    conn = _fail_open_conn([
        ("CA_O", "x", "x", "Ca1 O1", "P 1", 3, "2.0,2.5,3.0", "100,90,80"),
    ])
    assert _search(conn, {"Zn", "O"}) == []


def test_empty_formula_fail_open():
    conn = _fail_open_conn([
        ("EMPTY", "x", "x", "", "P 1", 3, "2.0,2.5,3.0", "100,90,80"),
    ])
    assert [r["cod_id"] for r in _search(conn, {"Zn", "O"})] == ["EMPTY"]


@pytest.mark.parametrize("formula,expected", [
    ("O Zn", {"O", "Zn"}),
    ("Li1.13 Mn2 O4", {"Li", "Mn", "O"}),
    ("O4 Zr3", {"O", "Zr"}),
    ("", set()),
])
def test_elements_from_db_formula_contract(formula, expected):
    assert elements_from_db_formula(formula) == expected


def test_elements_from_db_formula_space_group_semantics():
    assert elements_from_db_formula("P 63 m c") == {"P"}
    assert elements_from_db_formula("P 63 m c", space_group="P 63 m c") == set()
    assert elements_from_db_formula("O Zn", space_group="P 63 m c") == {"O", "Zn"}
    assert elements_from_db_formula("  P 63 m c ", space_group="P 63 m c") == set()
    assert elements_from_db_formula("P 63 m c", space_group="") == {"P"}


# ── 3. 向导死 UI / 死链路 ───────────────────────────────────

def test_wizard_dead_cif_search_removed():
    text = (ROOT / "src/polyxrd/views/refinement_wizard.py").read_text(
        encoding="utf-8")
    for dead in ("_cif_search_input", "_btn_cif_search", "_on_cif_search",
                 "_fill_cif_list", "_cell_summary", "_load_cod_cif_phase",
                 "cif_db_unavailable"):
        assert dead not in text, f"向导仍残留已下线的 CIF 搜索链路: {dead}"


def test_wizard_i18n_dead_keys_removed():
    from polyxrd.i18n.translations import en_US, ja_JP, zh_CN

    dead = ("cif_list_searching", "cif_list_browsing",
            "cif_list_no_db", "cif_db_unavailable")
    for mod in (zh_CN, en_US, ja_JP):
        text = Path(mod.__file__).read_text(encoding="utf-8")
        for key in dead:
            assert f'"{key}"' not in text, f"{mod.__name__} 仍有死键 {key}"


# ── 4. 启动日志 / 崩溃日志（从 v4.2.0 删除的旧测试补回）──────

def test_startup_and_crash_log_written(tmp_path, monkeypatch):
    import polyxrd.main as main_mod

    monkeypatch.setattr(main_mod, "_LOG_DIR_HINT", tmp_path / "logs")
    main_mod._startup_log("hello-startup")
    logs = list((tmp_path / "logs").glob("startup-*.log"))
    assert logs and "hello-startup" in logs[0].read_text(encoding="utf-8")

    try:
        raise RuntimeError("boom-for-test")
    except RuntimeError:
        path = main_mod._write_crash(*sys.exc_info())
    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "boom-for-test" in text and "Traceback" in text


def test_excepthook_is_installed():
    import polyxrd.main as main_mod

    main_mod._install_excepthooks()
    assert sys.excepthook is not sys.__excepthook__
