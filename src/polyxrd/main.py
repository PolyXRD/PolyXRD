"""
PolyXRD 应用入口
"""
from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QApplication, QSplashScreen

from polyxrd import __version__
from polyxrd.config import get_config
from polyxrd.services.instance_guard import InstanceGuard, default_lock_dir
from polyxrd.services import startup_diag
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

# 硬退出看门狗 (v1.0.2)
# 现场问题: "关掉程序后进程还在 -> 再双击打不开 -> 只能重启电脑"。
# app.exec() 返回后若解释器收尾被某个线程/句柄挂住, 进程就会一直挂在任务管理器里
# (窗口已消失)。这里挂一个守护线程兜底: 给正常收尾留 5 秒, 超时直接 os._exit,
# 保证**窗口一关, 进程必走**。
_HARD_EXIT_DELAY_S = 5.0


def _log_dir() -> Path:
    d = _LOG_DIR_HINT
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _startup_log(message: str) -> None:
    """启动流水日志 (带时间戳与 pid, 只追加)。

    pid 前缀 (v1.0.2): 现场日志 (Win11) 显示双实例并发启动时两份日志交错写入,
    没有 pid 根本分不清哪行属于哪个进程。
    """
    try:
        line = (
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
            f"[pid={os.getpid()}] {message}\n"
        )
        with (_log_dir() / f"startup-{datetime.now():%Y-%m-%d}.log").open(
            "a", encoding="utf-8"
        ) as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 - 日志失败不能影响启动
        pass


# faulthandler 需要文件句柄存活期间一直有效, 存模块级引用
_FAULT_LOG_FH: Optional[object] = None


def _enable_faulthandler() -> None:
    """原生崩溃 (access violation) 时把各线程 Python 调用栈落盘 (v1.0.2)。

    现场实证 (v1.0.1, Win11): 同一次会话里 9 次启动有 6 次死在 window.show()
    内部 —— 日志停在 "showing main window" 就没了, Python 层**没有异常**,
    sys.excepthook 收不到, crash-*.log 不会生成。faulthandler 靠向量化异常
    处理在原生崩溃瞬间抓 Python 栈, 正好补这个洞。
    """
    global _FAULT_LOG_FH
    try:
        path = _log_dir() / f"faulthandler-{datetime.now():%Y-%m-%d}.log"
        _FAULT_LOG_FH = path.open("a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_LOG_FH)
        _startup_log(f"faulthandler enabled -> {path.name}")
    except Exception:  # noqa: BLE001 - 诊断失败不能影响启动
        pass


def _apply_safe_render_overrides(argv: list) -> list:
    """保守渲染模式 (v1.0.2): `--safe-render` 或环境变量 POLYXRD_SAFE_RENDER=1。

    现场实证 (v1.0.1, Win11 24H2 + i5-13500H Iris Xe, 驱动 2023-06-15):
    9 次启动 6 次死在 window.show() 内部, 事件查看器 faulting module =
    **Qt6Widgets.dll 6.11.1 (0xC0000005 访问冲突)** ×5 +
    **ucrtbase.dll (0xC0000409 fail-fast, 即 qFatal/abort)** ×1;
    本机 (开发机) 同版本 Qt 完全不复现 → 疑与该机 GPU 驱动 / 24H2 主题挂钩。
    本开关在 QApplication 创建**之前**关掉全部 GPU / 主题捷径, 用于二分定位:
      QT_OPENGL=software                  -> Qt 全部走软件 GL
      QT_QPA_PLATFORM=windows:darkmode=0  -> 关闭 Win11 深色模式挂钩 (Qt 6.5+ 默认开)
      QT_ENABLE_HIGHDPI_SCALING=0         -> 关闭 DPI 缩放
    setdefault 语义: 用户显式设置的变量不被覆盖。返回清理后的 argv。
    """
    if "--safe-render" not in argv and os.environ.get("POLYXRD_SAFE_RENDER") != "1":
        return argv
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QPA_PLATFORM", "windows:darkmode=0")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    _startup_log(
        "safe-render mode: software GL / darkmode=0 / no DPI scaling "
        f"(QT_OPENGL={os.environ.get('QT_OPENGL')})"
    )
    return [a for a in argv if a != "--safe-render"]


# ── 启动期观测探针 (v5.2, P0-1) ──────────────────────────────
#
# 现场 (2026-10-29) 的 AV 只能定位到 "window.show() 这一行", 但 show() 内部
# 至少有两个阶段: ① 平台窗口创建 (CreateWindowEx / 桌面合成器); ② 首帧绘制
# (进入事件循环后)。这两类失败的**修法完全不同** (前者查 Qt 平台插件/DPI/
# 远程桌面, 后者查 GL 上下文/子控件绘制), 所以必须在两者之间插一根探针。
#
# 只在主窗口这条路径上加, 且全部 try/except: 探针自身绝不能成为新的失败点。


def _log_launch_context() -> None:
    """记下两个"日志里看不出来"的变量 (待办 P0-1 §4-4 要求锁死的)。

    现场那 15 次启动分不清 A/B 组, 根因就是日志里没有这两条:
      * **是否管理员**: 决定 ``cod_data/cif_db`` 能不能被 mkdir 出来;
      * **cif_db 是否已存在**: 已存在时普通用户也能过 (``exist_ok=True``
        不校验写权限), 于是"权限"这个变量被悄悄抹平。
    附带记会话类型 (远程桌面) 与关键渲染环境变量 —— Qt6 在 RDP / 混合 DPI 下
    ``show()`` 崩溃有先例, 有版本号才能比对。
    """
    try:
        admin = "unknown"
        if sys.platform == "win32":
            try:
                import ctypes

                admin = str(bool(ctypes.windll.shell32.IsUserAnAdmin()))
                remote = bool(
                    ctypes.windll.user32.GetSystemMetrics(0x1000)  # SM_REMOTESESSION
                )
            except Exception:  # noqa: BLE001
                remote = None
        else:
            remote = None
        cif_db = ""
        try:
            cif_db = str(get_config().paths.cif_db_path)
        except Exception:  # noqa: BLE001 - 配置不可用时这条留空
            cif_db = "<config unavailable>"
        exists = Path(cif_db).is_dir() if cif_db and "<" not in cif_db else None
        writable = startup_diag.dir_writable(cif_db) if exists else None
        _startup_log(
            f"context: admin={admin} remote_session={remote} "
            f"cif_db={cif_db!r} exists={exists} writable={writable} "
            f"opengl={os.environ.get('QT_OPENGL', '<unset>')} "
            f"qpa={os.environ.get('QT_QPA_PLATFORM', '<unset>')} "
            f"dpi_scale={os.environ.get('QT_ENABLE_HIGHDPI_SCALING', '<unset>')}"
        )
    except Exception:  # noqa: BLE001
        pass


def _install_first_paint_probe(app: QApplication, window) -> None:
    """在**第一个** Paint 事件发生时打一行 ``first-paint``。

    为什么不用 ``QWidget.paintEvent``: MainWindow 自己通常不重绘 (画的是子控件),
    覆写它可能永远不触发。改用应用级事件过滤器, 只认"属于主窗口树"的 Paint,
    第一个就够 —— 它证明"窗口创建成功且已经进过一次绘制"。

    判定价值: 崩在 ``post-show`` 与 ``first-paint`` 之间 ⇒ 首帧绘制/GL 上下文;
    连 ``post-show`` 都没有 ⇒ 平台窗口创建阶段。这条能把搜索面砍掉一半。
    """
    from PySide6.QtCore import QEvent, QObject

    class _FirstPaintProbe(QObject):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._seen = False

        def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
            if not self._seen and event.type() == QEvent.Type.Paint:
                try:
                    owner = obj.window() if hasattr(obj, "window") else None
                except Exception:  # noqa: BLE001
                    owner = None
                if owner is window:
                    self._seen = True
                    _startup_log("first-paint")
            return False

    try:
        probe = _FirstPaintProbe(app)
        app.installEventFilter(probe)
        # 保住引用: 过滤器被回收后事件就没人接了 (Qt 不持有 Python 引用)
        app._polyxrd_paint_probe = probe  # noqa: SLF001 - 只此一处
    except Exception:  # noqa: BLE001
        pass


# ── 崩溃自愈 (v2.0.1) ────────────────────────────────────────
#
# 现场问题: 打包版**拷到别的机器**运行时, 偶发"启动图/主窗口一闪就退出"。
# 已定位根因 (v1.0.2 取证): MainWindow.show() 内部的原生崩溃
# (Qt6Widgets.dll 0xC0000005, 与特定 GPU 驱动 / Win11 24H2 挂钩) —— 这类
# 崩溃发生在原生层, Python 的 excepthook / faulthandler 都拦不住进程消失。
# `--safe-render` 能绕开, 但它只是**手动**开关, 普通用户不知道要用。
#
# 这里做成**跨启动自愈**: 每次启动先写"pending"(尚未确认健康); 主窗口 show()
# 之后存活 N 秒才改写成"healthy"。下次启动若读到 pending 仍为真, 即上一次没跑到
# 健康态 (极可能就是 show() 阶段原生崩溃) -> 本次自动套用保守渲染。于是
# "第一次崩、第二次自动用软件 GL 起来", 用户无感、无需命令行。
_RENDER_HEALTHY_DELAY_MS = 5000
_RENDER_STATE_ENV = "POLYXRD_RENDER_STATE"  # 测试用: 指向临时状态文件


def _render_state_path() -> Path:
    override = os.environ.get(_RENDER_STATE_ENV)
    if override:
        return Path(override)
    return _log_dir().parent / "render_state.json"


def _read_render_pending() -> bool:
    """读上一次启动是否未达健康态 (文件缺失/损坏一律当作"健康")."""
    try:
        import json

        p = _render_state_path()
        if not p.is_file():
            return False
        return bool(json.loads(p.read_text(encoding="utf-8")).get("pending"))
    except Exception:  # noqa: BLE001 - 状态文件损坏不能拦住启动
        return False


def _write_render_state(pending: bool, *, safe_render: bool) -> None:
    try:
        import json

        p = _render_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "pending": bool(pending),
                    "safe_render": bool(safe_render),
                    "ts": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - 状态写失败不能拦住启动
        pass


def _auto_safe_render_if_needed() -> bool:
    """上次启动未达健康态 -> 本次自动启用保守渲染。返回是否自动启用。

    与 `--safe-render` 共用同一组环境变量 (setdefault: 不覆盖用户显式设置);
    必须在 QApplication 创建之前调用。调用方负责在测试下抑制 (见 main())。
    """
    if not _read_render_pending():
        return False
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QPA_PLATFORM", "windows:darkmode=0")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    _startup_log(
        "auto safe-render: previous launch did not reach healthy state "
        f"(QT_OPENGL={os.environ.get('QT_OPENGL')})"
    )
    return True


def _reset_render_state() -> int:
    """`--reset-render`: 清掉自愈状态, 回到正常渲染 (排障用)。"""
    try:
        p = _render_state_path()
        if p.is_file():
            p.unlink()
        _startup_log("--- render state reset")
    except Exception:  # noqa: BLE001
        pass
    return 0


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


def _startup_evidence(note: str = "") -> str:
    """把"为什么起不来"的证据凑成一段人话, 供弹窗/日志使用。

    关键: 这里会去查 EXE / 关键 DLL 是否**此刻被别的进程占着**
    (Restart Manager 反查占用者) —— 这正是"必须重启电脑"最典型的成因。
    """
    try:
        info = startup_diag.diagnose(sys.executable, extra_note=note or None)
        report = startup_diag.format_report(info)
    except Exception as exc:  # noqa: BLE001
        report = f"(诊断模块本身失败: {exc})"
    try:
        path = _log_dir() / f"startup-failure-{datetime.now():%Y-%m-%d}.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(report + "\n" + "=" * 70 + "\n")
    except Exception:  # noqa: BLE001
        pass
    return report


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


def _arm_hard_exit(code: int, delay: float = _HARD_EXIT_DELAY_S) -> None:
    """给正常收尾留 delay 秒; 到点还活着就硬退, 不留"幽灵进程"。

    副作用可控: 事件循环已经结束, 该落盘的都已经落盘 (项目/设置都在
    closeEvent / app.exec() 之内完成), 这里只负责"确保进程真的消失"。

    **重要**: 在 pytest 里绝不能挂 —— 测试会把 `QApplication.exec` 换成"立即返回",
    进程本身还要跑十几分钟, 5 秒后一发 `os._exit` 就会把整个测试进程干掉。
    这里用 `PYTEST_CURRENT_TEST`(pytest 自动设置) 与 `POLYXRD_NO_HARD_EXIT`
    双重开关兜住。
    """
    if delay <= 0 or os.environ.get("POLYXRD_NO_HARD_EXIT") or \
            os.environ.get("PYTEST_CURRENT_TEST"):
        _startup_log("hard exit watchdog skipped (test/opt-out)")
        return

    def _run() -> None:
        time.sleep(delay)
        _startup_log(f"hard exit watchdog fired (code={code}) -> os._exit")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:  # noqa: BLE001
            pass
        os._exit(code)

    t = threading.Thread(target=_run, name="polyxrd-hard-exit", daemon=True)
    t.start()


def _run_diagnose() -> int:
    """`--diagnose`: 不起 GUI, 产出一份"为什么打不开"的报告。

    典型用法: 出问题时双击打不开, 用命令行 `PolyXRD.exe --diagnose`
    看报告 —— 会指明是哪个文件被哪个进程占用。
    """
    _startup_log("--- diagnose requested")
    info = startup_diag.diagnose(sys.executable)
    report = startup_diag.format_report(info)
    out = None
    try:
        out = _log_dir() / f"diagnose-{datetime.now():%Y%m%d-%H%M%S}.txt"
        with out.open("w", encoding="utf-8") as fh:
            fh.write(report + "\n")
    except Exception:  # noqa: BLE001
        pass
    try:
        print(report)
    except Exception:  # noqa: BLE001
        pass
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        _fatal_dialog("PolyXRD 启动诊断", report + (f"\n\n报告已保存: {out}" if out else ""))
        _ = app
    except Exception:  # noqa: BLE001
        pass
    return 0


def _force_utf8_environment() -> None:
    """全链路 UTF-8 (v1.1.1)。

    目的: 同一个 exe 在中文 / 日文 / 英文 Windows 上行为一致, 不因系统 ANSI
    代码页 (GBK / CP932 / CP1252) 不同而产生乱码。

    做两件事:

    1. 把**本进程**的 stdout/stderr 重挂到 UTF-8 —— 冻结版没有控制台时这两个流
       可能指向被重定向的文件; 在 GBK 代码页下打印 ``°``、中文或日文会抛
       ``UnicodeEncodeError`` (dev 模式 ``run_dev.bat`` 尤其明显)。
       ``errors="replace"`` 保证"打印"永远不会成为新的失败点。
    2. 用 ``setdefault`` 给**子进程**留下 UTF-8 环境: 外部精修程序
       (GSAS-II / MAUD / FullProf) 多为 Python 程序或会回写文本文件,
       ``PYTHONUTF8=1`` + ``PYTHONIOENCODING=utf-8`` 让它们也按 UTF-8 走。
       setdefault 语义: 用户/系统显式设置的值不被覆盖。

    ⚠️ 本函数**不改变当前进程的文件系统编码** —— 那必须在解释器启动前设
    ``PYTHONUTF8=1``。所以代码内所有文本 I/O 一律显式
    ``encoding="utf-8"``(由 ``scripts/check_utf8_encoding.py`` 静态守护),
    不依赖任何平台默认值。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def main() -> int:
    """主入口函数"""
    # 最早执行: 让 stdio 与子进程环境在任何输出/子进程启动前就是 UTF-8
    _force_utf8_environment()
    _install_excepthooks()
    # 尽早开: 任何原生崩溃 (包括 window.show() 内部) 都要留下 Python 调用栈
    _enable_faulthandler()
    # 保守渲染: 手动开关 (--safe-render / POLYXRD_SAFE_RENDER) 与「上次崩溃自愈」
    # 共用同一组环境变量, 都必须在 QApplication 创建之前生效。
    manual_safe = ("--safe-render" in sys.argv[1:]) or (
        os.environ.get("POLYXRD_SAFE_RENDER") == "1"
    )
    sys.argv = _apply_safe_render_overrides(sys.argv)
    # 测试下不读/写真实自愈状态, 保证用例行为可预测 (自愈逻辑由单测直接覆盖)
    under_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    auto_safe = _auto_safe_render_if_needed() if not under_test else False
    using_safe = manual_safe or auto_safe

    if "--reset-render" in sys.argv[1:]:
        return _reset_render_state()

    if "--diagnose" in sys.argv[1:]:
        return _run_diagnose()

    # 版本号直接取包常量: 早先写的是 get_config().app_version, 这会让
    # ``get_config()`` 在 QApplication 之前就执行 —— 它一旦因路径问题抛异常,
    # 进程连窗口都出不来 (v4.4.0 装到 Program Files 时实测)。版本号本就
    # 不依赖配置, 没必要为打一行日志去动配置单例。
    _startup_log(
        f"--- start v{__version__} "
        f"frozen={getattr(sys, 'frozen', False)} exe={sys.executable}"
    )

    # ── 单实例守卫 (v1.0.2) ──────────────────────────────────
    # 用内核命名互斥量而不是"锁文件存在即拒绝": 上次被任务管理器强杀后,
    # 内核立刻回收对象, 下一次双击必然能起 —— 从机制上杜绝"关掉后再也打不开"。
    # 三种结果:
    #   a) 首个实例            -> 正常启动
    #   b) 有实例且有窗口      -> 把它的窗口拉到前台, 本次安静退出 (双击=切回)
    #   c) 有实例但找不到窗口  -> 典型"幽灵实例", **照样启动** (fail-open),
    #                             保证双击一定出窗口
    guard = InstanceGuard(default_lock_dir())
    _startup_log(f"instance: is_first={guard.is_first}")
    if not guard.is_first:
        handles = guard.existing_window_handles()
        if handles:
            raised = guard.activate_existing()
            _startup_log(
                f"existing instance window found (n={len(handles)}, "
                f"foreground={raised}) -> exiting quietly"
            )
            return 0
        _startup_log(
            "existing instance reported but no window found "
            "-> starting anyway (fail-open)"
        )

    # 标记"启动中, 尚未确认健康" —— 必须在过完单实例守卫之后再写: 否则
    # "双击=切回已有窗口"的安静退出会留下 pending, 误导下一次启动进保守渲染。
    if not under_test:
        _write_render_state(True, safe_render=using_safe)

    app = QApplication(sys.argv)
    _startup_log("QApplication OK")
    # P0-1 探针: 权限 / 会话类型 / cif_db 三态 —— 现场日志缺的正是这几项
    _log_launch_context()
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
                # 注意: 关闭启动图的定时器**必须**等到主窗口 show() 之后再挂。
                # 若在此处就挂 800ms 定时器, 首次运行 (matplotlib 字体缓存/冷 .pyc,
                # 主窗口构造要 3~4s) 期间一旦处理到事件, splash 就可能在主窗口
                # 显形前关闭; 此时"最后一个窗口已关闭" → quitOnLastWindowClosed
                # (默认 True) 触发 → 应用直接退出, 控制台一闪而过且**不留任何
                # 异常日志** (v0.15.2 排查到的"run_dev.bat 闪退"路径)。
                # 关闭动作统一放在 window.show() 之后。
        except Exception:  # noqa: BLE001 - 启动图失败不能拦住主窗口
            splash = None
    _startup_log(f"splash={'ok' if splash is not None else 'skipped'}")

    config = get_config()
    window = MainWindow(config)
    _startup_log("MainWindow OK")

    # 主窗口先显形, 关闭启动图的定时器**随后**才挂 (顺序不能反, 见 splash 段注释:
    # 反过来的顺序会在冷启动慢路径上触发 quitOnLastWindowClosed → 闪退)。
    # show() 单独包一层: 原生的窗口创建阶段若炸掉, 至少把 traceback 落盘,
    # 不再让进程"静默消失"。
    _startup_log("showing main window")
    # 首帧探针必须在 show() **之前**装好: Paint 事件要等事件循环转起来才来,
    # 但装上之后任何一次重绘都能抓到; show() 内部若就崩掉, 这一行本身也是证据。
    _install_first_paint_probe(app, window)
    try:
        window.show()
    except BaseException:  # noqa: BLE001 - 兜底: 一定留下证据
        _write_crash(*sys.exc_info())
        _fatal_dialog(
            "PolyXRD 启动失败",
            "主窗口 show() 阶段发生异常, 详情见日志:\n"
            f"{_log_dir()}\n\n"
            + "".join(traceback.format_exception(*sys.exc_info()))[-1500:],
        )
        raise
    # 记日志本身绝不能成为新的失败点: isVisible 只是"锦上添花"的证据,
    # 取不到就算了 (测试里的桩窗口就没有这个方法)。
    try:
        _visible: object = bool(window.isVisible())
    except Exception:  # noqa: BLE001
        _visible = "unknown"
    _startup_log(f"shown visible={_visible}")

    # P0-1: show() 返回后到事件循环真正跑起来之间还有一段 (平台窗口映射 +
    # 首帧)。0 ms 与 50 ms 两个点把这段切开: 崩在 post-show 与 ui-tick0 之间
    # ⇒ 窗口映射/合成器阶段; 崩在 ui-tick0 与 settled 之间 ⇒ 首帧绘制。
    if not under_test:
        QTimer.singleShot(0, lambda: _startup_log("ui-tick0"))
        QTimer.singleShot(50, lambda: _startup_log("settled"))

    if splash is not None:
        QTimer.singleShot(100, lambda: (splash.close(), window.activateWindow()))
        # 兜底: 上面那条 lambda 若被任何原因吞掉, 800ms 后也一定收掉启动图
        QTimer.singleShot(800, splash.close)

    # 自愈收尾: 主窗口已 show 且事件循环再跑若干秒仍活着 -> 判定"健康", 清掉
    # pending; 下次启动即恢复正常渲染。若进程在此之前原生崩溃, pending 留存,
    # 下次启动自动进保守渲染 (见 _auto_safe_render_if_needed)。
    if not under_test:
        QTimer.singleShot(
            _RENDER_HEALTHY_DELAY_MS,
            lambda: _write_render_state(False, safe_render=using_safe),
        )

    # 窗口关掉后, 若 Qt 的收尾阶段卡住 (外部工具句柄 / 残留线程), 这里硬退。
    try:
        app.aboutToQuit.connect(lambda: _arm_hard_exit(0, delay=20.0))
    except Exception:  # noqa: BLE001
        pass

    code = app.exec()
    _startup_log(f"--- exit code={code}")
    guard.release()
    # 事件循环已经结束 = 该保存的都保存了; 只保证进程一定消失, 不再留幽灵。
    _arm_hard_exit(code)
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
            + _startup_evidence("启动异常")
            + "\n\n"
            + "".join(traceback.format_exception(*sys.exc_info()))[-1200:],
        )
        sys.exit(1)
