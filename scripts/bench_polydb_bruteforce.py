#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polyDB 剪枝正确性基准：`search_by_d_peaks` vs 全库暴力精确打分。

用途（v4.0.0 代码评估新增）：验证 polyDB 的"位图倒排 + 精确前置键 + 自适应
扩池"没有丢候选。对每个基准试样：

  1) 用同一套 `_hanawalt_metric` 对**全库所有相**暴力打分（无剪枝），按与
     reader 完全相同的排序键（打分主键 + 行号决胜）取前 N 个 eid；
  2) 调 `PolyDatabase.search_by_d_peaks(..., limit=N)` 取前 N 个 eid；
  3) 逐条比对；并报 search/暴力的分级耗时。

判据：两组 eid **逐条一致**（不是集合相等 —— 顺序也要一致）。
Inorg（77,500 相）13 试样全绿；Full（521,361 相）单试样暴力约 45~55 s。

用法：
    python scripts/bench_polydb_bruteforce.py D:/path/COD-Inorg-20261021.polyDB
    python scripts/bench_polydb_bruteforce.py <db> --samples 1-2 5-1 --n 100
    python scripts/bench_polydb_bruteforce.py <db> --json docs/bench/x.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA = Path(r"D:/Project/XRD/test_xrd/txt")
SAMPLES = ["1-1", "1-2", "2-1", "2-2", "3-1", "3-2",
           "4-1", "5-1", "5-2", "5-2b", "5-3", "7-1", "7-2"]


def load_peaks(sample: str):
    """试样 → (波长, [(2θ, 强度), ...])，与检索入口用同一套默认寻峰。"""
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import default_peak_list

    data = DataLoader().load(DATA / ("%s.txt" % sample))
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    pl = default_peak_list(data)
    return data.wavelength, [(p.two_theta, float(p.intensity)) for p in pl.peaks]


def to_d(tth_list, wavelength):
    out = []
    for t in tth_list:
        s = np.sin(np.radians(t / 2.0))
        if s > 1e-6:
            out.append(wavelength / (2.0 * s))
    return out


def brute_force(db, md, mi, *, tol=0.02, min_match=3, max_ref_peaks=40,
                main_peak_topk=3, chunk=4096):
    """全库暴力精确打分 → 排序后的 (metric, row) 列表（键与 reader 同口径）。"""
    from polyxrd.services.polydb import _hanawalt_metric

    pairs = sorted(zip((float(x) for x in md), (float(v) for v in mi)),
                   key=lambda p: p[0])
    md_s = np.asarray([p[0] for p in pairs], dtype=np.float64)
    mi_s = np.asarray([p[1] for p in pairs], dtype=np.float64)
    main_topk = [float(md_s[j]) for j in np.argsort(-mi_s)[:max(1, main_peak_topk)]]
    n = db.stats().phases
    recs = []
    for s in range(0, n, chunk):
        e = min(s + chunk, n)
        rows = np.arange(s, e)
        d_all, i_all = db.peaks_of_rows(rows)
        for idx in range(rows.size):
            m = d_all[idx] > 0
            d_np, i_np = d_all[idx][m], i_all[idx][m]
            if d_np.size == 0:
                continue
            met = _hanawalt_metric(
                d_np, i_np, md=md_s, mi=mi_s, main_meas_d_topk=main_topk,
                tol_abs=tol, trel=0.0, use_rel=False,
                max_ref_peaks=max_ref_peaks)
            if met is None or met["n_matched_meas"] < min_match:
                continue
            recs.append((met, int(rows[idx])))
    recs.sort(key=lambda r: (r[0]["main_peak_match"], r[0]["top_precision"],
                             r[0]["intensity_weighted_top_recall"],
                             r[0]["top_recall"], r[0]["meas_ratio"],
                             r[0]["score"], -r[1]), reverse=True)
    return recs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="polyDB 目录")
    ap.add_argument("--samples", nargs="*", default=None)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    from polyxrd.services.polydb import PolyDatabase

    t0 = time.perf_counter()
    db = PolyDatabase(args.db)
    if not db.is_ready():
        print("polyDB 不可用: %s" % args.db)
        return 2
    print("db ready=%s stats: phases=%d k=%d size=%.1fMB (init %.3fs)"
          % (db.is_ready(), db.stats().phases, db.stats().k,
             db.stats().size_mb, time.perf_counter() - t0))

    samples = args.samples or SAMPLES
    report = {"db": args.db, "n": args.n, "samples": []}
    rc = 0
    for sample in samples:
        wavelength, peaks = load_peaks(sample)
        md = to_d([p[0] for p in peaks], wavelength)
        mi = [p[1] for p in peaks]
        db.search_by_d_peaks(md, mi, tolerance=0.02, min_match=3, limit=args.n,
                             max_ref_peaks=40, main_peak_topk=3)   # 预热页缓存
        t0 = time.perf_counter()
        got = db.search_by_d_peaks(md, mi, tolerance=0.02, min_match=3,
                                   limit=args.n, max_ref_peaks=40,
                                   main_peak_topk=3)
        search_s = time.perf_counter() - t0
        got_ids = [int(r["cod_id"]) for r in got]

        t0 = time.perf_counter()
        brute = brute_force(db, md, mi, tol=0.02, min_match=3)
        brute_s = time.perf_counter() - t0
        eids = db.eid_of_rows([r for _m, r in brute[:args.n]])
        missing = [i for i in eids if i not in set(got_ids)]
        same = got_ids == eids
        if missing:
            rc = 1
        print("[%s] n_meas=%d search=%.3fs brute=%.2fs cand=%d top%d %s missing=%s"
              % (sample, len(md), search_s, brute_s, len(brute), args.n,
                 "PASS" if same else ("FAIL" if missing else "ORDER-ONLY"),
                 missing[:5]), flush=True)
        report["samples"].append({
            "sample": sample, "n_meas": len(md),
            "search_s": round(search_s, 3), "brute_s": round(brute_s, 2),
            "same": same, "missing": missing,
        })
    report["ok"] = rc == 0
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print("已写出 %s" % p)
    print("polyDB 剪枝正确性: %s" % ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
