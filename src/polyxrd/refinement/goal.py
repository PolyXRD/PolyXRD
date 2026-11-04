"""D4 产品分层 + ``GOAL`` 物理量目标 —— 把"结果是啥、能不能信"写成机器可读。

分层的现实动机（见方案 §3.3）
---------------------------
同一个软件，三种输入，定量可信度差一个数量级：

===================  ======================================  ===============
档                   入口                                    定量可信度
===================  ======================================  ===============
免结构全谱拟合        无结构 CIF（只有峰列表）                 RIR 半定量
Le Bail 级            有晶胞、有位点，但结构自由度全固定       结构固定下的 wt%
真 Rietveld           有结构 CIF + 释放坐标/占位/Biso         可信 wt%
===================  ======================================  ===============

**为什么必须显式分层而不是"都报 wt%"**：Hill–Howard 的 ``W∝S·Z·M·V`` 里
``S`` 是"单位结构因子谱的标度"。结构因子若与真实结构不符（缺原子、占位错、
B 因子取默认 0.5），``S`` 就会把这个误差摊进含量里 —— 出来的 wt% 数字
照样漂亮，但它测的是"我的模型"，不是"我的样品"。分层就是承认这一点。

``GOAL``（借 Profex 的思路）
---------------------------
用户真正想要的从来不是"Rwp 6.2%"，而是"晶粒 85 nm"、"应变 0.12%"、"LFP 占
92 wt%"。``evaluate_goals`` 把这些量连同**误差棒**一起给出，并标注它是否
可靠（撞边界 / 未释放 / 低于检出限时明说不可靠，而不是给个漂亮的假数字）。

误差从哪来
----------
尺寸/应变是**非线性**参数，``σ`` 来自 ``diagnose`` 的协方差（已写回
``Parameter.sigma``）。重量分数是**线性层**标度的函数，``σ(S)`` 必须走
``linear_sigmas``（投影协方差），再按 ``W_p = S_p·M_p/Σ S_q·M_q`` 传播 ——
直接拿 ``diagnose`` 的协方差当标度误差是错的（那里压根没有标度这一列）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .linear import linear_sigmas
from .profile import SIZE_COEF_MIN, size_from_coefficient
from .quantitative import QuantResult

__all__ = [
    "Tier",
    "TIER_LABELS",
    "TIER_QUANT_NOTE",
    "GoalResult",
    "classify_tier",
    "evaluate_goals",
    "fraction_sigmas",
    "refined_stage",
    "tier_note",
]


class Tier(str, Enum):
    """内置引擎当前能做到的档位。"""

    STRUCTURE_FREE = "structure_free"
    LE_BAIL = "le_bail"
    RIETVELD = "rietveld"


TIER_LABELS: Dict[Tier, str] = {
    Tier.STRUCTURE_FREE: "免结构全谱拟合",
    Tier.LE_BAIL: "Le Bail 级（结构固定）",
    Tier.RIETVELD: "真 Rietveld（结构自由度已释放）",
}

TIER_QUANT_NOTE: Dict[Tier, str] = {
    Tier.STRUCTURE_FREE: "RIR 半定量：无结构因子，wt% 仅供排序参考",
    Tier.LE_BAIL: "结构固定下的 wt%：结构对则可信，结构错则误差全进含量",
    Tier.RIETVELD: "可信 wt%：坐标/占位/Biso 参与精修",
}

#: 各档默认用哪套协议（``protocol.PROTOCOLS`` 的键）
#:
#: 「免结构」与「Le Bail 级」共用 ``default``：没有位点时 ``build_parameters``
#: 根本不会建结构自由度，两档执行的其实是同一条路径 —— 硬拆成两套协议只会
#: 让人以为它们有区别。
TIER_PROTOCOLS: Dict[Tier, str] = {
    Tier.STRUCTURE_FREE: "default",
    Tier.LE_BAIL: "default",
    Tier.RIETVELD: "structure",
}


def protocol_for_tier(tier: Tier) -> str:
    """档位 → 默认协议名。"""
    return TIER_PROTOCOLS.get(Tier(tier), "default")


def refined_stage(summary) -> Optional[int]:
    """``FitSummary`` 里**真正跑过**的最后一个阶段号；没有则 None。

    为什么要看这个而不是"参数是不是 free"：``build_parameters`` 会把结构
    自由度（stage 6）一并建册且默认 ``fixed=False``，但默认协议只跑到 stage 5。
    若按 ``free`` 判档，会把一次"结构没动过"的精修报成「真 Rietveld」——
    这恰恰是 D4 要杜绝的误报。
    """
    stages = getattr(summary, "stages", None) or ()
    for entry in reversed(list(stages)):
        if entry.get("status") != "skipped":
            try:
                return int(entry["stage"])
            except (KeyError, TypeError, ValueError):  # pragma: no cover
                continue
    return None


def _free_names(problem, stage: Optional[int]) -> List[str]:
    idx = problem.params.free_indices(stage)
    return [problem.params.names()[i] for i in idx]


def classify_tier(problem, *, stage: Optional[int] = None) -> Tier:
    """按「有位点吗 / 结构自由度真放开了吗」定档。

    :param stage: 实际精修到的阶段号（``refined_stage(summary)``）；``None``
        表示"还没跑"，此时按参数书的配置判断
    """
    has_sites = any(
        len(getattr(ph.structure, "sites", ()) or ()) > 0
        for ph in problem.phases)
    if not has_sites:
        return Tier.STRUCTURE_FREE
    atoms_freed = any(".atom" in n for n in _free_names(problem, stage))
    return Tier.RIETVELD if atoms_freed else Tier.LE_BAIL


def tier_note(problem, *, stage: Optional[int] = None) -> str:
    """给 UI / 报告用的一句话（档位 + 定量可信度）。"""
    t = classify_tier(problem, stage=stage)
    return f"{TIER_LABELS[t]}｜{TIER_QUANT_NOTE[t]}"


@dataclass(frozen=True)
class GoalResult:
    """一个 ``GOAL`` 物理量的结果（值 + 误差 + 是否可靠）。"""

    name: str
    label: str
    value: float
    sigma: float
    unit: str
    reliable: bool = True
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "value": self.value,
                "sigma": self.sigma, "unit": self.unit,
                "reliable": self.reliable, "note": self.note}

    def text(self) -> str:
        s = f"{self.label} = {self.value:.4g}"
        if self.sigma and math.isfinite(self.sigma):
            s += f" ± {self.sigma:.2g}"
        s += f" {self.unit}"
        if not self.reliable:
            s += f"  ⚠ {self.note or '不可靠'}"
        elif self.note:
            s += f"  （{self.note}）"
        return s


def fraction_sigmas(
    quant: QuantResult,
    scale_sigmas: Sequence[float],
) -> Tuple[float, ...]:
    """重量分数的标准不确定度（由标度不确定度传播）。

    对 ``W_p = S_p·M_p / Σ_q S_q·M_q``（``M = Z·M·V``，记 ``T = Σ_q S_q·M_q``）：

        ∂W_p/∂S_q = (δ_pq·M_p − W_p·M_q) / T

    所以 ``σ²(W_p) = Σ_q [(δ_pq·M_p − W_p·M_q)/T]²·σ²(S_q)``。

    **交叉项里是 ``M_q`` 不是 ``W_q``**：``∂W_p/∂S_q (q≠p) = −S_p M_p M_q/T²
    = −W_p·M_q/T``，而 ``W_q = S_q M_q/T`` 多带了一个 ``S_q``。写成 ``W_q`` 会让
    交叉项系统性偏小（实测 65/35 两相下 σ 低估约 25%）。用 ``quant.scales`` /
    ``quant.factor`` / ``quant.fractions`` 就能算，不需要重新解一次线性层。
    """
    n = len(quant.labels)
    if n == 0:
        return ()
    sig = np.asarray(list(scale_sigmas), dtype=float).reshape(-1)
    if sig.size != n:
        return tuple(float("nan") for _ in range(n))
    s = np.asarray(quant.scales, dtype=float)
    z = np.asarray(quant.factor, dtype=float)
    w = np.asarray(quant.fractions, dtype=float)
    total = float(np.sum(np.maximum(s, 0.0) * z)) or 1.0
    eye = np.eye(n)
    out: List[float] = []
    for p in range(n):
        coef = (eye[p] * z[p] - w[p] * z) / total
        var = float(np.sum((coef ** 2) * np.maximum(sig, 0.0) ** 2))
        out.append(math.sqrt(max(var, 0.0)))
    return tuple(out)


def evaluate_goals(
    problem,
    summary=None,
    *,
    goals: Sequence[str] = ("size", "strain", "fraction"),
    min_fraction: float = 0.01,
    stage: Optional[int] = None,
) -> Tuple[GoalResult, ...]:
    """按名字取物理量目标：``size``（nm）/ ``strain``（%）/ ``fraction``（wt%）。

    :param summary: 有则用它的 ``quant`` 与 ``result.jac`` 算误差；无则只给值
    :param stage: 实际精修到的阶段；给定时会区分「本协议没释放」与「解为 0」
    """
    out: List[GoalResult] = []
    params = problem.params
    quant: Optional[QuantResult] = getattr(summary, "quant", None)
    jac = getattr(getattr(summary, "result", None), "jac", None)
    if stage is None:
        stage = refined_stage(summary)

    def _release_note(prm) -> str:
        if stage is not None and prm.stage > stage:
            return f"本协议未释放（属第 {prm.stage} 阶段）"
        return ""

    def _make(name: str, prm, label: str, unit: str, scale: float,
              zero_note: str, *, value: Optional[float] = None,
              sigma: Optional[float] = None) -> GoalResult:
        note = _release_note(prm)
        reliable = True
        if note:
            reliable = False
        elif prm.value <= 0.0:
            reliable, note = False, zero_note
        elif prm.at_bound(1e-6):
            reliable, note = False, "撞边界：数据不足以定该量"
        elif prm.sigma <= 0:
            note = "无误差棒（该参数未参与最后一段）"
        v = scale * float(prm.value) if value is None else float(value)
        s = scale * float(prm.sigma) if sigma is None else float(sigma)
        return GoalResult(name, label, v, s, unit, reliable, note)

    if "size" in goals or "strain" in goals:
        _wl = float(getattr(problem, "wavelength", 1.54056) or 1.54056)
        _k = float(getattr(problem.profile, "k_size", 0.9) or 0.9)
        for ph in problem.phases:
            p = ph.prefix
            if "size" in goals and f"{p}.sizec" in params:
                prm = params[f"{p}.sizec"]
                coef = float(prm.value)
                # 参数册里存的是洛伦兹系数（度·cosθ），目标是 nm —— 换算非线性，
                # 误差棒按 dD/dc = D/c 传播（§十七）
                if coef > SIZE_COEF_MIN:
                    d_nm = size_from_coefficient(coef, _wl, _k)
                    sd = d_nm * float(prm.sigma) / coef if prm.sigma > 0 else 0.0
                    out.append(_make("size", prm, f"{ph.label} 晶粒尺寸", "nm",
                                     1.0, "解为 0（无展宽）", value=d_nm, sigma=sd))
                else:
                    # 系数≈0：要么本协议没到 stage 5（_make 会给出"未释放"），
                    # 要么确实无尺寸展宽
                    out.append(_make("size", prm, f"{ph.label} 晶粒尺寸", "nm",
                                     1.0, "无尺寸展宽（超出可分辨上限）",
                                     value=0.0, sigma=0.0))
            if "strain" in goals and f"{p}.strain" in params:
                out.append(_make("strain", params[f"{p}.strain"],
                                 f"{ph.label} 微应变", "%", 100.0,
                                 "解为 0（无微应变）"))

    if "fraction" in goals:
        if quant is None:
            quant = problem.quantitative()
        sig = _scale_sigmas(problem, summary, jac)
        fsig = fraction_sigmas(quant, sig) if sig is not None else \
            tuple(float("nan") for _ in quant.labels)
        for lab, frac, sd in zip(quant.labels, quant.fractions, fsig):
            reliable = bool(frac >= min_fraction)
            note = "" if reliable else f"低于 {100 * min_fraction:.0f}% 可靠定量下限"
            if sig is None:
                note = (note + "；" if note else "") + "标度误差未传播"
            out.append(GoalResult("fraction", f"{lab} 重量分数",
                                  100.0 * float(frac), 100.0 * float(sd), "wt%",
                                  reliable, note))
    return tuple(out)


def _scale_sigmas(problem, summary, jac) -> Optional[np.ndarray]:
    """标度的标准不确定度；拿不到（无雅可比 / 维度不符）→ None。"""
    if jac is None:
        return None
    try:
        basis, bgb = problem.design()
    except Exception:  # noqa: BLE001 - 设计矩阵不可用时安静退化为"无误差棒"
        return None
    red = float(getattr(getattr(summary, "result", None), "reduced_chi2", 1.0)
                or 1.0)
    try:
        s, _b = linear_sigmas(jac, basis, problem.weights, bg_basis=bgb,
                              reduced_chi2=red)
    except (ValueError, np.linalg.LinAlgError):
        return None
    if s.size != len(problem.phases) or not np.all(np.isfinite(s)):
        return None
    return s
