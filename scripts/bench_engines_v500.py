"""三引擎对拍基准（v5.0.0 / step ②）：builtin · refinement · gsas2。

用法::

    venv/Scripts/python.exe scripts/bench_engines_v500.py           # 全部 13 试样
    venv/Scripts/python.exe scripts/bench_engines_v500.py 2-1 4-1   # 指定试样
    venv/Scripts/python.exe scripts/bench_engines_v500.py --json out.json

**目的**：给 ``auto`` 要不要纳入新引擎（``refinement``）提供依据。判据不是单看
Rwp —— 三个引擎喂的是**同一个相列表、同一份数据**，差异只能来自引擎本身。

相从哪来（关键，别省）
----------------------
真值相表（``TRUTH``）给的是化学式 + 矿物名；同一化学式往往有十几个多形体
（α/β-石英、三方超胞方镁石、高温方石英…）。用"库内峰数最多"这类启发式挑
会挑到高温相 —— 实测挑出 β-石英（a=4.998）和 3× 超胞 Brucite（15 位点）。
所以变体一律**用图谱本身定**：把该化学式的全部库条目按"最强若干条 d 线与
实测峰的重合度"打分取最优（:func:`_rank_variants`），再用
``PhaseIdentifier._make_polydb_phase`` 落成带全胞位点的 Phase。

builtin 引擎吃的是参考峰（``reference_peaks``）。为了让三引擎输入等价，参考峰
**由该相自己的结构算**（``build_reflections`` → 相对强度归一到 100），不另找库。

输出：markdown 表（stdout）+ 可选 JSON；每完成一个试样就写一次 JSON（长跑不怕中断）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# CIF 缓存指到工作区（沙箱/只读用户目录下默认位置写不进去 → GSAS-II 拿不到结构）
os.environ.setdefault(
    "POLYXRD_CIF_CACHE_DIR",
    str(_ROOT / ".workbuddy" / "tmp" / "cif_cache"))

import numpy as np  # noqa: E402

from polyxrd.refinement import StructureModel, build_reflections  # noqa: E402
from polyxrd.services.data_loader import DataLoader  # noqa: E402
from polyxrd.services.phase_identifier import PhaseIdentifier  # noqa: E402
from polyxrd.services.polydb import PolyDatabase  # noqa: E402
from polyxrd.services.rietveld_refiner import RietveldRefiner  # noqa: E402

DATA_DIR = Path(r"D:\Project\XRD\test_xrd\txt")
ENGINES = ("builtin", "refinement", "gsas2")

#: **钉死的相表**：(COD 编号, 说明)。为什么钉死而不是"按真值化学式自动选"——
#: 同一化学式在库里常有十几个多形体（α/β-石英、方解石 vs 单斜高压相、3× 超胞
#: Brucite），靠"强线重合数"或 Hanawalt 打分自动选，实测会在混合相样品上选错
#: （锐钛矿/金红石判成同一变体、方解石判成 3 位点高压相）。引擎对拍要求三引擎
#: 输入**完全一致且可信**，所以变体选择是基准的前置条件、必须可审计 —— 全部编号
#: 在此列出，改一行就是换一个起始结构。
PHASE_TABLE: Dict[str, List[Tuple[int, str]]] = {
    "1-1": [(1529151, "LiFePO4 Pnma")],
    # NCM811 库内无同式条目 → 用 LiNiO2（R-3m, a=2.875 c=14.18）作起始结构，
    # 单相定量恒为 100%，组成差异不影响"引擎能不能拟下来"这个判据。
    "1-2": [(1533770, "LiNiO2 代理 NCM811")],
    "2-1": [(9004180, "Zincite"), (9009668, "Calcite")],
    "2-2": [(7206075, "Anatase"), (9001681, "Rutile")],
    "3-1": [(9004180, "Zincite"), (2101056, "Corundum"), (1000043, "Fluorite")],
    "3-2": [(9004180, "Zincite"), (2101056, "Corundum"), (1000043, "Fluorite")],
    "4-1": [(9004180, "Zincite"), (2101056, "Corundum"), (1000043, "Fluorite"),
            (1000054, "Brucite")],
    "5-1": [(1011172, "Quartz low"), (9008225, "Cristobalite"),
            (9009668, "Calcite"), (9000380, "Magnesite"), (9001007, "Dolomite")],
    "5-2": [(1011172, "Quartz low"), (9008225, "Cristobalite"),
            (9009668, "Calcite"), (9015065, "Hematite"), (1011049, "Muscovite")],
    "5-2b": [(1011172, "Quartz low"), (9008225, "Cristobalite"),
             (9009668, "Calcite"), (9015065, "Hematite"), (1011049, "Muscovite")],
    "5-3": [(1011172, "Quartz low"), (1000048, "Gehlenite"),
            (1010996, "Fluorapatite"), (9003076, "Goethite"),
            (1011045, "Kaolinite")],
    "7-1": [(1011172, "Quartz low"), (9012253, "Boehmite"), (7206075, "Anatase"),
            (9003076, "Goethite"), (1011045, "Kaolinite"),
            (1011081, "Gibbsite"), (9015065, "Hematite")],
    "7-2": [(1011172, "Quartz low"), (1011205, "Orthoclase"),
            (9000525, "Albite"), (9000842, "Biotite"), (5000119, "Zircon")],
}

#: 参考 wt%（`test_xrd/物相结果+wt%.txt`；没有数字的试样不参与定量偏差统计）
TRUTH_WT: Dict[str, Dict[str, float]] = {
    "2-1": {"ZnO": 50.0, "CaCO3": 50.0},
    "3-1": {"ZnO": 93.59, "Al2O3": 5.04, "CaF2": 1.36},
    "4-1": {"ZnO": 19.94, "Al2O3": 21.27, "CaF2": 22.53, "Mg(OH)2": 36.26},
}

REF_TOP = 60         # 参考峰表最多保留多少条（喂 builtin）


# ── 相表 → Phase ──────────────────────────────────────────────

def _reference_peaks(phase, two_theta_range, wavelength) -> list:
    """用该相自己的结构算参考峰（喂 builtin 引擎）。"""
    st = StructureModel.from_phase(phase)
    if st is None:
        return []
    table = build_reflections(st, two_theta_range=two_theta_range,
                              wavelengths=(wavelength,))
    tt = np.asarray(table.two_theta, dtype=float)
    it = np.asarray(table.intensity, dtype=float)
    hkl = np.asarray(table.hkl)
    if tt.size == 0:
        return []
    keep = np.argsort(-it)[:REF_TOP]
    keep = keep[np.argsort(tt[keep])]
    imax = float(np.max(it[keep])) or 1.0
    return [(tuple(int(v) for v in hkl[j]), float(tt[j]), 100.0 * float(it[j]) / imax)
            for j in keep]


def build_phases(db: PolyDatabase, data, table: Sequence[Tuple[int, str]]
                 ) -> Tuple[list, list]:
    """相表（COD 编号 + 说明）→ 带全胞位点与参考峰的 Phase 列表。

    参考峰由该相**自己的结构**算（``build_reflections`` → 相对强度归一到 100），
    而不是另找库里的参考峰表 —— 三引擎吃同一份结构，输入才等价。
    """
    pi = PhaseIdentifier()
    lam = float(getattr(data, "wavelength", 1.54056) or 1.54056)
    tmin = float(np.min(data.two_theta))
    tmax = float(np.max(data.two_theta))
    phases, missing = [], []
    for eid, label in table:
        detail = db.get_phase(int(eid))
        if not detail:
            missing.append(f"COD {eid} ({label}) 库内无此条目")
            continue
        ph = pi._make_polydb_phase(detail, {"cod_id": int(eid)}, [], db=db)
        if not ph.atomic_sites:
            missing.append(f"COD {eid} ({label}) 无位点")
            continue
        ph.reference_peaks = _reference_peaks(ph, (tmin, tmax), lam)
        if not ph.reference_peaks:
            missing.append(f"COD {eid} ({label}) 参考峰为空")
            continue
        phases.append(ph)
    return phases, missing


# ── 单引擎运行 ────────────────────────────────────────────────

def run_engine(engine: str, data, phases, refiner: RietveldRefiner) -> dict:
    t0 = time.time()
    try:
        res = refiner.refine(data, phases, engine=engine,
                             perf_profile="fast", max_cycles=12)
    except Exception as e:  # noqa: BLE001 - 单引擎失败不该中断整表
        return {"engine": engine, "error": f"{type(e).__name__}: {e}",
                "seconds": time.time() - t0}
    fp = res.fit_params or {}
    # gsas2 的 res.wR 是 Le Bail 阶段的 wR (桥在切 Rietveld 之前捕获的),
    # 与 builtin/refinement 的"最终 Rietveld wR"不同口径。这里优先用
    # wR_rietveld, 保证三列可比; 缺失时才退回 res.wR。
    rwp = float(res.wR)
    if engine == "gsas2" and fp.get("wR_rietveld"):
        rwp = float(fp["wR_rietveld"])
    return {
        "engine": engine,
        "engine_used": fp.get("engine", ""),
        "fallback": fp.get("engine_fallback_reason") or "",
        "Rwp": rwp,
        "GOF": float(res.GOF or 0.0),
        "wt": [round(float(getattr(p, "weight_fraction", 0.0) or 0.0), 2)
               for p in res.phases],
        "names": [getattr(p, "name", "") for p in res.phases],
        "weight_basis": fp.get("weight_basis", ""),
        "seconds": time.time() - t0,
    }


def run_sample(key: str, db: PolyDatabase) -> dict:
    data = DataLoader().load(DATA_DIR / f"{key}.txt")
    phases, missing = build_phases(db, data, PHASE_TABLE[key])
    # GUI 精修前会跑一遍结构补齐（位点 → CIF 落盘）。GSAS-II 要求**真实 CIF 文件**
    # 才肯进 Rietveld 定量阶段，不跑这一步它只做 Le Bail（实测 quantified=False、
    # 无 wt%、无 GOF）。三个引擎必须吃同一份输入，所以这里统一先补。
    from polyxrd.services.phase_structure_resolver import PhaseStructureResolver

    phases = PhaseStructureResolver().resolve(
        phases, wavelength=float(getattr(data, "wavelength", 1.54056) or 1.54056),
        two_theta_range=(float(np.min(data.two_theta)), float(np.max(data.two_theta))))
    print(f"=== {key}  相 {len(phases)}/{len(PHASE_TABLE[key])}"
          + (f"  缺: {missing}" if missing else ""), flush=True)
    for p in phases:
        lat = p.lattice
        print(f"    {p.name[:40]:40s} sites={len(p.atomic_sites):3d} "
              f"a={lat.a:.4f} c={lat.c:.4f} ref={len(p.reference_peaks)}", flush=True)

    refiner = RietveldRefiner()
    rows = []
    for engine in ENGINES:
        if not phases:
            break
        row = run_engine(engine, data, phases, refiner)
        rows.append(row)
        if "error" in row:
            print(f"    [FAIL] {engine:11s} {row['error'][:70]}", flush=True)
        else:
            print(f"    {engine:11s} Rwp={row['Rwp']:6.2f}% GOF={row['GOF']:5.2f} "
                  f"wt={row['wt']} {row['seconds']:6.1f}s"
                  + (f"  [fallback: {row['fallback'][:40]}]" if row["fallback"] else ""),
                  flush=True)
    return {"key": key, "missing": missing,
            "phases": [p.name for p in phases], "runs": rows,
            "truth_wt": TRUTH_WT.get(key, {})}


def markdown(results: Sequence[dict]) -> str:
    lines = ["| 试样 | 相数 | 引擎 | Rwp% | GOF | 耗时 s | wt% | 备注 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        for run in r["runs"]:
            if "error" in run:
                lines.append(f"| {r['key']} | {len(r['phases'])} | {run['engine']} "
                             f"| — | — | {run['seconds']:.1f} | — | 失败: "
                             f"{run['error'][:40]} |")
                continue
            note = run["fallback"][:40] if run["fallback"] else ""
            wt = "/".join(f"{v:.1f}" for v in run["wt"])
            lines.append(
                f"| {r['key']} | {len(r['phases'])} | {run['engine']} "
                f"| {run['Rwp']:.2f} | {run['GOF']:.2f} | {run['seconds']:.1f} "
                f"| {wt} | {note} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", nargs="*", default=None)
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    keys = args.samples or list(PHASE_TABLE)

    db = PolyDatabase()
    if not db.is_ready():
        print("polyDB 不可用，无法定位真值相结构", file=sys.stderr)
        return 2

    results: list[dict] = []
    for key in keys:
        try:
            results.append(run_sample(key, db))
        except Exception as e:  # noqa: BLE001 - 单试样失败继续
            print(f"=== {key}  异常: {type(e).__name__}: {e}", flush=True)
            results.append({"key": key, "missing": [], "phases": [], "runs": [],
                            "error": f"{type(e).__name__}: {e}"})
        if args.json:
            Path(args.json).write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + markdown(results))
    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
