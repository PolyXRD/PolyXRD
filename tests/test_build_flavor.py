"""内部评估版徽标 + 构建变体判别 (v4.1.0)
=========================================

用户明确要求: 便携版（内部评估版）**在最下方状态栏用红色加粗显示「内部评估版本」**。
本文件钉住两件事:

1. **flavor 判别** —— 构建时烧入 ``polyxrd/_build_flavor.py``, 缺失/写错一律按
   正式版（保守: 保留注册机制, 不能因为文件坏了就白送一份免注册版）;
2. **徽标样式** —— 文案固定不翻译、红色 ``#d32f2f``、``font-weight: bold``,
   tooltip 三语齐全 (缺键会把原始键名显示给用户)。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.utils import build_flavor                    # noqa: E402
from polyxrd.utils.build_flavor import (                  # noqa: E402
    FLAVOR_INTERNAL,
    FLAVOR_RELEASE,
    INTERNAL_BUILD_LABEL,
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def flavor_mod(monkeypatch):
    """注入一个假的 ``polyxrd._build_flavor`` 模块, 返回设值的函数。"""
    fake = types.ModuleType("polyxrd._build_flavor")

    def _set(value) -> None:
        fake.BUILD_FLAVOR = value
        # 让 ``from polyxrd._build_flavor import BUILD_FLAVOR`` 命中假模块
        monkeypatch.setitem(sys.modules, "polyxrd._build_flavor", fake)
        build_flavor._reset_cache()

    yield _set
    build_flavor._reset_cache()


# ── 1. flavor 判别 ──────────────────────────────────────────

def test_default_is_release(monkeypatch):
    """没有构建标记文件 = 正式版。"""
    monkeypatch.setitem(sys.modules, "polyxrd._build_flavor", None)
    build_flavor._reset_cache()
    assert build_flavor.flavor() == FLAVOR_RELEASE
    assert build_flavor.is_internal() is False


def test_internal_marker_is_honoured(flavor_mod):
    flavor_mod(FLAVOR_INTERNAL)
    assert build_flavor.flavor() == FLAVOR_INTERNAL
    assert build_flavor.is_internal() is True


def test_marker_is_case_and_space_insensitive(flavor_mod):
    flavor_mod("  Internal ")
    assert build_flavor.is_internal() is True


def test_bogus_marker_falls_back_to_release(flavor_mod):
    """写错的值必须落回正式版 —— 不能因为一个错字白送免注册版。"""
    for bad in ("", "internl", "trial", 123):
        flavor_mod(bad)
        assert build_flavor.flavor() == FLAVOR_RELEASE, bad


def test_flavor_is_cached(flavor_mod):
    flavor_mod(FLAVOR_INTERNAL)
    assert build_flavor.is_internal() is True
    # 缓存后即使底层模块变了也不再重算 (运行期不可切换, 防绕过注册)
    flavor_mod(FLAVOR_RELEASE)
    build_flavor._reset_cache()
    assert build_flavor.is_internal() is False


# ── 2. 徽标 ─────────────────────────────────────────────────

def test_label_text_is_exact(qapp):
    from polyxrd.views.widgets.edition_badge import internal_badge_label

    assert INTERNAL_BUILD_LABEL == "内部评估版本"
    assert internal_badge_label().text() == "内部评估版本"


def test_label_is_red_and_bold(qapp):
    from polyxrd.views.widgets.edition_badge import internal_badge_label

    css = internal_badge_label().styleSheet()
    assert "#d32f2f" in css, css
    assert "font-weight: bold" in css, css


def test_label_tooltip_resolves_in_all_languages(qapp):
    from polyxrd.i18n import I18nManager, Language
    from polyxrd.i18n.translations import en_US, ja_JP, zh_CN
    from polyxrd.views.widgets.edition_badge import internal_badge_label

    mgr = I18nManager()
    old = mgr.current_language
    try:
        for lang, mod in ((Language.ZH_CN, zh_CN), (Language.EN_US, en_US),
                          (Language.JA_JP, ja_JP)):
            mgr.set_language(lang)
            tip = internal_badge_label().toolTip()
            assert tip and not tip.startswith("status."), f"{mod.__name__}: {tip}"
            node = mod.translations
            for part in ("status", "internal_tooltip"):
                node = node[part]
            assert tip == str(node), (mod.__name__, tip, node)
    finally:
        mgr.set_language(old)


def test_label_object_name_is_stable(qapp):
    """QSS / 自动化脚本按 objectName 找这个标签, 名字不能随手改。"""
    from polyxrd.views.widgets.edition_badge import internal_badge_label

    assert internal_badge_label().objectName() == "editionStatusLabel"
