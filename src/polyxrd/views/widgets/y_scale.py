"""
纵坐标刻度模式支持 (v0.12.0)
=============================
给 matplotlib 绘图控件加上 **线性 / 对数 / 方根** 三种纵坐标显示。

数值换算是真的
--------------
- **对数**: ``ax.set_yscale("log")`` —— matplotlib 原生对数轴, 刻度标签上写的是
  **真实强度**(如 10²、10³), 不是强度的对数;
- **方根**: ``ax.set_yscale("function", functions=(sqrt, square))`` —— matplotlib
  3.3+ 的函数刻度, y 位置 = √y, 刻度标签同样反算回**真实强度**。
  两者都不做任何"曲线重画"式的假变换, 数据、游标读数、导出图片全部一致。

为什么要自己管 y 轴范围
-----------------------
对数/方根刻度下 ``autoscale`` 会被非正值(残差曲线在 0 以下、扣背景后的负强度)
带偏: 对数轴把 ≤0 的点裁到 ~1e-308, 自动缩放后 y 轴下限直接掉到 1e-308,
整张图会被压成一条线。所以进入对数/方根时:

1. 只取**正的数据点**算 y 范围, 给出一个可用窗口;
2. ``set_autoscaley_on(False)`` 锁住, 免得后续 ``autoscale_view()`` 又把它拉回去;
3. 回到线性时恢复自动缩放, 行为与旧版完全一致。

交互
----
- **左键**点击 Y 轴区域(数据区左边缘往左 ``STRIP_PX`` 像素的竖条, 含刻度与轴标题)
  → 在 线性 → 对数 → 方根 之间循环;
- **右键**点击图内任意位置(含 Y 轴竖条) → 弹出菜单精确选择。

左键热区刻意**避开数据区**, 这样谱峰点击/框选/平移都不受影响。
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QActionGroup, QCursor
from PySide6.QtWidgets import QMenu

from polyxrd.i18n import tr

# ── 模式常量 ──────────────────────────────────────────────────────────
Y_SCALE_LINEAR = "linear"
Y_SCALE_LOG = "log"
Y_SCALE_SQRT = "sqrt"

#: 左键循环顺序
Y_SCALE_CYCLE: tuple[str, ...] = (Y_SCALE_LINEAR, Y_SCALE_LOG, Y_SCALE_SQRT)

_LABEL_KEYS = {
    Y_SCALE_LINEAR: "view.y_scale.linear",
    Y_SCALE_LOG: "view.y_scale.log",
    Y_SCALE_SQRT: "view.y_scale.sqrt",
}

#: **轴标题**上的模式标记 —— 刻意用国际通用技术记号, 任何语言下都一样。
#: 谱图是论文/报告里要拿去用的图, "Intensity (log)" 一眼就懂, 翻成"对数"反而
#: 与文献惯用写法脱节; 菜单/提示等界面控件才需要本地化 (见 ``y_scale_label``)。
Y_SCALE_TOKENS = {
    Y_SCALE_LINEAR: "",
    Y_SCALE_LOG: "log",
    Y_SCALE_SQRT: "sqrt",
}

#: Axes 上记录当前模式的属性名 (matplotlib Axes 允许挂任意属性)
_MODE_ATTR = "_polyxrd_y_scale"

#: 左键热区宽度 (像素): 数据区左边缘向左这段距离内的点击算"点 Y 轴"
STRIP_PX = 64


def normalize_y_scale(mode: Optional[str]) -> str:
    """把任意输入收敛成合法模式, 非法值一律当线性。"""
    return mode if mode in Y_SCALE_CYCLE else Y_SCALE_LINEAR


def y_scale_label(mode: str) -> str:
    """模式的人类可读名 (已本地化)。"""
    return tr(_LABEL_KEYS.get(normalize_y_scale(mode), "view.y_scale.linear"))


def next_y_scale(mode: str) -> str:
    """循环取下一个模式。"""
    m = normalize_y_scale(mode)
    return Y_SCALE_CYCLE[(Y_SCALE_CYCLE.index(m) + 1) % len(Y_SCALE_CYCLE)]


def current_y_scale(ax) -> str:
    """读某个 Axes 当前记录的模式 (没记录过 = 线性)。"""
    return normalize_y_scale(getattr(ax, _MODE_ATTR, Y_SCALE_LINEAR))


def scaled_ylabel(base: str, mode: str) -> str:
    """给轴标题加上模式后缀: ``Intensity (log)`` / ``Intensity (sqrt)``。

    ⚠️ 后缀用**技术记号**而非本地化词 (不写 "对数"/"方根") —— 谱图上要跟文献、
    软件界面的通用写法保持一致, 中文版也一样。线性时不加后缀, 保持界面干净。
    """
    m = normalize_y_scale(mode)
    token = Y_SCALE_TOKENS.get(m, "")
    if not token:
        return base
    return f"{base} ({token})"


# ── 刻度设置 ──────────────────────────────────────────────────────────


def _sqrt_forward(values):
    """方根刻度的正向变换: ``√y``, 负值先夹到 0。

    为什么不像素级"纯"地直接 ``np.sqrt``: 图上常有 0 以下的 artist (残差曲线、
    扣背景后的涨落), 它们的 y 也会被送进变换 → ``sqrt(负数)`` 每次都污染
    控制台一行 ``RuntimeWarning: invalid value encountered in sqrt``, 而且
    画出来是 nan (整段消失)。夹到 0 之后: 无告警, 那些点在 √ 空间里落到轴底,
    与"低于显示范围"的观感一致。刻度标签仍是**真实强度**, 换算没有被破坏。
    """
    arr = np.asarray(values, dtype=float)
    return np.sqrt(np.clip(arr, 0.0, None))


def _positive_y_range(ax) -> tuple[Optional[float], Optional[float]]:
    """扫描 Axes 上所有 Line2D, 取**有限且为正**的 y 值范围。

    残差曲线、扣背景后的负强度都会被这一步天然排除 —— 它们在对数轴上没有意义,
    也不该参与 y 范围计算。
    """
    lo: Optional[float] = None
    hi: Optional[float] = None
    for line in ax.get_lines():
        try:
            y = np.asarray(line.get_ydata(), dtype=float)
        except (TypeError, ValueError):
            continue
        if y.size == 0:
            continue
        y = y[np.isfinite(y) & (y > 0)]
        if y.size == 0:
            continue
        y_min = float(y.min())
        y_max = float(y.max())
        lo = y_min if lo is None else min(lo, y_min)
        hi = y_max if hi is None else max(hi, y_max)
    return lo, hi


def _positive_reference(ax) -> tuple[float, float]:
    """全图没有正值时给一个中性兜底范围, 保证 log/sqrt 有定义域可用。"""
    ref = 1.0
    for v in ax.get_ylim():
        try:
            fv = abs(float(v))
        except (TypeError, ValueError):
            continue
        if np.isfinite(fv) and fv > 0:
            ref = max(ref, fv)
    return ref * 1e-3, ref


def _prepare_positive_domain(ax) -> None:
    """在切到对数/方根**之前**把 y 范围抬进正半轴。

    对数与方根都只对正值有定义。如果当前 (线性) 范围下探到 ≤0 —— 例如图里
    只有一条整体压在 0 以下的残差曲线 —— matplotlib 会在 ``set_yscale`` 时
    抛错或弹出 "Data has no positive values, and therefore cannot be
    log-scaled" 警告。先摆正范围再换刻度, 这两个问题就都没了。
    """
    lo, hi = _positive_y_range(ax)
    if lo is None or hi is None or not (hi > 0):
        lo, hi = _positive_reference(ax)
    bottom = max(lo * 0.5, 1e-12)
    top = max(hi * 1.6, bottom * 10.0)
    try:
        ax.set_ylim(bottom, top)
    except (ValueError, TypeError):  # pragma: no cover - 极端数据兜底
        pass


def _fit_ylim(ax, mode: str) -> None:
    """按当前数据重设一个**对数/方根可用的** y 范围。"""
    lo, hi = _positive_y_range(ax)

    if lo is None or hi is None or not (hi > 0):
        # 全图没有正值 (例如纯残差图): 对数/方根无意义, 用一个中性窗口兜底,
        # 保证不抛异常、不把导航缩放到稀奇古怪的量级。
        lo, hi = _positive_reference(ax)

    if mode == Y_SCALE_LOG:
        bottom = max(lo * 0.5, 1e-12)
        top = hi * 1.6
        if not (bottom < top):
            bottom = max(top * 1e-6, 1e-12)
    else:  # sqrt: 定义域 [0, ∞)
        bottom = 0.0
        top = hi * 1.15
        if not (top > bottom):
            top = bottom + 1.0

    try:
        ax.set_ylim(bottom, top)
    except (ValueError, TypeError):  # pragma: no cover - 极端数据兜底
        pass


def apply_y_scale(ax, mode: str, *, refit: bool = True) -> str:
    """把 ``ax`` 的纵坐标设成指定模式, 并给出可用的 y 范围。

    Args:
        ax: matplotlib Axes
        mode: linear / log / sqrt
        refit: True 时按数据重算 y 范围; False 只改刻度不动范围。

    Returns:
        实际生效的模式 (任何异常都回退线性, 绝不把异常抛给 UI)。
    """
    mode = normalize_y_scale(mode)
    try:
        if mode in (Y_SCALE_LOG, Y_SCALE_SQRT):
            # 先把 y 范围抬进正半轴: log 与 sqrt 都只对正值有定义, 当前 (线性)
            # 范围若下探到 ≤0, set_yscale 会抛错或弹 "no positive values" 警告。
            _prepare_positive_domain(ax)
        if mode == Y_SCALE_LOG:
            # nonpositive="clip": 非正值裁到极小正数而不是屏蔽 —— 不会因为
            # 一小撮负点 (残差/涨落) 就整段曲线消失。
            ax.set_yscale("log", nonpositive="clip")
        elif mode == Y_SCALE_SQRT:
            ax.set_yscale("function", functions=(_sqrt_forward, np.square))
        else:
            ax.set_yscale("linear")
    except Exception:  # noqa: BLE001 - 任何刻度异常都不该让界面崩掉
        try:
            ax.set_yscale("linear")
        except Exception:  # noqa: BLE001
            pass
        mode = Y_SCALE_LINEAR

    setattr(ax, _MODE_ATTR, mode)

    if mode == Y_SCALE_LINEAR:
        ax.set_autoscaley_on(True)
        if refit:
            try:
                ax.relim()
                ax.autoscale_view()
            except Exception:  # noqa: BLE001
                pass
    else:
        # 锁住 y: 否则后面任何一次 relim/autoscale_view 都会把范围拉回
        # "被裁到 1e-308 的非正值"那个退化区间。
        ax.set_autoscaley_on(False)
        if refit:
            _fit_ylim(ax, mode)

    return mode


class YScaleController(QObject):
    """把"左键循环 / 右键菜单"挂到一张 matplotlib 画布上。

    Args:
        canvas: FigureCanvasQTAgg
        axes_getter: 返回参与切换的 Axes 列表, **第 0 个视为主轴**。
            子图里那些"虚拟行"坐标轴 (如棒区) 不该放进来。
        label_getter: ``(ax) -> str``, 该轴 y 标签的基文本 (不含模式后缀)。
        repaint: 切换后重画画布的回调 (通常是 ``canvas.draw_idle``)。
        on_change: 切换成功后回调 ``(mode)``, 用于刷新提示文字。
        parent: Qt 父对象 (菜单用)
    """

    def __init__(
        self,
        canvas,
        axes_getter: Callable[[], Sequence],
        label_getter: Optional[Callable[[object], str]] = None,
        repaint: Optional[Callable[[], None]] = None,
        on_change: Optional[Callable[[str], None]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._axes_getter = axes_getter
        self._label_getter = label_getter
        self._repaint = repaint
        self._on_change = on_change
        canvas.mpl_connect("button_press_event", self._on_press)

    # -- 对外 ----------------------------------------------------------

    def axes(self) -> list:
        try:
            return list(self._axes_getter() or [])
        except Exception:  # noqa: BLE001
            return []

    @property
    def primary(self):
        """主轴 (第 0 个), 没有则 None。"""
        axs = self.axes()
        return axs[0] if axs else None

    def mode(self, ax=None) -> str:
        ax = ax if ax is not None else self.primary
        return current_y_scale(ax) if ax is not None else Y_SCALE_LINEAR

    def set_mode(self, mode: str, ax=None, *, refit: bool = True) -> None:
        """设定模式并刷新标签 / 重画。"""
        ax = ax if ax is not None else self.primary
        if ax is None:
            return
        applied = apply_y_scale(ax, mode, refit=refit)
        self.refresh_label(ax)
        if self._repaint is not None:
            self._repaint()
        if self._on_change is not None:
            self._on_change(applied)

    def cycle(self, ax=None) -> None:
        """在当前模式下顺延一格。"""
        ax = ax if ax is not None else self.primary
        if ax is None:
            return
        self.set_mode(next_y_scale(self.mode(ax)), ax)

    def refresh_label(self, ax) -> None:
        if self._label_getter is None:
            return
        try:
            base = self._label_getter(ax) or ""
        except Exception:  # noqa: BLE001
            return
        try:
            ax.set_ylabel(scaled_ylabel(base, current_y_scale(ax)))
        except Exception:  # noqa: BLE001
            pass

    def refresh(self, *, refit: bool = True) -> None:
        """外部改了数据/清了图之后调用: 按记录的样式重刷标签与范围。"""
        for i, ax in enumerate(self.axes()):
            if i == 0:
                apply_y_scale(ax, current_y_scale(ax), refit=refit)
            self.refresh_label(ax)
        if self._on_change is not None:
            self._on_change(self.mode())

    # -- 事件 ----------------------------------------------------------

    def _on_press(self, event) -> None:
        button = getattr(event, "button", None)
        if button not in (1, 3):
            return
        if button == 3:
            ax = self._axes_at(event, inaxes_ok=True)
            if ax is not None:
                self.show_menu(ax)
            return
        # 左键只在 Y 轴竖条内响应 → 不抢数据区的峰点击/框选
        ax = self._axes_at(event, inaxes_ok=False)
        if ax is not None:
            self.cycle(ax)

    def _axes_at(self, event, *, inaxes_ok: bool):
        """找出点击落在哪个轴的 Y 轴竖条上。"""
        x = getattr(event, "x", None)
        y = getattr(event, "y", None)
        if x is None or y is None:
            # 非 GUI 后端 (Agg 直接调事件) 没有像素坐标 → 退化为 inaxes 判定
            if inaxes_ok:
                inaxes = getattr(event, "inaxes", None)
                return inaxes if inaxes in self.axes() else None
            return None
        for ax in self.axes():
            try:
                bb = ax.get_window_extent()
            except Exception:  # noqa: BLE001
                continue
            if not (bb.y0 <= y <= bb.y1):
                continue
            if bb.x0 - STRIP_PX <= x <= bb.x0:
                return ax
            if inaxes_ok and bb.x0 < x <= bb.x1:
                return ax
        return None

    def show_menu(self, ax) -> None:
        """右键菜单: 三种模式单选。"""
        menu = QMenu(self._canvas)
        title = QAction(tr("view.y_scale.menu_title"), menu)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()

        group = QActionGroup(menu)
        group.setExclusive(True)
        cur = current_y_scale(ax)
        for mode in Y_SCALE_CYCLE:
            act = QAction(y_scale_label(mode), menu)
            act.setCheckable(True)
            act.setChecked(mode == cur)
            group.addAction(act)
            act.triggered.connect(
                lambda _checked=False, m=mode, a=ax: self.set_mode(m, a)
            )
            menu.addAction(act)

        menu.exec(QCursor.pos())


def hint_text(mode: str) -> str:
    """给 UI 上的提示标签用的一句话说明。

    模式本身用 ``linear/log/sqrt`` 技术记号 (与轴标题后缀同源), 前后包裹的
    说明文字才本地化 —— 谱图相关的标记一律不做翻译。
    """
    return tr("view.y_scale.hint", mode=normalize_y_scale(mode))


__all__ = [
    "Y_SCALE_LINEAR",
    "Y_SCALE_LOG",
    "Y_SCALE_SQRT",
    "Y_SCALE_CYCLE",
    "Y_SCALE_TOKENS",
    "STRIP_PX",
    "YScaleController",
    "apply_y_scale",
    "current_y_scale",
    "hint_text",
    "next_y_scale",
    "normalize_y_scale",
    "scaled_ylabel",
    "y_scale_label",
]
