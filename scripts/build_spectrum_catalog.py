# -*- coding: utf-8 -*-
"""谱图数据集目录生成器 (spectrum catalog)。

扫描 D:/Project/XRD/XRData 与 D:/Project/XRD/test_xrd 两个数据集, 结合内置真值表
(IUCr 物相说明 / csuHJW 文件名真值 / test_xrd 物相结果+wt%.txt) 产出:

  - tests/spectrum_catalog.json  机器可读目录 (后续 agent 直接加载)
  - tests/spectrum_catalog.md    人类可读清单 (样品/真值/格式/坑点/验收入口)

设计: 真值在脚本内显式维护 (可审阅), 磁盘文件每次运行实时扫描 (自动发现新增/缺失)。
重跑: cd /d/Project/XRD/PolyXRD && ./venv/Scripts/python.exe scripts/build_spectrum_catalog.py
"""
from __future__ import annotations
import json, os, re, sys, datetime

XRDATA = r"D:/Project/XRD/XRData"
TESTXRD = r"D:/Project/XRD/test_xrd"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, "tests", "spectrum_catalog.json")
OUT_MD = os.path.join(ROOT, "tests", "spectrum_catalog.md")

SPECTRUM_EXTS = {".raw", ".RAW", ".mdi", ".txt", ".TXT", ".xy", ".dat", ".PRN"}
NON_SPECTRUM_EXTS = {".pdf", ".sav", ".rpt", ".abc", ".is0", ".is1", ".is2",
                     ".mtd", ".par", ".lst", ".gss", ".cif", ".apf", ".spf",
                     ".XLS", ".png", ".gif", ".gz"}


def scan(root):
    """root 下全部文件: relpath -> size 字节。目录不存在返回空。"""
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace("\\", "/")
            try:
                out[rel] = os.path.getsize(fp)
            except OSError:
                out[rel] = -1
    return out


def fmt_size(n):
    if n < 0:
        return "?"
    return f"{n/1024:.0f}K" if n < 1024 * 1024 else f"{n/1024/1024:.1f}M"


# ============================================================
# 真值表 (来源: XRData/IUCr/IUCr物相说明.txt, wt% 为 weighed 值)
# ============================================================
IUCR_TRUTH = {
    "CORUNDUM":  {"category": "单相氧化物", "truth": [("Corundum Al2O3", 100.0)]},
    "FLUORITE":  {"category": "单相卤化物", "truth": [("Fluorite CaF2", 100.0)]},
    "ZINCITE":   {"category": "单相氧化物", "truth": [("Zincite ZnO", 100.0)]},
    "BRUCITE":   {"category": "单相氢氧化物", "truth": [("Brucite Mg(OH)2", 100.0)]},
    "MAGNETIT":  {"category": "单相氧化物", "truth": [("Magnetite Fe3O4", 100.0)]},
    "ZIRCON":    {"category": "单相硅酸盐", "truth": [("Zircon ZrSiO4", 100.0)]},
    "SILICA":    {"category": "单相石英", "truth": [("alpha-Quartz SiO2", 100.0)]},
    "CPD-Y2O3":  {"category": "单相氧化物", "truth": [("Y2O3", 100.0)]},
    "CPD-1A": {"category": "三组分混合(1a)", "truth": [("Al2O3", 1.15), ("ZnO", 4.04), ("CaF2", 94.81)]},
    "CPD-1B": {"category": "三组分混合(1b)", "truth": [("Al2O3", 94.31), ("ZnO", 1.36), ("CaF2", 4.33)]},
    "CPD-1C": {"category": "三组分混合(1c)", "truth": [("Al2O3", 5.04), ("ZnO", 93.59), ("CaF2", 1.36)]},
    "CPD-1D": {"category": "三组分混合(1d)", "truth": [("Al2O3", 13.53), ("ZnO", 32.89), ("CaF2", 53.58)]},
    "CPD-1E": {"category": "三组分混合(1e)", "truth": [("Al2O3", 55.12), ("ZnO", 15.25), ("CaF2", 29.62)]},
    "CPD-1F": {"category": "三组分混合(1f)", "truth": [("Al2O3", 27.06), ("ZnO", 55.22), ("CaF2", 17.72)]},
    "CPD-1G": {"category": "三组分混合(1g,可单测)", "truth": [("Al2O3", 31.37), ("ZnO", 34.21), ("CaF2", 34.42)]},
    "CPD-1H": {"category": "三组分混合(1h)", "truth": [("Al2O3", 35.12), ("ZnO", 30.19), ("CaF2", 34.69)]},
    "CPD-2":  {"category": "四组分+择优取向", "truth": [("Al2O3", 21.27), ("ZnO", 19.94), ("CaF2", 22.53), ("Brucite Mg(OH)2", 36.26)]},
    "CPD-3":  {"category": "三组分+非晶", "truth": [("Al2O3", 30.79), ("ZnO", 19.68), ("CaF2", 20.06), ("Glass (SiO2,非晶)", 29.47)]},
    "CPD-4":  {"category": "三组分+微吸收", "truth": [("Al2O3", 50.46), ("Magnetite Fe3O4", 19.64), ("Zircon ZrSiO4", 29.90)]},
    "BAUXITE": {"category": "七相合成铝土矿", "truth": [("Gibbsite", 54.90), ("Boehmite", 14.93), ("Hematite", 10.00),
                                                        ("Goethite", 9.98), ("Quartz", 5.16), ("Kaolinite", 3.02), ("Anatase", 2.00)]},
    "GRANODIO": {"category": "天然花岗闪长岩", "truth": [("Quartz(主)", None), ("Feldspar(主)", None), ("Albite(主)", None),
                                                          ("Biotite(主)", None), ("Clinochlore(次)", None), ("Hornblende(次)", None), ("Zircon(痕量)", None)]},
    "PHARM1GR": {"category": "五相药物混合(1)", "truth": [("Mannitol", None), ("Sucrose", None), ("DL-Valine", None), ("Starch", None), ("Nizatidine", None)]},
    "PHARM2GR": {"category": "五相药物混合(2)", "truth": [("Mannitol", None), ("Sucrose", None), ("DL-Valine", None), ("Starch", None), ("Nizatidine", None)]},
    "MANNITOL": {"category": "单相有机物", "truth": [("Mannitol", 100.0)]},
    "SUCROSE":  {"category": "单相有机物", "truth": [("Sucrose", 100.0)]},
    "VALINE":   {"category": "单相有机物", "truth": [("DL-Valine", 100.0)]},
    "STARCH":   {"category": "单相有机物(近非晶)", "truth": [("Starch", 100.0)]},
    "NIZATIDI": {"category": "单相有机物", "truth": [("Nizatidine", 100.0)]},
}

# csuHJW 教学集: 真值写在文件名 (按 Data 编号; 键一律小写, 查找时大小写不敏感)
CSU_TRUTH = {
    "data001": ("双相TiO2(锐钛+金红石)", [("TiO2锐钛矿", None), ("TiO2金红石", None)],
                ".txt/.rpt 是 JADE Phase ID Report, 会防御性报错; 用 .raw (Rigaku 解析器) 或 .mdi"),
    "data002": ("标准硅 Si", [("Si", 100.0)], ".pdf 为报告非谱图"),
    "data003": ("AlCoO-650C", [("Al2O3(Co掺杂)", None)], "仅 .raw (Rigaku), 无 txt 副本"),
    "data004": ("AlCoO-750C", [("Al2O3(Co掺杂)", None)], ".sav 为 Bruker 专有"),
    "data005": ("AlCoO-650C", [("Al2O3(Co掺杂)", None)], ""),
    "data006": ("AlCoO-750C", [("Al2O3(Co掺杂)", None)], ""),
    "data007": ("铜 Cu", [("Cu(FCC)", 100.0)], "Data007-016 为同一 Cu 系列不同条件"),
    "data008": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data009": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data010": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data011": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data012": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data013": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data014": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data015": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data016": ("铜 Cu", [("Cu(FCC)", 100.0)], ""),
    "data017": ("铜 低角度", [("Cu(FCC)", 100.0)], ""),
    "data018": ("铜 高角度", [("Cu(FCC)", 100.0)], ""),
    "data019": ("Al-Zn-Mg合金时效态", [("Al(基体)", None), ("MgZn2(时效相)", None)], ""),
    "data020": ("残余奥氏体钢", [("奥氏体", None), ("铁素体", None)], ""),
    "data021": ("氧化铁", [("Fe2O3/Fe3O4", None)], ""),
    "data022": ("黏土矿物", [("黏土(高岭石/云母类)", None)], ""),
    "data023": ("含非晶相 ZnO+CaCO3+Al2O3", [("ZnO", None), ("CaCO3", None), ("Al2O3", None), ("非晶", None)], ""),
    "data024": ("炭原丝", [("碳(近非晶)", None)], "近非晶, 不宜强行结晶相匹配"),
    "data025": ("高聚物1", [("polymer(近非晶)", None)], "data025-029 高聚物系列, 近非晶"),
    "data026": ("高聚物2", [("polymer(近非晶)", None)], ""),
    "data027": ("高聚物3", [("polymer(近非晶)", None)], ""),
    "data028": ("高聚物4", [("polymer(近非晶)", None)], ""),
    "data029": ("高聚物5", [("polymer(近非晶)", None)], ""),
    "data030": ("LiMnO2+Si", [("LiMnO2", None), ("Si(内标)", None)], ""),
    "data031": ("ZrB-ZrB2", [("ZrB", None), ("ZrB2", None)], ".abc 专有格式"),
    "data032": ("Lansolazole(药物)", [("Lansolazole", None)], ".is0/.is1/.is2 专有格式; 无机库难覆盖"),
    "data033": ("单相锐钛矿", [("Anatase TiO2", 100.0)], ""),
    "data034": ("7046-7P(编号样品)", [], "真值未知, 需查 7046-7P 编号含义"),
    "data035": ("硬质合金 WC 残余应力", [("WC", 100.0)], "应力测试用途"),
    "data036": ("ZnO-CaCO3-SiO2+Al2O3 四元混合", [("ZnO", None), ("CaCO3", None), ("SiO2", None), ("Al2O3", None)], ""),
    "data037": ("Amorphous+SiO2", [("SiO2(结晶)", None), ("非晶", None)], ""),
    "data038": ("Y2O3", [("Y2O3", 100.0)], ".rrp 专有格式"),
    "data039": ("LiMnO2+Si", [("LiMnO2", None), ("Si(内标)", None)], ""),
    "data040": ("NCM811 三元正极", [("NCM811 LiNi0.8Co0.1Mn0.1O2", None)], "致密相; .raw 为 Rigaku 可解析"),
    "data041": ("ZnO+CaCO3", [("ZnO", None), ("CaCO3", None)], "目录型: 子目录含 ZnO.cif/CaCO3.cif 可作精修起点"),
    "data042": ("陶瓷ZrSiO4-1180部分晶化", [("ZrSiO4", None), ("ZrO2", None), ("Cristobalite", None)], "目录型: 子目录含 3 个 .cif; 仅 par/lst/txt, 原始谱图或需从 par 恢复"),
    "data043": ("Ni(OH)2", [("Ni(OH)2", None)], "目录型: 子目录含 .apf/.spf/.cif 与 07009 Ni(OH)2.raw"),
    "data044": ("Al-MgZn2过时效态", [("Al", None), ("MgZn2", None)], "目录型: 子目录含 Al.cif/MgZn2.cif; 仅 txt/par"),
}


def parse_testxrd_truth(path, with_wt):
    """解析 物相结果(+wt%).txt: 'key:' 行后跟 'name[\\twt%]' 行。"""
    out, cur = {}, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            if not line.strip():
                continue
            m = re.match(r"^([0-9]-[0-9][a-z]?)\s*[&]?\s*([0-9]-[0-9][a-z]?)?\s*[：:]", line.strip())
            if m:
                cur = [m.group(1)] + ([m.group(2)] if m.group(2) else [])
                for k in cur:
                    out.setdefault(k, [] if with_wt else [])
                continue
            if cur is None:
                continue
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if not parts:
                continue
            name = parts[0]
            wt = None
            if with_wt and len(parts) > 1:
                m2 = re.search(r"([\d.]+)\s*%", parts[-1])
                if m2:
                    wt = float(m2.group(1))
            for k in cur:
                out[k].append((name, wt) if with_wt else name)
    return out


def build():
    files_iucr = scan(XRDATA + "/IUCr")
    files_csu = scan(XRDATA + "/csuHJW")
    files_tx = scan(TESTXRD)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---------- IUCr ----------
    iucr_samples = []
    for sid, meta in IUCR_TRUTH.items():
        fmts = {}
        for rel, size in files_iucr.items():
            base = os.path.basename(rel)
            stem, ext = os.path.splitext(base)
            if stem.upper() == sid.upper() and "/" not in rel:
                fmts[ext.lower().lstrip(".")] = {"path": f"{XRDATA}/IUCr/{rel}", "size": size}
        if not fmts:
            continue
        iucr_samples.append({"id": sid, "category": meta["category"],
                             "truth": [list(t) for t in meta["truth"]],
                             "formats": fmts, "notes": ""})
    # MDI 与 RAW 均存在的 (BAUXITE/CPD 系) 标注双格式
    # 未纳入 37 样本 harness 的样本
    harness_iucr = {"CORUNDUM", "FLUORITE", "ZINCITE", "BRUCITE", "MAGNETIT", "ZIRCON",
                    "SILICA", "CPD-Y2O3", "CPD-1A", "CPD-1B", "CPD-1C", "CPD-1G",
                    "CPD-2", "CPD-3", "CPD-4", "BAUXITE", "GRANODIO", "PHARM1GR",
                    "PHARM2GR", "MANNITOL", "SUCROSE", "VALINE", "STARCH", "NIZATIDI"}
    for s in iucr_samples:
        if s["id"] not in harness_iucr:
            s["notes"] = "当前 validate_xrdata.py 未覆盖 (可作扩展验收样本)"

    # ---------- csuHJW ----------
    csu_samples, csu_other = [], []
    grouped = {}
    for rel, size in files_csu.items():
        base = os.path.basename(rel)
        m = re.match(r"^([Dd]ata\d{3})", base)
        if m and "/" not in rel:
            grouped.setdefault(m.group(1).lower(), {})[os.path.splitext(base)[1].lower().lstrip(".")] = \
                {"path": f"{XRDATA}/csuHJW/{rel}", "size": size}
        else:
            csu_other.append(rel)

    def csu_formats(sid_lower):
        """顶层同前缀文件 + 目录型样本的子目录谱图 (Data041-044)。"""
        fmts = dict(grouped.get(sid_lower, {}))
        for prefix in (sid_lower, sid_lower.capitalize()):
            for r, sz in files_csu.items():
                if r.startswith(prefix + "/"):
                    fmts.setdefault(os.path.splitext(os.path.basename(r))[1].lower().lstrip("."),
                                    {"path": f"{XRDATA}/csuHJW/{r}", "size": sz})
        return fmts

    for sid in sorted(CSU_TRUTH, key=lambda x: int(x[-3:])):
        cat, truth, note = CSU_TRUTH[sid]
        fmts = csu_formats(sid)
        if not fmts:
            continue
        csu_samples.append({"id": sid, "category": cat, "truth": [list(t) for t in truth],
                            "formats": fmts, "notes": note})

    # ---------- test_xrd ----------
    truth_phases = parse_testxrd_truth(os.path.join(TESTXRD, "txt", "物相结果.txt"), with_wt=False)
    truth_wt = parse_testxrd_truth(os.path.join(TESTXRD, "txt", "物相结果+wt%.txt"), with_wt=True)
    # 7-1/7-2 在 wt% 文件里是多列表格, 解析易乱 → 直接用与 IUCr 等价的干净真值覆盖
    truth_wt["7-1"] = [("Quartz", 5.16), ("Boehmite", 14.93), ("Anatase", 2.00),
                       ("Goethite", 9.98), ("Kaolinite", 3.02), ("Gibbsite", 54.90), ("Hematite", 10.00)]
    truth_wt["7-2"] = [("Quartz(主)", None), ("Feldspar(主)", None), ("Albite(主)", None),
                       ("Biotite(主)", None), ("Clinochlore(次)", None), ("Hornblende(次)", None), ("Zircon(痕量)", None)]
    ids13 = ["1-1", "1-2", "2-1", "2-2", "3-1", "3-2", "4-1",
             "5-1", "5-2", "5-2b", "5-3", "7-1", "7-2"]
    # 与 IUCr 标准集的对照关系 (同一批混合物在两个数据集重复出现)
    XREF = {"3-1": "≈ IUCr CPD-1C (同配比)", "3-2": "≈ IUCr CPD-3 (含非晶)",
            "4-1": "≈ IUCr CPD-2 (择优取向)", "7-1": "= IUCr BAUXITE (合成铝土矿)",
            "7-2": "= IUCr GRANODIO (花岗闪长岩)"}
    tx_samples = []
    for sid in ids13:
        fmts = {}
        for sub in ("txt", "mdi", "raw", "xy"):
            for rel, size in files_tx.items():
                if rel.startswith(f"{sub}/") and os.path.basename(rel).rsplit(".", 1)[0] == sid:
                    fmts.setdefault(os.path.splitext(rel)[1].lower().lstrip("."),
                                    {"path": f"{TESTXRD}/{rel}", "size": size})
        truth = truth_wt.get(sid) or [(p, None) for p in truth_phases.get(sid, [])]
        tx_samples.append({"id": sid, "category": "13试样基准(元素限定+定量)",
                           "truth": [list(t) for t in truth], "formats": fmts,
                           "notes": "端到端验收入口: tests/test_xrd_samples.py (含元素限定)"
                                    + (f"; {XREF[sid]}" if sid in XREF else "")})

    # geshi 格式转换集
    geshi = [{"id": "4-1", "category": "格式转换测试集(同一谱图5种格式)",
              "truth": [list(t) for t in (truth_wt.get("4-1") or [])],
              "formats": {os.path.splitext(os.path.basename(r))[1].lower().lstrip("."):
                          {"path": f"{TESTXRD}/geshi/{r}", "size": sz}
                          for r, sz in files_tx.items() if r.startswith("geshi/")},
              "notes": "验证 格式转换(dat/mdi/raw/txt/xy) 读入一致性与转换器"}]

    # 5/ 原始仪器导出目录
    export = []
    for d in sorted(os.listdir(TESTXRD + "/5")) if os.path.isdir(TESTXRD + "/5") else []:
        full = os.path.join(TESTXRD, "5", d)
        if os.path.isdir(full):
            sid = d.split("#")[0]
            truth = truth_wt.get(sid) or [(p, None) for p in truth_phases.get(sid, [])]
            export.append({"id": d, "category": f"原始仪器导出目录({sid})",
                           "truth": [list(t) for t in truth],
                           "formats": {os.path.splitext(f)[1].lower().lstrip("."):
                                       {"path": full.replace("\\", "/") + "/" + f,
                                        "size": os.path.getsize(os.path.join(full, f))}
                                       for f in os.listdir(full)},
                           "notes": "含 .mtd/.par/.lst 仪器文件与匹配 .cif (精修起点); 5-2b=5-2 无择优取向"})

    catalog = {
        "version": "1.0",
        "generated": now,
        "roots": {"xrdata_iucr": XRDATA + "/IUCr", "xrdata_csuhjw": XRDATA + "/csuHJW",
                  "test_xrd": TESTXRD},
        "datasets": {
            "xrdata_iucr": iucr_samples,
            "xrdata_csuhjw": csu_samples,
            "test_xrd_baseline13": tx_samples,
            "test_xrd_geshi": geshi,
            "test_xrd_raw_export": export,
        },
        "unattributed": {
            "xrdata_iucr": sorted(r for r in files_iucr
                                  if os.path.basename(r).rsplit(".", 1)[0].upper() not in
                                  {s.upper() for s in IUCR_TRUTH}),
            "xrdata_csuhjw": sorted(csu_other),
            "test_xrd": sorted(r for r in files_tx
                               if os.path.basename(r).rsplit(".", 1)[0] not in set(ids13)
                               and not r.startswith(("geshi/", "5/", "txt/物相结果", "txt/PolyXRD"))
                               and os.path.basename(r) not in ("元素限定.txt",)),
        },
        "pitfalls": [
            "csuHJW 的 .raw = Rigaku RINT-2000 二进制(魔数 FI\\0\\0) → data_loader._load_rigaku_raw 已支持 (2026-10-08 #55); 更早版本会落入启发式兜底返回垃圾。",
            "data001：TiO2双相.txt / .rpt = JADE Phase ID Report → data_loader 会防御性报错; 谱图请用 .raw 或 .mdi。",
            "IUCr 的 .RAW = Philips RAW2 二进制 → data_loader._load_raw2 支持。",
            "IUCr/Must do/ 下 .PRN/.txt 为同批谱图文本副本 (PRN 解析未接入, 仅 txt 已被 harness 用过 CPD 系列)。",
            "IUCr/(IUCr) Standard data sets_files/ = 网页资源缓存, 非谱图; gsas/*.gss 与 *.tar.gz 为 GSAS/归档, 未接入。",
            ".sav(Bruker)/.is0-2/.abc/.mtd/.par/.lst/.pdf 为专有参数/报告文件, 不作谱图解析。",
            "IUCr CPD-1D/1E/1F/1H 及 Must do 全套当前 validate_xrdata.py 未覆盖 → 扩展验收可用样本。",
            "test_xrd/geshi = 4-1 同谱图五格式 (dat/mdi/raw/txt/xy) → 格式转换一致性验收。",
            "test_xrd/txt/元素限定.txt = 13 试样元素过滤真值; tests/test_xrd_samples.py 已内置。",
            "近非晶样本 (STARCH/data024/高聚物系列/CPD-3 玻璃) 不出尖锐峰, 召回漏检属预期内, 不算算法失败。",
            "MANNITOL/VALINE 同时是有机库 (organic_reference_database.json) 的 exp 来源谱 — 改检索算法时勿破坏 #57 依赖。",
        ],
        "harness_map": [
            {"entry": "tests/validate_xrdata.py", "covers": "XRData 37 样本检索召回 (MANIFEST) + pdf2 兜底 + builtin 精修",
             "outputs": "tests/xrdata_validation_results.{json,csv}"},
            {"entry": "tests/make_xrdata_checklist.py", "covers": "重算召回(元素多重集匹配)并出最终清单",
             "outputs": "tests/xrdata_checklist.{md,csv}"},
            {"entry": "tests/test_xrd_samples.py", "covers": "test_xrd 13 试样端到端 (元素限定三态过滤 + Rietveld 定量)",
             "outputs": "tests/ 下 PolyXRD_测试报告*.txt"},
            {"entry": "scripts/build_organic_db.py", "covers": "有机库构建 (依赖 IUCr MANNITOL/VALINE.RAW 作 exp 来源)",
             "outputs": "src/polyxrd/resources/database/organic_reference_database.json"},
            {"entry": "tests/probe_organic_id.py / probe_xrdata_load.py", "covers": "快速探针 (有机命中 / 各格式加载)",
             "outputs": "stdout"},
        ],
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    # ---------------- Markdown ----------------
    L = []
    L.append("# 谱图数据集目录 (XRData + test_xrd)\n")
    L.append(f"> 生成于 {now} ｜ 重跑: `./venv/Scripts/python.exe scripts/build_spectrum_catalog.py`")
    L.append("> 机器可读版: `tests/spectrum_catalog.json` ｜ 本清单供后续 agent 直接取用与验收\n")

    n_i = len(iucr_samples); n_c = len(csu_samples); n_t = len(tx_samples)
    L.append("## 一、总览\n")
    L.append(f"- **XRData/IUCr**: {n_i} 个标准样本 (单相 8 + CPD 混合 12 + 铝土矿/花岗闪长岩 + 药物 7), RAW2 二进制 `.RAW` + 部分 `.mdi` 双格式")
    L.append(f"- **XRData/csuHJW**: {n_c} 个教学样本 (真值写在文件名), `.raw`=Rigaku RINT-2000 / `.TXT` 文本 / `.mdi`")
    L.append(f"- **test_xrd**: 13 试样基准 (含 wt% 真值+元素限定) + geshi 五格式转换集 + 5/ 原始导出目录")
    L.append(f"- 验收入口见文末「验收入口映射」; 已知坑点见「坑点速查」\n")

    def truth_str(truth):
        return "; ".join(f"{t[0]}" + (f" {t[1]}%" if t[1] is not None else "") for t in truth) or "—"

    def fmt_str(formats):
        return " + ".join(sorted(formats.keys())) if formats else "—"

    L.append("## 二、XRData/IUCr 标准集\n")
    L.append("| 样品 | 类别 | 真值 (wt% 为称重值) | 格式 | 备注 |")
    L.append("|---|---|---|---|---|")
    for s in iucr_samples:
        L.append(f"| {s['id']} | {s['category']} | {truth_str(s['truth'])} | {fmt_str(s['formats'])} | {s['notes']} |")

    L.append("\n## 三、XRData/csuHJW 教学集 (真值在文件名)\n")
    L.append("| 样品 | 类别 | 真值 | 格式 | 备注 |")
    L.append("|---|---|---|---|---|")
    for s in csu_samples:
        L.append(f"| {s['id']} | {s['category']} | {truth_str(s['truth'])} | {fmt_str(s['formats'])} | {s['notes']} |")

    L.append("\n## 四、test_xrd 13 试样基准\n")
    L.append("| 试样 | 真值 (wt% 可用时给出) | 格式 | 备注 |")
    L.append("|---|---|---|---|")
    for s in tx_samples:
        L.append(f"| {s['id']} | {truth_str(s['truth'])} | {fmt_str(s['formats'])} | {s['notes']} |")

    L.append("\n### geshi 格式转换集\n")
    for s in geshi:
        L.append(f"- **{s['id']}**: {fmt_str(s['formats'])} — {s['category']}；{s['notes']}")
    L.append("\n### 5/ 原始仪器导出目录\n")
    for s in export:
        L.append(f"- **{s['id']}**: {fmt_str(s['formats'])}；{s['notes']}")

    L.append("\n## 五、坑点速查 (后续 agent 必读)\n")
    for i, p in enumerate(catalog["pitfalls"], 1):
        L.append(f"{i}. {p}")

    L.append("\n## 六、验收入口映射\n")
    L.append("| 入口脚本 | 覆盖范围 | 产物 |")
    L.append("|---|---|---|")
    for h in catalog["harness_map"]:
        L.append(f"| `{h['entry']}` | {h['covers']} | `{h['outputs']}` |")

    L.append("\n## 七、未归类文件 (参考)\n")
    for k, v in catalog["unattributed"].items():
        if v:
            L.append(f"- **{k}**: {len(v)} 个 — {', '.join(v[:12])}{' …' if len(v) > 12 else ''}")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print(f"IUCr 样本={n_i}  csuHJW 样本={n_c}  test_xrd 基准={n_t}  geshi={len(geshi)}  导出目录={len(export)}")
    print("JSON:", OUT_JSON)
    print("MD  :", OUT_MD)


if __name__ == "__main__":
    build()
