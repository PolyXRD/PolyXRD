#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S10 / S17 polyDB 预筛召回基准：走**线上检索链路** vs 全量扫描。

判据（线路图 §G2 / S10）：**每个试样的 top-100 被 polyDB 检索结果完全覆盖**。
"覆盖"按 eid 集合比较，不比顺序 —— 顺序由同一套 Hanawalt 键决定，集合不一致
才说明预筛真的丢了候选。

两侧都调同一个 `_hanawalt_metric`（线上打分原子），所以差异只可能来自
"候选池"，这正是本基准要盯的东西。

用法：
    python scripts/bench_polydb_prescreen.py <db.polyDB>
    python scripts/bench_polydb_prescreen.py <db> --limit 100 --json out.json
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
SAMPLES = ["1-1", "1-2", "2-1", "2-2", "3-1", "3-2", "4-1",
           "5-1", "5-2", "5-2b", "5-3", "7-1", "7-2"]
TOL = 0.02
MIN_MATCH = 3
MAX_REF = 40
MAIN_TOPK = 3


def measured_peaks(sample: str, n_top: int = 25):
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import (
        PhaseIdentifier, default_peak_list,
    )

    data = DataLoader().load(DATA / ("%s.txt" % sample))
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    pl = default_peak_list(data)
    try:
        wl = float(PhaseIdentifier()._effective_wavelength(data))
    except Exception:  # noqa: BLE001
        wl = 1.5406
    tt = np.asarray([p.two_theta for p in pl.peaks], dtype=np.float64)
    ii = np.asarray([p.intensity for p in pl.peaks], dtype=np.float64)
    order = np.argsort(ii)[::-1][:n_top]
    tt, ii = tt[order], ii[order]
    d = wl / (2.0 * np.sin(np.radians(tt / 2.0)))
    o = np.argsort(d)
    return d[o], ii[o], wl


def rank_full(db, md, mi, tol, chunk: int = 8192):
    """全量逐相精确打分（暴力基线，与线上同一套 `_hanawalt_metric`）。"""
    from polyxrd.services.polydb import _hanawalt_metric

    main_topk = [float(md[j]) for j in np.argsort(-mi)[:MAIN_TOPK]]
    n = db.stats().phases
    out = []
    for s in range(0, n, chunk):
        rows = np.arange(s, min(s + chunk, n))
        d_all, i_all = db.peaks_of_rows(rows)
        for j in range(d_all.shape[0]):
            dd, ii = d_all[j], i_all[j]
            m = dd > 0
            if not m.any():
                continue
            met = _hanawalt_metric(
                dd[m], ii[m], md=md, mi=mi, main_meas_d_topk=main_topk,
                tol_abs=tol, trel=0.0, use_rel=False, max_ref_peaks=MAX_REF)
            if met is None or met["n_matched_meas"] < MIN_MATCH:
                continue
            out.append((int(rows[j]), met))
    out.sort(key=lambda t: (
        t[1]["main_peak_match"], t[1]["top_precision"],
        t[1]["intensity_weighted_top_recall"], t[1]["top_recall"],
        t[1]["meas_ratio"], t[1]["score"]), reverse=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--limit", type=int, default=100,
                    help="比较前 N 名的覆盖情况（默认 100）")
    ap.add_argument("--json", default="")
    ap.add_argument("--samples", nargs="*", default=None)
    args = ap.parse_args(argv)

    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase(args.db)
    if not db.is_ready():
        print("polyDB 不可用: %s" % args.db)
        return 2
    st = db.stats()
    print("polyDB: %d phases, K=%d, bins=%d, %.1f MB"
          % (st.phases, st.k, st.bins, st.size_mb))

    rows_out = []
    ok_all = True
    for s in (args.samples or SAMPLES):
        md, mi, _wl = measured_peaks(s)

        t0 = time.perf_counter()
        pred = db.search_by_d_peaks(
            md.tolist(), mi.tolist(), tolerance=TOL, min_match=MIN_MATCH,
            max_ref_peaks=MAX_REF, main_peak_topk=MAIN_TOPK, limit=args.limit)
        t_pred = time.perf_counter() - t0
        pred_ids = [int(r["cod_id"]) for r in pred]

        t0 = time.perf_counter()
        full = rank_full(db, md, mi, TOL)
        t_full = time.perf_counter() - t0
        full_ids = db.eid_of_rows([t[0] for t in full[:args.limit]])

        pred_set = set(pred_ids)
        inter = len(pred_set & set(full_ids))
        missed = [e for e in full_ids if e not in pred_set]
        # 边界并列：第 limit 名往后常跟着一大串打分**完全相同**的条目（多相样品
        # 的仿真相）。截断落在并列组里时取哪几条纯属决胜规则，不算漏检。
        def _mkey(met):
            return (met["main_peak_match"], met["top_precision"],
                    met["intensity_weighted_top_recall"], met["top_recall"],
                    met["meas_ratio"], met["score"])

        cutoff = _mkey(full[len(full_ids) - 1][1]) if full_ids else None
        kbyid = dict(zip(full_ids, [_mkey(t[1]) for t in full[:len(full_ids)]]))
        hard = [e for e in missed if kbyid.get(e) != cutoff]
        ok = not hard
        ok_all = ok_all and ok
        rows_out.append({
            "sample": s, "n_pred": len(pred_ids), "n_full": len(full_ids),
            "covered": inter, "missed": len(missed), "missed_hard": len(hard),
            "missed_ids": missed[:10], "missed_hard_ids": hard[:10],
            "pred_s": round(t_pred, 2), "full_s": round(t_full, 2),
            "verdict": "PASS" if ok else "FAIL",
        })
        print("%-5s pred=%5.2fs full=%6.2fs  top%d ∩=%3d 并列截断=%2d 真漏=%2d  %s"
              % (s, t_pred, t_full, args.limit, inter, len(missed) - len(hard),
                 len(hard), "PASS" if ok else "FAIL"), flush=True)

    rep = {"db": args.db, "limit": args.limit, "tol": TOL,
           "min_match": MIN_MATCH, "max_ref_peaks": MAX_REF,
           "samples": rows_out, "ok": ok_all}
    print("\nS10 判据: 每个试样 top%d 被检索结果完全覆盖 -> %s"
          % (args.limit, "PASS" if ok_all else "FAIL"))
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print("已写出 %s" % p)
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
