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

    if splash_path:
        QTimer.singleShot(100, lambda: (splash.close(), window.activateWindow()))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
