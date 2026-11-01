"""位点补齐（structure_augment）测试 —— v5.0.1

覆盖三件事：

1. **三道门**（化学式 / 空间群 / 晶胞）的判据边界：同分异构多形体、固溶体、
   晶胞走偏、空间群缺失，逐一确认"该拒的拒、该收的收"；
2. **不污染入参**：补齐返回新对象，入参相（检索结果）不被改写；
3. **失败不阻断**：库不可用 / 无匹配 / 位点展不开时原样返回，由引擎决定
   是否回退 —— 这条是"宁可不用新引擎，也不能用错结构"的落地形式。

用假库（``_FakeDB``）保持测试与 polyDB 挂载解耦；真库冒烟单独一条，未挂载
则 skip。
"""
from __future__ import annotations

import copy

import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.services import structure_augment as SA
from polyxrd.services.structure_augment import (
    SiteFill,
    fill_atomic_sites,
    normalize_space_group,
)


# ── 夹具：假库 ────────────────────────────────────────────────

class _FakeDB:
    """只实现 fill_atomic_sites 用到的三个方法。"""

    def __init__(self, entries: dict, sites: dict, ready: bool = True):
        self.entries = entries
        self.sites = sites
        self.ready = ready
        self.queries: list[str] = []

    def is_ready(self) -> bool:
        return self.ready

    def search_entries(self, query: str, limit: int = 20):
        self.queries.append(query)
        return list(self.entries.get(query, []))[:limit]

    def get_atomic_sites(self, eid: int):
        return [dict(s) for s in self.sites.get(int(eid), [])]

    def close(self) -> None:
        pass


def _row(eid, formula, mineral, sg, a, b, c, alpha=90.0, beta=90.0,
         gamma=90.0, n_peaks=20):
    return {"cod_id": eid, "formula": formula, "mineral_name": mineral,
            "space_group": sg, "cell_a": a, "cell_b": b, "cell_c": c,
            "cell_alpha": alpha, "cell_beta": beta, "cell_gamma": gamma,
            "n_peaks": n_peaks}


#: ZnO（P6₃mc，非对称单位 2 位点 → 全胞 4 位点）
ZNO_ROW = _row(9004179, "O Zn", "Zincite", "P 63 m c",
               3.2494, 3.2494, 5.2038, gamma=120.0)
ZNO_SITES = [
    {"label": "Zn", "element": "Zn", "x": 1 / 3, "y": 2 / 3, "z": 0.0,
     "occupancy": 1.0},
    {"label": "O", "element": "O", "x": 1 / 3, "y": 2 / 3, "z": 0.3819,
     "occupancy": 1.0},
]


def _zincite(**kw) -> Phase:
    """内置库形态：有参考峰 + 晶胞，**没有**原子位点。"""
    defaults = dict(name="Zincite", formula="ZnO", space_group="P63mc",
                    lattice=LatticeParams(a=3.2495, b=3.2495, c=5.2065,
                                          alpha=90.0, beta=90.0, gamma=120.0))
    defaults.update(kw)
    return Phase(**defaults)


# ── 空间群归一 ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("R -3 c :H", "r-3c"),
    ("R-3c", "r-3c"),
    ("P 63 m c", "p63mc"),
    ("P63mc", "p63mc"),
    ("F m -3 m", "fm-3m"),
    ("P 4/n m m :1", "p4/nmm"),
    ("", ""),
    (None, ""),
])
def test_normalize_space_group(raw, expected):
    assert normalize_space_group(raw) == expected


# ── 三道门 ────────────────────────────────────────────────────

def test_judge_accepts_identical_formula_sg_and_cell():
    how, dev, note = SA._judge(_zincite(), ZNO_ROW)
    assert how == "formula+sg+cell"
    assert dev < 0.01 and note == ""


def test_judge_rejects_space_group_mismatch():
    """同化学式不同多形体（立方 ZnO vs 六方 Zincite）必须拒。"""
    cubic = dict(ZNO_ROW, space_group="F m -3 m")
    assert SA._judge(_zincite(), cubic) is None


def test_judge_rejects_cell_outside_tolerance():
    """晶胞超 5%（固溶体/不同相）必须拒 —— 否则强度整体走形。"""
    off = dict(ZNO_ROW, cell_c=5.9)          # +13%
    assert SA._judge(_zincite(), off) is None


def test_judge_rejects_different_elements():
    other = dict(ZNO_ROW, formula="O Ti")     # 元素集不同
    assert SA._judge(_zincite(), other) is None


def test_judge_element_match_needs_tighter_cell_and_notes_composition():
    """元素集一致但配比不同（固溶体）：晶胞要更紧，且如实标注组成差异。"""
    solid = dict(ZNO_ROW, cod_id=2, formula="O Zn0.9 Co0.1",
                 cell_c=5.2038)
    # 配比不同 → 元素集也不同（多了 Co），先按元素集拒
    assert SA._judge(_zincite(), solid) is None

    # 真·元素相同配比不同：ZnO vs Zn2O2（同元素集）
    same_els = dict(ZNO_ROW, cod_id=3, formula="O2 Zn2")
    got = SA._judge(_zincite(), same_els)
    assert got is not None
    how, _dev, note = got
    assert how == "elements+sg+cell"
    assert "化学式不一致" in note

    # 同样情况但晶胞偏 3%（>2% 门槛）→ 拒
    loose = dict(same_els, cell_c=5.36)
    assert SA._judge(_zincite(), loose) is None


def test_judge_without_space_group_falls_back_to_cell_only():
    ph = _zincite(space_group="")
    how, _dev, note = SA._judge(ph, ZNO_ROW)
    assert how == "formula+cell"
    assert "空间群缺失" in note


# ── 补齐主流程 ────────────────────────────────────────────────

def test_fill_copies_expanded_sites_and_leaves_input_untouched():
    """补齐后位点必须是**全胞**（非对称单位 × 对称操作），且不改入参。"""
    ph = _zincite()
    before = copy.deepcopy(ph.atomic_sites)
    db = _FakeDB({"ZnO": [ZNO_ROW]}, {9004179: ZNO_SITES})

    out, fills = fill_atomic_sites([ph], db=db)

    assert len(fills) == 1
    fill = fills[0]
    assert isinstance(fill, SiteFill)
    assert fill.n_sites == 4                      # 2 位点 × 2 重对称
    assert "COD 9004179" in fill.source and "Zincite" in fill.source
    assert out[0] is not ph                       # 新对象
    assert len(out[0].atomic_sites) == 4
    assert ph.atomic_sites == before              # 入参未被改写
    assert out[0].lattice.a == pytest.approx(3.2495)   # 保留检索晶胞


def test_fill_skips_phase_that_already_has_sites():
    ph = _zincite(atomic_sites=[{"element": "Zn", "x": 0.0, "y": 0.0, "z": 0.0}])
    db = _FakeDB({"ZnO": [ZNO_ROW]}, {9004179: ZNO_SITES})
    out, fills = fill_atomic_sites([ph], db=db)
    assert out[0] is ph and fills == []
    assert db.queries == []                        # 一次库都没查


def test_fill_reports_miss_without_raising():
    ph = _zincite(name="Unobtainium", formula="Xx2O3")
    db = _FakeDB({}, {})
    out, fills = fill_atomic_sites([ph], db=db)
    assert out[0] is ph and fills == []


def test_fill_skips_candidate_whose_sites_cannot_be_expanded():
    """空间群认不出 → 展不开全胞 → 换下一个候选，绝不把非对称单位当全胞。"""
    ph = _zincite(space_group="", formula="ZnO")
    unexpandable = dict(ZNO_ROW, cod_id=11, space_group="Zz 9 q")
    good = dict(ZNO_ROW, cod_id=12)
    db = _FakeDB({"ZnO": [unexpandable, good]},
                 {11: ZNO_SITES, 12: ZNO_SITES})
    out, fills = fill_atomic_sites([ph], db=db)
    assert fills and fills[0].n_sites == 4
    assert "COD 12" in fills[0].source


def test_fill_noop_when_database_not_ready():
    ph = _zincite()
    db = _FakeDB({"ZnO": [ZNO_ROW]}, {9004179: ZNO_SITES}, ready=False)
    out, fills = fill_atomic_sites([ph], db=db, log_cb=lambda _m: None)
    assert out[0] is ph and fills == []
    assert db.queries == []


def test_fill_logs_sources():
    msgs: list[str] = []
    db = _FakeDB({"ZnO": [ZNO_ROW]}, {9004179: ZNO_SITES})
    fill_atomic_sites([_zincite()], db=db, log_cb=msgs.append)
    assert any("[cif]" in m and "补齐位点" in m and "9004179" in m for m in msgs)


def test_fill_queries_formula_before_name():
    """化学式优先（命中即停）—— 名字查询留给化学式打不中的相。"""
    db = _FakeDB({"ZnO": [ZNO_ROW]}, {9004179: ZNO_SITES})
    fill_atomic_sites([_zincite()], db=db)
    assert db.queries == ["ZnO"]


# ── 与 resolver 的接线 ───────────────────────────────────────

def test_resolver_augment_short_circuits_when_db_missing():
    """库不可用 → 一次探盘后置位，后续相不再反复查库。"""
    from polyxrd.services.phase_structure_resolver import PhaseStructureResolver

    r = PhaseStructureResolver()
    r._db = False                       # 模拟"库缺失/未挂载"
    ph = _zincite()
    out, fill = r._augment_sites(ph)
    assert out is ph and fill is None
    assert r._augment_off is True


# ── 真库冒烟（未挂载则跳过） ─────────────────────────────────

def test_real_polydb_fills_zincite():
    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase()
    if not db.is_ready():
        pytest.skip("polyDB 未挂载")
    out, fills = fill_atomic_sites([_zincite()], db=db)
    assert fills, "polyDB 里应当有 Zincite"
    assert len(out[0].atomic_sites) == 4
