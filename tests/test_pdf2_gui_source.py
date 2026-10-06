"""
PDF2-2004 数据源的 GUI 对接测试 (offscreen)
==========================================
覆盖 2026-09-10 补的 PDF2 检索源接入:

1. 「物相分析」面板的数据库源下拉含 PDF2-2004, key 与文案一一对齐
2. 选中 PDF2 → PhaseViewModel.identify_phases 走 identify_with_pdf2 分支
3. PDF2 库缺失时该项置灰 (不让用户选中后静默返回空结果)
4. 候选列表行尾带空间群标记, tooltip 带化学式/空间群/晶胞
5. 空间群/晶胞缺失的老卡片不会让标记/tooltip 出现 "None"
"""
from __future__ import annotations

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from polyxrd.viewmodels.main_vm import MainViewModel
from polyxrd.views.phase_view import PhaseView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def pv(qapp):
    vm = MainViewModel()
    return PhaseView(vm), vm


# ── 1. 下拉项 ────────────────────────────────────────────────

class TestDbSourceCombo:
    def test_pdf2_item_present_and_aligned(self, pv):
        view, _vm = pv
        keys = view._db_source_keys
        # v2.6.0: 末尾追加 "user" (用户自建库) —— 前 5 项索引一律不动,
        # 免得历史持久化的 db_source 索引错位 (选 A 跑 B)。
        assert keys == [
            "builtin", "cod_inorganics", "cod_full", "merged", "pdf2", "user",
        ]
        # 文案条数必须与 key 一一对应 (错位会让选 A 跑 B)
        assert view._db_combo.count() == len(keys)
        assert view._db_combo.itemText(keys.index("pdf2")).startswith("PDF2-2004")

    def test_selecting_pdf2_returns_key(self, pv):
        view, _vm = pv
        view._db_combo.setCurrentIndex(view._db_source_keys.index("pdf2"))
        assert view._current_db_source() == "pdf2"
        assert view._db_source_display().startswith("PDF2-2004")

    def test_tooltip_mentions_pdf2(self, pv):
        view, _vm = pv
        assert "PDF2-2004" in view._db_combo.toolTip()

    def test_disabled_when_db_missing(self, pv, monkeypatch):
        """库不可用时该项置灰, 且不因异常而导致整个面板起不来。

        0.10.0 起可用性判定统一走 ``db_import.live_counts()`` (三个槽位同一口径),
        不再单独 new 一个 PDF2Database 去问 —— 所以这里 patch 的是 live_counts。
        """
        from polyxrd.services import db_import

        monkeypatch.setattr(db_import, "live_counts",
                            lambda: {"cod_inorganics": 0, "pdf2": 0, "cod_index": 0})
        vm = MainViewModel()
        view = PhaseView(vm)          # 不应抛异常
        item = view._db_combo.model().item(view._db_source_keys.index("pdf2"))
        assert item is not None and not item.isEnabled()
        assert "未挂载" in view._db_source_labels()[4]

    def test_all_external_sources_disabled_without_dbs(self, pv, monkeypatch):
        """发布包不内置数据库: 除内置库外全部置灰, 且当前选中回退到内置库。"""
        from polyxrd.services import db_import

        monkeypatch.setattr(db_import, "live_counts",
                            lambda: {"cod_inorganics": 0, "pdf2": 0, "cod_index": 0})
        # 用户库条目数走真实 user_phases.sqlite: 固定为 0, 结果才与开发机状态无关
        monkeypatch.setattr(PhaseView, "_user_phase_count", staticmethod(lambda: 0))
        view, _vm = pv
        view._db_combo.setCurrentIndex(view._db_source_keys.index("pdf2"))
        view.refresh_db_sources()

        model = view._db_combo.model()
        assert model.item(0).isEnabled()
        # 1..5 = cod_inorganics / cod_full / merged / pdf2 / user
        for i in range(1, len(view._db_source_keys)):
            assert not model.item(i).isEnabled(), f"index {i} 应置灰"
        assert view._current_db_source() == "builtin", "选中项应回退到内置库"

    def test_user_db_source_disabled_and_hinted_when_empty(self, pv, monkeypatch):
        """v2.6.0: 用户库没有条目时置灰, 并给出「去导入 CIF」的专用提示。

        置灰而不只是标灰 —— 用户看到灰项会去菜单找入口, 看到提示会直接照做。
        """
        from PySide6.QtCore import Qt

        monkeypatch.setattr(PhaseView, "_user_phase_count", staticmethod(lambda: 0))
        view, _vm = pv
        view.refresh_db_sources()

        idx = view._db_source_keys.index("user")
        item = view._db_combo.model().item(idx)
        assert item is not None and not item.isEnabled()
        assert "用户数据库" in view._db_source_labels()[idx]
        hint = item.data(Qt.ItemDataRole.ToolTipRole) or item.toolTip()
        assert "CIF" in str(hint), "置灰项必须指路, 否则用户不知道去哪导入"

    def test_unmounted_hint_points_to_menu(self, pv, monkeypatch):
        """置灰项必须告诉用户去哪导入, 否则用户只会看到灰掉的选项。"""
        from polyxrd.services import db_import

        monkeypatch.setattr(db_import, "live_counts",
                            lambda: {"cod_inorganics": 0, "pdf2": 0, "cod_index": 0})
        view, _vm = pv
        # 注意: pv fixture 先于 monkeypatch 建立, 视图构造时用的是真实库状态,
        # 必须 refresh 一次才会套用上面 patch 出来的"全未挂载"。
        view.refresh_db_sources()
        tip = view._db_combo.model().item(1).toolTip()
        assert "外挂数据库管理" in tip


# ── 2. 识别分支 ──────────────────────────────────────────────

class TestIdentifyRouting:
    def test_vm_routes_pdf2_to_identify_with_pdf2(self, pv, monkeypatch):
        view, vm = pv
        calls: list[dict] = []

        def _spy(data, **kwargs):
            calls.append(kwargs)
            return []

        monkeypatch.setattr(vm._phase_vm._identifier, "identify_with_pdf2", _spy)
        # 造一个非空峰列表 (identify_phases 会先检查)
        from polyxrd.models.peak import Peak, PeakList
        vm._phase_vm._peaks = PeakList(peaks=[
            Peak(two_theta=29.4, intensity=100.0, fwhm=0.1, d_spacing=3.03),
        ])
        vm._phase_vm.identify_phases(
            data=object(), top_n=5, db_source="pdf2",
            element_filter={"must_have": ["Ca"]},
        )
        assert len(calls) == 1, "未走 PDF2 分支"
        assert calls[0]["top_n"] == 5
        # 元素过滤必须透传 (PDF2 与 COD 共用四态过滤)
        assert calls[0]["element_filter"] == {"must_have": ["Ca"]}

    def test_button_path_passes_pdf2(self, pv, monkeypatch):
        """点「传统 Search/Match」时下拉选中的 PDF2 必须传到 VM。"""
        view, vm = pv
        view._db_combo.setCurrentIndex(view._db_source_keys.index("pdf2"))
        seen: dict = {}

        def _spy(*, element_filter=None, top_n=10, db_source="builtin"):
            seen["db_source"] = db_source

        monkeypatch.setattr(vm, "identify_phases", _spy)
        view._on_traditional_identify()
        assert seen.get("db_source") == "pdf2"


# ── 3. 候选列表的对称性信息 ──────────────────────────────────

class _FakeLattice:
    a, b, c = 4.983, 4.983, 17.019
    alpha, beta, gamma = 90.0, 90.0, 120.0

    @property
    def volume(self) -> float:
        return 365.97


class _FakePhase:
    def __init__(self, sg: str = "R-3c", lattice=None, name: str = "Calcite"):
        self.name = name
        self.formula = "C Ca O3"
        self.space_group = sg
        self.lattice = lattice
        self.reference_peaks = [(0, 0, 0), (1, 0, 4)]
        self.elements = {"Ca", "C", "O"}


def test_candidate_label_and_tooltip(pv):
    view, _vm = pv
    p = _FakePhase(lattice=_FakeLattice())
    assert view._space_group_suffix(p) == " · R-3c"
    tip = view._phase_detail_text(p)
    assert "空间群: R-3c" in tip
    assert "a=4.9830" in tip and "17.0190" in tip
    assert "γ=120.00" in tip
    assert "V=365.97" in tip
    assert "参考峰: 2 条" in tip


def test_candidate_label_without_symmetry(pv):
    """老卡片 (无空间群/无晶胞) 不应出现 None / 空括号。"""
    view, _vm = pv
    p = _FakePhase(sg="", lattice=None)
    assert view._space_group_suffix(p) == ""
    tip = view._phase_detail_text(p)
    assert "None" not in tip
    assert "空间群" not in tip
    assert "化学式: C Ca O3" in tip


# ── 4. 真实库可用性文案 ──────────────────────────────────────

def test_pdf2_label_reports_real_count(pv):
    """挂载了真实库时文案里的相数来自实际 COUNT(*), 不是写死的。"""
    from polyxrd.services import db_import

    view, _vm = pv
    label = view._db_source_labels()[4]
    if db_import.live_counts().get("pdf2", 0) > 0:
        assert "163" in label or "164" in label, label
        assert "未挂载" not in label
    else:
        assert label == "PDF2-2004 库 (未挂载)"
