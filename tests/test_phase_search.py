"""``services/phase_search.py`` 单元与 golden 回归（v4.2 P1.2）。

golden 说明
-----------
``tests/data/phase_search_golden.json`` 是在**搬移代码之前**用旧的
``CIFDatabase.search_cod_by_d_peaks`` 对下面 ``SYNTH_ROWS`` 合成对抗库 +
``CASES`` 固定输入跑出来的逐字段快照。``search_phases_by_d_peaks`` 的语义
必须与它 **0 mismatch**。

这与 ``tests/test_cod_vectorized.py``（以 git 上一版模块为 oracle）互补：
那边保证"改动没变结果"，这边保证"搬移没变结果"，且不依赖 git 历史。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyxrd.services import phase_search as ps  # noqa: E402
from polyxrd.services.phase_search import (  # noqa: E402
    dedupe_by_tol,
    has_top_peak_columns,
    interval_hit,
    match_positions,
    parse_float_csv,
    search_phases_by_d_peaks,
    tol_scalar,
    top_peaks_of,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "phase_search_golden.json"


# ──────────────────────────────────────────────────────────────
# 合成对抗库: 把去重/容差/稳定排序的边界全部摆出来
# （与冻结 golden 时使用的 SYNTH_ROWS 必须逐字节一致，见 digest 断言）
# ──────────────────────────────────────────────────────────────
SYNTH_ROWS = [
    # (cod_id, peaks_d, peaks_i, formula, space_group)
    ("dup3",     [2.0, 2.0, 2.0, 3.0], [100, 90, 80, 70], "O2 Si", "P1"),
    # 相邻 d 恰差 = tolerance(0.02) -> `<=` 边界必须判命中
    ("exact",    [1.00, 1.02, 1.04, 1.06], [100, 99, 98, 97], "O2 Si", "P1"),
    # 恰差略大于 tolerance -> 必须判不命中
    ("over",     [1.00, 1.0201, 1.0402], [100, 99, 98], "O2 Si", "P1"),
    # 相对容差边界: d=1.0→t=0.02, d=3.0→t=0.06
    ("rel",      [1.0, 1.02, 3.0, 3.06, 3.12], [100, 99, 98, 97, 96], "O2 Si", "P1"),
    # 强峰全挤在同一个 d (低对称密集相)
    ("cluster",  [2.5, 2.5001, 2.5002, 2.5003, 2.6], [100, 99, 98, 97, 1], "O2 Si", "P1"),
    ("single",   [2.0], [100], "O2 Si", "P1"),
    ("two",      [2.0, 4.0], [100, 50], "O2 Si", "P1"),
    # I 全并列 -> 稳定排序语义
    ("tie_i",    [1.5, 2.5, 3.5, 4.5], [50, 50, 50, 50], "O2 Si", "P1"),
    # 乱序 + 30 个近重复弱峰
    ("many",     [round(1.0 + 0.01 * k, 4) for k in range(30)],
                 [((k * 37) % 100) + 1 for k in range(30)], "O2 Si", "P1"),
    # 长表: 3 个强峰 + 60 个并列弱峰 (max_ref_peaks 截断 + 并列边界)
    ("long",     [1.0, 1.1, 1.2] + [round(2.0 + 0.005 * k, 4) for k in range(60)],
                 [100, 90, 80] + [5] * 60, "O2 Si", "P1"),
    # 化学过滤会命中的相
    ("calcite",  [3.035, 2.495, 2.285, 1.913, 1.875],
                 [100, 40, 30, 25, 22], "C1 Ca1 O3", "R-3c"),
    ("blank",    [], [], "O2 Si", "P1"),
]

CASES = [
    ("intensity", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                       limit=1000, max_ref_peaks=40), True),
    ("no_intensity", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                          limit=1000, max_ref_peaks=40), False),
    ("abs_tol", dict(tolerance=0.02, tolerance_rel=0.0, min_match=1,
                     limit=1000, max_ref_peaks=40), True),
    ("rel_tol", dict(tolerance=0.02, tolerance_rel=0.02, min_match=1,
                     limit=1000, max_ref_peaks=40), True),
    ("elems", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                   limit=1000, max_ref_peaks=40,
                   elements_allowed={"O", "Si", "Ca", "C"}), True),
    ("min3", dict(tolerance=0.02, tolerance_rel=0.006, min_match=3,
                  limit=1000, max_ref_peaks=40), True),
    ("min10", dict(tolerance=0.02, tolerance_rel=0.006, min_match=10,
                   limit=1000, max_ref_peaks=40), True),
    ("maxref3", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                     limit=1000, max_ref_peaks=3), True),
    ("maxref1", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                     limit=1000, max_ref_peaks=1), True),
    ("single_meas", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                         limit=1000, max_ref_peaks=40), True),
    ("two_meas", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                      limit=1000, max_ref_peaks=40), True),
    ("limit5", dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
                    limit=5, max_ref_peaks=40), True),
]

MD_MAIN = [1.0, 1.02, 1.1, 1.2, 1.5, 1.98, 2.0, 2.5, 2.5001, 2.5002, 2.6,
           3.0, 3.06, 3.5, 4.0, 4.5, 5.5]
MI_MAIN = [100, 99, 80, 70, 50, 30, 20, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]

# golden 里记录的 SYNTH_ROWS 指纹 —— 两边一旦脱钩立刻失败
SYNTH_DIGEST = hashlib.sha256(
    json.dumps(SYNTH_ROWS, sort_keys=True, default=str).encode()
).hexdigest()

# 人为构造 d/I 长度不等的两行（真实库不可达），用于盯"k < len(d)"过滤；
# 预截断强峰列快路径假定两列已对齐，故等价性比对时排除它们。
LEN_MISMATCH_IDS = frozenset({"short_d", "short_i"})


def _meas_for(case: str):
    if case == "single_meas":
        return [2.0], [100]
    if case == "two_meas":
        return [1.0, 4.0], [100, 50]
    return MD_MAIN, MI_MAIN


def _create_phases(conn: sqlite3.Connection, with_top: bool = False) -> None:
    cols = (
        "cod_id TEXT, ref_id TEXT, display_id TEXT, formula TEXT, "
        "space_group TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT"
    )
    if with_top:
        cols += ", peaks_top_d TEXT, peaks_top_i TEXT"
    conn.execute(f"CREATE TABLE phases ({cols})")


def _insert_synth(conn: sqlite3.Connection, with_top: bool = False) -> None:
    rows = [
        (cid, cid, cid, formula, sg, len(ds),
         ",".join(repr(float(x)) for x in ds),
         ",".join(repr(float(x)) for x in iss))
        for cid, ds, iss, formula, sg in SYNTH_ROWS
    ]
    # d 数组比 I 数组短 / 反之 (旧实现有 k < len(ref_d_all) 过滤)
    rows.append(("short_d", "short_d", "short_d", "O2 Si", "P1", 4,
                 "1.5,2.5", "10,20,30,40"))
    rows.append(("short_i", "short_i", "short_i", "O2 Si", "P1", 4,
                 "1.5,2.5,3.5,4.5", "10,20"))
    if not with_top:
        conn.executemany(
            "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)", rows
        )
        return
    top_rows = []
    for row in rows:
        d = parse_float_csv(row[6] or "")
        i = parse_float_csv(row[7] or "")
        td, ti = top_peaks_of(d, i)
        top_rows.append(row + (",".join(repr(float(x)) for x in td),
                               ",".join(repr(float(x)) for x in ti)))
    conn.executemany(
        "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?)", top_rows
    )
    conn.commit()


def build_synth(with_top: bool = False) -> sqlite3.Connection:
    path = Path(tempfile.mkdtemp()) / "synth.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _create_phases(conn, with_top)
    _insert_synth(conn, with_top)
    conn.commit()
    return conn


@pytest.fixture(scope="module")
def synth():
    conn = build_synth()
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def synth_top():
    conn = build_synth(with_top=True)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def golden():
    assert GOLDEN.exists(), f"缺少 golden: {GOLDEN}"
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────
# golden 回归
# ──────────────────────────────────────────────────────────────
def test_golden_covers_all_cases(golden):
    assert set(golden["cases"]) == {c[0] for c in CASES}
    assert golden["synth_rows_sha256"] == SYNTH_DIGEST, (
        "SYNTH_ROWS 与冻结 golden 时不一致 —— golden 已失效，需重新冻结"
    )


@pytest.mark.parametrize("case, kw, with_i", CASES, ids=[c[0] for c in CASES])
def test_matches_golden(synth, golden, case, kw, with_i):
    g = golden["cases"][case]
    md, mi = _meas_for(case)
    if not with_i:
        mi = None
    got = search_phases_by_d_peaks(synth, md, mi, **kw)
    expect = g["results"]

    assert len(got) == len(expect), f"{case}: 行数 {len(got)} != {len(expect)}"
    for i, (a, b) in enumerate(zip(expect, got)):
        # v4.2.1: cod_id 也纳入比对 —— 并列指标完全相同、顺序互换时也能发现
        assert a.get("cod_id") == b.get("cod_id"), (
            f"{case}: #{i} cod_id {a.get('cod_id')!r} != {b.get('cod_id')!r}")
        for f in golden["compare_fields"]:
            va, vb = a[f], b[f]
            if isinstance(va, float):
                assert vb == pytest.approx(va, rel=1e-12, abs=1e-12), \
                    f"{case}: #{i} {f} {va!r} != {vb!r}"
            else:
                assert va == vb, f"{case}: #{i} {f} {va!r} != {vb!r}"


def test_golden_actually_exercises_scoring(golden):
    """确认 golden 不是一片空结果（否则上面的比对等于没测）。"""
    nonempty = [k for k, v in golden["cases"].items() if v["results"]]
    assert len(nonempty) >= 11, f"只有 {len(nonempty)} 个非空用例，覆盖不足"
    assert golden["cases"]["min10"]["results"] == []  # 合法为空


# ──────────────────────────────────────────────────────────────
# 预截断强峰列路径必须与全长解析等价
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("case, kw, with_i", CASES, ids=[c[0] for c in CASES])
def test_top_peak_columns_equivalent(synth, synth_top, case, kw, with_i):
    """peaks_top_d/peaks_top_i 存在且 max_ref_peaks ≤ PEAK_TOP_N 时走快路径,
    结果必须与全长解析逐字段一致。

    只排除 ``short_d`` / ``short_i`` 这两行**人为制造 d/I 长度不等**的数据：
    快路径把预截断列当作"已对齐的 (d, I) 对"，而慢路径对长度不等的行做
    ``k < len(d)`` 过滤 —— 真实建库时
    :func:`top_peaks_of` 的输入本就对齐，``build_top_peak_columns`` 写出的
    两列长度必然相等，故该分歧在真实库上不可达（属旧实现既有语义，不在
    v4.2 处理范围）。
    """
    assert has_top_peak_columns(synth_top)
    assert not has_top_peak_columns(synth)
    md, mi = _meas_for(case)
    if not with_i:
        mi = None
    slow = search_phases_by_d_peaks(synth, md, mi, **kw)
    fast = search_phases_by_d_peaks(synth_top, md, mi, **kw)
    slow = [r for r in slow if r["cod_id"] not in LEN_MISMATCH_IDS]
    fast = [r for r in fast if r["cod_id"] not in LEN_MISMATCH_IDS]
    assert len(slow) == len(fast), case
    for a, b in zip(slow, fast):
        assert a["cod_id"] == b["cod_id"], case
        for k, v in a.items():
            if isinstance(v, float):
                assert b[k] == pytest.approx(v, rel=1e-12, abs=1e-12), f"{case}.{k}"
            else:
                assert b[k] == v, f"{case}.{k}"


def test_max_ref_peaks_beyond_top_n_falls_back(synth, synth_top):
    """max_ref_peaks > PEAK_TOP_N 必须回退全长解析, 不得静默变结果。"""
    kw = dict(tolerance=0.02, tolerance_rel=0.006, min_match=1, limit=1000,
              max_ref_peaks=200)
    assert synth_top is not synth
    full = search_phases_by_d_peaks(synth, MD_MAIN, MI_MAIN, **kw)
    fallback = search_phases_by_d_peaks(synth_top, MD_MAIN, MI_MAIN, **kw)
    assert len(full) == len(fallback)
    for a, b in zip(full, fallback):
        assert a["cod_id"] == b["cod_id"]
        for k, v in a.items():
            if isinstance(v, float):
                assert b[k] == pytest.approx(v, rel=1e-12, abs=1e-12), k
            else:
                assert b[k] == v, k


# ──────────────────────────────────────────────────────────────
# 边界输入
# ──────────────────────────────────────────────────────────────
def test_empty_and_none_inputs(synth):
    assert search_phases_by_d_peaks(synth, []) == []
    assert search_phases_by_d_peaks(None, [1.0]) == []


def test_measured_i_length_mismatch_degrades(synth):
    """measured_i 长度不符 -> 视作未提供强度 (不报错)。"""
    got = search_phases_by_d_peaks(synth, [1.0, 2.0], [100], tolerance=0.02,
                                   min_match=1)
    assert got and all(r["main_peak_match"] == 0.0 for r in got)
    assert all(r["intensity_weighted_top_recall"] == 0.0 for r in got)


def test_empty_table_returns_empty():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_phases(conn)
    conn.commit()
    assert search_phases_by_d_peaks(conn, [1.0, 2.0, 3.0]) == []
    conn.close()


def test_missing_table_raises():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(sqlite3.OperationalError):
        search_phases_by_d_peaks(conn, [1.0])
    conn.close()


def test_limit_is_respected(synth):
    got = search_phases_by_d_peaks(synth, MD_MAIN, MI_MAIN, min_match=1,
                                   limit=3, tolerance=0.02, tolerance_rel=0.006)
    assert len(got) == 3


# ──────────────────────────────────────────────────────────────
# helper 单元测试
# ──────────────────────────────────────────────────────────────
def test_parse_float_csv_basic():
    assert list(parse_float_csv("4.983,3.826,2.44")) == [4.983, 3.826, 2.44]
    assert parse_float_csv("4.983, 3.826 , 2.44").tolist() == [4.983, 3.826, 2.44]
    assert parse_float_csv("").size == 0
    assert parse_float_csv("  ").size == 0
    assert parse_float_csv("4.983").tolist() == [4.983]
    assert parse_float_csv("1e-3,2E2").tolist() == [1e-3, 2e2]


def test_parse_float_csv_malformed_matches_old_semantics():
    """空字段必须被**丢弃**, 不能注入假峰也不能截断。

    这条专门盯住 np.fromstring(s, sep=",") 这个陷阱:
    "4.9,  ,2.4" → [4.9, -1.0, 2.4] (凭空一个 -1 Å 假峰);
    "4.9,,2.4"   → [4.9] (静默截断)。
    """
    old = lambda s: [float(x) for x in s.split(",") if x.strip()]  # noqa: E731
    for s in ["4.983,  ,2.44", "4.983,,2.44", "  ", "", "4.983",
              " 1.0 , 2.0 ", "4.983,3.826,2.44"]:
        assert list(parse_float_csv(s)) == old(s), s


def test_parse_float_csv_bytes_is_zero_copy():
    arr = np.array([1.5, 2.5, 3.5], dtype=np.float64)
    got = parse_float_csv(arr.tobytes())
    assert got.dtype == np.float64
    assert got.tolist() == [1.5, 2.5, 3.5]


def test_parse_float_csv_bad_token_raises_like_old():
    with pytest.raises(ValueError):
        parse_float_csv("1.0,abc")


def test_tol_scalar():
    assert tol_scalar(3.0, 0.02, 0.006, False) == 0.02
    # 相对分量要**超过**绝对下限才生效: 0.006*3.0 = 0.018 < 0.02 -> 取 0.02
    assert tol_scalar(3.0, 0.02, 0.006, True) == pytest.approx(0.02)
    # d > 0.02/0.006 = 3.333 之后相对分量才接管
    assert tol_scalar(4.0, 0.02, 0.006, True) == pytest.approx(0.024)
    assert tol_scalar(10.0, 0.02, 0.006, True) == pytest.approx(0.06)
    assert tol_scalar(1.0, 0.02, 0.006, True) == 0.02
    # NaN 时与内置 max() 一致: max(0.02, nan) -> 0.02
    assert tol_scalar(float("nan"), 0.02, 0.006, True) == 0.02
    assert max(0.02, 0.006 * float("nan")) == 0.02


def test_interval_hit_boundaries():
    data = np.array([1.0, 2.0, 3.0])
    assert interval_hit(data, [0.5], [1.5]).tolist() == [True]
    # 边界闭区间: lo=1.0 / hi=1.0 都算命中
    assert interval_hit(data, [1.0], [1.0]).tolist() == [True]
    assert interval_hit(data, [1.01], [1.99]).tolist() == [False]
    assert interval_hit(data, [2.5], [2.6]).tolist() == [False]
    assert interval_hit(data, [3.5], [4.0]).tolist() == [False]
    assert interval_hit(data, [0.0], [0.5]).tolist() == [False]
    # 空数据
    assert interval_hit(np.array([]), [0.0], [9.0]).tolist() == [False]
    # 多查询
    got = interval_hit(data, [0.5, 1.01, 2.99], [1.5, 1.99, 3.01])
    assert got.tolist() == [True, False, True]


def test_match_positions_leftmost_index():
    data = np.array([1.0, 2.0, 3.0, 4.0])
    hit, pos = match_positions(data, [1.5, 2.0, 9.0], [2.5, 2.0, 10.0])
    assert hit.tolist() == [True, True, False]
    # 命中时取"最左命中点下标", 供调用方去重计数
    assert pos[hit].tolist() == [1, 1]


def test_dedupe_by_tol_order_and_asymmetry():
    assert dedupe_by_tol([1.0, 1.03], 0.02, 0.0, False) == [1.0, 1.03]
    # 恰差 = 容差 -> 丢弃 (`<=`)。1.02-1.0 在 float64 下是
    # 0.020000000000000018 (> 0.02), 反而应保留。
    assert dedupe_by_tol([1.0, 1.25], 0.25, 0.0, False) == [1.0]
    assert dedupe_by_tol([1.0, 1.02], 0.02, 0.0, False) == [1.0, 1.02]
    # 顺序敏感: 先到者留下
    assert dedupe_by_tol([1.03, 1.0], 0.02, 0.0, False) == [1.03, 1.0]
    # 相对容差放大: d=3.05 的容差 = max(0.02, 0.061) = 0.061 -> |0.05| 被丢
    assert dedupe_by_tol([3.0, 3.05], 0.02, 0.02, True) == [3.0]
    assert dedupe_by_tol([3.0, 3.07], 0.02, 0.02, True) == [3.0, 3.07]
    # 返回 list (调用方要用 `if unique_top_d:` 判空)
    assert isinstance(dedupe_by_tol([1.0, 2.0], 0.02, 0.0, False), list)
    assert dedupe_by_tol([], 0.02, 0.0, False) == []


def test_dedupe_by_tol_nan_kept_like_old():
    """NaN 的容差: 旧实现 max(tol, nan)=tol, abs(nan-ud)<=tol 为假 -> 保留。"""
    got = dedupe_by_tol([float("nan"), 1.0], 0.02, 0.006, True)
    assert len(got) == 2 and got[1] == 1.0


def test_top_peaks_of_order_and_short_filter():
    d = np.array([1.0, 2.0, 3.5])
    i = np.array([10.0, 50.0, 30.0])
    td, ti = top_peaks_of(d, i, top_n=2)
    assert td.tolist() == [2.0, 3.5] and ti.tolist() == [50.0, 30.0]
    # i 比 d 长 -> 超出 d 长度的下标必须被过滤（但顺序仍按 I 降序）
    d2 = np.array([1.0, 2.0])
    i2 = np.array([1.0, 5.0, 9.0])
    td2, ti2 = top_peaks_of(d2, i2, top_n=3)
    assert td2.tolist() == [2.0, 1.0] and ti2.tolist() == [5.0, 1.0]
    # 空输入
    e, f = top_peaks_of(np.array([]), np.array([]))
    assert e.size == 0 and f.size == 0


def test_has_top_peak_columns_false_on_bad_conn():
    class _Boom:
        def execute(self, *a, **k):
            raise RuntimeError("boom")

    assert has_top_peak_columns(_Boom()) is False
    assert has_top_peak_columns(None) is False


# ──────────────────────────────────────────────────────────────
# 模块纯度 / 别名
# ──────────────────────────────────────────────────────────────
def test_phase_search_is_pure_module():
    """不得 import sqlite3 / PySide6 / 读配置路径（AST 检查，不受 docstring 干扰）。"""
    import ast

    src = Path(ps.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {"sqlite3", "PySide6", "polyxrd.config"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in {"sqlite3", "PySide6"}, a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in banned, node.module
            assert not node.module.startswith("PySide6"), node.module


def test_public_aliases_match_private_names():
    assert ps._parse_float_csv is ps.parse_float_csv
    assert ps._tol_scalar is ps.tol_scalar
    assert ps._interval_hit is ps.interval_hit
    assert ps._match_positions is ps.match_positions
    assert ps._dedupe_by_tol is ps.dedupe_by_tol
    assert ps._top_peaks_of is ps.top_peaks_of
    assert ps._PEAK_TOP_N == ps.PEAK_TOP_N == 64


def test_signature_has_conn_first():
    import inspect

    params = list(inspect.signature(search_phases_by_d_peaks).parameters)
    assert params[:3] == ["conn", "measured_d", "measured_i"]
