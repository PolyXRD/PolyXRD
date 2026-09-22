"""
元素周期表控件
==============
交互式元素周期表，支持四态选择 (0.9.11)：
- 含有 (绿色): 物相由这些元素构成，至少含其中一个
- 可能 (黄色): 允许出现但不要求，只放宽候选元素池
- 没有 (红色): 物相含任一这些元素即被淘汰
- 必有 (深绿): 物相必须**全部**含有这些元素 (AND) —— v0.12.0 把它挪到末位

**未勾选的元素默认等于「没有」** (闭环)，仅在 必有/含有/可能 至少勾中
一项时生效；三者全空 = 全库搜索，只勾「没有」= 开放世界。
单击元素循环 (v0.12.0 起「必有」置于末位):
    无 → 含有 → 可能 → 没有 → 必有 → 无。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QGridLayout,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QToolTip,
)

from polyxrd.i18n import tr
from polyxrd.utils.formula_parser import LIGHT_ELEMENTS


class ElementState(Enum):
    NONE = "none"
    MUST_HAVE = "must_have"
    MUST = "must"
    MAYBE = "maybe"
    EXCLUDE = "exclude"


STATE_COLORS = {
    ElementState.NONE: QColor(240, 240, 240),
    ElementState.MUST_HAVE: QColor(27, 94, 32),    # 深绿 (必有, AND)
    ElementState.MUST: QColor(76, 175, 80),        # 绿色 (含有)
    ElementState.MAYBE: QColor(255, 193, 7),       # 黄色 (可能)
    ElementState.EXCLUDE: QColor(244, 67, 54),     # 红色 (没有)
}

STATE_TEXT_COLORS = {
    ElementState.NONE: QColor(80, 80, 80),
    ElementState.MUST_HAVE: QColor(255, 255, 255),
    ElementState.MUST: QColor(255, 255, 255),
    ElementState.MAYBE: QColor(80, 60, 0),
    ElementState.EXCLUDE: QColor(255, 255, 255),
}

STATE_HEX = {
    ElementState.NONE: "#f0f0f0",
    ElementState.MUST_HAVE: "#1b5e20",
    ElementState.MUST: "#4caf50",
    ElementState.MAYBE: "#ffc107",
    ElementState.EXCLUDE: "#f44336",
}

# 状态文案 / 提示都是语言相关的, 因此不能在模块层求值 (否则永久定格在
# 导入时的语言) —— 统一在 state_label() / state_tip() 里按当前语言解析。
_STATE_LABEL_KEYS = {
    ElementState.MUST_HAVE: "vw.element_periodic_table.state_must_have",
    ElementState.MUST: "vw.element_periodic_table.state_must",
    ElementState.MAYBE: "vw.element_periodic_table.state_maybe",
    ElementState.EXCLUDE: "vw.element_periodic_table.state_exclude",
}

_STATE_TIP_KEYS = {
    ElementState.MUST_HAVE: "vw.element_periodic_table.tip_must_have",
    ElementState.MUST: "vw.element_periodic_table.tip_must",
    ElementState.MAYBE: "vw.element_periodic_table.tip_maybe",
    ElementState.EXCLUDE: "vw.element_periodic_table.tip_exclude",
}


def state_label(state: "ElementState") -> str:
    """图例文字 (按当前语言解析)。"""
    key = _STATE_LABEL_KEYS.get(state)
    return tr(key) if key else ""


def state_tip(state: "ElementState") -> str:
    """状态提示; 未选中的中性态用 tip_default。"""
    key = _STATE_TIP_KEYS.get(state, "vw.element_periodic_table.tip_default")
    return tr(key)


def element_name(symbol: str) -> str:
    """元素本地化名称; 缺键时回退元素符号。"""
    key = f"elem.{symbol}"
    val = tr(key)
    return symbol if val == key else val

# 单击循环顺序 (v0.12.0: 「必有」放到最后)
STATE_CYCLE = (
    ElementState.NONE,
    ElementState.MUST,
    ElementState.MAYBE,
    ElementState.EXCLUDE,
    ElementState.MUST_HAVE,
)

# 图例显示顺序 (v0.12.0: 「必有」放到最后)
LEGEND_ORDER = (
    ElementState.MUST,
    ElementState.MAYBE,
    ElementState.EXCLUDE,
    ElementState.MUST_HAVE,
)


# (row, col) positions in 18-column grid
PERIODIC_TABLE = {
    "H":  (1, 1), "He": (1, 18),
    "Li": (2, 1), "Be": (2, 2), "B":  (2, 13), "C":  (2, 14),
    "N":  (2, 15), "O":  (2, 16), "F":  (2, 17), "Ne": (2, 18),
    "Na": (3, 1), "Mg": (3, 2), "Al": (3, 13), "Si": (3, 14),
    "P":  (3, 15), "S":  (3, 16), "Cl": (3, 17), "Ar": (3, 18),
    "K":  (4, 1), "Ca": (4, 2), "Sc": (4, 3), "Ti": (4, 4),
    "V":  (4, 5), "Cr": (4, 6), "Mn": (4, 7), "Fe": (4, 8),
    "Co": (4, 9), "Ni": (4, 10), "Cu": (4, 11), "Zn": (4, 12),
    "Ga": (4, 13), "Ge": (4, 14), "As": (4, 15), "Se": (4, 16),
    "Br": (4, 17), "Kr": (4, 18),
    "Rb": (5, 1), "Sr": (5, 2), "Y":  (5, 3), "Zr": (5, 4),
    "Nb": (5, 5), "Mo": (5, 6), "Tc": (5, 7), "Ru": (5, 8),
    "Rh": (5, 9), "Pd": (5, 10), "Ag": (5, 11), "Cd": (5, 12),
    "In": (5, 13), "Sn": (5, 14), "Sb": (5, 15), "Te": (5, 16),
    "I":  (5, 17), "Xe": (5, 18),
    "Cs": (6, 1), "Ba": (6, 2), "La": (6, 3), "Ce": (6, 4),
    "Pr": (6, 5), "Nd": (6, 6), "Pm": (6, 7), "Sm": (6, 8),
    "Eu": (6, 9), "Gd": (6, 10), "Tb": (6, 11), "Dy": (6, 12),
    "Ho": (6, 13), "Er": (6, 14), "Tm": (6, 15), "Yb": (6, 16),
    "Lu": (6, 17), "Hf": (6, 18), "Ta": (6, 3), "W":  (6, 4),
    "Re": (6, 5), "Os": (6, 6), "Ir": (6, 7), "Pt": (6, 8),
    "Au": (6, 9), "Hg": (6, 10), "Tl": (6, 11), "Pb": (6, 12),
    "Bi": (6, 13), "Pa": (6, 14), "U":  (6, 15),
    "Fr": (7, 1), "Ra": (7, 2), "Ac": (7, 3), "Th": (7, 4),
    "Pa": (7, 5), "U":  (7, 6), "Np": (7, 7), "Pu": (7, 8),
}

# Lanthanide/Actinide rows (rows 9 and 10)
LANTHANIDE_POSITIONS = {
    "La":  (9, 3), "Ce": (9, 4), "Pr": (9, 5), "Nd": (9, 6),
    "Pm":  (9, 7), "Sm": (9, 8), "Eu": (9, 9), "Gd": (9, 10),
    "Tb":  (9, 11), "Dy": (9, 12), "Ho": (9, 13), "Er": (9, 14),
    "Tm":  (9, 15), "Yb": (9, 16), "Lu": (9, 17),
}

ACTINIDE_POSITIONS = {
    "Ac": (10, 3), "Th": (10, 4), "Pa": (10, 5), "U": (10, 6),
    "Np": (10, 7), "Pu": (10, 8), "Am": (10, 9), "Cm": (10, 10),
    "Bk": (10, 11), "Cf": (10, 12), "Es": (10, 13), "Fm": (10, 14),
    "Md": (10, 15), "No": (10, 16), "Lr": (10, 17),
}

ELEMENT_NAMES = {
    "H": "氢", "He": "氦", "Li": "锂", "Be": "铍", "B": "硼",
    "C": "碳", "N": "氮", "O": "氧", "F": "氟", "Ne": "氖",
    "Na": "钠", "Mg": "镁", "Al": "铝", "Si": "硅", "P": "磷",
    "S": "硫", "Cl": "氯", "Ar": "氩", "K": "钾", "Ca": "钙",
    "Sc": "钪", "Ti": "钛", "V": "钒", "Cr": "铬", "Mn": "锰",
    "Fe": "铁", "Co": "钴", "Ni": "镍", "Cu": "铜", "Zn": "锌",
    "Ga": "镓", "Ge": "锗", "As": "砷", "Se": "硒", "Br": "溴",
    "Kr": "氪", "Rb": "铷", "Sr": "锶", "Y": "钇", "Zr": "锆",
    "Nb": "铌", "Mo": "钼", "Tc": "锝", "Ru": "钌", "Rh": "铑",
    "Pd": "钯", "Ag": "银", "Cd": "镉", "In": "铟", "Sn": "锡",
    "Sb": "锑", "Te": "碲", "I": "碘", "Xe": "氙", "Cs": "铯",
    "Ba": "钡", "La": "镧", "Ce": "铈", "Pr": "镨", "Nd": "钕",
    "Pm": "钷", "Sm": "钐", "Eu": "铕", "Gd": "钆", "Tb": "铽",
    "Dy": "镝", "Ho": "钬", "Er": "铒", "Tm": "铥", "Yb": "镱",
    "Lu": "镥", "Hf": "铪", "Ta": "钽", "W": "钨", "Re": "铼",
    "Os": "锇", "Ir": "铱", "Pt": "铂", "Au": "金", "Hg": "汞",
    "Tl": "铊", "Pb": "铅", "Bi": "铋", "Pa": "镤", "U": "铀",
    "Fr": "钫", "Ra": "镭", "Ac": "锕", "Th": "钍", "Np": "镎",
    "Pu": "钚", "Am": "镅", "Cm": "锔", "Bk": "锫", "Cf": "锎",
    "Es": "锿", "Fm": "镄", "Md": "钔", "No": "锘", "Lr": "铹",
}

# Merge all positions
ALL_POSITIONS = {}
for table in [PERIODIC_TABLE, LANTHANIDE_POSITIONS, ACTINIDE_POSITIONS]:
    for elem, pos in table.items():
        ALL_POSITIONS[elem] = pos


class ElementButton(QPushButton):
    """单个元素按钮，支持四态切换 (无 → 含有 → 可能 → 没有 → 必有)"""

    def __init__(self, element: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._element = element
        self._state = ElementState.NONE
        self.setFixedSize(QSize(36, 36))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(element)
        self._update_style()
        self._update_tooltip()

    @property
    def element(self) -> str:
        return self._element

    @property
    def state(self) -> ElementState:
        return self._state

    def cycle_state(self) -> ElementState:
        idx = STATE_CYCLE.index(self._state)
        self._state = STATE_CYCLE[(idx + 1) % len(STATE_CYCLE)]
        self._update_style()
        self._update_tooltip()
        return self._state

    def set_state(self, state: ElementState) -> None:
        self._state = state
        self._update_style()
        self._update_tooltip()

    def reset(self) -> None:
        self._state = ElementState.NONE
        self._update_style()
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        name = element_name(self._element)
        tip = state_tip(self._state)
        # 名称回退成符号时不要再拼一次, 免得出现 "H (H)"
        head = self._element if name == self._element else f"{name} ({self._element})"
        self.setToolTip(f"{head}\n{tip}")

    def _update_style(self) -> None:
        bg = STATE_HEX[self._state]
        fg = STATE_TEXT_COLORS[self._state].name()
        border = "#bdbdbd" if self._state == ElementState.NONE else "#616161"
        self.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {bg};"
            f"  color: {fg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 4px;"
            f"  font-size: 10px;"
            f"  font-weight: bold;"
            f"  padding: 0px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border: 2px solid #1976d2;"
            f"}}"
        )


class ElementPeriodicTable(QWidget):
    """元素周期表控件 (四态)

    发出信号:
        selection_changed: 选择状态变更
            (must_have_elements, has_elements, maybe_elements, exclude_elements)
    """

    selection_changed = Signal(list, list, list, list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._buttons: dict[str, ElementButton] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 图例 (v0.12.0: 「必有」置于最后)
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(8)
        for state in LEGEND_ORDER:
            legend_layout.addWidget(self._make_legend_item(state))
        legend_layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        self._btn_light = QPushButton(tr("vw.element_periodic_table.btn_light"))
        self._btn_light.setFixedHeight(24)
        self._btn_light.setToolTip(tr("vw.element_periodic_table.btn_light_tip"))
        self._btn_light.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; }"
        )
        self._btn_light.clicked.connect(self.apply_light_elements)
        btn_layout.addWidget(self._btn_light)

        self._btn_reset = QPushButton(tr("vw.element_periodic_table.btn_reset"))
        self._btn_reset.setFixedHeight(24)
        self._btn_reset.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; }"
        )
        self._btn_reset.clicked.connect(self.reset_all)
        btn_layout.addWidget(self._btn_reset)
        legend_layout.addLayout(btn_layout)

        layout.addLayout(legend_layout)

        # 周期表网格
        grid = QGridLayout()
        grid.setSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)

        for element, (row, col) in ALL_POSITIONS.items():
            btn = ElementButton(element)
            btn.clicked.connect(lambda checked, b=btn: self._on_element_clicked(b))
            self._buttons[element] = btn
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)

        # 状态标签
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #666; padding: 2px; }"
        )
        layout.addWidget(self._status_label)

    def _make_legend_item(self, state: ElementState) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        color_box = QFrame()
        color_box.setFixedSize(16, 16)
        color_box.setStyleSheet(
            f"QFrame {{ background-color: {STATE_HEX[state]}; border: 1px solid #999; border-radius: 3px; }}"
        )

        label = QLabel(state_label(state))
        label.setStyleSheet("QLabel { font-size: 11px; }")
        label.setToolTip(state_tip(state))

        layout.addWidget(color_box)
        layout.addWidget(label)
        return widget

    def _on_element_clicked(self, button: ElementButton) -> None:
        button.cycle_state()
        self._update_status()
        self._emit_selection()

    def apply_light_elements(self) -> None:
        """一键把轻元素 (O,C,H,N,S) 设为「含有」(不覆盖已选中的元素)"""
        for elem in LIGHT_ELEMENTS:
            btn = self._buttons.get(elem)
            if btn is not None and btn.state == ElementState.NONE:
                btn.set_state(ElementState.MUST)
        self._update_status()
        self._emit_selection()

    def _update_status(self) -> None:
        must_have, has, maybe, exclude = self.get_selection()
        parts = []
        if must_have:
            parts.append(tr("vw.element_periodic_table.status_must_have", items=', '.join(must_have)))
        if has:
            parts.append(tr("vw.element_periodic_table.status_must", items=', '.join(has)))
        if maybe:
            parts.append(tr("vw.element_periodic_table.status_maybe", items=', '.join(maybe)))
        if exclude:
            parts.append(tr("vw.element_periodic_table.status_exclude", items=', '.join(exclude)))

        if not parts:
            self._status_label.setText(tr("vw.element_periodic_table.status_none"))
            return

        text = " | ".join(parts)
        if must_have or has or maybe:
            # 闭环: 未勾选元素一律视为「没有」
            excluded = sorted(set(ALL_POSITIONS) - set(must_have) - set(has) - set(maybe))
            preview = ", ".join(excluded[:12]) + ("…" if len(excluded) > 12 else "")
            text += tr("vw.element_periodic_table.status_excluded",
                       count=len(excluded), preview=preview)
        self._status_label.setText(text)

    def _emit_selection(self) -> None:
        must_have, has, maybe, exclude = self.get_selection()
        self.selection_changed.emit(must_have, has, maybe, exclude)

    def get_selection(self) -> tuple[list[str], list[str], list[str], list[str]]:
        """获取当前选择状态

        Returns:
            (must_have_elements, has_elements, maybe_elements, exclude_elements)
        """
        must_have: list[str] = []
        has: list[str] = []
        maybe: list[str] = []
        exclude: list[str] = []
        for elem, btn in self._buttons.items():
            if btn.state == ElementState.MUST_HAVE:
                must_have.append(elem)
            elif btn.state == ElementState.MUST:
                has.append(elem)
            elif btn.state == ElementState.MAYBE:
                maybe.append(elem)
            elif btn.state == ElementState.EXCLUDE:
                exclude.append(elem)
        return must_have, has, maybe, exclude

    def set_selection(
        self,
        must_have: Optional[list[str]] = None,
        has: Optional[list[str]] = None,
        maybe: Optional[list[str]] = None,
        exclude: Optional[list[str]] = None,
    ) -> None:
        """设置选择状态"""
        self.reset_all(silent=True)
        for e in (must_have or []):
            if e in self._buttons:
                self._buttons[e].set_state(ElementState.MUST_HAVE)
        for e in (has or []):
            if e in self._buttons:
                self._buttons[e].set_state(ElementState.MUST)
        for e in (maybe or []):
            if e in self._buttons:
                self._buttons[e].set_state(ElementState.MAYBE)
        for e in (exclude or []):
            if e in self._buttons:
                self._buttons[e].set_state(ElementState.EXCLUDE)
        self._update_status()

    def reset_all(self, silent: bool = False) -> None:
        """重置所有元素"""
        for btn in self._buttons.values():
            btn.reset()
        self._update_status()
        if not silent:
            self._emit_selection()

    def get_filter_dict(self) -> dict:
        """获取过滤条件字典，方便传递给识别服务

        Returns:
            {"must_have": [...], "must": [...], "maybe": [...], "exclude": [...]}
        """
        must_have, has, maybe, exclude = self.get_selection()
        return {
            "must_have": must_have,
            "must": has,
            "maybe": maybe,
            "exclude": exclude,
        }