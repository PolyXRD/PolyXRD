"""v2.1-C: 结构回填检索增强 + 失败原因可见 (回归测试)
====================================================
1. 元素集宽松回退: 固溶体/非整比相 (如 NCM 三元) 精确化学式落空时,
   按"元素集全部以独立 token 出现"把同系物结构候选找回来;
   回退候选带 _fallback 标记, 排序降权 (精确命中优先)。
2. 定量口径降级可见: weight_basis=relative 时产出结构化诊断
   diag.weight_basis_relative (缺结构的相名列在 params 里)。
"""
from __future__ import annotations

import numpy as np

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.phase_structure_resolver import (
    PhaseStructureResolver,
    _candidate_score,
)


# ── 元素集回退: resolver 层 ──────────────────────────────────

class _FallbackStubDB:
    """模拟"精确式查不到、元素集能查到"的 COD 库。"""

    def __init__(self):
        self.calls: list[tuple] = []

    def find_structure_candidates(self, formula_norm, mineral_name="",
                                  limit=24, elements=None):
        self.calls.append((formula_norm, mineral_name, tuple(elements or ())))
        if formula_norm:
            return []                      # 精确式: NCM 配比与库值差一档 → 空
        if elements:
            return [{
                "cod_id": 1520789,
                "formula": "Co0.1 Li1.03 Mn0.1 Ni0.77 O2",
                "space_group": "R -3 m",
                "a": 2.8645, "b": 2.8645, "c": 14.22,
                "alpha": 90.0, "beta": 90.0, "gamma": 120.0,
                "has_cif": True, "mineral_name": "",
                "_fallback": True,
            }]
        return []

    def get_phase(self, cod_id, **kwargs):
        p = Phase(
            name=f"COD_{cod_id}",
            formula="Co0.1 Li1.03 Mn0.1 Ni0.77 O2",
            space_group="R -3 m",
            lattice=LatticeParams(a=2.8645, b=2.8645, c=14.22,
                                  alpha=90, beta=90, gamma=120),
            atomic_sites=[
                {"label": "Ni1", "element": "Ni", "x": 0.0, "y": 0.0,
                 "z": 0.0, "occupancy": 1.0},
                {"label": "O1", "element": "O", "x": 0.0, "y": 0.0,
                 "z": 0.24, "occupancy": 1.0},
            ],
            cif_path=None,
        )
        p.reference_peaks = [((0, 0, 3), 18.8, 100.0), ((1, 0, 1), 36.7, 45.0)]
        return p

    def get_cif(self, cod_id):
        return "data_test\n"


def test_element_set_fallback_recovers_candidates():
    """精确式空 → 元素集回退命中 → 结构成功合并; 元素集参数正确传递。"""
    db = _FallbackStubDB()
    resolver = PhaseStructureResolver(cod_db=db)
    ncm = Phase(name="NCM811", formula="Li(Ni0.8Co0.1Mn0.1)O2")
    out = resolver.resolve([ncm])
    resolved = out[0]
    assert resolved is not ncm                       # 结构已补齐
    assert resolved.atomic_sites, resolved
    assert resolved.name == "NCM811"                 # 身份字段保留
    # 元素集回退确实被调用, 且元素来自化学式解析
    assert any(c[0] == "" and c[2] for c in db.calls), db.calls


def test_fallback_candidates_scored_below_exact():
    """_fallback 候选在同条件下必须排在精确命中之后 (降权 0.25)。"""
    ph = Phase(name="T", formula="Mg O",
               lattice=LatticeParams(a=4.2, b=4.2, c=4.2,
                                     alpha=90, beta=90, gamma=90))
    exact = {"cod_id": 1, "space_group": "Fm -3 m", "a": 4.21, "b": 4.21,
             "c": 4.21, "alpha": 90, "beta": 90, "gamma": 90, "has_cif": True,
             "mineral_name": ""}
    fb = dict(exact, cod_id=2, _fallback=True)
    s_exact = _candidate_score(exact, ph)
    s_fb = _candidate_score(fb, ph)
    assert s_fb > s_exact                            # 回退候选更"坏"


# ── 定量降级诊断: refiner 层 ─────────────────────────────────

def test_weight_basis_relative_emits_structured_diag():
    """无结构相 (仅参考峰) → weight_basis=relative 且诊断带相名。"""
    tt = np.arange(20.0, 60.0, 0.05)
    y = np.full_like(tt, 100.0)
    y += 900.0 * np.exp(-0.5 * ((tt - 30.0) / 0.08) ** 2)
    y += 400.0 * np.exp(-0.5 * ((tt - 43.0) / 0.08) ** 2)
    data = XRDData(two_theta=tt, intensity=y)
    data.wavelength = 1.5406
    ph = Phase(name="ZnO", formula="ZnO",
               lattice=LatticeParams(a=3.25, b=3.25, c=5.207,
                                     alpha=90, beta=90, gamma=120),
               reference_peaks=[((1, 0, 0), 31.7, 57.0),
                                ((1, 0, 1), 36.2, 100.0)])
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    r = RietveldRefiner().refine(data, [ph], engine="builtin", max_cycles=2,
                                 wR_threshold=None, detect_ka2=False)
    assert r.fit_params.get("weight_basis") == "relative"
    codes = {d.get("code"): d for d in r.diagnostics}
    entry = codes.get("diag.weight_basis_relative")
    assert entry is not None, r.diagnostics
    assert "ZnO" in entry["params"]["phases"]


if __name__ == "__main__":  # pragma: no cover
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
