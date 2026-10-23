#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1 源数据对账：`PolyXRD-DataBase/COD` 的 CIF 清单 vs 磁盘实际文件。

做三件事（全部只读，不改任何文件）：
  1. 逐条核对 manifest 中 lib='COD' 的记录在磁盘上是否存在、size 是否一致；
  2. 统计无机/有机分布、体积分布、异常项（缺失 / 尺寸不符 / 空文件）；
  3. 输出 JSON 报告 + 控制台摘要，供后续建库引用（判据：缺失 <0.1%）。

用法:
    python scripts/audit_cod_source.py --out docs/bench/cod_source_audit.json
    python scripts/audit_cod_source.py --limit 5000        # 抽样快跑
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

#: 共享数据根（2026-10-23 起在仓库外，PolyXRD / XinMatch 两库共用）。
DEFAULT_BASE = os.environ.get("XRD_DATA_ROOT") or r"D:/Project/XRD/sync-COD"
DEFAULT_MANIFEST = os.path.join(DEFAULT_BASE, "inorg_manifest.sqlite")
DEFAULT_COD = os.path.join(DEFAULT_BASE, "COD")


def audit(manifest: str, cod_dir: str, limit: int = 0) -> dict:
    """遍历 manifest 的 COD 记录，核对磁盘。"""
    if not os.path.exists(manifest):
        raise FileNotFoundError(manifest)
    con = sqlite3.connect("file:%s?mode=ro" % manifest, uri=True)
    sql = "SELECT cod_id, rel, is_inorg, size FROM files WHERE lib='COD' ORDER BY cod_id"
    if limit:
        sql += " LIMIT %d" % int(limit)

    t0 = time.perf_counter()
    n = n_inorg = n_missing = n_size = n_empty = 0
    sz_total = sz_inorg = 0
    missing: list[str] = []
    size_bad: list[dict] = []
    n_zero_peaks_src = 0

    for cod_id, rel, is_inorg, size in con.execute(sql):
        n += 1
        path = os.path.join(cod_dir, str(rel).replace("\\", "/"))
        try:
            st = os.stat(path)
        except OSError:
            n_missing += 1
            if len(missing) < 50:
                missing.append("%d:%s" % (cod_id, rel))
            continue
        sz_total += st.st_size
        if is_inorg:
            n_inorg += 1
            sz_inorg += st.st_size
        if st.st_size == 0:
            n_empty += 1
        elif size and st.st_size != size:
            n_size += 1
            if len(size_bad) < 50:
                size_bad.append({"cod_id": cod_id, "manifest": size,
                                 "disk": st.st_size, "rel": rel})
        if n % 50000 == 0:
            print("  ... %d/%d" % (n, n), flush=True)
    con.close()

    elapsed = time.perf_counter() - t0
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "manifest": manifest,
        "cod_dir": cod_dir,
        "checked": n,
        "inorg": n_inorg,
        "organic": n - n_inorg,
        "missing": n_missing,
        "size_mismatch": n_size,
        "empty_files": n_empty,
        "size_gib_total": round(sz_total / 2**30, 2),
        "size_gib_inorg": round(sz_inorg / 2**30, 2),
        "missing_rate": round(n_missing / n, 6) if n else 0.0,
        "pass": (n_missing / n) < 0.001 if n else False,
        "elapsed_s": round(elapsed, 1),
        "samples_missing": missing,
        "samples_size_mismatch": size_bad,
        "files_per_s": round(n / elapsed, 1) if elapsed else 0,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--cod-dir", default=DEFAULT_COD)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="docs/bench/cod_source_audit.json")
    args = ap.parse_args(argv)

    print("S1 源数据对账")
    print("  manifest:", args.manifest)
    print("  cod_dir :", args.cod_dir)
    rep = audit(args.manifest, args.cod_dir, args.limit)
    print(json.dumps(rep, ensure_ascii=False, indent=2)[:2000])

    if args.out:
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        print("report ->", out)

    print("S1 判据: 缺失率 %.4f%% < 0.1%%  ->  %s"
          % (rep["missing_rate"] * 100, "PASS" if rep["pass"] else "FAIL"))
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
