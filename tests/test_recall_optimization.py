"""
0.9.11 召回优化回归测试
=======================
覆盖本轮"提升 COD 物相识别召回"的四项改动:

1. 寻峰最小间距 distance 5.0° → 0.5°  (旧值会整条丢弃相邻强线)
2. 高精度寻峰 sigma_threshold 5.0 → 3.0 (改用局部噪声 σ 判据)
3. 物相识别默认寻峰改用高精度检测器 (default_peak_list)
4. COD 最终排序 fom_good 由 1-clip(fom/1.2) 改为 exp(-fom/0.8)
   并下调 Hanawalt 权重 0.30 → 0.10 (旧式在多相样品里整体饱和)
5. search_cod_by_d_peaks 新增 tolerance_rel 相对容差
"""
from __future__ import annotations

import inspect
import importlib.util
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


# ── 1. 寻峰最小间距 ──────────────────────────────────────────

def test_peak_finder_default_distance_is_sub_degree():
    from polyxrd.services.peak_finder import PeakFinder
    sig = inspect.signature(PeakFinder.find_peaks)
    assert sig.parameters["distance"].default == 0.5


def test_config_default_peak_distance_is_sub_degree():
    from polyxrd.config import get_config
    assert get_config().default_peak_distance == 0.5


def test_close_strong_lines_survive_default_distance():
    """两条相距 1.8° 的强线在默认参数下都必须被检出。

    回归背景: 旧默认 distance=5.0° 时 ZnO 的 31.8°/34.4°/36.3° 三强线
    只剩 36.3°, 直接导致 ZnO 主物相识别失败。
    """
    from polyxrd.models.xrd_data import XRDData
    from polyxrd.services.peak_finder import PeakFinder

    tt = np.arange(20.0, 60.0, 0.02)
    y = np.zeros_like(tt)
    for center, amp, fwhm in ((31.76, 57.0, 0.15),
                              (34.40, 44.0, 0.15),
                              (36.24, 100.0, 0.15)):
        sigma = fwhm / 2.355
        y += amp * np.exp(-0.5 * ((tt - center) / sigma) ** 2)
    y += 0.5  # 轻微基线
    data = XRDData(two_theta=tt, intensity=y, wavelength=1.5406)

    pf = PeakFinder()
    got = sorted(round(p.two_theta, 1) for p in pf.find_peaks(data).peaks)
    assert 31.8 in got and 34.4 in got and 36.2 in got, got

    # 旧默认值作为反例: 应确实丢掉两条
    legacy = sorted(
        round(p.two_theta, 1) for p in pf.find_peaks(data, distance=5.0).peaks
    )
    assert 36.2 in legacy and 31.8 not in legacy


def test_vm_and_mcp_defaults_follow_peak_finder():
    from polyxrd.viewmodels.main_vm import MainViewModel
    from polyxrd.viewmodels.phase_vm import PhaseViewModel

    fns = [MainViewModel.find_peaks, PhaseViewModel.find_peaks]
    if importlib.util.find_spec("mcp") is not None:
        from polyxrd.mcp_server import server
        fns.append(server.find_peaks)
    for fn in fns:
        assert inspect.signature(fn).parameters["distance"].default == 0.5


# ── 2. 高精度寻峰 σ 阈值 ────────────────────────────────────

def test_peak_detect_options_sigma_default_is_3():
    from polyxrd.services.peak_detection import PeakDetectOptions
    opts = PeakDetectOptions()
    assert opts.sigma_threshold == 3.0
    assert opts.distance_deg == 0.10


def test_vm_find_peaks_advanced_sigma_default():
    from polyxrd.viewmodels.main_vm import MainViewModel
    from polyxrd.viewmodels.phase_vm import PhaseViewModel
    for fn in (MainViewModel.find_peaks_advanced,
               PhaseViewModel.find_peaks_advanced):
        assert inspect.signature(fn).parameters["sigma_threshold"].default == 3.0


# ── 3. 默认寻峰走检测器 ─────────────────────────────────────

def _synth_pattern() -> "object":
    from polyxrd.models.xrd_data import XRDData
    tt = np.arange(10.0, 90.0, 0.02)
    y = np.full_like(tt, 20.0)
    for center, amp, fwhm in ((26.6, 100.0, 0.2), (36.2, 30.0, 0.2),
                              (50.1, 12.0, 0.2), (60.0, 4.0, 0.2),
                              (68.3, 3.0, 0.2)):
        sigma = fwhm / 2.355
        y += amp * np.exp(-0.5 * ((tt - center) / sigma) ** 2)
    rng = np.random.default_rng(0)
    y += rng.normal(0.0, 1.0, size=tt.size)
    return XRDData(two_theta=tt, intensity=y, wavelength=1.5406)


def test_default_peak_list_returns_peaklist():
    from polyxrd.models.peak import PeakList
    from polyxrd.services.phase_identifier import default_peak_list
    pl = default_peak_list(_synth_pattern())
    assert isinstance(pl, PeakList)
    assert len(pl.peaks) > 0


def test_default_peak_list_prefers_advanced_detector():
    from polyxrd.services.phase_identifier import default_peak_list
    pl = default_peak_list(_synth_pattern())
    assert pl.source == "advanced"


def test_default_peak_list_falls_back_when_detector_unavailable(monkeypatch):
    """检测器抛异常时必须回退到传统寻峰, 不得中断识别。"""
    import polyxrd.services.peak_detection as pd
    from polyxrd.services.phase_identifier import default_peak_list

    def _boom(*_a, **_k):
        raise RuntimeError("detector unavailable")

    monkeypatch.setattr(pd, "detect_peaks_from_data", _boom)
    pl = default_peak_list(_synth_pattern())
    assert len(pl.peaks) > 0


def test_identifier_uses_default_peak_list(monkeypatch):
    """identify_with_* 在 peaks=None 时应调用 default_peak_list。"""
    import polyxrd.services.phase_identifier as pim

    called = {"n": 0}
    real = pim.default_peak_list

    def _spy(data):
        called["n"] += 1
        return real(data)

    monkeypatch.setattr(pim, "default_peak_list", _spy)
    pi = pim.PhaseIdentifier()
    pi.identify_with_element_filter(_synth_pattern(), peaks=None, top_n=3)
    assert called["n"] == 1


# ── 4. COD 最终排序不再饱和 ─────────────────────────────────

class _R:
    __slots__ = ("score",)

    def __init__(self, score: float) -> None:
        self.score = score


def _cand(**kw) -> dict:
    base = {"main_peak_match": 0.0, "top_precision": 0.0,
            "intensity_weighted_top_recall": 0.0, "top_recall": 0.0}
    base.update(kw)
    return base


def test_cod_rank_constants():
    import polyxrd.services.phase_identifier as pim
    assert pim._COD_RANK_H_WEIGHT == 0.10
    assert pim._COD_RANK_FOM_TAU == 0.8


def test_cod_rank_score_is_monotonic_in_fom():
    from polyxrd.services.phase_identifier import cod_rank_score
    c = _cand()
    scores = [cod_rank_score((c, _R(f))) for f in (0.5, 1.0, 2.0, 4.0)]
    assert scores == sorted(scores, reverse=True)


def test_cod_rank_score_not_saturated_beyond_1p2():
    """旧口径 1-clip(fom/1.2) 在 fom>1.2 时全部等于 0 → 无法区分。

    多相样品里几乎所有候选的 FoM 都 >1.2, 旧式因此退化成纯 Hanawalt 排序。
    """
    from polyxrd.services.phase_identifier import cod_rank_score
    c = _cand()
    a = cod_rank_score((c, _R(1.5)))
    b = cod_rank_score((c, _R(3.0)))
    assert a > b > 0.0
    # 旧式对照: 两者都会是 0
    old = lambda f: 1.0 - min(max(f / 1.2, 0.0), 1.0)  # noqa: E731
    assert old(1.5) == old(3.0) == 0.0


def test_cod_rank_hanawalt_is_only_a_tiebreaker():
    """FoM 差异应压过 Hanawalt 差异 (w=0.10)。"""
    from polyxrd.services.phase_identifier import cod_rank_score
    strong_h_bad_fom = (_cand(main_peak_match=1.0, top_precision=1.0,
                              intensity_weighted_top_recall=1.0,
                              top_recall=1.0), _R(3.0))
    weak_h_good_fom = (_cand(main_peak_match=0.0, top_precision=0.4,
                             intensity_weighted_top_recall=0.3,
                             top_recall=0.2), _R(0.6))
    assert cod_rank_score(weak_h_good_fom) > cod_rank_score(strong_h_bad_fom)


def test_cod_inorganics_exposes_prefilter_knobs():
    import polyxrd.services.phase_identifier as pim
    p = inspect.signature(pim.PhaseIdentifier.identify_with_cod_inorganics).parameters
    for name in ("prefilter_limit", "prefilter_tolerance",
                 "prefilter_tolerance_rel", "prefilter_min_match",
                 "prefilter_max_ref_peaks"):
        assert name in p, name
    assert p["prefilter_tolerance_rel"].default == 0.0
    assert p["prefilter_max_ref_peaks"].default == 40


# ── 5. search_cod_by_d_peaks 相对容差 ───────────────────────

def _fake_db(rows: list[tuple]) -> "object":
    """构造只含 phases 表的 CIFDatabase (注入内存 sqlite 连接)。"""
    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase(enable_cod_local=False)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE phases (cod_id TEXT, ref_id TEXT, display_id TEXT, "
        "formula TEXT, space_group TEXT, n_peaks INT, peaks_d TEXT, peaks_i TEXT)"
    )
    conn.executemany(
        "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    db._cod_conn = conn
    return db


def _row(cod_id: str, formula: str, ds: list[float], is_: list[float]):
    return (cod_id, cod_id, cod_id, formula, "P 1", len(ds),
            ",".join(str(d) for d in ds), ",".join(str(i) for i in is_))


def test_tolerance_rel_widens_low_angle_window():
    """大 d (低角度) 处: 绝对 0.02 Å 只有 ~0.11° 的 2θ 窗口, 漏配真峰。

    参考峰 d=4.00, 实测峰 d=4.045 (偏差 0.045 Å, 超出 0.02 绝对容差)。
    加 tolerance_rel=0.02 后容差 = 0.08 Å → 应命中。
    """
    db = _fake_db([
        _row("A", "Zn1 O1", [4.00, 2.50, 2.10], [100.0, 60.0, 30.0]),
        _row("B", "Ca1 O1", [4.00, 2.50, 2.10], [100.0, 60.0, 30.0]),
    ])
    measured = [4.045, 2.53, 2.12]

    strict = db.search_cod_by_d_peaks(measured, [100.0, 60.0, 30.0],
                                      tolerance=0.02, min_match=3)
    assert strict == []

    loose = db.search_cod_by_d_peaks(measured, [100.0, 60.0, 30.0],
                                     tolerance=0.02, tolerance_rel=0.02,
                                     min_match=3)
    assert len(loose) == 2


def test_tolerance_rel_keeps_absolute_floor_at_high_angle():
    """小 d (高角度) 处: tol_rel·d 小于绝对下限 → 仍用绝对容差, 不过度放宽。"""
    db = _fake_db([
        _row("A", "Zn1 O1", [1.00, 0.90, 0.80], [100.0, 60.0, 30.0]),
    ])
    # 偏差 0.025 Å: 绝对 0.02 容不下; tol_rel=0.005 时 0.005*1.0=0.005 < 0.02
    # → 实际容差仍为 0.02, 不应命中
    got = db.search_cod_by_d_peaks([1.025, 0.90, 0.80], None,
                                   tolerance=0.02, tolerance_rel=0.005,
                                   min_match=3)
    assert got == []
    # 提到 0.03 的相对分量 (0.03*1.0=0.03 > 0.02) 才应命中
    got2 = db.search_cod_by_d_peaks([1.025, 0.90, 0.80], None,
                                    tolerance=0.02, tolerance_rel=0.03,
                                    min_match=3)
    assert len(got2) == 1


def test_tolerance_rel_default_is_pure_absolute():
    db = _fake_db([
        _row("A", "Zn1 O1", [4.00, 2.50, 2.10], [100.0, 60.0, 30.0]),
    ])
    a = db.search_cod_by_d_peaks([4.045, 2.53, 2.12], None, tolerance=0.02,
                                 min_match=3)
    b = db.search_cod_by_d_peaks([4.045, 2.53, 2.12], None, tolerance=0.02,
                                 tolerance_rel=0.0, min_match=3)
    assert a == b == []


def test_tolerance_rel_affects_main_peak_match_and_precision():
    """相对容差必须一致作用于 top_precision / main_peak_match 等所有判据。"""
    db = _fake_db([
        _row("A", "Zn1 O1", [4.00, 2.50, 2.10], [100.0, 60.0, 30.0]),
    ])
    # 各峰偏差 0.05 / 0.03 / 0.02 Å, 均超出绝对容差 0.02, 但在
    # max(0.02, 0.02·d) 的相对窗口 (0.080 / 0.050 / 0.042) 内
    got = db.search_cod_by_d_peaks(
        [4.05, 2.53, 2.12], [100.0, 60.0, 30.0],
        tolerance=0.02, tolerance_rel=0.02, min_match=3)
    assert len(got) == 1
    r = got[0]
    assert r["n_matched_meas"] == 3
    assert r["main_peak_match"] == 1.0
    assert r["top_precision"] == 1.0
    assert r["meas_ratio"] == 1.0


def test_max_ref_peaks_limits_reference_pool():
    ds = [4.0 - 0.05 * i for i in range(10)]
    is_ = [100.0 - 5.0 * i for i in range(10)]
    db = _fake_db([_row("A", "Zn1 O1", ds, is_)])
    r40 = db.search_cod_by_d_peaks(ds[:3], None, max_ref_peaks=40, min_match=3)
    r2 = db.search_cod_by_d_peaks(ds[:3], None, max_ref_peaks=2, min_match=3)
    assert r40 and r40[0]["n_ref_used"] == 10
    assert r2 == [] or r2[0]["n_ref_used"] == 2


def test_elements_allowed_pushes_down_chemical_filter():
    db = _fake_db([
        _row("A", "Zn1 O1", [4.0, 2.5, 2.1], [100.0, 60.0, 30.0]),
        _row("B", "Ca1 O1", [4.0, 2.5, 2.1], [100.0, 60.0, 30.0]),
    ])
    got = db.search_cod_by_d_peaks([4.0, 2.5, 2.1], None, min_match=3,
                                   elements_allowed={"Zn", "O"})
    assert [r["cod_id"] for r in got] == ["A"]
