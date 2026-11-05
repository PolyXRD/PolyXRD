"""
AppConfig 数据库路径持久化测试
=============================
所有外挂库的挂载点**共用** ``~/.polyxrd/user_db_paths.json``。历史上暴露过
两个真实缺陷：

1. 某个库的 setter 整体覆盖写文件 → 抹掉别的库已保存的键；
2. setter 写了但 getter 不回读 → 死 setter。

本文件把这两条钉成回归守卫。v5.2 起 PDF2-2004 不再是独立 sqlite 槽位，而是
polyDB 的第三个变体（``pdf2-2004`` → ``pdf2_polydb_path``），"多键共存"的
验证就落在三个变体之间 —— 它们同样走 ``_update_user_db_path`` 的增量合并。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.config import AppConfig


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """AppConfig 实例, user_db_paths.json 重定向到 tmp_path。

    同时关掉"自动发现默认库"：开发机 ``cod_data/PDF2-2004.polyDB`` 真实存在，
    不隔离的话"未挂载应为 None"一类断言会被它顶掉。
    """
    c = AppConfig()
    fake = tmp_path / "user_db_paths.json"
    monkeypatch.setattr(c, "_user_db_paths_file", lambda: fake)
    monkeypatch.setattr(c, "discover_polydb", lambda variant="cod-inorg": None)
    return c


def _read(c: AppConfig) -> dict:
    f = c._user_db_paths_file()
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


def _mkdb(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text('{"format":"polyDB","schema_version":1}',
                                 encoding="utf-8")
    (d / "index.sqlite").write_bytes(b"x")
    return d


# ── 基本读写往返 ─────────────────────────────────────────────

def test_pdf2_variant_set_get_roundtrip(cfg, tmp_path):
    db = _mkdb(tmp_path, "PDF2-2004.polyDB")
    cfg.set_polydb_path(db, variant="pdf2-2004")
    assert cfg.get_polydb_path("pdf2-2004") == db.resolve()
    assert _read(cfg)["pdf2_polydb_path"] == str(db.resolve())


def test_pdf2_variant_falls_back_to_discovery(cfg):
    assert cfg.get_polydb_path("pdf2-2004") is None


def test_pdf2_variant_falls_back_when_persisted_path_missing(cfg, tmp_path):
    """持久化路径已不存在 → 回退自动发现（此处被隔离为 None）。"""
    cfg.set_polydb_path(tmp_path / "gone.polyDB", variant="pdf2-2004")
    assert cfg.get_polydb_path("pdf2-2004") is None


def test_pdf2_variant_clear_reverts_to_discovery(cfg, tmp_path):
    db = _mkdb(tmp_path, "PDF2-2004.polyDB")
    cfg.set_polydb_path(db, variant="pdf2-2004")
    cfg.set_polydb_path(None, variant="pdf2-2004")
    assert "pdf2_polydb_path" not in _read(cfg)
    assert cfg.get_polydb_path("pdf2-2004") is None


# ── 多个 key 共存 (核心回归) ─────────────────────────────────

def test_set_pdf2_variant_does_not_wipe_cod(cfg, tmp_path):
    """回归: 挂载 PDF2 不得抹掉已保存的 COD 路径。"""
    cod = _mkdb(tmp_path, "COD-Inorg-x.polyDB")
    pdf2 = _mkdb(tmp_path, "PDF2-2004.polyDB")

    cfg.set_polydb_path(cod, variant="cod-inorg")
    cfg.set_polydb_path(pdf2, variant="pdf2-2004")

    data = _read(cfg)
    assert data["polydb_inorg_path"] == str(cod.resolve())
    assert data["pdf2_polydb_path"] == str(pdf2.resolve())
    assert cfg.get_polydb_path("cod-inorg") == cod.resolve()
    assert cfg.get_polydb_path("pdf2-2004") == pdf2.resolve()


def test_clear_cod_keeps_pdf2(cfg, tmp_path):
    """回归: 清除某个变体只删自己的 key, 不写空 {}。"""
    cod = _mkdb(tmp_path, "COD-Inorg-z.polyDB")
    pdf2 = _mkdb(tmp_path, "PDF2-2004.polyDB")

    cfg.set_polydb_path(cod, variant="cod-inorg")
    cfg.set_polydb_path(pdf2, variant="pdf2-2004")
    cfg.set_polydb_path(None, variant="cod-inorg")

    data = _read(cfg)
    assert "polydb_inorg_path" not in data
    assert data["pdf2_polydb_path"] == str(pdf2.resolve())
    assert cfg.get_polydb_path("pdf2-2004") == pdf2.resolve()


# ── 容错 ─────────────────────────────────────────────────────

def test_corrupt_json_recovers(cfg, tmp_path):
    """文件损坏 → 读写不抛异常, 且能被下一次写入修复。"""
    f = cfg._user_db_paths_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{ not json", encoding="utf-8")

    assert cfg.get_polydb_path("pdf2-2004") is None

    db = _mkdb(tmp_path, "PDF2-2004.polyDB")
    cfg.set_polydb_path(db, variant="pdf2-2004")
    assert cfg.get_polydb_path("pdf2-2004") == db.resolve()


def test_non_dict_json_recovers(cfg):
    f = cfg._user_db_paths_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("[1, 2, 3]", encoding="utf-8")
    assert cfg.get_polydb_path("pdf2-2004") is None


# ── 变体表与发现关键字 ───────────────────────────────────────

def test_pdf2_variant_registered():
    """PDF2 必须有独立的槽位键与目录名提示，否则装不上也发现不了。"""
    assert AppConfig.POLYDB_VARIANTS["pdf2-2004"] == "pdf2_polydb_path"
    assert "pdf2" in AppConfig._POLYDB_NAME_HINTS["pdf2-2004"]


def test_user_db_dir_is_under_home():
    """兜底目录必须在用户家目录下 —— 安装目录 Program Files 不可写。"""
    assert AppConfig().user_db_dir() == Path.home() / ".polyxrd" / "cif_db"
