"""
FoM 匹配纯函数 + 搜索-匹配编排 (M10, Sprint 1)
==============================================
设计:
  - compute_fom / check_three_strongest / delta_2theta_auto / profile_fitting_score
    都是纯函数, 输入 numpy/list, 不依赖数据库与 GUI, 便于单测。
  - search_match 是薄编排: 约束过滤 → (可选三强预检) → FoM 打分 → 排序/截断,
    返回 models.phase.PhaseMatchResult 列表 (score 低好)。

评分口径与既有 FOM 保持一致 (位置偏差 + 漏峰惩罚 + 强度一致性), 但把
匹配窗口改为可自动/手动指定, 且对无 FWHM 的峰有兜底。
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np

from polyxrd.models.fom import FoMResult
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.search_options import SearchOptions


# ─────────────────────────────────────────────────────────────
# 纯函数
# ─────────────────────────────────────────────────────────────

_NONMETAL = {"H", "He", "N", "O", "F", "Ne", "Cl", "Ar", "Br", "Kr", "I", "Xe",
             "Rn", "S", "P", "C", "Si", "Se", "Te", "As", "Ge", "B"}


def _is_pure_metal(phase) -> bool:
    els = phase.elements or set()
    return len(els) == 1 and not (els & _NONMETAL)


def _as_float_array(values) -> np.ndarray:
    return np.asarray([float(v) for v in values], dtype=float)


def compute_fom(
    obs_two_theta,
    obs_intensity,
    ref_peaks: Iterable,
    tol: float = 0.15,
    use_intensity: bool = True,
) -> FoMResult:
    """物相参考峰 vs 实验峰的 FoM。

    Args:
        obs_two_theta: 实验峰 2θ (可迭代)
        obs_intensity: 实验峰强度 (可迭代)
        ref_peaks: 参考峰 [(hkl|None, 2θ, I), ...]
        tol: 峰位匹配窗口 (度)
        use_intensity: 是否计入强度一致性
    Returns:
        FoMResult (score 越小越好)
    """
    refs = [(float(tt), float(i)) for _, tt, i in ref_peaks if i is not None]
    if not refs:
        return FoMResult(score=999.0, matched=0, missed=0,
                         delta_2theta=float(tol))
    obs_arr = np.asarray([float(t) for t in obs_two_theta])
    int_arr = np.asarray([float(v) for v in obs_intensity])
    order = np.argsort(obs_arr)
    obs_tt = obs_arr[order]
    obs_int = int_arr[order]
    if len(obs_tt) == 0:
        return FoMResult(score=999.0, matched=0, missed=len(refs),
                         delta_2theta=float(tol))

    matched = 0
    sum_dev = 0.0
    int_ratios: list[float] = []
    for tt, i in refs:
        pos = int(np.searchsorted(obs_tt, tt))
        best = None
        if pos < len(obs_tt):
            best = obs_tt[pos]
        if pos > 0 and (best is None or abs(obs_tt[pos - 1] - tt) < abs(best - tt)):
            best = obs_tt[pos - 1]
        if best is None:
            continue
        d = abs(best - tt)
        if d <= tol:
            matched += 1
            sum_dev += d
            if use_intensity:
                j = int(np.argmin(np.abs(obs_tt - best)))
                oi = float(obs_int[j]) if j < len(obs_int) else 0.0
                if oi > 0 and i > 0:
                    int_ratios.append(min(oi, i) / max(oi, i))

    total = len(refs)
    missed = total - matched
    norm = sum(tt for tt, _ in refs) or 1.0
    penalty = (sum_dev + missed * tol) / norm
    avg_int = float(np.mean(int_ratios)) if int_ratios else 0.0
    ratio = matched / total if total else 0.0
    # 与既有 FOM 同口径 (乘性): 位置惩罚为主, 强度一致性/覆盖率作系数。
    # 教训: 加性强度惩罚 (1-avg_int)*w 会因真实数据强度比普遍偏低 (~0.01)
    # 而给所有候选加上近似常数项, 抹掉位置区分度 → 必须乘性。
    if use_intensity:
        score = penalty * (1.0 - 0.3 * ratio) * (1.0 - 0.1 * avg_int)
    else:
        score = penalty * (1.0 - 0.3 * ratio)
    return FoMResult(
        score=float(max(score, 1e-4)),
        matched=matched,
        missed=missed,
        position_penalty=float(penalty),
        intensity_score=avg_int,
        method="fom",
        delta_2theta=float(tol),
    )


def check_three_strongest(
    obs_two_theta,
    ref_peaks: Iterable,
    tol: float = 0.15,
    min_hits: int = 1,
) -> bool:
    """三强峰预检: 参考谱前 3 强峰中, 至少 min_hits 条被实验峰命中。

    微量相常因三强峰漏检而被跳过 → 关闭预检或提高灵敏度可召回。
    """
    refs = sorted(
        ((float(tt), float(i)) for _, tt, i in ref_peaks if i is not None),
        key=lambda x: x[1], reverse=True,
    )[:3]
    if not refs:
        return True
    obs_tt = np.sort(_as_float_array(obs_two_theta))
    hits = 0
    for tt, _ in refs:
        pos = int(np.searchsorted(obs_tt, tt))
        near = False
        for j in (pos, pos - 1):
            if 0 <= j < len(obs_tt) and abs(obs_tt[j] - tt) <= tol:
                near = True
                break
        if near:
            hits += 1
    return hits >= max(1, int(min_hits))


def delta_2theta_auto(
    peaks,
    default_fwhm: float = 0.15,
    factor: float = 1.0,
) -> float:
    """自适应峰位关联窗口 = factor × 平均峰 FWHM。

    peaks 接受: PeakList/Peak 列表 (用其 fwhm), 或纯 float 列表 (视为 FWHM)。
    无有效 FWHM 时用 default_fwhm。
    """
    fwhms: list[float] = []
    for p in (getattr(peaks, "peaks", None) or peaks or []):
        if hasattr(p, "fwhm"):
            f = float(getattr(p, "fwhm") or 0.0)
        else:
            f = float(p)
        if f > 0:
            fwhms.append(f)
    mean_f = float(np.mean(fwhms)) if fwhms else default_fwhm
    return float(round(factor * mean_f, 4))


def profile_fitting_score(
    xrd,
    phase,
    fwhm: Optional[float] = None,
) -> dict:
    """峰型匹配评分 (v4 风格): 不依赖峰表, 直接比实测谱 vs 参考棒谱合成谱。

    Returns:
        {"corr": 皮尔逊相关, "scale": 最优尺度因子, "rwp": Rwp, "n_peaks": int}
    """
    import numpy as _np
    grid = _np.asarray(xrd.two_theta, dtype=float)
    obs = _np.asarray(xrd.intensity, dtype=float)
    refs = [(float(tt), float(i)) for _, tt, i in phase.get_reference_peaks()
            if i is not None]
    if not refs:
        return {"corr": 0.0, "scale": 0.0, "rwp": 999.0, "n_peaks": 0}
    if fwhm is None or fwhm <= 0:
        fwhm = 0.2
    sigma = fwhm / 2.355
    ymodel = _np.zeros_like(grid)
    for tt, i in refs:
        if i <= 0:
            continue
        ymodel += i * _np.exp(-0.5 * ((grid - tt) / sigma) ** 2)
    denom = float(_np.dot(ymodel, ymodel))
    scale = float(_np.dot(obs, ymodel) / denom) if denom > 1e-12 else 0.0
    scale = max(scale, 0.0)
    obs_n = obs - obs.mean()
    mod_n = (scale * ymodel) - (scale * ymodel).mean()
    den = float(_np.linalg.norm(obs_n) * _np.linalg.norm(mod_n))
    corr = float(_np.dot(obs_n, mod_n) / den) if den > 1e-12 else 0.0
    resid = obs - scale * ymodel
    rwp = float(_np.sqrt(_np.sum(resid ** 2) / max(_np.sum(obs ** 2), 1e-12)))
    return {"corr": corr, "scale": scale, "rwp": rwp * 100.0, "n_peaks": len(refs)}


# ─────────────────────────────────────────────────────────────
# 编排
# ─────────────────────────────────────────────────────────────

def _name_matches(name: str, pattern: str) -> bool:
    import fnmatch
    if not pattern:
        return True
    return (fnmatch.fnmatchcase(name, pattern)
            or pattern.lower() in name.lower())


def _passes_options(phase: Phase, opts: SearchOptions) -> bool:
    if opts.name_pattern and not _name_matches(phase.name or "", opts.name_pattern):
        return False
    els = phase.elements or set()
    if (opts.must or opts.maybe) and els:
        allowed = set(opts.must) | set(opts.maybe)
        if not els.issubset(allowed):
            return False
    if opts.exclude and els and (els & set(opts.exclude)):
        return False
    return True


def search_match(
    obs_two_theta,
    obs_intensity,
    phases: Iterable[Phase],
    options: Optional[SearchOptions] = None,
) -> list[PhaseMatchResult]:
    """搜索-匹配编排: 约束 → (三强预检) → FoM → 排序/截断。

    Args:
        obs_two_theta: 实验峰 2θ
        obs_intensity: 实验峰强度
        phases: 候选物相列表
        options: SearchOptions (None → 宽松默认)
    Returns:
        按 FoM 升序 (越好越前) 的 PhaseMatchResult 列表
    """
    opts = options or SearchOptions()
    obs_tt = list(obs_two_theta)
    obs_i = list(obs_intensity)

    results: list[PhaseMatchResult] = []
    for phase in phases:
        if not _passes_options(phase, opts):
            continue
        refs = phase.get_reference_peaks()
        if not refs:
            continue
        if opts.check_three_strongest and not check_three_strongest(
            obs_tt, refs, tol=opts.tol_fallback, min_hits=opts.three_strongest_hits
        ):
            continue

        if opts.delta_2theta is not None:
            tol = opts.delta_2theta
        elif opts.delta_2theta_auto:
            # 只有传入峰对象 (带 FWHM) 时自动窗口才有意义
            src = getattr(obs_two_theta, "peaks", None)
            if src:
                tol = delta_2theta_auto(
                    src, default_fwhm=opts.default_fwhm,
                    factor=opts.delta_2theta_factor,
                )
            else:
                tol = opts.default_fwhm * opts.delta_2theta_factor
            if not (tol > 1e-6):
                tol = opts.tol_fallback
        else:
            tol = opts.tol_fallback

        fom = compute_fom(obs_tt, obs_i, refs, tol=tol, use_intensity=opts.use_intensity)
        # 纯金属惩罚 (对齐项目基线 _match_phase_fom 的 ×1.5)
        if opts.metal_penalty and opts.metal_penalty != 1.0 \
                and _is_pure_metal(phase):
            fom.score = float(fom.score * opts.metal_penalty)
        if opts.score_threshold is not None and fom.score > opts.score_threshold:
            continue

        conf = "极好匹配" if fom.score < 0.1 else (
            "良好匹配" if fom.score < 0.3 else (
                "一般匹配" if fom.score < 0.5 else "可能不匹配"))
        results.append(PhaseMatchResult(
            phase=phase,
            score=round(float(fom.score), 4),
            matched_peaks=fom.matched,
            total_peaks=fom.total,
            confidence=conf,
            method="fom",
        ))

    results.sort(key=lambda r: (r.score, r.total_peaks))
    if opts.max_entries:
        results = results[: opts.max_entries]
    return results
