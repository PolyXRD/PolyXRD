"""
`polyxrd.main.main()` 的启动路径护栏 (离屏, 不真开窗口)。

针对的缺陷: `main()` 里 `splash` 只在 `if not pixmap.isNull()` 分支内绑定,
但后面用的是 `if splash_path:` —— 于是当**启动图路径存在却读不出来**
(文件缺失/损坏/非图片) 时会走到 `splash.close()` 而 `splash` 从未赋值,
抛 NameError 崩在 `app.exec()` 之前。

表现极具迷惑性: 进程起来又立刻死, 控制台一闪就关, 连主窗口都不出现 ——
会被误判成"打包坏了"或"环境缺 DLL", 实际上跟打包无关。

这里把 `QApplication.exec` 换成即时返回 + `MainWindow` 换成桩, 于是能只跑
"启动前那一段"而不必真的建整套 UI / 加载 COD 库。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 硬退出看门狗在测试里必须关掉: 测试把 QApplication.exec 换成"立即返回",
# 而测试进程还要跑十几分钟 —— 不关的话 5 秒后 os._exit(0) 会把 pytest 整个干掉。
os.environ.setdefault("POLYXRD_NO_HARD_EXIT", "1")

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

import polyxrd.main as main_mod


@pytest.fixture(scope="session")
def qapp():
    a = QApplication.instance() or QApplication([])
    yield a


class _StubWindow:
    """替掉 MainWindow, 避免加载 COD 库/建全部标签页。"""

    def __init__(self, *_a, **_k) -> None:
        self.shown = False
        self.activated = False

    def show(self) -> None:
        self.shown = True

    def isVisible(self) -> bool:  # noqa: N802 - Qt 命名
        return False

    def activateWindow(self) -> None:
        self.activated = True


class _StubWindowWithoutIsVisible(_StubWindow):
    """没有 isVisible 的窗口桩 —— 记日志不得因此把启动搞崩。"""

    isVisible = None  # type: ignore[assignment]


class _StubGuard:
    """替掉单实例守卫: 单测里不允许真去抢内核互斥量/枚举真实窗口。"""

    def __init__(self, *_a, **_k) -> None:
        self.lock_path = None

    @property
    def is_first(self) -> bool:
        return True

    def release(self) -> None:
        pass

    def existing_window_handles(self) -> list:
        return []

    def activate_existing(self) -> bool:
        return False


def _patch_runtime(monkeypatch, splash_path=None):
    """统一把 QApplication 换成"返回已存在单例"的工厂, 并让 exec 立即返回。"""
    monkeypatch.setattr(main_mod, "get_splash_screen_path", lambda: splash_path)
    monkeypatch.setattr(
        main_mod, "QApplication",
        lambda *a, **k: QApplication.instance(),
    )
    # 不真的进事件循环
    monkeypatch.setattr(
        QApplication, "exec", lambda self=None: 0, raising=False
    )


def _run_main(monkeypatch, splash_path, window_cls=_StubWindow):
    """跑一遍 main(), 立即返回的 exec 代替事件循环。

    `main()` 内部会 `QApplication(sys.argv)`, 但 Qt 只允许一个单例
    (否则 libshiboken 报 "Please destroy the QApplication singleton")。
    这里把 main_mod 里的 QApplication 换成"返回已存在单例"的工厂。
    """
    _patch_runtime(monkeypatch, splash_path)
    monkeypatch.setattr(main_mod, "MainWindow", window_cls)
    monkeypatch.setattr(main_mod, "InstanceGuard", _StubGuard)
    return main_mod.main()


class TestSplashHandling:
    def test_missing_splash_file_does_not_crash(self, qapp, monkeypatch, tmp_path):
        """核心回归: 路径存在但文件不存在 (QPixmap isNull) → 不能崩。"""
        ghost = tmp_path / "nope-splash.png"
        assert not ghost.exists()
        rc = _run_main(monkeypatch, str(ghost))
        assert rc == 0

    def test_corrupt_splash_file_does_not_crash(self, qapp, monkeypatch, tmp_path):
        """有文件但不是合法图片 → QPixmap isNull → 同样不能崩。"""
        bad = tmp_path / "broken.jpg"
        bad.write_bytes(b"this is definitely not a jpeg")
        rc = _run_main(monkeypatch, str(bad))
        assert rc == 0

    def test_real_splash_still_works(self, qapp, monkeypatch):
        """正常情况仍要走 splash 分支 (别为了修崩溃把功能删了)。"""
        from polyxrd.utils.resources import get_splash_screen_path

        assert get_splash_screen_path(), "示例启动图应当随包存在"
        rc = _run_main(monkeypatch, get_splash_screen_path())
        assert rc == 0

    def test_no_splash_path(self, qapp, monkeypatch):
        """资源取不到路径 (None) 时也要正常。"""
        rc = _run_main(monkeypatch, None)
        assert rc == 0


class TestMainContract:
    def test_splash_is_preinitialized(self):
        """静态护栏: splash 必须在 if 之前初始化, 否则又回到同一个坑。"""
        import inspect

        src = inspect.getsource(main_mod.main)
        assert "splash = None" in src or "splash: QSplashScreen | None = None" in src, \
            "splash 必须在 if splash_path 之前初始化为 None"

    def test_guards_on_splash_not_splash_path(self):
        """引用 splash 的条件必须是 `splash is not None`, 不能是 splash_path。"""
        import inspect

        src = inspect.getsource(main_mod.main)
        assert "if splash is not None:" in src, \
            "应当用 `if splash is not None:` 而非 `if splash_path:`"

    def test_returns_app_exec_code(self):
        import inspect

        src = inspect.getsource(main_mod.main)
        # v0.13.0: exec 的返回值先落进启动日志再返回, 故不再是字面
        # `return app.exec()`; 断言要的是"返回值来自事件循环"。
        assert "app.exec()" in src and "return code" in src


class TestStartupRobustness:
    """v1.0.2: 启动稳健性 —— 单实例守卫 / 硬退出看门狗 / 日志不得成为故障点。"""

    def test_window_without_isvisible_does_not_crash(self, qapp, monkeypatch):
        """记日志取 isVisible 失败不许把启动搞崩 (本版真踩过这个坑)。"""
        rc = _run_main(monkeypatch, None, window_cls=_StubWindowWithoutIsVisible)
        assert rc == 0

    def test_hard_exit_watchdog_disabled_under_pytest(self):
        """看门狗在测试里必须不生效: 否则 5s 后 os._exit 会干掉整个 pytest。"""
        assert os.environ.get("POLYXRD_NO_HARD_EXIT") == "1"
        main_mod._arm_hard_exit(0, delay=0.05)
        import time

        time.sleep(0.3)
        # 还活着 —— 说明看门狗没有真的 os._exit
        assert True

    def test_hard_exit_skipped_when_delay_non_positive(self):
        main_mod._arm_hard_exit(0, delay=0)      # 不得抛

    def test_existing_instance_short_circuits(self, qapp, monkeypatch):
        """已有实例且有窗口 -> 不起主窗口, 直接 0 返回 (双击=切回已有窗口)。"""

        class _BusyGuard(_StubGuard):
            @property
            def is_first(self) -> bool:
                return False

            def existing_window_handles(self) -> list:
                return [12345]

            def activate_existing(self) -> bool:
                return True

        class _ExplodingWindow:
            def __init__(self, *_a, **_k) -> None:
                raise AssertionError("已有实例时不应再建主窗口")

        monkeypatch.setattr(main_mod, "InstanceGuard", _BusyGuard)
        monkeypatch.setattr(main_mod, "MainWindow", _ExplodingWindow)
        _patch_runtime(monkeypatch)
        assert main_mod.main() == 0

    def test_windowless_instance_still_starts(self, qapp, monkeypatch):
        """幽灵实例 (没有窗口) -> fail-open, 照常启动, 保证双击一定出窗口。"""
        calls = {"n": 0}

        class _ZombieGuard(_StubGuard):
            @property
            def is_first(self) -> bool:
                return False

            def existing_window_handles(self) -> list:
                return []

        class _CountingWindow(_StubWindow):
            def __init__(self, *_a, **_k) -> None:
                calls["n"] += 1
                super().__init__(*_a, **_k)

        monkeypatch.setattr(main_mod, "InstanceGuard", _ZombieGuard)
        monkeypatch.setattr(main_mod, "MainWindow", _CountingWindow)
        _patch_runtime(monkeypatch)
        assert main_mod.main() == 0
        assert calls["n"] == 1, "无窗口的残留实例不得拦住启动"

    # ── 保守渲染开关 (现场取证后新增) ────────────────────────

    def test_safe_render_overrides_applied(self, monkeypatch):
        """--safe-render: 三个 QT 环境变量被设置, 未知参数从 argv 清除。"""
        for var in ("QT_OPENGL", "QT_QPA_PLATFORM", "QT_ENABLE_HIGHDPI_SCALING"):
            monkeypatch.delenv(var, raising=False)
        argv = main_mod._apply_safe_render_overrides(["prog", "--safe-render"])
        assert argv == ["prog"]
        assert os.environ["QT_OPENGL"] == "software"
        assert os.environ["QT_QPA_PLATFORM"] == "windows:darkmode=0"
        assert os.environ["QT_ENABLE_HIGHDPI_SCALING"] == "0"

    def test_safe_render_env_var_trigger(self, monkeypatch):
        """POLYXRD_SAFE_RENDER=1 与 --safe-render 等效。"""
        monkeypatch.setenv("POLYXRD_SAFE_RENDER", "1")
        monkeypatch.delenv("QT_OPENGL", raising=False)
        argv = main_mod._apply_safe_render_overrides(["prog"])
        assert argv == ["prog"]
        assert os.environ["QT_OPENGL"] == "software"

    def test_safe_render_off_by_default(self, monkeypatch):
        """默认不开: 未设开关时不得污染环境。"""
        monkeypatch.delenv("POLYXRD_SAFE_RENDER", raising=False)
        for var in ("QT_OPENGL", "QT_QPA_PLATFORM", "QT_ENABLE_HIGHDPI_SCALING"):
            monkeypatch.delenv(var, raising=False)
        argv = main_mod._apply_safe_render_overrides(["prog"])
        assert argv == ["prog"]
        assert "QT_OPENGL" not in os.environ
        assert "QT_QPA_PLATFORM" not in os.environ
        assert "QT_ENABLE_HIGHDPI_SCALING" not in os.environ

    def test_safe_render_respects_user_env(self, monkeypatch):
        """setdefault 语义: 用户显式设置的变量不被覆盖。"""
        monkeypatch.setenv("POLYXRD_SAFE_RENDER", "1")
        monkeypatch.setenv("QT_OPENGL", "desktop")
        main_mod._apply_safe_render_overrides(["prog", "--safe-render"])
        assert os.environ["QT_OPENGL"] == "desktop"
