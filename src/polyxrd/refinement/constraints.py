"""线性等式约束：把"依赖参数"从自由向量里消掉，由独立参数导出。

为什么 Rietveld 必须有约束
--------------------------
全胞展开后同一 Wyckoff 轨道上的原子共享一个坐标自由度。如果逐原子放开，
雅可比里会出现 4 条完全相同的列 → ``JᵀJ`` 直接奇异，LM 报 ``SVDsing``。
GSAS-II 的做法是建"约束方程表"，把依赖参数写成独立参数的线性组合：

    x_dep = c₀ + Σ_k a_k · x_k

本模块就做这一件事。支持的写法与 GSAS-II 对齐：

* **等值约束**：``atom1.x = atom2.x``（同轨道共享）
* **线性组合**：``occ(Ni) + occ(Li) = 1``（互占位，Li/Ni 混排）
* **比例约束**：``biso(O2) = 1.5·biso(O1)``
* **常量约束**：``occ = 0.5``（等价于 fixed，但保留在约束表里可追溯）

**求解顺序**：约束可以链式（dep2 依赖 dep1），用拓扑排序展开；成环报错。
所有约束都必须是**线性**的 —— 非线性约束（如 a/b 比值）请改用独立参数化
（把一个参数换成比值参数），别硬塞进这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "Constraint",
    "ConstraintSystem",
    "make_equal",
    "make_sum_to",
    "make_ratio",
]


@dataclass
class Constraint:
    """``name = const + Σ terms[k]·k``。"""

    name: str
    terms: Dict[str, float] = field(default_factory=dict)
    const: float = 0.0

    def __post_init__(self) -> None:
        self.terms = {str(k): float(v) for k, v in dict(self.terms).items()}
        if self.name in self.terms:
            raise ValueError(f"约束 {self.name} 依赖自身")
        if not self.terms:
            # 纯常量约束是合法的（等价 fixed，但留痕）
            self.terms = {}

    def inputs(self) -> Tuple[str, ...]:
        return tuple(self.terms)

    def evaluate(self, lookup) -> float:
        v = float(self.const)
        for k, a in self.terms.items():
            val = lookup(k)
            if val is None:
                raise KeyError(f"约束 {self.name} 引用了不存在的参数 {k}")
            v += a * float(val)
        return v


def make_equal(dependent: str, source: str, scale: float = 1.0,
               const: float = 0.0) -> Constraint:
    """``dependent = const + scale·source``。"""
    return Constraint(dependent, {source: float(scale)}, float(const))


def make_sum_to(names: Sequence[str], total: float = 1.0) -> List[Constraint]:
    """前 n−1 个自由，最后一个 = total − Σ 其余（互占位的标准写法）。"""
    names = list(names)
    if len(names) < 2:
        return []
    dep = names[-1]
    return [Constraint(dep, {n: -1.0 for n in names[:-1]}, float(total))]


def make_ratio(dependent: str, source: str, ratio: float) -> Constraint:
    """``dependent = ratio · source``。"""
    return Constraint(dependent, {source: float(ratio)}, 0.0)


class ConstraintSystem:
    """约束表 + 拓扑求值。"""

    __slots__ = ("_items",)

    def __init__(self, items: Iterable[Constraint] = ()) -> None:
        self._items: Dict[str, Constraint] = {}
        if isinstance(items, Constraint):      # 允许只传一条
            items = [items]
        for c in items:
            self.add(c)

    # ── 容器 ────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items.values())

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def add(self, c: Constraint) -> None:
        self._items[c.name] = c

    def remove(self, name: str) -> None:
        self._items.pop(name, None)

    def clear(self) -> None:
        self._items.clear()

    def dependent_names(self) -> List[str]:
        return list(self._items)

    def is_dependent(self, name: str) -> bool:
        return name in self._items

    # ── 求值 ────────────────────────────────────────────────────
    def order(self) -> List[str]:
        """拓扑序（被依赖的先算）；成环抛 ``ValueError``。"""
        pending = dict(self._items)
        done: List[str] = []
        resolved: set = set()

        guard = 0
        while pending:
            guard += 1
            if guard > 10 * (len(self._items) + 1):
                raise ValueError("约束成环：" + ", ".join(pending))
            ready = [n for n, c in pending.items()
                     if all((k in resolved or k not in self._items)
                            for k in c.terms)]
            if not ready:
                raise ValueError("约束成环：" + ", ".join(pending))
            for n in ready:
                done.append(n)
                resolved.add(n)
                pending.pop(n)
        return done

    def evaluate(self, getter) -> Dict[str, float]:
        """返回 ``{依赖参数: 值}``；``getter(name) -> float|None``。"""

        def lookup(name: str) -> Optional[float]:
            if name in resolved:
                return resolved[name]
            return getter(name)

        resolved: Dict[str, float] = {}
        out: Dict[str, float] = {}
        for name in self.order():
            c = self._items[name]
            v = c.const
            for k, a in c.terms.items():
                val = resolved[k] if k in resolved else getter(k)
                if val is None:
                    raise KeyError(f"约束 {name} 引用了不存在的参数 {k}")
                v += a * float(val)
            resolved[name] = v
            out[name] = v
        return out

    def apply(self, params) -> None:
        """把约束值写回 ``ParameterSet``（不改变自由向量）。"""
        vals = self.evaluate(params.get)
        for name, v in vals.items():
            if name in params:
                params.set(name, v)

    def describe(self) -> List[str]:
        out = []
        for n in self.order():
            c = self._items[n]
            rhs = " + ".join(f"{a:+.4g}·{k}" for k, a in c.terms.items())
            if c.const:
                rhs = f"{c.const:+.4g} " + rhs
            out.append(f"{n} = {rhs.strip()}")
        return out
