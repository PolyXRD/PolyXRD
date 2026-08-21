# -*- mode: python ; coding: utf-8 -*-
"""PolyXRD V0.8.21 PyInstaller spec (onedir mode)."""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve()
SRC_DIR = PROJECT_ROOT / "src"

datas = [
    (str(SRC_DIR / "polyxrd" / "i18n"), os.path.join("polyxrd", "i18n")),
    (str(SRC_DIR / "polyxrd" / "resources"), os.path.join("polyxrd", "resources")),
]
binaries = []

# All polyxrd submodules first (local package)
hiddenimports = list(collect_submodules("polyxrd"))

# Dependencies from pyproject.toml
for pkg in [
    "PySide6", "matplotlib", "pymatgen", "lmfit", "scipy",
    "numpy", "pandas", "pyqtgraph", "PIL", "platformdirs",
    "powerxrd",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print(f"[warn] collect_all({pkg}) failed: {e}")

# Remove duplicates
def _unique(items):
    seen = set()
    out = []
    for it in items:
        k = (it[0], it[1])
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out

datas = _unique(datas)
binaries = _unique(binaries)
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    [str(SRC_DIR / "polyxrd" / "main.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PyInstaller false positives / unused
        "tkinter", "IPython", "jupyter", "notebook",
        "PySide6.examples", "matplotlib.tests", "scipy.special._precompute",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

icon_path = SRC_DIR / "polyxrd" / "resources" / "app-icon.ico"
manifest_path = PROJECT_ROOT / "app.manifest"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PolyXRD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
    manifest=str(manifest_path) if manifest_path.exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PolyXRD',
)
