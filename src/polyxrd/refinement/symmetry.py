"""按空间群约束晶胞自由度 —— 六方相不能放开 6 个胞参。

为什么必须做
------------
``build_parameters`` 默认把 ``a/b/c/α/β/γ`` 全放开。立方相这样放开，Hessian
立刻秩亏（三个长度、三个角度互相完全抵消，任何"a 变大 1%、b 变小 1%"的组合
都不改变衍射图）；六方相同理（``a=b``、``γ=120°`` 是硬约束）。实测：LiNiO₂
（R-3m）放开 6 个胞参时秩 14/47，LM 的步长被投影到边界上、λ 涨到 1e8，
一百多次评估 Rwp 一动不动。

真实程序（GSAS-II / FullProf）都是**按空间群只放独立参数**，其余由对称性
约束住。本模块就是这条规则的显式实现：

======================  ==============================================
晶系                    独立胞参（其余被约束）
======================  ==============================================
三斜                    6
单斜（b 唯一轴）        a, b, c, β
正交                    a, b, c
四方 / 六方（六方轴）   a, c（四方 a=b、六方 a=b 且 γ=120°）
三方（菱形轴）          a, α
立方                    a
======================  ==============================================

三方相要看**轴的选择**：符号以 ``R`` 开头且给的是六方轴（``α=β=90°``、
``γ=120°``）时按六方处理；给的是菱形轴（``a=b=c``、``α=β=γ``）时按菱形处理。
两者是同一个群的不同坐标，混用会算出错的 d 值。

两种约束，机制不同（这是本模块唯一容易写错的地方）
--------------------------------------------------
* **常量约束**（``α=90°``、``γ=120°``）→ 直接 ``fix``。它不跟随任何东西，
  钉死即可。
* **跟随约束**（``b=a``、``c=a``、``β=γ=α``）→ **必须进约束表**，不能用 ``fix``。
  用 ``fix`` 只在建参数书的那一刻把 ``b`` 抄成当时的 ``a``；之后 ``a`` 每走一步
  ``b`` 都停在旧值 → 六方相瞬间变成 a≠b 的假单斜，整个 d 值序列都错。
  ``ConstraintSystem`` 的 ``apply`` 挂在 ``ParameterSet.assign`` 之后，每次写回
  都会重算依赖参数，正好是这里需要的语义。

位点自由度（v5.1）
------------------
胞参只是一半。位点坐标同样受空间群约束，而且约束形式更隐蔽：``StructureModel``
存的是**已展开的 P1 全胞**，刚玉 R-3c 有 30 个位点、方解石 30 个位点 —— 逐位点
放开 90 个坐标自由度，实际独立量只有 2 个（Al 的 z、O 的 x），Hessian 必然秩亏。

真实 Rietveld 的规则是：**同一 Wyckoff 轨道的原子共享一组自由度**，且轨道代表
点若落在特殊位置上，只有稳定子（stabilizer）允许的方向能走。本模块
:func:`orbit_decomposition` 就是这两条规则的显式实现：

1. **轨道归并**：逐位点用空间群操作生成轨道，同元素、同占位的轨道成员并成一个
   独立位点；记录"用哪条操作能把代表点搬到它"，于是代表点一动，整条轨道跟着动。
2. **稳定子锁轴**：代表点的稳定子（把它映回自身的操作集合）决定哪些方向是
   不变子空间 —— ``P = mean(R_stab)`` 是到不变子空间的正交投影，``P·e_a``
   为零的轴必须钉死（否则就是"把原子推离特殊位置"的假自由度）。
   等价方向（如 ``(x,x,x)`` 上的三个轴给出同一个方向）只保留第一个，
   其余钉死 —— 宁可少放，不放共线列。

投影之后每个参量还有 1:1 的物理含义：位移矩阵取 ``(P·e_a)/|P·e_a|²``，
普通位置上它就等于 ``e_a``（参数就是坐标），``(x,x,x)`` 上则是 "x 一动
三个分量一起动同样多"。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .constraints import Constraint, ConstraintSystem

__all__ = [
    "CRYSTAL_SYSTEMS",
    "INDEPENDENT_CELL_PARAMS",
    "SITE_TOL",
    "OrbitDecomposition",
    "crystal_system_from_symbol",
    "resolve_space_group_symbol",
    "cell_ties",
    "apply_cell_ties",
    "orbit_decomposition",
    "site_displacement_matrix",
    "stabilizer_projection",
]

CRYSTAL_SYSTEMS: Tuple[str, ...] = (
    "triclinic", "monoclinic", "orthorhombic", "tetragonal",
    "trigonal", "hexagonal", "cubic",
)

#: 各晶系**独立**的胞参名（其余由对称性定死或跟随）
INDEPENDENT_CELL_PARAMS: Dict[str, Tuple[str, ...]] = {
    "triclinic": ("a", "b", "c", "alpha", "beta", "gamma"),
    "monoclinic": ("a", "b", "c", "beta"),
    "orthorhombic": ("a", "b", "c"),
    "tetragonal": ("a", "c"),
    "hexagonal": ("a", "c"),
    "rhombohedral": ("a", "alpha"),
    "cubic": ("a",),
}

# 全角名 → 中文/符号（报告与 UI 用）
_ANGLE_FIXED_90 = {"alpha": 90.0, "beta": 90.0, "gamma": 90.0}

# 下标数字（CIF 里偶尔会出现 ``P2₁/c`` 这种带 Unicode 下标的写法）
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

#: 规范符号表缓存（首次调用时建，约 230 条）
_SYMBOLS: Optional[Tuple[str, ...]] = None

#: 空间群对象缓存（原写法 → ``SpaceGroup`` 或 ``None``）。
#: OrderedDict 做 LRU：CIF 里可能出现任意自定义符号，长会话下若无限增长会
#: 白占内存（SpaceGroup 内含对称操作矩阵）。上限 256 足够覆盖 230 个标准群
#: 加常见替代设置，超出时淘汰最久未用的一条。
_SG_CACHE: "OrderedDict[str, object]" = OrderedDict()
_SG_CACHE_MAX = 256


def _symbol_table() -> Tuple[str, ...]:
    """pymatgen 的规范符号集合。

    不同版本 ``SYMM_DATA`` 结构不同，这里取**并集**兜住：

    * 新版（``SYMM_DATA`` 是 ``{分类名: 表}``）：``space_group_encoding``（234 条，
      覆盖除单斜外全部群）＋ ``abbreviated_spacegroup_symbols``（13 条，只有单斜
      的缩写形式 ``P2_1/c`` —— 单斜在 encoding 表里是 ``P12/c1`` 这种全设置写法，
      跟 CIF 写法对不上）。
    * 老版（``SYMM_DATA`` 直接是 ``符号 → 操作`` 字典）：取其键。

    **不用** ``SpaceGroup.from_int_number`` 枚举：它返回"等价设置"（第 14 号给
    ``P12_1/c1`` 而不是 ``P2_1/c``），跟 CIF 对不上，且 230 次构造实测 2.4 s。
    """
    global _SYMBOLS
    if _SYMBOLS is None:
        try:
            from pymatgen.symmetry.groups import SYMM_DATA
        except Exception:  # noqa: BLE001 - pymatgen 不在
            _SYMBOLS = ()
            return _SYMBOLS
        syms: set = set()
        if isinstance(SYMM_DATA, dict) and "space_group_encoding" in SYMM_DATA:
            syms.update(SYMM_DATA.get("space_group_encoding", {}))
            abbrev = SYMM_DATA.get("abbreviated_spacegroup_symbols", {})
            if isinstance(abbrev, dict):
                syms.update(abbrev)
                syms.update(abbrev.values())
        else:
            syms.update(SYMM_DATA)
        _SYMBOLS = tuple(sorted(syms))
    return _SYMBOLS


def _setting_from_symbol(symbol: str) -> Optional[str]:
    """符号里的 setting 后缀：``':R'`` 表示菱形轴，``':H'`` 表示六方轴。"""
    s = str(symbol or "")
    if ":" not in s:
        return None
    tail = s.rsplit(":", 1)[-1].strip().upper()
    return tail[:1] or None


def _clean_symbol(symbol: str) -> str:
    """剥 setting 后缀、空格、Unicode 下标：``"P 1 21/n 1"`` → ``"P121/n1"``。"""
    raw = str(symbol or "").strip()
    if not raw:
        return ""
    return raw.split(":")[0].replace(" ", "").translate(_SUBSCRIPT)


def resolve_space_group_symbol(symbol: str) -> Optional[str]:
    """CIF 写法 → pymatgen 的规范符号（认不出返回 ``None``）。

    CIF 里普遍写 ``P21/c`` / ``P 21/c`` / ``R -3 c``，而规范表用 ``P2_1/c`` /
    ``R-3c``（螺旋轴要下划线）。少了这层归一化，单斜、六方相会被静默跳过 ——
    表现为"约束没生效"，比报错更难查。

    支持三种输入：规范符号、去掉下划线/空格的写法、国际表编号（``"225"``）。

    .. note::
       本函数只认**规范设置**。CIF 里大量出现替代设置（``P b n m`` 是 Pnma 的
       轴置换、``P 1 21/n 1`` 是 P2₁/n 的全设置写法），它们不在规范表里 →
       返回 ``None``。要拿晶系请用 :func:`crystal_system_from_symbol`，它会
       在规范表失手时直接构造（见 :func:`_load_space_group`）。
    """
    clean = _clean_symbol(symbol)
    if not clean:
        return None
    if clean.isdigit():
        try:
            from pymatgen.symmetry.groups import SpaceGroup

            return SpaceGroup.from_int_number(int(clean)).symbol
        except Exception:  # noqa: BLE001
            return None
    key = clean.replace("_", "").lower()
    for sym in _symbol_table():
        if sym.replace("_", "").lower() == key:
            return sym
    return None


def _load_space_group(symbol: str):
    """CIF 写法 → pymatgen ``SpaceGroup``；认不出返回 ``None``。

    **为什么不能只查规范表**（2026-11-05 实测）：COD 的吉布斯石写
    ``P 1 21/n 1``、针铁矿写 ``P b n m``，两者都不在规范符号表里，
    ``resolve_space_group_symbol`` 返回 ``None`` → ``apply_cell_ties`` 整段
    跳过 → 该相 6 个胞参全放开。7-1 的针铁矿因此把 β 从 90° 跑到 **130.8°**、
    a/b 各错 1~2%，峰位全错、标度塌到 1.04 wt%（真值 9.98）。

    而 pymatgen 的 ``SpaceGroup`` 构造器本身**能吃替代设置**（由 monty 的符号
    表兜底，只在认不出全名时给一条 ``Full symbol not available`` 警告），
    返回的 ``crystal_system`` 与对称操作都是对的。所以这里有第二道：
    规范表失手就用清洗后的原写法直接构造。

    构造一次约 1~3 ms（解析 8~192 条对称操作），每建一次参数册都要按相调一遍，
    故按原写法缓存 —— ``SpaceGroup`` 建后不再变，可以安全复用。
    """
    key = str(symbol or "")
    if key in _SG_CACHE:
        _SG_CACHE.move_to_end(key)
        return _SG_CACHE[key]
    sg = None
    for cand in (resolve_space_group_symbol(symbol), _clean_symbol(symbol)):
        if not cand:
            continue
        try:
            from pymatgen.symmetry.groups import SpaceGroup

            sg = SpaceGroup(cand)
            break
        except Exception:  # noqa: BLE001 - 这个候选不行，试下一个
            continue
    _SG_CACHE[key] = sg
    while len(_SG_CACHE) > _SG_CACHE_MAX:
        _SG_CACHE.popitem(last=False)
    return sg


def crystal_system_from_symbol(
    symbol: str,
    cell: Optional[object] = None,
) -> Optional[str]:
    """空间群符号 → 晶系名。认不出返回 ``None``（调用方据此不做约束）。

    只走 pymatgen 的权威表。**刻意不做符号启发式**：猜错晶系会直接把 d 值算错
    （比"不约束"危险得多），而 pymatgen 从 v2.x 起就是本项目的既有依赖，
    在 ``phase_cif`` 里已经用它展开对称操作 —— 没有它这条链路本来也不通。

    :param cell: 可选 ``Cell``，只用于三方相判断轴选择（菱形 vs 六方）
    """
    sg = _load_space_group(symbol)
    if sg is None:
        return None
    try:
        sysname = str(getattr(sg.crystal_system, "value",
                              sg.crystal_system)).lower()
    except Exception:  # noqa: BLE001 - 符号认不出
        return None
    if sysname == "trigonal":
        return _trigonal_axes(str(symbol or ""), cell)
    if sysname == "rhombohedral":
        return "rhombohedral"
    return sysname if sysname in CRYSTAL_SYSTEMS else None


def _trigonal_axes(symbol: str, cell: Optional[object]) -> str:
    """三方相：六方轴 → ``"hexagonal"``（a=b, γ=120°）；菱形轴 → ``"rhombohedral"``。"""
    setting = _setting_from_symbol(symbol)
    if setting == "R":
        return "rhombohedral"
    if setting == "H":
        return "hexagonal"
    if cell is not None:
        try:
            a, b, c = float(cell.a), float(cell.b), float(cell.c)
            al, be, ga = float(cell.alpha), float(cell.beta), float(cell.gamma)
            rhombo = (abs(a - b) < 1e-6 and abs(b - c) < 1e-6
                      and abs(al - be) < 1e-3 and abs(be - ga) < 1e-3
                      and abs(ga - 90.0) > 1e-3)
            if rhombo:
                return "rhombohedral"
        except (AttributeError, TypeError, ValueError):
            pass
    # R 心在三方里通常用六方轴习惯（calcite / corundum / LiNiO2 都是）
    return "hexagonal"


def _monoclinic_unique_angle(cell: Optional[object]) -> str:
    """单斜晶胞的唯一轴对应哪个角：``"beta"``（b 唯一轴）占绝大多数。

    判定 = 输入晶胞里离 90° 最远的那个角；三个角都贴着 90° 时退回 ``"beta"``。
    """
    best, best_dev = "beta", 0.0
    for tag in ("alpha", "beta", "gamma"):
        try:
            dev = abs(float(getattr(cell, tag)) - 90.0)
        except (AttributeError, TypeError, ValueError):
            continue
        if dev > best_dev:
            best, best_dev = tag, dev
    return best if best_dev > 1e-3 else "beta"


def cell_ties(
    system: str,
    *,
    cell: Optional[object] = None,
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """晶系 → ``(定死值, 跟随关系)``。

    :param cell: 可选 ``Cell``；只有单斜/三方需要看它（唯一轴 / 菱形轴判定）
    :returns: ``({"alpha": 90.0, ...}, {"b": "a", ...})``
    """
    fixed: Dict[str, float] = {}
    follow: Dict[str, str] = {}
    s = str(system or "").lower()

    if s == "cubic":
        follow.update({"b": "a", "c": "a"})
        fixed.update(_ANGLE_FIXED_90)
    elif s == "hexagonal":
        follow["b"] = "a"
        fixed.update(_ANGLE_FIXED_90)
        fixed["gamma"] = 120.0
    elif s == "tetragonal":
        follow["b"] = "a"
        fixed.update(_ANGLE_FIXED_90)
    elif s == "orthorhombic":
        fixed.update(_ANGLE_FIXED_90)
    elif s == "monoclinic":
        # 唯一轴**看晶胞**：绝大多数 CIF 是 b 唯一轴（α=γ=90°、β 自由），
        # 但也有 c 唯一轴的老设置（``P 1 1 21/c 1`` 之类），那时该钉的是
        # α、β，游走的角是 γ。按输入晶胞里"离 90° 最远的那个角"判定，
        # 三个角都恰好 90° 时退回 b 唯一轴（常见设置）。写死 β 会在 c 唯一
        # 轴的记录上把 γ 钉在 90° → 整个 d 序列算错，且没有任何报错。
        for tag in ("alpha", "beta", "gamma"):
            if tag != _monoclinic_unique_angle(cell):
                fixed[tag] = 90.0
    elif s == "rhombohedral":
        follow.update({"b": "a", "c": "a",
                       "beta": "alpha", "gamma": "alpha"})
    elif s == "triclinic":
        pass
    return fixed, follow


def apply_cell_ties(params, prefix: str, symbol: str,
                    cell: Optional[object] = None) -> List[str]:
    """按空间群把某相的胞参约束住，返回被约束的参数名。

    常量（90°/120°）直接 ``fix``；跟随关系写进 ``ConstraintSystem``（``assign``
    之后自动重算），这样 ``a`` 一走，``b``/``c`` 立刻跟上，晶胞始终自洽。

    这不是"近似"——对称性本来就规定它们相等，放进拟合只会多出一条恒零的
    雅可比列（Hessian 立刻奇异）。

    :param params: ``ParameterSet``
    :param prefix: 相前缀，如 ``"phase0"``
    :param symbol: 空间群符号（如 ``"R-3c"``），认不出 → 什么都不做
    """
    if not symbol:
        return []
    system = crystal_system_from_symbol(symbol, cell)
    if system is None:
        return []
    fixed, follow = cell_ties(system, cell=cell)
    touched: List[str] = []

    # 1) 常量：钉死即可
    for tag, value in fixed.items():
        name = f"{prefix}.cell.{tag}"
        if name in params:
            params.set(name, value)
            params.fix(name, True)
            touched.append(name)

    # 2) 跟随：必须进约束表（见模块 docstring）
    ties = []
    for tag, src in follow.items():
        name = f"{prefix}.cell.{tag}"
        src_name = f"{prefix}.cell.{src}"
        if name in params and src_name in params:
            ties.append(Constraint(name, {src_name: 1.0}, 0.0))
            touched.append(name)
    if ties:
        cons = params.constraints
        if cons is None:
            params.set_constraints(ConstraintSystem(ties))
        else:
            for c in ties:
                cons.add(c)
            cons.apply(params)          # 立刻对齐一次，别等第一次 assign
    return touched


# ── 位点：Wyckoff 轨道归并 + 稳定子锁轴 ──────────────────────────────
#: 判定"两个分数坐标是同一个点"的容差（周期性回绕后比较）
#:
#: 取 1e-3 而不是机器精度：COD 里的坐标只印 4~6 位小数，同一条轨道上的
#: 等价位点展开回来往往差 1e-4 量级（例如 0.3333 与 1/3）。容差放大到 1e-3
#: 会把两个真实不同的位点并掉的概率极低（0.3 pm 以内），却能把"轨道根本没
#: 闭合"的脏结构整条挡在门外。
SITE_TOL: float = 1e-3


def _ops_arrays(ops: Sequence) -> Tuple[np.ndarray, np.ndarray]:
    """pymatgen ``SymmOp`` 序列 → ``(rots (n,3,3), trans (n,3))``。"""
    rots = np.array([np.asarray(op.rotation_matrix, dtype=float) for op in ops],
                    dtype=float)
    trans = np.array([np.asarray(op.translation_vector, dtype=float) for op in ops],
                     dtype=float)
    return rots, trans


def _periodic_delta(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``a - b`` 的周期性最短差（逐分量落在 ``[-0.5, 0.5]``）。"""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    return d - np.round(d)


def _projection(rots: np.ndarray, trans: np.ndarray, frac: np.ndarray,
                tol: float = SITE_TOL) -> np.ndarray:
    """到"稳定子不变子空间"的正交投影 ``P``（3×3）。

    稳定子 = 把 ``frac`` 映回自身的操作（周期性意义下）；``P = mean(R_stab)``
    对有限群是幂等对称矩阵，把任意位移投影到"不破坏位点对称性"的方向上。

    没有非恒等稳定子（一般位置）时返回单位阵。稳定子**不含**恒等操作说明
    ``frac`` 与空间群不自洽（脏数据）→ 也返回单位阵，让调用方退回逐位点放开。
    """
    imgs = rots @ frac + trans
    hit = np.all(np.abs(_periodic_delta(imgs, frac)) < tol, axis=1)
    if not np.any(hit):
        return np.eye(3)
    return rots[hit].mean(axis=0)


def stabilizer_projection(ops: Sequence, frac, tol: float = SITE_TOL) -> np.ndarray:
    """见 :func:`_projection`；对外入口（拿 ``SymmOp`` 序列直接调）。"""
    if ops is None or len(ops) == 0:
        return np.eye(3)
    rots, trans = _ops_arrays(ops)
    return _projection(rots, trans, np.asarray(frac, dtype=float), tol)


def _displacement_matrix(P: np.ndarray) -> np.ndarray:
    """``P`` → 「参量位移 → 分数位移」矩阵 ``M``（3×3）。

    逐轴：``M[:,a] = (P·e_a)/|P·e_a|²``。

    * 一般位置（``P=I``）：``M=I`` —— 参数就是坐标，完全向后兼容。
    * ``(x,0,1/4)`` 这类位置：``P·e_y = P·e_z = 0`` → 那两列全零，调用方据此
      **钉死** ``y``/``z`` 两个参量。
    * ``(x,x,x)``：三列都是 ``(1,1,1)/3``，只有第一个是独立方向 → 后两列清零，
      ``M[:,x] = (1,1,1)``，于是"x 参量一动，三个分量一起动同样多"。

    除以 ``|P·e_a|²`` 而不是 ``|P·e_a|`` 是刻意的：它让参量与坐标保持 1:1，
    ``atom{k}.x`` 报出的数就是原子的 x 坐标（而不是被投影缩过的量）。
    """
    M = np.zeros((3, 3), dtype=float)
    kept: List[int] = []
    for a in range(3):
        v = np.asarray(P, dtype=float)[:, a]
        nv = float(np.linalg.norm(v))
        if nv < 1e-8:
            continue                       # 该方向被稳定子完全锁死
        if kept:
            B = np.column_stack([np.asarray(P, dtype=float)[:, b] for b in kept])
            resid = v - B @ np.linalg.lstsq(B, v, rcond=None)[0]
            if float(np.linalg.norm(resid)) < 1e-6 * max(1.0, nv):
                continue                    # 与已保留方向共线 → 钉死，避免重复列
        M[:, a] = v / float(v @ v)
        kept.append(a)
    return M


def site_displacement_matrix(ops: Sequence, frac,
                             tol: float = SITE_TOL) -> np.ndarray:
    """位点 ``frac`` → 位移矩阵 ``M``（3×3，零列 = 该轴被对称性锁死）。"""
    if ops is None or len(ops) == 0:
        return np.eye(3)
    rots, trans = _ops_arrays(ops)
    return _displacement_matrix(_projection(rots, trans,
                                            np.asarray(frac, dtype=float), tol))


@dataclass(eq=False, frozen=True)
class OrbitDecomposition:
    """全胞位点 → 独立位点（Wyckoff 轨道代表）的映射。

    :param rep_of: 长度 = 位点数；每个位点所属的独立位点编号
    :param op_of: 长度 = 位点数；把独立位点搬到该位点的对称操作下标
        （``None`` = 恒等，坐标直接取独立位点）
    :param rep_site: 长度 = 独立位点数；代表位点在输入里的下标
    :param mats: 长度 = 独立位点数；3×3 位移矩阵（见 :func:`_displacement_matrix`）
    :param trivial: True = 没做归并（空间群缺失 / P1 / 认不出）：
        一位点一自由量，``mats`` 全是单位阵
    """

    rep_of: Tuple[int, ...]
    op_of: Tuple[Optional[int], ...]
    rep_site: Tuple[int, ...]
    mats: Tuple[np.ndarray, ...]
    trivial: bool = False

    @property
    def n_rep(self) -> int:
        return len(self.rep_site)


def _trivial(m: int) -> OrbitDecomposition:
    return OrbitDecomposition(
        rep_of=tuple(range(m)), op_of=(None,) * m, rep_site=tuple(range(m)),
        mats=tuple(np.eye(3) for _ in range(m)), trivial=True)


def orbit_decomposition(
    ops: Optional[Sequence],
    positions,
    elements: Sequence[str],
    occupancy=None,
    tol: float = SITE_TOL,
) -> OrbitDecomposition:
    """把全胞位点按空间群轨道归并成独立位点。

    **为什么要归并**：``StructureModel`` 存的是已展开的 P1 全胞。刚玉 R-3c 的
    30 个位点里只有 2 个是独立的（Al 12c 的 z、O 18e 的 x）；逐位点放开 90 个
    坐标自由度，Hessian 立刻秩亏（实测秩 14/47，LM 步长被边界投影吃掉）。

    **归并规则**：同元素、同占位（容差内）、且能被某条空间群操作从同一个代表点
    生成 —— 三条全满足才并。任何一条不满足就各算各的（退化成逐位点），
    所以"轨道没闭合"的脏结构不会把不相干的原子并在一起。

    :param ops: 对称操作序列（``phase_cif.space_group_ops`` 的返回值）；
        ``None`` / 空 / 只有恒等 → 返回 ``trivial=True`` 的逐位点分解
    :param positions: ``(M,3)`` 分数坐标
    :param elements: 长度 M 的元素符号（轨道不跨元素）
    :param occupancy: 长度 M 的占位；``None`` → 全 1.0
    """
    pos = np.asarray(positions, dtype=float)
    m = int(pos.shape[0]) if pos.ndim == 2 else 0
    if m == 0:
        return _trivial(0)
    if ops is None or len(ops) <= 1:
        return _trivial(m)

    rots, trans = _ops_arrays(ops)
    if rots.shape[1:] != (3, 3):          # 保险丝：操作数组形状不对 → 不归并
        return _trivial(m)
    elems = [str(e or "") for e in elements]
    if len(elems) != m:
        return _trivial(m)
    occ = np.ones(m, dtype=float) if occupancy is None \
        else np.asarray(occupancy, dtype=float).reshape(-1)
    if occ.size != m:
        return _trivial(m)

    pool_by_elem: Dict[str, List[int]] = {}
    for i, e in enumerate(elems):
        pool_by_elem.setdefault(e, []).append(i)

    used = np.zeros(m, dtype=bool)
    rep_of: List[int] = [-1] * m
    op_of: List[Optional[int]] = [None] * m
    rep_site: List[int] = []
    mats: List[np.ndarray] = []
    for i in range(m):
        if used[i]:
            continue
        k = len(rep_site)
        rep_of[i] = k
        op_of[i] = None
        used[i] = True
        rep_site.append(i)
        mats.append(_displacement_matrix(_projection(rots, trans, pos[i], tol)))
        for oi in range(rots.shape[0]):
            q = rots[oi] @ pos[i] + trans[oi]
            q = q - np.floor(q)
            pool = [j for j in pool_by_elem[elems[i]] if not used[j]]
            if not pool:
                break
            d = np.abs(pos[pool] - q)
            d = np.minimum(d, 1.0 - d)
            hit = np.nonzero(np.all(d < tol, axis=1))[0]
            if hit.size == 0:
                continue
            j = pool[int(hit[0])]
            if abs(occ[j] - occ[i]) > tol:
                continue                    # 轨道内占位不一致（无序）→ 不并
            rep_of[j] = k
            op_of[j] = oi
            used[j] = True
    return OrbitDecomposition(rep_of=tuple(rep_of), op_of=tuple(op_of),
                              rep_site=tuple(rep_site), mats=tuple(mats),
                              trivial=False)
