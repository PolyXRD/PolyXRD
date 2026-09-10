"""
化学式解析器
============
将化学式字符串解析为元素集合。

支持的格式:
- 简单: SiO2, Al2O3, Fe2O3
- 括号: Ca(OH)2, CaMg(CO3)2
- 嵌套: KAl2Si3O10(OH)2
- 逗号: (Mg,Fe)5Al(Si3Al)O10(OH)8
- 分数: LiNi0.8Co0.1Mn0.1O2
"""
from __future__ import annotations

import re
from typing import Optional


VALID_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Pa", "U", "Fr", "Ra", "Ac", "Th", "Np",
    "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr",
}


def parse_formula(formula: str) -> set[str]:
    """解析化学式，返回元素集合

    Args:
        formula: 化学式字符串，如 "SiO2", "Ca(OH)2", "KAl2Si3O10(OH)2"

    Returns:
        元素符号集合，如 {"Si", "O"}
    """
    if not formula or not formula.strip():
        return set()

    formula = formula.strip()
    elements = _parse_group(formula, 0)[0]
    return set(elements.keys())


def parse_formula_detailed(formula: str) -> dict[str, float]:
    """解析化学式，返回元素及数量

    Args:
        formula: 化学式字符串

    Returns:
        {元素符号: 数量} 字典
    """
    if not formula or not formula.strip():
        return {}

    formula = formula.strip()
    return _parse_group(formula, 0)[0]


def _parse_group(formula: str, pos: int) -> tuple[dict[str, float], int]:
    """递归解析括号内的基团"""
    elements: dict[str, float] = {}
    n = len(formula)

    while pos < n:
        if formula[pos] == "(":
            # 找到匹配的右括号
            depth = 1
            end = pos + 1
            while end < n and depth > 0:
                if formula[end] == "(":
                    depth += 1
                elif formula[end] == ")":
                    depth -= 1
                end += 1

            # 递归解析括号内
            inner_elements, _ = _parse_group(formula, pos + 1)

            # 读取括号后的系数
            end_pos, multiplier = _read_number(formula, end)

            for elem, count in inner_elements.items():
                elements[elem] = elements.get(elem, 0) + count * multiplier

            pos = end_pos

        elif formula[pos] == ")":
            return elements, pos + 1

        elif formula[pos].isupper():
            # 读取元素符号
            elem_end = pos + 1
            while elem_end < n and formula[elem_end].islower():
                elem_end += 1
            elem = formula[pos:elem_end]

            if elem not in VALID_ELEMENTS:
                pos = elem_end
                continue

            # 读取元素后的系数
            pos, count = _read_number(formula, elem_end)

            elements[elem] = elements.get(elem, 0) + count

        elif formula[pos] == ",":
            # 逗号分隔的同位置元素 (Mg,Fe) 形式
            pos += 1
            continue

        elif formula[pos].isspace():
            pos += 1

        else:
            # 跳过未知字符
            pos += 1

    return elements, pos


def _read_number(formula: str, pos: int) -> tuple[int, float]:
    """读取数字（整数或小数）作为系数"""
    n = len(formula)
    if pos >= n:
        return pos, 1.0

    start = pos
    has_dot = False

    while pos < n and (formula[pos].isdigit() or formula[pos] == "."):
        if formula[pos] == ".":
            if has_dot:
                break
            has_dot = True
        pos += 1

    if pos == start:
        return pos, 1.0

    try:
        value = float(formula[start:pos])
        return pos, value
    except ValueError:
        return pos, 1.0


# 轻元素: EDX/EDS 等常规手段常测不出, 但 XRD 中 (氢氧化物/碳酸盐/水合物)
# 极常见 → UI 提供"一键设为含有"的辅助。
LIGHT_ELEMENTS: tuple[str, ...] = ("O", "C", "H", "N", "S")

# 元素过滤四类键 (统一口径, 0.9.11)
ELEMENT_FILTER_KEYS: tuple[str, ...] = ("must_have", "has", "maybe", "exclude")


def normalize_element_filter(element_filter: Optional[dict]) -> dict:
    """把 UI / 工程文件里的元素过滤字典规整为统一的四类键。

    兼容旧键 ``must`` (旧语义 = "至少含一个", 对应新的「含有」has)。
    返回 ``{"must_have": [...], "has": [...], "maybe": [...], "exclude": [...]}``
    (缺失项为空列表, 元素保持首次出现顺序且已去重)。
    """
    src = element_filter or {}
    out: dict[str, list[str]] = {k: [] for k in ELEMENT_FILTER_KEYS}
    seen: set[str] = set()
    # 旧键 must 视为「含有」; 新键 has 优先, 二者并存时取并集
    for key in ("must_have", "has", "must", "maybe", "exclude"):
        target = "has" if key == "must" else key
        for el in src.get(key) or []:
            if not el or el in seen:
                continue
            seen.add(el)
            out[target].append(el)
    return out


def elements_match_filter(
    phase_elements: set[str],
    has: Optional[list[str]] = None,
    maybe: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
    *,
    must_have: Optional[list[str]] = None,
    closed_world: bool = True,
) -> bool:
    """四类元素过滤统一判定 (0.9.11)。

    记 S = 物相元素集合, P/H/M/E = 必有/含有/可能/没有 的元素集合:

    ==========  ==============  ==================================================
    类别        判定式          含义
    ==========  ==============  ==================================================
    必有 P       ``P ⊆ S``       每个必有元素都必须出现 (AND, 全部必含)
    含有 H       ``S ∩ H ≠ ∅``   物相由 H 构成, 至少含其中一个
    可能 M       无强制条件       仅放宽允许池; H 为空时「可能」代行 H 之职
    没有 E       ``S ∩ E = ∅``   含任一没有元素即淘汰
    ==========  ==============  ==================================================

    闭环 (``closed_world=True`` 且 ``P∪H∪M`` 非空): 未勾选元素一律视为
    「没有」, 等价于 ``S ⊆ P∪H∪M``。三者全空时不启用闭环 = 全库搜索;
    只勾「没有」时也是开放世界, 仅排除这些元素。

    勾了「必有」时不再要求至少含一个「含有」(纯金属等单元素相仍可作为候选)。

    重叠优先级: 必有 > 含有 > 可能 > 没有。

    Args:
        phase_elements: 物相包含的元素集合
        has: 含有元素 (旧接口的 ``must``, 语义一致)
        maybe: 可能元素
        exclude: 没有元素
        must_have: 必有元素 (关键字参数)
        closed_world: 是否启用"未勾选 = 没有"

    Returns:
        True 表示符合过滤条件
    """
    s = set(phase_elements or ())
    p = set(must_have or ())
    h = set(has or ())
    m = set(maybe or ())
    e = set(exclude or ())
    # 重叠去重: 高优先级类别胜出
    h -= p
    m -= (p | h)
    e -= (p | h | m)

    # ① 没有: 命中任一即淘汰
    if e and (s & e):
        return False
    # ② 闭环: 未勾选元素视为没有 (等价于 S ⊆ P∪H∪M)
    if closed_world and (p or h or m) and not s <= (p | h | m):
        return False
    # ③ 必有: 全部必含
    if p and not p <= s:
        return False
    # ④ 含有: 至少含一个 (必有已满足时不再要求; 含有为空时「可能」代行其职)
    if not p:
        pool = h or m
        if pool and not (s & pool):
            return False
    return True