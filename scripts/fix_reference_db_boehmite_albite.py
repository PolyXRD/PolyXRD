"""修复内置参考库 Boehmite / Albite 条目 (0.5.3 第二批)
====================================================================

**Boehmite 病根**: 条目挂在 COD 1533936 (**Al10.64O16**, I4_1/amd) 上 ——
根本不是 γ-AlOOH (正确空间群 C m c m), 库内主线 66.65° 在真实薄水铝石
谱里不存在, 真实主线 (020)@14.43° 缺位 → 7-1 (Boehmite 14.93 wt%)
检索 top20 MISS。
**修法**: 换 COD 9012250 (AlHO2, C m c m, a=2.869/b=12.265/c=3.715),
重算 (020)@14.432(100)/(021)@28.06(51)/(130)@38.30(44),
与 7-1 实测 14.48/38.37 吻合。

**Albite 病根**: 条目挂在 Pnnm 正交晶胞 (a=8.24/b=8.68/c=4.84) 且
peaks_source 为空 —— 不是标准低钠长石 (三斜 P-1, a≈8.15/b≈12.79/c≈7.16,
β≈116.5), 库内 (21.55, I=80) 线在实测中落空 → 7-2 Albite 排 17 (top12 外)。
**修法**: 换 COD 9000525 (AlNaO8Si3, C -1 ≡ P-1, a=8.153/b=12.869/c=7.107),
重算 (002)@28.10(100)/(2,0,-1)@22.01(99)/(-1,3,0)@23.71(47),
与 7-2 实测 27.53/27.82/22.01/23.63 吻合。

用法:
  venv/Scripts/python.exe scripts/fix_reference_db_boehmite_albite.py             # 试算
  venv/Scripts/python.exe scripts/fix_reference_db_boehmite_albite.py --write     # 落盘 (先备份)
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
REPORT = ROOT / "_refdb_round2_fix_report.txt"

WAVELENGTH = 1.5406
TTH_RANGE = (5.0, 90.0)
MIN_INTENSITY = 0.4
PEAKS_VER = "0.5.3-round2-fix"

# key → (默认 COD, 元素白名单, 主线参考值, 主线容差)
TARGETS = {
    "Boehmite": (9012250, {"Al", "O", "H"}, 14.43, 0.5),
    "Albite": (9000525, {"Na", "Al", "Si", "O"}, 28.10, 0.5),
}


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
    args = ap.parse_args()

    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    log: list[str] = []
    changed = 0
    for key, (cod_id, els_allowed, ref_main, main_tol) in TARGETS.items():
        entry = next((e for e in doc["phases"] if e.get("key") == key), None)
        if entry is None:
            log.append(f"[跳过] 条目 {key} 不存在")
            continue
        struct = _load_struct(cod_id)
        p = struct.lattice.parameters
        sg_name = str(struct.get_space_group_info()[0])
        comp = struct.composition.reduced_formula
        els = {el.symbol for el in struct.composition.elements}
        if not els <= els_allowed:
            raise SystemExit(f"{key}: 元素集合不符 {sorted(els)} ⊄ {sorted(els_allowed)}")
        peaks = _peaks_from_struct(struct)
        if not peaks:
            raise SystemExit(f"{key}: 峰表重算为空")
        main = max(peaks, key=lambda r: r["intensity"])
        if abs(main["two_theta"] - ref_main) > main_tol:
            raise SystemExit(f"{key}: 主线 {main['two_theta']:.2f}° 偏离参考 "
                             f"{ref_main}° 过远, 拒绝落盘")
        old_main = max(entry["peaks"], key=lambda q: q["intensity"]) if entry.get("peaks") else None
        log.append(
            f"[重算] {key}: COD {cod_id} ({comp}, {sg_name}, {len(struct)} 位点, "
            f"a={p[0]:.4f} b={p[1]:.4f} c={p[2]:.4f}) 主线 "
            f"{old_main['two_theta']:.3f}°→{main['two_theta']:.3f}°, "
            f"峰数 {len(entry['peaks'])}→{len(peaks)}")
        if args.write:
            entry["lattice"] = {
                "a": round(p[0], 4), "b": round(p[1], 4), "c": round(p[2], 4),
                "alpha": round(p[3], 3), "beta": round(p[4], 3),
                "gamma": round(p[5], 3),
            }
            entry["space_group"] = sg_name
            entry["peaks"] = peaks
            entry["peaks_source"] = (
                f"COD {cod_id} ({comp}, {len(struct)} 位点, 晶胞接管)")
            entry["peaks_version"] = PEAKS_VER
            changed += 1

    if args.write:
        if changed:
            bak = JSON_PATH.with_suffix(".json.bak-" + date.today().isoformat())
            if not bak.exists():
                shutil.copy2(JSON_PATH, bak)
                log.append(f"[backup] {bak.name}")
            note = ("|| 0.5.3 (第二批): Boehmite 由 Al10.64O16 (I4_1/amd, 错相) 换为 "
                    "γ-AlOOH (COD 9012250, C m c m, 主线 14.43°); "
                    "Albite 由 Pnnm 错晶胞换为三斜低钠长石 (COD 9000525, C -1, 主线 28.10°)")
            if note not in doc.get("peaks_note", ""):
                doc["peaks_note"] = str(doc.get("peaks_note", "")) + note
            JSON_PATH.write_text(
                json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            log.append(f"[write] {changed} 条目已更新 (peaks_version → {PEAKS_VER})")
    else:
        log.append("[dry-run] 未落盘 (加 --write 生效)")

    REPORT.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    print(f"[report] {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
