"""v0.13.0 启动健壮性护栏
=========================

两类缺陷的回归:

1. **打包后往安装目录写库** —— `get_cod_root()` 的 Phase 3 兜底会
   `mkdir <install>/cod`, 紧接着 `CODLocalDatabase` 就在安装目录里
   connect 出一个 **0 条目的空 cod_index.sqlite** (2026-09-17 实测 60 KB)。
   装到 Program Files 时普通用户还写不进去。空库一旦存在, 旧版
   `_bundled_cod_db_source()` 的开发模式兜底又会把它当成"随包索引"
   复制进用户目录, 把真库永久顶掉。
2. **GUI 子系统下启动异常静默消失** —— 打包版没有控制台, 未捕获异常
   只让进程无声退出 (用户看到的就是"双击打不开"、无任何提示)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from polyxrd.services import cod_local


# ── 安装目录识别 ─────────────────────────────────────────────

@pytest.fixture()
def fake_install(tmp_path, monkeypatch):
    """伪造"打包运行": sys.frozen=True + exe 在 tmp/<install>/PolyXRD.exe。"""
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "PolyXRD.exe"),
                        raising=False)
    return install


def test_app_dir_none_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert cod_local.app_dir() is None
    # 非打包时一律不拦 (开发树里的 cod/ 与 cod_index.sqlite 必须照旧可用)
    assert cod_local.is_inside_app_dir(Path(r"D:/ExternalOutsideApp/cod")) is False


def test_is_inside_app_dir(fake_install):
    assert cod_local.is_inside_app_dir(fake_install / "cod") is True
    assert cod_local.is_inside_app_dir(fake_install / "cod_index.sqlite") is True
    assert cod_local.is_inside_app_dir(fake_install.parent / "elsewhere") is False


# ── 不再把安装目录里的残留当"随包索引" ───────────────────────

def test_bundled_source_ignores_install_dir_when_frozen(fake_install):
    """安装目录里的 cod_index.sqlite 是运行时产物, 不能当随包资源。"""
    stray = fake_install / "cod_index.sqlite"
    stray.write_bytes(b"x" * 128)
    assert cod_local._bundled_cod_db_source() is None


def test_bundled_source_still_uses_dev_tree(monkeypatch):
    """源码模式下项目根的 cod_index.sqlite 仍要能被找到 (部署路径依赖它)。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    src = cod_local._bundled_cod_db_source()
    assert src is not None and src.name == "cod_index.sqlite"


# ── 索引库路径不再落在安装目录 ───────────────────────────────

@pytest.fixture()
def no_cod_data_candidates(monkeypatch):
    """屏蔽 cod_data/ 候选。

    v0.13.2 起 `_cod_data_index_candidates()` 会把开发树里真实存在的
    ``<root>/cod_data/cod_index.sqlite`` (431 MB) 当作候选, 这会干扰下面
    两个"隔离环境里的行为"断言 —— 这两个测试要验证的是**候选都没有时**
    的兜底次序, 所以把该来源显式关掉。
    """
    monkeypatch.setattr(cod_local, "_cod_data_index_candidates", lambda: [])


def test_index_db_path_avoids_install_dir(fake_install, monkeypatch,
                                          no_cod_data_candidates):
    """cod_root 在安装目录且无索引 → 退回 resolved_index_db_path(), 不在原地建库。"""
    cod_root = fake_install / "cod"
    sentinel = fake_install.parent / "user_cod_index.sqlite"
    monkeypatch.setattr(cod_local, "resolved_index_db_path",
                        lambda deploy=True: sentinel)
    got = cod_local._index_db_path(cod_root)
    assert got == sentinel
    assert not (fake_install / "cod_index.sqlite").exists()


def test_index_db_path_keeps_existing_index(fake_install):
    """随包/便携布局: 安装目录里**确实存在**的索引要继续用 (可移植性)。"""
    cod_root = fake_install / "cod"
    cod_root.mkdir()
    idx = fake_install / "cod_index.sqlite"
    idx.write_bytes(b"real index")
    assert cod_local._index_db_path(cod_root) == idx


def test_index_db_path_outside_install_unchanged(tmp_path, fake_install,
                                                 no_cod_data_candidates):
    """安装目录之外的 cod_root 行为保持不变 (源码树的 <root>/cod)。"""
    other = tmp_path / "tree" / "cod"
    other.mkdir(parents=True)
    assert cod_local._index_db_path(other) == tmp_path / "tree" / "cod_index.sqlite"


# ── v0.13.2: 索引与另两库同放 cod_data/ 也能被找到 ────────────

def test_cod_data_candidates_include_project_layout():
    """cod_data/ 是三库统一目录, 必须是索引的一等候选 (体积门槛内)。"""
    cands = cod_local._cod_data_index_candidates()
    assert cands, "至少要有 <root>/cod_data/cod_index.sqlite 这条候选"
    assert any(c.parent.name == "cod_data" for c in cands)


def test_index_db_path_falls_back_to_cod_data(fake_install, monkeypatch,
                                              tmp_path):
    """项目根没有索引、但 cod_data/ 里有 → 返回 cod_data 的那个,
    而不是返回一个不存在的路径 (否则调用方 connect() 会在那里凭空建空库)。"""
    monkeypatch.setattr(cod_local.AppConfig, "_PROJECT_ROOT", tmp_path / "root")
    data_idx = tmp_path / "root" / "cod_data" / "cod_index.sqlite"
    data_idx.parent.mkdir(parents=True)
    data_idx.write_bytes(b"x" * (cod_local._MIN_VALID_DB_BYTES + 1))
    got = cod_local._index_db_path(tmp_path / "root" / "cod")
    assert got == data_idx


# ── get_cod_root 的兜底不落到安装目录 ────────────────────────

def test_get_cod_root_fallback_skips_install_dir(fake_install, monkeypatch, tmp_path):
    """Phase 3 兜底必须跳过安装目录 (否则凭空 mkdir 出 <install>/cod)。"""
    user_cif = tmp_path / "user_cif_db"
    monkeypatch.setattr(cod_local.AppConfig, "_PROJECT_ROOT", fake_install)
    monkeypatch.setattr(
        cod_local, "get_config",
        lambda: type("C", (), {
            "get_cod_index_sqlite_path": lambda self: None,
            "get_cif_db_path": lambda self: fake_install / "cod_data" / "cif_db",
            "user_db_dir": lambda self: user_cif,
        })(),
    )
    root = cod_local.get_cod_root()
    assert not cod_local.is_inside_app_dir(root), f"不该落到安装目录: {root}"
    assert root == user_cif / "cod" and root.exists()


# ── 启动日志 / 崩溃日志 ──────────────────────────────────────

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
