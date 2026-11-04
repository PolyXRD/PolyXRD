# -*- coding: utf-8 -*-
"""系统性强度误差 A/B（v5.2 第二件）：表面粗糙度 SR + Brindley 微吸收 MA。

口径与基准报告 §二十 一致：refinement 引擎、``fast`` 档、``max_cycles=12``、
相表钉死（``bench_engines_v500.PHASE_TABLE``）。

用法::

    python scripts/bench_intensity_ab.py     # 约 1000 s（空载机）

结果落 ``.workbuddy/tmp/bench_intensity_ab.json``（gitignore）。

五条臂
------
* ``base``  ：全关（= v5.1 行为，用来验"默认零影响"）
* ``sr``    ：``roughness_model="sidey"`` + ``refine_roughness=True``
* ``ma10``  ：``microabsorption=True`` + 颗粒半径 10 µm（μ 由位点组成现算）
* ``ma25``  ：同上，半径 25 µm（放大到"确实粗"的量级，看方向对不对）
* ``both``  ：``sr`` + ``ma25``（真实样品两者同时存在）

判据（沿用"不为 Rwp 牺牲定量"的纪律）
------------------------------------
1. Rwp 只降不升 → SR 是否该默认开；
2. Σ|Δwt| 是否同时改善 → 若 Rwp 降但定量变差，说明 SR 在替结构误差背锅；
3. MA **不允许改 Rwp**（τ 会被标度吸收）—— 这一条是接线正确性的硬检查，
   逐试样必须逐位相同，不同就说明 τ 漏进了强度模型。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))
os.environ.setdefault("POLYXRD_CIF_CACHE_DIR",
                      str(_ROOT / ".workbuddy" / "tmp" / "cif_cache"))

import numpy as np  # noqa: E402

from bench_engines_v500 import DATA_DIR, PHASE_TABLE, build_phases  # noqa: E402
from polyxrd.services.data_loader import DataLoader  # noqa: E402
from polyxrd.services.phase_structure_resolver import (  # noqa: E402
    PhaseStructureResolver)
from polyxrd.services.polydb import PolyDatabase  # noqa: E402
from polyxrd.services.rietveld_refiner import RietveldRefiner  # noqa: E402

SAMPLES = ("2-1", "3-1", "4-1", "7-1")

#: 真值（矿物名 → wt%），来自 test_xrd/物相结果+wt%.txt
TRUTH_BY_NAME = {
    "2-1": {"Zincite": 50.0, "Calcite": 50.0},
    "3-1": {"Zincite": 93.59, "Corundum": 5.04, "Fluorite": 1.36},
    "4-1": {"Zincite": 19.94, "Corundum": 21.27, "Fluorite": 22.53,
            "Brucite": 36.26},
    "7-1": {"Quartz low": 5.16, "Boehmite": 14.93, "Anatase": 2.00,
            "Goethite": 9.98, "Kaolinite": 3.02, "Gibbsite": 54.90,
            "Hematite": 10.00},
}

ARMS = {
    "base": {},
    "sr": {"roughness_model": "sidey", "refine_roughness": True},
    "ma10": {"microabsorption": True, "grain_radius_um": 10.0},
    "ma25": {"microabsorption": True, "grain_radius_um": 25.0},
    "both": {"roughness_model": "sidey", "refine_roughness": True,
             "microabsorption": True, "grain_radius_um": 25.0},
}

#: 逐试样臂表：7-1 有 7 相、跑一轮要几分钟，只跑决定性的三臂
ARM_PLAN = {
    "2-1": tuple(ARMS),
    "3-1": tuple(ARMS),
    "4-1": tuple(ARMS),
    "7-1": ("base", "sr", "ma25"),
}

db = PolyDatabase()
loader = DataLoader()
resolver = PhaseStructureResolver()
refiner = RietveldRefiner()
OUT = _ROOT / ".workbuddy" / "tmp" / "bench_intensity_ab.json"


def run_one(key: str, arm: str) -> dict:
    data = loader.load(DATA_DIR / f"{key}.txt")
    lam = float(getattr(data, "wavelength", 1.54056) or 1.54056)
    phases, missing = build_phases(db, data, PHASE_TABLE[key])
    if not phases:
        return {"arm": arm, "error": "no phases", "missing": missing}
    phases = resolver.resolve(
        phases, wavelength=lam,
        two_theta_range=(float(np.min(data.two_theta)),
                         float(np.max(data.two_theta))))
    logs: list[str] = []
    t0 = time.time()
    try:
        res = refiner.refine(data, phases, engine="refinement",
                             perf_profile="fast", max_cycles=12,
                             log_cb=logs.append, **ARMS[arm])
    except Exception as e:  # noqa: BLE001 - 单臂失败不中断整表
        return {"arm": arm, "error": f"{type(e).__name__}: {e}",
                "seconds": time.time() - t0}
    fp = res.fit_params or {}
    return {
        "arm": arm,
        "Rwp": round(float(res.wR), 3),
        "GOF": round(float(res.GOF or 0.0), 3),
        "wt": [round(float(getattr(p, "weight_fraction", 0.0) or 0.0), 2)
               for p in res.phases],
        "names": [str(getattr(p, "name", "")).split(" - ")[0].strip()
                  for p in res.phases],
        "roughness_s": fp.get("roughness_s"),
        "mu_linear": fp.get("mu_linear"),
        "tau": fp.get("microabsorption_tau"),
        "mu_bar": fp.get("microabsorption_mu_bar"),
        "clamped": fp.get("microabsorption_clamped"),
        "seconds": round(time.time() - t0, 1),
        "ma_log": [m for m in logs if "microabsorption" in m],
    }


def sum_abs(key: str, names, wt) -> float | None:
    truth = TRUTH_BY_NAME.get(key)
    if not truth or not names:
        return None
    s = 0.0
    for n, w in zip(names, wt):
        if n in truth:
            s += abs(float(w) - float(truth[n]))
    return round(s, 2)


def main() -> None:
    out: dict = {}
    t_all = time.time()
    print(f"试样 {len(SAMPLES)}，总运行 "
          f"{sum(len(ARM_PLAN.get(k, ARMS)) for k in SAMPLES)} 次", flush=True)
    for key in SAMPLES:
        out[key] = {}
        for arm in ARM_PLAN.get(key, ARMS):
            row = run_one(key, arm)
            out[key][arm] = row
            OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            if "error" in row:
                print(f"[{key}/{arm}] FAIL {row['error'][:70]}", flush=True)
                continue
            sa = sum_abs(key, row["names"], row["wt"])
            print(f"[{key}/{arm}] Rwp={row['Rwp']:.2f} GOF={row['GOF']:.2f} "
                  f"Σ|Δ|={'%.2f' % sa if sa is not None else '-'} "
                  f"s={row['roughness_s']} tau="
                  f"{[round(t, 3) for t in (row['tau'] or [])]} "
                  f"({row['seconds']}s)", flush=True)
        # 每试样小结
        b = out[key].get("base") or {}
        for arm in ARMS:
            r = out[key].get(arm) or {}
            if "Rwp" in r and "Rwp" in b:
                sa_b = sum_abs(key, b.get("names"), b.get("wt"))
                sa_r = sum_abs(key, r.get("names"), r.get("wt"))
                print(f"    Δ{arm:5s} dRwp={r['Rwp'] - b['Rwp']:+.2f} "
                      f"dΣ|Δ|="
                      + (f"{sa_r - sa_b:+.2f}" if sa_b is not None
                         and sa_r is not None else "-"), flush=True)
    print(f"\n全部完成，总耗时 {time.time() - t_all:.1f}s -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
