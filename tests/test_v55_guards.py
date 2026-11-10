"""v5.5 守卫/产品化单测：P0-E′ 区间、弱相晶胞冻结。"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

pymatgen = pytest.importorskip("pymatgen")
from pymatgen.core import Lattice, Structure  # noqa: E402

from polyxrd.refinement import (  # noqa: E402
    AtomSite,
    Cell,
    StructureModel,
    build_reflections,
)
from polyxrd.refinement.problem import (  # noqa: E402
    WEAK_PHASE_CELL_SHARE,
    PatternProblem,
    PhaseBlock,
)
from polyxrd.refinement.report import (  # noqa: E402
    Finding,
    wt_ranges_from_findings,
)


def _si() -> StructureModel:
    struct = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0, 0, 0]])
    sites = [AtomSite(element="Si", x=float(s.frac_coords[0]),
                      y=float(s.frac_coords[1]), z=float(s.frac_coords[2]),
                      occupancy=1.0) for s in struct]
    lat = struct.lattice
    return StructureModel(sites=tuple(sites), name="Si",
                          cell=Cell(lat.a, lat.b, lat.c,
                                    lat.alpha, lat.beta, lat.gamma))


def test_wt_range_helper_basic():
    f = Finding(
        "PHASE_NEAR_DEGENERATE", "warn", "m", "h",
        {"phase": "Muscovite", "fraction_pct": 44.0, "ratio": 80.0})
    out = wt_ranges_from_findings([f])
    # half = 80 × 0.2 = 16 pp
    assert out["Muscovite"] == pytest.approx([28.0, 60.0])


def test_wt_range_helper_ignores_other_codes_and_clamps():
    f = Finding("PHASE_FRACTION_UNVERIFIABLE", "warn", "m", "h", {"phase": "X"})
    assert wt_ranges_from_findings([f]) == {}
    f2 = Finding("PHASE_NEAR_DEGENERATE", "warn", "m", "h",
                 {"phase": "Y", "fraction_pct": 95.0, "ratio": 60.0})
    lo, hi = wt_ranges_from_findings([f2])["Y"]
    assert 0.0 <= lo and hi <= 100.0


def test_weak_phase_cell_is_frozen():
    model = _si()
    table = build_reflections(model, two_theta_range=(15.0, 100.0))
    weak_table = replace(table, intensity=np.full_like(table.intensity, 1.0e-6))
    tt = np.arange(15.0, 100.0, 0.02)

    strong = PhaseBlock(label="Strong", structure=model, table=table, index=0)
    weak = PhaseBlock(label="Weak", structure=model, table=weak_table, index=1)
    prob = PatternProblem(tt, np.ones_like(tt), [strong, weak],
                          wavelength=1.54056)
    params = prob.build_parameters()
    assert not params["phase0.cell.a"].fixed
    assert params["phase1.cell.a"].fixed
    assert params["phase1.cell.gamma"].fixed

    share = float(np.sum(weak_table.intensity)) / (
        float(np.sum(table.intensity)) + float(np.sum(weak_table.intensity)))
    assert share < WEAK_PHASE_CELL_SHARE


def test_normal_single_phase_keeps_cell_free():
    model = _si()
    table = build_reflections(model, two_theta_range=(15.0, 100.0))
    tt = np.arange(15.0, 100.0, 0.02)
    prob = PatternProblem(tt, np.ones_like(tt),
                          [PhaseBlock(label="Si", structure=model, table=table)],
                          wavelength=1.54056)
    assert not prob.build_parameters()["phase0.cell.a"].fixed
