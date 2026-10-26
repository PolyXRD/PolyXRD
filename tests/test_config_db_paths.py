"""
AppConfig 数据库路径持久化测试
=============================
PDF2-2004 sqlite、polyDB 挂载点等多个库的路径**共用**
``~/.polyxrd/user_db_paths.json``。历史上暴露过两个真实缺陷：

1. 某个库的 setter 整体覆盖写文件 → 抹掉别的库已保存的键；
2. ``get_pdf2_db_path()`` 不回读用户设置 → ``set_pdf2_db_path()`` 是死 setter。

本文件把这两条钉成回归守卫。v4.2.0 起本地 COD sqlite 运行时被删除
（``cod_db_path`` / ``cod_index_db_path`` 两个键不再存在），"多键共存"
的验证改用 polyDB 挂载槽位（``polydb_inorg_path``）承担 —— 它同样走
``_update_user_db_path`` 的增量合并路径，语义完全一致。
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
    """AppConfig 实例, user_db_paths.json 重定向到 tmp_path。"""
    c = AppConfig()
    fake = tmp_path / "user_db_paths.json"
    monkeypatch.setattr(c, "_user_db_paths_file", lambda: fake)
    return c


def _read(c: AppConfig) -> dict:
    f = c._user_db_paths_file()
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


# ── 基本读写往返 ─────────────────────────────────────────────

def test_pdf2_set_get_roundtrip(cfg, tmp_path):
    db = tmp_path / "pdf2.sqlite"
    db.write_bytes(b"x")
    cfg.set_pdf2_db_path(db)
    assert cfg.get_pdf2_db_path() == db.resolve()
    assert _read(cfg)["pdf2_db_path"] == str(db.resolve())


def test_pdf2_falls_back_to_default_when_unset(cfg):
    assert cfg.get_pdf2_db_path() == cfg.pdf2_db_path


def test_pdf2_falls_back_when_persisted_path_missing(cfg, tmp_path):
    """持久化路径已不存在 → 回退默认。"""
    cfg.set_pdf2_db_path(tmp_path / "gone.sqlite")
    assert cfg.get_pdf2_db_path() == cfg.pdf2_db_path


def test_pdf2_clear_reverts_to_default(cfg, tmp_path):
    db = tmp_path / "pdf2.sqlite"
    db.write_bytes(b"x")
    cfg.set_pdf2_db_path(db)
    cfg.set_pdf2_db_path("")
    assert cfg.get_pdf2_db_path() == cfg.pdf2_db_path
    assert "pdf2_db_path" not in _read(cfg)


# ── 多个 key 共存 (核心回归) ─────────────────────────────────

def test_set_polydb_does_not_wipe_pdf2(cfg, tmp_path):
    """回归: 挂载 polyDB 不得抹掉已保存的 PDF2 路径。"""
    pdf2 = tmp_path / "pdf2.sqlite"
    pdf2.write_bytes(b"x")
    polydb = tmp_path / "COD-Inorg-x"
    (polydb / "sub").mkdir(parents=True)

    cfg.set_pdf2_db_path(pdf2)
    cfg.set_polydb_path(polydb, variant="cod-inorg")

    data = _read(cfg)
    assert data["pdf2_db_path"] == str(pdf2.resolve())
    assert data["polydb_inorg_path"] == str(polydb.resolve())
    assert cfg.get_pdf2_db_path() == pdf2.resolve()
    assert cfg.get_polydb_path("cod-inorg") == polydb.resolve()


def test_set_pdf2_does_not_wipe_polydb(cfg, tmp_path):
    pdf2 = tmp_path / "pdf2.sqlite"
    pdf2.write_bytes(b"x")
    polydb = tmp_path / "COD-Inorg-y"
    (polydb / "sub").mkdir(parents=True)

    cfg.set_polydb_path(polydb, variant="cod-inorg")
    cfg.set_pdf2_db_path(pdf2)

    data = _read(cfg)
    assert data["polydb_inorg_path"] == str(polydb.resolve())
    assert data["pdf2_db_path"] == str(pdf2.resolve())


def test_clear_polydb_keeps_pdf2(cfg, tmp_path):
    """回归: 清除某个库的自定义路径只删自己的 key, 不写空 {}。"""
    pdf2 = tmp_path / "pdf2.sqlite"
    pdf2.write_bytes(b"x")
    polydb = tmp_path / "COD-Inorg-z"
    (polydb / "sub").mkdir(parents=True)

    cfg.set_pdf2_db_path(pdf2)
    cfg.set_polydb_path(polydb, variant="cod-inorg")
    cfg.set_polydb_path(None, variant="cod-inorg")

    data = _read(cfg)
    assert "polydb_inorg_path" not in data
    assert data["pdf2_db_path"] == str(pdf2.resolve())
    assert cfg.get_pdf2_db_path() == pdf2.resolve()


# ── 容错 ─────────────────────────────────────────────────────

def test_corrupt_json_recovers(cfg, tmp_path):
    """文件损坏 → 读写不抛异常, 且能被下一次写入修复。"""
    f = cfg._user_db_paths_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{ not json", encoding="utf-8")

    assert cfg.get_pdf2_db_path() == cfg.pdf2_db_path

    db = tmp_path / "pdf2.sqlite"
    db.write_bytes(b"x")
    cfg.set_pdf2_db_path(db)
    assert cfg.get_pdf2_db_path() == db.resolve()


def test_non_dict_json_recovers(cfg):
    f = cfg._user_db_paths_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("[1, 2, 3]", encoding="utf-8")
    assert cfg.get_pdf2_db_path() == cfg.pdf2_db_path


# ── 用户目录兜底 (0.10.0 数据库外挂) ─────────────────────────

class _FakeCfg(AppConfig):
    """把默认位置与用户目录都指到 tmp, 用于验证优先级。"""

    def __init__(self, default_dir: Path, user_dir: Path):
        super().__init__()
        self.pdf2_db_path = default_dir / "PDF2_2004.sqlite"
        self._user_dir = user_dir

    def user_db_dir(self) -> Path:
        return self._user_dir


@pytest.fixture
def fake_cfg(tmp_path, monkeypatch):
    """构造 fake_cfg 并把 user_db_paths.json 也重定向到 tmp。"""
    def _build(default_dir: Path, user_dir: Path):
        c = _FakeCfg(default_dir, user_dir)
        monkeypatch.setattr(c, "_user_db_paths_file",
                            lambda: tmp_path / "user_db_paths.json")
        return c
    return _build


def test_user_dir_fallback_used_when_default_absent(fake_cfg, tmp_path):
    """安装目录里没有库时, 用户目录 (~/.polyxrd/cif_db) 里的库应被自动发现。"""
    default_dir, user_dir = tmp_path / "install", tmp_path / "userdir"
    user_dir.mkdir(parents=True)
    (user_dir / "PDF2_2004.sqlite").write_bytes(b"x")
    c = fake_cfg(default_dir, user_dir)

    assert c.get_pdf2_db_path() == user_dir / "PDF2_2004.sqlite"


def test_default_wins_over_user_dir(fake_cfg, tmp_path):
    """开发/内嵌整包场景: 默认位置存在时不该被用户目录里的同名旧库顶掉。"""
    default_dir, user_dir = tmp_path / "install", tmp_path / "userdir"
    default_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    (default_dir / "PDF2_2004.sqlite").write_bytes(b"new")
    (user_dir / "PDF2_2004.sqlite").write_bytes(b"old")
    c = fake_cfg(default_dir, user_dir)

    assert c.get_pdf2_db_path() == default_dir / "PDF2_2004.sqlite"


def test_user_import_beats_both(fake_cfg, tmp_path):
    """GUI 导入的路径优先级最高。"""
    default_dir, user_dir = tmp_path / "install", tmp_path / "userdir"
    default_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    (default_dir / "PDF2_2004.sqlite").write_bytes(b"new")
    (user_dir / "PDF2_2004.sqlite").write_bytes(b"old")
    imported = tmp_path / "imported.sqlite"
    imported.write_bytes(b"imported")
    c = fake_cfg(default_dir, user_dir)
    c.set_pdf2_db_path(imported)

    assert c.get_pdf2_db_path() == imported.resolve()


def test_user_db_dir_is_under_home():
    """兜底目录必须在用户家目录下 —— 安装目录 Program Files 不可写。"""
    assert AppConfig().user_db_dir() == Path.home() / ".polyxrd" / "cif_db"
