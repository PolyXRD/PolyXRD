"""
PDF2-2004 → polyDB 对接测试
===========================
不依赖真实 ICDD 数据文件，用合成的 80 字符定宽记录在 tmp_path 里现场建库，
覆盖 v5.2 的整条新链路：

1. 定宽流解析（标记第 71 列、序列字母可变、标志区截断）
2. ``scripts/build_pdf2_polydb.build`` → 规范 v1 的 8 个段 + meta 口径
3. ``PolyDatabase`` 读回：probe / get_phase / display_id / name 可选列
4. 检索与 COD 家族同一套打分（含 tolerance_rel / 元素过滤）
5. PDF2 无原子坐标 → sites 段为空但库仍可用（能力与旧 sqlite 通道一致）
"""
from __future__ import annotations

import inspect
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_pdf2_polydb import build as build_polydb  # noqa: E402

WL = 1.5406
_PDF2_WL = 80


def _line(data: str, rec_id: str) -> str:
    """一条 80 字符定宽 field：数据 0~70 列，标记固定从第 71 列起。"""
    return data[:71].ljust(71) + rec_id[:9]


def _xi_line(pairs, rec_id: str = "P010001XI") -> str:
    """XI 行：3 对 d(7 字符)+I(3 字符)，列偏移 0/23/46。"""
    buf = [" "] * _PDF2_WL
    for idx, (d, i) in enumerate(pairs):
        off = (0, 23, 46)[idx]
        s = f"{d:7.4f}{int(round(i)):3d}"
        buf[off:off + len(s)] = list(s)
    return _line("".join(buf).rstrip(), rec_id)


def _rec(pdf2_id: int, formula: str, formula_norm: str, name: str,
         peaks: list[tuple[float, float]], with_peaks: bool = True,
         seq: str = "X", cell: tuple | None = None,
         sg: tuple[str, int] | None = None,
         mineral: str = "") -> list[str]:
    """构造一条合成记录（可选空间群行 / 常规晶胞行 / 矿物名行）。"""
    rid = f"P{pdf2_id:06d}{seq}"
    lines = [_line("", f"{rid}1")]
    if sg is not None:
        sym, num = sg
        # 类型 3: 0~7 符号 / 8~10 标志 / 11~13 号 / 14 设置位 / 15~ Z·密度·体积。
        # 尾部必须有内容（真实行都有体积），否则 `_data_area` 的 rstrip 会把
        # 第 14 列削掉。
        lines.append(_line(
            f"{sym:<8}{'':3}{num:>3} " + "     2     2.710     2.700      365.97",
            f"{rid}3"))
    if cell is not None:
        a, b, c, al, be, ga = cell
        lines.append(_line(f"{a:8.4f}{b:8.4f}{c:8.4f}{al:8.3f}{be:8.3f}{ga:8.3f}",
                           f"{rid}E"))
    lines.append(_line(name, f"{rid}6"))
    if mineral:
        # 名称类别落在 67~68 列：M = 矿物名（必须正好 80 字符，定宽流按 80 切）
        lines.append(mineral[:67].ljust(67) + "M " + "  " + f"{rid}6")
    lines.append(_line(formula, f"{rid}7"))
    lines.append(_line(formula_norm, f"{rid}8"))
    if with_peaks:
        for i in range(0, len(peaks), 3):
            lines.append(_xi_line(peaks[i:i + 3], f"{rid}I"))
    lines.append(_line("", f"{rid}K"))
    return lines


def _write_raw(path: Path, recs: list[list[str]]) -> Path:
    path.write_bytes("".join("".join(r) for r in recs).encode("ascii"))
    return path


def _d_to_tt(d: float, wl: float = WL) -> float:
    return 2.0 * math.degrees(math.asin(min(1.0, wl / (2.0 * d))))


def _pattern_from_peaks(peaks, tt_range=(5.0, 90.0), step=0.02, noise=0.5):
    """peaks = [(2θ, 强度, FWHM)] → XRDData"""
    from polyxrd.models.xrd_data import XRDData

    tt = np.arange(tt_range[0], tt_range[1], step)
    y = np.full_like(tt, 20.0)
    for c, amp, fwhm in peaks:
        sigma = fwhm / 2.355
        y += amp * np.exp(-0.5 * ((tt - c) / sigma) ** 2)
    rng = np.random.default_rng(1)
    y += rng.normal(0.0, noise, size=tt.size)
    return XRDData(two_theta=tt, intensity=y, wavelength=WL)


# ── 1. 解析器 ────────────────────────────────────────────────

def test_marker_anchored_at_column_71():
    """回归: 记录标记固定在第 71 列, 序列字母可变。"""
    from polyxrd.services.pdf2_scan import parse_pdf2_record

    lines = _rec(10837, "C Ca O3", "C Ca O3", "Calcite",
                 [(3.035, 100), (1.913, 18)], seq="R")
    lines[0] = lines[0].replace("P010837R", "D010837R")  # 数据集字母换 D
    rec = parse_pdf2_record(lines, offset=0)
    assert rec is not None, "D...R... 标记必须能解析"
    assert rec.pdf2_id == 10837
    assert rec.formula == "C Ca O3"
    assert rec.name == "Calcite"
    assert len(rec.peaks_d) == 2


def test_continuation_tail_stripped_from_formula():
    """回归: 数据区末尾 (67~70 列) 是标志区, 不得混入数据。"""
    from polyxrd.services.pdf2_scan import parse_pdf2_record

    lines = _rec(410877, "1.5 Ca O ! Si O2 !x H2 O", "", "CSH", [(3.04, 100)])
    lines[2] = "1.5 Ca O ! Si O2 !x H2 O".ljust(68) + "S 2" + "P410877R7"
    assert len(lines[2]) == 80 and lines[2][71] == "P"
    rec = parse_pdf2_record(lines, offset=0)
    assert rec is not None
    assert rec.formula == "1.5 Ca O ! Si O2 !x H2 O", rec.formula


def test_parse_xi_peaks_three_pairs():
    from polyxrd.services.pdf2_scan import _parse_xi_peaks
    line = _xi_line([(3.343, 100), (4.255, 20), (1.818, 8)])
    got = _parse_xi_peaks(line)
    assert [(round(d, 3), i) for d, i in got] == [
        (3.343, 100.0), (4.255, 20.0), (1.818, 8.0)]


def test_parse_xi_peaks_skips_zero_and_garbage():
    from polyxrd.services.pdf2_scan import _parse_xi_peaks
    line = _xi_line([(0.0, 0), (4.255, 20)])
    assert len(_parse_xi_peaks(line)) == 1


def test_parse_record_extracts_fields():
    from polyxrd.services.pdf2_scan import parse_pdf2_record
    lines = _rec(10001, "Si1 O2", "Si1 O2", "Quartz",
                 [(3.343, 100), (4.255, 20), (1.818, 8)],
                 cell=(4.9134, 4.9134, 5.4052, 90, 90, 120),
                 sg=("P 32 2 1", 154))
    rec = parse_pdf2_record(lines, offset=0)
    assert rec is not None
    assert rec.pdf2_id == 10001
    assert rec.name == "Quartz"
    assert rec.n_peaks == 3
    assert rec.peaks_d[0] == pytest.approx(3.343, abs=1e-3)
    assert rec.space_group_num == 154
    assert rec.cell_a == pytest.approx(4.9134, abs=1e-4)
    assert rec.record_size == len(lines) * 80


def test_parse_record_without_peaks_returns_zero_peaks():
    from polyxrd.services.pdf2_scan import parse_pdf2_record
    rec = parse_pdf2_record(_rec(10002, "Ca1 O1", "Ca1 O1", "Lime", [],
                                 with_peaks=False), 0)
    assert rec is not None and rec.n_peaks == 0


# ── 2. 建库（polyDB v1 规范） ────────────────────────────────

@pytest.fixture()
def pdf2_db(tmp_path):
    """合成 2 条记录（石英 + 无峰坏记录）→ PDF2-2004.polyDB。"""
    raw = _write_raw(tmp_path / "pdf2.dat", [
        _rec(10001, "Si1 O2", "Si1 O2", "Quartz",
             [(3.343, 100), (4.255, 20), (1.818, 8), (1.541, 6)],
             cell=(4.9134, 4.9134, 5.4052, 90, 90, 120),
             sg=("P 32 2 1", 154), mineral="Quartz low"),
        _rec(10002, "Ca1 O1", "Ca1 O1", "Lime", [], with_peaks=False),
    ])
    out = tmp_path / "PDF2-2004.polyDB"
    meta = build_polydb(raw, out, progress=lambda *a, **k: None)
    from polyxrd.services.polydb import PolyDatabase

    return PolyDatabase(out), meta, out


def test_build_meta_is_spec_compliant(pdf2_db):
    _, meta, out = pdf2_db
    assert meta["format"] == "polyDB" and meta["schema_version"] == 1
    assert meta["variant"] == "pdf2-2004"
    assert meta["counts"]["phases"] == 1, "无峰卡片必须被跳过"
    assert meta["counts"]["sites"] == 0
    pc = meta["peak_convention"]
    assert pc["peak_origin"] == "observed"
    assert pc["k"] == 100 and pc["bins_top_m"] == 40
    assert pc["intensity_scale"] == 1000.0
    # 8 个必需段全在，且字节数与 meta 一致（probe 会逐段核对）
    for name in ("peaks_d.f32", "peaks_i.u16", "bins.u8", "elem.u8",
                 "sites.bin", "sites_off.i64", "index.sqlite"):
        assert (out / name).is_file(), name
    on_disk = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert on_disk["sections"]["sites.bin"]["bytes"] == 0


def test_build_probe_and_stats(pdf2_db):
    from polyxrd.services.polydb import probe

    db, _, out = pdf2_db
    ok, why = probe(out)
    assert ok, why
    assert db.is_ready()
    st = db.stats()
    assert st.phases == 1 and st.k == 100 and st.bins == 501
    assert st.variant == "pdf2-2004"
    assert st.peak_convention["peak_origin"] == "observed"


def test_get_phase_carries_pdf2_fields(pdf2_db):
    db, _, _ = pdf2_db
    d = db.get_phase(10001)
    assert d is not None
    assert d["formula"] == "Si1 O2"
    assert d["display_id"] == "PDF2-010001"
    assert d["name"] == "Quartz"            # ICDD 化合物名（可选列）
    assert d["mineral_name"] == "Quartz low"
    assert d["sg_number"] == 154
    assert d["cell_a"] == pytest.approx(4.9134, abs=1e-4)
    assert d["volume"] > 0
    assert d["peaks_d_list"][0] == pytest.approx(3.343, abs=1e-3)
    assert len(d["peaks_d_list"]) == len(d["peaks_i_list"]) == 4
    # 每相最强峰归一到 1000（PDF2 原表 I/I0=100）
    assert max(d["peaks_i_list"]) == pytest.approx(1000.0, abs=0.05)
    assert db.get_phase(999999) is None


def test_no_atomic_sites_but_db_is_usable(pdf2_db):
    """PDF2 没有原子坐标：侧车为空，但库必须照常可检索（与旧通道能力一致）。"""
    db, _, _ = pdf2_db
    assert db.get_atomic_sites(10001) == []


def test_search_entries_by_name_and_formula(pdf2_db):
    db, _, _ = pdf2_db
    assert [r["cod_id"] for r in db.search_entries("Quartz")] == [10001]
    assert [r["cod_id"] for r in db.search_entries("Si1 O2")] == [10001]
    assert [r["cod_id"] for r in db.search_entries("10001")] == [10001]
    assert db.search_entries("") == []


def test_search_by_d_peaks_finds_quartz(pdf2_db):
    db, _, _ = pdf2_db
    hits = db.search_by_d_peaks([3.343, 4.255, 1.818], [100, 20, 6],
                                min_match=3, limit=10)
    assert hits and hits[0]["cod_id"] == 10001
    assert hits[0]["display_id"] == "PDF2-010001"


def test_search_by_d_peaks_supports_tolerance_rel(pdf2_db):
    db, _, _ = pdf2_db
    shifted = [3.40, 4.31, 1.84]
    assert db.search_by_d_peaks(shifted, None, tolerance=0.02, min_match=3) == []
    got = db.search_by_d_peaks(shifted, None, tolerance=0.02,
                               tolerance_rel=0.02, min_match=3)
    assert got and got[0]["cod_id"] == 10001


def test_element_filter_uses_bitmap(pdf2_db):
    db, _, _ = pdf2_db
    hit = db.search_by_d_peaks([3.343, 4.255, 1.818], None, min_match=3,
                               elements_allowed={"Si", "O"})
    miss = db.search_by_d_peaks([3.343, 4.255, 1.818], None, min_match=3,
                                elements_allowed={"Ca"})
    assert hit and not miss


# ── 3. 峰槽位与截断（k=100） ─────────────────────────────────

def test_peaks_truncated_to_k_by_intensity(tmp_path):
    """>100 条峰时按强度保留前 100 条（规范 §2 intensity_top）。"""
    peaks = [(0.9 + i * 0.02, float(i + 1)) for i in range(120)]
    raw = _write_raw(tmp_path / "pdf2.dat", [
        _rec(20001, "Fe2 O3", "Fe2 O3", "Hematite", peaks)])
    out = tmp_path / "Small.polyDB"
    meta = build_polydb(raw, out, progress=lambda *a, **k: None)
    assert meta["build"]["truncated_to_k"] == 1
    assert meta["counts"]["peaks"] == 120       # 真实峰数如实记入 meta
    assert meta["counts"]["k"] == 100

    from polyxrd.services.polydb import PolyDatabase

    d = PolyDatabase(out).get_phase(20001)
    assert len(d["peaks_d_list"]) == 100
    # 最强 100 条留下 → 最弱的 20 条（i=1..20）必须不在
    assert min(d["peaks_i_list"]) > 20.0


# ── 4. 与识别链路的一致性 ───────────────────────────────────

def test_identify_with_polydb_end_to_end(pdf2_db, monkeypatch):
    """合成石英谱 → identify_with_polydb 应把 PDF2 石英排到首位。"""
    import polyxrd.services.phase_identifier as pim

    db, _, out = pdf2_db
    tt_peaks = [(_d_to_tt(d), i, 0.2)
                for d, i in [(3.343, 100.0), (4.255, 20.0), (1.818, 8.0),
                             (1.541, 6.0)]]
    data = _pattern_from_peaks(tt_peaks)
    r = pim.PhaseIdentifier().identify_with_polydb(
        data, peaks=None, element_filter={"must": ["Si", "O"]},
        top_n=5, tolerance=0.2, db_path=str(out))
    assert r, "识别结果为空"
    assert "Si1 O2" == r[0].phase.formula
    assert "PDF2" in r[0].phase.name
    assert r[0].phase.space_group == "P 32 2 1"


def test_identify_polydb_uses_default_peak_list(monkeypatch, tmp_path):
    import polyxrd.services.phase_identifier as pim

    called = {"n": 0}
    real = pim.default_peak_list

    def spy(d):
        called["n"] += 1
        return real(d)

    monkeypatch.setattr(pim, "default_peak_list", spy)
    r = pim.PhaseIdentifier().identify_with_polydb(
        _pattern_from_peaks([(26.6, 100.0, 0.2)]), peaks=None,
        db_path=str(tmp_path / "nope.polyDB"))
    assert r == []
    assert called["n"] == 1


def test_sort_uses_cod_rank_score():
    """排序口径必须复用 cod_rank_score —— PDF2 没有自己的第二套。"""
    import polyxrd.services.phase_identifier as pim
    src = inspect.getsource(pim.PhaseIdentifier)
    assert "_pdf2_rank_score" not in src
    assert "cod_rank_score(it)" in src


def test_elements_from_db_formula_is_single_source():
    """公式解析单点实现：所有检索路径 import 同一个函数。"""
    from polyxrd.utils.formula_parser import elements_from_db_formula as impl

    assert impl("Li1.13 Mn2 O4") == {"Li", "Mn", "O"}
    assert impl("O4 Zr3") == {"O", "Zr"}
    assert impl("") == set()

    import polyxrd.services.phase_identifier as pim
    assert pim.elements_from_db_formula is impl

    mod_src = inspect.getsource(pim)
    assert "def _elements_from_db_formula" not in mod_src
    for meth in (pim.PhaseIdentifier._make_polydb_phase,
                 pim.PhaseIdentifier._make_user_phase):
        assert "elements_from_db_formula(" in inspect.getsource(meth), meth.__name__
