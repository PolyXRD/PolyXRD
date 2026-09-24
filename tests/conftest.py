# -*- coding: utf-8 -*-
"""pytest 全局夹具 —— 让测试与「语言环境状态」彻底解耦。

**为什么需要这个文件**

`I18nManager` 是进程级单例，而 `MainWindow.__init__` 会调用
`_apply_persisted_language()`，用 `QSettings` 里**持久化的 `language`** 覆盖当前语言。
于是同一个用例，结论会随"机器状态"和"跑法"变化：

- 单跑某个文件 → 注册表里是 `zh_CN` → 断言中文字面量 → 绿；
- 跑整套 → 前序用例 / 注册表残留把语言带到别的语种 → 同一条断言变红。

这类"红/绿取决于先跑了什么"的测试毫无价值，必须消除。同时，测试也**不应该**读写
开发者真机上的 `HKCU\\Software\\PolyXRD\\PolyXRD` —— 实测发生过一次 ja_JP 冒烟把
注册表语言写成日文，双击启动后界面直接变日文。

因此这里每个用例：
1. 把 `QSettings` 的 `language` 键读**和**写都变成空操作（不碰真机注册表）；
2. 强制 `I18nManager` 回 `zh_CN`，用例结束后还原。

⚠️ `QSettings.setDefaultFormat(IniFormat)` + `setPath(...)` 在 Windows 上**拦不住**
`QSettings(org, app)` —— 它照样读 Native 注册表。所以只能像上面那样在类上猴补方法。
"""
from __future__ import annotations

import pytest

_LANGUAGE_KEY = "language"


@pytest.fixture(autouse=True)
def _pin_language_zh_cn(monkeypatch):
    """把界面语言钉死为 zh_CN，并隔离 QSettings 里的语言读写。"""
    from PySide6.QtCore import QSettings

    from polyxrd.i18n import I18nManager

    real_value = QSettings.value
    real_set_value = QSettings.setValue

    def _value(self, key, default=None, *args, **kwargs):
        if key == _LANGUAGE_KEY:
            # 返回假值 → MainWindow._apply_persisted_language 不会覆盖语言
            return ""
        return real_value(self, key, default, *args, **kwargs)

    def _set_value(self, key, value, *args, **kwargs):
        if key == _LANGUAGE_KEY:
            return None  # 测试不改动真机注册表
        return real_set_value(self, key, value, *args, **kwargs)

    monkeypatch.setattr(QSettings, "value", _value)
    monkeypatch.setattr(QSettings, "setValue", _set_value)

    manager = I18nManager()
    previous = manager.current_language
    manager.set_language("zh_CN")
    try:
        yield
    finally:
        manager.set_language(previous)
