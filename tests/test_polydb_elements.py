"""polyDB 元素表 / 元素位图的守卫测试。

背景（2026-10-29）：读取端 ``polydb.ELEMENTS`` 曾漏掉 **Rh（Z=45）**，
而建库端 ``tools/build_polydb.py`` 的表是完整的。``Z_OF`` 由
``enumerate(ELEMENTS)`` 生成，漏一个元素不会报错、也不会出现重复值，
只是 Rh 之后所有元素的下标整体前移一位 —— 于是查询端读的元素位图
平面错了一层：**查 W 拿到的是 Ta 的位图、查 Pb 拿到 Tl、查 U 拿到 Pa**。

这类错位不会抛异常，表现为「用 EDX 元素限定后检不出物相」或「给出
同族邻近元素的相」，只能靠 Z 值锚点断言抓。本文件就是那道防线。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.services.polydb import ELEMENTS, Z_OF  # noqa: E402

#: 跨周期挑锚点：漏元素造成的整体位移在任何一段都会暴露
_ANCHORS = {
    "H": 1, "He": 2, "C": 6, "N": 7, "O": 8, "Na": 11, "Al": 13, "Si": 14,
    "S": 16, "Cl": 17, "Ca": 20, "Ti": 22, "Cr": 24, "Fe": 26, "Ni": 28,
    "Zn": 30, "Br": 35, "Sr": 38, "Zr": 40, "Mo": 42, "Ru": 44,
    # ↓ Rh 是历史上漏掉的那个，必须单列
    "Rh": 45, "Pd": 46, "Ag": 47, "Sn": 50, "I": 53, "Xe": 54,
    "Cs": 55, "Ba": 56, "La": 57, "Nd": 60, "Gd": 64, "Lu": 71,
    "Hf": 72, "Ta": 73, "W": 74, "Re": 75, "Ir": 77, "Pt": 78, "Au": 79,
    "Hg": 80, "Tl": 81, "Pb": 82, "Bi": 83, "Th": 90, "U": 92,
}


class TestElementTable:
    def test_length_is_118(self):
        assert len(ELEMENTS) == 118

    def test_no_duplicates(self):
        assert len(set(ELEMENTS)) == len(ELEMENTS)

    @pytest.mark.parametrize("symbol,z", sorted(_ANCHORS.items(), key=lambda kv: kv[1]))
    def test_anchor_atomic_numbers(self, symbol: str, z: int):
        """每个锚点的 Z 必须精确 —— 漏一个元素就会整体偏移。"""
        assert Z_OF.get(symbol) == z, (
            f"{symbol} 的原子序数应为 {z}，实际 {Z_OF.get(symbol)}"
            "（检查 ELEMENTS 是否漏元素导致整体错位）"
        )

    def test_z_covers_1_to_118(self):
        assert sorted(Z_OF.values()) == list(range(1, 119))

    def test_rh_present(self):
        """Rh 曾被漏掉：它的缺席会让 Rh 之后全部错位一位。"""
        assert "Rh" in ELEMENTS
        assert ELEMENTS.index("Rh") == 44  # 0-based → Z=45


# ── 位图语义（需要真实 polyDB，缺库时跳过）──────────────────────

_POLYDB = Path(r"D:\Project\XRD\PolyXRD-DataBase\polydb\COD-Inorg-20261021.polyDB")


def _has_db() -> bool:
    return (_POLYDB / "meta.json").is_file()


@pytest.fixture(scope="module")
def inorg_db():
    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase(_POLYDB, variant="cod-inorg")
    assert db.is_ready()
    return db


@pytest.mark.skipif(not _has_db(), reason="本机无 COD-Inorg polyDB，跳过位图语义测试")
class TestElementMask:
    def _in_mask(self, db, eid: int, pool: list[str]) -> bool:
        mask = db._element_mask(pool)
        row = db._get_conn().execute(
            "SELECT row_idx FROM entries WHERE eid = ?", (eid,)).fetchone()
        assert row is not None
        return bool(mask[int(row[0])])

    def test_wo3_passes_w_o_pool(self, inorg_db):
        """WO3 必须落在 {W,O} 允许池内 —— 元素表错位时这里会是 False。"""
        assert self._in_mask(inorg_db, 1528915, ["W", "O"]) is True

    def test_w18o49_passes_w_o_pool(self, inorg_db):
        assert self._in_mask(inorg_db, 1001678, ["W", "O"]) is True

    def test_ta_phase_rejected_by_w_pool(self, inorg_db):
        """含 Ta 的相不能被 {W} 池放行（旧错位下 Ta 正是"W"位平面）。"""
        row = inorg_db._get_conn().execute(
            "SELECT eid FROM entries WHERE formula LIKE '%Ta%' "
            "AND formula NOT LIKE '%W%' LIMIT 1").fetchone()
        if row is None:
            pytest.skip("库内找不到只含 Ta 不含 W 的相")
        assert self._in_mask(inorg_db, int(row[0]), ["W"]) is False

    def test_mask_not_empty_sanity(self, inorg_db):
        """允许池越大命中越多（⊆ 语义的自洽检查）。"""
        n_w = int(inorg_db._element_mask(["W"]).sum())
        n_wo = int(inorg_db._element_mask(["W", "O"]).sum())
        assert 0 < n_w < n_wo < inorg_db.stats().phases


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
