# -*- coding: utf-8 -*-
"""XRData 物相检索 + 精修效果验证 (v2.7.0)。

对 D:/Project/XRD/XRData 下带真值的谱图, 跑多库物相检索 (cod_inorganics + builtin,
漏检 pdf2 兜底) 与单相标样 builtin 精修, 产出清单 (JSON + CSV + 控制台摘要)。

用法:
  cd /d/Project/XRD/PolyXRD && CODEBUDDY_SAFE_DELETE_ENABLED=0 \
    QT_QPA_PLATFORM=offscreen ./venv/Scripts/python.exe -u tests/validate_xrdata.py
"""
from __future__ import annotations
import os, sys, time, json, csv, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")
ROOT = r"D:/Project/XRD/PolyXRD"; sys.path.insert(0, os.path.join(ROOT, "src"))

from PySide6.QtCore import QSettings
_ov, _os = QSettings.value, QSettings.setValue
QSettings.value = lambda self, k, d=None, *a, **kw: ("" if k == "language" else _ov(self, k, d, *a, **kw))
QSettings.setValue = lambda self, k, v, *a, **kw: (None if k == "language" else _os(self, k, v, *a, **kw))
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
for _cls in (QMessageBox, QDialog):
    try: _cls.exec = lambda self, *a, **k: 0
    except Exception: pass
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFontDatabase, QFont
for _f in ("msyh.ttc", "simsun.ttc", "arial.ttf"):
    _p = os.path.join(r"C:\Windows\Fonts", _f)
    if os.path.exists(_p): QFontDatabase.addApplicationFont(_p)
try: app.setFont(QFont("Microsoft YaHei", 9))
except Exception: pass
from polyxrd.config import get_config
from polyxrd.views.main_window import MainWindow

def pump(s=0.3):
    end = time.time() + s
    while time.time() < end: app.processEvents()

win = MainWindow(get_config())
print("MainWindow OK", flush=True)

IUCr = r"D:/Project/XRD/XRData/IUCr"
csu  = r"D:/Project/XRD/XRData/csuHJW"
# truth: 每个组分 = 一组可在候选 name/formula 中匹配的 key
MANIFEST = [
    # ---- IUCr 单相标样 (RAW2) ----
    ("CORUNDUM", f"{IUCr}/CORUNDUM.RAW", "raw", "单相氧化物", [["corundum","al2o3"]], "corundum"),
    ("FLUORITE", f"{IUCr}/FLUORITE.RAW", "raw", "单相卤化物", [["fluorite","caf2"]], "fluorite"),
    ("ZINCITE",  f"{IUCr}/ZINCITE.RAW",  "raw", "单相氧化物", [["zincite","zno"]], "zincite"),
    ("BRUCITE",  f"{IUCr}/BRUCITE.RAW",  "raw", "单相氢氧化物", [["brucite","mg(oh)2","mgoh"]], None),
    ("MAGNETIT", f"{IUCr}/MAGNETIT.RAW", "raw", "单相氧化物", [["magnetite","fe3o4"]], None),
    ("ZIRCON",   f"{IUCr}/ZIRCON.RAW",   "raw", "单相硅酸盐", [["zircon","zrsio4"]], None),
    ("SILICA",   f"{IUCr}/SILICA.RAW",   "raw", "单相石英", [["quartz","silicon dioxide","sio2"]], "quartz"),
    ("Y2O3",     f"{IUCr}/CPD-Y2O3.RAW", "raw", "单相氧化物", [["y2o3","yttria","yttrium"]], "y2o3"),
    # ---- IUCr 混合样品 (RAW2) ----
    ("CPD-1A", f"{IUCr}/CPD-1A.RAW", "raw", "三组分混合(1a)", [["corundum","al2o3"],["zincite","zno"],["fluorite","caf2"]], None),
    ("CPD-1B", f"{IUCr}/CPD-1B.RAW", "raw", "三组分混合(1b)", [["corundum","al2o3"],["zincite","zno"],["fluorite","caf2"]], None),
    ("CPD-1C", f"{IUCr}/CPD-1C.RAW", "raw", "三组分混合(1c)", [["corundum","al2o3"],["zincite","zno"],["fluorite","caf2"]], None),
    ("CPD-1G", f"{IUCr}/CPD-1G.RAW", "raw", "三组分混合(1g)", [["corundum","al2o3"],["zincite","zno"],["fluorite","caf2"]], None),
    ("CPD-2",  f"{IUCr}/CPD-2.RAW",  "raw", "四组分+择尤(2)", [["corundum","al2o3"],["zincite","zno"],["fluorite","caf2"],["brucite","mg(oh)2"]], None),
    ("CPD-3",  f"{IUCr}/CPD-3.RAW",  "raw", "三组分+非晶(3)", [["corundum","al2o3"],["zincite","zno"],["fluorite","caf2"],["glass","amorphous","sio2"]], None),
    ("CPD-4",  f"{IUCr}/CPD-4.RAW",  "raw", "三组分+微吸收(4)", [["corundum","al2o3"],["magnetite","fe3o4"],["zircon","zrsio4"]], None),
    # ---- IUCr 多相复杂 ----
    ("BAUXITE", f"{IUCr}/BAUXITE.mdi", "mdi", "七相混合(铝土矿)",
        [["gibbsite"],["goethite"],["boehmite"],["hematite"],["quartz","sio2"],["kaolinite"],["anatase"]], None),
    ("GRANODIO", f"{IUCr}/GRANODIO.mdi", "mdi", "天然花岗闪长岩(无固定含量)",
        [["quartz","sio2"],["feldspar"],["albite"],["biotite"],["clinochlore"],["hornblende"],["zircon"]], None),
    ("PHARM1GR", f"{IUCr}/PHARM1GR.RAW", "raw", "五相药物混合(1)",
        [["mannitol"],["sucrose"],["valine"],["starch"],["nizatidine"]], None),
    ("PHARM2GR", f"{IUCr}/PHARM2GR.RAW", "raw", "五相药物混合(2)",
        [["mannitol"],["sucrose"],["valine"],["starch"],["nizatidine"]], None),
    ("MANNITOL", f"{IUCr}/MANNITOL.RAW", "raw", "单相有机物", [["mannitol"]], None),
    ("SUCROSE",  f"{IUCr}/SUCROSE.RAW",  "raw", "单相有机物", [["sucrose"]], None),
    ("VALINE",   f"{IUCr}/VALINE.RAW",   "raw", "单相有机物", [["valine"]], None),
    ("STARCH",   f"{IUCr}/STARCH.RAW",   "raw", "单相有机物(近非晶)", [["starch"]], None),
    ("NIZATIDI", f"{IUCr}/NIZATIDI.RAW", "raw", "单相有机物", [["nizatidine"]], None),
    # ---- csuHJW 教学集 (txt/mdi) ----
    ("Cu-007", f"{csu}/Data007：铜衍射谱系列.TXT", "txt", "单相金属Cu", [["copper","cu","fcc"]], "copper"),
    ("Cu-010", f"{csu}/Data010：铜衍射谱系列.TXT", "txt", "单相金属Cu", [["copper","cu","fcc"]], None),
    ("Cu-013", f"{csu}/Data013：铜衍射谱系列.TXT", "txt", "单相金属Cu", [["copper","cu","fcc"]], None),
    ("Cu-017低角", f"{csu}/Data017：铜的低角度衍射谱.txt", "txt", "单相金属Cu(低角)", [["copper","cu","fcc"]], None),
    ("Cu-018高角", f"{csu}/Data018：铜的高角度衍射谱.txt", "txt", "单相金属Cu(高角)", [["copper","cu","fcc"]], None),
    ("Poly-025", f"{csu}/Data025：高聚物1.txt", "txt", "高聚物(近非晶)", [["polymer","poly","organic"]], None),
    ("Poly-027", f"{csu}/Data027：高聚物3.txt", "txt", "高聚物(近非晶)", [["polymer","poly","organic"]], None),
    ("Poly-029", f"{csu}/Data029：高聚物5.txt", "txt", "高聚物(近非晶)", [["polymer","poly","organic"]], None),
    ("TiO2双相", f"{csu}/data001：TiO2双相.raw", "raw", "双相TiO2(锐钛+金红)", [["anatase"],["rutile"],["tio2"]], None),
    ("AlCoO-750c", f"{csu}/data004：AlCoO-750C.txt", "txt", "Co掺杂Al2O3(750C)", [["alcoo","coal","al2o3","cobalt"]], None),
    ("AlCoO-650c", f"{csu}/data005：AlCoO-650C.txt", "txt", "Co掺杂Al2O3(650C)", [["alcoo","coal","al2o3","cobalt"]], None),
    ("AlCoO-750cB", f"{csu}/data006：AlCoO-750C.TXT", "txt", "Co掺杂Al2O3(750C)", [["alcoo","coal","al2o3","cobalt"]], None),
    ("NCM811", f"{csu}/Data040：NCM：811.mdi", "mdi", "三元正极NCM811(致密相召回难点)",
        [["ncm","nickel cobalt manganese","limn","lini","li(ni","licoo2","mn"]], None),
]

OUT_JSON = os.path.join(ROOT, "tests", "xrdata_validation_results.json")
OUT_CSV  = os.path.join(ROOT, "tests", "xrdata_validation_results.csv")

def norm(s):
    return (s or "").lower().replace(" ", "").replace("(", "").replace(")", "").replace(",", "")

def match_component(cands, keys):
    """在候选列表 cands[(name,formula,FOM,conf,cov)] 中找含任一 key 的; 返回 (rank1based, cand) 或 (None,None)。"""
    nk = [norm(k) for k in keys]
    for i, c in enumerate(cands, 1):
        blob = norm(c[0]) + "|" + norm(c[1])
        if any(k and k in blob for k in nk):
            return i, c
    return None, None

def top_list(vm):
    out = []
    for m in vm.matched_phases or []:
        out.append((m.phase.name, m.phase.formula, round(float(m.score),3),
                    m.confidence, f"{m.matched_peaks}/{m.total_peaks}"))
    return out

def annotate_amorphous(vm, top_cod, top_built):
    """P2-2: 计算非晶/近非晶诊断, 供清单把"物理无解"的漏检与算法失败区分开。

    top_cod/top_built 是 (name, formula, FOM, confidence, "matched/total") 元组,
    这里取两库中 FOM 最低者构造一个轻量 top_match 交给 assess_amorphous 做 veto。
    """
    from types import SimpleNamespace
    from polyxrd.services.amorphous import assess_amorphous

    best = None
    for lst in (top_cod, top_built):
        for name, formula, fom, conf, cov in lst or []:
            try:
                matched = int(str(cov).split("/")[0])
            except Exception:
                matched = 0
            if best is None or fom < best.score:
                best = SimpleNamespace(confidence=conf, score=float(fom),
                                       matched_peaks=matched)
    try:
        return assess_amorphous(vm.current_data, peaks=vm.peaks, top_match=best)
    except Exception as e:
        return {"level": "unknown", "note": f"assess failed: {type(e).__name__}: {e}"}


def select_refine_phase(vm, truth_keys):
    """在已识别候选里挑一个匹配 truth_keys 且带晶胞(lattice)的相用于精修。"""
    for m in vm.matched_phases or []:
        p = m.phase
        if p.lattice is None:
            continue
        blob = norm(p.name) + "|" + norm(p.formula)
        if any(k and k in blob for k in [norm(k) for k in truth_keys]):
            return p
    return None

results = []

def dump():
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

for entry in MANIFEST:
    label, path, fmt, category, truth, refine_key = entry
    rec = {"label": label, "path": path, "fmt": fmt, "category": category,
           "truth": truth, "refine_key": refine_key, "status": "ok"}
    t0 = time.time()
    try:
        win._vm.load_file(path); pump(0.3)
        d = win._vm.current_data
        if d is None:
            rec.update(status="LOAD_FAIL", note="current_data is None"); results.append(rec); dump(); continue
        rec["n_points"] = int(d.two_theta.size)
        rec["two_theta_range"] = [round(float(d.two_theta.min()),2), round(float(d.two_theta.max()),2)]
        win._vm.reset_analysis_state(); pump(0.1)
        win._vm.find_peaks_advanced(); pump(0.5)
        rec["n_peaks"] = len(win._vm.peaks.peaks)
        # 双库检索
        win._vm.identify_phases(top_n=10, db_source="cod_inorganics"); pump(1.0)
        top_cod = top_list(win._vm)
        win._vm.identify_phases(top_n=10, db_source="builtin"); pump(0.5)
        top_built = top_list(win._vm)
        rec["top_cod"] = top_cod; rec["top_builtin"] = top_builtin = top_built
        # P2-2: 非晶/近非晶诊断 (纯附加, 不影响检索与召回判定)
        rec["amorphous"] = annotate_amorphous(win._vm, top_cod, top_built)
        # 各真值组分的召回
        recall = []
        for comp in truth:
            r_cod, c_cod = match_component(top_cod, comp)
            r_b, c_b = match_component(top_built, comp)
            found = r_cod is not None or r_b is not None
            recall.append({"comp": comp, "found": found,
                           "cod_rank": r_cod, "builtin_rank": r_b})
        rec["recall"] = recall
        # 漏检 → pdf2 兜底 (top50)
        missed = [c["comp"] for c in recall if not c["found"]]
        if missed:
            win._vm.identify_phases(top_n=50, db_source="pdf2"); pump(1.0)
            top_pdf = top_list(win._vm)
            rec["top_pdf2"] = top_pdf
            for c in recall:
                if not c["found"]:
                    r_p, c_p = match_component(top_pdf, c["comp"])
                    if r_p is not None:
                        c["found"] = True; c["pdf2_rank"] = r_p
            rec["pdf2_rescued"] = [c["comp"] for c in recall if c.get("pdf2_rank")]
        rec["recall_rate"] = round(sum(1 for c in recall if c["found"]) / max(1,len(recall)), 3)
        # 精修 (单相标样)
        if refine_key:
            refine_phase = select_refine_phase(win._vm, [refine_key] + sum(truth, []))
            if refine_phase is None:
                # 回退: 用 pdf2 重新识别并挑选
                win._vm.identify_phases(top_n=50, db_source="pdf2"); pump(1.0)
                refine_phase = select_refine_phase(win._vm, [refine_key] + sum(truth, []))
            if refine_phase is None:
                rec["refine"] = {"status": "no_lattice_phase", "note": "未找到带晶胞的匹配相"}
            else:
                win._vm._phase_vm.clear_selection(); pump(0.1)
                win._vm.select_phase(refine_phase); pump(0.1)
                lo = max(float(d.two_theta.min()) + 2.0, 10.0)
                hi = min(float(d.two_theta.max()) - 2.0, 80.0)
                t1 = time.time()
                win._vm.refine_structure(engine="builtin", max_cycles=2, two_theta_range=(lo, hi))
                pump(1.0)
                r = win._vm.refinement_result
                rec["refine"] = {
                    "status": "ok", "phase": refine_phase.name, "formula": refine_phase.formula,
                    "Rwp": round(float(getattr(r,"wR",0.0)),3),
                    "GOF": round(float(getattr(r,"GOF",0.0)),3),
                    "quality": getattr(r,"quality_grade",""),
                    "converged": bool(getattr(r,"converged",False)),
                    "cycles": int(getattr(r,"num_cycles",0)),
                    "time_s": round(float(getattr(r,"time_seconds",time.time()-t1)),1),
                    "window": [round(lo,1), round(hi,1)],
                    "weight_fraction": [round(float(p.weight_fraction),2) for p in (r.phases if r else [])],
                }
        rec["elapsed_s"] = round(time.time()-t0, 1)
    except Exception as e:
        rec["status"] = "ERROR"; rec["note"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(rec)
    dump()
    print(f"[DONE] {label} {rec.get('status')} recall={rec.get('recall_rate')} "
          f"peaks={rec.get('n_peaks')} refine={rec.get('refine',{}).get('Rwp') if isinstance(rec.get('refine'),dict) else None} "
          f"({rec.get('elapsed_s')}s)", flush=True)

# 写 CSV 清单
try:
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["样品","格式","类别","真值组分","召回率","cod_inorganics命中","builtin命中",
                    "pdf2兜底","精修相","Rwp%","GOF","质量","精修窗口","状态"])
        for r in results:
            truth_s = "; ".join("/".join(c) for c in r.get("truth",[]))
            rc = r.get("recall",[])
            cod_s = "; ".join(("Y@%d"%c["cod_rank"]) if c.get("cod_rank") else "N" for c in rc)
            b_s   = "; ".join(("Y@%d"%c["builtin_rank"]) if c.get("builtin_rank") else "N" for c in rc)
            p_s   = "; ".join(("Y@%d"%c["pdf2_rank"]) if c.get("pdf2_rank") else "-" for c in rc)
            rf = r.get("refine") or {}
            w.writerow([r["label"], r["fmt"], r["category"], truth_s, r.get("recall_rate"),
                        cod_s, b_s, p_s, rf.get("phase",""), rf.get("Rwp",""),
                        rf.get("GOF",""), rf.get("quality",""),
                        rf.get("window",""), r.get("status")])
    print("CSV written:", OUT_CSV, flush=True)
except Exception as e:
    print("CSV ERROR:", e, flush=True)

# 摘要统计
n = len(results)
ok = [r for r in results if r.get("status")=="ok"]
cod_hit = built_hit = pdf_hit = 0
tot_comp = 0; tot_found = 0
for r in ok:
    for c in r.get("recall",[]):
        tot_comp += 1
        if c["found"]: tot_found += 1
        if c.get("cod_rank"): cod_hit += 1
        if c.get("builtin_rank"): built_hit += 1
        if c.get("pdf2_rank"): pdf_hit += 1
print("\n==== 摘要 ====", flush=True)
print(f"样品总数={n} 成功={len(ok)}", flush=True)
print(f"真值组分总数={tot_comp} 召回={tot_found} ({tot_found/max(1,tot_comp)*100:.1f}%)", flush=True)
print(f"  cod_inorganics 命中组分={cod_hit}  builtin 命中={built_hit}  pdf2兜底命中={pdf_hit}", flush=True)
print("JSON:", OUT_JSON, flush=True)
print("VALIDATION DONE", flush=True)
