"""
PDF2-2004 数据源的 GUI 对接测试 (offscreen)
==========================================
覆盖 2026-09-10 补的 PDF2 检索源接入:

1. 「物相分析」面板的数据库源下拉含 PDF2-2004, key 与文案一一对齐
2. 选中 PDF2 → PhaseViewModel.identify_phases 走 identify_with_polydb 分支,
   且把 ``variant="pdf2-2004"`` 一路带下去 (v5.2: PDF2 已是 polyDB 变体,
   独立 sqlite 通道与 kind ``pdf2`` 一并删除)
3. PDF2 库缺失时该项置灰 (不让用户选中后静默返回空结果)
4. 候选列表行尾带空间群标记, tooltip 带化学式/空间群/晶胞
5. 空间群/晶胞缺失的老卡片不会让标记/tooltip 出现 "None"
"""
from __future__ import annotations

from pathlib import Path

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
def pv(qapp, tmp_path, monkeypatch):
    # 物相页换源会把「当前库」写进挂载表 → 指到临时文件, 不污染真实配置
    from polyxrd.services import db_mounts

    monkeypatch.setattr(db_mounts, "_store_file",
                        lambda: tmp_path / "db_mounts.json")
    vm = MainViewModel()
    return PhaseView(vm), vm


# ── 1. 下拉项 ────────────────────────────────────────────────
#
# v4.0.0: 「数据源」不再是写死的槽位表, 而是由挂载注册表
# (``polyxrd.services.db_mounts``) 现算 —— 挂了几份库就有几项。所以这里
# 一律 patch ``db_mounts.source_entries``, 断言与开发机上真实挂了什么库无关。

#: (挂载 id, 类型, polyDB 变体, 路径, 相数, i18n 键) —— 与 probe_all 的行同形
#: v5.2: 只剩 polyDB 三个变体 + 用户库; PDF2-2004 已并入 polyDB 家族
#: (``kind="polydb"`` / ``variant="pdf2-2004"``), 独立的 ``pdf2`` 类型已删。
_STD_SOURCES = (
    ("polydb:cod-inorg", "polydb", "cod-inorg", r"D:\db\COD-Inorg.polyDB", 77500,
     "db_mounts.kind.polydb_inorg"),
    ("polydb:cod-full", "polydb", "cod-full", r"D:\db\COD-Full.polyDB", 521361,
     "db_mounts.kind.polydb_full"),
    ("pdf2", "polydb", "pdf2-2004", r"D:\db\PDF2-2004.polyDB", 163834,
     "db_manager.kind.pdf2"),
    ("user", "user", "", r"D:\db\user_phases.sqlite", 5, "db_mounts.kind.user"),
)


def _fake_sources(ok=True, user_rows: int = 5) -> list[dict]:
    """构造 probe_all 同形数据; ``ok`` 可整体置真假, 也可按 id 逐个指定。"""
    from pathlib import Path as _P

    out: list[dict] = []
    for mid, kind, variant, path, rows, label_key in _STD_SOURCES:
        good = ok if isinstance(ok, bool) else ok.get(mid, True)
        n = user_rows if kind == "user" else rows
        out.append({
            "id": mid, "kind": kind, "path": path, "exists": True,
            "builtin": True, "variant": variant, "label_key": label_key,
            "label": _P(path).name, "ok": good, "rows": n if good else 0,
            "size_mb": 1.0, "engine": kind,
            "error": "" if good else "missing", "hint": "", "detail": "",
            "has_top_peaks": False, "mount": None,
        })
    return out


@pytest.fixture
def patched_sources(monkeypatch):
    """把挂载表换成可控数据; 返回一个"再 patch 一次"的函数 (便于切场景)。"""
    from polyxrd.services import db_mounts

    def _apply(ok=True, user_rows: int = 5) -> None:
        monkeypatch.setattr(db_mounts, "source_entries",
                            lambda: _fake_sources(ok, user_rows))

    _apply()
    return _apply


class TestDbSourceCombo:
    def test_source_list_is_registry_driven(self, pv, patched_sources):
        """下拉项 = 内置 + 每个挂载项 + 用户库, 文案与 key 一一对齐。"""
        view, _vm = pv
        view.refresh_db_sources()
        keys = view._db_source_keys
        assert keys[0] == "builtin"
        # 挂载项按注册表顺序出现 (同一类型挂多份也会各占一项)
        for mid in ("polydb:cod-inorg", "polydb:cod-full", "pdf2"):
            assert mid in keys, f"{mid} 未出现在数据源下拉里"
        # 用户库固定在末尾 (v2.6.0 以来的约定位置)
        assert keys[-1] == "user"
        # v4.1.0 删掉的旧槽位不能再冒出来
        for gone in ("cod_inorganics", "cod_index", "xinmatch", "merged"):
            assert gone not in keys, f"旧槽位 {gone} 还在下拉里"
        # 文案条数必须与 key 一一对应 (错位会让选 A 跑 B)
        assert view._db_combo.count() == len(keys)
        assert view._db_combo.itemText(keys.index("pdf2")).startswith("PDF2-2004")

    def test_selecting_pdf2_returns_key(self, pv, patched_sources):
        view, _vm = pv
        view.refresh_db_sources()
        view._db_combo.setCurrentIndex(view._db_source_keys.index("pdf2"))
        assert view._current_db_source() == "pdf2"
        assert view._db_source_display().startswith("PDF2-2004")

    def test_tooltip_mentions_pdf2(self, pv):
        view, _vm = pv
        assert "PDF2-2004" in view._db_combo.toolTip()

    def test_disabled_when_db_missing(self, pv, patched_sources):
        """库不可用时该项置灰, 且不因异常而导致整个面板起不来。"""
        patched_sources({"pdf2": False})
        view, _vm = pv
        view.refresh_db_sources()
        idx = view._db_source_keys.index("pdf2")
        item = view._db_combo.model().item(idx)
        assert item is not None and not item.isEnabled()
        assert "未挂载" in view._db_source_labels()[idx]

    def test_all_external_sources_disabled_without_dbs(self, pv, patched_sources):
        """发布包不内置数据库: 除内置库外全部置灰, 且当前选中回退到内置库。"""
        patched_sources(False, user_rows=0)
        view, _vm = pv
        view.refresh_db_sources()
        view._db_combo.setCurrentIndex(view._db_source_keys.index("pdf2"))
        view.refresh_db_sources()

        model = view._db_combo.model()
        assert model.item(0).isEnabled()
        for i in range(1, len(view._db_source_keys)):
            assert not model.item(i).isEnabled(), f"index {i} 应置灰"
        assert view._current_db_source() == "builtin", "选中项应回退到内置库"

    def test_user_db_source_disabled_and_hinted_when_empty(self, pv, patched_sources):
        """v2.6.0: 用户库没有条目时置灰, 并给出「去导入 CIF」的专用提示。

        置灰而不只是标灰 —— 用户看到灰项会去菜单找入口, 看到提示会直接照做。
        """
        from PySide6.QtCore import Qt

        patched_sources(True, user_rows=0)
        view, _vm = pv
        view.refresh_db_sources()

        idx = view._db_source_keys.index("user")
        item = view._db_combo.model().item(idx)
        assert item is not None and not item.isEnabled()
        assert "用户数据库" in view._db_source_labels()[idx]
        hint = item.data(Qt.ItemDataRole.ToolTipRole) or item.toolTip()
        assert "CIF" in str(hint), "置灰项必须指路, 否则用户不知道去哪导入"

    def test_unmounted_hint_points_to_menu(self, pv, patched_sources):
        """置灰项必须告诉用户去哪导入, 否则用户只会看到灰掉的选项。"""
        patched_sources(False, user_rows=0)
        view, _vm = pv
        # 注意: pv fixture 先于 patch 生效前的构造, 必须 refresh 一次才套用
        view.refresh_db_sources()
        tip = view._db_combo.model().item(1).toolTip()
        assert "外挂数据库管理" in tip

    def test_polydb_variants_are_separate_items(self, pv, patched_sources):
        """polyDB 的无机库与全库是两份库 → 必须是两个独立数据源。

        合成一项的话, "选无机库"和"选全库"会落到同一个 db_source, 用户
        以为换库了实际没换。
        """
        view, _vm = pv
        view.refresh_db_sources()
        keys = view._db_source_keys
        assert "polydb:cod-inorg" in keys and "polydb:cod-full" in keys
        assert view._db_combo.itemText(keys.index("polydb:cod-inorg")).startswith(
            "COD 无机物库（polyDB）")
        assert view._db_combo.itemText(keys.index("polydb:cod-full")).startswith(
            "COD 全库（polyDB）")
        assert "77,500" in view._db_source_labels()[keys.index("polydb:cod-inorg")]
        assert "521,361" in view._db_source_labels()[keys.index("polydb:cod-full")]

    def test_polydb_inorg_is_the_default_library(self, pv, patched_sources):
        """COD-Inorg 那份是默认库: 挂上后就是可用项, 且排在其他库前面。"""
        view, _vm = pv
        view.refresh_db_sources()
        keys = view._db_source_keys
        assert keys.index("polydb:cod-inorg") < keys.index("pdf2")
        idx = keys.index("polydb:cod-inorg")
        assert view._db_combo.model().item(idx).isEnabled()


# ── 2. 识别分支 ──────────────────────────────────────────────

class _FakePdf2Mount:
    """PDF2-2004 挂载项的替身 (不碰真实库, 只验路由与变体透传)。"""

    id = "pdf2"
    kind = "polydb"
    engine = "polydb"
    variant = "pdf2-2004"
    exists = True
    path = Path(r"D:\db\PDF2-2004.polyDB")

    def display_name(self) -> str:
        return "PDF2-2004 库"


class TestIdentifyRouting:
    def test_vm_routes_pdf2_to_identify_with_polydb(self, pv, monkeypatch):
        """db_source="pdf2" 必须落到 identify_with_polydb(variant="pdf2-2004")。

        v5.2 起 PDF2-2004 是 polyDB 的一个变体, 与 COD 两变体共用同一套
        reader/打分; 老字面量 ``db_source="pdf2"`` 由注册表别名映射到这一行,
        历史项目文件不需要迁移。
        """
        view, vm = pv
        calls: list[dict] = []

        def _spy(data, **kwargs):
            calls.append(kwargs)
            return []

        monkeypatch.setattr(vm._phase_vm._identifier,
                            "identify_with_polydb", _spy)
        monkeypatch.setattr(vm._phase_vm, "_resolve_mount",
                            lambda db_source: _FakePdf2Mount())
        monkeypatch.setattr(vm._phase_vm, "_ensure_mount_usable",
                            lambda mount: True)
        # 造一个非空峰列表 (identify_phases 会先检查)
        from polyxrd.models.peak import Peak, PeakList
        vm._phase_vm._peaks = PeakList(peaks=[
            Peak(two_theta=29.4, intensity=100.0, fwhm=0.1, d_spacing=3.03),
        ])
        vm._phase_vm.identify_phases(
            data=object(), top_n=5, db_source="pdf2",
            element_filter={"must_have": ["Ca"]},
        )
        assert len(calls) == 1, "未走 polyDB 分支"
        assert calls[0]["top_n"] == 5
        # 元素过滤必须透传 (PDF2 与 COD 共用四态过滤)
        assert calls[0]["element_filter"] == {"must_have": ["Ca"]}
        # 变体 + 库路径都必须带下去: 少了 variant 会当成 COD 无机库查,
        # 少了 db_path 会在槽位变更后查到另一份库。
        assert calls[0]["variant"] == "pdf2-2004"
        assert calls[0]["db_path"] == str(_FakePdf2Mount.path)

    def test_vm_routes_polydb_to_identify_with_polydb(self, pv, monkeypatch):
        """db_source="polydb:cod-inorg" 必须落到 identify_with_polydb (默认库)。"""
        view, vm = pv
        calls: list[dict] = []

        def _spy(data, **kwargs):
            calls.append(kwargs)
            return []

        monkeypatch.setattr(vm._phase_vm._identifier,
                            "identify_with_polydb", _spy)
        from polyxrd.models.peak import Peak, PeakList
        vm._phase_vm._peaks = PeakList(peaks=[
            Peak(two_theta=29.4, intensity=100.0, fwhm=0.1, d_spacing=3.03),
        ])
        vm._phase_vm.identify_phases(
            data=object(), top_n=5, db_source="polydb:cod-inorg",
            element_filter={"must_have": ["Zn"]},
        )
        assert len(calls) == 1, "未走 polyDB 分支"
        assert calls[0]["element_filter"] == {"must_have": ["Zn"]}
        # 变体必须带下去, 否则两个 polyDB 变体会互相串门
        assert calls[0]["variant"] == "cod-inorg"

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

def test_pdf2_label_reports_real_count(pv, patched_sources):
    """挂载了真实库时文案里的相数来自实际探测结果, 不是写死的常量。"""
    view, _vm = pv
    view.refresh_db_sources()
    idx = view._db_source_keys.index("pdf2")
    label = view._db_source_labels()[idx]
    # patch 出来的行带 163,834 相 → 文案必须把它格式化进括号里
    assert "163,834" in label, label
    assert "未挂载" not in label
