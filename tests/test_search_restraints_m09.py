"""M09 候选检索与约束 - 单元测试 (search_restraints)"""
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.search_options import SearchOptions
from polyxrd.services import search_restraints as sr


def _phase(name="Quartz", formula="SiO2", density=None, a=4.913,
           b=4.913, c=5.405, alpha=90.0, beta=90.0, gamma=120.0,
           elements=None):
    lat = LatticeParams(a=a, b=b, c=c, alpha=alpha, beta=beta,
                        gamma=gamma) if a else None
    return Phase(
        name=name, formula=formula, density=density, lattice=lat,
        elements=elements if elements is not None else {"Si", "O"},
    )


# ── formula_mass / estimate_density ──

def test_formula_mass_sio2():
    # Si 28.085 + 2×15.999 = 60.083
    assert sr.formula_mass("SiO2") == pytest.approx(60.083, abs=0.01)


def test_formula_mass_bad():
    assert sr.formula_mass("") is None
    assert sr.formula_mass("Qq9") is None  # 解析不出任何合法元素


def test_estimate_density_quartz():
    # 石英 Z=3, ρ≈2.65; Z=1 下限估计 ≈0.88
    p = _phase()
    d1 = sr.estimate_density(p, z=1)
    assert d1 == pytest.approx(0.885, rel=0.02)
    assert sr.estimate_density(p, z=3) == pytest.approx(2.65, rel=0.03)


def test_estimate_density_cubic_si():
    # Si: a=5.4309, 8 原子/胞 → Z=8/8=1 式单元? 金刚石结构 8 Si 原子 → Z=8
    p = _phase(name="Si", formula="Si", a=5.4309, b=5.4309, c=5.4309,
               gamma=90.0, elements={"Si"})
    assert sr.estimate_density(p, z=8) == pytest.approx(2.33, rel=0.02)


def test_effective_density_prefers_stored():
    assert sr.effective_density(_phase(density=3.21)) == 3.21
    assert sr.effective_density(_phase()) == pytest.approx(0.885, rel=0.02)
    assert sr.effective_density(_phase(a=None)) is None  # 无晶胞


# ── apply_restraints ──

def test_apply_restraints_name_pattern():
    phases = [_phase("Corundum", "Al2O3", elements={"Al", "O"}),
              _phase("Quartz", "SiO2"),
              _phase("Moganite", "SiO2")]
    opts = SearchOptions(name_pattern="*corundum*")
    out = sr.apply_restraints(phases, opts)
    assert [p.name for p in out] == ["Corundum"]


def test_apply_restraints_density_range():
    # 石英实测 2.65; 假密度 1.0 的相被排除; 无密度无晶胞的相放行
    quartz = _phase(density=2.65)
    light = _phase(name="Light", density=1.0)
    unknown = _phase(name="Unknown", a=None)  # 无密度且无法估算
    opts = SearchOptions(density_range=(2.0, 3.0))
    out = sr.apply_restraints([quartz, light, unknown], opts)
    assert [p.name for p in out] == ["Quartz", "Unknown"]


def test_apply_restraints_elements_unchanged():
    phases = [_phase(), _phase("Alumina", "Al2O3", elements={"Al", "O"})]
    opts = SearchOptions(exclude=["Al"])
    assert [p.name for p in sr.apply_restraints(phases, opts)] == ["Quartz"]


# ── find_phases_direct ──

def test_find_phases_direct_substring_case_insensitive():
    phases = [_phase("Corundum"), _phase("Quartz"), _phase("Moganite")]
    assert [p.name for p in sr.find_phases_direct("CORUN", phases)] == \
        ["Corundum"]


def test_find_phases_direct_prefix_ranking():
    phases = [_phase("Quartz-like"), _phase("Quartz")]
    out = sr.find_phases_direct("quartz", phases)
    assert out[0].name == "Quartz"  # 前缀命中排在子串前


def test_find_phases_direct_formula_and_wildcard():
    phases = [_phase("Quartz", "SiO2"), _phase("Cristobalite", "SiO2"),
              _phase("Corundum", "Al2O3")]
    assert len(sr.find_phases_direct("SiO2", phases)) == 2
    assert [p.name for p in sr.find_phases_direct("*crist*", phases)] == \
        ["Cristobalite"]
    assert sr.find_phases_direct("", phases) == []


# ── 预设存取 (tmp_path 隔离 ~/.polyxrd) ──

@pytest.fixture()
def preset_home(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "_presets_file",
                        lambda: tmp_path / "search_presets.json")
    return tmp_path


def _full_opts() -> SearchOptions:
    return SearchOptions(
        must_have=["Fe"], must=["O"], maybe=["Si"], exclude=["Na"],
        name_pattern="*ite", density_range=(2.0, 5.0),
        score_threshold=12.5, max_entries=50,
        check_three_strongest=True, three_strongest_hits=2,
        delta_2theta=0.2, delta_2theta_auto=False,
        delta_2theta_factor=1.2, default_fwhm=0.1,
        use_intensity=False, metal_penalty=1.5, tol_fallback=0.1,
    )


def test_preset_roundtrip(preset_home):
    opts = _full_opts()
    sr.save_preset("iron_oxides", opts)
    assert "iron_oxides" in sr.list_presets()
    loaded = sr.load_preset("iron_oxides")
    assert loaded == opts  # dataclass 相等 (含 tuple 还原)
    # 密度范围还原为 tuple
    assert loaded.density_range == (2.0, 5.0)
    assert isinstance(loaded.density_range, tuple)


def test_preset_overwrite_and_missing(preset_home):
    sr.save_preset("a", SearchOptions(max_entries=1))
    sr.save_preset("a", SearchOptions(max_entries=2))
    assert sr.load_preset("a").max_entries == 2
    assert sr.load_preset("nope") is None
    assert sr.delete_preset("a") is True
    assert sr.delete_preset("a") is False
    assert sr.list_presets() == []
