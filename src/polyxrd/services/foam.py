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

from polyxrd.models.fom import FoMResult, confidence_from_score
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


# ── 匹配因子 (FoM) 调参常量 ────────────────────────────────
_FOM_W_MIN = 0.3               # 参考峰基础权重 (强峰权重上限 1.0)
_FOM_SPEC_WEIGHT = 0.30        # 未解释实验峰惩罚权重
_FOM_INTENSITY_WEIGHT = 0.20   # 强度一致性乘性权重


def compute_fom(
    obs_two_theta,
    obs_intensity,
    ref_peaks: Iterable,
    tol: float = 0.15,
    use_intensity: bool = True,
    obs_range=None,
    min_visible_frac: float = 0.0,
    scale=None,
    scale_penalty: float = 0.0,
) -> FoMResult:
    """物相参考峰 vs 实验峰的匹配因子 (0.9.11 加权互斥版)。

    与旧口径的三点差异:
      1. **一一对应互斥匹配**: 先枚举所有 |Δ2θ| ≤ tol 的 (参考峰, 实验峰) 对,
         按偏差升序贪心配对, 每条参考峰与每条实验峰都最多使用一次。旧实现让
         多条参考峰各自就近吸附到同一条实验峰, 峰多的密集物相因此被系统性高估。
      2. **强峰加权 + 改用 Σw 归一**: 参考峰权重 w = 0.3 + 0.7·I/Imax, 漏掉
         强峰的代价远大于漏掉弱峰; 归一化不再用 Σ2θ (旧口径使高角度、多峰物相
         天然占优, 与"匹配好坏"无关)。
      3. **特异性项**: 未被任何参考峰解释的实验峰按比例惩罚, 抑制"只解释少数
         几条峰却因偏差小排在前列"的伪匹配。v2.1 起该比例按**强度加权**
         (Σ未解释强度 / Σ总强度) 而非峰计数 —— 峰检测无幅度下限时噪声峰
         数量多但强度低, 计数口径会把惩罚打满、丧失区分力 (v2.1 P1-3)。

    ``score = (bad + 0.30·未解释强度比) · (1 - 0.20·强度余弦)``

    v2.2 S09/S10 追加 (全部默认关闭, 默认参数下行为与 v2.1 完全一致):

      4. **S09 参考峰可观测性**: 只有"可观测"的参考峰进 Σw 分母并参与漏检
         计数 —— 扫描范围外 / 缩放后低于检出限的参考峰不再被冤枉为漏检。
           - ``obs_range``: 实验 2θ 扫描范围 (lo, hi); 范围外参考峰不计;
           - ``scale``: 强度尺度因子。``"auto"`` = 用本函数在互斥匹配对上
             算出的 s* (S10); 传正数 = 外部指定; ``None`` = 不启用;
             启用后 ``I_exp = s*·I_ref < 1%·max(I_obs)`` 的参考峰不计漏检
           - ``min_visible_frac``: scale 未启用时的保守口径
             (I_ref/Imax ≥ 该值才计入漏检), 默认 0.0 = 不启用
      5. **S10 强度尺度因子**: 在互斥匹配对上求
         ``s* = Σ(w·I_obs·I_ref)/Σ(w·I_ref²)``, 记入 FoMResult.scale;
         ``scale_rel = clip(s*·I_ref,max / I_obs,max, 0, 1)``;
         ``scale_penalty > 0`` 时按 ``×(1 + scale_penalty·(1-scale_rel))``
         连续降权 —— "只配上噪声"的伪匹配 s* 极小, 得分变差、排名下降。

    Args:
        obs_two_theta: 实验峰 2θ (可迭代)
        obs_intensity: 实验峰强度 (可迭代)
        ref_peaks: 参考峰 [(hkl|None, 2θ, I), ...]
        tol: 峰位匹配窗口 (度)
        use_intensity: 是否计入强度一致性
        obs_range: 实验 2θ 扫描范围 (lo, hi) 或 None
        min_visible_frac: 保守可观测阈值 (I_ref/Imax), 默认 0.0
        scale: 强度尺度因子 (正数 / "auto" / None)
        scale_penalty: 尺度因子降权强度 ∈ [0, 1), 默认 0.0 (关)
    Returns:
        FoMResult (score 越小越好; scale/scale_rel 记录 s* 与相对强度)
    """
    refs = [(float(tt), float(i)) for _, tt, i in ref_peaks if i is not None]
    if not refs:
        return FoMResult(score=999.0, matched=0, missed=0,
                         delta_2theta=float(tol))

    obs_arr = np.asarray([float(t) for t in obs_two_theta], dtype=float)
    int_arr = np.asarray([float(v) for v in obs_intensity], dtype=float)
    if obs_arr.size == 0:
        return FoMResult(score=999.0, matched=0, missed=len(refs),
                         delta_2theta=float(tol))
    order = np.argsort(obs_arr)
    obs_tt = obs_arr[order]
    obs_int = int_arr[order] if int_arr.size == obs_arr.size else np.zeros_like(obs_tt)
    tol = float(tol) if tol and float(tol) > 1e-9 else 1e-9

    # ── 1. 候选配对 + 按偏差升序贪心互斥分配 ──────────────────
    pairs: list[tuple[float, int, int]] = []
    for ri, (tt, _) in enumerate(refs):
        pos = int(np.searchsorted(obs_tt, tt))
        for j in (pos - 1, pos):
            if 0 <= j < obs_tt.size:
                d = abs(float(obs_tt[j]) - tt)
                if d <= tol:
                    pairs.append((d, ri, j))
    pairs.sort(key=lambda p: p[0])

    used_ref: set[int] = set()
    used_obs: set[int] = set()
    match_pairs: list[tuple[int, int, float]] = []
    for d, ri, j in pairs:
        if ri in used_ref or j in used_obs:
            continue
        used_ref.add(ri)
        used_obs.add(j)
        match_pairs.append((ri, j, d))

    # ── 2. 强峰加权位置项 + 加权漏峰项 (S09: 按"可观测参考峰"口径) ──
    i_max = max((i for _, i in refs), default=0.0)
    if i_max > 0:
        weights = [_FOM_W_MIN + (1.0 - _FOM_W_MIN) * (i / i_max) for _, i in refs]
    else:
        weights = [1.0] * len(refs)

    # ── S10: 互斥匹配对上的最优强度尺度因子 s* ────────────────
    # 只用强线 (I_ref/Imax ≥ 0.2) 的匹配对拟合 —— 弱线参考峰容易被贪心
    # 配到无关强实测峰, 会把最小二乘拉爆 (实测 5-1 方石英 s*=400 失真)。
    # 无强线匹配对时回退全部匹配对。
    s_star = 0.0
    if match_pairs:
        strong_ri = set()
        if i_max > 0:
            strong_ri = {k for k, (_tt, it) in enumerate(refs)
                         if it / i_max >= 0.2}
        fit_pairs = [(ri, j) for ri, j, _d in match_pairs
                     if (ri in strong_ri or not strong_ri)]
        if not fit_pairs:
            fit_pairs = [(ri, j) for ri, j, _d in match_pairs]
        num = 0.0
        den = 0.0
        for ri, j in fit_pairs:
            w = weights[ri]
            r_i = refs[ri][1]
            o_i = float(obs_int[j])
            num += w * o_i * r_i
            den += w * r_i * r_i
        if den > 1e-12:
            s_star = max(num / den, 0.0)

    # ── S09: 可观测性过滤 (默认全可见 = 与 v2.1 行为一致) ─────
    visible = [True] * len(refs)
    if obs_range is not None:
        lo, hi = float(obs_range[0]), float(obs_range[1])
        visible = [v and (lo <= tt <= hi) for (tt, _i), v in zip(refs, visible)]
    eff_scale = None
    if scale == "auto":
        eff_scale = s_star if s_star > 0 else None
    elif isinstance(scale, (int, float)) and float(scale) > 0:
        eff_scale = float(scale)
    max_obs_int = float(obs_int.max()) if obs_int.size else 0.0
    if eff_scale is not None and max_obs_int > 1e-12:
        thr = 0.01 * max_obs_int
        visible = [v and (eff_scale * it >= thr)
                   for (_tt, it), v in zip(refs, visible)]
    elif min_visible_frac > 0 and i_max > 0:
        visible = [v and (it / i_max >= min_visible_frac)
                   for (_tt, it), v in zip(refs, visible)]
    vis = [k for k, v in enumerate(visible) if v]
    vis_set = set(vis)
    w_sum = float(sum(weights[k] for k in vis))
    if w_sum <= 1e-12:
        # 没有任何可观测参考峰: 该相在本谱上不可判读
        return FoMResult(score=999.0, matched=0,
                         missed=len(vis) if vis else len(refs),
                         position_penalty=2.0, intensity_score=0.0,
                         method="fom", delta_2theta=float(tol),
                         unexplained_obs=int(obs_tt.size),
                         total_obs=int(obs_tt.size),
                         scale=float(s_star), scale_rel=0.0)

    sum_dev = 0.0
    matched_w = 0.0
    matched = 0
    for ri, _j, d in match_pairs:
        if ri in vis_set:
            sum_dev += weights[ri] * (d / tol)
            matched_w += weights[ri]
            matched += 1
    bad = (sum_dev + (w_sum - matched_w)) / w_sum
    missed = len(vis) - matched

    # ── 3. 特异性: 未被解释的实验峰 (v2.1 P1-3: 强度加权) ─────
    # 旧口径 = 未解释峰数/总峰数 —— 峰检测无幅度下限时, 噪声峰(数多但强度低)
    # 会把该比项推到 ~0.88, 特异性惩罚被打满, FoM 区分力丧失。
    # 改为强度加权: Σ(未解释峰强度)/Σ(全部观测峰强度) —— 噪声峰贡献的强度
    # 占比天然很小, 而一条真正强而未被解释的峰仍能给出有力惩罚。
    n_obs = int(obs_tt.size)
    unexplained = n_obs - len(used_obs)
    total_int = float(np.sum(obs_int)) if n_obs else 0.0
    if n_obs == 0:
        unexp_ratio = 0.0
    elif total_int > 1e-12:
        unexp_int = float(np.sum(
            obs_int[j] for j in range(n_obs) if j not in used_obs
        ))
        unexp_ratio = unexp_int / total_int
    else:
        # 全零强度 (退化输入): 回退计数口径
        unexp_ratio = unexplained / n_obs

    # ── 4. 强度一致性: 匹配对上的余弦相似度 (尺度无关, 比 min/max 稳) ──
    ic = 0.0
    if use_intensity and matched >= 2:
        ref_v = np.asarray([refs[ri][1] for ri, _, _ in match_pairs], dtype=float)
        obs_v = np.asarray([obs_int[j] for _, j, _ in match_pairs], dtype=float)
        nr = float(np.linalg.norm(ref_v))
        no = float(np.linalg.norm(obs_v))
        if nr > 1e-12 and no > 1e-12:
            ic = float(np.dot(ref_v, obs_v) / (nr * no))
            ic = min(max(ic, 0.0), 1.0)

    score = bad + _FOM_SPEC_WEIGHT * unexp_ratio
    if use_intensity:
        score *= (1.0 - _FOM_INTENSITY_WEIGHT * ic)

    # ── S10: 尺度因子连续降权 (默认 0 = 关) ───────────────────
    # scale_rel 低 = 该相所需强度尺度远小于谱中最强实测峰
    # (微量相 / 配噪声), 应使其得分变差 (排后) 而非变好。
    scale_rel = 0.0
    if s_star > 0 and i_max > 0 and max_obs_int > 1e-12:
        scale_rel = min(max(s_star * i_max / max_obs_int, 0.0), 1.0)
        if scale_penalty > 0:
            score *= (1.0 + scale_penalty * (1.0 - scale_rel))

    return FoMResult(
        score=float(max(score, 1e-4)),
        matched=matched,
        missed=missed,
        position_penalty=float(bad),
        intensity_score=ic,
        method="fom",
        delta_2theta=float(tol),
        unexplained_obs=int(unexplained),
        total_obs=n_obs,
        scale=float(s_star),
        scale_rel=float(scale_rel),
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
    if any(ch in pattern for ch in "*?"):
        # 带通配符: fnmatchcase 之外再对小写化两侧匹配一次,
        # 否则 "*corundum*" 永远命中不了 "Corundum" (M09 修复)
        if fnmatch.fnmatchcase(name, pattern):
            return True
        return fnmatch.fnmatchcase(name.lower(), pattern.lower())
    return pattern.lower() in name.lower()


def _passes_options(phase: Phase, opts: SearchOptions) -> bool:
    if opts.name_pattern and not _name_matches(phase.name or "", opts.name_pattern):
        return False
    from polyxrd.utils.formula_parser import elements_match_filter
    return elements_match_filter(
        phase.elements or set(),
        has=opts.must,
        maybe=opts.maybe,
        exclude=opts.exclude,
        must_have=opts.must_have,
    )


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

        conf = confidence_from_score(fom.score)
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
