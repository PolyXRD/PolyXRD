"""
多相迭代识别 (M11, Sprint 1)
============================
"识别-扣除-再识别" 闭环:
  1) 用 M10 增强 FoM 在候选池中选出最可信物相;
  2) 用 M06 残差峰把已解释的实测峰移除;
  3) 在残差峰上继续下一轮, 直到无新相 / 无进展 / 残差峰耗尽。

与贪心单轮 top-k 截断的区别: 微量相被主相峰"淹没"时, 只要它拥有未被解释的
独立峰, 就能在后续轮次被召回 (对应 Match! 的 trace 相探测)。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Iterable, Optional

from polyxrd.models.peak import PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.search_options import SearchOptions
from polyxrd.services.foam import search_match
from polyxrd.services.peak_manager import PeakManager


def iterative_identify(
    observed: PeakList,
    phases: Iterable[Phase],
    options: Optional[SearchOptions] = None,
    max_rounds: int = 6,
    min_round_score: float = 999.0,
    min_round_matches: int = 2,
    regions=None,
    progress_cb: Optional[Callable[[int, PhaseMatchResult, int], None]] = None,
) -> list[PhaseMatchResult]:
    """迭代多相识别。

    Args:
        observed: 实测峰表 (PeakList)
        phases: 候选池 (Phase 列表)
        options: M10 SearchOptions (元素约束/三强预检/窗口等)
        max_rounds: 最多识别轮数
        min_round_score: 单轮可接受最大 score (超过视为不可信, 停止)
        min_round_matches: 每轮候选最少解释的实测峰数。真实数据里
            1 峰巧合匹配的噪声相 (Graphite/Diamond 类) 非常多, 过滤掉
            可显著抑制假相; 微量相若只解释 1 峰可将其调回 1。
        regions: 全程忽略的 2θ 区间 (传入 M06 残差计算)
        progress_cb: 每轮回调 (round_index, best, residual_count)

    Returns:
        按识别顺序排列的 PhaseMatchResult 列表
    """
    opts = options or SearchOptions()
    pool = [p for p in phases if p is not None]
    residual_peaks = [replace(p) for p in observed.peaks]
    chosen: list[PhaseMatchResult] = []
    chosen_phases: list[Phase] = []

    for rnd in range(max_rounds):
        if not residual_peaks:
            break
        tt = [p.two_theta for p in residual_peaks]
        ii = [p.intensity for p in residual_peaks]
        cands = search_match(tt, ii, pool, options=opts)
        good = [c for c in cands
                if c.matched_peaks >= min_round_matches
                and c.score < min_round_score]
        if not good:
            break
        best = good[0]
        before = len(residual_peaks)

        chosen.append(best)
        chosen_phases.append(best.phase)
        pool = [p for p in pool if p.name != best.phase.name
                or p is best.phase]

        # 残差判定窗口与 FoM 匹配窗口保持一致, 避免"已解释峰再次出现"
        from polyxrd.services.foam import delta_2theta_auto as _dta
        if opts.delta_2theta is not None:
            tol = opts.delta_2theta
        elif opts.delta_2theta_auto:
            tol = _dta(observed, default_fwhm=opts.default_fwhm,
                       factor=opts.delta_2theta_factor)
        else:
            tol = opts.tol_fallback

        new_res = PeakManager.compute_residual_peaks(
            PeakList(peaks=residual_peaks, source=observed.source),
            chosen_phases,
            tolerance=tol,
            regions=regions,
        )
        if progress_cb is not None:
            progress_cb(rnd, best, len(new_res))

        # 无进展保护: 该相没有解释掉任何残差峰 → 冗余, 终止
        if len(new_res) >= before:
            break
        residual_peaks = list(new_res.peaks)
        if not residual_peaks:
            break

    return chosen


def trace_report(results: list[PhaseMatchResult]) -> list[dict]:
    """输出逐轮诊断: 相名/化学式/匹配峰数/FoM。"""
    return [
        {
            "round": i + 1,
            "name": r.phase.name,
            "formula": r.phase.formula,
            "matched_peaks": r.matched_peaks,
            "total_peaks": r.total_peaks,
            "score": r.score,
        }
        for i, r in enumerate(results)
    ]
