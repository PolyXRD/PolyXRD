<div align="center">
  <img src="src/polyxrd/resources/app-icon.png" alt="PolyXRD Logo" width="120" />
  <h1>PolyXRD</h1>
  <p>
    <b>Comprehensive Analysis Suite for Polycrystalline X-ray Diffraction (XRD) Patterns</b>
    <br />
    Peak detection &nbsp;·&nbsp; Multi-phase qualitative search &nbsp;·&nbsp; Rietveld structure refinement &nbsp;·&nbsp; Le Bail cell refinement &nbsp;·&nbsp; Indexing &nbsp;·&nbsp; 3D structure visualization &nbsp;·&nbsp; Three external databases (COD Inorganics / COD Full / PDF2-2004)
  </p>
  <p>
    <a href="https://github.com/PolyXRD/PolyXRD/releases"><img src="https://img.shields.io/badge/Release-v2.5.0-blue?style=flat-square" /></a>
    &nbsp;
    <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-lightgrey?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/UI-PySide6%20(Qt6)-41cd52?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Tests-1100%2B%20collected-brightgreen?style=flat-square" />
  </p>
  <p><i>🌐 简体中文文档：[README.md](README.md)</i></p>
</div>

---

## 📖 About

**PolyXRD** is a **desktop application for comprehensive analysis of polycrystalline X-ray diffraction (XRD) patterns**, built for researchers in materials science, chemistry, and crystallography. It integrates the entire workflow — "**load raw XRD data → preprocess → peak detection → multi-phase qualitative search → Rietveld structure refinement → cell refinement → whole-pattern fitting → reporting**" — into a single unified PySide6 (Qt6) desktop application with a **Chinese / English / Japanese** trilingual interface.

Core design philosophy:

- **No Python environment required** — the installer bundles a complete Python 3.10 + PySide6 + pymatgen + scipy stack; target machines work out of the box.
- **Strict separation of program and databases** — the main program (installer / portable package) ships with no database; all three databases are packaged, downloaded, and mounted independently. The inorganic database is published by default in a **slim index form** (362 MB, no embedded CIFs); CIFs are supplied on demand from a local `cod/cif` archive or the COD online API.
- **Controllable algorithms + reproducible results** — every preprocessing/fitting step is parameterized, saveable, and replayable; project files (`.polyxrd` JSON) are fully serialized.
- **UI / algorithm layering** — MVVM architecture; the `services/` layer is pure algorithm code with no Qt dependency and can be unit-tested independently.

> 📋 **Changelog**: see [docs/CHANGELOG.md](docs/CHANGELOG.md) (Chinese).
> 🏗️ **Code structure & layering**: see [docs/代码结构说明.md](docs/代码结构说明.md) (Chinese).

---

## 🆕 Latest Release v2.5.0 (2026-10-01)

**Search-chain enhancements + combination-strategy tuning + residual-peak search** (validated on a 13-sample benchmark; see [docs/基准报告-物相检索-v1.md](docs/基准报告-物相检索-v1.md) and [docs/基准报告-物相组合-v1.md](docs/基准报告-物相组合-v1.md), Chinese):

| Metric | v2.4.0 | v2.5.0 |
|---|---|---|
| Search level-A top10 / MISS | 96% / 0 | **96% / 0** |
| Search level-B top10 / MISS | 86% / 2 | **90% / 2** |
| Search MRR (level A / B) | 0.498 / 0.487 | **0.499 / 0.488** |
| Combination phase-level hit / sample-level complete | 42/49 / 8 of 13 | **45/49 / 10 of 13** |

- **Minimum correlated peaks penalty (B-7, on by default)**: candidates with < 2 matched peaks get FoM ×2, suppressing false positives — **the sole source of this release's gains** (combination +3 phases / +2 samples, search level-B top10 +2)
- **B-6 per-candidate zero-point adaptive correction (default off)**: fully implemented, but the 13-sample ablation measured a net negative (level-A MISS 0→1, MRR drop) — same treatment as B-3; code and the `fom_zero_grid` parameter are kept for spectra with real zero-point drift
- **PFSM ΔRwp reordering (default off)**: ranks by Rwp reduction instead of correlation, with dual filtering (min Rwp reduction + min scale factor)
- **Residual-peak search**: right-click menu "Search unexplained peaks only" for iterative weak-phase recovery
- **Combination strategy E1/E2**: FoM-weighted cover_vector scaling, matched≥2 pool rescue (ablation-verified as neutral infrastructure)
- 👉 [Download v2.5.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v2.5.0)

---

## ✨ Features

### ① Data processing pipeline
| Feature | Details |
|---|---|
| Data loading | `.xrdml` (PANalytical), `.raw` (Bruker), `.txt/.csv`, `.prf` (GSAS); drag-and-drop open; batch merge |
| Wavelengths | Cu Kα default / Mo Co Cr Fe Ag W Au Ga Mn Ni Kα selectable |
| Background subtraction | SNIP (4 variants) / Sonneveld-Visser / Polynomial (order 2–10) / DWT wavelet |
| Smoothing | Savitzky-Golay / FFT low-pass / Whittaker-Eilers |
| Kα2 stripping | Rachinger (forward recursion, Δ2θ angle-dependent) / pseudo-Voigt |
| Peak search | 2nd derivative + PV fitting, automatic SNR ≥ 2 threshold; joint fitting of overlapping peak clusters |
| Peak fitting | Pseudo-Voigt / Pearson VII / Split-PV, LMFit solver, RWP & χ² |
| Instrument calibration | external-standard calibration (`services/calibration.py`) |
| Pattern format conversion | menu "File ▸ Pattern Format Conversion": 8 formats, including `.mdi` / `.raw` (RAW2) read/write (`services/pattern_convert.py`) |

### ② Phase analysis
- Multi-phase qualitative search: **d-I peak matching + Hanawalt composite + FoM scoring + formula/element filtering + mineral-name keywords** → Top-N candidates
- **Candidate search restraints (M09)**: density range `density_range`, **fuzzy direct search** by name/formula `find_phases_direct`, composite restraint filter `apply_restraints`, search-preset save/load
- **Four element-filter semantics**: must-have (`must_have`, all present) / contain (`must`, at least one) / maybe (`maybe`, widens the allowed pool only) / exclude (`exclude`). Unchecked elements default to "exclude" for a closed loop; LIGHT_ELEMENTS (O/C/H/N/S) support a one-click "set as contained"
- **FoM weighted one-to-one matching**: greedy one-to-one matching of reference vs. observed peaks (prevents dense phases from being overrated) + strong-peak weighting + specificity term + intensity cosine
- Interactive element filter (118-element periodic-table picker)
- Multi-phase joint fitting: compute calculated patterns → least squares against the observed pattern → **mass fraction (%)** per phase
- Combination selection: branch-and-bound over candidate peak-position masks, maximizing joint coverage + a hard constraint of ≤20% pure metals; **polytypes with the same formula are ranked by peak-position differences** (`phase_structure_resolver.py`)

### ③ Crystal phases & crystallography
- **Structure refinement (tiered engine capability)**:
  - **True Rietveld** (structural degrees of freedom: coordinates/occupancies/ADPs + `S·ZMV` quantification) → **GSAS-II / FullProf / MAUD**;
  - **Built-in engine** = **structure-free whole-pattern fitting (Le Bail grade, fast)**: uses CIF `|F|²` reference peaks + per-phase isotropic cell scaling
    + March-Dollase texture + Chebyshev background + statistical weights; yields usable wR/Rp without installing external programs;
    it does **not** refine atomic coordinates/occupancies/ADPs, so its wt% values are **relative quantification**, not strict mass fractions.
  - Sequential / automatic / manual refinement strategies apply to all engines above.
  - ⚠️ Metric convention: `Rwp/Rexp/GOF` are always based on **statistical weights** (`stat_weights="poisson"`).
    If unit weights (`"none"`) are explicitly selected, `Rexp/GOF` lose physical meaning and the UI shows "not interpretable".
- **Le Bail cell-parameter refinement**: refines only a/b/c/α/β/γ, no atom occupancies needed — suited to cell determination of unknown structures
- **Indexing (M15)**: built-in indexing for cubic / tetragonal / hexagonal systems (`services/indexing.py`; acceptance: cubic Si → a≈5.43 Å); hooks reserved for external Treor / Dicvol
- **3D crystal-structure visualization (M17)**: 3D unit cell + atomic-sphere view embedded in the CIF browser, automatically **expanding the asymmetric unit** by space group (`services/structure_viz.py`)
- Structure simulation: space group/atom occupancies → calculated XRD pattern (Lorentz-polarization correction + B factors)
- hkl indexing (d→hkl), standardization for 230 space groups (spglib)
- Space-group (72.8%) and cell (81.8%) mapping based on **PDF2-2004** — matched phases can be used directly as refinement starting structures
- **External refinement program integration (M25)**: FullProf auto-generates `.dat/.pcr` → fp2k batch run → parses `.sum` and writes back Rwp/Rexp/Rp/GoF² plus per-phase R_Bragg/cell/amount; one-click "export + launch GUI" for GSAS-II / MAUD

### ④ Projects & reporting
- `.polyxrd` project save/open/save-as (JSON parameters + full pattern archive)
- Export: peak-list CSV / PNG+SVG images / multi-phase report PDF / batch reports / selected-phase CIF
- Scripting interface (`services/scripting.py`)

### ⑤ UI & multilingual
- PySide6 (Qt6) + PyQtGraph dual canvas (main pattern + residual plot), dockable panels
- 5:1 split of main pattern and residual strip, bidirectional X-axis sync; adaptive plot X-axis (cursor-centered wheel zoom, left-drag pan)
- **简体中文 / English / 日本語** switching without restart; **full re-translation on switch** (page content + dock panels + toolbar/menu/action tooltips; static text only, runtime data untouched); the three translation key sets are fully aligned
- **End-to-end UTF-8, no mojibake on any Windows locale** — all text I/O with explicit encodings; user files read with `utf-8-sig` (BOM-immune); statically guarded by `scripts/check_utf8_encoding.py`
- Light/dark themes, Fusion style, HiDPI support; Y-axis linear / log / sqrt switching
- Interactive periodic table (double-click selection, with atomic weights and characteristic wavelengths)
- **Single-instance operation**: double-clicking again does not spawn another window — it brings the running window to the foreground
- **Database manager dialog**: three slots each showing "mounted/not mounted", record count, size, and which download package the slot expects

### ⑥ Three external database services
| Database | Scale | Purpose |
|---|---|---|
| COD Inorganics | 71,199 phases | Precomputed d-I peaks + pre-truncated strong-peak lists + Hanawalt pre-screening — the **primary search database**, fastest. Published by default in **slim index form** (362 MB, `COD_inorganics_index.sqlite`): atomic sites fully retained, CIFs read on demand from a local `cod/cif` archive, with automatic fallback to the COD online API. The full embedded edition (1.19 GB) can still be imported; the two are row-for-row identical |
| COD Full Index | 113,223 entries | Index of the complete COD CIF collection (432 MB, no embedded CIFs), serving the "COD Full" and "Built-in + Full merged" search sources |
| PDF2-2004 | 163,834 phases | ICDD PDF-2 2004, with space groups and cell parameters, for comparison against the commercial library |

- Path priority: **persistent path imported via GUI (`~/.polyxrd/user_db_paths.json`) > default location (used only if it exists) > `~/.polyxrd/cif_db/` fallback**
- **Database-type validation on import**: the three databases share table names (COD Inorganics and PDF2 both use `phases`), so picking the wrong slot raises a prompt instead of failing silently
- Effective immediately after import, **no restart**; the "database source" dropdown in the phase-analysis panel refreshes in sync; unmounted sources are greyed out
- The three databases are fully independent — you can mount just one; with none mounted, the built-in **106 reference phases** still work

---

## 🚀 Getting Started

### Option A · Regular users (recommended, no Python needed)

```
① Download PolyXRD-Setup-vX.Y.Z.exe (Windows x64) or the Portable package (unzip and run)
   ↓
② Install (default C:\Program Files\PolyXRD\) and run PolyXRD.exe
   ↓
③ Download database packages as needed — each is independent; take only what you need
   Extract to any directory (must be truly extracted to disk, not opened inside the archive)
   ↓
④ Launch PolyXRD → menu "Database ▸ External Database Manager…"
   Each slot states "download package: … → extracts to …"; match it and click "Import…" on that row
   → effective immediately, no restart
   ↓
⑤ Start using it!
```

> **Release contents**: a release provides the **Setup installer + Portable package + two COD index database packages**
> (Setup 241 MB / Portable 369 MB / inorganics index 134 MB / full index 206 MB).
> The PDF2-2004 package is an ICDD-copyrighted library and is **not distributed with the release**; prepare the library file yourself if you need it.

> **About the slim inorganics database**: the index edition contains no embedded CIFs. If your machine has the
> raw COD `cod/cif/` archive (4-level shard directories), CIFs are read directly on demand; otherwise it
> automatically falls back to downloading CIFs by ID from the COD website (internet required). If you need a
> fully offline, self-contained single file, use the full embedded edition `COD_inorganics.sqlite` (1.19 GB) instead — the data is identical.

> **About the PDF2-2004 database**: this is an ICDD commercial database, **copyright-protected; this repository does not distribute it and the release does not include it**.
> Users with a valid license may prepare `PDF2_2004.sqlite` themselves and import it into the PDF2 slot via "External Database Manager…";
> if unlicensed, simply leave the slot empty — all other features are unaffected.

> Even with no database mounted, the program still works with its built-in **106** common reference phases.
> Detailed instructions and troubleshooting: see the paragraphs above (the "External Database Manager" dialog describes each slot).

### Option B · Developers / secondary development (run from source)

```bash
# 1. Clone the repository
git clone https://github.com/PolyXRD/PolyXRD.git
cd PolyXRD

# 2. Create a virtual environment (Python 3.10+)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch the application
python -m polyxrd.main

# 5. Run tests
python -m pytest -q
```

#### One-click launch from source (for manual acceptance)

`run_dev.bat` at the repository root already sets up PYTHONPATH — just double-click it:

```bat
run_dev.bat
```

It runs the in-repository `src/` directly, so it **always reflects the latest code** without waiting for a PyInstaller build —
ideal for feature acceptance and manual testing. The packaged and source editions differ only in distribution; the business code is identical.

### Building release artifacts

```bat
:: After editing set APPVER= at the top of build.bat:
build.bat
```

`build.bat` performs, in order: icon generation → PyInstaller packaging → **self-check that dist contains no business databases** →
Inno Setup installer compilation → portable package → three independent database packages → SHA-256 computation.

> **Note**: by default **no** database is packaged. To embed databases into the binary, use `POLYXRD_WITH_DB=1`.
>
> To only verify / regenerate release artifacts (without rebuilding the exe):
> ```powershell
> pwsh -NoProfile -File scripts\verify_release.ps1 -Version X.Y.Z
> ```

### 5-minute quick start (workflow example)

```
① File → Open → load a .xrdml / .txt sample (or drag the file onto the window)
② Preprocessing panel: SNIP-40 background → SG w=11 p=3 smoothing → Max normalization
③ Peak detection: automatic threshold → Search
④ Phase search: check "COD Inorganics" → must-have elements [Mg, Al, O] → Search
   → Top candidate: MgAl₂O₄ Spinel ✅
⑤ Rietveld refinement: select coexisting phases → refinement wizard → built-in engine → sequential strategy
   → refinement done; inspect wR and the residual plot
⑥ When needed: CIF browser for the 3D cell / indexing for cell parameters / export report (CSV/PDF)
```

### Startup / shutdown troubleshooting

| Symptom | Handling |
|---|---|
| **Double-click does nothing** | PolyXRD is a **single-instance** program: if an instance is already running, double-clicking **brings the existing window to the front** (with a taskbar flash if minimized or covered). If Task Manager shows `PolyXRD.exe` but no window (ghost instance), end it directly; newer versions **start normally** in this situation instead of being blocked |
| **Process persists after closing the window** (`PolyXRD.exe` still in Task Manager) | New versions **always exit** when the window closes (a 5-second hard-exit watchdog runs after the event loop ends). On older versions, end the process manually |
| **Diagnosing "why won't it open"** | Run `PolyXRD.exe --diagnose` from a command line — no UI is started; a report is generated directly (`%USERPROFILE%\.polyxrd\logs\diagnose-*.txt`), and Windows Restart Manager identifies **which process is holding the program files** (such file locks are the most typical cause of "you must restart your PC") |
| **Startup / crash logs** | `%USERPROFILE%\.polyxrd\logs\`: `startup-YYYY-MM-DD.log` (startup trace, each line tagged `[pid=]`; the app is truly up only when `shown visible=True` appears), `crash-*.log` (Python exceptions), `startup-failure-*.log` (with file-lock diagnostics), `faulthandler-*.log` (per-thread Python stacks dumped automatically on **native crashes**) |
| **On a few Win11 machines, the splash flashes and the app exits** (Event Viewer points to `Qt6Widgets.dll`) | First **update the graphics driver** (field-proven: a 2023-06-15 Intel Iris Xe driver + Qt 6.11 triggers a native crash inside `window.show()`). If it still reproduces, use conservative rendering: run `PolyXRD.exe --safe-render` from a command line, or `set POLYXRD_SAFE_RENDER=1` before double-clicking (software GL + dark mode off + DPI scaling off, for bisection) |

> Startup-robustness design: **the single-instance guard is implemented with a kernel named mutex** —
> whether the previous instance exits normally or is force-killed from Task Manager, the next launch is unaffected;
> the guard "allows when in doubt" and never locks the user out over stale state.

---

## 🙏 Open-source acknowledgements

PolyXRD is built on many high-quality open-source projects — Python / PySide6 (Qt6) / PyInstaller / Inno Setup / pymatgen / spglib / scipy / NumPy / pandas / Matplotlib / PyQtGraph / LMFIT / GSAS-II / powerxrd / platformdirs, and the [Crystallography Open Database](https://www.crystallography.net/cod/) (inorganic phase data source). Thanks to the maintainers and contributor communities of these upstream projects (ICDD PDF-2 2004 is a commercial database; it is not bundled, redistributed, or included — users must obtain their own license).

---

## 📦 Release

For the latest version and the full changelog, see [docs/CHANGELOG.md](docs/CHANGELOG.md) (Chinese). Binary artifacts (Setup installer + Portable package + two COD index database packages) are available on the [👉 Releases page](https://github.com/PolyXRD/PolyXRD/releases). SHA-256 checksums are published alongside the release assets; verifying after downloading a database package is recommended (a truncated database may still open in SQLite, but errors only surface when reading tail records).

---

## 📝 Version compatibility & License

| PolyXRD | COD Inorganics | COD Full Index | PDF2-2004 |
|---|---|---|---|
| **2.x / 1.x (current)** | `…-Databases-COD-inorg-index.zip` (slim index, default; full edition still importable) | `…-Databases-COD-full-index.zip` | user-provided (ICDD license; not distributed here) |
| 0.11.0–0.13.2 | `…-Databases-COD-inorg.zip` (v2, embedded CIFs) | `…-Databases-COD-full.zip` | user-provided (ICDD license; not distributed here) |
| 0.10.0 | `…-Databases-COD-inorg.zip` (v1, d-I peaks only) | `…-Databases-COD-full.zip` | user-provided (ICDD license; not distributed here) |
| 0.9.10 and earlier | embedded or `PolyXRD_COD_Inorganics_v0.9.x.zip` | embedded or `PolyXRD_COD_Full_v0.9.x.zip` | not supported |

### Copyright & License

Copyright (c) 2026 PolyXRD Team.

This software is free for academic research and education.
Commercial use is prohibited without a separate written license from the copyright holder.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

Full terms: [`LICENSE`](LICENSE) (English) and [`LICENSE-CN`](LICENSE-CN) (Chinese); commercial licensing: sshztx@outlook.com.
When using this software, also comply with third-party license terms of upstream projects such as PySide6 (LGPL/GPL), pymatgen, and COD.

---

<div align="right">
  <i>PolyXRD Team · 2025 — 2026 · doc version 2.5.0 (2026-10-01) · contact: sshztx@outlook.com</i>
</div>
