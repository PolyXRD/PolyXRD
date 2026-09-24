"""
M20 v2 主窗口高级交互测试 (Sprint 3 收尾)
=========================================
覆盖: 拖放文件打开 — 静态辅助函数与类方法存在性。
GUI 拖放手势本身需要真实坐标事件, 在 offscreen 下难以稳定复现; 此处仅
单测可解耦的纯函数与管道存在性, 端到端拖放靠人工验收。
"""
import os

# 必须在 import 任何 PySide6 模块之前设好, 否则 offscreen 平台插件不生效
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from polyxrd.models.peak import Peak
from polyxrd.views.main_window import MainWindow


class TestDragDropPlumbing:
    """拖放管道: 关键方法存在, 静态辅助函数行为正确。"""

    def test_drag_events_present(self):
        for name in ("dragEnterEvent", "dragMoveEvent", "dropEvent"):
            assert hasattr(MainWindow, name), name

    def test_shared_load_helper_present(self):
        assert hasattr(MainWindow, "_load_file_path")

    def test_set_accept_drops_in_init(self):
        import inspect
        # setAcceptDrops 实际在 _setup_ui (由 __init__ 调用) 中; 检查整个类源
        src = inspect.getsource(MainWindow)
        assert "setAcceptDrops(True)" in src


class TestFirstLocalPath:
    """_first_local_path: 从候选路径列表中取第一个非空本地文件路径。"""

    def test_first_of_many(self):
        assert MainWindow._first_local_path(["/tmp/a.xy", "/tmp/b.xy"]) == "/tmp/a.xy"

    def test_empty_list_returns_none(self):
        assert MainWindow._first_local_path([]) is None

    def test_skip_empty_string(self):
        assert MainWindow._first_local_path(["", "/x"]) == "/x"

    def test_skip_none(self):
        # None 与 "" 都视为无效, 跳过取下一个非空
        assert MainWindow._first_local_path([None, "/y"]) == "/y"

    def test_all_empty_returns_none(self):
        assert MainWindow._first_local_path([None, ""]) is None


# ------------------------------------------------------------------
# M20 v2: 主题切换 + 峰表右键菜单 (需要 QApplication, offscreen)
# ------------------------------------------------------------------
import pytest

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestTheme:
    """主题: 调色板构建与应用。"""

    def test_palettes_differ(self):
        from PySide6.QtGui import QPalette

        from polyxrd.views.theme import build_dark_palette, build_light_palette

        dark = build_dark_palette()
        light = build_light_palette()
        assert (dark.color(QPalette.ColorRole.Window) !=
                light.color(QPalette.ColorRole.Window))
        assert (dark.color(QPalette.ColorRole.Base) !=
                light.color(QPalette.ColorRole.Base))

    def test_apply_theme_none_app_noop(self):
        from polyxrd.views.theme import apply_theme

        assert apply_theme(None, dark=True) is None  # 不抛异常即可

    def test_apply_theme_changes_palette(self, qapp):
        from polyxrd.views.theme import apply_theme, build_light_palette

        from PySide6.QtGui import QPalette

        apply_theme(qapp, dark=True)
        dark_win = qapp.palette().color(QPalette.ColorRole.Window)
        apply_theme(qapp, dark=False)
        light_win = qapp.palette().color(QPalette.ColorRole.Window)
        assert dark_win != light_win
        # 收尾: 还原浅色, 不影响其他测试
        qapp.setPalette(build_light_palette())


class TestPeakTableContextMenu:
    """峰表右键菜单管道。"""

    def _make_table(self):
        from polyxrd.views.widgets.peak_table import PeakTable

        pt = PeakTable()
        pt.set_peaks([
            Peak(two_theta=28.44, intensity=1000.0, fwhm=0.12, d_spacing=3.135),
            Peak(two_theta=47.30, intensity=600.0, fwhm=0.12, d_spacing=1.920),
        ])
        return pt

    def test_custom_context_menu_policy(self, qapp):
        from PySide6.QtCore import Qt

        pt = self._make_table()
        assert (pt._table.contextMenuPolicy() ==
                Qt.ContextMenuPolicy.CustomContextMenu)

    def test_copy_selected_to_clipboard(self, qapp):
        from PySide6.QtGui import QGuiApplication

        pt = self._make_table()
        pt._table.selectRow(0)   # 视觉行 (重载后表格已按排序指示器重排, 顺序不保证)
        pt._copy_selected_to_clipboard()
        text = QGuiApplication.clipboard().text()
        lines = text.splitlines()
        assert len(lines) == 2                       # 表头 + 1 行
        assert lines[0].startswith("编号")
        # 行内容应为某个峰的完整行 (前 5 列非空: 编号/2θ/d/I/FWHM)
        cells = lines[1].split("\t")
        assert len(cells) == 7
        assert all(c != "" for c in cells[:5])
        assert ("28.4400" in lines[1]) or ("47.3000" in lines[1])

    def test_copy_empty_selection(self, qapp):
        from PySide6.QtGui import QGuiApplication

        pt = self._make_table()
        pt._table.clearSelection()
        pt._copy_selected_to_clipboard()
        text = QGuiApplication.clipboard().text()
        assert len(text.splitlines()) == 1           # 仅表头