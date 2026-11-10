"""谱图操作行：一排直接作用于谱图的彩色图标按钮。

移植自 XinRefinement（``xinrefinement/gui/plot_tools.py``），与导航工具条
分工一致：

- **导航工具条**（上方）= 图形级操作（回退/前进、平移、框选、保存）；
- **谱图操作行**（紧贴谱图上方）= 针对衍射谱的常用动作（复位、按轴框选、
  平移、步进缩放、十字线读数）。

按钮 → 动作（动作实现由宿主 ``PlotWidget`` 提供）：

============  ==================================================
按钮          动作
============  ==================================================
reset         恢复默认视场（横轴全量 + 纵轴贴合）
zoom_x        拖出角度区间，只改横轴
zoom_y        拖出强度区间，只改纵轴
zoom_rect     拖出矩形，横纵轴一起改
pan_left      视场左移 25%
pan_right     视场右移 25%
zoom_in       以视场中心步进放大
zoom_out      以视场中心步进缩小
crosshair     红色竖线跟随鼠标，状态提示报角度与强度
============  ==================================================
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from polyxrd.i18n import tr
from polyxrd.views.widgets.plot_icons import plot_icon

#: 按钮顺序（分组之间插分隔线）
TOOL_GROUPS: tuple[tuple[str, ...], ...] = (
    ("reset",),
    ("zoom_x", "zoom_y", "zoom_rect"),
    ("pan_left", "pan_right"),
    ("zoom_in", "zoom_out"),
    ("crosshair",),
)

#: 可保持选中状态的工具（其余是「点一下就执行」的瞬时按钮）
MODE_TOOLS = ("zoom_x", "zoom_y", "zoom_rect", "crosshair")

#: 平移步长（视场宽度的比例）与缩放系数
PAN_FRAC = 0.25
ZOOM_STEP = 0.8          # <1 为放大

_ICON_PX = 22


class PlotToolBar(QWidget):
    """谱图操作按钮行（贴着谱图上方显示）。

    ``host`` 需提供：``set_plot_tool(tool)`` / ``reset_view()`` /
    ``pan_x(frac)`` / ``zoom_scale(factor)``。
    """

    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.buttons: dict[str, QToolButton] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(2)

        # 互斥由代码保证（不用 QButtonGroup 的 exclusive：用户要求再点一次
        # 能取消，exclusive 组不允许取消勾选）
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)

        for i, group in enumerate(TOOL_GROUPS):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.VLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                lay.addWidget(line)
            for key in group:
                btn = QToolButton()
                btn.setCheckable(key in MODE_TOOLS)
                btn.setAutoRaise(True)
                btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
                icon = plot_icon(key)
                if icon is not None:
                    btn.setIcon(icon)
                else:                       # 图标绘制失败时退化为文字
                    btn.setText(key)
                btn.clicked.connect(
                    lambda _c=False, k=key: self._on_click(k))
                lay.addWidget(btn)
                self._group.addButton(btn)
                self.buttons[key] = btn

        lay.addStretch(1)
        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color: #6b6b6b;")
        lay.addWidget(self.lbl_hint)

        self.retranslate()

    # -- 交互 ---------------------------------------------------------- #
    def _on_click(self, key: str) -> None:
        """按钮点击：模式类切换选中态，动作类立即执行。"""
        if key in MODE_TOOLS:
            btn = self.buttons[key]
            active = btn.isChecked()
            for other in MODE_TOOLS:        # 单选：先清掉其它工具
                if other != key:
                    self.buttons[other].setChecked(False)
            self.host.set_plot_tool(key if active else None)
            if not active:
                self.lbl_hint.setText("")
            return
        btn = self.buttons[key]
        if btn.isChecked():                 # 瞬时按钮不该保持选中
            btn.setChecked(False)
        if key == "reset":
            self.host.reset_view()
        elif key == "pan_left":
            self.host.pan_x(-PAN_FRAC)
        elif key == "pan_right":
            self.host.pan_x(PAN_FRAC)
        elif key == "zoom_in":
            self.host.zoom_scale(ZOOM_STEP)
        elif key == "zoom_out":
            self.host.zoom_scale(1.0 / ZOOM_STEP)

    def set_hint(self, text: str) -> None:
        """十字线读数（贴着谱图也显示一份）。"""
        self.lbl_hint.setText(text)

    def sync(self, tool: str | None) -> None:
        """程序化切换工具（测试与快捷键用），保持按钮状态一致。"""
        for key in MODE_TOOLS:
            self.buttons[key].setChecked(key == tool)
        if tool is None:
            self.lbl_hint.setText("")

    @property
    def mode(self) -> str | None:
        for key in MODE_TOOLS:
            if self.buttons[key].isChecked():
                return key
        return None

    def retranslate(self) -> None:
        for key, btn in self.buttons.items():
            btn.setToolTip(tr(f"vw.plot_widget.tool_{key}"))


__all__ = ["PlotToolBar", "TOOL_GROUPS", "MODE_TOOLS", "PAN_FRAC", "ZOOM_STEP"]
