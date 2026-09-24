"""
AppConfig 数据库路径持久化测试
=============================
COD 与 PDF2-2004 两个库的路径**共用** ~/.polyxrd/user_db_paths.json。
PDF2 键是后加的, 曾暴露两个真实缺陷:

1. set_cod_db_path() 整体覆盖写文件 → 抹掉 pdf2_db_path
2. get_pdf2_db_path() 不回读用户设置 → set_pdf2_db_path() 是死 setter

本文件把这两条钉成回归守卫。
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
    """持久化路径已不存在 → 回退默认 (与 COD 行为一致)。"""
    cfg.set_pdf2_db_path(tmp_path / "gone.sqlite")
    assert cfg.get_pdf2_db_path() == cfg.pdf2_db_path


def test_pdf2_clear_reverts_to_default(cfg, tmp_path):
    db = tmp_path / "pdf2.sqlite"
    db.write_bytes(b"x")
    cfg.set_pdf2_db_path(db)
    cfg.set_pdf2_db_path("")
    assert cfg.get_pdf2_db_path() == cfg.pdf2_db_path
    assert "pdf2_db_path" not in _read(cfg)


# ── 两个 key 共存 (核心回归) ─────────────────────────────────

def test_set_cod_does_not_wipe_pdf2(cfg, tmp_path):
    """回归: 设置 COD 路径不得抹掉已保存的 PDF2 路径。"""
    pdf2 = tmp_path / "pdf2.sqlite"
    pdf2.write_bytes(b"x")
    cod = tmp_path / "cod.sqlite"
    cod.write_bytes(b"y")

    cfg.set_pdf2_db_path(pdf2)
    cfg.set_cod_db_path(cod)

    data = _read(cfg)
    assert data["pdf2_db_path"] == str(pdf2.resolve())
    assert data["cod_db_path"] == str(cod.resolve())
    assert cfg.get_pdf2_db_path() == pdf2.resolve()
    assert cfg.get_cod_db_path() == cod.resolve()


def test_set_pdf2_does_not_wipe_cod(cfg, tmp_path):
    cod = tmp_path / "cod.sqlite"
    cod.write_bytes(b"y")
    pdf2 = tmp_path / "pdf2.sqlite"
    pdf2.write_bytes(b"x")

    cfg.set_cod_db_path(cod)
    cfg.set_pdf2_db_path(pdf2)

    data = _read(cfg)
    assert data["cod_db_path"] == str(cod.resolve())
    assert data["pdf2_db_path"] == str(pdf2.resolve())


def test_clear_cod_keeps_pdf2(cfg, tmp_path):
    """回归: 清除 COD 自定义路径只删自己的 key, 不写空 {}。"""
    pdf2 = tmp_path / "pdf2.sqlite"
    pdf2.write_bytes(b"x")
    cod = tmp_path / "cod.sqlite"
    cod.write_bytes(b"y")

    cfg.set_pdf2_db_path(pdf2)
    cfg.set_cod_db_path(cod)
    cfg.set_cod_db_path("")

    data = _read(cfg)
    assert "cod_db_path" not in data
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
        self.cod_db_path = default_dir / "COD_inorganics.sqlite"
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
    (user_dir / "COD_inorganics.sqlite").write_bytes(b"x")
    c = fake_cfg(default_dir, user_dir)

    assert c.get_cod_db_path() == user_dir / "COD_inorganics.sqlite"
    # 另一个库没放进用户目录 → 仍回退默认 (即使不存在)
    assert c.get_pdf2_db_path() == default_dir / "PDF2_2004.sqlite"


def test_default_wins_over_user_dir(fake_cfg, tmp_path):
    """开发/内嵌整包场景: 默认位置存在时不该被用户目录里的同名旧库顶掉。"""
    default_dir, user_dir = tmp_path / "install", tmp_path / "userdir"
    default_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    (default_dir / "COD_inorganics.sqlite").write_bytes(b"new")
    (user_dir / "COD_inorganics.sqlite").write_bytes(b"old")
    c = fake_cfg(default_dir, user_dir)

    assert c.get_cod_db_path() == default_dir / "COD_inorganics.sqlite"


def test_user_import_beats_both(fake_cfg, tmp_path):
    """GUI 导入的路径优先级最高。"""
    default_dir, user_dir = tmp_path / "install", tmp_path / "userdir"
    default_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    (default_dir / "COD_inorganics.sqlite").write_bytes(b"new")
    (user_dir / "COD_inorganics.sqlite").write_bytes(b"old")
    imported = tmp_path / "imported.sqlite"
    imported.write_bytes(b"imported")
    c = fake_cfg(default_dir, user_dir)
    c.set_cod_db_path(imported)

    assert c.get_cod_db_path() == imported.resolve()


def test_user_db_dir_is_under_home():
    """兜底目录必须在用户家目录下 —— 安装目录 Program Files 不可写。"""
    assert AppConfig().user_db_dir() == Path.home() / ".polyxrd" / "cif_db"
