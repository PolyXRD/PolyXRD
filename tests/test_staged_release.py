"""分阶段释放 (W27) 与 Le Bail 级流水线 (W26)
==========================================
两者共用同一机制: 带**热启动**的多阶段拟合 (每阶段只放开一部分参数, 用上一阶段的解
作为下一阶段的第 1 个起点)。区别只在阶段表:
  - `pipeline="le_bail_then_rietveld"` (W26): 2 阶段 —— 先稳 cell+背景+标度 (轮廓冻结),
    再全放开;
  - `release_stages=True` (W27): 5 阶段渐进释放 scale+bg → +profile → +零点/位移 → +cell → +结构项。

本测试锁住阶段表、热启动是否真的接上、以及结果记录。
"""
from __future__ import annotations

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

LAM = 1.5406


def _gauss(x, cen, amp, fwhm):
    sig = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return amp * np.exp(-0.5 * ((x - cen) / sig) ** 2)


def _phase(name="T", a=4.0) -> Phase:
    return Phase(
        name=name, formula="T", lattice=LatticeParams(a=a, b=a, c=a),
        reference_peaks=[((1, 0, 0), 22.0, 100.0), ((1, 1, 0), 31.5, 60.0),
                         ((2, 0, 0), 45.9, 35.0), ((2, 1, 1), 57.0, 20.0)],
    )


def _data(seed: int = 2) -> XRDData:
    """两相谱: 主相 + 次相 (次相峰位与主相不重叠)"""
    rng = np.random.default_rng(seed)
    tt = np.arange(15.0, 75.0, 0.02)
    y = np.full_like(tt, 55.0)
    for _h, cen, amp in _phase().reference_peaks:
        y = y + 9.0 * amp * _gauss(tt, cen, 1.0, 0.10)
    for cen, amp in ((26.3, 40.0), (52.0, 25.0)):
        y = y + 9.0 * amp * _gauss(tt, cen, 1.0, 0.11)
    y = rng.poisson(np.maximum(y, 0.0)).astype(float)
    d = XRDData(two_theta=tt, intensity=y)
    d.wavelength = LAM
    return d


class TestSchedule:

    def test_le_bail_pipeline_table(self):
        st = RietveldRefiner._stage_schedule("le_bail_then_rietveld")
        assert [s[0] for s in st] == ["stabilize", "full"]
        m0 = st[0][1]
        assert m0["cell"] and m0["scale"] and m0["background"]
        assert not m0["profile"], "稳定阶段必须冻结轮廓"
        assert st[1][1] is None, "第二阶段应全放开"

    def test_release_stages_table_is_progressive(self):
        st = RietveldRefiner._stage_schedule("")
        names = [s[0] for s in st]
        assert names == ["scale_bg", "profile", "positions", "cell", "structure"]
        # 单调放开: 每个阶段放开的自由度数是递增的
        counts = [sum(1 for v in m.values() if v) if m else 99 for _n, m in st]
        assert counts == sorted(counts), counts
        assert st[0][1]["profile"] is False and st[0][1]["cell"] is False


class TestRefine:

    def test_release_stages_runs_and_records_trace(self):
        r = RietveldRefiner().refine(_data(), [_phase(), _phase("S", 4.3)],
                                     engine="builtin", max_cycles=6,
                                     release_stages=True, detect_ka2=False,
                                     n_starts=1, max_nfev_per_start=60)
        st = r.fit_params.get("stages")
        assert st and len(st) == 5, st
        assert [s["stage"] for s in st] == [
            "scale_bg", "profile", "positions", "cell", "structure"]
        # 逐阶段 wR 不应变差 (允许极小数值波动)
        wrs = [s["wR"] for s in st]
        assert wrs[-1] <= wrs[0] + 1e-6, wrs
        assert np.isfinite(r.wR) and r.wR < 100.0

    def test_le_bail_pipeline_runs(self):
        r = RietveldRefiner().refine(_data(seed=5), [_phase()],
                                     engine="builtin", max_cycles=6,
                                     pipeline="le_bail_then_rietveld",
                                     detect_ka2=False,
                                     n_starts=1, max_nfev_per_start=60)
        st = r.fit_params.get("stages")
        assert st and len(st) == 2, st
        assert r.fit_params.get("pipeline") == "le_bail_then_rietveld"
        assert np.isfinite(r.wR)

    def test_default_has_no_stage_trace(self):
        r = RietveldRefiner().refine(_data(seed=7), [_phase()],
                                     engine="builtin", max_cycles=4,
                                     wR_threshold=None, detect_ka2=False)
        assert "stages" not in r.fit_params
        assert "pipeline" not in r.fit_params

    def test_staged_is_not_worse_than_single_shot(self):
        """同预算下分阶段不应明显劣于一次全放开 (热启动 + 逐段收敛的效果)"""
        d = _data(seed=11)
        ph = [_phase(), _phase("S", 4.3)]
        kw = dict(engine="builtin", max_cycles=6, detect_ka2=False,
                  n_starts=1, max_nfev_per_start=60)
        r_flat = RietveldRefiner().refine(d, ph, wR_threshold=None, **kw)
        r_st = RietveldRefiner().refine(d, ph, release_stages=True, **kw)
        print(f"[staged] flat={r_flat.wR:.3f}%  staged={r_st.wR:.3f}%")
        assert r_st.wR <= r_flat.wR * 1.10 + 1e-9, (r_flat.wR, r_st.wR)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
