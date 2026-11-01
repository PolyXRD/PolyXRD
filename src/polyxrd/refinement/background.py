"""背景内核：Chebyshev 与 tent 双基，均作**线性层**直接给设计矩阵。

为什么背景必须是线性层
----------------------
Rietveld 里背景与各相标度是同一类"幅度型"参数 —— 它们只做**线性**组合，
不参与峰位/峰宽的非线性迭代。把它们放进非线性最小二乘会让雅可比多出一堆
几乎共线的列（背景系数与标度强相关），条件数直接爆掉。correct 的做法是
**变量投影**（separable NLS）：每轮先用 ``lstsq`` 闭式解出这些线性系数，
非线性层只剩 5~11 个真参数。

两个基各自适合什么
------------------
* **Chebyshev**（``chebyshev_basis``）：正交多项式，天然良态，适合缓变的
  弥散背景（非晶基线、空气散射）。阶数越高越容易"抢"峰，实战 4~8 阶。
* **tent**（``tent_basis``，GSAS-II 风格）：三角帽基，系数 ≈ 该节点处的
  背景高度，**直观可读**、局部性好、不会像高阶多项式那样在端点发散。
  节点数 = 系数数，通常 8~20。《全谱拟合优化方案 v5》D 阶段"一键默认"里
  tent 更适合作默认（初值 = 用户肉眼看到的背景水平）。

两种基都构造为 ``(N, n)`` 矩阵，``y_bg = basis @ coefs``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

__all__ = [
    "BACKGROUND_KINDS",
    "BackgroundParams",
    "chebyshev_basis",
    "tent_basis",
    "background_basis",
    "background_values",
    "DEFAULT_TENT_NODES",
]

BACKGROUND_KINDS: Tuple[str, ...] = ("chebyshev", "tent", "none")

#: tent 背景的推荐节点数（GSAS-II 默认 6~12；实测 10 对锂电谱很稳）
DEFAULT_TENT_NODES = 10


@dataclass(frozen=True)
class BackgroundParams:
    """背景描述。

    :param kind: ``chebyshev`` / ``tent`` / ``none``
    :param n_terms: Chebyshev 阶数（含常数项）或 tent 节点数
    :param lo: 基的定义区间下界；None → 用传入的 ``two_theta`` 端点
    :param hi: 基的定义区间上界；None → 同上
    """

    kind: str = "tent"
    n_terms: int = DEFAULT_TENT_NODES
    lo: Optional[float] = None
    hi: Optional[float] = None

    def __post_init__(self) -> None:
        if self.kind not in BACKGROUND_KINDS:
            raise ValueError(f"未知背景类型 {self.kind!r}，应为 {BACKGROUND_KINDS}")
        if self.kind != "none" and int(self.n_terms) < 1:
            raise ValueError("n_terms 必须 ≥ 1")

    @property
    def n_coeffs(self) -> int:
        return 0 if self.kind == "none" else int(self.n_terms)

    @property
    def uses_background(self) -> bool:
        return self.kind != "none"


def _axis_span(two_theta, lo: Optional[float], hi: Optional[float]) -> Tuple[float, float]:
    tt = np.asarray(two_theta, dtype=float)
    a = float(lo) if lo is not None else (float(tt.min()) if tt.size else 0.0)
    b = float(hi) if hi is not None else (float(tt.max()) if tt.size else 1.0)
    if not np.isfinite(a) or not np.isfinite(b) or b <= a:
        b = a + 1.0
    return a, b


def chebyshev_basis(
    two_theta,
    n_terms: int = 6,
    *,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
) -> np.ndarray:
    """Chebyshev 多项式基 ``(N, n_terms)``，自变量映射到 ``[-1, 1]``。

    用三项递推 ``T_{k+1} = 2x·T_k − T_{k−1}``，不走 ``np.polynomial.chebyshev``
    的类接口 —— 后者每次调用要建对象，在热循环里开销明显。

    ``n_terms = 1`` → 常数列（等价"只有常数背景"）。
    """
    tt = np.asarray(two_theta, dtype=float)
    n = int(n_terms)
    if n < 1:
        return np.zeros((tt.size, 0))
    a, b = _axis_span(tt, lo, hi)
    x = 2.0 * (tt - a) / (b - a) - 1.0
    out = np.empty((tt.size, n), dtype=float)
    out[:, 0] = 1.0
    if n >= 2:
        out[:, 1] = x
    for k in range(2, n):
        out[:, k] = 2.0 * x * out[:, k - 1] - out[:, k - 2]
    return out


def tent_basis(
    two_theta,
    n_nodes: int = DEFAULT_TENT_NODES,
    *,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
) -> np.ndarray:
    """三角帽（tent / hat）基 ``(N, n_nodes)``，**各单位分解**（逐点行和 = 1）。

    节点等距铺在 ``[lo, hi]`` 上。内部节点是标准三角帽；**首尾节点做半幅延拓**
    （首节点的帽在 ``x ≤ p₀`` 处恒为 1，末节点在 ``x ≥ p_{n−1}`` 处恒为 1），
    这样行和严格为 1 —— 即"常数背景"能被精确表示，且系数语义就是该处的背景
    高度（初值可直接取 ``y`` 的分位数，无需换基换算）。

    ``n_nodes = 1`` → 常数列。
    """
    tt = np.asarray(two_theta, dtype=float)
    n = int(n_nodes)
    if n < 1:
        return np.zeros((tt.size, 0))
    a, b = _axis_span(tt, lo, hi)
    if n == 1:
        return np.ones((tt.size, 1), dtype=float)

    nodes = np.linspace(a, b, n)
    out = np.zeros((tt.size, n), dtype=float)
    step = (b - a) / (n - 1)

    # 内部节点 k=1..n-2：帽在 [p_{k-1}, p_{k+1}] 上
    for k in range(1, n - 1):
        left, mid, right = nodes[k - 1], nodes[k], nodes[k + 1]
        seg = (tt >= left) & (tt <= right)
        x = tt[seg]
        out[seg, k] = np.where(
            x <= mid,
            (x - left) / max(mid - left, 1e-12),
            (right - x) / max(right - mid, 1e-12),
        )

    # 首节点：x ≤ p0 恒 1，然后线性降到 p1 处 0
    if step > 0:
        seg0 = tt <= nodes[1]
        out[seg0, 0] = np.clip((nodes[1] - tt[seg0]) / step, 0.0, 1.0)
        seg1 = tt >= nodes[-2]
        out[seg1, n - 1] = np.clip((tt[seg1] - nodes[-2]) / step, 0.0, 1.0)
    else:  # 退化区间
        out[:, 0] = 1.0
    return out


def background_basis(
    two_theta,
    params: Optional[BackgroundParams] = None,
    *,
    kind: Optional[str] = None,
    n_terms: Optional[int] = None,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
) -> np.ndarray:
    """统一入口：按 ``params`` 生成 ``(N, n_coeffs)`` 背景设计矩阵。

    关键字参数可零散覆盖 ``params`` 里的同名项（拟合器把参数摊平成向量时用）。
    """
    p = params or BackgroundParams()
    k = kind if kind is not None else p.kind
    n = int(n_terms if n_terms is not None else p.n_terms)
    a = lo if lo is not None else p.lo
    b = hi if hi is not None else p.hi
    if k == "none":
        return np.zeros((np.asarray(two_theta).size, 0))
    if k == "chebyshev":
        return chebyshev_basis(two_theta, n, lo=a, hi=b)
    return tent_basis(two_theta, n, lo=a, hi=b)


def background_values(two_theta, coefs, params: Optional[BackgroundParams] = None,
                      **kw) -> np.ndarray:
    """``y_bg = basis @ coefs``；``coefs`` 为空 → 全 0。"""
    c = np.asarray(coefs, dtype=float).reshape(-1)
    if c.size == 0:
        return np.zeros(np.asarray(two_theta, dtype=float).shape)
    basis = background_basis(two_theta, params, **kw)
    if basis.shape[1] != c.size:
        raise ValueError(
            f"背景系数个数 {c.size} 与基列数 {basis.shape[1]} 不一致"
        )
    return basis @ c
