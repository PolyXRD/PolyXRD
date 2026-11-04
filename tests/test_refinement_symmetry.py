"""v5.0.0 阶段 E 前置验收：按空间群约束胞参（``refinement/symmetry.py``）。

为什么单独一组用例
------------------
这是"真实试样能不能跑"的开关。合成谱（LFP，三斜）怎么放开都不会退化，所以
A~D 阶段的用例全绿也说明不了六方/立方相可用。真实试样（ZnO P6₃mc、CaF₂
Fm-3m、Al₂O₃ R-3c、TiO₂ P4₂/mnm）只要放开 6 个胞参，Hessian 立刻秩亏。

覆盖清单
--------
* 符号归一化：CIF 写法（``P21/c`` / ``R -3 c`` / 下标数字）→ 规范符号，
  国际表编号，认不出返回 ``None``
* 晶系判定：六大晶系 + 三方相的**轴选择**（``:R`` / ``:H`` / 按胞参推断）
* 约束表内容：各晶系定死哪些角度、哪些参数跟随谁
* 约束落地：``apply_cell_ties`` 后的自由胞参数恰好等于 ``INDEPENDENT_CELL_PARAMS``
* 跟踪性：``a`` 走一步，``b`` 立刻跟上（``assign`` / ``restore`` / 手工 ``set``
  三条路径都要自洽 —— 只 ``fix`` 不建约束是这里最容易写错的地方）
* 认不出符号 → 保持全放开（行为不劣化）
"""

from __future__ import annotations

import numpy as np
import pytest

from polyxrd.refinement import (
    CRYSTAL_SYSTEMS,
    INDEPENDENT_CELL_PARAMS,
    AtomSite,
    BackgroundParams,
    Cell,
    PatternProblem,
    PhaseBlock,
    PhaseSpec,
    ProfileParams,
    StructureModel,
    apply_cell_ties,
    background_basis,
    build_reflections,
    cell_ties,
    crystal_system_from_symbol,
    design_matrix,
    resolve_space_group_symbol,
)

# ZnO 的位点：正反两个 Zn/O 对，任何晶系都能算（坐标只是占位）
_ZNO_SITES = (
    AtomSite("Zn", 1 / 3, 2 / 3, 0.0, 1.0, 0.5, "Zn1"),
    AtomSite("Zn", 2 / 3, 1 / 3, 0.5, 1.0, 0.5, "Zn1"),
    AtomSite("O", 1 / 3, 2 / 3, 0.3819, 1.0, 0.5, "O1"),
    AtomSite("O", 2 / 3, 1 / 3, 0.8819, 1.0, 0.5, "O1"),
)
HEX_CELL = Cell(3.2498, 3.2498, 5.2066, 90.0, 90.0, 120.0)
RHOMB_CELL = Cell(5.4, 5.4, 5.4, 59.5, 59.5, 59.5)
CUBIC_CELL = Cell(5.4631, 5.4631, 5.4631, 90.0, 90.0, 90.0)
MONO_CELL = Cell(4.6, 5.0, 7.2, 90.0, 99.0, 90.0)
TT = np.linspace(20.0, 90.0, 400)
CUT = 25.0
_PROFILE = ProfileParams(u=0.02, v=-0.01, w=0.012, x=0.01)
_BG = BackgroundParams("tent", 8)


def _synthetic_y() -> np.ndarray:
    """用六方 ZnO 的参考晶胞合成一条**有峰**的谱。

    不能用常数底：``solve_linear`` 会把 scale 解成 0（峰全是正的、拟合不了常数
    底），于是残差与胞参完全无关、雅可比一片 1e-8 —— 秩/条件数全都测不出来。
    标度也不能写死：强度口径含 ``1/V²``，按"最强峰 3000 counts"反推才稳。
    """
    tab = build_reflections(StructureModel(sites=_ZNO_SITES, cell=HEX_CELL,
                                           space_group="P63mc", name="ZnO"),
                            two_theta_range=(TT[0] - 2.0, TT[-1] + 2.0))
    basis = design_matrix(TT, [PhaseSpec(tab)], _PROFILE, cutoff_fwhm=CUT)
    return (basis @ np.array([3000.0 / basis.max()])
            + background_basis(TT, _BG) @ np.linspace(60.0, 40.0, 8))


Y_OBS = _synthetic_y()


def _problem(cell: Cell, symbol: str = "P63mc") -> PatternProblem:
    st = StructureModel(sites=_ZNO_SITES, cell=cell, space_group=symbol,
                        name="ZnO")
    prob = PatternProblem(
        TT, Y_OBS, [PhaseBlock("ZnO", st)],
        profile=_PROFILE, bg=_BG, weights=1.0 / np.maximum(Y_OBS, 1.0),
        cutoff_fwhm=CUT, wavelength=1.5406,
    )
    prob.apply()
    return prob


def _free_cell_tags(prob: PatternProblem) -> list:
    """自由胞参，按 ``a,b,c,α,β,γ`` 的固定顺序（不按字母排 —— ``alpha`` 会跑到 ``b`` 前面）。"""
    names = prob.params.names()
    got = {names[i].rsplit(".", 1)[-1] for i in prob.params.free_indices()
           if ".cell." in names[i]}
    return [t for t in ("a", "b", "c", "alpha", "beta", "gamma") if t in got]


# ── 符号归一化 ────────────────────────────────────────────────


class TestSymbolResolution:
    @pytest.mark.parametrize("raw,want", [
        ("P2_1/c", "P2_1/c"),
        ("P21/c", "P2_1/c"),
        ("P 21/c", "P2_1/c"),
        ("P2₁/c", "P2_1/c"),          # Unicode 下标
        ("P63/mmc", "P6_3/mmc"),
        ("R -3 c", "R-3c"),
        ("F m -3 m", "Fm-3m"),
        ("P42/mnm", "P4_2/mnm"),
        ("P3221", "P3_221"),
    ])
    def test_cif_spellings(self, raw, want):
        assert resolve_space_group_symbol(raw) == want

    def test_international_number(self):
        assert resolve_space_group_symbol("225") == "Fm-3m"
        assert resolve_space_group_symbol("194") == "P6_3/mmc"

    @pytest.mark.parametrize("raw", ["", "   ", "乱码", "Q7", "P999"])
    def test_unknown_returns_none(self, raw):
        assert resolve_space_group_symbol(raw) is None

    def test_setting_suffix_ignored(self):
        assert resolve_space_group_symbol("R-3c:R") == "R-3c"
        assert resolve_space_group_symbol("R-3c:H") == "R-3c"


# ── 晶系判定 ──────────────────────────────────────────────────


class TestCrystalSystem:
    @pytest.mark.parametrize("symbol,want", [
        ("P-1", "triclinic"),
        ("P2_1/c", "monoclinic"),
        ("Pnma", "orthorhombic"),
        ("P4_2/mnm", "tetragonal"),
        ("P6_3mc", "hexagonal"),
        ("Fm-3m", "cubic"),
        ("R-3c", "hexagonal"),          # 三方 + 六方轴（默认设置）
    ])
    def test_six_systems(self, symbol, want):
        assert crystal_system_from_symbol(symbol) == want

    def test_all_systems_known(self):
        for name in CRYSTAL_SYSTEMS:
            assert name in INDEPENDENT_CELL_PARAMS or name == "trigonal"

    def test_trigonal_setting_suffix(self):
        assert crystal_system_from_symbol("R-3c:R") == "rhombohedral"
        assert crystal_system_from_symbol("R-3c:H") == "hexagonal"

    def test_trigonal_axes_inferred_from_cell(self):
        """没给 setting 时按胞参认：a=b=c 且角相等且非 90° → 菱形轴。"""
        assert crystal_system_from_symbol("R-3c", RHOMB_CELL) == "rhombohedral"

    def test_trigonal_hexagonal_cell_stays_hexagonal(self):
        assert crystal_system_from_symbol("R-3c", HEX_CELL) == "hexagonal"

    @pytest.mark.parametrize("raw", ["", "乱码"])
    def test_unknown_symbol_no_constraint(self, raw):
        assert crystal_system_from_symbol(raw) is None


# ── 约束表内容 ────────────────────────────────────────────────


class TestCellTies:
    @pytest.mark.parametrize("system,fixed,follow", [
        ("cubic", {"alpha": 90.0, "beta": 90.0, "gamma": 90.0},
         {"b": "a", "c": "a"}),
        ("hexagonal", {"alpha": 90.0, "beta": 90.0, "gamma": 120.0},
         {"b": "a"}),
        ("tetragonal", {"alpha": 90.0, "beta": 90.0, "gamma": 90.0},
         {"b": "a"}),
        ("orthorhombic", {"alpha": 90.0, "beta": 90.0, "gamma": 90.0}, {}),
        ("monoclinic", {"alpha": 90.0, "gamma": 90.0}, {}),
        ("rhombohedral", {},
         {"b": "a", "c": "a", "beta": "alpha", "gamma": "alpha"}),
        ("triclinic", {}, {}),
    ])
    def test_fixed_and_follow(self, system, fixed, follow):
        got_fixed, got_follow = cell_ties(system)
        assert got_fixed == fixed
        assert got_follow == follow

    @pytest.mark.parametrize("system", list(INDEPENDENT_CELL_PARAMS))
    def test_independent_count_matches_table(self, system):
        """定死 + 跟随 之后剩下的自由胞参数个数 == 表里的独立参数个数。"""
        fixed, follow = cell_ties(system)
        n_free = 6 - len(fixed) - len(follow)
        assert n_free == len(INDEPENDENT_CELL_PARAMS[system])

    def test_unknown_system_is_permissive(self):
        assert cell_ties("") == ({}, {})
        assert cell_ties("whatever") == ({}, {})


# ── 约束落地 ──────────────────────────────────────────────────


class TestApplyCellTies:
    @pytest.mark.parametrize("symbol,cell,want", [
        ("Fm-3m", CUBIC_CELL, ["a"]),
        ("P6_3mc", HEX_CELL, ["a", "c"]),
        ("P4_2/mnm", Cell(4.6, 4.6, 3.0, 90.0, 90.0, 90.0), ["a", "c"]),
        ("Pnma", Cell(4.6, 5.0, 7.2, 90.0, 90.0, 90.0), ["a", "b", "c"]),
        ("P2_1/c", MONO_CELL, ["a", "b", "c", "beta"]),
        ("P-1", MONO_CELL, ["a", "b", "c", "alpha", "beta", "gamma"]),
        ("R-3c", HEX_CELL, ["a", "c"]),
        ("R-3c:R", RHOMB_CELL, ["a", "alpha"]),
    ])
    def test_free_cell_params(self, symbol, cell, want):
        assert _free_cell_tags(_problem(cell, symbol)) == want

    def test_no_symbol_keeps_all_six(self):
        got = _free_cell_tags(_problem(HEX_CELL, ""))
        assert got == ["a", "b", "c", "alpha", "beta", "gamma"]

    def test_unknown_symbol_keeps_all_six(self):
        assert len(_free_cell_tags(_problem(HEX_CELL, "乱码"))) == 6

    def test_hexagonal_angles_overridden(self):
        """CIF 里 γ 写成 90° 的脏数据，按空间群必须被拉回 120°。"""
        bad = Cell(3.2498, 3.2498, 5.2066, 90.0, 90.0, 90.0)
        prob = _problem(bad, "P6_3mc")
        assert prob.params.get("phase0.cell.gamma") == pytest.approx(120.0)
        assert prob.phases[0].structure.cell.gamma == pytest.approx(120.0)

    def test_cubic_b_and_c_follow_a(self):
        prob = _problem(CUBIC_CELL, "Fm-3m")
        prob.params.set("phase0.cell.a", 5.50)
        prob.apply()
        assert prob.params.get("phase0.cell.b") == pytest.approx(5.50)
        assert prob.params.get("phase0.cell.c") == pytest.approx(5.50)
        assert prob.phases[0].structure.cell.a == pytest.approx(5.50)

    def test_constraints_reported(self):
        prob = _problem(HEX_CELL, "P6_3mc")
        assert prob.params.constrained_names() == ["phase0.cell.b"]

    def test_idempotent(self):
        prob = _problem(HEX_CELL, "P6_3mc")
        before = (len(prob.params.constrained_names()),
                  prob.params.free_indices().size)
        again = apply_cell_ties(prob.params, "phase0", "P6_3mc", HEX_CELL)
        assert again                                   # 有命中
        assert (len(prob.params.constrained_names()),
                prob.params.free_indices().size) == before


# ── 跟踪性（三条写回路径） ────────────────────────────────────


class TestTieTracking:
    def test_assign_keeps_b_equal_a(self):
        prob = _problem(HEX_CELL, "P6_3mc")
        x = prob.params.to_vector()
        # 只动 a（找到它在自由向量里的位置）
        names = [prob.params.names()[i] for i in prob.params.free_indices()]
        x[names.index("phase0.cell.a")] = 3.35
        prob.params.assign(x)
        assert prob.params.get("phase0.cell.b") == pytest.approx(3.35)
        prob.apply()
        assert prob.phases[0].structure.cell.b == pytest.approx(3.35)

    def test_restore_keeps_b_equal_a(self):
        """协议回滚走 ``restore``：快照里 b 是旧值，回滚后必须重新对齐。"""
        prob = _problem(HEX_CELL, "P6_3mc")
        ps = prob.params
        ps.set("phase0.cell.a", 3.40)          # 故意不 refresh → b 仍是 3.2498
        snap = ps.snapshot()
        assert snap["phase0.cell.b"] == pytest.approx(3.2498)
        ps.restore(snap)
        assert ps.get("phase0.cell.b") == pytest.approx(3.40)

    def test_manual_set_overridden_on_apply(self):
        """手工把 b 掰歪，``apply`` 时也必须掰回来（晶胞不能自相矛盾）。"""
        prob = _problem(HEX_CELL, "P6_3mc")
        prob.params.set("phase0.cell.b", 3.10)
        prob.apply()
        assert prob.phases[0].structure.cell.b == pytest.approx(3.2498)

    def test_existing_consistent_cell_pattern_unchanged(self):
        """原本就 a=b 的六方晶胞，加约束不能改变谱图（一致性回归）。"""
        loose = _problem(HEX_CELL, "")
        tied = _problem(HEX_CELL, "P6_3mc")
        y0 = loose.calc_pattern()
        y1 = tied.calc_pattern()
        assert np.allclose(y0, y1, rtol=1e-9, atol=1e-9 * max(1.0, y0.max()))

    def test_rank_not_deficient_after_ties(self):
        """高对称相的胞参雅可比必须满秩（这正是本模块存在的理由）。

        反证：同一个六方晶胞把空间群去掉（= 放开 6 个胞参），实测**秩只有 4/6**、
        条件数 1.7e11 —— 多出来的方向是纯退化，LM 的步长会被投影掉、λ 一路涨。
        """

        def _rank(prob: PatternProblem) -> tuple:
            # 只留胞参 + 峰形/零位之外的东西全部定住，专注于"胞参是否退化"
            for pref in ("phase0.atom", "phase0.sizec", "phase0.strain",
                         "phase0.po", "phase0.bovr", "inst."):
                prob.params.fix_prefix(pref, True)
            x0 = prob.params.to_vector()
            r0 = prob.residual(x0)
            cols = []
            for j in range(x0.size):
                h = 1e-6 * max(1.0, abs(x0[j]))
                x = x0.copy()
                x[j] += h
                cols.append((prob.residual(x) - r0) / h)
            jac = np.column_stack(cols)
            # 相对秩：按最大奇异值归一，避免绝对量纲影响判定
            sv = np.linalg.svd(jac, compute_uv=False)
            tol = max(jac.shape) * sv[0] * 1e-8 if sv.size else 0.0
            return x0.size, int(np.sum(sv > tol))

        n_tied, rank_tied = _rank(_problem(HEX_CELL, "P6_3mc"))
        assert n_tied == 2                                   # a, c
        assert rank_tied == n_tied

        n_loose, rank_loose = _rank(_problem(HEX_CELL, ""))
        assert n_loose == 6
        assert rank_loose < n_loose                          # 退化

        # 立方更极端：a=b=c 且三个角全 90°，只剩一个方向
        n_cube, rank_cube = _rank(_problem(CUBIC_CELL, "Fm-3m"))
        assert (n_cube, rank_cube) == (1, 1)
        _, rank_cube_loose = _rank(_problem(CUBIC_CELL, ""))
        assert rank_cube_loose < 6


class TestSampleBroadeningIdentifiability:
    """样品展宽的可辨识性（基准报告 §十七，2026-11-04）。

    两件事一起踩过：

    1. ``β_size = Kλ/(D cosθ)`` 在 ``D → ∞`` 处**平坦**（``dβ/dD ∝ 1/D²``），
       数值差分的列会在浮点上归零 —— 2-2 的 ``phase1.size`` 停在 99988 nm，
       秩打成 15/16、SVD0=5e-15。所以参数册里存的是**洛伦兹系数**（度·cosθ），
       ``0`` 是"无展宽"这个正常点，列恒为 ``1/cosθ``。
    2. ``X`` 与 ``4ε``、``Y`` 与 ``Kλ/D`` 是逐字相同的基函数，一起放开只有
       它们的和可辨识 —— stage 5 一启用就把 ``inst.x``/``inst.y`` 钉住。
    """

    @staticmethod
    def _only_free(prob: PatternProblem, keep: str) -> None:
        prob.params.fix_prefix("", True)          # 全定住
        prob.params.fix(keep, False)              # 只放一个

    def _column_norm(self, prob: PatternProblem, coef: float) -> float:
        prob.params.set("phase0.sizec", coef)
        prob.apply()
        x0 = prob.params.to_vector()
        r0 = prob.residual(x0)
        h = 1e-6 * max(1.0, abs(coef))
        x1 = x0.copy()
        x1[0] += h
        return float(np.linalg.norm(prob.residual(x1) - r0) / h)

    def test_size_column_survives_tiny_coefficient(self):
        """旧口径的反例：D 很大时列几乎为零（1e-11 量级），秩检查报亏。

        现在参数是系数：``coef = 1e-5`` 度 ≈ 8000 nm（大晶粒、近乎无展宽），
        列的量级必须和中等展宽（``coef = 0.03`` 度 ≈ 265 nm）时相当 ——
        因为它们乘的是同一个基函数 ``1/cosθ``。
        """
        prob = _problem(HEX_CELL)
        self._only_free(prob, "phase0.sizec")
        big = self._column_norm(prob, 1e-5)
        mid = self._column_norm(prob, 0.03)
        assert mid > 0.0
        assert big > 0.3 * mid, (big, mid)

    def _rank_of(self, prob: PatternProblem, names) -> tuple:
        prob.params.fix_prefix("", True)
        for name in names:
            prob.params.fix(name, False)
        x0 = prob.params.to_vector()
        r0 = prob.residual(x0)
        cols = []
        for j in range(x0.size):
            h = 1e-6 * max(1.0, abs(x0[j]))
            x = x0.copy()
            x[j] += h
            cols.append((prob.residual(x) - r0) / h)
        jac = np.column_stack(cols)
        sv = np.linalg.svd(jac, compute_uv=False)
        tol = max(jac.shape) * sv[0] * 1e-8
        return x0.size, int(np.sum(sv > tol)), sv

    def test_x_with_strain_and_y_with_size_are_collinear(self):
        """反证：``X`` 与 ``4ε``、``Y`` 与 ``Kλ/D`` 是**逐字相同**的基函数。

        一起放开时方程只有它们的和可辨识 —— 单相谱上实测秩 6/8、SVD0≈1e-17。
        这条用例存在的意义是：**任何"顺手把 inst.x/y 放开"的改动都会被它拦住**。
        """
        prob = _problem(HEX_CELL)
        n, rank, _sv = self._rank_of(
            prob, ("phase0.sizec", "phase0.strain", "inst.u", "inst.v",
                   "inst.w", "inst.x", "inst.y", "inst.z"))
        assert n == 8
        assert rank < n, "x↔ε / y↔size 的共线居然消失了？先确认基函数是否被改过"

    def test_rank_is_full_once_instrument_lorentz_is_frozen(self):
        """钉住 ``inst.x``/``inst.y`` 后，剩下的方向必须满秩（6/6）。

        这是 ``solver`` 实际跑的那条路径：``run_protocol`` 一看到 stage 5 就
        调 ``freeze_instrument_lorentz()``。
        """
        prob = _problem(HEX_CELL)
        prob.freeze_instrument_lorentz()
        n, rank, _sv = self._rank_of(
            prob, ("phase0.sizec", "phase0.strain", "inst.u", "inst.v",
                   "inst.w", "inst.z"))
        assert n == 6
        assert rank == n

    def test_freeze_instrument_lorentz(self):
        prob = _problem(HEX_CELL)
        frozen = prob.freeze_instrument_lorentz()
        assert frozen == ["inst.x", "inst.y"]
        names = prob.params.names()
        free = {names[i] for i in prob.params.free_indices()}
        assert "inst.x" not in free and "inst.y" not in free
        # U/V/W/Z 仍然自由 —— 高斯分量与常数洛伦兹项没有被牵连
        assert {"inst.u", "inst.v", "inst.w", "inst.z"} <= free
