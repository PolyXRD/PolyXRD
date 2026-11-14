<div align="center">
 <img src="src/polyxrd/resources/app-icon.png" alt="PolyXRD Logo" width="120" />
 <h1>PolyXRD</h1>
 <p><b>Comprehensive Analysis Suite for Polycrystalline X-ray Diffraction (XRD) Patterns</b></p>
 <p>Peak detection · Multi-phase search · Rietveld refinement · Le Bail refinement · Indexing · 3D structure visualization</p>
 <p>
  <a href="https://github.com/PolyXRD/PolyXRD/releases"><img src="https://img.shields.io/badge/Release-v5.5.0-blue?style=flat-square" /></a>
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-lightgrey?style=flat-square" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square" />
  <img src="https://img.shields.io/badge/UI-PySide6%20(Qt6)-41cd52?style=flat-square" />
 </p>
</div>

## Current version

**v5.5.0** (2026-11-13) — installers and SHA-256 checksums: [Releases](https://github.com/PolyXRD/PolyXRD/releases). Full release history: [changelog.md](changelog.md). 中文文档（补充）：[README-CN.md](README-CN.md).

## What PolyXRD does

A Windows desktop application for the full powder-XRD workflow — raw pattern → preprocessing → peak detection → multi-phase identification → whole-pattern / Rietveld refinement → reports — with a Chinese / English / Japanese interface.

- **Data processing** — `.xrdml` (PANalytical), `.raw` (Bruker), `.txt` / `.csv` import; SNIP, polynomial and wavelet background; Savitzky-Golay / FFT smoothing; Kα₂ stripping; second-derivative peak search and pseudo-Voigt / Pearson VII fitting; external-standard instrument calibration.
- **Phase identification** — d-I matching with Hanawalt pre-screening and FoM scoring, formula / element restraints (must-have / contain / maybe / exclude), interactive periodic table, sequential multi-phase search, and joint whole-pattern fitting for weight fractions.
- **Refinement** — the built-in `polyxrd.refinement` engine (structure factors, TCH profile, variable projection, Hill–Howard quantification, staged protocol with rollback, structured diagnostics) plus Le Bail cell refinement and optional FullProf / GSAS-II / MAUD integration.
- **Crystallography** — indexing for cubic / tetragonal / hexagonal systems, CIF browser with 3D unit-cell rendering, hkl assignment, space-group cell constraints.
- **Projects & reports** — `.polyxrd` JSON projects (parameters + full pattern archive), CSV / PNG / SVG / PDF exports, batch reports, and a scriptable services layer.
- **UI** — PySide6 (Qt6) with a main / residual dual canvas, language switching without restart, light / dark themes, HiDPI support, and single-instance operation.

## Design principles

1. **No Python environment for end users** — the installer bundles Python 3.10 + PySide6 + the scientific stack; a source checkout stays fully runnable.
2. **Kernel / UI decoupled** — `services/` and `refinement/` are pure computation, unit-testable without a display; `views/` and `viewmodels/` are a thin MVVM layer.
3. **Open data first** — the bundled COD-Inorg default library is derived from the [Crystallography Open Database](https://www.crystallography.net/cod/) (CC0). Proprietary ICDD data is never redistributed.
4. **Small, verifiable steps** — every algorithm change ships with pytest acceptance criteria, so builds and numerical behaviour can be checked independently.

## Project layout

```
src/polyxrd/
├── services/       # pure algorithms: IO, preprocessing, search, calibration, reports
├── refinement/     # built-in whole-pattern / Rietveld engine + diagnostics
├── models/        # Pattern, Peak, Phase, Project data models
├── viewmodels/     # MVVM state between services and views
├── views/          # PySide6 GUI
├── i18n/           # zh-CN / en-US / ja-JP translations
├── resources/      # icons, styles, bundled default library
├── utils/          # registration + build flavor (stdlib only, no Qt)
└── main.py         # application entry point
tests/               # pytest suite
scripts/             # build and release-verification helpers
run_dev.bat          # run the working tree without building
build.bat            # full release build
```

## Getting started

### End users (no Python required)

1. Download `PolyXRD-Setup-v5.5.0.exe` and `SHA256-v5.5.0.txt` from [Releases](https://github.com/PolyXRD/PolyXRD/releases).
2. Verify the SHA-256 checksum, install, and launch `PolyXRD.exe`.
3. The bundled COD-Inorg default library works out of the box. Optional database packages are published in [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases); mount them under **Database ▸ External Database Manager…**, effective immediately, no restart needed.

> Releases ship **program artifacts only** — the installer and its checksum file, no portable package, no databases. ICDD PDF-2 2004 is never redistributed; users with a valid license prepare it themselves.

### Developers (run from source)

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m polyxrd.main
python -m pytest -q
```

`run_dev.bat` at the repository root sets `PYTHONPATH=src` and launches the working tree directly — no PyInstaller build, always the latest source. Double-click it to start the GUI; it is the recommended entry point for manual acceptance.

### Building release artifacts

```bat
set POLYXRD_FLAVOR=release
build.bat
```

`build.bat` performs icon generation → PyInstaller packaging → bundled-library check → Inno Setup compilation → SHA-256 generation. `scripts/verify_release.ps1 -CheckDistVersion` re-validates the produced artifacts. The version is defined once in `src/polyxrd/__init__.py` and mirrored in `pyproject.toml`, `build.bat` (`APPVER`) and `scripts/PolyXRD-Setup.iss` (`AppVersion`).

## Builds & registration

| Build | Artifact | Registration |
|---|---|---|
| Release (public) | `PolyXRD-Setup-v<ver>.exe` | Required; `PXRD1-…` code entered through the in-app registration dialog |
| Internal evaluation (local only) | single-file `PolyXRD.exe`, not published | None; the build marks itself as internal |

Registration is shared across the PolyXRD family (PolyXRD-Reg). Only the installer and its `SHA256-v<ver>.txt` are attached to GitHub Releases.

## Links

| | |
|---|---|
| Downloads | [GitHub Releases](https://github.com/PolyXRD/PolyXRD/releases) |
| Release history | [changelog.md](changelog.md) |
| 中文文档（补充） | [README-CN.md](README-CN.md) |
| Developer entry point | [run_dev.bat](run_dev.bat) |
| Database packages | [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases) |
| License | [LICENSE](LICENSE) · [LICENSE-CN](LICENSE-CN) |
| Issues & feedback | [GitHub Issues](https://github.com/PolyXRD/PolyXRD/issues) |

## License

**Dual license (Academic + Commercial)**: free for academic research and education; any commercial use requires a separate written license from the copyright holder. Full terms: [LICENSE](LICENSE) (English) and [LICENSE-CN](LICENSE-CN) (中文). Upstream components — PySide6 (LGPL/GPL), pymatgen, spglib, COD and others — keep their own license terms.

This repository publishes program artifacts only. Databases are distributed separately, and ICDD PDF-2 2004 is never redistributed.
