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


def elements_match_filter(
    phase_elements: set[str],
    must: Optional[list[str]] = None,
    maybe: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
) -> bool:
    """检查物相元素是否满足过滤条件

    Args:
        phase_elements: 物相包含的元素集合
        must: 必须包含的元素列表（至少含一个）
        maybe: 可选元素列表（不影响判断）
        exclude: 必须排除的元素列表

    Returns:
        True 表示符合过滤条件
    """
    # 检查排除条件
    if exclude:
        for elem in exclude:
            if elem in phase_elements:
                return False

    # 检查必须条件
    if must:
        has_required = any(elem in phase_elements for elem in must)
        if not has_required:
            return False

    return True