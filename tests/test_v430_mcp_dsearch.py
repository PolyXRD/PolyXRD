# -*- coding: utf-8 -*-
"""v4.3.0: MCP polyDB d 峰检索（Hanawalt）回归。"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REAL_DB = Path(
    r"D:\Project\XRD\PolyXRD-DataBase\polydb\COD-Inorg-20261021.polyDB")


def _fake_db(monkeypatch, *, available=True, ready=True, matches=None):
    from polyxrd.services import polydb as polydb_mod

    class FakeDB:
        def __init__(self, *a, **k):
            pass

        @property
        def available(self):
            return available

        def is_ready(self):
            return ready

        def search_by_d_peaks(self, *a, **k):
            FakeDB.last_args = (a, k)
            return list(matches or [])

    monkeypatch.setattr(polydb_mod, "PolyDatabase", FakeDB)
    return FakeDB


def test_legacy_signature_preserved():
    from polyxrd.mcp_server.server import search_cod_by_d_peaks

    params = list(inspect.signature(search_cod_by_d_peaks).parameters)
    assert params == ["d_values", "intensities", "tolerance", "min_match", "limit"]


def test_no_mount_returns_json_not_exception(monkeypatch):
    from polyxrd.mcp_server.server import (
        search_cod_by_d_peaks, search_phases_by_d_peaks,
    )

    _fake_db(monkeypatch, available=False)
    out = json.loads(search_phases_by_d_peaks([3.343, 1.817]))
    assert out["mounted"] is False
    assert out["n_results"] == 0 and out["matches"] == []
    assert out["hint"]
    old = json.loads(search_cod_by_d_peaks([3.343, 1.817]))
    assert old["mounted"] is False and old["n_results"] == 0


def test_corrupted_layout_reports_error(monkeypatch):
    from polyxrd.mcp_server.server import search_phases_by_d_peaks

    _fake_db(monkeypatch, available=True, ready=False)
    out = json.loads(search_phases_by_d_peaks([3.343, 1.817]))
    assert out["mounted"] is True
    assert "corrupted" in out["error"].lower()


def test_happy_path_passes_options_and_normalizes_fields(monkeypatch):
    from polyxrd.mcp_server.server import (
        search_cod_by_d_peaks, search_phases_by_d_peaks,
    )

    fake = _fake_db(monkeypatch, matches=[{
        "cod_id": 1011097, "formula": "O2 Si", "space_group": "P 31 2 1",
        "mineral_name": "Quartz low", "n_peaks": 35, "score": 91.0,
        "top_precision": 0.6, "main_peak_match": 1.0,
    }])
    out = json.loads(search_phases_by_d_peaks(
        [3.343, 4.255], [100.0, 20.0], tolerance=0.03,
        tolerance_rel=0.001, min_match=2, limit=3,
        elements=["Si", "O"], max_ref_peaks=30, main_peak_topk=2))
    assert out["mounted"] is True and out["n_results"] == 1
    m = out["matches"][0]
    assert m["cod_id"] == 1011097
    assert m["display_id"] == "97-1011097"
    assert m["ref_id"] == "96-101-1097"
    assert m["mineral_name"] == "Quartz low"
    # 选项确实下传
    args, kwargs = fake.last_args
    assert kwargs["tolerance"] == pytest.approx(0.03)
    assert kwargs["tolerance_rel"] == pytest.approx(0.001)
    assert kwargs["min_match"] == 2 and kwargs["limit"] == 3
    assert kwargs["elements_allowed"] == {"Si", "O"}
    assert kwargs["max_ref_peaks"] == 30 and kwargs["main_peak_topk"] == 2

    old = json.loads(search_cod_by_d_peaks(
        [3.343, 4.255], [100.0, 20.0], min_match=2, limit=3))
    assert old["n_results"] == out["n_results"]
    assert [r["cod_id"] for r in old["matches"]] == [r["cod_id"] for r in out["matches"]]


@pytest.mark.parametrize("d,inten,needle", [
    ([], None, "empty"),
    ([3.3, -1.0], None, "> 0"),
    ([3.3], [100.0, 20.0], "same length"),
    ([3.3], [-1.0], ">= 0"),
    ([3.3], None, None),  # 合法，见下方单独断言
])
def test_input_validation(monkeypatch, d, inten, needle):
    from polyxrd.mcp_server.server import search_phases_by_d_peaks

    _fake_db(monkeypatch)
    out = json.loads(search_phases_by_d_peaks(d, inten))
    if needle is None:
        assert "error" not in out
    else:
        assert "error" in out and needle in out["error"]


def test_unknown_element_rejected(monkeypatch):
    from polyxrd.mcp_server.server import search_phases_by_d_peaks

    _fake_db(monkeypatch)
    out = json.loads(search_phases_by_d_peaks([3.343], elements=["Zz"]))
    assert "unknown element" in out["error"].lower()


@pytest.mark.skipif(not REAL_DB.is_dir(), reason="本机无实测 polyDB 库")
def test_real_db_quartz_search_and_element_filter():
    from polyxrd.mcp_server.server import search_phases_by_d_peaks

    d = [3.343, 4.255, 1.818, 2.457, 2.282]
    i = [100.0, 20.0, 6.0, 10.0, 9.0]
    out = json.loads(search_phases_by_d_peaks(d, i, min_match=3, limit=10))
    assert out["mounted"] is True and out["n_results"] >= 1
    ids = [m["cod_id"] for m in out["matches"]]
    assert 1011097 in ids, f"石英应在前 10: {ids}"
    q = next(m for m in out["matches"] if m["cod_id"] == 1011097)
    assert q["display_id"] == "97-1011097"
    assert q["ref_id"] == "96-101-1097"

    # 元素白名单只允许 Si/O：不应出现 Fe 相等物相
    si_o = json.loads(search_phases_by_d_peaks(
        d, i, min_match=3, limit=10, elements=["Si", "O"]))
    assert si_o["n_results"] >= 1
    for m in si_o["matches"]:
        formula = (m.get("formula") or "").upper()
        assert "FE" not in formula
