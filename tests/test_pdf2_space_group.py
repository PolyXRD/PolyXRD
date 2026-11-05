"""
PDF2-2004 空间群 / 晶胞映射测试
================================
覆盖类型 3（空间群）/ A（Pearson）/ D（约化晶胞）/ E（常规晶胞）子记录的
列位解析，以及这些字段经 polyDB 落盘后的往返。

A. 合成记录（不依赖真实数据文件，永远运行）：
   列位、设置字母、未定空间群的 Bravais 字母陷阱、体积字段的小数点判据、
   名称/矿物名的标志区区分、polyDB 建库哨兵 vol_mismatch、晶胞往返。
B. 真实库（``cod_data/PDF2-2004.polyDB`` 在则跑，否则 skip）：
   方解石 010837 全字段、覆盖率下限、体积哨兵区间、双峰偏差、名称检索。

⚠️ 类型 3 的 Z 与密度字段**故意不入库**（同一卡片内 Z 与 Dx 可能出自不同
晶胞基准，约 20% 无解）。``test_type3_z_and_density_not_stored`` 守住这个
决定，免得日后有人"顺手"把它们加回来。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.build_pdf2_polydb import build as build_polydb  # noqa: E402

WL = 1.5406
_PDF2_WL = 80

_REAL_DB = ROOT / "cod_data" / "PDF2-2004.polyDB"
_RAW_DAT = Path(r"C:\pdf2\pdf2.dat")

requires_real_db = pytest.mark.skipif(
    not _REAL_DB.exists(),
    reason="真实 PDF2-2004 polyDB 不存在（先跑 scripts/build_pdf2_polydb.py）",
)
requires_raw_dat = pytest.mark.skipif(
    not _RAW_DAT.exists(),
    reason="PDF-2 2004 原始 pdf2.dat 不存在（仅授权机器有）",
)


# ── 合成记录工具（与 test_pdf2_database.py 同口径，独立复制以免耦合） ──

def _line(data: str, rec_id: str) -> str:
    """一条 80 字符定宽 field：数据 0~70 列，标记固定从第 71 列起。"""
    return data[:71].ljust(71) + rec_id[:9]


def _raw_line(data: str, flag: str, rec_id: str) -> str:
    """带 cols 67~70 标志区的一行（标志区不能混进数据区）。"""
    assert len(flag) <= 4
    assert len(data) <= 67
    return data.ljust(67) + flag.ljust(4) + rec_id[:9]


def _xi_line(pairs, rec_id: str = "P010001XI") -> str:
    buf = [" "] * _PDF2_WL
    for idx, (d, i) in enumerate(pairs):
        off = (0, 23, 46)[idx]
        s = f"{d:7.3f}{int(round(i)):3d}"
        buf[off:off + len(s)] = list(s)
    return _line("".join(buf).rstrip(), rec_id)


def _xi_lines(pairs, rec_id: str = "P010001XI") -> list[str]:
    return [_xi_line(pairs[i:i + 3], rec_id) for i in range(0, len(pairs), 3)]


def _rec(lines_body: list[str], pdf2_id: int = 10837, seq: str = "R") -> list[str]:
    rid = f"P{pdf2_id:06d}{seq}"
    return [_line("", f"{rid}1")] + lines_body + [_line("", f"{rid}K")]


def _build(tmp_path, lines: list[str], name: str = "pdf2.dat"):
    """合成流 → polyDB，返回 (PolyDatabase, meta)。"""
    from polyxrd.services.polydb import PolyDatabase

    raw = tmp_path / name
    raw.write_bytes("".join(lines).encode("ascii"))
    out = tmp_path / (name + ".polyDB")
    meta = build_polydb(raw, out, progress=lambda *a, **k: None)
    return PolyDatabase(out), meta


# 真实方解石 D010837R3 行（逐字符来自 pdf2.dat）
CALCITE_R3 = "R-3c       167          2     2.710                            365.97"
# 真实方解石 D010837RE 行（常规晶胞）
CALCITE_RE = "   4.983   4.983  17.019  90.00  90.00 120.00   3.4154"
# 真实方解石 D010837RD 行（约化晶胞 + 末列无关键序号）
CALCITE_RD = "   4.983   4.983   6.361  66.94  66.94  60.00   121.99            9"


# ════════════════════════════════════════════════════════════
# A. 合成记录
# ════════════════════════════════════════════════════════════

def test_type3_columns_symbol_number_setting():
    """类型 3：符号在 0~7 列，空间群号在 11~13 列，设置字母在第 14 列。"""
    from polyxrd.services.pdf2_scan import PDF2Record, _parse_symmetry_line

    rec = PDF2Record()
    # 列位与真实行一致：符号 0~7 / 标志 8~10 / 号 11~13（右对齐）/ 设置字母 14
    sym_user = f"{'P 21/c':<8}{'':3}{14:>3}A" + "         4            160.24"
    _parse_symmetry_line(sym_user, rec)
    assert rec.space_group == "P 21/c"
    assert rec.space_group_num == 14
    assert rec.space_group_setting == "A"

    rec2 = PDF2Record()
    _parse_symmetry_line("Pmnm        59C         2                                       94.67", rec2)
    assert rec2.cell_vol == pytest.approx(94.67)


def test_unknown_space_group_not_taken_as_bravais_letter():
    """号 = 0 时 0~7 列是 Bravais 点阵字母，不能当空间群符号收下。"""
    from polyxrd.services.pdf2_scan import PDF2Record, _parse_symmetry_line

    rec = PDF2Record()
    _parse_symmetry_line(
        "F           0         16                                     1025.47", rec)
    assert rec.space_group == ""
    assert rec.space_group_num == 0
    assert rec.cell_vol == pytest.approx(1025.47)


def test_type3_volume_only_from_decimal_field():
    """体积判据 = 末字段含小数点（Z 是纯整数，不能当体积）。"""
    from polyxrd.services.pdf2_scan import PDF2Record, _parse_symmetry_line

    rec = PDF2Record()
    _parse_symmetry_line("Pmmm        47          4", rec)
    assert rec.cell_vol is None


def test_type3_z_and_density_not_stored(tmp_path):
    """守住决定：Z 与密度不入库（get_phase 里必须退化为 0 / NULL）。"""
    body = [
        _line("Pmmm        47          4     1.850   1.856                    496.88",
              "P010900R3"),
        _line(CALCITE_RE, "P010900RE"),
        _xi_line([(3.04, 100), (2.49, 20)], "P010900RI"),
    ]
    db, _ = _build(tmp_path, _rec(body, pdf2_id=10900))
    d = db.get_phase(10900)
    assert d["z"] == 0 and d["density"] == 0.0
    conn = db._get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
    for col in ("z_reduced", "density_x", "density_m"):
        assert col not in cols


def test_typeE_conventional_cell_parsed():
    from polyxrd.services.pdf2_scan import _parse_cell_fields

    cell = _parse_cell_fields(CALCITE_RE, 6)
    assert cell == pytest.approx((4.983, 4.983, 17.019, 90.0, 90.0, 120.0))
    assert _cell_volume(*cell) == pytest.approx(365.97, rel=0.002)


def test_typeD_reduced_cell_and_trailing_serial():
    """类型 D 末列是与数据无关的序号，体积在第 7 个 token。"""
    from polyxrd.services.pdf2_scan import _num, _parse_cell_fields

    cell = _parse_cell_fields(CALCITE_RD, 6)
    assert cell == pytest.approx((4.983, 4.983, 6.361, 66.94, 66.94, 60.0))
    toks = CALCITE_RD.split()
    assert _num(toks[6]) == pytest.approx(121.99)
    assert _cell_volume(*cell) == pytest.approx(121.99, rel=0.002)


def test_pearson_and_name_mineral_tags():
    """类型 A = Pearson；类型 6 的名称按 cols 67~68 的类别分流。"""
    from polyxrd.services.pdf2_scan import parse_pdf2_record

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
    assert rec.mineral == "Calcite"                  # M 类，不覆盖 name
    assert rec.space_group == "R-3c" and rec.space_group_num == 167
    assert (rec.cell_a, rec.cell_c, rec.cell_gamma) == (4.983, 17.019, 120.0)
    assert rec.red_vol == pytest.approx(121.99)
    assert rec.cell_vol == pytest.approx(365.97, rel=0.002)


def test_build_sentinel_flags_volume_mismatch(tmp_path):
    """建库哨兵：报告体积与六参数自算差 >2% 时计数（列位读错会跳到几万）。"""
    body = [
        _line(CALCITE_R3.replace("365.97", "999.99"), "P010837R3"),
        _line(CALCITE_RE, "P010837RE"),
        _xi_line([(3.04, 100), (2.49, 20), (2.28, 15)], "P010837RI"),
    ]
    db, meta = _build(tmp_path, _rec(body))
    assert meta["build"]["vol_mismatch"] == 1
    d = db.get_phase(10837)
    # 采用自算体积（365.97），而不是行里那个错误的 999.99
    assert d["volume"] == pytest.approx(365.97, rel=0.002)


def test_build_coverage_counters(tmp_path):
    """建库统计：with_cell / with_sg / with_name。"""
    ok = _rec([
        _line(CALCITE_R3, "P010837R3"),
        _raw_line("Calcium Carbonate Oxide", " P 1", "P010837R6"),
        _raw_line("Calcite", " M 2", "P010837R6"),
        _line(CALCITE_RE, "P010837RE"),
        _xi_line([(3.04, 100), (2.49, 20), (2.28, 15)], "P010837RI"),
    ], pdf2_id=10837)
    no_sg = _rec([
        _line("B       E    0         16                                     1025.47",
              "P090364X3"),
        _raw_line("Barium Nitrate", " P 1", "P090364X6"),
        _xi_line([(3.60, 100), (2.60, 40), (2.10, 25)], "P090364XI"),
    ], pdf2_id=90364, seq="X")
    _, meta = _build(tmp_path, ok + no_sg)
    b = meta["build"]
    assert meta["counts"]["phases"] == 2
    assert b["records_read"] == 2
    assert b["with_cell"] == 1
    assert b["with_sg"] == 1
    assert b["with_name"] == 2
    assert b["vol_mismatch"] == 0


def test_lattice_and_name_search_roundtrip(tmp_path):
    """polyDB 命中必须能取出晶胞（Rietveld 起始值）与名称（GUI 展示）。"""
    body = [
        _line(CALCITE_R3, "P010837R3"),
        _raw_line("Calcium Carbonate Oxide", " P 1", "P010837R6"),
        _raw_line("Calcite", " M 2", "P010837R6"),
        _line(CALCITE_RE, "P010837RE"),
        _line(CALCITE_RD, "P010837RD"),
        _xi_line([(3.04, 100), (2.49, 20), (2.28, 15)], "P010837RI"),
    ]
    db, _ = _build(tmp_path, _rec(body))

    d = db.get_phase(10837)
    assert (d["cell_a"], d["cell_c"], d["cell_gamma"]) == (4.983, 17.019, 120.0)
    assert d["volume"] == pytest.approx(365.97, rel=0.002)
    assert db.get_phase(999999) is None

    assert db.search_entries("Calcite")[0]["cod_id"] == 10837
    assert db.search_entries("Calcium Carbonate Oxide")[0]["cod_id"] == 10837
    assert len(db.search_entries("10837")) == 1


def test_identify_carries_space_group_and_lattice(tmp_path):
    """PDF2 命中必须把空间群与晶胞带到 Phase 上（精修起始值 / GUI 展示）。"""
    import numpy as np

    import polyxrd.services.phase_identifier as pim
    from polyxrd.models.xrd_data import XRDData

    body = [
        _line(CALCITE_R3, "P010837R3"),
        _raw_line("Calcium Carbonate Oxide", " P 1", "P010837R6"),
        _raw_line("Calcite", " M 2", "P010837R6"),
        _line(CALCITE_RE, "P010837RE"),
        *_xi_lines([(3.86, 8), (3.04, 100), (2.49, 20), (2.28, 15),
                    (2.09, 18), (1.92, 25), (1.87, 20)], "P010837RI"),
    ]
    db, _ = _build(tmp_path, _rec(body))

    tt = np.arange(10.0, 70.0, 0.02)
    y = np.full_like(tt, 20.0)
    for d, amp in ((3.86, 8), (3.04, 100), (2.49, 20), (2.28, 15),
                   (2.09, 18), (1.92, 25), (1.87, 20)):
        c = 2.0 * math.degrees(math.asin(WL / (2.0 * d)))
        y += amp * np.exp(-0.5 * ((tt - c) / 0.085) ** 2)
    y += np.random.default_rng(3).normal(0, 0.4, size=tt.size)

    res = pim.PhaseIdentifier().identify_with_polydb(
        XRDData(two_theta=tt, intensity=y, wavelength=WL), peaks=None,
        top_n=5, db_path=str(db.path))
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
    from polyxrd.services.polydb import PolyDatabase
    return PolyDatabase(_REAL_DB)


@requires_real_db
def test_real_calcite_full_mapping(real_db):
    """方解石 010837 = ICDD 卡片的标准参照（R-3c / 167 / a=4.983 / c=17.019）。"""
    p = real_db.get_phase(10837)
    assert p["space_group"] == "R-3c"
    assert p["sg_number"] == 167
    assert p["mineral_name"] == "Calcite"
    assert p["name"] == "Calcium Carbonate Oxide"
    assert p["pearson"] == "hR"
    assert (p["cell_a"], p["cell_b"], p["cell_c"]) == (4.983, 4.983, 17.019)
    assert (p["cell_alpha"], p["cell_beta"], p["cell_gamma"]) == (90.0, 90.0, 120.0)
    assert p["volume"] == pytest.approx(365.97, rel=0.002)
    assert p["display_id"] == "PDF2-010837"


@requires_real_db
def test_real_meta_coverage_floors(real_db):
    """覆盖率下限（163,834 相）：晶胞 ≥80%、空间群 ≥70%、名称 ≥99%。"""
    m = real_db.meta
    n = int(m["counts"]["phases"])
    b = m["build"]
    assert n >= 163_000
    assert b["with_cell"] / n >= 0.80, b
    assert b["with_sg"] / n >= 0.70, b
    assert b["with_name"] / n >= 0.99, b


@requires_real_db
def test_real_volume_sentinel_range(real_db):
    """建库哨兵 vol_mismatch 必须落在合理区间（≈986 / 133,935 = 0.74%）。"""
    b = real_db.meta["build"]
    assert b["with_cell"] >= 130_000, b
    assert b["vol_mismatch"] <= 0.01 * b["with_cell"], b


@requires_real_db
def test_real_k_and_truncation(real_db):
    """k=100；约 22% 的卡片峰数 >100，必须被如实计数（不是静默截断）。"""
    b = real_db.meta["build"]
    assert real_db.meta["counts"]["k"] == 100
    assert b["truncated_to_k"] > 30_000, b


@requires_raw_dat
def test_real_volume_disagreement_is_bimodal():
    """从原始 .dat 回读：报告体积与 E 胞自算体积的偏差是**双峰**的。

    99.264% 精确吻合（<0.5%），0.736% 差 >10%（ICDD 按菱面体原胞或超胞口径
    给报告体积），**中间 0.5~10% 一条都没有** —— 这条比任何单点断言都更能
    区分"数据口径差异"与"列位解析错误"（后者会糊在中间带）。
    """
    import collections

    from polyxrd.services.pdf2_scan import iter_pdf2_records
    from polyxrd.utils.math_utils import lattice_volume

    buckets: collections.Counter = collections.Counter()
    for rec in iter_pdf2_records(_RAW_DAT):
        if not (rec.cell_a and rec.cell_b and rec.cell_c and rec.cell_vol):
            continue
        v = lattice_volume(rec.cell_a, rec.cell_b, rec.cell_c,
                           rec.cell_alpha or 90.0, rec.cell_beta or 90.0,
                           rec.cell_gamma or 90.0)
        if not (v > 0):
            continue
        rel = abs(rec.cell_vol - v) / v
        if rel <= 0.005:
            buckets["match"] += 1
        elif rel <= 0.10:
            buckets["middle"] += 1
        else:
            buckets["far"] += 1
    assert buckets["match"] > 0.98 * sum(buckets.values())
    assert buckets["middle"] == 0, f"中间带出现 {buckets['middle']} 条 → 列位可疑"
    assert buckets["far"] > 500
