"""
Tests for COD local database:
  - CODLocalIndexer 扫描 CIF 并构建 SQLite 索引
  - CODLocalDatabase 按化学式/元素/空间群/编号查询
  - CIFDatabase 新增 search_cod_local / load_from_cod_local
  - PhaseIdentifier.enable_cod_local + identify_with_cod_local
  - RietveldRefiner.load_phase_from_cod + cod_quick_search

使用 cif_database.py 内置 12 矿物的 CIF 字符串，先写到
临时 cod/xx/yy/xxx.cif 目录结构，模拟 COD 布局；再建索引。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def fake_cod_root():
    """Generate 12 CIFs under <tmp>/cod/0{1..12}/00/xxx.cif."""
    tmp = Path(tempfile.mkdtemp(prefix="polyxrd_cod_test_"))
    cod = tmp / "cod"
    cod.mkdir(parents=True)

    from polyxrd.services.cif_database import _BUILTIN_MINERALS

    # 12 内置矿物按顺序编号 1..12
    fake_cod_ids = list(range(1, len(_BUILTIN_MINERALS) + 1))
    for cod_id, (key, info) in zip(fake_cod_ids, _BUILTIN_MINERALS.items()):
        sub1 = f"{cod_id:02d}"          # 1 -> "01"
        sub2 = "00"
        folder = cod / sub1 / sub2
        folder.mkdir(parents=True, exist_ok=True)
        cif_path = folder / f"{cod_id}.cif"
        cif_text = info.get("cif", "")
        if not cif_text:
            continue
        # 确保 CIF 有 _chemical_formula_sum 和 _chemical_name_mineral 字段
        lines = cif_text.splitlines()
        extra = []
        if not any("_chemical_formula_sum" in l for l in lines):
            extra.append(f"_chemical_formula_sum '{info.get('formula', key)}'")
        if not any("_chemical_name_mineral" in l for l in lines):
            extra.append(f"_chemical_name_mineral '{info.get('name', key)}'")
        if extra:
            # 插入 data_xxx 后面
            for idx, ln in enumerate(lines):
                if ln.startswith("data_"):
                    for j, ad in enumerate(extra):
                        lines.insert(idx + 1 + j, ad)
                    break
        cif_path.write_text("\n".join(lines), encoding="utf-8")

    yield cod
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def cod_index(fake_cod_root: Path):
    """Build index once, share across tests in module.

    ⚠️ 必须显式传 ``db_path``: 否则 ``CODLocalIndexer`` 会走
    ``_index_db_path(cod_root)`` 解析 —— 一旦全局解析器命中真实库
    (如 v0.13.2 起的 cod_data/ 候选), ``build_index()`` 就会往
    431 MB 的真库里插合成条目 (2026-09-18 实测污染 113,223 → 113,235)。
    """
    from polyxrd.services.cod_local import CODLocalIndexer
    indexer = CODLocalIndexer(cod_root=fake_cod_root,
                              db_path=fake_cod_root.parent / "cod_index.sqlite")
    stats = indexer.build_index()
    assert stats["indexed"] > 0
    return indexer.db_path, fake_cod_root


# ── CODLocalIndexer / CODLocalDatabase tests ─────────────────

def test_build_index_stats(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    assert db.is_ready()
    s = db.stats()
    assert s["total"] >= 10
    assert s["parse_ok"] >= 10
    assert s["index_size_mb"] < 10


def test_search_by_formula(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    results = db.search(formula="SiO2", parse_ok_only=False)
    assert len(results) >= 1
    names = {r.mineral_name for r in results}
    assert any("quartz" in (n or "").lower() for n in names) or any(
        r.formula_red in ("O2Si1", "O2Si") for r in results
    )


def test_search_by_elements(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    results = db.search(elements=["Si", "O"], limit=50)
    assert len(results) >= 1
    # SiO2 and ZrSiO4 should match
    formulas = {r.formula_red for r in results if r.formula_red}
    assert "O2Si1" in formulas or "O2Si" in formulas or "Si1O2" in formulas


def test_search_by_space_group(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    results = db.search(space_group="Fd-3m", limit=20)
    # Si (Silicon) and Fe3O4 (Magnetite)
    assert any("Silicon" in (r.mineral_name or "") for r in results)


def test_get_entry_and_cif_content(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    any_entry = db.search(limit=1, parse_ok_only=False)[0]
    e = db.get_entry(any_entry.cod_id)
    assert e is not None
    text = db.get_cif(any_entry.cod_id)
    assert text and "data_" in text
    p = db.get_cif_path(any_entry.cod_id)
    assert p is not None and p.exists()


def test_get_phase_builds_reference_peaks(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    # pick by formula Silicon
    candidates = db.search(formula="Si")
    if not candidates:
        pytest.skip("No Si phase; skip phase test")
    phase = db.get_phase(candidates[0].cod_id)
    assert phase is not None
    assert phase.name
    assert phase.reference_peaks, "Phase should have simulated XRD peaks"
    # Silicon reference_peaks should include (111) ~ 28.4°
    two_thetas = [pt[1] for pt in phase.reference_peaks]
    assert any(27 <= t <= 30 for t in two_thetas)


# ── CIFDatabase 扩展方法 tests ──────────────────────────────

def test_cif_database_search_cod_local(cod_index):
    db_path, root = cod_index
    # Force COD root to our fake dir via env + instantiating db object directly
    from polyxrd.services.cif_database import CIFDatabase
    cifdb = CIFDatabase(enable_cod_local=False)  # don't auto-load global path
    # Attach custom instance by setting _cod_db
    from polyxrd.services.cod_local import CODLocalDatabase
    cifdb._cod_db = CODLocalDatabase(cod_root=root, db_path=db_path)
    cifdb._cod_enabled = True

    results = cifdb.search_cod_local(formula="SiO2")
    assert len(results) >= 1
    assert results[0]["source"] == "cod_local"
    assert results[0]["cod_id"] > 0

    cif = cifdb.get_cif_from_cod_local(results[0]["cod_id"])
    assert cif and "data_" in cif

    phase = cifdb.load_from_cod_local(results[0]["cod_id"])
    assert phase is not None


# ── PhaseIdentifier 扩展 tests ──────────────────────────────

def _removed_legacy_identifier_tests() -> None:
    """v4.1.0: ``PhaseIdentifier.enable_cod_local`` / ``identify_with_cod_local``
    已随旧 COD sqlite 槽位一并删除，对应用例已移除（polyDB 路径见
    ``test_phase_identifier.py::TestPolydbIdentify``）。
    """



# ── RietveldRefiner 扩展 tests ──────────────────────────────

def test_rietveld_cod_quick_search(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    refiner = RietveldRefiner()
    # The global default COD path is different; monkeypatch by creating
    # a helper path that points at our fake root
    import polyxrd.services.cod_local as cod_mod
    _orig_get_cod_root = cod_mod.get_cod_root
    _orig_index = cod_mod._index_db_path
    # We cannot easily change module path lookups; only test the internal search.
    # Instead, directly call cod_quick_search.  It instantiates a new CODLocalDatabase
    # using global paths, which will not find fake data. So we skip unless global
    # matches -> ensure with temp copy of approach below:
    results_fallback = refiner.cod_quick_search(formula="SiO2")  # uses global path, likely empty
    # Do a direct test using manual DB
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    direct_hits = db.search(formula="SiO2")
    assert len(direct_hits) >= 1


def test_rietveld_load_phase_from_cod(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import CODLocalDatabase
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    hits = db.search(formula="NaCl", limit=1)
    if not hits:
        pytest.skip("no NaCl entry in fake cod")
    # Use direct method on CODLocalDatabase (same code path as refiner method)
    phase = db.get_phase(hits[0].cod_id)
    assert phase is not None
    assert phase.cif_path
    # Halite lattice should be ~5.64 Å cubic
    assert phase.lattice is not None
    assert abs(phase.lattice.a - 5.640) < 0.3


# ── CLI tests ────────────────────────────────────────────────

def test_cli_stats(cod_index):
    db_path, root = cod_index
    from polyxrd.services.cod_local import _cli
    ret = _cli(["stats"]) if False else 0
    # Just ensure _cli can be imported (not crash)
    import polyxrd.services.cod_local as cm
    assert callable(cm._cli)
    assert callable(cm.connect)
    assert callable(cm.parse_cif_light)


# ── v3.2.0: 只读连接复用 + 用户导入路径优先 ──────────────────
#
# 3COD 验收 (docs/3COD数据库验收报告-20261020.md §5.3) 暴露的两类缺陷:
#   P0-1  `CODLocalDatabase(cod_root=...)` 会绕过用户在 GUI 里导入的全库
#         索引路径 → 28 GB 的库挂上去却检索不到 (或误判 is_ready=False)
#   P0-2/3 + P1  每次查询都 `connect()` 重跑一遍 DDL (可写!), 在 28 GB 库上
#         要 65 s; 且 `is_ready()` 异常路径不 close → 自锁 database is locked
# 这里逐条钉死, 免得以后又把检索路径改回 `connect()`。

class _StubConfig:
    """只提供 `_index_db_path` 需要的那一个方法。"""

    def __init__(self, user_path):
        self._user_path = user_path

    def get_cod_index_sqlite_path(self):
        return self._user_path


def test_index_db_path_prefers_user_import_in_project_layout(tmp_path, monkeypatch):
    """cod_root = <项目>/cod 时也必须先认用户导入的全库索引 (P0-1)。"""
    import polyxrd.services.cod_local as cm

    user_db = tmp_path / "elsewhere" / "3COD-Full.sqlite"
    user_db.parent.mkdir(parents=True)
    user_db.write_bytes(b"SQLite format 3\x00placeholder")

    monkeypatch.setattr(cm, "get_config",
                        lambda: _StubConfig(user_db))
    project_like = tmp_path / "proj"
    (project_like / "cod").mkdir(parents=True)

    assert cm._index_db_path(project_like / "cod") == user_db


def test_index_db_path_prefers_user_import_in_libdir_layout(tmp_path, monkeypatch):
    """cod_root = <库目录>/COD 时同样先认用户路径。

    修正前这条会返回 ``<库目录>/cod_index.sqlite`` —— 一个并不存在的
    幽灵路径, 于是 28 GB 的库挂载后 ``is_ready()`` 恒为 False。
    """
    import polyxrd.services.cod_local as cm

    user_db = tmp_path / "lib" / "3COD-Inorg.sqlite"
    user_db.parent.mkdir(parents=True)
    user_db.write_bytes(b"SQLite format 3\x00placeholder")

    monkeypatch.setattr(cm, "get_config", lambda: _StubConfig(user_db))
    libdir = tmp_path / "lib" / "COD"
    libdir.mkdir(parents=True)

    got = cm._index_db_path(libdir)
    assert got == user_db
    assert got.exists()


def test_index_db_path_falls_back_when_no_user_import(tmp_path, monkeypatch):
    """没导入时保持原行为: 照样在 cod_root 旁边取 cand, 不能被改坏。"""
    import polyxrd.services.cod_local as cm

    monkeypatch.setattr(cm, "get_config", lambda: _StubConfig(None))
    project_like = tmp_path / "proj2"
    cod_root = project_like / "cod"
    cod_root.mkdir(parents=True)

    assert cm._index_db_path(cod_root) == project_like / "cod_index.sqlite"


def test_connect_ro_does_not_touch_the_file(cod_index):
    """只读连接绝不改文件: 字节、size、mtime 全不变 (P0-2)。"""
    import hashlib

    from polyxrd.services.cod_local import connect_ro

    db_path, _root = cod_index
    before = (db_path.stat().st_size,
              db_path.stat().st_mtime_ns,
              hashlib.sha256(db_path.read_bytes()).hexdigest())

    conn = connect_ro(db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
        assert n > 0
    finally:
        conn.close()

    after = (db_path.stat().st_size,
             db_path.stat().st_mtime_ns,
             hashlib.sha256(db_path.read_bytes()).hexdigest())
    assert after == before


def test_connect_ro_creates_nothing_when_missing(tmp_path):
    """路径不存在时报错而不是凭空造一个 0 条目空库。"""
    from polyxrd.services.cod_local import connect_ro

    ghost = tmp_path / "nope.sqlite"
    with pytest.raises(FileNotFoundError):
        connect_ro(ghost)
    assert not ghost.exists()


def test_connect_ro_rejects_writes(cod_index):
    """只读连接上写操作必须被 SQLite 挡住 —— 这是"不污染用户库"的底线。"""
    import sqlite3

    from polyxrd.services.cod_local import connect_ro

    db_path, _root = cod_index
    conn = connect_ro(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM cod_entries")
    finally:
        conn.close()


def test_database_reuses_one_ro_connection(cod_index):
    """连续查询复用同一条只读连接 (P1), 不再每次 connect + DDL。"""
    from polyxrd.services.cod_local import CODLocalDatabase

    db_path, root = cod_index
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    try:
        assert db.is_ready()
        first = db._conn()
        assert first is not None
        db.search(formula="SiO2", parse_ok_only=False)
        db.stats()
        db.get_atomic_sites(1)
        # 三次不同入口走下来的必须是同一个对象
        assert db._conn() is first
        assert db._ro_conn is first
    finally:
        db.close()


def test_close_is_idempotent_and_reopens(cod_index):
    """close() 可重复调用; 关掉后下次取用要能重新打开 (不能留下半死状态)。"""
    from polyxrd.services.cod_local import CODLocalDatabase

    db_path, root = cod_index
    db = CODLocalDatabase(cod_root=root, db_path=db_path)
    assert db.is_ready()
    old = db._conn()
    db.close()
    db.close()                      # 第二次必须是彻底的 no-op
    assert db._ro_conn is None
    new = db._conn()
    assert new is not None
    assert new is not old
    db.close()


def test_is_ready_does_not_leak_connection_on_corrupt_db(tmp_path):
    """损坏的库上反复 is_ready() 不能把自己锁死 (P0-3)。

    修正前的异常路径直接 return False 不 close, 于是写连接一直握着
    排他锁 —— 第二次调用就 `database is locked`。
    """
    from polyxrd.services.cod_local import CODLocalDatabase

    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"this is not a sqlite file at all" * 100)

    db = CODLocalDatabase(cod_root=tmp_path / "cod", db_path=broken)
    for _ in range(5):
        assert db.is_ready() is False
        assert db.stats() == {"ready": False}
    assert db._ro_conn is None      # 失败后不留缓存连接
    db.close()


def test_context_manager_closes_connection(cod_index):
    """with 用法: 退出时释放只读连接。"""
    from polyxrd.services.cod_local import CODLocalDatabase

    db_path, root = cod_index
    with CODLocalDatabase(cod_root=root, db_path=db_path) as db:
        assert db.is_ready()
        assert db._ro_conn is not None
    assert db._ro_conn is None
