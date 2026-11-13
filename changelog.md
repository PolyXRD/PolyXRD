# Changelog

All notable PolyXRD releases, newest first. Installers and SHA-256 checksums are published on the [Releases page](https://github.com/PolyXRD/PolyXRD/releases). Historical release notes were migrated here from the previous README; `README.md` now keeps only the current version and links.

This file and `README.md` are updated together for every GitHub release. Databases are distributed in [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases); ICDD PDF-2 2004 is never redistributed.

## v5.5.0 — 2026-11-13

**Refinement correctness, opt-in amorphous modelling, and a corrected internal-standard workflow.**

- **Covariance fix**: the phase-scale covariance block is now read at the correct offset via `linear_block_slices` (previously `cov[:n_phase]` picked profile parameters, understating wt% error bars by 10–30x and producing false `SCALE_CORRELATED` findings). `full_covariance` now uses the SVD of the design matrix instead of `pinv(MᵀM)`, which preserves positive semi-definiteness; rho is clipped before computing `sigma_ratio`, so a perfectly negative correlation no longer drops the entire finding set.
- **Amorphous humps (opt-in)**: unit-area pseudo-Voigt columns join the linear layer only (`Problem.set_amorphous_humps`), so Hill–Howard quantification and phase-scale covariance are untouched. A background-sensitivity check reports `doc_spread` / `doc_reliable`; when the area-based degree of crystallinity swings between background models, the diagnostic reports the range instead of a number. Structured diagnostic `diag.refinement.amorphous_hump` with zh/en/ja translations.
- **Absolute amorphous content**: `absolute_amorphous_from_standard` now subtracts the internal standard itself (`standard_wt_pct`) — the previous chain over-reported the amorphous fraction by one standard loading. `refine_with_internal_standard` reports `unmodelled_wt_pct`.
- **Per-run `bg_deg` override** for background node count; tier defaults are unchanged.
- Release policy: English-only release notes, README reduced to current version + links, changelog maintained here.

Validation: 457 core refinement tests pass; the quality gate now tracks README/changelog version synchronisation.

## v5.4.0 — 2026-11-11

Colour-icon plot toolbar: nine programmatic QPainter icons (zero image assets, crisp on HiDPI) replace the text buttons, and the eight matplotlib navigation actions are recoloured. Crosshair readout follows the cursor; export moves to the navigation bar's save action. UI-only release, no algorithm changes.

## v5.3.0 — 2026-11-10

Anisotropic broadening and low-angle tail profiles, plus interval-based reporting for quantitative results. Over the seven-sample MAUD benchmark the mean Rwp dropped from 11.66% to 10.91% (reference implementation 11.23%).

## v5.2.0 — 2026-11-05

Systematic intensity-error models (surface roughness and microabsorption), a NIST-based per-element attenuation table with uncertainty propagation, the discriminating-peak guard (`PHASE_UNSUPPORTED` / `PHASE_FRACTION_UNVERIFIABLE`), conclusion-first diagnostic ordering, corrected built-in R-3c coordinates, and three GSAS-II bridge fixes.

## v4.7.0 — 2026-10-31

Sequential multi-phase identification: confirm a phase, subtract its explained intensity, then re-search the residual peaks. Adds a status strip and undo.

## v4.5.0 — 2026-10-29

Installation reliability fixes (write-permission failure under `Program Files`, read-only PDF2 mounting, element-filter bitmap misalignment for Z >= 45). No change to algorithm conventions.

## v4.4.0 — 2026-10-27

Rebuilt reference-library panel in the refinement wizard (formula / mineral / space-group / ID search, strongest-peak scoring), plus one-shot legacy configuration cleanup and 32 new i18n keys per language.

## v4.3.0 — 2026-10-27

`search_phases_by_d_peaks` MCP tool with Hanawalt d-spacing scoring; legacy `search_cod_by_d_peaks` restored and sharing the same scoring path as the UI.

## v4.2.1 — 2026-10-26

Acceptance fixes for 4.2.0: MCP old-name compatibility, formula / space-group normalisation, removal of dead wizard UI, and build-verification hardening.

## v4.2.0 — 2026-10-26

Retired the legacy COD SQLite runtime (about 4,800 lines) and extracted three pure, Qt-free modules (`cif_utils`, `phase_search`, `cif_minerals`) with a golden-fixture guarantee of zero behavioural drift.

## v4.1.1 — 2026-10-24

Hotfix: correct full-cell site expansion for the bundled default library (fixes spurious simulated peaks), external refinement engines on clean installs, reproducible builds, and release-policy cleanup.

## v4.1.0 — 2026-10-23

COD-Inorg becomes the only bundled default library (77,500 phases, 86 MiB, eight polyDB segments); all legacy-format runtime code removed.

## v4.0.0 — 2026-10-23

Introduced polyDB, a purpose-built external phase-database format. This repository releases program artifacts only.

## v3.2.0 — 2026-10-20

Large-database usability fixes for 20–30 GB external phase databases.

## v3.1.0 — 2026-10-18

Third-party four-table library support, mounting from arbitrary locations, and full code-review fixes.

## v3.0.0 — 2026-10-17

WPSM full-pattern fitting search (off by default).

## v2.5.0 — 2026-10-01

Search-chain enhancements, combination-strategy tuning, and residual-peak search validated on a 13-sample benchmark.

## Earlier releases (<= v2.4.0)

See the archived [README-EN.md](README-EN.md) and the release notes on the [Releases page](https://github.com/PolyXRD/PolyXRD/releases).
