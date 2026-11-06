"""微吸收「没启用」的定量敏感度探针（v5.3, P0-E）守护。

## 为什么需要它

`microabsorption=True` **只在同时给了** `grain_radius_um > 0` 时才真正生效
（Brindley 的 τ 需要颗粒半径 R）。只给开关时整段被静默跳过，而 τ 既不进拟合
向量、也不改变 Rwp —— 于是"没做修正"在结果里**完全看不出来**。

这条静默项很贵。用 13 组实测样的称量配比做真值（`物相结果+wt%.txt`）实测：

| 试样 | 真值 | 默认（未修正） | 5 µm 修正后 |
|---|---|---|---|
| 2-1 | ZnO 50.00 / CaCO3 50.00 | 47.96 / 52.04（偏 2.04 pp） | 49.81 / 50.19（偏 0.19 pp） |
| 3-1 | ZnO 93.59 / Al2O3 5.04 / CaF2 1.36 | 最大 1.01 pp | — |

Rwp 在两种情形下**逐位相同（8.509）**，因为 τ 只改份额、被标度吸收。所以
"Rwp 好"完全不能说明 wt% 对 —— 必须主动探一次并告知用户。

## 四条断言

1. 只给开关不给半径 → 出 `MICROABSORPTION_OFF`，且带 `diag.refinement.` 前缀；
2. 给了半径（真做了修正）→ 不出该警告，`microabsorption_tau` 非空；
3. 位移低于门限 → 不出（别拿噪声打扰用户）；
4. 单相问题 → 不探（没有相间 μ 反差这回事）。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

LAM = 1.5406
GRID = np.arange(20.0, 80.0, 0.05)


def _phase(name: str, a: float, sites: list[dict]) -> Phase:
    return Phase(name=name, formula="AB", space_group="P 1",
                 lattice=LatticeParams(a=a, b=a, c=a, alpha=90, beta=90,
                                       gamma=90),
                 atomic_sites=sites)


def _light() -> Phase:
    """轻元素相（μ 小）。"""
    return _phase("light", 5.640, [
        {"label": "Na1", "element": "Na", "x": 0.0, "y": 0.0, "z": 0.0,
         "occupancy": 1.0, "b_iso": 0.5},
        {"label": "Cl1", "element": "Cl", "x": 0.5, "y": 0.5, "z": 0.5,
         "occupancy": 1.0, "b_iso": 0.5},
    ])


def _heavy() -> Phase:
    """重元素相（μ 大）—— 与 light 组成高反差，微吸收才有实际位移。"""
    return _phase("heavy", 5.200, [
        {"label": "Ba1", "element": "Ba", "x": 0.0, "y": 0.0, "z": 0.0,
         "occupancy": 1.0, "b_iso": 0.5},
        {"label": "O1", "element": "O", "x": 0.5, "y": 0.5, "z": 0.5,
         "occupancy": 1.0, "b_iso": 0.5},
    ])


def _synth(phases, weights):
    from polyxrd.refinement.pattern import PhaseSpec, phase_pattern
    from polyxrd.refinement.profile import ProfileParams
    from polyxrd.refinement.structure import StructureModel, build_reflections

    prof = ProfileParams(w=0.006, v=-0.002, u=0.0004, eta=0.6, use_tch=True)
    y = np.zeros_like(GRID)
    for ph, w in zip(phases, weights):
        st = StructureModel.from_phase(ph)
        tab = build_reflections(st, two_theta_range=(15.0, 85.0),
                                wavelengths=(LAM,))
        y += w * phase_pattern(GRID, PhaseSpec(table=tab), prof,
                               wavelength=LAM, cutoff_fwhm=20.0)
    rng = np.random.default_rng(7)
    return np.maximum(y + rng.normal(0.0, np.sqrt(np.maximum(y, 1.0))), 0.0)


def _run(phases, weights, *, sensitivity=None, **kw):
    cls = RietveldRefiner
    old = cls.MICROABS_SENSITIVITY_PP
    if sensitivity is not None:
        cls.MICROABS_SENSITIVITY_PP = float(sensitivity)
    try:
        y = _synth(phases, weights)
        return cls().refine(
            XRDData(two_theta=GRID, intensity=y, wavelength=LAM),
            phases, engine="refinement", max_cycles=6, perf_profile="fast", **kw)
    finally:
        cls.MICROABS_SENSITIVITY_PP = old


def _codes(res) -> set:
    return {f.get("code") for f in res.fit_params.get("v5_findings", [])}


class TestMuUsesFullCell:
    """μ 必须按**全胞成分**算，不能用 ``Phase.atomic_sites``（非对称单元）。

    这条是实测挖出来的真 bug：``linear_mu_from_sites`` 的约定是"全胞计数"，
    而 ``cif_to_phase`` 放进 ``atomic_sites`` 的是独立位点，于是 μ 按 ``1/Z``
    偏低 —— 实测真值样的 COD CIF（Cu Kα）：

    ==========  =========  =========  ===========
    相          位点表 μ   全胞 μ      NIST 期望
    ==========  =========  =========  ===========
    ZnO         140.5      281.1      ~277
    Fluorite    73.7       307.2      ~305
    Kaolinite   40.4       80.7       ~81
    Corundum    **None**   127.8      ~124
    Gibbsite    **None**   59.4       ~59
    ==========  =========  =========  ===========

    τ 偏小 ⇒ 微吸收几乎不起作用（v5.2 的卖点悄悄失效）；返回 None ⇒ 整条
    修正被放弃（4-1 就是这样）。用 NaCl（Fm-3m，Z=4）卡这个比值最干净。
    """

    def _nacl(self):
        return Phase(
            name="NaCl", formula="NaCl", space_group="F m -3 m",
            lattice=LatticeParams(a=5.640, b=5.640, c=5.640,
                                  alpha=90, beta=90, gamma=90),
            atomic_sites=[
                {"label": "Na1", "element": "Na", "x": 0.0, "y": 0.0, "z": 0.0,
                 "occupancy": 1.0},
                {"label": "Cl1", "element": "Cl", "x": 0.5, "y": 0.5, "z": 0.5,
                 "occupancy": 1.0}])

    def test_full_cell_is_z_times_asymmetric_unit(self):
        from polyxrd.refinement import linear_mu_from_sites
        from polyxrd.refinement.structure import StructureModel
        from polyxrd.services.rietveld_refiner import _phase_linear_mu

        ph = self._nacl()
        st = StructureModel.from_phase(ph)
        assert st.composition() == {"Na": 4.0, "Cl": 4.0}      # Z=4 已展开

        class _Block:          # 只要 .structure，够 _phase_linear_mu 用
            def __init__(self, structure):
                self.structure = structure

        mu = _phase_linear_mu([_Block(st)], [ph])[0]
        raw = linear_mu_from_sites(ph.atomic_sites, ph.lattice.volume)
        assert mu == pytest.approx(4.0 * raw, rel=0.02), (mu, raw)

    def test_falls_back_when_structure_missing(self):
        """拿不到结构时才退回位点表 —— 口径会偏，但不能因此整条失效。"""
        from polyxrd.refinement import linear_mu_from_sites
        from polyxrd.services.rietveld_refiner import _phase_linear_mu

        ph = self._nacl()
        mu = _phase_linear_mu([], [ph])[0]
        assert mu == pytest.approx(
            linear_mu_from_sites(ph.atomic_sites, ph.lattice.volume))

class TestMicroabsorptionProbe:
    def test_flag_without_radius_is_reported(self):
        """只给 `microabsorption=True`（无半径）→ 必须报，不能静默。"""
        res = _run([_light(), _heavy()], [0.5, 0.5],
                   sensitivity=0.0, microabsorption=True)
        assert "MICROABSORPTION_OFF" in _codes(res)
        item = [f for f in res.fit_params["v5_findings"]
                if f["code"] == "MICROABSORPTION_OFF"][0]
        ev = item["evidence"]
        assert ev["radius_um"] == pytest.approx(
            RietveldRefiner.MICROABS_PROBE_RADIUS_UM)
        assert ev["mu_ratio"] > 1.0
        # 进了界面 diagnostics 就必须是 diag. 前缀的点分键（否则显示原始码名）
        keys = [d["code"] for d in res.diagnostics]
        assert "diag.refinement.microabsorption_off" in keys
        assert len(res.diagnostics) <= 4

    def test_applied_path_gives_no_warning(self):
        """真做了修正（给了半径）→ 不该再报"没做"。"""
        res = _run([_light(), _heavy()], [0.5, 0.5],
                   sensitivity=0.0, microabsorption=True, grain_radius_um=5.0)
        assert "MICROABSORPTION_OFF" not in _codes(res)
        assert res.fit_params.get("microabsorption_tau")

    def test_below_threshold_is_silent(self):
        """位移小于门限 → 不打扰用户。"""
        res = _run([_light(), _heavy()], [0.5, 0.5],
                   sensitivity=999.0, microabsorption=True)
        assert "MICROABSORPTION_OFF" not in _codes(res)

    def test_single_phase_not_probed(self):
        """单相问题不存在相间 μ 反差，探针应直接跳过。"""
        res = _run([_heavy()], [1.0], sensitivity=0.0, microabsorption=True)
        assert "MICROABSORPTION_OFF" not in _codes(res)
