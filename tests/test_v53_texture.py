"""v5.3 P0-B：织构模型（Legendre 纤维对称级数）守护。

对标 MAUD 时发现的真实差距（`docs/评估报告-MAUD对标-精修质量-v3.md` §3）：
定量偏差全部落在片状相，单轴 March–Dollase 一个 ``r`` 拟合不了真实取向分布。
MAUD 用 4–10 阶 Harmonic（`.par` 里 `_pd_proc_ls_pref_orient_corr 'Harmonic'`，
并逐相存了 `_rita_texture_factor_calc`）。

本模型的选择理由（三条都写成测试）：

1. **球面平均恒为 1** → Hill–Howard 定量的"随机取向基准"不被织构带偏；
2. **权重恒正** → MAUD 在 S7 高岭石给出 −2.43 的负因子（``cut_negative false``），
   那种解连强度正定性都没有；这里钳到 ``TEXTURE_FLOOR``；
3. **偶阶** → 极图必须满足 ``P(cosα)=P(−cosα)``（+d 与 −d 是同一组面）。

另有一组"能不能被辨识"的定量测试：忽略织构会让两相标度比系统性跑偏，
带上正确的织构系数就能逐位还原 —— 这是"织构会带偏 wt%"的最短证明。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement.background import BackgroundParams, background_basis
from polyxrd.refinement.linear import solve_linear
from polyxrd.refinement.pattern import PhaseSpec, design_matrix
from polyxrd.refinement.profile import ProfileParams
from polyxrd.refinement.structure import (
    TEXTURE_FLOOR,
    build_reflections,
    legendre_texture_weight,
    po_direction_from_hkl,
)

pymatgen = pytest.importorskip("pymatgen", reason="结构构造依赖 pymatgen")
from pymatgen.core import Lattice, Structure  # noqa: E402

from polyxrd.refinement.cell import Cell  # noqa: E402
from polyxrd.refinement.structure import AtomSite, StructureModel  # noqa: E402


# ── 构造 ──────────────────────────────────────────────────────

def _model(struct: Structure, name: str) -> StructureModel:
    sites = []
    for site in struct:
        el = site.species.elements[0].symbol
        sites.append(AtomSite(element=el,
                              x=float(site.frac_coords[0]),
                              y=float(site.frac_coords[1]),
                              z=float(site.frac_coords[2]),
                              occupancy=float(site.species.get(el)),
                              b_iso=0.4))
    lat = struct.lattice
    return StructureModel(sites=tuple(sites), name=name,
                          cell=Cell(lat.a, lat.b, lat.c,
                                    lat.alpha, lat.beta, lat.gamma))


def _si() -> StructureModel:
    return _model(Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0, 0, 0]]), "Si")


def _tio2() -> StructureModel:
    return _model(Structure.from_spacegroup(
        "P4_2/mnm", Lattice.tetragonal(4.594, 2.959),
        ["Ti", "O"], [[0, 0, 0], [0.305, 0.305, 0]]), "TiO2")


GRID = np.arange(15.0, 90.0, 0.02)
PROFILE = ProfileParams(w=0.0035, v=-0.0008, u=0.0001, eta=0.6,
                        asymmetry=0.0, use_tch=True)
AXIS = (0, 0, 1)


def _tables(with_axis: bool = True):
    out = []
    for st in (_si(), _tio2()):
        tab = build_reflections(
            st, two_theta_range=(10.0, 100.0), wavelengths=(1.5406,),
            po_direction=(po_direction_from_hkl(AXIS, st.cell)
                          if with_axis else None))
        out.append(tab)
    return out


# ── 1. 权重函数本身 ────────────────────────────────────────────

class TestLegendreWeight:
    def test_zero_coefs_is_unity(self):
        x = np.linspace(-1, 1, 41)
        assert np.allclose(legendre_texture_weight(x, ()), 1.0)
        assert np.allclose(legendre_texture_weight(x, (0.0, 0.0, 0.0)), 1.0)

    def test_pole_values(self):
        """cosα=±1 处只有 P_l(±1)=1 起作用 → W = 1 + Σ c_l。"""
        w = legendre_texture_weight(np.array([1.0, -1.0]), (0.3, -0.1, 0.2))
        assert np.allclose(w, 1.0 + 0.3 - 0.1 + 0.2)

    def test_even_symmetry(self):
        """极图必须满足 P(cosα)=P(−cosα)，否则 +d/−d 会被算成不同强度。"""
        x = np.linspace(-1, 1, 101)
        c = (0.7, -0.35, 0.22)
        assert np.allclose(legendre_texture_weight(x, c),
                           legendre_texture_weight(-x, c))

    def test_spherical_average_is_one(self):
        """**定量正确性的核心**：平均取向因子必须是 1。

        否则 Hill–Howard 的"随机取向"强度基准被整体缩放，wt% 会系统性偏。
        MAUD 的 Harmonic 解在 S7 高岭石上跑到 −2.43，这一条正好卡住它。
        """
        th = np.linspace(0.0, np.pi, 200001)
        x = np.cos(th)
        w = legendre_texture_weight(x, (0.9, -0.6, 0.45, 0.3))
        # ∮P dΩ/(4π) = ∫₀^π P(cosθ) sinθ dθ / 2
        avg = float(np.trapezoid(w * np.sin(th), th) / 2.0)
        assert abs(avg - 1.0) < 1e-6

    def test_floor_prevents_negative_intensity(self):
        """大负系数必须被下限钳住 —— 负强度没有物理意义。"""
        x = np.linspace(-1, 1, 201)
        w = legendre_texture_weight(x, (-1.5, -1.5, -1.5))
        assert float(w.min()) >= TEXTURE_FLOOR - 1e-12
        assert np.all(np.isfinite(w))


# ── 2. 反射表重加权 ────────────────────────────────────────────

class TestTableReweight:
    def _tab(self):
        return _tables()[0]

    def test_no_detail_returns_untouched(self):
        tab = _tables(with_axis=False)[0]
        assert tab.po_detail is None
        assert tab.reweight(1.0, (0.5, 0.0, 0.0)) is tab.intensity

    def test_zero_coefs_noop(self):
        tab = self._tab()
        assert tab.po_detail is not None
        assert tab.reweight(1.0, (0.0, 0.0, 0.0)) is tab.intensity

    def test_matches_manual_per_reflection_sum(self):
        """归并后的峰强度必须等于"逐反射乘权重再求和"。"""
        tab = self._tab()
        coefs = (0.6, -0.2, 0.1)
        values, cos_a, offsets = tab.po_detail
        expect = np.add.reduceat(values * legendre_texture_weight(cos_a, coefs),
                                 offsets[:-1])
        assert np.allclose(tab.reweight(1.0, coefs), expect)

    def test_md_and_texture_compose(self):
        """MD 与 Legendre 相乘后再归并，等价于两次权重之积逐反射求和。"""
        tab = self._tab()
        from polyxrd.refinement.structure import march_dollase_weight
        values, cos_a, offsets = tab.po_detail
        coefs = (0.5, 0.0, 0.0)
        w = march_dollase_weight(cos_a, 0.7) * legendre_texture_weight(cos_a, coefs)
        expect = np.add.reduceat(values * w, offsets[:-1])
        assert np.allclose(tab.reweight(0.7, coefs), expect)

    def test_total_intensity_scales_with_average(self):
        """随机取向（系数全零）时两相的总强度比不应被织构代码改动。"""
        tab = self._tab()
        assert np.isclose(float(tab.reweight(1.0, (0.0, 0.0, 0.0)).sum()),
                          float(tab.intensity.sum()))


# ── 3. 织构会把标度比带偏（可辨识性）────────────────────────────

class TestTextureBias:
    """两相 1:1 混合，只给第一相加织构：忽略织构必然把标度比带偏。"""

    COEF = (0.8, -0.3, 0.15)

    def _setup(self):
        a, b = _tables()
        prof = PROFILE
        truth_specs = [PhaseSpec(table=a, po_c=self.COEF), PhaseSpec(table=b)]
        basis_true = design_matrix(GRID, truth_specs, prof,
                                   wavelength=1.5406, cutoff_fwhm=20.0)
        bg = background_basis(GRID, BackgroundParams("tent", 8))
        coefs = np.array([300.0, 50.0, 20.0, 8.0, 3.0, 1.0, 0.3, 0.0])
        y = basis_true @ np.array([1.0, 1.0]) + bg @ coefs
        return a, b, prof, y, bg

    def test_ignoring_texture_biases_phase_ratio(self):
        a, b, prof, y, bg = self._setup()
        basis = design_matrix(GRID, [PhaseSpec(table=a), PhaseSpec(table=b)],
                              prof, wavelength=1.5406, cutoff_fwhm=20.0)
        lin = solve_linear(basis, y, weights=1.0 / np.maximum(y, 1.0),
                           bg_basis=bg)
        ratio = float(lin.scales[0] / lin.scales[1])
        # 真值 1.0；不带织构时第一相标度被带偏（实测约 +30%）
        assert abs(ratio - 1.0) > 0.05, f"忽略织构却没带偏：ratio={ratio:.4f}"

    def test_correct_texture_restores_ratio(self):
        a, b, prof, y, bg = self._setup()
        basis = design_matrix(
            GRID, [PhaseSpec(table=a, po_c=self.COEF), PhaseSpec(table=b)],
            prof, wavelength=1.5406, cutoff_fwhm=20.0)
        lin = solve_linear(basis, y, weights=1.0 / np.maximum(y, 1.0),
                           bg_basis=bg)
        ratio = float(lin.scales[0] / lin.scales[1])
        assert abs(ratio - 1.0) < 1e-6, f"带对织构仍偏：ratio={ratio:.6f}"


# ── 4. 服务层接线 ─────────────────────────────────────────────

class TestServiceWiring:
    """`texture_model` 参数：默认仍是 MD（旧行为逐位不变），legendre 才放开级数。"""

    def _refine(self, **kw):
        from polyxrd.models.xrd_data import XRDData
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        a, b = _tables()
        y = (design_matrix(GRID, [PhaseSpec(table=a, po_c=(0.7, 0.0, 0.0)),
                                  PhaseSpec(table=b)], PROFILE,
                           wavelength=1.5406, cutoff_fwhm=20.0)
             @ np.array([500.0, 400.0]))
        rng = np.random.default_rng(7)
        y = np.maximum(y + rng.normal(0.0, 3.0, y.size) + 20.0, 0.0)
        data = XRDData(two_theta=GRID.copy(), intensity=y, wavelength=1.5406)
        return RietveldRefiner().refine(data, self._phases(), engine="refinement",
                                        max_cycles=3, **kw)

    @staticmethod
    def _phases():
        from polyxrd.models.phase import LatticeParams, Phase
        out = []
        for st in (_si(), _tio2()):
            lat = st.cell
            sites = [{"label": f"{s.element}{k}", "element": s.element,
                      "x": s.x, "y": s.y, "z": s.z,
                      "occupancy": s.occupancy, "b_iso": s.b_iso}
                     for k, s in enumerate(st.sites)]
            out.append(Phase(
                name=st.name, formula="", atomic_sites=sites,
                lattice=LatticeParams(a=lat.a, b=lat.b, c=lat.c,
                                      alpha=lat.alpha, beta=lat.beta,
                                      gamma=lat.gamma)))
        return out

    def test_default_is_march_dollase(self):
        res = self._refine()
        assert res.fit_params.get("v5_texture_model") == "march_dollase"
        assert res.fit_params.get("v5_texture_degree") == 0

    def test_legendre_reports_degree_and_pins_r(self):
        res = self._refine(texture_model="legendre", texture_degree=4,
                           _po_directions={0: (0, 0, 1)},
                           auto_preferred_orientation=False)
        fp = res.fit_params
        assert fp.get("v5_texture_model") == "legendre"
        assert fp.get("v5_texture_degree") == 4
        coefs = fp.get("v5_texture_coef") or []
        assert len(coefs) == 2 and len(coefs[0]) == 2, coefs
        # MD 的 r 必须被钉住（与 Legendre 在同一 cosα 上会互相抵消）
        assert abs(float(fp["v5_po_r"][0]) - 1.0) < 1e-12
