"""
PolyXRD 应用入口
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QApplication, QSplashScreen

from polyxrd.config import get_config
from polyxrd.utils.resources import (
    get_app_icon_path,
    get_splash_screen_path,
)
from polyxrd.views.main_window import MainWindow


def main() -> int:
    """主入口函数"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    app_icon_path = get_app_icon_path()
    if app_icon_path:
        app.setWindowIcon(QIcon(app_icon_path))

    # 注意: splash 必须在 if 之前初始化。若 splash_path 有值但图片读不出来
    # (文件缺失/损坏), 下面 `if not pixmap.isNull()` 不成立, splash 就从未绑定,
    # 后面引用它必然 NameError 崩在 app.exec() 之前 —— 表现为"启动即闪退无窗口"。
    splash: QSplashScreen | None = None
    splash_path = get_splash_screen_path()
    if splash_path:
        pixmap = QPixmap(splash_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                480, 270,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
                )
            splash = QSplashScreen(scaled)
            splash.setWindowFlags(
                splash.windowFlags() | Qt.WindowType.FramelessWindowHint
            )
            splash.show()
            app.processEvents()

            QTimer.singleShot(800, splash.close)

    config = get_config()
    window = MainWindow(config)
    window.show()

    if splash is not None:
        QTimer.singleShot(100, lambda: (splash.close(), window.activateWindow()))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
