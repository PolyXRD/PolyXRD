"""
PDF2-2004 空间群 / 晶胞映射测试
================================
覆盖 2026-09-10 补齐的类型 3 (空间群) / A (Pearson) / D (约化晶胞) /
E (常规晶胞) 子记录解析。分两层:

A. 合成记录 (不依赖真实数据文件, 永远运行):
   列位、设置字母、未定空间群的 Bravais 字母陷阱、体积字段的小数点判据、
   名称/矿物名的标志区区分、建库哨兵 vol_mismatch、get_lattice 往返。

B. 真实库 (cod_data/PDF2_2004.sqlite 在则跑, 否则 skip):
   方解石 010837 全字段、覆盖率下限、vol_mismatch=0、晶系一致性 100%、
   名称检索、identify_with_pdf2 带回空间群与晶胞。

真实文件没有时整组 skip —— 保持 CI 可跑。

⚠️ 类型 3 的 Z 与密度字段**故意不入库** (同一卡片内 Z 与 Dx 可能出自不同
晶胞基准, 约 20% 无解)。本文件含 `test_type3_z_and_density_not_stored`
守住这个决定, 免得日后有人"顺手"把它们加回来。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

WL = 1.5406
_PDF2_WL = 80

_REAL_DB = Path(__file__).resolve().parents[1] / "cod_data" / "PDF2_2004.sqlite"
_RAW_DAT = Path(r"E:\TEMP\XRD-PDF2-2004\pdf2 - 2004.dat")

requires_real_db = pytest.mark.skipif(
    not _REAL_DB.exists(),
    reason="真实 PDF2-2004 索引库不存在 (需自备 pdf2 - 2004.dat 建库)",
)
requires_raw_dat = pytest.mark.skipif(
    not _RAW_DAT.exists(),
    reason="PDF-2 2004 原始 .dat 不存在 (仅本机有)",
)


# ── 合成记录工具 (与 test_pdf2_database.py 同口径, 独立复制以免耦合) ──

def _line(data: str, rec_id: str) -> str:
    """一条 80 字符定宽 field: 数据 0~70 列, 标记固定从第 71 列起。"""
    return data[:71].ljust(71) + rec_id[:9]


def _raw_line(data: str, flag: str, rec_id: str) -> str:
    """带 cols 67~70 标志区的一行 (标志区不能混进数据区)。"""
    assert len(flag) <= 4
    assert len(data) <= 67
    return data.ljust(67) + flag.ljust(4) + rec_id[:9]


def _xi_line(pairs, rec_id: str = "P010001XI") -> str:
    """XI 行: 3 对 d(7字符)+I(3字符), 列偏移 0/23/46"""
    buf = [" "] * _PDF2_WL
    for idx, (d, i) in enumerate(pairs):
        off = (0, 23, 46)[idx]
        s = f"{d:7.3f}{int(round(i)):3d}"
        buf[off:off + len(s)] = list(s)
    return _line("".join(buf).rstrip(), rec_id)


def _xi_lines(pairs, rec_id: str = "P010001XI") -> list[str]:
    """按真实布局每行 3 对切成若干 XI 行。"""
    return [_xi_line(pairs[i:i + 3], rec_id) for i in range(0, len(pairs), 3)]


def _rec(lines_body: list[str], pdf2_id: int = 10837, seq: str = "R") -> list[str]:
    """把若干子记录行包成一条完整记录 (加 X1 头与 XK 尾)。"""
    rid = f"P{pdf2_id:06d}{seq}"
    return [_line("", f"{rid}1")] + lines_body + [_line("", f"{rid}K")]


def _build(tmp_path, lines: list[str], name: str = "pdf2.dat"):
    from polyxrd.services.pdf2_database import PDF2Database, PDF2DatabaseBuilder

    raw = tmp_path / name
    raw.write_bytes("".join(lines).encode("ascii"))
    db_path = tmp_path / (name + ".sqlite")
    stats = PDF2DatabaseBuilder(raw, db_path).build()
    return PDF2Database(db_path), stats


# 真实方解石 D010837R3 行 (逐字符来自 pdf2 - 2004.dat)
CALCITE_R3 = "R-3c       167          2     2.710                            365.97"
# 真实方解石 D010837RE 行 (常规晶胞)
CALCITE_RE = "   4.983   4.983  17.019  90.00  90.00 120.00   3.4154"
# 真实方解石 D010837RD 行 (约化晶胞 + 末列无关键序号)
CALCITE_RD = "   4.983   4.983   6.361  66.94  66.94  60.00   121.99            9"


# ════════════════════════════════════════════════════════════
# A. 合成记录
# ════════════════════════════════════════════════════════════

def test_type3_columns_symbol_number_setting():
    """类型 3: 符号在 0~7 列, 空间群号在 11~13 列, 设置字母在第 14 列。"""
    from polyxrd.services.pdf2_database import _parse_symmetry_line, _PDF2Record

    rec = _PDF2Record()
    _parse_symmetry_line(CALCITE_R3, rec)
    assert rec.space_group == "R-3c"
    assert rec.space_group_num == 167
    assert rec.space_group_setting == ""
    assert rec.cell_vol == pytest.approx(365.97)

    # 设置字母: 14A = P21/c, 14B = P21/a (同一空间群号的不同设置)
    rec2 = _PDF2Record()
    _parse_symmetry_line(
        "P21/c       14A         4     2.410                           1245.13", rec2)
    assert (rec2.space_group, rec2.space_group_num, rec2.space_group_setting) == (
        "P21/c", 14, "A")

    rec3 = _PDF2Record()
    _parse_symmetry_line(
        "P21/a       14B                                               2645.77", rec3)
    assert (rec3.space_group, rec3.space_group_num, rec3.space_group_setting) == (
        "P21/a", 14, "B")
    assert rec3.cell_vol == pytest.approx(2645.77)


def test_unknown_space_group_not_taken_as_bravais_letter():
    """回归: 空间群号为 0 时, 0~7 列是 Bravais 点阵字母, 不是空间群。

    真实样本 (卡片 090364 / 011110): `B       E    0         16` —— 若照收
    就会得到 space_group="B", 把点阵符号当成空间群 (且与号 0 自相矛盾)。
    实测 44,637 条无空间群的记录都靠这条判据分流。
    """
    from polyxrd.services.pdf2_database import _parse_symmetry_line, _PDF2Record

    for sym, line in (
        ("B", "B       E    0         16                                     1025.47"),
        ("F", "F            0          8E                                     588.90"),
        ("I", "I            0          2E                                    1789.63"),
        ("",  "             0                                                1763.95"),
    ):
        rec = _PDF2Record()
        _parse_symmetry_line(line, rec)
        assert rec.space_group == "", f"点阵字母 {sym!r} 被误当空间群"
        assert rec.space_group_num == 0


def test_type3_volume_only_from_decimal_field():
    """体积判据 = 末字段含小数点。

    纯整数末字段是 Z (如 `P21/m  11  4` 表示空间群 11 + Z=4), 不能当体积;
    真实报告体积一律写成两位小数。
    """
    from polyxrd.services.pdf2_database import _parse_symmetry_line, _PDF2Record

    rec = _PDF2Record()
    _parse_symmetry_line("P21/m       11          4", rec)
    assert rec.space_group == "P21/m" and rec.space_group_num == 11
    assert rec.cell_vol is None, "Z=4 被误当成了晶胞体积"

    rec2 = _PDF2Record()
    _parse_symmetry_line("Pmnm        59C         2                                       94.67", rec2)
    assert rec2.cell_vol == pytest.approx(94.67)


def test_type3_z_and_density_not_stored():
    """守住决定: Z 与密度字段不入库。

    实测 45,557 条"约化胞 ≠ 常规胞"的卡片中, 约 20% 无法用任何单一晶胞
    自洽复现 Dx (如刚玉 Al2O3 报 Z=2, 而 Dx=3.97 是按 Z=6 的六方胞算的)。
    存下来只会误导按密度筛选的下游。
    """
    from polyxrd.services.pdf2_database import _parse_symmetry_line, _PDF2Record
    from polyxrd.services.pdf2_database import _SCHEMA_SQL

    rec = _PDF2Record()
    _parse_symmetry_line(
        "Pmmm        47          4     1.850   1.856                    496.88", rec)
    assert rec.cell_vol == pytest.approx(496.88)
    for attr in ("z_reduced", "density_x", "density_m"):
        assert not hasattr(rec, attr), f"记录不应再有 {attr} 字段"
    for col in ("z_reduced", "density_x", "density_m"):
        assert col not in _SCHEMA_SQL


def test_typeE_conventional_cell_parsed():
    from polyxrd.services.pdf2_database import _parse_cell_fields

    cell = _parse_cell_fields(CALCITE_RE, 6)
    assert cell == pytest.approx((4.983, 4.983, 17.019, 90.0, 90.0, 120.0))
    # 用六个参数算出的体积必须等于 X3 报告的 365.97 (这是列位解读的哨兵)
    assert _cell_volume(*cell) == pytest.approx(365.97, rel=0.002)


def test_typeD_reduced_cell_and_trailing_serial():
    """类型 D 末列是与数据无关的序号, 体积在第 7 个 token。"""
    from polyxrd.services.pdf2_database import _parse_cell_fields, _num

    cell = _parse_cell_fields(CALCITE_RD, 6)
    assert cell == pytest.approx((4.983, 4.983, 6.361, 66.94, 66.94, 60.0))
    toks = CALCITE_RD.split()
    assert _num(toks[6]) == pytest.approx(121.99)
    assert _cell_volume(*cell) == pytest.approx(121.99, rel=0.002)


def test_pearson_and_name_mineral_tags():
    """类型 A = Pearson; 类型 6 的名称按 cols 67~68 的类别分流。"""
    from polyxrd.services.pdf2_database import parse_pdf2_record

    body = [
        _line(CALCITE_R3, "P010837R3"),
        _raw_line("Calcium Carbonate Oxide", " P 1", "P010837R6"),
        _raw_line("Calcite", " M 2", "P010837R6"),
        _line("hR   3.33", "P010837RA"),
        _line(CALCITE_RE, "P010837RE"),
        _line(CALCITE_RD, "P010837RD"),
        _xi_line([(3.86, 8), (3.04, 100), (2.49, 20)], "P010837RI"),
    ]
    rec = parse_pdf2_record(_rec(body), offset=0)
    assert rec is not None
    assert rec.pearson == "hR"
    assert rec.name == "Calcium Carbonate Oxide"     # P 类
    assert rec.mineral == "Calcite"                  # M 类, 不覆盖 name
    assert rec.space_group == "R-3c" and rec.space_group_num == 167
    assert (rec.cell_a, rec.cell_c, rec.cell_gamma) == (4.983, 17.019, 120.0)
    assert rec.red_vol == pytest.approx(121.99)
    # 常规胞体积来自六个参数自算, 与报告值一致
    assert rec.cell_vol == pytest.approx(365.97, rel=0.002)


def test_build_sentinel_flags_volume_mismatch(tmp_path):
    """建库哨兵: 报告体积与六参数算出的体积差 >2% 时计数并改用自算值。

    这是解析布局的报警器 —— 列位一旦读错, 该计数会从 0 跳到几万。
    """
    body = [
        _line(CALCITE_R3.replace("365.97", "999.99"), "P010837R3"),
        _line(CALCITE_RE, "P010837RE"),
        _xi_line([(3.04, 100), (2.49, 20), (2.28, 15)], "P010837RI"),
    ]
    db, stats = _build(tmp_path, _rec(body))
    assert stats["vol_mismatch"] == 1
    d = db.get_phase(10837)
    # 采用自算体积 (365.97), 而不是行里那个错误的 999.99
    assert d["cell_vol"] == pytest.approx(365.97, rel=0.002)


def test_build_coverage_counters(tmp_path):
    """建库统计里 with_cell / with_sg / sg_unknown / with_name 的计数。"""
    ok = _rec([
        _line(CALCITE_R3, "P010837R3"),
        _raw_line("Calcium Carbonate Oxide", " P 1", "P010837R6"),
        _raw_line("Calcite", " M 2", "P010837R6"),
        _line(CALCITE_RE, "P010837RE"),
        _xi_line([(3.04, 100), (2.49, 20), (2.28, 15)], "P010837RI"),
    ], pdf2_id=10837)
    # 无空间群、无晶胞的卡片 090364 形态
    no_sg = _rec([
        _line("B       E    0         16                                     1025.47",
              "P090364X3"),
        _raw_line("Barium Nitrate", " P 1", "P090364X6"),
        _xi_line([(3.60, 100), (2.60, 40), (2.10, 25)], "P090364XI"),
    ], pdf2_id=90364, seq="X")
    db, stats = _build(tmp_path, ok + no_sg)
    assert stats["total"] == 2 and stats["ok"] == 2
    assert stats["with_cell"] == 1
    assert stats["with_sg"] == 1
    assert stats["sg_unknown"] == 1
    assert stats["with_name"] == 2
    assert stats["vol_mismatch"] == 0


def test_get_lattice_and_search_by_name(tmp_path):
    """get_lattice 供 Rietveld 精修取起始晶胞; 名称/矿物名可被检索。"""
    from polyxrd.models.phase import LatticeParams

    body = [
        _line(CALCITE_R3, "P010837R3"),
        _raw_line("Calcium Carbonate Oxide", " P 1", "P010837R6"),
        _raw_line("Calcite", " M 2", "P010837R6"),
        _line(CALCITE_RE, "P010837RE"),
        _line(CALCITE_RD, "P010837RD"),
        _xi_line([(3.04, 100), (2.49, 20), (2.28, 15)], "P010837RI"),
    ]
    db, _ = _build(tmp_path, _rec(body))

    lat = db.get_lattice(10837)
    assert isinstance(lat, LatticeParams)
    assert (lat.a, lat.c, lat.gamma) == (4.983, 17.019, 120.0)
    assert lat.volume == pytest.approx(366.0, rel=0.01)
    assert db.get_lattice(999999) is None

    assert db.search_phases("Calcite")[0]["cod_id"] == 10837
    assert db.search_phases("Calcium Carbonate Oxide")[0]["cod_id"] == 10837
    assert len(db.search_phases("10837")) == 1


def test_identify_with_pdf2_carries_space_group_and_lattice(tmp_path, monkeypatch):
    """PDF2 命中必须把空间群与晶胞带到 Phase 上 (精修起始值 / GUI 展示)。"""
    import polyxrd.services.pdf2_database as pd2
    import polyxrd.services.phase_identifier as pim
    from polyxrd.models.xrd_data import XRDData
    import numpy as np

    body = [
        _line(CALCITE_R3, "P010837R3"),
        _raw_line("Calcium Carbonate Oxide", " P 1", "P010837R6"),
        _raw_line("Calcite", " M 2", "P010837R6"),
        _line(CALCITE_RE, "P010837RE"),
        *_xi_lines([(3.86, 8), (3.04, 100), (2.49, 20), (2.28, 15),
                    (2.09, 18), (1.92, 25), (1.87, 20)], "P010837RI"),
    ]
    db, _ = _build(tmp_path, _rec(body))
    real_cls = pd2.PDF2Database
    monkeypatch.setattr(
        pd2, "PDF2Database",
        lambda db_path=None: real_cls(db_path=getattr(db, "_db_path")),
    )

    tt = np.arange(10.0, 70.0, 0.02)
    y = np.full_like(tt, 20.0)
    for d, amp in ((3.86, 8), (3.04, 100), (2.49, 20), (2.28, 15),
                   (2.09, 18), (1.92, 25), (1.87, 20)):
        c = 2.0 * math.degrees(math.asin(WL / (2.0 * d)))
        y += amp * np.exp(-0.5 * ((tt - c) / 0.085) ** 2)
    y += np.random.default_rng(3).normal(0, 0.4, size=tt.size)

    res = pim.PhaseIdentifier().identify_with_pdf2(
        XRDData(two_theta=tt, intensity=y, wavelength=WL), peaks=None, top_n=5)
    assert res, "未识别出任何物相"
    top = res[0].phase
    assert top.space_group == "R-3c"
    assert "Calcite" in top.name, top.name
    assert top.lattice is not None, "PDF2 命中未带回晶胞 → 精修只能从默认胞起步"
    assert top.lattice.c == pytest.approx(17.019, rel=0.01)


def _cell_volume(a, b, c, al, be, ga) -> float:
    ca, cb, cg = (math.cos(math.radians(x)) for x in (al, be, ga))
    return a * b * c * math.sqrt(1 - ca * ca - cb * cb - cg * cg + 2 * ca * cb * cg)


# ════════════════════════════════════════════════════════════
# B. 真实库
# ════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def real_db():
    from polyxrd.services.pdf2_database import PDF2Database
    return PDF2Database(_REAL_DB)


@requires_real_db
def test_real_calcite_full_mapping(real_db):
    """方解石 010837 = ICDD 卡片的标准参照 (R-3c / 167 / a=4.983 / c=17.019)。"""
    p = real_db.get_phase(10837)
    assert p["space_group"] == "R-3c"
    assert p["space_group_num"] == 167
    assert p["mineral"] == "Calcite"
    assert p["name"] == "Calcium Carbonate Oxide"
    assert p["pearson"] == "hR"
    assert (p["cell_a"], p["cell_b"], p["cell_c"]) == (4.983, 4.983, 17.019)
    assert (p["cell_alpha"], p["cell_beta"], p["cell_gamma"]) == (90.0, 90.0, 120.0)
    assert p["cell_vol"] == pytest.approx(365.97, rel=0.002)
    # 约化胞 (菱面体原胞) 与常规胞不同, 体积应为 1/3
    assert p["red_vol"] == pytest.approx(121.99, rel=0.002)
    assert p["cell_vol"] / p["red_vol"] == pytest.approx(3.0, abs=0.02)

    lat = real_db.get_lattice(10837)
    assert lat is not None and lat.volume == pytest.approx(366.0, rel=0.01)


@requires_real_db
def test_real_coverage_floors(real_db):
    """覆盖率下限 (163,834 相): 晶胞 ≥80%, 空间群 ≥70%, 名称 ≥99%。"""
    cov = real_db.coverage()
    assert cov["total"] >= 163_000
    assert cov["pct_cell"] >= 80.0, cov
    assert cov["pct_space_group"] >= 70.0, cov
    assert cov["name"] >= 0.99 * cov["total"], cov
    assert cov["mineral"] >= 10_000, cov


@requires_real_db
def test_real_volume_sentinel_range(real_db):
    """建库哨兵 vol_mismatch 必须落在合理区间 (≈986 / 133,935 = 0.74%)。

    列位读错时该计数会从 ~986 跳到几万 (2026-09-10 就靠它发现类型 3 的
    体积字段落在 63~68 列、被 67 列截断而整体丢失)。
    """
    st = real_db.stats()
    assert st["with_cell"] >= 130_000, st
    assert st["vol_mismatch"] <= 0.01 * st["with_cell"], st


@requires_raw_dat
def test_real_volume_disagreement_is_bimodal():
    """从原始 .dat 回读, 验证报告体积与 E 胞自算体积的偏差是**双峰**的。

    99.264% 精确吻合 (<0.5%), 0.736% 差 >10% (ICDD 报告体积按菱面体原胞
    或超胞口径给出), **中间 0.5~10% 一条都没有** —— 这条比任何单点断言
    都更能区分"数据口径差异"与"列位解析错误" (后者会糊在中间带)。
    """
    import collections

    from polyxrd.services.pdf2_database import iter_pdf2_records
    from polyxrd.utils.math_utils import lattice_volume

    buckets = collections.Counter()
    for rec in iter_pdf2_records(_RAW_DAT):
        if not (rec.cell_a and rec.cell_b and rec.cell_c and rec.cell_vol):
            continue
        v = lattice_volume(rec.cell_a, rec.cell_b, rec.cell_c,
                           rec.cell_alpha or 90.0, rec.cell_beta or 90.0,
                           rec.cell_gamma or 90.0)
        if not (v > 0):
            continue
        rel = abs(rec.cell_vol - v) / v
        if rel < 0.005:
            buckets["exact"] += 1
        elif 0.02 < rel < 0.10:
            buckets["mid"] += 1
        else:
            buckets["off"] += 1

    total = sum(buckets.values())
    assert total >= 130_000, buckets
    assert buckets["mid"] == 0, (
        f"{buckets['mid']} 条落在 2~10% 中间带 → 疑似列位读偏而非数据口径差异")
    assert buckets["exact"] >= 0.99 * total, buckets
    assert buckets["off"] >= 900, buckets       # 已知的 ICDD 口径差异, 不该消失


@requires_real_db
def test_real_crystal_system_consistency(real_db):
    """空间群号所属晶系 == Pearson 符号所属晶系 (119,197 条应 100% 一致)。

    若空间群号取自错误列位 (例如读到了标志区或 Z 字段), 这条会大面积失败。
    三角晶系 (143~167) 归入 h (与 hR 一致)。
    """
    def sys_of_sg(n: int) -> str:
        if n <= 2:
            return "a"
        if n <= 15:
            return "m"
        if n <= 74:
            return "o"
        if n <= 142:
            return "t"
        if n <= 194:
            return "h"
        return "c"

    conn = real_db._get_conn()
    rows = conn.execute(
        "SELECT space_group_num, pearson FROM phases "
        "WHERE space_group_num > 0 AND pearson IS NOT NULL AND pearson <> ''"
    ).fetchall()
    assert len(rows) >= 100_000
    bad = []
    for r in rows:
        pl = (r["pearson"] or "")[:1].lower()
        pl = "h" if pl == "r" else pl
        if pl in "amothc" and sys_of_sg(r["space_group_num"]) != pl:
            bad.append((r["space_group_num"], r["pearson"]))
    assert not bad, f"{len(bad)} 条晶系不一致, 前 10: {bad[:10]}"


@requires_real_db
def test_real_space_group_symbol_sanity(real_db):
    """有空间群号的记录, 符号非空且以点阵字母开头; 含未定字符的占少数。"""
    conn = real_db._get_conn()
    empty = conn.execute(
        "SELECT COUNT(*) FROM phases WHERE space_group_num > 0 "
        "AND (space_group IS NULL OR space_group = '')"
    ).fetchone()[0]
    assert empty == 0

    bad_head = conn.execute(
        "SELECT COUNT(*) FROM phases WHERE space_group_num > 0 "
        "AND SUBSTR(space_group, 1, 1) NOT IN "
        "('P','A','B','C','I','F','R')"
    ).fetchone()[0]
    assert bad_head == 0

    total = conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
    uncertain = conn.execute(
        "SELECT COUNT(*) FROM phases WHERE space_group LIKE '%*%' "
        "OR space_group LIKE '%,%'"
    ).fetchone()[0]
    # 实测含未定字符的是少数 (ICDD 用 '*'/',' 占位无法确定的下标)
    assert uncertain < 0.05 * total, f"{uncertain}/{total} 符号含未定字符"


@requires_real_db
def test_real_identify_returns_lattice(real_db, monkeypatch):
    """真实库跑一次方解石谱: 命中相带空间群 + 晶胞。"""
    import numpy as np
    import polyxrd.services.pdf2_database as pd2
    import polyxrd.services.phase_identifier as pim
    from polyxrd.models.xrd_data import XRDData

    real_cls = pd2.PDF2Database
    monkeypatch.setattr(
        pd2, "PDF2Database", lambda db_path=None: real_cls(db_path=_REAL_DB))

    tt = np.arange(10.0, 70.0, 0.02)
    y = np.full_like(tt, 20.0)
    for d, amp in ((3.86, 8), (3.04, 100), (2.49, 20), (2.28, 15),
                   (2.09, 18), (1.92, 25), (1.87, 20), (1.60, 16),
                   (1.51, 12), (1.48, 5), (1.44, 8), (1.43, 5)):
        c = 2.0 * math.degrees(math.asin(WL / (2.0 * d)))
        y += amp * np.exp(-0.5 * ((tt - c) / 0.085) ** 2)
    y += np.random.default_rng(5).normal(0, 0.4, size=tt.size)

    res = pim.PhaseIdentifier().identify_with_pdf2(
        XRDData(two_theta=tt, intensity=y, wavelength=WL), peaks=None,
        element_filter={"must_have": ["Ca", "C", "O"]}, top_n=5)
    assert res
    top = res[0].phase
    assert top.space_group == "R-3c", top.space_group
    assert top.lattice is not None
    assert top.lattice.a == pytest.approx(4.983, rel=0.05)
    assert top.lattice.c == pytest.approx(17.019, rel=0.05)
