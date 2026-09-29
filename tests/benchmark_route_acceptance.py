"""A/B 路线验收基准 (任务 #59/#60/#61 收口取证)
================================================
对 D:/Project/XRD/test_xrd 的 13 个真实试样:
  1. 识别物相 (元素过滤按 物相结果.txt 真值) → B&B 组合
  2. PhaseStructureResolver 从 COD 库回填 CIF 结构 (B 路线链路)
  3. builtin 精修 (v0.15.1 CIF |F|² 参考峰, use_cif_peaks=True)
2-1 / 4-1 额外跑一组"无结构基线"对照 (A 路线验收样本)。

结果逐行追加写 `_route_benchmark_result.txt`, 中断后重跑不丢已完成样本。
用法: venv/Scripts/python.exe tests/benchmark_route_acceptance.py [样本名 ...]
"""
from __future__ import annotations

import copy
import io
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA = Path(r"D:/Project/XRD/test_xrd\txt")
OUT = ROOT / os.environ.get("BENCH_OUT", "_route_benchmark_result.txt")

MAYBE = ["H", "Li", "Be", "B", "C", "N", "O", "F", "Na", "Mg",
         "Al", "Si", "K", "Ca", "Ti", "Fe", "P"]

SAMPLES: dict[str, dict] = {
    "1-1":  {"must": ["Li", "Fe", "P"], "n": 1},
    "1-2":  {"must": ["Li", "Ni", "Mn", "Co"], "n": 1},
    "2-1":  {"must": ["Zn", "Ca"], "maybe": ["H", "C", "O", "F", "Na", "Mg"], "n": 2},
    "2-2":  {"must": ["Ti"], "n": 2},
    "3-1":  {"must": ["Zn", "Al", "Ca"], "n": 3},
    "3-2":  {"must": ["Zn", "Al", "Ca"], "n": 3},
    "4-1":  {"must": ["Zn", "Al", "Ca", "Mg"],
             "maybe": ["H", "C", "O", "F", "Na"], "n": 4},
    "5-1":  {"must": ["Si", "Ca", "Mg"], "n": 5},
    "5-2":  {"must": ["Si", "Ca", "Fe", "K", "Al"], "n": 5},
    "5-2b": {"must": ["Si", "Ca", "Fe", "K", "Al"], "n": 5},
    "5-3":  {"must": ["Si", "Ca", "Al", "Fe", "P"], "n": 5},
    "7-1":  {"must": ["Si", "Al", "Ti", "Fe"], "n": 7},
    "7-2":  {"must": ["Si", "Al", "Na", "K", "Fe", "Mg", "Ca", "Zr"], "n": 6},
}
BASELINE_ONLY = {"2-1", "4-1"}  # 这两个加跑无结构基线


def _out(line: str) -> None:
    print(line, flush=True)
    with io.open(OUT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_sample(name: str) -> None:
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import PhaseIdentifier, default_peak_list
    from polyxrd.services.phase_structure_resolver import PhaseStructureResolver
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    cfg = SAMPLES[name]
    t0 = time.time()
    data = DataLoader().load(DATA / f"{name}.txt")
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    tth = list(data.two_theta)
    rng = (float(min(tth)), float(max(tth)))

    # 与 App 实际路径一致: 默认走高精度寻峰 (peak_detection)。
    # 旧的低灵敏度 PeakFinder 在 3-1 这类"一条超强线 + 多条弱线"的谱上只检出
    # 12/66 个峰, 识别必然失手 —— 那是寻峰口径问题, 不是参考库/精修的问题。
    peaks = default_peak_list(data)
    # BENCH_FAST=1 → 关掉 Caglioti 精细模式 (只跑快检), 用于"13 样全跑通"的耗时控制
    fast = os.environ.get("BENCH_FAST") == "1"
    refine_kw = {"wR_threshold": None, "use_caglioti": False} if fast else {}
    # BENCH_NFEV=60 → 压低单起点 nfev 上限。7-1/7-2 这类含 15R SiC (192 位点)
    # 等大结构的组合, 每次谱合成要求数万峰×7251 点, 400 上限会跑数小时;
    # "全跑通"口径只验证链路无错无挂, 不是精度记录。
    nfev = os.environ.get("BENCH_NFEV")
    if nfev:
        refine_kw["max_nfev_per_start"] = int(nfev)
    starts = os.environ.get("BENCH_STARTS")
    if starts:
        refine_kw["n_starts"] = int(starts)

    pi = PhaseIdentifier()
    matches = pi.identify_with_element_filter(
        data, peaks=peaks,
        element_filter={"must": cfg["must"],
                        "maybe": cfg.get("maybe", MAYBE),
                        "exclude": []},
        top_n=12, tolerance=0.2,
    )
    combo = pi.build_refinement_combination(
        matches, expected_count=cfg["n"], min_coverage=0.3, peaks=peaks
    )
    _out(f"### {name}  组合({len(combo)}): {[p.name for p in combo]}  "
         f"实测峰 {len(peaks.peaks)}  识别+组合 {time.time()-t0:.1f}s")

    refiner = RietveldRefiner()

    # ── 基线 (无结构, 仅 2-1/4-1) ──
    if name in BASELINE_ONLY:
        r0 = refiner.refine(data, copy.deepcopy(combo),
                            engine="builtin", max_cycles=30, **refine_kw)
        _out(f"  [{name}] 基线(无CIF)   wR={r0.wR:6.2f}%  GOF={r0.GOF:5.2f}  "
             f"t={r0.time_seconds:6.1f}s")

    # ── B 路线: 回填 CIF 结构 ──
    resolver = PhaseStructureResolver()
    resolved = resolver.resolve(
        copy.deepcopy(combo), wavelength=float(data.wavelength),
        two_theta_range=rng,
        log_cb=lambda m: _out(f"    {m}"),
    )
    n_struct = sum(1 for p in resolved if getattr(p, "atomic_sites", None))
    _out(f"  [{name}] 结构回填: {n_struct}/{len(resolved)} 相带 atomic_sites")

    r1 = refiner.refine(data, resolved, engine="builtin", max_cycles=30, **refine_kw)
    wts = ", ".join(
        f"{p.name}={getattr(p, 'weight_fraction', 0.0) or 0.0:.1f}%"
        for p in r1.phases)
    _out(f"  [{name}] CIF|F|²精修  wR={r1.wR:6.2f}%  GOF={r1.GOF:5.2f}  "
         f"t={r1.time_seconds:6.1f}s  [{wts}]")


def main() -> int:
    names = sys.argv[1:] or list(SAMPLES)
    _out(f"\n===== benchmark start {time.strftime('%F %T')}  samples={names}")
    failed = []
    for nm in names:
        try:
            run_sample(nm)
        except Exception:
            failed.append(nm)
            _out(f"  [{nm}] FAILED:\n" + traceback.format_exc(limit=4))
    _out(f"===== benchmark done  failed={failed or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
