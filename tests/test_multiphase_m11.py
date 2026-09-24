"""
M11 多相迭代识别测试 (Sprint 1)
===============================
覆盖: 主相→微量相迭代召回 / 冗余相不进入 / 诊断报告。
"""
from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.models.search_options import SearchOptions
from polyxrd.services.multiphase import iterative_identify, trace_report


def _phase(name, formula, refs, elements):
    return Phase(name=name, formula=formula, elements=set(elements),
                 reference_peaks=refs)


def _plist(tt_int):
    return PeakList(peaks=[Peak(two_theta=tt, intensity=it)
                           for tt, it in tt_int])


class TestIterativeIdentify:

    def _db(self):
        return [
            _phase("MajorA", "A2O3", [((1,), 30.0, 100.0), ((2,), 50.0, 60.0),
                                      ((3,), 60.0, 30.0)], ["A", "O"]),
            _phase("TraceB", "BO", [((1,), 33.0, 100.0), ((2,), 55.0, 40.0)],
                   ["B", "O"]),
            _phase("NoiseC", "CO3", [((1,), 31.0, 100.0)], ["C", "O"]),
        ]

    def test_major_then_trace_recalled(self):
        """主相 A + 微量 B 混合: 迭代应先在残差上召回 B。"""
        obs = _plist([(30.0, 100.0), (33.0, 12.0), (50.0, 60.0),
                      (55.0, 6.0), (60.0, 30.0)])
        res = iterative_identify(obs, self._db(), max_rounds=4)
        names = [r.phase.name for r in res]
        print("iter ->", names)
        assert "MajorA" in names, f"主相应被识别: {names}"
        assert "TraceB" in names, f"微量相应通过残差迭代被召回: {names}"
        # NoiseC (只解释残差里没有的 31°) 不应被选中
        assert "NoiseC" not in names

    def test_residual_empty_terminates(self):
        """单相试样: 一轮后残差为空即停止, 不会空转多轮。"""
        obs = _plist([(30.0, 100.0), (50.0, 60.0), (60.0, 30.0)])
        res = iterative_identify(obs, self._db(), max_rounds=6)
        assert [r.phase.name for r in res] == ["MajorA"]

    def test_redundant_phase_not_appended(self):
        """与主相参考峰完全相同但不同名的冗余相不得被追加。"""
        dup = _phase("MajorA2", "A2O3b",
                     [((1,), 30.0, 100.0), ((2,), 50.0, 60.0), ((3,), 60.0, 30.0)],
                     ["A", "O"])
        obs = _plist([(30.0, 100.0), (50.0, 60.0), (60.0, 30.0)])
        res = iterative_identify(obs, self._db() + [dup], max_rounds=6)
        assert len(res) == 1, f"冗余相不应进入结果: {[r.phase.name for r in res]}"

    def test_element_constraint_limits_pool(self):
        """SearchOptions.must 全允集不含 B → TraceB 永不出现。"""
        obs = _plist([(30.0, 100.0), (33.0, 12.0), (50.0, 60.0),
                      (55.0, 6.0), (60.0, 30.0)])
        opts = SearchOptions(must=["A", "O"], maybe=["C"])
        res = iterative_identify(obs, self._db(), options=opts, max_rounds=4)
        names = [r.phase.name for r in res]
        assert all(n != "TraceB" for n in names), f"元素约束应排除 TraceB: {names}"

    def test_trace_report_shape(self):
        obs = _plist([(30.0, 100.0), (33.0, 12.0), (50.0, 60.0),
                      (55.0, 6.0), (60.0, 30.0)])
        res = iterative_identify(obs, self._db(), max_rounds=4)
        report = trace_report(res)
        assert len(report) == len(res)
        assert set(report[0]) >= {"round", "name", "formula", "matched_peaks",
                                  "score"}
        assert report[0]["round"] == 1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
