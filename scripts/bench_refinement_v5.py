"""v5.0.0 阶段 E1：真实试样精修基准（脚本主体）。

用法::

    python scripts/bench_refinement_v5.py            # 全部试样
    python scripts/bench_refinement_v5.py 3-1 4-1    # 指定试样
    python scripts/bench_refinement_v5.py --json out.json

产物：stdout 的 markdown 表格 + 可选的 JSON 明细。报告正文
（``docs/基准报告-精修-v5.0.0.md``）由这些数字手工整理，不做自动截断。

设计约定
--------
* **结构不来自内置矿物库**。``cif_minerals`` 的 R-3c 条目（Corundum / Calcite）
  的 O 少了 ``z=1/4``，按空间群展开会得到 48 个位点（应为 30）—— 在修好之前
  基准不依赖它。本文件内的坐标是文献值，脚本自己校验位点数。
* **峰形 / 生物**：先用 ``seed_problem`` 给峰宽曲线与零位起点，再跑 default
  协议（峰位 → 峰形 → 择优 → 样品展宽）。
* **择优取向默认不开**：没给惯习面时 March–Dollase 权重恒 1，放开只会多一条
  零列。只有试样明确是片状（4-1 的 Brucite）才给 ``po_hkl``。
* **重量分数口径**：Hill–Howard 只算晶相、自动归一到 100%。试样含非晶时
  （3-2 的玻璃 29.5%）基准同时报「相对晶相」一列，避免把非晶算成误差。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from polyxrd.refinement import (  # noqa: E402
    BackgroundParams,
    Cell,
    Kalpha2,
    PatternProblem,
    PhaseBlock,
    ProfileParams,
    StructureModel,
    StageSpec,
    build_report,
    evaluate_goals,
    run_protocol,
    seed_problem,
    site_from_dict,
)

DATA_DIR = Path(r"D:\Project\XRD\test_xrd\xy")
CUT = 25.0
KALPHA2 = Kalpha2(wavelength=1.54056, ratio=0.497, separation=True)


# ══════════════════════════════════════════════════════════════════
# 结构表（文献坐标，非对称单元；脚本会断言展开后的位点数）
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Mineral:
    name: str
    formula: str
    space_group: str
    cell: Tuple[float, float, float, float, float, float]
    sites: Tuple[Tuple[str, str, float, float, float], ...]   # (label, element, x, y, z)
    n_full: int                                                # 全胞位点数（校验用）


MINERALS: Dict[str, Mineral] = {
    "ZnO": Mineral(
        "Zincite", "ZnO", "P6_3mc", (3.2498, 3.2498, 5.2066, 90.0, 90.0, 120.0),
        (("Zn1", "Zn", 1 / 3, 2 / 3, 0.0),
         ("O1", "O", 1 / 3, 2 / 3, 0.3819)), 4),
    "CaCO3": Mineral(
        "Calcite", "CaCO3", "R-3c", (4.9890, 4.9890, 17.0680, 90.0, 90.0, 120.0),
        # CO₃²⁻ 是**平面**基团：C 与 O 必须同层（z=1/4），Ca 在 z=0。
        # 写成 Ca(0,0,1/4)+C(0,0,0) 会把 O 挪到钙层里 —— 峰位不变（d 值由
        # 晶胞定），但 012 的相对强度会从 ~18% 飙到 86%，多相定量全错。
        (("Ca1", "Ca", 0.0, 0.0, 0.0),
         ("C1", "C", 0.0, 0.0, 0.25),
         ("O1", "O", 0.2578, 0.0, 0.25)), 30),
    "TiO2_anatase": Mineral(
        "Anatase", "TiO2", "I4_1/amd", (3.7852, 3.7852, 9.5139, 90.0, 90.0, 90.0),
        (("Ti1", "Ti", 0.0, 0.0, 0.0),
         ("O1", "O", 0.0, 0.0, 0.2081)), 12),
    "TiO2_rutile": Mineral(
        "Rutile", "TiO2", "P4_2/mnm", (4.5937, 4.5937, 2.9587, 90.0, 90.0, 90.0),
        (("Ti1", "Ti", 0.0, 0.0, 0.0),
         ("O1", "O", 0.3053, 0.3053, 0.0)), 6),
    "Al2O3": Mineral(
        "Corundum", "Al2O3", "R-3c", (4.7589, 4.7589, 12.9915, 90.0, 90.0, 120.0),
        (("Al1", "Al", 0.0, 0.0, 0.35216),
         ("O1", "O", 0.30624, 0.0, 0.25)), 30),
    "CaF2": Mineral(
        "Fluorite", "CaF2", "Fm-3m", (5.4626, 5.4626, 5.4626, 90.0, 90.0, 90.0),
        (("Ca1", "Ca", 0.0, 0.0, 0.0),
         ("F1", "F", 0.25, 0.25, 0.25)), 12),
    "Mg(OH)2": Mineral(
        "Brucite", "Mg(OH)2", "P-3m1", (3.1420, 3.1420, 4.7660, 90.0, 90.0, 120.0),
        (("Mg1", "Mg", 0.0, 0.0, 0.0),
         ("O1", "O", 1 / 3, 2 / 3, 0.2213),
         ("H1", "H", 1 / 3, 2 / 3, 0.4080)), 5),
    "SiO2_quartz": Mineral(
        "α-Quartz", "SiO2", "P3_121", (4.9134, 4.9134, 5.4052, 90.0, 90.0, 120.0),
        (("Si1", "Si", 0.4697, 0.0, 1 / 3),
         ("O1", "O", 0.4135, 0.2669, 0.1191)), 9),
}


def build_structure(key: str) -> StructureModel:
    """非对称单元 → 按空间群展开成全胞 ``StructureModel``（位点数自校验）。"""
    from polyxrd.services.phase_cif import expand_sites_by_symmetry

    m = MINERALS[key]
    raw = [{"label": lab, "element": el, "x": x, "y": y, "z": z,
            "occupancy": 1.0, "b_iso": 0.5}
           for lab, el, x, y, z in m.sites]
    expanded = expand_sites_by_symmetry(raw, m.space_group)
    if not expanded:
        raise RuntimeError(f"{key}: 空间群 {m.space_group} 展开失败")
    if len(expanded) != m.n_full:
        raise RuntimeError(
            f"{key}: 展开得 {len(expanded)} 个位点，期望 {m.n_full} —— "
            f"坐标与 {m.space_group} 不自洽（大概率漏了 1/4 类的特殊位置）")
    return StructureModel(
        sites=tuple(site_from_dict(s) for s in expanded),
        cell=Cell(*m.cell), space_group=m.space_group,
        name=m.name, formula=m.formula,
    )


# ══════════════════════════════════════════════════════════════════
# 试样配置（真值见 test_xrd/xy/物相结果+wt%.txt）
# ══════════════════════════════════════════════════════════════════

@dataclass
class SampleSpec:
    name: str
    phases: Tuple[str, ...]
    truth: Dict[str, float] = field(default_factory=dict)     # 质量分数 %
    po: Dict[str, Tuple[float, float, float]] = field(default_factory=dict)
    note: str = ""
    amorphous: float = 0.0                                     # 非晶质量分数 %


SPECS: Dict[str, SampleSpec] = {
    "2-1": SampleSpec("2-1", ("ZnO", "CaCO3"),
                      {"ZnO": 50.0, "CaCO3": 50.0},
                      note="两相 50/50 标样"),
    "2-2": SampleSpec("2-2", ("TiO2_anatase", "TiO2_rutile"),
                      note="锐钛矿 + 金红石（真值未给 wt%）"),
    "3-1": SampleSpec("3-1", ("ZnO", "Al2O3", "CaF2"),
                      {"ZnO": 93.59, "Al2O3": 5.04, "CaF2": 1.36},
                      note="ZnO 主相 + 两个弱相"),
    "3-2": SampleSpec("3-2", ("ZnO", "Al2O3", "CaF2"),
                      {"ZnO": 19.68, "Al2O3": 30.79, "CaF2": 20.06},
                      note="三相 + 非晶玻璃", amorphous=29.47),
    "4-1": SampleSpec("4-1", ("ZnO", "Al2O3", "CaF2", "Mg(OH)2"),
                      {"ZnO": 19.94, "Al2O3": 21.27, "CaF2": 22.53,
                       "Mg(OH)2": 36.26},
                      po={"Mg(OH)2": (0.0, 0.0, 1.0)},
                      note="四相；Brucite 片状 → 开 (001) 择优"),
    "5-2": SampleSpec("5-2", ("SiO2_quartz",),
                      note="只精修石英主相（真值含 5 相，多相拆分不在 E1 范围）"),
}


# ══════════════════════════════════════════════════════════════════
# 单试样流程
# ══════════════════════════════════════════════════════════════════

def load_xy(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(path)
    if data.ndim != 2 or data.shape[1] < 2:
        raise RuntimeError(f"{path.name}: 期望两列数据，得到 {data.shape}")
    return data[:, 0].astype(float), data[:, 1].astype(float)


def make_problem(spec: SampleSpec) -> PatternProblem:
    tt, y = load_xy(DATA_DIR / f"{spec.name}.xy")
    phases = [
        PhaseBlock(label=MINERALS[k].name, structure=build_structure(k),
                   index=i, po_hkl=spec.po.get(k))
        for i, k in enumerate(spec.phases)
    ]
    n_bg = max(8, int(round((tt[-1] - tt[0]) / 8.0)))
    return PatternProblem(
        tt, y, phases,
        profile=ProfileParams(w=0.02, x=0.01, y=0.0),
        bg=BackgroundParams("tent", n_bg),
        wavelength=KALPHA2.wavelength, kalph2=KALPHA2,
        weights=1.0 / np.maximum(y, 1.0), cutoff_fwhm=CUT,
    )


def run_sample(spec: SampleSpec, *, max_iter: Optional[int] = None) -> dict:
    t0 = time.perf_counter()
    prob = make_problem(spec)
    rwp0 = prob.metrics()["Rwp"]
    seeds = seed_problem(prob, apply=True)
    # 严格两段式：没有惯习面就不排 stage 4（那一阶段零自由参数，只会耗 patience）
    protocol = [StageSpec(2, 150), StageSpec(3, 120)]
    if spec.po:
        protocol.append(StageSpec(4, 60))
    protocol.append(StageSpec(5, 80))
    if max_iter:
        protocol = [StageSpec(s.stage, max_iter, s.method) for s in protocol]
    summary = run_protocol(prob, protocol=protocol, converge_tol=1e-4, patience=3)
    rep = build_report(prob, summary)
    goals = evaluate_goals(prob, summary)

    out = {
        "sample": spec.name,
        "phases": [MINERALS[k].name for k in spec.phases],
        "n_points": int(prob.two_theta.size),
        "two_theta": [float(prob.two_theta[0]), float(prob.two_theta[-1])],
        "rwp0": float(rwp0),
        "rwp": float(summary.metrics["Rwp"]),
        "rexp": float(summary.metrics.get("Rexp", 0.0)),
        "gof": float(summary.metrics["GOF"]),
        "nfev": int(summary.result.nfev),
        "seconds": round(time.perf_counter() - t0, 1),
        "stages": [{k: v for k, v in s.items()
                    if k in ("stage", "label", "Rwp", "nfev", "rolled_back")}
                   for s in summary.stages],
        "seed_notes": list(seeds.notes),
        "health": rep.healthy,
        "findings": [f.text() for f in rep.findings],
        "goals": [g.text() for g in goals],
        "fractions": {},
        "scales": {},
        "truth": dict(spec.truth),
        "amorphous": spec.amorphous,
    }
    # 标度留档：定量口径若调整，不必重跑拟合就能重算分数
    for ph in prob.phases:
        out["scales"][ph.label] = float(prob.params.get(f"{ph.prefix}.scale", 0.0))
    # 重量分数取 GoalResult（已带 Hill–Howard 误差传播），别绕过它直接读 quant。
    # 键用**矿物键**（ZnO/CaCO3…）而不是相名（Zincite/Calcite），才能和真值对表。
    frac_goals = [g for g in goals if g.name == "fraction"]
    for key, g in zip(spec.phases, frac_goals):
        out["fractions"][key] = [round(g.value, 2), round(g.sigma, 2)]
    return out


# ══════════════════════════════════════════════════════════════════
# 报告
# ══════════════════════════════════════════════════════════════════

def markdown_table(rows: Sequence[dict]) -> str:
    head = ("| 试样 | 相 | Rwp 初 → 终 (%) | GOF | 迭代 | 耗时 (s) "
            "| 健康 | 主要提示 |")
    sep = "|" + "---|" * 8
    lines = [head, sep]
    for r in rows:
        warn = [f for f in r["findings"] if f.startswith("[错误]")
                or f.startswith("[警告]")]
        tip = warn[0].split("] ", 1)[-1][:42] + "…" if warn else "—"
        lines.append(
            f"| {r['sample']} | {'+'.join(r['phases'])} "
            f"| {r['rwp0']:.2f} → {r['rwp']:.2f} | {r['gof']:.2f} "
            f"| {r['nfev']} | {r['seconds']} "
            f"| {'OK' if r['health'] else '有告警'} | {tip} |")
    return "\n".join(lines)


def quant_table(rows: Sequence[dict]) -> str:
    lines = ["| 试样 | 相 | 真值 wt% | 精修 wt% | Δ | 相对晶相真值 | 相对晶相精修 |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["truth"]:
            continue
        crys = sum(r["truth"].values()) or 1.0
        crys_fit = sum(v[0] for v in r["fractions"].values()) or 1.0
        for lab, t in r["truth"].items():
            w = r["fractions"].get(lab, [0.0, 0.0])
            lines.append(
                f"| {r['sample']} | {lab} | {t:.2f} | {w[0]:.2f} ± {w[1]:.2f} "
                f"| {w[0] - t:+.2f} | {100 * t / crys:.2f} "
                f"| {100 * w[0] / crys_fit:.2f} |")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 交叉样本：与 PolyXRD-LFP 这套独立实现比同一份数据
# ══════════════════════════════════════════════════════════════════

CROSS_DIR = Path(r"D:\Project\XRD\XRData\smz geshi")
LFP_CIF = Path(r"D:\Project\PolyXRD-Tools\PolyXRD-LFP\lfp\data\lfp.cif")


@dataclass
class CrossSpec:
    name: str
    pattern: str                                   # 谱图文件通配（文件名含 #，不能直拼）
    reference: Dict[str, float] = field(default_factory=dict)   # 参照值
    note: str = ""


# 参照值取自 PolyXRD-LFP 的 docs/VALIDATION_v1.0.0.md §3（同一份 Shimadzu 谱）。
# 对拍意义：两套实现的结构来源、峰形口径、权重都不同，晶胞若能在 1e-3 Å 内
# 对上、D/ε 在同量级，说明 PolyXRD 的 1/V² 强度口径与 Caglioti+size/strain
# 标定没有系统偏差。
CROSS: Dict[str, CrossSpec] = {
    "LFP-01": CrossSpec(
        "LFP-01", "LiFePO4#01*_100.txt",
        {"rwp": 22.13, "gof": 0.852, "a": 10.32441,
         "size_nm": 97.2, "strain_pct": 0.005},
        note="快扫（计数低）：GOF<1 说明残差已到泊松噪声限"),
    "LFP-02": CrossSpec(
        "LFP-02", "LinSuanTieLi#1*_100.txt",
        {"rwp": 12.76, "gof": 2.055, "a": 10.32274,
         "size_nm": 117.3, "strain_pct": 0.002},
        note="计数高：Rwp 好看但 GOF>2，模型仍有系统偏差"),
}


def load_shimadzu(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Shimadzu 剖面转储 txt → (2θ, I)。

    格式：若干行 ``key = value`` 头信息，数据区由 ``<2Theta>   <   I   >``
    开头，其后每行两列空白分隔；遇非数字行（结尾标记）即停。
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if "<2Theta>" in ln), None)
    if start is None:
        raise RuntimeError(f"{path.name}: 找不到 <2Theta> 表头")
    tt: List[float] = []
    yy: List[float] = []
    for ln in lines[start:]:
        parts = ln.split()
        if len(parts) < 2:
            break
        try:
            tt.append(float(parts[0]))
            yy.append(float(parts[1]))
        except ValueError:
            break
    if len(tt) < 100:
        raise RuntimeError(f"{path.name}: 数据区只读到 {len(tt)} 个点")
    return np.asarray(tt), np.asarray(yy)


def lfp_structure() -> StructureModel:
    """lfp.cif → 全胞 ``StructureModel``（P n m a，28 位点）。"""
    from polyxrd.services.phase_cif import cif_to_phase

    phase = cif_to_phase(LFP_CIF.read_text(encoding="utf-8", errors="replace"),
                         fallback_name="LiFePO4")
    st = StructureModel.from_phase(phase)
    if st is None or not st.sites:
        raise RuntimeError(f"{LFP_CIF.name}: 解析不出结构（晶胞或位点缺失）")
    return st


def run_cross(spec: CrossSpec, *, max_iter: Optional[int] = None) -> dict:
    t0 = time.perf_counter()
    hits = sorted(CROSS_DIR.glob(spec.pattern))
    if not hits:
        raise RuntimeError(f"{spec.name}: {CROSS_DIR} 下找不到 {spec.pattern}")
    tt, y = load_shimadzu(hits[0])
    prob = PatternProblem(
        tt, y,
        [PhaseBlock(label="LiFePO4", structure=lfp_structure(), index=0)],
        profile=ProfileParams(w=0.02, x=0.01, y=0.0),
        bg=BackgroundParams("tent", max(8, int(round((tt[-1] - tt[0]) / 8.0)))),
        wavelength=KALPHA2.wavelength, kalph2=KALPHA2,
        weights=1.0 / np.maximum(y, 1.0), cutoff_fwhm=CUT,
    )
    rwp0 = prob.metrics()["Rwp"]
    seed_problem(prob, apply=True)
    protocol = [StageSpec(2, 150), StageSpec(3, 120), StageSpec(5, 80)]
    if max_iter:
        protocol = [StageSpec(s.stage, max_iter, s.method) for s in protocol]
    summary = run_protocol(prob, protocol=protocol, converge_tol=1e-4, patience=3)

    pref = prob.phases[0].prefix
    a = float(prob.params.get(f"{pref}.cell.a", 0.0))
    size = float(prob.params.get(f"{pref}.size", 0.0))
    strain = float(prob.params.get(f"{pref}.strain", 0.0))
    return {
        "sample": spec.name,
        "file": hits[0].name,
        "n_points": int(tt.size),
        "two_theta": [float(tt[0]), float(tt[-1])],
        "rwp0": float(rwp0),
        "rwp": float(summary.metrics["Rwp"]),
        "rexp": float(summary.metrics.get("Rexp", 0.0)),
        "gof": float(summary.metrics["GOF"]),
        "a": a,
        "size_nm": size,
        "strain_pct": strain * 100.0,
        "nfev": int(summary.result.nfev),
        "seconds": round(time.perf_counter() - t0, 1),
        "reference": dict(spec.reference),
        "note": spec.note,
    }


def cross_table(rows: Sequence[dict]) -> str:
    lines = [
        "| 试样 | Rwp 初 → 终 (%) | GOF | a (Å) | 参考 a | Δa (mÅ) "
        "| D (nm) | 参考 D | ε (%) | 参考 ε | 耗时 (s) |",
        "|" + "---|" * 11,
    ]
    for r in rows:
        ref = r["reference"]
        lines.append(
            f"| {r['sample']} | {r['rwp0']:.2f} → {r['rwp']:.2f} | {r['gof']:.2f} "
            f"| {r['a']:.5f} | {ref.get('a', 0.0):.5f} "
            f"| {1000 * (r['a'] - ref.get('a', 0.0)):+.2f} "
            f"| {r['size_nm']:.1f} | {ref.get('size_nm', 0.0):.1f} "
            f"| {r['strain_pct']:.4f} | {ref.get('strain_pct', 0.0):.4f} "
            f"| {r['seconds']} |")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="v5.0.0 真实试样精修基准")
    ap.add_argument("samples", nargs="*", help="试样名（默认全部，含交叉样本）")
    ap.add_argument("--json", default="", help="明细写到该 JSON")
    ap.add_argument("--max-iter", type=int, default=0, help="每阶段迭代上限")
    args = ap.parse_args(argv)

    all_names = list(SPECS) + list(CROSS)
    rows: List[dict] = []
    cross: List[dict] = []
    for name in args.samples or all_names:
        if name in SPECS:
            print(f">>> {name} ...", file=sys.stderr, flush=True)
            rows.append(run_sample(SPECS[name], max_iter=args.max_iter or None))
        elif name in CROSS:
            print(f">>> {name}（交叉）...", file=sys.stderr, flush=True)
            cross.append(run_cross(CROSS[name], max_iter=args.max_iter or None))
        else:
            print(f"未知试样 {name}，可选：{', '.join(all_names)}", file=sys.stderr)
            return 2

    if rows:
        print("\n## 拟合质量\n")
        print(markdown_table(rows))
        print("\n## 定量（Hill–Howard vs 真值）\n")
        print(quant_table(rows))
    if cross:
        print("\n## 交叉样本（与 PolyXRD-LFP 独立实现对拍同一份谱）\n")
        print(cross_table(cross))

    if args.json:
        Path(args.json).write_text(
            json.dumps({"samples": rows, "cross": cross},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n明细已写入 {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
