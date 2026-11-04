# -*- coding: utf-8 -*-
"""B 方向：检索折叠时优先"位点元素齐全"的条目（同键组内换代表）。

真实问题链（2026-11-04）：COD 的氢氧化物/含水矿物条目常只列重原子 ——
formula 写 ``Al H3 O3``，CIF 原子环里只有 Al/O。H 对 X 射线散射贡献 ≈1 个
电子，峰位与相对强度几乎不变，所以这种"缺氢条目"在检索阶段与含氢条目打分
并列，产品检索就选中了缺氢的那条。一旦进 Rietveld，该相基面强线被算低、
定量系统性偏低（7-1 实测 Gibbsite 43.16 vs 真值 54.90；换含氢条目后 45.46）。

修法：``_collapse_distinct`` 折叠同相复本时，同键组内若有"位点元素齐全"的
条目，优先用它当代表。**只换该位置的条目内容、不动位置与顺序**，所以对
top-N 的相集合零影响（严格保持"去重对真值召回非回退"的既有保证）。

另加：折叠键的空间群改用**国际表编号** —— 同相替代设置（``P n m a`` /
``P b n m``、``C m c m`` / ``B b m m`` / ``A m a m``）共享编号而字符串写法
各异，只按字符串比会把同相拆成多键、白占 top-N 名额（7-1/5-3 实测）。
"""
from __future__ import annotations

import pytest

from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.services.phase_identifier import (
    _COD_PREFER_COMPLETE_SITES,
    _COMPLETE_SITE_SCORE_FLOOR,
    _cod_comp_key,
    _collapse_distinct,
    _missing_site_elements,
    _site_element_symbols,
)


def _phase(formula: str, elements: set[str], site_els: list[str],
           name: str = "X") -> Phase:
    return Phase(
        name=name,
        formula=formula,
        elements=set(elements),
        atomic_sites=[
            {"label": f"{el}1", "element": el,
             "x": 0.0, "y": 0.0, "z": 0.0, "occupancy": 1.0}
            for el in site_els
        ],
    )


def _item(phase: Phase, score: float, formula: str | None = None,
          sg: str = "P 1 21/n 1", sg_number: int = 14,
          hanawalt: float = 0.9, name: str | None = None) -> tuple:
    """(预筛候选 dict, PhaseMatchResult) —— 与 _rank_candidates 的入参同构。"""
    if name is not None:
        phase.name = name
    cand = {
        "formula": formula or phase.formula,
        "space_group": sg,
        "sg_number": sg_number,
        "main_peak_match": hanawalt,
        "top_precision": hanawalt,
        "intensity_weighted_top_recall": hanawalt,
        "top_recall": hanawalt,
    }
    return (cand, PhaseMatchResult(phase=phase, score=float(score)))


class TestSiteElementSymbols:
    """位点元素提取：兼容 ``element`` 字段、``label`` 兜底、带后缀写法。"""

    def test_plain_elements(self):
        p = _phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"])
        assert _site_element_symbols(p) == {"Al", "O", "H"}

    def test_strips_numeric_suffix(self):
        """``H1`` / ``Fe0.86`` 这类写法要归一到 ``H`` / ``Fe``。"""
        p = Phase(formula="Fe H O2", elements={"Fe", "H", "O"},
                  atomic_sites=[{"label": "H1"}, {"label": "Fe0.86"},
                                {"label": "O2"}])
        assert _site_element_symbols(p) == {"H", "Fe", "O"}

    def test_empty_sites(self):
        assert _site_element_symbols(_phase("Al H3 O3", {"Al", "H", "O"}, [])) == set()


class TestMissingSiteElements:
    """缺元素判据：名义元素 - 实际位点元素。"""

    def test_hydrogen_missing_is_detected(self):
        """缺氢条目（formula 含 H、位点无 H）→ 缺 {H}。"""
        p = _phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"])
        assert _missing_site_elements(p) == {"H"}

    def test_complete_structure_returns_empty(self):
        p = _phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"])
        assert _missing_site_elements(p) == set()

    def test_empty_sites_are_not_judged(self):
        """位点未解析（空）→ 空集：不能把"读不到位点"当成"缺元素"。"""
        p = _phase("Al H3 O3", {"Al", "H", "O"}, [])
        assert _missing_site_elements(p) == set()

    def test_no_nominal_elements_are_not_judged(self):
        p = _phase("Al H3 O3", set(), ["Al", "O"])
        assert _missing_site_elements(p) == set()

    def test_non_hydrogen_missing_also_detected(self):
        """不止 H：名义有 Ti、位点没有，同样判不齐（通用判据）。"""
        p = _phase("Al Ti O3", {"Al", "Ti", "O"}, ["Al", "O"])
        assert _missing_site_elements(p) == {"Ti"}


class TestCollapseKeySpaceGroupNumber:
    """折叠键用国际表编号：替代设置同键、真多形体分立。"""

    def test_alternative_settings_share_key(self):
        # Pnma(62) 与 Pbnm(62) 是同一空间群的轴置换
        assert _cod_comp_key("Fe H O2", "P n m a", 62) == \
            _cod_comp_key("Fe H O2", "P b n m", 62)

    def test_cmcm_settings_share_key(self):
        # Cmcm / Bbmm / Amam 三种设置编号都是 63
        a = _cod_comp_key("Al H O2", "C m c m", 63)
        assert a == _cod_comp_key("Al H O2", "B b m m", 63)
        assert a == _cod_comp_key("Al H O2", "A m a m", 63)

    def test_polymorphs_stay_distinct(self):
        """真多形体编号不同（Kaolinite 2M = 9 vs 1T = 1）→ 不同键。"""
        assert _cod_comp_key("Al2 H4 O9 Si2", "C 1 c 1", 9) != \
            _cod_comp_key("Al2 H4 O9 Si2", "P 1", 1)

    def test_missing_number_falls_back_to_string(self):
        """编号缺失（用户库）→ 退回归一化字符串，行为与旧版一致。"""
        assert _cod_comp_key("Fe H O2", "P b n m", 0) != \
            _cod_comp_key("Fe H O2", "P n m a", 0)
        assert _cod_comp_key("Fe H O2", "P b n m", 0) == \
            _cod_comp_key("Fe H O2", "Pbnm", 0)

    def test_different_elements_never_merge(self):
        assert _cod_comp_key("Fe H O2", "P b n m", 62) != \
            _cod_comp_key("Co0.03 Fe0.97 H O2", "P b n m", 62)


class TestCollapsePrefersCompleteSites:
    """同键组内换代表：齐全优先，但有分数护栏。"""

    def test_missing_h_is_replaced_by_complete(self):
        """最优代表缺 H、组内第二名额齐全且分数够 → 代表换成齐全的。"""
        bad = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.60,
                    name="Gibbsite")
        good = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"]),
                     0.59, name="Gibbsite-H")
        out = _collapse_distinct([bad, good])
        assert len(out) == 1
        assert out[0][1].phase.name == "Gibbsite-H"

    def test_score_floor_blocks_too_weak_candidate(self):
        """齐全条目排序分远低于最优代表 → 不换（不能为完整度牺牲匹配质量）。

        注意 ``PhaseMatchResult.score`` 是 **FoM（越低越好）**，排序分
        ``cod_rank_score`` 再经 ``exp(-FoM/τ)`` 变换，所以"更弱"要写成
        **更大**的 FoM。此处代表 FoM=0.50、齐全候选 FoM=1.20，两者排序分
        相差约 49%（远超 1-0.95 的 5% 容差），护栏必须挡住。
        """
        bad = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.50,
                    name="Gibbsite")
        weak = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"]),
                     1.20, name="Gibbsite-H")
        out = _collapse_distinct([bad, weak])
        assert out[0][1].phase.name == "Gibbsite"

    def test_score_floor_boundary_just_inside(self):
        """刚好卡在护栏内侧的齐全候选仍然替换（避免护栏过严退化成本轮无效）。"""
        assert _COMPLETE_SITE_SCORE_FLOOR == pytest.approx(0.95)
        bad = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.60,
                    name="Gibbsite")
        # FoM 0.60→0.62：排序分差 ≈1.2%，落在 5% 容差内
        near = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"]),
                     0.62, name="Gibbsite-H")
        out = _collapse_distinct([bad, near])
        assert out[0][1].phase.name == "Gibbsite-H"

    def test_already_complete_is_untouched(self):
        good = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"]), 0.70)
        worse = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.69)
        out = _collapse_distinct([good, worse])
        assert out[0][1].phase.name == "X"

    def test_all_missing_keeps_best(self):
        a = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.70)
        b = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.65)
        out = _collapse_distinct([a, b])
        assert out[0][1].score == pytest.approx(0.70)

    def test_non_hydrogen_missing_also_prefers_complete(self):
        """不只 H：名义含 Ti、位点没有的条目，也会被齐全条目替换。"""
        bad = _item(_phase("Al Ti O3", {"Al", "Ti", "O"}, ["Al", "O"]), 0.60)
        good = _item(_phase("Al Ti O3", {"Al", "Ti", "O"}, ["Al", "O", "Ti"]), 0.59)
        out = _collapse_distinct([bad, good])
        assert _missing_site_elements(out[0][1].phase) == set()


class TestCollapseNonRegression:
    """换代表不得破坏既有"严格非回退"保证。"""

    def test_output_positions_and_order_unchanged(self):
        """三个不同键 + 一个缺 H 键：替换后输出顺序与键的数量都不变。"""
        a = _item(_phase("O Zn", {"O", "Zn"}, ["O", "Zn"]), 0.90,
                  formula="O Zn", sg="P 63 m c", sg_number=186, name="Zincite")
        bad = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.80,
                    name="Gibbsite")
        c = _item(_phase("C Ca O3", {"C", "Ca", "O"}, ["C", "Ca", "O"]), 0.70,
                  formula="C Ca O3", sg="R -3 c", sg_number=167, name="Calcite")
        good = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"]),
                     0.79, name="Gibbsite-H")
        out = _collapse_distinct([a, bad, c, good])
        assert [it[1].phase.name for it in out] == \
            ["Zincite", "Gibbsite-H", "Calcite"]

    def test_multiple_keys_each_keep_one(self):
        a1 = _item(_phase("Fe H O2", {"Fe", "H", "O"}, ["Fe", "O"]), 0.90,
                   sg="P b n m", sg_number=62, name="Goethite-old")
        a2 = _item(_phase("Fe H O2", {"Fe", "H", "O"}, ["Fe", "H", "O"]), 0.89,
                   sg="P n m a", sg_number=62, name="Goethite-H")
        b1 = _item(_phase("Al H O2", {"Al", "H", "O"}, ["Al", "O"]), 0.88,
                   sg="C m c m", sg_number=63, name="Boehmite-old")
        out = _collapse_distinct([a1, b1, a2])
        assert len(out) == 2
        # 两个键各自的第一代表：Goethite 换成齐全的，Boehmite 保持
        assert out[0][1].phase.name == "Goethite-H"
        assert out[1][1].phase.name == "Boehmite-old"

    def test_switch_off_restores_legacy_behavior(self, monkeypatch):
        """关掉开关 → 完全退回"每键留打分最优"，不换代表。"""
        import polyxrd.services.phase_identifier as m
        monkeypatch.setattr(m, "_COD_PREFER_COMPLETE_SITES", False)
        bad = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.60,
                    name="Gibbsite")
        good = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"]), 0.59,
                     name="Gibbsite-H")
        out = _collapse_distinct([bad, good])
        assert out[0][1].phase.name == "Gibbsite"

    def test_max_per_phase_gt_one_uses_legacy_path(self):
        """max_per_phase != 1 时保持旧行为（当前调用方都是默认 1）。"""
        bad = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O"]), 0.60,
                    name="Gibbsite")
        good = _item(_phase("Al H3 O3", {"Al", "H", "O"}, ["Al", "O", "H"]), 0.59,
                     name="Gibbsite-H")
        out = _collapse_distinct([bad, good], max_per_phase=2)
        assert [it[1].phase.name for it in out] == ["Gibbsite", "Gibbsite-H"]
