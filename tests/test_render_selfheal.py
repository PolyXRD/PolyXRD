"""v2.0.1 崩溃自愈 (跨启动保守渲染回退) 的纯逻辑单测。

不真的开窗口/进事件循环 —— 只测 main.py 里的状态读写与"何时自动进安全渲染"。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("POLYXRD_NO_HARD_EXIT", "1")

import polyxrd.main as main_mod  # noqa: E402

_QTVARS = ("QT_OPENGL", "QT_QPA_PLATFORM", "QT_ENABLE_HIGHDPI_SCALING")


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv(main_mod._RENDER_STATE_ENV, str(tmp_path / "render_state.json"))


def test_state_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert main_mod._read_render_pending() is False          # 文件不存在 = 健康
    main_mod._write_render_state(True, safe_render=False)
    assert main_mod._read_render_pending() is True
    main_mod._write_render_state(False, safe_render=True)
    assert main_mod._read_render_pending() is False
    data = json.loads((tmp_path / "render_state.json").read_text(encoding="utf-8"))
    assert data["pending"] is False
    assert data["safe_render"] is True


def test_auto_safe_only_when_pending(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for v in _QTVARS:
        monkeypatch.delenv(v, raising=False)

    # 无 pending -> 什么都不做, 不得污染环境
    assert main_mod._auto_safe_render_if_needed() is False
    assert "QT_OPENGL" not in os.environ

    # 有 pending (上次崩了) -> 自动启用保守渲染
    main_mod._write_render_state(True, safe_render=False)
    assert main_mod._auto_safe_render_if_needed() is True
    assert os.environ["QT_OPENGL"] == "software"
    assert os.environ["QT_QPA_PLATFORM"] == "windows:darkmode=0"
    assert os.environ["QT_ENABLE_HIGHDPI_SCALING"] == "0"


def test_auto_safe_respects_user_env(tmp_path, monkeypatch):
    """setdefault 语义: 用户显式设的值不被自愈覆盖。"""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("QT_OPENGL", "desktop")
    main_mod._write_render_state(True, safe_render=False)
    assert main_mod._auto_safe_render_if_needed() is True
    assert os.environ["QT_OPENGL"] == "desktop"


def test_reset_clears_state(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    main_mod._write_render_state(True, safe_render=True)
    assert main_mod._reset_render_state() == 0
    assert main_mod._read_render_pending() is False


def test_corrupt_state_is_treated_as_healthy(tmp_path, monkeypatch):
    """状态文件损坏绝不能拦住启动 —— 当作"健康"。"""
    p = tmp_path / "render_state.json"
    p.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv(main_mod._RENDER_STATE_ENV, str(p))
    assert main_mod._read_render_pending() is False
