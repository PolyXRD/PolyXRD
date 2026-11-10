"""v5.5 P0-B″/P0-C 验收：各向异性展宽（P₂/P₄）与低角拖尾。

对应《评测报告-MAUD对标-v5-20261107.md》§9：
* P0-B″：``FWHM_hkl = FWHM_iso·(1 + c2·P₂(cosφ) + c4·P₄(cosφ))``，
  cosφ = 峰法向与 c* 轴的余弦；
* P0-C：低角拖尾 = 主峰 ``(1−t)`` + 左移 0.25·FWHM、宽 3.2× 的洛伦兹
  ``t``（面积守恒）；
* 两者默认 **opt-in**：关闭时参数固定为 0、数值逐位保持 v5.3 行为。
"""
from __future__ import annotations

import numpy as np
import pytest

pymatgen = pytest.importorskip("pymatgen")
from pymatgen.core import Lattice, Structure  # noqa: E402

from polyxrd.refinement import (  # noqa: E402
    AtomSite,
    Cell,
    PhaseSpec,
    ProfileParams,
    StructureModel,
    build_reflections,
    phase_pattern,
)
from polyxrd.refinement.problem import PatternProblem, PhaseBlock  # noqa: E402


def _si_cubic() -> StructureModel:
    struct = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0, 0, 0]])
    sites = [AtomSite(element="Si", x=float(s.frac_coords[0]),
                      y=float(s.frac_coords[1]),
                      z=float(s.frac_coords[2]), occupancy=1.0)
             for s in struct]
    lat = struct.lattice
    return StructureModel(
        sites=tuple(sites), name="Si",
        cell=Cell(lat.a, lat.b, lat.c, lat.alpha, lat.beta, lat.gamma))


def _p2(x: float) -> float:
    return 0.5 * (3.0 * x * x - 1.0)


def _setup(c2: float = 0.0, c4: float = 0.0, tail: float = 0.0):
    model = _si_cubic()
    table = build_reflections(model,
                              two_theta_range=(15.0, 100.0))
    profile = ProfileParams(w=0.02 ** 2, tail=tail, use_tch=False)
    spec = PhaseSpec(table=table, aniso_c2=c2, aniso_c4=c4)
    grid = np.arange(15.0, 100.0, 0.02)
    return table, profile, spec, grid


def test_cos_phi_c_is_one_along_c_star():
    """立方/四方晶胞：00l 的 cosφ=1、h00/hk0 的 cosφ=0。"""
    table, *_ = _setup()
    hkl = np.asarray(table.hkl, dtype=int)
    cos = np.asarray(table.cos_phi_c, dtype=float)
    pick001 = (np.abs(hkl[:, 0]) == 0) & (np.abs(hkl[:, 1]) == 0) \
        & (np.abs(hkl[:, 2]) > 0)
    pick100 = (np.abs(hkl[:, 0]) > 0) & (np.abs(hkl[:, 1]) == 0) \
        & (np.abs(hkl[:, 2]) == 0)
    assert np.allclose(cos[pick001], 1.0, atol=1e-6)
    assert np.allclose(cos[pick100], 0.0, atol=1e-6)


def test_aniso_scales_fwhm_by_p2():
    """c2=0.5 时，00l 的 FWHM 应为等宽的 1.5×（P₂(1)=1）。"""
    table, profile, spec0, grid = _setup()
    _y, det0 = phase_pattern(grid, spec0, profile, wavelength=1.54056,
                             cutoff_fwhm=None, return_detail=True)
    spec = PhaseSpec(table=table, aniso_c2=0.5)
    _y, det = phase_pattern(grid, spec, profile, wavelength=1.54056,
                            cutoff_fwhm=None, return_detail=True)
    ratio = np.asarray(det.fwhm) / np.asarray(det0.fwhm)
    cos = np.asarray(table.cos_phi_c, dtype=float)
    expected = 1.0 + 0.5 * _p2(cos)
    assert np.allclose(ratio, expected, rtol=1e-10, atol=1e-12)


def test_aniso_off_is_bitwise_identical():
    """全零系数 → 与不带 aniso 的谱逐位相同。"""
    table, profile, spec0, grid = _setup()
    y0 = phase_pattern(grid, spec0, profile, wavelength=1.54056,
                       cutoff_fwhm=None)
    y1 = phase_pattern(grid, PhaseSpec(table=table, aniso_c2=0.0,
                                       aniso_c4=0.0),
                       profile, wavelength=1.54056, cutoff_fwhm=None)
    assert np.array_equal(y0, y1)


def test_tail_conserves_area_and_lowers_peak():
    """拖尾只改形状不改总面积：∫y 守恒，峰高下降。"""
    _t, profile0, spec, grid = _setup()
    _t, profile_t, spec, _g = _setup(tail=0.2)
    y0 = phase_pattern(grid, spec, profile0, wavelength=1.54056,
                       cutoff_fwhm=None)
    y1 = phase_pattern(grid, spec, profile_t, wavelength=1.54056,
                       cutoff_fwhm=None)
    a0, a1 = float(np.trapezoid(y0, grid)), float(np.trapezoid(y1, grid))
    assert abs(a1 - a0) / max(a0, 1e-12) < 0.02
    assert float(y1.max()) < float(y0.max())


def test_tail_off_is_bitwise_identical():
    _t, profile0, spec, grid = _setup()
    _t, profile_zero, spec, _g = _setup(tail=0.0)
    y0 = phase_pattern(grid, spec, profile0, wavelength=1.54056,
                       cutoff_fwhm=None)
    y1 = phase_pattern(grid, spec, profile_zero, wavelength=1.54056,
                       cutoff_fwhm=None)
    assert np.array_equal(y0, y1)


def test_problem_params_opt_in_defaults():
    """默认关闭：aniso.c2/c4 与 inst.tail 固定；显式开启才自由。"""
    model = _si_cubic()
    table = build_reflections(model,
                              two_theta_range=(15.0, 100.0))
    tt = np.arange(15.0, 100.0, 0.02)
    y = np.ones_like(tt)
    block = PhaseBlock(label="Si", structure=model, table=table)
    prob = PatternProblem(tt, y, [block], wavelength=1.54056)
    params = prob.build_parameters()
    assert params["phase0.aniso.c2"].fixed
    assert params["phase0.aniso.c4"].fixed
    assert params["inst.tail"].fixed

    block2 = PhaseBlock(label="Si", structure=model, table=table, aniso_on=True)
    prob2 = PatternProblem(tt, y, [block2], wavelength=1.54056, tail_on=True)
    params2 = prob2.build_parameters()
    assert not params2["phase0.aniso.c2"].fixed
    assert not params2["phase0.aniso.c4"].fixed
    assert not params2["inst.tail"].fixed

