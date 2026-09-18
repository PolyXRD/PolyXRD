"""
PolyXRD 应用入口
"""
from __future__ import annotations

import logging
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QApplication, QSplashScreen

from polyxrd.config import get_config
from polyxrd.utils.resources import (
    get_app_icon_path,
    get_splash_screen_path,
)
from polyxrd.views.main_window import MainWindow


# ── 启动诊断 (v0.13.0) ────────────────────────────────────────
#
# 打包版是 GUI 子系统程序: 没有控制台, 未捕获的异常只会让进程**静默消失**
# (用户看到的就是"双击打不开")。启动/崩溃日志写到 ~/.polyxrd/logs/,
# 出问题时有据可查 —— 尤其是原生崩溃 (access violation) 之前走到哪一步。
#
# 注意: 全部用 try/except 包住, 记日志本身绝不能成为新的启动失败点。

_LOG_DIR_HINT = Path.home() / ".polyxrd" / "logs"


def _log_dir() -> Path:
    d = _LOG_DIR_HINT
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _startup_log(message: str) -> None:
    """启动流水日志 (带时间戳, 只追加)。"""
    try:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n"
        with (_log_dir() / f"startup-{datetime.now():%Y-%m-%d}.log").open(
            "a", encoding="utf-8"
        ) as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 - 日志失败不能影响启动
        pass


def _write_crash(exc_type, exc_value, exc_tb) -> Optional[Path]:
    """把异常写进 crash 日志并返回日志路径。"""
    try:
        path = _log_dir() / f"crash-{datetime.now():%Y-%m-%d}.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write("=" * 70 + "\n")
            fh.write(f"time    : {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            fh.write(f"frozen  : {getattr(sys, 'frozen', False)}\n")
            fh.write(f"exe     : {sys.executable}\n")
            fh.write(f"cwd     : {Path.cwd()}\n")
            fh.write(f"argv    : {sys.argv}\n")
            fh.write("".join(traceback.format_exception(
                exc_type, exc_value, exc_tb)))
        return path
    except Exception:  # noqa: BLE001
        return None


def _install_excepthooks() -> None:
    """把未捕获异常 (主线程 + 子线程) 落盘, 不再静默消失。"""

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        path = _write_crash(exc_type, exc_value, exc_tb)
        try:
            sys.stderr.write(
                "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            )
            if path:
                sys.stderr.write(f"[PolyXRD] 崩溃日志: {path}\n")
        except Exception:  # noqa: BLE001 - GUI 子系统下 stderr 可能为 None
            pass

    sys.excepthook = _hook

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        _hook(args.exc_type, args.exc_value, args.exc_traceback)

    try:
        threading.excepthook = _thread_hook
    except Exception:  # noqa: BLE001 - 老解释器无此属性
        pass


def _fatal_dialog(title: str, text: str) -> None:
    """尽力弹一个能看见的报错框 (QApplication 起不来时静默跳过)。"""
    try:
        from PySide6.QtWidgets import QApplication as _App, QMessageBox

        if _App.instance() is None:
            return
        QMessageBox.critical(None, title, text)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    """主入口函数"""
    _install_excepthooks()
    _startup_log(
        f"--- start v{get_config().app_version} "
        f"frozen={getattr(sys, 'frozen', False)} exe={sys.executable}"
    )

    app = QApplication(sys.argv)
    _startup_log("QApplication OK")
    app.setStyle("Fusion")

    app_icon_path = get_app_icon_path()
    if app_icon_path:
        app.setWindowIcon(QIcon(app_icon_path))
    _startup_log(f"icon={app_icon_path}")

    # 注意: splash 必须在 if 之前初始化。若 splash_path 有值但图片读不出来
    # (文件缺失/损坏), 下面 `if not pixmap.isNull()` 不成立, splash 就从未绑定,
    # 后面引用它必然 NameError 崩在 app.exec() 之前 —— 表现为"启动即闪退无窗口"。
    splash: QSplashScreen | None = None
    splash_path = get_splash_screen_path()
    if splash_path:
        try:
            pixmap = QPixmap(splash_path)
            if not pixmap.isNull():
                # 磁盘上的 splash-screen.png 已预缩放到 480x270; 只有拿到更大的
                # 图 (回退到旧 JPEG) 时才需要缩放。缩放是一次重量级解码后的重采样,
                # 能省则省。
                if pixmap.width() > 480 or pixmap.height() > 270:
                    pixmap = pixmap.scaled(
                        480, 270,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                        )
                splash = QSplashScreen(pixmap)
                splash.setWindowFlags(
                    splash.windowFlags() | Qt.WindowType.FramelessWindowHint
                )
                splash.show()
                app.processEvents()

                QTimer.singleShot(800, splash.close)
        except Exception:  # noqa: BLE001 - 启动图失败不能拦住主窗口
            splash = None
    _startup_log(f"splash={'ok' if splash is not None else 'skipped'}")

    config = get_config()
    window = MainWindow(config)
    _startup_log("MainWindow OK")
    window.show()
    _startup_log("shown")

    if splash is not None:
        QTimer.singleShot(100, lambda: (splash.close(), window.activateWindow()))

    code = app.exec()
    _startup_log(f"--- exit code={code}")
    return code


if __name__ == "__main__":
    logging.getLogger("polyxrd").addHandler(logging.NullHandler())
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - 兜底: 保证一定留下日志
        _write_crash(*sys.exc_info())
        _fatal_dialog(
            "PolyXRD 启动失败",
            "程序启动时发生异常, 详情见日志:\n"
            f"{_log_dir()}\n\n"
            + "".join(traceback.format_exception(*sys.exc_info()))[-1500:],
        )
        sys.exit(1)

