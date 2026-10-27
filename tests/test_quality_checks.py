"""工程质量守卫测试 —— v4.0.0 审计落地（2026-10-23）。

这些用例只校验「仓库级一致性契约」，不依赖外挂数据库 / 网络 / 外部引擎，
应当在任何机器上稳定通过（polyDB 实测库用例带 skipif 守卫）。

每条用例都对应 ``.workbuddy/tmp/review-quality.md`` 里的一条审计结论：

1. 版本号单一真源收口（CHANGELOG 附录 E 的 5 处）；
2. pyproject 的 ruff 门禁与 CI workflow 完全一致；
3. pytest 自定义 mark 必须注册（防止 ``@pytest.mark.slow`` 静默降级为告警）；
4. ``tests/test_*.py`` 不得是零用例的死文件；
5. polyDB 实测库与 reader 契约自洽（bins/elem/sites 字节数、entries.row_idx）。
"""
from __future__ import annotations

import ast
import math
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "polyxrd"
TESTS = ROOT / "tests"

# 已知缺口（修复后删掉对应白名单项即可让本测试继续收紧）：
#   - tests/ 里未注册的 mark: slow（pytest 只发 PytestUnknownMarkWarning）
#   - tests/ 里名字叫 test_* 但没有 test 函数的历史手工脚本
KNOWN_UNREGISTERED_MARKS = {"slow"}
KNOWN_DEAD_TEST_FILES = {"test_sample_tar_index.py", "test_xrd_samples.py"}

# 实测 polyDB 根目录；不存在则相关用例 skip（CI 上必然 skip）
_DB_ROOT = Path(
    r"D:\Project\XRD\PolyXRD-DataBase\polydb"
)
_INORG_DB = _DB_ROOT / "COD-Inorg-20261021.polyDB"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _version_tuple(text: str) -> str:
    m = re.search(r"(\d+\.\d+\.\d+)", text)
    assert m, f"未能从文本中解析出版本号: {text[:120]!r}"
    return m.group(1)


# ---------------------------------------------------------------------------
# 1. 版本号单一真源（CHANGELOG 附录 E）
# ---------------------------------------------------------------------------
def test_version_is_consistent_across_five_release_points():
    """5 处发版位置必须同版本；唯一真源 = ``src/polyxrd/__init__.py``。"""
    init_ver = _version_tuple(_read("src/polyxrd/__init__.py"))
    pyproject_ver = _version_tuple(
        re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"), re.M).group(1)
    )
    build_bat = _read("build.bat")
    m = re.search(r"^\s*set\s+APPVER=(\S+)", build_bat, re.M | re.I)
    assert m, "build.bat 顶部缺少 set APPVER="
    build_ver = m.group(1).strip()
    iss = _read("scripts/PolyXRD-Setup.iss")
    m = re.search(r'#define\s+AppVersion\s+"([^"]+)"', iss)
    assert m, "scripts/PolyXRD-Setup.iss 缺少 #define AppVersion"
    iss_ver = m.group(1)

    assert init_ver == pyproject_ver == build_ver == iss_ver, (
        f"版本号漂移: __init__={init_ver} pyproject={pyproject_ver} "
        f"build.bat={build_ver} iss={iss_ver}"
    )


def test_release_script_matches_current_version():
    """本版发版脚本必须存在、版本与唯一真源一致，且仍带"禁库"守卫。

    v4.4.0 验收补：脚本名/``$tag``/``$version`` 三处与 ``__init__.__version__``
    脱钩过一次（版号收口时漏改脚本），发布时才会在 ``gh release create`` 那一步
    才炸。这里做静态对齐，早发现。
    """
    ver = _version_tuple(_read("src/polyxrd/__init__.py"))
    script = ROOT / "scripts" / f"create_github_release_v{ver}.ps1"
    assert script.is_file(), f"缺少本版发布脚本: scripts/{script.name}"
    text = script.read_text(encoding="utf-8", errors="replace")
    assert re.search(rf"\$tag\s*=\s*['\"]v{re.escape(ver)}['\"]", text), \
        f"脚本 $tag 与版本 {ver} 不符"
    assert re.search(rf"\$version\s*=\s*['\"]{re.escape(ver)}['\"]", text), \
        f"脚本 $version 与版本 {ver} 不符"
    assert "$BANNED" in text and "PDF2" in text, \
        "脚本缺少 PDF2 / Databases- 禁传守卫"
    assert (ROOT / "docs" / f"RELEASE-NOTES-v{ver}.md").is_file()
    assert (ROOT / "docs" / f"发布检查清单-v{ver}.md").is_file()


def test_config_app_version_is_derived_not_duplicated():
    """config.app_version 必须从 ``__init__.__version__`` 派生（v2.3.0 收口约定）。"""
    cfg = _read("src/polyxrd/config.py")
    assert "from polyxrd import __version__" in cfg
    assert "app_version: str = __version__" in cfg
    # 不允许在 config.py 里再写死一个版本字面量
    assert not re.search(r'app_version\s*[:=]\s*["\']\d+\.\d+\.\d+', cfg)


# ---------------------------------------------------------------------------
# 2. ruff 门禁：pyproject 与 CI 一致
# ---------------------------------------------------------------------------
def test_ruff_gate_matches_ci_workflow():
    pyproject = _read("pyproject.toml")
    m = re.search(r"^\[tool\.ruff\.lint\]\s*$(.*?)(?=^\[|\Z)", pyproject, re.M | re.S)
    assert m, "pyproject.toml 缺少 [tool.ruff.lint]"
    sel = re.search(r"^select\s*=\s*\[([^\]]*)\]", m.group(1), re.M)
    assert sel, "[tool.ruff.lint] 缺少 select"
    gate = {x.strip().strip('"\'') for x in sel.group(1).split(",") if x.strip()}
    assert gate, "ruff 门禁 select 为空"

    workflow = _read(".github/workflows/test.yml")
    ci = re.findall(r"ruff\s+check\s+src/?\s+--select\s+([A-Za-z0-9,]+)", workflow)
    assert ci, "CI workflow 里没找到 ruff gate 命令"
    ci_gate = {x.strip() for x in ci[0].split(",") if x.strip()}
    assert ci_gate == gate, f"pyproject 门禁 {sorted(gate)} != CI 门禁 {sorted(ci_gate)}"


# ---------------------------------------------------------------------------
# 3. pytest mark 必须注册（否则只是 PytestUnknownMarkWarning）
# ---------------------------------------------------------------------------
_BUILTIN_MARKS = {
    "parametrize", "skip", "skipif", "xfail", "usefixtures",
    "filterwarnings", "timeout", "asyncio", "tryfirst", "trylast",
}


def test_pytest_marks_are_registered():
    used = set()
    for p in TESTS.glob("*.py"):
        used.update(re.findall(r"pytest\.mark\.([A-Za-z_]\w*)", p.read_text(
            encoding="utf-8", errors="replace")))
    pyproject = _read("pyproject.toml")
    registered = set()
    m = re.search(r"markers\s*=\s*\[(.*?)\]", pyproject, re.S)
    if m:
        registered = {x.strip().strip('"\'') for x in re.findall(r'"([^"]+)"', m.group(1))}
    unregistered = used - _BUILTIN_MARKS - registered - KNOWN_UNREGISTERED_MARKS
    assert not unregistered, (
        f"发现未注册的 pytest mark: {sorted(unregistered)}；"
        "请在 pyproject.toml [tool.pytest.ini_options] markers 里注册"
    )


# ---------------------------------------------------------------------------
# 4. tests/test_*.py 不得是零用例死文件
# ---------------------------------------------------------------------------
def _count_test_functions(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return 0
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            n += 1
    return n


def test_no_dead_test_files():
    dead = {p.name for p in TESTS.glob("test_*.py") if _count_test_functions(p) == 0}
    unexpected = dead - KNOWN_DEAD_TEST_FILES
    assert not unexpected, (
        f"这些 test_*.py 没有收集到任何 test 函数（应移入 scripts/ 或改名）: "
        f"{sorted(unexpected)}"
    )


# ---------------------------------------------------------------------------
# 5. polyDB 实测库与 reader 契约自洽
# ---------------------------------------------------------------------------
def _db_available() -> bool:
    return (_INORG_DB / "meta.json").is_file()


@pytest.mark.skipif(not _db_available(), reason="本机无 polyDB 实测库（CI 上正常 skip）")
def test_polydb_sections_are_self_consistent():
    """字节数 = shape 声明值；sites.bin = 17 B/位点；bins 箱数由 meta 驱动。"""
    import json

    meta = json.loads((_INORG_DB / "meta.json").read_text(encoding="utf-8"))
    n = int(meta["counts"]["phases"])
    k = int(meta["counts"]["k"])
    n_sites = int(meta["counts"]["sites"])
    expected_bins = 501  # 实测 = 500 个数据箱 + 1 overflow；规范文档写 494 是错的
    expected_elem = 118
    nbytes = math.ceil(n / 8)

    assert meta["sections"]["bins.u8"]["shape"][0] == expected_bins
    assert meta["sections"]["bins.u8"]["shape"][1] == nbytes
    assert (_INORG_DB / "bins.u8").stat().st_size == expected_bins * nbytes
    assert (_INORG_DB / "elem.u8").stat().st_size == expected_elem * nbytes
    assert (_INORG_DB / "peaks_d.f32").stat().st_size == n * k * 4
    assert (_INORG_DB / "peaks_i.u16").stat().st_size == n * k * 2
    # sites.bin 规范写 17 B/位点 —— 实测逐字节整除，可核对
    assert (_INORG_DB / "sites.bin").stat().st_size == 17 * n_sites


@pytest.mark.skipif(not _db_available(), reason="本机无 polyDB 实测库（CI 上正常 skip）")
def test_polydb_entries_has_explicit_row_idx():
    """数组段行号必须走显式 entries.row_idx（规范里缺失该列/该索引）。"""
    con = sqlite3.connect(f"file:{_INORG_DB / 'index.sqlite'}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(entries)")]
        assert "row_idx" in cols
        idx = [r[1] for r in con.execute("PRAGMA index_list(entries)")]
        assert "idx_entries_row" in idx, f"缺 idx_entries_row: {idx}"
        assert con.execute("SELECT COUNT(*) FROM entries WHERE row_idx IS NULL").fetchone()[0] == 0
        n_entries = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        import json

        meta = json.loads((_INORG_DB / "meta.json").read_text(encoding="utf-8"))
        assert n_entries == int(meta["counts"]["phases"])
    finally:
        con.close()
