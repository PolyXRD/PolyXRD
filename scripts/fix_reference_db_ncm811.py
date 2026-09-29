"""修复内置参考库 NCM 811 条目 (v0.15.2 → 0.5.3 数据修复, 与 Cristobalite 同批)
==================================================================================

**病根**: `NCM811` 条目挂在**坏管道超胞**上 (P2_1/c, a=12.83/b=14.91/c=38.10,
峰表 5420 条 → v0.15.2 截断到 400, 治标不治本)。条目主线 18.443° 与真实
NCM 811 (003) ≈18.8° 差 0.32° > 0.2° 容差, 还混入 12–14° 一批真实结构没有的
幻影线; 强线 (101)≈36.7°/(012)≈38.4° 全部缺位。
实测后果 (S19 基准): 单相试样 1-2 检索 top12 直接 MISS (组合退化为 Nickel),
且 5-2b/2-1 等样品被其密集幻影线"覆盖毯"误召回 (多余相 NCM 811)。

**修复 (与 fix_reference_db_cristobalite.py 同手法)**: 取本地 COD 层状
R-3m 结构 (默认 1520789: Co0.1 Li1.03 Mn0.1 Ni0.77 O2, a=2.8645/c=14.161,
成分即 NCM 811), CifParser 对称展开 → XRDCalculator (Cu Kα 1.5406) 重算
峰表, 接管条目 lattice / space_group。重算主线 (003)@18.78/(101)@36.75
与 1-2 实测 18.76/36.7 吻合。

用法:
  venv/Scripts/python.exe scripts/fix_reference_db_ncm811.py             # 试算
  venv/Scripts/python.exe scripts/fix_reference_db_ncm811.py --write     # 落盘 (先备份)
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
REPORT = ROOT / "_refdb_ncm811_fix_report.txt"

WAVELENGTH = 1.5406
TTH_RANGE = (5.0, 90.0)
MIN_INTENSITY = 0.4
PEAKS_VER = "0.5.3-ncm811-fix"
DEFAULT_COD_ID = 1520789   # R-3m 层状, Co0.1 Li Mn0.1 Ni0.8 O2 型, a=2.8645/c=14.161
TARGET_KEY = "NCM811"


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
    """六方/三方 (gamma≈120) 沿用库内 4 指标 hkil 记法 (pymatgen 已直接给出)。"""
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
            if len(raw) >= 4:
                hkl = [int(v) for v in raw[:4]]
            elif len(raw) >= 3:
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
    els = {el.symbol for el in struct.composition.elements}
    if not els <= {"Li", "Ni", "Co", "Mn", "O"} or "Ni" not in els:
        raise SystemExit(f"元素集合不符层状 NCM: {sorted(els)}, 拒绝落盘")

    peaks = _peaks_from_struct(struct)
    if not peaks:
        raise SystemExit("峰表重算为空")
    top3 = sorted(peaks, key=lambda r: -r["intensity"])[:3]
    main = top3[0]
    log.append(f"新峰表: {len(peaks)} 峰; 最强线 {tuple(main['hkl'])} "
               f"@ {main['two_theta']:.3f}° (I=100)")
    for r in top3[1:]:
        log.append(f"  次强: {tuple(r['hkl'])} @ {r['two_theta']:.3f}° I={r['intensity']:.2f}")
    if abs(main["two_theta"] - 18.8) > 0.5:
        raise SystemExit(f"最强线 {main['two_theta']:.2f}° 偏离 NCM (003) 参考值 "
                         f"18.8° 过远, 疑似拿错结构, 拒绝落盘")

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
            f"晶胞接管: P2_1/c 坏超胞 → R-3m 层状, 修 18.44°→{main['two_theta']:.2f}°)")
        entry["peaks_version"] = PEAKS_VER
        doc["version"] = "0.5.3"
        note = ("|| 0.5.3 (库 0.5.3): NCM 811 条目由 P2_1/c 坏超胞 (5420 峰→截断 400, "
                "主线 18.44° 错位) 换为层状 R-3m 结构 "
                f"(COD {args.cod_id}, 主线 {main['two_theta']:.2f}°), "
                "修复 1-2 检索 MISS 与幻影线覆盖毯误召回")
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
