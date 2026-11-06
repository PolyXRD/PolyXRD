"""择优取向入口的逐相语义（v5.3.0, 2026-11-06）。

三个被实测咬过的坑，全部在这里锁住：

1. **只给方向、不给 ``_po_r`` 时择优被静默丢弃**：旧实现写成
   ``po_hkl = tuple(po_dir) if (po_dir and abs(po_r−1) > 1e-9) else None``，
   而 ``_po_r`` 默认 1.0 → 用户以为开了择优，实际整段没生效。
   实测代价：S3（萤石+石英+锐钛矿+刚玉+金红石）**22.97% vs 12.53%**。
2. **``_po_r`` 从未写进 ``PhaseBlock``**：r 起点 1.2 / 1.5 / 0.8 三种取值
   给出**逐位相同**的结果（12.531）—— 参数被吞。
3. **一个方向套全相**：真实多相试样各相惯习面不同（S3 只有萤石有 110、
   S7 是高岭石 001 + 萤石 110）。现在支持 ``_po_directions`` /
   ``_po_rs`` 逐相给出（dict 或 list），未给的相保持无择优。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

LAM = 1.5406


def _phase(name: str, a: float, sites: list[dict]) -> Phase:
    return Phase(name=name, formula="AB", space_group="P 1",
                 lattice=LatticeParams(a=a, b=a, c=a, alpha=90, beta=90, gamma=90),
                 atomic_sites=sites)


def _two_phases() -> list[Phase]:
    """两个立方相（不同 a），P1 位点已展开 —— 只为跑通 v5 引擎的参数链路。"""
    return [
        _phase("rock", 5.640, [
            {"label": "Na1", "element": "Na", "x": 0.0, "y": 0.0, "z": 0.0, "occupancy": 1.0},
            {"label": "Cl1", "element": "Cl", "x": 0.5, "y": 0.5, "z": 0.5, "occupancy": 1.0},
        ]),
        _phase("fluor", 5.463, [
            {"label": "Ca1", "element": "Ca", "x": 0.0, "y": 0.0, "z": 0.0, "occupancy": 1.0},
            {"label": "F1", "element": "F", "x": 0.25, "y": 0.25, "z": 0.25, "occupancy": 1.0},
        ]),
    ]


def _data() -> XRDData:
    tt = np.arange(20.0, 70.0, 0.05)
    y = np.full_like(tt, 30.0)
    for cen, amp in ((31.6, 100.0), (45.2, 45.0), (56.4, 25.0),      # rock
                     (32.7, 80.0), (46.9, 40.0)):                     # fluor
        y = y + amp * np.exp(-0.5 * ((tt - cen) / 0.09) ** 2)
    d = XRDData(two_theta=tt, intensity=y)
    d.wavelength = LAM
    return d


def _refine(**kw):
    return RietveldRefiner().refine(
        _data(), _two_phases(), engine="refinement", max_cycles=3,
        perf_profile="fast", auto_preferred_orientation=False, **kw)


class TestDirectionWithoutR:
    def test_single_direction_without_r_is_applied(self):
        """回归线：``_po_r`` 缺省（=1.0）时方向必须照样生效。"""
        r = _refine(_po_direction=(0, 0, 1))
        assert r.fit_params["v5_po_hkl"] == [[0, 0, 1], [0, 0, 1]]

    def test_no_direction_means_none(self):
        r = _refine()
        assert r.fit_params["v5_po_hkl"] == [None, None]

    def test_r_seed_reaches_block(self):
        """``_po_r`` 必须真的进到相状态里（旧实现被吞，三种起点结果逐位相同）。"""
        r = _refine(_po_direction=(0, 0, 1), _po_r=1.6)
        rs = r.fit_params["v5_po_r"]
        assert len(rs) == 2 and all(isinstance(v, float) for v in rs)


class TestPerPhaseDirections:
    def test_dict_only_first_phase(self):
        r = _refine(_po_directions={0: (0, 0, 1)})
        assert r.fit_params["v5_po_hkl"] == [[0, 0, 1], None]

    def test_list_sparse(self):
        r = _refine(_po_directions=[(0, 0, 1), None])
        assert r.fit_params["v5_po_hkl"] == [[0, 0, 1], None]

    def test_different_axes_per_phase(self):
        r = _refine(_po_directions={0: (0, 0, 1), 1: (1, 1, 0)})
        assert r.fit_params["v5_po_hkl"] == [[0, 0, 1], [1, 1, 0]]

    def test_per_phase_r(self):
        r = _refine(_po_directions={0: (0, 0, 1), 1: (1, 1, 0)},
                    _po_rs={0: 1.8, 1: 0.6})
        assert len(r.fit_params["v5_po_r"]) == 2

    def test_float_hkl_is_coerced_to_int(self):
        r = _refine(_po_directions={0: (0.0, 0.0, 1.0)})
        assert r.fit_params["v5_po_hkl"][0] == [0, 0, 1]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
