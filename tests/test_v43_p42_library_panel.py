"""v4.3.0 P4.2 —— 精修向导「检索库」面板（polyDB 结构检索）回归。

覆盖两层：

* **服务层** ``polydb_structure``：d→2θ 换算、条目→Phase（晶胞/位点展开/
  参考峰裁剪）、展示标签、检索入口的入参守卫；
* **UI 层** ``RefinementWizard``：新页签存在、无数据时「按最强峰找」置灰、
  结果能渲染进列表并能加入已选物相。

服务层的用例**不依赖 Qt**，用现场构造的迷你 polyDB（与
``tests/test_polydb_reader.py`` 同一个写入器）钉住对外契约，CI 上没有实测库
也能跑。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.services import polydb_structure as PS  # noqa: E402
from polyxrd.services.polydb import PolyDatabase  # noqa: E402
from tests.test_polydb_reader import _phase, _write_polydb  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """Qt 应用实例（与本仓库其它 UI 测试同一写法，模块级共享）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ── 夹具 ──────────────────────────────────────────────────

@pytest.fixture()
def quartz_db(tmp_path) -> Path:
    """迷你库：1 个石英 + 1 个刚玉（都能被文本查与 d 峰查命中）。"""
    quartz = _phase(1000001,
                    [(3.343, 1000), (4.257, 620), (1.817, 420),
                     (2.457, 380), (2.281, 300), (1.541, 220)],
                    formula="O2 Si", mineral="Quartz",
                    space_group="P 32 2 1", sg_number=154,
                    a=4.9134, b=4.9134, c=5.4052, volume=113.0, density=2.65,
                    elements=["Si", "O"],
                    sites=[(14, 0.4697, 0.0, 0.0, 1.0)])
    corundum = _phase(1000002,
                      [(2.085, 900), (2.551, 700), (1.601, 450),
                       (3.480, 300), (1.374, 200), (2.379, 150)],
                      formula="Al2 O3", mineral="Corundum",
                      space_group="R -3 c", sg_number=167,
                      a=4.7607, b=4.7607, c=12.9938, volume=255.0, density=3.99,
                      elements=["Al", "O"],
                      sites=[(13, 0.0, 0.0, 0.3521, 1.0)])
    return _write_polydb(tmp_path / "mini.polyDB", [quartz, corundum])


@pytest.fixture()
def db(quartz_db) -> PolyDatabase:
    handle = PolyDatabase(quartz_db)
    assert handle.is_ready()
    yield handle
    handle.close()


class _FakeDB:
    """只实现 phase_from_entry 用到的那两个方法（位点/详情可取任意值）。"""

    def __init__(self, detail: dict, sites: list[dict]) -> None:
        self._detail = detail
        self._sites = sites
        self.calls: list[str] = []

    def get_phase(self, eid: int):
        self.calls.append(f"phase:{eid}")
        return self._detail

    def get_atomic_sites(self, eid: int):
        self.calls.append(f"sites:{eid}")
        return [dict(s) for s in self._sites]


def _detail(**kw) -> dict:
    base = {
        "cod_id": 1000001, "formula": "Si O2", "mineral_name": "Quartz",
        "space_group": "P 1", "elements_list": ["Si", "O"],
        "cell_a": 4.9134, "cell_b": 4.9134, "cell_c": 5.4052,
        "cell_alpha": 90.0, "cell_beta": 90.0, "cell_gamma": 120.0,
        "density": 2.65, "z": 3,
        "peaks_d_list": [3.343, 4.257, 1.817],
        "peaks_i_list": [1000.0, 620.0, 420.0],
    }
    base.update(kw)
    return base


# ── 服务层：峰换算 ────────────────────────────────────────

class TestPeaksToDI:
    def test_quartz_101_gives_3343(self):
        """石英最强线 101 在 Cu Kα 下 26.64° ↔ d=3.343 Å。"""
        d, i = PS.peaks_to_d_i([26.64], [1000.0], wavelength=1.5406)
        assert d and abs(d[0] - 3.3425) < 5e-3
        assert i == [1000.0]

    def test_keeps_only_strongest_then_sorts_by_d(self):
        two_theta = [20.0, 26.6, 50.0, 60.0]
        inten = [100.0, 900.0, 300.0, 50.0]
        d, i = PS.peaks_to_d_i(two_theta, inten, top=2)
        assert len(d) == 2 and len(i) == 2
        # 先按强度取前 2（26.6°=900、50.0°=300），再按 d 升序输出
        # → d 小的（50.0°/1.822 Å）排前面，强度随之重排
        assert i == [300.0, 900.0]
        assert d == sorted(d)                # 输出按 d 升序（= 2θ 升序）
        assert abs(d[1] - 3.3484) < 2e-3     # 26.6° → 石英 101 (3.34 Å)

    def test_rejects_out_of_range_two_theta(self):
        d, i = PS.peaks_to_d_i([0.0, 180.0, -5.0], [10.0, 10.0, 10.0])
        assert d == [] and i == []

    def test_empty_input(self):
        assert PS.peaks_to_d_i([], []) == ([], [])


# ── 服务层：展示标签 ──────────────────────────────────────

class TestLabels:
    def test_pseudo_mineral_is_filtered(self):
        """``data_`` 行就是编号的条目不该显示成矿名。"""
        entry = {"cod_id": 2101438, "mineral_name": "2101438",
                 "formula": "H2 Mg O2", "space_group": "P -3 m 1"}
        assert PS.display_label(entry) == "H2 Mg O2"

    def test_mineral_and_formula_combined(self):
        entry = {"cod_id": 1011097, "mineral_name": "Rutile",
                 "formula": "Ti O2", "space_group": "P 42/m n m",
                 "cell_a": 4.5937, "cell_b": 4.5937, "cell_c": 2.9587}
        label = PS.entry_label(entry)
        assert label.startswith("Rutile (Ti O2)")
        assert "P 42/m n m" in label
        assert "a=4.594 b=4.594 c=2.959 Å" in label
        assert label.endswith("COD 1011097")

    def test_cubic_cell_collapses_to_single_a(self):
        entry = {"cod_id": 1, "formula": "Si", "cell_a": 5.431,
                 "cell_b": 5.431, "cell_c": 5.431}
        assert PS._cell_summary(entry) == "a=5.431 Å"

    def test_dirty_cell_is_skipped(self):
        entry = {"cod_id": 1, "formula": "Si", "cell_a": 0.0,
                 "cell_b": 0.0, "cell_c": 0.0}
        assert PS._cell_summary(entry) == ""


# ── 服务层：条目 → Phase ──────────────────────────────────

class TestPhaseFromEntry:
    def test_builds_cell_sites_and_reference_peaks(self):
        fake = _FakeDB(_detail(), [{"label": "Si", "element": "Si",
                                    "x": 0.47, "y": 0.0, "z": 0.0,
                                    "occupancy": 1.0}])
        phase = PS.phase_from_entry(1000001, fake, wavelength=1.5406)
        assert phase is not None
        assert phase.name == "Quartz - Si O2 (COD 1000001)"
        assert phase.db_id == 1000001
        assert phase.lattice is not None
        assert phase.lattice.a == pytest.approx(4.9134)
        assert phase.lattice.gamma == pytest.approx(120.0)
        assert len(phase.atomic_sites) == 1
        assert phase.elements == {"Si", "O"}
        assert phase.density == pytest.approx(2.65)
        # 3 条参考峰都在窗口内 → 全保留，hkl 占位 (0,0,0)，按 2θ 升序
        assert len(phase.reference_peaks) == 3
        assert all(hkl == (0, 0, 0) for hkl, _tt, _i in phase.reference_peaks)
        tts = [tt for _h, tt, _i in phase.reference_peaks]
        assert tts == sorted(tts)
        assert tts[0] == pytest.approx(20.84, abs=0.05)   # d=4.257

    def test_accepts_search_result_dict(self):
        fake = _FakeDB(_detail(), [])
        phase = PS.phase_from_entry({"cod_id": 1000001}, fake)
        assert phase is not None and phase.db_id == 1000001

    def test_two_theta_range_clips_reference_peaks(self):
        fake = _FakeDB(_detail(), [])
        phase = PS.phase_from_entry(1000001, fake, two_theta_range=(20.0, 30.0))
        assert phase is not None
        # d=4.257 → 20.8°、d=3.343 → 26.6° 保留；d=1.817 → 50.2° 被裁
        assert len(phase.reference_peaks) == 2

    def test_missing_entry_returns_none(self):
        class _Empty:
            def get_phase(self, eid):
                return None

        assert PS.phase_from_entry(1, _Empty()) is None

    def test_bad_cell_degrades_to_no_lattice(self):
        fake = _FakeDB(_detail(cell_a=0.0, cell_b=0.0, cell_c=0.0), [])
        phase = PS.phase_from_entry(1000001, fake)
        assert phase is not None and phase.lattice is None

    def test_expands_asymmetric_unit_sites(self):
        """非对称单位位点必须展开成全胞 —— 否则高对称相精修出假峰（v4.1.1）。"""
        pytest.importorskip("pymatgen.symmetry.groups")
        fake = _FakeDB(
            _detail(space_group="F d -3 m", formula="Si", mineral_name="Diamond",
                    elements_list=["Si"],
                    cell_a=5.431, cell_b=5.431, cell_c=5.431),
            [{"label": "Si", "element": "Si", "x": 0.0, "y": 0.0, "z": 0.0,
              "occupancy": 1.0}],
        )
        phase = PS.phase_from_entry(1000001, fake,
                                    two_theta_range=None)
        assert phase is not None
        assert len(phase.atomic_sites) > 1

    def test_p1_space_group_keeps_sites_as_is(self):
        sites = [{"label": "Si", "element": "Si", "x": 0.1, "y": 0.2,
                  "z": 0.3, "occupancy": 1.0}]
        fake = _FakeDB(_detail(space_group="P 1"), sites)
        phase = PS.phase_from_entry(1000001, fake)
        assert phase is not None and len(phase.atomic_sites) == 1


# ── 服务层：检索入口守卫 ──────────────────────────────────

class TestSearchGuards:
    def test_text_search_without_db_returns_empty(self):
        assert PS.search_structures("SiO2", db=None) == []

    def test_text_search_blank_query_returns_empty(self, db):
        assert PS.search_structures("   ", db=db) == []

    def test_peak_search_needs_enough_peaks(self, db):
        assert PS.search_structures_by_peaks([3.34, 4.26], db=db, min_match=3) == []

    def test_peak_search_without_db_returns_empty(self):
        assert PS.search_structures_by_peaks([3.34, 4.26, 1.82], db=None) == []


# ── 集成：迷你库上跑通「查 → 挑 → 装载」 ──────────────────

class TestMiniLibraryIntegration:
    def test_open_database_with_explicit_path(self, quartz_db):
        handle = PS.open_database(db_path=quartz_db)
        assert handle is not None and handle.is_ready()
        handle.close()

    def test_open_database_rejects_bogus_path(self, tmp_path):
        assert PS.open_database(db_path=tmp_path / "nope") is None

    def test_text_search_hits_quartz_first(self, db):
        rows = PS.search_structures("SiO2", db=db)
        assert rows, "化学式规范化后应命中石英"
        assert rows[0]["mineral_name"] == "Quartz"
        assert rows[0]["cod_id"] == 1000001

    def test_text_search_by_mineral_name(self, db):
        rows = PS.search_structures("Corundum", db=db)
        assert [r["cod_id"] for r in rows] == [1000002]

    def test_peak_search_ranks_quartz_top(self, db):
        md, mi = PS.peaks_to_d_i([26.64, 20.90, 50.20, 36.60, 39.50],
                                 [1000.0, 620.0, 420.0, 380.0, 300.0])
        rows = PS.search_structures_by_peaks(md, mi, db=db, limit=5)
        assert rows, "石英的 6 条强线应能命中"
        assert rows[0]["cod_id"] == 1000001

    def test_loaded_phase_is_ready_for_refinement(self, db):
        rows = PS.search_structures("Quartz", db=db)
        phase = PS.phase_from_entry(rows[0], db, wavelength=1.5406)
        assert phase is not None
        assert phase.lattice is not None and phase.lattice.a == pytest.approx(4.9134)
        assert phase.atomic_sites, "位点必须带出来，否则精修还得再查一次库"
        assert phase.reference_peaks

    def test_library_label_mentions_variant_and_count(self, db):
        label = PS.library_label(db)
        assert "synthetic" in label
        assert "2" in label

    def test_library_label_of_none(self):
        assert PS.library_label(None) == ""


# ── UI 层：向导面板 ──────────────────────────────────────

@pytest.fixture()
def wizard(qapp, quartz_db):
    """构造向导；把 polyDB 指到迷你库（不碰真机 ~/.polyxrd）。"""
    from polyxrd.views.refinement_wizard import RefinementWizard

    w = RefinementWizard()
    w.set_library_database(PolyDatabase(quartz_db))
    yield w
    w.deleteLater()


class TestWizardLibraryPanel:
    def test_library_tab_exists_first(self, qapp):
        from polyxrd.views.refinement_wizard import RefinementWizard

        w = RefinementWizard()
        try:
            assert w._lib_tab_index == 0
            assert w._phase_tabs.count() == 3
        finally:
            w.deleteLater()

    def test_by_peaks_disabled_without_data(self, qapp):
        from polyxrd.views.refinement_wizard import RefinementWizard

        w = RefinementWizard()
        try:
            assert not w._btn_lib_by_peaks.isEnabled()
        finally:
            w.deleteLater()

    def test_fill_list_renders_entries(self, wizard, db):
        from PySide6.QtCore import Qt

        rows = PS.search_structures("SiO2", db=db)
        wizard._fill_library_list(rows)
        assert wizard._lib_results_list.count() == len(rows)
        item = wizard._lib_results_list.item(0)
        assert "Quartz" in item.text()
        assert isinstance(item.data(Qt.ItemDataRole.UserRole), dict)

    def test_add_selected_creates_refinable_phase(self, wizard, db):
        rows = PS.search_structures("Quartz", db=db)
        wizard._fill_library_list(rows)
        wizard._lib_results_list.setCurrentRow(0)
        wizard._on_add_lib_phases()
        assert len(wizard._selected_phases) == 1
        phase = wizard._selected_phases[0]
        assert phase.db_id == 1000001
        assert phase.lattice is not None
        assert phase.atomic_sites

    def test_add_same_phase_twice_is_rejected(self, wizard, db, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information",
                            staticmethod(lambda *a, **k: None))
        rows = PS.search_structures("Quartz", db=db)
        wizard._fill_library_list(rows)
        wizard._lib_results_list.setCurrentRow(0)
        wizard._on_add_lib_phases()
        wizard._on_add_lib_phases()
        assert len(wizard._selected_phases) == 1

    def test_search_sets_status_when_query_blank(self, wizard):
        wizard._lib_search_input.setText("   ")
        wizard._on_lib_search()
        assert wizard._lib_status.text()   # 有提示, 不是空白

    def test_raw_strong_points_fallback(self, qapp):
        """峰检测抛异常时退化路径也要给出峰（不能静默空手）。"""
        import numpy as np

        from polyxrd.models.xrd_data import XRDData
        from polyxrd.views.refinement_wizard import RefinementWizard

        tt = np.linspace(10.0, 80.0, 701)
        inten = np.exp(-((tt - 26.6) ** 2) / 0.02) * 1000.0 + 1.0
        w = RefinementWizard(data=XRDData(two_theta=tt, intensity=inten))
        try:
            twos, ints = w._raw_strong_points()
            assert twos and ints
            assert abs(twos[0] - 26.6) < 1.0
        finally:
            w.deleteLater()
