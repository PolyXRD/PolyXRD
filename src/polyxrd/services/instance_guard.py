"""单实例守卫 (kill-safe, 失败即放行)。

设计目标 —— 直接对应"关掉再打开打不开 / 必须重启电脑"这一类现场问题:

1. **绝不能因为上一次异常退出而拦住这一次启动**。
   所以不用"锁文件存在即视为在运行"这种写法 (那是崩溃后就永久卡死的经典写法),
   而是用**内核对象**: Windows 命名互斥量 (named mutex)。进程一死, 内核立刻回收,
   下一次启动必然拿得到 —— 哪怕上次是被任务管理器强杀的。
2. **已经有实例在跑时, 双击要把它的窗口拉出来**, 而不是默默什么都不做
   (用户视角:"双击没反应")。
3. **拿不准就放行** (fail-open)。任何异常 / 不支持的平台 / 无法判断的情况,
   一律返回"你是第一个实例", 保证双击总能出窗口。

模块保持 Qt-free (只依赖标准库 + ctypes), 便于单测。
"""
from __future__ import annotations

import atexit
import ctypes
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

MUTEX_NAME = "Local\\PolyXRD.SingleInstance.v1"
LOCK_FILE_NAME = "instance.lock"

_IS_WINDOWS = sys.platform.startswith("win")


# ─────────────────────────────────────────────────────────────
# 互斥量 (Windows) —— kill-safe 的核心
# ─────────────────────────────────────────────────────────────

def _acquire_windows_mutex(name: str = MUTEX_NAME) -> Tuple[bool, Optional[int]]:
    """返回 (是否首个实例, 句柄)。任何异常都返回 (True, None) —— 失败即放行。"""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return True, None

    try:
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_wchar_p]
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, 0, name)
        err = ctypes.get_last_error()
        if not handle:
            return True, None
        ERROR_ALREADY_EXISTS = 183
        if err == ERROR_ALREADY_EXISTS:
            # 已经有人在跑: 句柄仍要留着 (关掉它不影响对方), 但本次不是首个
            return False, int(handle)
        return True, int(handle)
    except Exception:  # noqa: BLE001
        return True, None


def _release_windows_handle(handle: Optional[int]) -> None:
    if not handle:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────────────────────────────────────────
# 锁文件 (非 Windows 回退) —— 带"陈旧锁"自愈
# ─────────────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _IS_WINDOWS:
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32.OpenProcess.restype = ctypes.c_void_p
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(ctypes.c_void_p(h),
                                             ctypes.byref(code))
            kernel32.CloseHandle(ctypes.c_void_p(h))
            return bool(ok) and code.value == STILL_ACTIVE
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    except Exception:  # noqa: BLE001
        return True          # 判断不了就当活着 (保守)
    return True


def _acquire_lock_file(path: Path) -> bool:
    """O_EXCL 建锁; 若锁陈旧 (持有者已死) 则抢占。失败即放行。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return True

    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            holder = -1
            try:
                holder = int(path.read_text(encoding="ascii").strip() or "-1")
            except (OSError, ValueError):
                holder = -1
            if holder > 0 and _pid_alive(holder):
                return False
            # 陈旧锁 (持有者已死) -> 删掉重抢; 删不掉也别卡着
            try:
                path.unlink()
            except OSError:
                return True
        except OSError:
            return True
    return True


def _release_lock_file(path: Path) -> None:
    try:
        if path.exists() and path.read_text(encoding="ascii").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────
# 对外接口
# ─────────────────────────────────────────────────────────────

class InstanceGuard:
    """进程级单实例守卫。用法:

        guard = InstanceGuard(lock_dir)
        if not guard.is_first:
            guard.activate_existing()      # 把已在跑的窗口拉到前台
            ... 然后正常退出
        # 首个实例 -> 继续启动; 退出时 guard.release()
    """

    def __init__(self, lock_dir: Optional[Path] = None,
                 mutex_name: str = MUTEX_NAME) -> None:
        self.lock_path = (Path(lock_dir) if lock_dir else Path.home() / ".polyxrd") \
            / LOCK_FILE_NAME
        self.mutex_name = mutex_name
        self._handle: Optional[int] = None
        self._used_mutex = False
        self._is_first = True
        self.acquire()

    # -- 获取 / 释放 --------------------------------------------------
    def acquire(self) -> bool:
        if _IS_WINDOWS:
            first, handle = _acquire_windows_mutex(self.mutex_name)
            self._handle = handle
            self._used_mutex = True
            self._is_first = first
        else:
            self._is_first = _acquire_lock_file(self.lock_path)
        if self._is_first:
            atexit.register(self.release)
        return self._is_first

    def release(self) -> None:
        if self._used_mutex:
            _release_windows_handle(self._handle)
            self._handle = None
        else:
            _release_lock_file(self.lock_path)

    @property
    def is_first(self) -> bool:
        return self._is_first

    # -- 与已有实例交互 ----------------------------------------------
    def existing_window_handles(self) -> List[int]:
        """枚举"别的 PolyXRD 进程"的顶层窗口 (只看标题/类名, 不去猜进程)。"""
        if not _IS_WINDOWS:
            return []
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
        except OSError:
            return []

        found: List[int] = []
        self_pid = os.getpid()
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                         ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return 1
                n = user32.GetWindowTextLengthW(hwnd)
                if n <= 0:
                    return 1
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value or ""
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                cls_name = cls.value or ""
                if not (title.startswith("PolyXRD") or "QWindowIcon" in cls_name):
                    return 1
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd),
                                                ctypes.byref(pid))
                if pid.value and pid.value != self_pid:
                    found.append(int(hwnd))
            except Exception:  # noqa: BLE001
                pass
            return 1

        try:
            user32.EnumWindows(WNDENUMPROC(_cb), None)
        except Exception:  # noqa: BLE001
            return []
        return found

    def activate_existing(self) -> bool:
        """把已在运行的实例窗口拉到前台。

        返回 True = **找到了已有实例的窗口** (并且已经尽力把它显形/闪烁提醒)。
        注意: Windows 有"前台锁定"(ForegroundLockTimeout), 后台进程调用
        `SetForegroundWindow` 经常直接返回失败 —— 那是系统策略, **不代表没有窗口**。
        所以这里只要找到窗口就算成功, 抢不到焦点就退回 `FlashWindowEx` 闪任务栏,
        绝不再因此误判成"没有窗口"而多起一个实例。
        """
        if not _IS_WINDOWS:
            return False
        handles = self.existing_window_handles()
        if not handles:
            return False
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            SW_RESTORE = 9
            HWND_TOP = 0
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            FLASHW_ALL = 3
            FLASHW_TIMERNOFG = 12

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint),
                            ("hwnd", ctypes.c_void_p),
                            ("dwFlags", ctypes.c_uint),
                            ("uCount", ctypes.c_uint),
                            ("dwTimeout", ctypes.c_uint)]

            for hwnd in handles:
                h = ctypes.c_void_p(hwnd)
                user32.ShowWindow(h, SW_RESTORE)
                focused = bool(user32.SetForegroundWindow(h))
                if not focused:
                    # 前台锁定挡着: 至少把它显式置顶 + 闪任务栏, 让用户看得见
                    try:
                        user32.BringWindowToTop(h)
                        user32.SetWindowPos(h, ctypes.c_void_p(HWND_TOP), 0, 0, 0, 0,
                                            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), h,
                                          FLASHW_ALL | FLASHW_TIMERNOFG, 3, 0)
                        user32.FlashWindowEx(ctypes.byref(info))
                    except Exception:  # noqa: BLE001
                        pass
            return True
        except Exception:  # noqa: BLE001
            return True          # 窗口确实在, 只是没能摆弄它 —— 仍按"找到"处理

    def existing_but_windowless(self) -> bool:
        """有人在跑, 但找不到窗口 —— 僵尸实例特征 (关不掉 / 没窗口)。"""
        return (not self.is_first) and not self.existing_window_handles()


def default_lock_dir() -> Path:
    """与 main.py 的日志目录同源, 避免两处各写一份 ~/.polyxrd。"""
    return Path.home() / ".polyxrd"
