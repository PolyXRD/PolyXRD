"""v2.1 P1-2: 元素周期表 118 元素 + 标准布局断言测试。

背景 (docs/代码评估与改进计划.md §五 P1-2): 旧表只有 100 个元素 ——
Pa/U 重复键被静默覆盖, 第 6 周期 La-Lu 铺占主网格导致 Hf 错到第 18 列,
Po/At/Rn/Rf..Og 共 18 个元素完全缺失。旧测试只跑构建流程、从未断言数据正确。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.views.widgets.element_periodic_table import (
    ACTINIDE_POSITIONS,
    ALL_POSITIONS,
    ELEMENT_NAMES,
    LANTHANIDE_POSITIONS,
    PERIODIC_TABLE,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])

# 评估报告列出的 18 个缺失元素 —— 全部必须存在
MISSING_18 = {
    "Po", "At", "Rn", "Rf", "Db", "Sg", "Bh", "Hs", "Mt",
    "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
}


def test_118_elements_no_duplicate_cell():
    assert len(ALL_POSITIONS) == 118
    # 每个元素占唯一格子 (无重复键覆盖: 旧版 Pa/U 的 F601)
    cells = list(ALL_POSITIONS.values())
    assert len(set(cells)) == 118, "存在重复的 (row, col) 格子"


def test_missing_18_now_present():
    for elem in MISSING_18:
        assert elem in ALL_POSITIONS, f"缺少元素 {elem}"
        assert elem in ELEMENT_NAMES, f"ELEMENT_NAMES 缺少 {elem} 中文名"


def test_period6_standard_order():
    """第 6 周期主网格: Hf 在第 4 列, Ta..Rn 依次右移, f 区只留空位。"""
    assert ALL_POSITIONS["Hf"] == (6, 4)
    expected_p6 = {
        "Cs": (6, 1), "Ba": (6, 2),
        "Hf": (6, 4), "Ta": (6, 5), "W": (6, 6), "Re": (6, 7),
        "Os": (6, 8), "Ir": (6, 9), "Pt": (6, 10), "Au": (6, 11),
        "Hg": (6, 12), "Tl": (6, 13), "Pb": (6, 14), "Bi": (6, 15),
        "Po": (6, 16), "At": (6, 17), "Rn": (6, 18),
    }
    for elem, pos in expected_p6.items():
        assert ALL_POSITIONS[elem] == pos, f"{elem} 位置错误: {ALL_POSITIONS[elem]}"
    # 主网格第 6 周期不再放镧系 (La-Lu 只在 f 区行)
    for lanthanide in LANTHANIDE_POSITIONS:
        row = PERIODIC_TABLE.get(lanthanide)
        assert row is None or row[0] != 6 or lanthanide not in PERIODIC_TABLE, (
            f"{lanthanide} 不应出现在主网格第 6 周期"
        )


def test_f_block_rows():
    """镧系第 9 行 3..17 列, 锕系第 10 行 3..17 列。"""
    assert LANTHANIDE_POSITIONS["La"] == (9, 3)
    assert LANTHANIDE_POSITIONS["Lu"] == (9, 17)
    assert ACTINIDE_POSITIONS["Ac"] == (10, 3)
    assert ACTINIDE_POSITIONS["Lr"] == (10, 17)


def test_element_names_cover_all():
    missing = set(ALL_POSITIONS) - set(ELEMENT_NAMES)
    assert not missing, f"ELEMENT_NAMES 缺少: {missing}"
    extra = set(ELEMENT_NAMES) - set(ALL_POSITIONS)
    assert not extra, f"ELEMENT_NAMES 多出: {extra}"


def test_widget_builds_118_buttons(qapp):
    from polyxrd.views.widgets.element_periodic_table import ElementPeriodicTable

    widget = ElementPeriodicTable()
    assert len(widget._buttons) == 118
    # 新增元素可交互 (参与元素过滤)
    assert "Po" in widget._buttons and "Og" in widget._buttons
    # 过滤字典可正常产出
    widget.set_selection(has=["Zn", "Po"])
    fd = widget.get_filter_dict()
    assert fd["must"] == ["Zn", "Po"]
    widget.deleteLater()
