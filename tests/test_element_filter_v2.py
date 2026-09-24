"""
0.9.11 四态元素过滤 + 加权互斥匹配因子 测试
==========================================
覆盖用户给出的语义定义与三个示例, 以及新 FoM 的结构性修正。
"""
import numpy as np
import pytest

from polyxrd.models.fom import confidence_from_score
from polyxrd.models.search_options import SearchOptions
from polyxrd.services.foam import compute_fom, search_match
from polyxrd.models.phase import Phase
from polyxrd.utils.formula_parser import (
    LIGHT_ELEMENTS, elements_match_filter, normalize_element_filter,
)


def S(*els):
    return set(els)


class TestFourStateElementFilter:
    """必有 P / 含有 H / 可能 M / 没有 E, 未勾选默认 = 没有"""

    def test_example1_has_only(self):
        """含有{Mg,Ca,C,O} → MgO/CaO/CaCO3/MgCO3/CaMgCO3"""
        kw = dict(has=["Mg", "Ca", "C", "O"])
        for ok in [("Mg", "O"), ("Ca", "O"), ("Ca", "C", "O"),
                   ("Mg", "C", "O"), ("Ca", "Mg", "C", "O")]:
            assert elements_match_filter(S(*ok), **kw), ok
        assert not elements_match_filter(S("Zn", "O"), **kw)     # Zn 未勾选
        assert not elements_match_filter(S("Ca", "S", "O"), **kw)  # S 未勾选

    def test_example2_must_have_plus_has(self):
        """必有{Mg} + 含有{Ca,C,O} → MgO/MgCO3/CaMgCO3, 纯 Mg 也可 (用户确认)"""
        kw = dict(has=["Ca", "C", "O"], must_have=["Mg"])
        for ok in [("Mg", "O"), ("Mg", "C", "O"), ("Ca", "Mg", "C", "O"), ("Mg",)]:
            assert elements_match_filter(S(*ok), **kw), ok
        assert not elements_match_filter(S("Ca", "C", "O"), **kw)  # 缺 Mg

    def test_example3_must_have_all(self):
        """必有{Mg,Ca,C,O} → 只能是 CaMgCO3 (AND, 非 OR)"""
        kw = dict(must_have=["Mg", "Ca", "C", "O"])
        assert elements_match_filter(S("Ca", "Mg", "C", "O"), **kw)
        assert not elements_match_filter(S("Mg", "O"), **kw)
        assert not elements_match_filter(S("Ca", "C", "O"), **kw)
        assert not elements_match_filter(S("Ca", "Mg", "C", "O", "H"), **kw)  # H 未勾选

    def test_example4_edx_light_element_maybe(self):
        """EDX 测出 Al/O, H 放"可能" → Al2O3/Al/Al(OH)3 均可"""
        kw = dict(has=["Al", "O"], maybe=["H"])
        for ok in [("Al", "O"), ("Al",), ("Al", "O", "H")]:
            assert elements_match_filter(S(*ok), **kw), ok
        # 不勾 H → Al(OH)3 被默认排除
        assert not elements_match_filter(S("Al", "O", "H"), has=["Al", "O"])

    def test_maybe_alone_behaves_like_has(self):
        """只勾"可能" → 在可能元素中排列组合 (含有为空时可能代行其职)"""
        kw = dict(maybe=["Si", "O"])
        assert elements_match_filter(S("Si", "O"), **kw)
        assert elements_match_filter(S("Si",), **kw)
        assert not elements_match_filter(S("Fe", "O"), **kw)

    def test_exclude_only_is_open_world(self):
        """只勾"没有" → 开放世界, 仅排除这些元素"""
        assert elements_match_filter(S("Ca", "O"), exclude=["S"])
        assert not elements_match_filter(S("Ca", "S", "O"), exclude=["S"])

    def test_empty_is_full_search(self):
        assert elements_match_filter(S("Fe", "O"))
        assert elements_match_filter(set())

    def test_must_have_does_not_require_has(self):
        """勾了必有时不再要求至少含一个含有"""
        assert elements_match_filter(S("Mg"), has=["Ca"], must_have=["Mg"])
        assert not elements_match_filter(S("Mg"), must_have=["Mg", "Ca"])

    def test_priority_must_have_over_others(self):
        """同一元素同时出现在多类时, 必有 > 含有 > 可能 > 没有"""
        assert elements_match_filter(S("Mg"), must_have=["Mg"], exclude=["Mg"])

    def test_empty_elements_phase_excluded_when_closed(self):
        assert not elements_match_filter(set(), has=["Mg"])
        assert not elements_match_filter(set(), must_have=["Mg"])

    def test_closed_world_off(self):
        """closed_world=False 时未勾选元素不再自动排除"""
        assert elements_match_filter(S("Ca", "S", "O"), has=["Ca"], closed_world=False)


class TestNormalizeElementFilter:

    def test_legacy_must_maps_to_has(self):
        out = normalize_element_filter({"must": ["Zn"], "maybe": ["O"]})
        assert out == {"must_have": [], "has": ["Zn"], "maybe": ["O"], "exclude": []}

    def test_new_keys(self):
        out = normalize_element_filter({"must_have": ["Ca"], "has": ["Mg"],
                                        "maybe": [], "exclude": ["S"]})
        assert out["must_have"] == ["Ca"] and out["has"] == ["Mg"]
        assert out["exclude"] == ["S"]

    def test_dedup_priority(self):
        out = normalize_element_filter({"must": ["Ca", "Mg"], "must_have": ["Mg"]})
        assert out["must_have"] == ["Mg"] and out["has"] == ["Ca"]

    def test_none(self):
        out = normalize_element_filter(None)
        assert all(v == [] for v in out.values())

    def test_light_elements_constant(self):
        assert set(LIGHT_ELEMENTS) == {"O", "C", "H", "N", "S"}


# ── 匹配因子 ────────────────────────────────────────────────

def _refs(*pairs):
    return [((i,), tt, ii) for i, (tt, ii) in enumerate(pairs)]


class TestWeightedExclusiveFom:

    def test_perfect_match_is_zero(self):
        r = _refs((28.44, 100.0), (47.30, 60.0), (56.11, 35.0))
        f = compute_fom([28.44, 47.30, 56.11], [100.0, 60.0, 35.0], r, tol=0.15)
        assert f.matched == 3 and f.missed == 0
        assert f.score < 0.01

    def test_exclusive_matching_no_peak_stealing(self):
        """密集物相不能把多条参考峰都吸附到同一条实验峰上"""
        refs = _refs((30.0, 100.0), (30.05, 80.0), (30.10, 60.0))
        f = compute_fom([30.0], [100.0], refs, tol=0.15)
        assert f.matched == 1, f"互斥匹配应只允许 1 条命中, 实际 {f.matched}"
        assert f.missed == 2

    def test_strong_peak_miss_costs_more(self):
        """漏掉强峰的代价 > 漏掉弱峰"""
        obs = [20.0, 25.0]
        inten = [100.0, 50.0]
        strong_missed = compute_fom(obs, inten, _refs((20.0, 100.0), (40.0, 100.0)),
                                    tol=0.15)
        weak_missed = compute_fom(obs, inten, _refs((20.0, 100.0), (40.0, 5.0)),
                                  tol=0.15)
        assert strong_missed.score > weak_missed.score

    def test_normalization_independent_of_peak_count(self):
        """同一匹配质量下, 峰多的物相不应因归一化而系统性占优"""
        # 3 峰全部命中且偏差为 0 → 得分接近 0; 12 峰同理
        small = compute_fom([20.0, 30.0, 40.0], [100.0, 60.0, 30.0],
                            _refs((20.0, 100.0), (30.0, 60.0), (40.0, 30.0)),
                            tol=0.15)
        big = compute_fom([20.0 + 2 * i for i in range(12)],
                          [100.0 - 5 * i for i in range(12)],
                          _refs(*[(20.0 + 2 * i, 100.0 - 5 * i) for i in range(12)]),
                          tol=0.15)
        assert abs(small.score - big.score) < 0.01, (small.score, big.score)

    def test_unexplained_obs_penalized(self):
        """只解释少数实测峰的伪匹配被特异性项惩罚"""
        refs = _refs((20.0, 100.0))
        few = compute_fom([20.0], [100.0], refs, tol=0.15)
        many = compute_fom([20.0, 30.0, 40.0, 50.0, 60.0],
                           [100.0, 90.0, 80.0, 70.0, 60.0], refs, tol=0.15)
        assert many.score > few.score
        assert many.unexplained_obs == 4 and many.total_obs == 5

    def test_intensity_cosine_scale_invariant(self):
        """强度整体缩放不改变一致性判定 (余弦尺度无关)"""
        refs = _refs((20.0, 100.0), (30.0, 50.0), (40.0, 20.0))
        a = compute_fom([20.0, 30.0, 40.0], [100.0, 50.0, 20.0], refs, tol=0.15)
        b = compute_fom([20.0, 30.0, 40.0], [10.0, 5.0, 2.0], refs, tol=0.15)
        assert a.intensity_score == pytest.approx(1.0, abs=1e-6)
        assert b.intensity_score == pytest.approx(1.0, abs=1e-6)

    def test_confidence_bands(self):
        assert confidence_from_score(0.05) == "极好匹配"
        assert confidence_from_score(0.3) == "良好匹配"
        assert confidence_from_score(0.5) == "一般匹配"
        assert confidence_from_score(0.9) == "可能不匹配"


class TestSearchOptionsMustHave:

    def _db(self):
        return [
            Phase(name="Periclase", formula="MgO", elements={"Mg", "O"},
                  reference_peaks=[((1,), 42.9, 100.0)]),
            Phase(name="Corundum", formula="Al2O3", elements={"Al", "O"},
                  reference_peaks=[((1,), 25.6, 100.0)]),
            Phase(name="Dolomite", formula="CaMg(CO3)2",
                  elements={"Ca", "Mg", "C", "O"},
                  reference_peaks=[((1,), 31.0, 100.0)]),
        ]

    def test_must_have_filters(self):
        # 必有 Mg; O/Ca/C 放"可能"以免被默认排除
        res = search_match([42.9, 25.6, 31.0], [100.0, 90.0, 80.0], self._db(),
                           options=SearchOptions(must_have=["Mg"],
                                                 maybe=["O", "Ca", "C", "Al"]))
        names = {r.phase.name for r in res}
        assert names == {"Periclase", "Dolomite"}

    def test_must_have_all_required(self):
        res = search_match([42.9, 31.0], [100.0, 80.0], self._db(),
                           options=SearchOptions(must_have=["Mg", "Ca", "C", "O"]))
        assert [r.phase.name for r in res] == ["Dolomite"]

    def test_closed_world_default_excludes_unchecked(self):
        """含有 Mg 但未勾 O → MgO 因 O 未勾选而被排除 (闭环生效)"""
        res = search_match([42.9, 25.6], [100.0, 90.0], self._db(),
                           options=SearchOptions(must=["Mg"]))
        assert res == []
        # 补上 O 为"可能" → Periclase 回来
        res2 = search_match([42.9, 25.6], [100.0, 90.0], self._db(),
                            options=SearchOptions(must=["Mg"], maybe=["O"]))
        assert [r.phase.name for r in res2] == ["Periclase"]
