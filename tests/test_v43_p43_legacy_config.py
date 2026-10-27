"""v4.3.0 P4.3 —— 旧库配置检测与一次性清理。

三件事必须钉住：

1. **只清配置、不删库文件**——旧 ``COD_inorganics.sqlite`` 可能还被别处
   使用，自动删文件是不可接受的副作用；
2. **只动旧键**——``user_db_paths.json`` 里还住着 polyDB 槽位与
   ``polydb_disabled``，整体覆盖写会把它们悄悄抹掉；
3. **"稍后"按版本记住**——不重复打扰，但升级后要再问一次。

所有用例都在 ``tmp_path`` 里造配置文件，并 monkeypatch
``db_mounts._store_file``，绝不碰真机 ``~/.polyxrd``。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.services import legacy_config as L  # noqa: E402


# ── 夹具 ──────────────────────────────────────────────────

@pytest.fixture()
def cfg_files(tmp_path):
    """返回 (paths_file, store_file) 两个空路径（父目录已建）。"""
    paths = tmp_path / "user_db_paths.json"
    store = tmp_path / "db_mounts.json"
    return paths, store


@pytest.fixture()
def legacy_sqlite(tmp_path):
    """一个"旧库文件"，用体积可断言（写了 2 MB 稀疏内容）。"""
    f = tmp_path / "COD_inorganics.sqlite"
    f.write_bytes(b"\0" * (2 * 1024 * 1024))
    return f


def _write(paths_file: Path, store_file: Path, paths: dict, store: dict) -> None:
    paths_file.write_text(json.dumps(paths, ensure_ascii=False), encoding="utf-8")
    store_file.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


# ── 盘点 ──────────────────────────────────────────────────

class TestScan:
    def test_no_files_means_no_legacy(self, cfg_files):
        paths, store = cfg_files
        rep = L.scan(paths, store)
        assert not rep and len(rep) == 0

    def test_detects_legacy_sqlite_key(self, cfg_files, legacy_sqlite):
        paths, store = cfg_files
        _write(paths, store,
               {"cod_db_path": str(legacy_sqlite),
                "polydb_inorg_path": "D:/x/polyDB"},
               {"version": 1, "active": "", "mounts": []})
        rep = L.scan(paths, store)
        assert rep and len(rep) == 1
        item = rep.items[0]
        assert item.key == "cod_db_path"
        assert item.source == "user_db_paths"
        assert item.exists is True
        # MB = 1e6 字节（与 db_mounts 的统计口径一致），2 MiB ≈ 2.1 MB
        assert item.size_mb == pytest.approx(
            legacy_sqlite.stat().st_size / 1e6, abs=0.05)
        assert item.is_polydb is False

    def test_missing_path_still_reported(self, cfg_files, tmp_path):
        paths, store = cfg_files
        _write(paths, store,
               {"cod_index_db_path": str(tmp_path / "gone.sqlite")},
               {"version": 1, "active": "", "mounts": []})
        rep = L.scan(paths, store)
        assert rep and rep.items[0].exists is False
        assert rep.items[0].size_mb == 0.0
        assert rep.existing == ()          # 不占地方 → 不算"仍存在"

    def test_modern_keys_are_not_legacy(self, cfg_files):
        paths, store = cfg_files
        _write(paths, store,
               {"polydb_inorg_path": "D:/a", "polydb_full_path": "D:/b",
                "pdf2_db_path": "D:/c", "polydb_disabled": ["cod-full"]},
               {"version": 1, "active": "", "mounts": []})
        assert not L.scan(paths, store)

    def test_detects_legacy_mount_kind_and_active(self, cfg_files):
        paths, store = cfg_files
        _write(paths, store, {},
               {"version": 1, "active": "cod_index:abcd1234",
                "mounts": [{"id": "cod_index:abcd1234", "kind": "cod_index",
                            "path": "D:/old/cod_index.sqlite"}]})
        rep = L.scan(paths, store)
        keys = rep.keys()
        assert "cod_index:abcd1234" in keys
        active = [i for i in rep.items if i.source == "db_mounts_active"]
        assert len(active) == 1 and active[0].key == "cod_index:abcd1234"

    def test_corrupt_json_is_ignored(self, cfg_files):
        paths, store = cfg_files
        paths.write_text("{not json", encoding="utf-8")
        store.write_text("[]", encoding="utf-8")
        assert not L.scan(paths, store)

    def test_report_aggregates_size(self, cfg_files, legacy_sqlite, tmp_path):
        paths, store = cfg_files
        other = tmp_path / "cod_index.sqlite"
        other.write_bytes(b"\0" * (1024 * 1024))
        _write(paths, store,
               {"cod_db_path": str(legacy_sqlite),
                "cod_index_db_path": str(other)},
               {"version": 1, "active": "", "mounts": []})
        rep = L.scan(paths, store)
        assert len(rep.existing) == 2
        assert rep.total_mb == pytest.approx(
            (legacy_sqlite.stat().st_size + other.stat().st_size) / 1e6,
            abs=0.15)


# ── 清理 ──────────────────────────────────────────────────

class TestCleanup:
    def test_removes_legacy_keys_only(self, cfg_files, legacy_sqlite):
        paths, store = cfg_files
        _write(paths, store,
               {"cod_db_path": str(legacy_sqlite),
                "polydb_inorg_path": "D:/keep/polyDB",
                "polydb_disabled": ["cod-full"]},
               {"version": 1, "active": "", "mounts": []})
        changed = L.cleanup(paths_file=paths, store_file=store)
        assert changed and "cod_db_path" in changed
        data = json.loads(paths.read_text(encoding="utf-8"))
        assert "cod_db_path" not in data
        assert data["polydb_inorg_path"] == "D:/keep/polyDB"
        assert data["polydb_disabled"] == ["cod-full"]

    def test_never_deletes_library_files(self, cfg_files, legacy_sqlite):
        paths, store = cfg_files
        _write(paths, store,
               {"cod_db_path": str(legacy_sqlite)},
               {"version": 1, "active": "", "mounts": []})
        L.cleanup(paths_file=paths, store_file=store, remount_polydb=False)
        assert legacy_sqlite.is_file(), "清理配置绝不能删库文件"

    def test_drops_legacy_mount_and_clears_active(self, cfg_files):
        paths, store = cfg_files
        _write(paths, store, {},
               {"version": 1, "active": "cod_inorganics:x",
                "mounts": [
                    {"id": "cod_inorganics:x", "kind": "cod_inorganics",
                     "path": "D:/old/a.sqlite"},
                    {"id": "polydb:keep", "kind": "polydb",
                     "path": "D:/keep/polyDB", "variant": "cod-full"},
                ]})
        changed = L.cleanup(paths_file=paths, store_file=store,
                            remount_polydb=False)
        data = json.loads(store.read_text(encoding="utf-8"))
        assert [m["id"] for m in data["mounts"]] == ["polydb:keep"]
        assert data["active"] == ""
        assert any(c.startswith("mounts:") for c in changed)
        assert "active" in changed

    def test_keeps_active_when_it_is_not_legacy(self, cfg_files):
        paths, store = cfg_files
        _write(paths, store, {},
               {"version": 1, "active": "polydb:keep",
                "mounts": [
                    {"id": "cod_index:y", "kind": "cod_index", "path": "D:/old"},
                    {"id": "polydb:keep", "kind": "polydb", "path": "D:/keep"},
                ]})
        L.cleanup(paths_file=paths, store_file=store, remount_polydb=False)
        data = json.loads(store.read_text(encoding="utf-8"))
        assert data["active"] == "polydb:keep"

    def test_empty_report_is_noop(self, cfg_files):
        paths, store = cfg_files
        assert L.cleanup(paths_file=paths, store_file=store) == []
        assert not paths.exists() and not store.exists()

    def test_remounts_path_that_is_really_polydb(self, cfg_files, tmp_path,
                                                 monkeypatch):
        """旧键指到的其实是一份 polyDB → 清理时挂回来，而不是一并丢掉。"""
        from polyxrd.services import db_mounts
        from tests.test_polydb_reader import _phase, _write_polydb

        poly = _write_polydb(
            tmp_path / "found.polyDB",
            [_phase(1000001, [(3.34, 900), (4.26, 700), (1.82, 500)])])
        paths, store = cfg_files
        _write(paths, store, {"cod_index_db_path": str(poly)},
               {"version": 1, "active": "", "mounts": []})
        monkeypatch.setattr(db_mounts, "_store_file", lambda: store)
        monkeypatch.setattr(db_mounts, "_PROBE_CACHE", {})
        db_mounts.clear_probe_cache()

        rep = L.scan(paths, store)
        assert rep.recoverable, "polyDB 目录应被识别为可救回"
        changed = L.cleanup(rep, remount_polydb=True)
        assert any(c.startswith("remount:") for c in changed)
        mounts = [m for m in db_mounts.all_mounts() if m.kind == "polydb"
                  and m.path is not None]
        assert any(str(m.path.resolve()) == str(poly.resolve()) for m in mounts)


# ── 记住位 ────────────────────────────────────────────────

class TestDismiss:
    def test_not_dismissed_by_default(self, cfg_files):
        paths, _store = cfg_files
        assert L.is_dismissed(paths) is False

    def test_dismiss_then_is_dismissed(self, cfg_files):
        paths, _store = cfg_files
        L.dismiss(paths)
        assert L.is_dismissed(paths) is True
        data = json.loads(paths.read_text(encoding="utf-8"))
        assert data[L.DISMISS_KEY]

    def test_dismiss_preserves_other_keys(self, cfg_files):
        paths, _store = cfg_files
        paths.write_text(json.dumps({"polydb_inorg_path": "D:/a"}),
                         encoding="utf-8")
        L.dismiss(paths)
        data = json.loads(paths.read_text(encoding="utf-8"))
        assert data["polydb_inorg_path"] == "D:/a"

    def test_old_version_banner_does_not_suppress(self, cfg_files):
        """别的版本记下的"稍后"不该压制本版本的提示。"""
        paths, _store = cfg_files
        paths.write_text(json.dumps({L.DISMISS_KEY: "0.0.1"}),
                         encoding="utf-8")
        assert L.is_dismissed(paths) is False


# ── 文案 ──────────────────────────────────────────────────

class TestDescribe:
    def test_lines_cover_existing_and_missing(self, cfg_files, legacy_sqlite,
                                              tmp_path):
        paths, store = cfg_files
        _write(paths, store,
               {"cod_db_path": str(legacy_sqlite),
                "cod_index_db_path": str(tmp_path / "gone.sqlite")},
               {"version": 1, "active": "", "mounts": []})
        lines = L.describe(L.scan(paths, store))
        assert len(lines) == 2
        assert any("存在" in s for s in lines)
        assert any("已不存在" in s for s in lines)

    def test_active_line_has_no_size(self, cfg_files):
        paths, store = cfg_files
        _write(paths, store, {},
               {"version": 1, "active": "xinmatch:z",
                "mounts": [{"id": "xinmatch:z", "kind": "xinmatch",
                            "path": ""}]})
        lines = L.describe(L.scan(paths, store))
        assert any("检索源" in s for s in lines)


# ── 对话框 ────────────────────────────────────────────────

class TestDialog:
    @pytest.fixture(scope="module")
    def qapp(self):
        from PySide6.QtWidgets import QApplication

        yield QApplication.instance() or QApplication([])

    def _report(self, cfg_files, legacy_sqlite, tmp_path):
        paths, store = cfg_files
        _write(paths, store,
               {"cod_db_path": str(legacy_sqlite)},
               {"version": 1, "active": "", "mounts": []})
        return L.scan(paths, store)

    def test_shows_paths(self, qapp, cfg_files, legacy_sqlite, tmp_path):
        from polyxrd.views.legacy_config_dialog import LegacyConfigDialog

        rep = self._report(cfg_files, legacy_sqlite, tmp_path)
        dlg = LegacyConfigDialog(rep)
        try:
            text = dlg._details.toPlainText()
            assert "COD_inorganics.sqlite" in text
            assert "MB" in text and "存在" in text
        finally:
            dlg.deleteLater()

    def test_remount_unchecked_when_nothing_recoverable(self, qapp, cfg_files,
                                                        legacy_sqlite, tmp_path):
        from polyxrd.views.legacy_config_dialog import LegacyConfigDialog

        rep = self._report(cfg_files, legacy_sqlite, tmp_path)
        dlg = LegacyConfigDialog(rep)
        try:
            assert dlg.remount_polydb is False
        finally:
            dlg.deleteLater()

    def test_ask_returns_action(self, qapp, cfg_files, legacy_sqlite, tmp_path,
                                monkeypatch):
        from PySide6.QtWidgets import QDialog

        from polyxrd.views.legacy_config_dialog import LegacyConfigDialog

        rep = self._report(cfg_files, legacy_sqlite, tmp_path)
        monkeypatch.setattr(LegacyConfigDialog, "exec",
                            lambda self: QDialog.DialogCode.Rejected)
        assert LegacyConfigDialog.ask(rep) == (
            LegacyConfigDialog.ACTION_LATER, False)

        monkeypatch.setattr(LegacyConfigDialog, "exec",
                            lambda self: QDialog.DialogCode.Accepted)
        assert LegacyConfigDialog.ask(rep) == (
            LegacyConfigDialog.ACTION_CLEANUP, False)


# ── 与主窗口的接线 ────────────────────────────────────────

class TestMainWindowWiring:
    def test_deferred_tasks_calls_legacy_hint(self):
        """启动钩子必须调用它 —— 否则功能写了但永远不会被触发。"""
        import inspect

        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._deferred_startup_tasks)
        assert "_maybe_legacy_config_hint" in src

    def test_hook_skips_when_dismissed(self, monkeypatch):
        from polyxrd.services import legacy_config
        from polyxrd.views.main_window import MainWindow

        monkeypatch.setattr(legacy_config, "is_dismissed", lambda *a, **k: True)
        called = {"scan": 0}

        def _boom(*a, **k):
            called["scan"] += 1
            raise AssertionError("已选择稍后就不该再盘点")

        monkeypatch.setattr(legacy_config, "scan", _boom)
        # 早退分支不碰 self（不建窗口、不读状态栏），传 None 即可
        MainWindow._maybe_legacy_config_hint(None)
        assert called["scan"] == 0


# ── v4.4.0 独立验收的修复项 ────────────────────────────────

class TestAuditFixes:
    """验收报告 P1-1 / P1-3 / P2-6 / P2-8 / P2-9 / P2-10 的回归钉。"""

    # P1-1 —— 启动期不再对几十万文件的旧库目录做无上限遍历
    def test_size_mb_dir_traversal_is_capped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(L, "_SIZE_MAX_ENTRIES", 5)
        d = tmp_path / "big"
        d.mkdir()
        for i in range(12):
            (d / f"f{i}.cif").write_bytes(b"\0" * 1000)
        mb, truncated = L._size_mb(d)
        assert truncated is True, "超上限必须标 truncated（数值只是下限）"
        assert mb >= 0.0

    def test_size_mb_small_dir_is_exact(self, tmp_path):
        d = tmp_path / "small"
        d.mkdir()
        for i in range(3):
            (d / f"f{i}.cif").write_bytes(b"\0" * 1_000_000)
        mb, truncated = L._size_mb(d)
        assert truncated is False
        assert mb == pytest.approx(3.0, abs=0.1)

    def test_report_marks_truncated_size(self, cfg_files, tmp_path, monkeypatch):
        monkeypatch.setattr(L, "_SIZE_MAX_ENTRIES", 5)
        d = tmp_path / "big"
        d.mkdir()
        for i in range(12):
            (d / f"f{i}.cif").write_bytes(b"\0" * 1000)
        paths, store = cfg_files
        _write(paths, store, {"cod_svn_path": str(d)},
               {"version": 1, "active": "", "mounts": []})
        rep = L.scan(paths, store)
        assert rep.items[0].size_truncated is True
        assert rep.size_truncated is True
        assert "≥" in L.describe(rep)[0]

    # P2-6 —— 非 UTF-8 老配置不能被当成"空配置"
    def test_read_json_flags_non_utf8(self, tmp_path):
        f = tmp_path / "user_db_paths.json"
        f.write_bytes('{"cod_db_path": "D:/旧库"}'.encode("gbk"))
        data, ok = L._read_json(f)
        assert data == {} and ok is False

    # P1-3 —— 读不出的文件绝不能被空字典盖掉
    def test_cleanup_keeps_corrupt_paths_file_intact(self, cfg_files):
        paths, store = cfg_files
        paths.write_text("{broken", encoding="utf-8")
        store.write_text(json.dumps({
            "version": 1, "active": "",
            "mounts": [{"id": "cod_index:z", "kind": "cod_index",
                        "path": "D:/old"}],
        }), encoding="utf-8")
        changed = L.cleanup(paths_file=paths, store_file=store,
                            remount_polydb=False)
        assert "mounts:cod_index:z" in changed
        assert paths.read_text(encoding="utf-8") == "{broken"

    def test_dismiss_keeps_corrupt_paths_file_intact(self, cfg_files):
        paths, _store = cfg_files
        paths.write_text("{broken", encoding="utf-8")
        L.dismiss(paths)
        assert paths.read_text(encoding="utf-8") == "{broken"
        assert L.is_dismissed(paths) is False

    def test_atomic_write_leaves_no_tmp_file(self, cfg_files):
        paths, _store = cfg_files
        L.dismiss(paths)
        assert json.loads(paths.read_text(encoding="utf-8"))
        assert not list(paths.parent.glob("*.tmp")), "tmp + os.replace 后不该留残骸"

    # P2-8 —— active 本来就空时不该在 changed 里凭空多一条
    def test_active_not_reported_when_it_was_already_empty(self, cfg_files):
        paths, store = cfg_files
        _write(paths, store, {},
               {"version": 1, "active": "",
                "mounts": [{"kind": "cod_index", "path": "D:/old"}]})
        changed = L.cleanup(paths_file=paths, store_file=store,
                            remount_polydb=False)
        assert "mounts:cod_index" in changed
        assert "active" not in changed

    # P2-9 —— 悬空 active 一并清掉
    def test_dangling_active_is_cleared(self, cfg_files):
        paths, store = cfg_files
        _write(paths, store,
               {"cod_db_path": "D:/gone/cod.sqlite"},
               {"version": 1, "active": "polydb:vanished",
                "mounts": [{"id": "polydb:keep", "kind": "polydb",
                            "path": "D:/keep"}]})
        changed = L.cleanup(paths_file=paths, store_file=store,
                            remount_polydb=False)
        data = json.loads(store.read_text(encoding="utf-8"))
        assert data["active"] == ""
        assert "active:dangling" in changed

    # P2-10 —— 明细行走 i18n
    def test_describe_accepts_translator(self, cfg_files, legacy_sqlite):
        paths, store = cfg_files
        _write(paths, store, {"cod_db_path": str(legacy_sqlite)},
               {"version": 1, "active": "", "mounts": []})
        lines = L.describe(
            L.scan(paths, store),
            lambda key, **kw: f"<{key.rsplit('.', 1)[-1]}>")
        assert lines and "line_state_exists" in lines[0]

    def test_dialog_note_has_no_markdown_bold(self, cfg_files, legacy_sqlite):
        from PySide6.QtWidgets import QApplication, QLabel

        from polyxrd.views.legacy_config_dialog import LegacyConfigDialog

        _ = QApplication.instance() or QApplication([])
        paths, store = cfg_files
        _write(paths, store, {"cod_db_path": str(legacy_sqlite)},
               {"version": 1, "active": "", "mounts": []})
        dlg = LegacyConfigDialog(L.scan(paths, store))
        try:
            texts = [w.text() for w in dlg.findChildren(QLabel)]
            assert texts and not any("**" in t for t in texts), \
                "QLabel 不渲染 Markdown，`**` 会原样显示"
        finally:
            dlg.deleteLater()
