"""
PDF2-2004 数据库对接测试
========================
不依赖真实 PDF-2 2004 数据文件 (10 MB, gitignored), 全部用合成的定宽
80 字符记录在 tmp_path 里现场建库, 覆盖:

1. XI d-I 行解析 / 记录解析 / 建库往返
2. search_by_d_peaks 复用 CIFDatabase 实现 (含 tolerance_rel)
3. identify_with_pdf2 与 COD 路径共用 default_peak_list 与 cod_rank_score
4. 数据库缺失/不可用时的降级行为
"""
from __future__ import annotations

import inspect
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

WL = 1.5406

# PDF2 记录 ID 出现在每行末尾附近; 数据区 = 行首到 ID 起点
_PDF2_WL = 80


def _line(data: str, rec_id: str) -> str:
    """一条 80 字符定宽 field: 数据在 0~70 列, 记录标记固定从第 71 列起。

    ⚠️ 必须按真实布局把标记钉在 71 列 —— 旧版测试把标记紧跟在数据后面,
    与旧版"任意位置 search"的正则自洽, 结果掩盖了真实文件里
    "标记固定 71 列 + 序列字母可变" 两个事实 (见 test_*_real_layout)。
    """
    return data[:71].ljust(71) + rec_id[:9]


def _xi_line(pairs, rec_id: str = "P010001XI") -> str:
    """XI 行: 3 对 d(7字符)+I(3字符), 列偏移 0/23/46"""
    buf = [" "] * _PDF2_WL
    for idx, (d, i) in enumerate(pairs):
        off = (0, 23, 46)[idx]
        s = f"{d:7.3f}{int(round(i)):3d}"
        buf[off:off + len(s)] = list(s)
    return _line("".join(buf).rstrip(), rec_id)


def test_marker_anchored_at_column_71():
    """回归: 记录标记固定在第 71 列, 序列字母可变。

    真实 PDF-2 是无换行的 80 字符定宽流, 标记 token 恒在 field 尾部:
      <数据集字母 P/D/...><6位卡片号><序列字母 X/R/H/...><类型 1/7/I/K>
    旧版正则硬编码 P...X... 导致约 65% 卡片被丢弃 (25,237 vs 163,834)。
    """
    from polyxrd.services.pdf2_database import parse_pdf2_record

    # 方解石 010837 的真实标记形态: 数据集字母 D, 序列字母 R
    lines = _rec(10837, "C Ca O3", "Ca C O3", "Calcite",
                 [(3.035, 100), (1.913, 18)], seq="R")
    lines[2] = lines[2].replace("P010837R", "D010837R")  # 数据集字母换 D
    rec = parse_pdf2_record(lines, offset=0)
    assert rec is not None, "D...R... 标记必须能解析"
    assert rec.pdf2_id == 10837
    assert rec.formula == "C Ca O3"
    assert rec.name == "Calcite"
    assert len(rec.peaks_d) == 2


def test_continuation_tail_stripped_from_formula():
    """回归: 数据区末尾 (67~70 列) 是标志区, 不得混入数据。

    真实文件里该区出现孤立 "G"、续行标记 "DB 1"/"SM 2"/" P " 等;
    旧版拼进 formula 后 "G" 会被当成元素, 污染元素过滤
    (实测 4342/163834 条被污染)。
    """
    from polyxrd.services.pdf2_database import parse_pdf2_record

    lines = _rec(410877, "1.5 Ca O ! Si O2 !x H2 O", "", "CSH",
                 [(3.04, 100)])
    # 仿真实 cod_id=10026 的 X7 field: 化学式后跟空格 + 标志位 "G"/"S 2"
    lines[2] = "1.5 Ca O ! Si O2 !x H2 O".ljust(68) + "S 2" + "P410877R7"
    assert len(lines[2]) == 80 and lines[2][71] == "P"
    rec = parse_pdf2_record(lines, offset=0)
    assert rec is not None
    assert rec.formula == "1.5 Ca O ! Si O2 !x H2 O", rec.formula


def _rec(pdf2_id: int, formula: str, formula_norm: str, name: str,
         peaks: list[tuple[float, float]], with_peaks: bool = True,
         seq: str = "X") -> list[str]:
    """构造一条合成记录。

    seq = 记录序列字母。真实文件里它随卡片变化 (石英 470715 全用 X,
    方解石 010837 全用 R, 211487 用 H), 旧版正则硬编码 "P...X..." 漏掉
    约 65% 卡片 —— 所以测试必须用非 X 的字母才能守住这个回归。
    """
    rid = f"P{pdf2_id:06d}{seq}"
    lines = [
        _line("", f"{rid}1"),
        _line(name, f"{rid}6"),
        _line(formula, f"{rid}7"),
        _line(formula_norm, f"{rid}8"),
    ]
    if with_peaks:
        for i in range(0, len(peaks), 3):
            lines.append(_xi_line(peaks[i:i + 3], f"{rid}I"))
    lines.append(_line("", f"{rid}K"))
    return lines


def _d_to_tt(d: float, wl: float = WL) -> float:
    return 2.0 * math.degrees(math.asin(min(1.0, wl / (2.0 * d))))


def _pattern_from_peaks(peaks, tt_range=(5.0, 90.0), step=0.02, noise=0.5):
    """peaks = [(2θ, 强度)] → XRDData"""
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

def test_parse_xi_peaks_three_pairs():
    from polyxrd.services.pdf2_database import _parse_xi_peaks
    line = _xi_line([(3.343, 100), (4.255, 20), (1.818, 8)])
    got = _parse_xi_peaks(line)
    assert [(round(d, 3), i) for d, i in got] == [
        (3.343, 100.0), (4.255, 20.0), (1.818, 8.0)]


def test_parse_xi_peaks_skips_zero_and_garbage():
    from polyxrd.services.pdf2_database import _parse_xi_peaks
    line = _xi_line([(0.0, 0), (4.255, 20)])
    assert len(_parse_xi_peaks(line)) == 1


def test_parse_record_extracts_fields():
    from polyxrd.services.pdf2_database import parse_pdf2_record
    lines = _rec(10001, "SiO2", "Si1 O2", "Quartz",
                 [(3.343, 100), (4.255, 20), (1.818, 8)])
    rec = parse_pdf2_record(lines, offset=0)
    assert rec is not None
    assert rec.pdf2_id == 10001
    # formula 为空时回退 formula_norm
    assert rec.formula in ("SiO2", "Si1 O2")
    assert rec.formula_norm == "Si1 O2"
    assert rec.name == "Quartz"
    assert rec.n_peaks == 3
    assert rec.peaks_d[0] == pytest.approx(3.343, abs=1e-3)
    assert rec.record_size == len(lines) * 80


def test_parse_record_without_peaks_returns_zero_peaks():
    from polyxrd.services.pdf2_database import parse_pdf2_record
    rec = parse_pdf2_record(_rec(10002, "CaO", "Ca1 O1", "Lime", [],
                                 with_peaks=False), 0)
    assert rec is not None and rec.n_peaks == 0


# ── 2. 建库 + 查询往返 ───────────────────────────────────────

@pytest.fixture()
def pdf2_db(tmp_path):
    """合成 2 条记录 (石英 + 无峰坏记录) 的临时 PDF2 数据库"""
    from polyxrd.services.pdf2_database import PDF2DatabaseBuilder
    raw = tmp_path / "pdf2.dat"
    lines = (
        _rec(10001, "SiO2", "Si1 O2", "Quartz",
             [(3.343, 100), (4.255, 20), (1.818, 8), (1.541, 6)])
        + _rec(10002, "CaO", "Ca1 O1", "Lime", [], with_peaks=False)
    )
    raw.write_bytes("".join(lines).encode("ascii"))
    db_path = tmp_path / "pdf2.sqlite"
    stats = PDF2DatabaseBuilder(raw, db_path).build()
    from polyxrd.services.pdf2_database import PDF2Database
    return PDF2Database(db_path), stats, tmp_path


def test_build_stats(pdf2_db):
    _, stats, _ = pdf2_db
    assert stats["total"] == 2
    assert stats["ok"] == 1
    assert stats["bad"] == 1


def test_phase_count_and_get_phase(pdf2_db):
    db, _, _ = pdf2_db
    assert db.phase_count() == 1
    assert db.is_available()
    d = db.get_phase(10001)
    assert d is not None
    assert d["formula"] == "Si1 O2"
    assert d["source"] == "pdf2"
    assert d["peaks_d_list"][0] == pytest.approx(3.343, abs=1e-4)
    assert len(d["peaks_d_list"]) == len(d["peaks_i_list"]) == 4
    assert db.get_phase(999999) is None


def test_search_phases_by_formula_and_id(pdf2_db):
    db, _, _ = pdf2_db
    assert len(db.search_phases("Si1 O2")) == 1
    assert len(db.search_phases("10001")) == 1
    assert db.search_phases("") == []


def test_search_by_d_peaks_finds_quartz(pdf2_db):
    db, _, _ = pdf2_db
    hits = db.search_by_d_peaks([3.343, 4.255, 1.818], [100, 20, 6],
                                min_match=3, limit=10)
    assert hits and hits[0]["cod_id"] == 10001


def test_search_by_d_peaks_supports_tolerance_rel(pdf2_db):
    """与 COD 同一实现 → 相对容差同样可用"""
    db, _, _ = pdf2_db
    shifted = [3.40, 4.31, 1.84]  # 各偏 ~0.05/0.055/0.022 Å
    assert db.search_by_d_peaks(shifted, None, tolerance=0.02, min_match=3) == []
    got = db.search_by_d_peaks(shifted, None, tolerance=0.02,
                               tolerance_rel=0.02, min_match=3)
    assert got and got[0]["cod_id"] == 10001


def test_missing_db_degrades_gracefully(tmp_path):
    from polyxrd.services.pdf2_database import PDF2Database
    db = PDF2Database(tmp_path / "nope.sqlite")
    assert not db.is_available()
    assert db.phase_count() == 0
    assert db.stats() == {"ready": False}
    assert db.get_phase(1) is None
    assert db.search_phases("SiO2") == []
    assert db.search_by_d_peaks([3.0], None) == []


def test_reload_reconnects(pdf2_db):
    db, _, _ = pdf2_db
    assert db.phase_count() == 1
    db.reload()
    assert db.phase_count() == 1


# ── 3. 与 COD 识别路径的一致性 ───────────────────────────────

def test_identify_with_pdf2_shares_cod_rank_score():
    """回归守卫: 排序口径必须复用 cod_rank_score, 不得再复制一份。"""
    import polyxrd.services.phase_identifier as pim
    src = inspect.getsource(pim.PhaseIdentifier.identify_with_pdf2)
    assert "_pdf2_rank_score" not in src
    assert "cod_rank_score(it)" in src
    assert "PeakFinder" not in src  # 默认寻峰走 default_peak_list
    # 数据库公式解析也必须走单点实现, 不得在方法内重新定义闭包
    assert "def _elements_from_db_formula" not in src


def test_elements_from_db_formula_is_single_source():
    """公式解析单点实现: COD 路径与 PDF2 路径都 import 同一个函数。"""
    from polyxrd.utils.formula_parser import elements_from_db_formula as impl

    assert impl("Li1.13 Mn2 O4") == {"Li", "Mn", "O"}
    assert impl("O4 Zr3") == {"O", "Zr"}
    assert impl("") == set()

    import polyxrd.services.phase_identifier as pim
    assert pim.elements_from_db_formula is impl

    cod_src = inspect.getsource(pim.PhaseIdentifier.identify_with_cod_inorganics)
    pdf2_src = inspect.getsource(pim.PhaseIdentifier.identify_with_pdf2)
    for src in (cod_src, pdf2_src):
        assert "elements_from_db_formula(formula)" in src
        assert "def _elements_from_db_formula" not in src


def test_identify_with_pdf2_uses_default_peak_list(monkeypatch):
    import polyxrd.services.pdf2_database as pd2
    import polyxrd.services.phase_identifier as pim

    called = {"n": 0}
    real = pim.default_peak_list

    def spy(d):
        called["n"] += 1
        return real(d)

    class _Unavailable:
        def __init__(self, db_path=None):
            pass

        def is_available(self):
            return False

    monkeypatch.setattr(pim, "default_peak_list", spy)
    monkeypatch.setattr(pd2, "PDF2Database", _Unavailable)
    r = pim.PhaseIdentifier().identify_with_pdf2(
        _pattern_from_peaks([(26.6, 100.0, 0.2)]), peaks=None)
    assert r == []
    assert called["n"] == 1


def test_identify_with_pdf2_end_to_end(pdf2_db, monkeypatch):
    """合成石英谱 → identify_with_pdf2 应把 PDF2 石英排到首位"""
    import polyxrd.services.pdf2_database as pd2
    import polyxrd.services.phase_identifier as pim
    db, _, _ = pdf2_db

    real_cls = pd2.PDF2Database

    # identify_with_pdf2 内部调用 PDF2Database() (无参, 走配置路径) →
    # 用工厂闭包把库路径钉到临时库上
    def _factory(db_path=None):
        return real_cls(db_path=getattr(db, "_db_path"))

    monkeypatch.setattr(pd2, "PDF2Database", _factory)

    tt_peaks = [( _d_to_tt(d), i, 0.2)
                for d, i in [(3.343, 100.0), (4.255, 20.0), (1.818, 8.0),
                             (1.541, 6.0)]]
    data = _pattern_from_peaks(tt_peaks)
    r = pim.PhaseIdentifier().identify_with_pdf2(
        data, peaks=None, element_filter={"must": ["Si", "O"]},
        top_n=5, tolerance=0.2)
    assert r, "识别结果为空"
    assert "Si1 O2" == r[0].phase.formula
    assert "PDF2" in r[0].phase.name
