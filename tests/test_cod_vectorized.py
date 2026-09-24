"""向量化检索打分 (0.9.12) 回归测试。

`CIFDatabase.search_cod_by_d_peaks` 的扫描层由逐相 Python 循环改成了
NumPy 批量操作。这个改动**不允许**改变任何输出字段, 包括并列时的先后、
去重顺序、`n_matched_meas` 的"最左命中下标去重"口径。

因此本测试的 oracle 是 **git 上一版的模块本体** —— 由

    git show HEAD~N:src/polyxrd/services/cif_database.py > tests/_cif_old_ref.py

导出为 `tests/_cif_old_ref.py`, 零转写风险。若该文件不存在则跳过比对
部分 (helper 的单元测试仍会跑)。

运行::

    python -m pytest tests/test_cod_vectorized.py -v
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from polyxrd.services.cif_database import (  # noqa: E402
    CIFDatabase,
    _dedupe_by_tol,
    _interval_hit,
    _match_positions,
    _parse_float_csv,
    _tol_scalar,
    has_top_peak_columns,
    top_peak_column_stats,
)

OLD_REF = Path(__file__).resolve().parent / "_cif_old_ref.py"
HAS_ORACLE = OLD_REF.exists()

FIELDS = [
    "cod_id", "ref_id", "display_id", "formula", "space_group", "n_peaks",
    "n_ref_used", "n_matched_ref", "n_matched_meas", "n_meas_in_top",
    "n_top_unique", "n_top_observed", "n_top_k", "top_recall", "top_precision",
    "intensity_weighted_top_recall", "main_peak_match", "match_ratio",
    "meas_ratio", "score",
]
# cod_id 的 SQLite 类型随建库方式而变 (int/str), 不算语义差异
COMPARE_FIELDS = [f for f in FIELDS if f != "cod_id"]


# ──────────────────────────────────────────────────────────────
# 合成对抗库: 把去重/容差/稳定排序的边界全部摆出来
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


def _build_synth(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE phases (cod_id TEXT, ref_id TEXT, display_id TEXT, "
        "formula TEXT, space_group TEXT, n_peaks INTEGER, "
        "peaks_d TEXT, peaks_i TEXT)"
    )
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
    conn.executemany("INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


class _Bound:
    """把某个连接绑到 (未 __init__ 的) CIFDatabase 实例上。"""

    def __init__(self, cls, conn):
        self._conn = conn
        self._db = cls.__new__(cls)

    def search_cod_by_d_peaks(self, *a, **kw):
        self._db._cod_conn = self._conn
        return self._db.search_cod_by_d_peaks(*a, **kw)


def _oracle_cls():
    if not HAS_ORACLE:
        pytest.skip("缺少 oracle 模块 tests/_cif_old_ref.py")
    from _cif_old_ref import CIFDatabase as Old
    return Old


# ──────────────────────────────────────────────────────────────
# helper 单元测试
# ──────────────────────────────────────────────────────────────
def test_parse_float_csv_basic():
    assert list(_parse_float_csv("4.983,3.826,2.44")) == [4.983, 3.826, 2.44]
    assert _parse_float_csv("4.983, 3.826 , 2.44").tolist() == [4.983, 3.826, 2.44]
    assert _parse_float_csv("").size == 0
    assert _parse_float_csv("  ").size == 0
    assert _parse_float_csv("4.983").tolist() == [4.983]
    assert _parse_float_csv("1e-3,2E2").tolist() == [1e-3, 2e2]


def test_parse_float_csv_malformed_matches_old_semantics():
    """空字段必须被**丢弃**, 不能注入假峰也不能截断。

    这条专门盯住 np.fromstring(s, sep=",") 这个陷阱:
    "4.9,  ,2.4" → [4.9, -1.0, 2.4] (凭空一个 -1 Å 假峰);
    "4.9,,2.4"   → [4.9] (静默截断)。
    """
    old = lambda s: [float(x) for x in s.split(",") if x.strip()]  # noqa: E731
    for s in ["4.983,  ,2.44", "4.983,,2.44", "  ", "", "4.983",
              " 1.0 , 2.0 ", "4.983,3.826,2.44"]:
        assert list(_parse_float_csv(s)) == old(s), s


def test_parse_float_csv_bytes_is_zero_copy():
    arr = np.array([1.5, 2.5, 3.5], dtype=np.float64)
    got = _parse_float_csv(arr.tobytes())
    assert got.dtype == np.float64
    assert got.tolist() == [1.5, 2.5, 3.5]


def test_parse_float_csv_bad_token_raises_like_old():
    with pytest.raises(ValueError):
        _parse_float_csv("1.0,abc")


def test_tol_scalar():
    assert _tol_scalar(3.0, 0.02, 0.006, False) == 0.02
    # 相对分量要**超过**绝对下限才生效: 0.006*3.0 = 0.018 < 0.02 -> 取 0.02
    assert _tol_scalar(3.0, 0.02, 0.006, True) == pytest.approx(0.02)
    # d > 0.02/0.006 = 3.333 之后相对分量才接管
    assert _tol_scalar(4.0, 0.02, 0.006, True) == pytest.approx(0.024)
    assert _tol_scalar(10.0, 0.02, 0.006, True) == pytest.approx(0.06)
    assert _tol_scalar(1.0, 0.02, 0.006, True) == 0.02
    # NaN 时与内置 max() 一致: max(0.02, nan) -> 0.02
    assert _tol_scalar(float("nan"), 0.02, 0.006, True) == 0.02
    assert max(0.02, 0.006 * float("nan")) == 0.02


def test_interval_hit_boundaries():
    data = np.array([1.0, 2.0, 3.0])
    # 窗口 [0.5,1.5] 命中 1.0
    assert _interval_hit(data, [0.5], [1.5]).tolist() == [True]
    # 边界闭区间: lo=1.0 / hi=1.0 都算命中
    assert _interval_hit(data, [1.0], [1.0]).tolist() == [True]
    # 窗口落在 1.0 与 2.0 之间 -> 不命中
    assert _interval_hit(data, [1.01], [1.99]).tolist() == [False]
    # 窗口落在 2.0 与 3.0 之间 -> 不命中 (附近有数据点但都不在窗口内)
    assert _interval_hit(data, [2.5], [2.6]).tolist() == [False]
    # 超出两端
    assert _interval_hit(data, [3.5], [4.0]).tolist() == [False]
    assert _interval_hit(data, [0.0], [0.5]).tolist() == [False]
    # 空数据
    assert _interval_hit(np.array([]), [0.0], [9.0]).tolist() == [False]
    # 多查询
    got = _interval_hit(data, [0.5, 1.01, 2.99], [1.5, 1.99, 3.01])
    assert got.tolist() == [True, False, True]


def test_match_positions_leftmost_index():
    data = np.array([1.0, 2.0, 3.0, 4.0])
    hit, pos = _match_positions(data, [1.5, 2.0, 9.0], [2.5, 2.0, 10.0])
    assert hit.tolist() == [True, True, False]
    # 命中时取"最左命中点下标", 供调用方去重计数
    assert pos[hit].tolist() == [1, 1]


def test_dedupe_by_tol_order_and_asymmetry():
    # 容差取自**候选自身**: d=1.0 容差 0.02, d=1.03 已是新峰 (1.03-1.0=0.03>0.02)
    assert _dedupe_by_tol([1.0, 1.03], 0.02, 0.0, False) == [1.0, 1.03]
    # 恰差 = 容差 -> 丢弃 (`<=`)。这里特意选二进制可精确表示的差值:
    # 1.02-1.0 在 float64 下是 0.020000000000000018 (> 0.02), 反而应保留。
    assert _dedupe_by_tol([1.0, 1.25], 0.25, 0.0, False) == [1.0]
    assert _dedupe_by_tol([1.0, 1.02], 0.02, 0.0, False) == [1.0, 1.02]
    # 顺序敏感: 先到者留下, 且容差随候选变
    assert _dedupe_by_tol([1.03, 1.0], 0.02, 0.0, False) == [1.03, 1.0]
    # 相对容差放大: d=3.05 的容差 = max(0.02, 0.061) = 0.061 -> |0.05| 被丢
    assert _dedupe_by_tol([3.0, 3.05], 0.02, 0.02, True) == [3.0]
    assert _dedupe_by_tol([3.0, 3.07], 0.02, 0.02, True) == [3.0, 3.07]
    # 返回 list (调用方要用 `if unique_top_d:` 判空)
    assert isinstance(_dedupe_by_tol([1.0, 2.0], 0.02, 0.0, False), list)
    assert _dedupe_by_tol([], 0.02, 0.0, False) == []


def test_dedupe_by_tol_nan_kept_like_old():
    """NaN 的 nan 容差: 旧实现 max(tol, nan)=tol, abs(nan-ud)<=tol 为假 -> 保留。"""
    got = _dedupe_by_tol([float("nan"), 1.0], 0.02, 0.006, True)
    assert len(got) == 2 and got[1] == 1.0


# ──────────────────────────────────────────────────────────────
# 合成库: 新旧实现逐字段比对
# ──────────────────────────────────────────────────────────────
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


def _meas_for(case):
    if case == "single_meas":
        return [2.0], [100]
    if case == "two_meas":
        return [1.0, 4.0], [100, 50]
    return MD_MAIN, MI_MAIN


@pytest.fixture(scope="module")
def synth():
    path = Path(tempfile.mkdtemp()) / "synth.sqlite"
    conn = _build_synth(path)
    yield conn
    conn.close()


@pytest.mark.parametrize("case, kw, with_i", CASES, ids=[c[0] for c in CASES])
def test_synth_matches_oracle(synth, case, kw, with_i):
    Old = _oracle_cls()
    md, mi = _meas_for(case)
    if not with_i:
        mi = None
    old = _Bound(Old, synth).search_cod_by_d_peaks(md, mi, **kw)
    new = _Bound(CIFDatabase, synth).search_cod_by_d_peaks(md, mi, **kw)

    assert len(old) == len(new), f"{case}: 长度 {len(old)} != {len(new)}"
    # min10 在合成库上合法地为空 (没有相能覆盖 10 个独立测量峰)
    if case not in ("min10",):
        assert new, f"{case}: 结果为空, 用例没覆盖到打分逻辑"
    for i, (a, b) in enumerate(zip(old, new)):
        for f in COMPARE_FIELDS:
            va, vb = a[f], b[f]
            if isinstance(va, float):
                assert vb == pytest.approx(va, rel=1e-12, abs=1e-12), \
                    f"{case}: #{i} {f} {va!r} != {vb!r}"
            else:
                assert va == vb, f"{case}: #{i} {f} {va!r} != {vb!r}"


def test_synth_deep_coverage():
    """确认合成库确实产出了非平凡候选集 (否则上面的比对等于没测)。"""
    Old = _oracle_cls()
    got = _Bound(Old, _build_synth(Path(tempfile.mkdtemp()) / "s.sqlite")) \
        .search_cod_by_d_peaks(MD_MAIN, MI_MAIN, tolerance=0.02,
                               tolerance_rel=0.006, min_match=1, limit=1000,
                               max_ref_peaks=40)
    assert len(got) >= 11, f"只有 {len(got)} 条候选, 覆盖不足"


# ──────────────────────────────────────────────────────────────
# 真实 COD 库 (抽样, 保证真实数据形态又不必全表跑两遍)
# ──────────────────────────────────────────────────────────────
SAMPLE_N = 4000


def _cod_ready() -> bool:
    try:
        return CIFDatabase(enable_cod_local=True)._get_cod_conn() is not None
    except Exception:
        return False


@pytest.fixture(scope="module")
def real_sample():
    """从真实 COD 库等距抽 4000 相 (含空/畸形行), 灌进临时库。"""
    if not _cod_ready():
        pytest.skip("COD 无机库不可用")
    src = CIFDatabase(enable_cod_local=True)._get_cod_conn()
    total = int(src.execute("SELECT COUNT(*) FROM phases").fetchone()[0])
    step = max(1, total // SAMPLE_N)
    path = Path(tempfile.mkdtemp()) / "sample.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE phases (cod_id TEXT, ref_id TEXT, display_id TEXT, "
        "formula TEXT, space_group TEXT, n_peaks INTEGER, "
        "peaks_d TEXT, peaks_i TEXT)"
    )
    rows = src.execute(
        "SELECT cod_id, ref_id, display_id, formula, space_group, n_peaks, "
        "peaks_d, peaks_i FROM phases WHERE rowid % ? = 0", (step,)
    ).fetchall()
    conn.executemany(
        "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?)",
        [tuple(r) for r in rows],
    )
    conn.commit()
    assert len(rows) >= 1000, f"抽样过少: {len(rows)}"
    yield conn
    conn.close()


@pytest.mark.parametrize("kw", [
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=3, limit=100, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.0, min_match=3, limit=100, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.02, min_match=3, limit=100, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=1, limit=500, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=10, limit=100, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=3, limit=100, max_ref_peaks=8),
], ids=["默认", "绝对容差", "相对容差", "min1", "min10", "maxref8"])
@pytest.mark.parametrize("with_i", [True, False], ids=["有强度", "无强度"])
def test_real_sample_matches_oracle(real_sample, kw, with_i):
    """⚠️ 这里**故意不含** elements_allowed 用例。

    v0.13.2 有意改变了「formula 不可信时」的扫描层行为: 旧实现把解析不出
    元素的 formula 直接淘汰 (``if not els ... continue``), 新实现改为
    **fail-open** (放行, 交给判定层用 CIF 复核) —— 否则 COD 无机库那 609 条
    被空间群符号覆盖的 formula 会让真物相在扫描层就被误杀 (实测 ZnO)。
    因此含元素过滤的场景不再是逐字段等价, 其新语义由
    ``tests/test_inorg_formula_fix.py::TestScanLayerFailOpen`` 与下面的
    ``test_elements_allowed_is_superset_of_oracle`` 专门守住。
    """
    Old = _oracle_cls()
    rng = np.random.default_rng(7)
    md = sorted(rng.uniform(0.9, 6.0, 50).tolist())
    mi = sorted(rng.uniform(1, 100, 50).tolist(), reverse=True)
    if not with_i:
        mi = None
    old = _Bound(Old, real_sample).search_cod_by_d_peaks(md, mi, **kw)
    new = _Bound(CIFDatabase, real_sample).search_cod_by_d_peaks(md, mi, **kw)
    assert len(old) == len(new)
    for i, (a, b) in enumerate(zip(old, new)):
        for f in COMPARE_FIELDS:
            va, vb = a[f], b[f]
            if isinstance(va, float):
                assert vb == pytest.approx(va, rel=1e-12, abs=1e-12), \
                    f"#{i} {f} {va!r} != {vb!r}"
            else:
                assert va == vb, f"#{i} {f} {va!r} != {vb!r}"


def _filtered_kw(allowed):
    return dict(tolerance=0.02, tolerance_rel=0.006, min_match=3,
                limit=100, max_ref_peaks=40, elements_allowed=allowed)


@pytest.mark.skipif(not _cod_ready(), reason="COD 无机库不可用")
@pytest.mark.parametrize("with_i", [True, False], ids=["有强度", "无强度"])
def test_elements_allowed_is_superset_of_oracle(real_sample, with_i):
    """元素过滤: 新结果必须是旧结果的**超集**, 且多出来的只可能是不可信行。

    fail-open 只该"少淘汰", 不该让原本命中的候选消失, 也不该改变命中项
    的相对顺序。多出来的条目其 formula 必须与 space_group 相同 (或为空)。
    """
    Old = _oracle_cls()
    rng = np.random.default_rng(7)
    md = sorted(rng.uniform(0.9, 6.0, 50).tolist())
    mi = sorted(rng.uniform(1, 100, 50).tolist(), reverse=True)
    if not with_i:
        mi = None
    kw = _filtered_kw({"O", "Ca", "C"})
    old = _Bound(Old, real_sample).search_cod_by_d_peaks(md, mi, **kw)
    new = _Bound(CIFDatabase, real_sample).search_cod_by_d_peaks(md, mi, **kw)
    old_ids = [r["cod_id"] for r in old]
    new_ids = [r["cod_id"] for r in new]
    assert set(old_ids) <= set(new_ids), "旧候选不得因 fail-open 而消失"
    assert [i for i in new_ids if i in set(old_ids)] == old_ids, "命中项顺序不得变"
    extra = [i for i in new_ids if i not in set(old_ids)]
    by_id = {r["cod_id"]: r for r in new}
    for cid in extra:
        f = (by_id[cid]["formula"] or "").strip()
        sg = (by_id[cid]["space_group"] or "").strip()
        assert (not f) or (f == sg), \
            f"多出的 {cid} formula={f!r} 并非不可信行 (sg={sg!r}) → 过滤逻辑漏了"


@pytest.mark.skipif(not _cod_ready(), reason="COD 无机库不可用")
def test_real_cod_empty_and_edge_inputs():
    db_new = CIFDatabase(enable_cod_local=True)
    db_old = _oracle_cls()(enable_cod_local=True)
    for md, mi in [([], None), ([2.0], None), ([2.0], [100]),
                   ([1.0, 2.0], [10]), ([0.5], [1])]:
        a = db_old.search_cod_by_d_peaks(md, mi, tolerance=0.02, limit=20)
        b = db_new.search_cod_by_d_peaks(md, mi, tolerance=0.02, limit=20)
        assert len(a) == len(b)


# ──────────────────────────────────────────────────────────────
# 预截断强峰列 (_PEAK_TOP_N): 前缀等价 + 超范围回退
# ──────────────────────────────────────────────────────────────
def _fill_sample(src_rows, path: Path) -> sqlite3.Connection:
    """建一份与真实 COD 库同形的抽样库 (含 cell_* 等列)。"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE phases (cod_id TEXT, formula TEXT, space_group TEXT, "
        "cell_a REAL, cell_b REAL, cell_c REAL, cell_alpha REAL, "
        "cell_beta REAL, cell_gamma REAL, n_peaks INTEGER, peaks_d TEXT, "
        "peaks_i TEXT, ref_id TEXT, display_id TEXT)"
    )
    conn.executemany(
        "INSERT INTO phases (cod_id, ref_id, display_id, formula, "
        "space_group, n_peaks, peaks_d, peaks_i) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [tuple(r) for r in src_rows],
    )
    conn.commit()
    return conn


@pytest.fixture(scope="module")
def precomp_pair(tmp_path_factory):
    """同一份数据两份拷贝: (未迁移连接, 已迁移连接)。"""
    from polyxrd.services.cif_database import (
        _PEAK_TOP_N,
        build_top_peak_columns,
    )

    if not _cod_ready():
        pytest.skip("COD 无机库不可用")
    src = CIFDatabase(enable_cod_local=True)._get_cod_conn()
    total = int(src.execute("SELECT COUNT(*) FROM phases").fetchone()[0])
    step = max(1, total // SAMPLE_N)
    rows = src.execute(
        "SELECT cod_id, ref_id, display_id, formula, space_group, n_peaks, "
        "peaks_d, peaks_i FROM phases WHERE rowid % ? = 0", (step,)
    ).fetchall()
    d = tmp_path_factory.mktemp("precomp")
    plain = _fill_sample(rows, d / "plain.sqlite")
    top_path = d / "top.sqlite"
    _fill_sample(rows, top_path)
    info = build_top_peak_columns(top_path, top_n=_PEAK_TOP_N, backup=False)
    assert info["added_columns"] and info["rows_filled"] == len(rows)
    top = sqlite3.connect(top_path)
    top.row_factory = sqlite3.Row
    assert has_top_peak_columns(top), "迁移后应检测到预截断列"
    assert not has_top_peak_columns(plain), "未迁移库不应被误判"
    yield plain, top
    plain.close()
    top.close()


TOP_N_KW = [
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=3, limit=100, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.0, min_match=3, limit=100, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.02, min_match=1, limit=500, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=10, limit=100, max_ref_peaks=40),
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=3, limit=100, max_ref_peaks=12),
    dict(tolerance=0.02, tolerance_rel=0.006, min_match=3, limit=100, max_ref_peaks=64),
]


@pytest.mark.parametrize("kw", TOP_N_KW, ids=[str(k["max_ref_peaks"]) + "-"
                                             + str(k["min_match"]) + "-"
                                             + str(k["tolerance_rel"])
                                             for k in TOP_N_KW])
@pytest.mark.parametrize("with_i", [True, False], ids=["有强度", "无强度"])
def test_precomputed_matches_oracle(precomp_pair, kw, with_i):
    """迁移后结果必须与 oracle (旧实现) 以及迁移前逐字段一致。"""
    Old = _oracle_cls()
    plain, top = precomp_pair
    rng = np.random.default_rng(11)
    md = sorted(rng.uniform(0.9, 6.0, 50).tolist())
    mi = sorted(rng.uniform(1, 100, 50).tolist(), reverse=True)
    if not with_i:
        mi = None
    ref = _Bound(Old, plain).search_cod_by_d_peaks(md, mi, **kw)
    before = _Bound(CIFDatabase, plain).search_cod_by_d_peaks(md, mi, **kw)
    after = _Bound(CIFDatabase, top).search_cod_by_d_peaks(md, mi, **kw)
    assert len(ref) == len(before) == len(after), \
        f"{len(ref)} / {len(before)} / {len(after)}"
    assert after, "结果为空, 覆盖不足"
    for i, (a, b, c) in enumerate(zip(ref, before, after)):
        for f in COMPARE_FIELDS:
            va, vb, vc = a[f], b[f], c[f]
            if isinstance(va, float):
                assert vb == pytest.approx(va, rel=1e-12, abs=1e-12), \
                    f"#{i} {f} 迁移前 {va!r} != {vb!r}"
                assert vc == pytest.approx(va, rel=1e-12, abs=1e-12), \
                    f"#{i} {f} 迁移后 {va!r} != {vc!r}"
            else:
                assert vb == va and vc == va, \
                    f"#{i} {f} {va!r} / {vb!r} / {vc!r}"


def test_fallback_when_max_ref_exceeds_top_n(precomp_pair):
    """max_ref_peaks > _PEAK_TOP_N 必须回退全长解析 (不能静默少取峰)。"""
    from polyxrd.services.cif_database import _PEAK_TOP_N

    Old = _oracle_cls()
    plain, top = precomp_pair
    rng = np.random.default_rng(11)
    md = sorted(rng.uniform(0.9, 6.0, 50).tolist())
    mi = sorted(rng.uniform(1, 100, 50).tolist(), reverse=True)
    kw = dict(tolerance=0.02, tolerance_rel=0.006, min_match=1,
              limit=500, max_ref_peaks=_PEAK_TOP_N + 30)
    ref = _Bound(Old, plain).search_cod_by_d_peaks(md, mi, **kw)
    got = _Bound(CIFDatabase, top).search_cod_by_d_peaks(md, mi, **kw)
    assert len(ref) == len(got)
    assert got
    for i, (a, b) in enumerate(zip(ref, got)):
        assert b["n_ref_used"] == a["n_ref_used"], \
            f"#{i} n_ref_used {a['n_ref_used']} != {b['n_ref_used']} (未回退?)"


def test_top_peaks_of_prefix_equivalence():
    """_top_peaks_of 的前缀必须与全长 argsort 一致 (含并列时的先后)。"""
    from polyxrd.services.cif_database import _top_peaks_of

    # I 大量并列 + 一个 d 比 i 短的行
    d = np.array([1.0, 1.1, 1.2, 1.3, 1.4, 1.5])
    i = np.array([50.0, 50.0, 90.0, 50.0, 70.0, 50.0])
    d_top, i_top = _top_peaks_of(d, i, 3)
    full = np.argsort(-i, kind="stable")
    assert d_top.tolist() == d[full[:3]].tolist()
    assert i_top.tolist() == i[full[:3]].tolist()
    # 并列的 I 保持原始先后 (index 0 早于 index 1)
    assert d_top.tolist() == [1.2, 1.4, 1.0]
    # top_n 超过峰数 -> 全取
    assert _top_peaks_of(d, i, 99)[0].size == 6
    # 空输入
    e = np.empty(0)
    assert _top_peaks_of(e, e)[0].size == 0


def test_top_peaks_of_filters_d_shorter_than_i():
    from polyxrd.services.cif_database import _top_peaks_of

    d = np.array([1.0, 2.0])
    i = np.array([10.0, 30.0, 20.0])   # 最长的是 index 1, 合法
    d_top, i_top = _top_peaks_of(d, i, 5)
    assert d_top.tolist() == [2.0, 1.0]
    assert i_top.tolist() == [30.0, 10.0]


def test_build_top_peak_columns_is_idempotent(tmp_path):
    """重复迁移只补缺, 不重复写; top_n < 12 直接拒绝。"""
    from polyxrd.services.cif_database import build_top_peak_columns

    path = tmp_path / "s.sqlite"
    conn = _build_synth(path)
    conn.close()
    a = build_top_peak_columns(path, backup=False)
    b = build_top_peak_columns(path, backup=False)
    assert a["added_columns"] is True and a["rows_filled"] > 0
    assert b["added_columns"] is False and b["rows_filled"] == 0
    assert has_top_peak_columns(sqlite3.connect(str(path)))
    stats = top_peak_column_stats(path)
    assert stats["available"] and stats["pending"] == 0
    with pytest.raises(ValueError):
        build_top_peak_columns(path, top_n=8, backup=False)


def test_top_peak_column_stats_on_plain_db(tmp_path):
    path = tmp_path / "n.sqlite"
    _build_synth(path).close()
    stats = top_peak_column_stats(path)
    assert stats["available"] is False
    assert "无预截断列" in stats["reason"]


def test_get_cod_phase_still_returns_full_peak_list(precomp_pair):
    """迁移绝不能把物相详情页/FoM 的峰表截断。

    `get_cod_phase()` 供 FoM 打分与详情展示用, 必须仍读**全长**
    peaks_d/peaks_i (它显式列出列名, 所以不会碰到 peaks_top_*)。这条守卫
    防止有人为了"更省"把它也改成读预截断列 —— 那会改变 FoM 的输入。
    """
    from polyxrd.services.cif_database import CIFDatabase as DB

    _plain, top = precomp_pair
    db = DB.__new__(DB)
    db._cod_conn = top
    seen = 0
    for row in top.execute(
        "SELECT cod_id, n_peaks, peaks_d FROM phases LIMIT 60"
    ):
        detail = db.get_cod_phase(row["cod_id"])
        if not detail:
            continue
        seen += 1
        assert len(detail["peaks_d_list"]) == row["n_peaks"], (
            f"{row['cod_id']}: get_cod_phase 返回 "
            f"{len(detail['peaks_d_list'])} 个峰, 但 n_peaks={row['n_peaks']} "
            "(被截断了?)"
        )
        assert len(detail["peaks_i_list"]) == row["n_peaks"]
    assert seen > 0, "取样为空"
