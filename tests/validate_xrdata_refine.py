# -*- coding: utf-8 -*-
"""XRData 精修补跑 (仅 7 个单相标样)。

主验证脚本因 clear_selection 路径错误漏跑了精修; 本脚本单独补跑。
用 cod_inorganics(带晶胞) → 回退 pdf2 选相, builtin 引擎 max_cycles=2 + 窗口限幅。

用法:
  cd /d/Project/XRD/PolyXRD && CODEBUDDY_SAFE_DELETE_ENABLED=0 \
    QT_QPA_PLATFORM=offscreen ./venv/Scripts/python.exe -u tests/validate_xrdata_refine.py
"""
from __future__ import annotations
import os, sys, time, json, traceback
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
# (label, path, refine_key, truth_keys_for_select)
REFINE_TARGETS = [
    ("CORUNDUM", f"{IUCr}/CORUNDUM.RAW", "corundum", ["corundum","al2o3"]),
    ("FLUORITE", f"{IUCr}/FLUORITE.RAW", "fluorite", ["fluorite","caf2"]),
    ("ZINCITE",  f"{IUCr}/ZINCITE.RAW",  "zincite",  ["zincite","zno"]),
    ("SILICA",   f"{IUCr}/SILICA.RAW",   "quartz",   ["quartz","sio2","silicon dioxide"]),
    ("Y2O3",     f"{IUCr}/CPD-Y2O3.RAW", "y2o3",     ["y2o3","yttria","yttrium oxide"]),
    ("Cu-007",   f"{csu}/Data007：铜衍射谱系列.TXT", "copper", ["copper","cu","fcc"]),
]
OUT = os.path.join(ROOT, "tests", "xrdata_refine_results.json")

def norm(s):
    return (s or "").lower().replace(" ", "").replace("(", "").replace(")", "").replace(",", "")

def select_refine_phase(vm, keys):
    nk = [norm(k) for k in keys]
    for m in vm.matched_phases or []:
        p = m.phase
        if p.lattice is None:
            continue
        blob = norm(p.name) + "|" + norm(p.formula)
        if any(k and k in blob for k in nk):
            return p
    return None

results = []
for label, path, rkey, tkeys in REFINE_TARGETS:
    rec = {"label": label, "path": path, "refine_key": rkey}
    t0 = time.time()
    try:
        win._vm.load_file(path); pump(0.3)
        d = win._vm.current_data
        rec["two_theta_range"] = [round(float(d.two_theta.min()),2), round(float(d.two_theta.max()),2)]
        win._vm.reset_analysis_state(); pump(0.1)
        win._vm.find_peaks_advanced(); pump(0.5)
        rec["n_peaks"] = len(win._vm.peaks.peaks)
        # 选相: 先 cod_inorganics(top50, 带晶胞), 缺则 pdf2(top50)
        refine_phase = None
        for db in ("cod_inorganics", "pdf2"):
            win._vm.identify_phases(top_n=50, db_source=db); pump(1.0)
            refine_phase = select_refine_phase(win._vm, [rkey] + tkeys)
            if refine_phase is not None:
                rec["phase_source_db"] = db
                break
        if refine_phase is None:
            rec.update(status="no_lattice_phase", note="未找到带晶胞的匹配相")
        else:
            win._vm._phase_vm.clear_selection(); pump(0.1)
            win._vm.select_phase(refine_phase); pump(0.1)
            lo = max(float(d.two_theta.min()) + 2.0, 10.0)
            hi = min(float(d.two_theta.max()) - 2.0, 80.0)
            win._vm.refine_structure(engine="builtin", max_cycles=2, two_theta_range=(lo, hi))
            pump(1.0)
            r = win._vm.refinement_result
            rec.update(status="ok", phase=refine_phase.name, formula=refine_phase.formula,
                       Rwp=round(float(getattr(r,"wR",0.0)),3), GOF=round(float(getattr(r,"GOF",0.0)),3),
                       quality=getattr(r,"quality_grade",""), converged=bool(getattr(r,"converged",False)),
                       cycles=int(getattr(r,"num_cycles",0)),
                       time_s=round(float(getattr(r,"time_seconds",0.0)),1),
                       window=[round(lo,1), round(hi,1)],
                       weight_fraction=[round(float(p.weight_fraction),2) for p in (r.phases if r else [])])
        rec["elapsed_s"] = round(time.time()-t0, 1)
    except Exception as e:
        rec.update(status="ERROR", note=f"{type(e).__name__}: {e}")
        traceback.print_exc()
    results.append(rec)
    print(f"[REFINE] {label} {rec.get('status')} Rwp={rec.get('Rwp')} "
          f"({rec.get('elapsed_s')}s)", flush=True)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("REFINE JSON:", OUT, flush=True)
print("REFINE DONE", flush=True)
