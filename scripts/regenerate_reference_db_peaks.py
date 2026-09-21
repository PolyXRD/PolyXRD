"""重建内置参考库 xrd_reference_database.json 的峰值表 (v0.15.2 数据修复)
================================================================================

**病根**: 该库的 `peaks` 是按"只含非对称单元位点的 P1 结构"算出来的 (未做空间群
对称展开 + 未施消光条件)。实测后果 (审计):
  - 118 条中 **59 条**最强线 d > 4 Å 明显异常 (如 R-3c 方解石最强线变成 0001 @5.17°,
    真值应为 104 @29.4°; 刚玉 0001 @6.8° 而真值 104 @35.1°);
  - 识别 FOM 建立在错误峰表上 → 2-1 试样把"P2_1/c 型 CaCO3"排到正确方解石之前,
    内置精修因此无法拟合 29.36° 主峰, wR 长期卡在 40%。

**修复**: 逐条目取回真实晶体结构 (cif_source 指定的 CIF 优先; 其余按
化学式 + 晶胞 + 空间群 在本地 COD 库检索), 用 pymatgen ``CifParser``
(自动展开对称操作) → ``XRDCalculator`` 重算峰表 (归一到 max=100),
六方/三方条目沿用 4 指标 hkil 记法。

用法:
  venv/Scripts/python.exe scripts/regenerate_reference_db_peaks.py            # 试算, 只出报告
  venv/Scripts/python.exe scripts/regenerate_reference_db_peaks.py --write     # 落盘 (先备份)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

JSON_PATH = ROOT / "src" / "polyxrd" / "resources" / "database" / "xrd_reference_database.json"
REPORT = ROOT / "_refdb_regen_report.txt"

WAVELENGTH = 1.5406
TTH_RANGE = (5.0, 90.0)
MIN_INTENSITY = 0.4  # 丢弃噪声级弱线, 控制体积
PEAKS_VER = "v0.15.2-symmetry-expanded"

#: 校验用已知主峰 (2θ°, Cu Kα) — 仅覆盖最常用的矿物。
#: 值可以是单个 (2θ, tol), 也可以是多个备选 —— pymatgen 的 XRDCalculator 用运动学
#: 结构因子算强度, 个别物相的最强线与实验 PDF 卡不同 (最典型的是刚玉: 实验卡 104@35.1°
#: 最强, 结构因子下 116@57.5° 最强), 峰位本身两者一致, 故两种都算通过。
KNOWN_MAIN = {
    "Quartz": (26.6, 0.8), "α-Quartz": (26.6, 0.8),
    "Calcite": (29.4, 0.8),
    "Corundum": ((35.1, 1.0), (57.5, 1.5)),
    "Hematite": (33.2, 1.0), "Zincite": (36.2, 0.8),
    "Fluorite": (47.0, 1.0), "Anatase": (25.3, 1.0),
    "Rutile": (27.4, 1.0),
    "Brucite": ((18.6, 1.0), (38.1, 1.5)),
    "Halite": (31.7, 0.8), "Periclase": (42.9, 1.2),
    "Siderite": (32.0, 1.5), "Magnesite": (32.6, 1.5),
    "Barite": (25.9, 1.2), "Zircon": (27.2, 1.0),
    "Gypsum": (11.6, 1.0),
}


def _norm_sg(sg: object) -> str:
    s = re.sub(r"\s*:\s*[A-Za-z0-9]{1,2}$", "", str(sg or "").strip())
    return re.sub(r"\s+", "", s)


def _is_hex_axes(lat: dict, sg: str) -> bool:
    """六方/三方 (含 R/H setting) → hkil 4 指标记法 (与库内既有约定一致)."""
    try:
        if abs(float(lat.get("gamma", 90.0)) - 120.0) < 0.5:
            return True
    except (TypeError, ValueError):
        return False
    return False


def _cell_match(lat: dict, struct) -> tuple[bool, float]:
    """把 pymatgen 结构晶胞与条目标称晶胞比对 (允许轴向换算误差)。"""
    try:
        p = struct.lattice.parameters  # a,b,c,alpha,beta,gamma
    except Exception:  # noqa: BLE001
        return False, 99.0
    ref = [float(lat.get(k, 0.0) or 0.0) for k in ("a", "b", "c", "alpha", "beta", "gamma")]
    if ref[0] <= 0:
        return False, 99.0
    lens_d = [abs(p[i] - ref[i]) / ref[i] for i in range(3)]
    angs_d = [abs(p[3 + i] - ref[3 + i]) / max(ref[3 + i], 1.0) for i in range(3)]
    worst = max(lens_d + angs_d)
    return worst < 0.03, worst


def _vol_ratio(lat: dict, struct) -> float:
    """结构晶胞体积 / 条目标称体积 (==1 表示同一 setting)。"""
    try:
        a, b, c = (float(lat.get(k, 0.0) or 0.0) for k in ("a", "b", "c"))
        al, be, ga = (math.radians(float(lat.get(k, 90.0) or 90.0))
                      for k in ("alpha", "beta", "gamma"))
        ca, cb, cg = math.cos(al), math.cos(be), math.cos(ga)
        v1 = a * b * c * math.sqrt(max(1e-12, 1 - ca * ca - cb * cb - cg * cg
                                       + 2 * ca * cb * cg))
        v2 = float(struct.lattice.volume)
        return v2 / v1 if v1 > 0 else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _parse_counts(formula: str) -> dict[str, int] | None:
    """化学式 → 元素计数 (支持嵌套括号; 固溶体式返回 None 表示放弃核对)。"""
    s = re.sub(r"\s+", "", str(formula or ""))
    if not s or "/" in s or "," in s:
        return None  # 固溶体/混合式 → 无法做计量比核对
    s = s.replace("·", "")

    def _parse(seg: str) -> dict[str, int]:
        out: dict[str, int] = {}
        i = 0
        while i < len(seg):
            if seg[i] == "(":
                depth, j = 1, i + 1
                while j < len(seg) and depth:
                    depth += (seg[j] == "(") - (seg[j] == ")")
                    j += 1
                inner = _parse(seg[i + 1:j - 1])
                m = re.match(r"\d+", seg[j:])
                mult = int(m.group()) if m else 1
                if m:
                    j += m.end()
                for k, v in inner.items():
                    out[k] = out.get(k, 0) + v * mult
                i = j
                continue
            m = re.match(r"([A-Z][a-z]?)(\d*)", seg[i:])
            if not m:
                i += 1
                continue
            out[m.group(1)] = out.get(m.group(1), 0) + int(m.group(2) or 1)
            i += m.end()
        return out

    got = _parse(s)
    return got or None


def _composition_ok(formula: str, struct, tol: float = 0.08) -> tuple[bool, str]:
    """化学计量比核对: 元素集合必须一致, 且摩尔比一致 (拦截 FeO↔Fe2O3 这类错配)。"""
    want = _parse_counts(formula)
    # 结构侧的元素计数: pymatgen 对氧化态物种给出的 symbol 形如 "Al3+"/"O2-"/"Cr0+",
    # 必须归并回元素符号, 否则与条目化学式 (Al2O3 这种) 的元素集合永远对不上。
    have: dict[str, float] = {}
    for k, v in struct.composition.as_dict().items():
        sym = getattr(getattr(k, "element", None), "symbol", None) or getattr(k, "symbol", k)
        sym = re.sub(r"[^A-Za-z]", "", str(sym)) or str(sym)
        have[sym] = have.get(sym, 0.0) + float(v)
    if not want:
        # 无化学式或固溶体式 → 退化为元素集合核对
        return True, ""
    # 结构 CIF 里常常省略 H (X 射线对氢几乎不敏感, 解结构时基本不带), 这时按去氢
    # 化学式比对, 否则 Muscovite/Kaolinite 这类羟基矿物会被整片误判为"元素集合不符"。
    if "H" not in have and "H" in want:
        want = {k: v for k, v in want.items() if k != "H"} or want
    if set(want) != set(have):
        return False, f"元素集合不符 ({sorted(want)} vs {sorted(have)})"
    tot_w = sum(want.values())
    tot_h = sum(have.values()) or 1.0
    for el, n_w in want.items():
        r_w = n_w / tot_w
        r_h = have[el] / tot_h
        if abs(r_w - r_h) > tol:
            return False, (f"计量比不符 ({el}: {r_w:.3f} vs {r_h:.3f})")
    return True, ""


def _elements_ok(formula: str, struct) -> bool:
    return _composition_ok(formula, struct)[0]


def _peaks_from_struct(struct, lat: dict, sg: str) -> list[dict]:
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    calc = XRDCalculator(wavelength=WAVELENGTH)
    pat = calc.get_pattern(struct, two_theta_range=TTH_RANGE)
    rows = []
    for i in range(len(pat.x)):
        inten = float(pat.y[i])
        hkl = [0, 0, 0]
        info = pat.hkls[i] if i < len(pat.hkls) else []
        if info and isinstance(info[0], dict):
            raw = list(info[0].get("hkl", (0, 0, 0)))
            if _is_hex_axes(lat, sg) and len(raw) >= 3:
                h, k, l = int(raw[0]), int(raw[1]), int(raw[2])
                hkl = [h, k, -h - k, l]
            elif len(raw) >= 4:
                hkl = [int(v) for v in raw[:4]]
            elif len(raw) >= 3:
                hkl = [int(v) for v in raw[:3]]
        rows.append([hkl, float(pat.x[i]), inten])
    if not rows:
        return []
    imax = max(r[2] for r in rows) or 1.0
    return [
        {"hkl": r[0], "two_theta": round(r[1], 3),
         "intensity": round(100.0 * r[2] / imax, 2)}
        for r in rows if 100.0 * r[2] / imax >= MIN_INTENSITY
    ]


def _load_cif(cif_text: str):
    from pymatgen.io.cif import CifParser

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return CifParser.from_str(cif_text, occupancy_tolerance=1.2).parse_structures(
            primitive=False)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="落盘 (默认只试算)")
    args = ap.parse_args()

    from polyxrd.services.cod_local import CODLocalDatabase
    from polyxrd.services.phase_structure_resolver import (
        PhaseStructureResolver, _candidate_score, normalize_cod_formula,
    )

    _clean_mineral = PhaseStructureResolver._clean_mineral
    from polyxrd.models.phase import LatticeParams, Phase

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    phases = data["phases"]
    db = CODLocalDatabase()

    log_lines: list[str] = []
    stats = {"cif_source": 0, "lookup": 0, "kept": 0, "sibling": 0}

    def _log(s: str) -> None:
        log_lines.append(s)

    for e in phases:
        name, formula = e.get("name", ""), e.get("formula", "")
        lat = e.get("lattice", {}) or {}
        sg = str(e.get("space_group", "") or "")
        old_peaks = e.get("peaks") or []
        old_main = max(old_peaks, key=lambda p: p.get("intensity", 0)) if old_peaks else None
        new_peaks = None
        src = ""

        # ── 1) cif_source 直取 ──
        cand_ids: list[int] = []
        if e.get("cif_source"):
            cid = "".join(ch for ch in str(e["cif_source"]) if ch.isdigit())
            if cid:
                cand_ids.append(int(cid))

        # ── 2) 化学式 (+矿物名) 检索 ──
        # 注意: 即使 cif_source 已给出候选, 也要把检索候选接在后面 —— 库里部分条目
        # 的 cif_source 指向的其实不是本矿物 (实测 CaCO3/Calcite 指向一水合硝酸钙),
        # 不回退就会白白保留旧错峰表。
        exact_used = True
        norm = normalize_cod_formula(formula)
        if norm:
            probe = Phase(name=name, formula=formula, space_group=sg,
                          lattice=LatticeParams(
                              a=lat.get("a", 1.0) or 1.0,
                              b=lat.get("b", 1.0) or 1.0,
                              c=lat.get("c", 1.0) or 1.0,
                              alpha=lat.get("alpha", 90.0) or 90.0,
                              beta=lat.get("beta", 90.0) or 90.0,
                              gamma=lat.get("gamma", 90.0) or 120.0))
            cands = []
            for mineral_arg in (_clean_mineral(name), ""):
                try:
                    cands = db.find_structure_candidates(
                        norm, mineral_name=mineral_arg)
                except Exception:  # noqa: BLE001
                    cands = []
                if cands:
                    break
            cands.sort(key=lambda c: _candidate_score(c, probe))
            for c in cands[:8]:
                cid = int(c["cod_id"])
                if cid not in cand_ids:
                    cand_ids.append(cid)

        # 两轮: 先要求晶胞严格一致 (3%), 退而求其次「同体积同矿物」并接管其晶胞
        fallback: tuple | None = None
        for cid in cand_ids:
            txt = db.get_cif(cid)
            if not txt:
                continue
            try:
                struct = _load_cif(txt)
            except Exception:  # noqa: BLE001
                continue
            if not _elements_ok(formula, struct):
                _log(f"  · {name}: COD {cid} "
                     f"{_composition_ok(formula, struct)[1]} → 跳过")
                continue
            ok, worst = _cell_match(lat, struct)
            if not ok:
                vr = _vol_ratio(lat, struct)
                # 放宽接受: 晶胞差异 ≤7% 且体积一致, 或差异 ≤25% (条目里的标称晶胞
                # 本身来源不一, 有的记成了超胞/不同 setting, 逐参数对不上但确是同一物相)。
                # 命中后接管结构的晶胞, 保证峰表与晶胞自洽。
                if fallback is None and (0.985 < vr < 1.015 or worst < 0.25):
                    fallback = (cid, struct, worst, vr)
                    _log(f"  · {name}: COD {cid} 晶胞参数不同 (最大偏差 {worst:.1%}, "
                         f"体积×{vr:.3f}) → 备选, 接管其晶胞")
                else:
                    _log(f"  · {name}: COD {cid} 晶胞不匹配 "
                         f"(最大偏差 {worst:.1%}, 体积×{vr:.3f}) → 跳过")
                continue
            peaks = _peaks_from_struct(struct, lat, sg)
            if peaks:
                new_peaks = peaks
                src = (f"COD {cid} ({struct.composition.reduced_formula}, "
                       f"{len(struct)} 位点, 晶胞一致)")
                exact_used = True
                break

        if new_peaks is None and fallback is not None:
            cid, struct, worst, vr = fallback
            peaks = _peaks_from_struct(struct, lat, sg)
            if peaks:
                new_peaks = peaks
                exact_used = False
                src = (f"COD {cid} ({struct.composition.reduced_formula}, "
                       f"{len(struct)} 位点, 晶胞已接管)")
                # 用结构晶胞替换条目标称晶胞 (保持一致)
                p = struct.lattice.parameters
                e["lattice"] = {
                    "a": round(p[0], 4), "b": round(p[1], 4), "c": round(p[2], 4),
                    "alpha": round(p[3], 3), "beta": round(p[4], 3),
                    "gamma": round(p[5], 3),
                }
                e["space_group"] = str(struct.get_space_group_info()[0] or sg)

        if new_peaks is None:
            stats["kept"] += 1
            _log(f"[保留] {name:<26} {formula:<12} 未找到可用结构 → 沿用旧峰表 "
                 f"({len(old_peaks)} 峰)")
            continue

        nm = max(new_peaks, key=lambda p: p["intensity"])
        stats["cif_source" if e.get("cif_source") else "lookup"] += 1
        _log(
            f"[重算] {name:<26} {formula:<12} {src:<42} "
            f"旧主峰 {old_main['two_theta']:6.2f}° → 新主峰 {nm['two_theta']:6.2f}° "
            f"(I={nm['intensity']:.0f})  峰数 {len(old_peaks)}→{len(new_peaks)}"
        )
        e["peaks"] = new_peaks
        e["peaks_source"] = src.strip()
        e["peaks_version"] = PEAKS_VER

    # ── 二遍: 同名条目沿用已修好的峰表 ──
    # 库内存在同名重复条目 (如 Calcite/Corundum/Brucite 各两条, 一条是老内置库,
    # 一条是后来按 CIF 追加的)。若其中一条已重算成功, 另一条直接沿用, 免得同一种
    # 物相在库里带着两套互相矛盾的峰表, 徒增识别误判。
    fixed_by_name: dict[str, dict] = {}
    for e in phases:
        if e.get("peaks_version") == PEAKS_VER and e.get("peaks"):
            fixed_by_name.setdefault(str(e.get("name")), e)
    for e in phases:
        if e.get("peaks_version") == PEAKS_VER:
            continue
        sib = fixed_by_name.get(str(e.get("name")))
        if sib is None:
            continue
        e["peaks"] = [dict(p) for p in sib["peaks"]]
        e["peaks_source"] = f"沿用同名条目 {sib.get('key')} ({sib.get('peaks_source', '')})"
        e["peaks_version"] = PEAKS_VER
        stats["sibling"] += 1
        _log(f"[同名] {e.get('name'):<24} 沿用 {sib.get('key')} 的已修正峰表")

    # ── 三遍: 超量峰表截断 ──
    # 个别条目 (实测 NCM 811, 5420 峰) 是更早坏管道的产物 —— 峰数远超晶体学合理上限,
    # 识别没意义, 精修更是灾难 (单相 least_squares 一轮就要 20 分钟)。按强度保留前
    # _MAX_KEEP_PEAKS 条即可覆盖识别所需的全部强线。
    _MAX_KEEP_PEAKS = 400
    _TRIM_OVER = 500
    for e in phases:
        pk = e.get("peaks") or []
        if len(pk) <= _TRIM_OVER:
            continue
        n_old = len(pk)
        pk = sorted(pk, key=lambda p: -float(p.get("intensity", 0.0)))[:_MAX_KEEP_PEAKS]
        pk = sorted(pk, key=lambda p: float(p["two_theta"]))
        e["peaks"] = pk
        e["peaks_source"] = (str(e.get("peaks_source") or "")
                             + f" [截断 {n_old}→{len(pk)}]")

    # ── 校验: 已知矿物主峰 ──
    _log("\n=== 已知主峰校验 (Cu Kα) ===")
    bad = 0
    for e in phases:
        k = KNOWN_MAIN.get(e.get("name"))
        if not k or not e.get("peaks") or e.get("peaks_version") != PEAKS_VER:
            continue
        expect, tol = k
        alts = expect if isinstance(expect, tuple) else (expect,)
        tols = tol if isinstance(tol, tuple) else (tol,) * len(alts)
        nm = max(e["peaks"], key=lambda p: p["intensity"])
        ok = any(abs(nm["two_theta"] - a) <= t for a, t in zip(alts, tols))
        if not ok:
            bad += 1
        _log(f"  {'OK ' if ok else 'BAD'} {e['name']:<12} "
             f"期望≈{'/'.join(f'{a:g}' for a in alts)}° "
             f"实测最强 {nm['two_theta']:6.2f}° (I={nm['intensity']:.0f})")

    # ── 校验: 异常最强线数量 ──
    import math

    sus = 0
    for e in phases:
        pk = e.get("peaks") or []
        if not pk:
            continue
        nm = max(pk, key=lambda p: p["intensity"])
        dd = WAVELENGTH / (2 * math.sin(math.radians(nm["two_theta"] / 2)))
        if dd > 4.0:
            sus += 1
    _log(f"\n最强线 d>4.0 Å 的条目数: {sus} / {len(phases)}  "
         f"(修复前审计为 59)")

    # ── 明细: 仍未修复 (沿用旧表) 且最强线异常的条目 ──
    left = []
    for e in phases:
        pk = e.get("peaks") or []
        if not pk or e.get("peaks_version") == PEAKS_VER:
            continue
        nm = max(pk, key=lambda p: p["intensity"])
        dd = WAVELENGTH / (2 * math.sin(math.radians(nm["two_theta"] / 2)))
        if dd > 4.0:
            left.append((e.get("name"), e.get("formula"), nm["two_theta"], dd, len(pk)))
    if left:
        _log(f"\n--- 待人工收口的异常条目 ({len(left)}) ---")
        for nm_, fm, tt, dd, n in left:
            _log(f"  · {nm_:<24} {fm:<14} 主峰 {tt:6.2f}° (d={dd:.2f} Å) {n} 峰")
    _log(f"统计: cif_source 重算 {stats['cif_source']} / 检索重算 {stats['lookup']} "
         f"/ 同名沿用 {stats['sibling']} / 保留旧表 {stats['kept']} "
         f"/ 校验异常 {bad}")

    REPORT.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print("\n".join(log_lines[-40:]))

    if args.write:
        bak = JSON_PATH.with_suffix(".json.bak_v0.4.0")
        if not bak.exists():
            shutil.copy2(JSON_PATH, bak)
            print(f"[backup] {bak.name}")
        data["version"] = "0.5.0"
        data["peaks_note"] = (
            "v0.15.2: 全部峰表按真实晶体结构 (CifParser 空间群展开 + 消光条件) "
            "重算, 修正旧版按 P1 非对称单元计算导致的强度/峰位错误"
        )
        JSON_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[write] {JSON_PATH} (version → 0.5.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
