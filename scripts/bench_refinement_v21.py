"""v2.1 全量精修基准 (13 试样) —— 依赖 v2.1-A 自适应抛光预算
=============================================================
与 W29 (v2.0.0) 同口径的预算受限基准, 但:
  - 覆盖全部 13 试样 (含 5-1/5-2/5-2b/5-3/7-1/7-2);
  - 抛光预算已按峰数自适应 (v2.1-A) → 7-1 应能跑完;
  - 记录 v2.1 新指标: 真实 Bragg R (v2.1-D)、定量降级诊断 (v2.1-C)、
    结构回填成功率。

输出: docs/基准报告-精修-v2.1.0.md
用法: venv/Scripts/python.exe scripts/bench_refinement_v21.py [--samples 7-1 ...]
"""
from __future__ import annotations

import argparse
import copy
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA = Path(r"E:\TEMP\test_xrd\txt")
OUT = ROOT / "docs" / "基准报告-精修-v2.1.0.md"

BUDGET = dict(engine="builtin", max_cycles=10, n_starts=1,
              max_nfev_per_start=80, use_caglioti=True,
              wR_threshold=None, detect_ka2=False)

CASES: dict = {
    "1-1": (["Lithium iron phosphate"],
            {"Lithium iron phosphate": 100.0}, "单相 (库名 Lithium iron phosphate)"),
    "1-2": (["NCM 811"], {"NCM 811": 100.0}, "单相 (NCM 三元, 结构回填考验)"),
    "2-1": (["Zincite", "Calcite"], {"Zincite": 50.0, "Calcite": 50.0}, "双相 50/50"),
    "2-2": (["Anatase", "Rutile"], None, "双相同质多象 (真值无 wt%)"),
    "3-1": (["Zincite", "Corundum", "Fluorite"],
            {"Zincite": 93.59, "Corundum": 5.04, "Fluorite": 1.36},
            "三相, 含 1.4% 微量相"),
    "3-2": (["Zincite", "Corundum", "Fluorite"], None,
            "含 29.5% 非晶玻璃 -> 模型无法表示, 只记 wR"),
    "4-1": (["Zincite", "Corundum", "Fluorite", "Brucite"],
            {"Zincite": 19.94, "Corundum": 21.27, "Fluorite": 22.53,
             "Brucite": 36.26}, "四相"),
    "5-1": (["α-Quartz", "Cristobalite", "Calcite", "Magnesite", "Dolomite"],
            None, "五相碳酸盐-硅酸盐 (真值无 wt%)"),
    "5-2": (["α-Quartz", "Cristobalite", "Calcite", "Hematite", "Muscovite"],
            None, "五相 (真值无 wt%)"),
    "5-2b": (["α-Quartz", "Cristobalite", "Calcite", "Hematite", "Muscovite"],
             None, "5-2 的重复测试"),
    "5-3": (["α-Quartz", "Gehlenite", "Fluorapatite", "Goethite", "Kaolinite"],
            None, "五相 (真值无 wt%)"),
    "7-1": (["α-Quartz", "Boehmite", "Anatase", "Goethite", "Kaolinite",
             "Gibbsite", "Hematite"],
            {"α-Quartz": 5.16, "Boehmite": 14.93, "Anatase": 2.00,
             "Goethite": 9.98, "Kaolinite": 3.02, "Gibbsite": 54.90,
             "Hematite": 10.00}, "七相 (最复杂; 自适应抛光预算考核)"),
    "7-2": (["Quartz", "Albite", "Biotite", "Clinochlore", "Hornblende",
             "Zircon"],
            None, "天然矿物多相 (真值只给相名)"),
}


def _pick(pi, name: str):
    for p in pi._phase_database:
        if p.name == name:
            return copy.deepcopy(p)
    # 宽松回退: 去空格/大小写不敏感的包含匹配
    key = name.replace(" ", "").lower()
    for p in pi._phase_database:
        nm = (p.name or "").replace(" ", "").lower()
        if key and (key in nm or nm in key):
            return copy.deepcopy(p)
    return None


def run_case(name: str) -> dict:
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import PhaseIdentifier
    from polyxrd.services.phase_structure_resolver import PhaseStructureResolver
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    want, truth, note = CASES[name]
    data = DataLoader().load(DATA / f"{name}.txt")
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    pi = PhaseIdentifier()
    phases, missing = [], []
    for nm in want:
        ph = _pick(pi, nm)
        if ph is None:
            missing.append(nm)
        else:
            phases.append(ph)
    if missing:
        return {"sample": name, "note": note, "error": f"库中找不到相: {missing}"}

    rng = (float(min(data.two_theta)), float(max(data.two_theta)))
    t0 = time.perf_counter()
    resolved = PhaseStructureResolver().resolve(
        phases, wavelength=float(data.wavelength), two_theta_range=rng,
        log_cb=lambda m: None)
    n_struct = sum(1 for p in resolved if getattr(p, "atomic_sites", None))
    t_resolve = time.perf_counter() - t0

    t0 = time.perf_counter()
    res = RietveldRefiner().refine(data, resolved, **BUDGET)
    t_ref = time.perf_counter() - t0

    got = {p.name: float(getattr(p, "weight_fraction", 0.0) or 0.0)
           for p in res.phases}
    dev = None
    if truth:
        dev = {k: got.get(k, 0.0) - v for k, v in truth.items()}
    return {
        "sample": name, "note": note, "n_phases": len(resolved),
        "n_struct": n_struct, "wR": float(res.wR), "Rexp": float(res.Rexp),
        "GOF": float(res.GOF), "basis": res.fit_params.get("weight_basis"),
        "bragg_r": res.fit_params.get("bragg_r", 0.0),
        "diag_codes": [d.get("code") for d in (res.diagnostics or [])],
        "t_resolve": t_resolve, "t_refine": t_ref,
        "got": got, "truth": truth, "dev": dev,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="*", default=None,
                    help="只跑指定试样; 默认全量 13 试样")
    args = ap.parse_args()
    names = args.samples or list(CASES)
    rows = []
    for nm in names:
        print(f"[run] {nm} ...", flush=True)
        try:
            r = run_case(nm)
        except Exception as e:  # noqa: BLE001
            r = {"sample": nm, "note": CASES[nm][2],
                 "error": f"{type(e).__name__}: {e}"}
        rows.append(r)
        if "wR" in r:
            print(f"   wR={r['wR']:.2f}%  BraggR={r['bragg_r']:.2f}  "
                  f"结构 {r['n_struct']}/{r['n_phases']}  basis={r['basis']}  "
                  f"t={r['t_resolve'] + r['t_refine']:.0f}s", flush=True)
        else:
            print(f"   ERROR: {r.get('error')}", flush=True)

    ok = [r for r in rows if "wR" in r]
    n_backfill = sum(r["n_struct"] for r in ok)
    n_total = sum(r["n_phases"] for r in ok)
    full = [r for r in ok if r["n_struct"] == r["n_phases"]]

    L = []
    L.append("# 精修基准报告 · PolyXRD v2.1.0（全量 13 试样）")
    L.append("")
    L.append(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}　引擎：builtin")
    L.append("> 预算受限口径 `n_starts=1, max_nfev_per_start=80, use_caglioti=True, 无快检早退`：")
    L.append("> 各试样之间可比，但不是引擎的最好成绩（默认预算会更好但慢数倍）。")
    L.append("> 相来自真值 → PhaseStructureResolver 从本地 COD 回填结构 → 精修。")
    L.append("> 相对 v2.0.0 (W29) 的新增记录: **真实 Bragg R**（v2.1-D）、"
             "**抛光预算自适应**（v2.1-A，7-1 应能跑完）、**定量降级诊断**（v2.1-C）。")
    L.append("")
    L.append("## 一、总览")
    L.append("")
    L.append("| 试样 | 说明 | 相数(带结构) | wR % | Bragg R % | Rexp % | GOF | 定量口径 | 耗时 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if "wR" not in r:
            L.append(f"| {r['sample']} | {r.get('note','')} | — | — | — | — | — | — | 失败: {r.get('error')} |")
            continue
        L.append(
            f"| {r['sample']} | {r['note']} | {r['n_struct']}/{r['n_phases']} | "
            f"**{r['wR']:.2f}** | {r['bragg_r']:.2f} | {r['Rexp']:.2f} | {r['GOF']:.2f} | "
            f"{r['basis']} | {r['t_resolve']:.1f}+{r['t_refine']:.1f} s |")
    L.append("")
    L.append(f"**结构回填**: {n_backfill}/{n_total} 相带结构; "
             f"**全相回填试样**: {len(full)}/{len(ok)}（验收口径 ≥ 7/8 已知真值试样）")
    L.append("")
    L.append("## 二、定量对比（仅真值给出 wt% 的试样）")
    L.append("")
    for r in rows:
        if not r.get("truth"):
            continue
        L.append(f"### {r['sample']}（{r['note']}）")
        L.append("")
        L.append("| 相 | 真值 wt% | 测得 wt% | 偏差 |")
        L.append("|---|---|---|---|")
        tot = 0.0
        for k, v in r["truth"].items():
            g = r["got"].get(k, 0.0)
            d = g - v
            tot += abs(d)
            L.append(f"| {k} | {v:.2f} | {g:.2f} | **{d:+.2f}** |")
        L.append(f"| **合计绝对偏差** | | | **{tot:.2f} pp** |")
        L.append("")
    L.append("## 三、口径与限制（如实说明）")
    L.append("")
    L.append("- wR 为**加权**口径（`stat_weights=poisson`）；单位权下 Rexp/GOF 不可解读。")
    L.append("- Bragg R 为 v2.1-D 新指标（按反射积分强度对账）；0 = 未取得（旧结果/提取失败）。")
    L.append("- 定量口径 relative = 部分相未匹配到结构（降级原因见诊断 `diag.weight_basis_relative`）。")
    L.append("- 3-2 含 29.47% 非晶玻璃：模型无法表示非晶相，其 wR 仅供参考、不参与定量。")
    L.append("- 微量相（如 3-1 的 CaF2 = 1.36%）受检出与权重限制，绝对偏差天然偏大。")
    L.append("- 5-x / 7-2 的真值只给相名不给 wt% → 不含定量对比。")
    L.append("")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"[ok] 报告: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
