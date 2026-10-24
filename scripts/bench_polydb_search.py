#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polyDB 检索召回 / 耗时基准（v4.1.2：旧 COD sqlite 后端已删除，不再 A/B）。

对 13 个基准试样逐个跑 polyDB 的完整检索链路，报告：

  1. **召回**（准确性第一）：真值相在候选列表里的名次 → top1/top3/top10、
     MRR、MISS，两级口径（A 级 = 真值元素约束 / B 级 = 无约束）；
  2. **耗时**：检索墙钟时间（先跑一次预热 mmap，报第二次）。

说明：v4.1.0 已删除旧格式 COD sqlite 检索入口，原先的 "旧库 vs polyDB"
对照基准不再可跑；本脚本保留为**回归基准**（召回 + 耗时），用于换库/改
打分后的横向比较。

用法：
    python scripts/bench_polydb_search.py <db.polyDB>
    python scripts/bench_polydb_search.py <db> --levels B --json docs/bench/x.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA = Path(r"D:/Project/XRD/test_xrd/txt")
TOP_N = 20
TOL = 0.2

# 13 试样真值（与 scripts/bench_fom_ablation.py 同一张表，勿另立一套）
TRUTH: dict[str, list[str]] = {
    "1-1": ["Lithium iron phosphate"],
    "1-2": ["NCM 811"],
    "2-1": ["Zincite", "Calcite"],
    "2-2": ["Anatase", "Rutile"],
    "3-1": ["Zincite", "Corundum", "Fluorite"],
    "3-2": ["Zincite", "Corundum", "Fluorite"],
    "4-1": ["Zincite", "Corundum", "Fluorite", "Brucite"],
    "5-1": ["α-Quartz", "Cristobalite", "Calcite", "Magnesite", "Dolomite"],
    "5-2": ["α-Quartz", "Cristobalite", "Calcite", "Hematite", "Muscovite"],
    "5-2b": ["α-Quartz", "Cristobalite", "Calcite", "Hematite", "Muscovite"],
    "5-3": ["α-Quartz", "Gehlenite", "Fluorapatite", "Goethite", "Kaolinite"],
    "7-1": ["α-Quartz", "Boehmite", "Anatase", "Goethite", "Kaolinite",
            "Gibbsite", "Hematite"],
    "7-2": ["Quartz", "Albite", "Biotite", "Clinochlore", "Hornblende", "Zircon"],
}

_GREEK = re.compile(r"^[αβγ]\s*-\s*")
_COD_ID = re.compile(r"\(COD\s*(\d+)\)")


def _eid_of(match) -> int | None:
    """从候选取 COD 编号（优先 db_id，其次展示名里的 ``(COD …)``）。"""
    if match.phase.db_id is not None:
        try:
            return int(match.phase.db_id)
        except (TypeError, ValueError):
            pass
    m = _COD_ID.search(match.phase.name or "")
    return int(m.group(1)) if m else None


def _norm(name: str) -> str:
    return _GREEK.sub("", name or "").replace(" ", "").replace("-", "").lower()


def _name_eq(cand: str, truth: str) -> bool:
    a, b = _norm(cand), _norm(truth)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _rank_of(names: list[str], truth: str):
    for i, c in enumerate(names):
        if _name_eq(c, truth):
            return i + 1
    return None


def _truth_elements(pi, want: list[str]) -> set:
    """真值元素（只从内置库解析，用于 A 级约束）。"""
    out: set = set()
    for tw in want:
        for p in pi._phase_database:
            if _name_eq(p.name or "", tw):
                out |= set(p.elements or ())
                break
    return out


def run_backend(pi, db, sample: str, level: str) -> dict:
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import default_peak_list

    want = TRUTH[sample]
    data = DataLoader().load(DATA / ("%s.txt" % sample))
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    peaks = default_peak_list(data)

    ef = None
    if level == "A":
        els = _truth_elements(pi, want)
        ef = {"must": [], "maybe": sorted(els), "exclude": []} if els else None

    t0 = time.perf_counter()
    matches = pi.identify_with_polydb(
        data, peaks=peaks, element_filter=ef, top_n=TOP_N, tolerance=TOL,
        db=db)
    dt = time.perf_counter() - t0

    return {
        "sample": sample,
        "level": level,
        "elapsed_s": round(dt, 2),
        "n": len(matches),
        "ids": [_eid_of(m) for m in matches],
        "names": [m.phase.name or "" for m in matches],
        "ranks": {tw: _rank_of([m.phase.name or "" for m in matches], tw)
                  for tw in want},
    }


def _agg(rows: list[dict]) -> dict:
    ranks = [r for row in rows for r in row["ranks"].values()]
    n = len(ranks)
    found = [x for x in ranks if x]
    return {
        "n": n,
        "top1": sum(1 for x in ranks if x == 1),
        "top3": sum(1 for x in ranks if x and x <= 3),
        "top10": sum(1 for x in ranks if x and x <= 10),
        "mrr": round(sum(1.0 / x for x in found) / n, 3) if n else 0.0,
        "miss": n - len(found),
        "time_s": round(sum(r["elapsed_s"] for r in rows), 1),
        "avg_s": round(sum(r["elapsed_s"] for r in rows) / max(1, len(rows)), 2),
    }


def _fmt(tag: str, m: dict) -> str:
    n = max(1, m["n"])
    return ("  %-8s top1 %2d/%d (%3.0f%%) · top3 %2d · top10 %2d (%3.0f%%) · "
            "MRR %.3f · MISS %d · %.1fs (avg %.2fs/sample)"
            % (tag, m["top1"], m["n"], 100 * m["top1"] / n, m["top3"],
               m["top10"], 100 * m["top10"] / n, m["mrr"], m["miss"],
               m["time_s"], m["avg_s"]))


def main() -> int:
    global TOP_N
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="polyDB 目录")
    ap.add_argument("--samples", nargs="*", default=None)
    ap.add_argument("--levels", default="B")
    ap.add_argument("--top-n", type=int, default=TOP_N)
    ap.add_argument("--json", default=None)
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()

    TOP_N = args.top_n
    samples = args.samples or list(TRUTH)
    levels = [x.strip().upper() for x in args.levels.split(",") if x.strip()]

    from polyxrd.services.phase_identifier import PhaseIdentifier
    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase(args.db)
    if not db.is_ready():
        print("polyDB 不可用: %s" % args.db)
        return 2
    pi = PhaseIdentifier()

    report: dict = {"db": args.db, "top_n": TOP_N, "tol": TOL,
                    "levels": {}, "verdict": "PASS"}
    ok_all = True

    for level in levels:
        print("=== level %s（%s）===" % (
            level, "真值元素约束" if level == "A" else "无约束"), flush=True)
        # 预热：polyDB 的 mmap 首读要落页缓存，别算进计时
        run_backend(pi, db, samples[0], level)

        rows = []
        for s in samples:
            row = run_backend(pi, db, s, level)
            rows.append(row)
            print("  %-6s %.2fs · ranks %s"
                  % (s, row["elapsed_s"],
                     {k: v for k, v in row["ranks"].items()}), flush=True)

        m = _agg(rows)
        print(_fmt("polydb", m))
        if m["miss"]:
            ok_all = False
            print("  → FAIL：%d 个真值相未被召回（MISS）" % m["miss"])
        else:
            print("  → PASS：全部真值相均被召回")
        report["levels"][level] = {
            "metrics": m,
            "rows": rows,
            "verdict": "PASS" if not m["miss"] else "FAIL",
        }

    report["verdict"] = "PASS" if ok_all else "FAIL"
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print("已写出 %s" % p)
    if args.detail:
        for level, blk in report["levels"].items():
            for row in blk["rows"]:
                print(level, row["sample"], row["ranks"])
    print("polyDB search benchmark: %s" % ("PASS" if ok_all else "FAIL"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
