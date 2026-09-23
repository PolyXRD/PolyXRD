"""W29 精修基准 (v2.0.0) —— 真值明确的样本
==========================================
用途: 在**真值已知**的试样上量化精修质量 (wR / 权重百分比偏差), 作为 2.0.0 的基准记录。

方法 (与 App 用户路径一致):
  1. 真值给相 (来自 `物相结果+wt%.txt`) → 从内置库按名取相;
  2. `PhaseStructureResolver` 从本地 COD 全库回填 CIF 结构 (App 主流程同款);
  3. `RietveldRefiner` builtin 引擎精修 (预算受限, 各试样之间可比)。

输出: docs/基准报告-精修-v2.0.0.md
用法: venv/Scripts/python.exe scripts/bench_refinement_w29.py
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
OUT = ROOT / "docs" / "基准报告-精修-v2.0.0.md"

BUDGET = dict(engine="builtin", max_cycles=10, n_starts=1,
              max_nfev_per_start=80, use_caglioti=True,
              wR_threshold=None, detect_ka2=False)

CASES: dict = {
    # 注意: 真值键必须用**库中相名** (真值文件写 LiFePO4, 库相名为 Lithium iron
    # phosphate —— 首版按真值写法取键, 导致单相被判成 0.00%, 是报告脚本的映射问题)
    "1-1": (["Lithium iron phosphate"],
            {"Lithium iron phosphate": 100.0}, "单相 (库名 Lithium iron phosphate)"),
    "1-2": (["NCM 811"], {"NCM 811": 100.0}, "单相"),
    "2-1": (["Zincite", "Calcite"], {"Zincite": 50.0, "Calcite": 50.0}, "双相 50/50"),
    "3-1": (["Zincite", "Corundum", "Fluorite"],
            {"Zincite": 93.59, "Corundum": 5.04, "Fluorite": 1.36},
            "三相, 含 1.4% 微量相"),
    "4-1": (["Zincite", "Corundum", "Fluorite", "Brucite"],
            {"Zincite": 19.94, "Corundum": 21.27, "Fluorite": 22.53,
             "Brucite": 36.26}, "四相"),
    "7-1": (["α-Quartz", "Boehmite", "Anatase", "Goethite", "Kaolinite",
             "Gibbsite", "Hematite"],
            {"α-Quartz": 5.16, "Boehmite": 14.93, "Anatase": 2.00,
             "Goethite": 9.98, "Kaolinite": 3.02, "Gibbsite": 54.90,
             "Hematite": 10.00}, "七相 (最复杂)"),
    "2-2": (["Anatase", "Rutile"], None, "双相同质多象 (真值无 wt%)"),
    "3-2": (["Zincite", "Corundum", "Fluorite"], None,
            "含 29.5% 非晶玻璃 -> 模型无法表示, 只记 wR"),
}


def _pick(pi, name: str):
    for p in pi._phase_database:
        if p.name == name:
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
        "t_resolve": t_resolve, "t_refine": t_ref,
        "got": got, "truth": truth, "dev": dev,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="*", default=None,
                    help="只跑指定试样; 默认排除 7-1")
    args = ap.parse_args()
    # 7-1 (七相) 在这个预算下 25 分钟仍未跑完 —— 瓶颈是"大峰表 × 抛光阶段的 675 次
    # 谱合成评估", 不是收敛问题。默认排除并在报告里如实记录 (见文末"未完成项")。
    names = args.samples or [k for k in CASES if k != "7-1"]
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
            print(f"   wR={r['wR']:.2f}%  结构 {r['n_struct']}/{r['n_phases']}  "
                  f"basis={r['basis']}  t={r['t_resolve'] + r['t_refine']:.0f}s",
                  flush=True)
        else:
            print(f"   ERROR: {r.get('error')}", flush=True)

    L = []
    L.append("# 精修基准报告 · PolyXRD v2.0.0（W29）")
    L.append("")
    L.append(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}　引擎：builtin")
    L.append("> 预算受限口径 `n_starts=1, max_nfev_per_start=80, use_caglioti=True, 无快检早退`：")
    L.append("> 各试样之间可比，但不是引擎的最好成绩（默认预算会更好但慢数倍）。")
    L.append("> 相来自真值 → PhaseStructureResolver 从本地 COD 回填结构 → 精修。")
    L.append("")
    L.append("## 一、总览")
    L.append("")
    L.append("| 试样 | 说明 | 相数(带结构) | wR % | Rexp % | GOF | 定量口径 | 耗时 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        if "wR" not in r:
            L.append(f"| {r['sample']} | {r.get('note','')} | — | — | — | — | — | 失败: {r.get('error')} |")
            continue
        L.append(
            f"| {r['sample']} | {r['note']} | {r['n_struct']}/{r['n_phases']} | "
            f"**{r['wR']:.2f}** | {r['Rexp']:.2f} | {r['GOF']:.2f} | {r['basis']} | "
            f"{r['t_resolve']:.1f}+{r['t_refine']:.1f} s |")
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
    L.append("- 5-1 / 5-2 / 5-3 / 7-2 的真值只给相名不给 wt% → 本表不含其定量对比。")
    L.append("- 3-2 含 29.47% 非晶玻璃：模型无法表示非晶相，其 wR 仅供参考、不参与定量。")
    L.append("- 微量相（如 3-1 的 CaF2 = 1.36%）受检出与权重限制，绝对偏差天然偏大。")
    L.append("- 结构可回填时 wt% 为**质量分数**（`W∝S·ZMV`），否则退回相对定量（表内已标口径）。")
    if "7-1" not in names:
        L.append("")
        L.append("## 四、未完成项（如实记录）")
        L.append("")
        L.append("- **7-1（七相，最复杂）本轮未跑完**：在 25 分钟时人工终止。"
                 "瓶颈是**大峰表 × 抛光阶段的 675 次谱合成评估**（非收敛问题）。"
                 "后续应给抛光阶段加「按峰数自适应」的评估预算，"
                 "或对超过阈值的峰表直接跳过抛光。")
    L.append("")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"[ok] 报告: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
