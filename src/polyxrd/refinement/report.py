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
    "audit",
    "build_report",
    "residual_stats",
]

#: 严重度排序（越小越严重）
SEVERITY_RANK: Dict[str, int] = {"error": 0, "warn": 1, "info": 2}


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
) -> List[Finding]:
    """跑完整诊断规则，返回按严重度排序的 ``Finding`` 列表。

    :param calc_centers: 当前模型全部计算峰位（用于判断「残差峰有没有对应的
        反射」）；给 ``None`` 则跳过「疑似未识别相」这条规则 —— 没有对照就
        断言「多了个相」是不负责任的。
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
    # Rwp 与各自 σ 都看不出来：两相标度高度负相关时，份额在它们之间互换而
    # 总谱几乎不变。此时"wt% 精确到小数点后两位"是**表面精度**，物理上无意义。
    # 只看 |ρ| 与两相含量（<1% 的相本来就是检出限问题，另有规则管）。
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
                    rho = abs(float(corr[i, j]))
                    if worst is None or rho > worst[0]:
                        worst = (rho, i, j)
            if worst is not None and worst[0] >= 0.95:
                rho, i, j = worst
                out.append(Finding(
                    "SCALE_CORRELATED", "warn",
                    f"{quant.labels[i]} 与 {quant.labels[j]} 的相标度相关系数 "
                    f"|ρ|={rho:.2f}（>0.95）—— 两相份额可在彼此之间互换而总谱"
                    f"几乎不变，这两个 wt% 只能当一个区间读，不是两个独立数",
                    "要真正分开：延长扫描/换靶提高分辨率、加一条只属于其中一相"
                    "的孤立强线、或先修好该相的择优取向与占位（模型越准，相关"
                    "越低）；在此之前不要用这两个 wt% 比较版本优劣",
                    {"rho": rho,
                     "phase_a": str(quant.labels[i]),
                     "phase_b": str(quant.labels[j])}))

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
    tmin = float(problem.two_theta[0]) if problem.two_theta.size else 0.0
    tmax = float(problem.two_theta[-1]) if problem.two_theta.size else 0.0
    for ph in problem.phases:
        try:
            ph.ensure_table((tmin, tmax), (problem.wavelength,))
            centers.append(np.asarray(ph.table.two_theta, dtype=float))
        except Exception:  # noqa: BLE001 - 反射表不可用就不做未识别相判断
            pass
    calc_centers = np.concatenate(centers) if centers else None

    findings = audit(
        problem.two_theta, problem.y_obs, y_calc, problem.weights,
        metrics=metrics, diagnostics=diag, quant=quant,
        calc_centers=calc_centers,
        kalph2_modeled=bool(kalph2_modeled),
        po_freed=po_freed, sample_freed=sample_freed, atoms_freed=atoms_freed,
        scale_corr=_scale_correlations(problem, summary))

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
