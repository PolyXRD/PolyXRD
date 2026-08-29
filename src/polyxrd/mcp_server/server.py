"""
PolyXRD MCP Server — main entry point.

Exposes PolyXRD's XRD analysis pipeline as MCP tools so that any
MCP-compatible AI client (Claude Desktop, TraeCode, etc.) can:
  - Load & preprocess XRD data
  - Detect & fit peaks
  - Search the COD inorganic database (71,199 phases)
  - Identify phases
  - Run Rietveld refinement
  - Simulate patterns from CIF structures
  - Export results & manage projects

Transport: stdio (default) or SSE/HTTP.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from mcp.server import MCPServer

from polyxrd.mcp_server.session import get_session

# ── Create MCP server instance ────────────────────────────────
mcp = MCPServer(
    name="polyxrd",
    version="0.9.0",
    title="PolyXRD — XRD Analysis Suite",
    description="AI-friendly XRD analysis: load → preprocess → peaks → phases → Rietveld → export",
)


# ════════════════════════════════════════════════════════════════
#  1. DATA LOADING
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def load_xrd_data(
    file_path: str,
    wavelength: Optional[float] = None,
) -> str:
    """Load an XRD data file (.xrdml, .xy, .csv, .txt, .raw, .brml).

    Args:
        file_path: Absolute path to the XRD data file.
        wavelength: X-ray wavelength in Angstroms. If omitted, uses Cu Kα1 (1.5406 Å).

    Returns:
        JSON summary: data points, 2θ range, wavelength, file format.
    """
    from polyxrd.services.data_loader import DataLoader

    session = get_session()
    loader = DataLoader()
    data = loader.load(file_path, wavelength=wavelength)

    session.raw_data = data
    session.processed_data = None  # reset pipeline
    session.source_file = file_path

    result = {
        "status": "ok",
        "file_path": file_path,
        "n_points": len(data),
        "two_theta_min": round(float(data.two_theta[0]), 4),
        "two_theta_max": round(float(data.two_theta[-1]), 4),
        "wavelength": data.wavelength,
        "intensity_min": round(float(data.intensity.min()), 2),
        "intensity_max": round(float(data.intensity.max()), 2),
        "metadata": data.metadata,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def get_data_summary() -> str:
    """Get a summary of the currently loaded XRD data (raw or processed).

    Returns:
        JSON with data points, 2θ range, intensity stats, processing history.
    """
    session = get_session()
    data = session.current_data
    if data is None:
        return json.dumps({"error": "No XRD data loaded. Call load_xrd_data first."})

    result = {
        "source_file": session.source_file,
        "n_points": len(data),
        "two_theta_min": round(float(data.two_theta[0]), 4),
        "two_theta_max": round(float(data.two_theta[-1]), 4),
        "wavelength": data.wavelength,
        "intensity_min": round(float(data.intensity.min()), 4),
        "intensity_max": round(float(data.intensity.max()), 4),
        "intensity_mean": round(float(data.intensity.mean()), 4),
        "is_processed": session.processed_data is not None,
        "metadata": data.metadata,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
#  2. PREPROCESSING
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def preprocess_data(
    method: str = "snip",
    smooth_method: str = "savgol",
    smooth_window: int = 11,
    strip_ka2: bool = False,
    normalize: bool = True,
    two_theta_min: Optional[float] = None,
    two_theta_max: Optional[float] = None,
) -> str:
    """Preprocess XRD data: background removal, smoothing, Kα2 stripping, normalization.

    Args:
        method: Background removal method. One of: "snip", "als", "polyfit", "median", "rolling".
        smooth_method: Smoothing method. One of: "savgol", "gaussian", "moving", "median".
        smooth_window: Smoothing window size (odd number, e.g. 11).
        strip_ka2: Whether to strip Kα2 peaks.
        normalize: Whether to normalize intensity to [0, 1].
        two_theta_min: Crop lower 2θ bound (optional).
        two_theta_max: Crop upper 2θ bound (optional).

    Returns:
        JSON summary of the processed data.
    """
    from polyxrd.services.data_preprocessor import DataPreprocessor

    session = get_session()
    data = session.raw_data
    if data is None:
        return json.dumps({"error": "No XRD data loaded. Call load_xrd_data first."})

    preprocessor = DataPreprocessor()

    # 1. Crop
    if two_theta_min is not None or two_theta_max is not None:
        lo = two_theta_min or float(data.two_theta[0])
        hi = two_theta_max or float(data.two_theta[-1])
        data = data.crop(lo, hi)

    # 2. Background subtraction
    bg_result = preprocessor.subtract_background(data, method=method)
    data = bg_result.corrected

    # 3. Smoothing
    data = preprocessor.smooth(data, method=smooth_method, window=smooth_window)

    # 4. Kα2 stripping
    if strip_ka2:
        data = preprocessor.strip_ka_alpha2(data)

    # 5. Normalization
    if normalize:
        data = data.normalize()

    session.processed_data = data

    result = {
        "status": "ok",
        "n_points": len(data),
        "two_theta_min": round(float(data.two_theta[0]), 4),
        "two_theta_max": round(float(data.two_theta[-1]), 4),
        "bg_method": method,
        "smooth_method": smooth_method,
        "smooth_window": smooth_window,
        "stripped_ka2": strip_ka2,
        "normalized": normalize,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
#  3. PEAK DETECTION & FITTING
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def find_peaks(
    height: float = 0.05,
    distance: float = 5.0,
    prominence: float = 0.01,
    width: Optional[float] = None,
) -> str:
    """Detect peaks in the current XRD data.

    Args:
        height: Minimum peak height (relative to max intensity, 0-1).
        distance: Minimum 2θ distance between peaks (degrees).
        prominence: Peak prominence threshold (relative to max intensity).
        width: Minimum peak width (optional).

    Returns:
        JSON list of detected peaks: 2θ, intensity, d-spacing, FWHM.
    """
    from polyxrd.services.peak_finder import PeakFinder

    session = get_session()
    data = session.current_data
    if data is None:
        return json.dumps({"error": "No XRD data loaded. Call load_xrd_data first."})

    finder = PeakFinder()
    peaks = finder.find_peaks(
        data,
        height=height,
        distance=distance,
        prominence=prominence,
        width=width,
    )
    session.peak_list = peaks

    result = {
        "n_peaks": len(peaks),
        "peaks": [
            {
                "two_theta": round(p.two_theta, 4),
                "d_spacing": round(p.d_spacing, 4) if p.d_spacing else None,
                "intensity": round(p.intensity, 4),
                "fwhm": round(p.fwhm, 4) if p.fwhm else None,
            }
            for p in peaks.peaks
        ],
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def list_peaks() -> str:
    """List all previously detected peaks in the session.

    Returns:
        JSON with peak count and list of {2θ, d, intensity, FWHM}.
    """
    session = get_session()
    if session.peak_list is None or len(session.peak_list) == 0:
        return json.dumps({"error": "No peaks detected. Call find_peaks first."})

    result = {
        "n_peaks": len(session.peak_list),
        "source": session.peak_list.source,
        "peaks": [
            {
                "two_theta": round(p.two_theta, 4),
                "d_spacing": round(p.d_spacing, 4) if p.d_spacing else None,
                "intensity": round(p.intensity, 4),
                "fwhm": round(p.fwhm, 4) if p.fwhm else None,
            }
            for p in session.peak_list.peaks
        ],
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def fit_peaks(
    model: str = "voigt",
    fit_range: Optional[float] = 2.0,
) -> str:
    """Fit detected peaks with a profile model (Voigt, Gaussian, Lorentzian, pseudo-Voigt).

    Args:
        model: Peak shape model. One of: "voigt", "gaussian", "lorentzian", "pseudo_voigt", "emg".
        fit_range: Fitting range in degrees (peak center ± fit_range). Set to None for auto.

    Returns:
        JSON with fit results: position, amplitude, FWHM, R² for each peak.
    """
    from polyxrd.services.peak_fitter import PeakFitter

    session = get_session()
    data = session.current_data
    if data is None:
        return json.dumps({"error": "No XRD data loaded."})
    if session.peak_list is None or len(session.peak_list) == 0:
        return json.dumps({"error": "No peaks detected. Call find_peaks first."})

    fitter = PeakFitter()
    results = []
    for peak in session.peak_list.peaks:
        rng = (peak.two_theta - fit_range, peak.two_theta + fit_range) if fit_range else None
        fit = fitter.fit_peak(data, peak, model=model, fit_range=rng)
        results.append(fit)
    session.fit_results = results

    out = []
    for i, fit in enumerate(results):
        out.append({
            "peak_index": i,
            "center": round(fit.center, 4) if hasattr(fit, "center") else None,
            "amplitude": round(fit.amplitude, 4) if hasattr(fit, "amplitude") else None,
            "fwhm": round(fit.fwhm, 4) if hasattr(fit, "fwhm") else None,
            "r_squared": round(fit.r_squared, 4) if hasattr(fit, "r_squared") else None,
        })

    return json.dumps({"n_fitted": len(out), "fits": out}, ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
#  4. PHASE IDENTIFICATION
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def search_phases(
    elements: Optional[list[str]] = None,
    top_n: int = 10,
    tolerance: float = 0.15,
) -> str:
    """Identify phases from detected peaks using the built-in reference database.

    Args:
        elements: List of elements that must be present (e.g. ["Fe", "O"]).
        top_n: Number of top candidates to return.
        tolerance: 2θ matching tolerance in degrees.

    Returns:
        JSON with ranked phase candidates: name, formula, FOM, matched peaks.
    """
    from polyxrd.services.phase_identifier import PhaseIdentifier

    session = get_session()
    data = session.current_data
    if data is None:
        return json.dumps({"error": "No XRD data loaded."})

    identifier = PhaseIdentifier()
    results = identifier.identify(
        data=data,
        peaks=session.peak_list,
        elements=elements,
        top_n=top_n,
        tolerance=tolerance,
    )
    session.phase_matches = results

    out = []
    for r in results:
        out.append({
            "name": r.phase.name,
            "formula": r.phase.formula,
            "space_group": r.phase.space_group,
            "score": round(r.score, 4),
            "matched_peaks": r.matched_peaks,
            "total_peaks": r.total_peaks,
            "coverage_pct": round(r.coverage, 1),
            "confidence": r.confidence,
            "method": r.method,
        })

    return json.dumps({"n_results": len(out), "matches": out}, ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
#  5. COD DATABASE SEARCH
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def search_cod_phases(
    query: str,
    limit: int = 20,
) -> str:
    """Search the COD inorganic database (71,199 phases) by formula, space group, or COD ID.

    Args:
        query: Search keyword. Examples: "SiO2", "quartz", "Fd-3m", "1011097".
        limit: Maximum number of results to return (default 20).

    Returns:
        JSON list of matching phases with cod_id, formula, space group, cell parameters.
    """
    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase()
    results = db.search_cod_phases(query, limit=limit)

    return json.dumps(
        {"query": query, "n_results": len(results), "phases": results},
        ensure_ascii=False,
        default=str,
    )


@mcp.tool()
def search_cod_by_d_peaks(
    d_values: list[float],
    intensities: Optional[list[float]] = None,
    tolerance: float = 0.02,
    min_match: int = 3,
    limit: int = 20,
) -> str:
    """Search the COD database by measured d-spacing peaks (Hanawalt-style search).

    Args:
        d_values: List of measured d-spacing values in Angstroms.
        intensities: Corresponding peak intensities (optional but recommended).
        tolerance: d-value matching tolerance in Angstroms.
        min_match: Minimum number of matched peaks for a phase to be included.
        limit: Maximum number of results to return.

    Returns:
        JSON with ranked phase matches: cod_id, formula, match statistics.
    """
    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase()
    results = db.search_cod_by_d_peaks(
        measured_d=d_values,
        measured_i=intensities,
        tolerance=tolerance,
        min_match=min_match,
        limit=limit,
    )

    return json.dumps(
        {"n_results": len(results), "matches": results},
        ensure_ascii=False,
        default=str,
    )


@mcp.tool()
def get_cod_phase_details(cod_id: int) -> str:
    """Get full details of a COD phase including d-I peak list.

    Args:
        cod_id: COD database entry ID (e.g. 1011097).

    Returns:
        JSON with phase info: formula, space group, cell params, d-I peak list.
    """
    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase()
    phase = db.get_cod_phase(cod_id)

    if phase is None:
        return json.dumps({"error": f"COD ID {cod_id} not found in database."})

    return json.dumps(phase, ensure_ascii=False, default=str)


@mcp.tool()
def search_cod_online(
    formula: Optional[str] = None,
    mineral_name: Optional[str] = None,
    space_group: Optional[str] = None,
    timeout: int = 15,
) -> str:
    """Search the Crystallography Open Database (COD) online for crystal structures.

    Args:
        formula: Chemical formula (e.g. "SiO2").
        mineral_name: Mineral name (e.g. "quartz").
        space_group: Space group symbol (e.g. "Fd-3m").
        timeout: Request timeout in seconds.

    Returns:
        JSON list of COD entries with cod_id, name, formula.
    """
    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase()
    results = db.search_cod(
        formula=formula,
        mineral_name=mineral_name,
        space_group=space_group,
        timeout=timeout,
    )

    return json.dumps(
        {"n_results": len(results), "entries": results},
        ensure_ascii=False,
        default=str,
    )


# ════════════════════════════════════════════════════════════════
#  6. PATTERN SIMULATION
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def simulate_pattern(
    cif_path: str,
    wavelength: float = 1.5406,
    two_theta_min: float = 10.0,
    two_theta_max: float = 90.0,
    peak_width: float = 0.15,
    include_kalpha2: bool = False,
) -> str:
    """Simulate an XRD pattern from a CIF structure file.

    Args:
        cif_path: Path to a .cif crystal structure file.
        wavelength: X-ray wavelength in Angstroms (default Cu Kα1 = 1.5406).
        two_theta_min: Minimum 2θ (degrees).
        two_theta_max: Maximum 2θ (degrees).
        peak_width: Peak width for generating continuous pattern.
        include_kalpha2: Whether to include Kα2 peaks.

    Returns:
        JSON summary of the simulated pattern with top peaks.
    """
    from polyxrd.services.structure_simulator import StructureSimulator

    simulator = StructureSimulator()
    pattern = simulator.simulate(
        structure=cif_path,
        wavelength=wavelength,
        two_theta_range=(two_theta_min, two_theta_max),
        peak_width=peak_width,
        include_kalpha2=include_kalpha2,
    )

    # Store in session
    session = get_session()
    session.raw_data = pattern
    session.source_file = f"simulated:{cif_path}"

    # Find top 10 peaks in the simulated pattern
    import numpy as np
    from scipy import signal as scipy_signal

    peak_indices, _ = scipy_signal.find_peaks(
        pattern.intensity,
        height=0.01 * pattern.intensity.max(),
        distance=int(1.0 / np.mean(np.diff(pattern.two_theta))),
    )
    top_indices = sorted(peak_indices, key=lambda i: -pattern.intensity[i])[:10]

    result = {
        "status": "ok",
        "n_points": len(pattern),
        "two_theta_min": round(float(pattern.two_theta[0]), 4),
        "two_theta_max": round(float(pattern.two_theta[-1]), 4),
        "wavelength": pattern.wavelength,
        "n_peaks_total": len(peak_indices),
        "top_peaks": [
            {
                "two_theta": round(float(pattern.two_theta[i]), 4),
                "d_spacing": round(float(pattern.d_spacing[i]), 4),
                "intensity": round(float(pattern.intensity[i]), 4),
            }
            for i in top_indices
        ],
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
#  7. RIETVELD REFINEMENT
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def refine_rietveld(
    phase_names: Optional[list[str]] = None,
    strategy: str = "sequential",
    engine: str = "builtin",
    max_cycles: int = 20,
) -> str:
    """Run Rietveld structure refinement on the loaded data with selected phases.

    Args:
        phase_names: List of phase names to refine. If omitted, uses all
            phases from the last search_phases result.
        strategy: Refinement strategy. One of: "sequential", "auto", "manual".
        engine: Refinement engine. One of: "gsas2", "powerxrd", "builtin".
        max_cycles: Maximum number of refinement cycles.

    Returns:
        JSON with refinement results: Rwp, Rp, GoF, phase fractions, lattice params.
    """
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    session = get_session()
    data = session.current_data
    if data is None:
        return json.dumps({"error": "No XRD data loaded."})

    # Gather phases to refine
    phases: list = []
    if phase_names:
        # Match from phase_matches or selected_phases
        from polyxrd.models.phase import Phase
        for name in phase_names:
            for r in session.phase_matches:
                if r.phase.name == name:
                    phases.append(r.phase)
                    break
    else:
        # Use top-N from last search
        for r in session.phase_matches[:5]:
            phases.append(r.phase)

    if not phases:
        return json.dumps({"error": "No phases selected. Run search_phases first or provide phase_names."})

    session.selected_phases = phases
    refiner = RietveldRefiner()
    result = refiner.refine(
        data=data,
        phases=phases,
        strategy=strategy,
        engine=engine,
        max_cycles=max_cycles,
    )
    session.refinement_result = result

    out = {
        "status": "ok",
        "rwp": round(result.rwp, 4) if hasattr(result, "rwp") else None,
        "rp": round(result.rp, 4) if hasattr(result, "rp") else None,
        "gof": round(result.gof, 4) if hasattr(result, "gof") else None,
        "time_seconds": round(result.time_seconds, 2) if hasattr(result, "time_seconds") else None,
        "n_phases": len(phases),
        "phases": [],
    }
    for p in result.phases if hasattr(result, "phases") else []:
        out["phases"].append({
            "name": p.name if hasattr(p, "name") else str(p),
            "weight_fraction": round(p.weight_fraction, 4) if hasattr(p, "weight_fraction") else None,
            "lattice": p.lattice.to_dict() if hasattr(p, "lattice") and p.lattice else None,
        })

    return json.dumps(out, ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
#  8. EXPORT & PROJECT MANAGEMENT
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def export_results(
    output_dir: str,
    format: str = "json",
) -> str:
    """Export analysis results (Rietveld refinement, phase report) to files.

    Args:
        output_dir: Directory path for output files.
        format: Output format. One of: "json", "txt", "csv", "all".

    Returns:
        JSON with list of generated file paths.
    """
    from polyxrd.services.export_service import ExportService

    session = get_session()
    exporter = ExportService()
    generated: list[str] = []

    # Export Rietveld results if available
    if session.refinement_result is not None:
        files = exporter.export_rietveld_result(
            session.refinement_result, output_dir, format=format
        )
        generated.extend(files)

    # Export phase report if phases available
    if session.phase_matches:
        phases = [r.phase for r in session.phase_matches]
        files = exporter.export_phase_report(phases, output_dir, format="json")
        generated.extend(files)

    if not generated:
        return json.dumps({"error": "No results to export. Run analysis first."})

    return json.dumps({"status": "ok", "files": generated}, ensure_ascii=False, default=str)


@mcp.tool()
def save_project(file_path: str) -> str:
    """Save the current analysis session as a .pxrd project file.

    Args:
        file_path: Path for the .pxrd project file.

    Returns:
        JSON confirming save success.
    """
    from polyxrd.services.project_service import ProjectService

    session = get_session()
    if session.current_data is None:
        return json.dumps({"error": "No data loaded to save."})

    service = ProjectService()
    service.save_project(
        file_path=file_path,
        data=session.current_data,
        peaks=session.peak_list,
        phases=[r.phase for r in session.phase_matches],
        refinement_result=session.refinement_result,
    )
    session.project_file = file_path

    return json.dumps({"status": "ok", "file_path": file_path}, ensure_ascii=False)


@mcp.tool()
def load_project(file_path: str) -> str:
    """Load a .pxrd project file, restoring data, peaks, phases, and results.

    Args:
        file_path: Path to the .pxrd project file.

    Returns:
        JSON summary of the restored session.
    """
    from polyxrd.services.project_service import ProjectService

    session = get_session()
    service = ProjectService()
    project = service.load_project(file_path)

    session.raw_data = project.data
    session.peak_list = project.peaks
    session.phase_matches = project.phase_matches or []
    session.refinement_result = project.refinement_result
    session.project_file = file_path
    session.source_file = file_path

    result = {
        "status": "ok",
        "file_path": file_path,
        "n_points": len(project.data) if project.data else 0,
        "n_peaks": len(project.peaks) if project.peaks else 0,
        "n_phases": len(project.phase_matches) if project.phase_matches else 0,
        "has_refinement": project.refinement_result is not None,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
#  9. SESSION MANAGEMENT
# ════════════════════════════════════════════════════════════════

@mcp.tool()
def get_session_status() -> str:
    """Get the current session status: what data/peaks/phases/results are loaded.

    Returns:
        JSON summary of the session state.
    """
    session = get_session()

    result = {
        "has_raw_data": session.raw_data is not None,
        "has_processed_data": session.processed_data is not None,
        "source_file": session.source_file,
        "n_peaks": len(session.peak_list) if session.peak_list else 0,
        "n_phase_matches": len(session.phase_matches),
        "n_selected_phases": len(session.selected_phases),
        "has_refinement": session.refinement_result is not None,
        "project_file": session.project_file,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def reset_session() -> str:
    """Clear all session state (data, peaks, phases, results).

    Returns:
        JSON confirming reset.
    """
    get_session().reset()
    return json.dumps({"status": "ok", "message": "Session cleared."}, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  Entry point
# ════════════════════════════════════════════════════════════════

def main() -> None:
    """Run the MCP server via stdio transport."""
    import asyncio

    print("PolyXRD MCP Server starting (stdio transport)...", file=sys.stderr)
    asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
