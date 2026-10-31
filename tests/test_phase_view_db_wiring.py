"""v4.6.0: 工具栏/菜单入口必须与物相页数据源下拉使用同一个库。
============================================================

用户反馈的核心场景：在物相页把数据源切成某份外挂库，再从**工具栏**点「识别」，
结果却来自内置 118 相库 —— 两个入口各走各的，且没有任何提示。
本文件钉住三条接线：

1. MainWindow._on_identify 传当前 db_source + 元素过滤；
2. MainWindow._on_profile_fitting 传当前 db_source + 元素过滤；
3. 物相页数据源行的「管理数据库…」按钮只发信号（不自己 new 对话框），
   主窗口收到后才打开管理界面。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.config import get_config
from polyxrd.views.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="module")
def window(qapp):
    win = MainWindow(get_config())
    yield win
    win.close()


def test_toolbar_identify_uses_selected_source(window, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(window._vm, "identify_phases",
                        lambda **kw: captured.update(kw))
    monkeypatch.setattr(window._phase_view, "current_db_source",
                        lambda: "polydb:deadbeef")
    monkeypatch.setattr(window._phase_view, "current_element_filter",
                        lambda: {"must": ["Al"]})
    window._on_identify()
    assert captured["db_source"] == "polydb:deadbeef"
    assert captured["element_filter"] == {"must": ["Al"]}


def test_toolbar_profile_fitting_uses_selected_source(window, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(window._vm, "identify_phases_profile_fitting",
                        lambda **kw: captured.update(kw))
    monkeypatch.setattr(window._phase_view, "current_db_source",
                        lambda: "pdf2:cafe")
    monkeypatch.setattr(window._phase_view, "current_element_filter",
                        lambda: {})
    window._on_profile_fitting()
    assert captured["db_source"] == "pdf2:cafe"
    assert captured["element_filter"] is None


def test_manage_button_emits_signal_only(window):
    pv = window._phase_view
    pv.request_db_manager.disconnect()
    got: list[int] = []
    pv.request_db_manager.connect(lambda: got.append(1))
    pv._btn_manage_db.click()
    assert got == [1]
