"""挂载类型注册表 / polyDB 元数据 / 重命名 (v4.6.0)
====================================================

v4.1.0 把挂载模型换成了"列表", 但可挂的**类型**还是写死的三种, 判别与探测
各写一遍 if/elif。v4.6.0 把类型也改成**可注册的**, 本文件钉住由此新增的六条
契约:

1. **内置三类只是种子** —— polydb / pdf2 / user 都登记在 MOUNT_KINDS 里, 但
   注册表还能再收自建格式; 注册后自动判别 / 探测 / 列表 / 检索分发全部接上;
2. **不限插槽** —— 同一类型挂 60 份库全部共存, id 互不相同;
3. **元数据是附加的** —— probe 行带 meta / dataset / built / schema_version,
   现有键一个不少 (老 UI 不需要改);
4. **改名** —— 只有用户自加项能改名, 空名恢复按目录名显示, 且真的落盘;
5. **半成品库可挂但探测失败** —— 挂载判据只看容器结构, 探测负责说"哪里坏",
   失败时元数据仍要能显示 (否则用户不知道该修哪份库);
6. **老 json 容错** —— 未知 kind 的条目被跳过, 坏 JSON 当空表, version 仍是 1。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config   # noqa: E402
from polyxrd.services import db_mounts             # noqa: E402


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """挂载表 + 槽位配置 + 类型注册表全部隔离。

    注册表也要隔离: 自定义 kind 若注册进真实 MOUNT_KINDS, 会跟着测试进程活到
    后面的用例, 让别的文件的"检测不出这个路径属于哪类库"断言莫名失败。
    """
    store = tmp_path / "db_mounts.json"
    monkeypatch.setattr(db_mounts, "_store_file", lambda: store)
    monkeypatch.setattr(AppConfig, "_user_db_paths_file",
                        lambda self: tmp_path / "user_db_paths.json")
    cfg = get_config()
    empty = tmp_path / "empty"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(cfg, "pdf2_db_path", empty / "n_pdf2.sqlite")
    monkeypatch.setattr(cfg, "cif_db_path", empty)
    monkeypatch.setattr(cfg, "user_db_dir", lambda: empty)
    monkeypatch.setattr(cfg, "get_polydb_path", lambda *a, **k: None)
    monkeypatch.setattr(db_mounts, "_probe_user",
                        lambda p: {"ok": False, "rows": 0, "error": "user_db_empty"})
    # 注册表副本: register_kind 改的是模块级 dict, monkeypatch 结束自动还原。
    monkeypatch.setattr(db_mounts, "MOUNT_KINDS", dict(db_mounts.MOUNT_KINDS))
    monkeypatch.setattr(db_mounts, "KIND_ENGINE", dict(db_mounts.KIND_ENGINE))
    monkeypatch.setattr(db_mounts, "KIND_LABEL_KEY", dict(db_mounts.KIND_LABEL_KEY))
    db_mounts.clear_probe_cache()
    return store


@pytest.fixture
def store(isolated):
    """db_mounts.json 的路径 (由 isolated fixture 定到 tmp_path)。"""
    return isolated


# ── 造库 ─────────────────────────────────────────────────────

def _polydb(root: Path, name: str, *, variant: str = "cod-inorg",
            phases: int = 100, dataset: str = "", built: str = "",
            schema_version: int = 1) -> Path:
    """造一个"容器结构成立、但数组段缺失"的 polyDB 目录 (可挂、不可探测)。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "format": "polyDB", "schema_version": schema_version,
        "variant": variant,
        "counts": {"phases": phases, "k": 100, "peaks": 1000, "sites": 500},
    }
    if dataset:
        meta["name"] = dataset
    if built:
        meta["build"] = {"date": built}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "index.sqlite").write_bytes(b"")
    return d


def _ready_polydb(root: Path, name: str, *, phases: int = 3, k: int = 2,
                  dataset: str = "COD Inorg 2026-10",
                  built: str = "2026-10-21 10:45:40") -> Path:
    """造一份**探测能通过**的最小 polyDB: 分段字节数与 meta 完全对得上。

    真实库有几百 MB, 单测只需要"能过 is_ready + stats"的骨架。bins 与 peaks
    的 shape 必须写进 meta —— PolyDatabase 用它们算 memmap 形状。
    """
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    nbytes = (phases + 7) // 8
    nbins = 64
    sections = {
        "peaks_d.f32": {"dtype": "float32", "shape": [phases, k],
                        "bytes": phases * k * 4},
        "peaks_i.u16": {"dtype": "uint16", "shape": [phases, k],
                        "bytes": phases * k * 2},
        "bins.u8": {"dtype": "uint8", "shape": [nbins, nbytes],
                    "bytes": nbins * nbytes},
        "elem.u8": {"dtype": "uint8", "shape": [118, nbytes],
                    "bytes": 118 * nbytes},
        "sites_off.i64": {"dtype": "int64", "shape": [phases + 1],
                          "bytes": (phases + 1) * 8},
        "sites.bin": {"bytes": 0},
        "index.sqlite": {"bytes": 0},
    }
    meta = {
        "format": "polyDB", "schema_version": 1, "variant": "cod-inorg",
        "name": dataset,
        "build": {"date": built, "tool": "build_polydb.py"},
        "counts": {"phases": phases, "k": k,
                   "peaks": phases * k, "sites": 5},
        "sections": sections,
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for fname, sec in sections.items():
        (d / fname).write_bytes(b"\0" * int(sec["bytes"]))
    return d


def _stored(store: Path) -> dict:
    return json.loads(store.read_text(encoding="utf-8"))


# ── 1. 注册表本身 ────────────────────────────────────────────

def test_builtin_kinds_are_seeded(isolated):
    """内置三类是注册表的种子, Mount 的 is_dir / engine 也改由注册表回答。"""
    keys = [k.key for k in db_mounts.iter_kinds()]
    assert {"polydb", "pdf2", "user"} <= set(keys)
    assert db_mounts.KIND_ENGINE["polydb"] == "polydb"
    assert db_mounts.KIND_ENGINE["pdf2"] == "pdf2"
    assert db_mounts.get_kind("polydb").is_dir is True
    assert db_mounts.get_kind("pdf2").is_dir is False

    poly = db_mounts.Mount(id="polydb:x", kind="polydb", path=Path("somewhere"))
    assert poly.is_dir is True and poly.engine == "polydb"
    pdf = db_mounts.Mount(id="pdf2:x", kind="pdf2", path=Path("a.sqlite"))
    assert pdf.is_dir is False and pdf.engine == "pdf2"


def test_duplicate_registration_requires_replace(isolated):
    """抢同一个类型名要报错; 显式 replace=True 才允许覆盖。"""
    spec = db_mounts.MountKind(key="dup", engine="dup",
                               probe=lambda p: {}, detect=lambda p: False)
    db_mounts.register_kind(spec)
    with pytest.raises(ValueError):
        db_mounts.register_kind(spec)
    db_mounts.register_kind(spec, replace=True)
    assert db_mounts.get_kind("dup") is spec


def test_register_custom_file_kind_mounts_probes_and_lists(isolated, tmp_path):
    """注册自建单文件格式后: 自动判别、可挂、可探测、进 all_mounts。"""
    lib = tmp_path / "mine.crystal"
    lib.write_bytes(b"CRYSTAL")
    db_mounts.register_kind(
        key="crystal", engine="crystal", label_key="",
        probe=lambda p: {"ok": True, "rows": 42, "size_mb": 0.1},
        detect=lambda p: p.suffix == ".crystal")

    assert db_mounts.KIND_ENGINE["crystal"] == "crystal"
    assert db_mounts.detect_kind(lib) == ("crystal", "")

    m = db_mounts.add_mount(lib)
    assert m.kind == "crystal" and m.builtin is False
    assert m.id.startswith("crystal:")
    assert m.id in {x.id for x in db_mounts.all_mounts()}
    assert db_mounts.resolve_source(m.id) == ("crystal", lib.resolve())

    row = next(r for r in db_mounts.probe_all() if r["id"] == m.id)
    assert row["ok"] is True and row["rows"] == 42
    assert row["engine"] == "crystal"


def test_register_custom_dir_kind_uses_directory_semantics(isolated, tmp_path):
    """自定义目录型库: 挂载判据是"目录 + 自定义标记文件", is_dir 也跟着变。"""
    lib = tmp_path / "mylib"
    lib.mkdir()
    (lib / "manifest.txt").write_text("x", encoding="utf-8")
    db_mounts.register_kind(
        key="folderdb", engine="folderdb",
        probe=lambda p: {"ok": True, "rows": 3},
        detect=lambda p: (p / "manifest.txt").is_file(), is_dir=True)

    m = db_mounts.add_mount(lib)
    assert m.kind == "folderdb" and m.is_dir is True and m.exists
    assert db_mounts.detect_kind(lib) == ("folderdb", "")


def test_registry_probe_resolves_module_globals_at_call_time(
        isolated, tmp_path, monkeypatch):
    """注册表里的 probe 必须是薄包装: monkeypatch 模块级函数要能生效。

    test_db_mounts / test_db_manager_dialog 都靠 monkeypatch _probe_polydb
    造"相数可控"的库; 若种子注册时把函数对象绑死, 那些用例会读到真实容器。
    """
    lib = _polydb(tmp_path / "libs", "A.polyDB")
    monkeypatch.setattr(db_mounts, "_probe_polydb",
                        lambda p: {"ok": True, "rows": 999, "detail": "patched"})
    res = db_mounts.probe(db_mounts.Mount(id="polydb:test", kind="polydb", path=lib))
    assert res["ok"] is True and res["rows"] == 999
    assert res["detail"] == "patched"


# ── 2. 不限插槽: 60 份同类型库共存 ───────────────────────────

def test_sixty_libraries_of_same_kind_coexist(isolated, tmp_path, store):
    root = tmp_path / "many"
    mounts = [db_mounts.add_mount(_polydb(root, f"Lib-{i:02d}.polyDB"))
              for i in range(60)]

    ids = [m.id for m in mounts]
    assert len(ids) == 60
    assert len(set(ids)) == 60, "同一类型挂多份时数据源 id 必须互不相同"

    listed = [m for m in db_mounts.all_mounts()
              if m.kind == "polydb" and not m.builtin]
    assert len(listed) == 60
    assert {m.id for m in listed} == set(ids)

    saved = _stored(store)
    assert saved["version"] == 1
    assert len(saved["mounts"]) == 60


# ── 3. polyDB 元数据 ─────────────────────────────────────────

def test_polydb_probe_carries_metadata(isolated, tmp_path):
    """完好 polyDB: probe 行带 dataset / built / schema_version / meta。"""
    lib = _ready_polydb(tmp_path / "libs", "COD-Inorg-20261021.polyDB", phases=7)
    m = db_mounts.add_mount(lib)
    assert m.dataset == "COD Inorg 2026-10"
    assert m.built == "2026-10-21 10:45:40"
    assert m.schema_version == 1

    row = next(r for r in db_mounts.probe_all() if r["id"] == m.id)
    assert row["ok"] is True and row["rows"] == 7
    assert row["engine"] == "polydb"
    assert row["dataset"] == "COD Inorg 2026-10"
    assert row["built"] == "2026-10-21 10:45:40"
    assert row["schema_version"] == 1
    assert row["meta"]["variant"] == "cod-inorg"
    assert row["meta"]["counts"]["phases"] == 7
    # 既有键一个不少 (对话框与历史测试都按这些键读)
    assert {"ok", "rows", "size_mb", "engine", "error", "hint", "detail",
            "has_top_peaks"} <= set(row)


def test_half_built_polydb_mounts_but_probe_fails(isolated, tmp_path):
    """半成品 polyDB (meta + 空 index, 缺数组段): 可挂, probe 报不可用。"""
    lib = _polydb(tmp_path / "libs", "Broken.polyDB", dataset="Broken set")
    m = db_mounts.add_mount(lib)
    row = next(r for r in db_mounts.probe_all() if r["id"] == m.id)

    assert row["ok"] is False and row["error"] == "polydb_not_ready"
    # 失败路径仍带元数据: 用户得知道"这行本该是哪份库"
    assert row["dataset"] == "Broken set"
    assert row["meta"]["variant"] == "cod-inorg"


def test_broken_meta_json_does_not_crash_mount_or_probe(isolated, tmp_path):
    """meta.json 是坏 JSON: 仍可挂 (容器判据只看文件在不在), 探测失败但不崩。"""
    lib = _polydb(tmp_path / "libs", "BadMeta.polyDB")
    (lib / "meta.json").write_text("{not json", encoding="utf-8")

    m = db_mounts.add_mount(lib)
    assert m.schema_version == 0 and m.dataset == ""
    row = next(r for r in db_mounts.probe_all() if r["id"] == m.id)
    assert row["ok"] is False and row["error"] == "polydb_not_ready"
    # 元数据摘要仍是同结构 (只是全空), 界面可以无脑按键取值
    assert row["meta"]["variant"] == "" and row["meta"]["counts"] == {}
    assert row["dataset"] == "" and row["schema_version"] == 0


# ── 4. 重命名 ────────────────────────────────────────────────

def test_rename_custom_mount_persists_and_empty_restores(isolated, tmp_path, store):
    m = db_mounts.add_mount(_polydb(tmp_path / "libs", "Mine.polyDB"))

    renamed = db_mounts.rename_mount(m.id, "我的无机库")
    assert renamed.label == "我的无机库"
    assert db_mounts.get_mount(m.id).label == "我的无机库"
    row = next(r for r in db_mounts.probe_all() if r["id"] == m.id)
    assert row["label"] == "我的无机库"

    saved = _stored(store)
    assert saved["version"] == 1
    assert saved["mounts"][0]["label"] == "我的无机库"

    # 空名 (含纯空白) = 清掉自定义名, 恢复按目录名显示
    db_mounts.rename_mount(m.id, "   ")
    assert db_mounts.get_mount(m.id).display_name() == "Mine.polyDB"
    row = next(r for r in db_mounts.probe_all() if r["id"] == m.id)
    assert row["label"] == "Mine.polyDB"
    assert _stored(store)["mounts"][0]["label"] == ""


def test_rename_builtin_is_rejected(isolated):
    """内置项的显示名由类型/变体决定, 改名会让两份内置库分不清。"""
    with pytest.raises(ValueError):
        db_mounts.rename_mount("polydb:cod-inorg", "随便叫")
    with pytest.raises(KeyError):
        db_mounts.rename_mount("no-such-mount", "x")


# ── 5. 老 json 兼容 ─────────────────────────────────────────

def test_unknown_kind_entries_are_skipped(isolated, tmp_path, store):
    """旧 json 里残留的未知 kind 一律跳过: 不崩、不冒出幽灵行。"""
    lib = _polydb(tmp_path / "libs", "A.polyDB")
    store.write_text(json.dumps({
        "version": 1, "active": "ghost:1",
        "mounts": [
            {"id": "ghost:1", "kind": "ghost_engine", "path": str(lib)},
            {"id": "polydb:abc", "kind": "polydb", "path": str(lib),
             "label": "A", "variant": "cod-inorg"},
        ],
    }), encoding="utf-8")

    ids = [m.id for m in db_mounts.all_mounts()]
    assert "ghost:1" not in ids
    assert ids[-1] == "polydb:abc"
    # active 指向被跳过的条目也不崩: 解析不到就当未指定
    assert db_mounts.active_mount() is None


def test_late_registered_kind_revives_saved_entry(isolated, tmp_path, store):
    """先存条目、后注册类型: 注册后该条目应重新出现在列表里。"""
    lib = tmp_path / "late.crystal"
    lib.write_bytes(b"x")
    store.write_text(json.dumps({
        "version": 1, "active": "", "mounts": [
            {"id": "crystal:deadbeef", "kind": "crystal", "path": str(lib),
             "label": "Late"},
        ],
    }), encoding="utf-8")
    assert all(m.id != "crystal:deadbeef" for m in db_mounts.all_mounts())

    db_mounts.register_kind(key="crystal", engine="crystal",
                            probe=lambda p: {"ok": True, "rows": 1},
                            detect=lambda p: p.suffix == ".crystal")
    assert any(m.id == "crystal:deadbeef" for m in db_mounts.all_mounts())


def test_corrupt_store_falls_back_to_builtins(isolated, tmp_path, store):
    """db_mounts.json 整个坏掉: 内置项照常显示, 且下一次写入会重建合法文件。"""
    store.write_text("{ this is not json", encoding="utf-8")
    ids = [m.id for m in db_mounts.all_mounts()]
    assert ids[:4] == ["polydb:cod-inorg", "polydb:cod-full", "pdf2", "user"]

    m = db_mounts.add_mount(_polydb(tmp_path / "libs", "A.polyDB"))
    saved = _stored(store)
    assert saved["version"] == 1
    assert [r["id"] for r in saved["mounts"]] == [m.id]
