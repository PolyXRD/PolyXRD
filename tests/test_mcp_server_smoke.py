"""C 组工程: MCP server 冒烟测试.

背景: src/polyxrd/mcp_server/ 暴露 18 个 @mcp.tool(), 但仅 save/load_project
有覆盖 (test_project_roundtrip_v21.py), 覆盖率 ~11%. 本文件对每个工具做最小
冒烟: (a) 无数据时的错误路径返回合法 JSON; (b) 有合成数据时的快乐路径返回
预期字段; (c) server 实例元数据与工具注册完整.

设计:
- 不依赖外部 COD 在线 / 大数据库, 全部走合成 .xy 文件 + 内置 phase 库;
- 单例 session 在每个测试前 reset(), 避免相互污染;
- mcp 包未安装时整文件 skip (pyproject.toml [project.optional-dependencies].mcp).
"""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None,
    reason="mcp 包未安装 (pip install -e .[mcp])",
)


# ── 合成数据 fixture ───────────────────────────────────────────────

def _synth_xy_content(n: int = 200) -> str:
    """合成 .xy 内容: 10-80° 区间, 在 26.6/31.7/45.4° 各放一个高斯峰."""
    tt = np.linspace(10.0, 80.0, n)
    y = np.full_like(tt, 5.0)
    for center, amp, fwhm in ((26.6, 100.0, 0.25), (31.7, 60.0, 0.25),
                              (45.4, 30.0, 0.25)):
        sigma = fwhm / 2.355
        y += amp * np.exp(-0.5 * ((tt - center) / sigma) ** 2)
    rng = np.random.default_rng(42)
    y += rng.normal(0, 0.5, n)
    y = np.clip(y, 0, None)
    return "\n".join(f"{t:.4f} {i:.4f}" for t, i in zip(tt, y))


@pytest.fixture
def xy_file(tmp_path) -> Path:
    p = tmp_path / "synth.xy"
    p.write_text(_synth_xy_content(), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _reset_session():
    """每个测试前清空 MCP 全局 session, 避免相互污染."""
    from polyxrd.mcp_server.session import get_session
    get_session().reset()
    yield
    get_session().reset()


# ── 1. Server 实例元数据 & 工具注册 ─────────────────────────────────

def test_mcp_server_metadata():
    """server.mcp 实例 name/version/title 字段齐全."""
    from polyxrd.mcp_server.server import mcp
    assert mcp.name == "polyxrd"
    # version 取自 polyxrd.__version__, 非空字符串
    assert isinstance(mcp.version, str) and mcp.version
    assert "XRD" in (mcp.title or "")


def test_mcp_server_registers_all_tools():
    """18 个 @mcp.tool() 装饰函数应在 server 模块可见.

    用模块属性而非 dir(mcp) 验证, 因为 mcp 实例有 lazy property (session_manager)
    在 streamable_http_app() 调用前访问会抛 RuntimeError.
    """
    from polyxrd.mcp_server import server
    # 关键工具名应作为模块级属性存在 (经 @mcp.tool() 装饰后仍是普通函数)
    expected = [
        "load_xrd_data", "get_data_summary", "preprocess_data",
        "find_peaks", "list_peaks", "fit_peaks",
        "search_phases", "search_cod_phases", "search_cod_by_d_peaks",
        "get_cod_phase_details", "search_cod_online",
        "simulate_pattern", "refine_rietveld",
        "export_results", "save_project", "load_project",
        "get_session_status", "reset_session",
    ]
    missing = [name for name in expected if not callable(getattr(server, name, None))]
    assert not missing, f"缺失工具: {missing}"


# ── 2. 会话管理工具 ─────────────────────────────────────────────────

def test_get_session_status_empty():
    from polyxrd.mcp_server.server import get_session_status
    out = json.loads(get_session_status())
    assert out["has_raw_data"] is False
    assert out["has_processed_data"] is False
    assert out["n_peaks"] == 0
    assert out["n_phase_matches"] == 0
    assert out["has_refinement"] is False


def test_reset_session_clears_state():
    from polyxrd.mcp_server.session import get_session
    from polyxrd.mcp_server.server import reset_session, get_session_status
    # 先塞一点状态
    sess = get_session()
    sess.source_file = "fake.xy"
    sess.peak_list = []
    out = json.loads(reset_session())
    assert out["status"] == "ok"
    status = json.loads(get_session_status())
    assert status["has_raw_data"] is False
    assert status["source_file"] is None


# ── 3. 无数据时的错误路径 ───────────────────────────────────────────

@pytest.mark.parametrize("tool_name,kwargs", [
    ("get_data_summary", {}),
    ("preprocess_data", {}),
    ("find_peaks", {}),
    ("list_peaks", {}),
    ("fit_peaks", {}),
    ("search_phases", {}),
    ("refine_rietveld", {}),
    ("save_project", {"file_path": "/tmp/should_not_exist.polyxrd"}),
])
def test_tool_returns_error_json_when_no_data(tool_name, kwargs):
    """无数据时所有工具应返回 {"error": ...} 而非抛异常."""
    from polyxrd.mcp_server import server
    fn = getattr(server, tool_name)
    out = json.loads(fn(**kwargs))
    assert "error" in out, f"{tool_name} 应返回 error 键, 实际: {out}"


# ── 4. 数据加载快乐路径 ─────────────────────────────────────────────

def test_load_xrd_data_returns_summary(xy_file):
    from polyxrd.mcp_server.server import load_xrd_data
    out = json.loads(load_xrd_data(str(xy_file)))
    assert out["status"] == "ok"
    assert out["n_points"] == 200
    assert out["two_theta_min"] == pytest.approx(10.0, abs=0.01)
    assert out["two_theta_max"] == pytest.approx(80.0, abs=0.01)
    assert out["wavelength"] == 1.5406  # Cu Kα1 default


def test_get_data_summary_after_load(xy_file):
    from polyxrd.mcp_server.server import load_xrd_data, get_data_summary
    load_xrd_data(str(xy_file))
    out = json.loads(get_data_summary())
    assert out["n_points"] == 200
    assert out["two_theta_min"] == pytest.approx(10.0, abs=0.01)
    assert "intensity_mean" in out


def test_get_session_status_after_load(xy_file):
    from polyxrd.mcp_server.server import load_xrd_data, get_session_status
    load_xrd_data(str(xy_file))
    out = json.loads(get_session_status())
    assert out["has_raw_data"] is True
    assert out["source_file"] == str(xy_file)


# ── 5. 预处理 / 寻峰快乐路径 ───────────────────────────────────────

def test_preprocess_data_after_load(xy_file):
    from polyxrd.mcp_server.server import load_xrd_data, preprocess_data
    load_xrd_data(str(xy_file))
    out = json.loads(preprocess_data(method="snip", normalize=True))
    assert out["status"] == "ok"
    assert out["n_points"] > 0
    assert out["normalized"] is True


def test_find_peaks_after_preprocess(xy_file):
    from polyxrd.mcp_server.server import load_xrd_data, preprocess_data, find_peaks
    load_xrd_data(str(xy_file))
    preprocess_data(normalize=True)
    out = json.loads(find_peaks(height=0.05, distance=0.5))
    # 合成峰位于 26.6/31.7/45.4, 至少应找到 3 个
    assert out["n_peaks"] >= 3, f"应至少找到 3 个合成峰, 实际 {out['n_peaks']}"
    peak_tts = [p["two_theta"] for p in out["peaks"]]
    # 验证三个合成峰位置都被检测到 (±0.5°)
    for expected in (26.6, 31.7, 45.4):
        assert any(abs(t - expected) < 0.5 for t in peak_tts), \
            f"合成峰 {expected}° 未被检测到, 检出: {peak_tts}"


def test_list_peaks_after_find(xy_file):
    from polyxrd.mcp_server.server import (
        load_xrd_data, preprocess_data, find_peaks, list_peaks,
    )
    load_xrd_data(str(xy_file))
    preprocess_data(normalize=True)
    find_peaks(height=0.05, distance=0.5)
    out = json.loads(list_peaks())
    assert out["n_peaks"] >= 3
    assert isinstance(out["peaks"], list)
    assert "two_theta" in out["peaks"][0]


# ── 6. Session 优先级 (processed > raw) ────────────────────────────

def test_session_current_data_prefers_processed(xy_file):
    from polyxrd.mcp_server.session import get_session
    from polyxrd.mcp_server.server import load_xrd_data, preprocess_data
    sess = get_session()
    load_xrd_data(str(xy_file))
    assert sess.current_data is sess.raw_data
    preprocess_data(normalize=True)
    assert sess.current_data is sess.processed_data
    assert sess.processed_data is not sess.raw_data


# ── 7. Phase 搜索 (内置库, 无需 COD 在线) ──────────────────────────

def test_search_phases_after_peaks(xy_file):
    """合成峰未对齐任何参考峰时, search_phases 仍应返回 JSON 列表 (可能 0 结果)."""
    from polyxrd.mcp_server.server import (
        load_xrd_data, preprocess_data, find_peaks, search_phases,
    )
    load_xrd_data(str(xy_file))
    preprocess_data(normalize=True)
    find_peaks(height=0.05, distance=0.5)
    out = json.loads(search_phases(top_n=5, tolerance=0.3))
    # 内置库可能匹配也可能不匹配 (合成峰不在标准位置), 但结构应合法
    assert "n_results" in out
    assert isinstance(out["matches"], list)
    assert out["n_results"] == len(out["matches"])


# ── 8. 项目保存 (smoke level) ───────────────────────────────────────

def test_save_project_after_load(xy_file, tmp_path):
    from polyxrd.mcp_server.server import load_xrd_data, save_project
    load_xrd_data(str(xy_file))
    p = str(tmp_path / "mcp_smoke.polyxrd")
    out = json.loads(save_project(p))
    assert out["status"] == "ok"
    assert out["file_path"] == p
