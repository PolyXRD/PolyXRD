"""诊断 CORUNDUM.RAW 检索为何找不到刚玉 (Al2O3)。

用法 (同 probe):
  cd /d/Project/XRD/PolyXRD && CODEBUDDY_SAFE_DELETE_ENABLED=0 \
    QT_QPA_PLATFORM=offscreen ./venv/Scripts/python.exe -u tests/diag_corundum.py
"""
from __future__ import annotations
import os, sys, time
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
win = MainWindow(get_config())
def pump(s=0.3):
    end = time.time() + s
    while time.time() < end: app.processEvents()

P = r"D:/Project/XRD/XRData/IUCr/CORUNDUM.RAW"
win._vm.load_file(P); pump(0.3)
d = win._vm.current_data
print("=== data meta ===")
print("wavelength:", getattr(d, "wavelength", None))
print("meta:", getattr(d, "meta", {}))
print("first 2θ/int:", [ (round(float(d.two_theta[i]),3), round(float(d.intensity[i]),1)) for i in range(5)])
# 实验最强峰 2θ
import numpy as np
order = np.argsort(d.intensity)[::-1][:6]
print("strongest obs 2θ:", [round(float(d.two_theta[i]),3) for i in order])

win._vm.find_peaks_advanced(); pump(0.5)
peaks = win._vm.peaks.peaks
print("n_peaks:", len(peaks), "first peaks 2θ:", [round(float(p.two_theta),3) for p in peaks[:5]])

for db in ("builtin", "cod_inorganics", "pdf2"):
    win._vm.identify_phases(top_n=20, db_source=db); pump(1.0)
    mp = win._vm.matched_phases
    # 在前 20 里找 corundum / Al2O3
    hit = [m for m in mp if "corundum" in m.phase.name.lower() or "al2o3" in m.phase.formula.lower() or "al" in m.phase.formula.lower()]
    print(f"\n--- db={db} candidates={len(mp)} ---")
    for i, m in enumerate(mp[:10]):
        print(f"  #{i+1} {m.phase.name!r} form={m.phase.formula!r} FOM={m.score:.3f} cov={m.matched_peaks}/{m.total_peaks} conf={m.confidence!r}")
    if hit:
        print("  >>> 含 Al 相:", [(m.phase.name, round(m.score,3)) for m in hit])
    else:
        print("  >>> 前20 无 corundum/Al2O3")

# 剥 Kα2 后再试 cod_inorganics
print("\n=== 剥 Kα2 后 cod_inorganics ===")
win._vm.load_file(P); pump(0.3)
win._vm.strip_kalpha2(); pump(0.3)
win._vm.find_peaks_advanced(); pump(0.5)
win._vm.identify_phases(top_n=20, db_source="cod_inorganics"); pump(1.0)
mp = win._vm.matched_phases
hit = [m for m in mp if "corundum" in m.phase.name.lower() or "al2o3" in m.phase.formula.lower()]
for i, m in enumerate(mp[:10]):
    print(f"  #{i+1} {m.phase.name!r} form={m.phase.formula!r} FOM={m.score:.3f} cov={m.matched_peaks}/{m.total_peaks} conf={m.confidence!r}")
print("  >>> 含 corundum/Al2O3:", [(m.phase.name, round(m.score,3)) for m in hit] if hit else "无")
print("DIAG DONE", flush=True)
