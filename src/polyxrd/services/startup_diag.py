"""启动诊断: 查"为什么打不开"。

现场诉求: 关掉程序后双击打不开、要重启电脑。这类问题**进程没起来**时不会留任何
Python 日志, 属于"静默无痕"。本模块提供两件可落地的事:

1. `locked_paths()` —— 逐个尝试以**独占方式**打开 EXE / 关键 DLL,
   报出哪些文件此刻被占用 (典型: 上一次被强杀后, 残留进程或 WER 仍持有映像)。
2. `lock_holders()` —— 用 Windows **Restart Manager API** 反查"是哪个进程占用了它",
   把"重启电脑吧"变成"是 xxx.exe (pid=1234) 占着"。

任何一步失败一律返回空结果 —— 诊断本身绝不能成为新的崩溃点。Qt-free, 可单测。
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_IS_WINDOWS = sys.platform.startswith("win")

# 打包后 _internal 里最关键、最容易被"残留进程"钉住的几个文件
CRITICAL_INTERNAL = (
    "python310.dll",
    "base_library.zip",
    "PySide6/Qt6Core.dll",
    "PySide6/Qt6Gui.dll",
    "PySide6/Qt6Widgets.dll",
    "PySide6/Qt6Network.dll",
)


def dir_writable(directory: os.PathLike[str] | str) -> Optional[bool]:
    """目录能否新建文件。None = 探测本身失败（不参与结论）。"""
    try:
        probe = Path(directory) / ".polyxrd_write_probe"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False
    except Exception:  # noqa: BLE001
        return None


def lock_status(path: str) -> Tuple[bool, Optional[str]]:
    """(是否被占用, 诊断描述)。文件不存在 -> (False, None)。

    判别分三种，**不能只看异常类型**：

    * ``winerror == 32`` (ERROR_SHARING_VIOLATION) —— 确凿的共享冲突，
      有别的进程按独占/写方式拿着它。
    * ``winerror is None`` / ``5`` (拒绝访问) —— CPython 走 io 时经常只带
      ``errno=13`` 而无 winerror，此时用"所在目录能否写新文件"来分辨：
      目录不可写 = 权限不足（装到 Program Files 且非管理员）；目录可写
      却仍打不开 = 确实被映射着（典型就是**本进程自己映射着自己**）。
    * 其它 OSError —— 路径是目录 / 超长路径，不算占用。

    早先只看"是不是 PermissionError"，于是把"没写权限"和"自己映射自己"
    全报成了"被占用"，诊断结论一路指向"重启电脑"（v4.4.0 实测踩过）。
    """
    if not os.path.exists(path):
        return False, None
    try:
        with open(path, "r+b"):
            pass
        return False, None
    except PermissionError as exc:
        winerror = getattr(exc, "winerror", None)
        if winerror == 32:
            return True, "PermissionError(winerror=32, 共享冲突)"
        if dir_writable(Path(path).parent) is False:
            return False, f"无写权限(winerror={winerror})"
        return True, f"PermissionError(winerror={winerror}, 已被映射)"
    except OSError as exc:  # 路径是目录 / 超长路径之类, 不算被占用
        return False, f"{type(exc).__name__}(winerror={getattr(exc, 'winerror', None)})"


def unwritable_paths(exe_path: str) -> List[str]:
    """返回当前用户**没有写权限**的关键文件（只读安装目录的特征）。"""
    out: List[str] = []
    for p in critical_paths(exe_path):
        locked, why = lock_status(p)
        if not locked and why and why.startswith("无写权限"):
            out.append(p)
    return out


def install_dir_writable(exe_path: str) -> Optional[bool]:
    """安装目录能否创建文件。None = 探测本身失败。"""
    return dir_writable(Path(exe_path).resolve().parent)


def critical_paths(exe_path: str) -> List[str]:
    """EXE 本体 + _internal 下关键文件 (存在才收集)。"""
    root = Path(exe_path).resolve().parent
    out: List[str] = [str(Path(exe_path).resolve())]
    internal = root / "_internal"
    for rel in CRITICAL_INTERNAL:
        p = internal / rel
        if p.exists():
            out.append(str(p))
    # 源码运行时没有 _internal, 补一个"本进程正在用的解释器"
    if len(out) == 1 and not internal.exists():
        for rel in ("python310.dll", "python3.dll"):
            p = root / rel
            if p.exists():
                out.append(str(p))
    return out


def locked_paths(exe_path: str) -> List[Tuple[str, str]]:
    """返回 [(文件, 错误描述)] —— 只列被占用的。"""
    res = []
    for p in critical_paths(exe_path):
        locked, why = lock_status(p)
        if locked:
            res.append((p, why or "locked"))
    return res


# ─────────────────────────────────────────────────────────────
# Restart Manager: 反查占用进程
# ─────────────────────────────────────────────────────────────

class _RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwProcessId", ctypes.c_ulong),
        ("ProcessStartTime", ctypes.c_ulong * 2),   # FILETIME
    ]


class _RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("Process", _RM_UNIQUE_PROCESS),
        ("strAppName", ctypes.c_wchar * 256),
        ("strServiceShortName", ctypes.c_wchar * 64),
        ("ApplicationType", ctypes.c_ulong),
        ("AppStatus", ctypes.c_ulong),
        ("TSSessionId", ctypes.c_ulong),
        ("bRestartable", ctypes.c_int),
    ]


CCH_RM_SESSION_KEY = 32
CCH_RM_MAX_APP_NAME = 255
CCH_RM_MAX_SVC_NAME = 63
ERROR_SUCCESS = 0
ERROR_MORE_DATA = 234


def lock_holders(paths: Iterable[str]) -> List[Tuple[str, str, int]]:
    """返回 [(应用名, 映像名, pid)] —— 正在占用给定文件的进程。失败返回 []。"""
    if not _IS_WINDOWS:
        return []
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return []
    try:
        rstrtmgr = ctypes.WinDLL("RstrtMgr", use_last_error=True)
        rstrtmgr.RmStartSession.argtypes = [ctypes.POINTER(ctypes.c_ulong),
                                            ctypes.c_ulong, ctypes.c_wchar_p]
        rstrtmgr.RmStartSession.restype = ctypes.c_ulong
        rstrtmgr.RmRegisterResources.argtypes = [
            ctypes.c_ulong, ctypes.c_uint, ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        rstrtmgr.RmRegisterResources.restype = ctypes.c_ulong
        rstrtmgr.RmGetList.argtypes = [
            ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(_RM_PROCESS_INFO), ctypes.POINTER(ctypes.c_ulong)]
        rstrtmgr.RmGetList.restype = ctypes.c_ulong
        rstrtmgr.RmEndSession.argtypes = [ctypes.c_ulong]
        rstrtmgr.RmEndSession.restype = ctypes.c_ulong
    except OSError:
        return []

    try:
        session = ctypes.c_ulong()
        key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
        rc = rstrtmgr.RmStartSession(ctypes.byref(session), 0, key)
        if rc != ERROR_SUCCESS:
            return []

        try:
            arr = (ctypes.c_wchar_p * len(paths))(*paths)
            rc = rstrtmgr.RmRegisterResources(
                session, len(paths), arr, 0, None, 0, None)
            if rc != ERROR_SUCCESS:
                return []

            need = ctypes.c_ulong(0)
            count = ctypes.c_ulong(0)
            reasons = ctypes.c_ulong(0)
            rc = rstrtmgr.RmGetList(session, ctypes.byref(need),
                                    ctypes.byref(count), None,
                                    ctypes.byref(reasons))
            if rc == ERROR_MORE_DATA and need.value:
                buf = (_RM_PROCESS_INFO * need.value)()
                count = ctypes.c_ulong(need.value)
                rc = rstrtmgr.RmGetList(session, ctypes.byref(need),
                                        ctypes.byref(count), buf,
                                        ctypes.byref(reasons))
                if rc == ERROR_SUCCESS:
                    return [(buf[i].strAppName or "?", "", buf[i].Process.dwProcessId)
                            for i in range(count.value)]
            return []
        finally:
            try:
                rstrtmgr.RmEndSession(session)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        return []


# ─────────────────────────────────────────────────────────────

def diagnose(exe_path: str, extra_note: Optional[str] = None) -> Dict[str, object]:
    """一次性产出一份可写进日志/弹窗的诊断结果。"""
    locked = locked_paths(exe_path)
    holders = lock_holders([p for p, _ in locked]) if locked else []
    me = os.getpid()
    # 自己映射着自己的 exe/dll 是**必然**的, Restart Manager 必然把自己报出来;
    # 那不是"别人占着", 混进结论里只会让人去杀自己的进程。
    others = [h for h in holders if h[2] != me]
    return {
        "exe": exe_path,
        "frozen": bool(getattr(sys, "frozen", False)),
        "frozen_dir": getattr(sys, "_MEIPASS", None),
        "cwd": os.getcwd(),
        "pid": me,
        "python": sys.version.split()[0],
        "locked": locked,
        "holders": others,
        "holders_self": [h for h in holders if h[2] == me],
        "unwritable": unwritable_paths(exe_path),
        "install_dir_writable": install_dir_writable(exe_path),
        "note": extra_note,
    }


def format_report(info: Dict[str, object]) -> str:
    lines = ["=" * 70, "PolyXRD 启动诊断", "=" * 70]
    for k in ("pid", "frozen", "python", "exe", "frozen_dir", "cwd", "note"):
        lines.append(f"{k:<11}: {info.get(k)}")
    lines.append(f"install dir writable: {info.get('install_dir_writable')}")
    locked = info.get("locked") or []
    lines.append(f"locked files: {len(locked)}")
    for path, why in locked:  # type: ignore[misc]
        lines.append(f"  - {path}  [{why}]")
    holders = info.get("holders") or []
    if holders:
        lines.append("占用进程 (Restart Manager):")
        for app, image, pid in holders:  # type: ignore[misc]
            lines.append(f"  - {app or image} pid={pid}")
    elif locked:
        self_mapped = all("已被映射" in str(why) for _, why in locked)  # type: ignore[misc]
        if self_mapped or info.get("holders_self"):
            lines.append(
                "占用进程: 只有本进程自身 (自己映射自己的 exe/dll, 属正常) "
                "-> 不存在外部残留进程"
            )
        else:
            lines.append("占用进程: 未能识别")
    unwritable = info.get("unwritable") or []
    if unwritable:
        # 与"被占用"区分开: 这两种情况的处置完全不同（一个杀进程/重启，
        # 一个装到可写目录或以管理员运行），混在一起只会误导。
        lines.append(f"无写权限的文件: {len(unwritable)}")
        for path in unwritable:  # type: ignore[misc]
            lines.append(f"  - {path}")
        lines.append(
            "  提示: 程序装在只读目录 (如 C:\\Program Files) 且当前不是管理员。"
            "数据目录改到 ~/.polyxrd 即可，无需提权运行。"
        )
    return "\n".join(lines)
