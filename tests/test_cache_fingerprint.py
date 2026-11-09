"""缓存正确性守护（2026-11-09）
==============================
覆盖三类"缓存键 / 失效条件不完整"的回归：

1. ``PhaseStructureResolver``：同名同式的多型（不同晶胞 / 空间群 / 位点）
   不得共用缓存键；波长与 2θ 范围改变补齐口径，也必须换键。
2. ``StructureSimulator``：内置参考库 JSON 变化后必须重载，不能永久吃旧缓存。
3. ``refinement.symmetry``：空间群缓存必须有上界且按 LRU 淘汰。
"""
from __future__ import annotations

import json
import os

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.refinement import symmetry
from polyxrd.services import structure_simulator as sim_mod
from polyxrd.services.phase_structure_resolver import (
    PhaseStructureResolver,
    _structure_fingerprint,
)
from polyxrd.services.structure_simulator import StructureSimulator


def _phase(**kw) -> Phase:
    base = dict(
        name="TiO2",
        formula="O2 Ti",
        lattice=LatticeParams(a=4.59, b=4.59, c=2.96),
        space_group="P42/mnm",
    )
    base.update(kw)
    return Phase(**base)


# ── 1. 结构指纹 ────────────────────────────────────────────────

def test_fingerprint_is_stable_for_identical_phases():
    assert _structure_fingerprint(_phase()) == _structure_fingerprint(_phase())


def test_fingerprint_separates_polymorphs():
    rutile = _phase()
    anatase = _phase(lattice=LatticeParams(a=3.78, b=3.78, c=9.50),
                     space_group="I41/amd")
    assert _structure_fingerprint(rutile) != _structure_fingerprint(anatase)


def test_fingerprint_separates_sites_and_db_entry():
    a = _phase(atomic_sites=[{"label": "Ti", "x": 0.0, "y": 0.0, "z": 0.0}])
    b = _phase(atomic_sites=[{"label": "Ti", "x": 0.5, "y": 0.5, "z": 0.5}])
    assert _structure_fingerprint(a) != _structure_fingerprint(b)
    assert _structure_fingerprint(_phase(db_id=1)) != _structure_fingerprint(
        _phase(db_id=2))


def test_resolver_cache_keys_include_fingerprint_and_resolve_scope(monkeypatch):
    r = PhaseStructureResolver()
    # 隔离外部 polyDB 与 CIF 落盘：两条补齐路径都置空，只观察缓存键
    monkeypatch.setattr(r, "_augment_sites", lambda p: (p, None))
    monkeypatch.setattr(
        PhaseStructureResolver, "_synthesize_cif_from_sites",
        staticmethod(lambda p: None),
    )

    r.resolve([_phase()], wavelength=1.5406)
    r.resolve([_phase(lattice=LatticeParams(a=3.78, b=3.78, c=9.50))],
              wavelength=1.5406)
    assert len(r._cache) == 2, "同名多型被压进同一个缓存键"

    r.resolve([_phase()], wavelength=1.54056)
    assert len(r._cache) == 3, "波长变化未进缓存键"

    r.resolve([_phase()], wavelength=1.5406, two_theta_range=(10.0, 80.0))
    assert len(r._cache) == 4, "2θ 范围变化未进缓存键"

    # 完全相同的输入仍应复用同一个键
    r.resolve([_phase()], wavelength=1.5406)
    assert len(r._cache) == 4


# ── 2. 内置参考库缓存失效 ──────────────────────────────────────

def test_reference_db_reuses_cache_while_unchanged(tmp_path, monkeypatch):
    db = tmp_path / "xrd_reference_database.json"
    db.write_text(json.dumps({"phases": [{"name": "A"}]}), encoding="utf-8")
    monkeypatch.setattr(sim_mod, "get_resource_path", lambda _p: str(db))

    s = StructureSimulator()
    first = s.list_database_phases()
    assert first == ["A"]
    assert s._load_reference_database() is s._load_reference_database()


def test_reference_db_reloads_after_file_changes(tmp_path, monkeypatch):
    db = tmp_path / "xrd_reference_database.json"
    db.write_text(json.dumps({"phases": [{"name": "A"}]}), encoding="utf-8")
    monkeypatch.setattr(sim_mod, "get_resource_path", lambda _p: str(db))

    s = StructureSimulator()
    assert s.list_database_phases() == ["A"]

    db.write_text(json.dumps({"phases": [{"name": "B"}]}), encoding="utf-8")
    st = db.stat()
    # 内容长度相同，显式推后 mtime，确保戳确实变化
    os.utime(db, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    assert s.list_database_phases() == ["B"], "参考库文件变了仍吃旧缓存"


# ── 3. 空间群缓存上界 ──────────────────────────────────────────

def test_sg_cache_is_bounded():
    cache = symmetry._SG_CACHE
    cache.clear()
    try:
        for i in range(symmetry._SG_CACHE_MAX + 20):
            cache[f"FAKE-{i}"] = None
        symmetry._load_space_group("P1")
        assert len(cache) == symmetry._SG_CACHE_MAX, "空间群缓存无上界"
        assert "P1" in cache
    finally:
        cache.clear()


def test_sg_cache_hit_refreshes_lru_order():
    cache = symmetry._SG_CACHE
    cache.clear()
    try:
        symmetry._load_space_group("P1")
        symmetry._load_space_group("P-1")
        assert list(cache)[-1] == "P-1"
        symmetry._load_space_group("P1")
        assert list(cache)[-1] == "P1", "命中未刷新 LRU 位置"
    finally:
        cache.clear()


if __name__ == "__main__":  # pragma: no cover
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
