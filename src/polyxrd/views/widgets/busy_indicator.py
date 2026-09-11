"""忙碌提示 / 防重入闸门
==========================
长耗时操作 (峰检测、峰拟合、物相检索、Rietveld 精修) 全部在主线程**同步**执行。
期间 Qt 事件循环被占住, 界面既不重绘也不响应点击, 用户看不到任何反馈时会再点
几次按钮 —— 这些点击并不会消失, 而是**积压在消息队列里**, 等任务结束、按钮刚被
重新启用的那一刻被一次性投递, 于是又叠起几轮长任务, 表现为"程序未响应"乃至崩溃。

`refinement_view._on_refine` 原本已经做了 `setEnabled(False)`, 但因为
`refinement_completed` 是同步信号, 重新启用发生在阻塞调用返回**之前**, 所以挡不住
这批"迟到的点击"。闸门必须一直持有到积压输入被排空为止 —— 这就是本模块存在的理由。

本模块提供三件事:

1. **看得见的反馈** —— 置顶模态小窗「正在执行，请稍后…」+ 不确定进度条 + 等待光标;
2. **挡住重入** —— 模态窗拦住父窗口输入; 类级占用标志兜底 (键盘快捷键、
   信号回调等绕过鼠标的那条路); 收尾时**先排空积压输入再撤防** (关键);
3. **保持重绘** —— `pump()` 以 `ExcludeUserInputEvents` 处理事件: 界面能重绘、
   Windows 不会把窗口标成"未响应", 但用户输入仍然被丢弃, 不会重新入闸门。

用法::

    from polyxrd.views.widgets.busy_indicator import busy

    with busy(self, tr("busy.peak_search")) as acquired:
        if not acquired:      # 已有长任务在跑 → 忽略本次触发
            return
        do_long_work()

耗时循环里周期性调 `busy.pump()` 即可保持窗口"活着"::

    for i, x in enumerate(items):
        ...
        BusyIndicator.pump()

也可作装饰器 (父窗口取 `self`)::

    @busy_guard("busy.peak_search")
    def _on_find_peaks(self) -> None:
        ...
"""
from __future__ import annotations

import functools
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from polyxrd.i18n import tr

__all__ = ["BusyIndicator", "busy", "busy_guard"]


class _BusyDialog(QDialog):
    """置顶模态提示窗: 一行主文案 + 不确定进度条 + 一行提示。

    刻意不提供任何按钮 —— 既没有"取消"也没有"确定", 因为此刻主线程正忙于计算,
    任何按钮都点不动; 放个点不动的按钮只会加重"卡死"的观感。
    """

    def __init__(self, parent: Optional[QWidget], text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("busy.title"))
        # 顶层 + 应用级模态: 拦住整个程序的输入, 而不只是父窗口
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(260)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        # 0/0 → 不确定模式 (滚动条纹), 因为多数算法给不出可靠的百分比
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(14)
        layout.addWidget(self._bar)

        hint = QLabel(tr("busy.hint"))
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(hint)

    def set_text(self, text: str) -> None:
        self._label.setText(text)


class BusyIndicator:
    """全局忙碌闸门。所有方法都是类方法 —— 同一时刻只该有一个长任务。"""

    _active: bool = False
    """是否已有长任务在执行。

    约定: **同一时刻只允许一个长任务**, 重入一律返回 False (调用方静默返回, 不弹错)。
    刻意不做嵌套放行 —— 闸门要挡的正是"第二轮长任务", 无论它是用户第二次点击,
    还是内层代码又起一轮 (那会让用户看到两轮进度、两倍等待)。
    真正拦住用户输入的是模态窗 + `ExcludeUserInputEvents`; 这个标志只负责把
    "一次只跑一个" 这条约定固化下来, 让键盘快捷键、信号回调等绕过鼠标的路径
    也一并归一。
    """

    _dialog: Optional[_BusyDialog] = None
    _cursor_active: bool = False
    """是否由本闸门设置了等待光标。

    单独记一个标志 (而不是无条件 `restoreOverrideCursor`), 避免在 `_show` 中途
    失败时误弹掉别的模块设置的覆盖光标。
    """

    # ── 查询 ────────────────────────────────────────────────
    @classmethod
    def is_busy(cls) -> bool:
        return cls._active

    # ── 进出闸门 ────────────────────────────────────────────
    @classmethod
    def enter(cls, parent: Optional[QWidget], text: str) -> bool:
        """进入忙碌状态。

        Returns:
            True 表示这次调用应当继续执行; False 表示已有长任务在跑, 应直接放弃。
        """
        if cls._active:
            return False
        cls._active = True
        cls._show(parent, text)
        return True

    @classmethod
    def leave(cls) -> None:
        if not cls._active:
            return
        cls._active = False
        cls._drain_then_hide()

    @classmethod
    def _show(cls, parent: Optional[QWidget], text: str) -> None:
        app = QApplication.instance()
        if app is None:  # 无 GUI (纯逻辑调用) → 闸门仍然生效, 只是不弹窗
            return
        try:
            dlg = _BusyDialog(parent, text)
            dlg.show()
            # 先跑一轮事件让窗体和文字真正画出来, 否则用户看到的是空白/残影
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        except Exception:  # noqa: BLE001 - 提示失败不该拖垮主流程
            return
        # 弹窗确实建起来了才登记, 保证 leave 时能收干净
        cls._dialog = dlg
        try:
            app.setOverrideCursor(Qt.CursorShape.WaitCursor)
            cls._cursor_active = True
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def _hide_dialog(cls) -> None:
        """撤掉弹窗与等待光标 (不排空事件队列 —— 那步只在 `_drain_then_hide` 做)。"""
        app = QApplication.instance()
        if cls._cursor_active and app is not None:
            try:
                app.restoreOverrideCursor()
            except Exception:  # noqa: BLE001
                pass
        cls._cursor_active = False
        dlg, cls._dialog = cls._dialog, None
        if dlg is not None:
            try:
                dlg.hide()
                dlg.deleteLater()
            except Exception:  # noqa: BLE001
                pass

    @classmethod
    def _drain_then_hide(cls) -> None:
        """先排空阻塞期间积压的输入, 再撤掉闸门。

        顺序不能反: 闸门 (模态窗) 还开着的时候, 积压的点击会被模态机制直接丢弃;
        一旦先关窗再排空, 这些迟到点击就会打到刚恢复的按钮上, 又起一轮长任务 ——
        这正是"多点几下就未响应/崩溃"的成因。
        """
        app = QApplication.instance()
        if app is not None:
            try:
                # 不传 flags = 全部事件都派发, 目的就是把这批"迟到点击"排空
                for _ in range(3):
                    app.processEvents()
            except Exception:  # noqa: BLE001
                pass
        cls._hide_dialog()

    # ── 保持响应 ────────────────────────────────────────────
    @classmethod
    def pump(cls) -> None:
        """耗时循环里周期性调用: 重绘界面但**不**派发用户输入。

        `ExcludeUserInputEvents` 是这里的要点 —— 只重绘不接收输入, 所以不会因为
        泵事件而把用户的点击放进来 (那正是我们要挡的东西)。
        """
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def set_text(cls, text: str) -> None:
        dlg = cls._dialog
        if dlg is not None:
            try:
                dlg.set_text(text)
            except Exception:  # noqa: BLE001
                pass

    @classmethod
    def progress_tick(cls, done: int, total: int) -> None:
        """给耗时循环用的现成回调: 刷新提示文案并泵一次事件。"""
        if total > 0:
            cls.set_text(tr("busy.progress", done=done, total=total))
        else:
            cls.set_text(tr("busy.working"))
        cls.pump()

    @classmethod
    def reset(cls) -> None:
        """测试用: 强制清空状态并撤掉可能残留的弹窗。"""
        cls._active = False
        cls._hide_dialog()


@contextmanager
def busy(parent: Optional[QWidget], text: str) -> Iterator[bool]:
    """忙碌闸门上下文管理器。

    Yields:
        True = 拿闸门成功, 可以执行; False = 已有长任务在跑, 请直接返回。
    """
    acquired = BusyIndicator.enter(parent, text)
    try:
        yield acquired
    finally:
        if acquired:
            BusyIndicator.leave()


def busy_guard(key: str, text_getter: Optional[Callable[..., str]] = None) -> Callable:
    """装饰器: 给长耗时槽函数套上忙碌提示 + 防重入。

    Args:
        key: 翻译键, 作为提示文案, 如 ``"busy.peak_search"``。
        text_getter: 可选, 由被装饰方法自身算文案 (需要读 self 上的控件状态时用),
            签名 ``(self, *args, **kwargs) -> str``。

    Note:
        被装饰方法若返回 None 且本次未拿到闸门, 会**静默返回** —— 用户又点了一次
        不该弹出任何错误框, 否则更烦。
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            parent = self if isinstance(self, QWidget) else None
            text = text_getter(self, *args, **kwargs) if text_getter else tr(key)
            with busy(parent, text) as acquired:
                if not acquired:
                    return None
                return fn(self, *args, **kwargs)

        return wrapper

    return decorator
