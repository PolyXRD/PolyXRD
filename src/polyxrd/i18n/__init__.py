"""
PolyXRD 国际化框架
==================
提供多语言翻译支持，默认使用简体中文。

Usage::

    from polyxrd.i18n import I18nManager, tr, Language

    # 获取翻译
    text = tr("menu.file.open")

    # 切换语言
    I18nManager().set_language(Language.EN_US)

    # 监听语言变化
    manager = I18nManager()
    manager.languageChanged.connect(lambda lang: print(f"Language changed to: {lang}"))

    # 参数替换
    text = tr("status.loading_file", path="/data/sample.xy")
"""
from __future__ import annotations

from polyxrd.i18n.i18n_manager import I18nManager, Language, tr

__all__ = ["I18nManager", "Language", "tr"]