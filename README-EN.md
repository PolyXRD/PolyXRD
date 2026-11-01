<div align="center">
  <img src="src/polyxrd/resources/app-icon.png" alt="PolyXRD Logo" width="120" />
  <h1>PolyXRD</h1>
  <p>
    <b>Comprehensive Analysis Suite for Polycrystalline X-ray Diffraction (XRD) Patterns</b>
    <br />
    Peak detection &nbsp;·&nbsp; Multi-phase qualitative search &nbsp;·&nbsp; Rietveld structure refinement &nbsp;·&nbsp; Le Bail cell refinement &nbsp;·&nbsp; Indexing &nbsp;·&nbsp; 3D structure visualization &nbsp;·&nbsp; Bundled COD-Inorg polyDB default library + external COD-Full / PDF2-2004
  </p>
  <p>
    <a href="https://github.com/PolyXRD/PolyXRD/releases"><img src="https://img.shields.io/badge/Release-v4.7.0-blue?style=flat-square" /></a>
    &nbsp;
    <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-lightgrey?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/UI-PySide6%20(Qt6)-41cd52?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Tests-1904%20passed-brightgreen?style=flat-square" />
  </p>
  <p><i>🌐 简体中文文档：[README.md](README.md)</i></p>
</div>

---

## 📖 About

**PolyXRD** is a **desktop application for comprehensive analysis of polycrystalline X-ray diffraction (XRD) patterns**, built for researchers in materials science, chemistry, and crystallography. It integrates the entire workflow — "**load raw XRD data → preprocess → peak detection → multi-phase qualitative search → Rietveld structure refinement → cell refinement → whole-pattern fitting → reporting**" — into a single unified PySide6 (Qt6) desktop application with a **Chinese / English / Japanese** trilingual interface.

Core design philosophy:

- **No Python environment required** — the installer bundles a complete Python 3.10 + PySide6 + pymatgen + scipy stack; target machines work out of the box.
- **Bundled default library, external extensions** — since v4.1.0 the installer / portable package **bundles the COD-Inorg polyDB default library** (77,500 phases) so search works out of the box; extension libraries (COD-Full etc.), the builder tools and the format specification live in a **separate repository**, [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase), distributed through its Releases. **This repository releases program artifacts only — no databases are uploaded here.** PDF2-2004 is an ICDD commercial library and is never redistributed.
- **Controllable algorithms + reproducible results** — every preprocessing/fitting step is parameterized, saveable, and replayable; project files (`.polyxrd` JSON) are fully serialized.
- **UI / algorithm layering** — MVVM architecture; the `services/` layer is pure algorithm code with no Qt dependency and can be unit-tested independently.

> 📋 **Changelog**: see [docs/CHANGELOG.md](docs/CHANGELOG.md) (Chinese).
> 🏗️ **Code structure & layering**: see [docs/代码结构说明.md](docs/代码结构说明.md) (Chinese).

---

## 🚧 In Development v4.7.0 (2026-10-31 · unreleased)

**Sequential multi-phase identification: confirm a phase → re-search the residual peaks → confirm the next** (see [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.7.0 and [docs/序贯多相鉴定-v4.7.0.md](docs/序贯多相鉴定-v4.7.0.md)):

- **Confirm from the candidate list to advance**: highlight a row and press “Confirm & Search Next”, or simply double-click it → the peaks that phase explains leave the problem → the remaining unexplained peaks are searched again → candidates for the next phase are listed. The loop runs until no peak is left, with every phase confirmed by the user.
- **Intensity residual bookkeeping** (`services/sequential.py`, following the layering of XinMatch `core/search/sequential.py`, reimplemented on this project's models): per-phase scale factor by least squares in count space, then peak-by-peak subtraction `I_obs − Σ scale·r`. A peak counts as explained only when its residual drops below 5 % of its own intensity; partially explained peaks stay in the residual set with their leftover intensity (overlaps are real physics). Lines weaker than 1 % of the strongest peak are neither searched nor counted in the coverage denominator.
- **Status strip + undo**: `2 phase(s) confirmed ｜ 12/25 peaks left ｜ 84.3 % intensity explained`; “Undo Last” pops the last phase and re-searches the returned residual peaks (back to full-pattern search at zero phases). Confirmed phases stay in the pattern overlay instead of being wiped by every residual round.
- **Same database throughout**: the data source is passed through, so an external library used in round one is used in every later round; confirmed phases are removed from the new candidate list (deduplicated by `db_id` first).
- **Tests**: 22 new cases in `tests/test_sequential_phase.py` (bookkeeping / state machine / VM / view), plus a real-pattern smoke run on sample 3-1 (Zincite 82.6 % → Hornblende +1.6 % → undo returns exactly). Full regression: **1904 passed / 5 skipped / 0 failed**.

---

## 🚧 In Development v4.6.0 (2026-10-31 · unreleased)

**External databases: unlimited count, multiple types, selected database drives every search** (details in Chinese: [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.6.0 and [docs/外挂数据库-多库挂载与选中检索-v4.6.0.md](docs/外挂数据库-多库挂载与选中检索-v4.6.0.md)):

- **Mount-type registry**: polyDB / PDF2 / user library become seed types; a new format registered via `register_kind()` automatically gets detection, probing, list rendering and search dispatch — no more if/elif edits in the mount module.
- **No mount-count limit**: the same type can be mounted any number of times (internal disk + portable drive + custom subset + a colleague's export); list, dropdown and persistence have no cap (a 60-mount stress test passes).
- **polyDB metadata + rename**: the manager shows dataset / variant / schema version / build date; user-added mounts can be renamed; built-in names stay tied to type/variant.
- **Selected database drives every entry point**: traditional search, quick identify, marked-peak re-match, **residual-peak search**, **Profile Fitting**, **toolbar/menu Identify**, the refinement wizard's reference-library tab, and **MCP** all follow the current data source. Profile Fitting on an external library pre-screens 200 d-I candidates from that library first, then re-ranks them by full-profile fitting (exhaustive fitting over 521k phases is not feasible).
- **Two real "selected but not used" bugs fixed**: the toolbar Identify action silently used the built-in 118-phase library regardless of the dropdown; residual search was hard-wired to `builtin`. Corrupt selected libraries now report "database cannot be used for search" instead of silently returning no candidates.
- **Tests**: full regression **1881 passed / 5 skipped / 0 failed**; real 3-library polyDB smoke (mount → select → traditional search / Profile Fitting → MCP database selection) all green, see `tools/smoke_v460_mounts.py`.

---

## 🆕 Latest Version v4.4.0 (2026-10-27 · pending release)

**Rebuilt "find a structure in the reference library" panel + one-shot legacy config cleanup** — closes the v4.2 leftovers P4.2/P4.3 (details in Chinese: [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.4.0 and [docs/RELEASE-NOTES-v4.4.0.md](docs/RELEASE-NOTES-v4.4.0.md)):

- **New first tab "Reference Library (polyDB)" in the refinement wizard**: search by formula / mineral name / space group / ID, or **match the strongest peaks** of the current pattern with Hanawalt d-I scoring. Added phases come with cell and atomic sites (sites expanded to the full cell by space group), ready to refine.
- **One-shot legacy config cleanup**: on startup it detects the old `cod_*` keys in `user_db_paths.json` and entries of removed engines in `db_mounts.json`, then offers to clean them — **settings only, never library files**; a folder that turns out to be a polyDB is re-mounted instead of being dropped.
- **i18n**: 32 new UI string keys per language (zh/en/ja key sets aligned at 1058 each).
- **No algorithm change**: scoring, refiner and reporting are identical to v4.3.0; MCP surface still 21 tools.
- **Tests**: full suite **1764 passed / 6 skipped / 0 failed**; 53 cases for the library panel and 37 for the config cleanup (16 of them added by a second independent review after the release).

| Asset | Size | SHA-256 (first 16) | Notes |
|---|---|---|---|
| `PolyXRD-Setup-v4.4.0.exe` | 288.3 MB | `b25d973fbb8a26ec…` | Release installer (registration enabled), bundles COD-Inorg |
| `PolyXRD-v4.4.0-Portable.zip` | 430.7 MB | `98c3f111a6d43e8e…` | Portable package (**internal evaluation build**), bundles COD-Inorg |
| `SHA256-v4.4.0.txt` | — | — | SHA-256 of the two program artifacts |

> Released: [Release v4.4.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.4.0) (3 assets, no databases).

---

## Previous Release v4.3.0 (2026-10-27 · released)

**polyDB d-spacing search returns to MCP** — closes the v4.2.1 leftover (details in Chinese: [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.3.0 and [docs/RELEASE-NOTES-v4.3.0.md](docs/RELEASE-NOTES-v4.3.0.md)):

- **New MCP tool `search_phases_by_d_peaks`**: Hanawalt search from measured d-spacings/intensities with `tolerance`/`tolerance_rel`/`min_match`/`limit`/`elements`/`max_ref_peaks`, backed by the polyDB bitmap inverted index + exact scoring.
- **Legacy `search_cod_by_d_peaks` works again**: keeps its old signature and forwards to polyDB; no more `deprecated`; adds `display_id`/`ref_id` compatibility fields and `mounted` state.
- **Same scoring path as the UI**: shares `phase_search` semantics with polyDB identification / PDF2 / user database d-peak search; no-mount, corrupted-layout and invalid-input cases return JSON errors instead of raising.
- **Tests**: new v4.3.0 MCP d-peak regression (real-library quartz search, element filter, no-mount/error paths); MCP tool count 20 → 21.

| Asset | Size | SHA-256 (first 16) | Notes |
|---|---|---|---|
| `PolyXRD-Setup-v4.3.0.exe` | 286.8 MB | `59c62ce98970…` | Release installer (registration enabled), bundles COD-Inorg |
| `PolyXRD-v4.3.0-Portable.zip` | 428.1 MB | `cb1ad1b6eed7…` | Portable package (**internal evaluation build**), bundles COD-Inorg |
| `SHA256-v4.3.0.txt` | — | — | SHA-256 of the two program artifacts |

👉 **Released**: [Release v4.3.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.3.0) — 3 assets, no databases.

---

## 📚 Previous Release v4.2.1 (2026-10-26 · released)

**Acceptance-fix release for v4.2.0** — 4 P1 compatibility/UX fixes + documentation corrections + build/verification hardening (details in Chinese: [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.2.1):

- **MCP old-name compatibility restored**: `search_cod_phases` accepts `97-1011097` / `96-101-1097` and restores `ref_id` / `display_id`; formulas are normalized (`SiO2` → `O2 Si`) and space groups ignore spaces (`Fd-3m`); `get_cod_phase_details(cod_id)` keeps the legacy argument name; `search_cod_online` returns JSON on network errors and honours `timeout`.
- **Wizard dead UI removed**: the retired local-CIF search box/button and its dead chain/i18n keys are gone; built-in 12 minerals + external CIF import, COD online search, and polyDB/PDF2/user-database structure auto-fill remain.
- **Documentation corrections**: baseline commit, tag/HEAD, net line count, import timing and "no UI change" claims fixed; design/execution plan statuses back-filled.
- **Build/verification hardening**: `verify_release.ps1` now has the missing `-SkipBundledDb` parameter, a stable SHA timestamp, and `-ExpectedFlavor` / `-CheckDistVersion` hard checks for dist flavour/version; the internal build cleans the flavour marker; MCP/fail-open/startup-log/golden tests added.

| Asset | Size | SHA-256 (first 16) | Notes |
|---|---|---|---|
| `PolyXRD-Setup-v4.2.1.exe` | 286.8 MB | `22ca6501cf39…` | Release installer (registration enabled), bundles COD-Inorg |
| `PolyXRD-v4.2.1-Portable.zip` | 428.1 MB | `8a6bbc6ba756…` | Portable package (**internal evaluation build**), bundles COD-Inorg |
| `SHA256-v4.2.1.txt` | — | — | SHA-256 of the two program artifacts |

👉 **Released**: [Release v4.2.1](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.2.1) — 3 assets, no databases.

---

## 📚 Previous Release v4.2.0 (2026-10-26 · released)

**Structural cleanup: the legacy COD sqlite runtime is retired** (details in Chinese: [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.2.0 and [docs/RELEASE-NOTES-v4.2.0.md](docs/RELEASE-NOTES-v4.2.0.md)):

- **Legacy runtime removed**: `services/cif_database.py` (2,421 lines) and `services/cod_local.py` (2,410 lines) are gone, together with `cod_db_path` / `cod_index_db_path` / `cod_svn_path` and six getters/setters in `config`. Only **polyDB + PDF2 + user-built libraries** remain at runtime.
- **Three pure modules extracted**: `cif_utils` (CIF parsing / sites / element checks), `phase_search` (Hanawalt scoring + pre-screening), `cif_minerals` (12 built-in mineral CIFs). None imports `sqlite3` or `PySide6`, none reads config paths (AST-asserted), so all are directly unit-testable.
- **Zero behavioural drift**: `phase_search` ships a 71 KB golden fixture recorded **before** the move (12 cases, 0 mismatch); the polyDB retrieval benchmark is **per-sample identical** to v4.1.2 (13 samples: same candidate IDs/names/ranks, top1 9/49 · top10 16 · MRR 0.213, 96.0 s vs 96.6 s).
- **MCP surface**: new `search_phases_polydb` / `get_phase_details`; `search_cod_phases` / `get_cod_phase_details` become thin aliases (existing clients keep working); `search_cod_by_d_peaks` returns a deprecated notice (d-spacing search is being rebuilt on polyDB).
- **Test suite tightened**: 9 legacy-only test files removed and 3 migrated, total 1809 → **1628**; a new static guard (`tests/test_v42_structure.py`) prevents the old modules from coming back. 12 legacy maintenance scripts archived under `tools/legacy_sqlite/`.

| Asset | Size | SHA-256 (first 16) | Notes |
|---|---|---|---|
| `PolyXRD-Setup-v4.2.0.exe` | 288.3 MB | `e46bfa79b53c47b4…` | Release installer (registration enabled), bundles COD-Inorg |
| `PolyXRD-v4.2.0-Portable.zip` | 430.7 MB | `7d9e504d7dda8c42…` | Portable package (**internal evaluation build**), bundles COD-Inorg |
| `SHA256-v4.2.0.txt` | — | — | SHA-256 of the two program artifacts |

👉 **Released**: [Release v4.2.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.2.0) — 3 assets, no databases (remote digests match the local manifest asset by asset).

> Previous release v4.1.2 (out-of-the-box search / discovery priority / legacy migration hints / minimal builds) — see [CHANGELOG §4.1.2](docs/CHANGELOG.md).

## 📚 Earlier Release v4.1.1 (2026-10-24 · released)

## 📚 Previous Release v4.1.1 (2026-10-24 · released)

**Hotfix: default-library refinement correctness + external engines on a clean install + reproducible build + release-policy cleanup**

**Hotfix: default-library refinement correctness + external engines on a clean install + reproducible build + release-policy cleanup** (details in Chinese: [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.1.1):

- **Fixed wrong simulated peaks from the bundled default library (P1)**: polyDB's `sites.bin` stores **asymmetric-unit** sites, but v4.1.0 fed them to the refiner as a full cell — high-symmetry phases got fake peaks (Corundum measured a 6.8° fake peak at 100% while the true 35.14/43.34 peaks were lost). v4.1.1 expands sites by space group at the polyDB exit (idempotent) and adds a defensive expansion in the refiner; Corundum now gives **57.49/43.34/35.14**.
- **GSAS-II / MAUD available on a clean install (P1)**: when only the bundled polyDB is present (no CIF file), the resolver now synthesizes a CIF from atomic sites into the CIF cache and back-fills `cif_path` (1.3 ms → 4 ms, `structure match 1/1`); CIF export has the same fallback.
- **Reproducible build (P0)**: `scripts/_build_post.py` had been silently ignored by `.gitignore` and was never committed (a fresh clone could not bundle the default library, write VERSION.txt or portable extras). It is now tracked, guarded by a test, and every critical build step fails hard on error.
- **Release policy cleanup**: this repository's Releases ship **program artifacts only (3 assets)** — no database packages; the default library is bundled and extension libraries are distributed by [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase/releases).
- **Documentation errata**: bundled library phase count is **77,500** (matching the bundled `meta.json`); English README synced to v4.1.1.

| Asset | Size | SHA-256 (first 16) | Notes |
|---|---|---|---|
| `PolyXRD-Setup-v4.1.1.exe` | 286.8 MB | `bb43ecc12d2d…` | Release installer (registration enabled), bundles COD-Inorg |
| `PolyXRD-v4.1.1-Portable.zip` | 428.2 MB | `09da5ecc35be…` | Portable package (**internal evaluation build**, red "Internal Evaluation" badge), bundles COD-Inorg |
| `SHA256-v4.1.1.txt` | — | — | SHA-256 of the two program artifacts |

👉 **Released**: [Release v4.1.1](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.1.1) — 3 assets; remote digests verified against the local checksums.

> PDF2-2004 is an ICDD commercial library and never appears in any Release. COD-Full and other extension libraries are distributed by [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases).

## 📚 Previous Release v4.0.0 (2026-10-23 · released)

**polyDB — a purpose-built external phase-database format** (sites expanded, 77,500-phase inorganics library; details in [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.0.0). This repository releases program artifacts only; databases live in [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase).

## 📚 Previous Release v3.2.0 (2026-10-20)

**Large-database usability fixes** — makes 20-30 GB external phase databases actually usable. Full details (Chinese): [docs/CHANGELOG.md](docs/CHANGELOG.md) §3.2.0 and [docs/3COD数据库验收报告-20261020.md](docs/3COD数据库验收报告-20261020.md).

- **A mounted database was silently ignored**: index-path resolution assumed the index always sat next to the COD directory and never looked at the path the user had imported — the manager showed "mounted" while searches kept reading the old database (or reported "not ready"). Read paths now prefer the user-imported file; the index builder deliberately does not, so an external library can never become a write target.
- **Read-only connections for retrieval**: every query used to open the index writable and re-run schema/DDL. On a 28 GB library that took **65 s** for `is_ready()` (returning False) and made `stats()` raise `database is locked`. Now **0.013 s / 0.125 s**, with the connection reused and no leak on error.
- **Index-build progress**: a million-phase library needs 5-10 min to build its strong-peak index on first mount, previously with no feedback at all. Three stages (count phases → build peak index → read metadata) are now reported in the status bar.
- **Measured on 3COD-Full** (28.17 GiB / 1.96 M phases): `identify_with_cod_local` 8-13 s, top-1 matches ground truth, database file size/mtime unchanged.
- **Usage note**: bigger is not better. Mounting a 1.19 M-phase library as the COD-inorganics slot pushed CaF2 out of the top-20 on sample 4-1 (rank 2 before) — ranking dilution from a 16.7x larger candidate pool, not a retrieval defect.

👉 [Download v3.2.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v3.2.0) (installer + internal evaluation portable + SHA256)

## 📚 Earlier Release v2.5.0 (2026-10-01)

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
  - **Built-in engine `builtin` (default for the short path)** = **structure-free whole-pattern fitting (Le Bail grade, fast)**: uses CIF `|F|²` reference peaks + per-phase isotropic cell scaling
    + March-Dollase texture + Chebyshev background + statistical weights; yields usable wR/Rp without installing external programs;
    it does **not** refine atomic coordinates/occupancies/ADPs, so its wt% values are **relative quantification**, not strict mass fractions.
  - **v5.0.0 new engine `polyxrd.refinement` (wired to the GUI: pick `refinement` in the engine dropdown)**: a complete forward model —
    Cromer–Mann scattering factors, `I ∝ m|F|²·LP/V²` intensity convention, Kα2 doublet separation, TCH profile synthesis,
    crystallite/strain broadening, Poisson weights `w=1/max(y,1)`; solved by **variable projection** (scales + background
    closed-form least squares each iteration) with a staged protocol (positions → profile → preferred orientation → sample
    broadening → structure), per-stage rollback and early convergence; quantification uses Hill–Howard with the **density
    convention** (`W ∝ S·M_cell/V`) plus scale-error propagation; ships GSAS-II-style diagnostics (rank deficiency, condition
    number, parameter correlation, unexplained residual peaks) and applies space-group cell constraints automatically
    (constants fixed, `b=a`-style ties placed in the constraint system).
    Validation on real samples: [docs/基准报告-精修-v5.0.0.md](docs/基准报告-精修-v5.0.0.md) — four-phase sample total
    absolute deviation **7.16 pp** (legacy engine 21.40 pp), two-phase 50/50 standard **±2.00 pp**.
    ⚠️ Intensities come from **structure factors**, so **every phase must carry atomic sites**. When phases come
    straight from search results (built-in mineral table / PDF2 / some user-library entries carry reference peaks only),
    sites are **filled automatically**: formula + space group + cell are matched against polyDB and that entry's
    full-cell sites are copied (`services/structure_augment.py`, log line `[cif] <phase>: 补齐位点 ← polyDB COD xxx`).
    Only phases that still cannot be resolved fall back to the built-in engine, with an explicit "engine fallback"
    diagnostic (never a silent swap). Measured on sample 2-1, two phases straight from search:
    Rwp 21.12%, wt% 47.99/52.01 (true 50/50).
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

### ⑥ External database services (polyDB / COD / PDF2 / XinMatch)
| Database | Scale | Purpose |
|---|---|---|
| COD Inorganics | 71,199 phases | Precomputed d-I peaks + pre-truncated strong-peak lists + Hanawalt pre-screening — the **primary search database**, fastest. Published by default in **slim index form** (362 MB, `COD_inorganics_index.sqlite`): atomic sites fully retained, CIFs read on demand from a local `cod/cif` archive, with automatic fallback to the COD online API. The full embedded edition (1.19 GB) can still be imported; the two are row-for-row identical |
| COD Full Index | 113,223 entries | Index of the complete COD CIF collection (432 MB, no embedded CIFs), serving the "COD Full" and "Built-in + Full merged" search sources |
| PDF2-2004 | 163,834 phases | ICDD PDF-2 2004, with space groups and cell parameters, for comparison against the commercial library |
| **polyDB** (v4.0.0) | 77,500 / 521,361 phases | PolyXRD's own columnar container (`meta.json` + `index.sqlite` + peak matrices + d-bin bitmap + element bitmaps + atomic-site sidecar). Read-only mmap, zero parse on open, candidates decoded per row; candidates carry asymmetric-unit atomic sites and can go straight into refinement. Mount a `.polyDB` directory from any folder |

- Path priority: **persistent path imported via GUI (`~/.polyxrd/user_db_paths.json`) > default location (used only if it exists) > `~/.polyxrd/cif_db/` fallback**
- **Database-type validation on import**: the three databases share table names (COD Inorganics and PDF2 both use `phases`), so picking the wrong slot raises a prompt instead of failing silently
- Effective immediately after import, **no restart**; the "database source" dropdown in the phase-analysis panel refreshes in sync; unmounted sources are greyed out
- The databases are fully independent — you can mount just one; the bundled COD-Inorg library (77,500 phases) is available out of the box, and the built-in **106 reference phases** still work
- **Where to download databases** (since v4.1.1): this repository and its Releases ship **program artifacts only (3 assets)**; the bundled COD-Inorg library needs no download; extension libraries are published in [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases) (current tag `20261021`; see that repository's Releases page for what is currently uploaded), together with the builder tools and format spec

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

> The COD-Inorg polyDB default library (77,500 phases) is bundled; the program also works with its built-in **106** common reference phases.
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

For the latest version and the full changelog, see [docs/CHANGELOG.md](docs/CHANGELOG.md) (Chinese). **Program artifacts** (Setup installer + Portable package + SHA256) are available on the [👉 Releases page](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.0.0); **database packages** are published separately in [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases). SHA-256 checksums are published alongside each release.

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
