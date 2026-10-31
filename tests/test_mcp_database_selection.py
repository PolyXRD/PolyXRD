# -*- coding: utf-8 -*-
"""v4.6.0: MCP 按"当前库 / 显式库"检索 polyDB 的回归。

背景：MCP 的 polyDB 工具以前一律 PolyDatabase()（配置里的默认 cod-inorg），
完全不理会用户在「数据库管理」里"设为当前"的那一行 —— 界面选中的库与 AI
客户端检索的库可能不是同一份。本文件用假挂载表 + 假 PolyDatabase 钉住解析
优先级：显式 database（id / 路径 / 标签）→ active_mount → 默认槽。

设计：不碰真实库文件与用户配置；db_mounts 的 all_mounts / active_mount /
active_id / probe_all 与 polydb.PolyDatabase 都换成测试替身。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.services.db_mounts import Mount  # noqa: E402


class FakeDB:
    """假 PolyDatabase：记录被打开的路径，返回可控的检索结果。"""

    instances: list["FakeDB"] = []
    _available = True
    ready = True
    entries = [
        {"cod_id": 42, "formula": "SiO2", "mineral_name": "Quartz low"},
    ]
    d_matches = [{"cod_id": 42, "formula": "SiO2"}]

    def __init__(self, db_path=None, variant="cod-inorg"):
        self.path = Path(db_path) if db_path else None
        self.variant = variant
        FakeDB.instances.append(self)

    @property
    def available(self) -> bool:
        # 未显式给路径 = 模拟 PolyDatabase() 找不到配置槽
        return bool(FakeDB._available) and self.path is not None

    def is_ready(self) -> bool:
        return bool(FakeDB.ready)

    def search_entries(self, query, limit=20):
        return list(FakeDB.entries)[:limit]

    def search_by_d_peaks(self, *args, **kwargs):
        FakeDB.last_d_args = (args, kwargs)
        return list(FakeDB.d_matches)

    def get_phase(self, eid):
        return {"cod_id": int(eid), "formula": "SiO2",
                "mineral_name": "Quartz low"}

    def get_atomic_sites(self, eid):
        return [{"label": "Si1"}]


def _make_mount(tmp_path, name: str, *, kind="polydb", label="",
                variant="cod-inorg") -> Mount:
    p = tmp_path / name
    if kind == "polydb":
        p.mkdir()
    else:
        p.write_text("not a real db", encoding="utf-8")
    return Mount(id=f"{kind}:{name}", kind=kind, path=p, label=label,
                 builtin=False, variant=variant)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """三行挂载表：两份 polyDB + 一份 PDF2；active 由测试自行设置。"""
    from polyxrd.services import db_mounts
    from polyxrd.services import polydb as polydb_mod

    db_a = _make_mount(tmp_path, "A.polyDB", label="Active DB")
    db_b = _make_mount(tmp_path, "B.polyDB", label="Second DB")
    pdf = _make_mount(tmp_path, "PDF2.sqlite", kind="pdf2")
    mounts = [db_a, db_b, pdf]
    state = {"mounts": mounts, "active": None}

    monkeypatch.setattr(db_mounts, "all_mounts",
                        lambda *a, **k: list(state["mounts"]))
    monkeypatch.setattr(db_mounts, "active_mount", lambda: state["active"])
    monkeypatch.setattr(
        db_mounts, "active_id",
        lambda: state["active"].id if state["active"] else "")
    monkeypatch.setattr(polydb_mod, "PolyDatabase", FakeDB)
    FakeDB.instances.clear()
    FakeDB._available = True
    FakeDB.ready = True
    return {"mounts": state["mounts"], "state": state,
            "a": db_a, "b": db_b, "pdf": pdf}


# ── 显式 database：id / 路径 / 标签 ────────────────────────────────

def test_explicit_database_id_selects_that_mount(env):
    from polyxrd.mcp_server.server import search_phases_polydb

    out = json.loads(search_phases_polydb("SiO2", database=env["b"].id))

    assert out["database"] == env["b"].id
    assert out["mounted"] is True
    assert out["n_results"] == 1
    assert out["phases"][0]["cod_id"] == 42
    assert FakeDB.instances[-1].path == env["b"].path


def test_explicit_database_path_and_label_also_resolve(env):
    from polyxrd.mcp_server.server import search_phases_polydb

    json.loads(search_phases_polydb("SiO2", database=str(env["b"].path)))
    assert FakeDB.instances[-1].path == env["b"].path

    json.loads(search_phases_polydb("SiO2", database=env["b"].label))
    assert FakeDB.instances[-1].path == env["b"].path


def test_non_polydb_mount_rejected_with_error(env):
    """PDF2 行不能用于 MCP 物相检索：明确报错而不是静默换库。"""
    from polyxrd.mcp_server.server import search_phases_polydb

    out = json.loads(search_phases_polydb("SiO2", database=env["pdf"].id))

    assert out["mounted"] is False
    assert "polyDB" in out["error"]


# ── 空参：active_mount → 默认槽 ────────────────────────────────────

def test_empty_database_uses_active_mount(env):
    env["state"]["active"] = env["a"]
    from polyxrd.mcp_server.server import search_phases_polydb

    out = json.loads(search_phases_polydb("SiO2"))

    assert out["database"] == env["a"].id
    assert FakeDB.instances[-1].path == env["a"].path


def test_empty_database_falls_back_to_default_slot(env):
    from polyxrd.mcp_server.server import search_phases_polydb

    out = json.loads(search_phases_polydb("SiO2"))

    assert out["database"] == "default"
    assert FakeDB.instances[-1].path is None


def test_no_mount_keeps_mounted_false_behavior(env):
    """无库时四个工具的旧契约（mounted=false + hint）不变。"""
    from polyxrd.mcp_server.server import (
        search_phases_by_d_peaks, search_phases_polydb,
    )

    out = json.loads(search_phases_polydb("SiO2"))
    assert out["mounted"] is False
    assert out["n_results"] == 0 and out["phases"] == []
    assert out["hint"]

    d = json.loads(search_phases_by_d_peaks([3.343, 1.817]))
    assert d["mounted"] is False
    assert d["n_results"] == 0 and d["matches"] == []
    assert d["hint"]


# ── 非法 reference：MCP 边界返回 JSON，绝不抛异常 ──────────────────

@pytest.mark.parametrize("tool_name,args", [
    ("search_phases_polydb", ("SiO2",)),
    ("get_phase_details", (1011097,)),
    ("search_phases_by_d_peaks", ([3.343],)),
    ("search_cod_by_d_peaks", ([3.343],)),
])
def test_invalid_reference_returns_error_json(env, tool_name, args):
    from polyxrd.mcp_server import server

    bad = "no:such-db"
    out = json.loads(getattr(server, tool_name)(*args, database=bad))

    assert out["database"] == bad
    assert "error" in out and "not found" in out["error"]


# ── 详情 / d 峰工具同样跟随 database 并回显字段 ────────────────────

def test_get_phase_details_and_d_peaks_honor_database(env):
    from polyxrd.mcp_server.server import (
        get_phase_details, search_cod_by_d_peaks, search_phases_by_d_peaks,
    )

    det = json.loads(get_phase_details(1011097, database=env["b"].id))
    assert det["database"] == env["b"].id
    assert det["atomic_sites"] == [{"label": "Si1"}]
    assert FakeDB.instances[-1].path == env["b"].path

    d = json.loads(search_phases_by_d_peaks([3.343], database=env["b"].id))
    assert d["database"] == env["b"].id
    assert d["n_results"] == 1
    assert FakeDB.instances[-1].path == env["b"].path

    old = json.loads(search_cod_by_d_peaks([3.343], database=env["b"].id))
    assert old["database"] == env["b"].id
    assert old["n_results"] == d["n_results"]


# ── list_phase_databases ───────────────────────────────────────────

def test_list_phase_databases_lists_every_mount(env, monkeypatch):
    from polyxrd.mcp_server.server import list_phase_databases
    from polyxrd.services import db_mounts

    env["state"]["active"] = env["b"]
    # probe 行不带 meta/built 时也能从 meta.json 兜底显示变体/构建时间
    (env["a"].path / "meta.json").write_text(
        json.dumps({"variant": "cod-inorg",
                    "build": {"date": "2026-10-21"}}),
        encoding="utf-8",
    )
    rows = [
        {"mount": env["a"], "id": env["a"].id, "ok": True, "rows": 77500,
         "size_mb": 89.9, "engine": "polydb"},
        {"mount": env["b"], "id": env["b"].id, "ok": False,
         "error": "polydb_not_ready", "detail": "missing segments"},
        {"mount": env["pdf"], "id": env["pdf"].id, "ok": False,
         "error": "wrong_kind", "detail": "not a polyDB"},
    ]
    monkeypatch.setattr(db_mounts, "probe_all", lambda mounts=None: rows)

    out = json.loads(list_phase_databases())

    assert out["active"] == env["b"].id
    assert out["active_label"] == env["b"].label
    assert out["n_databases"] == 3
    assert [r["id"] for r in out["databases"]] ==         [m.id for m in env["mounts"]]

    required = {"id", "kind", "label", "path", "available", "phases",
                "size_mb", "variant", "built", "engine", "is_active",
                "reason"}
    by_id = {}
    for row in out["databases"]:
        assert required <= set(row)
        by_id[row["id"]] = row

    a = by_id[env["a"].id]
    assert a["available"] is True
    assert a["phases"] == 77500
    assert a["size_mb"] == pytest.approx(89.9)
    assert a["variant"] == "cod-inorg"
    assert a["built"] == "2026-10-21"
    assert a["engine"] == "polydb"
    assert a["is_active"] is False

    b = by_id[env["b"].id]
    assert b["available"] is False and b["phases"] is None
    assert b["reason"] == "missing segments"
    assert b["is_active"] is True


def test_list_phase_databases_survives_mount_registry_failure(monkeypatch):
    from polyxrd.mcp_server.server import list_phase_databases
    from polyxrd.services import db_mounts

    def _boom(*args, **kwargs):
        raise OSError("registry broken")

    monkeypatch.setattr(db_mounts, "all_mounts", _boom)

    out = json.loads(list_phase_databases())

    assert "error" in out
    assert out["databases"] == [] and out["n_databases"] == 0
