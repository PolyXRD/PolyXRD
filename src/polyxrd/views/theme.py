"""
主题 (M20 v2)
=============
浅色 / 深色主题切换。QPalette 构建独立成纯函数, 便于离屏单测。

用法:
    from polyxrd.views.theme import apply_theme
    apply_theme(QApplication.instance(), dark=True)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


# 深色调色板色值 (低饱和小面积强调色, 避免刺眼)
_DARK = {
    "window":        "#2B2B2B",
    "window_text":   "#E8E8E8",
    "base":          "#232323",
    "alt_base":      "#2A2A2A",
    "text":          "#E8E8E8",
    "button":        "#353535",
    "button_text":   "#E8E8E8",
    "highlight":     "#185FA5",
    "highlight_text":"#FFFFFF",
    "tool_tip_base": "#3A3A3A",
    "tool_tip_text": "#E8E8E8",
    "link":          "#5B9BD5",
    "disabled_text": "#6E6E6E",
    "placeholder":   "#8A8A8A",
}

# 浅色调色板 (跟随系统默认观感的显式值, 保证切换后可回退)
_LIGHT = {
    "window":        "#F0F0F0",
    "window_text":   "#1A1A1A",
    "base":          "#FFFFFF",
    "alt_base":      "#F7F7F7",
    "text":          "#1A1A1A",
    "button":        "#F0F0F0",
    "button_text":   "#1A1A1A",
    "highlight":     "#185FA5",
    "highlight_text":"#FFFFFF",
    "tool_tip_base": "#FFFFDC",
    "tool_tip_text": "#1A1A1A",
    "link":          "#185FA5",
    "disabled_text": "#9A9A9A",
    "placeholder":   "#9A9A9A",
}


def build_palette(spec: dict) -> QPalette:
    """按色值规格构建 QPalette (纯函数, 便于测试)。"""
    pal = QPalette()
    c = {k: QColor(v) for k, v in spec.items()}

    pal.setColor(QPalette.ColorRole.Window, c["window"])
    pal.setColor(QPalette.ColorRole.WindowText, c["window_text"])
    pal.setColor(QPalette.ColorRole.Base, c["base"])
    pal.setColor(QPalette.ColorRole.AlternateBase, c["alt_base"])
    pal.setColor(QPalette.ColorRole.Text, c["text"])
    pal.setColor(QPalette.ColorRole.Button, c["button"])
    pal.setColor(QPalette.ColorRole.ButtonText, c["button_text"])
    pal.setColor(QPalette.ColorRole.Highlight, c["highlight"])
    pal.setColor(QPalette.ColorRole.HighlightedText, c["highlight_text"])
    pal.setColor(QPalette.ColorRole.ToolTipBase, c["tool_tip_base"])
    pal.setColor(QPalette.ColorRole.ToolTipText, c["tool_tip_text"])
    pal.setColor(QPalette.ColorRole.Link, c["link"])
    pal.setColor(QPalette.ColorRole.PlaceholderText, c["placeholder"])
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                 c["disabled_text"])
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText,
                 c["disabled_text"])
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
                 c["disabled_text"])
    return pal


def build_dark_palette() -> QPalette:
    return build_palette(_DARK)


def build_light_palette() -> QPalette:
    return build_palette(_LIGHT)


def apply_theme(app: Optional[QApplication], dark: bool) -> None:
    """把主题应用到 QApplication; app 为 None 时静默返回 (便于单测)。"""
    if app is None:
        return
    app.setStyle("Fusion")  # 两个平台下观感一致, 且 palette 生效最彻底
    app.setPalette(build_dark_palette() if dark else build_light_palette())
