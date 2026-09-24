"""
v0.12.0 元素选择界面顺序调整测试
================================
「必有」在 v0.12.0 被挪到**末位**:
- 单击循环: 无 → 含有 → 可能 → 没有 → 必有 → 无
- 图例显示顺序: 含有 / 可能 / 没有 / 必有
其余语义 (必有=AND、未勾选=没有的闭环) 完全不变。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from polyxrd.i18n import I18nManager
from polyxrd.views.widgets.element_periodic_table import (
    LEGEND_ORDER,
    STATE_CYCLE,
    ElementPeriodicTable,
    ElementState,
    state_label,
)


@pytest.fixture(scope="module", autouse=True)
def _pin_zh_cn():
    """语言钉死为 zh_CN。

    ``state_label()`` 是按**当前语言**解析的 (i18n 重构后不再有模块级
    ``STATE_LABELS`` 常量), 不钉住的话断言结果会随 QSettings 里持久化的
    语言漂移。
    """
    I18nManager().set_language("zh_CN")
    yield


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_state_cycle_puts_must_have_last():
    assert [s.value for s in STATE_CYCLE] == [
        "none", "must", "maybe", "exclude", "must_have",
    ]
    assert STATE_CYCLE[-1] is ElementState.MUST_HAVE


def test_legend_order_puts_must_have_last():
    assert [s.value for s in LEGEND_ORDER] == [
        "must", "maybe", "exclude", "must_have",
    ]
    assert state_label(LEGEND_ORDER[-1]) == "必有"


def test_legend_widgets_rendered_in_new_order(qapp):
    t = ElementPeriodicTable()
    texts = [w.text() for w in t.findChildren(QLabel)]
    # 图例四项按新顺序出现在标签序列里
    order = [state_label(s) for s in LEGEND_ORDER]
    idx = [texts.index(x) for x in order if x in texts]
    assert len(idx) == 4, texts
    assert idx == sorted(idx), f"图例顺序不对: {texts}"


def test_click_cycle_follows_new_order(qapp):
    t = ElementPeriodicTable()
    btn = t._buttons["Si"]
    seq = [btn.state.value]
    for _ in range(5):
        t._on_element_clicked(btn)
        seq.append(btn.state.value)
    assert seq == ["none", "must", "maybe", "exclude", "must_have", "none"]


def test_selection_semantics_unchanged(qapp):
    """四态语义与 get_selection/get_filter_dict 映射保持不变。"""
    t = ElementPeriodicTable()
    t.set_selection(must_have=["Fe"], has=["O"], maybe=["Na"], exclude=["Cl"])
    mh, has, maybe, ex = t.get_selection()
    assert mh == ["Fe"] and has == ["O"] and maybe == ["Na"] and ex == ["Cl"]
    d = t.get_filter_dict()
    assert d["must_have"] == ["Fe"] and d["must"] == ["O"]
    assert d["maybe"] == ["Na"] and d["exclude"] == ["Cl"]
    assert t._buttons["Fe"].state is ElementState.MUST_HAVE
