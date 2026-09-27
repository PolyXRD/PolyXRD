"""v2.2 S13 回归测试: 标记峰搜索 (marked-peaks only)
=====================================================
- marked_peak_indices 纯函数: 最近归属 / 窗口过滤 / 去重 / 空输入
- search_match 默认行为不变 (marked_peaks=None)
- 传 marked_peaks 时只用标记峰打分 (残差相追查场景)
- 标记无命中 → 空结果
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.phase import Phase
from polyxrd.services.foam import marked_peak_indices, search_match


def _phase(name, refs):
    return Phase(name=name, formula=name, elements=set(),
                 reference_peaks=refs)


class TestMarkedPeakIndices:
    def test_nearest_and_window(self):
        obs = [10.0, 20.0, 30.0]
        # 20.05 → 20; 29.8 → 30; 15.0 无峰 (窗口 0.3) → 忽略
        assert marked_peak_indices(obs, [20.05, 29.8, 15.0]) == [1, 2]

    def test_window_cutoff(self):
        obs = [10.0, 20.0]
        # 10.4 距 10 为 0.4 > 0.3 → 无命中
        assert marked_peak_indices(obs, [10.4]) == []
        # 放宽窗口到 0.5 → 命中 10
        assert marked_peak_indices(obs, [10.4], mark_tol=0.5) == [0]

    def test_dedup_and_sorted(self):
        obs = [10.0, 20.0]
        # 两个标记都归属到 20 → 去重; 下标升序
        assert marked_peak_indices(obs, [20.1, 19.95, 10.0]) == [0, 1]

    def test_empty_inputs(self):
        assert marked_peak_indices([], [10.0]) == []
        assert marked_peak_indices([10.0], []) == []


class TestSearchMatchMarked:
    @staticmethod
    def _db():
        return [
            _phase("Full", [((1,), 25.0, 100.0), ((2,), 30.0, 60.0),
                            ((3,), 40.0, 50.0)]),
            _phase("Residual", [((1,), 30.0, 100.0), ((2,), 40.0, 80.0)]),
        ]

    def test_default_unchanged(self):
        """marked_peaks=None 与不传 → 结果完全一致 (默认不变)。"""
        tt, ii = [25.0, 30.0, 40.0], [100.0, 60.0, 50.0]
        a = search_match(tt, ii, self._db())
        b = search_match(tt, ii, self._db(), marked_peaks=None)
        assert [(r.phase.name, r.score) for r in a] == \
               [(r.phase.name, r.score) for r in b]

    def test_marked_restricts_scoring(self):
        """只标记 25 → Residual 相 (参考峰 30/40) 全漏检, Full 相仍匹配。"""
        tt, ii = [25.0, 30.0, 40.0], [100.0, 60.0, 50.0]
        full_res = search_match(tt, ii, self._db())
        by_name_full = {r.phase.name: r for r in full_res}
        # 全峰口径下 Residual 两条参考线全命中
        assert by_name_full["Residual"].matched_peaks == 2

        marked_res = search_match(tt, ii, self._db(), marked_peaks=[25.0])
        by_name = {r.phase.name: r for r in marked_res}
        # 标记口径下 Residual 的 30/40 不在观测集 → matched=0, 分数变差
        assert by_name["Residual"].matched_peaks == 0
        assert by_name["Residual"].score > by_name_full["Residual"].score
        # Full 相主强线 25 仍命中 (matched ≥ 1)
        assert by_name["Full"].matched_peaks >= 1

    def test_no_hit_marks_empty_result(self):
        """标记位无任何实测峰在窗口内 → 空结果 (而非全峰打分)。"""
        res = search_match([25.0, 30.0], [100.0, 60.0], self._db(),
                           marked_peaks=[50.0])
        assert res == []

    def test_marks_outside_window_dropped(self):
        """部分标记无命中 → 只保留命中的标记 (不整体回退)。"""
        tt, ii = [25.0, 30.0], [100.0, 60.0]
        a = search_match(tt, ii, self._db(), marked_peaks=[30.0, 99.0])
        b = search_match(tt, ii, self._db(), marked_peaks=[30.0])
        assert [(r.phase.name, r.score) for r in a] == \
               [(r.phase.name, r.score) for r in b]
