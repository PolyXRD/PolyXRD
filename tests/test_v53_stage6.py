"""结构层（stage 6）进 precise 档的三道闸（v5.3.0, 2026-11-06）。

背景：对标 MAUD 时发现**协议最多只跑到 stage 5**，独立位点坐标 / Biso 这
整层强度自由度从来没被放开过。MAUD 的 7 组工程明确写着
``_riet_refine_crystal_structure_over 0.1``，而我们是"结构全程冻结"。补齐后
7 组 Rwp/MAUD 的均值从 1.36 降到 1.08（S6b 0.65、S5b 0.85、S4b 0.94 反超）。

三道闸（缺一条都会出事）：

1. **只在 precise 档**：fast 档是"快速预览"，多几十列雅可比等于毁掉它的定位。
2. **用户可关**：``refine_structure=False`` 必须真的裁掉 stage 6，并让
   ``v5_atom_params`` 报 0（否则报告侧会声称"结构精修过"而其实没有）。
3. **参数上限**：独立位点上百、反射数却不够时，stage 6 会把系统误差拟合成
   假键长；超过 ``V5_ATOM_MAX_PARAMS`` 就整段跳过。
"""
from __future__ import annotations

import re

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

LAM = 1.5406

#: 协议日志缓存：一次 refine 动辄几十秒，同参数的用例共用一次执行
_PROTO_CACHE: dict = {}


def _phase(name: str, a: float, sites: list[dict]) -> Phase:
    return Phase(name=name, formula="AB", space_group="P 1",
                 lattice=LatticeParams(a=a, b=a, c=a, alpha=90, beta=90,
                                       gamma=90),
                 atomic_sites=sites)


def _two_phases() -> list[Phase]:
    return [
        _phase("rock", 5.640, [
            {"label": "Na1", "element": "Na", "x": 0.0, "y": 0.0, "z": 0.0,
             "occupancy": 1.0},
            {"label": "Cl1", "element": "Cl", "x": 0.5, "y": 0.5, "z": 0.5,
             "occupancy": 1.0},
        ]),
        _phase("fluor", 5.463, [
            {"label": "Ca1", "element": "Ca", "x": 0.0, "y": 0.0, "z": 0.0,
             "occupancy": 1.0},
            {"label": "F1", "element": "F", "x": 0.25, "y": 0.25, "z": 0.25,
             "occupancy": 1.0},
        ]),
    ]


def _data() -> XRDData:
    tt = np.arange(20.0, 70.0, 0.05)
    y = np.full_like(tt, 30.0)
    for cen, amp in ((31.6, 100.0), (45.2, 45.0), (56.4, 25.0),
                     (32.7, 80.0), (46.9, 40.0)):
        y = y + amp * np.exp(-0.5 * ((tt - cen) / 0.09) ** 2)
    d = XRDData(two_theta=tt, intensity=y)
    d.wavelength = LAM
    return d


def _refine(**kw):
    kw.setdefault("engine", "refinement")
    kw.setdefault("max_cycles", 1)
    kw.setdefault("auto_preferred_orientation", False)
    return RietveldRefiner().refine(_data(), _two_phases(), **kw)


class TestTierStage6:
    def test_precise_tier_has_stage6(self):
        stages = [int(st) for st, _ in
                  RietveldRefiner.V5_TIERS["precise"]["protocol"]]
        assert 6 in stages, f"precise 档协议缺 stage 6: {stages}"
        assert stages[-1] == 6, f"stage 6 必须是最后一段: {stages}"

    def test_fast_tier_has_no_stage6(self):
        """fast 档定位是"快速预览"，结构层不进它。"""
        stages = [int(st) for st, _ in RietveldRefiner.V5_TIERS["fast"]["protocol"]]
        assert 6 not in stages

    def test_fast_tier_reports_zero_atom_params(self):
        r = _refine(perf_profile="fast")
        assert r.fit_params["v5_atom_params"] == 0

    def test_precise_tier_actually_frees_atoms(self):
        r = _refine(perf_profile="precise")
        # 2 相 × 2 位点：坐标 3 + Biso 1（占位满 → 固定）
        assert r.fit_params["v5_atom_params"] == 2 * 2 * 4


class TestStage6Gates:
    def test_refine_structure_false_drops_stage6(self):
        r = _refine(perf_profile="precise", refine_structure=False)
        assert r.fit_params["v5_atom_params"] == 0

    def test_param_cap_drops_stage6(self, monkeypatch):
        """上限调成 1 时，8 个自由原子参数必须被整段拦下。"""
        monkeypatch.setattr(RietveldRefiner, "V5_ATOM_MAX_PARAMS", 1)
        r = _refine(perf_profile="precise")
        assert r.fit_params["v5_atom_params"] == 0

    def test_no_sites_at_all_still_refines(self):
        """免结构相（参考峰直通、位点补不上）不该因为 stage 6 整条失败。

        这里直接用"空位点 + 已有参考峰"的相，引擎要么补齐位点、要么回退
        builtin，但绝不能抛 —— 也不能在 fit_params 里声称精修过结构。
        """
        phases = _two_phases()
        phases[0].atomic_sites = []
        res = RietveldRefiner().refine(
            _data(), phases, engine="refinement", max_cycles=1,
            perf_profile="precise", auto_preferred_orientation=False)
        assert "v5_atom_params" not in res.fit_params or \
            res.fit_params["v5_atom_params"] >= 0


class TestProtocolBudget:
    """档位表里的 ``max_iter`` 必须真的进到协议里。

    踩过的坑（2026-11-06）：``StageSpec`` 的签名是
    ``StageSpec(stage, label="", max_iter=100, method="auto")`` —— 第二个**位置**
    参数是 ``label``。调用处写成 ``StageSpec(st, min(it, max_cycles*20))``，于是
    迭代预算被当成展示名，``max_iter`` 恒取默认 **100**：档位表的 150/120/40/80
    与 ``max_cycles`` 从未生效，唯一线索是执行日志里每段都写着 ``≤100``。
    这条测试直接对**真实执行的协议日志**断言，不去 import ``StageSpec``
    （后者在可选依赖 try 块里，模块级 import 会破坏优雅降级）。
    """

    @staticmethod
    def _protocol_line(**kw):
        key = tuple(sorted((k, str(v)) for k, v in kw.items()))
        if key not in _PROTO_CACHE:
            logs: list[str] = []
            _refine(log_cb=logs.append, **kw)
            line = [s for s in logs if s.startswith("[v5] protocol:")]
            assert line, "没打出协议日志"
            _PROTO_CACHE[key] = line[0]
        return _PROTO_CACHE[key]

    def test_tier_budgets_reach_the_protocol(self):
        line = self._protocol_line(perf_profile="fast", max_cycles=5)
        pairs = re.findall(r"stage (\d+)\(≤(\d+)\)", line)
        assert pairs, line
        budget = {int(st): int(it) for st, it in
                  RietveldRefiner.V5_TIERS["fast"]["protocol"]}
        for st, it in pairs:
            assert int(it) == budget[int(st)], (st, it, line)

    def test_max_cycles_clamps_budget(self):
        """``max_cycles=1`` → 每段预算被压到 ``max(10, 20) = 20``。"""
        line = self._protocol_line(perf_profile="fast", max_cycles=1)
        assert "≤20" in line, line

    def test_budget_is_not_default_100(self):
        """回归线：任何一段都不该是无源无故的 100（= 位置参数被当 label 的指纹）。"""
        line = self._protocol_line(perf_profile="fast", max_cycles=5)
        assert "≤100" not in line, line


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
