"""v5.1 阶段：Wyckoff 轨道归并 + 位点自由度的可辨识性（基准报告 §十八）。

为什么必须归并
--------------
``StructureModel`` 存的是**已展开的 P1 全胞**。刚玉 R-3c 有 30 个位点，独立量
只有 2 个（Al 12c 的 z、O 18e 的 x）。旧口径逐位点放开 → 90 个坐标列秩只有 2
（实测 SVD0 = 1.9e-8），Hessian 秩亏、LM 步长被边界投影吃掉。

两条账要一起算
--------------
1. **轨道归并**：同元素、同占位、能被某条空间群操作从同一个代表点生成的位点
   并成一个独立位点；代表点一动，整条轨道跟着动。
2. **缓存键缺位点**（更隐蔽）：反射表与设计矩阵的缓存键里只有晶胞，改坐标后
   两者都命中旧缓存 → **stage 6 在 LM 内部完全是空的**。合成 LFP 上把
   ``atom1.x`` 挪 0.05，2001 个点的残差变化 0 个；手工重建反射表后 ``|F|²``
   最大变化 1.17 —— 结构因子本身是接通的，纯粹被缓存挡住。

覆盖清单
--------
* 刚玉 30 → 2 个独立位点，多重度 {12, 18}
* 特殊位置锁轴：12c 只有 z、18e 只有 x；萤石两个位点全部锁死
* ``(x,x,x)``（尖晶石 32e）只保留一个方向，且沿它走一步仍留在同一轨道上
* 占位不一致（掺杂）时不并
* 无空间群时退化成"一位点一自由量"，行为与 v5.0 一致
* 参数册规模、雅可比满秩、改坐标能改变计算谱、反复 ``apply()`` 不漂移
"""

from __future__ import annotations

from dataclasses import replace as _replace

import numpy as np

from polyxrd.refinement import (
    AtomSite,
    BackgroundParams,
    Cell,
    PatternProblem,
    PhaseBlock,
    PhaseSpec,
    ProfileParams,
    StructureModel,
    background_basis,
    build_reflections,
    design_matrix,
    orbit_decomposition,
    site_displacement_matrix,
)

CUT = 25.0
_PROFILE = ProfileParams(u=0.02, v=-0.01, w=0.012, x=0.01)
_BG = BackgroundParams("tent", 8)

_AL2O3_ASYM = (
    dict(label="Al", element="Al", x=0.0, y=0.0, z=0.3521, occupancy=1.0),
    dict(label="O", element="O", x=0.3064, y=0.0, z=0.25, occupancy=1.0),
)
_AL2O3_CELL = Cell(4.7602, 4.7602, 12.9933, 90.0, 90.0, 120.0)
_FLUORITE_ASYM = (
    dict(label="Ca", element="Ca", x=0.0, y=0.0, z=0.0, occupancy=1.0),
    dict(label="F", element="F", x=0.25, y=0.25, z=0.25, occupancy=1.0),
)
_SPINEL_ASYM = (
    dict(label="Mg", element="Mg", x=0.125, y=0.125, z=0.125, occupancy=1.0),
    dict(label="Al", element="Al", x=0.5, y=0.5, z=0.5, occupancy=1.0),
    dict(label="O", element="O", x=0.2624, y=0.2624, z=0.2624, occupancy=1.0),
)


def _expanded(asym, symbol: str, b_iso: float = 0.5):
    from polyxrd.services.phase_cif import expand_sites_by_symmetry

    full = expand_sites_by_symmetry([dict(a) for a in asym], symbol)
    assert full, f"{symbol} 展开失败"
    return tuple(AtomSite(s["element"], s["x"], s["y"], s["z"],
                          s["occupancy"], b_iso, s["label"]) for s in full)


def _ops(symbol: str):
    from polyxrd.services.phase_cif import space_group_ops

    return space_group_ops(symbol) if symbol else None


def _decompose(sites, symbol: str = "R -3 c"):
    return orbit_decomposition(_ops(symbol), [[s.x, s.y, s.z] for s in sites],
                               [s.element for s in sites],
                               [s.occupancy for s in sites])


def _free_tags(mat) -> list:
    return [tag for a, tag in enumerate("xyz")
            if float(np.abs(np.asarray(mat)[:, a]).max()) > 1e-12]


def _corundum_problem() -> PatternProblem:
    st = StructureModel(sites=_expanded(_AL2O3_ASYM, "R -3 c"), cell=_AL2O3_CELL,
                        space_group="R -3 c", name="Al2O3")
    tt = np.linspace(15.0, 100.0, 1201)
    tab = build_reflections(st, two_theta_range=(13.0, 102.0))
    basis = design_matrix(tt, [PhaseSpec(tab)], _PROFILE, cutoff_fwhm=CUT)
    y = (basis @ np.array([5000.0 / basis.max()])
         + background_basis(tt, _BG) @ np.linspace(60.0, 40.0, 8))
    prob = PatternProblem(tt, y, [PhaseBlock("Al2O3", st)], profile=_PROFILE,
                          bg=_BG, weights=1.0 / np.maximum(y, 1.0),
                          cutoff_fwhm=CUT, wavelength=1.5406)
    prob.apply()
    return prob


class TestOrbitDecomposition:
    def test_corundum_merges_to_two_independent_sites(self):
        sites = _expanded(_AL2O3_ASYM, "R -3 c")
        assert len(sites) == 30, "刚玉全胞应为 Al 12 + O 18"
        dec = _decompose(sites)
        assert dec.trivial is False
        assert dec.n_rep == 2
        mult = sorted(int(np.sum(np.asarray(dec.rep_of) == k))
                      for k in range(dec.n_rep))
        assert mult == [12, 18], mult

    def test_corundum_special_positions_lock_the_wrong_axes(self):
        """12c 只有 z 能动、18e 只有 x 能动 —— 其余轴必须被稳定子锁死。"""
        dec = _decompose(_expanded(_AL2O3_ASYM, "R -3 c"))
        free = [_free_tags(dec.mats[k]) for k in range(dec.n_rep)]
        assert sorted(free) == [["x"], ["z"]], free

    def test_site_without_free_direction_is_fully_locked(self):
        """萤石 Fm-3m：Ca(0,0,0) 与 F(¼,¼,¼) 都没有任何自由方向。"""
        sites = _expanded(_FLUORITE_ASYM, "F m -3 m")
        assert len(sites) == 12
        dec = _decompose(sites, "F m -3 m")
        assert dec.n_rep == 2
        for mat in dec.mats:
            assert float(np.abs(mat).max()) == 0.0

    def test_diagonal_site_keeps_exactly_one_direction(self):
        """``(x,x,x)``（尖晶石 32e）只有一个自由度，其余两轴要钉死。"""
        sites = _expanded(_SPINEL_ASYM, "F d -3 m")
        dec = _decompose(sites, "F d -3 m")
        assert dec.n_rep == 3
        counts = sorted(int(np.sum(np.asarray(dec.rep_of) == k))
                        for k in range(dec.n_rep))
        assert counts == [8, 16, 32], counts
        n_free = [len(_free_tags(mat)) for mat in dec.mats]
        assert sorted(n_free) == [0, 0, 1], n_free

    def test_unknown_space_group_keeps_one_site_per_atom(self):
        sites = _expanded(_AL2O3_ASYM, "R -3 c")
        dec = _decompose(sites, "")
        assert dec.trivial is True
        assert dec.n_rep == len(sites)
        for mat in dec.mats:
            assert np.allclose(mat, np.eye(3))

    def test_occupancy_mismatch_blocks_merging(self):
        """轨道内占位不一致（掺杂 / 无序）→ 那一位点单独算，不并进大轨道。"""
        sites = list(_expanded(_AL2O3_ASYM, "R -3 c"))
        oxygen = [i for i, s in enumerate(sites) if s.element == "O"]
        sites[oxygen[1]] = _replace(sites[oxygen[1]], occupancy=0.5)
        assert _decompose(tuple(sites)).n_rep == 3

    def test_displacement_matrix_keeps_parameter_meaning(self):
        """一般位置上位移矩阵必须是单位阵（参数就是坐标，与 v5.0 一致）。"""
        ops = _ops("P2_1/c")
        assert ops is not None
        assert np.allclose(site_displacement_matrix(ops, [0.13, 0.27, 0.41]),
                           np.eye(3))

    def test_moving_along_the_matrix_stays_on_the_orbit(self):
        """核心物理保证：沿位移矩阵走一步，位点仍在同一条 Wyckoff 轨道上。"""
        sites = _expanded(_AL2O3_ASYM, "R -3 c")
        dec = _decompose(sites)
        ops = _ops("R -3 c")
        for k, i in enumerate(dec.rep_site):
            base_mult = int(np.sum(np.asarray(dec.rep_of) == k))
            for a in range(3):
                if float(np.abs(dec.mats[k][:, a]).max()) < 1e-12:
                    continue
                moved = (np.asarray([sites[i].x, sites[i].y, sites[i].z])
                         + 0.005 * dec.mats[k][:, a])
                orbit: list = []
                for op in ops:
                    q = np.asarray(op.operate(moved), dtype=float)
                    q = q - np.floor(q)
                    if not any(np.all(np.minimum(np.abs(q - o),
                                                 1.0 - np.abs(q - o)) < 1e-3)
                               for o in orbit):
                        orbit.append(q)
                assert len(orbit) == base_mult, (k, "xyz"[a], len(orbit), base_mult)


class TestStructureDegreesOfFreedom:
    """参数册 + 雅可比的端到端检查（轨道归并到底有没有让 stage 6 可用）。"""

    def test_parameter_book_is_orbit_sized(self):
        """2 个独立位点 ×（3 坐标 + 占位 + B）= 10 个参数（旧口径是 150）。"""
        prob = _corundum_problem()
        atoms = [p for p in prob.params if ".atom" in p.name]
        assert len(atoms) == 10
        free_xyz = [p.name for p in atoms if p.name[-1] in "xyz" and not p.fixed]
        assert len(free_xyz) == 2, free_xyz

    def test_locked_axes_are_marked_fixed(self):
        prob = _corundum_problem()
        locked = [p for p in prob.params if "特殊位置锁定" in p.label]
        assert len(locked) == 4
        assert all(p.fixed for p in locked)

    def test_full_occupancy_is_locked(self):
        """满占位位点的占位必须钉住。

        ``occ`` 的上界就是 1.0，全占位结构一开始就在边界上 —— 前向差分的列
        恒为零（实测 ``|dy|/h = 0``），LM 永远迈不出一步，只会白占自由度并让
        秩检查报亏。``occ = 0.999`` 时列立刻回到 ~7.5e3 量级。
        """
        prob = _corundum_problem()
        occ = [p for p in prob.params if p.name.endswith(".occ")]
        assert occ and all(p.fixed for p in occ)
        assert all("满占位" in p.label for p in occ)

    def test_partial_occupancy_keeps_a_healthy_column(self):
        """部分占位（occ < 1）的导数正常，占位参数应保持可放。"""
        st = StructureModel(sites=_expanded(_AL2O3_ASYM, "R -3 c"),
                            cell=_AL2O3_CELL, space_group="R -3 c", name="Al2O3")
        sites = tuple(_replace(s, occupancy=0.5) if s.element == "O" else s
                      for s in st.sites)
        st = StructureModel(sites=sites, cell=st.cell,
                            space_group=st.space_group, name=st.name)
        tt = np.linspace(15.0, 100.0, 1201)
        tab = build_reflections(st, two_theta_range=(13.0, 102.0))
        basis = design_matrix(tt, [PhaseSpec(tab)], _PROFILE, cutoff_fwhm=CUT)
        y = (basis @ np.array([5000.0 / basis.max()])
             + background_basis(tt, _BG) @ np.linspace(60.0, 40.0, 8))
        prob = PatternProblem(tt, y, [PhaseBlock("Al2O3", st)], profile=_PROFILE,
                              bg=_BG, weights=1.0 / np.maximum(y, 1.0),
                              cutoff_fwhm=CUT, wavelength=1.5406)
        free_occ = [p.name for p in prob.params
                    if p.name.endswith(".occ") and not p.fixed]
        assert len(free_occ) == 1, free_occ
        y0 = prob.calc_pattern()
        prob.params.set(free_occ[0], 0.45)
        prob.apply()
        assert float(np.max(np.abs(prob.calc_pattern() - y0))) > 1.0

    @staticmethod
    def _rank_of(prob: PatternProblem, names) -> tuple:
        # 先记下"参数册自己认可的可用轴"（特殊位置锁定的不在其中）
        usable = [n for n in names if not prob.params[n].fixed]
        prob.params.fix_prefix("", True)
        for name in usable:
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

    def test_coordinate_columns_are_full_rank(self):
        """归并后坐标列必须**满秩**（2/2）；旧口径是 2/90。"""
        prob = _corundum_problem()
        names = [p.name for p in prob.params
                 if ".atom" in p.name and p.name[-1] in "xyz"]
        n, rank, _sv = self._rank_of(prob, names)
        assert n == 2
        assert rank == n

    def test_atom_change_reaches_the_pattern(self):
        """改坐标必须改变计算谱 —— 缓存键少了位点，stage 6 就是空的。"""
        prob = _corundum_problem()
        y0 = prob.calc_pattern()
        free = [p.name for p in prob.params
                if ".atom" in p.name and p.name[-1] in "xyz" and not p.fixed]
        target = free[0]
        prob.params.set(target, float(prob.params.get(target)) + 0.02)
        prob.apply()
        assert float(np.max(np.abs(prob.calc_pattern() - y0))) > 1.0

    def test_whole_orbit_moves_together(self):
        """动一个代表位点：整条轨道一起动，别的轨道一位不动。"""
        prob = _corundum_problem()
        before = list(prob.phases[0].structure.sites)
        elem_free = [p for p in prob.params
                     if ".atom" in p.name and p.name[-1] in "xyz" and not p.fixed]
        # 找 O 轨道的那个自由坐标
        target = [p for p in elem_free
                  if prob._atom_map[0].reps[int(p.name.split(".")[1][4:])].element
                  == "O"][0]
        prob.params.set(target.name, float(prob.params.get(target.name)) + 0.004)
        prob.apply()
        after = list(prob.phases[0].structure.sites)
        moved = {s.element for s, t in zip(before, after)
                 if abs(s.x - t.x) + abs(s.y - t.y) + abs(s.z - t.z) > 1e-9}
        assert moved == {"O"}, moved
        n_moved = sum(1 for s, t in zip(before, after)
                      if abs(s.x - t.x) + abs(s.y - t.y) + abs(s.z - t.z) > 1e-9)
        assert n_moved == 18, n_moved      # 18e 整条轨道
        # 位点仍落在同一条轨道上（多重度不变）
        assert _decompose(tuple(after)).n_rep == 2

    def test_apply_does_not_drift(self):
        """位移以初始坐标作锚点：反复 ``apply()`` 不能累积漂移。"""
        prob = _corundum_problem()
        prob.apply()
        first = [(s.x, s.y, s.z) for s in prob.phases[0].structure.sites]
        for _ in range(3):
            prob.apply()
        again = [(s.x, s.y, s.z) for s in prob.phases[0].structure.sites]
        assert np.allclose(np.asarray(first), np.asarray(again), atol=1e-12)
