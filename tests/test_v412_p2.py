# -*- coding: utf-8 -*-
"""v4.1.2 P2 批次回归守卫（默认库发现优先级 / 旧库提示 / 构建与验收政策）。"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from polyxrd.config import AppConfig  # noqa: E402
from polyxrd.services import db_mounts  # noqa: E402

SEGMENTS = ("meta.json", "index.sqlite", "peaks_d.f32", "peaks_i.u16",
            "bins.u8", "elem.u8", "sites.bin", "sites_off.i64")


def _polydb(root: Path, name: str, variant: str = "cod-inorg",
            phases: int = 10, meta: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    if meta is None:
        meta = json.dumps({
            "format": "polyDB", "schema_version": 1, "variant": variant,
            "counts": {"phases": phases},
        })
    (d / "meta.json").write_text(meta, encoding="utf-8")
    (d / "index.sqlite").write_bytes(b"")
    return d


def _legacy_sqlite(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE cod_entries (cod_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO cod_entries VALUES (1)")
        conn.commit()
    finally:
        conn.close()
    return path


def _load_build_post():
    spec = importlib.util.spec_from_file_location(
        "_bp_v412", ROOT / "scripts" / "_build_post.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. discover_polydb：root 顺序即优先级 ────────────────────

def test_discover_polydb_root_priority(tmp_path, monkeypatch):
    explicit = _polydb(tmp_path / "explicit", "COD-Inorg-20260101.polyDB")
    newer = _polydb(tmp_path / "fallback", "COD-Inorg-20261021.polyDB")
    monkeypatch.setattr(AppConfig, "_polydb_search_roots",
                        lambda self: [explicit.parent, newer.parent])
    cfg = AppConfig()
    assert cfg.discover_polydb("cod-inorg") == explicit, \
        "显式 root 的旧快照被 fallback root 的新快照顶掉了（root 优先级失效）"


def test_discover_meta_invalid_falls_back_to_filename(tmp_path, monkeypatch):
    d = _polydb(tmp_path / "root", "COD-Inorg-20260101.polyDB",
                meta="{not json")
    monkeypatch.setattr(AppConfig, "_polydb_search_roots",
                        lambda self: [d.parent])
    cfg = AppConfig()
    assert cfg.discover_polydb("cod-inorg") == d


# ── 2. 旧格式库挂载提示 + 部分挂载原因 ───────────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mounts, "_store_file",
                        lambda: tmp_path / "db_mounts.json")
    monkeypatch.setattr(AppConfig, "_user_db_paths_file",
                        lambda self: tmp_path / "user_db_paths.json")
    return tmp_path


def test_mount_any_report_reports_legacy_sqlite(store):
    libs = store / "libs"
    poly = _polydb(libs, "COD-Inorg-Mine.polyDB")
    legacy = _legacy_sqlite(libs / "COD_inorganics.sqlite")

    mounted, skipped = db_mounts.mount_any_report(libs)
    assert len(mounted) == 1 and mounted[0].path == poly
    assert skipped, "旧格式 sqlite 被跳过了但没有返回原因"
    assert "旧格式" in skipped[0] and "polyDB" in skipped[0], skipped


def test_mount_any_all_invalid_raises_with_migration_hint(store):
    bad = store / "old"
    bad.mkdir()
    _legacy_sqlite(bad / "cod_index.sqlite")
    with pytest.raises(ValueError) as ei:
        db_mounts.mount_any(bad)
    assert "旧格式" in str(ei.value)


def test_detect_kind_legacy_cod_message(tmp_path):
    legacy = _legacy_sqlite(tmp_path / "COD_inorganics.sqlite")
    kind, note = db_mounts.detect_kind(legacy)
    assert kind == ""
    assert "v4.1.0" in note and "polyDB" in note


# ── 3. 内置库打包/布局校验 ───────────────────────────────────

def test_validate_polydb_meta():
    mod = _load_build_post()
    good = {"format": "polyDB", "schema_version": 1, "variant": "cod-inorg",
            "counts": {"phases": 77500}}
    assert mod._validate_polydb_meta(good) == []
    assert mod._validate_polydb_meta(dict(good, format="x"))
    assert mod._validate_polydb_meta(dict(good, schema_version=2))
    assert mod._validate_polydb_meta(dict(good, variant="cod-full"))
    assert mod._validate_polydb_meta(dict(good, counts={"phases": 0}))
    assert mod._validate_polydb_meta({})


def test_db_layout_rejects_bad_meta(tmp_path, monkeypatch):
    mod = _load_build_post()
    dist = tmp_path / "dist" / "PolyXRD"
    lib = dist / "databases" / "COD-Inorg-bad.polyDB"
    lib.mkdir(parents=True)
    for seg in SEGMENTS:
        (lib / seg).write_bytes(b"")
    (lib / "meta.json").write_text(json.dumps({
        "format": "polyDB", "schema_version": 1, "variant": "cod-inorg",
        "counts": {"phases": 0}}), encoding="utf-8")
    monkeypatch.setattr(mod, "DIST", str(dist))
    assert mod.assert_db_layout() == 1, "meta 相数为 0 的库仍通过布局门禁"


# ── 4. 构建/验收脚本政策守卫 ────────────────────────────────

def test_verify_release_has_skip_bundled_db():
    s = (ROOT / "scripts" / "verify_release.ps1").read_text(
        encoding="utf-8", errors="ignore")
    assert "SkipBundledDb" in s
    assert "POLYXRD_NO_BUNDLE_DB" in s
    assert "$metaNames" in s, "内置库校验仍只看第一个 meta.json"


def test_verify_installer_has_no_bundled_db():
    s = (ROOT / "scripts" / "verify_installer.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "--no-bundled-db" in s
    assert "expect_bundled" in s


def test_build_bat_no_bundle_flow():
    s = (ROOT / "build.bat").read_text(encoding="utf-8", errors="ignore")
    assert "skip_bundle_db" in s
    assert "SkipBundledDb" in s


def test_bench_script_no_removed_api():
    s = (ROOT / "scripts" / "bench_polydb_search.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "identify_with_cod_inorganics" not in s
    assert "identify_with_polydb" in s


def test_mount_partial_i18n_keys_exist():
    from polyxrd.i18n.translations import en_US, ja_JP, zh_CN

    def flatten(d, prefix=""):
        out = set()
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            out |= flatten(v, key) if isinstance(v, dict) else {key}
        return out

    def find(mod):
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, dict) and obj and all(
                    isinstance(v, (str, dict)) for v in obj.values()):
                return flatten(obj)
        raise AssertionError(mod.__name__)

    for mod in (zh_CN, en_US, ja_JP):
        keys = find(mod)
        assert "db_manager.mount_partial_title" in keys
        assert "db_manager.mount_partial_body" in keys
