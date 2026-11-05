"""M21 S5: PhaseView v2 多相勾选叠加集成测试 (offscreen)。

验证: 载入数据 → 寻峰 → 识别 → 候选可勾选 → 勾选驱动
PatternDisplayWidget(实验/参考棒/计算谱/归属) + PeakMatchTable 刷新。
"""

import numpy as np
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.phase_view import PhaseView
from polyxrd.services.peak_finder import PeakFinder


def _write_synth_quartz(path: str) -> None:
    """合成类石英谱 (主峰 ~26.6°) 到 .xy 文件。"""
    x = np.arange(15.0, 60.0, 0.02)
    y = np.zeros_like(x)
    for c, I in [(26.6, 1000), (20.9, 200), (36.5, 120), (39.5, 80),
                 (40.3, 50), (42.5, 60), (45.8, 70), (50.2, 100), (54.9, 60)]:
        y += I * np.exp(-((x - c) / 0.08) ** 2)
    y += 8.0
    with open(path, "w") as f:
        for a, b in zip(x, y):
            f.write(f"{a:.4f} {b:.3f}\n")


def _drive_identify(pv: PhaseView, vm: MainViewModel) -> None:
    """寻峰 + 识别 → 候选列表填充 (真实按钮路径的 service 层)。"""
    app = QApplication.instance()
    data = vm.current_data
    pf = PeakFinder()
    vm._phase_vm._peaks = pf.find_peaks(data, height=0.02, distance=3.0)
    vm.identify_phases(elements=None, top_n=8, db_source="builtin")
    for _ in range(10):
        app.processEvents()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def setup(qapp: QApplication, tmp_path):
    vm = MainViewModel()
    pv = PhaseView(vm)
    # v4.0.0: 写 tmp_path（原实现写 tempfile.gettempdir()，TEMP 不可写时会
    # 落到 cwd，测试因此往仓库根丢 .xy 残留）。
    path = str(tmp_path / "polyxrd_qt_synth.xy")
    _write_synth_quartz(path)
    vm.load_file(path)
    for _ in range(5):
        qapp.processEvents()
    _drive_identify(pv, vm)
    assert pv._candidate_list.count() > 0
    return pv, vm


class TestPhaseViewV2:
    def test_candidates_checkable(self, setup):
        pv, _vm = setup
        item = pv._candidate_list.item(0)
        assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
        assert item.checkState() == Qt.CheckState.Unchecked

    def test_check_selects_and_draws_overlay(self, setup):
        pv, vm = setup
        item = pv._candidate_list.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        for _ in range(5):
            QApplication.instance().processEvents()
        # VM 选中集合含该相
        assert len(vm._phase_vm.selected_phases) == 1
        # 实验谱已画
        assert pv._plot._main_x.size > 0
        # 参考棒区有棒
        n_stick = sum(1 for l in pv._plot._ax_stick.lines
                      if l.get_gid() == "stick")
        assert n_stick > 0
        # 峰归属表已填充
        rows = pv._match_table._table.rowCount()
        assert rows > 0

    def test_uncheck_removes_from_overlay(self, setup):
        pv, vm = setup
        item = pv._candidate_list.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        for _ in range(3):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 1
        item.setCheckState(Qt.CheckState.Unchecked)
        for _ in range(3):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 0

    def test_clear_selection_unchecks_all(self, setup):
        pv, vm = setup
        for idx in range(min(2, pv._candidate_list.count())):
            pv._candidate_list.item(idx).setCheckState(Qt.CheckState.Checked)
        for _ in range(5):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 2
        pv._on_clear_selection()
        for _ in range(3):
            QApplication.instance().processEvents()
        assert len(vm._phase_vm.selected_phases) == 0
        # 候选列表仍保留 (未清空)
        assert pv._candidate_list.count() > 0

    def test_toggle_calc_shows_hides_calc(self, setup):
        pv, _vm = setup
        pv._candidate_list.item(0).setCheckState(Qt.CheckState.Checked)
        for _ in range(5):
            QApplication.instance().processEvents()
        # 默认叠加计算谱开启 → calc 线存在
        n_calc_on = sum(1 for l in pv._plot._ax_main.lines
                        if l.get_gid() == "calc")
        assert n_calc_on == 1
        pv._btn_toggle_calc.setChecked(False)
        pv._refresh_overlay()
        for _ in range(3):
            QApplication.instance().processEvents()
        n_calc_off = sum(1 for l in pv._plot._ax_main.lines
                         if l.get_gid() == "calc")
        assert n_calc_off == 0


# ── v4.0.0: 数据源下拉 (挂载列表) 刷新性能与状态同步 ──────────────────

class TestDbSourceRefresh:
    """钉住两处 v4.0.0 数据源下拉的缺陷:

    1. PDF2 覆盖率是全表聚合, 每次 refresh 都重跑会卡主线程;
    2. 选回「内置库 / 合并」时必须清 active, 否则下次刷新会悄悄跳回外挂库。
    """

    @pytest.fixture
    def pv(self, qapp):
        from polyxrd.viewmodels.main_vm import MainViewModel

        return PhaseView(MainViewModel())

    def test_default_source_prefers_bundled_polydb(self, pv, monkeypatch):
        """v4.1.2：首启数据源应选中内置 COD-Inorg，而不是 118 相 builtin。"""
        from polyxrd.services import db_mounts

        rows = [{
            "kind": "polydb", "id": "polydb:cod-inorg",
            "label_key": "db_mounts.kind.polydb_inorg",
            "label": "COD-Inorg", "ok": True, "rows": 77500,
            "variant": "cod-inorg", "path": "", "builtin": True,
        }]
        monkeypatch.setattr(db_mounts, "source_entries", lambda: rows)
        monkeypatch.setattr(db_mounts, "active_id", lambda: "")
        pv._db_source_labels()  # 用假挂载表重建 keys/enabled
        idx = pv._preferred_db_source_index()
        assert pv._db_source_keys[idx] == "polydb:cod-inorg"

    def test_default_source_falls_back_to_builtin(self, pv, monkeypatch):
        from polyxrd.services import db_mounts

        monkeypatch.setattr(db_mounts, "source_entries", lambda: [])
        monkeypatch.setattr(db_mounts, "active_id", lambda: "")
        pv._db_source_labels()
        assert pv._preferred_db_source_index() == 0

    def test_pdf2_coverage_reads_polydb_meta_once(self, pv, tmp_path,
                                                  monkeypatch):
        """PDF2 已是 polyDB：覆盖率读 meta.json，按 (路径, mtime, size) 缓存。"""
        import json
        import os

        from polyxrd.config import get_config

        db = tmp_path / "PDF2-2004.polyDB"
        db.mkdir()
        meta = db / "meta.json"
        meta.write_text(json.dumps({
            "counts": {"phases": 10},
            "build": {"with_sg": 8, "with_cell": 9},
        }), encoding="utf-8")
        monkeypatch.setattr(get_config(), "get_polydb_path",
                            lambda variant="cod-inorg": db)

        pv._pdf2_cov_cache = None
        line = pv._pdf2_coverage_line()
        assert "10" in line and "80" in line and "90" in line
        cached = pv._pdf2_cov_cache
        for _ in range(3):
            assert pv._pdf2_coverage_line() == line
        assert pv._pdf2_cov_cache == cached, "库没换就不该重读 meta"

        # 库被替换 (mtime 变) → 必须重新读取
        meta.write_text(json.dumps({
            "counts": {"phases": 20},
            "build": {"with_sg": 10, "with_cell": 20},
        }), encoding="utf-8")
        os.utime(meta, (meta.stat().st_atime, meta.stat().st_mtime + 5))
        line2 = pv._pdf2_coverage_line()
        assert line2 != line and "20" in line2

    def test_selecting_non_mount_source_clears_active(self, pv, tmp_path,
                                                      monkeypatch):
        from polyxrd.services import db_mounts

        monkeypatch.setattr(db_mounts, "_store_file",
                            lambda: tmp_path / "db_mounts.json")
        db_mounts.set_active("pdf2")   # 假装之前选过外挂库
        pv._db_combo.setCurrentIndex(0)   # 内置库 (非挂载项)
        pv._on_db_source_changed()
        assert db_mounts.active_id() == "", (
            "选回非挂载数据源后 active 必须清空, 否则下次刷新会把下拉拽回旧库")


def test_project_status_keys_resolve_in_all_languages():
    """项目保存/打开的 status/error 键三语齐全 (缺键会直接显示成键名)。"""
    from polyxrd.i18n.translations import en_US, ja_JP, zh_CN

    def _resolve(tree: dict, dotted: str):
        node = tree
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    keys = ("dialog.project_saved", "dialog.project_loaded",
            "dialog.project_load_failed")
    for mod in (zh_CN, en_US, ja_JP):
        for k in keys:
            assert _resolve(mod.translations, k), f"{k} 在 {mod.__name__} 中缺失"

