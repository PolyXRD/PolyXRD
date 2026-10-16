# -*- coding: utf-8 -*-
"""构建变体（flavor）开关 —— 区分「正式发布版」与「内部评估版」。

================================================================================
两种二进制产物
================================================================================
* **正式版（release，默认）**：Inno Setup 安装包。启用注册机制 ——
  每次启动检查注册状态，未注册弹出版权提示；帮助菜单提供「输入注册码」；
  注册后状态栏最右侧展示单位部门名称。
* **内部版（internal）**：单文件 EXE，内部自用。**不含注册机制**
  （不弹提示、不出现「输入注册码」菜单），状态栏最右侧固定显示

      ``内部评估版本``

================================================================================
flavor 如何烧入
================================================================================
flavor 在**构建时**确定，运行时不可切换（防止改配置绕开注册）：

* 内部版构建脚本在调用 PyInstaller **之前**写出 ``polyxrd/_build_flavor.py``::

      BUILD_FLAVOR = "internal"

* 正式版**不写**该文件 —— 缺失即 ``release``。

``src/polyxrd/_build_flavor.py`` 是**构建产物**，不入库：
``.gitignore`` 的 ``_*.py`` 已覆盖 ``__init__.py`` 的放行例外之外的一切
``_*`` 模块，故直接落名字即可，无需额外改 ignore。

之所以用一个「生成模块」而不是环境变量/配置文件，是因为环境变量与外置
json 都能被终端用户改动；把 flavor 编译进字节码（import 型依赖）才能让
分析器把它当作普通模块打包，同时保持源码树干净。
"""
from __future__ import annotations

from typing import Optional

#: 正式发布版（默认）
FLAVOR_RELEASE = "release"

#: 内部评估版
FLAVOR_INTERNAL = "internal"

#: 内部版状态栏文案（按需求固定，不做翻译）
INTERNAL_BUILD_LABEL = "内部评估版本"

_flavor: Optional[str] = None


def _detect() -> str:
    """读取构建时烧入的 flavor；缺失/异常一律按 release（保守：保留注册机制）。"""
    try:
        from polyxrd._build_flavor import BUILD_FLAVOR  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 —— 模块不存在或内容损坏，都走 release
        return FLAVOR_RELEASE
    value = str(BUILD_FLAVOR).strip().lower()
    return value if value in (FLAVOR_RELEASE, FLAVOR_INTERNAL) else FLAVOR_RELEASE


def flavor() -> str:
    """当前构建变体：``"release"`` 或 ``"internal"``（结果缓存）。"""
    global _flavor
    if _flavor is None:
        _flavor = _detect()
    return _flavor


def is_internal() -> bool:
    """是否内部评估版（无注册机制）。"""
    return flavor() == FLAVOR_INTERNAL


def _reset_cache() -> None:
    """清空缓存 —— 仅供测试（单测里 monkeypatch ``_build_flavor`` 后重取）。"""
    global _flavor
    _flavor = None
