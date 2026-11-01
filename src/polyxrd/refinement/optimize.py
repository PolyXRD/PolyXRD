"""非线性层：自写 Levenberg–Marquardt + scipy ``trf`` 兜底。

为什么不直接用 ``scipy.optimize.least_squares`` 了事
--------------------------------------------------
scipy 的 ``trf`` 很稳，但它在 Rietveld 上有两个实际的痛点：

1. **每轮评估次数不透明**。LM 的雅可比用前向差分就要 n+1 次模型评估；一次
   Rietveld 评估 = 反射表重建 + 峰形卷积 + 线性层求解，几十毫秒。参数 30 个时
   一轮就是 1 秒，迭代 50 轮 = 1 分钟。自写 LM 能把"雅可比只重算变了的列"
   这类优化显式做出来（阶段 B3），scipy 不给这个口子。
2. **收敛判据按自己的量纲**。峰位、占位、B 因子、背景系数量级差 3~4 个量级，
   scipy 的 ``xtol`` 是绝对量，只能靠 ``x_scale`` 猜。Marquardt 的
   ``λ·diag(JᵀJ)`` 缩放在这一点上是自动的。

所以：**默认自写 LM**，``trf`` 作为"LM 卡住/撞边界"时的兜底，两者接口一致，
可以互换。

关于边界
--------
LM 本身不处理边界。这里的做法是**投影步**（projected LM）：算出的步长先夹到
``[lo, hi]`` 再评估；如果某个参数已贴界且步长继续往外推，就把该分量清零
（并在 Hessian 里把该行列置为对角、梯度置零），相当于临时固定。这比把
"有界"参数做 logit 变换简单，也不会在边界附近把步长压成 0。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "FitResult",
    "levenberg_marquardt",
    "scipy_least_squares",
    "minimize_residual",
]

ResidualFn = Callable[[np.ndarray], np.ndarray]


@dataclass
class FitResult:
    """拟合结果与诊断。"""

    x: np.ndarray
    cost: float                     # 0.5·‖r‖²（与 scipy 同口径）
    resid: np.ndarray
    nfev: int = 0
    njev: int = 0
    status: str = "converged"
    message: str = ""
    jac: Optional[np.ndarray] = None
    n_params: int = 0
    n_data: int = 0
    method: str = "lm"

    @property
    def rms(self) -> float:
        return float(np.sqrt(self.cost * 2.0 / max(self.n_data, 1)))

    @property
    def reduced_chi2(self) -> float:
        dof = max(self.n_data - self.n_params, 1)
        return float(self.cost * 2.0 / dof)

    def covariance(self) -> Optional[np.ndarray]:
        """``σ²·(JᵀJ)⁻¹``，奇异时返回 ``None``（交给诊断层报 SVDsing）。"""
        if self.jac is None:
            return None
        H = self.jac.T @ self.jac
        try:
            return np.linalg.inv(H) * self.reduced_chi2
        except np.linalg.LinAlgError:
            return None


def _numeric_jacobian(
    fun: ResidualFn, x: np.ndarray, r0: np.ndarray, *,
    step: float = 1e-6, bounds: Optional[Tuple[np.ndarray, np.ndarray]] = None,
    central: bool = False,
) -> Tuple[np.ndarray, int]:
    """前向（或中心）差分雅可比，返回 ``(J, 额外评估次数)``。

    步长按参数自身量级缩放：``h = step·max(|x_j|, 1)``。参数里有 ``a≈5``、
    ``U≈0.01``、``occ≈1`` 这种跨量级混排，绝对步长会让小量级参数的差分变成
    纯浮点噪声。
    """
    n = x.size
    J = np.empty((r0.size, n), dtype=float)
    nn = 0
    lo, hi = bounds if bounds is not None else (
        np.full(n, -np.inf), np.full(n, np.inf))

    for j in range(n):
        h = step * max(abs(x[j]), 1.0)
        xp = x.copy()
        xp[j] = min(x[j] + h, hi[j])
        if xp[j] == x[j]:                       # 已在上界 → 反向差分
            xp[j] = max(x[j] - h, lo[j])
            if xp[j] == x[j]:
                J[:, j] = 0.0
                continue
            rp = fun(xp)
            nn += 1
            J[:, j] = (r0 - rp) / (x[j] - xp[j])
            continue
        rp = fun(xp)
        nn += 1
        if central:
            xm = x.copy()
            xm[j] = max(x[j] - h, lo[j])
            if xm[j] != x[j]:
                rm = fun(xm)
                nn += 1
                J[:, j] = (rp - rm) / (xp[j] - xm[j])
                continue
        J[:, j] = (rp - r0) / (xp[j] - x[j])
    return J, nn


def levenberg_marquardt(
    fun: ResidualFn,
    x0: Sequence[float],
    *,
    bounds: Optional[Tuple[Sequence[float], Sequence[float]]] = None,
    jac: Optional[Callable[[np.ndarray], np.ndarray]] = None,
    diff_step: float = 1e-6,
    max_iter: int = 200,
    ftol: float = 1e-12,
    xtol: float = 1e-12,
    gtol: float = 1e-12,
    callback: Optional[Callable[[int, np.ndarray, float], None]] = None,
) -> FitResult:
    """带边界投影与 Marquardt 缩放的 LM。

    :param fun: ``x -> r``（残差向量，**不要**预先平方）
    :param x0: 初值
    :param bounds: ``(lo, hi)``；None → 无界
    :param jac: 可选解析雅可比 ``x -> J``；None → 差分
    :param diff_step: 差分相对步长
    :param ftol/xtol/gtol: 代价相对下降 / 步长 / 梯度（都按相对量归一）
    :param callback: ``(iter, x, cost)``，用于进度条与日志

    收敛状态：``converged`` / ``max_iter`` / ``singular`` / ``no_improve``。
    """
    x = np.asarray(x0, dtype=float).reshape(-1).copy()
    n = x.size
    if n == 0:
        r = np.asarray(fun(x), dtype=float)
        return FitResult(x=x, cost=0.5 * float(r @ r), resid=r,
                         status="converged", message="无自由参数",
                         n_params=0, n_data=r.size)
    if bounds is not None:
        lo = np.asarray(bounds[0], dtype=float).reshape(-1)
        hi = np.asarray(bounds[1], dtype=float).reshape(-1)
        x = np.clip(x, lo, hi)
    else:
        lo, hi = np.full(n, -np.inf), np.full(n, np.inf)

    r = np.asarray(fun(x), dtype=float)
    m = r.size
    cost = 0.5 * float(r @ r)
    nfev, njev = 1, 0
    lam = 1e-3
    nu = 2.0
    status, message = "max_iter", ""

    for it in range(max_iter):
        if jac is not None:
            J = np.asarray(jac(x), dtype=float)
            if J.shape != (m, n):
                raise ValueError(f"雅可比形状 {J.shape} 应为 {(m, n)}")
        else:
            J, nn = _numeric_jacobian(fun, x, r, step=diff_step,
                                      bounds=(lo, hi))
            nfev += nn
        njev += 1

        g = J.T @ r
        H = J.T @ J
        diagH = np.maximum(np.diag(H), 1e-30)

        # 梯度范数（按参数尺度归一）—— 已在最优点时直接退出
        g_inf = float(np.max(np.abs(g) / np.sqrt(diagH)))
        if g_inf <= gtol:
            status, message = "converged", "梯度已消失"
            break

        accepted = False
        for _ in range(60):
            A = H + lam * np.diag(diagH)
            # 贴界且步长向外推的分量 → 临时固定（对角加大、梯度置零）
            free = np.ones(n, dtype=bool)
            try:
                step = np.linalg.solve(A, -g)
            except np.linalg.LinAlgError:
                status, message = "singular", "Hessian 奇异"
                lam *= 10.0
                if lam > 1e16:
                    break
                continue

            # 边界投影：把向外推的分量清零后重解一次
            x_new = x + step
            out_hi = (x_new > hi) & (step > 0)
            out_lo = (x_new < lo) & (step < 0)
            blocked = out_hi | out_lo
            if np.any(blocked):
                # 撞界分量直接落到边界上，其余分量重解
                x_new = np.clip(x_new, lo, hi)
                free[blocked] = False
                if np.any(free):
                    Af = A[np.ix_(free, free)]
                    gf = g[free]
                    try:
                        step_f = np.linalg.solve(Af, -gf)
                    except np.linalg.LinAlgError:
                        step_f = -gf / np.maximum(np.diag(Af), 1e-30)
                    x_new = x.copy()
                    x_new[free] = x[free] + step_f
                    x_new = np.clip(x_new, lo, hi)

            r_new = np.asarray(fun(x_new), dtype=float)
            nfev += 1
            cost_new = 0.5 * float(r_new @ r_new)

            # 实际/预测下降比（Nielsen 的 ρ）。注意 step 要用**实际走的步**。
            # ``diag(diagH)·v`` 等价于逐元素 ``diagH*v``，别写成矩阵乘。
            step_eff = x_new - x
            pred = 0.5 * float(step_eff @ (lam * diagH * step_eff - g))
            rho = (cost - cost_new) / pred if pred > 0 else -1.0

            if cost_new < cost:
                dx = float(np.linalg.norm(x_new - x))
                x_scale = float(np.linalg.norm(x)) + 1e-30
                x, r, cost = x_new, r_new, cost_new
                accepted = True
                lam *= max(1.0 / 3.0, 1.0 - (2.0 * rho - 1.0) ** 3) if rho > 0 else 1.0 / 3.0
                lam = max(lam, 1e-12)
                nu = 2.0
                if callback is not None:
                    callback(it, x, cost)
                if dx <= xtol * x_scale:
                    status, message = "converged", "步长过小"
                break
            lam *= nu
            nu *= 2.0
            if lam > 1e16:
                break

        if status == "converged":
            break
        if not accepted:
            status, message = "no_improve", "无法再降低残差（可能已到局部极小或撞边界）"
            break

    # 收尾：重算一次雅可比供协方差用
    if jac is not None:
        J = np.asarray(jac(x), dtype=float)
    else:
        J, nn = _numeric_jacobian(fun, x, r, step=diff_step, bounds=(lo, hi))
        nfev += nn

    return FitResult(x=x, cost=cost, resid=r, nfev=nfev, njev=njev,
                     status=status, message=message, jac=J,
                     n_params=n, n_data=m, method="lm")


def scipy_least_squares(
    fun: ResidualFn,
    x0: Sequence[float],
    *,
    bounds: Optional[Tuple[Sequence[float], Sequence[float]]] = None,
    max_iter: int = 2000,
    callback: Optional[Callable[[int, np.ndarray, float], None]] = None,
) -> FitResult:
    """``scipy.optimize.least_squares(method='trf')`` 的薄封装（兜底/对照）。"""
    from scipy.optimize import least_squares

    x0 = np.asarray(x0, dtype=float).reshape(-1)
    lo = hi = None
    if bounds is not None:
        lo = np.asarray(bounds[0], dtype=float).reshape(-1)
        hi = np.asarray(bounds[1], dtype=float).reshape(-1)
        # scipy 要求严格 lo < hi；把无穷换掉
        lo = np.where(np.isfinite(lo), lo, -np.inf)
        hi = np.where(np.isfinite(hi), hi, np.inf)
        bad = ~(lo < hi)
        if np.any(bad):
            lo = np.where(bad, -np.inf, lo)
            hi = np.where(bad, np.inf, hi)
        x0 = np.clip(x0, lo, hi)

    cnt = [0]

    def _fun(x):
        cnt[0] += 1
        return fun(x)

    res = least_squares(_fun, x0, bounds=(lo, hi) if lo is not None
                        else (-np.inf, np.inf), max_nfev=max_iter)
    r = np.asarray(res.fun, dtype=float)
    status = "converged" if res.success else "no_improve"
    J = getattr(res, "jac", None)
    return FitResult(
        x=np.asarray(res.x, dtype=float), cost=0.5 * float(r @ r), resid=r,
        nfev=int(res.nfev), njev=int(getattr(res, "njev", 0) or 0),
        status=status, message=str(res.message), jac=J,
        n_params=x0.size, n_data=r.size, method="trf",
    )


def minimize_residual(
    fun: ResidualFn,
    x0: Sequence[float],
    *,
    bounds: Optional[Tuple[Sequence[float], Sequence[float]]] = None,
    method: str = "auto",
    **kw,
) -> FitResult:
    """统一入口：``auto`` → 先 LM，状态不好再 ``trf`` 兜底。"""
    if method == "trf":
        return scipy_least_squares(fun, x0, bounds=bounds, **kw)
    res = levenberg_marquardt(fun, x0, bounds=bounds, **kw)
    if method == "lm" or res.status == "converged":
        return res
    # LM 没收敛 → 用 LM 的结果做初值再试 trf（通常能救回来）
    try:
        alt = scipy_least_squares(fun, res.x, bounds=bounds)
    except Exception:                       # pragma: no cover - scipy 内部异常
        return res
    if alt.cost <= res.cost:
        alt.method = f"trf(after lm:{res.status})"
        return alt
    return res
