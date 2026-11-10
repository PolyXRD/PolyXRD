"""MAUD 7 组基准门限（CI）。

门限（报告 §9）：
* ``Rwp <= 1.5 × MAUD``（逐样）；
* 逐相 wt% 与基线相差 ``<= 2.0 pp``（按**排序后的列表**比对，避免相序差异）。

真正跑 7 组精修很慢（~40 min），因此拆成两段：
1. 本文件里的 ``gate_failures`` 是纯函数单测（秒级，始终运行）；
2. 若环境里已有 sweep 结果 JSON（``POLYXRD_MAUD_RESULTS`` 或默认路径），
   再做一次真实结果的门限校验；没有就 skip。

   跑真实门限（7 组各自的 ``eval_p0bc.py <sample> 3 20 80 aniso`` 产物汇总成
   ``results_v5_default.json``）：
   ``python -m pytest tests/test_maud_gate.py``
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

BASELINE = Path(__file__).with_name("data") / "maud_gate_baseline.json"
DEFAULT_RESULTS = (Path(__file__).resolve().parents[1]
                   / ".workbuddy" / "tmp" / "maud_cmp"
                   / "results_v5_default.json")

RWP_FACTOR = 1.5
WT_TOL_PP = 2.0


def _short(sample: str) -> str:
    return str(sample).split("#")[0]


def gate_failures(baseline: dict, results: list[dict],
                  *, rwp_factor: float = RWP_FACTOR,
                  wt_tol: float = WT_TOL_PP) -> list[str]:
    """返回失败原因列表（空 = 通过）。``results`` 与 sweep 产物同格式。"""
    fails: list[str] = []
    base = baseline.get("samples") or {}
    seen = set()
    for rec in results or ():
        if rec.get("error"):
            fails.append(f"{_short(rec.get('sample', '?'))}: refinement error")
            continue
        key = _short(rec.get("sample", ""))
        ref = base.get(key)
        if not ref:
            continue
        seen.add(key)
        rwp = float(rec.get("our_rwp", rec.get("rwp", 0.0)))
        if rwp > rwp_factor * float(ref["maud_rwp"]):
            fails.append(
                f"{key}: Rwp {rwp:.2f} > {rwp_factor:.1f}×MAUD "
                f"({rwp_factor * float(ref['maud_rwp']):.2f})")
        got = sorted(float(v) for v in (rec.get("wt_pct") or rec.get("wt") or {}).values())
        want = sorted(float(v) for v in (ref.get("wt") or {}).values())
        if len(got) != len(want):
            fails.append(f"{key}: phase count {len(got)} != {len(want)}")
            continue
        for a, b in zip(got, want):
            if abs(a - b) > wt_tol:
                fails.append(f"{key}: wt {a:.2f} vs baseline {b:.2f} "
                             f"(>{wt_tol:.1f} pp)")
    missing = set(base) - seen
    if missing and results:
        fails.append("missing samples: " + ", ".join(sorted(missing)))
    return fails


def test_gate_baseline_is_well_formed():
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    samples = data["samples"]
    assert len(samples) == 7
    for name, ref in samples.items():
        assert ref["maud_rwp"] > 0.0
        assert ref["rwp"] > 0.0
        assert abs(sum(ref["wt"].values()) - 100.0) < 0.5, name


def test_gate_accepts_matching_results():
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    results = []
    for name, ref in data["samples"].items():
        results.append({
            "sample": name + "#1##20260101-000000_100",
            "our_rwp": ref["rwp"],
            "wt_pct": {f"phase{i}": v for i, v in enumerate(ref["wt"].values())},
        })
    assert gate_failures(data, results) == []


def test_gate_rejects_rwp_and_wt_regressions():
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    name, ref = next(iter(data["samples"].items()))
    bad_rwp = [{"sample": name + "#1", "our_rwp": ref["maud_rwp"] * 1.8,
                "wt_pct": {f"p{i}": v for i, v in enumerate(ref["wt"].values())}}]
    fails = gate_failures(data, bad_rwp)
    assert any("Rwp" in f for f in fails)

    bad_wt = [{"sample": name + "#1", "our_rwp": ref["rwp"],
               "wt_pct": {f"p{i}": v for i, v in enumerate(ref["wt"].values())}}]
    # 把一个相挪 3 pp（从最大相扣掉，保持总和）
    biggest = max(bad_wt[0]["wt_pct"], key=bad_wt[0]["wt_pct"].get)
    bad_wt[0]["wt_pct"][biggest] -= 3.0
    other = "p0" if biggest != "p0" else "p1"
    bad_wt[0]["wt_pct"][other] += 3.0
    fails = gate_failures(data, bad_wt)
    assert any("wt" in f for f in fails)


def test_gate_on_real_sweep_results():
    path = Path(os.environ.get("POLYXRD_MAUD_RESULTS", DEFAULT_RESULTS))
    if not path.exists():
        pytest.skip("no sweep results; run sweep_v4.py first")
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    results = json.loads(path.read_text(encoding="utf-8"))
    fails = gate_failures(data, results)
    assert not fails, "\n".join(fails)
