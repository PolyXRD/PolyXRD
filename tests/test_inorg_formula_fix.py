"""COD 无机库 ``phases.formula`` 被空间群符号覆盖 —— 修复回归测试 (v0.13.2)

背景 (2026-09-18 实测)
----------------------
``cod_data/COD_inorganics.sqlite`` 的 ``phases.formula`` 列有 609 条被建库
脚本写成了**空间群符号** (如 ``P 63 m c``), 而内嵌 ``cif_gz`` 里的
``_chemical_formula_sum`` 是正确的。后果:

* ``elements_from_db_formula("P 63 m c")`` → ``{'P'}`` (被当成磷);
* 该元素集被下推到 ``search_cod_by_d_peaks`` 做 ``issubset`` 淘汰 →
  试样 3-1 (ZnO 93.59%) 一勾 Zn/O 过滤, 真 ZnO 在扫描层就被丢掉
  (候选 40 → 2)。不勾过滤时 top-8 虽全是 ZnO, 但名称显示成 ``P 63 m c``。

修复三层, 本文件逐层守住:
  1. 数据层 —— ``scripts/migrate_inorg_formula.py`` 用 CIF 重写 formula
     (只在「可无歧义判定为错」时改写);
  2. 判定层 —— ``formula_parser.elements_from_db_formula`` 新增
     ``space_group`` 参数, 与之相同的 formula 返回空集 = 不可信;
  3. 扫描层 —— ``search_cod_by_d_peaks`` 对不可信 formula **放行**
     (fail-open), 交给判定层用 CIF 复核; 另有 ``cod_local`` 的公式回退
     ``recover_inorg_formula`` 与索引空库门槛 ``_is_usable_index_file``。
"""

from __future__ import annotations

import gzip
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from polyxrd.services import cod_local as CL  # noqa: E402
from polyxrd.services.cif_database import CIFDatabase  # noqa: E402
from polyxrd.utils.formula_parser import (  # noqa: E402
    elements_from_db_formula,
    normalize_cod_formula,
)

INORG_DB = _ROOT / "cod_data" / "COD_inorganics.sqlite"


def _cod_ready() -> bool:
    try:
        return INORG_DB.exists() and INORG_DB.stat().st_size > 50 * 1024 * 1024
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────
# ① formula_parser: space_group 参数语义
# ──────────────────────────────────────────────────────────────
class TestElementsFromDbFormula:

    @pytest.mark.parametrize("formula,expected", [
        ("O Zn", {"O", "Zn"}),
        ("Li1.13 Mn2 O4", {"Li", "Mn", "O"}),
        ("O4 Zr3", {"O", "Zr"}),
        ("", set()),
    ], ids=["简单", "小数系数", "正常", "空"])
    def test_正常化学式不受影响(self, formula, expected):
        assert elements_from_db_formula(formula) == expected

    def test_不加space_group时保持旧行为(self):
        """向后兼容: 不传 space_group 时 "P 63 m c" 仍解析成 {'P'}。

        这是**刻意保留**的 —— 调用方必须显式传入同一行的 space_group 才能
        获得「不可信 → 空集」的判定, 免得误伤真的含磷物相。
        """
        assert elements_from_db_formula("P 63 m c") == {"P"}

    def test_与space_group相同则返回空集(self):
        assert elements_from_db_formula("P 63 m c", space_group="P 63 m c") == set()
        assert elements_from_db_formula("R 3 m", space_group="R 3 m") == set()

    def test_与space_group不同则照常解析(self):
        assert elements_from_db_formula("O Zn", space_group="P 63 m c") == {"O", "Zn"}

    def test_忽略两端空白(self):
        assert elements_from_db_formula(
            "  P 63 m c ", space_group="P 63 m c"
        ) == set()

    def test_space_group为空时不启用该判定(self):
        assert elements_from_db_formula("P 63 m c", space_group="") == {"P"}


# ──────────────────────────────────────────────────────────────
# ② cod_local: CIF 取式 / 可信判定 / 公式回退 / 索引门槛
# ──────────────────────────────────────────────────────────────
_BRU = """data_9004178
_chemical_formula_sum            'O Zn'
_chemical_name_mineral           Zincite
_cod_database_code               9004178
"""

_UNQUOTED = """data_x
_chemical_formula_sum   O2 Ti
"""

_TEXT_BLOCK = """data_y
_chemical_formula_sum
; Mg O4 Sc2
;
"""


class TestFormulaSumFromCif:

    @pytest.mark.parametrize("text,expected", [
        (_BRU, "O Zn"),
        (_UNQUOTED, "O2 Ti"),
        (_TEXT_BLOCK, "Mg O4 Sc2"),
        ("", ""),
        ("data_z\n_space_group_name_H-M 'P 1'\n", ""),
        ("_chemical_formula_sum   ?\n", ""),
    ], ids=["单引号", "无引号", "多行块", "空串", "缺标签", "问号占位"])
    def test_抽取与归一(self, text, expected):
        assert CL.formula_sum_from_cif(text) == expected

    def test_归一化与库内写法一致(self):
        """CIF 里 "Zn O" 这类非字母序写法要归一到库内 "O Zn"。"""
        assert CL.formula_sum_from_cif("_chemical_formula_sum 'Zn O'\n") == \
            normalize_cod_formula("ZnO")


class TestIsDbFormulaTrusted:

    @pytest.mark.parametrize("formula,sg,expected", [
        ("O Zn", "P 63 m c", True),
        ("O3 Zn0.64125", "R 3 m", True),
        ("", "P 1", False),
        ("   ", "", False),
        ("P 63 m c", "P 63 m c", False),      # 空间群覆盖
        ("C 1 2 1", "C 1 2 1", False),        # 形如化学式的空间群
        ("P 63 m c", "", True),               # 无 sg 佐证时不判定 (可能真含 P)
    ], ids=["正常", "小数", "空", "空白", "空间群覆盖", "含数字空间群", "无sg"])
    def test_判定(self, formula, sg, expected):
        assert CL.is_db_formula_trusted(formula, sg) is expected


def _conn_with_cif(rows) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE phases (cod_id INTEGER, cif_gz BLOB)")
    conn.executemany("INSERT INTO phases VALUES (?,?)", rows)
    conn.commit()
    return conn


class TestRecoverInorgFormula:

    def _blob(self, text: str) -> bytes:
        return gzip.compress(text.encode("utf-8"))

    def test_可信时原样返回_不查CIF(self):
        conn = _conn_with_cif([(1, self._blob(_BRU))])
        assert CL.recover_inorg_formula(conn, 1, "O Zn", "P 63 m c") == "O Zn"

    def test_被空间群覆盖时用CIF恢复(self):
        conn = _conn_with_cif([(9004178, self._blob(_BRU))])
        assert CL.recover_inorg_formula(
            conn, 9004178, "P 63 m c", "P 63 m c"
        ) == "O Zn"

    def test_无可信CIF时保留原值(self):
        conn = _conn_with_cif([(5, None)])
        assert CL.recover_inorg_formula(conn, 5, "P 63 m c", "P 63 m c") == "P 63 m c"

    def test_库无cif_gz列时不崩且保留原值(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE phases (cod_id INTEGER, formula TEXT)")
        conn.execute("INSERT INTO phases VALUES (7,'P 1')")
        conn.commit()
        assert CL.recover_inorg_formula(conn, 7, "P 63 m c", "P 63 m c") == "P 63 m c"

    def test_空CIF不返回空串(self):
        conn = _conn_with_cif([(9, self._blob("data_q\n_nothing 1\n"))])
        out = CL.recover_inorg_formula(conn, 9, "P 63 m c", "P 63 m c")
        assert out == "P 63 m c" and out


class TestUsableIndexFile:

    def test_不存在(self, tmp_path):
        assert CL._is_usable_index_file(tmp_path / "nope.sqlite") is False

    def test_空库被拒(self, tmp_path):
        p = tmp_path / "small.sqlite"
        sqlite3.connect(p).close()          # 0 条目、几 KB
        assert CL._is_usable_index_file(p) is False

    def test_达到门槛才接受(self, tmp_path):
        p = tmp_path / "ok.sqlite"
        with open(p, "wb") as f:
            f.write(b"\0" * (CL._MIN_VALID_DB_BYTES + 1))
        assert CL._is_usable_index_file(p) is True

    def test_None被拒(self):
        assert CL._is_usable_index_file(None) is False


# ──────────────────────────────────────────────────────────────
# ③ 扫描层 fail-open (元素约束下推)
# ──────────────────────────────────────────────────────────────
def _row(cod_id: str, formula: str, sg: str, ds, is_) -> tuple:
    return (cod_id, cod_id, cod_id, formula, sg, len(ds),
            ",".join(str(d) for d in ds), ",".join(str(i) for i in is_))


def _fake_db(rows) -> CIFDatabase:
    db = CIFDatabase(enable_cod_local=False)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE phases (cod_id TEXT, ref_id TEXT, display_id TEXT, "
        "formula TEXT, space_group TEXT, n_peaks INT, peaks_d TEXT, peaks_i TEXT)"
    )
    conn.executemany("INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    db._cod_conn = conn
    return db


_DS = [4.00, 2.50, 2.10]
_IS = [100.0, 60.0, 30.0]


class TestScanLayerFailOpen:
    """核心: formula 不可信时不能在扫描层按元素淘汰。"""

    def test_被空间群覆盖的相在元素过滤下被放行(self):
        db = _fake_db([
            _row("SG_OVERWRITTEN", "P 63 m c", "P 63 m c", _DS, _IS),
        ])
        got = db.search_cod_by_d_peaks(_DS, _IS, min_match=3,
                                       elements_allowed={"Zn", "O"})
        assert [r["cod_id"] for r in got] == ["SG_OVERWRITTEN"], \
            "formula 与空间群相同 → 放行 (旧实现在此淘汰, 真 ZnO 就是这样丢的)"

    def test_可信但不符化学的相仍被淘汰(self):
        db = _fake_db([
            _row("CA_O", "Ca1 O1", "P 1", _DS, _IS),
        ])
        got = db.search_cod_by_d_peaks(_DS, _IS, min_match=3,
                                       elements_allowed={"Zn", "O"})
        assert got == [], "可信 formula 且元素不符 → 必须照旧淘汰"

    def test_空formula也被放行(self):
        db = _fake_db([
            _row("EMPTY", "", "P 1", _DS, _IS),
        ])
        got = db.search_cod_by_d_peaks(_DS, _IS, min_match=3,
                                       elements_allowed={"Zn", "O"})
        assert [r["cod_id"] for r in got] == ["EMPTY"]

    def test_三种情形混在一起(self):
        db = _fake_db([
            _row("ZnO_ok", "O Zn", "P 63 m c", _DS, _IS),
            _row("SG_OVR", "P 63 m c", "P 63 m c", _DS, _IS),
            _row("CA_O", "Ca1 O1", "P 1", _DS, _IS),
        ])
        got = db.search_cod_by_d_peaks(_DS, _IS, min_match=3,
                                       elements_allowed={"Zn", "O"})
        ids = sorted(r["cod_id"] for r in got)
        assert ids == ["SG_OVR", "ZnO_ok"]

    def test_不传elements_allowed时全部保留(self):
        db = _fake_db([
            _row("A", "P 63 m c", "P 63 m c", _DS, _IS),
            _row("B", "Ca1 O1", "P 1", _DS, _IS),
        ])
        got = db.search_cod_by_d_peaks(_DS, _IS, min_match=3)
        assert sorted(r["cod_id"] for r in got) == ["A", "B"]


# ──────────────────────────────────────────────────────────────
# ④ search_structures 的 97-/96- 前缀 (旧实现把前缀数字也算进去)
# ──────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _cod_ready(), reason="COD 无机库不可用")
class TestSearchStructuresPrefixedId:

    @pytest.fixture(scope="class")
    def db(self):
        return CL.CODLocalDatabase()

    @pytest.mark.parametrize("query", ["9004178", "97-9004178", "96-9004178",
                                       "97 9004178"])
    def test_前缀形式与裸编号等价(self, db, query):
        got = db.search_structures(query, limit=5)
        assert got, f"{query!r} 应能查到记录 (旧实现: 97- 前缀会拼成 979004178)"
        assert 9004178 in [int(r["cod_id"]) for r in got]

    def test_不存在的编号返回空(self, db):
        # 用 cod_id 0: 全库编号从 1 起, 0 必不存在。
        # (不能用 "97-0000001": 它按 display_id 格式本就映射到 cod_id 1,
        #  而全库里 1 = Si 是真实存在的, 返回它才是正确行为)
        assert db.search_structures("97-0000000", limit=5) == []
        assert db.search_structures("96-000-0000", limit=5) == []


# ──────────────────────────────────────────────────────────────
# ⑤ 真实库护栏 (迁移后的状态)
# ──────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _cod_ready(), reason="COD 无机库不可用")
class TestLiveInorgDb:

    @pytest.fixture(scope="class")
    def conn(self):
        c = sqlite3.connect(f"file:{INORG_DB}?mode=ro", uri=True)
        c.text_factory = str
        c.row_factory = sqlite3.Row
        yield c
        c.close()

    def test_zincite_的formula已修正(self, conn):
        rows = conn.execute(
            "SELECT formula FROM phases WHERE cod_id IN "
            "(9004178, 9008877, 2300450, 9004179, 9004180, 9004181, 9011662)"
        ).fetchall()
        assert len(rows) == 7, "7 条 COD Zincite 都应在无机库里"
        for r in rows:
            assert r["formula"] == "O Zn", f"Zincite formula 未修正: {r['formula']!r}"

    def test_残余覆盖规模已收敛(self, conn):
        """迁移后 formula==space_group 应只剩「有护栏拦下」的少数条目。

        迁移前 609 条; 541 条可无歧义改写, 余下 68 条因 CIF 位点元素不被
        CIF 化学式覆盖 (R 3 m 类长石/云母, CIF 的 formula_sum 明显截断)
        而**刻意不改**。这里把上界钉住, 防止回归时静默变多。
        """
        n = conn.execute(
            "SELECT COUNT(*) FROM phases WHERE formula = space_group"
        ).fetchone()[0]
        assert n <= 72, f"formula==space_group 又涨到 {n} 条 (迁移前 609, 迁移后 72)"

    def test_meta里留有迁移痕迹(self, conn):
        row = conn.execute(
            "SELECT value FROM meta WHERE key='formula_fix'"
        ).fetchone()
        assert row is not None, "迁移应写入 meta.formula_fix"
        assert "count=" in row["value"]

    def test_get_cod_phase_返回可读名称与元素(self):
        """修复前: name/formula 都是 "P 63 m c", elements={'P'}。"""
        db = CIFDatabase(enable_cod_local=True)
        detail = db.get_cod_phase(9004178)
        assert detail is not None
        assert detail["formula"] == "O Zn"
        assert elements_from_db_formula(detail["formula"]) == {"O", "Zn"}
        assert detail["name"] if detail.get("name") else True

    def test_所有不可信条目的formula都不是空串(self, conn):
        """回退路径绝不产出空 formula (会毁掉名称与元素判定)。"""
        rows = conn.execute(
            "SELECT cod_id, formula FROM phases "
            "WHERE formula IS NULL OR TRIM(formula) = ''"
        ).fetchall()
        assert rows == [], f"出现空 formula: {[r['cod_id'] for r in rows[:10]]}"


# ──────────────────────────────────────────────────────────────
# ⑥ MCP 侧搜索 search_cod_phases 的编号前缀 (与 search_structures 同一类 bug)
# ──────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _cod_ready(), reason="COD 无机库不可用")
class TestSearchCodPhasesPrefixedId:
    """``CIFDatabase.search_cod_phases`` 经 MCP 暴露给外部调用方。

    旧实现: 第一个分支判 ``len(q_dash) == 15``, 但 ``display_id`` 实为
    ``"97-1011097"`` (10 字符) → 分支永假; "96-" 分支又拿带横杠的原串去比
    ``ref_id`` (11 字符) → 也落空。于是**两种官方编号写法都搜不到**。
    """

    @pytest.fixture(scope="class")
    def db(self):
        return CIFDatabase(enable_cod_local=True)

    @pytest.mark.parametrize("query", ["9004178", "97-9004178", "97 9004178",
                                       "96-900-4178", "969004178"])
    def test_各写法等价(self, db, query):
        got = db.search_cod_phases(query, limit=5)
        assert got, f"{query!r} 应能查到记录"
        assert 9004178 in [int(r["cod_id"]) for r in got]
        assert got[0]["formula"] == "O Zn"

    def test_带横杠编号不再落空(self, db):
        """回归锚点: 修复前 "97-1011097" 返回空列表。"""
        got = db.search_cod_phases("97-1011097", limit=3)
        assert [int(r["cod_id"]) for r in got] == [1011097]

    def test_不存在的编号返回空(self, db):
        # cod_id 0 必不在无机库里 (编号从 1000005 起)
        assert db.search_cod_phases("97-0000000", limit=5) == []


# ──────────────────────────────────────────────────────────────
# ⑦ 晶胞列修复 (scripts/repair_inorg_cell.py)
# ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(_ROOT / "scripts"))
import repair_inorg_cell as RC  # noqa: E402


class TestCellFromCif:
    """纯函数: CIF 文本 → 晶胞 6 参数 (缺失角按 CIF 语义取 90)。"""

    _CUBIC = """
_cell_length_a  8.875
_cell_angle_alpha 90.0
_cell_angle_beta  90.0
_cell_angle_gamma 90.0
"""

    def test_立方只给_a时_b_c补成_a(self):
        got = RC.cell_from_cif(self._CUBIC)
        assert got == {"a": 8.875, "b": 8.875, "c": 8.875,
                       "alpha": 90.0, "beta": 90.0, "gamma": 90.0}

    def test_六方(self):
        got = RC.cell_from_cif(
            "_cell_length_a 3.2494\n_cell_length_c 5.2038\n"
            "_cell_angle_gamma 120.0\n")
        assert got["a"] == 3.2494 and got["c"] == 5.2038
        assert got["b"] == 3.2494 and got["gamma"] == 120.0

    def test_标准差写法被剥离(self):
        got = RC.cell_from_cif("_cell_length_a 5.189(10)\n")
        assert got["a"] == pytest.approx(5.189)

    def test_缺_a视为不可用(self):
        assert RC.cell_from_cif("_cell_length_c 5.0\n") is None
        assert RC.cell_from_cif("") is None
        assert RC.cell_from_cif("_cell_length_a 0\n") is None


class TestCellSame:
    """容差判据: 文档化的 0.5% 相对容差; NULL/垃圾值一律视为需修。"""

    def test_容差内视为一致(self):
        assert RC._same("9.7399", 9.7397)
        assert RC._same("11.2176", 11.217)

    def test_真实偏差判为不一致(self):
        assert not RC._same("10.3702", 5.189)   # 恰好 2 倍
        assert not RC._same("10.35", 19.887)

    def test_空值与非有限值判为不一致(self):
        assert not RC._same(None, 90.0)
        assert not RC._same("", 5.0)
        assert not RC._same("6.365987374e-314", 90.0)   # denormal 垃圾
        assert not RC._same("nan", 5.0)

    def test_浮点垃圾不再被当成有限值放过(self):
        # 旧审计脚本的坑: denormal 是有限数, 会被 abs(a-b)/b 判成一致
        assert not RC._same(6.365987374e-314, 90.0)


@pytest.mark.skipif(not _cod_ready(), reason="COD 无机库不可用")
class TestLiveInorgCell:
    """迁移后的真实库护栏。"""

    @pytest.fixture(scope="class")
    def conn(self):
        c = sqlite3.connect(f"file:{INORG_DB}?mode=ro", uri=True)
        c.text_factory = str
        c.row_factory = sqlite3.Row
        yield c
        c.close()

    def test_已知错值行已用CIF值改写(self, conn):
        """这三行的库值原本分别是 2 倍 / float 垃圾 / NULL。"""
        want = {
            1000042: (5.189, 20.09698),     # 原 10.3702 (恰好 2×), c 恰好一致
            1000005: (11.217, 19.887),      # 原 c=10.35(浮点垃圾), a 恰好一致
            1000009: (9.6808, 5.218),       # 原 c=NULL
        }
        for cid, (a, c) in want.items():
            r = conn.execute("SELECT cell_a, cell_c FROM phases WHERE cod_id=?",
                             (cid,)).fetchone()
            assert r is not None, f"{cid} 不在库"
            assert r["cell_a"] == pytest.approx(a, rel=1e-4), cid
            assert r["cell_c"] == pytest.approx(c, rel=1e-4), cid

    def test_zincite晶胞保持不变(self, conn):
        r = conn.execute("SELECT cell_a, cell_c FROM phases WHERE cod_id=9004178"
                         ).fetchone()
        assert r["cell_a"] == pytest.approx(3.2494, rel=1e-4)
        assert r["cell_c"] == pytest.approx(5.2038, rel=1e-4)

    def test_角度不再有垃圾值(self, conn):
        """合法角度必在 (0, 180]; 迁移前有 471 行是 denormal。"""
        n = conn.execute(
            "SELECT COUNT(*) FROM phases WHERE cell_alpha IS NOT NULL "
            "AND (cell_alpha <= 1.0 OR cell_alpha > 180.0 "
            "     OR cell_beta <= 1.0 OR cell_beta > 180.0 "
            "     OR cell_gamma <= 1.0 OR cell_gamma > 180.0)"
        ).fetchone()[0]
        assert n <= 43, f"仍有 {n} 行角度非法 (仅无 CIF 的 43 行允许保留)"

    def test_有CIF的行晶胞与CIF一致(self, conn):
        """抽样复核: 与迁移脚本同一套判据, 任何一行都不该再被判为需修。

        抽 400 行 (取 cod_id 最小的, 即迁移前偏差最密集的一段) 以免全库
        扫描拖慢测试。
        """
        rows = conn.execute(
            "SELECT cod_id, cell_a, cell_b, cell_c, cell_alpha, cell_beta, "
            "cell_gamma, cif_gz FROM phases WHERE cif_gz IS NOT NULL "
            "ORDER BY cod_id LIMIT 400"
        ).fetchall()
        assert len(rows) == 400
        bad = []
        for r in rows:
            txt = gzip.decompress(r["cif_gz"]).decode("utf-8", "replace")
            new = RC.cell_from_cif(txt)
            if new is None:
                continue
            cur = (r["cell_a"], r["cell_b"], r["cell_c"],
                   r["cell_alpha"], r["cell_beta"], r["cell_gamma"])
            vals = (new["a"], new["b"], new["c"],
                    new["alpha"], new["beta"], new["gamma"])
            if not all(RC._same(c, v) for c, v in zip(cur, vals)):
                bad.append(r["cod_id"])
        assert not bad, f"这些行仍与 CIF 不一致: {bad[:10]}"

    def test_meta里留有晶胞修复痕迹(self, conn):
        row = conn.execute("SELECT value FROM meta WHERE key='cell_fix'").fetchone()
        assert row is not None, "迁移应写入 meta.cell_fix"
        assert "count=" in row["value"]
