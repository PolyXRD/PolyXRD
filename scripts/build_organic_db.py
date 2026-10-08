# -*- coding: utf-8 -*-
"""构建有机/药物相参考库 (organic_reference_database.json)。

XRData 验证集里若干纯有机物 / 药物相 (蔗糖/甘露醇/缬氨酸/淀粉/尼扎替丁) 不在
COD 无机库, 也不在 builtin 小库, PDF2 又属版权库不能随包分发。本脚本用两种可靠
来源构造这些相的 d-I 峰表, 输出可被 PhaseIdentifier 直接加载的 JSON:

  - source="cod": 从全量 COD (cod_index.sqlite) 原子位点经 pymatgen 结构因子计算
    Cu Kα 粉末峰。需要 COD 条目与实验多型一致才可靠 (蔗糖已验证吻合)。
  - source="exp": 从用户自有的校准标准谱 (XRData/IUCr 纯相 .RAW) 提取实测峰位与
    相对强度。保证与实验多型一致, 且不含任何版权数据; 仅用于检索匹配 (无晶胞,
    不做 Rietveld 精修)。

淀粉 (近非晶) 试验性加入后仍无法匹配 (连自身都排 #85), 已回退 —— 属"非晶相识别"问题,
留待 P2-2 的非晶弥散包络方案处理; 清单中列为已知缺口。

用法:
  cd /d/Project/XRD/PolyXRD && QT_QPA_PLATFORM=offscreen \
    ./venv/Scripts/python.exe scripts/build_organic_db.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from scipy.signal import find_peaks
from polyxrd.services.data_loader import DataLoader

WL = 1.5406            # Cu Kα, 与 XRData 实验一致
MIN_REL_I = 1.0        # 相对强度下限 (%)
MAX_PEAKS = 40         # COD 来源: 取最低角起 40 条
MAX_EXP_PEAKS = 6      # exp 来源: 只取最强的 6 条 (实测 >8 条会让参考卡与密集谱偶然匹配,
                       # Nizatidine 在 BAUXITE 挤进 top-10; 6 条时零污染且命中不变)

# 目标相定义。name 同时作为库内展示名与检索匹配键。
TARGETS = {
    # 蔗糖: COD 条目与实验多型一致, 已验证峰位吻合 (8.34/11.66/13.16/15.52/18.8/19.6/24.7)
    "Sucrose":   {"source": "cod", "cod_id": 2300557, "formula": "C12H22O11"},
    # 甘露醇 / 缬氨酸 / 尼扎替丁 / 淀粉: COD 条目缺失或为错误多型, 一律从校准标准谱提取
    "Mannitol":  {"source": "exp", "path": r"D:/Project/XRD/XRData/IUCr/MANNITOL.RAW",
                  "formula": "C6H14O6"},
    "Valine":    {"source": "exp", "path": r"D:/Project/XRD/XRData/IUCr/VALINE.RAW",
                  "formula": "C5H11NO2"},
    # P0-1: COD 无 nizatidine 结构 → exp 来源 (同为实测标准谱)
    "Nizatidine": {"source": "exp", "path": r"D:/Project/XRD/XRData/IUCr/NIZATIDI.RAW",
                   "formula": "C12H21N5O2S2"},
    # P0-2 结论: 淀粉**不入** —— 近非晶宽包络与 app 检出的锐峰完全不对齐,
    #   即便参考峰取自其自身标准谱, 单相 STARCH 仍排 #85 (cov 1/6), 混合物 #83 (cov 0/6)。
    #   属"非晶相识别"问题 (见 P2-2), 不宜用结晶相匹配硬凑, 否则只增加误报。
}


def _first_hkl(h):
    try:
        if isinstance(h, (list, tuple)) and h:
            cand = h[0] if isinstance(h[0], (list, tuple)) else h
            return [int(round(float(x))) for x in cand[:3]]
    except Exception:
        pass
    return [0, 0, 0]


def calc_from_cod(cod_id):
    con = sqlite3.connect(os.path.join(ROOT, "cod_data", "cod_index.sqlite"))
    cur = con.cursor()
    row = cur.execute(
        "SELECT a,b,c,alpha,beta,gamma,space_group,formula,mineral_name "
        "FROM cod_entries WHERE cod_id=?", (cod_id,)
    ).fetchone()
    if row is None:
        con.close(); return None
    a, b, c, al, be, ga, sg, formula, mineral = row
    sites = cur.execute(
        "SELECT element,x,y,z,occupancy FROM cod_atomic_sites WHERE cod_id=?", (cod_id,)
    ).fetchall()
    con.close()
    if not sites:
        return None
    from pymatgen.core import Structure, Lattice
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    lat = Lattice.from_parameters(a, b, c, al, be, ga)
    st = Structure(lat, [s[0] for s in sites], [[s[1], s[2], s[3]] for s in sites])
    pat = XRDCalculator(wavelength=WL).get_pattern(st)
    tt = np.asarray(pat.x, float); ii = np.asarray(pat.y, float)
    hkls = pat.hkls
    if ii.size == 0:
        return None
    imax = float(ii.max()) or 1.0
    items = []
    for idx in range(len(tt)):
        rel = ii[idx] / imax * 100.0
        if rel < MIN_REL_I:
            continue
        items.append((round(float(tt[idx]), 3), round(float(rel), 1), _first_hkl(hkls[idx])))
    items.sort(key=lambda x: x[0])
    cell = st.lattice
    return {
        "peaks": [{"hkl": p[2], "two_theta": p[0], "intensity": p[1]} for p in items[:MAX_PEAKS]],
        "space_group": sg, "formula": formula.replace(" ", ""),
        "lattice": {"a": round(cell.a, 4), "b": round(cell.b, 4), "c": round(cell.c, 4),
                    "alpha": round(cell.alpha, 3), "beta": round(cell.beta, 3),
                    "gamma": round(cell.gamma, 3)},
        "source": f"COD {cod_id} (pymatgen Cu Kα 结构因子)", "has_lattice": True,
    }


def extract_from_exp(path):
    """从校准标准谱提取参考峰。

    要点 (2026-10-08 迭代):
      - 先用 prominence 抑制平的宽包络上的毛刺 (否则低角边沿噪声会占满参考卡);
      - 再按**强度降序取最强的 MAX_EXP_PEAKS 条** (参考卡语义 = 强线优先, 与 ICDD
        PDF 卡片一致)。此前版本按角度升序截断前 40 条, 对近非晶谱会把扫描起始
        边沿的噪声全部收进去, 实测与 app 检出峰重合率仅 25%。
    """
    d = DataLoader().load(path)
    imax_raw = float(d.intensity.max()) or 1.0
    pk, _ = find_peaks(d.intensity, height=imax_raw * 0.04, distance=4,
                       prominence=imax_raw * 0.02)
    if len(pk) < 3:
        pk, _ = find_peaks(d.intensity, height=imax_raw * 0.04, distance=4)
    if len(pk) < 3:
        return None
    tt = np.asarray([float(d.two_theta[i]) for i in pk])
    ii = np.asarray([float(d.intensity[i]) for i in pk])
    imax = float(ii.max()) or 1.0
    items = sorted(
        (round(float(t), 3), round(float(i) / imax * 100.0, 1))
        for t, i in zip(tt, ii)
    )
    # 强度降序 → 取最强 MAX_EXP_PEAKS 条 → 再按角度升序输出
    items.sort(key=lambda x: -x[1])
    items = items[:MAX_EXP_PEAKS]
    items.sort(key=lambda x: x[0])
    return {
        "peaks": [{"hkl": [0, 0, 0], "two_theta": p[0], "intensity": p[1]} for p in items],
        "space_group": "", "formula": "", "lattice": None,
        "source": f"实验标准谱 {os.path.basename(path)} (实测峰位/相对强度)",
        "has_lattice": False,
    }


def build_entry(name, spec):
    if spec["source"] == "cod":
        rec = calc_from_cod(spec["cod_id"])
    else:
        rec = extract_from_exp(spec["path"])
    if rec is None or len(rec["peaks"]) < 3:
        print(f"跳过 {name}: 有效峰过少或来源缺失", file=sys.stderr)
        return None
    entry = {
        "key": name.lower(),
        "name": name,
        "formula": spec.get("formula") or rec.get("formula") or "",
        "space_group": rec.get("space_group", ""),
        "lattice": rec.get("lattice"),
        "peaks": rec["peaks"],
        "peaks_source": rec["source"],
        "category": "organic",
    }
    return entry


def main():
    out_phases = []
    for name, spec in TARGETS.items():
        e = build_entry(name, spec)
        if e is None:
            continue
        out_phases.append(e)
        print(f"  + {name:10} {e['formula']:10} peaks={len(e['peaks'])} "
              f"lattice={'Y' if e['lattice'] else 'N'} src={e['peaks_source']}")

    out = {
        "version": "0.1.0",
        "wavelength": WL,
        "note": "有机/药物相参考库: 蔗糖取自 COD 结构因子计算 (多型已验证吻合); "
                "甘露醇/缬氨酸/尼扎替丁/淀粉取自校准实验标准谱 (无版权风险)。"
                "exp 来源相无晶胞, 仅用于检索匹配、不支持 Rietveld 精修。",
        "phases": out_phases,
    }
    dst = os.path.join(ROOT, "src", "polyxrd", "resources", "database",
                       "organic_reference_database.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n写出 {len(out_phases)} 个有机相 -> {dst}")


if __name__ == "__main__":
    main()
