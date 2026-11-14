# -*- coding: utf-8 -*-
"""v4.1.1 hotfix 回归守卫。

覆盖：
1. 构建链：``_build_post.py`` 必须入库、build.bat 引用的脚本都存在、关键步骤硬失败；
2. 默认库：polyDB 非对称位点必须展开（Corundum 真实库）；精修侧对未展开位点做幂等兜底；
3. 干净安装：resolver 能从 atomic_sites 反生成 CIF 回填 cif_path，外部引擎不再静默退化；
4. 发布政策：默认不打包数据库包、验收器不再硬编码库名、文档不再写错相数。
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from polyxrd.models.phase import LatticeParams, Phase  # noqa: E402
from polyxrd.services.phase_cif import expand_sites_by_symmetry  # noqa: E402

REAL_DB = Path(
    r"D:\Project\XRD\PolyXRD-DataBase\polydb\COD-Inorg-20261021.polyDB")

_NACL_SITES = [
    {"label": "Na1", "element": "Na", "x": 0.0, "y": 0.0, "z": 0.0,
     "occupancy": 1.0},
    {"label": "Cl1", "element": "Cl", "x": 0.5, "y": 0.5, "z": 0.5,
     "occupancy": 1.0},
]


def _nacl_phase(db_id: int | None = 999000001) -> Phase:
    return Phase(
        name="halite (COD 999000001)",
        formula="Na Cl",
        space_group="F m -3 m",
        lattice=LatticeParams(a=5.6402, b=5.6402, c=5.6402,
                              alpha=90.0, beta=90.0, gamma=90.0),
        atomic_sites=[dict(s) for s in _NACL_SITES],
        db_id=db_id,
    )


def _load_build_post():
    spec = importlib.util.spec_from_file_location(
        "_bp_v411", ROOT / "scripts" / "_build_post.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. 构建链 ────────────────────────────────────────────────

def test_build_bat_referenced_pyscripts_exist():
    bat = (ROOT / "build.bat").read_text(encoding="utf-8", errors="ignore")
    refs = set(re.findall(r"scripts\\([A-Za-z0-9_]+\.py)", bat))
    assert refs, "build.bat 里没有解析到 scripts 引用"
    for name in refs:
        assert (ROOT / "scripts" / name).is_file(), f"build.bat 引用缺失: scripts/{name}"


def test_build_post_script_is_tracked_by_git():
    """P0 回归：_build_post.py 曾被 .gitignore 的 `_*.py` 吞掉。"""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "scripts/_build_post.py"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.SubprocessError):
        pytest.skip("git 不可用")
    assert proc.returncode == 0, \
        "scripts/_build_post.py 未被 git 跟踪 —— fresh clone 构建会丢内置库/VERSION/便携 extras"


def test_build_bat_critical_steps_hard_fail():
    bat = (ROOT / "build.bat").read_text(encoding="utf-8", errors="ignore")
    for marker in ("bundle-polydb", "db-layout", "portable-extras"):
        assert marker in bat
    # 每个关键调用后 400 字符内必须有硬失败
    for marker in ("_build_post.py bundle-polydb",
                   "_build_post.py db-layout",
                   "_build_post.py version %APPVER%",
                   "_build_post.py portable-extras"):
        idx = bat.find(marker)
        assert idx >= 0, f"build.bat 缺少 {marker}"
        assert "exit /b 1" in bat[idx:idx + 400], \
            f"{marker} 之后没有 errorlevel 硬失败，构建会带病继续"
    # 验收口径由 flavor 决定（不能靠“文件不存在”自证跳过）
    assert "-SkipPortable" in bat and "-SkipSetup" in bat


def test_assert_db_layout_returns_nonzero_on_problem(tmp_path, monkeypatch):
    mod = _load_build_post()
    dist = tmp_path / "dist" / "PolyXRD"
    dist.mkdir(parents=True)
    monkeypatch.setattr(mod, "DIST", str(dist))
    assert mod.assert_db_layout() == 1, "空 dist 仍返回 0 —— 门禁没有真正生效"


def test_write_version_uses_builtin_phase_count(tmp_path, monkeypatch):
    mod = _load_build_post()
    dist = tmp_path / "dist" / "PolyXRD"
    lib = dist / "databases" / "COD-Inorg-20261021.polyDB"
    lib.mkdir(parents=True)
    (lib / "meta.json").write_text(
        json.dumps({"format": "polyDB", "schema_version": 1,
                    "variant": "cod-inorg", "counts": {"phases": 77500}}),
        encoding="utf-8")
    monkeypatch.setattr(mod, "DIST", str(dist))
    assert mod._bundled_phase_count() == "77,500 相"


# ── 2. 位点展开（默认库精修正确性）─────────────────────────

def test_expand_sites_idempotent_nacl():
    full = expand_sites_by_symmetry(_NACL_SITES, "F m -3 m")
    assert len(full) == 8, "NaCl Fm-3m 应展开为 4a+4b = 8 个位点"
    again = expand_sites_by_symmetry(full, "F m -3 m")
    assert len(again) == 8, "幂等展开不应重复叠加"
    assert {s["element"] for s in full} == {"Na", "Cl"}


class TestStrictExpand:
    """``strict=True``：降级路径返回 ``None`` 而不是"原样返回"。

    v4.1.1 那个假峰事故的根因是"调用方分不清『本来就是全胞』与『展不开』"。
    ``polydb_structure._expanded_sites`` 因此传 ``strict=True`` —— 这些用例
    钉住那条约定：**只有** P1/C1 这种"本来就无操作可展"才返回原样列表。
    """

    ASYM: ClassVar[list[dict]] = [
        {"label": "Ca1", "element": "Ca", "x": 0.0, "y": 0.0, "z": 0.0,
         "occupancy": 1.0},
        {"label": "C1", "element": "C", "x": 0.0, "y": 0.0, "z": 0.25,
         "occupancy": 1.0},
        {"label": "O1", "element": "O", "x": 0.2568, "y": 0.0, "z": 0.25,
         "occupancy": 1.0},
    ]

    def test_normal_expand_returns_full_cell(self):
        assert len(expand_sites_by_symmetry(
            self.ASYM, "R -3 c", strict=True)) == 30

    def test_p1_returns_input_unchanged(self):
        """P1 无操作可展 —— 位点本身就是全胞，strict 下也该返回原样。"""
        out = expand_sites_by_symmetry(self.ASYM, "P 1", strict=True)
        assert out is not None and len(out) == 3

    def test_missing_or_unparsable_space_group_returns_none(self):
        assert expand_sites_by_symmetry(self.ASYM, "", strict=True) is None
        assert expand_sites_by_symmetry(self.ASYM, "C m c a", strict=True) is None

    def test_dirty_site_returns_none(self):
        dirty = [{"label": "Ca1", "element": "Ca", "x": "a", "y": 0,
                  "z": 0, "occupancy": 1.0}]
        assert expand_sites_by_symmetry(dirty, "R -3 c", strict=True) is None
        # 非 strict 保持老行为：原样返回，不劣化
        assert expand_sites_by_symmetry(dirty, "R -3 c") == dirty

    def test_non_finite_coordinate_returns_none(self):
        """``float("NaN")`` 能过 ``float()``，但会污染出 36 个 NaN 假位点。"""
        dirty = [{"label": "Ca1", "element": "Ca", "x": "NaN", "y": 0,
                  "z": 0, "occupancy": 1.0}]
        assert expand_sites_by_symmetry(dirty, "R -3 c", strict=True) is None

    def test_pathological_fuse_returns_none(self):
        """``len(sites)*len(ops) > 500_000`` 保险丝触发时不谎报"已展开"。"""
        many = [{"label": f"Ca{i}", "element": "Ca", "x": i / 5000.0,
                 "y": 0.0, "z": 0.0, "occupancy": 1.0} for i in range(2000)]
        assert expand_sites_by_symmetry(many, "R -3 c", strict=True) is None

    def test_max_sites_overflow_returns_none(self):
        assert expand_sites_by_symmetry(
            self.ASYM, "R -3 c", max_sites=2, strict=True) is None
        assert len(expand_sites_by_symmetry(
            self.ASYM, "R -3 c", max_sites=2)) == 3


def test_refiner_expands_unexpanded_sites():
    """回归：未展开位点直构 Structure 会给高对称相造出假峰。"""
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    phase = _nacl_phase()
    peaks = RietveldRefiner()._cif_reference_peaks(
        phase, wavelength=1.5406, tth_range=(5.0, 90.0))
    assert peaks, "没有生成模拟峰"
    # NaCl Fm-3m 第一条允许反射是 111 (~27.3°)；未展开的 P1 会多出 100(~15.6°)
    strong_low = [(round(t, 2), round(i, 1))
                  for _h, t, i in peaks if t < 25.0 and i > 5.0]
    assert not strong_low, f"出现 P1 假峰: {strong_low}"
    top = sorted(peaks, key=lambda r: -r[2])[:3]
    assert min(abs(t - 31.7) for _h, t, _i in top) < 0.5, \
        f"NaCl 最强 200 反射 (~31.7°) 不在 top3: {top}"


@pytest.mark.skipif(not REAL_DB.is_dir(), reason="本机无实测 polyDB 库")
def test_polydb_phase_sites_are_expanded_corundum():
    from polyxrd.services.phase_identifier import PhaseIdentifier
    from polyxrd.services.polydb import PolyDatabase
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    db = PolyDatabase(str(REAL_DB))
    assert db.is_ready()
    detail = db.get_phase(1000017)  # Corundum, R -3 c
    phase = PhaseIdentifier._make_polydb_phase(
        detail, {"cod_id": 1000017}, [], db=db)
    assert len(phase.atomic_sites) == 30, \
        f"侧车 2 个非对称位点应展开为 30 个全胞位点，实际 {len(phase.atomic_sites)}"
    peaks = RietveldRefiner()._cif_reference_peaks(
        phase, wavelength=1.5406, tth_range=(5.0, 90.0))
    top = sorted(peaks, key=lambda r: -r[2])[:3]
    assert abs(top[0][1] - 57.49) < 0.3, f"Corundum 主峰错: {top}"
    fake = [(round(t, 2), round(i, 1)) for _h, t, i in peaks
            if t < 10.0 and i > 10.0]
    assert not fake, f"6.8° 假峰回归: {fake}"


# ── 3. 干净安装：resolver 从位点生成 CIF ─────────────────────

def test_resolver_synthesizes_cif_from_sites(tmp_path, monkeypatch):
    from polyxrd.config import AppConfig
    from polyxrd.services.phase_structure_resolver import PhaseStructureResolver
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    cache = tmp_path / "cif_cache"
    cache.mkdir(parents=True, exist_ok=True)

    class _FakeCfg:
        def cif_cache_dir(self):
            return cache

    # resolver 在方法内 `from polyxrd.config import get_config`，patch 模块属性最稳
    monkeypatch.setattr("polyxrd.config.get_config", lambda: _FakeCfg())

    phase = _nacl_phase()
    resolver = PhaseStructureResolver()
    logs: list[str] = []
    out = resolver.resolve([phase], log_cb=logs.append)

    assert len(out) == 1 and out[0] is not phase
    cif = out[0].cif_path
    assert cif and Path(cif).is_file(), "resolver 未能从位点生成 CIF"
    text = Path(cif).read_text(encoding="utf-8", errors="ignore")
    assert "data_" in text and "_atom_site_fract_x" in text
    assert RietveldRefiner._phases_have_structure(out), \
        "cif_path 回填后 _phases_have_structure 仍为 False（外部引擎会被静默跳过）"
    assert any("由原子位点生成 CIF" in line for line in logs)


def test_phase_cif_export_uses_atomic_sites():
    from polyxrd.services import phase_cif_export

    # v4.2: 旧 COD 库通道已删除，位点反生成是主路径（无需再屏蔽库）
    text, _cod_id = phase_cif_export.get_phase_cif_text(_nacl_phase())
    assert "_atom_site_fract_x" in text
    assert "Na" in text and "Cl" in text


# ── 4. 发布政策 / 文档守卫 ──────────────────────────────────

def test_verify_release_skips_db_packages_by_default():
    s = (ROOT / "scripts" / "verify_release.ps1").read_text(
        encoding="utf-8", errors="ignore")
    assert "PackDbPackages" in s
    assert "if (-not $PackDbPackages) { $dbKinds = @() }" in s, \
        "关闭 PackDbPackages 时旧 sqlite 库包仍会被生成"
    assert "-SkipSetup" in s


def test_verify_installer_bundled_lib_is_dynamic():
    s = (ROOT / "scripts" / "verify_installer.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "BUNDLED_LIB_GLOB" in s
    assert "20261021" not in s, "验收器仍硬编码库名，换库会误报"


@pytest.mark.parametrize("rel", [
    "README.md",
    "docs/RELEASE-NOTES-v4.1.0.md", "scripts/_build_post.py",
])
def test_docs_do_not_claim_wrong_phase_count(rel):
    p = ROOT / rel
    if not p.is_file():
        pytest.skip(f"{rel} 不存在")
    text = p.read_text(encoding="utf-8", errors="ignore")
    assert "78,036" not in text, f"{rel} 仍写 78,036 相（实际库是 77,500 相）"
