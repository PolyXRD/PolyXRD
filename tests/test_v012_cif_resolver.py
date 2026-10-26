"""精修前置 CIF 结构补齐 (phase_structure_resolver) 单元测试
==========================================================

v4.2 起解析器只剩两条路：
  1. 相已带 ``atomic_sites`` + 磁盘 ``cif_path`` → 原样保留；
  2. 相有位点但无 CIF 文件 → 由位点反生成 CIF 落盘并回填 ``cif_path``
     （polyDB / PDF2 / 用户库候选的典型形态，v4.1.1 引入）；
  3. 都不满足 → 原样返回，以参考峰剖面参与 builtin 精修。

旧的"按 COD 编号/化学式去 COD 本地 sqlite 找候选"分支已在 v4.2 删除
（约 250 行，含多形体甄别与 BLOB 落盘），相应 stub 库用例一并移除。
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


@pytest.fixture(autouse=True)
def _isolated_cif_cache(tmp_path, monkeypatch):
    """CIF 落盘缓存隔离到 tmp_path。

    解析器把反生成的 CIF 写到 ``cif_cache_dir()``；测试写真实用户目录既不
    卫生，在只读用户目录 / 受控文件夹环境下还会抛 PermissionError。这里把
    它指到 tmp_path。
    """
    from polyxrd.config import get_config

    cache = tmp_path / "cif_cache"
    monkeypatch.setattr(get_config(), "cif_cache_dir", lambda: cache)
    return cache


# ── 化学式规范化（纯函数，保留） ──────────────────────────────

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


# ── COD 编号提取（供 CIF 导出/向导识别 "USER-"/"COD" 前缀） ──

def test_extract_cod_id_from_name():
    assert extract_cod_id("H2 Mg O2 (COD 1000054)") == 1000054
    assert extract_cod_id("Al2 O3 COD:9002348") == 9002348
    assert extract_cod_id("Brucite", "Mg(OH)2") is None
    assert extract_cod_id(None) is None


# ── 路径 1: 已带结构 → 原样保留 ──────────────────────────────

@pytest.fixture()
def structured_phase(tmp_path):
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


def test_resolve_skips_already_structured(structured_phase):
    phase, _cif = structured_phase
    logs: list[str] = []
    out = PhaseStructureResolver().resolve([phase], log_cb=logs.append)
    assert out[0] is phase  # 原对象, 未复制
    assert any("已有结构" in ln and "existing.cif" in ln for ln in logs)
    assert any("structure match: 0/1" in ln for ln in logs)  # 不计入"补齐"


# ── 路径 2: 有位点无 CIF → 反生成落盘（v4.1.1 主路径） ────────

def _poly_phase(name="ZnO", db_id=None):
    return Phase(
        name=name, formula="ZnO",
        lattice=LatticeParams(a=3.2498, b=3.2498, c=5.2066,
                              alpha=90, beta=90, gamma=120),
        atomic_sites=[
            {"label": "Zn1", "element": "Zn", "x": 0.0, "y": 0.0,
             "z": 0.0, "occupancy": 1.0},
            {"label": "O1", "element": "O", "x": 0.0, "y": 0.0,
             "z": 0.3819, "occupancy": 1.0},
        ],
        db_id=db_id,
    )


def test_resolve_synthesizes_cif_from_sites(_isolated_cif_cache):
    """polyDB/用户库候选：晶胞 + 全胞位点、无 CIF 文件 → 落盘并回填。"""
    phase = _poly_phase()
    logs: list[str] = []
    out = PhaseStructureResolver().resolve([phase], log_cb=logs.append)

    got = out[0]
    assert got is not phase, "应返回回填了 cif_path 的副本"
    assert got.cif_path and Path(got.cif_path).exists()
    assert Path(got.cif_path).parent == _isolated_cif_cache
    text = Path(got.cif_path).read_text(encoding="utf-8")
    assert "_cell_length_a" in text and "3.2498" in text
    # 身份字段不变
    assert (got.name, got.formula) == ("ZnO", "ZnO")
    assert got.lattice.a == pytest.approx(3.2498)
    assert len(got.atomic_sites) == len(phase.atomic_sites)
    # 入参未被就地修改
    assert phase.cif_path is None
    # 日志：命中并计入 1/1
    assert any("由原子位点生成 CIF" in ln for ln in logs)
    assert any("1/1" in ln for ln in logs)


def test_synthesized_stem_uses_db_id(_isolated_cif_cache):
    """带 db_id 的相 → 文件名 COD<id>.cif（便于人工对应回库条目）。"""
    out = PhaseStructureResolver().resolve([_poly_phase(db_id=1234567)])
    assert Path(out[0].cif_path).name == "COD1234567.cif"


def test_synthesized_stem_hashes_name_without_db_id(_isolated_cif_cache):
    out = PhaseStructureResolver().resolve([_poly_phase(name="Some Unknownite")])
    assert Path(out[0].cif_path).name.startswith("PHASE-")


def test_synthesize_is_idempotent(_isolated_cif_cache):
    """同一相解析两遍：第二遍直接命中"已有结构"分支，不重复写盘。"""
    r = PhaseStructureResolver()
    first = r.resolve([_poly_phase()])[0]
    mtime = Path(first.cif_path).stat().st_mtime_ns
    second = r.resolve([first])[0]
    assert second is first
    assert Path(first.cif_path).stat().st_mtime_ns == mtime


# ── 路径 3: 无位点无 CIF → 原样返回，不阻断 ──────────────────

def test_resolve_returns_original_without_sites():
    target = Phase(
        name="Unknownite", formula="Zz9 Q2",
        lattice=LatticeParams(a=3.0, b=3.0, c=3.0),
        reference_peaks=[((0, 0, 1), 20.0, 100.0)],
    )
    logs: list[str] = []
    out = PhaseStructureResolver().resolve([target], log_cb=logs.append)
    assert out[0] is target  # 原样保留, 不阻断
    assert any("无可用 CIF" in ln for ln in logs)
    assert any("0/1" in ln for ln in logs)


def test_resolver_caches_second_lookup():
    """无位点的相同 (name, formula) 第二次走缓存，不重复生成。"""
    r = PhaseStructureResolver()
    a = Phase(name="Z", formula="SiO2")
    first = r.resolve([a])[0]
    logs: list[str] = []
    b = Phase(name="Z", formula="SiO2")  # 不同实例, 同 key
    second = r.resolve([b], log_cb=logs.append)[0]
    assert first is a and second is a  # 命中缓存里的第一个对象
    assert any("命中缓存" in ln for ln in logs)


def test_resolve_keeps_order_and_length():
    phases = [_poly_phase("A"), Phase(name="B", formula="Q"),
              _poly_phase("C")]
    out = PhaseStructureResolver().resolve(phases)
    assert len(out) == 3
    assert [p.name for p in out] == ["A", "B", "C"]


def test_resolve_empty_list():
    assert PhaseStructureResolver().resolve([]) == []
