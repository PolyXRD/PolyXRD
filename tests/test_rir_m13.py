"""
M13 RIR 半定量测试 (Sprint 2)
=============================
覆盖: 相对 RIR 定量 / I/Icor 缺失降级 / 内标绝对定量。
"""
from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.services.rir import RIRAnalyzer


def _phase(name, formula, main_tt, elements):
    return Phase(name=name, formula=formula, elements=set(elements),
                 reference_peaks=[((1, 0, 0), main_tt, 100.0),
                                  ((2, 0, 0), main_tt + 10, 40.0)])


def _plist(tt_int):
    return PeakList(peaks=[Peak(two_theta=tt, intensity=it) for tt, it in tt_int])


class TestRIR:

    def test_relative_two_phase(self):
        a = _phase("A", "A2O", 30.0, ["A", "O"])
        b = _phase("B", "BO", 40.0, ["B", "O"])
        peaks = _plist([(30.0, 100.0), (40.0, 80.0)])
        res = RIRAnalyzer().rir_quantify(
            [a, b], peaks, iicor={"A": 2.0, "B": 1.0})
        # raw: A=100/2=50, B=80/1=80 → wA=38.46, wB=61.54
        assert abs(res.weights["A"] - 38.46) < 0.5, res.weights
        assert abs(res.weights["B"] - 61.54) < 0.5, res.weights
        assert res.quality == "ok"

    def test_iicor_by_formula_key(self):
        a = _phase("A-name", "A2O", 30.0, ["A", "O"])
        peaks = _plist([(30.0, 100.0)])
        res = RIRAnalyzer().rir_quantify([a], peaks, iicor={"A2O": 2.0})
        assert abs(res.weights["A-name"] - 100.0) < 1e-6
        assert abs(res.iicor_used["A-name"] - 2.0) < 1e-9

    def test_missing_main_peak_downgrades(self):
        a = _phase("A", "A2O", 30.0, ["A", "O"])
        b = _phase("B", "BO", 40.0, ["B", "O"])
        peaks = _plist([(30.0, 100.0)])   # B 的最强峰缺失
        res = RIRAnalyzer().rir_quantify([a, b], peaks, iicor={"A": 2.0, "B": 1.0})
        assert res.weights["B"] == 0.0
        assert res.quality == "low"
        assert "未在实测峰中找到" in res.note

    def test_missing_iicor_defaults_to_one(self):
        a = _phase("A", "A2O", 30.0, ["A", "O"])
        peaks = _plist([(30.0, 100.0)])
        res = RIRAnalyzer().rir_quantify([a], peaks, iicor={})
        assert "暂按 1.0" in res.note
        assert res.quality == "low"

    def test_internal_standard_absolute(self):
        a = _phase("A", "A2O", 30.0, ["A", "O"])
        b = _phase("B", "BO", 40.0, ["B", "O"])
        std = _phase("Std", "S2O", 50.0, ["S", "O"])
        peaks = _plist([(30.0, 100.0), (40.0, 80.0), (50.0, 60.0)])
        res = RIRAnalyzer().internal_standard_quantify(
            [a, b], std, std_wt_pct=20.0, peaks=peaks,
            iicor={"A": 2.0, "B": 1.0, "Std": 1.0})
        # raw: A50 B80 Std60 → wA'=26.32 wB'=42.11 wStd'=31.58
        # scale=20/31.58=0.633 → A=16.67, B=26.67
        assert res.absolute is True
        assert abs(res.weights["A"] - 16.67) < 0.5, res.weights
        assert abs(res.weights["B"] - 26.67) < 0.5, res.weights
        # 内标不计入样品 wt 输出
        assert "Std" not in res.weights

    def test_internal_standard_zero_std_reports_error(self):
        a = _phase("A", "A2O", 30.0, ["A", "O"])
        std = _phase("Std", "S2O", 50.0, ["S", "O"])
        peaks = _plist([(30.0, 100.0)])   # 内标峰缺失
        res = RIRAnalyzer().internal_standard_quantify(
            [a], std, std_wt_pct=20.0, peaks=peaks,
            iicor={"A": 2.0, "Std": 1.0})
        assert res.quality == "error"
        assert "无法定标" in res.note


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
