"""
PolyXRD 13 试样端到端验证 (含元素限定)
=====================================
逐一加载 D:/Project/XRD/test_xrd/txt 下的 13 个 XRD 试样,
按元素限定文件执行三态元素过滤物相识别 + Rietveld 精修定量,
比对预期物相和含量, 生成测试报告。
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path

import numpy as np

# ── 元素限定 (来自 元素限定.txt) ──────────────────────────
ELEMENT_FILTERS = {
    "1-1":  {"must": ["Fe", "P"],            "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "1-2":  {"must": ["Ni", "Co", "Mn"],     "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg","Al"]},
    "2-1":  {"must": ["Zn", "Ca"],           "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "2-2":  {"must": ["Ti"],                 "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "3-1":  {"must": ["Zn", "Ca", "Al"],     "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "3-2":  {"must": ["Zn", "Ca", "Al", "Si"], "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "4-1":  {"must": ["Zn", "Ca", "Al", "Mg"], "maybe": ["H","Li","Be","B","C","N","O","F","Na"]},
    "5-1":  {"must": ["Si", "Ca", "Mg"],     "maybe": ["H","Li","Be","B","C","N","O","F","Na"]},
    "5-2":  {"must": ["Si", "Ca", "Fe", "Al", "K"], "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "5-2b": {"must": ["Si", "Ca", "Fe", "Al", "K"], "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "5-3":  {"must": ["Si", "Ca", "Al", "P", "Fe"], "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "7-1":  {"must": ["Si", "Al", "Ti", "Fe"], "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"]},
    "7-2":  {"must": ["Si", "Na", "K", "Ca", "Fe", "Al", "Mg"], "maybe": ["H","Li","Be","B","C","N","O","F","Zr"]},
}

# ── 预期结果 (来自 物相结果+wt%.txt) ──────────────────────
EXPECTED = {
    "1-1":  {"phases": [("LiFePO4", 100.0)]},
    "1-2":  {"phases": [("NCM 811", 100.0)]},
    "2-1":  {"phases": [("ZnO", 50.0), ("CaCO3", 50.0)]},
    "2-2":  {"phases": [("TiO2锐钛矿", None), ("TiO2金红石", None)]},
    "3-1":  {"phases": [("ZnO", 93.59), ("Al2O3", 5.04), ("CaF2", 1.36)]},
    "3-2":  {"phases": [("ZnO", 19.68), ("Al2O3", 30.79), ("CaF2", 20.06), ("非晶玻璃", 29.47)]},
    "4-1":  {"phases": [("ZnO", 19.94), ("Al2O3", 21.27), ("CaF2", 22.53), ("Mg(OH)2", 36.26)]},
    "5-1":  {"phases": [("SiO2(α-石英)", None), ("SiO2(方石英)", None), ("CaCO3", None),
                         ("MgCO3", None), ("CaMg(CO3)2", None)]},
    "5-2":  {"phases": [("SiO2(α-石英)", None), ("SiO2(方石英)", None), ("CaCO3", None),
                         ("Fe2O3", None), ("白云母", None)]},
    "5-2b": {"phases": [("SiO2(α-石英)", None), ("SiO2(方石英)", None), ("CaCO3", None),
                         ("Fe2O3", None), ("白云母", None)]},
    "5-3":  {"phases": [("SiO2", None), ("Ca2Al2SiO7", None), ("Ca5[PO4]3F", None),
                         ("α-FeO(OH)", None), ("高岭土", None)]},
    "7-1":  {"phases": [("Quartz", 5.16), ("Boehmite", 14.93), ("Anatase", 2.00),
                         ("Goethite", 9.98), ("Kaolinite", 3.02), ("Gibbsite", 54.90),
                         ("Hematite", 10.00)]},
    "7-2":  {"phases": [("Quartz", None), ("Feldspar", None), ("Albite", None),
                         ("Biotite", None), ("Clinochlore", None), ("Hornblende", None),
                         ("Zircon", None)]},
}

# ── 预期物相名 → 内置库名称映射 ──────────────────────────
PHASE_NAME_MAP = {
    "LiFePO4": "Lithium iron phosphate",
    "NCM 811": "NCM 811",
    "ZnO": "Zincite",
    "CaCO3": "Calcite",
    "TiO2锐钛矿": "Anatase",
    "TiO2金红石": "Rutile",
    "Al2O3": "Corundum",
    "CaF2": "Fluorite",
    "Mg(OH)2": "Brucite",
    "SiO2(α-石英)": "α-Quartz",
    "SiO2(方石英)": "Cristobalite",
    "SiO2": "α-Quartz",
    "MgCO3": "Magnesite",
    "CaMg(CO3)2": "Dolomite",
    "Fe2O3": "Hematite",
    "白云母": "Muscovite",
    "高岭土": "Kaolinite",
    "Quartz": "α-Quartz",
    "Boehmite": "Boehmite",
    "Anatase": "Anatase",
    "Goethite": "Goethite",
    "Kaolinite": "Kaolinite",
    "Gibbsite": "Gibbsite",
    "Hematite": "Hematite",
    "Feldspar": "Feldspar",
    "Albite": "Albite",
    "Biotite": "Biotite",
    "Clinochlore": "Clinochlore",
    "Hornblende": "Hornblende",
    "Zircon": "Zircon",
    "非晶玻璃": None,
    "Ca2Al2SiO7": None,
    "Ca5[PO4]3F": None,
    "α-FeO(OH)": "Goethite",
}

DATA_DIR = Path(r"D:/Project/XRD/test_xrd/txt")


def load_xrd(file_path: Path):
    from polyxrd.services.data_loader import DataLoader
    return DataLoader().load(file_path)


def find_peaks(data):
    from polyxrd.services.peak_finder import PeakFinder
    return PeakFinder().find_peaks(data)


def identify_with_filter(data, peaks, element_filter, top_n=10, tolerance=0.2):
    """三态元素过滤物相识别"""
    from polyxrd.services.phase_identifier import PhaseIdentifier
    pi = PhaseIdentifier()
    results = pi.identify_with_element_filter(
        data, peaks=peaks, element_filter=element_filter,
        top_n=top_n, tolerance=tolerance,
    )
    return results


def refine_quantify(data, phases, max_cycles=30):
    from polyxrd.services.rietveld_refiner import RietveldRefiner
    refiner = RietveldRefiner()
    result = refiner.refine(data, phases, engine="builtin", max_cycles=max_cycles)
    return result


def match_expected(expected_name: str, found_name: str) -> bool:
    mapped = PHASE_NAME_MAP.get(expected_name, expected_name)
    if mapped is None:
        return False
    fl = found_name.lower()
    ml = mapped.lower()
    el = expected_name.lower()
    return (ml in fl) or (fl in ml) or (el in fl) or (fl in el)


def run_single_test(sample_id: str) -> dict:
    result = {
        "sample": sample_id,
        "status": "RUNNING",
        "file": None,
        "n_points": 0,
        "two_theta_range": "",
        "element_filter": ELEMENT_FILTERS.get(sample_id, {}),
        "n_candidates": 0,
        "identified": [],
        "refined": [],
        "expected": EXPECTED.get(sample_id, {"phases": []}),
        "match_phase": [],
        "match_wt": [],
        "wR": 0.0,
        "GOF": 0.0,
        "quality": "",
        "error": None,
    }

    file_path = DATA_DIR / f"{sample_id}.txt"
    if not file_path.exists():
        result["status"] = "FAIL"
        result["error"] = f"文件不存在: {file_path}"
        return result
    result["file"] = str(file_path)

    try:
        # 1. 加载数据
        data = load_xrd(file_path)
        result["n_points"] = len(data)
        result["two_theta_range"] = f"{data.two_theta[0]:.1f}-{data.two_theta[-1]:.1f}"

        # 2. 峰检测
        peaks = find_peaks(data)

        # 3. 元素限定物相识别
        ef = result["element_filter"]
        matches = identify_with_filter(data, peaks, ef, top_n=10, tolerance=0.2)
        result["n_candidates"] = len(matches)
        for m in matches[:5]:
            result["identified"].append({
                "name": m.phase.name,
                "formula": m.phase.formula,
                "fom": m.score,
                "coverage": m.coverage,
                "matched_peaks": m.matched_peaks,
                "total_peaks": m.total_peaks,
            })

        # 4. 比对预期物相
        expected_phases = result["expected"]["phases"]
        found_names = [m.phase.name for m in matches]
        for exp_name, exp_wt in expected_phases:
            matched = False
            for fn in found_names:
                if match_expected(exp_name, fn):
                    matched = True
                    break
            result["match_phase"].append({
                "expected": exp_name,
                "expected_wt": exp_wt,
                "matched": matched,
                "found": [fn for fn in found_names if match_expected(exp_name, fn)][:3],
            })

        # 5. Rietveld 精修定量 (使用 build_refinement_combination 优化物相组合)
        has_wt = any(w is not None for _, w in expected_phases)
        if has_wt and matches:
            from polyxrd.services.phase_identifier import PhaseIdentifier
            pi2 = PhaseIdentifier()
            expected_cnt = len(expected_phases)
            refine_phases = pi2.build_refinement_combination(
                matches, expected_count=expected_cnt, min_coverage=0.3,
                peaks=peaks,
            )
            try:
                ref_result = refine_quantify(data, refine_phases, max_cycles=30)
                result["wR"] = ref_result.wR
                result["GOF"] = ref_result.GOF
                result["quality"] = ref_result.quality_grade

                for p in ref_result.phases:
                    wt = getattr(p, "weight_fraction", 0.0) or 0.0
                    result["refined"].append({
                        "name": p.name,
                        "formula": p.formula,
                        "wt_pct": wt,
                    })

                for exp_name, exp_wt in expected_phases:
                    if exp_wt is None:
                        continue
                    mapped = PHASE_NAME_MAP.get(exp_name, exp_name)
                    if mapped is None:
                        result["match_wt"].append({
                            "expected": exp_name, "expected_wt": exp_wt,
                            "found": None, "found_wt": None,
                            "diff": None, "status": "NOMAP",
                        })
                        continue
                    found_wt = None
                    for r in result["refined"]:
                        if match_expected(exp_name, r["name"]):
                            found_wt = r["wt_pct"]
                            break
                    diff = abs(found_wt - exp_wt) if found_wt is not None else None
                    result["match_wt"].append({
                        "expected": exp_name,
                        "expected_wt": exp_wt,
                        "found": mapped,
                        "found_wt": round(found_wt, 2) if found_wt is not None else None,
                        "diff": round(diff, 2) if diff is not None else None,
                        "status": "PASS" if (diff is not None and diff < 10.0) else "FAIL",
                    })
            except Exception as e:
                result["error"] = f"精修失败: {e}"

        result["status"] = "DONE"
    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = f"{e}\n{traceback.format_exc()}"

    return result


def generate_report(results: list[dict]) -> str:
    lines = []
    lines.append("=" * 90)
    lines.append("PolyXRD 程序可用性测试报告 (含元素限定)")
    lines.append(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"测试试样: {len(results)} 个")
    lines.append(f"元素限定: 按元素限定.txt 三态过滤 (must/maybe/exclude)")
    lines.append("=" * 90)
    lines.append("")

    # 1. 数据加载 + 元素限定
    lines.append("-" * 70)
    lines.append("1. 数据加载 + 元素限定概览")
    lines.append("-" * 70)
    lines.append(f"{'试样':<7} {'数据点':>6} {'2θ范围':<14} {'必含元素':<22} {'候选':>4} {'状态':<4}")
    lines.append("-" * 70)
    for r in results:
        status = "OK" if r["status"] != "FAIL" else "FAIL"
        must_str = "/".join(r["element_filter"].get("must", []))
        lines.append(f"{r['sample']:<7} {r['n_points']:>6} {r['two_theta_range']:<14} "
                     f"{must_str:<22} {r['n_candidates']:>4} {status:<4}")
    lines.append("")

    # 2. 物相识别结果
    lines.append("-" * 70)
    lines.append("2. 物相识别结果 (Top-5, 含元素限定过滤)")
    lines.append("-" * 70)
    for r in results:
        lines.append(f"\n  ■ 试样 {r['sample']}:")
        lines.append(f"    元素限定: 必含={','.join(r['element_filter'].get('must',[]))} "
                     f"可能含={','.join(r['element_filter'].get('maybe',[]))}")
        if r["error"] and r["status"] == "FAIL":
            lines.append(f"    错误: {r['error']}")
            continue
        if not r["identified"]:
            lines.append("    未识别到物相")
        else:
            lines.append(f"    {'#':<3} {'物相名':<28} {'化学式':<18} {'FOM':>7} {'覆盖率':>7}")
            for i, p in enumerate(r["identified"][:5]):
                lines.append(f"    {i+1:<3} {p['name']:<28} {p['formula']:<18} "
                             f"{p['fom']:>7.3f} {p['coverage']:>6.1f}%")

        if r["match_phase"]:
            lines.append(f"    预期物相比对:")
            all_matched = True
            for m in r["match_phase"]:
                mark = "Y" if m["matched"] else "X"
                if not m["matched"]:
                    all_matched = False
                found_str = ", ".join(m["found"]) if m["found"] else "未找到"
                lines.append(f"      [{mark}] {m['expected']:<20} -> {found_str}")
            r["phase_all_matched"] = all_matched
    lines.append("")

    # 3. 精修定量结果
    lines.append("-" * 70)
    lines.append("3. Rietveld 精修定量结果")
    lines.append("-" * 70)
    for r in results:
        if not r["refined"]:
            continue
        lines.append(f"\n  ■ 试样 {r['sample']}:")
        lines.append(f"    wR = {r['wR']:.2f}%  GOF = {r['GOF']:.4f}  质量评级 = {r['quality']}")
        lines.append(f"    {'物相名':<28} {'wt%':>8}")
        for p in r["refined"]:
            lines.append(f"    {p['name']:<28} {p['wt_pct']:>8.2f}")

        if r["match_wt"]:
            lines.append(f"    含量比对:")
            wt_pass = 0
            wt_total = 0
            for m in r["match_wt"]:
                mark = "Y" if m["status"] == "PASS" else "X"
                if m["status"] == "PASS":
                    wt_pass += 1
                wt_total += 1
                if m["found_wt"] is not None:
                    lines.append(f"      [{mark}] {m['expected']:<20} 预期={m['expected_wt']:>6.2f}%  "
                                 f"实测={m['found_wt']:>6.2f}%  偏差={m['diff']:>5.2f}%")
                else:
                    lines.append(f"      [{mark}] {m['expected']:<20} 预期={m['expected_wt']:>6.2f}%  "
                                 f"实测=未找到")
            r["wt_pass"] = wt_pass
            r["wt_total"] = wt_total
    lines.append("")

    # 4. 测试总结
    lines.append("-" * 70)
    lines.append("4. 测试总结")
    lines.append("-" * 70)

    phase_total = 0
    phase_hit = 0
    for r in results:
        for m in r.get("match_phase", []):
            phase_total += 1
            if m["matched"]:
                phase_hit += 1

    wt_total_all = 0
    wt_pass_all = 0
    for r in results:
        wt_total_all += r.get("wt_total", 0)
        wt_pass_all += r.get("wt_pass", 0)

    n_loaded = sum(1 for r in results if r["status"] != "FAIL")
    n_refined = sum(1 for r in results if r["refined"])

    lines.append(f"数据加载:        {n_loaded}/{len(results)} 试样成功")
    lines.append(f"物相识别命中率:  {phase_hit}/{phase_total} 物相命中 "
                 f"({100*phase_hit/max(1,phase_total):.1f}%)")
    if wt_total_all > 0:
        lines.append(f"含量定量命中率:  {wt_pass_all}/{wt_total_all} 物相含量偏差<10% "
                     f"({100*wt_pass_all/wt_total_all:.1f}%)")
    lines.append(f"精修定量:        {n_refined}/{len(results)} 试样完成精修")
    lines.append("")

    # 5. 单试样结论
    lines.append("-" * 70)
    lines.append("5. 单试样结论")
    lines.append("-" * 70)
    lines.append(f"{'试样':<7} {'数据':<6} {'物相识别':<10} {'精修定量':<10} {'结论':<20}")
    lines.append("-" * 70)
    for r in results:
        data_ok = "Y" if r["n_points"] > 0 else "X"
        if r.get("match_phase"):
            ph = sum(1 for m in r["match_phase"] if m["matched"])
            pt = len(r["match_phase"])
            phase_str = f"{ph}/{pt}"
        else:
            phase_str = "-"
        if r["refined"]:
            if r.get("wt_total", 0) > 0:
                wt_str = f"{r.get('wt_pass',0)}/{r['wt_total']}"
            else:
                wt_str = "完成"
        else:
            wt_str = "未做"
        if r["status"] == "FAIL":
            concl = "失败"
        elif r.get("phase_all_matched") and r.get("wt_pass", 0) == r.get("wt_total", 0):
            concl = "完全通过"
        elif r.get("phase_all_matched"):
            concl = "物相通过"
        else:
            concl = "部分通过"
        lines.append(f"{r['sample']:<7} {data_ok:<6} {phase_str:<10} {wt_str:<10} {concl:<20}")

    lines.append("")
    lines.append("=" * 90)
    lines.append("报告结束")
    lines.append("=" * 90)

    return "\n".join(lines)


def main():
    print("PolyXRD 13 试样端到端验证 (含元素限定)")
    print("=" * 60)

    sample_ids = ["1-1", "1-2", "2-1", "2-2", "3-1", "3-2",
                  "4-1", "5-1", "5-2", "5-2b", "5-3", "7-1", "7-2"]

    results = []
    for sid in sample_ids:
        print(f"\n[测试] 试样 {sid} ...", flush=True)
        t0 = time.time()
        r = run_single_test(sid)
        elapsed = time.time() - t0
        r["elapsed_s"] = elapsed
        must_str = "/".join(r["element_filter"].get("must", []))
        print(f"  -> 状态: {r['status']}  耗时: {elapsed:.1f}s  数据点: {r['n_points']}  "
              f"必含: {must_str}  候选: {r['n_candidates']}", flush=True)
        if r["identified"]:
            print(f"  -> Top-1: {r['identified'][0]['name']} "
                  f"(FOM={r['identified'][0]['fom']:.3f})", flush=True)
        if r["error"]:
            print(f"  -> 错误: {r['error'][:200]}", flush=True)
        results.append(r)

    print("\n" + "=" * 60)
    print("生成测试报告...")
    report = generate_report(results)

    report_path = DATA_DIR / "PolyXRD_测试报告_元素限定.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"报告已保存: {report_path}")
    print("\n" + report)


if __name__ == "__main__":
    main()
