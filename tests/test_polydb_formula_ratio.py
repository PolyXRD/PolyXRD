# -*- coding: utf-8 -*-
"""P2-4 守卫：化学式**配比**检索（整数写法 ↔ 小数下标写法）。

背景：COD 对同一个相并存两种记法 —— 整数配比 ``O49 W18`` 与小数下标
``O2.9 W`` / ``O2.72 W``。用户与现场记录按整数写（``W20O58``、``W18O49``），
``normalize_cod_formula`` 只做元素排序与去空格，字符串仍然不等 → 检索
返回 0 条。P2-4 因此被误判成"W20O58 无标准卡"。实际 COD 1538317
（``O2.9 W``, P2/m, a=12.10 b=3.78 c=23.40 β=95, V=1066.2）就是 W20O58。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.services.polydb import PolyDatabase  # noqa: E402

REAL_DB = Path(
    r"D:\Project\XRD\PolyXRD-DataBase\polydb\COD-Inorg-20261021.polyDB")


@pytest.mark.parametrize("formula,expected", [
    ("W20O58", (("O", 2.9), ("W", 1.0))),
    ("O58 W20", (("O", 2.9), ("W", 1.0))),
    ("O2.9 W", (("O", 2.9), ("W", 1.0))),
    ("W18O49", (("O", 2.722), ("W", 1.0))),
    ("O2.72 W", (("O", 2.72), ("W", 1.0))),
    ("WO3", (("O", 3.0), ("W", 1.0))),
    ("W5O14", (("O", 2.8), ("W", 1.0))),
])
def test_ratio_key_normalizes_notation(formula, expected):
    assert PolyDatabase._formula_ratio_key(formula) == expected


@pytest.mark.parametrize("bad", ["", "   ", "W", "not a formula", None])
def test_ratio_key_rejects_unparsable(bad):
    assert PolyDatabase._formula_ratio_key(bad) is None


def test_ratio_equal_tolerates_decimal_rounding():
    k = PolyDatabase._formula_ratio_key
    # 49/18 = 2.7222…（写成 2.722）vs 库里的 2.72：同一相，必须等价
    assert PolyDatabase._ratio_equal(k("W18O49"), k("O2.72 W"))
    # 2.9 vs 3.0 是不同相（W20O58 vs WO3），不得混淆
    assert not PolyDatabase._ratio_equal(k("W20O58"), k("WO3"))
    # 元素集不同 → 不等价（Fe2O3 与 W20O58 长度相同但元素不同）
    assert not PolyDatabase._ratio_equal(k("Fe2O3"), k("WO3"))


@pytest.mark.skipif(not REAL_DB.is_dir(), reason="本机无实测 polyDB 库")
class TestRealLibrary:
    def test_w20o58_resolves_to_o29w(self):
        db = PolyDatabase(str(REAL_DB))
        for q in ("W20O58", "O58 W20", "O2.9 W"):
            ids = [r["cod_id"] for r in db.search_entries(q, limit=5)]
            assert 1538317 in ids, f"{q} 应命中 COD 1538317（O2.9 W）"
            row = db.get_phase(1538317)
            assert row["formula"] == "O2.9 W"
            assert abs(row["cell_a"] - 12.1) < 1e-6
            assert abs(row["cell_c"] - 23.4) < 1e-6

    def test_w18o49_returns_both_notations(self):
        """三份 W18O49 卡片（两份整数记法 + 一份 O2.72 W）都该出现。"""
        db = PolyDatabase(str(REAL_DB))
        ids = {r["cod_id"] for r in db.search_entries("W18O49", limit=8)}
        assert {1001678, 1528166, 1538315} <= ids

    def test_w5o14_resolves(self):
        db = PolyDatabase(str(REAL_DB))
        ids = {r["cod_id"] for r in db.search_entries("W5O14", limit=5)}
        assert 1527783 in ids

    def test_plain_formulas_keep_exact_hits_first(self):
        """既有查询（SiO2/Al2O3）的首条仍是精确归一化命中，顺序不变。"""
        db = PolyDatabase(str(REAL_DB))
        for q, expect in (("SiO2", "O2 Si"), ("Al2O3", "Al2 O3"),
                          ("WO3", "O3 W")):
            rows = db.search_entries(q, limit=5)
            assert rows, q
            assert rows[0]["formula"] == expect, q

    def test_id_and_text_queries_unaffected(self):
        db = PolyDatabase(str(REAL_DB))
        assert [r["cod_id"] for r in db.search_entries("1011097", limit=3)] \
            == [1011097]
        assert db.search_entries("quartz", limit=3)
