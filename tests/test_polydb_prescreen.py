"""polyDB「只预筛、不打分」候选接口 (v4.6.0, Profile Fitting 用)。

常规 identify_with_polydb 会对上百个候选算 FoM —— 对 Profile Fitting 是纯浪费
(它自己按全谱相关系数重排)。本文件钉住 prescreen_with_polydb 的契约：
只走位图预筛、按预筛排序取前 N、构造带晶胞的 Phase、应用元素过滤、
库不可用/无命中返回空列表而不是抛异常。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.models.peak import Peak, PeakList            # noqa: E402
from polyxrd.models.xrd_data import XRDData              # noqa: E402
from polyxrd.services.phase_identifier import PhaseIdentifier  # noqa: E402


class _FakeDB:
    ready = True
    rows: list[int] = [7, 9]
    calls: list[dict] = []

    def __init__(self, db_path=None, variant="cod-inorg"):
        self.path = Path(db_path) if db_path else None
        self.variant = variant

    def is_ready(self) -> bool:
        return bool(type(self).ready)

    def ordered_candidates(self, d_list, i_list, **kw):
        type(self).calls.append({"d": list(d_list), "i": list(i_list), **kw})
        return np.asarray(type(self).rows, dtype=np.int64), np.zeros(
            (len(type(self).rows), 3))

    def eid_of_rows(self, rows):
        return [int(r) for r in rows]

    def get_phase(self, eid):
        return {
            "cod_id": int(eid), "eid": int(eid),
            "formula": "Al2 O3", "mineral_name": "",
            "space_group": "R -3 c", "elements_list": ["Al", "O"],
            "cell_a": 4.759, "cell_b": 4.759, "cell_c": 12.991,
            "cell_alpha": 90.0, "cell_beta": 90.0, "cell_gamma": 120.0,
            "density": 3.99, "peaks_d_list": [2.085, 1.6],
            "peaks_i_list": [1000.0, 400.0],
        }

    def get_atomic_sites(self, eid):
        return []


def _data():
    x = np.linspace(20.0, 60.0, 200)
    return XRDData(two_theta=x, intensity=np.ones_like(x) * 100.0)


def _peaks():
    return PeakList(peaks=[Peak(two_theta=43.3, intensity=1000.0)])


@pytest.fixture
def fake(monkeypatch):
    from polyxrd.services import polydb as polydb_mod

    monkeypatch.setattr(polydb_mod, "PolyDatabase", _FakeDB)
    _FakeDB.ready = True
    _FakeDB.rows = [7, 9]
    _FakeDB.calls = []
    return _FakeDB


def test_prescreen_returns_phases_without_fom(fake):
    phases = PhaseIdentifier().prescreen_with_polydb(
        _data(), peaks=_peaks(), limit=37)
    assert [p.formula for p in phases] == ["Al2 O3", "Al2 O3"]
    assert fake.calls and fake.calls[0]["limit"] == 37
    # d 值来自实测峰 2θ（Cu Kα1）：43.3° → ~2.09 Å
    assert 2.0 < fake.calls[0]["d"][0] < 2.2
    assert phases[0].reference_peaks, "候选必须带参考峰, 否则无法做全谱拟合"


def test_prescreen_applies_element_filter(fake):
    phases = PhaseIdentifier().prescreen_with_polydb(
        _data(), peaks=_peaks(),
        element_filter={"must": ["Fe"], "has": [], "maybe": [], "exclude": []})
    assert phases == [] or all("Fe" in p.elements for p in phases)
    # 元素池已传给预筛层（位图过滤）
    assert fake.calls[0]["elements_allowed"] == {"Fe"}


def test_prescreen_unavailable_or_empty(fake):
    fake.ready = False
    assert PhaseIdentifier().prescreen_with_polydb(_data(), peaks=_peaks()) == []
    fake.ready = True
    fake.rows = []
    assert PhaseIdentifier().prescreen_with_polydb(_data(), peaks=_peaks()) == []
