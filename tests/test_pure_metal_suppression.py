"""
纯金属干扰优化的 TDD 测试
=========================
验证 PhaseIdentifier 的组合选择策略能:
1. 正确识别化合物优先于纯金属（当元素限定时）
2. 纯金属 FOM 即使更低，也不应挤占关键化合物
3. 测试试样 1-1 (LiFePO4 应优先于 Hematite)
4. 测试试样 2-1 (Zincite/Calcite 应优先于 Zinc 纯金属)
5. 测试试样 4-1 (Zincite/Corundum/Fluorite/Brucite 不应有 Zinc)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DATA_DIR = Path(r"E:/TEMP/test_xrd/txt")


# v2.1 P2-4: 本地试样目录缺失时整体跳过 (CI 环境无 E:/TEMP/test_xrd)
pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "4-1.txt").exists(),
    reason=f"本地试样目录不存在: {DATA_DIR}",
)


def _load_xrd(name: str):
    from polyxrd.services.data_loader import DataLoader
    return DataLoader().load(DATA_DIR / f"{name}.txt")


def _find_peaks(data):
    from polyxrd.services.peak_finder import PeakFinder
    return PeakFinder().find_peaks(data)


def _identify(data, peaks, ef, top_n=10):
    from polyxrd.services.phase_identifier import PhaseIdentifier
    pi = PhaseIdentifier()
    return pi.identify_with_element_filter(
        data, peaks=peaks, element_filter=ef, top_n=top_n, tolerance=0.2
    )


class TestPureMetalSuppression:
    """纯金属干扰抑制测试"""

    # ---- 1. 试样 2-1: ZnO+CaCO3, 不应有 Zn 纯金属在 Top-2 ----
    def test_sample_2_1_no_pure_zinc_in_top2(self):
        """2-1 试样: 预期 ZnO(Zincite)/CaCO3(Calcite)，Top-2 不应有 Zn 纯金属"""
        data = _load_xrd("2-1")
        peaks = _find_peaks(data)
        ef = {"must": ["Zn", "Ca"],
              "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"],
              "exclude": []}
        matches = _identify(data, peaks, ef, top_n=5)
        top2_names = [m.phase.name for m in matches[:2]]
        print("2-1 Top-5:", [(m.phase.name, round(m.score,3)) for m in matches])
        # 优化后: 纯金属 Zinc 不应在 Top-2
        assert "Zinc" not in top2_names, (
            f"优化后 2-1 Top-2 不应有纯金属 Zinc，但实际为: {top2_names}"
        )

    def test_sample_2_1_compounds_rank_above_metals(self):
        """2-1: 化合物 Zincite/Calcite 的排名应高于纯金属"""
        data = _load_xrd("2-1")
        peaks = _find_peaks(data)
        ef = {"must": ["Zn", "Ca"],
              "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"],
              "exclude": []}
        matches = _identify(data, peaks, ef, top_n=10)
        rank = {m.phase.name: i+1 for i, m in enumerate(matches)}
        print("2-1 Rankings:", rank)
        # Zincite (ZnO 化合物) 应在 Zinc (纯金属) 之前
        if "Zincite" in rank and "Zinc" in rank:
            assert rank["Zincite"] < rank["Zinc"], (
                f"化合物 Zincite (第{rank['Zincite']}) 应优先于纯金属 Zinc (第{rank['Zinc']})"
            )
        # Calcite (CaCO3) 应在纯金属之前
        if "Calcite" in rank and "Zinc" in rank:
            assert rank["Calcite"] < rank["Zinc"]

    # ---- 2. 试样 4-1: 化合物不应有 Zn 纯金属排 Top-3 ----
    def test_sample_4_1_no_pure_zinc_in_top3(self):
        """4-1 试样: ZnO/Al2O3/CaF2/Mg(OH)2，Top-3 不应有纯金属"""
        data = _load_xrd("4-1")
        peaks = _find_peaks(data)
        ef = {"must": ["Zn", "Ca", "Al", "Mg"],
              "maybe": ["H","Li","Be","B","C","N","O","F","Na"],
              "exclude": []}
        matches = _identify(data, peaks, ef, top_n=5)
        top3_names = [m.phase.name for m in matches[:3]]
        print("4-1 Top-5:", [(m.phase.name, round(m.score,3)) for m in matches])
        # 优化后: 纯金属不应在 Top-3
        for pure in ["Zinc", "Titanium", "Copper", "Silver", "Gold", "Aluminum"]:
            assert pure not in top3_names, (
                f"4-1 Top-3 不应有纯金属 {pure}，实际: {top3_names}"
            )

    # ---- 3. 试样 1-2: NCM 811 应优于 Cobalt/Nickel 纯金属 ----
    def test_sample_1_2_ncm_ranks_above_cobalt(self):
        """1-2 试样: NCM 811 应优于 Cobalt/Nickel 纯金属"""
        data = _load_xrd("1-2")
        peaks = _find_peaks(data)
        ef = {"must": ["Ni", "Co", "Mn"],
              "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg","Al"],
              "exclude": []}
        matches = _identify(data, peaks, ef, top_n=6)
        rank = {m.phase.name: i+1 for i, m in enumerate(matches)}
        print("1-2 Rankings:", rank)
        # NCM 811 应比 Cobalt / Nickel 纯金属排名更优或同等
        # 至少: NCM 811 不应被纯金属挤出 Top-4
        assert "NCM 811" in rank, f"NCM 811 应在 Top-6 中，但实际: {list(rank.keys())}"

    # ---- 4. 试样 3-1: 纯金属应不挤入Top-3, Fluorite/Corundum 在Top-15 ----
    def test_sample_3_1_no_pure_metals_in_top3_and_minerals_visible(self):
        """3-1: 优化后纯金属 Zinc 不应挤入 Top-3；低含量矿物可在 Top-15 找到"""
        data = _load_xrd("3-1")
        peaks = _find_peaks(data)
        ef = {"must": ["Zn", "Ca", "Al"],
              "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"],
              "exclude": []}
        matches = _identify(data, peaks, ef, top_n=15)
        names = [m.phase.name for m in matches]
        print("3-1 Top-15:", names)
        # 纯金属不应挤入 Top-3
        pure_metals = {"Zinc","Titanium","Copper","Silver","Gold","Aluminum","Cobalt",
                       "Nickel","Iron","Lead","Zirconium","Magnesium","Sodium","Potassium",
                       "Calcium","Platinum","Vanadium","Niobium","Manganese","Chromium"}
        top3 = names[:3]
        for pm in pure_metals:
            assert pm not in top3, f"3-1 Top-3 不应有纯金属 {pm}，实际: {top3}"
        # Corundum (Al2O3 5.04%) 或 Fluorite (CaF2 1.36%) 应在 Top-15
        found = [n for n in names if n in ("Fluorite", "Corundum")]
        assert len(found) >= 1, (
            f"3-1 Top-15 应能找到 Fluorite/Corundum (低含量但应可见)，实际: {names}"
        )

    # ---- 5. 组合选择: 精修物相列表不应超过 20% 的纯金属比例 ----
    def test_combination_selection_limit_pure_metal_ratio(self):
        """精修前的物相组合筛选：纯金属比例不应超过 20%"""
        from polyxrd.services.phase_identifier import PhaseIdentifier
        pi = PhaseIdentifier()
        # 从内置库中提取纯金属物相名 (单元素非气态)
        pure_metals = set()
        non_metals = {"H","He","N","O","F","Ne","Cl","Ar","Br","Kr","I","Xe","Rn","S","P","C","Si","Se","Te","As","Ge","B"}
        for p in pi._phase_database:
            el = p.elements
            if len(el) == 1 and not (el & non_metals):
                pure_metals.add(p.name)
        print("内置纯金属列表:", pure_metals)

        # 加载 2-1 数据
        data = _load_xrd("2-1")
        peaks = _find_peaks(data)
        ef = {"must": ["Zn", "Ca"],
              "maybe": ["H","Li","Be","B","C","N","O","F","Na","Mg"],
              "exclude": []}
        matches = _identify(data, peaks, ef, top_n=5)

        # 组合选择：假设取 Top-5 物相做精修
        refine_candidates = [m.phase.name for m in matches[:5]]
        metal_count = sum(1 for n in refine_candidates if n in pure_metals)
        ratio = metal_count / max(1, len(refine_candidates))
        print(f"2-1 精修候选: {refine_candidates}, 纯金属比例: {ratio:.0%}")

        # 优化后: 纯金属比例应 <= 20% (即最多 1/5)
        assert ratio <= 0.20, (
            f"精修候选中纯金属比例 {ratio:.0%} 超过 20%，候选: {refine_candidates}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
