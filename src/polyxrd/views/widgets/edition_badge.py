# -*- coding: utf-8 -*-
"""状态栏「内部评估版本」徽标（v4.1.0）。

内部评估版不带注册机制，状态栏最右侧固定显示这四个字。样式要求（用户明确）：
**红色 + 加粗**。

为什么单独一个模块而不是写死在 ``main_window`` 里：徽标要在**没有注册机制**的
构建里也能被单测覆盖，而 ``MainWindow`` 一构造就会装配四个页签 + 后台线程，
在 CI 里代价过高。这里只做"造一个 QLabel"这件小事。

样式用**控件自带 stylesheet** 而不是全局 QSS：状态栏在切主题时会被整体重刷，
挂在控件上的规则优先级更高，换主题也不会掉色。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from polyxrd.i18n import tr
from polyxrd.utils.build_flavor import INTERNAL_BUILD_LABEL

#: 红色取自 Material Red 700（白底/深色底都能看清，且与告警色区分开）。
INTERNAL_BADGE_CSS = "color: #d32f2f; font-weight: bold; padding: 0 6px;"


def internal_badge_label(parent: QWidget | None = None) -> QLabel:
    """造一个内部版徽标（文字固定、红色加粗、带说明 tooltip）。"""
    label = QLabel(INTERNAL_BUILD_LABEL, parent)
    label.setObjectName("editionStatusLabel")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setToolTip(tr("status.internal_tooltip"))
    label.setStyleSheet(INTERNAL_BADGE_CSS)
    return label
