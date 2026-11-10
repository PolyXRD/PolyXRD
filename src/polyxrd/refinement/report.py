"""D3 诚实诊断 —— 把「模型缺了什么」变成可读清单，而不是让用户猜 Rwp。

为什么需要它
------------
Rietveld 最骗人的不是发散，而是「收敛得很漂亮但物理上错」。Rwp 是个**整体**
数字：一个 2% 含量的未知相、一段欠拟合的背景、一个没开的 Kα2，都能让 Rwp
从 4% 涨到 9%，而用户在界面上只看到「9%」，不知道该动哪个杠杆。

本模块把问题拆成两类证据：

1. **残差结构**（``residual_stats``）：Durbin–Watson 自相关、分段 Rwp、
   负强度点数、最大残差位置。这些是「模型系统性缺项」的直接痕迹 —— 白噪声
   残差 DW≈2、分段均匀；否则一定有什么没建进去。
2. **参数病态**（透传 ``diagnostics``）：秩亏 / 高相关 / 贴边界。这些说明
   「数字算出来了但不可信」。

两类合起来出一份 ``Finding`` 清单，每条都带**下一步该试什么**（``hint``）。
刻意不自动改模型 —— 自动「修」会把用户的判断力也一起修掉，而且实测里
「Rwp 降了但结果错了」比「Rwp 高一点」危险得多。

与 GSAS-II ``ReportProblems`` 的关系：它只覆盖第 2 类（psing/SVD0/SVDsing/
Hcorr），本模块对齐这四个并补第 1 类。第 1 类是 v5.0.0 新增，四个参考工具
都没有。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .diagnostics import Diagnostics
from .goal import (GoalResult, classify_tier, evaluate_goals, refined_stage,
                   tier_note)
from .intensity import BRINDLEY_TAU
from .problem import pattern_metrics
from .quantitative import QuantResult

__all__ = [
    "Finding",
    "ResidualStats",
    "FitReport",
    "HIGH_VALUE_CODES",
    "audit",
    "build_report",
    "observed_peaks",
    "prioritise",
    "residual_stats",
]

#: 严重度排序（越小越严重）
SEVERITY_RANK: Dict[str, int] = {"error": 0, "warn": 1, "info": 2}

#: 告诉用户「这个结果本身错了」的码 —— 界面只显示前几条时它们不能被挤掉
HIGH_VALUE_CODES = frozenset({
    "RANK_DEFICIENT",
    "PHASE_NOT_DETECTED",
    "PHASE_UNSUPPORTED",
    "PHASE_FRACTION_UNVERIFIABLE",
    "PHASE_NEAR_DEGENERATE",
    "AT_BOUND",
    "SCALE_CORRELATED",
    "MICROABSORPTION_CLAMPED",
    # P0-J：显式关 PO 时 wt% 可被带偏数倍而 Rwp 只差 1 pp —— 界面只挂 4 条时必须
    # 优先露出，否则会被 AT_BOUND/BACKGROUND_TREND 之类"改了也看不出"的 warn 挤掉
    "PO_DISABLED_SUSPECT",
})

#: 「份额有没有谱线支撑」的判据（P2-10）—— 该相自身 I/Imax 到多少算强线
UNSUPPORTED_STRONG_REL = 0.30
#: 别的相要**多强**的线才算"能解释这个峰"（见 ``_phase_support`` 的掩膜说明）
UNSUPPORTED_MASK_REL = 0.05
#: 与**别的相**反射相距 ≤ 该值 → 这条强线被遮盖，不能当"这相存在"的证据
UNSUPPORTED_OVERLAP_TOL = 0.30
#: 别的相在同位置上的**加权强度**（rel×份额）比本相高这么多倍 → 本相那条线被埋掉
UNSUPPORTED_BURY_RATIO = 2.0
#: 观测峰与模型峰位的容差（模型反射表是 Bragg 位置、不含仪器零点，故另估偏移）
UNSUPPORTED_OBS_TOL = 0.20

# ── P0-E′：定量「近简并」判据（评估报告 §13.8 第 3 条）────────────
#: 该相**最强独立线**的观测净积分占全谱净积分低于该值 → 约束太弱
NEAR_DEGENERATE_SHARE = 0.15
#: 把该相 wt% 推 ``NEAR_DEGENERATE_TARGET_PP`` 个百分点所需的 Rwp 代价
#: 超过该比值 → 「wt% 与 Rwp 脱钩」，只能给区间不能给点值
NEAR_DEGENERATE_WT_PER_RWP = 50.0
#: 探针把该相 wt% 推动多少个**百分点**（与 Rwp 变化量的单位同为 pp）
NEAR_DEGENERATE_TARGET_PP = 10.0
#: 最强独立线的净积分窗口半宽（度）。S4b 白云母 002 用 ±1.0° 得 1.1%，
#: 与 ``peak_share.py`` 的 8.0–10.2° 窗口同口径
NEAR_DEGENERATE_WINDOW_DEG = 1.0




def prioritise(findings: Sequence[Finding], limit: int = 4,
               severities: Sequence[str] = ("error", "warn")) -> List[Finding]:
    """挑出送进界面的前 ``limit`` 条（同级内 ``HIGH_VALUE_CODES`` 优先）。

    为什么需要它：服务层只把前 4 条 error/warn 写进 ``diagnostics``，而
    ``audit`` 的排序键是 ``(severity, code)`` —— 同级内**纯按字母**。实测
    WO3+W20O58 那条 ``PHASE_FRACTION_UNVERIFIABLE`` 正好排第 4；再多一条
    ``NEGATIVE_CALC``（字母更靠前）就会被静默截掉，而它恰恰是"这个 wt% 不可信"
    的唯一提示。宁可少报一条无关紧要的提示，也不能把"结果本身错了"挤出去。
    """
    pool = [f for f in findings if f.severity in severities]
    pool.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 9),
                             0 if f.code in HIGH_VALUE_CODES else 1))
    return pool[:limit]


def _noise_sigma(y: np.ndarray) -> float:
    """由二阶差分稳健估噪声 σ（``var(d2)=6σ²``，不受局部斜率影响）。"""
    if y.size < 5:
        return 0.0
    d2 = y[1:-1] - 2.0 * y[:-2] + y[2:]
    return float(1.4826 * float(np.median(np.abs(d2))) / math.sqrt(6.0))


def observed_peaks(two_theta, y_obs, *, rel: float = 0.01,
                   snr: float = 5.0) -> List[Tuple[float, float]]:
    """观测峰表 ``[(2θ, 突出度/Imax)]``，判据是 **prominence**。

    与 ``scripts/bench_wo3_validate.py`` 同一口径（P2-5 定稿，2026-11-05）。
    为什么不用"绝对局部极大"：主峰陡降尾巴上的噪声起伏会被判成峰 —— WO3 实测
    里 ``24.64:978 > 24.66:896 > 24.68:812`` 就这么把 24.34° 主峰的衰减段
    报成了"24.66° 有峰"。prominence 对单调坡上的噪声包给 0（左肩根本没有
    下坡），对坐在大峰肩上的真峰给出"翻过山坳"的正突出度，两类都能分开。
    """
    from scipy.signal import find_peaks

    x = np.asarray(two_theta, dtype=float).reshape(-1)
    y = np.asarray(y_obs, dtype=float).reshape(-1)
    if x.size != y.size or y.size < 9:
        return []
    y = y - float(np.percentile(y, 1))
    if float(y.max()) <= 0:
        return []
    ys = np.convolve(y, np.array([0.25, 0.5, 0.25]), mode="same")
    ys[:2] = y[:2]
    ys[-2:] = y[-2:]
    ymax = float(ys.max())
    prom = max(float(snr) * _noise_sigma(y), float(rel) * ymax)
    idx, props = find_peaks(ys, prominence=prom)
    return [(float(x[i]), float(p) / ymax)
            for i, p in zip(idx, props["prominences"])]


@dataclass(frozen=True)
class ResidualStats:
    """残差的结构性指标（不含参数信息，纯看谱）。"""

    durbin_watson: float
    segment_rwp: Tuple[float, ...]
    segment_edges: Tuple[float, ...]
    max_abs_resid: float
    max_abs_resid_at: float
    n_negative_calc: int
    n_points: int
    sigma: float

    def as_dict(self) -> dict:
        return {"durbin_watson": self.durbin_watson,
                "segment_rwp": list(self.segment_rwp),
                "segment_edges": list(self.segment_edges),
                "max_abs_resid": self.max_abs_resid,
                "max_abs_resid_at": self.max_abs_resid_at,
                "n_negative_calc": self.n_negative_calc,
                "n_points": self.n_points, "sigma": self.sigma}


def _segment_edges(tmin: float, tmax: float,
                   cuts: Sequence[float]) -> Tuple[float, ...]:
    edges = [float(tmin)]
    for c in cuts:
        if tmin < float(c) < tmax:
            edges.append(float(c))
    edges.append(float(tmax))
    return tuple(edges)


def residual_stats(
    two_theta,
    y_obs,
    y_calc,
    weights=None,
    *,
    segments: Sequence[float] = (30.0, 60.0),
) -> ResidualStats:
    """残差结构统计。

    * ``durbin_watson = Σ(r_i − r_{i−1})² / Σ r_i²``：白噪声 ≈ 2；明显 < 2
      说明残差逐点相关（模型缺项）；> 2 说明相邻点**反向**摆动（过度拟合
      或网格/平滑伪影）。
    * 分段 ``Rwp``：同一公式按角度区间各算一次，暴露出「哪一段没拟合好」。
      整体 Rwp 会把低角 3 个强峰的误差平摊掉。
    """
    x = np.asarray(two_theta, dtype=float).reshape(-1)
    y = np.asarray(y_obs, dtype=float).reshape(-1)
    yc = np.asarray(y_calc, dtype=float).reshape(-1)
    n = y.size
    if n == 0 or x.size != n or yc.size != n:
        return ResidualStats(float("nan"), (), (), float("nan"), float("nan"),
                             0, 0, float("nan"))
    w = np.ones(n) if weights is None else np.asarray(weights, float).reshape(-1)

    r = y - yc
    denom = float(np.sum(r * r))
    if denom > 0 and n > 1:
        dw = float(np.sum(np.diff(r) ** 2) / denom)
    else:  # pragma: no cover - 完美拟合
        dw = float("nan")

    edges = _segment_edges(float(x[0]), float(x[-1]), segments)
    seg: List[float] = []
    for k, (a, b) in enumerate(zip(edges, edges[1:])):
        last = k == len(edges) - 2
        sel = (x >= a) & (x <= b) if last else (x >= a) & (x < b)
        if not np.any(sel):
            seg.append(float("nan"))
            continue
        num = float(np.sum(w[sel] * r[sel] ** 2))
        den = float(np.sum(w[sel] * y[sel] ** 2))
        seg.append(math.sqrt(num / den) * 100.0 if den > 0 else float("nan"))

    i_max = int(np.argmax(np.abs(r)))
    sigma = 1.4826 * float(np.median(np.abs(r - np.median(r))))
    return ResidualStats(
        durbin_watson=dw, segment_rwp=tuple(seg), segment_edges=edges,
        max_abs_resid=float(abs(r[i_max])), max_abs_resid_at=float(x[i_max]),
        n_negative_calc=int(np.count_nonzero(yc < 0.0)), n_points=int(n),
        sigma=float(sigma) if np.isfinite(sigma) else 0.0)


@dataclass(frozen=True)
class Finding:
    """一条诊断结论（``code`` 稳定，供 UI 做图标/筛选）。"""

    code: str
    severity: str
    message: str
    hint: str = ""
    evidence: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "message": self.message, "hint": self.hint,
                "evidence": dict(self.evidence)}

    def text(self) -> str:
        tag = {"error": "错误", "warn": "警告", "info": "提示"}.get(
            self.severity, self.severity)
        s = f"[{tag}] {self.message}"
        if self.hint:
            s += f" → {self.hint}"
        return s


def _positive_clusters(r: np.ndarray, thr: float) -> List[int]:
    """残差超过阈值的**连续段**，返回每段内峰值位置的下标。"""
    idx = np.flatnonzero(r > thr)
    if idx.size == 0:
        return []
    splits = np.flatnonzero(np.diff(idx) > 1)
    groups = np.split(idx, splits + 1)
    return [int(g[int(np.argmax(r[g]))]) for g in groups if g.size >= 2]


def noise_scale(y_obs, resid_sigma: float) -> float:
    """残差噪声尺度的稳健估计，``max(MAD 估计, 计数统计下限)``。

    为什么不能只用 MAD：残差大部分点恰好为 0 时（合成数据、或模型把整条谱都
    跟住了只漏一个小峰），``median|r − median(r)| = 0``，于是"超过 6σ"的阈值
    变成 0，规则不是"报错"而是**静默失效** —— 恰恰在最该报的场合不报。

    下限取 ``median(√y)``：XRD 是计数实验，单个通道的本征噪声就是 ``√N``。
    这条下限与"这条谱有多少计数"绑定，而不是拍一个绝对值。
    """
    y = np.maximum(np.asarray(y_obs, dtype=float).reshape(-1), 0.0)
    poisson = float(np.median(np.sqrt(y))) if y.size else 0.0
    return max(float(resid_sigma), poisson)


def _reflection_shift(obs_positions, calc_centers) -> float:
    """观测峰 ↔ 计算峰位的中位偏移（度）。

    反射表是 Bragg 位置、不含仪器零点；不先对齐的话，一个 0.3° 的零点就会把
    所有相都判成"无支撑"。只采纳 ``|δ| ≤ 0.5°`` 的配对，少于 3 对不判（返回 0）。
    """
    if calc_centers is None or not np.size(calc_centers) or not len(obs_positions):
        return 0.0
    cal = np.sort(np.asarray(calc_centers, dtype=float).ravel())
    offs = []
    for t in obs_positions:
        d = float(t - cal[int(np.argmin(np.abs(cal - t)))])
        if abs(d) <= 0.5:
            offs.append(d)
    return float(np.median(offs)) if len(offs) >= 3 else 0.0


def _phase_support(
    x: np.ndarray,
    y: np.ndarray,
    phase_peaks,
    quant: Optional[QuantResult],
    calc_centers,
    *,
    min_fraction: float = 0.01,
    strong_rel: float = UNSUPPORTED_STRONG_REL,
    mask_rel: float = UNSUPPORTED_MASK_REL,
    overlap_tol: float = UNSUPPORTED_OVERLAP_TOL,
    bury_ratio: float = UNSUPPORTED_BURY_RATIO,
    obs_tol: float = UNSUPPORTED_OBS_TOL,
) -> List[Finding]:
    """P2-10：份额非零，但**没有一条强线能独立支撑它** → 这个 wt% 不可信。

    :param phase_peaks: ``[(label, two_theta, intensity)]``，各相的反射表
        （``ReflectionTable.intensity`` = ``|F|²·LP·w_λ`` 归并和，未乘标度）。

    为什么不能只看份额与 Rwp：**大胞相自带独立峰宽参数**，能把样品展宽造成的
    失配整块摊平，于是 Rwp 变好、份额非零，而该相在谱上其实没有任何独立证据。
    WO3 实测（2026-11-05）：W20O58 分到 15.6 %、Rwp 降 3.0 pp，但它最强判别线
    24.66°（该相 I/Imax 0.67）是主峰 24.34° 的单调衰减尾巴；同批对照里"不该有"
    的 MoO3 分到 1.3 %、WO2 2.8 %、α/γ 同相异型互分 28~98 %。

    判据逐条强线（自身 I/Imax ≥ ``strong_rel``）算**加权强度**
    ``w = rel × 份额``，再看同位置（±``overlap_tol``）上别的相能不能给出
    ``≥ bury_ratio × w``：

    * 能 → 这条线被埋掉，**不构成证据**（位置重合还不够，得看谁更强；
      只看位置重合会把主相自己判成"全部重叠"，实测就撞过）；
    * 不能 → **可作证据**，再看 ±``obs_tol`` 内有没有观测峰。

    然后分三支：

    * 有可作证据的线且有观测峰 → 该相有支撑，**不报**；
    * 有可作证据的线但一条都没观测到 → ``PHASE_UNSUPPORTED``（硬证据：
      MoO3 对照臂就是这一支，1.29 %、27.51° 那条线谱上没有）；
    * **一条可作证据的线都没有** → ``PHASE_FRACTION_UNVERIFIABLE``（软证据：
      该 wt% 完全由峰宽/背景自由度决定。W20O58 就是这一支：引擎算出的 5 条强线
      23.55 / 24.39 / 24.36 / 34.16 / 23.05 全落在 WO3 的 23.08 / 24.18 / 23.67 /
      34.09 / 33.30 的 0.30° 内，最小间距 0.03°，加权后又被主相压 5 倍）。

    ⚠ 掩膜必须按强度筛，不能用整张反射表：引擎的 ``ReflectionTable`` 是**计算**
    反射表（``noise_ratio=1e-9`` 全收），WO3 在 20–90° 有 **323** 条、W20O58 有
    **762** 条。70° 里 323 条线、平均间距 0.22° —— 拿全表当掩膜，等于任何位置都
    "被主相盖住"，守卫会 100% 沉默（2026-11-05 首次端到端验收就栽在这里：
    W20O58 15.63 wt% 没报，反倒只报了 MoO3）。
    """
    tabs = [(str(lab), np.asarray(tt, dtype=float).ravel(),
             np.asarray(ii, dtype=float).ravel())
            for lab, tt, ii in (phase_peaks or ()) if np.size(tt)]
    if not tabs or y.size == 0:
        return []
    obs = observed_peaks(x, y)
    if not obs:
        return []                       # 峰表不可用就沉默，不凭空的"没峰"定罪
    o = np.asarray([t for t, _ in obs], dtype=float)

    fracs: Dict[str, float] = {}
    if quant is not None and getattr(quant, "labels", None):
        fracs = {str(l): float(f) for l, f in zip(quant.labels, quant.fractions)}

    # 反射表是 Bragg 位置（不含仪器零点），用"观测峰 ↔ 计算峰位"的中位偏移对齐；
    # 不先对齐的话，一个 0.3° 的零点就会把所有相都判成"无支撑"
    shift = _reflection_shift(o, calc_centers)

    out: List[Finding] = []
    for i, (lab, tt, ii) in enumerate(tabs):
        frac = fracs.get(lab, 1.0)
        imax = float(ii.max()) if ii.size else 0.0
        if frac < min_fraction or not tt.size or imax <= 0:
            continue
        rel_i = ii / imax
        sel = rel_i >= strong_rel
        if not sel.any():
            continue
        pos = tt[sel] + shift
        rel_s = rel_i[sel]
        n_strong = int(pos.size)
        # 掩膜 = 别的相里**真能被看见**的线（I ≥ mask_rel），带**加权强度**
        # w = rel × 份额：位置重合只是"可能被解释"，得看谁更强才算埋掉。
        # 只按位置筛会把主相自己判成"全部重合"（实测撞过：WO3 84 wt% 被报）。
        m_pos: List[float] = []
        m_w: List[float] = []
        for j, (l2, tt2, ii2) in enumerate(tabs):
            f2 = fracs.get(l2, 1.0)
            if j == i or f2 < min_fraction:
                continue
            m2 = float(ii2.max()) if ii2.size else 0.0
            if m2 <= 0:
                continue
            rel2 = ii2 / m2
            sel2 = rel2 >= mask_rel
            m_pos.extend((tt2[sel2] + shift).ravel().tolist())
            m_w.extend((rel2[sel2] * f2).ravel().tolist())
        gap_min = None
        if m_pos:
            mp = np.asarray(m_pos, dtype=float)
            mw = np.asarray(m_w, dtype=float)
            gaps, bury = [], []
            for p, r in zip(pos, rel_s):
                near = np.abs(mp - p) <= overlap_tol
                gaps.append(float(np.min(np.abs(mp[near] - p))) if near.any() else 99.0)
                # 同位置的"别人最强"能给出多少加权强度
                bury.append(float(np.max(mw[near])) if near.any() else 0.0)
            gaps = np.asarray(gaps)
            bury = np.asarray(bury)
            gap_min = float(np.min(gaps)) if gaps.size else None
            w_self = rel_s * frac
            capable = bury < bury_ratio * w_self
            pos, rel_s = pos[capable], rel_s[capable]
        if not pos.size:
            # 一条能独立支撑的强线都没有 → 份额由峰宽/背景自由度决定
            out.append(Finding(
                "PHASE_FRACTION_UNVERIFIABLE", "warn",
                f"{lab} 被定量到 {100 * frac:.2f} wt%，但它 {n_strong} 条强线"
                f"（I/Imax ≥ {strong_rel:.0%}）在谱上都被其它相更强的线压住"
                f"（最近间距 {gap_min:.2f}°）——该份额完全由峰宽/背景自由度决定，"
                "数据没有独立约束它",
                "补一条属于该相、且与主相分开 >0.3° 的线（换靶/延长扫描/更高"
                "分辨率）再定量；否则只报检出、不报数字。份额非零 ≠ 该相存在"
                "（详见 docs/待办清单.md P2-10）",
                {"phase": lab,
                 "fraction": float(frac),
                 "n_strong": float(n_strong),
                 "min_gap": float(gap_min) if gap_min is not None else 0.0,
                 "zero_shift": float(shift)}))
            continue
        if any(float(np.min(np.abs(o - p))) <= obs_tol for p in pos):
            continue
        k = int(np.argmax(rel_s))
        out.append(Finding(
            "PHASE_UNSUPPORTED", "warn",
            f"{lab} 被定量到 {100 * frac:.2f} wt%，但它 {pos.size} 条唯一强线"
            f"（该相 I/Imax ≥ {strong_rel:.0%}）在实测中一条都没出现"
            f"（最强 {pos[k]:.2f}° 应有 I/Imax={rel_s[k]:.2f}）"
            "—— 这个份额没有谱线支撑",
            "先确认这条线是否在扫描窗口内、是否被择优取向压低；都不是就把该相"
            "删掉重拟合。份额非零 ≠ 该相存在：多出来的衍射强度会被峰宽/背景"
            "自由度吸收，Rwp 反而更低（详见 docs/待办清单.md P2-10）",
            {"phase": lab,
             "fraction": float(frac),
             "strongest_2theta": float(pos[k]),
             "strongest_rel": float(rel_s[k]),
             "n_unique_strong": float(pos.size),
             "zero_shift": float(shift)}))
    return out


def net_area_above_baseline(
    x: np.ndarray, y: np.ndarray,
    lo: Optional[float] = None, hi: Optional[float] = None,
    edge: int = 5,
) -> float:
    """窗口内（两端均值连线基线以上的）净积分。

    用于「某条线的净面积」和「全谱净面积」的同一口径比值；不依赖拟合背景，
    所以不会因为背景自由度把份额稀释掉。
    """
    sel = np.ones(x.size, dtype=bool)
    if lo is not None:
        sel &= x >= lo
    if hi is not None:
        sel &= x <= hi
    if np.count_nonzero(sel) < 5:
        return 0.0
    xs = np.asarray(x[sel], dtype=float)
    ys = np.asarray(y[sel], dtype=float)
    n = max(1, min(int(edge), xs.size // 2))
    base = np.interp(xs, [xs[0], xs[-1]],
                     [float(ys[:n].mean()), float(ys[-n:].mean())])
    return float(np.trapezoid(np.maximum(ys - base, 0.0), xs))


def _near_degenerate(
    x: np.ndarray,
    y: np.ndarray,
    phase_peaks,
    quant: Optional[QuantResult],
    calc_centers,
    *,
    wt_rwp_probe: Optional[Dict[str, Tuple[float, float, float]]] = None,
    min_fraction: float = 0.01,
) -> List[Finding]:
    """P0-E′：判某相 wt% 是否「近简并」——有强线、但线太弱，wt 与 Rwp 脱钩。

    两条判据同时成立才报（评估报告 §13.8）：

    1. 该相**最强独立线**的观测净积分占全谱净积分 ``< NEAR_DEGENERATE_SHARE``；
    2. 把该相 wt% 推 ``NEAR_DEGENERATE_TARGET_PP`` 个百分点，Rwp 只变
       ``< target / NEAR_DEGENERATE_WT_PER_RWP``（即 Δwt/ΔRwp > 50 pp/%）。

    "独立线"= 该相最强反射且不被别的相的同位置强线压过（复用 P2-10 的埋葬判据）。
    找不到独立线时**不报**——那属于 ``PHASE_FRACTION_UNVERIFIABLE`` 的范畴。
    """
    if quant is None or not getattr(quant, "labels", None) or len(quant.labels) < 2:
        return []
    if wt_rwp_probe is None or not wt_rwp_probe:
        return []
    tabs = []
    for ph in phase_peaks or ():
        try:
            lab, tt, ii = ph
        except (TypeError, ValueError):
            continue
        tt = np.asarray(tt, dtype=float).ravel()
        ii = np.asarray(ii, dtype=float).ravel()
        if tt.size == 0 or ii.size != tt.size:
            continue
        tabs.append((str(lab), tt, ii))
    if not tabs:
        return []

    fracs = {str(l): float(f) for l, f in zip(quant.labels, quant.fractions)}
    obs = observed_peaks(x, y)
    shift = _reflection_shift([t for t, _ in obs], calc_centers)
    total = net_area_above_baseline(x, y)
    if total <= 0.0:
        return []

    out: List[Finding] = []
    for i, (lab, tt, ii) in enumerate(tabs):
        frac = fracs.get(lab)
        if frac is None or frac < min_fraction:
            continue
        probe = wt_rwp_probe.get(lab)
        if not probe:
            continue
        imax = float(ii.max())
        if imax <= 0.0:
            continue
        rel = ii / imax
        idx = int(np.argmax(ii))
        pos = tt[idx] + shift
        if pos < float(x[0]) or pos > float(x[-1]):
            continue
        # 埋葬判据：别的相在同位置上的加权强度比本相高 2 倍 → 这条最强线不是
        # "本相独立证据"，不能用它衡量约束力
        w_self = float(rel[idx]) * frac
        buried = 0.0
        for j, (lab2, tt2, ii2) in enumerate(tabs):
            if j == i:
                continue
            f2 = fracs.get(lab2)
            if f2 is None or f2 < min_fraction:
                continue
            m2 = float(ii2.max())
            if m2 <= 0.0:
                continue
            near = np.abs(tt2 - tt[idx]) <= UNSUPPORTED_OVERLAP_TOL
            if np.any(near):
                buried = max(buried, float(np.max(ii2[near] / m2 * f2)))
        if buried >= UNSUPPORTED_BURY_RATIO * w_self:
            continue

        area = net_area_above_baseline(
            x, y, pos - NEAR_DEGENERATE_WINDOW_DEG, pos + NEAR_DEGENERATE_WINDOW_DEG)
        if area <= 0.0:
            continue
        share = area / total
        try:
            import os
            if os.environ.get("POLYXRD_DEBUG_P0E"):
                print(f"[P0E] {lab} strongest={pos:.2f}° "
                      f"share={100 * share:.2f}% probe={probe}", flush=True)
        except Exception:  # noqa: BLE001
            pass
        if share >= NEAR_DEGENERATE_SHARE:
            continue

        ratio, d_wt, d_rwp = probe
        if ratio < NEAR_DEGENERATE_WT_PER_RWP:
            continue
        out.append(Finding(
            "PHASE_NEAR_DEGENERATE", "warn",
            f"{lab} 被定量到 {100 * frac:.2f} wt%，但其最强独立线 {pos:.2f}° 的"
            f"净积分只占全谱 {100 * share:.1f}%（判据 <"
            f"{100 * NEAR_DEGENERATE_SHARE:.0f}%）：把该相 wt% 推 {d_wt:.1f} pp"
            f" 只需 Rwp 变 {d_rwp:.2f} pp（{ratio:.0f} pp/% > "
            f"{NEAR_DEGENERATE_WT_PER_RWP:.0f}）——份额与拟合质量近乎脱钩",
            "这个 wt% 只能当区间读：不要当点值、不要用它判定两版算法优劣。"
            "要更可信：补一条该相孤立强线（换靶/扩角/提高分辨率），或先用化学"
            "分析、热重、光学显微等谱外手段把该相含量定住并作为先验；若只能就谱"
            "论谱，请在报告里给出 wt% 的 Rwp 摆动区间（按 ±0.2 pp Rwp 折算）",
            {"phase": lab,
             "fraction_pct": float(100 * frac),
             "strongest_2theta": float(pos),
             "share_pct": float(100 * share),
             "ratio": float(ratio),
             "delta_wt_pp": float(d_wt),
             "delta_rwp_pp": float(d_rwp)}))
    return out


def wt_ranges_from_findings(
    findings,
    *,
    rwp_step_pp: float = 0.2,
) -> Dict[str, List[float]]:
    """P0-E′ 产品化：近简并相 → wt% 区间（``{相名: [lo, hi]}``，单位 wt%）。

    只收 ``PHASE_NEAR_DEGENERATE`` 的 finding。区间按"Rwp 摆动
    ``rwp_step_pp`` 个百分点"折算：``half = ratio·rwp_step_pp``。
    ratio 是 probe 直接量到的 ``Δwt(pp)/ΔRwp(pp)``，对近简并相 > 50，
    所以 ±0.2 pp 的 Rwp 噪声就能换来 ±10 pp 以上的份额摆动 —— 这正是
    "不要给点值"的量化依据。下限保护 ``half ≥ 0.5``（避免数值噪声给出
    一个看似精确的窄区间）。
    """
    out: Dict[str, List[float]] = {}
    for f in findings or ():
        if getattr(f, "code", "") != "PHASE_NEAR_DEGENERATE":
            continue
        ev = getattr(f, "evidence", None) or {}
        try:
            lab = str(ev["phase"])
            frac = float(ev["fraction_pct"])
            ratio = float(ev["ratio"])
        except (KeyError, TypeError, ValueError):
            continue
        half = max(0.5, ratio * float(rwp_step_pp))
        out[lab] = [max(0.0, frac - half), min(100.0, frac + half)]
    return out


def audit(
    two_theta,
    y_obs,
    y_calc,
    weights=None,
    *,
    metrics: Optional[Dict[str, float]] = None,
    diagnostics: Optional[Diagnostics] = None,
    quant: Optional[QuantResult] = None,
    calc_centers: Optional[Sequence[float]] = None,
    phase_peaks: Optional[Sequence[Tuple[str, Sequence[float],
                                          Sequence[float]]]] = None,
    kalph2_modeled: bool = True,
    po_freed: bool = False,
    sample_freed: bool = False,
    atoms_freed: bool = False,
    gof_warn: float = 4.0,
    gof_error: float = 8.0,
    dw_warn: float = 1.5,
    segment_ratio_warn: float = 2.0,
    unidentified_snr: float = 6.0,
    unmatched_tol: float = 0.35,
    min_phase_fraction: float = 0.01,
    scale_corr=None,
    wt_rwp_probe: Optional[Dict[str, Tuple[float, float, float]]] = None,
) -> List[Finding]:
    """跑完整诊断规则，返回按严重度排序的 ``Finding`` 列表。

    :param calc_centers: 当前模型全部计算峰位（用于判断「残差峰有没有对应的
        反射」）；给 ``None`` 则跳过「疑似未识别相」这条规则 —— 没有对照就
        断言「多了个相」是不负责任的。
    :param phase_peaks: 各相自己的反射表 ``[(label, 2θ, 强度)]``，用于 P2-10
        的「份额有没有谱线支撑」；给 ``None`` 则跳过该规则（单相问题不存在）。
    :param kalph2_modeled: 前向模型里有没有 Kα2 双线
    :param po_freed / sample_freed: 择优取向 / 样品展宽是否已释放（决定能否
        把「低角差」归因到织构、「高角差」归因到峰宽）
    :param scale_corr: 相标度相关系数矩阵（``linear.scale_correlations``）。
        给了才判「两相份额不可分辨」—— 这条判据无法从 Rwp / 各自 σ 推出来：
        两相此消彼长时 Rwp 与两个 σ 都可以很漂亮，份额却整体错位。
    """
    y = np.asarray(y_obs, dtype=float).reshape(-1)
    yc = np.asarray(y_calc, dtype=float).reshape(-1)
    x = np.asarray(two_theta, dtype=float).reshape(-1)
    out: List[Finding] = []
    if y.size == 0 or yc.size != y.size:
        return out

    st = residual_stats(x, y, yc, weights)
    m = dict(metrics) if metrics else pattern_metrics(y, yc, weights)

    # ── 1. 整体吻合 ────────────────────────────────────────────
    gof = float(m.get("GOF", float("nan")))
    if math.isfinite(gof):
        if gof >= gof_error:
            out.append(Finding(
                "GOF_HIGH", "error",
                f"GOF={gof:.1f}（Rwp {m['Rwp']:.2f}% vs Rexp "
                f"{m['Rexp']:.2f}%）——模型有系统性缺项，不是噪声问题",
                "按顺序排查：是否有未识别相 → 择优取向 → Kα2 是否开启 → "
                "峰宽模型（尺寸/应变）是否够用 → 背景阶数",
                {"GOF": gof}))
        elif gof >= gof_warn:
            out.append(Finding(
                "GOF_HIGH", "warn",
                f"GOF={gof:.1f}：Rwp 明显高于噪声底",
                "看下面的分段 Rwp 定位到具体角度区间再动手",
                {"GOF": gof}))

    # ── 2. 残差自相关（模型缺项的指纹）────────────────────────
    if math.isfinite(st.durbin_watson) and st.durbin_watson < dw_warn:
        out.append(Finding(
            "RESIDUAL_SERIAL", "warn",
            f"残差逐点相关（DW={st.durbin_watson:.2f}，白噪声应≈2）"
            "——不是随机噪声，是模型缺项",
            "常见成因：Kα2 未建模、峰宽模型不足（缺尺寸/应变项）、"
            "背景阶数过低、峰形用单一 pV 但实际有明显不对称",
            {"durbin_watson": st.durbin_watson}))

    # ── 3. 分段失配 ────────────────────────────────────────────
    rwp_all = float(m.get("Rwp", float("nan")))
    if math.isfinite(rwp_all) and rwp_all > 0 and st.segment_rwp:
        worst_i = -1
        worst_ratio = 0.0
        for i, seg_r in enumerate(st.segment_rwp):
            if not math.isfinite(seg_r):
                continue
            ratio = seg_r / rwp_all
            if ratio > worst_ratio:
                worst_i, worst_ratio = i, ratio
        if worst_i >= 0 and worst_ratio >= segment_ratio_warn:
            a = st.segment_edges[worst_i]
            b = st.segment_edges[worst_i + 1]
            n_seg = len(st.segment_rwp)
            if worst_i == 0:
                hint = ("低角失配优先查：零位/样品位移、低角不对称、"
                        "择优取向（片状晶粒在低角偏强）")
                if not po_freed:
                    out.append(Finding(
                        "TEXTURE_SUSPECT", "warn",
                        "低角段明显更差，且择优取向参数未释放——疑似织构未修正",
                        "释放 March–Dollase r 再拟合；若 r 撞边界说明取向很强，"
                        "需要更复杂的取向模型",
                        {"segment_rwp": float(st.segment_rwp[worst_i])}))
            elif worst_i == n_seg - 1:
                hint = ("高角失配优先查：峰宽模型（尺寸/应变）、温度因子 B、"
                        "Kα2、以及峰位随角度的系统漂移（晶胞未收敛）")
                if not sample_freed:
                    out.append(Finding(
                        "WIDTH_MODEL_SUSPECT", "warn",
                        "高角段明显更差，且样品展宽参数未释放——疑似峰宽模型不足",
                        "释放晶粒尺寸与微应变（TCH）再拟合；"
                        "高角峰宽靠 Caglioti 的 tanθ 项硬撑往往撑不住",
                        {"segment_rwp": float(st.segment_rwp[worst_i])}))
            else:
                hint = "中角失配常见于结构因子/占位不准，或背景基形状不匹配"
            out.append(Finding(
                "SEGMENT_MISFIT", "warn",
                f"{a:.0f}–{b:.0f}° 段的 Rwp 是整体的 {worst_ratio:.1f} 倍"
                f"（{st.segment_rwp[worst_i]:.2f}% vs {rwp_all:.2f}%）",
                hint,
                {"segment_rwp": float(st.segment_rwp[worst_i]),
                 "segment_from": float(a), "segment_to": float(b)}))

    # ── 4. 计算谱负强度（退化解的硬证据）──────────────────────
    if st.n_negative_calc > 0:
        out.append(Finding(
            "NEGATIVE_CALC", "error",
            f"计算谱出现 {st.n_negative_calc} 个负强度点"
            "——背景或峰形参数跑成了非物理值",
            "检查背景系数与峰形参数是否撞边界；这通常是 LM 用负背景去补偿"
            "某个缺失的峰，收敛数字再漂亮也不能用",
            {"n_negative": float(st.n_negative_calc)}))

    # ── 5. 未建模 Kα2 ──────────────────────────────────────────
    if not kalph2_modeled:
        out.append(Finding(
            "KA2_UNMODELLED", "info",
            "未建模 Kα2 双线：Cu/Co 靶在中高角会留下系统性正残差，"
            "并让高角峰宽被高估",
            "开启前向双线（Kα2）后重新精修，再判断其他问题；"
            "Kα2 通常是高角失配的第一嫌疑",
            {}))

    # ── 6. 残差里的「多出来的峰」（疑似未识别相）─────────────
    if calc_centers is not None:
        cal = np.sort(np.asarray(list(calc_centers), dtype=float).reshape(-1))
        r = y - yc
        peaks = _positive_clusters(r, unidentified_snr * noise_scale(y, st.sigma))
        if cal.size:
            extra = [float(x[i]) for i in peaks
                     if np.min(np.abs(cal - float(x[i]))) > unmatched_tol]
            if extra:
                extra.sort()
                shown = ", ".join(f"{p:.2f}°" for p in extra[:6])
                out.append(Finding(
                    "UNIDENTIFIED_PEAKS", "warn",
                    f"{len(extra)} 处残差峰没有对应的计算反射（{shown}）"
                    "——疑似存在未纳入模型的物相",
                    "回到物相检索/确认流程补相；单靠精修参数无法吸收真正的"
                    "第二相峰",
                    {"n_unmatched": float(len(extra)),
                     "first_at": float(extra[0])}))

    # ── 7. 背景长程趋势 ────────────────────────────────────────
    if st.n_points >= 40:
        r = y - yc
        n_blk = min(20, max(4, st.n_points // 20))
        means = np.asarray([float(np.mean(b)) for b in np.array_split(r, n_blk)])
        k = max(1, st.n_points // n_blk)
        noise = max(noise_scale(y, st.sigma), 1e-12) / math.sqrt(k)
        sig_idx = np.flatnonzero(np.abs(means) > 3.0 * noise)
        runs = 0
        if sig_idx.size:
            splits = np.flatnonzero(np.diff(sig_idx) > 1)
            runs = max(len(g) for g in np.split(sig_idx, splits + 1))
        if runs >= 3:
            out.append(Finding(
                "BACKGROUND_TREND", "warn",
                f"残差有 {runs} 个连续区块的系统性偏移（最大 "
                f"{float(np.max(np.abs(means))) / noise:.1f}σ）"
                "——长程成分没被背景基吸收",
                "提高背景阶数（或改用 tent 节点）；若趋势是整体偏高/偏低，"
                "则是标度问题而非背景",
                {"max_block_mean": float(np.max(np.abs(means)))}))

    # ── 8. 参数病态（透传 diagnostics）─────────────────────────
    if diagnostics is not None:
        if diagnostics.rank_deficient:
            out.append(Finding(
                "RANK_DEFICIENT", "error",
                f"参数秩亏（秩 {diagnostics.rank}/{len(diagnostics.names)}，"
                f"SVD0={diagnostics.svd0_ratio:.1e}）：存在完全不可辨识的参数组合",
                "载荷参数：" + (", ".join(diagnostics.psing) or "未定位")
                + " → 用约束（等价/求和）或减少同时释放的自由度",
                {"svd0": diagnostics.svd0_ratio,
                 "rank": float(diagnostics.rank)}))
        if diagnostics.high_corr:
            top = diagnostics.high_corr[:3]
            pairs = ", ".join(f"{a}↔{b}(ρ={r:+.2f})" for a, b, r in top)
            out.append(Finding(
                "HIGH_CORRELATION", "warn",
                f"{len(diagnostics.high_corr)} 对参数高度相关：{pairs}",
                "相关对里的参数单独不可信（误差棒会失真）；"
                "固定其一或加约束再拟合",
                {"n_pairs": float(len(diagnostics.high_corr)),
                 "max_abs_rho": float(abs(top[0][2]))}))
        if diagnostics.at_bounds:
            out.append(Finding(
                "AT_BOUND", "warn",
                f"{len(diagnostics.at_bounds)} 个参数贴在边界上："
                + ", ".join(diagnostics.at_bounds[:6]),
                "撞界说明数据不支持这个自由度，或边界设得太紧；"
                "贴界的参数误差棒没有意义",
                {"n_at_bound": float(len(diagnostics.at_bounds))}))

    # ── 9. 定量结果可用性 ──────────────────────────────────────
    if quant is not None and quant.labels:
        for lab, frac, det in zip(quant.labels, quant.fractions,
                                  quant.detectable):
            if not det:
                out.append(Finding(
                    "PHASE_NOT_DETECTED", "error",
                    f"{lab} 的标度被压到 0（或低于检出限）——该相无法定量",
                    "确认该相是否真的存在；若存在，多半是晶胞/结构给错，"
                    "或该相的最强峰被主相完全遮盖",
                    {"fraction": float(frac)}))
            elif frac < min_phase_fraction:
                out.append(Finding(
                    "WEAK_PHASE", "info",
                    f"{lab} 含量 {100 * frac:.2f} wt%，低于可靠定量下限",
                    "报检出而不是报数字；微量相的相对误差会被放大到几十个百分点",
                    {"fraction": float(frac)}))
        if not atoms_freed:
            out.append(Finding(
                "STRUCTURE_FIXED", "info",
                "结构自由度未释放：wt% 是结构固定下的结果",
                "若结构可信（文献 CIF、占位已知），这个 wt% 可用；"
                "否则误差会整块进到含量里",
                {}))

    # ── 10. 微吸收修正的适用性（v5.2）──────────────────────────
    # τ 由 μ 与颗粒半径 R 确定、**不进拟合向量**，所以它的对错不会被 Rwp 反映
    # 出来 —— 只能在这里判：撞表端点（|(μ−μ̄)·R| > 0.5）就必须告警，因为表外
    # 的值是截断出来的，继续报 wt% 会把"颗粒太粗、Rietveld 定量已失效"写成正常数。
    taus = getattr(quant, "tau", ()) if quant is not None else ()
    if taus:
        clamped = bool(getattr(quant, "mu_clamped", False))
        if clamped:
            n_clamped = sum(1 for t in taus
                            if t <= BRINDLEY_TAU[0] + 1e-6
                            or t >= BRINDLEY_TAU[-1] - 1e-6)
            out.append(Finding(
                "MICROABSORPTION_CLAMPED", "warn",
                f"微吸收颗粒半径超出 Brindley 表适用范围"
                f"（μ̄={float(getattr(quant, 'mu_bar', 0.0)):.0f} cm⁻¹，"
                f"{n_clamped}/{len(taus)} 相 τ 撞表端点）——wt% 只能定性参考",
                "把颗粒半径降到 |(μ−μ̄)·R| ≤ 0.5（或确认实际粒度：SEM / 激光"
                "粒度 / 沉降法）；表外外推比不修正更糟",
                {"mu_bar": float(getattr(quant, "mu_bar", 0.0)),
                 "n_clamped": float(n_clamped)}))
        else:
            out.append(Finding(
                "MICROABSORPTION_APPLIED", "info",
                "已施加 Brindley 微吸收修正："
                f"μ̄={float(getattr(quant, 'mu_bar', 0.0)):.0f} cm⁻¹，"
                f"τ={min(taus):.2f}~{max(taus):.2f}",
                "wt% 已按 W ∝ S/τ 搬运；Rwp 不受影响（τ 只改份额、被标度吸收），"
                "所以 Rwp 变差说明半径给错了",
                {"mu_bar": float(getattr(quant, "mu_bar", 0.0)),
                 "tau_min": float(min(taus)), "tau_max": float(max(taus))}))

    # ── 11. 两相份额是否根本不可分辨（v5.2, 5-3 定量重排的答案）──────
    # Rwp 与各自 σ 都看不出来：两相标度高度**负**相关时，份额在它们之间互换
    # （一个涨另一个跌）而总谱几乎不变。此时"wt% 精确到小数点后两位"是
    # **表面精度**，物理上无意义。
    # 只判负相关（P0-E）：正相关的两相不是"此消彼长"，份额各自可辨，
    # |ρ| 大不构成不可分辨证据 —— 5-3 组最大 |ρ|=0.705 定量照样达标，
    # 7-1 组 ρ=−0.91 才是真病态（评估报告 §9）。
    # 阈值 ρ ≤ −0.80 ≡ σ差/σ和 = √((1−ρ)/(1+ρ)) ≥ 3.0（同一判据的两种写法）。
    if scale_corr is not None and quant is not None and len(quant.labels) > 1:
        corr = np.asarray(scale_corr, dtype=float)
        n_lab = len(quant.labels)
        if corr.shape == (n_lab, n_lab) and np.all(np.isfinite(corr)):
            fracs = np.asarray(quant.fractions, dtype=float)
            worst = None
            for i in range(n_lab):
                for j in range(i + 1, n_lab):
                    if (fracs[i] < min_phase_fraction
                            or fracs[j] < min_phase_fraction):
                        continue
                    rho = float(corr[i, j])
                    if worst is None or rho < worst[0]:
                        worst = (rho, i, j)
            if worst is not None and worst[0] <= -0.80:
                rho, i, j = worst
                sigma_ratio = float(np.sqrt((1.0 - rho) / (1.0 + rho)))
                out.append(Finding(
                    "SCALE_CORRELATED", "warn",
                    f"{quant.labels[i]} 与 {quant.labels[j]} 的相标度相关系数 "
                    f"ρ={rho:.2f}（≤−0.80）—— 两相份额可在彼此之间互换（此消"
                    f"彼长，σ差/σ和={sigma_ratio:.1f}）而总谱几乎不变，这两个 "
                    f"wt% 只能当一个区间读，不是两个独立数",
                    "要真正分开：延长扫描/换靶提高分辨率、加一条只属于其中一相"
                    "的孤立强线、或先修好该相的择优取向与占位（模型越准，相关"
                    "越低）；在此之前不要用这两个 wt% 比较版本优劣",
                    {"rho": rho,
                     "sigma_ratio": sigma_ratio,
                     "phase_a": str(quant.labels[i]),
                     "phase_b": str(quant.labels[j])}))

    # ── 12. 份额有没有谱线支撑（P2-10，v5.2）────────────────────
    # 份额、Rwp、各相 σ 三者都看不出这件事：大胞相用独立峰宽把失配摊平后，
    # Rwp 反而更低。只有"该相最强的那几条唯一线在实测里到底有没有峰"能证伪它。
    if phase_peaks:
        out.extend(_phase_support(x, y, phase_peaks, quant, calc_centers,
                                  min_fraction=min_phase_fraction))
        out.extend(_near_degenerate(x, y, phase_peaks, quant, calc_centers,
                                    wt_rwp_probe=wt_rwp_probe,
                                    min_fraction=min_phase_fraction))

    out.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 9), f.code))
    return out

@dataclass
class FitReport:
    """一次精修的人读 + 机读报告（D3 + D4 的落点）。"""

    metrics: Dict[str, float]
    findings: List[Finding] = field(default_factory=list)
    residual: Optional[ResidualStats] = None
    diagnostics: Optional[Diagnostics] = None
    quant: Optional[QuantResult] = None
    goals: Tuple[GoalResult, ...] = ()
    tier: str = ""
    tier_note: str = ""
    title: str = "全谱拟合报告"

    # ── 查询 ────────────────────────────────────────────────────
    def by_severity(self, severity: str) -> List[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def errors(self) -> List[Finding]:
        return self.by_severity("error")

    @property
    def warnings(self) -> List[Finding]:
        return self.by_severity("warn")

    @property
    def healthy(self) -> bool:
        """无错误级问题（警告仍可能有 —— 那是「可以更好」，不是「不能用」）。"""
        return not self.errors

    def codes(self) -> List[str]:
        return [f.code for f in self.findings]

    # ── 渲染 ────────────────────────────────────────────────────
    def text(self, *, max_findings: int = 12) -> str:
        m = self.metrics or {}
        lines = [self.title + (f"｜{self.tier_note}" if self.tier_note else "")]
        lines.append("─" * 58)
        lines.append(
            f"吻合   Rwp {m.get('Rwp', float('nan')):.2f}%   "
            f"Rp {m.get('Rp', float('nan')):.2f}%   "
            f"Rexp {m.get('Rexp', float('nan')):.2f}%   "
            f"GOF {m.get('GOF', float('nan')):.3f}   "
            f"χ² {m.get('chi2', float('nan')):.3f}")
        if self.residual is not None:
            rs = self.residual
            seg = " / ".join(f"{v:.2f}" if math.isfinite(v) else "—"
                             for v in rs.segment_rwp)
            lines.append(f"残差   DW {rs.durbin_watson:.2f}   "
                         f"分段 Rwp {seg} (%)   最大残差 "
                         f"{rs.max_abs_resid:.4g} @ {rs.max_abs_resid_at:.2f}°")
        if self.diagnostics is not None and self.diagnostics.names:
            d = self.diagnostics
            lines.append(f"参数   {len(d.names)} 个   秩 {d.rank}   "
                         f"SVD0 {d.svd0_ratio:.1e}   "
                         f"高相关 {len(d.high_corr)} 对   "
                         f"贴边界 {len(d.at_bounds)}")
        if self.quant is not None and self.quant.labels:
            q = "   ".join(f"{lab} {100 * f:.2f} wt%"
                           for lab, f in zip(self.quant.labels,
                                             self.quant.fractions))
            lines.append(f"定量   {q}")
        for g in self.goals:
            lines.append(f"GOAL   {g.text()}")
        if self.findings:
            lines.append("问题清单")
            for f in self.findings[:max_findings]:
                lines.append("  " + f.text())
            rest = len(self.findings) - max_findings
            if rest > 0:
                lines.append(f"  …另有 {rest} 条")
        else:
            lines.append("问题清单   未发现系统性问题")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "title": self.title, "tier": self.tier, "tier_note": self.tier_note,
            "metrics": dict(self.metrics or {}),
            "residual": self.residual.as_dict() if self.residual else None,
            "findings": [f.as_dict() for f in self.findings],
            "goals": [g.as_dict() for g in self.goals],
            "quant": self.quant.as_dict() if self.quant else {},
            "healthy": self.healthy,
        }


def _scale_correlations(problem, summary):
    """相标度相关矩阵；拿不到（无雅可比 / 维度不符）→ ``None``（不判）。

    与 ``goal._scale_sigmas`` 同源（投影协方差），只是取的是非对角块。
    任何一步失败都安静返回 ``None``：这是"加分项诊断"，不能因为矩阵奇异
    就把整份报告打挂。
    """
    jac = getattr(getattr(summary, "result", None), "jac", None)
    if jac is None or len(getattr(problem, "phases", ())) < 2:
        return None
    try:
        from .linear import scale_correlations

        basis, bgb = problem.design()
        red = float(getattr(getattr(summary, "result", None), "reduced_chi2", 1.0)
                    or 1.0)
        return scale_correlations(jac, basis, problem.weights,
                                  bg_basis=bgb, reduced_chi2=red)
    except Exception:  # noqa: BLE001 - 诊断失败不能影响报告
        return None


def _wt_rwp_probe(
    problem,
    quant: Optional[QuantResult],
) -> Dict[str, Tuple[float, float, float]]:
    """P0-E′ 的定量探针：把一相 wt% 推 10 pp，看 Rwp 要付多少代价。

    做法（线性层是闭式解，代价只有两次小最小二乘/相）：
    固定该相标度到 ``k·s0``（由 Hill–Howard 归一化反解出恰好 ±10 pp 的 k），
    其余相标度 + 背景重解，算约束后的 Rwp。比值
    ``Δwt(pp) / ΔRwp(pp)`` 越大，说明这条 wt% 与拟合质量越"脱钩"。

    返回 ``{label: (ratio, delta_wt_pp, delta_rwp_pp)}``；失败或单相返回 ``{}``。
    """
    if quant is None or len(getattr(quant, "labels", ())) < 2:
        return {}
    try:
        from .linear import design_stack, solve_linear

        basis, bgb = problem.design()
        A = design_stack(basis, bgb)
        y = np.asarray(problem.y_obs, dtype=float).reshape(-1)
        w = problem.weights
        base = solve_linear(basis, y, weights=w, bg_basis=bgb)
        rwp0 = float(pattern_metrics(y, base.y_calc, w)["Rwp"])
        labels = [str(x) for x in quant.labels]
        f0 = np.asarray(quant.fractions, dtype=float).reshape(-1)
        s0 = np.asarray(base.scales, dtype=float).reshape(-1)
    except Exception:  # noqa: BLE001 - 加分项诊断，失败静默
        return {}
    n_ph = int(basis.shape[1])
    n_tot = int(A.shape[1])
    if min(len(labels), f0.size, s0.size, n_ph) < 2:
        return {}
    target = NEAR_DEGENERATE_TARGET_PP / 100.0
    probe: Dict[str, Tuple[float, float, float]] = {}
    for i in range(min(len(labels), n_ph)):
        fi = float(f0[i])
        if fi < 0.01:
            continue
        best: Optional[Tuple[float, float, float]] = None
        for ft in (min(fi + target, 0.98), max(fi - target, 0.002)):
            if abs(ft - fi) < 1e-4:
                continue
            # 只改一相标度时 Hill–Howard 份额的闭式关系
            k = ft * (1.0 - fi) / max(fi * (1.0 - ft), 1e-12)
            y_adj = y - basis[:, i] * (s0[i] * k)
            keep_ph = [j for j in range(n_ph) if j != i]
            lin = solve_linear(basis[:, keep_ph], y_adj, weights=w, bg_basis=bgb)
            coef = np.concatenate([lin.scales, lin.bg_coefs])
            idx = keep_ph + list(range(n_ph, n_tot))
            # 固定相那一条**必须**加回计算谱：只解其余相得到的 y 里没有它，
            # 若直接拿来算 Rwp，等于把该相从模型里删掉 —— ΔRwp 被系统性放大，
            # 比值永远到不了 50，P0-E′ 会恒定漏报。
            y_fixed = A[:, idx] @ coef + basis[:, i] * (s0[i] * k)
            rwp2 = float(pattern_metrics(y, y_fixed, w)["Rwp"])
            drwp = float(rwp2 - rwp0)
            if drwp < -1e-6:
                continue
            dwt = float(100.0 * (ft - fi))
            ratio = abs(dwt) / max(drwp, 1e-9)
            cand = (ratio, dwt, drwp)
            if best is None or cand[0] > best[0]:
                best = cand
        if best is not None:
            probe[labels[i]] = best
            try:
                import os
                if os.environ.get("POLYXRD_DEBUG_P0E"):
                    print(f"[P0E] {labels[i]} f={fi:.3f} "
                          f"ratio={best[0]:.1f} dwt={best[1]:.2f} "
                          f"drwp={best[2]:.3f}", flush=True)
            except Exception:  # noqa: BLE001
                pass
    return probe


def build_report(
    problem,
    summary=None,
    *,
    goals: Sequence[str] = ("size", "strain", "fraction"),
    kalph2_modeled: Optional[bool] = None,
    title: str = "全谱拟合报告",
) -> FitReport:
    """从 ``PatternProblem``（+ 可选 ``FitSummary``）直接产出报告。

    这是 UI / 脚本的唯一入口：所有「该不该报警」的判断都在这里定，界面只负责
    渲染 ``Finding`` 列表，不再各自写一套阈值。
    """
    y_calc = None
    metrics: Dict[str, float] = {}
    diag = None
    quant = None
    if summary is not None:
        y_calc = getattr(summary, "y_calc", None)
        metrics = dict(getattr(summary, "metrics", {}) or {})
        diag = getattr(summary, "diagnostics", None)
        quant = getattr(summary, "quant", None)
    if y_calc is None:
        y_calc = problem.calc_pattern()
    if not metrics:
        metrics = problem.metrics()
    if quant is None:
        quant = problem.quantitative()

    params = problem.params
    stage = refined_stage(summary)
    free_names = [params.names()[i] for i in params.free_indices(stage)]
    po_freed = any(n.endswith(".po.r") for n in free_names)
    sample_freed = any(n.endswith(".sizec") or n.endswith(".strain")
                       for n in free_names)
    atoms_freed = any(".atom" in n for n in free_names)
    if kalph2_modeled is None:
        kalph2_modeled = getattr(problem, "kalph2", None) is not None

    centers: List[np.ndarray] = []
    phase_peaks: List[Tuple[str, np.ndarray, np.ndarray]] = []
    tmin = float(problem.two_theta[0]) if problem.two_theta.size else 0.0
    tmax = float(problem.two_theta[-1]) if problem.two_theta.size else 0.0
    for ph in problem.phases:
        try:
            ph.ensure_table((tmin, tmax), (problem.wavelength,))
            centers.append(np.asarray(ph.table.two_theta, dtype=float))
            phase_peaks.append((str(ph.label),
                                np.asarray(ph.table.two_theta, dtype=float),
                                np.asarray(ph.table.intensity, dtype=float)))
        except Exception:  # noqa: BLE001 - 反射表不可用就不做未识别相判断
            pass
    calc_centers = np.concatenate(centers) if centers else None

    findings = audit(
        problem.two_theta, problem.y_obs, y_calc, problem.weights,
        metrics=metrics, diagnostics=diag, quant=quant,
        calc_centers=calc_centers,
        phase_peaks=phase_peaks,
        kalph2_modeled=bool(kalph2_modeled),
        po_freed=po_freed, sample_freed=sample_freed, atoms_freed=atoms_freed,
        scale_corr=_scale_correlations(problem, summary),
        wt_rwp_probe=_wt_rwp_probe(problem, quant))

    return FitReport(
        metrics=metrics, findings=findings,
        residual=residual_stats(problem.two_theta, problem.y_obs, y_calc,
                                problem.weights),
        diagnostics=diag, quant=quant,
        goals=evaluate_goals(problem, summary, goals=goals, stage=stage),
        tier=classify_tier(problem, stage=stage).value,
        tier_note=tier_note(problem, stage=stage),
        title=title,
    )
