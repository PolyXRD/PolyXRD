"""结构候选排序分 + 定量口径降级可见 (回归测试)
==============================================
1. ``_candidate_score``: ``_fallback`` 候选 (元素集回退来的同系物) 在同条件
   下必须排在精确命中之后。该打分函数仍被 ``phase_cif_export`` 的按式查号
   路径使用, 故保留测试。（v4.2 删除了 resolver 里调用它的 COD 候选检索。）
2. 定量口径降级可见: weight_basis=relative 时产出结构化诊断
   diag.weight_basis_relative (缺结构的相名列在 params 里)。
"""
from __future__ import annotations

import numpy as np

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.phase_structure_resolver import _candidate_score


# ── 候选排序分 ────────────────────────────────────────────────

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
