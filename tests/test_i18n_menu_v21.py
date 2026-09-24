"""v2.1 P2-5: 语言菜单与实际可用语言对齐。

背景 (docs/代码评估与改进计划.md §五 P2-5): 菜单暴露 9 种语言但只有 3 种
有翻译文件, 选中其余 6 种后界面回退中文而菜单仍勾选 —— 宣称与实现不符。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.i18n.i18n_manager import Language


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_available_languages_match_translation_files():
    avail = Language.available_languages()
    assert {l.value for l in avail} == {"zh_CN", "en_US", "ja_JP"}


def test_language_menu_only_lists_available(qapp):
    from polyxrd.views.main_window import MainWindow
    from polyxrd.config import get_config

    win = MainWindow(get_config())
    actions = win._language_actions
    assert set(actions.keys()) == {"zh_CN", "en_US", "ja_JP"}
    win.close()
