"""单实例守卫与启动诊断的单元测试 (Qt-free, 快)。

重点验证"稳健性"命题: **上一次异常退出 / 强杀, 绝不能让下一次启动打不开**。
其中 `test_kill_safe_*` 是真正跨进程的取证 —— 起一个子进程占住守卫,
再把它强杀, 父进程必须能立刻重新拿到。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from polyxrd.services import startup_diag  # noqa: E402
from polyxrd.services.instance_guard import (  # noqa: E402
    InstanceGuard,
    _acquire_lock_file,
    _pid_alive,
    _release_lock_file,
    default_lock_dir,
)

GUARD_PY = SRC / "polyxrd" / "services" / "instance_guard.py"


def _uniq_mutex() -> str:
    return f"Local\\PolyXRD.UnitTest.{os.getpid()}.{uuid.uuid4().hex}"


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _spawn_holder(mutex_name: str, lock_dir: Path) -> subprocess.Popen:
    """子进程: 直接按文件路径加载 instance_guard (绕开包 __init__ 的重依赖),
    占住守卫后打印 FIRST=... 并一直活着。"""
    code = (
        "import importlib.util, sys, time\n"
        "spec = importlib.util.spec_from_file_location('ig', r'%s')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "from pathlib import Path\n"
        "g = m.InstanceGuard(Path(r'%s'), mutex_name=r'%s')\n"
        "print('FIRST=%%s' %% g.is_first, flush=True)\n"
        "time.sleep(120)\n"
    ) % (str(GUARD_PY), str(lock_dir), mutex_name)
    return subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


# ── 互斥量 / 单实例 ────────────────────────────────────────────────

def test_first_instance_is_first(tmp_path):
    g = InstanceGuard(tmp_path, mutex_name=_uniq_mutex())
    assert g.is_first is True
    g.release()


def test_second_instance_same_process_is_not_first(tmp_path):
    name = _uniq_mutex()
    g1 = InstanceGuard(tmp_path, mutex_name=name)
    g2 = InstanceGuard(tmp_path, mutex_name=name)
    assert g1.is_first is True
    assert g2.is_first is False
    g2.release()
    g1.release()


def test_kill_safe_cross_process(tmp_path):
    """核心取证: 子进程占着守卫被强杀后, 新实例必须立刻能起。"""
    name = _uniq_mutex()
    proc = _spawn_holder(name, tmp_path)
    try:
        line = (proc.stdout.readline() or "").strip()
        assert line == "FIRST=True", f"子进程未能占住守卫: {line!r}"

        g = InstanceGuard(tmp_path, mutex_name=name)
        assert g.is_first is False, "已有实例在跑时必须能检测到"
        g.release()                      # 父进程不再持有句柄

        proc.kill()                      # == 任务管理器"结束任务"
        proc.wait(timeout=20)
        time.sleep(0.5)

        g2 = InstanceGuard(tmp_path, mutex_name=name)
        assert g2.is_first is True, "上一实例被强杀后, 新实例必须能启动 (kill-safe)"
        g2.release()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=20)


def test_window_probe_smoke(tmp_path):
    g = InstanceGuard(tmp_path, mutex_name=_uniq_mutex())
    assert isinstance(g.existing_window_handles(), list)
    assert g.activate_existing() in (True, False)
    assert g.existing_but_windowless() in (True, False)
    g.release()


def test_default_lock_dir_points_to_user_dir():
    assert default_lock_dir().name == ".polyxrd"


# ── 锁文件回退路径 (跨平台可测) ────────────────────────────────────

def test_pid_alive_self_and_dead():
    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(_dead_pid()) is False
    assert _pid_alive(-1) is False
    assert _pid_alive(0) is False


def test_lock_file_roundtrip(tmp_path):
    p = tmp_path / "instance.lock"
    assert _acquire_lock_file(p) is True
    assert p.read_text(encoding="ascii").strip() == str(os.getpid())
    assert _acquire_lock_file(p) is False      # 自己还活着 -> 第二次拿不到
    _release_lock_file(p)
    assert not p.exists()
    assert _acquire_lock_file(p) is True       # 释放后又能拿到
    _release_lock_file(p)


def test_stale_lock_file_is_taken_over(tmp_path):
    """陈旧锁 (持有者已死) 必须被自愈, 而不是把用户永久挡在门外。"""
    p = tmp_path / "instance.lock"
    p.write_text(str(_dead_pid()), encoding="ascii")
    assert _acquire_lock_file(p) is True
    assert p.read_text(encoding="ascii").strip() == str(os.getpid())
    _release_lock_file(p)


def test_garbage_lock_file_is_taken_over(tmp_path):
    p = tmp_path / "instance.lock"
    p.write_text("not-a-pid", encoding="ascii")
    assert _acquire_lock_file(p) is True
    _release_lock_file(p)


# ── 启动诊断 ──────────────────────────────────────────────────────

def test_lock_status_missing_file(tmp_path):
    assert startup_diag.lock_status(str(tmp_path / "nope.bin")) == (False, None)


def test_lock_status_free_file(tmp_path):
    f = tmp_path / "free.bin"
    f.write_bytes(b"x")
    assert startup_diag.lock_status(str(f)) == (False, None)


def test_critical_paths_puts_exe_first():
    paths = startup_diag.critical_paths(sys.executable)
    assert paths, "至少要包含 EXE 本体"
    assert os.path.normcase(paths[0]) == os.path.normcase(
        str(Path(sys.executable).resolve()))


def test_locked_paths_and_holders_smoke():
    """正向取证: 当前进程自己的解释器映像必然"被占用",
    Restart Manager 应能把本进程报出来 (拿不到也不许抛)。"""
    locked = startup_diag.locked_paths(sys.executable)
    assert isinstance(locked, list)
    for path, why in locked:
        assert isinstance(path, str) and isinstance(why, str)
    holders = startup_diag.lock_holders([sys.executable])
    assert isinstance(holders, list)
    for app, _image, pid in holders:
        assert isinstance(app, str)
        assert isinstance(pid, int)


def test_diagnose_and_format_report():
    info = startup_diag.diagnose(sys.executable, extra_note="unit-test")
    assert info["pid"] == os.getpid()
    assert info["exe"] == sys.executable
    text = startup_diag.format_report(info)
    assert "启动诊断" in text
    assert sys.executable in text
    assert "unit-test" in text
    assert "locked files:" in text
