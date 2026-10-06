"""v2.7.0 消融仪 —— 一次跑完「检索 + 组合」双指标, 对比各变体。

只读基准: 不改任何算法源文件。通过两条途径开关特性:
  1. 给 identify_with_element_filter 传 kwargs (与真实调用路径一致);
  2. 运行时打补丁 foam 模块常量 (v2.7.0 已把内联魔法数提升为模块常量)。
运行结束自动还原补丁。

指标:
  检索 A 级 (真值元素 restraint, top_n=20) / B 级 (无约束): top1/3/10, MRR, MISS
  组合: 相级命中 x/49, 试样级完全 x/13

用法:
  venv/Scripts/python.exe scripts/_ablate_v270.py --variants baseline,minvis_0.2 --levels B
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

# 变体: kw = identify_with_element_filter 的 kwargs; foam = foam 模块常量补丁
VARIANTS = {
    "baseline": {"kw": {}, "foam": {}},
    # 可观测性: 提高"预期可见"门槛 → 复杂相/微量相的漏检惩罚应下降
    "minvis_0.2": {"kw": {"fom_min_visible_frac": 0.2}, "foam": {}},
    "minvis_0.3": {"kw": {"fom_min_visible_frac": 0.3}, "foam": {}},
    # 特异性权重 (实验峰解释力)
    "spec_0.4": {"kw": {}, "foam": {"_FOM_SPEC_WEIGHT": 0.4}},
    "spec_0.45": {"kw": {}, "foam": {"_FOM_SPEC_WEIGHT": 0.45}},
    "spec_0.5": {"kw": {}, "foam": {"_FOM_SPEC_WEIGHT": 0.5}},
    "spec_0.55": {"kw": {}, "foam": {"_FOM_SPEC_WEIGHT": 0.55}},
    "spec_0.6": {"kw": {}, "foam": {"_FOM_SPEC_WEIGHT": 0.6}},
    "spec_0.7": {"kw": {}, "foam": {"_FOM_SPEC_WEIGHT": 0.7}},
    # 强线漏检倍率
    "missmult_1.0": {"kw": {}, "foam": {"_FOM_STRONG_MISS_MULT": 1.0}},
    "missfrac_0.7": {"kw": {}, "foam": {"_FOM_STRONG_MISS_FRAC": 0.7}},
    # 强度余弦权重
    "ic_0.35": {"kw": {}, "foam": {"_FOM_INTENSITY_WEIGHT": 0.35}},
    "ic_0.10": {"kw": {}, "foam": {"_FOM_INTENSITY_WEIGHT": 0.10}},
    # B-5 PFSM 全谱拟合重排 (已实现, 默认 weight=0 关闭)
    "pfsm_0.3": {"kw": {"fom_pfsm_weight": 0.3}, "foam": {}},
    "pfsm_0.5": {"kw": {"fom_pfsm_weight": 0.5}, "foam": {}},
    "pfsm_0.7": {"kw": {"fom_pfsm_weight": 0.7}, "foam": {}},
    "pfsm_1.0": {"kw": {"fom_pfsm_weight": 1.0}, "foam": {}},
    "pfsm_0.5_n20": {"kw": {"fom_pfsm_weight": 0.5, "fom_pfsm_top_n": 20},
                     "foam": {}},
    # C-1 漏检项独立权重 (1.0 = v2.6.0 行为)
    "miss_w_0.8": {"kw": {}, "foam": {"_FOM_MISS_WEIGHT": 0.8}},
    "miss_w_0.6": {"kw": {}, "foam": {"_FOM_MISS_WEIGHT": 0.6}},
    "miss_w_0.4": {"kw": {}, "foam": {"_FOM_MISS_WEIGHT": 0.4}},
    # 组合项
    "pfsm_0.2": {"kw": {"fom_pfsm_weight": 0.2}, "foam": {}},
    "pfsm_0.3_spec_0.5": {"kw": {"fom_pfsm_weight": 0.3},
                          "foam": {"_FOM_SPEC_WEIGHT": 0.5}},
    "spec_0.5_pfsm_0.2": {"kw": {"fom_pfsm_weight": 0.2},
                          "foam": {"_FOM_SPEC_WEIGHT": 0.5}},
    "miss_w_0.6_spec_0.5": {
        "kw": {}, "foam": {"_FOM_MISS_WEIGHT": 0.6,
                           "_FOM_SPEC_WEIGHT": 0.5}},
    "miss_w_0.4_spec_0.5": {
        "kw": {}, "foam": {"_FOM_MISS_WEIGHT": 0.4,
                           "_FOM_SPEC_WEIGHT": 0.5}},
}


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


def run_variant(vname: str, spec: dict, samples: list[str],
                levels: tuple) -> dict:
    from polyxrd.services import foam
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import (
        PhaseIdentifier, default_peak_list,
    )

    saved = {k: getattr(foam, k) for k in spec["foam"]}
    for k, v in spec["foam"].items():
        setattr(foam, k, v)
    try:
        pi = PhaseIdentifier()
        rows = []
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
            ef_A = {"must": [], "maybe": sorted(truth_elements),
                    "exclude": []}

            out = {"sample": s, "truth": want}
            for level in levels:
                ef = ef_A if level == "A" else None
                matches = pi.identify_with_element_filter(
                    data, peaks=gpl, element_filter=ef,
                    top_n=TOP_N_SEARCH, tolerance=TOL, **spec["kw"])
                names = [m.phase.name or "" for m in matches]
                out[level] = {"ranks": {tw: _rank_of(names, tw)
                                        for tw in want}}
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
    finally:
        for k, v in saved.items():
            setattr(foam, k, v)
    return _summarize(vname, rows, levels)


def _summarize(vname: str, rows: list[dict], levels: tuple) -> dict:
    res = {"variant": vname}
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
    return res


def _fmt(m) -> str:
    return (f"top1 {m['top1']:2d}/{m['n']} ({100*m['top1']/m['n']:2.0f}%) · "
            f"top3 {m['top3']:2d}/{m['n']} ({100*m['top3']/m['n']:2.0f}%) · "
            f"top10 {m['top10']:2d}/{m['n']} ({100*m['top10']/m['n']:2.0f}%) · "
            f"MRR {m['mrr']:.3f} · MISS {m['miss']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="baseline")
    ap.add_argument("--samples", nargs="*", default=None)
    ap.add_argument("--levels", default="A,B")
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()

    samples = args.samples or list(TRUTH)
    levels = tuple(x.strip().upper() for x in args.levels.split(","))
    names = [v.strip() for v in args.variants.split(",")]
    for v in names:
        if v not in VARIANTS:
            print(f"unknown variant: {v}\nhave: {list(VARIANTS)}")
            return 2

    t0 = time.perf_counter()
    for v in names:
        spec = VARIANTS[v]
        print(f"--- {v}: kw={spec['kw']} foam={spec['foam']} ---", flush=True)
        r = run_variant(v, spec, samples, levels)
        c = r["combo"]
        for lv in levels:
            print(f"  {lv}: {_fmt(r[lv])}")
        print(f"  组合: 相级 {c['phase_hit']}/{c['phase_n']} · "
              f"试样级完全 {c['sample_complete']}/{c['sample_n']}")
        if args.detail:
            for row in r["_rows"]:
                miss_ph = [tw for tw in row["truth"]
                           if not row["combo"]["hit"][tw]]
                if miss_ph or row["combo"]["extra"]:
                    print(f"    [{row['sample']}] 缺 {miss_ph} · "
                          f"多 {row['combo']['extra']}")
    print(f"\ntotal {time.perf_counter()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
