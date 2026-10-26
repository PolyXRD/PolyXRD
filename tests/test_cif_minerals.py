"""``services/cif_minerals.py`` 单元测试（v4.2 P1.3）。

覆盖：内置 12 矿物的查询/详情/Phase 转换、外部 CIF 导入（文件 + 目录）、
增删、导出、以及模块纯度（无 sqlite3 / 无 Qt / 不读配置）。

与旧实现的等价性已在搬迁时一次性对拍确认（12 键逐字段、get_phase_list、
get_mineral_info、get_cif_content、get_phase、search* 7 组查询、
load_cif_file 3 键、export_all 12 文件逐字节），本文件只守住新类自身契约。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyxrd.models.phase import Phase  # noqa: E402
from polyxrd.services import cif_minerals as cm  # noqa: E402
from polyxrd.services.cif_minerals import CifMineralLibrary  # noqa: E402

BUILTIN_KEYS = ["Si", "SiO2", "NaCl", "Al2O3", "CaCO3", "Fe2O3",
                "TiO2_anatase", "TiO2_rutile", "ZrSiO4", "CaTiO3",
                "Fe3O4", "KAlSi3O8"]

REQUIRED_FIELDS = ("name", "formula", "space_group", "lattice",
                   "atomic_sites", "cif")


@pytest.fixture()
def lib():
    return CifMineralLibrary()


@pytest.fixture()
def cif_file(tmp_path):
    """用内置堇青石/方解石 CIF 落盘成外部文件。"""
    p = tmp_path / "my_calcite.cif"
    p.write_text(CifMineralLibrary().get_cif_content("CaCO3"), encoding="utf-8")
    return p


# ──────────────────────────────────────────────────────────────
# 内置数据完整性
# ──────────────────────────────────────────────────────────────
def test_builtin_minerals_complete():
    assert list(cm._BUILTIN_MINERALS) == BUILTIN_KEYS
    for key in BUILTIN_KEYS:
        data = cm._BUILTIN_MINERALS[key]
        for f in REQUIRED_FIELDS:
            assert f in data, f"{key} 缺字段 {f}"
        assert data["key"] == key
        assert data["lattice"]["a"] > 0
        assert data["atomic_sites"], f"{key} 无位点"
        assert "_cell_length_a" in data["cif"], key


def test_len_and_contains(lib):
    assert len(lib) == 12
    assert "SiO2" in lib
    assert "TiO2_rutile" in lib
    assert "nope" not in lib


# ──────────────────────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────────────────────
def test_get_phase_list(lib):
    rows = lib.get_phase_list()
    assert len(rows) == 12
    assert {r["source"] for r in rows} == {"builtin"}
    assert {"key", "name", "formula", "space_group"} <= set(rows[0])
    assert [r["key"] for r in rows] == BUILTIN_KEYS


def test_search_by_formula(lib):
    assert [r["key"] for r in lib.search_by_formula("SiO2")] == ["SiO2"]
    # 大小写/空白不敏感
    assert [r["key"] for r in lib.search_by_formula("  sio2 ")] == ["SiO2"]
    assert lib.search_by_formula("CaCO3")[0]["space_group"] == "R-3c"
    assert lib.search_by_formula("does-not-exist") == []


def test_search_by_name_is_substring(lib):
    assert [r["key"] for r in lib.search_by_name("quartz")] == ["SiO2"]
    assert [r["key"] for r in lib.search_by_name("QUARTZ")] == ["SiO2"]
    assert [r["key"] for r in lib.search_by_name("ita")] == []  # 无匹配
    assert len(lib.search_by_name("i")) >= 2  # Si / Calcite 等


def test_search_by_space_group(lib):
    assert {r["key"] for r in lib.search_by_space_group("Fd-3m")} == {"Si", "Fe3O4"}
    assert lib.search_by_space_group("fd-3m")  # 不区分大小写
    assert lib.search_by_space_group("  ") == []


def test_search_unions_and_dedupes(lib):
    """综合搜索按 key 去重（同时命中 formula 与 space_group 也只出现一次）。"""
    got = lib.search("SiO2")
    keys = [r["key"] for r in got]
    assert keys.count("SiO2") == 1
    assert set(keys) >= {"SiO2"}


def test_search_empty_query(lib):
    assert all(isinstance(r, dict) for r in lib.search(""))


# ──────────────────────────────────────────────────────────────
# 详情 / Phase 转换
# ──────────────────────────────────────────────────────────────
def test_get_cif_content(lib):
    text = lib.get_cif_content("SiO2")
    assert "data_" in text and "_cell_length_a" in text
    assert lib.get_cif_content("nope") is None


def test_get_mineral_info(lib):
    info = lib.get_mineral_info("Al2O3")
    assert info["name"] == "Corundum"
    assert info["formula"] == "Al2O3"
    assert info["space_group_number"] == 167
    assert info["source"] == "builtin"
    assert lib.get_mineral_info("nope") is None


def test_get_phase_builds_model(lib):
    p = lib.get_phase("SiO2")
    assert isinstance(p, Phase)
    assert p.formula == "SiO2"
    assert p.space_group == "P3121"
    assert p.lattice.a == pytest.approx(4.913)
    assert p.lattice.gamma == pytest.approx(120.0)
    assert len(p.atomic_sites) == 4
    assert p.cif_path is None
    assert lib.get_phase("nope") is None


# ──────────────────────────────────────────────────────────────
# 外部 CIF 导入 / 增删
# ──────────────────────────────────────────────────────────────
def test_load_cif_file(lib, cif_file):
    """内置 CIF 只带晶胞/空间群/位点，**不含** _chemical_formula_sum。"""
    data = lib.load_cif_file(str(cif_file))
    assert data["source"] == "external"
    assert data["key"] == cif_file.stem
    assert data["space_group"] == "R-3c"
    assert data["space_group_number"] == 167
    assert data["lattice"]["a"] == pytest.approx(4.989, abs=1e-6)
    assert data["lattice"]["gamma"] == pytest.approx(120.0)
    assert data["atomic_sites"]
    # 位点补齐规范键（v1.1.2 行为）
    site = data["atomic_sites"][0]
    assert {"x", "y", "z", "element", "u_iso"} <= set(site)

    assert len(lib) == 13
    assert cif_file.stem in lib
    assert lib.get_cif_content(cif_file.stem) == cif_file.read_text(encoding="utf-8")
    assert lib.get_phase_list()[-1]["source"] == "external"


def test_load_cif_file_with_formula_sum(lib, tmp_path):
    """带 _chemical_formula_sum 的 CIF 才解析出 formula（单引号形式）。"""
    cif = tmp_path / "with_sum.cif"
    cif.write_text(
        "data_Test\n"
        "_cell_length_a 4.0\n_cell_length_b 4.0\n_cell_length_c 4.0\n"
        "_symmetry_space_group_name_H-M 'P 1'\n"
        "_chemical_formula_sum 'Ca1 C1 O3'\n"
        "loop_\n"
        "_atom_site_label\n_atom_site_fract_x\n_atom_site_fract_y\n"
        "_atom_site_fract_z\n_atom_site_occupancy\n"
        "Ca1 0.0 0.0 0.0 1.0\n"
        "C1 0.25 0.25 0.25 1.0\n",
        encoding="utf-8",
    )
    data = lib.load_cif_file(str(cif))
    assert data["formula"] == "Ca1 C1 O3"
    assert data["space_group"] == "P 1"
    assert data["name"] == "Test"
    assert len(data["atomic_sites"]) == 2


def test_load_cif_file_missing_raises(lib, tmp_path):
    with pytest.raises(FileNotFoundError):
        lib.load_cif_file(str(tmp_path / "nope.cif"))


def test_load_cif_file_is_lenient_on_garbage(lib, tmp_path):
    """⚠️ 已知遗留行为（v4.2 不改变语义，P4 再收紧）：

    ``_parse_cif_content`` 对任何文本都返回非空 dict（至少含 ``cif`` 键），
    所以 ``load_cif_file`` 里的 ``raise ValueError`` 分支实际**不可达** ——
    垃圾文件会被静默登记为"外部矿物"，且其 ``get_mineral_info`` 会因缺
    ``name`` 抛 KeyError。这里把现状钉住，避免"以为它有校验"。
    """
    bad = tmp_path / "bad.cif"
    bad.write_text("this is not a cif\n", encoding="utf-8")
    data = lib.load_cif_file(str(bad))
    assert data["atomic_sites"] == []
    assert "lattice" not in data
    assert "bad" in lib
    with pytest.raises(KeyError):
        lib.get_mineral_info("bad")


def test_load_cif_directory_loads_everything(lib, tmp_path, cif_file):
    (tmp_path / "broken.cif").write_text("garbage", encoding="utf-8")
    got = lib.load_cif_directory(str(tmp_path))
    # 2 个 .cif 都被收下（legacy 宽松语义，见上一个用例）
    assert len(got) == 2
    assert {g["key"] for g in got} == {cif_file.stem, "broken"}
    assert len(lib) == 14


def test_add_and_remove_mineral(lib):
    lib.add_mineral("MY_PHASE", {"name": "My Phase", "formula": "Xx1",
                                 "space_group": "P1", "cif": "data_x"})
    assert len(lib) == 13
    assert "MY_PHASE" in lib
    assert lib.get_mineral_info("MY_PHASE")["source"] == "external"
    assert lib.search_by_formula("Xx1")[0]["key"] == "MY_PHASE"
    # 外部可删，内置不可删
    assert lib.remove_mineral("MY_PHASE") is True
    assert "MY_PHASE" not in lib
    assert len(lib) == 12
    assert lib.remove_mineral("SiO2") is False
    assert len(lib) == 12


# ──────────────────────────────────────────────────────────────
# 导出
# ──────────────────────────────────────────────────────────────
def test_export_cif(lib, tmp_path):
    out = lib.export_cif("SiO2", str(tmp_path))
    assert out is not None
    p = Path(out)
    assert p.exists()
    assert p.read_text(encoding="utf-8") == lib.get_cif_content("SiO2")
    # 文件名取矿物名（希腊字母等被替换为 _ 之前的部分仍可读）
    assert p.suffix == ".cif"
    assert lib.export_cif("nope", str(tmp_path)) is None


def test_export_all(lib, tmp_path):
    paths = lib.export_all(str(tmp_path))
    assert len(paths) == 12
    for p in paths:
        assert Path(p).exists()
        assert "_cell_length_a" in Path(p).read_text(encoding="utf-8")


def test_exported_cif_is_reloadable(lib, tmp_path):
    """导出的 CIF 能被本类重新导入（自洽性）。"""
    out = lib.export_cif("TiO2_rutile", str(tmp_path))
    again = CifMineralLibrary()
    data = again.load_cif_file(out)
    assert data["space_group"]
    assert data["lattice"]["a"] == pytest.approx(4.594, abs=1e-3)
    assert data["atomic_sites"]


def test_exported_cif_parsable_by_pymatgen(lib, tmp_path):
    """内置 CIF 应能被 pymatgen 解析（它是下游结构/精修的硬依赖）。

    内置 CIF 走 P1 单胞 + 显式 symmetry_equiv_pos_as_xyz，pymatgen 读取后
    原子数与文件里写出的位点数一致（不做空间群展开）。
    """
    pmg = pytest.importorskip("pymatgen.core")
    out = lib.export_cif("CaCO3", str(tmp_path))
    struct = pmg.Structure.from_file(out)
    assert struct.composition.num_atoms > 0
    assert len(struct) >= 3
    assert {"Ca", "C", "O"} <= {str(el) for el in struct.composition.elements}


# ──────────────────────────────────────────────────────────────
# 模块纯度
# ──────────────────────────────────────────────────────────────
def test_cif_minerals_is_pure_module():
    """不得 import sqlite3 / PySide6 / 读配置路径（AST 检查，不受 docstring 干扰）。"""
    tree = ast.parse(Path(cm.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in {"sqlite3", "PySide6"}, a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module != "polyxrd.config", node.module
            assert not node.module.startswith("PySide6"), node.module


def test_no_legacy_symbols_in_module():
    """新模块不得残留旧 COD sqlite 运行时的类名/表名。"""
    text = Path(cm.__file__).read_text(encoding="utf-8")
    for sym in ("CODLocalDatabase", "CODLocalIndexer", "cod_index.sqlite",
                "COD_inorganics.sqlite"):
        assert sym not in text, sym


def test_does_not_touch_user_config(tmp_path, monkeypatch):
    """构造实例不应读写 ~/.polyxrd（旧类 __init__ 会 mkdir）。"""
    import polyxrd.config as config_mod

    called: list[str] = []

    class _Boom:
        def __getattr__(self, name):
            called.append(name)
            raise AssertionError(f"不应访问配置: {name}")

    monkeypatch.setattr(config_mod, "get_config", lambda: _Boom())
    CifMineralLibrary()
    assert called == []
