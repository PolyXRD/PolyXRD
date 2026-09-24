"""
M10 搜索-匹配增强测试 (Sprint 1)
===============================
覆盖: FoM 纯函数 / 三强峰预检 / Δ2θ 自适应 / 峰型匹配 / search_match 编排。
"""
import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.models.search_options import SearchOptions
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.foam import (
    check_three_strongest, compute_fom, delta_2theta_auto,
    profile_fitting_score, search_match,
)

SI_REFS = [((1, 1, 1), 28.44, 100.0), ((2, 2, 0), 47.30, 60.0),
           ((3, 1, 1), 56.11, 35.0), ((4, 0, 0), 69.13, 15.0)]
SI_OBS_TT = [r[1] for r in SI_REFS]
SI_OBS_I = [r[2] for r in SI_REFS]


def _phase(name, formula, refs, elements):
    return Phase(name=name, formula=formula, elements=set(elements),
                 reference_peaks=refs)


class TestComputeFom:

    def test_perfect_match_small_score(self):
        fom = compute_fom(SI_OBS_TT, SI_OBS_I, SI_REFS, tol=0.15)
        assert fom.matched == 4 and fom.missed == 0
        assert fom.score < 0.05, f"完美匹配 score 应很小, 实际 {fom.score}"

    def test_shifted_ref_misses_all(self):
        shifted = [((h,), tt + 0.3, i) for (h,), tt, i in
                   [((h,), tt, i) for h, tt, i in SI_REFS]]
        fom = compute_fom(SI_OBS_TT, SI_OBS_I, SI_REFS, tol=0.15)
        fom2 = compute_fom(SI_OBS_TT, SI_OBS_I, shifted, tol=0.15)
        assert fom2.matched == 0 and fom2.missed == 4
        assert fom2.score > fom.score

    def test_intensity_consistency_favored(self):
        # 峰位存在小偏差(penalty>0)时, 强度与实测一致的 refB 得分更低。
        # (乘性公式: 强度项作用于位置惩罚之上)
        obs_i = [100.0, 50.0, 20.0]
        obs_tt = [t + 0.10 for t in [28.44, 47.30, 56.11]]  # 每条偏差 0.10 ≤ tol
        refs_a = [((1,), 28.44, 100.0), ((2,), 47.30, 100.0), ((3,), 56.11, 100.0)]
        refs_b = [((1,), 28.44, 100.0), ((2,), 47.30, 50.0), ((3,), 56.11, 20.0)]
        fa = compute_fom(obs_tt, obs_i, refs_a, tol=0.15)
        fb = compute_fom(obs_tt, obs_i, refs_b, tol=0.15)
        assert fb.intensity_score > fa.intensity_score
        assert fb.score < fa.score, f"强度一致者应更低分: {fa.score:.4f} vs {fb.score:.4f}"

    def test_no_obs_peaks_returns_max(self):
        fom = compute_fom([], [], SI_REFS, tol=0.15)
        assert fom.score >= 999.0 and fom.matched == 0


class TestThreeStrongest:

    def test_hit_when_present(self):
        assert check_three_strongest(SI_OBS_TT, SI_REFS, tol=0.15, min_hits=1)
        assert check_three_strongest(SI_OBS_TT, SI_REFS, tol=0.15, min_hits=3)

    def test_miss_when_absent(self):
        # 前 3 强峰缺 2 条 (只留 47.3) → min_hits=2 应不通过
        gone = [47.3]
        assert not check_three_strongest(gone, SI_REFS, tol=0.15, min_hits=2)


class TestDeltaThetaAuto:

    def test_auto_from_peak_fwhm(self):
        pl = PeakList(peaks=[Peak(two_theta=28.0, intensity=1, fwhm=0.2),
                             Peak(two_theta=47.0, intensity=1, fwhm=0.1)])
        tol = delta_2theta_auto(pl, factor=1.0)
        assert abs(tol - 0.15) < 1e-6
        tol2 = delta_2theta_auto(pl, factor=2.0)
        assert abs(tol2 - 0.3) < 1e-6

    def test_fallback_default(self):
        assert delta_2theta_auto([], default_fwhm=0.2) == 0.2


class TestProfileFitting:

    def _synth(self, centers, amps, lo=20.0, hi=75.0, step=0.05, fwhm=0.2):
        g = np.arange(lo, hi + step / 2, step)
        y = np.zeros_like(g)
        s = fwhm / 2.355
        for c, a in zip(centers, amps):
            y += a * np.exp(-0.5 * ((g - c) / s) ** 2)
        return XRDData(two_theta=g, intensity=y)

    def test_correct_phase_high_corr(self):
        xrd = self._synth([r[1] for r in SI_REFS], [r[2] for r in SI_REFS])
        si = _phase("Silicon", "Si", SI_REFS, ["Si"])
        out = profile_fitting_score(xrd, si, fwhm=0.2)
        assert out["corr"] > 0.95, f"正确相相关应 >0.95, 实际 {out['corr']}"

    def test_wrong_phase_low_corr(self):
        xrd = self._synth([28.44, 47.30], [100.0, 60.0])
        wrong = _phase("Wrong", "W", [((h,), tt + 3.0, i)
                                      for (h,), tt, i in
                                      [((h,), tt, i) for h, tt, i in SI_REFS[:2]]],
                       ["W"])
        out = profile_fitting_score(xrd, wrong, fwhm=0.2)
        assert out["corr"] < 0.5, f"错误相相关应低, 实际 {out['corr']}"


class TestSearchMatch:

    def _db(self):
        return [
            _phase("Zincite", "ZnO", [((1,), 31.8, 100.0), ((2,), 34.4, 50.0)],
                   ["Zn", "O"]),
            _phase("Calcite", "CaCO3", [((1,), 29.4, 100.0), ((2,), 39.4, 40.0)],
                   ["Ca", "C", "O"]),
            _phase("Gypsum", "CaSO4", [((1,), 29.2, 100.0)], ["Ca", "S", "O"]),
            _phase("Zinc", "Zn", [((1,), 43.2, 100.0)], ["Zn"]),
        ]

    def test_ranking_and_element_restraint(self):
        db = self._db()
        # 实测峰 = Zincite + Calcite 混合
        tt = [31.8, 34.4, 29.4, 39.4]
        i = [100.0, 50.0, 90.0, 30.0]
        opts = SearchOptions(must=["Zn", "Ca"], maybe=["O", "C"], exclude=["S"])
        res = search_match(tt, i, db, options=opts)
        names = [r.phase.name for r in res]
        print("rank:", names)
        assert names[0] == "Zincite", f"完美匹配的 Zincite 应第一, 实际 {names}"
        assert "Gypsum" not in names, "exclude=S 应剔除 Gypsum"
        assert all(r.score < 999 for r in res)

    def test_max_entries_and_score_threshold(self):
        db = self._db()
        tt = [31.8, 34.4]
        i = [100.0, 50.0]
        opts = SearchOptions(max_entries=2, score_threshold=0.5)
        res = search_match(tt, i, db, options=opts)
        assert len(res) <= 2

    def test_three_strongest_gate(self):
        db = self._db()
        tt = [34.4]  # 只有 Zincite 次强峰
        opts = SearchOptions(check_three_strongest=True, three_strongest_hits=2)
        res = search_match(tt, [50.0], db, options=opts)
        assert all(r.phase.name != "Zincite" for r in res), \
            "三强峰预检未通过时不应放行 Zincite"

    def test_name_pattern(self):
        db = self._db()
        tt = [31.8, 34.4]
        opts = SearchOptions(name_pattern="*Zincite")
        res = search_match(tt, [100.0, 50.0], db, options=opts)
        assert {r.phase.name for r in res} == {"Zincite"}


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
