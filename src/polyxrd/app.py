"""
PolyXRD 应用程序核心
====================
负责QApplication初始化、全局异常处理和主窗口创建。
"""
from __future__ import annotations

import sys
import traceback
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from polyxrd.config import get_config
from polyxrd.views.main_window import MainWindow


class PolyXRDApplication:
    """PolyXRD 主应用程序类"""

    def __init__(self, argv: list[str]) -> None:
        self._argv = argv
        self._qt_app: Optional[QApplication] = None
        self._main_window: Optional[MainWindow] = None
        self._setup_done = False

    def _setup(self) -> None:
        """初始化Qt应用"""
        self._qt_app = QApplication(self._argv)
        self._qt_app.setApplicationName("PolyXRD")
        self._qt_app.setOrganizationName("PolyXRD")
        self._qt_app.setApplicationVersion(get_config().app_version)

        # matplotlib 图上文字含中文 → 尽早把系统中文字体插进字体栈 (幂等)
        from polyxrd.utils.mpl_font import ensure_cjk_font

        ensure_cjk_font()

        # 启用高DPI支持
        self._qt_app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        self._qt_app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)

        # 应用持久化主题 (M20 v2: 视图菜单可切换, QSettings 持久化)
        from PySide6.QtCore import QSettings

        from polyxrd.views.theme import apply_theme

        _cfg = get_config()
        _settings = QSettings(_cfg.app_org, _cfg.app_name)
        apply_theme(
            self._qt_app,
            dark=_settings.value("view/dark_theme", False, type=bool),
        )

        # 设置全局异常处理
        sys.excepthook = self._global_exception_handler

        # 创建主窗口
        config = get_config()
        self._main_window = MainWindow(config)
        self._main_window.resize(config.window_width, config.window_height)

        self._setup_done = True

    def run(self) -> int:
        """启动应用并进入事件循环"""
        if not self._setup_done:
            self._setup()

        if self._main_window:
            self._main_window.show()

        assert self._qt_app is not None
        return self._qt_app.exec()

    def _global_exception_handler(
        self, exc_type: type, exc_value: BaseException, exc_tb: traceback.TracebackType | None
    ) -> None:
        """全局异常处理器"""
        error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(f"[PolyXRD Error]\n{error_msg}", file=sys.stderr)

        if self._qt_app and self._main_window:
            QMessageBox.critical(
                self._main_window,
                "程序错误",
                f"发生未处理的异常：\n\n{str(exc_value)}\n\n详情请查看控制台输出。",
            )
