"""S08 检索排序基准 (13 试样, A/B 两级) —— 手册 v1 · M-B 第一项
===================================================================
只读基准: 不改任何算法。
  A 级: 真值元素 restraint (maybe = 真值相元素并集) → 测 FoM 打分质量;
  B 级: 无 restraint 全库 → 测端到端 (预筛+打分+排序)。
指标: top-1 / top-3 / top-10 真值召回、MRR、真值平均排名 (MISS = 排名 >20)。

寻峰口径: 固定 `default_peak_list` (无幅度下限 min_signal_abs=0 /
min_prominence_frac=0, 噪声峰会进入特异性项) —— 所有数字都在该口径下。

产物: docs/基准报告-物相检索-v1.md
用法: venv/Scripts/python.exe scripts/bench_search_match.py [--samples 2-1 ...]
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
OUT = ROOT / "docs" / "基准报告-物相检索-v1.md"
TOP_N = 20

# 真值相名即内置库名 (与 bench_refinement_v21.CASES 同源)
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
    s = _GREEK.sub("", name or "")
    return s.replace(" ", "").replace("-", "").lower()


def _name_eq(candidate: str, truth: str) -> bool:
    a, b = _norm(candidate), _norm(truth)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _rank_of(cand_names: list[str], truth: str):
    """真值相在候选列表里的 1-based 排名; 不在 → None (MISS)。"""
    for i, c in enumerate(cand_names):
        if _name_eq(c, truth):
            return i + 1
    return None


def run_case(sample: str, pi) -> dict:
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import default_peak_list

    want, note = TRUTH[sample]
    data = DataLoader().load(DATA / f"{sample}.txt")
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    gpl = default_peak_list(data)

    # 真值相元素并集 (A 级 restraint 用)
    truth_elements: set = set()
    for tw in want:
        for p in pi._phase_database:
            if _name_eq(p.name or "", tw):
                truth_elements |= set(p.elements or ())
                break
    ef_A = {"must": [], "maybe": sorted(truth_elements), "exclude": []}

    out = {"sample": sample, "note": note, "truth": want}
    for level, ef in (("A", ef_A), ("B", None)):
        t0 = time.perf_counter()
        matches = pi.identify_with_element_filter(
            data, peaks=gpl, element_filter=ef, top_n=TOP_N, tolerance=0.2)
        dt = time.perf_counter() - t0
        names = [m.phase.name or "" for m in matches]
        scores = [float(m.score) for m in matches]
        ranks = {tw: _rank_of(names, tw) for tw in want}
        out[level] = {"ranks": ranks, "n_cand": len(matches),
                      "t": dt, "names": names, "scores": scores}
    return out


def _level_metrics(rows: list, level: str):
    ranks = [r[level]["ranks"][tw] for r in rows for tw in r["truth"]]
    found = [x for x in ranks if x is not None]
    n = len(ranks)
    top1 = sum(1 for x in ranks if x == 1)
    top3 = sum(1 for x in ranks if x and x <= 3)
    top10 = sum(1 for x in ranks if x and x <= 10)
    mrr = sum((1.0 / x) for x in found) / n if n else 0.0
    mean_rank = sum(found) / len(found) if found else float("nan")
    return {"n": n, "top1": top1, "top3": top3, "top10": top10,
            "mrr": mrr, "mean_rank": mean_rank, "miss": n - len(found)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="*", default=None)
    args = ap.parse_args()
    samples = args.samples or list(TRUTH)

    from polyxrd.services.phase_identifier import PhaseIdentifier
    pi = PhaseIdentifier()

    rows = []
    for s in samples:
        print(f"[{s}] running ...", flush=True)
        try:
            rows.append(run_case(s, pi))
        except Exception as exc:  # noqa: BLE001
            rows.append({"sample": s, "error": repr(exc)})
            print(f"[{s}] ERROR: {exc!r}", flush=True)

    valid = [r for r in rows if "error" not in r]
    mA = _level_metrics(valid, "A")
    mB = _level_metrics(valid, "B")

    def _fmt(m):
        return (f"top1 {m['top1']}/{m['n']} ({100*m['top1']/m['n']:.0f}%) · "
                f"top3 {m['top3']}/{m['n']} ({100*m['top3']/m['n']:.0f}%) · "
                f"top10 {m['top10']}/{m['n']} ({100*m['top10']/m['n']:.0f}%) · "
                f"MRR {m['mrr']:.3f} · 平均排名 {m['mean_rank']:.1f} · "
                f"MISS {m['miss']}")

    lines = [
        "# 基准报告 · 物相检索排序 v1（S08 标尺）",
        "",
        "> 生成脚本：`scripts/bench_search_match.py`（只读基准，不改算法）",
        "> **寻峰口径声明**：`default_peak_list`（无幅度下限 min_signal_abs=0 /",
        "> min_prominence_frac=0），噪声峰进入 FoM 特异性项 —— 本报告全部数字同口径。",
        f"> A 级 = 真值元素 restraint（maybe = 真值元素并集）；B 级 = 无约束全库。",
        f"> 候选截断 top_n={TOP_N}；排名 > {TOP_N} 记 MISS。",
        "> 手册 §S08 基线（内置库）：Top-10 召回 19/20 = 95%、真值排名 1–4、",
        "> 5-1 方石英 MISS —— 待本报告 B 级数字对照。",
        "",
        "## 一、总览",
        "",
        "| 级别 | 指标 |",
        "|---|---|",
        f"| A 级（真值元素约束） | {_fmt(mA)} |",
        f"| B 级（无约束端到端） | {_fmt(mB)} |",
        "",
        "## 二、逐试样真值排名",
        "",
        "| 试样 | 真值相 | A 级排名 | B 级排名 | B 级 FoM |",
        "|---|---|---|---|---|",
    ]
    for r in valid:
        for tw in r["truth"]:
            ra = r["A"]["ranks"][tw]
            rb = r["B"]["ranks"][tw]
            fa = "—" if rb is None else f"{r['B']['scores'][rb - 1]:.3f}"
            fmt = lambda x: (str(x) if x else "MISS")  # noqa: E731
            lines.append(f"| {r['sample']} | {tw} | {fmt(ra)} | {fmt(rb)} | {fa} |")

    lines += ["", "## 三、手册 §S08 验证点核对", ""]
    cr = [(r["sample"], r["B"]["ranks"].get("Cristobalite"))
          for r in valid if "Cristobalite" in r["B"]["ranks"]]
    for s, rk in cr:
        lines.append(f"- 方石英（{s}）B 级排名: {'**MISS**' if rk is None else rk}")
    miss_b = [(r["sample"], tw) for r in valid for tw in r["truth"]
              if r["B"]["ranks"][tw] is None]
    lines.append(f"- B 级 MISS 清单: {miss_b or '无'}")
    miss_a = [(r["sample"], tw) for r in valid for tw in r["truth"]
              if r["A"]["ranks"][tw] is None]
    lines.append(f"- A 级 MISS 清单（元素约束也救不回 → FoM 打分问题）: {miss_a or '无'}")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {OUT}")
    print("A:", _fmt(mA))
    print("B:", _fmt(mB))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
