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
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .constraints import Constraint, ConstraintSystem

__all__ = [
    "CRYSTAL_SYSTEMS",
    "INDEPENDENT_CELL_PARAMS",
    "crystal_system_from_symbol",
    "resolve_space_group_symbol",
    "cell_ties",
    "apply_cell_ties",
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


def resolve_space_group_symbol(symbol: str) -> Optional[str]:
    """CIF 写法 → pymatgen 的规范符号（认不出返回 ``None``）。

    CIF 里普遍写 ``P21/c`` / ``P 21/c`` / ``R -3 c``，而规范表用 ``P2_1/c`` /
    ``R-3c``（螺旋轴要下划线）。少了这层归一化，单斜、六方相会被静默跳过 ——
    表现为"约束没生效"，比报错更难查。

    支持三种输入：规范符号、去掉下划线/空格的写法、国际表编号（``"225"``）。
    """
    raw = str(symbol or "").strip()
    if not raw:
        return None
    clean = raw.split(":")[0].replace(" ", "").translate(_SUBSCRIPT)
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
    canonical = resolve_space_group_symbol(symbol)
    if canonical is None:
        return None
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        sg = SpaceGroup(canonical)
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


def cell_ties(
    system: str,
    *,
    cell: Optional[object] = None,
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """晶系 → ``(定死值, 跟随关系)``。

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
        # b 唯一轴的标准设置：α=γ=90°，β 自由
        fixed["alpha"] = 90.0
        fixed["gamma"] = 90.0
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
