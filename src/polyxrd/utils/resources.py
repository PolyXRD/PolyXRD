"""
PolyXRD 资源路径工具
====================
处理在开发环境和 PyInstaller 打包环境下的资源路径解析。
"""
from __future__ import annotations

import sys
from pathlib import Path


def get_resource_path(relative_path: str) -> Path:
    """获取资源文件的绝对路径

    在开发环境中，资源位于 src/polyxrd/resources/ 下。
    在 PyInstaller 打包环境中，资源被解压到 sys._MEIPASS 下。

    Args:
        relative_path: 相对于 resources 目录的路径，如 "app-icon.png"

    Returns:
        资源文件的绝对路径
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base_dir / "polyxrd" / "resources" / relative_path
    else:
        return Path(__file__).resolve().parent.parent / "resources" / relative_path


def get_app_icon_path() -> str:
    """获取**运行时窗口图标**路径。

    v0.13.1: 优先 PNG。Qt6 的 PNG 解码器**内建在 Qt6Gui 里**, 取 PNG 不会加载
    任何 imageformats 插件; 而 ``.ico`` 必须加载 ``qico.dll`` 插件 —— 实测在
    打包版启动阶段 (窗口 ``show()`` 之前) 多加载一个图片插件会显著提高原生
    崩溃概率 (干净 3/3 vs 崩 0/3)。``.ico`` 仍保留给 exe 资源 / 安装器使用
    (``PolyXRD.spec`` 的 ``icon=`` 与 ``Setup.iss`` 的 ``SetupIconFile``),
    那两条路径与 Qt 运行时无关。
    """
    for name in ("app-icon.png", "app-icon.ico"):
        path = get_resource_path(name)
        if path.exists():
            return str(path)
    return ""


def get_splash_screen_path() -> str:
    """获取启动画面路径。

    同上, 优先 PNG (内建解码器, 不加载 ``qjpeg.dll``)。磁盘上的
    ``splash-screen.png`` 已按 480x270 预缩放 —— 原来要先解 2560x1440 的 JPEG
    再 ``SmoothTransformation`` 缩放, 既慢又是启动期最重的一次解码。
    """
    for name in ("splash-screen.png", "splash-screen.jpg"):
        path = get_resource_path(name)
        if path.exists():
            return str(path)
    return ""


def get_hero_banner_path() -> str:
    """获取英雄横幅路径"""
    path = get_resource_path("hero-banner.jpg")
    return str(path) if path.exists() else ""


def get_logo_horizontal_path() -> str:
    """获取水平Logo路径"""
    path = get_resource_path("logo-horizontal.png")
    return str(path) if path.exists() else ""


def get_crystal_mark_path() -> str:
    """获取晶体标志路径"""
    path = get_resource_path("crystal-mark.png")
    return str(path) if path.exists() else ""


def get_icon_path(icon_name: str) -> str:
    """获取图标路径

    Args:
        icon_name: 图标名称，如 "open", "save", "background"

    Returns:
        图标文件的绝对路径，如果不存在则返回空字符串
    """
    for ext in (".svg", ".png", ".ico"):
        path = get_resource_path(f"icons/{icon_name}{ext}")
        if path.exists():
            return str(path)
    return ""


def get_all_icon_names() -> list[str]:
    """获取所有可用图标名称列表"""
    icons_dir = get_resource_path("icons")
    if not icons_dir.exists():
        return []
    names = []
    for f in icons_dir.iterdir():
        if f.suffix in (".svg", ".png", ".ico"):
            names.append(f.stem)
    return sorted(names)
