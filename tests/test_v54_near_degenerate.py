"""P0-E′：定量「近简并」判定与 Δwt/ΔRwp 探针的守护测试。

判据（docs/评估报告-MAUD对标-精修质量-v4.md §13.8）：
1. 该相最强**独立**线的观测净积分占全谱 < 15%；
2. 把该相 wt% 推 10 pp，Rwp 只变 < 0.2 pp（即 Δwt/ΔRwp > 50 pp/%）。
两条同时成立才报 ``PHASE_NEAR_DEGENERATE``。
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from polyxrd.refinement.report import _near_degenerate, _wt_rwp_probe


def _pattern(small_height: float = 300.0) -> tuple[np.ndarray, np.ndarray]:
    x = np.arange(10.0, 50.0, 0.02)
    y = np.full_like(x, 100.0)
    y += 4000.0 * np.exp(-((x - 20.0) / 0.08) ** 2)
    y += small_height * np.exp(-((x - 40.0) / 0.08) ** 2)
    return x, y


def _quant(fractions=(0.8, 0.2)) -> SimpleNamespace:
    # _near_degenerate 只读 labels/fractions；不必构造完整 QuantResult
    return SimpleNamespace(labels=("Big", "Small"), fractions=fractions)


def test_flags_weak_independent_line_with_expensive_wt() -> None:
    x, y = _pattern()
    peaks = [("Big", np.array([20.0]), np.array([1.0])),
             ("Small", np.array([40.0]), np.array([1.0]))]
    probe = {"Small": (109.0, 10.0, 0.092), "Big": (9.0, 10.0, 1.1)}

    out = _near_degenerate(x, y, peaks, _quant(), calc_centers=[20.0, 40.0],
                           wt_rwp_probe=probe)

    assert [f.code for f in out] == ["PHASE_NEAR_DEGENERATE"]
    ev = out[0].evidence
    assert ev["phase"] == "Small"
    assert ev["fraction_pct"] == 20.0
    assert 0.0 < ev["share_pct"] < 15.0
    assert ev["ratio"] == 109.0


def test_no_flag_when_rwp_responds() -> None:
    """Rwp 对 wt% 有明显反应（比值 < 50）→ 不是近简并，不报。"""
    x, y = _pattern()
    peaks = [("Big", np.array([20.0]), np.array([1.0])),
             ("Small", np.array([40.0]), np.array([1.0]))]
    probe = {"Small": (20.0, 10.0, 0.5)}

    assert _near_degenerate(x, y, peaks, _quant(), [20.0, 40.0],
                            wt_rwp_probe=probe) == []


def test_no_flag_when_line_carries_enough_area() -> None:
    """最强独立线净积分占全谱 ≥ 15% → 约束足够，不报。"""
    x, y = _pattern(small_height=5000.0)
    peaks = [("Big", np.array([20.0]), np.array([1.0])),
             ("Small", np.array([40.0]), np.array([1.0]))]
    probe = {"Small": (109.0, 10.0, 0.092)}

    assert _near_degenerate(x, y, peaks, _quant(), [20.0, 40.0],
                            wt_rwp_probe=probe) == []


def test_no_flag_for_buried_strongest_line() -> None:
    """最强线被别的相压过时它不算"独立证据"，交给 PHASE_FRACTION_UNVERIFIABLE。"""
    x, y = _pattern()
    peaks = [("Big", np.array([20.0]), np.array([1.0])),
             ("Small", np.array([20.0]), np.array([1.0]))]
    probe = {"Small": (109.0, 10.0, 0.092)}

    assert _near_degenerate(x, y, peaks, _quant(), [20.0, 40.0],
                            wt_rwp_probe=probe) == []


def test_no_probe_or_single_phase_is_silent() -> None:
    x, y = _pattern()
    peaks = [("Big", np.array([20.0]), np.array([1.0])),
             ("Small", np.array([40.0]), np.array([1.0]))]

    assert _near_degenerate(x, y, peaks, _quant(), [20.0, 40.0],
                            wt_rwp_probe={}) == []
    assert _near_degenerate(x, y, peaks, _quant((1.0,)), [20.0, 40.0],
                            wt_rwp_probe={"Small": (109.0, 10.0, 0.092)}) == []


def test_probe_reports_cheap_vs_expensive_fraction() -> None:
    """小峰相推 10 pp 几乎不花 Rwp，大峰相要花很多 → 探针比值一高一低。"""

    class _Prob:
        def __init__(self, basis, y):
            self.basis = basis
            self.y_obs = y
            self.weights = np.ones_like(y)

        def design(self):
            return self.basis, None

    x, y = _pattern(small_height=300.0)
    basis = np.column_stack([
        4000.0 * np.exp(-((x - 20.0) / 0.08) ** 2),
        300.0 * np.exp(-((x - 40.0) / 0.08) ** 2),
    ])
    quant = SimpleNamespace(labels=("Big", "Small"), fractions=(0.9, 0.1))

    probe = _wt_rwp_probe(_Prob(basis, y), quant)

    assert set(probe) == {"Big", "Small"}
    assert probe["Small"][0] > probe["Big"][0]
    # 小峰推 10 pp 的 Rwp 代价远小于大峰
    assert probe["Small"][2] < probe["Big"][2]
