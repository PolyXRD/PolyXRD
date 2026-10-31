"""外挂库「选中即用于检索」—— PhaseViewModel 分发链路测试 (v4.6.0)
================================================================

用户要求: 不限插槽, 可挂很多类数据库; **选中某个数据库就用于物相检索和匹配**。
本文件钉住三处曾经各走各路的入口:

1. 传统检索/残差追查/Profile Fitting 必须使用同一个 db_source;
2. 选中的库打不开 (半成品/被截断) 时必须报明确原因, 不能静默返回空候选;
3. 外挂库做 Profile Fitting 时先按 d-I 预筛候选、再全谱拟合重排,
   而内置 118 相库仍走原来的穷举路径。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.services import db_mounts
from polyxrd.services.db_mounts import Mount
from polyxrd.viewmodels.phase_vm import PhaseViewModel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _vm_with_peaks() -> PhaseViewModel:
    vm = PhaseViewModel()
    vm._peaks = PeakList(peaks=[Peak(two_theta=30.0, intensity=1000)])
    return vm


def _mount(tmp_path, kind="polydb", label="Mine.polyDB") -> Mount:
    path = tmp_path / label
    path.mkdir()
    return Mount(id=f"{kind}:deadbeef", kind=kind, path=path,
                 builtin=False, label=label, variant="cod-full")


def _result(name: str):
    phase = Phase(name=name, formula=name, elements={"Si", "O"},
                  reference_peaks=[((1, 0, 0), 30.0, 100.0)])
    return SimpleNamespace(phase=phase, score=50.0, method="fom")


# ── 1. 残差追查沿用同一个数据源 ────────────────────────────────

def test_residual_search_forwards_db_source(qapp, monkeypatch):
    vm = _vm_with_peaks()
    vm._selected_phases = [Phase(name="X", formula="SiO2")]
    # 一个解释不到的峰 → 走"残差峰再检索"分支
    monkeypatch.setattr(
        vm, "current_assignment",
        lambda tolerance=0.30: ([SimpleNamespace(two_theta=30.0,
                                                 phase_index=None)], []))
    calls: list[dict] = []
    monkeypatch.setattr(vm, "identify_phases",
                        lambda data, **kw: calls.append(kw))
    vm.search_residual_peaks(None, db_source="polydb:deadbeef")
    assert calls and calls[0]["db_source"] == "polydb:deadbeef"
    assert calls[0]["marked_peaks"] == [30.0]


# ── 2. 选中的库不可用 → 明确报错, 不进引擎 ────────────────────

def test_corrupt_selected_mount_reports_error(qapp, tmp_path, monkeypatch):
    mount = _mount(tmp_path)
    monkeypatch.setattr(db_mounts, "resolve_mount", lambda mid: mount)
    monkeypatch.setattr(db_mounts, "probe",
                        lambda m, use_cache=True: {
                            "ok": False, "error": "polydb_not_ready",
                            "detail": str(m.path)})
    vm = _vm_with_peaks()
    errs: list[str] = []
    vm.error.connect(errs.append)
    called: list[int] = []
    monkeypatch.setattr(vm._identifier, "identify_with_polydb",
                        lambda *a, **k: called.append(1) or [])
    vm.identify_phases(None, db_source="polydb:deadbeef")
    assert errs and "polydb_not_ready" in errs[0]
    assert not called, "库不可用时不能再去调用引擎"


def test_selected_mount_ready_and_path_passed(qapp, tmp_path, monkeypatch):
    mount = _mount(tmp_path)
    monkeypatch.setattr(db_mounts, "resolve_mount", lambda mid: mount)
    monkeypatch.setattr(db_mounts, "probe",
                        lambda m, use_cache=True: {"ok": True, "rows": 10})
    vm = _vm_with_peaks()
    calls: list[dict] = []
    monkeypatch.setattr(vm._identifier, "identify_with_polydb",
                        lambda data, **kw: calls.append(kw) or [])
    vm.identify_phases(None, db_source="polydb:deadbeef")
    assert calls[0]["db_path"] == str(mount.path)
    assert calls[0]["variant"] == "cod-full"


# ── 3. Profile Fitting: 内置库穷举 / 外挂库预筛+重排 ───────────

def test_profile_fitting_builtin_keeps_exhaustive_path(qapp, monkeypatch):
    vm = _vm_with_peaks()
    calls: list[dict] = []
    monkeypatch.setattr(vm._profile_fitting, "identify",
                        lambda data, **kw: calls.append(kw) or [])
    scored: list[int] = []
    monkeypatch.setattr(vm._profile_fitting, "score_phases",
                        lambda *a, **k: scored.append(1) or [])
    vm.identify_phases_profile_fitting(None, top_n=3, db_source="builtin")
    assert calls, "builtin 仍走原来的 118 相穷举"
    assert not scored


def test_profile_fitting_external_prefilters_then_reranks(
        qapp, tmp_path, monkeypatch):
    mount = _mount(tmp_path)
    monkeypatch.setattr(db_mounts, "resolve_mount", lambda mid: mount)
    monkeypatch.setattr(db_mounts, "probe",
                        lambda m, use_cache=True: {"ok": True, "rows": 10})
    vm = _vm_with_peaks()
    pre_calls: list[dict] = []
    phases_pre = [_result("A").phase, _result("B").phase, _result("C").phase]
    # polyDB 走"只预筛、不 FoM"的快速路径；assert 被调的是它而不是
    # identify_with_polydb (后者会对 200 个候选算 FoM, 正是要省掉的成本)。
    monkeypatch.setattr(
        vm._identifier, "prescreen_with_polydb",
        lambda data, **kw: pre_calls.append(kw) or phases_pre)
    fom_calls: list[int] = []
    monkeypatch.setattr(
        vm._identifier, "identify_with_polydb",
        lambda *a, **k: fom_calls.append(1) or [])
    score_calls: list[dict] = []
    final = _result("B")
    monkeypatch.setattr(
        vm._profile_fitting, "score_phases",
        lambda data, ps, **kw: score_calls.append(
            {"n": len(ps), "fwhm": kw.get("fwhm")}) or [final])

    emitted: list[list] = []
    infos: list[str] = []
    vm.phase_identified.connect(lambda rs: emitted.append(list(rs)))
    vm.info.connect(infos.append)
    vm.identify_phases_profile_fitting(None, top_n=2, db_source="polydb:deadbeef")

    pool = vm.PROFILE_EXTERNAL_POOL
    assert pre_calls and pre_calls[0]["limit"] == pool
    assert not fom_calls, "Profile Fitting 不应再对候选做 FoM 打分"
    assert score_calls and score_calls[0]["n"] == 3
    assert emitted and emitted[-1] == [final]
    assert final.method == "profile_fitting"
    assert infos, "外挂库 Profile Fitting 应在状态栏说明候选来源"


def test_profile_fitting_external_no_candidates_is_empty(
        qapp, tmp_path, monkeypatch):
    mount = _mount(tmp_path)
    monkeypatch.setattr(db_mounts, "resolve_mount", lambda mid: mount)
    monkeypatch.setattr(db_mounts, "probe",
                        lambda m, use_cache=True: {"ok": True, "rows": 10})
    vm = _vm_with_peaks()
    monkeypatch.setattr(vm._identifier, "prescreen_with_polydb",
                        lambda *a, **k: [])
    scored: list[int] = []
    monkeypatch.setattr(vm._profile_fitting, "score_phases",
                        lambda *a, **k: scored.append(1) or [])
    emitted: list[list] = []
    vm.phase_identified.connect(lambda rs: emitted.append(list(rs)))
    vm.identify_phases_profile_fitting(None, db_source="polydb:deadbeef")
    assert not scored
    assert emitted == [[]]
