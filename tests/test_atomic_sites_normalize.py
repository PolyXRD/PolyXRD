"""atomic_sites 键名统一 + U_iso 解析 (实施手册 v3 / M6-W20)
=========================================================
`_extract_atomic_sites` 此前只产出 fract_x/fract_y/fract_z (且只把 4 个列转 float),
而下游 (phase_to_cif_text / pymatgen 直构 / 3D 视图) 一律读 x/y/z/element/u_iso
→ 走 CIF 解析的物相在下游**静默失败**。

本测试锁住新契约: 规范键必须齐, 原始 fract_* 键必须保留 (兼容), u_iso 必须
按 U_iso_or_equiv 优先 / B_iso_or_equiv÷(8π²) / 缺省 0.005 的规则给出。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.services.cif_database import _extract_atomic_sites

CIF_U = """data_test
_cell_length_a 5.431
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_occupancy
Si1 Si 0.0000 0.0000 0.0000 0.006(1) 1.0
O1 O 0.2500 0.2500 0.2500 0.0100 0.500
"""

CIF_B = """data_test
_cell_length_a 5.431
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_B_iso_or_equiv
Si1 Si 0.0000 0.0000 0.0000 0.0789569
"""

CIF_NONE = """data_test
_cell_length_a 5.431
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0.0000 0.0000 0.0000
"""


class TestAtomicSitesNormalize:

    def test_canonical_keys_present_and_fract_kept(self):
        sites = _extract_atomic_sites(CIF_U)
        assert len(sites) == 2
        s = sites[0]
        for k in ("label", "element", "x", "y", "z", "occupancy", "u_iso"):
            assert k in s, f"缺少规范键 {k}: {s}"
        # 兼容: 原始 fract_* 键保留
        assert "fract_x" in s and "fract_y" in s and "fract_z" in s
        assert s["x"] == pytest.approx(0.0)
        assert sites[1]["x"] == pytest.approx(0.25)
        assert sites[1]["occupancy"] == pytest.approx(0.5)
        assert sites[1]["element"] == "O"

    def test_u_iso_from_u_column_with_esd(self):
        sites = _extract_atomic_sites(CIF_U)
        assert sites[0]["u_iso"] == pytest.approx(0.006)
        assert sites[0]["u_iso_default"] is False
        assert sites[1]["u_iso"] == pytest.approx(0.010)

    def test_b_iso_converted_to_u_iso(self):
        sites = _extract_atomic_sites(CIF_B)
        assert len(sites) == 1
        # B = 8π²U  →  0.0789569 / (8π²) = 0.001 Å²
        assert sites[0]["u_iso"] == pytest.approx(0.001, rel=1e-3)
        assert sites[0]["u_iso_default"] is False

    def test_missing_adp_uses_default(self):
        sites = _extract_atomic_sites(CIF_NONE)
        assert len(sites) == 1
        assert sites[0]["u_iso"] == pytest.approx(0.005)
        assert sites[0]["u_iso_default"] is True

    def test_downstream_phase_to_cif_text_accepts_parsed_sites(self):
        """回归: 解析出的位点能直接喂给 phase_to_cif_text (此前 KeyError 被吞掉)"""
        from polyxrd.models.phase import LatticeParams, Phase
        from polyxrd.services.phase_cif import phase_to_cif_text
        sites = _extract_atomic_sites(CIF_U)
        ph = Phase(name="t", formula="SiO2", space_group="P1",
                   lattice=LatticeParams(a=5.431, b=5.431, c=5.431),
                   atomic_sites=sites)
        txt = phase_to_cif_text(ph)
        assert "_atom_site_fract_x" in txt
        assert "Si1" in txt


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
