"""PolyXRD 精修内核（v5.0.0）—— 与 Qt 无关，可独立单测。

设计要点（见 ``docs/全谱拟合优化方案-v5.0.0.md``）：

* **分层严格**：``cell``（几何）→ ``scattering``（散射因子）→ ``structure``
  （结构因子 + 反射表）→ ``profile``（峰形）→ ``background``（背景基）
  → 精修层（变量投影）→ 协议层（分阶段）→ 报告层（诊断 + 分层）。
* **三层架构**（方案 §2）：

  ==== ============================================ =========================
  层3  ``protocol`` / ``report`` / ``goal``          一键默认 / 诚实诊断 / GOAL
  层2  ``parameters`` / ``linear`` / ``optimize``    变量投影 + 分阶段释放
  层1  ``cell``~``pattern``                          逐原子结构因子前向模型
  ==== ============================================ =========================

  外加 ``constraints``（约束系统）、``quantitative``（Hill–Howard）、
  ``diagnostics``（秩亏 / 高相关 / psing）。
* **缓存友好**：反射表只依赖结构/波长/窗口/择优面方向，**不含**峰形参数与
  择优取向的 ``r``，因此峰形与 ``r`` 精修时无需重算反射表。
* **不 import 兄弟仓库**：参考工具（RutAna / LFP / NCA / NCM）的内核只作口径
  依据，本包为 PolyXRD 自有实现，已绕过 vendor ``shape.caglioti`` 的
  ``tan(2θ)`` 历史缺陷。

最小用法::

    summary = run_tiered(problem)            # 定档 + 选协议 + 种子化 + 精修
    print(build_report(problem, summary).text())
"""

from polyxrd.refinement.background import (
    BACKGROUND_KINDS,
    DEFAULT_TENT_NODES,
    BackgroundParams,
    background_basis,
    background_values,
    chebyshev_basis,
    tent_basis,
)
from polyxrd.refinement.cell import (
    Cell,
    cell_angle_cosines,
    d_spacings,
    lorentz_polarization,
    reciprocal_magnitudes,
    two_theta_from_d,
    two_theta_from_g,
)
from polyxrd.refinement.constraints import (
    Constraint,
    ConstraintSystem,
    make_equal,
    make_ratio,
    make_sum_to,
)
from polyxrd.refinement.diagnostics import (
    HIGHCORR,
    Diagnostics,
    correlation_matrix,
    diagnose,
)
from polyxrd.refinement.goal import (
    TIER_LABELS,
    TIER_QUANT_NOTE,
    GoalResult,
    Tier,
    TIER_PROTOCOLS,
    classify_tier,
    evaluate_goals,
    fraction_sigmas,
    protocol_for_tier,
    refined_stage,
    tier_note,
)
from polyxrd.refinement.linear import (
    LinearSolve,
    design_stack,
    full_covariance,
    linear_covariance,
    linear_sigmas,
    solve_linear,
)
from polyxrd.refinement.optimize import (
    FitResult,
    levenberg_marquardt,
    minimize_residual,
    scipy_least_squares,
)
from polyxrd.refinement.parameters import STAGE_LABELS, Parameter, ParameterSet
from polyxrd.refinement.pattern import (
    DEFAULT_CUTOFF_FWHM,
    PhasePattern,
    PhaseSpec,
    design_matrix,
    phase_pattern,
    reflection_centers_and_intensities,
    synthesize,
)
from polyxrd.refinement.problem import (
    FitSummary,
    PatternProblem,
    PhaseBlock,
    finalize_summary,
    pattern_metrics,
)
from polyxrd.refinement.protocol import (
    DEFAULT_PROTOCOL,
    PROTOCOLS,
    STAGE_ORDER,
    PeakSeed,
    ProfileSeed,
    SeedBundle,
    StageSpec,
    ZeroSeed,
    find_observed_peaks,
    resolve_protocol,
    run_protocol,
    run_tiered,
    seed_caglioti,
    seed_problem,
    seed_zero,
    snip_baseline,
)
from polyxrd.refinement.quantitative import (
    ATOMIC_MASS,
    QuantResult,
    atomic_mass,
    formula_mass,
    hill_howard,
    mass_per_cell,
    phase_weight_factor,
    phase_zmv,
)
from polyxrd.refinement.report import (
    Finding,
    FitReport,
    ResidualStats,
    audit,
    build_report,
    residual_stats,
)
from polyxrd.refinement.orientation import select_po_directions
from polyxrd.refinement.profile import (
    FWHM_TO_SIGMA,
    PROFILE_KINDS,
    Kalpha2,
    ProfileParams,
    area_normalized_profile,
    caglioti_fwhm,
    detect_ka2_doublet,
    ka2_two_theta,
    ka2_wavelength,
    profile_centers,
    split_asymmetry_factor,
    split_scale_factors,
    tch_combine,
    tch_widths,
)
from polyxrd.refinement.scattering import (
    ScatteringTable,
    atomic_form_factor,
    atomic_number,
    has_scattering_params,
    normalize_element,
    scattering_coefficients,
)
from polyxrd.refinement.structure import (
    B_ISO_DEFAULT,
    TWO_THETA_MERGE_TOL,
    AtomSite,
    ReflectionTable,
    StructureModel,
    build_reflections,
    march_dollase_weight,
    normalize_wavelengths,
    po_direction_from_hkl,
    site_from_dict,
)
from polyxrd.refinement.symmetry import (
    CRYSTAL_SYSTEMS,
    INDEPENDENT_CELL_PARAMS,
    apply_cell_ties,
    cell_ties,
    crystal_system_from_symbol,
    resolve_space_group_symbol,
)

__all__ = [
    "ATOMIC_MASS",
    "AtomSite",
    "BACKGROUND_KINDS",
    "B_ISO_DEFAULT",
    "BackgroundParams",
    "CRYSTAL_SYSTEMS",
    "Cell",
    "Constraint",
    "ConstraintSystem",
    "DEFAULT_CUTOFF_FWHM",
    "DEFAULT_PROTOCOL",
    "DEFAULT_TENT_NODES",
    "Diagnostics",
    "FWHM_TO_SIGMA",
    "Finding",
    "FitReport",
    "FitResult",
    "FitSummary",
    "GoalResult",
    "HIGHCORR",
    "INDEPENDENT_CELL_PARAMS",
    "Kalpha2",
    "LinearSolve",
    "PROFILE_KINDS",
    "PROTOCOLS",
    "Parameter",
    "ParameterSet",
    "PatternProblem",
    "PeakSeed",
    "PhaseBlock",
    "PhasePattern",
    "PhaseSpec",
    "ProfileParams",
    "ProfileSeed",
    "QuantResult",
    "ReflectionTable",
    "ResidualStats",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "ScatteringTable",
    "SeedBundle",
    "StageSpec",
    "StructureModel",
    "ZeroSeed",
    "TIER_LABELS",
    "TIER_PROTOCOLS",
    "TIER_QUANT_NOTE",
    "TWO_THETA_MERGE_TOL",
    "Tier",
    "area_normalized_profile",
    "apply_cell_ties",
    "atomic_form_factor",
    "atomic_mass",
    "atomic_number",
    "audit",
    "background_basis",
    "background_values",
    "build_reflections",
    "build_report",
    "caglioti_fwhm",
    "cell_angle_cosines",
    "cell_ties",
    "chebyshev_basis",
    "classify_tier",
    "refined_stage",
    "correlation_matrix",
    "crystal_system_from_symbol",
    "d_spacings",
    "design_matrix",
    "design_stack",
    "diagnose",
    "detect_ka2_doublet",
    "evaluate_goals",
    "finalize_summary",
    "find_observed_peaks",
    "formula_mass",
    "fraction_sigmas",
    "full_covariance",
    "has_scattering_params",
    "hill_howard",
    "ka2_two_theta",
    "ka2_wavelength",
    "levenberg_marquardt",
    "linear_covariance",
    "linear_sigmas",
    "lorentz_polarization",
    "make_equal",
    "make_ratio",
    "make_sum_to",
    "march_dollase_weight",
    "mass_per_cell",
    "minimize_residual",
    "normalize_element",
    "normalize_wavelengths",
    "pattern_metrics",
    "phase_pattern",
    "phase_weight_factor",
    "phase_zmv",
    "protocol_for_tier",
    "po_direction_from_hkl",
    "profile_centers",
    "select_po_directions",
    "reciprocal_magnitudes",
    "residual_stats",
    "resolve_protocol",
    "resolve_space_group_symbol",
    "run_protocol",
    "run_tiered",
    "scattering_coefficients",
    "scipy_least_squares",
    "seed_caglioti",
    "seed_problem",
    "seed_zero",
    "site_from_dict",
    "snip_baseline",
    "solve_linear",
    "split_asymmetry_factor",
    "split_scale_factors",
    "synthesize",
    "tch_combine",
    "tch_widths",
    "tent_basis",
    "tier_note",
    "two_theta_from_d",
    "two_theta_from_g",
]
