"""v0.15.0 M23 物相列表交互重构 + CIF 导出测试
==============================================
- phase_cif_export: cod_id 解析 / cif_path 直读 / 导出落盘 / 失败抛错 / 文件名
- project_service: selected_phases 保存/恢复 roundtrip
- GUI 管道存在性: 主窗勾选驱动重建 + 右键菜单 (照 M20 模式, 不真建窗)
"""
import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from polyxrd.models.phase import Phase
from polyxrd.services import phase_cif_export as pce
from polyxrd.services.project_service import ProjectService


# ----------------------------------------------------------------------
# phase_cif_export (纯逻辑)
# ----------------------------------------------------------------------

def test_resolve_cod_id_from_name_formula_path():
    p = Phase(name="Calcite (COD 1000054)", formula="CaCO3")
    assert pce.resolve_cod_id(p) == 1000054
    p2 = Phase(name="ZnO", formula="COD:9002348")
    assert pce.resolve_cod_id(p2) == 9002348
    p3 = Phase(name="X", cif_path="C:/cache/COD9002348.cif")
    assert pce.resolve_cod_id(p3) == 9002348
    p4 = Phase(name="X", cif_path="C:/cache/9002348.cif")
    assert pce.resolve_cod_id(p4) == 9002348
    assert pce.resolve_cod_id(Phase(name="Quartz")) is None


def test_get_cif_text_reads_local_cif_path(tmp_path):
    cif = tmp_path / "COD1000054.cif"
    cif.write_text("data_test\n_cell_length_a 4.0\n", encoding="utf-8")
    p = Phase(name="Test", cif_path=str(cif))
    text, cod_id = pce.get_phase_cif_text(p)
    assert "_cell_length_a" in text
    assert cod_id == 1000054


def test_export_phase_cif_writes_file(tmp_path):
    cif = tmp_path / "src.cif"
    cif.write_text("data_x\n", encoding="utf-8")
    p = Phase(name="My Phase", cif_path=str(cif))
    out = pce.export_phase_cif(p, tmp_path / "sub" / "out.cif")
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "data_x\n"


def test_cif_unavailable_raises(monkeypatch):
    # 断掉库通道 (测试机上真库可用, 会污染"应失败"断言)
    monkeypatch.setattr(pce, "_cod_db", lambda: None)
    p = Phase(name="NoSuchPhase XYZ", formula="")
    with pytest.raises(pce.CifUnavailableError):
        pce.get_phase_cif_text(p)


def test_default_cif_filename():
    p = Phase(name='Calcite (COD 1000054)')
    name = pce.default_cif_filename(p, 1000054)
    assert name == "Calcite (COD 1000054)_1000054.cif"
    bad = pce.default_cif_filename(Phase(name='a/b:c*d'), None)
    assert "/" not in bad and ":" not in bad and "*" not in bad


# ----------------------------------------------------------------------
# project_service: selected_phases roundtrip
# ----------------------------------------------------------------------

def test_project_roundtrip_selected_phases(tmp_path):
    svc = ProjectService()
    sel = [
        Phase(name="Calcite", formula="CaCO3", space_group="R-3c", match_score=88.5),
        Phase(name="ZnO", formula="ZnO"),
    ]
    path = str(tmp_path / "p.pxrd")
    svc.save_project(path, selected_phases=sel)
    loaded = svc.load_project(path)
    assert len(loaded["selected_phases"]) == 2
    assert loaded["selected_phases"][0].name == "Calcite"
    assert loaded["selected_phases"][0].match_score == pytest.approx(88.5)


def test_project_without_selected_phases_defaults_empty(tmp_path):
    svc = ProjectService()
    path = str(tmp_path / "q.pxrd")
    svc.save_project(path)
    loaded = svc.load_project(path)
    assert loaded["selected_phases"] == []


# ----------------------------------------------------------------------
# GUI 管道存在性 (不真建窗, 照 M20 模式)
# ----------------------------------------------------------------------

class TestGuiPlumbing:
    def test_main_window_has_selection_driven_tree(self):
        from polyxrd.views.main_window import MainWindow

        for name in ("_on_phase_selection_changed", "_phase_tree_context_menu",
                     "_export_selected_phase_cifs", "_show_phase_details"):
            assert hasattr(MainWindow, name), name

    def test_phases_updated_no_longer_fills_tree(self):
        from polyxrd.views.main_window import MainWindow

        src = inspect.getsource(MainWindow._on_phases_updated)
        assert "addTopLevelItem" not in src

    def test_connection_wired_in_source(self):
        import polyxrd.views.main_window as mw

        src = inspect.getsource(mw)
        assert "_phase_vm.selection_changed.connect" in src

    def test_phase_view_has_candidate_context_menu(self):
        from polyxrd.views.phase_view import PhaseView

        assert hasattr(PhaseView, "_candidate_context_menu")
        src = inspect.getsource(PhaseView)
        assert "customContextMenuRequested.connect" in src
