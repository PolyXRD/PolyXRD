"""
PolyXRD MCP Server — main entry point.

Exposes PolyXRD's XRD analysis pipeline as MCP tools so that any
MCP-compatible AI client (Claude Desktop, TraeCode, etc.) can:
  - Load & preprocess XRD data
  - Detect & fit peaks
  - Search phases in the mounted polyDB by formula / name / space group / d-spacings
  - Identify phases
  - Run Rietveld refinement
  - Simulate patterns from CIF structures
  - Export results & manage projects

Transport: stdio (default) or SSE/HTTP.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Optional

from mcp.server import MCPServer

from polyxrd.mcp_server.session import get_session

# ── Create MCP server instance ────────────────────────────────
mcp = MCPServer(
    name="polyxrd",
    # v2.3.0: 与主程序版本单源对齐 (从包 __init__ 取, 防再次漂移)
    version=__import__("polyxrd").__version__,
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
    distance: float = 0.5,
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
#  5. PHASE DATABASE SEARCH (polyDB 外挂库 + COD 在线)
# ════════════════════════════════════════════════════════════════
#
# v4.2：本地 COD sqlite 运行时已从发布包移除，原 4 个 COD 工具改成：
#   · search_phases_polydb / get_phase_details  → polyDB 外挂库（新名字）
#   · search_cod_phases / get_cod_phase_details → 同名保留，转调 polyDB
#     （不破坏已有外部客户端；条目 ID 自 v4.0.0 起就是 polyDB 的 eid）
#   · search_cod_by_d_peaks → v4.3.0 起转调 polyDB 原生 d 峰检索（旧签名不变）
#   · search_phases_by_d_peaks → v4.3.0 新增原生 d 峰检索（含元素过滤/相对容差）
#   · search_cod_online → 走 COD REST（本来就不依赖本地库）


@mcp.tool()
def search_phases_polydb(
    query: str,
    limit: int = 20,
) -> str:
    """Search the mounted polyDB phase database by formula, mineral name, space group, or ID.

    Args:
        query: Search keyword. Examples: "SiO2", "O2 Si", "quartz", "F d -3 m" (spaces optional), "1011097", "97-1011097".
        limit: Maximum number of results to return (default 20).

    Returns:
        JSON list of matching phases with cod_id, formula, mineral name,
        space group and cell parameters. ``mounted=false`` when no polyDB is
        mounted (the DB ships as a separate optional download).
    """
    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase()
    if not db.available:
        return json.dumps(
            {
                "query": query,
                "mounted": False,
                "n_results": 0,
                "phases": [],
                "hint": (
                    "No polyDB mounted. Download a PolyXRD-DataBase release "
                    "and mount it in the app, or use search_cod_online for "
                    "structures from crystallography.net."
                ),
            },
            ensure_ascii=False,
        )
    if not db.is_ready():
        return json.dumps(
            {
                "query": query,
                "mounted": True,
                "n_results": 0,
                "phases": [],
                "error": "polyDB layout is incomplete/corrupted "
                         "(meta.json/index.sqlite or segments missing).",
            },
            ensure_ascii=False,
        )
    results = db.search_entries(query, limit=limit)
    return json.dumps(
        {"query": query, "mounted": True, "n_results": len(results),
         "phases": results},
        ensure_ascii=False,
        default=str,
    )


@mcp.tool()
def search_cod_phases(
    query: str,
    limit: int = 20,
) -> str:
    """Deprecated alias of ``search_phases_polydb`` (searches the mounted polyDB).

    Kept so existing MCP clients keep working after the local COD sqlite
    runtime was removed in v4.2.0.
    """
    return search_phases_polydb(query=query, limit=limit)


@mcp.tool()
def get_phase_details(eid: int) -> str:
    """Get full details of a polyDB phase including its d-I peaks and structure.

    Args:
        eid: polyDB entry ID (e.g. 1011097).

    Returns:
        JSON with phase info: formula, mineral name, space group, cell params,
        d-I peak list and non-symmetric-unit atomic sites.
    """
    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase()
    if not db.available:
        return json.dumps({
            "error": "No polyDB mounted.",
            "hint": "Mount a PolyXRD-DataBase release in the app first.",
        }, ensure_ascii=False)
    if not db.is_ready():
        return json.dumps({
            "error": "polyDB layout is incomplete/corrupted.",
            "hint": "Re-mount a valid PolyXRD-DataBase release.",
        }, ensure_ascii=False)
    phase = db.get_phase(int(eid))
    if phase is None:
        return json.dumps({"error": f"Entry {eid} not found in polyDB."},
                          ensure_ascii=False)
    phase["atomic_sites"] = db.get_atomic_sites(int(eid))
    return json.dumps(phase, ensure_ascii=False, default=str)


@mcp.tool()
def get_cod_phase_details(cod_id: int) -> str:
    """Deprecated alias of ``get_phase_details`` (polyDB-backed since v4.2.0).

    v4.2.1：保留旧参数名 ``cod_id``（MCP 入参 schema 由函数签名生成），
    旧客户端按 ``{"cod_id": …}`` 调用不会失效。
    """
    return get_phase_details(eid=cod_id)


def _polydb_d_peak_search(
    d_values,
    intensities=None,
    *,
    tolerance: float = 0.02,
    tolerance_rel: float = 0.0,
    min_match: int = 3,
    limit: int = 20,
    elements=None,
    max_ref_peaks: int = 40,
    main_peak_topk: int = 1,
) -> dict:
    """MCP d 峰检索公共实现：校验 → polyDB 检索 → 统一 JSON 字段。

    v4.3.0 起 d 峰检索回到 MCP 工具面，但底层不再是已删除的 COD sqlite，
    而是 polyDB 的位图倒排 + Hanawalt 精确打分（与 UI 的 polyDB 识别同源）。
    """
    # ── 入参校验（MCP 工具必须返回 JSON，不能抛给客户端）──
    try:
        ds = [float(x) for x in (d_values or [])]
    except (TypeError, ValueError):
        return {"error": "d_values must be a list of numbers",
                "n_results": 0, "matches": []}
    if not ds:
        return {"error": "d_values is empty", "n_results": 0, "matches": []}
    if any((not math.isfinite(v)) or v <= 0.0 for v in ds):
        return {"error": "d_values must be finite and > 0",
                "n_results": 0, "matches": []}
    if len(ds) > 500:
        return {"error": "too many d values (max 500)",
                "n_results": 0, "matches": []}
    iis = None
    if intensities is not None:
        try:
            iis = [float(v) for v in intensities]
        except (TypeError, ValueError):
            return {"error": "intensities must be a list of numbers",
                    "n_results": 0, "matches": []}
        if len(iis) != len(ds):
            return {"error": "intensities and d_values must have the same length",
                    "n_results": 0, "matches": []}
        if any((not math.isfinite(v)) or v < 0.0 for v in iis):
            return {"error": "intensities must be finite and >= 0",
                    "n_results": 0, "matches": []}
    try:
        tol = float(tolerance)
        trel = float(tolerance_rel)
        minm = int(min_match)
        lim = int(limit)
        max_ref = int(max_ref_peaks)
        topk = int(main_peak_topk)
    except (TypeError, ValueError):
        return {"error": "invalid numeric option", "n_results": 0, "matches": []}
    if not math.isfinite(tol) or tol <= 0 or not math.isfinite(trel) or trel < 0:
        return {"error": "tolerance must be > 0 and tolerance_rel >= 0",
                "n_results": 0, "matches": []}
    minm = max(1, min(minm, len(ds)))
    lim = max(1, min(lim, 200))
    max_ref = max(1, min(max_ref, 1000))
    topk = max(1, min(topk, 20))

    elems = None
    if elements:
        elems = {str(e).strip().title() for e in elements if str(e).strip()}
        if not elems:
            elems = None

    from polyxrd.services.polydb import PolyDatabase, Z_OF

    if elems:
        unknown = sorted(e for e in elems if e not in Z_OF)
        if unknown:
            return {"error": f"unknown element(s): {', '.join(unknown)}",
                    "n_results": 0, "matches": []}

    db = PolyDatabase()
    if not db.available:
        return {
            "mounted": False,
            "n_results": 0,
            "matches": [],
            "hint": (
                "No polyDB mounted. Download a PolyXRD-DataBase release and "
                "mount it in the app (or ship the bundled COD-Inorg library)."
            ),
        }
    if not db.is_ready():
        return {
            "mounted": True,
            "error": "polyDB layout is incomplete/corrupted "
                     "(meta.json/index.sqlite or segments missing).",
            "n_results": 0,
            "matches": [],
        }
    try:
        matches = db.search_by_d_peaks(
            ds, iis, tolerance=tol, tolerance_rel=trel, min_match=minm,
            limit=lim, max_ref_peaks=max_ref, main_peak_topk=topk,
            elements_allowed=elems,
        )
    except Exception as exc:  # noqa: BLE001 - MCP 边界必须返回 JSON
        return {
            "mounted": True,
            "error": f"polyDB d-peak search failed: {type(exc).__name__}: {exc}",
            "n_results": 0,
            "matches": [],
        }

    # 与 search_phases_polydb 的字段口径一致：display/ref 用旧 COD 字符串格式
    for m in matches:
        cid = int(m.get("cod_id", 0))
        m["cod_id"] = cid
        m["display_id"] = f"97-{cid:07d}"
        m["ref_id"] = f"96-{cid // 10000:03d}-{cid % 10000:04d}"

    return {
        "mounted": True,
        "n_results": len(matches),
        "matches": matches,
        "query": {
            "d_values": ds,
            "intensities": iis,
            "tolerance": tol,
            "tolerance_rel": trel,
            "min_match": minm,
            "elements": sorted(elems) if elems else None,
        },
    }


@mcp.tool()
def search_phases_by_d_peaks(
    d_values: list[float],
    intensities: Optional[list[float]] = None,
    tolerance: float = 0.02,
    tolerance_rel: float = 0.0,
    min_match: int = 3,
    limit: int = 20,
    elements: Optional[list[str]] = None,
    max_ref_peaks: int = 40,
    main_peak_topk: int = 1,
) -> str:
    """Search the mounted polyDB by measured d-spacings (Hanawalt-style).

    Args:
        d_values: Measured d-spacings in Angstrom (e.g. quartz: 3.343, 4.255).
        intensities: Optional matching peak intensities (enables weighted
            recall + main-peak criterion; strongly recommended).
        tolerance: Absolute d-matching tolerance in Angstrom (default 0.02).
        tolerance_rel: Relative tolerance (fraction of d; 0 = absolute only).
        min_match: Minimum matched peaks for a phase to be returned.
        limit: Maximum number of ranked matches (1..200).
        elements: Optional element whitelist (e.g. ["Si", "O"]) — phases
            containing elements outside the whitelist are filtered out.
        max_ref_peaks: Only the strongest N reference peaks per phase are used.
        main_peak_topk: Measured strongest peaks checked by main-peak match.

    Returns:
        JSON with mounted/n_results/matches. Each match has cod_id, formula,
        mineral_name, space_group, cell/peak counts and Hanawalt scores.
        ``mounted=false`` when no polyDB is mounted.
    """
    payload = _polydb_d_peak_search(
        d_values, intensities, tolerance=tolerance,
        tolerance_rel=tolerance_rel, min_match=min_match, limit=limit,
        elements=elements, max_ref_peaks=max_ref_peaks,
        main_peak_topk=main_peak_topk,
    )
    return json.dumps(payload, ensure_ascii=False, default=str)


@mcp.tool()
def search_cod_by_d_peaks(
    d_values: list[float],
    intensities: Optional[list[float]] = None,
    tolerance: float = 0.02,
    min_match: int = 3,
    limit: int = 20,
) -> str:
    """Deprecated-name alias of ``search_phases_by_d_peaks`` (polyDB-backed).

    v4.3.0: the old COD sqlite backing is gone, but the legacy signature is
    kept and now searches the mounted polyDB — existing MCP clients keep
    working without parameter changes.
    """
    payload = _polydb_d_peak_search(
        d_values, intensities, tolerance=tolerance, min_match=min_match,
        limit=limit,
    )
    return json.dumps(payload, ensure_ascii=False, default=str)


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
        timeout: Request timeout in seconds (kept for API compatibility).

    Returns:
        JSON list of COD entries with cod_id, name, formula.
    """
    from polyxrd.services.cod_searcher import CODSearcher

    if not any([formula, mineral_name, space_group]):
        return json.dumps(
            {"n_results": 0, "entries": [],
             "error": "give at least one of formula / mineral_name / "
                      "space_group"},
            ensure_ascii=False,
        )
    try:
        # v4.2.1: timeout 真正生效；网络异常按旧行为返回 JSON（不抛出）。
        result = CODSearcher(timeout=timeout).search(
            formula=formula, mineral_name=mineral_name, space_group=space_group,
        )
    except Exception as exc:  # noqa: BLE001 - MCP 工具必须返回可消费 JSON
        return json.dumps(
            {
                "n_results": 0,
                "entries": [],
                "error": f"COD online search failed: {type(exc).__name__}: {exc}",
                "hint": "Check network access / try again later, or use "
                        "search_phases_polydb for the locally mounted library.",
            },
            ensure_ascii=False,
        )
    entries = [
        {
            "cod_id": e.cod_id,
            "name": e.mineral_name or "",
            "formula": e.formula or "",
            "space_group": e.space_group or "",
        }
        for e in (getattr(result, "entries", None) or [])
    ]
    return json.dumps(
        {"n_results": len(entries), "entries": entries},
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
    # P0-1: 参数名与 ProjectService.save_project 真实签名对齐
    # (旧代码传 file_path=/refinement_result=, 前者不存在、后者签名无此参数 → TypeError)
    service.save_project(
        path=file_path,
        data=session.current_data,
        peaks=session.peak_list,
        phases=[r.phase for r in session.phase_matches],
        results=list(session.phase_matches) or None,
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

    # P0-1: load_project 返回 **dict** (不是对象) —— 旧代码按属性访问 → AttributeError;
    # 匹配结果键名是 "results" (不是 phase_matches), 精修结果键名是 "refinement_result"。
    data = project.get("data")
    peaks = project.get("peaks")
    results = project.get("results") or []
    refinement = project.get("refinement_result")

    session.raw_data = data
    session.peak_list = peaks
    session.phase_matches = results
    session.refinement_result = refinement
    session.project_file = file_path
    session.source_file = file_path

    result = {
        "status": "ok",
        "file_path": file_path,
        "n_points": len(data.two_theta) if data is not None else 0,
        "n_peaks": len(peaks) if peaks is not None else 0,
        "n_phases": len(results),
        "has_refinement": refinement is not None,
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
