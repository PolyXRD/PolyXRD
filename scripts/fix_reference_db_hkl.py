"""修复内置参考库的 hkl 与 2θ 自洽性 (v0.15.2 → v1.1.2 数据修复)
=================================================================

**病根 (与 v0.15.2 那次不同)**: `xrd_reference_database.json` 的 `peaks` 里
**2θ 与强度是对的** (v0.15.2 按真实 CIF 重算过, 与 PDF 卡一致), 但 **hkl 是错的**:
实测 Zincite 多个不同峰都标成 `(1,0,-1,-1)`, 还出现 `(0,0,0,0)` —— 显然是那次
重算时 pymatgen `pattern.hkls` 与峰表**下标错位 / 四指标转换写坏**。
后果: 任何依赖 hkl 的功能都不可用 —— 全晶胞精修 (W18) 会把峰位算飞;
将来的 `S·ZMV` 定量同样不可信。

**另一处更根本的 bug (同批修掉)**: `_calc_d_spacing_from_hkl` 的一般三斜公式
漏了归一化因子 `(1 − cos²α − cos²β − cos²γ + 2cosαcosβcosγ)` (= (V/abc)²),
导致**非正交晶胞全错** (六方 γ=120° 时因子 0.75 → d 偏大 √(4/3) 倍)。
该函数已在源码里修正 (rietveld_refiner.py), 本脚本按修正后的数学重新索引。

**修复策略**: 保留已验证的 2θ 与强度, 对每个峰在"由晶胞枚举出的允许反射表"里
按 2θ 最近邻匹配, 用匹配到的 hkl **替换**该峰的 hkl 与 2θ (取计算值, 使表自洽),
匹配不上 (超出容差) 的峰丢弃并记录; 同一 hkl 重复出现时保留最强的一条。

用法:
  venv/Scripts/python.exe scripts/fix_reference_db_hkl.py            # 试算, 只出报告
  venv/Scripts/python.exe scripts/fix_reference_db_hkl.py --write    # 落盘 (先备份)
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

JSON_PATH = ROOT / "src" / "polyxrd" / "resources" / "database" / "xrd_reference_database.json"
REPORT = ROOT / "_refdb_hkl_fix_report.txt"

WAVELENGTH = 1.5406
TTH_RANGE = (5.0, 90.0)
HKL_RANGE = 8          # h,k,l ∈ [-8, 8]
MATCH_TOL = 0.35       # 2θ 匹配容差 (度)
NEW_VERSION = "0.5.2"


def _d_spacing(a, b, c, al, be, ga, h, k, l) -> float:
    """修正后的通用三斜 1/d² (含归一化因子)。与 rietveld_refiner 保持同一数学。"""
    ar, br, gr = math.radians(al), math.radians(be), math.radians(ga)
    ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)
    sa, sb, sg = math.sin(ar), math.sin(br), math.sin(gr)
    inv = ((h * h * sa * sa) / (a * a)
           + (k * k * sb * sb) / (b * b)
           + (l * l * sg * sg) / (c * c)
           + (2 * k * l * (cb * cg - ca)) / (b * c)
           + (2 * h * l * (ca * cg - cb)) / (a * c)
           + (2 * h * k * (ca * cb - cg)) / (a * b))
    norm = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
    if norm <= 1e-12:
        return 0.0
    inv = inv / norm
    if inv <= 0:
        return 0.0
    return 1.0 / math.sqrt(inv)


def _two_theta(d: float) -> float:
    if d <= 0:
        return -1.0
    s = WAVELENGTH / (2.0 * d)
    if s >= 1.0:
        return -1.0
    return 2.0 * math.degrees(math.asin(s))


def _allowed_reflections(lat: dict) -> list[tuple[float, tuple[int, int, int]]]:
    """由晶胞枚举允许反射 (未施空间群消光, 由 2θ 匹配兜住)。"""
    a = float(lat["a"]); b = float(lat["b"]); c = float(lat["c"])
    al = float(lat.get("alpha", 90.0)); be = float(lat.get("beta", 90.0))
    ga = float(lat.get("gamma", 90.0))
    out = []
    for h in range(-HKL_RANGE, HKL_RANGE + 1):
        for k in range(-HKL_RANGE, HKL_RANGE + 1):
            for l in range(-HKL_RANGE, HKL_RANGE + 1):
                if h == 0 and k == 0 and l == 0:
                    continue
                t = _two_theta(_d_spacing(a, b, c, al, be, ga, h, k, l))
                if TTH_RANGE[0] <= t <= TTH_RANGE[1]:
                    out.append((t, (h, k, l)))
    out.sort()
    return out


def fix_phase(ph: dict) -> tuple[dict, dict]:
    """返回 (修好的 peak 列表, 统计)。"""
    lat = ph.get("lattice") or {}
    peaks = ph.get("peaks") or []
    stat = {"in": len(peaks), "renamed": 0, "kept": 0, "dropped": 0, "dedup": 0}
    if not peaks or not lat.get("a"):
        stat["dropped"] = len(peaks)
        return [], stat
    allowed = _allowed_reflections(lat)
    if not allowed:
        stat["dropped"] = len(peaks)
        return [], stat
    a = float(lat["a"]); b = float(lat["b"]); c = float(lat["c"])
    al = float(lat.get("alpha", 90.0)); be = float(lat.get("beta", 90.0))
    ga = float(lat.get("gamma", 90.0))
    fixed: list[dict] = []
    best_by_hkl: dict[tuple[int, int, int], dict] = {}
    for p in peaks:
        try:
            t_stored = float(p["two_theta"]); inten = float(p.get("intensity", 0.0))
        except (KeyError, TypeError, ValueError):
            stat["dropped"] += 1
            continue
        hkl_stored = p.get("hkl")
        # ① 先验证**原 hkl**: 2θ 对得上就保留原标记 (避免等价反射之间的无意义改名),
        #    只把 2θ 吸附到计算值使表严格自洽。
        t_calc = None
        hkl = None
        if hkl_stored and len(hkl_stored) in (3, 4):
            h, k, l = ((hkl_stored[0], hkl_stored[1], hkl_stored[3])
                       if len(hkl_stored) == 4
                       else (hkl_stored[0], hkl_stored[1], hkl_stored[2]))
            t_try = _two_theta(_d_spacing(a, b, c, al, be, ga,
                                          int(h), int(k), int(l)))
            if t_try > 0 and abs(t_try - t_stored) <= MATCH_TOL:
                t_calc, hkl = t_try, (int(h), int(k), int(l))
        if hkl is None:
            # ② 原 hkl 不可信 → 在允许反射表里按 2θ 最近邻重索引
            best = None; best_d = 1e9
            for t_allow, hkl_allow in allowed:
                d = abs(t_allow - t_stored)
                if d < best_d:
                    best_d, best = d, (t_allow, hkl_allow)
                elif t_allow - t_stored > MATCH_TOL and best_d < 1e8:
                    break   # 已越过最近邻 (allowed 按 2θ 升序)
            if best is None or best_d > MATCH_TOL:
                stat["dropped"] += 1
                continue
            t_calc, hkl = best
            stat["renamed"] += 1
        rec = {"hkl": [int(hkl[0]), int(hkl[1]), int(hkl[2])],
               "two_theta": round(float(t_calc), 3),
               "intensity": round(inten, 2)}
        prev = best_by_hkl.get(hkl)
        if prev is not None:
            stat["dedup"] += 1
            if rec["intensity"] <= prev["intensity"]:
                continue
        best_by_hkl[hkl] = rec
    fixed = sorted(best_by_hkl.values(), key=lambda r: r["two_theta"])
    if fixed:
        imax = max(r["intensity"] for r in fixed)
        if imax > 0:
            for r in fixed:
                r["intensity"] = round(r["intensity"] * 100.0 / imax, 2)
    stat["kept"] = len(fixed)
    return fixed, stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="落盘 (会先备份)")
    args = ap.parse_args()

    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    phases = doc.get("phases") or []
    lines: list[str] = []
    tot = {"in": 0, "renamed": 0, "kept": 0, "dropped": 0, "dedup": 0}
    bad_before = 0
    for ph in phases:
        fixed, st = fix_phase(ph)
        for k in tot:
            tot[k] += st[k]
        if st["renamed"] > 0 or st["dropped"] > 0:
            bad_before += 1
            lines.append(f"{ph.get('name','?'):24s} in={st['in']:3d} "
                         f"renamed={st['renamed']:3d} dedup={st['dedup']:3d} "
                         f"kept={st['kept']:3d} dropped={st['dropped']:3d}")
        if args.write:
            ph["peaks"] = fixed
            ph["peaks_version"] = NEW_VERSION + "-hkl-consistent"
    lines.append("")
    lines.append(f"合计: 输入 {tot['in']} → 保留 {tot['kept']} "
                 f"(改名 {tot['renamed']}, 去重 {tot['dedup']}, 丢弃 {tot['dropped']}); "
                 f"受影响条目 {bad_before}/{len(phases)}")

    if args.write:
        bak = JSON_PATH.with_suffix(".json.bak-" + date.today().isoformat())
        if not bak.exists():
            shutil.copy2(JSON_PATH, bak)
        doc["version"] = NEW_VERSION
        JSON_PATH.write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        lines.append(f"[write] version → {NEW_VERSION}; 备份: {bak.name}")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[-14:]))
    print(f"[report] {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
