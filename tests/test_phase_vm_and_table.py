"""
M21 PhaseViewModel 扩展 + PeakMatchTable 测试 (offscreen Qt)
===========================================================
验证 VM 多选集合管理与归属计算, 以及峰归属表渲染。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.viewmodels.phase_vm import PhaseViewModel
from polyxrd.services.phase_display import assign_peaks, phase_color
from polyxrd.views.widgets.peak_match_table import PeakMatchTable


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _phase(name, main_tt, elements=("A",)):
    return Phase(name=name, formula=name, elements=set(elements),
                 reference_peaks=[((1, 0, 0), main_tt, 100.0),
                                   ((1, 1, 0), main_tt + 12, 45.0)])


class TestViewModelSelection:
    def test_update_selection_add_remove(self, qapp):
        vm = PhaseViewModel()
        A = _phase("A", 30.0)
        sig = []
        vm.selection_changed.connect(lambda lst: sig.append([p.name for p in lst]))
        vm.update_selection(A, True)
        assert [p.name for p in vm.selected_phases] == ["A"]
        assert sig[-1] == ["A"]
        vm.update_selection(A, False)
        assert vm.selected_phases == []
        assert sig[-1] == []

    def test_dedupe_by_name_formula(self, qapp):
        vm = PhaseViewModel()
        A1 = _phase("A", 30.0)
        A2 = _phase("A", 30.0)   # 同名同公式 → 视为同一
        vm.update_selection(A1, True)
        vm.update_selection(A2, True)   # 应去重, 仍 1 个
        assert len(vm.selected_phases) == 1

    def test_ordered_and_max(self, qapp):
        vm = PhaseViewModel()
        for i in range(9):
            vm.update_selection(_phase(f"P{i}", 20 + i), True)
        # 达到 MAX_SELECTED=8 后第 9 个被拒
        assert len(vm.selected_phases) == vm.MAX_SELECTED
        assert vm.selected_phases[0].name == "P0"

    def test_is_selected(self, qapp):
        vm = PhaseViewModel()
        A = _phase("A", 30.0)
        assert not vm.is_selected(A)
        vm.update_selection(A, True)
        assert vm.is_selected(A)

    def test_current_assignment(self, qapp):
        vm = PhaseViewModel()
        A = _phase("A", 30.0)
        B = _phase("B", 42.0, elements=("B",))
        vm._peaks = PeakList(peaks=[Peak(two_theta=30.0, intensity=1000),
                                    Peak(two_theta=68.0, intensity=100)])
        vm.update_selection(A, True)
        vm.update_selection(B, True)
        assigns, hit = vm.current_assignment(tolerance=0.3)
        # 30→A; 68→None (残差)
        names = [a.phase_name for a in assigns]
        assert names == ["A", ""]
        assert assigns[1].phase_index is None
        assert len(hit) == 2

    def test_current_assignment_no_peaks(self, qapp):
        vm = PhaseViewModel()
        vm.update_selection(_phase("A", 30.0), True)
        assigns, hit = vm.current_assignment()
        assert assigns == [] and len(hit) == 1


class TestPeakMatchTable:
    def test_rows_sorted_by_two_theta(self, qapp):
        pmt = PeakMatchTable()
        assigns, _ = assign_peaks(
            [Peak(two_theta=56.0, intensity=300),
             Peak(two_theta=30.0, intensity=1000),
             Peak(two_theta=42.0, intensity=600)],
            [_phase("A", 30.0)], tolerance=0.3)
        pmt.set_assignments(assigns)
        assert pmt._table.rowCount() == 3
        # 行序按 2θ 升序
        tts = [float(pmt._table.item(r, 0).text()) for r in range(3)]
        assert tts == sorted(tts)

    def test_unmatched_row_light_red(self, qapp):
        pmt = PeakMatchTable()
        assigns, _ = assign_peaks(
            [Peak(two_theta=30.0, intensity=1000),
             Peak(two_theta=68.0, intensity=100)],   # 68 未解释
            [_phase("A", 30.0)], tolerance=0.3)
        pmt.set_assignments(assigns)
        # 找 68 所在行, 检查其归属单元格文案与背景
        found_unmatched = False
        for r in range(pmt._table.rowCount()):
            it = pmt._table.item(r, 3)
            if it and "未解释" in it.text():
                found_unmatched = True
                assert it.background().color().name() == "#ffebee"
        assert found_unmatched

    def test_matched_row_shows_phase_name(self, qapp):
        pmt = PeakMatchTable()
        assigns, _ = assign_peaks(
            [Peak(two_theta=30.0, intensity=1000)], [_phase("A", 30.0)],
            tolerance=0.3)
        pmt.set_assignments(assigns)
        it = pmt._table.item(0, 3)
        assert "A" in it.text()

    def test_click_emits_two_theta(self, qapp):
        pmt = PeakMatchTable()
        assigns, _ = assign_peaks(
            [Peak(two_theta=30.0, intensity=1000)], [_phase("A", 30.0)],
            tolerance=0.3)
        pmt.set_assignments(assigns)
        got = []
        pmt.peak_row_clicked.connect(lambda tt: got.append(tt))
        pmt._on_cell_clicked(0, 0)
        assert got and abs(got[0] - 30.0) < 1e-6

    def test_clear_table(self, qapp):
        pmt = PeakMatchTable()
        assigns, _ = assign_peaks([Peak(two_theta=30.0, intensity=1000)],
                                  [_phase("A", 30.0)], tolerance=0.3)
        pmt.set_assignments(assigns)
        pmt.clear_table()
        assert pmt._table.rowCount() == 0


# ── v4.0.0: 列表式挂载 → polyDB 分支的 db_path / 失效库处理 ─────────────

class TestPolyDbDispatch:
    """同一类型挂多份库时, db_source 必须是"挂载项 id", 显式路径/变体要带下去。"""

    def _vm_with_peaks(self):
        vm = PhaseViewModel()
        vm._peaks = PeakList(peaks=[Peak(two_theta=30.0, intensity=1000)])
        return vm

    def test_custom_polydb_mount_passes_explicit_path_and_variant(
            self, qapp, tmp_path, monkeypatch):
        from polyxrd.services import db_mounts
        from polyxrd.services.db_mounts import Mount

        dbdir = tmp_path / "mydb.polyDB"
        dbdir.mkdir()
        (dbdir / "index.sqlite").write_bytes(b"")
        (dbdir / "meta.json").write_text("{}", encoding="utf-8")
        mount = Mount(id="polydb:deadbeef", kind="polydb", path=dbdir,
                      builtin=False, variant="cod-full")
        monkeypatch.setattr(db_mounts, "resolve_mount",
                            lambda mid: mount if mid == "polydb:deadbeef" else None)
        # v4.6.0: 分发前会 probe 选中的库 (本用例的目录只是"存在"的空壳,
        # 真实探测必然失败) —— 这里只测分发参数, 探测结果按可用处理。
        monkeypatch.setattr(db_mounts, "probe",
                            lambda m, use_cache=True: {"ok": True, "rows": 1})

        vm = self._vm_with_peaks()
        calls: list[dict] = []
        monkeypatch.setattr(vm._identifier, "identify_with_polydb",
                            lambda data, **kw: calls.append(kw) or [])
        vm.identify_phases(None, db_source="polydb:deadbeef", top_n=5)
        assert calls, "polyDB 挂载项必须分发到 identify_with_polydb"
        assert calls[0]["db_path"] == str(dbdir)
        assert calls[0]["variant"] == "cod-full"

    def test_missing_custom_mount_emits_error_and_skips_dispatch(
            self, qapp, tmp_path, monkeypatch):
        from polyxrd.services import db_mounts
        from polyxrd.services.db_mounts import Mount

        gone = tmp_path / "gone.sqlite"
        mount = Mount(id="pdf2:cafe", kind="pdf2", path=gone, builtin=False)
        monkeypatch.setattr(db_mounts, "resolve_mount",
                            lambda mid: mount if mid == "pdf2:cafe" else None)

        vm = self._vm_with_peaks()
        errs: list[str] = []
        vm.error.connect(errs.append)
        called: list[int] = []
        monkeypatch.setattr(vm._identifier, "identify_with_pdf2",
                            lambda *a, **k: called.append(1) or [])
        vm.identify_phases(None, db_source="pdf2:cafe")
        assert errs, "库文件被挪走后必须报错, 不能静默返回空结果"
        assert not called, "不可用的挂载项不该再进检索引擎"

