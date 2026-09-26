"""S07 组合选择回归测试 (手册 v1) + S02/S04/S05 单元口径测试
=================================================================
- S02: 覆盖向量的强度加权语义 (弱强度峰贡献小)
- S04: pool_top_n 池裁剪只影响 B&B 池
- S05: 归一化成分分组键 (水合物/写法差异不再漏判同结构重复)
- S07: 2-1/4-1/5-1 真值命中回归 (依赖真库+真实数据; M-A 未收口前 skip,
  手册允许"新测试可先 skip, 但不得删除"—— 待 M-B (S08-S10) 收口后启用)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.services.phase_identifier import PhaseIdentifier

DATA_DIR = Path(r"E:\TEMP\test_xrd\txt")


def _mk_match(name, formula, tt_intens, score, elements):
    phase = Phase(
        name=name, formula=formula, elements=set(elements),
        reference_peaks=[((0, 0, 0), float(tt), float(it)) for tt, it in tt_intens],
    )
    return PhaseMatchResult(
        phase=phase, score=score,
        matched_peaks=len(tt_intens), total_peaks=len(tt_intens),
        confidence="test", method="fom",
    )


def _mk_peaks(tt_intens):
    from polyxrd.models.peak import Peak, PeakList
    return PeakList(peaks=[Peak(two_theta=float(tt), intensity=float(it))
                           for tt, it in tt_intens])


# ── S02: 覆盖向量 ────────────────────────────────────────────

class TestCoverVector:
    def setup_method(self):
        self.pi = PhaseIdentifier()

    def test_strong_peak_outranks_weak_noise(self):
        """同两条参考峰, 命中强峰的覆盖 > 命中弱噪声峰。"""
        ph = Phase(name="P", formula="PO", elements={"P", "O"},
                   reference_peaks=[((0, 0, 0), 30.0, 100.0)])
        v_strong = self.pi._phase_cover_vector(
            ph, [30.0, 60.0], [100.0, 5.0], 0.2)
        v_weak = self.pi._phase_cover_vector(
            ph, [30.0, 60.0], [5.0, 100.0], 0.2)
        assert v_strong[0] == pytest.approx(1.0)
        assert v_weak[0] == pytest.approx(0.05)
        assert v_strong.sum() > v_weak.sum()

    def test_zero_intensity_degenerates_to_boolean(self):
        """全 0 强度 → 等权 + 质量项 1 (接近旧布尔口径, 保证不崩)。"""
        ph = Phase(name="P", formula="PO", elements={"P", "O"},
                   reference_peaks=[((0, 0, 0), 30.0, 100.0)])
        v = self.pi._phase_cover_vector(ph, [30.0], [0.0, 0.0], 0.2)
        assert v[0] == pytest.approx(1.0)

    def test_bb_prefers_unique_explainer_with_intensity(self):
        """S02 端到端: 唯一解释强峰的相必须入选 (强度加权后仍成立)。"""
        matches = [
            _mk_match("Noise", "NX", [(30, 100), (40, 90)], 0.10, {"N", "X"}),
            _mk_match("A", "AO", [(30, 100), (40, 90)], 0.20, {"A", "O"}),
            _mk_match("B", "BO", [(30, 100), (50, 80)], 0.30, {"B", "O"}),
        ]
        peaks = _mk_peaks([(30, 100), (40, 90), (50, 80)])
        chosen = self.pi.build_refinement_combination(
            matches, expected_count=2, min_coverage=0.0, peaks=peaks)
        names = [p.name for p in chosen]
        assert "B" in names, names
        assert len(chosen) == 2


# ── S04: 池裁剪 ──────────────────────────────────────────────

class TestPoolPruning:
    def test_pool_top_n_blocks_low_rank_dense_phase(self):
        """pool_top_n=2 时, FoM 排名第 3 的密集相不得进入组合。"""
        matches = [
            _mk_match(f"P{i}", f"PO{i}", [(30 + i, 100.0)], 0.10 * (i + 1),
                      {f"E{i}", "O"})
            for i in range(5)
        ]
        peaks = _mk_peaks([(30 + i, 100.0) for i in range(5)])
        pi = PhaseIdentifier()
        chosen = pi.build_refinement_combination(
            matches, expected_count=1, min_coverage=0.0,
            peaks=peaks, pool_top_n=2)
        names = [p.name for p in chosen]
        assert len(chosen) == 1
        assert names[0] in ("P0", "P1"), names


# ── S05: 归一化成分分组键 ─────────────────────────────────────

class TestFormulaKeyDedupe:
    def setup_method(self):
        self.pi = PhaseIdentifier()

    def test_formula_key_normalizes_hydrate_variants(self):
        key1 = self.pi._formula_key("CaSO4.2H2O")
        key2 = self.pi._formula_key("CaSO4·2H2O")
        key3 = self.pi._formula_key("H4CaO6S")
        assert key1 == key2 == key3

    def test_formula_variant_same_structure_deduped(self):
        """写法不同但成分/结构相同的两条候选 → 只留 FoM 最优。"""
        m_good = _mk_match("GypA", "CaSO4.2H2O",
                           [(20.0, 100), (25.0, 60), (31.0, 40)], 0.10,
                           {"Ca", "S", "O", "H"})
        m_dup = _mk_match("GypB", "CaSO4·2H2O",
                          [(20.0, 100), (25.0, 60), (31.0, 40)], 0.50,
                          {"Ca", "S", "O", "H"})
        kept = self.pi._dedupe_results([m_good, m_dup])
        names = [r.phase.name for r in kept]
        assert names == ["GypA"], names


# ── S07: 真值命中回归 (真实库 + 真实数据; M-B 收口后启用) ──────

TRUTH_CASES = {
    "2-1": ["Zincite", "Calcite"],
    "4-1": ["Zincite", "Corundum", "Fluorite", "Brucite"],
    "5-1": ["α-Quartz", "Cristobalite", "Calcite", "Magnesite", "Dolomite"],
}


def _name_eq(a: str, b: str) -> bool:
    strip = lambda s: s.replace(" ", "").replace("-", "").lower()  # noqa: E731
    a2, b2 = strip(a or ""), strip(b or "")
    if not a2 or not b2:
        return False
    return a2 == b2 or a2 in b2 or b2 in a2


@pytest.mark.parametrize("sample", sorted(TRUTH_CASES))
@pytest.mark.skipif(not DATA_DIR.exists(),
                    reason="真实测试数据 E:/TEMP/test_xrd/txt 不存在")
@pytest.mark.skip(reason="M-A 未收口: 池内密集相挤占与检索 MISS 待 S08-S10 修复后启用 (手册 S07)")
def test_combination_contains_truth(sample):
    """组合结果必须包含真值相 (S01 映射表口径)。"""
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import default_peak_list

    truth = TRUTH_CASES[sample]
    data = DataLoader().load(DATA_DIR / f"{sample}.txt")
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = 1.5406
    pi = PhaseIdentifier()
    gpl = default_peak_list(data)
    matches = pi.identify_with_element_filter(
        data, peaks=gpl, element_filter=None, top_n=12, tolerance=0.2)
    combo = pi.build_refinement_combination(
        matches, expected_count=len(truth), min_coverage=0.3, peaks=gpl)
    combo_names = [p.name or "" for p in combo]
    for tw in truth:
        assert any(_name_eq(c, tw) for c in combo_names), \
            f"{sample}: 真值 {tw} 不在组合 {combo_names}"
