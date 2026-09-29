"""修复内置参考库 Cristobalite 条目 (v0.15.2 → 0.5.3 数据修复)
==========================================================================

**病根**: `SiO2_cristobalite` 条目挂的是 **β-cristobalite 型正交晶胞**
(P2_12_12_1, a=7.22/b=7.09/c=7.30, COD 9017505), 其最强线 (111) 落在
**21.35°**; 而室温稳定相是 **α-cristobalite** (四方 P4_12_12,
a≈4.9717/c≈6.9223), 最强线 (101) 在 **≈21.95°**。
实测后果 (S19 基准): 5-1/5-2/5-2b 三个含方石英样品在 21.84–21.94° 有强峰,
与库内 21.353° 相差 ~0.5° > 0.2° 容差 → Cristobalite B 级检索全部 MISS,
组合层连带丢相 (5-1 缺 Cristobalite 多出 Diopside)。

**修复 (与 regenerate_reference_db_peaks.py 同手法)**: 取本地 COD
α-cristobalite 结构 (默认 9001578, P4_12_12, a=4.9717/c=6.9223, 12 位点),
CifParser 对称展开 → XRDCalculator (Cu Kα 1.5406) 重算峰表,
接管条目 lattice / space_group 保证峰表与晶胞自洽。

用法:
  venv/Scripts/python.exe scripts/fix_reference_db_cristobalite.py             # 试算
  venv/Scripts/python.exe scripts/fix_reference_db_cristobalite.py --write     # 落盘 (先备份)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import warnings
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

JSON_PATH = ROOT / "src" / "polyxrd" / "resources" / "database" / "xrd_reference_database.json"
REPORT = ROOT / "_refdb_cristobalite_fix_report.txt"

WAVELENGTH = 1.5406
TTH_RANGE = (5.0, 90.0)
MIN_INTENSITY = 0.4
PEAKS_VER = "0.5.3-alpha-cristobalite-fix"
DEFAULT_COD_ID = 9001578   # α-cristobalite, P4_12_12, a=4.9717, c=6.9223
TARGET_KEY = "SiO2_cristobalite"


def _load_struct(cod_id: int):
    from pymatgen.io.cif import CifParser
    from polyxrd.services.cod_local import CODLocalDatabase

    txt = CODLocalDatabase().get_cif(cod_id)
    if not txt:
        raise SystemExit(f"COD {cod_id} 无本地 CIF")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
            primitive=False)[0]


def _peaks_from_struct(struct) -> list[dict]:
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    pat = XRDCalculator(wavelength=WAVELENGTH).get_pattern(
        struct, two_theta_range=TTH_RANGE)
    rows = []
    for i in range(len(pat.x)):
        inten = float(pat.y[i])
        hkl = [0, 0, 0]
        info = pat.hkls[i] if i < len(pat.hkls) else []
        if info and isinstance(info[0], dict):
            raw = list(info[0].get("hkl", (0, 0, 0)))
            if len(raw) >= 3:
                hkl = [int(v) for v in raw[:3]]
        rows.append({"hkl": hkl, "two_theta": float(pat.x[i]), "intensity": inten})
    if not rows:
        return []
    imax = max(r["intensity"] for r in rows) or 1.0
    return [
        {"hkl": r["hkl"], "two_theta": round(r["two_theta"], 3),
         "intensity": round(100.0 * r["intensity"] / imax, 2)}
        for r in rows if 100.0 * r["intensity"] / imax >= MIN_INTENSITY
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="落盘 (会先备份)")
    ap.add_argument("--cod-id", type=int, default=DEFAULT_COD_ID)
    args = ap.parse_args()

    struct = _load_struct(args.cod_id)
    p = struct.lattice.parameters
    sg_name = str(struct.get_space_group_info()[0])
    comp = struct.composition.reduced_formula
    log: list[str] = [
        f"结构源: COD {args.cod_id} ({comp}, {sg_name}, {len(struct)} 位点)",
        f"  晶胞: a={p[0]:.4f} b={p[1]:.4f} c={p[2]:.4f} "
        f"α={p[3]:.2f} β={p[4]:.2f} γ={p[5]:.2f}",
    ]
    if comp != "SiO2":
        raise SystemExit(f"化学式不符: {comp} != SiO2")

    peaks = _peaks_from_struct(struct)
    if not peaks:
        raise SystemExit("峰表重算为空")
    top3 = sorted(peaks, key=lambda r: -r["intensity"])[:3]
    main = top3[0]
    log.append(f"新峰表: {len(peaks)} 峰; 最强线 "
               f"({main['hkl'][0]}{main['hkl'][1]}{main['hkl'][2]}) "
               f"@ {main['two_theta']:.3f}° (I=100)")
    for r in top3[1:]:
        log.append(f"  次强: ({r['hkl'][0]}{r['hkl'][1]}{r['hkl'][2]}) "
                   f"@ {r['two_theta']:.3f}° I={r['intensity']:.2f}")
    if abs(main["two_theta"] - 21.95) > 0.8:
        raise SystemExit(f"最强线 {main['two_theta']:.2f}° 偏离 α-cristobalite "
                         f"参考值 21.95° 过远, 疑似拿错结构, 拒绝落盘")

    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    entry = next((e for e in doc["phases"] if e.get("key") == TARGET_KEY), None)
    if entry is None:
        raise SystemExit(f"条目 {TARGET_KEY} 不存在")
    old_main = max(entry["peaks"], key=lambda q: q["intensity"]) if entry.get("peaks") else None
    log.append(f"条目 {TARGET_KEY}: 旧主峰 {old_main['two_theta']:.3f}° → "
               f"新主峰 {main['two_theta']:.3f}°; 峰数 {len(entry['peaks'])}→{len(peaks)}")

    if args.write:
        bak = JSON_PATH.with_suffix(".json.bak-" + date.today().isoformat())
        if not bak.exists():
            shutil.copy2(JSON_PATH, bak)
            log.append(f"[backup] {bak.name}")
        entry["lattice"] = {
            "a": round(p[0], 4), "b": round(p[1], 4), "c": round(p[2], 4),
            "alpha": round(p[3], 3), "beta": round(p[4], 3), "gamma": round(p[5], 3),
        }
        entry["space_group"] = sg_name
        entry["peaks"] = peaks
        entry["peaks_source"] = (
            f"COD {args.cod_id} ({comp}, {len(struct)} 位点, "
            f"晶胞接管: β正交 → α四方, 修 21.35°→{main['two_theta']:.2f}°)")
        entry["peaks_version"] = PEAKS_VER
        doc["version"] = "0.5.3"
        note = ("|| 0.5.3 (库 0.5.3): Cristobalite 条目由 β 型正交晶胞 "
                "(COD 9017505, 主线 21.35°) 换为室温稳定 α 相 "
                f"(COD {args.cod_id}, P4_12_12, 主线 {main['two_theta']:.2f}°), "
                "修复 5-x 样品检索 MISS")
        if note not in doc.get("peaks_note", ""):
            doc["peaks_note"] = str(doc.get("peaks_note", "")) + note
        JSON_PATH.write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        log.append(f"[write] version → 0.5.3, peaks_version → {PEAKS_VER}")

    REPORT.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    print(f"[report] {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
