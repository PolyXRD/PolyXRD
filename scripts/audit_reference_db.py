"""内置参考库全库条目审计 (对账引用 COD 结构 vs 库内峰表)
====================================================================
对每条含引用 COD 结构的条目: 取回 CIF → CifParser 对称展开 →
XRDCalculator 重算理论谱, 与库内峰表对比:
  ① 主线位置差 Δθ_main (库内最强线 vs 理论最强线最近邻);
  ② 理论主线在库内是否有命中 (≤0.35°);
  ③ 库内主线在理论谱里的强度占比 (强度乱序检测)。
输出嫌疑清单 (Δθ>0.3° 或 理论主线缺失 或 库主线理论强度<50%)。

用法: venv/Scripts/python.exe scripts/audit_reference_db.py
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

JSON_PATH = ROOT / "src" / "polyxrd" / "resources" / "database" / "xrd_reference_database.json"
REPORT = ROOT / "_refdb_audit_report.txt"
WAVELENGTH = 1.5406
TTH_RANGE = (5.0, 90.0)


def _cod_id(src: str) -> int | None:
    m = re.search(r"COD\s+(\d{5,7})", str(src or ""))
    return int(m.group(1)) if m else None


def _load_struct(cod_id: int):
    from pymatgen.io.cif import CifParser
    from polyxrd.services.cod_local import CODLocalDatabase

    txt = CODLocalDatabase().get_cif(cod_id)
    if not txt:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                primitive=False)[0]
        except Exception:  # noqa: BLE001
            return None


def _pattern(struct):
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    pat = XRDCalculator(wavelength=WAVELENGTH).get_pattern(
        struct, two_theta_range=TTH_RANGE)
    imax = float(pat.y.max()) or 1.0
    theo = sorted(
        ((float(x), float(y) / imax * 100.0) for x, y in zip(pat.x, pat.y)),
        key=lambda t: -t[1])
    return theo


def main() -> int:
    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    lines, suspects = [], []
    for e in doc["phases"]:
        cid = _cod_id(e.get("peaks_source", ""))
        if cid is None:
            lines.append(f"[无源] {e.get('name','?'):16s} peaks_source 无 COD 引用, 跳过")
            continue
        struct = _load_struct(cid)
        if struct is None:
            lines.append(f"[无CIF] {e.get('name','?'):16s} COD {cid} 不可用, 跳过")
            continue
        try:
            theo = _pattern(struct)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"[算崩] {e.get('name','?'):16s} COD {cid}: {exc}")
            continue
        if not theo or not e.get("peaks"):
            continue
        lib = sorted(e["peaks"], key=lambda p: -float(p["intensity"]))
        lib_main = lib[0]
        # 理论主线 → 库内最近邻
        t_main = theo[0]
        d = [abs(p["two_theta"] - t_main[0]) for p in e["peaks"]]
        i_near = min(range(len(d)), key=lambda i: d[i])
        gap_main = d[i_near]
        # 库内主线在理论谱中的最近强度
        dd = [abs(x - lib_main["two_theta"]) for x, _ in theo]
        j = min(range(len(dd)), key=lambda i: dd[i])
        theo_i_of_lib_main = theo[j][1] if dd[j] <= 0.35 else 0.0
        bad = (gap_main > 0.3) or (theo_i_of_lib_main < 50.0)
        if bad:
            suspects.append(e.get("name", "?"))
            lines.append(
                f"[SUSPECT] {e.get('name','?'):16s} COD {cid} "
                f"理论主线 {t_main[0]:7.2f}°(I={t_main[1]:5.1f}) → 库内最近 {gap_main:.2f}° | "
                f"库主线 {lib_main['two_theta']:7.2f}° 的理论强度 {theo_i_of_lib_main:5.1f}% "
                f"| 库n={len(e['peaks'])}")
        else:
            lines.append(
                f"[ok]      {e.get('name','?'):16s} COD {cid} "
                f"主线 {lib_main['two_theta']:7.2f}° ≈ 理论 {t_main[0]:7.2f}° "
                f"(Δ={gap_main:.2f}°, 理论强度占比 {theo_i_of_lib_main:5.1f}%)")

    lines.insert(0, f"===== 审计 {time_note()} : 嫌疑 {len(suspects)} 条 =====")
    lines.insert(1, "嫌疑清单: " + ", ".join(suspects))
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"[report] {REPORT}")
    return 0


def time_note() -> str:
    import time
    return time.strftime("%F %T")


if __name__ == "__main__":
    raise SystemExit(main())
