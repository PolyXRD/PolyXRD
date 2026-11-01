"""v5.0.0 阶段 A 验收：前向模型（散射因子 → 晶胞 → 反射表 → 峰形 → 背景 → 合成谱）。

这批用例是 ``src/polyxrd/refinement/`` 的**口径守卫** —— 每一条都对应一个
"算错了会在物理上露馅"的不变量，改动内核若要修改这里的数字，必须先在
``docs/全谱拟合优化方案-v5.0.0.md`` 里说明理由。

覆盖清单
--------
* 散射因子：Cromer–Mann 紧凑式 ``f(0)=Z``、与 pymatgen 逐元素一致
* 晶胞几何：六大晶系 d 值（**含六方/单斜/三斜的转置陷阱回归**）
* 反射表：与 pymatgen ``XRDCalculator`` 逐峰比对（峰位 0.000000°、相对强度 0.000）
* 峰形：面积归一（解析）、split 峰心连续 + 面积守恒、Caglioti(tanθ)、TCH、尺寸-应变单位
* 背景：Chebyshev 近似正交、tent 单位分解
* 装配：峰面积 == 反射强度、Kα2 面积守恒、设计矩阵与 synthesize 一致
"""

from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement import (
    Cell,
    AtomSite,
    StructureModel,
    build_reflections,
    ProfileParams,
    Kalpha2,
    BackgroundParams,
    area_normalized_profile,
    caglioti_fwhm,
    tch_combine,
    tch_widths,
    split_asymmetry_factor,
    split_scale_factors,
    ka2_two_theta,
    chebyshev_basis,
    tent_basis,
    background_basis,
    PhaseSpec,
    phase_pattern,
    design_matrix,
    synthesize,
)
from polyxrd.refinement.profile import FWHM_TO_SIGMA

pymatgen = pytest.importorskip("pymatgen", reason="散射因子比对依赖 pymatgen")
from pymatgen.core import Lattice, Structure  # noqa: E402
from pymatgen.analysis.diffraction.xrd import XRDCalculator  # noqa: E402


# ── 共用构造 ──────────────────────────────────────────────────

def _model_from_pmg(struct: Structure, name: str = "", b_iso: float = 0.0):
    """pymatgen Structure → StructureModel。

    ``b_iso=0.0`` 是**必须**的：``XRDCalculator`` 不计 Debye–Waller 温度因子，
    用默认的 0.5 会让每一峰的相对强度都偏低（实测 Si 的 max|ΔI| 达 3.8）。
    """
    sites = []
    for site in struct:
        el = site.species.elements[0].symbol
        sites.append(AtomSite(
            element=el,
            x=float(site.frac_coords[0]),
            y=float(site.frac_coords[1]),
            z=float(site.frac_coords[2]),
            occupancy=float(site.species.get(el)),
            b_iso=b_iso,
        ))
    lat = struct.lattice
    return StructureModel(
        sites=tuple(sites), name=name,
        cell=Cell(lat.a, lat.b, lat.c, lat.alpha, lat.beta, lat.gamma),
    )


def _si():
    return Structure.from_spacegroup("Fd-3m", Lattice.cubic(5.431), ["Si"], [[0, 0, 0]])


def _tio2():
    return Structure.from_spacegroup(
        "I41/amd", Lattice.tetragonal(3.7845, 9.5143),
        ["Ti", "O"], [[0, 0, 0], [0, 0, 0.2081]])


def _lfp():
    return Structure.from_spacegroup(
        "Pnma", Lattice.orthorhombic(10.33, 6.01, 4.69),
        ["Li", "Fe", "P", "O"],
        [[0, 0, 0], [0.2821, 0.25, 0.9745], [0.0947, 0.25, 0.4183],
         [0.0966, 0.25, 0.7427]])


def _linio2():
    return Structure.from_spacegroup(
        "R-3m", Lattice.hexagonal(2.878, 14.19),
        ["Li", "Ni", "O"], [[0, 0, 0.5], [0, 0, 0], [0, 0, 0.241]])


def _mono():
    return Structure.from_spacegroup(
        "P2_1/c", Lattice.monoclinic(5.0, 6.0, 7.0, 100.0),
        ["Si", "Si"], [[0, 0, 0], [0.3, 0.35, 0.4]])


def _tric():
    return Structure.from_spacegroup(
        "P-1", Lattice.from_parameters(5.0, 6.0, 7.0, 80.0, 75.0, 70.0),
        ["Si", "O"], [[0, 0, 0], [0.3, 0.35, 0.4]])


ALL_STRUCTS = [
    ("Si Fd-3m", _si),
    ("TiO2 I41/amd", _tio2),
    ("LiFePO4 Pnma", _lfp),
    ("LiNiO2 R-3m", _linio2),
    ("Si P21/c", _mono),
    ("Si/O P-1", _tric),
]


# ── 散射因子 ──────────────────────────────────────────────────

class TestScattering:
    def test_form_factor_at_zero_is_z(self):
        """Cromer–Mann 紧凑式在 s=0 处必须严格等于原子序数。"""
        from polyxrd.refinement import atomic_form_factor, atomic_number
        for sym, z in [("Si", 14), ("Fe", 26), ("O", 8), ("Ni", 28),
                       ("Li", 3), ("P", 15), ("Ti", 22), ("U", 92)]:
            assert abs(float(atomic_form_factor(sym, np.array([0.0]))[0]) - z) < 1e-9
            assert atomic_number(sym) == z

    def test_element_normalization(self):
        """``'fe'``/``'FE'``/``'Fe3+'`` 都归一成 ``'Fe'``；未知符号原子序数为 0。

        ``normalize_element`` 只做**词法**归一（取字母前缀），不做存在性校验 ——
        校验交给 ``atomic_number`` / ``has_scattering_params``。
        """
        from polyxrd.refinement import (
            normalize_element, atomic_number, has_scattering_params)
        assert normalize_element("fe") == "Fe"
        assert normalize_element("FE") == "Fe"
        assert normalize_element("Fe3+") == "Fe"
        assert normalize_element("O2-") == "O"
        assert normalize_element(" Si ") == "Si"
        assert normalize_element("") == ""
        assert atomic_number("Xx") == 0
        assert has_scattering_params("Xx") is False
        assert has_scattering_params("Si") is True

    def test_form_factor_monotone_decreasing(self):
        """``f(s)`` 在**物理可达域** ``s = sinθ/λ ≤ 1.4`` 内单调下降。

        上限 1.4 覆盖 Cu(0.65) / Co(0.71) / Mo(1.41) 靶。紧凑式在大 s 处会回升
        （``Σa·exp(−b s²)`` 衰减到 0，减项消失后 f 回到 Z），实测 Si 在 s≈1.585
        转升 —— 那是**拟合区间之外**，Ag Kα（s_max=1.79）才有影响，实验室光源
        碰不到。真需要 Ag 靶时再换 9 参数表。
        """
        from polyxrd.refinement import atomic_form_factor
        s = np.linspace(0.0, 1.4, 200)
        for sym in ("Si", "Fe", "O", "Li", "Ni", "P", "Ti"):
            assert np.all(np.diff(atomic_form_factor(sym, s)) < 1e-9), sym

    def test_form_matches_pymatgen(self):
        """逐元素与 pymatgen ``ATOMIC_SCATTERING_PARAMS`` 同式同值。

        pymatgen 的向量化写法（``xrd.py`` 注释里给出的等价式）就是
        ``Z − 41.78214·s²·Σ a_i·exp(−b_i·s²)`` —— 与本节口径**逐字一致**。
        """
        from polyxrd.refinement import atomic_form_factor, atomic_number
        from pymatgen.analysis.diffraction.xrd import ATOMIC_SCATTERING_PARAMS
        s = np.array([0.0, 0.1, 0.3, 0.6, 1.0, 1.3])
        s2 = s ** 2
        for sym in ("Si", "Fe", "O", "Li", "Ni", "P", "Ti", "Mn", "Co"):
            coeff = ATOMIC_SCATTERING_PARAMS[sym]
            ref = atomic_number(sym) - 41.78214 * s2 * sum(
                c[0] * np.exp(-c[1] * s2) for c in coeff)
            mine = atomic_form_factor(sym, s)
            assert np.allclose(mine, ref, atol=1e-10), (
                f"{sym}: 最大偏差 {np.max(np.abs(mine - ref)):.2e}")


# ── 晶胞几何（转置陷阱回归）───────────────────────────────────

class TestCellGeometry:
    def test_cubic_d_spacing(self):
        from polyxrd.refinement import d_spacings
        c = Cell(5.431, 5.431, 5.431)
        assert abs(float(d_spacings([[1, 1, 1]], c)[0]) - 5.431 / np.sqrt(3)) < 1e-12

    def test_hexagonal_d_spacing_regression(self):
        """六方 d 值必须用 ``hkl @ B``（B 的行即倒易基矢）。

        历史 bug：写成 ``hkl @ B.T``。转置只在**正交晶胞**下偶然等价 ——
        LiNiO2 R-3m 的 d(101) 会算成 2.8206，而正确值是 2.4549。
        """
        from polyxrd.refinement import d_spacings
        c = Cell(2.878, 2.878, 14.19, 90.0, 90.0, 120.0)
        d = float(d_spacings([[1, 0, 1]], c)[0])
        # 六方 d 公式：1/d² = 4(h²+hk+k²)/(3a²) + l²/c²
        ref = 1.0 / np.sqrt(4.0 * 1.0 / (3.0 * 2.878 ** 2) + 1.0 / 14.19 ** 2)
        assert abs(d - ref) < 1e-12, f"d(101)={d:.4f} 应为 {ref:.4f}"
        assert abs(d - 2.4549) < 5e-4

    def test_monoclinic_d_spacing(self):
        """单斜 d 公式（**k²/b² 要乘 sin²β**，常被漏掉）。"""
        from polyxrd.refinement import d_spacings
        a, b, c = 5.0, 6.0, 7.0
        beta = np.radians(100.0)
        cell = Cell(a, b, c, 90.0, 100.0, 90.0)
        h, k, l = 1.0, 2.0, 3.0
        sb = np.sin(beta) ** 2
        inv_d2 = ((h / a) ** 2 + (k / b) ** 2 * sb + (l / c) ** 2
                  - 2 * h * l * np.cos(beta) / (a * c)) / sb
        ref = 1.0 / np.sqrt(inv_d2)
        got = float(d_spacings([[h, k, l]], cell)[0])
        assert abs(got - ref) < 1e-12, f"{got:.8f} vs {ref:.8f}"

    def test_two_theta_roundtrip(self):
        from polyxrd.refinement import two_theta_from_d
        d = np.array([1.0, 2.0, 3.0])
        tt = two_theta_from_d(d, 1.54056)
        back = 1.54056 / (2.0 * np.sin(np.radians(tt) / 2.0))
        assert np.allclose(back, d, rtol=1e-12)

    def test_volume(self):
        assert abs(Cell(2.0, 3.0, 4.0).volume() - 24.0) < 1e-12
        hexv = Cell(2.0, 2.0, 5.0, 90.0, 90.0, 120.0).volume()
        assert abs(hexv - 2.0 * 2.0 * 5.0 * np.sin(np.radians(60.0))) < 1e-12


# ── 反射表 vs pymatgen ────────────────────────────────────────

class TestReflectionsMatchPymatgen:
    """六体系逐峰比对：峰位与相对强度都必须严丝合缝。"""

    @pytest.mark.parametrize("name,factory", ALL_STRUCTS)
    def test_positions_and_intensities(self, name, factory):
        lam = 1.54056
        tmin, tmax = 10.0, 90.0
        struct = factory()

        patt = XRDCalculator(wavelength=lam).get_pattern(
            struct, two_theta_range=(tmin, tmax))
        model = _model_from_pmg(struct, name)
        table = build_reflections(model, two_theta_range=(tmin, tmax),
                                  wavelengths=(lam,))

        ref_tt = np.asarray(patt.x, dtype=float)
        ref_i = np.asarray(patt.y, dtype=float)
        ref_i = ref_i / ref_i.max() * 100.0
        my_tt = np.asarray(table.two_theta, dtype=float)
        my_i = np.asarray(table.intensity, dtype=float)
        my_i = my_i / my_i.max() * 100.0

        unmatched = []
        pos_err, int_err = [], []
        for i in range(ref_tt.size):
            j = int(np.argmin(np.abs(my_tt - ref_tt[i])))
            delta = abs(my_tt[j] - ref_tt[i])
            if delta > 0.02:
                unmatched.append(float(ref_tt[i]))
                continue
            pos_err.append(delta)
            int_err.append(abs(my_i[j] - ref_i[i]))

        assert not unmatched, f"{name}: 有 {len(unmatched)} 个 pymatgen 峰找不到对应"
        assert max(pos_err) < 1e-6, f"{name}: 峰位最大偏差 {max(pos_err):.2e}°"
        assert max(int_err) < 1e-6, f"{name}: 强度最大偏差 {max(int_err):.2e}"

    def test_b_iso_attenuates_only(self):
        """Debye–Waller 只能衰减，不能增强任何反射的绝对强度。"""
        struct = _linio2()
        m0 = _model_from_pmg(struct, "LiNiO2", b_iso=0.0)
        m1 = _model_from_pmg(struct, "LiNiO2", b_iso=1.0)
        t0 = build_reflections(m0, two_theta_range=(10.0, 90.0))
        t1 = build_reflections(m1, two_theta_range=(10.0, 90.0))
        assert t0.two_theta.size == t1.two_theta.size
        assert np.all(t1.intensity <= t0.intensity * (1.0 + 1e-9))
        # 高角衰减更狠
        hi = t0.two_theta > 60.0
        assert np.median(t1.intensity[hi] / t0.intensity[hi]) < 0.95

    def test_merge_tolerance(self):
        """同 2θ（<1e-3°）的反射必须合并，且强度求和；系统消光被剔除。"""
        from polyxrd.refinement import TWO_THETA_MERGE_TOL
        assert TWO_THETA_MERGE_TOL == 1e-3
        tab = build_reflections(_model_from_pmg(_si()), two_theta_range=(20.0, 90.0))
        assert tab.two_theta.size == tab.intensity.size == tab.n_merged.size
        assert np.all(tab.n_merged >= 1)
        # 金刚石结构的 F 心消光：(110)/(200)/(211) 等混奇偶反射强度为 0，
        # noise_ratio 阈值必须把它们剔掉 —— 否则 (110) 会以 23.14° 混进来
        assert not np.any(np.abs(tab.two_theta - 23.1415) < 0.01)
        # 与 pymatgen 的独立峰数一致
        patt = XRDCalculator(wavelength=1.54056).get_pattern(
            _si(), two_theta_range=(20.0, 90.0))
        assert tab.two_theta.size == len(patt.x)


# ── 峰形 ──────────────────────────────────────────────────────

def _pv_analytic_area(fwhm, eta, a):
    from math import erf, atan, pi
    sigma = fwhm * FWHM_TO_SIGMA
    gamma = fwhm / 2.0
    g = erf(a / (sigma * np.sqrt(2.0)))
    ell = 2.0 / pi * atan(a / gamma)
    return eta * g + (1.0 - eta) * ell


class TestProfileNormalization:
    @pytest.mark.parametrize("kind", ["gaussian", "lorentzian", "pseudo-voigt"])
    @pytest.mark.parametrize("fwhm", [0.02, 0.08, 0.3, 1.5])
    def test_area_unity_backward(self, kind, fwhm):
        """``∫pV = 1``（用解析式，避免 Lorentz 长尾被误判）。"""
        eta = {"gaussian": 1.0, "lorentzian": 0.0}.get(kind, 0.7)
        a = 4000.0 * fwhm
        assert abs(_pv_analytic_area(fwhm, eta, a) - 1.0) < 2e-3

    @pytest.mark.parametrize("kind", ["gaussian", "lorentzian", "pseudo-voigt"])
    def test_matches_legacy_phase_display(self, kind):
        """非 split 分支必须与 ``phase_display`` 逐点一致（口径不漂）。"""
        from polyxrd.services.phase_display import _area_normalized_profile as legacy
        d = np.linspace(-3, 3, 20001)
        assert np.allclose(
            area_normalized_profile(d, 0.15, 0.7, kind), legacy(d, 0.15, 0.7, kind))

    def test_split_center_is_continuous(self):
        """split-PV 在峰心**必须连续**。

        裸 split（左右各自面积归一到 0.5）会让峰值 = 1/宽度，左右宽度比就是
        峰顶跳变比 —— 实测 a=0.25 时跳 66%，峰顶是台阶。本模块用
        ``split_scale_factors`` 做高度归一修正。
        """
        eps = 1e-9
        lo = float(area_normalized_profile(
            np.array([-eps]), 0.2, 0.6, "pseudo-voigt", 0.30, 0.18)[0])
        hi = float(area_normalized_profile(
            np.array([eps]), 0.2, 0.6, "pseudo-voigt", 0.30, 0.18)[0])
        assert abs(lo - hi) / lo < 1e-9
        # 同时确认旧版确实跳（记录已知差异，防止有人"修回去"）
        from polyxrd.services.phase_display import _area_normalized_profile as legacy
        old_lo = float(legacy(np.array([-eps]), 0.2, 0.6, "pseudo-voigt", 0.30, 0.18)[0])
        old_hi = float(legacy(np.array([eps]), 0.2, 0.6, "pseudo-voigt", 0.30, 0.18)[0])
        assert (old_hi - old_lo) / old_lo > 0.5

    def test_split_area_conserved(self):
        """split 的总面积仍为 1，且宽侧分到更多。"""
        from scipy import integrate
        xs = np.linspace(-100, 100, 400001)
        y = area_normalized_profile(xs, 0.2, 0.6, "pseudo-voigt", 0.30, 0.18)
        total = integrate.simpson(y, x=xs)
        assert abs(total - 1.0) < 5e-4
        left = integrate.simpson(y[xs < 0], x=xs[xs < 0])
        assert left > 0.5, f"低角侧应 >50%，实测 {left:.4f}"

    def test_split_scale_factors_sum_to_two(self):
        for wl, wh in [(0.3, 0.18), (0.15, 0.15), (0.1, 0.5)]:
            k_lo, k_hi = split_scale_factors(wl, wh, 0.6)
            assert abs(float(k_lo) + float(k_hi) - 2.0) < 1e-12
            if wl == wh:
                assert abs(float(k_lo) - 1.0) < 1e-12


class TestCaglioti:
    def test_uses_bragg_theta(self):
        """``FWHM² = U tan²θ + V tanθ + W``，θ = 2θ/2（**不是** 2θ）。"""
        for t in (20.0, 60.0, 120.0):
            th = np.radians(t / 2.0)
            ref = np.sqrt(0.008 * np.tan(th) ** 2 - 0.003 * np.tan(th) + 0.05)
            got = float(caglioti_fwhm([t], 0.008, -0.003, 0.05)[0])
            assert abs(got - ref) < 1e-12

    def test_no_blowup_at_90(self):
        """2θ=90° 处必须有限（误用 tan(2θ) 会爆到 1e16）。"""
        fw = caglioti_fwhm(np.array([90.0, 100.0, 150.0]), 0.01, -0.005, 0.02)
        assert np.all(np.isfinite(fw)) and np.all(fw < 10.0)

    def test_constant_case(self):
        assert np.allclose(caglioti_fwhm(np.array([10.0, 90.0]), 0, 0, 0.04), 0.2)

    def test_negative_guard(self):
        """负根截断到极小正值而非 NaN。"""
        fw = caglioti_fwhm(np.array([80.0]), -1.0, 0.0, 0.0)
        assert np.isfinite(fw[0]) and fw[0] > 0


class TestTCH:
    def test_pure_gaussian(self):
        f, e = tch_combine(0.2, 0.0)
        assert abs(float(f) - 0.2) < 1e-9 and abs(float(e)) < 1e-9

    def test_pure_lorentzian(self):
        f, e = tch_combine(0.0, 0.2)
        assert abs(float(f) - 0.2) < 1e-9 and abs(float(e) - 1.0) < 1e-9

    def test_mixed_is_wider(self):
        """TCH 混合比两纯组分都宽（F⁵ 是六项和，不是线性插值）。"""
        f, _ = tch_combine(0.2, 0.2)
        expect = 0.2 * (1 + 2.69269 + 2.42843 + 4.47163 + 0.07842 + 1) ** 0.2
        assert abs(float(f) - expect) < 1e-9 and float(f) > 0.2

    def test_eta_monotone_in_lorentz(self):
        e = [float(tch_combine(0.2, l)[1]) for l in (0.01, 0.05, 0.15, 0.4, 1.0)]
        assert all(a < b for a, b in zip(e, e[1:]))
        assert e[-1] <= 1.0


class TestSizeStrain:
    TT = np.array([10.0, 20.0, 45.0, 90.0, 150.0])

    def test_size_broadens_with_one_over_cos(self):
        """``β_size = Kλ/(D cosθ)`` —— 随 2θ **增大**（1/cosθ 单调增）。"""
        base, _ = tch_widths(self.TT, 1.54056, ProfileParams(w=0.01))
        size, _ = tch_widths(self.TT, 1.54056, ProfileParams(w=0.01, size_nm=20.0))
        assert np.all(size > base)
        assert size[-1] > size[0]

    def test_strain_broadens_with_tan(self):
        base, _ = tch_widths(self.TT, 1.54056, ProfileParams(w=0.01))
        eps, _ = tch_widths(self.TT, 1.54056, ProfileParams(w=0.01, strain=1e-3))
        assert np.all(eps > base) and eps[-1] > eps[0]
        # 应变比尺寸增长快
        size, _ = tch_widths(self.TT, 1.54056, ProfileParams(w=0.01, size_nm=20.0))
        assert (eps[-1] / eps[0]) > (size[-1] / size[0])

    def test_scherrer_magnitude(self):
        """手算核对 Scherrer：D=20nm 在 2θ=10° 的贡献（弧度→度）。"""
        th = np.radians(5.0)
        beta = 0.9 * 1.54056 / (200.0 * np.cos(th)) * 180.0 / np.pi
        g = np.sqrt(0.01)
        ref, _ = tch_combine(np.array([g]), np.array([beta]))
        size, _ = tch_widths(np.array([10.0]), 1.54056,
                             ProfileParams(w=0.01, size_nm=20.0))
        assert abs(float(size[0]) - float(ref[0])) < 1e-9

    def test_zero_sample_terms_noop(self):
        base, _ = tch_widths(self.TT, 1.54056, ProfileParams(w=0.01))
        assert np.allclose(base, caglioti_fwhm(self.TT, 0.0, 0.0, 0.01))


class TestAsymmetry:
    def test_factor_profile(self):
        fac = split_asymmetry_factor(np.array([10.0, 20.0, 45.0, 90.0]), 0.3)
        assert abs(fac[0] - 0.3) < 1e-9 and abs(fac[1] - 0.3) < 1e-9
        assert fac[2] < fac[1] and fac[3] < fac[2]

    def test_zero_amplitude(self):
        assert np.allclose(split_asymmetry_factor(np.array([20.0, 60.0]), 0.0), 0.0)

    def test_clipped(self):
        assert np.all(split_asymmetry_factor(np.array([5.0]), 5.0) <= 0.4)


# ── Kα2 ───────────────────────────────────────────────────────

class TestKalpha2:
    def test_weights_normalized(self):
        w1, w2 = Kalpha2(1.54056, 0.497, True).component_weights()
        assert abs(w1 + w2 - 1.0) < 1e-12
        assert abs(w2 / w1 - 0.497) < 1e-9

    def test_disabled(self):
        assert Kalpha2(1.54056, 0.497, False).component_weights() == (1.0, 0.0)

    def test_strict_bragg(self):
        """严式 ``2θ₂ = 2·asin(λ₂/λ₁·sinθ₁)``，与 tanθ 近似在低角一致。"""
        t1 = np.array([20.0, 45.0, 90.0])
        sep = ka2_two_theta(t1, 1.54056, 1.54439) - t1
        assert np.all(np.diff(sep) > 0)
        approx = (2 * np.tan(np.radians(t1 / 2)) * (1.54439 - 1.54056)
                  / 1.54056 * 180 / np.pi)
        assert abs(sep[0] - approx[0]) < 1e-4


# ── 背景基 ────────────────────────────────────────────────────

class TestBackground:
    TT = np.linspace(15.0, 100.0, 3000)

    @pytest.mark.parametrize("n", [2, 6, 10, 20])
    def test_tent_partition_of_unity(self, n):
        """tent 基行和恒为 1 ⇒ 常数背景可被精确表示。"""
        assert np.allclose(tent_basis(self.TT, n).sum(axis=1), 1.0)

    def test_tent_constant_background(self):
        assert np.allclose(tent_basis(self.TT, 10) @ np.full(10, 42.0), 42.0)

    def test_tent_endpoint_extension(self):
        """端点外首/末节点恒为 1（半幅延拓）。"""
        b = tent_basis(np.array([10.0, 200.0]), 5, lo=20.0, hi=100.0)
        assert abs(b[0, 0] - 1.0) < 1e-12 and abs(b[1, -1] - 1.0) < 1e-12

    @pytest.mark.parametrize("n", [4, 6, 8])
    def test_chebyshev_shape(self, n):
        assert chebyshev_basis(self.TT, n).shape == (3000, n)

    def test_chebyshev_near_orthogonal(self):
        B = chebyshev_basis(self.TT, 8)
        G = B.T @ B
        off = G - np.diag(np.diag(G))
        assert np.max(np.abs(off)) / np.max(np.abs(np.diag(G))) < 0.5

    def test_chebyshev_constant_term(self):
        assert np.allclose(chebyshev_basis(self.TT, 1), 1.0)

    def test_none_returns_empty(self):
        assert background_basis(self.TT, BackgroundParams("none")).shape[1] == 0

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            BackgroundParams("fourier")


# ── 前向装配 ──────────────────────────────────────────────────

def _si_table():
    model = StructureModel(
        sites=(AtomSite("Si", 0, 0, 0, 1.0, 0.0),),
        cell=Cell(5.431, 5.431, 5.431), name="Si")
    return build_reflections(model, two_theta_range=(20.0, 90.0))


class TestAssembly:
    GRID = np.linspace(0.0, 180.0, 180001)

    def test_peak_area_equals_intensity(self):
        """``∫y = Σ I·(截断因子)`` —— 面积归一 + 装配的联合验收。"""
        from scipy import integrate
        from polyxrd.refinement.profile import FWHM_TO_SIGMA as S
        tab = _si_table()
        y = phase_pattern(self.GRID, PhaseSpec(tab),
                          ProfileParams(fwhm=0.12, eta=0.6), cutoff_fwhm=None)
        got = integrate.simpson(y, x=self.GRID)
        # 端点外 Lorentz 长尾损失的解析值
        from math import erf, atan, pi
        c = tab.two_theta
        sigma = np.maximum(0.12 * S, 1e-12)
        gamma = 0.06
        lo, hi = self.GRID[0], self.GRID[-1]
        g = 0.5 * (np.vectorize(erf)((hi - c) / (sigma * np.sqrt(2.0)))
                   + np.vectorize(erf)((c - lo) / (sigma * np.sqrt(2.0))))
        ell = (np.arctan((hi - c) / gamma) + np.arctan((c - lo) / gamma)) / pi
        expect = float(np.sum(tab.intensity * (0.6 * g + 0.4 * ell)))
        assert abs(got - expect) / expect < 1e-5

    def test_ka2_area_conserved(self):
        from scipy import integrate
        tab = _si_table()
        p = ProfileParams(fwhm=0.12, eta=0.6)
        y0 = phase_pattern(self.GRID, PhaseSpec(tab), p, cutoff_fwhm=None)
        y2 = phase_pattern(self.GRID, PhaseSpec(tab), p, cutoff_fwhm=None,
                           kalph2=Kalpha2(1.54056, 0.497, True))
        a0 = integrate.simpson(y0, x=self.GRID)
        a2 = integrate.simpson(y2, x=self.GRID)
        assert abs(a2 - a0) / a0 < 1e-5
        # 双线确实分开了
        assert not np.allclose(y0, y2)

    def test_windowed_matches_full_matrix(self):
        tab = _si_table()
        p = ProfileParams(fwhm=0.12, eta=0.6)
        full = phase_pattern(self.GRID, PhaseSpec(tab), p, cutoff_fwhm=None)
        win = phase_pattern(self.GRID, PhaseSpec(tab), p, cutoff_fwhm=25.0)
        assert np.max(np.abs(win - full)) / full.max() < 2e-3

    def test_all_reflections_appear(self):
        from scipy.signal import argrelmax
        tab = _si_table()
        y = phase_pattern(self.GRID, PhaseSpec(tab),
                          ProfileParams(fwhm=0.12, eta=0.6), cutoff_fwhm=None)
        loc = self.GRID[argrelmax(y, order=20)[0]]
        for p in tab.two_theta:
            assert np.min(np.abs(loc - p)) < 0.01, f"缺峰 {p:.4f}°"

    def test_design_matrix_shape_and_sum(self):
        tab = _si_table()
        Bd = design_matrix(self.GRID, [PhaseSpec(tab)], ProfileParams(w=0.01))
        assert Bd.shape == (self.GRID.size, 1)
        y = synthesize(self.GRID, [PhaseSpec(tab)], [2.0], ProfileParams(w=0.01),
                       basis=Bd)
        assert np.allclose(y, Bd[:, 0] * 2.0)

    def test_synthesize_equals_manual(self):
        tab = _si_table()
        specs = [PhaseSpec(tab), PhaseSpec(tab, size_nm=30.0, strain=5e-4)]
        p = ProfileParams(w=0.01, x=0.002, y=0.001)
        Bd = design_matrix(self.GRID, specs, p)
        bgs = BackgroundParams("tent", 8)
        coefs = np.linspace(3.0, 12.0, 8)
        y = synthesize(self.GRID, specs, [1.0, 2.5], p,
                       bg_params=bgs, bg_coefs=coefs, basis=Bd)
        manual = Bd @ np.array([1.0, 2.5]) + background_basis(self.GRID, bgs) @ coefs
        assert np.allclose(y, manual)

    def test_scale_length_mismatch_raises(self):
        tab = _si_table()
        Bd = design_matrix(self.GRID, [PhaseSpec(tab)], ProfileParams(w=0.01))
        with pytest.raises(ValueError):
            synthesize(self.GRID, [PhaseSpec(tab)], [1.0, 2.0],
                       ProfileParams(w=0.01), basis=Bd)

    def test_per_phase_profile_decoupled(self):
        """同结构、不同晶粒尺寸 → 峰宽不同（逐相峰形解耦）。"""
        tab = _si_table()
        small = design_matrix(self.GRID, [PhaseSpec(tab, size_nm=5.0)],
                              ProfileParams(w=0.01))
        big = design_matrix(self.GRID, [PhaseSpec(tab, size_nm=200.0)],
                            ProfileParams(w=0.01))
        assert small.max() < big.max(), "小晶粒峰应更矮更宽"

    def test_empty_inputs(self):
        empty = np.array([])
        assert phase_pattern(empty, PhaseSpec(_si_table()), ProfileParams()).size == 0
        assert synthesize(empty, [], [], ProfileParams()).size == 0

    def test_unknown_profile_kind_raises(self):
        with pytest.raises(ValueError):
            ProfileParams(kind="voigt")
