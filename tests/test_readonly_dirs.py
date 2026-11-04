"""只读/不可写路径下的行为守护（P1-2，v4.5.0 欠账）。

v4.4.0 装机事故链：``get_config()`` 对 ``C:\\Program Files\\PolyXRD\\cod_data``
无条件 ``mkdir`` → ``PermissionError(5)`` → 进程连窗口都出不来（待办 P0-1 A 组）。
v4.5.0 的修复（``_ensure_dir`` 吞 OSError + ``_default_cif_db_dir`` 回退用户目录）
全部发生在"目录不可写"分支，而现有用例全在可写的 ``tmp_path`` 里跑 ——
这两个 bug 若被后人改回去，回归不会报警。本文件把三道防线钉死：

1. ``_ensure_dir``：路径被文件挡住 / mkdir 抛 OSError 时返回 ``False`` 且**绝不抛**；
2. ``_default_cif_db_dir``：项目内目录不存在时回退用户目录，且**解析函数无副作用**
   （不 mkdir —— 那是无写权限场景下唯一的安全解）；
3. ``startup_diag.lock_status`` / ``dir_writable``：只读文件（winerror≠32）在
   可写/不可写目录下的三态判别 —— 不能把"没写权限"和"被占用"混为一谈
   （v4.4.0 实测踩过，结论一路指向"重启电脑"）。

Windows 上目录本身的只读属性拦不住"新建文件"，所以"目录不可写"用两个
确定性替代：``_ensure_dir`` 用文件挡路、``lock_status`` 用 ``monkeypatch``
钉 ``dir_writable`` —— 两处都不依赖 icacls，任何环境可复现。
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import polyxrd.config as config_mod  # noqa: E402
from polyxrd.config import AppConfig, _ensure_dir, get_config  # noqa: E402
from polyxrd.services import startup_diag  # noqa: E402


# ──────────────────────────────────────────────────────────────
# _ensure_dir
# ──────────────────────────────────────────────────────────────
class TestEnsureDir:
    def test_creates_nested_missing_dir(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"
        assert _ensure_dir(target) is True
        assert target.is_dir()

    def test_file_blocked_path_returns_false_not_raise(self, tmp_path):
        """路径被**文件**挡住（mkdir 必抛 FileExistsError ⊂ OSError）。"""
        blocker = tmp_path / "x"
        blocker.write_text("i am a file")
        assert _ensure_dir(blocker) is False
        assert blocker.is_file()  # 原文件被动过没？不能动

    def test_never_raises_on_permission_error(self, tmp_path, monkeypatch):
        """mkdir 抛 PermissionError 必须被吞成 False（v4.4.0 事故的根）。"""

        def boom(self, *a, **k):
            raise PermissionError(5, "access denied")

        monkeypatch.setattr(Path, "mkdir", boom)
        assert _ensure_dir(tmp_path / "nope") is False

    def test_existing_dir_is_true(self, tmp_path):
        assert _ensure_dir(tmp_path) is True


# ──────────────────────────────────────────────────────────────
# _default_cif_db_dir
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def fake_root(tmp_path, monkeypatch):
    monkeypatch.setattr(AppConfig, "_PROJECT_ROOT", tmp_path)
    return tmp_path


class TestDefaultCifDbDir:
    def test_prefers_project_dir_when_present(self, fake_root):
        want = fake_root / "cod_data" / "cif_db"
        want.mkdir(parents=True)
        assert AppConfig._default_cif_db_dir() == want

    def test_falls_back_to_user_dir_when_absent(self, fake_root):
        """项目内目录不存在 → 回退 ~/.polyxrd/cif_db（v4.4.0 修复的正面）。"""
        got = AppConfig._default_cif_db_dir()
        assert got == Path.home() / AppConfig._HOME_CIF_DB_REL
        assert got != fake_root / "cod_data" / "cif_db"

    def test_falls_back_when_blocked_by_file(self, fake_root):
        """目录位被文件占住 = is_dir() False → 同样回退，且不炸。"""
        fake_root.joinpath("cod_data").mkdir()
        fake_root.joinpath("cod_data", "cif_db").write_text("file")
        assert AppConfig._default_cif_db_dir() == (
            Path.home() / AppConfig._HOME_CIF_DB_REL)

    def test_resolution_has_no_side_effect(self, fake_root):
        """解析函数**不得 mkdir** —— 只读安装目录下这是唯一的安全解。

        回归 v4.4.0：get_config() 无条件 mkdir 的行为若被搬回这里，
        普通用户装机即 PermissionError。
        """
        AppConfig._default_cif_db_dir()
        assert not (fake_root / "cod_data" / "cif_db").exists()


class TestGetConfigUnwritable:
    @pytest.fixture()
    def reset_singleton(self):
        old = config_mod._config
        config_mod._config = None
        yield
        config_mod._config = old

    def test_survives_all_three_dirs_blocked(self, tmp_path, monkeypatch,
                                             reset_singleton):
        """cif_db / export / log 三个落点全被文件挡住 → get_config 仍返回实例。

        对应现场事故：装在 Program Files、普通用户，三个 mkdir 全炸 ——
        正确行为是静默降级，让主窗口照常起来。
        """
        monkeypatch.setattr(AppConfig, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "cod_data").mkdir()
        for rel in (("cod_data", "cif_db"), ("exports",), ("logs",)):
            tmp_path.joinpath(*rel).write_text("blocked")
        cfg = get_config()
        assert cfg is not None
        # 实例字段仍是"解析出的路径"（哪怕建不出来），不做偷偷替换
        assert Path(cfg.cif_db_path).name == "cif_db"


# ──────────────────────────────────────────────────────────────
# startup_diag.dir_writable / lock_status
# ──────────────────────────────────────────────────────────────
class TestDirWritable:
    def test_writable_dir_true(self, tmp_path):
        assert startup_diag.dir_writable(tmp_path) is True

    def test_missing_dir_false(self, tmp_path):
        assert startup_diag.dir_writable(tmp_path / "nope") is False

    def test_file_as_dir_false(self, tmp_path):
        f = tmp_path / "f"
        f.write_text("x")
        assert startup_diag.dir_writable(f) is False

    def test_unexpected_exception_returns_none(self, tmp_path, monkeypatch):
        """OSError 之外的异常 = 探测失败 → None（不参与结论，也别炸调用方）。"""

        def boom(self, data):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(Path, "write_bytes", boom)
        assert startup_diag.dir_writable(tmp_path) is None


class TestLockStatusReadonly:
    @staticmethod
    def _readonly_file(tmp_path):
        f = tmp_path / "ro.bin"
        f.write_bytes(b"data")
        os.chmod(f, stat.S_IREAD)  # 只读属性：open('r+b') → PermissionError
        return f

    @pytest.mark.skipif(not sys.platform.startswith("win"),
                        reason="POSIX 下 root 可绕过只读位，判别不稳")
    def test_readonly_file_in_writable_dir_maps_as_locked(self, tmp_path):
        """只读文件 + 目录可写 → 按"已被映射"报（现状语义：自己映射自己）。

        这是 lock_status 判别表里 winerror∈{None,5} 且目录可写 的分支 ——
        若有人把 PermissionError 一刀切回"被占用"，这里先红。
        """
        f = self._readonly_file(tmp_path)
        try:
            locked, why = startup_diag.lock_status(str(f))
            assert locked is True
            assert why is not None and "已被映射" in why
        finally:
            os.chmod(f, stat.S_IWRITE)  # 让 tmp_path 能清理

    def test_readonly_file_in_unwritable_dir_reports_no_permission(
            self, tmp_path, monkeypatch):
        """只读文件 + 目录不可写 → 报"无写权限"，**不得**算成被占用。

        monkeypatch dir_writable 替代 icacls：判定逻辑本身才是被测对象。
        """
        f = self._readonly_file(tmp_path)
        monkeypatch.setattr(startup_diag, "dir_writable",
                            lambda d: False)
        try:
            locked, why = startup_diag.lock_status(str(f))
            assert locked is False
            assert why is not None and why.startswith("无写权限")
        finally:
            os.chmod(f, stat.S_IWRITE)

    def test_sharing_violation_is_locked(self, tmp_path, monkeypatch):
        """winerror=32（ERROR_SHARING_VIOLATION）→ 确凿被占用，与权限无关。"""
        f = tmp_path / "busy.bin"
        f.write_bytes(b"data")
        real_open = open

        def fake_open(file, mode="r", *a, **k):
            if str(file) == str(f) and "b" in mode and "+" in mode:
                exc = PermissionError(32, "sharing violation")
                exc.winerror = 32
                raise exc
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        locked, why = startup_diag.lock_status(str(f))
        assert locked is True
        assert why is not None and "32" in why

    def test_unwritable_paths_picks_no_permission_only(self, tmp_path,
                                                       monkeypatch):
        """unwritable_paths 只收"无写权限"项，被占用项不得混入。"""
        f = tmp_path / "ro.bin"
        f.write_bytes(b"data")
        os.chmod(f, stat.S_IREAD)
        monkeypatch.setattr(startup_diag, "dir_writable", lambda d: False)
        monkeypatch.setattr(startup_diag, "critical_paths",
                            lambda exe: [str(f)])
        try:
            assert startup_diag.unwritable_paths("whatever.exe") == [str(f)]
        finally:
            os.chmod(f, stat.S_IWRITE)
