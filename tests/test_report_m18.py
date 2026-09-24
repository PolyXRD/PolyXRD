"""
M18 报告与导出测试 (Sprint 3)
=============================
"""
from pathlib import Path

import numpy as np
import pytest

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.report import (export_peak_table_csv,
                                     export_refined_cif, export_svg_pattern,
                                     render_html_report)


def _xrd():
    x = np.linspace(20, 70, 201)
    y = np.zeros_like(x)
    for c, a in [(28.44, 1000.0), (47.3, 600.0), (56.1, 300.0)]:
        y += a * np.exp(-0.5 * ((x - c) / 0.15) ** 2)
    return XRDData(two_theta=x, intensity=y)


def _peaks():
    return PeakList(peaks=[Peak(two_theta=28.44, intensity=1000, fwhm=0.3),
                           Peak(two_theta=47.3, intensity=600, fwhm=0.3)])


class TestSvg:
    def test_contains_curve_and_axis(self):
        svg = export_svg_pattern(_xrd(), title="Si")
        assert "<svg" in svg and "polyline" in svg
        assert "2θ (deg)" in svg and "Si" in svg

    def test_peak_markers_and_ref_sticks(self):
        svg = export_svg_pattern(_xrd(), peaks=_peaks(),
                                 ref_peaks=[(28.44, 100.0), (47.3, 60.0)])
        assert svg.count("<polygon") == 2
        assert svg.count("<line x1=") >= 3   # 参考棒 + 坐标轴


class TestHtml:
    def test_sections_present(self, tmp_path):
        matches = []
        from polyxrd.models.phase import PhaseMatchResult
        matches.append(PhaseMatchResult(
            phase=Phase(name="Silicon", formula="Si"),
            score=0.05, matched_peaks=2, total_peaks=3))
        html = render_html_report(_xrd(), peaks=_peaks(), matches=matches,
                                  quantified={"Silicon": 80.0},
                                  title="Test", out=str(tmp_path / "r.html"))
        assert html.startswith("<!DOCTYPE html>")
        assert "峰表" in html and "Silicon" in html and "80.00%" in html
        assert (tmp_path / "r.html").exists()

    def test_empty_sections_ok(self):
        html = render_html_report(_xrd())
        assert "<table" in html


class TestExportCsvCif:
    def test_csv(self, tmp_path):
        p = tmp_path / "peaks.csv"
        export_peak_table_csv(_peaks(), p)
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3                 # 表头 + 2 峰
        assert lines[1].startswith("1,")

    def test_cif_with_sites(self, tmp_path):
        ph = Phase(name="Si", formula="Si",
                   lattice=None,
                   atomic_sites=[
                       {"label": "Si1", "element": "Si",
                        "x": 0.0, "y": 0.0, "z": 0.0, "occupancy": 1.0},
                       {"label": "Si2", "element": "Si",
                        "x": 0.25, "y": 0.25, "z": 0.25, "occupancy": 1.0},
                   ])
        from polyxrd.models.phase import LatticeParams
        ph.lattice = LatticeParams(a=5.431, b=5.431, c=5.431)
        p = tmp_path / "si.cif"
        export_refined_cif(ph, p)
        text = p.read_text(encoding="utf-8")
        assert "_cell_length_a    5.431000" in text
        assert "_atom_site_fract_x" in text
        assert "Si1" in text

    def test_cif_without_sites_comments(self, tmp_path):
        p = tmp_path / "no.cif"
        export_refined_cif(Phase(name="X", formula="X"), p)
        assert "无原子位点信息" in p.read_text(encoding="utf-8")

    # ── LibreOffice 无头转换 (未安装则跳过) ──

    def test_find_libreoffice_returns_path_or_none(self):
        from polyxrd.services.report import find_libreoffice
        hit = find_libreoffice()
        assert hit is None or Path(hit).exists()

    def test_export_docx_via_libreoffice(self, tmp_path):
        from polyxrd.services.report import (
            export_via_libreoffice, find_libreoffice,
        )
        if find_libreoffice() is None:
            pytest.skip("LibreOffice 未安装")
        html = tmp_path / "r.html"
        html.write_text(
            "<html><body><h1>PolyXRD</h1><p>hello</p></body></html>",
            encoding="utf-8",
        )
        out = export_via_libreoffice(html, "docx", timeout=180)
        assert out is not None and Path(out).exists()
        assert Path(out).suffix == ".docx"

    def test_export_xlsx_from_csv(self, tmp_path):
        from polyxrd.models.peak import Peak, PeakList
        from polyxrd.services.report import (
            export_peak_table_csv, export_via_libreoffice, find_libreoffice,
        )
        if find_libreoffice() is None:
            pytest.skip("LibreOffice 未安装")
        pl = PeakList(peaks=[Peak(two_theta=28.44, intensity=1000.0,
                                  fwhm=0.12, d_spacing=3.135)])
        csv_path = tmp_path / "peaks.csv"
        export_peak_table_csv(pl, csv_path)
        out = export_via_libreoffice(csv_path, "xlsx", timeout=180)
        assert out is not None and Path(out).exists()

    def test_export_returns_none_for_missing_source(self, tmp_path):
        from polyxrd.services.report import export_via_libreoffice
        assert export_via_libreoffice(tmp_path / "nope.html", "docx") is None
