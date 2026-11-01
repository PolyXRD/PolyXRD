"""精修参数系统：命名、边界、固定、分阶段、不确定度。

为什么需要独立一层
------------------
Rietveld 一次要动几十个参数（每相 6 个胞参数 + 峰形 5 个 + 择优 1 个 + 每原子
4 个），而且它们**不能一次性全放出去** —— 同时开 6 个胞参数会让峰位与峰宽强
相关、Hessian 条件数爆炸，LM 直接发散。真实工具（GSAS-II / FullProf / TOPAS）
都是**分阶段**放参数：先标度+背景 → 再峰形 → 再峰位 → 再结构 → 最后一起收。

本模块只做"参数书"这一件事：给每个参数起名、记住初值/边界/是否固定/属于哪一
阶段/精修后的不确定度。它**不知道**参数怎么影响模型（那是 ``problem.py`` 的
``apply`` 的事），因此可以独立单测。

命名约定（engine/problem 靠前缀分派，新增自由度必须遵守）
-------------------------------------------------------
``inst.zero`` / ``inst.asym`` / ``inst.u`` / ``.v`` / ``.w`` / ``.x`` / ``.y`` / ``.z``
``phase{i}.cell.a`` / ``.b`` / ``.c`` / ``.alpha`` / ``.beta`` / ``.gamma``
``phase{i}.size`` / ``.strain``（样品展宽，TCH）
``phase{i}.po.r``
``phase{i}.atom{k}.x`` / ``.y`` / ``.z`` / ``.occ`` / ``.biso``
``phase{i}.scale``
``bg.c{k}``

``scale`` 与 ``bg.c*`` 恒为 ``fixed``：它们由线性层每轮闭式解出（变量投影），
进自由向量只会让雅可比多一列恒零。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "Parameter",
    "ParameterSet",
    "STAGE_LABELS",
]

#: 阶段编号 → 人类可读标签（UI / 日志用）
#:
#: 顺序即"放开顺序"，累积语义（``stage <= n`` 全放开）。编号对齐
#: ``docs/全谱拟合优化方案-v5.0.0.md`` §3.1，唯一刻意的偏离与理由是：
#:
#: **峰位（2）必须早于峰形（3）**。方案 §3.1 原草稿把"峰形"排在"晶胞"前，
#: 但晶胞未定时去拟合峰宽，Caglioti 参数会把"峰位算错了"吸收成"峰太宽"，
#: 最后卡在假极小（实测：先峰形后峰位，``inst.x`` 跑到 -0.45，真值 0.004）。
#: 这一条与 GSAS-II 的实际操作顺序一致。
#:
#: 4 与 5 分开（择优取向 / 样品展宽）也是刻意的：``r`` 与 TCH 的尺寸项
#: 都在"改变峰强/峰宽的整体走势"，同时放开会互相抵消出等价的假解。
STAGE_LABELS: Dict[int, str] = {
    1: "标度与背景（线性层自动求解，无自由参数）",
    2: "峰位（晶胞 + 零位）",
    3: "峰形（Caglioti / Lorentz / 不对称）",
    4: "择优取向（March–Dollase r）",
    5: "样品展宽（晶粒尺寸 / 微应变）",
    6: "结构（坐标 / 占位 / Biso）",
    7: "全参数收尾",
}


@dataclass
class Parameter:
    """一个可精修量。

    :param name: 唯一名（见模块 docstring 的命名约定）
    :param value: 当前值
    :param min: 下界；``-inf`` = 无
    :param max: 上界；``+inf`` = 无
    :param fixed: True → 不参与拟合（但保留在册，UI 可勾选）
    :param stage: 从第几阶段开始放开（越小越先）
    :param sigma: 精修后标准不确定度（0 = 未估）
    :param label: 展示名（可留空，UI 回退到 name）
    """

    name: str
    value: float
    min: float = -math.inf
    max: float = math.inf
    fixed: bool = False
    stage: int = 1
    sigma: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Parameter.name 不能为空")
        self.value = float(self.value)
        self.min = float(self.min)
        self.max = float(self.max)
        if self.min > self.max:
            raise ValueError(f"{self.name}: min({self.min}) > max({self.max})")
        if not (self.min <= self.value <= self.max):
            # 初值越界 → 夹回边界，而不是抛异常（读入外部 CIF 时经常会碰到）
            self.value = float(np.clip(self.value, self.min, self.max))

    # ── 状态 ────────────────────────────────────────────────────
    @property
    def bounded(self) -> bool:
        return math.isfinite(self.min) or math.isfinite(self.max)

    @property
    def free(self) -> bool:
        return not self.fixed

    def at_bound(self, tol: float = 1e-9) -> bool:
        """是否贴在边界上（精修"卡死"的典型症状，诊断要用）。"""
        if math.isfinite(self.min) and abs(self.value - self.min) <= tol * max(1.0, abs(self.min)):
            return True
        if math.isfinite(self.max) and abs(self.value - self.max) <= tol * max(1.0, abs(self.max)):
            return True
        return False

    def clip(self, value: float) -> float:
        return float(np.clip(value, self.min, self.max))

    def copy(self, **kw) -> "Parameter":
        return replace(self, **kw)

    def as_dict(self) -> dict:
        return {
            "name": self.name, "value": self.value, "min": self.min,
            "max": self.max, "fixed": self.fixed, "stage": self.stage,
            "sigma": self.sigma, "label": self.label,
        }


class ParameterSet:
    """参数书：有序、可按名索引、可按阶段切出自由参数向量。

    ``to_vector(stage)`` / ``assign(x, stage)`` 是拟合器唯一入口 —— 拟合器只看见
    一个 ``x`` 向量，参数名与语义全在这一层。
    """

    __slots__ = ("_params", "_index", "_cons")

    def __init__(self, params: Iterable[Parameter] = (),
                 constraints=None) -> None:
        self._params: List[Parameter] = []
        self._index: Dict[str, int] = {}
        # 约束系统（可选）：被约束的参数不出现在自由向量里，值由独立参数导出
        self._cons = constraints
        for p in params:
            self.add(p)

    # ── 容器协议 ────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._params)

    def __iter__(self) -> Iterator[Parameter]:
        return iter(self._params)

    def __getitem__(self, key) -> Parameter:
        if isinstance(key, str):
            return self._params[self._index[key]]
        return self._params[key]

    def __contains__(self, name: object) -> bool:
        return name in self._index

    # ── 增删查 ──────────────────────────────────────────────────
    def add(self, param: Parameter) -> Parameter:
        if param.name in self._index:
            raise ValueError(f"参数名重复: {param.name}")
        self._index[param.name] = len(self._params)
        self._params.append(param)
        return param

    def extend(self, params: Iterable[Parameter]) -> None:
        for p in params:
            self.add(p)

    def remove(self, name: str) -> None:
        i = self._index.pop(name)
        self._params.pop(i)
        self._index = {p.name: j for j, p in enumerate(self._params)}

    def names(self) -> List[str]:
        return [p.name for p in self._params]

    def values(self) -> np.ndarray:
        return np.array([p.value for p in self._params], dtype=float)

    def get(self, name: str, default: Optional[float] = None) -> Optional[float]:
        p = self._index.get(name)
        return default if p is None else self._params[p].value

    def set(self, name: str, value: float, *, sigma: Optional[float] = None) -> None:
        p = self._params[self._index[name]]
        p.value = p.clip(float(value))
        if sigma is not None:
            p.sigma = float(sigma)

    def fix(self, name: str, fixed: bool = True) -> None:
        self._params[self._index[name]].fixed = bool(fixed)

    def fix_prefix(self, prefix: str, fixed: bool = True) -> int:
        """按前缀批量固定/放开；返回命中个数。"""
        n = 0
        for p in self._params:
            if p.name.startswith(prefix):
                p.fixed = bool(fixed)
                n += 1
        return n

    def subset(self, prefix: str) -> List[Parameter]:
        return [p for p in self._params if p.name.startswith(prefix)]

    # ── 阶段与向量化 ────────────────────────────────────────────
    # ── 约束 ────────────────────────────────────────────────────
    @property
    def constraints(self):
        return self._cons

    def set_constraints(self, cons) -> None:
        """挂上约束系统并立即求值一次（依赖参数从此不进自由向量）。"""
        self._cons = cons
        if cons is not None:
            cons.apply(self)

    def constrained_names(self) -> List[str]:
        return [] if self._cons is None else self._cons.dependent_names()

    def free_indices(self, stage: Optional[int] = None) -> np.ndarray:
        """当前阶段**应参与拟合**的参数下标。

        排除三类：``fixed`` 的、阶段未到的、以及**被约束决定**的
        （依赖参数完全由独立参数导出，放进自由向量会让 Hessian 奇异）。
        """
        cons = self._cons
        idx = [
            i for i, p in enumerate(self._params)
            if p.free and (stage is None or p.stage <= stage)
            and not (cons is not None and cons.is_dependent(p.name))
        ]
        return np.asarray(idx, dtype=int)

    def to_vector(self, stage: Optional[int] = None) -> np.ndarray:
        return np.array([self._params[i].value for i in self.free_indices(stage)],
                        dtype=float)

    def bounds(self, stage: Optional[int] = None) -> Tuple[np.ndarray, np.ndarray]:
        idx = self.free_indices(stage)
        lo = np.array([self._params[i].min for i in idx], dtype=float)
        hi = np.array([self._params[i].max for i in idx], dtype=float)
        return lo, hi

    def assign(self, x: Sequence[float], stage: Optional[int] = None) -> None:
        """把向量写回参数（自动夹到边界内）。长度不符 → ValueError。"""
        idx = self.free_indices(stage)
        arr = np.asarray(x, dtype=float).reshape(-1)
        if arr.size != idx.size:
            raise ValueError(f"向量长度 {arr.size} 与自由参数个数 {idx.size} 不符")
        for i, v in zip(idx, arr):
            self._params[i].value = self._params[i].clip(float(v))
        # 写回后立刻重算依赖参数，保证内部状态始终自洽
        self.refresh_constraints()

    def refresh_constraints(self) -> None:
        """重算被约束的参数（``b = a`` 这类跟随关系）。

        ``assign`` 会自动调；``restore`` / 手工 ``set`` 之后也要调 —— 否则
        协议回滚把 ``a`` 退回去、``b`` 还停在新值，六方相立刻变成 a≠b。
        """
        if self._cons is not None:
            self._cons.apply(self)

    def sigmas(self, stage: Optional[int] = None) -> np.ndarray:
        return np.array([self._params[i].sigma for i in self.free_indices(stage)],
                        dtype=float)

    def set_sigmas(self, sigmas: Sequence[float], stage: Optional[int] = None) -> None:
        idx = self.free_indices(stage)
        arr = np.asarray(sigmas, dtype=float).reshape(-1)
        if arr.size != idx.size:
            raise ValueError(f"sigma 长度 {arr.size} 与自由参数个数 {idx.size} 不符")
        for i, s in zip(idx, arr):
            self._params[i].sigma = float(s)

    # ── 诊断辅助 ────────────────────────────────────────────────
    def at_bound(self, stage: Optional[int] = None) -> List[str]:
        """贴在边界上的自由参数名（"拟合卡死"的信号）。"""
        return [self._params[i].name for i in self.free_indices(stage)
                if self._params[i].at_bound()]

    def snapshot(self) -> Dict[str, float]:
        return {p.name: p.value for p in self._params}

    def restore(self, snap: Dict[str, float]) -> None:
        for name, v in snap.items():
            if name in self._index:
                p = self._params[self._index[name]]
                p.value = p.clip(float(v))
        self.refresh_constraints()

    def copy(self) -> "ParameterSet":
        return ParameterSet([p.copy() for p in self._params], self._cons)

    def as_dict(self) -> dict:
        return {
            "params": [p.as_dict() for p in self._params],
            "constraints": [
                {"name": c.name, "terms": dict(c.terms), "const": c.const}
                for c in (self._cons or ())
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParameterSet":
        from polyxrd.refinement.constraints import Constraint, ConstraintSystem

        items = data.get("constraints") or []
        cons = ConstraintSystem(Constraint(**c) for c in items) if items else None
        return cls([Parameter(**d) for d in data.get("params", ())], cons)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        n_free = int(np.sum([p.free for p in self._params]))
        return f"ParameterSet(n={len(self._params)}, free={n_free})"
