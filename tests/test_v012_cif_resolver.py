"""v0.12 精修前置 CIF 自动匹配 (phase_structure_resolver) 单元测试
================================================================

不依赖真实 COD 库 —— 用 stub db 模拟 `find_structure_candidates` /
`get_phase` / `get_cif`, 验证解析、排序、合并、缓存与回退语义。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.services.phase_structure_resolver import (
    PhaseStructureResolver,
    extract_cod_id,
    normalize_cod_formula,
)


# ── 化学式规范化 ──────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Mg(OH)2", "H2 Mg O2"),
        ("CaCO3", "C Ca O3"),
        ("Al2O3", "Al2 O3"),
        ("SiO2", "O2 Si"),
        ("KAl2Si3O10(OH)2", "Al2 H2 K O12 Si3"),
        # COD 库格式输入 → 幂等
        ("H2 Mg O2", "H2 Mg O2"),
        ("O2 Si", "O2 Si"),
        ("", ""),
        (None, ""),
        ("###", ""),
    ],
)
def test_normalize_cod_formula(raw, want):
    assert normalize_cod_formula(raw) == want


def test_normalize_cod_formula_float_counts():
    assert normalize_cod_formula("Fe0.9O") == "Fe0.9 O"


# ── COD 编号提取 ─────────────────────────────────────────────

def test_extract_cod_id_from_name():
    assert extract_cod_id("H2 Mg O2 (COD 1000054)") == 1000054
    assert extract_cod_id("Al2 O3 COD:9002348") == 9002348
    assert extract_cod_id("Brucite", "Mg(OH)2") is None
    assert extract_cod_id(None) is None


# ── stub 库 ──────────────────────────────────────────────────

def _cif_phase(cod_id=1000054, formula="H2 Mg O2", sg="P -3 m 1",
               a=3.142, c=4.766, n_sites=3, with_peaks=True):
    p = Phase(
        name=f"COD_{cod_id}",
        formula=formula,
        space_group=sg,
        lattice=LatticeParams(a=a, b=a, c=c, alpha=90, beta=90, gamma=120),
        atomic_sites=[
            {"label": "Mg1", "element": "Mg", "x": 0.0, "y": 0.0,
             "z": 0.0, "occupancy": 1.0},
        ][: max(1, n_sites - 1)] + [
            {"label": "O1", "element": "O", "x": 0.667, "y": 0.333,
             "z": 0.222, "occupancy": 1.0},
        ],
        cif_path=None,
    )
    if with_peaks:
        p.reference_peaks = [((0, 0, 1), 18.67, 100.0), ((1, 0, 1), 33.0, 30.0)]
    return p


class StubDB:
    """模拟 CODLocalDatabase 的最小接口。"""

    def __init__(self, candidates=None, cif_phase=None, fail_ids=(),
                 phases_by_id=None):
        self.candidates = candidates or []
        self.cif_phase = cif_phase
        self.fail_ids = set(fail_ids)
        self.phases_by_id = phases_by_id or {}
        self.candidates_calls: list[tuple] = []
        self.get_phase_calls: list[int] = []
        self.cif_text_calls: list[int] = []

    def find_structure_candidates(self, formula_norm, mineral_name="", limit=24):
        self.candidates_calls.append((formula_norm, mineral_name))
        return list(self.candidates)

    def get_phase(self, cod_id, **kwargs):
        self.get_phase_calls.append(cod_id)
        if cod_id in self.fail_ids:
            return None
        p = self.phases_by_id.get(cod_id, self.cif_phase)
        if p is not None and p.cif_path is None:
            import copy

            p = copy.deepcopy(p)
        return p

    def get_cif(self, cod_id):
        self.cif_text_calls.append(cod_id)
        return "data_global\n_cell_length_a 3.14\n"


@pytest.fixture()
def structured_target(tmp_path):
    """已带结构的物相 (cif 文件真实存在)。"""
    cif = tmp_path / "existing.cif"
    cif.write_text("data_test\n", encoding="utf-8")
    phase = Phase(
        name="Quartz", formula="SiO2",
        lattice=LatticeParams(a=4.91, b=4.91, c=5.40),
        atomic_sites=[{"label": "Si1", "element": "Si", "x": 0.0,
                       "y": 0.0, "z": 0.0, "occupancy": 1.0}],
        cif_path=str(cif),
    )
    return phase, cif


# ── resolve 语义 ─────────────────────────────────────────────

def test_resolve_skips_already_structured(structured_target):
    phase, cif = structured_target
    db = StubDB()
    out = PhaseStructureResolver(db).resolve([phase])
    assert out[0] is phase  # 原对象, 未复制
    assert db.candidates_calls == []  # 根本没查库


def test_resolve_merges_cif_structure_keeps_identity():
    target = Phase(
        name="Brucite", formula="Mg(OH)2", space_group="P-3m1",
        lattice=LatticeParams(a=3.125, b=3.125, c=4.766, alpha=90,
                              beta=90, gamma=120),
        reference_peaks=[((0, 0, 1), 18.9, 100.0)],
        match_score=0.42, weight_fraction=0.0,
        elements={"Mg", "O", "H"},
    )
    db = StubDB(
        candidates=[{
            "cod_id": 1010484, "formula": "H2 Mg O2",
            "space_group": "P -3 m 1", "a": 3.13, "b": 3.13, "c": 4.75,
            "alpha": 90.0, "beta": 90.0, "gamma": 120.0,
            "has_cif": True, "mineral_name": "",
        }],
        cif_phase=_cif_phase(cod_id=1010484, a=3.13, c=4.75),
    )
    logs: list[str] = []
    out = PhaseStructureResolver(db).resolve(
        [target], wavelength=1.5406, two_theta_range=(5.0, 140.0),
        log_cb=logs.append,
    )
    p = out[0]
    # 身份沿用原相
    assert (p.name, p.formula, p.match_score) == ("Brucite", "Mg(OH)2", 0.42)
    assert p.space_group == "P-3m1"  # 原相已有 → 不被 CIF 覆盖
    # 结构来自 CIF
    assert p.cif_path and Path(p.cif_path).name == "COD1010484.cif"
    assert len(p.atomic_sites) == 2
    assert p.lattice.a == pytest.approx(3.13)
    # 参考峰优先用 CIF 模拟峰
    assert p.reference_peaks[0][1] == pytest.approx(18.67)
    # 原对象未被修改
    assert target.cif_path is None and target.atomic_sites == []
    # 日志
    assert any("[cif]" in l and "1010484" in l for l in logs)
    assert any("1/1" in l for l in logs)


def test_resolve_prefers_closer_cell_and_matching_sg():
    """空间群一致 + 晶胞更近的候选排在前面被选中。"""
    target = Phase(
        name="X", formula="AB O3", space_group="P m -3 m",
        lattice=LatticeParams(a=3.905, b=3.905, c=3.905),
        elements={"A", "B", "O"},
    )
    near = {"cod_id": 111, "formula": "A B O3", "space_group": "P m -3 m",
            "a": 3.910, "b": 3.910, "c": 3.910, "alpha": 90.0, "beta": 90.0,
            "gamma": 90.0, "has_cif": True, "mineral_name": ""}
    far = {"cod_id": 222, "formula": "A B O3", "space_group": "R -3 c",
           "a": 5.5, "b": 5.5, "c": 13.0, "alpha": 90.0, "beta": 90.0,
           "gamma": 120.0, "has_cif": True, "mineral_name": ""}
    dirty = {"cod_id": 333, "formula": "A B O3", "space_group": "P m -3 m",
             "a": None, "b": 5.5e-313, "c": 3.9, "alpha": None, "beta": 90.0,
             "gamma": 90.0, "has_cif": True, "mineral_name": ""}
    db = StubDB(
        candidates=[far, dirty, near],  # 故意乱序
        cif_phase=_cif_phase(cod_id=111, formula="A B O3",
                             sg="P m -3 m", a=3.91, c=3.91),
    )
    out = PhaseStructureResolver(db).resolve([target])
    # v0.15.2: 择优语义 —— 允许依次加载多个候选做模拟峰失配甄别,
    # 但最终必须选中"空间群一致 + 晶胞更近"的最优候选 111
    assert 111 in db.get_phase_calls
    assert out[0].cif_path and "COD111" in out[0].cif_path


def test_resolve_discriminates_polymorphs_by_peak_positions():
    """v0.15.2 多形体甄别: 模拟峰位置失配参与择优。

    场景 (源自 2-1 实测): 文石型 Pmcn CaCO3 晶胞更接近原相、按旧排序
    排第一, 但其模拟峰 (主峰 ~23.5°) 与库内方解石 d-I 峰 (104 主峰
    29.4°) 完全对不上; R-3c 真方解石模拟峰与库峰一致 → 必须选它。
    """
    target = Phase(
        name="Calcite", formula="C Ca O3", space_group="",
        lattice=LatticeParams(a=4.99, b=4.99, c=17.06, alpha=90,
                              beta=90, gamma=120),
        reference_peaks=[((1, 0, 4), 29.4, 100.0), ((0, 1, 2), 23.0, 27.0),
                         ((1, 1, 3), 39.4, 18.0)],
        elements={"C", "Ca", "O"},
    )
    aragonite_like = {
        "cod_id": 9016071, "formula": "C Ca O3", "space_group": "P m c n",
        "a": 4.988, "b": 4.985, "c": 17.05, "alpha": 90.0, "beta": 90.0,
        "gamma": 120.0, "has_cif": True, "mineral_name": "",
    }
    calcite_like = {
        "cod_id": 9016706, "formula": "C Ca O3", "space_group": "R -3 c",
        "a": 4.984, "b": 4.984, "c": 17.04, "alpha": 90.0, "beta": 90.0,
        "gamma": 120.0, "has_cif": True, "mineral_name": "",
    }

    def _mk(cod_id, peaks):
        p = Phase(name=f"COD_{cod_id}", formula="C Ca O3",
                  space_group="P m c n" if cod_id == 9016071 else "R -3 c",
                  lattice=LatticeParams(a=4.98, b=4.98, c=17.0),
                  atomic_sites=[{"label": "Ca1", "element": "Ca",
                                 "x": 0.0, "y": 0.0, "z": 0.0,
                                 "occupancy": 1.0}],
                  elements={"C", "Ca", "O"})
        p.reference_peaks = peaks
        return p

    db = StubDB(
        candidates=[aragonite_like, calcite_like],  # 旧排序: 文石在前 (晶胞略近)
        phases_by_id={
            # 文石型: 主峰 23.5°, 29.4° 无峰 → 失配大
            9016071: _mk(9016071, [((1, 1, 1), 23.45, 100.0),
                                   ((0, 2, 1), 26.0, 60.0),
                                   ((1, 2, 1), 27.9, 50.0)]),
            # 方解石型: 104 主峰 29.4° → 失配 ≈ 0
            9016706: _mk(9016706, [((1, 0, 4), 29.44, 100.0),
                                   ((0, 0, 6), 23.05, 25.0),
                                   ((1, 1, 3), 39.42, 20.0)]),
        },
    )
    out = PhaseStructureResolver(db).resolve([target])
    assert "COD9016706" in (out[0].cif_path or ""), (
        f"应选中方解石型结构, 实际: {out[0].cif_path}"
    )
    # 峰表换成方解石型模拟峰 (104 主峰在场)
    assert any(abs(t - 29.44) < 0.05 for _, t, i in out[0].reference_peaks)


def test_resolve_falls_back_gracefully_when_no_hit():
    target = Phase(
        name="Unknownite", formula="Zz9 Q2",
        lattice=LatticeParams(a=3.0, b=3.0, c=3.0),
        reference_peaks=[((0, 0, 1), 20.0, 100.0)],
    )
    db = StubDB(candidates=[], cif_phase=None)
    logs: list[str] = []
    out = PhaseStructureResolver(db).resolve([target], log_cb=logs.append)
    assert out[0] is target  # 原样保留, 不阻断
    assert any("未找到可用 CIF" in l for l in logs)


def test_resolve_tries_next_candidate_when_load_fails():
    target = Phase(name="Y", formula="A B", elements={"A", "B"},
                   lattice=LatticeParams(a=3.0, b=3.0, c=3.0))
    c1 = {"cod_id": 1, "formula": "A B", "space_group": "P 1",
          "a": 3.0, "b": 3.0, "c": 3.0, "alpha": 90.0, "beta": 90.0,
          "gamma": 90.0, "has_cif": True, "mineral_name": ""}
    c2 = dict(c1, cod_id=2)
    db = StubDB(candidates=[c1, c2], cif_phase=_cif_phase(cod_id=2),
                fail_ids={1})
    out = PhaseStructureResolver(db).resolve([target])
    assert db.get_phase_calls == [1, 2]
    assert "COD2" in (out[0].cif_path or "")


def test_resolve_uses_cod_id_from_name_directly():
    target = Phase(name="O2 Si (COD 1000054)", formula="O2 Si")
    db = StubDB()  # 候选列表为空也无所谓 —— 编号直取
    db.cif_phase = _cif_phase(cod_id=1000054)
    out = PhaseStructureResolver(db).resolve([target])
    assert db.get_phase_calls == [1000054]
    assert db.candidates_calls == []
    assert out[0].name == "O2 Si (COD 1000054)"  # 名字沿用


def test_resolver_caches_second_lookup():
    target = Phase(
        name="Brucite", formula="Mg(OH)2",
        lattice=LatticeParams(a=3.125, b=3.125, c=4.766),
        elements={"Mg", "O", "H"},
    )
    db = StubDB(
        candidates=[{"cod_id": 1010484, "formula": "H2 Mg O2",
                     "space_group": "P -3 m 1", "a": 3.13, "b": 3.13,
                     "c": 4.75, "alpha": 90.0, "beta": 90.0, "gamma": 120.0,
                     "has_cif": True, "mineral_name": ""}],
        cif_phase=_cif_phase(cod_id=1010484),
    )
    r = PhaseStructureResolver(db)
    out1 = r.resolve([target])
    out2 = r.resolve([target])
    assert db.candidates_calls and len(db.candidates_calls) == 1  # 第二次走缓存
    assert out2[0] is out1[0]


def test_resolver_without_db_returns_original():
    target = Phase(name="Z", formula="SiO2")
    r = PhaseStructureResolver(cod_db=None)
    # 让 _get_db 探测失败 (真实环境无库时 CODLocalDatabase.is_ready()=False)
    r._db_ready = False
    logs: list[str] = []
    out = r.resolve([target], log_cb=logs.append)
    assert out[0] is target
    assert any("COD 库不可用" in l for l in logs)


def test_merge_does_not_mutate_inputs():
    target = Phase(name="B", formula="Mg(OH)2",
                   lattice=LatticeParams(a=3.125, b=3.125, c=4.766))
    cif = _cif_phase(cod_id=1010484)
    cif_sites_snapshot = [dict(s) for s in cif.atomic_sites]
    merged = PhaseStructureResolver._merge(target, cif, 1010484)
    merged.atomic_sites.append({"label": "X", "element": "X",
                                "x": 0, "y": 0, "z": 0, "occupancy": 1})
    assert len(cif.atomic_sites) == len(cif_sites_snapshot)
    assert target.atomic_sites == []
