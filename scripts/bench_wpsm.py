"""v3.0.0 WPSM 基准仪 —— 全谱拟合精排 vs 峰表 FoM 基线 (13 试样)。

两阶段: 与 FPFM 同构 —— 先用现有检索做**预筛** (top prescreen_top_n), 再对
预筛候选做**全谱精排** (WPSM), 按 FoM=exp(−Rwp/σ) 重排, 取 top_n 输出。

指标沿用 scripts/bench_fom_ablation.py 的口径, 可直接与历史基线比:
  A 级 = 真值元素约束; B 级 = 无约束; 组合 = build_refinement_combination

用法:
  venv/Scripts/python.exe scripts/bench_wpsm.py --levels B
  venv/Scripts/python.exe scripts/bench_wpsm.py --sigma 0.15,0.25,0.35
  venv/Scripts/python.exe scripts/bench_wpsm.py --prescreen 50,150
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA = Path(r"D:/Project/XRD/test_xrd\txt")
TOP_N_SEARCH = 20
TOP_N_COMBO = 12
TOL = 0.2

TRUTH: dict[str, tuple[list[str], str]] = {
    "1-1": (["Lithium iron phosphate"], "单相"),
    "1-2": (["NCM 811"], "单相 (NCM 三元)"),
    "2-1": (["Zincite", "Calcite"], "双相 50/50"),
    "2-2": (["Anatase", "Rutile"], "双相同质多象"),
    "3-1": (["Zincite", "Corundum", "Fluorite"], "三相, 含 1.4% 微量相"),
    "3-2": (["Zincite", "Corundum", "Fluorite"], "含 29.5% 非晶"),
    "4-1": (["Zincite", "Corundum", "Fluorite", "Brucite"], "四相"),
    "5-1": (["α-Quartz", "Cristobalite", "Calcite", "Magnesite", "Dolomite"],
            "五相碳酸盐-硅酸盐"),
    "5-2": (["α-Quartz", "Cristobalite", "Calcite", "Hematite", "Muscovite"],
            "五相"),
    "5-2b": (["α-Quartz", "Cristobalite", "Calcite", "Hematite", "Muscovite"],
             "5-2 重复"),
    "5-3": (["α-Quartz", "Gehlenite", "Fluorapatite", "Goethite", "Kaolinite"],
            "五相"),
    "7-1": (["α-Quartz", "Boehmite", "Anatase", "Goethite", "Kaolinite",
             "Gibbsite", "Hematite"], "七相 (最复杂)"),
    "7-2": (["Quartz", "Albite", "Biotite", "Clinochlore", "Hornblende",
             "Zircon"], "天然矿物多相"),
}

_GREEK = re.compile(r"^[αβγ]\s*-\s*")


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


def _fmt(m) -> str:
    return (f"top1 {m['top1']:2d}/{m['n']} ({100*m['top1']/m['n']:2.0f}%) · "
            f"top3 {m['top3']:2d}/{m['n']} ({100*m['top3']/m['n']:2.0f}%) · "
            f"top10 {m['top10']:2d}/{m['n']} ({100*m['top10']/m['n']:2.0f}%) · "
            f"MRR {m['mrr']:.3f} · MISS {m['miss']}")


def run(
    label: str,
    samples: list[str],
    levels: tuple,
    *,
    prescreen_top_n: int = 0,   # 0 = 关闭 WPSM (纯 FoM 基线)
    sigma: float = 0.25,
    cell_refine: bool = True,
    bg_bound_mode: str = "scaled",
    verbose: bool = False,
) -> dict:
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import (
        PhaseIdentifier, default_peak_list,
    )
    from polyxrd.services.wpsm import WpsmConfig, wpsm_rerank

    cfg = WpsmConfig(prescreen_top_n=prescreen_top_n, top_n=TOP_N_SEARCH,
                     fom_sigma=sigma, cell_refine=cell_refine,
                     bg_bound_mode=bg_bound_mode)
    pi = PhaseIdentifier()
    rows = []
    t_wpsm = 0.0
    for s in samples:
        want, _note = TRUTH[s]
        data = DataLoader().load(DATA / f"{s}.txt")
        if not getattr(data, "wavelength", 0.0):
            data.wavelength = 1.5406
        gpl = default_peak_list(data)

        truth_elements: set = set()
        for tw in want:
            for p in pi._phase_database:
                if _name_eq(p.name or "", tw):
                    truth_elements |= set(p.elements or ())
                    break
        ef_A = {"must": [], "maybe": sorted(truth_elements), "exclude": []}

        out = {"sample": s, "truth": want}
        for level in levels:
            ef = ef_A if level == "A" else None
            n_pre = max(prescreen_top_n, TOP_N_SEARCH)
            matches = pi.identify_with_element_filter(
                data, peaks=gpl, element_filter=ef,
                top_n=n_pre, tolerance=TOL)
            if prescreen_top_n > 0 and len(matches) > 1:
                t0 = time.perf_counter()
                items = [(i, m.phase.get_reference_peaks())
                         for i, m in enumerate(matches[:prescreen_top_n])]
                timing: dict = {}
                fits = wpsm_rerank(data.two_theta, data.intensity, items,
                                   cfg=cfg, timing=timing)
                t_wpsm += time.perf_counter() - t0
                order = [f.key for f in fits]
                rest = [m for i, m in enumerate(matches[:prescreen_top_n])
                        if i not in set(order)]
                matches = [matches[i] for i in order] + rest \
                    + matches[prescreen_top_n:]
                if verbose and level == "B":
                    top = [(matches[i].phase.name or "")[:22]
                           for i in order[:6]]
                    print(f"      [{s}] WPSM top6: {top}")
            names = [m.phase.name or "" for m in matches[:TOP_N_SEARCH]]
            out[level] = {"ranks": {tw: _rank_of(names, tw) for tw in want}}
            if level == "B":
                top12 = matches[:TOP_N_COMBO]
                combo = pi.build_refinement_combination(
                    top12, expected_count=len(want),
                    min_coverage=0.3, peaks=gpl)
                cnames = [p.name or "" for p in combo]
                out["combo"] = {
                    "hit": {tw: any(_name_eq(c, tw) for c in cnames)
                            for tw in want},
                    "extra": [c for c in cnames
                              if not any(_name_eq(c, tw) for tw in want)],
                }
        rows.append(out)

    res = {"label": label}
    for level in levels:
        ranks = [r[level]["ranks"][tw] for r in rows for tw in r["truth"]]
        n = len(ranks)
        found = [x for x in ranks if x is not None]
        res[level] = {
            "n": n,
            "top1": sum(1 for x in ranks if x == 1),
            "top3": sum(1 for x in ranks if x and x <= 3),
            "top10": sum(1 for x in ranks if x and x <= 10),
            "mrr": sum(1.0 / x for x in found) / n if n else 0.0,
            "miss": n - len(found),
        }
    pl_hit = sum(sum(1 for tw in r["truth"] if r["combo"]["hit"][tw])
                 for r in rows)
    pl_n = sum(len(r["truth"]) for r in rows)
    complete = sum(1 for r in rows if all(r["combo"]["hit"].values()))
    res["combo"] = {"phase_hit": pl_hit, "phase_n": pl_n,
                    "sample_complete": complete, "sample_n": len(rows)}
    res["_rows"] = rows
    res["_t_wpsm"] = t_wpsm
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="*", default=None)
    ap.add_argument("--levels", default="A,B")
    ap.add_argument("--prescreen", default="0,150")
    ap.add_argument("--sigma", default="0.25")
    ap.add_argument("--cell", default="1")
    ap.add_argument("--bg", default="scaled")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    samples = args.samples or list(TRUTH)
    levels = tuple(x.strip().upper() for x in args.levels.split(","))

    combos = []
    for ps in args.prescreen.split(","):
        for sg in args.sigma.split(","):
            for ce in args.cell.split(","):
                combos.append((int(ps), float(sg), ce.strip() in ("1", "true", "True")))

    t_all = time.perf_counter()
    for ps, sg, ce in combos:
        label = ("baseline(FoM)" if ps == 0
                 else f"WPSM pre={ps} σ={sg} cell={int(ce)} bg={args.bg}")
        print(f"--- {label} ---", flush=True)
        r = run(label, samples, levels, prescreen_top_n=ps, sigma=sg,
                cell_refine=ce, bg_bound_mode=args.bg,
                verbose=args.verbose)
        for lv in levels:
            print(f"  {lv}: {_fmt(r[lv])}")
        c = r["combo"]
        print(f"  组合: 相级 {c['phase_hit']}/{c['phase_n']} · "
              f"试样级完全 {c['sample_complete']}/{c['sample_n']} · "
              f"WPSM 耗时 {r['_t_wpsm']:.1f}s")
        if args.detail:
            for row in r["_rows"]:
                miss_ph = [tw for tw in row["truth"]
                           if not row["combo"]["hit"][tw]]
                if miss_ph or row["combo"]["extra"]:
                    print(f"    [{row['sample']}] 缺 {miss_ph} · "
                          f"多 {row['combo']['extra']}")
    print(f"\ntotal {time.perf_counter()-t_all:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
