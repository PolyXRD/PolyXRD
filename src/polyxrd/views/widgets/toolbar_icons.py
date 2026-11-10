"""matplotlib 导航工具栏图标彩色化。

matplotlib 自带的 NavigationToolbar2QT 图标是单色剪影；本模块用
**矢量源 SVG**（mpl-data/images/*.svg，随 datas 打包）按品牌色系
重新着色渲染，并垫一层同色系浅色圆角底衬，观感更精致。

移植自 XinRefinement（``xinrefinement/gui/toolbar_icons.py``），与谱图
工具行（``plot_icons.py``）同一套设计语言。

- 分辨率无关：QSvgRenderer 渲染，不糊边；
- 每个动作一种家族色；
- 任何一步失败（QtSvg 缺失 / 资源缺失）静默保留原图标，不影响功能。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPixmap

import matplotlib.cbook as cbook

#: 动作名（toolbar._actions 的 callback 键）→ 图标矢量源 + 品牌色
TOOL_COLORS: dict[str, tuple[str, str]] = {
    "home":               ("home.svg",                 "#1f77b4"),  # 蓝
    "back":               ("back.svg",                 "#ff7f0e"),  # 橙
    "forward":            ("forward.svg",              "#2ca02c"),  # 绿
    "pan":                ("move.svg",                 "#9467bd"),  # 紫
    "zoom":               ("zoom_to_rect.svg",         "#17becf"),  # 青
    "configure_subplots": ("subplots.svg",             "#d62728"),  # 红
    "edit_parameters":    ("qt4_editor_options.svg",   "#8c564b"),  # 棕
    "save_figure":        ("filesave.svg",             "#0D285C"),  # 品牌深蓝
}

#: 底衬与图标的绘制尺寸（逻辑像素）
_CHIP = 36
_ICON_INNER = 30      # 图标在底衬内的有效区（SVG 自带少量留白，放大铺满）
_RADIUS = 9.0
_BG_ALPHA = 34        # 底衬透明度（约 13%）


def _render_colored_icon(svg_path: str, hex_color: str,
                         chip: int = _CHIP) -> QPixmap | None:
    """SVG → 彩色圆角底衬图标位图；失败返回 None。"""
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        return None

    color = QColor(hex_color)
    inner = int(round(chip * _ICON_INNER / _CHIP))
    off = (chip - inner) / 2.0
    radius = _RADIUS * chip / _CHIP

    # 1) 底衬：同色系浅色圆角矩形
    img_chip = QImage(chip, chip, QImage.Format.Format_ARGB32_Premultiplied)
    img_chip.fill(Qt.GlobalColor.transparent)
    p = QPainter(img_chip)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = QColor(color)
    bg.setAlpha(_BG_ALPHA)
    p.setBrush(QBrush(bg))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(1.5, 1.5, chip - 3.0, chip - 3.0),
                      radius, radius)

    # 2) 图标：SVG 以 alpha 为掩膜，整体染成目标色后叠加在底衬上
    img = QImage(inner, inner, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p2 = QPainter(img)
    renderer.render(p2, QRectF(0, 0, inner, inner))
    p2.end()
    tinted = QImage(inner, inner, QImage.Format.Format_ARGB32_Premultiplied)
    tinted.fill(color)
    p3 = QPainter(tinted)
    p3.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p3.drawImage(0, 0, img)
    p3.end()
    p.drawImage(QPointF(off, off), tinted)
    p.end()
    return QPixmap.fromImage(img_chip)


def colorize_nav_toolbar(toolbar, chip: int = _CHIP) -> int:
    """给 NavigationToolbar2QT 的各动作换上彩色图标；返回成功数。

    ``chip`` 为图标底衬边长。失败（QtSvg 缺失 / mpl-data 缺 SVG）时保持
    原图标，不抛异常。
    """
    replaced = 0
    size = toolbar.iconSize()
    want = QSize(chip, chip)
    if size.width() < want.width():
        toolbar.setIconSize(QSize(chip - 6, chip - 6))  # 略小于底衬，留白协调
    for callback, (svg_name, hex_color) in TOOL_COLORS.items():
        act = getattr(toolbar, "_actions", {}).get(callback)
        if act is None:
            continue
        try:
            svg_path = str(cbook._get_data_path("images", svg_name))
        except Exception:  # noqa: BLE001
            continue
        pix = _render_colored_icon(svg_path, hex_color, chip=chip)
        if pix is None:
            continue
        act.setIcon(QIcon(pix))
        replaced += 1
    return replaced


__all__ = ["colorize_nav_toolbar", "TOOL_COLORS"]
