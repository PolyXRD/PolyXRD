"""默认参考库 (polyDB) 的发现与挂载语义 (v4.1.0)
===============================================

v4.1.0 起 polyDB 的 **COD-Inorg 变体就是默认参考库**: 便携版把库放在
``<exe>/databases/`` 下, 解压即用, 不需要用户先手工挂载。本文件钉住四条:

1. **自动发现优先取最新快照** —— 同名目录 ``COD-Inorg-20261021.polyDB`` 与
   ``-20261020`` 并存时取字串序最大 (日期后缀即时间序);
2. **``meta.json`` 的 variant 是主判据**, 文件名只是兜底 —— 有人把目录改名也
   不该串门 (无机库被当成全库是最坏的错法: 检索结果少一大截却毫无提示);
3. **显式挂载压过自动发现**;
4. **取消挂载要"记住了"** —— 否则下次启动又被自动发现顶回来, 用户以为卸载没用;
   但显式挂载一次就清掉这条记忆。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config   # noqa: E402


def _polydb(root: Path, name: str, variant: str = "cod-inorg") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    meta = {"format": "polyDB", "schema_version": 1, "variant": variant,
            "counts": {"phases": 10, "k": 100, "peaks": 1000, "sites": 50}}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "index.sqlite").write_bytes(b"")
    return d


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """配置隔离 + 把"默认库候选目录"指到临时目录 (与开发机产物无关)。"""
    monkeypatch.setattr(AppConfig, "_user_db_paths_file",
                        lambda self: tmp_path / "user_db_paths.json")
    libs = tmp_path / "databases"
    libs.mkdir()
    monkeypatch.setenv("POLYXRD_POLYDB_DIR", str(libs))
    monkeypatch.setattr(AppConfig, "_polydb_search_roots",
                        lambda self: [libs])
    return get_config(), libs


# ── 1. 自动发现 ─────────────────────────────────────────────

def test_nothing_found_returns_none(cfg):
    config, _libs = cfg
    assert config.discover_polydb("cod-inorg") is None
    assert config.get_polydb_path("cod-inorg") is None


def test_discovers_by_meta_variant(cfg):
    config, libs = cfg
    d = _polydb(libs, "SomeRandomName.polyDB", variant="cod-inorg")
    assert config.discover_polydb("cod-inorg") == d


def test_newest_snapshot_wins(cfg):
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261020.polyDB")
    newest = _polydb(libs, "COD-Inorg-20261021.polyDB")
    assert config.discover_polydb("cod-inorg") == newest


def test_variants_do_not_cross(cfg):
    """无机库绝不能被当成全库 (反之亦然)。"""
    config, libs = cfg
    inorg = _polydb(libs, "COD-Inorg-20261021.polyDB", variant="cod-inorg")
    full = _polydb(libs, "COD-Full-20261021.polyDB", variant="cod-full")
    assert config.discover_polydb("cod-inorg") == inorg
    assert config.discover_polydb("cod-full") == full


def test_meta_variant_beats_filename(cfg):
    """目录名写错也能靠 meta 认出来 —— 反例: 名字像全库、meta 说无机。"""
    config, libs = cfg
    d = _polydb(libs, "COD-Full-wrong-name.polyDB", variant="cod-inorg")
    assert config.discover_polydb("cod-inorg") == d
    assert config.discover_polydb("cod-full") is None


def test_filename_hint_used_when_meta_unreadable(cfg):
    """meta 坏掉时退回文件名判据 (容错, 不让用户面对"库不见了")。"""
    config, libs = cfg
    d = _polydb(libs, "COD-Inorg-broken.polyDB")
    (d / "meta.json").write_text("{not json", encoding="utf-8")
    assert config.discover_polydb("cod-inorg") == d


def test_unknown_variant_returns_none(cfg):
    config, _libs = cfg
    assert config.discover_polydb("cod-organic") is None
    assert config.get_polydb_path("cod-organic") is None


def test_shipped_dir_is_itself_a_polydb(cfg):
    """候选目录本身就是一个 polyDB 时也要认 (便携版直接放 databases/ 的写法)。"""
    config, libs = cfg
    meta = {"format": "polyDB", "schema_version": 1, "variant": "cod-inorg",
            "counts": {"phases": 3}}
    (libs / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (libs / "index.sqlite").write_bytes(b"")
    assert config.discover_polydb("cod-inorg") == libs


# ── 2. 挂载优先级 ───────────────────────────────────────────

def test_user_mount_beats_auto_discovery(cfg, tmp_path):
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    mine = _polydb(tmp_path / "mine", "My.polyDB", variant="cod-inorg")
    config.set_polydb_path(mine, "cod-inorg")
    assert config.get_polydb_path("cod-inorg") == mine


def test_unmounted_variant_is_remembered(cfg):
    """取消挂载后不再自动发现 —— 否则"卸载不掉"。"""
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    assert config.get_polydb_path("cod-inorg") is not None

    config.set_polydb_path(None, "cod-inorg")
    assert config.get_polydb_path("cod-inorg") is None
    assert config._load_user_db_paths().get("polydb_disabled") == ["cod-inorg"]

    # 另一个变体不受牵连
    _polydb(libs, "COD-Full-20261021.polyDB", variant="cod-full")
    assert config.get_polydb_path("cod-full") is not None


def test_remount_clears_disabled_flag(cfg, tmp_path):
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    config.set_polydb_path(None, "cod-inorg")
    mine = _polydb(tmp_path / "mine", "My.polyDB", variant="cod-inorg")
    config.set_polydb_path(mine, "cod-inorg")
    assert config.get_polydb_path("cod-inorg") == mine
    assert config._load_user_db_paths().get("polydb_disabled") is None


def test_both_variants_can_be_disabled(cfg):
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    _polydb(libs, "COD-Full-20261021.polyDB", variant="cod-full")
    config.set_polydb_path(None, "cod-inorg")
    config.set_polydb_path(None, "cod-full")
    assert config._load_user_db_paths().get("polydb_disabled") == [
        "cod-inorg", "cod-full"]
    assert config.get_polydb_path("cod-inorg") is None
    assert config.get_polydb_path("cod-full") is None


def test_disabled_list_has_no_duplicates(cfg):
    """重复取消挂载不该把变体名堆成 ['cod-inorg', 'cod-inorg']。"""
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    for _ in range(3):
        config.set_polydb_path(None, "cod-inorg")
    assert config._load_user_db_paths().get("polydb_disabled") == ["cod-inorg"]


def test_mount_path_must_be_a_directory(cfg, tmp_path):
    """挂一个文件 (而不是目录) 时按未挂载处理, 不抱住死路径。"""
    config, _libs = cfg
    f = tmp_path / "not_a_dir.polyDB"
    f.write_bytes(b"x")
    config.set_polydb_path(f, "cod-inorg")
    assert config.get_polydb_path("cod-inorg") is None


def test_stale_mount_path_falls_back_to_default(cfg, tmp_path):
    """用户挂载的库**被挪走**后要回退到自动发现的默认库。

    这是 v4.1.0「解压便携版就能检索」的核心承诺: 便携版把库放在
    ``<exe>/databases/``, 但用户配置里可能还留着上一份外挂库的路径
    (换了机器 / 挪了目录 / 删了旧库)。那条路径失效时若直接报"没有库",
    用户看到的就是"解压了却检索不了" —— 必须回退到内置库。
    """
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    gone = tmp_path / "moved_away.polyDB"
    config.set_polydb_path(gone, "cod-inorg")
    # 目录此刻还不存在 —— 模拟"用户把外挂库挪走了"
    assert config.get_polydb_path("cod-inorg") == libs / "COD-Inorg-20261021.polyDB"


def test_stale_mount_path_falls_back_even_if_it_existed_once(cfg, tmp_path):
    """路径曾经有效、现在被删掉 —— 同样要回退, 不能抱住死路径。"""
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    mine = _polydb(tmp_path / "mine", "My.polyDB", variant="cod-inorg")
    config.set_polydb_path(mine, "cod-inorg")
    assert config.get_polydb_path("cod-inorg") == mine

    # 用户删掉了自己的库
    for child in mine.iterdir():
        child.unlink()
    mine.rmdir()
    assert config.get_polydb_path("cod-inorg") == libs / "COD-Inorg-20261021.polyDB"


def test_stale_mount_path_does_not_resurrect_disabled_flag(cfg, tmp_path):
    """路径失效 ≠ 用户取消挂载: 回退到默认库时不得顺手清掉 disabled 标记。

    反过来也成立: 用户显式取消挂载后, 即使配置里还留着旧路径,
    也不能被自动发现顶回来 (否则界面上表现为"卸载不掉")。
    """
    config, libs = cfg
    _polydb(libs, "COD-Inorg-20261021.polyDB")
    gone = tmp_path / "moved_away.polyDB"
    config.set_polydb_path(gone, "cod-inorg")
    config.set_polydb_path(None, "cod-inorg")
    assert config.get_polydb_path("cod-inorg") is None
    assert config._load_user_db_paths().get("polydb_disabled") == ["cod-inorg"]


def test_set_unknown_variant_raises(cfg):
    config, _libs = cfg
    with pytest.raises(ValueError):
        config.set_polydb_path(None, "cod-organic")
