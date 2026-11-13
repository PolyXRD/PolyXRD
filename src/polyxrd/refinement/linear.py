"""变量投影的线性层：每轮闭式解「各相标度 + 背景系数」。

为什么叫变量投影（separable NLS）
--------------------------------
``y_calc = Σ_p s_p·B_p(x) + Σ_k c_k·G_k + ...`` —— 只有 ``s``（标度）与 ``c``
（背景系数）是**线性**出现的，非线性参数 ``x``（峰位/峰宽/占位）只决定基函数
``B_p(x)`` 的形状。于是可以把它拆成两层：

    min_x ‖ y − A(x)·β ‖,  β = [s, c]
    ⇒ 内层对 β 有闭式解 β*(x) = argmin‖y − A(x)β‖（加权最小二乘）
    ⇒ 外层只对 x 做非线性优化，残差 r(x) = y − A(x)β*(x)

好处（这是 Rietveld 里最值得抄的一招）：

* 非线性维数从 "6+5+1+4×n_atom+背景阶数" 降到 "6+5+1+4×n_atom"，背景阶数
  再高也不增加非线性维数；
* 标度与背景的强相关（同一个鞍点）被闭式解吸收，LM 的条件数改善一到两个量级；
* 每次迭代只需一次 ``lstsq``（~μs 级），比放进 Jacobian 便宜得多。

**注意**：投影之后残差不再是"普通最小二乘"，协方差要用投影公式
（见 :func:`linear_covariance`），否则标度的不确定度会偏大。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "LinearSolve",
    "solve_linear",
    "linear_covariance",
    "full_covariance",
    "linear_sigmas",
    "design_stack",
]

#: 非线性/线性层之间传递的"线性系数个数"下限，防止全 0 设计矩阵
_MIN_RCOND = 1e-12
#: ``full_covariance`` 里 M 的奇异值截断（相对最大奇异值）。
#: 比 lstsq 的 1e-12 略松：这里判的是"这个方向到底有没有被数据约束"，
#: 留 1e-10 以免把纯舍入噪声当成一个可估方向、给出 1e20 量级的假方差。
_COV_RCOND = 1e-10


@dataclass
class LinearSolve:
    """线性层的解与诊断。"""

    scales: np.ndarray
    bg_coefs: np.ndarray
    y_calc: np.ndarray
    resid: np.ndarray
    rank: int
    cond: float
    clipped: Tuple[int, ...] = ()

    @property
    def n_linear(self) -> int:
        return int(self.scales.size + self.bg_coefs.size)


def design_stack(
    basis: np.ndarray,
    bg_basis: Optional[np.ndarray] = None,
) -> np.ndarray:
    """把 ``[相基 | 背景基]`` 横向拼成 ``(N, n_phase + n_bg)``。"""
    b = np.asarray(basis, dtype=float)
    if b.ndim == 1:
        b = b[:, None]
    if bg_basis is None or np.asarray(bg_basis).size == 0:
        return b
    g = np.asarray(bg_basis, dtype=float)
    if g.ndim == 1:
        g = g[:, None]
    if g.shape[0] != b.shape[0]:
        raise ValueError(f"背景基行数 {g.shape[0]} 与相基行数 {b.shape[0]} 不符")
    return np.hstack([b, g])


def _nnls_active_set(
    A: np.ndarray, rhs: np.ndarray, w: np.ndarray,
    active: np.ndarray, deactivatable: np.ndarray, max_iter: int = 64,
) -> Tuple[np.ndarray, Tuple[int, ...]]:
    """极简非负最小二乘（active-set）。

    规模很小（相数 + 背景阶数，通常 < 30 列），不值得上 scipy 的完整 NNLS。
    做法：解 → 把所有跑负的**可约束**列锁到 0 → 用剩余列重解 → 重复。

    :param active: 初始参与的列（就地修改）
    :param deactivatable: 允许被锁到 0 的列（相标度；背景列一般不锁）
    """
    n = A.shape[1]
    coef = np.zeros(n, dtype=float)
    active = np.asarray(active, dtype=bool).copy()
    clipped: list[int] = []

    for _ in range(max_iter):
        idx = np.flatnonzero(active)
        if idx.size == 0:
            break
        Aw = A[:, idx] * w[:, None]
        c_sub, *_ = np.linalg.lstsq(Aw, rhs, rcond=_MIN_RCOND)
        coef[:] = 0.0
        coef[idx] = c_sub
        bad = idx[(c_sub < -1e-12) & deactivatable[idx]]
        if bad.size == 0:
            # 可约束列取 max(·,0) 只是数值清理；它们此处已经 ≥0
            coef[idx] = np.where(deactivatable[idx], np.maximum(c_sub, 0.0), c_sub)
            break
        active[bad] = False
        clipped.extend(int(i) for i in bad)
    return coef, tuple(clipped)


def solve_linear(
    basis: np.ndarray,
    y_obs: np.ndarray,
    *,
    weights: Optional[np.ndarray] = None,
    bg_basis: Optional[np.ndarray] = None,
    nonneg_scales: bool = True,
    nonneg_bg: bool = False,
    diagnose: bool = True,
) -> LinearSolve:
    """加权最小二乘解 ``β = [scales, bg_coefs]``。

    :param basis: ``(N, n_phase)`` 各相单位标度谱（``design_matrix`` 的列）
    :param y_obs: ``(N,)`` 观测谱
    :param weights: ``(N,)`` 权重（通常 ``1/y``）；None → 等权
    :param bg_basis: ``(N, n_bg)`` 背景基；None → 无背景
    :param nonneg_scales: 相标度为负无物理意义（会被背景吃掉）→ 默认压到 0
    :param nonneg_bg: 背景一般也非负，但 Chebyshev 系数可以负（正交基），
        故默认**不**约束 —— 用 tent 基时才建议打开

    返回的 ``resid`` 是**加权后**的残差 ``(y − y_calc)·√w``，可直接给 LM 当
    目标向量的前 n 项。
    """
    A = design_stack(basis, bg_basis)
    y = np.asarray(y_obs, dtype=float).reshape(-1)
    if A.shape[0] != y.size:
        raise ValueError(f"基行数 {A.shape[0]} 与观测点数 {y.size} 不符")

    if weights is None:
        w = np.ones_like(y)
    else:
        w = np.asarray(weights, dtype=float).reshape(-1)
        if w.size != y.size:
            raise ValueError(f"权重长度 {w.size} 与观测点数 {y.size} 不符")
    w_lin = np.sqrt(np.maximum(w, 0.0))          # lstsq 用的是 √w

    n_ph = int(np.asarray(basis).shape[1]) if np.ndim(basis) == 2 else 1
    n_col = A.shape[1]
    n_bg = n_col - n_ph

    clipped: Tuple[int, ...] = ()
    if nonneg_scales and n_ph:
        active = np.ones(n_col, dtype=bool)
        deactivatable = np.zeros(n_col, dtype=bool)
        deactivatable[:n_ph] = True
        if nonneg_bg and n_bg:
            deactivatable[n_ph:] = True
        coef, clipped = _nnls_active_set(A, y * w_lin, w_lin, active, deactivatable)
    else:
        coef, *_ = np.linalg.lstsq(A * w_lin[:, None], y * w_lin, rcond=_MIN_RCOND)

    y_calc = A @ coef
    resid = (y - y_calc) * w_lin

    # 条件数（诊断"背景阶数太高 / 相基几乎共线"）。
    # ``diagnose=False`` 给**优化器内循环**用：这里每次 residual 都要解一次
    # 线性层，而 rank/cond 在整个 v5 流程里**没有任何消费者**（诊断用的是
    # 雅可比 SVD，不是这里的线性层）。实测 S2：5564 次 residual → SVD 3.4 s，
    # 占全程 6%。只在直连调用（测试 / 报告）保留默认 True。
    if diagnose:
        try:
            sv = np.linalg.svd(A * w_lin[:, None], compute_uv=False)
            cond = float(sv[0] / sv[-1]) if sv.size and sv[-1] > 0 else float("inf")
            rank = int(np.sum(sv > sv[0] * 1e-12)) if sv.size else 0
        except np.linalg.LinAlgError:  # pragma: no cover - 极端数值问题
            cond, rank = float("inf"), 0
    else:
        cond, rank = float("inf"), -1

    return LinearSolve(
        scales=np.asarray(coef[:n_ph], dtype=float),
        bg_coefs=np.asarray(coef[n_ph:], dtype=float),
        y_calc=y_calc,
        resid=resid,
        rank=rank,
        cond=cond,
        clipped=clipped,
    )


def linear_covariance(
    basis: np.ndarray,
    weights: Optional[np.ndarray],
    *,
    bg_basis: Optional[np.ndarray] = None,
    reduced_chi2: float = 1.0,
) -> np.ndarray:
    """线性层系数的协方差 ``(AᵀWA)⁻¹·χ²_red``。

    只给线性层用。全参数（线性 + 非线性）的协方差要用投影后的雅可比，
    见 :func:`full_covariance` —— 直接拿这里的矩阵当"标度不确定度"在投影
    框架下是**错的**（会把标度与背景的自由度重复计入）。
    """
    A = design_stack(basis, bg_basis)
    w = np.ones(A.shape[0]) if weights is None else np.asarray(weights, float)
    w = np.maximum(w, 0.0)
    M = A.T @ (A * w[:, None])
    try:
        cov = np.linalg.pinv(M)
    except np.linalg.LinAlgError:  # pragma: no cover
        return np.full_like(M, np.nan)
    return cov * float(max(reduced_chi2, 0.0))


def full_covariance(
    jac: Optional[np.ndarray],
    basis: np.ndarray,
    weights: Optional[np.ndarray] = None,
    *,
    bg_basis: Optional[np.ndarray] = None,
    reduced_chi2: float = 1.0,
) -> np.ndarray:
    """变量投影框架下的**全参数**协方差 ``(JᵀJ)⁻¹·χ²_red``。

    为什么不能分开算：投影之后非线性残差 ``r(x)`` 已经"吃掉"了线性层的最优
    解，``∂r/∂x`` 里隐含 ``∂β*/∂x``。要拿到标度的真实不确定度，必须把
    ``[非线性雅可比 | 加权设计矩阵]`` 拼成一个整体再求逆 —— 这正是
    Golub–Pereyra 的 separable NLS 协方差结论。

    拼出的矩阵列数 = ``P_nonlin + n_phase + n_bg``（通常 10~40），求伪逆
    代价可忽略；**只**在收尾时算一次。

    :param jac: 加权残差对非线性参数的雅可比 ``(M, P_nonlin)``
    :param basis: 相基 ``(M, n_phase)``；``bg_basis`` 同

    **列序**：``[非线性 P_nonlin | 相标度 n_phase | 背景 n_bg]``。取"标度块"
    必须从第 ``P_nonlin`` 列起 —— 从第 0 列取得到的是**非线性参数**的块
    （两者数量级完全不同：实测五相试样 P_nonlin=108、n_phase=5，取错就
    等于拿前 5 个峰形参数的相关性冒充相分数相关性）。偏移量统一由
    :func:`linear_block_slices` 给出。
    """
    A = design_stack(basis, bg_basis)
    m = A.shape[0]
    w = np.ones(m) if weights is None else np.asarray(weights, float).reshape(-1)
    if w.size != m:
        raise ValueError(f"权重长度 {w.size} 与基行数 {m} 不符")
    Aw = A * np.sqrt(np.maximum(w, 0.0))[:, None]

    if jac is None or np.size(jac) == 0:
        M = Aw
    else:
        J = np.asarray(jac, float)
        if J.ndim != 2 or J.shape[0] != m:
            raise ValueError(f"雅可比形状 {J.shape} 与基行数 {m} 不符")
        M = np.hstack([J, Aw])
    # 用 M 的 SVD 求 (MᵀM)⁻¹，**不要**显式拼 MᵀM：这一步把条件数平方
    # （κ→κ²），五相以上的试样里 κ(M) 已到 1e3~1e4，平方后 1e8 的相对舍入
    # 足以让"相标度"子块失去半正定性 —— 实测 ShiJK-7 直接从 pinv(MᵀM) 的
    # 块里算出特征值 −1.385（相关矩阵不可能为负），进而 ρ=±1.000。
    # V·diag(s⁻²)·Vᵀ 与数学上的 (MᵀM)⁻¹ 等价，且按构造半正定。
    try:
        _u, s, vt = np.linalg.svd(M, full_matrices=False)
    except np.linalg.LinAlgError:  # pragma: no cover
        return np.full((M.shape[1], M.shape[1]), np.nan)
    keep = s > (s[0] * _COV_RCOND if s.size and s[0] > 0 else 0.0)
    if not np.any(keep):  # pragma: no cover - 全零矩阵
        return np.zeros((M.shape[1], M.shape[1]))
    v = vt[keep].T
    cov = (v / (s[keep] ** 2)) @ v.T
    return cov * float(max(reduced_chi2, 0.0))


def linear_block_slices(
    jac: Optional[np.ndarray],
    basis: np.ndarray,
    bg_basis: Optional[np.ndarray] = None,
) -> Tuple[slice, slice]:
    """``full_covariance`` 里「相标度块」「背景块」的切片，``(sl_scale, sl_bg)``。

    为什么要单独一个函数：``full_covariance`` 拼的是 ``[J | A]``，**列序以
    非线性参数打头**。历史上 ``linear_sigmas`` / ``scale_correlations`` 都写
    成 ``cov[:n_phase]``，即"假定线性参数排在最前"。``jac`` 为 ``None`` 时
    恰好成立（此时 ``M = A``），而**真实报告路径永远带 jac** —— 于是界面上的
    wt% 误差棒与 ``SCALE_CORRELATED`` 一直取的是前 n 个**峰形/占位参数**的
    方差，与相分数无关。实测 ShiJK-4（P_nonlin=108, n_phase=5）：错误口径
    σ=[0.004,0.017,0.026,0.032,0.008]、正确口径 σ=[0.192,0.322,0.232,0.088,
    1.035]；相关性由"p2/p3/p4 近奇异 ρ≈−0.94"变成"最大 |ρ|=0.18"。正确块
    与 Schur 补 ``(AᵀWA − AᵀWJ(JᵀWJ)⁺JᵀWA)⁻¹`` 逐元素一致（差 ~3e−6）。
    """
    n_ph = int(np.asarray(basis).shape[1]) if np.ndim(basis) == 2 else 1
    n_bg = 0 if bg_basis is None else int(np.asarray(bg_basis).shape[1])
    p = 0 if jac is None or np.size(jac) == 0 else int(np.asarray(jac).shape[1])
    return slice(p, p + n_ph), slice(p + n_ph, p + n_ph + n_bg)


def linear_sigmas(
    jac: Optional[np.ndarray],
    basis: np.ndarray,
    weights: Optional[np.ndarray] = None,
    *,
    bg_basis: Optional[np.ndarray] = None,
    reduced_chi2: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """线性层（标度 / 背景）的标准不确定度，``(σ_scale, σ_bg)``。

    从 :func:`full_covariance` 的对角块开方取（块位置由
    :func:`linear_block_slices` 给，**不能**假定线性参数排在最前）。这是
    "重量分数带误差棒"的唯一正确来源 —— 标度是线性层的，``diagnose`` 的雅可比
    里根本没有它们。
    """
    n_ph = int(np.asarray(basis).shape[1]) if np.ndim(basis) == 2 else 1
    cov = full_covariance(jac, basis, weights, bg_basis=bg_basis,
                          reduced_chi2=reduced_chi2)
    sl_s, sl_b = linear_block_slices(jac, basis, bg_basis)
    diag = np.diag(cov)
    s = np.sqrt(np.clip(diag[sl_s], 0.0, None))
    b = np.sqrt(np.clip(diag[sl_b], 0.0, None))
    if s.size != n_ph:  # pragma: no cover - 维度自检
        raise ValueError(f"相标度块大小 {s.size} 与 n_phase={n_ph} 不符")
    return s, b



def scale_correlations(
    jac: Optional[np.ndarray],
    basis: np.ndarray,
    weights: Optional[np.ndarray] = None,
    *,
    bg_basis: Optional[np.ndarray] = None,
    reduced_chi2: float = 1.0,
) -> np.ndarray:
    """相标度之间的**相关系数**矩阵 ``(n_phase, n_phase)``。

    为什么单独给一个函数：``linear_sigmas`` 只回答"这个相的 wt% 抖多少"，
    回答不了"这个相的 wt% 和那个相是不是一起动"。多相试样里峰重叠严重时，
    两相标度可以**此消彼长而总 Rwp 几乎不变** —— 此时 wt% 有两位小数的
    表面精度，物理上却完全不可辨（5-3 的定量大幅重排就是这么来的）。

    ``ρ_ij = cov_ij / √(cov_ii·cov_jj)``，从 :func:`full_covariance` 的相标度
    块取。判读经验值：

    ==========  ==========================================================
    |ρ|         含义
    ==========  ==========================================================
    < 0.8       两相有各自独立的强线，份额可分
    0.8 ~ 0.95  轻度共享峰区，wt% 差 1~2 pp 不宜当结论
    > 0.95      **不可分辨**：份额可在两相间互换，wt% 只能定性
    ==========  ==========================================================

    注意这是"给定当前模型"的条件相关系数：模型（择优/占位/峰形）本身错时，
    相关性只会更高，不会更低 —— 所以它是个下界意义上的"不可分辨"判据。

    块位置走 :func:`linear_block_slices`：带 ``jac`` 时必须跳过前 ``P_nonlin``
    列，否则取到的是非线性参数块（详见该函数说明）。
    """
    b = np.asarray(basis, dtype=float)
    n = int(b.shape[1]) if b.ndim == 2 else 1
    if n < 2:
        return np.ones((n, n))
    cov = full_covariance(jac, b, weights, bg_basis=bg_basis,
                          reduced_chi2=reduced_chi2)
    sl_s, _sl_b = linear_block_slices(jac, b, bg_basis)
    blk = np.asarray(cov[sl_s, sl_s], dtype=float)
    if not np.all(np.isfinite(blk)):
        return np.full((n, n), np.nan)
    d = np.sqrt(np.clip(np.diag(blk), 1e-300, None))
    corr = blk / np.outer(d, d)
    corr = np.clip(corr, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    return corr
