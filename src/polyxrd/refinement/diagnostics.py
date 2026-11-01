"""相关性矩阵与奇异诊断 —— 诚实报告"这组参数到底能不能定"。

GSAS-II 的 ``ReportProblems`` 会打印四类东西，本模块对齐：

===========  ============================================================
``SVD0``     ``JᵀJ`` 的最小奇异值与最大之比低于阈值 → **秩亏**，有参数
             组合完全不可辨识（通常是同一 Wyckoff 轨道逐原子放开、或
             占位与 B 因子强耦合）
``SVDsing``  最小奇异值本身（越小越病态）
``psing``    秩亏方向上的**载荷参数**（该方向上系数显著的那些），直接告诉
             用户"是这几个参数在互相抵消"
``Hcorr``    相关系数超过阈值的参数对（``|ρ| > 0.9`` 基本等于共线）
===========  ============================================================

为什么值得做：Rietveld 最容易骗人的失败不是发散，而是**收敛到一个 Rwp 很低
但参数毫无意义的解**（占位全跑 0、B 因子跑到 50、择优 r 撞边界）。数值上
一切"成功"，物理上全是废话。这些诊断就是把这种解揭出来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "Diagnostics",
    "diagnose",
    "correlation_matrix",
]

#: 相关系数绝对值的警戒线（GSAS-II 用 0.9 报"高相关"）
HIGHCORR = 0.90
#: 秩亏判据：最小/最大奇异值
SVD0_TOL = 1e-8
#: 判定某参数"参与奇异方向"的载荷阈值（相对最大载荷）
PSING_TOL = 0.15


@dataclass
class Diagnostics:
    """一组参数的病态诊断结果。"""

    names: List[str] = field(default_factory=list)
    singular_values: np.ndarray = field(default_factory=lambda: np.zeros(0))
    rank: int = 0
    rank_deficient: bool = False
    svd0_ratio: float = 0.0
    svd_sing: float = 0.0
    psing: List[str] = field(default_factory=list)
    high_corr: List[Tuple[str, str, float]] = field(default_factory=list)
    at_bounds: List[str] = field(default_factory=list)
    sigmas: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.warnings

    def report(self, max_corr: int = 10) -> str:
        """给人看的多行报告（也进日志）。"""
        lines = [
            f"参数数 {len(self.names)}  秩 {self.rank}  "
            f"SVD0={self.svd0_ratio:.2e}  SVDsing={self.svd_sing:.3e}",
        ]
        if self.rank_deficient:
            lines.append(f"  ⚠ 秩亏：不可辨识方向涉及 {', '.join(self.psing) or '(未能定位)'}")
        for a, b, r in self.high_corr[:max_corr]:
            lines.append(f"  ⚠ 高相关 ρ={r:+.3f}: {a} ↔ {b}")
        if self.at_bounds:
            lines.append(f"  ⚠ 贴边界: {', '.join(self.at_bounds)}")
        if self.healthy:
            lines.append("  未发现病态")
        return "\n".join(lines)


def correlation_matrix(cov: np.ndarray) -> np.ndarray:
    """协方差 → 相关系数矩阵（对角归一；零方差置 0）。"""
    cov = np.asarray(cov, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError("协方差必须是方阵")
    d = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    denom = np.outer(d, d)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(denom > 0, cov / denom, 0.0)
    # 病态时 inv(JᵀJ) 会给 |ρ| 略大于 1（实测 -1.001）；夹回 [-1,1] 再报，
    # 否则 UI 上出现 "相关 101%" 这种一眼假的数字
    corr = np.clip(corr, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    return corr


def diagnose(
    jac: Optional[np.ndarray],
    names: Sequence[str],
    *,
    sigmas: Optional[Sequence[float]] = None,
    at_bounds: Optional[Sequence[str]] = None,
    reduced_chi2: float = 1.0,
    svd0_tol: float = SVD0_TOL,
    highcorr: float = HIGHCORR,
) -> Diagnostics:
    """由（加权残差的）雅可比给出病态诊断。

    :param jac: ``(M, P)`` 雅可比；``None`` → 只做边界检查
    :param names: 列名（长度 = P）
    :param sigmas: 各参数标准不确定度（可省，省则从协方差推）
    :param at_bounds: 贴边界的参数名（由 ``ParameterSet.at_bound`` 提供）
    :param reduced_chi2: ``σ² = cost·2/(M−P)``，用于把协方差缩放到物理量纲
    """
    names = list(names)
    diag = Diagnostics(names=names, at_bounds=list(at_bounds or ()))

    if jac is None or np.size(jac) == 0:
        if diag.at_bounds:
            diag.warnings.append("有参数贴在边界上（无法做奇异诊断）")
        return diag

    J = np.asarray(jac, dtype=float)
    if J.shape[1] != len(names):
        names = [f"p{i}" for i in range(J.shape[1])]
        diag.names = names

    P = J.shape[1]
    # 奇异值分解：右奇异向量给出"参数方向"
    try:
        _u, sv, vt = np.linalg.svd(J, full_matrices=False)
    except np.linalg.LinAlgError:  # pragma: no cover
        diag.warnings.append("雅可比 SVD 失败")
        return diag

    diag.singular_values = sv
    smax = float(sv[0]) if sv.size else 0.0
    smin = float(sv[-1]) if sv.size else 0.0
    diag.svd_sing = smin
    diag.svd0_ratio = (smin / smax) if smax > 0 else 0.0
    # 秩与秩亏用**同一个**阈值，否则会出现"秩满但 SVD0 极小"的自相矛盾
    # （旧版秩用 1e-12、判据用 1e-8，SVD0=4e-11 时既不报秩亏又警告，很误导）
    diag.rank = int(np.sum(sv > smax * svd0_tol)) if smax > 0 else 0
    diag.rank_deficient = diag.rank < P

    if diag.rank_deficient:
        # 最小奇异方向 = 最后一个右奇异向量
        v = vt[-1]
        thr = PSING_TOL * float(np.max(np.abs(v))) if v.size else 0.0
        diag.psing = [names[i] for i in range(min(len(names), v.size))
                      if abs(v[i]) >= thr]
        diag.warnings.append(
            f"秩亏（SVD0={diag.svd0_ratio:.1e}）：不可辨识方向 "
            f"{' ↔ '.join(diag.psing) or '未定位'}")

    # 协方差与相关矩阵
    if P and J.shape[0] > P:
        try:
            cov = np.linalg.inv(J.T @ J) * max(reduced_chi2, 0.0)
            sd = np.sqrt(np.clip(np.diag(cov), 0.0, None))
            diag.sigmas = {names[i]: float(sd[i]) for i in range(P)}
            corr = correlation_matrix(cov)
            for i in range(P):
                for j in range(i + 1, P):
                    r = float(corr[i, j])
                    if abs(r) >= highcorr and np.isfinite(r):
                        diag.high_corr.append((names[i], names[j], r))
            diag.high_corr.sort(key=lambda t: -abs(t[2]))
            if diag.high_corr:
                diag.warnings.append(
                    f"{len(diag.high_corr)} 对参数 |ρ|≥{highcorr}")
        except np.linalg.LinAlgError:
            diag.warnings.append("JᵀJ 不可逆（秩亏严重）")

    if sigmas is not None and len(sigmas) == P:
        diag.sigmas = {names[i]: float(sigmas[i]) for i in range(P)}

    if diag.at_bounds:
        diag.warnings.append(f"{len(diag.at_bounds)} 个参数贴边界")

    return diag
