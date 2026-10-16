#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建变体（flavor）烧制工具 —— 在调用 PyInstaller **之前**跑。

================================================================================
用法
================================================================================
    python scripts/set_build_flavor.py internal   # 烧成内部评估版
    python scripts/set_build_flavor.py release    # 回到正式发布版（默认）
    python scripts/set_build_flavor.py show       # 看当前状态

================================================================================
为什么是「生成一个模块」而不是环境变量 / 配置文件
================================================================================
环境变量与外部 json 都能被终端用户改动 —— 用它们区分版本，等于把「内部版不弹注册
提示」这个开关暴露给使用者。把 flavor 编成一个**普通 Python 模块**，它就会被当作
常规依赖打进包里，运行时不可切换，且源码树保持干净。

``src/polyxrd/_build_flavor.py`` 是**构建产物**：已被 ``.gitignore`` 的
``_*.py`` 规则覆盖，永远不会入库（已用 ``git check-ignore`` 验证）。

================================================================================
⚠️ 配套要求
================================================================================
``PolyXRD.spec`` 必须检测到该文件后把 ``polyxrd._build_flavor`` 加进
``hiddenimports``。因为 ``build_flavor._detect()`` 是在 ``try/except`` 里动态
import 的，单靠 PyInstaller 的静态分析**有可能漏收集** —— 一旦漏掉，内部版会
静默退化成正式版（开始弹注册提示），且极难察觉。spec 里已有对应兜底。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGET = _REPO_ROOT / "src" / "polyxrd" / "_build_flavor.py"

#: 写进生成模块的模板
_TEMPLATE = '''# -*- coding: utf-8 -*-
"""构建期烧入的版本变体 —— **自动生成，勿手工修改，勿入库**。

由 ``scripts/set_build_flavor.py internal`` 生成；改回正式版请跑
``python scripts/set_build_flavor.py release``（该文件会被删除，
缺失即 release）。
"""

BUILD_FLAVOR = "{flavor}"
'''


def apply_flavor(flavor: str) -> str:
    """写入/清除 flavor 标记文件，返回当前生效的 flavor。"""
    if flavor == "release":
        # 正式版 = 标记文件不存在（缺失时 _detect() 回落到 release）
        if _TARGET.exists():
            _TARGET.unlink()
        return "release"
    _TARGET.parent.mkdir(parents=True, exist_ok=True)
    _TARGET.write_text(_TEMPLATE.format(flavor=flavor), encoding="utf-8")
    return flavor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="set_build_flavor",
        description="PolyXRD 构建变体烧制（PyInstaller 之前调用）",
    )
    parser.add_argument(
        "flavor",
        nargs="?",
        default="show",
        choices=["release", "internal", "show"],
        help="release=正式发布版（带注册）/ internal=内部评估版（无注册）/ show=查看当前",
    )
    args = parser.parse_args(argv)

    if args.flavor == "show":
        current = "release"
        if _TARGET.exists():
            # 从文件内容读，避免与预期不一致时误判
            text = _TARGET.read_text(encoding="utf-8")
            for candidate in ("internal", "release"):
                if f'"{candidate}"' in text:
                    current = candidate
                    break
        print(f"[flavor] current = {current}  (marker exists: {_TARGET.exists()})")
        return 0

    result = apply_flavor(args.flavor)
    location = "none (falls back to release)" if not _TARGET.exists() else str(_TARGET)
    print(f"[flavor] set -> {result}")
    print(f"[flavor] marker: {location}")
    if result == "internal":
        print("[flavor] 该构建将: 不显示注册 UI、不弹未注册提示、状态栏右端显示「内部评估版本」")
    else:
        print("[flavor] 该构建将: 启用注册机制（未注册每次启动提示版权信息）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
