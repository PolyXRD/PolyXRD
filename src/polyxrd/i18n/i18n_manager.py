"""
国际化管理器
==========
基于单例模式的 I18nManager，支持多语言切换、参数替换和Qt信号。
"""
from __future__ import annotations

import importlib
from enum import Enum
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal


class Language(str, Enum):
    """支持的语言枚举"""

    ZH_CN = "zh_CN"
    EN_US = "en_US"
    JA_JP = "ja_JP"
    DE_DE = "de_DE"
    FR_FR = "fr_FR"
    ES_ES = "es_ES"
    KO_KR = "ko_KR"
    RU_RU = "ru_RU"

    @classmethod
    def display_names(cls) -> dict[str, str]:
        return {
            cls.ZH_CN: "中文",
            cls.EN_US: "English",
            cls.JA_JP: "日本語",
            cls.DE_DE: "Deutsch",
            cls.FR_FR: "Français",
            cls.ES_ES: "Español",
            cls.KO_KR: "한국어",
            cls.RU_RU: "Русский",
        }


class I18nManager(QObject):
    """国际化管理器（单例模式）

    提供多语言翻译、参数替换和Qt语言变化信号。
    翻译键使用点分命名，如 "menu.file.open"。

    Signals:
        languageChanged: 语言变化时发射，携带新语言代码
    """

    languageChanged = Signal(str)

    _instance: Optional[I18nManager] = None
    _initialized: bool = False

    def __new__(cls, *args: Any, **kwargs: Any) -> I18nManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None) -> None:
        if self._initialized:
            return
        super().__init__(parent)
        self._initialized = True
        self._current_language: str = Language.ZH_CN
        self._translations: dict[str, dict] = {}
        self._load_translation(self._current_language)

    @property
    def current_language(self) -> str:
        return self._current_language

    def set_language(self, language: str) -> None:
        if language not in [lang.value for lang in Language]:
            return
        if language == self._current_language:
            return
        self._current_language = language
        self._load_translation(language)
        self.languageChanged.emit(language)

    def tr(self, key: str, **kwargs: Any) -> str:
        """翻译指定键，支持参数替换

        Args:
            key: 点分命名的翻译键，如 "menu.file.open"
            **kwargs: 模板参数，如 tr("greeting.hello", name="World")

        Returns:
            翻译后的字符串，若未找到则返回原始键
        """
        text = self._resolve_key(key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass
        return text

    def _resolve_key(self, key: str) -> str:
        parts = key.split(".")
        node: Any = self._translations
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return key
        return node if isinstance(node, str) else key

    def _load_translation(self, language: str) -> None:
        try:
            module = importlib.import_module(
                f"polyxrd.i18n.translations.{language}"
            )
            self._translations = getattr(module, "translations", {})
        except ImportError:
            self._translations = {}

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        cls._initialized = False


_i18n: Optional[I18nManager] = None


def _ensure_i18n() -> I18nManager:
    global _i18n
    if _i18n is None:
        _i18n = I18nManager()
    return _i18n


def tr(key: str, **kwargs: Any) -> str:
    """全局翻译函数

    Args:
        key: 点分命名的翻译键
        **kwargs: 模板参数

    Returns:
        翻译后的字符串
    """
    return _ensure_i18n().tr(key, **kwargs)