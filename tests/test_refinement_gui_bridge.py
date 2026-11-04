"""v5.0.0 精修引擎接入 GUI 的桥接测试（服务层，不起 Qt）。

这里验的不是精修算法本身（那在 ``tests/test_refinement_*.py``），而是
"界面点『引擎 = refinement』之后到底发生了什么"：

1. 引擎键注册了吗？状态表里有吗？别名 ``v5`` 会不会走进同一个函数？
2. 真跑一遍合成两相谱，晶胞与定量能不能回到真值？
3. **结构不全时必须显式回退**（``engine_requested`` / ``engine_fallback_reason``），
   不能静默换成 builtin 还让用户以为跑的是新引擎。
4. 向导里取消勾选的自由度（零位 / 晶胞 / 峰形）要真的钉住。
5. 择优取向在 ``refine()`` 里是从 options 摘出来的，v5 拿不到就得走参考峰 —— 必须传下去。

历史教训：v4.4.0 曾出现"向导里选什么引擎都跑 builtin"（engine 没下传），
静默失效最难查。所以第 3、5 条比第 2 条更重要。
"""
from __future__ import annotations

import types

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.refinement import (
    BackgroundParams,
    Cell,
    Kalpha2,
    PhaseSpec,
    ProfileParams,
    StructureModel,
    background_basis,
    build_reflections,
    design_matrix,
    hill_howard,
    site_from_dict,
)
from polyxrd.services.rietveld_refiner import RietveldRefiner

LAM = 1.54056
CUT = 25.0
TT = np.arange(15.0, 80.0, 0.02)


# ── 合成两相体系（立方，各 2 个非对称位点）─────────────────────
_CAF2 = ("CaF2", "Fm-3m", (5.4626, 5.4626, 5.4626, 90.0, 90.0, 90.0),
         (("Ca1", "Ca", 0.0, 0.0, 0.0), ("F1", "F", 0.25, 0.25, 0.25)))
_NACL = ("NaCl", "Fm-3m", (5.6402, 5.6402, 5.6402, 90.0, 90.0, 90.0),
         (("Na1", "Na", 0.0, 0.0, 0.0), ("Cl1", "Cl", 0.5, 0.5, 0.5)))


def _raw_sites(spec) -> list[dict]:
    return [{"label": lab, "element": el, "x": x, "y": y, "z": z,
             "occupancy": 1.0, "b_iso": 0.5}
            for lab, el, x, y, z in spec[3]]


def _structure(spec) -> StructureModel:
    from polyxrd.services.phase_cif import expand_sites_by_symmetry

    name, sg, cell, _sites = spec
    expanded = expand_sites_by_symmetry(_raw_sites(spec), sg)
    assert expanded, f"{name}: 空间群 {sg} 展开失败"
    return StructureModel(sites=tuple(site_from_dict(s) for s in expanded),
                          cell=Cell(*cell), space_group=sg, name=name)


def _phase(spec) -> Phase:
    name, sg, cell, _sites = spec
    return Phase(name=name, formula=name, space_group=sg,
                 lattice=LatticeParams(*cell),
                 atomic_sites=_raw_sites(spec), elements=set())


def _profile() -> ProfileParams:
    # u/v/w：Caglioti（度²）；x/y/z：Lorentz（度）
    return ProfileParams(u=0.004, v=-0.002, w=0.012, x=0.008, y=0.0, z=0.0)


def _synthetic(fractions=(50.0, 50.0), ka2=True):
    """按给定质量分数合成两相谱；返回 (XRDData, 真值 dict, 起点 Rwp)。

    ``ka2=False`` 生成单色（无双线）数据，供 Kα2 存在性判别测试用。
    """
    st_a, st_b = _structure(_CAF2), _structure(_NACL)
    kal = Kalpha2(wavelength=LAM, ratio=0.497, separation=ka2)
    tabs = [build_reflections(st, two_theta_range=(12.0, 83.0)) for st in (st_a, st_b)]
    basis = design_matrix(TT, [PhaseSpec(t) for t in tabs], _profile(),
                          kalph2=kal, cutoff_fwhm=CUT)
    # 让定量落在目标分数上：W ∝ S·M_cell/V，先按单位标度算比例再反解
    unit = hill_howard(["a", "b"], [1.0, 1.0], [st_a, st_b])
    w_unit = np.array(unit.fractions)
    want = np.asarray(fractions, dtype=float) / 100.0
    scales = want / w_unit
    bg = background_basis(TT, BackgroundParams("tent", 9))
    y_true = basis @ scales + bg @ np.linspace(40.0, 25.0, 9)
    rng = np.random.default_rng(11)
    y_obs = y_true + rng.normal(0.0, np.sqrt(np.maximum(y_true, 1.0)))
    data = XRDData(two_theta=TT.copy(), intensity=y_obs, wavelength=LAM)
    return data, {"CaF2": fractions[0], "NaCl": fractions[1]}, st_a, st_b, scales


class TestEngineRegistration:
    def test_status_has_refinement_and_it_is_available(self):
        status = RietveldRefiner().get_engine_status()
        assert "refinement" in status
        assert status["refinement"]["available"] is True
        assert status["refinement"]["note"]

    def test_aliases_dispatch_to_v5(self, monkeypatch):
        refiner = RietveldRefiner()
        calls = []
        monkeypatch.setattr(
            refiner, "_refine_v5",
            lambda *a, **kw: calls.append("v5") or _stub_result())

        data = XRDData(two_theta=TT.copy(), intensity=np.full(TT.size, 100.0),
                       wavelength=LAM)
        for alias in ("refinement", "v5", "builtin_v5"):
            refiner.refine(data, [_phase(_CAF2)], engine=alias, max_cycles=5,
                           detect_ka2=False)
        assert calls == ["v5", "v5", "v5"], f"别名没走到新引擎: {calls}"


def _stub_result() -> RefinementResult:
    return RefinementResult(phases=[], wR=10.0, fit_params={"engine": "refinement"})


@pytest.fixture(scope="module")
def fitted():
    """跑一次 v5 引擎的合成两相精修（模块内共用，省掉重复拟合）。"""
    data, truth, _st_a, _st_b, _scales = _synthetic()
    # 基线：不含任何峰模型的"常数谱"Rwp（不拿另一个引擎当对照 ——
    # 那会把一条断言变成两次精修，慢且与本测试目的无关）
    w = 1.0 / np.maximum(data.intensity, 1.0)
    mean = float(np.average(data.intensity, weights=w))
    rwp0 = float(100.0 * np.sqrt(np.sum(w * (data.intensity - mean) ** 2)
                                 / np.sum(w * data.intensity ** 2)))
    result = RietveldRefiner().refine(
        data, [_phase(_CAF2), _phase(_NACL)], engine="refinement",
        max_cycles=60, perf_profile="fast")
    return result, truth, rwp0


class TestRefinesSyntheticTwoPhase:
    """冒烟级端到端：晶胞与定量都要回到合成时的真值。"""

    def test_engine_is_v5_not_fallback(self, fitted):
        result, _t, _r = fitted
        assert result.fit_params["engine"] == "refinement"
        assert "engine_fallback_reason" not in result.fit_params

    def test_metrics_valid_and_rwp_drops(self, fitted):
        result, _t, rwp0 = fitted
        assert result.metrics_valid is True      # 统计权拟合，Rexp/GOF 可解读
        assert result.wR < rwp0 + 1e-9
        assert result.GOF > 0 and np.isfinite(result.GOF)

    def test_cell_recovered(self, fitted):
        result, _t, _r = fitted
        a = result.phases[0].lattice.a
        assert abs(a - 5.4626) < 0.03, f"CaF2 a={a:.5f} 偏离真值"

    def test_fractions_close_to_truth(self, fitted):
        result, truth, _r = fitted
        got = {p.name: p.weight_fraction for p in result.phases}
        for name, want in truth.items():
            assert abs(got[name] - want) < 8.0, f"{name}: 精修 {got[name]:.1f}% vs 真值 {want:.1f}%"
        assert sum(got.values()) == pytest.approx(100.0, abs=1.0)

    def test_frozen_zero_and_cell_when_mask_off(self):
        data, _truth, _a, _b, _s = _synthetic()
        result = RietveldRefiner().refine(
            data, [_phase(_CAF2), _phase(_NACL)], engine="refinement",
            max_cycles=20, perf_profile="fast",
            options=types.SimpleNamespace(
                refine_zero_shift=False, refine_cell=False, refine_profile=False,
                refine_scale=True, refine_background=True,
                zero_shift_init=0.0, preferred_orientation=None))
        frozen = result.fit_params["v5_frozen_params"]
        assert "inst.zero" in frozen
        assert any(".cell.a" in n for n in frozen)
        # 峰形全钉住 → 六个 Lorentz/Caglioti 参数都在冻结表里
        assert {"inst.u", "inst.v", "inst.w", "inst.x", "inst.y", "inst.z"} <= set(frozen)


class TestFallbackIsExplicit:
    def test_phase_without_structure_falls_back_with_reason(self, monkeypatch):
        refiner = RietveldRefiner()
        calls = []

        def _fake_builtin(data, phases, strategy, max_cycles, **kw):
            calls.append("builtin")
            # 真 builtin 会把 engine 写成 "builtin" —— 回退诊断正是靠这个差异
            return RefinementResult(phases=[], wR=10.0,
                                    fit_params={"engine": "builtin"})

        monkeypatch.setattr(refiner, "_refine_builtin", _fake_builtin)
        bare = Phase(name="no-atoms", formula="X", space_group="Fm-3m",
                     lattice=LatticeParams(5.0, 5.0, 5.0, 90.0, 90.0, 90.0),
                     atomic_sites=[])
        data = XRDData(two_theta=TT.copy(), intensity=np.full(TT.size, 100.0),
                       wavelength=LAM)
        result = refiner.refine(data, [bare], engine="refinement", max_cycles=5)

        assert calls == ["builtin"], "缺结构时必须回退内置引擎"
        assert result.fit_params["engine_requested"] == "refinement"
        assert "no structure" in result.fit_params["engine_fallback_reason"]
        codes = [d.get("code") for d in result.diagnostics]
        assert "diag.engine_fallback" in codes, "回退必须留下结构化诊断"


class TestSiteFillWiring:
    """检索直通场景：候选相只有参考峰（无位点）时，先补位点、不直接回退。

    v5.0.1 之前这里必然是 ``engine_fallback_reason='no structure: ...'`` ——
    内置矿物表 / PDF2 的相天生没有位点，于是"选了新引擎却永远跑内置"。
    """

    def test_fill_supplies_sites_and_avoids_fallback(self, monkeypatch):
        from polyxrd.services import structure_augment as SA

        data, _truth, st_a, st_b, _sc = _synthetic()
        bare = []
        for spec in (_CAF2, _NACL):
            ph = _phase(spec)
            ph.atomic_sites = []          # 模拟检索直通：只有晶胞与参考峰
            bare.append(ph)

        calls = []

        def _fake_builtin(data_, phases, strategy, max_cycles, **kw):
            calls.append("builtin")
            return RefinementResult(phases=[], wR=99.0,
                                    fit_params={"engine": "builtin"})

        def _fake_fill(phases, *, db=None, log_cb=None):
            out, fills = [], []
            for ph, st in zip(phases, (st_a, st_b)):
                new = Phase(name=ph.name, formula=ph.formula,
                            space_group=ph.space_group, lattice=ph.lattice,
                            atomic_sites=[s.to_dict() for s in st.sites])
                out.append(new)
                fills.append(SA.SiteFill(name=ph.name, source="polyDB COD 1",
                                         matched_by="formula+sg+cell",
                                         n_sites=len(new.atomic_sites),
                                         cell_dev=0.0))
            return out, fills

        refiner = RietveldRefiner()
        monkeypatch.setattr(refiner, "_refine_builtin", _fake_builtin)
        monkeypatch.setattr(SA, "fill_atomic_sites", _fake_fill)

        result = refiner.refine(data, bare, engine="refinement", max_cycles=3)

        assert calls == [], "补到结构后不该回退内置引擎"
        fp = result.fit_params
        assert fp["engine"] == "refinement"
        assert not fp.get("engine_fallback_reason")
        assert len(fp["v5_structure_fills"]) == 2
        assert "COD 1" in fp["v5_structure_fills"][0]

    def test_fill_records_are_empty_when_sites_already_present(self, fitted):
        """本来就带位点 → 不做补齐、``v5_structure_fills`` 为空（不谎报）。"""
        result = fitted[0] if isinstance(fitted, tuple) else fitted
        assert result.fit_params["v5_structure_fills"] == []


class TestPreferredOrientationPlumbing:
    def test_po_direction_reaches_v5(self, monkeypatch):
        refiner = RietveldRefiner()
        seen = {}

        def _fake_v5(data, phases, strategy, max_cycles, **kw):
            seen.update(kw)
            return _stub_result()

        monkeypatch.setattr(refiner, "_refine_v5", _fake_v5)
        data = XRDData(two_theta=TT.copy(), intensity=np.full(TT.size, 100.0),
                       wavelength=LAM)
        refiner.refine(
            data, [_phase(_CAF2)], engine="refinement", max_cycles=5,
            options=types.SimpleNamespace(
                preferred_orientation={"direction": (0, 0, 1), "r": 1.6},
                zero_shift_init=0.0, refine_scale=True, refine_background=True,
                refine_profile=True, refine_cell=True, refine_zero_shift=True))
        assert tuple(seen.get("_po_direction", ())) == (0, 0, 1)
        assert seen.get("_po_r") == pytest.approx(1.6)


class TestKa2AutoDetection:
    """model_ka2="auto"（v5 默认）：按数据判 Kα2 双线有无（§十二 12.2-3）。

    收益不是 Rwp（含双线数据打平），是**参数可信度**：无双线数据却建模
    双线时 U·tan²θ 会被迫当伴峰的替身，宽度参数失去物理可解读性。

    数据用**单相宽角域**（CaF2 至 105°）：双相重叠谱的高角净窗太窄
    （~72–79°），判别器只能给 None（保守维持建模）——那是正确行为，
    但演示不了"判无"分支，所以这里选判别条件充分的数据。
    """

    @staticmethod
    def _caf2_data(ka2: bool) -> XRDData:
        st = _structure(_CAF2)
        tab = build_reflections(st, two_theta_range=(12.0, 108.0))
        tt = np.arange(15.0, 105.0, 0.02)
        kal = Kalpha2(wavelength=LAM, ratio=0.497, separation=ka2)
        basis = design_matrix(tt, [PhaseSpec(tab)], _profile(),
                              kalph2=kal, cutoff_fwhm=CUT)
        bg = background_basis(tt, BackgroundParams("tent", 7))
        y = basis @ np.array([50.0]) + bg @ np.linspace(40.0, 25.0, 7)
        rng = np.random.default_rng(7)
        y = y + rng.normal(0.0, np.sqrt(np.maximum(y, 1.0)))
        return XRDData(two_theta=tt, intensity=y, wavelength=LAM)

    def test_auto_disables_model_on_mono_data(self):
        res = RietveldRefiner().refine(
            self._caf2_data(ka2=False), [_phase(_CAF2)],
            engine="refinement", max_cycles=5)
        fp = res.fit_params
        assert fp["ka2_auto"] is True
        assert fp["model_ka2"] is False
        assert fp["ka2_detect"]["flagged"] is False

    def test_auto_keeps_model_on_doublet_data(self):
        res = RietveldRefiner().refine(
            self._caf2_data(ka2=True), [_phase(_CAF2)],
            engine="refinement", max_cycles=5)
        fp = res.fit_params
        assert fp["ka2_auto"] is True
        assert fp["model_ka2"] is True
        assert fp["ka2_detect"]["flagged"] is True

    def test_narrow_window_data_conservatively_keeps_model(self):
        """双相重叠谱（TT 15–80°）高角净窗不足 → 判 None → 维持建模。"""
        data, _truth, *_ = _synthetic(ka2=False)
        res = RietveldRefiner().refine(
            data, [_phase(_CAF2), _phase(_NACL)],
            engine="refinement", max_cycles=5)
        fp = res.fit_params
        assert fp["ka2_auto"] is True
        assert fp["ka2_detect"]["flagged"] is None
        assert fp["model_ka2"] is True

    def test_explicit_override_wins(self):
        res = RietveldRefiner().refine(
            self._caf2_data(ka2=False), [_phase(_CAF2)],
            engine="refinement", max_cycles=5, model_ka2=True)
        fp = res.fit_params
        assert fp["ka2_auto"] is False
        assert fp["model_ka2"] is True


class TestOverallBService:
    """每相整体 B 的服务层口径：**默认冻结**（opt-in），不为 Rwp 牺牲定量。

    依据（基准报告 §十四）：2-1 上 B 开使 Rwp 14.20→13.13 但定量从
    50.48/49.52 偏到 46.98/53.02（真值 50/50），B 在吸收结构误差。
    """

    def test_frozen_by_default(self):
        data, _truth, *_ = _synthetic()
        res = RietveldRefiner().refine(
            data, [_phase(_CAF2), _phase(_NACL)],
            engine="refinement", max_cycles=5)
        fp = res.fit_params
        assert fp["refine_b_overall"] is False
        assert fp["b_overall"] == [0.0, 0.0]

    def test_opt_in_reports_per_phase_b(self):
        data, _truth, *_ = _synthetic()
        res = RietveldRefiner().refine(
            data, [_phase(_CAF2), _phase(_NACL)],
            engine="refinement", max_cycles=5, refine_b_overall=True)
        fp = res.fit_params
        assert fp["refine_b_overall"] is True
        assert len(fp["b_overall"]) == 2
        assert max(fp["b_overall"]) > 0.0       # 参数真的进了非线性向量


class TestTierProtocolOrder:
    """档位协议阶段必须严格递增，且只能是引擎已定义的阶段号。

    这是一条**纯静态**守卫，但代价换来的是一次真实事故（2026-11-04）：precise
    档曾写成 ``(2,150) (3,120) (5,80) (4,40)``，而 stage 4 的裁剪条件是
    "全部相都无惯习面"—— 于是**只有自动择优命中时才保留 stage 4**，顺序恰好
    变成 5→4，`resolve_protocol` 抛 "协议阶段必须递增"，整条精修失败回退
    builtin。fast 档顺序正确，所以 A/B 与常规回归都看不出来。
    """

    def test_stages_strictly_increasing(self):
        for tier, spec in RietveldRefiner.V5_TIERS.items():
            stages = [st for st, _ in spec["protocol"]]
            assert stages == sorted(stages), f"{tier} 档阶段未递增: {stages}"
            assert len(set(stages)) == len(stages), f"{tier} 档阶段重复: {stages}"

    def test_stages_are_known(self):
        for tier, spec in RietveldRefiner.V5_TIERS.items():
            for st, iters in spec["protocol"]:
                assert 2 <= st <= 6, f"{tier} 档出现非法阶段 {st}"
                assert iters >= 10, f"{tier} 档 stage {st} 迭代数过小: {iters}"

    def test_trimmed_protocol_still_ordered(self):
        """模拟"自动择优命中 → 保留 stage 4"与"无 PO → 裁掉 stage 4"两种裁剪，
        结果都必须递增（这才是真正会跑的那条路径）。"""
        for tier, spec in RietveldRefiner.V5_TIERS.items():
            for drop4 in (True, False):
                stages = [st for st, _ in spec["protocol"]
                          if not (drop4 and st == 4)]
                assert stages == sorted(stages), (tier, drop4, stages)
