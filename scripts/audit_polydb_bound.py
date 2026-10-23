#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polyDB 前置键审计：`_bound_keys` 是否等于 `_hanawalt_metric` 的前三个主键。

背景（v4.0.0 代码评估）：候选截断依赖"排序键的上界"。0.2~3.x 的实现用
"最近测量峰 + 列命中数"近似，实测在真实库上**并非上界**（top-300 里
200~294 行被低估，最大 0.375），导致 5-1 试样丢 3 个物相。现在
:meth:`PolyDatabase._bound_keys` 改为精确复刻前三个分量，本脚本是它的
回归探针：

  · mh / p5 必须**完全相等**；
  · wrec 允许 `bound >= exact`（重叠窗按并集，安全上界），且差值 <= 0.05。

用法：
    python scripts/audit_polydb_bound.py D:/path/COD-Inorg-20261021.polyDB
    python scripts/audit_polydb_bound.py <db> --rows 2000 --samples 1-2 5-1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from bench_polydb_bruteforce import load_peaks, to_d  # noqa: E402

TOL = 0.02


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="polyDB 目录")
    ap.add_argument("--samples", nargs="*",
                    default=["1-2", "5-1", "7-2"])
    ap.add_argument("--rows", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261023)
    args = ap.parse_args()

    from polyxrd.services.polydb import PolyDatabase, _hanawalt_metric

    db = PolyDatabase(args.db)
    if not db.is_ready():
        print("polyDB 不可用: %s" % args.db)
        return 2
    db._get_arrays()
    rng = np.random.default_rng(args.seed)
    total = bad = 0
    for sample in args.samples:
        wavelength, peaks = load_peaks(sample)
        pairs = sorted(zip(to_d([p[0] for p in peaks], wavelength),
                           [p[1] for p in peaks]), key=lambda p: p[0])
        md = np.asarray([p[0] for p in pairs], dtype=np.float64)
        mi = np.asarray([p[1] for p in pairs], dtype=np.float64)
        main_topk = [float(md[j]) for j in np.argsort(-mi)[:3]]
        rows = rng.integers(0, db.stats().phases, size=args.rows)
        bounds = db._bound_keys(rows, md, mi, TOL, 3)
        d_all, i_all = db.peaks_of_rows(rows)
        for j in range(rows.size):
            m = d_all[j] > 0
            d_np, i_np = d_all[j][m], i_all[j][m]
            met = _hanawalt_metric(
                d_np, i_np, md=md, mi=mi, main_meas_d_topk=main_topk,
                tol_abs=TOL, trel=0.0, use_rel=False, max_ref_peaks=40)
            if met is None:
                continue
            total += 1
            ok = (abs(bounds[j, 0] - met["main_peak_match"]) < 1e-12
                  and abs(bounds[j, 1] - met["top_precision"]) < 1e-12
                  and bounds[j, 2] + 1e-12
                  >= met["intensity_weighted_top_recall"]
                  and bounds[j, 2] - met["intensity_weighted_top_recall"]
                  <= 0.05)
            if not ok:
                bad += 1
                if bad <= 5:
                    print("MISMATCH row=%d bound=(%.3f,%.3f,%.3f) exact=(%.3f,%.3f,%.3f)"
                          % (rows[j], bounds[j, 0], bounds[j, 1], bounds[j, 2],
                             met["main_peak_match"], met["top_precision"],
                             met["intensity_weighted_top_recall"]))
        print("%-4s 抽样 %d 行完成（累计不一致 %d/%d）"
              % (sample, rows.size, bad, total), flush=True)
    print("前置键审计: %s（%d/%d 行不一致）"
          % ("PASS" if bad == 0 else "FAIL", bad, total))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
