"""S01 组合准确率基准 (13 试样) —— 物相检索与组合选择改进实施手册 v1 · S01
=============================================================================
只读基准: 不改任何算法。对每试样跑
  default_peak_list → identify_with_element_filter(top_n=12, tol=0.2)
  → build_refinement_combination(expected_count=真值相数, min_coverage=0.3, peaks=gpl)
指标:
  - 完全命中率 (组合 ⊇ 真值)
  - 缺失相数 / 多余相数
  - 真值相在 identify(top_n=12) 结果里的排名 (区分"检索没给到"与"组合丢掉了")

产物: docs/基准报告-物相组合-v1.md
用法: venv/Scripts/python.exe scripts/bench_combination.py [--samples 2-1 ...]
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
OUT = ROOT / "docs" / "基准报告-物相组合-v1.md"

# 真值相名即内置库名 (与 bench_refinement_v21.CASES 同源)。
# 匹配规则: 先归一化精确相等, 再退化为包含匹配 (去空格/小写/去希腊前缀)。
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


def _match_names(candidates: list[str], truth: str) -> list[str]:
    return [c for c in candidates if _name_eq(c, truth)]


def run_case(sample: str) -> dict:
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import PhaseIdentifier, default_peak_list

    want, note = TRUTH[sample]
    data = DataLoader().load(DATA / f"{sample}.txt")
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    pi = PhaseIdentifier()

    t0 = time.perf_counter()
    gpl = default_peak_list(data)
    t_peaks = time.perf_counter() - t0

    t0 = time.perf_counter()
    matches = pi.identify_with_element_filter(
        data, peaks=gpl, element_filter=None, top_n=12, tolerance=0.2)
    t_ident = time.perf_counter() - t0

    cand_names = [m.phase.name or "" for m in matches]
    cand_norm = [_norm(c) for c in cand_names]

    # 真值相在检索结果里的排名 (1-based; 不在 top12 → MISS)
    ranks: dict[str, str] = {}
    for tw in want:
        rank = "MISS"
        for i, cn in enumerate(cand_norm):
            if _name_eq(cand_names[i], tw):
                rank = str(i + 1)
                break
        ranks[tw] = rank

    t0 = time.perf_counter()
    combo = pi.build_refinement_combination(
        matches, expected_count=len(want), min_coverage=0.3, peaks=gpl)
    t_combo = time.perf_counter() - t0
    combo_names = [p.name or "" for p in combo]

    hit = {tw: bool(_match_names(combo_names, tw)) for tw in want}
    # 多余相: 组合里匹配不到任何真值相的条目
    extra = [c for c in combo_names
             if not any(_name_eq(c, tw) for tw in want)]
    n_hit = sum(hit.values())
    return {
        "sample": sample, "note": note, "truth": want,
        "combo": combo_names, "hit": hit, "n_hit": n_hit,
        "complete": n_hit == len(want),
        "missing": [tw for tw in want if not hit[tw]],
        "extra": extra,
        "ranks": ranks,
        "t_peaks": t_peaks, "t_ident": t_ident, "t_combo": t_combo,
        "n_cand": len(matches),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="*", default=None)
    args = ap.parse_args()
    samples = args.samples or list(TRUTH)

    rows = []
    for s in samples:
        print(f"[{s}] running ...", flush=True)
        try:
            rows.append(run_case(s))
        except Exception as exc:  # noqa: BLE001
            rows.append({"sample": s, "error": repr(exc)})
            print(f"[{s}] ERROR: {exc!r}", flush=True)

    # ── 汇总 ────────────────────────────────────────────────
    valid = [r for r in rows if "error" not in r]
    n_truth = sum(len(r["truth"]) for r in valid)
    n_hit = sum(r["n_hit"] for r in valid)
    n_complete = sum(1 for r in valid if r["complete"])

    lines = [
        "# 基准报告 · 物相组合选择 v1（S01 标尺）",
        "",
        "> 生成脚本：`scripts/bench_combination.py`（只读基准，不改算法）",
        "> 口径：`default_peak_list` → `identify_with_element_filter(top_n=12, tolerance=0.2)`",
        "> → `build_refinement_combination(expected_count=真值相数, min_coverage=0.3, peaks=gpl)`",
        "> 注意：`default_peak_list` 无幅度下限（min_signal_abs=0 / min_prominence_frac=0），",
        "> 噪声峰会进入覆盖与特异性项 —— 本报告所有数字都在该口径下。",
        "",
        "## 一、总览",
        "",
        "| 试样 | 真值相数 | 组合命中 | 完全命中 | 缺失 | 多余 |",
        "|---|---|---|---|---|---|",
    ]
    for r in valid:
        lines.append(
            f"| {r['sample']} | {len(r['truth'])} | {r['n_hit']}/{len(r['truth'])} "
            f"| {'✅' if r['complete'] else '❌'} "
            f"| {', '.join(r['missing']) or '—'} "
            f"| {', '.join(r['extra']) or '—'} |")
    lines += [
        "",
        f"**相级命中**: {n_hit}/{n_truth}（{100.0 * n_hit / max(n_truth, 1):.1f}%）；"
        f"**试样级完全命中**: {n_complete}/{len(valid)}",
        "",
        "## 二、组合明细与真值排名",
        "",
    ]
    for r in valid:
        lines.append(f"### {r['sample']}（{r['note']}）")
        lines.append("")
        lines.append(f"- 组合 ({len(r['combo'])}): "
                     + "、".join(f"`{c}`" for c in r["combo"]))
        rank_items = [f"{tw} → 第 {rk} 名" if rk != "MISS" else f"{tw} → **MISS(>12)**"
                      for tw, rk in r["ranks"].items()]
        lines.append("- 真值检索排名: " + "；".join(rank_items))
        lines.append("")
    # 反例核对 (手册 §1.1)
    lines += [
        "## 三、手册 §1.1 反例核对",
        "",
    ]
    for s, expect_wrong in (("2-1", {"Zincite", "Calcite"}),
                            ("4-1", {"Zincite", "Corundum", "Fluorite", "Brucite"}),
                            ("5-1", {"α-Quartz", "Cristobalite", "Calcite",
                                     "Magnesite", "Dolomite"})):
        r = next((x for x in valid if x["sample"] == s), None)
        if r is None:
            lines.append(f"- {s}: 无结果")
            continue
        status = "已复现 ❌" if not r["complete"] else "未复现（组合已正确）"
        lines.append(f"- **{s}**: 完全命中={'是' if r['complete'] else '否'} → {status}；"
                     f"缺失={r['missing'] or '无'}；多余={r['extra'] or '无'}")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {OUT}")
    print(f"phase-level hit: {n_hit}/{n_truth}, sample-level complete: {n_complete}/{len(valid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
