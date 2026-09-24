"""v2.1 P0-1: 项目保存/加载链路回归测试。

背景 (docs/代码评估与改进计划.md §五 P0-1):
- (b) project_service.py 缺 `Peak` 导入 → 含峰表项目加载必抛 NameError;
- (c) mcp_server save_project 参数名/参数与 ProjectService 真实签名不符 → TypeError;
- (d) mcp_server load_project 按属性访问 dict → AttributeError;
- GUI 侧 _on_save/_on_save_as 原为"未实现"空壳 (已在 v2.1 接 ProjectService)。

本文件锁定: peaks 往返、精修结果往返 (含谱数组与 numpy 标量)、MCP 两工具往返。
"""
from __future__ import annotations

import json
import numpy as np
import pytest

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import LatticeParams, Phase, PhaseMatchResult
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.project_service import ProjectService


def _make_data(n: int = 300) -> XRDData:
    return XRDData(
        two_theta=np.linspace(10.0, 80.0, n),
        intensity=np.abs(np.sin(np.linspace(0, 20, n))) * 100.0,
        wavelength=1.5406,
    )


def _make_peaks() -> PeakList:
    return PeakList(peaks=[
        Peak(two_theta=31.5, intensity=1000.0),
        Peak(two_theta=34.2, intensity=800.0),
        Peak(two_theta=47.3, intensity=500.0),
    ])


def _make_phase(name: str = "Zincite", formula: str = "ZnO") -> Phase:
    return Phase(
        name=name,
        formula=formula,
        space_group="P 63 m c",
        lattice=LatticeParams(a=3.25, b=3.25, c=5.21, alpha=90.0, beta=90.0, gamma=120.0),
        weight_fraction=62.5,
        match_score=0.132,
        elements={"Zn", "O"},
    )


def _make_refinement(phases: list[Phase]) -> RefinementResult:
    x = np.linspace(10.0, 80.0, 50)
    return RefinementResult(
        phases=phases,
        observed_data=(x, x * 0.1 + 1.0),
        simulated_data=(x, x * 0.098 + 1.0),
        residual_data=(x, x * 0.002),
        wR=8.94, Rexp=8.65, Rb=0.0, Rp=6.71,
        chi2=1.067, chi2_red=1.067,
        metrics_valid=True, metric_note="poisson",
        GOF=1.033, quality="优秀",
        num_cycles=10, converged=True, time_seconds=0.64,
        fit_params={"scale": 0.0123, "u": np.float64(0.004)},
        warnings=["ka2.detected"],
    )


# ── 1) peaks 往返 (旧代码: NameError: name 'Peak' is not defined) ──────

def test_save_load_with_peaks_roundtrip(tmp_path):
    svc = ProjectService()
    path = str(tmp_path / "t.polyxrd")
    peaks = _make_peaks()

    svc.save_project(path, data=_make_data(), peaks=peaks)
    project = svc.load_project(path)

    assert project["peaks"] is not None
    loaded = project["peaks"]
    assert len(loaded) == len(peaks)
    for p_new, p_old in zip(loaded.peaks, peaks.peaks):
        assert p_new.two_theta == pytest.approx(p_old.two_theta)
        assert p_new.intensity == pytest.approx(p_old.intensity)


# ── 2) 完整往返: 数据+峰+物相+勾选集+匹配结果+精修结果 ────────────────

def test_full_project_roundtrip(tmp_path):
    svc = ProjectService()
    path = str(tmp_path / "full.polyxrd")
    data, peaks = _make_data(), _make_peaks()
    phase = _make_phase()
    results = [PhaseMatchResult(
        phase=phase, score=0.132, matched_peaks=8, total_peaks=11,
        confidence="high",
    )]
    selected = [phase]
    refinement = _make_refinement([phase])

    svc.save_project(
        path, data=data, peaks=peaks, phases=[phase],
        results=results, selected_phases=selected,
        refinement_result=refinement,
    )
    project = svc.load_project(path)

    # 数据
    d = project["data"]
    assert d is not None
    np.testing.assert_allclose(d.two_theta, data.two_theta)
    np.testing.assert_allclose(d.intensity, data.intensity)
    assert d.wavelength == pytest.approx(1.5406)

    # 物相 / 勾选集 / 匹配结果
    assert len(project["phases"]) == 1
    assert project["phases"][0].name == "Zincite"
    assert project["selected_phases"][0].formula == "ZnO"
    r = project["results"][0]
    assert r.score == pytest.approx(0.132)
    assert r.matched_peaks == 8 and r.total_peaks == 11

    # 精修结果: 标量 + 谱数组 + fit_params (numpy 标量) + warnings
    rr = project["refinement_result"]
    assert rr is not None
    assert rr.wR == pytest.approx(8.94)
    assert rr.GOF == pytest.approx(1.033)
    assert rr.metrics_valid is True
    assert rr.converged is True
    assert rr.num_cycles == 10
    assert rr.metric_note == "poisson"
    assert rr.warnings == ["ka2.detected"]
    assert rr.fit_params["scale"] == pytest.approx(0.0123)
    assert isinstance(rr.fit_params["u"], float)  # numpy 标量已转 python float
    np.testing.assert_allclose(rr.observed_data[0], refinement.observed_data[0])
    np.testing.assert_allclose(rr.simulated_data[1], refinement.simulated_data[1])
    assert rr.phases[0].name == "Zincite"


# ── 3) 无精修结果的项目: 键存在且为 None (向后兼容旧项目文件) ─────────

def test_load_without_refinement_returns_none(tmp_path):
    svc = ProjectService()
    path = str(tmp_path / "norefine.polyxrd")
    svc.save_project(path, data=_make_data())
    project = svc.load_project(path)
    assert project["refinement_result"] is None


# ── 4) MCP save_project / load_project 往返 ──────────────────────────

def test_mcp_save_load_project_roundtrip(tmp_path):
    from polyxrd.mcp_server import server as mcp_server
    from polyxrd.mcp_server.session import get_session

    session = get_session()
    session.reset()
    session.raw_data = _make_data()
    session.peak_list = _make_peaks()
    phase = _make_phase()
    session.phase_matches = [PhaseMatchResult(
        phase=phase, score=0.2, matched_peaks=3, total_peaks=5,
    )]
    session.refinement_result = _make_refinement([phase])

    path = str(tmp_path / "mcp.polyxrd")

    out_save = json.loads(mcp_server.save_project(path))
    assert out_save["status"] == "ok"
    assert session.project_file == path

    # 清空会话后加载, 状态应完整恢复
    session.reset()
    out_load = json.loads(mcp_server.load_project(path))
    assert out_load["status"] == "ok"
    assert out_load["n_points"] == 300
    assert out_load["n_peaks"] == 3
    assert out_load["n_phases"] == 1
    assert out_load["has_refinement"] is True

    assert session.raw_data is not None
    assert len(session.peak_list) == 3
    assert len(session.phase_matches) == 1
    assert session.refinement_result is not None
    assert session.refinement_result.wR == pytest.approx(8.94)
    assert session.project_file == path

    session.reset()
