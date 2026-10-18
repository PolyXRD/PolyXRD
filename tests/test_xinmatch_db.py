"""XinMatch 格式数据库适配 (v3.1.0) 单测
=====================================

三块内容各自钉牢:

1. **探测与判别** —— 四表齐才算 XinMatch 库; 反例 (缺表/非 sqlite/不存在)
   必须给出机器可读的错误标记, 而不是静默判成"别的库"。
2. **打分口径一致性** —— 这是本模块最要紧的一条。适配器没有复用
   ``search_cod_by_d_peaks`` 的循环 (那套是吃 ``phases.peaks_d`` 逗号串的),
   而是自己按同样口径算了一遍 Hanawalt 度量。所以这里**造一份同数据的
   PolyXRD 格式库**, 让两个实现对同一批峰逐字段比对 —— 任何一处口径漂移
   (顺序、容差、n_top 封顶、去重方向) 都会被这条用例抓住。
3. **任意位置挂载** —— 用户把库文件放在哪个文件夹都得能挂上; 指到文件夹
   时同目录下多类库一次全挂; 指到不合格的东西时要说清原因。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config          # noqa: E402
from polyxrd.services import db_import                    # noqa: E402
from polyxrd.services.xinmatch_db import (                # noqa: E402
    XinMatchDatabase,
    _cache_file_for,
    clear_index_cache,
    probe,
)

# ── 合成库 ───────────────────────────────────────────────────
#
# 三相对照设计:
#   XM-A  ZnO           —— "测量谱"就是从它的峰合成的, 必须排第一
#   XM-B  TiO2-rutile   —— 峰位与 A 部分重叠 (保证候选池非空)
#   XM-C  CaCO3         —— 峰位远离 A, 用于验证 min_match 剪枝
# 强度刻意全部互不相同, 避免 ORDER BY intensity DESC 的并列次序影响比对。

_ENTRY_DDL = """
CREATE TABLE entries (
    entry_id TEXT PRIMARY KEY, formula TEXT, mineral_name TEXT, space_group TEXT,
    crystal_system TEXT, a REAL, b REAL, c REAL, alpha REAL, beta REAL,
    gamma REAL, volume REAL, density REAL, color TEXT, year INTEGER,
    author TEXT, journal TEXT, quality TEXT, elements TEXT)
"""
_PEAK_DDL = """
CREATE TABLE peaks (
    entry_id TEXT NOT NULL, d REAL NOT NULL, intensity REAL,
    h INTEGER, k INTEGER, l INTEGER,
    FOREIGN KEY (entry_id) REFERENCES entries(entry_id))
"""
_ELEM_DDL = """
CREATE TABLE elements (entry_id TEXT NOT NULL, element TEXT NOT NULL,
    PRIMARY KEY (entry_id, element))
"""
_COMBO_DDL = """
CREATE TABLE element_combo (element_set_hash TEXT PRIMARY KEY, entry_ids TEXT NOT NULL)
"""

#: (entry_id, formula, mineral, sg, system, a,b,c,α,β,γ, elements)
_ENTRIES = [
    ("XM-A", "O Zn", "Zincite", "P 63 m c", "hexagonal",
     3.2495, 3.2495, 5.2069, 90.0, 90.0, 120.0, "O,Zn"),
    ("XM-B", "O2 Ti", "Rutile", "P 42/m n m", "tetragonal",
     4.5937, 4.5937, 2.9587, 90.0, 90.0, 90.0, "O,Ti"),
    ("XM-C", "C Ca O3", "Calcite", "R 3 c", "trigonal",
     4.9896, 4.9896, 17.061, 90.0, 90.0, 120.0, "C,Ca,O"),
]
#: entry_id → [(d, I), ...] (强度互不相同且已按降序给出)
_PEAKS = {
    "XM-A": [(2.4759, 570.0), (2.6023, 441.0), (1.4762, 291.0),
             (1.6263, 236.0), (1.9111, 121.0), (1.3782, 88.0),
             (1.3582, 61.0), (1.3017, 43.0)],
    "XM-B": [(3.2482, 999.0), (1.6874, 502.0), (2.4870, 171.0),
             (1.4798, 133.0), (1.3572, 92.0), (1.2518, 47.0)],
    "XM-C": [(3.0354, 1000.0), (2.2845, 213.0), (2.0937, 187.0),
             (1.9127, 176.0), (1.8755, 129.0), (1.6033, 71.0)],
}


def _make_xinmatch_db(path: Path) -> Path:
    """合成一个最小合法的 XinMatch 格式库。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_ENTRY_DDL)
    conn.execute(_PEAK_DDL)
    conn.execute(_ELEM_DDL)
    conn.execute(_COMBO_DDL)
    for eid, formula, mineral, sg, system, a, b, c, al, be, ga, els in _ENTRIES:
        conn.execute(
            "INSERT INTO entries (entry_id, formula, mineral_name, space_group,"
            " crystal_system, a, b, c, alpha, beta, gamma, volume, density,"
            " quality, elements) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, formula, mineral, sg, system, a, b, c, al, be, ga,
             a * b * c, None, "", els))
        for k, (d, i) in enumerate(_PEAKS[eid]):
            conn.execute(
                "INSERT INTO peaks (entry_id, d, intensity, h, k, l)"
                " VALUES (?,?,?,?,?,?)", (eid, d, i, k, 0, 0))
        for el in els.split(","):
            conn.execute("INSERT INTO elements VALUES (?,?)", (eid, el))
        conn.execute("INSERT INTO element_combo VALUES (?,?)",
                     (f"hash-{eid}", eid))
    conn.commit()
    conn.close()
    return path


_PHASES_DDL = """
CREATE TABLE phases (
    cod_id INTEGER PRIMARY KEY, ref_id TEXT, display_id TEXT, formula TEXT,
    space_group TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT,
    cell_a REAL, cell_b REAL, cell_c REAL,
    cell_alpha REAL, cell_beta REAL, cell_gamma REAL)
"""


def _make_phases_db(path: Path) -> Path:
    """同数据、PolyXRD ``phases`` 格式的库 (供口径比对用)。

    峰串按**强度降序**写, 与 XinMatch 侧 ``ORDER BY intensity DESC``
    对齐 —— 否则并列峰的次序差异会被误当成口径漂移。
    """
    conn = sqlite3.connect(path)
    conn.execute(_PHASES_DDL)
    for n, (eid, formula, _m, sg, _sys, a, b, c, al, be, ga, _els) in enumerate(_ENTRIES):
        pk = _PEAKS[eid]
        conn.execute(
            "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1000 + n, eid, eid, formula, sg, len(pk),
             ",".join(f"{d:.6f}" for d, _ in pk),
             ",".join(f"{i:.4f}" for _, i in pk),
             a, b, c, al, be, ga))
    conn.commit()
    conn.close()
    return path


#: 合成"测量谱"用的 d-I (取 XM-A 的全部峰, 强度含两位小数扰动以模拟实测)
_MEAS_D = [d for d, _ in _PEAKS["XM-A"]]
_MEAS_I = [i * 1.03 for _, i in _PEAKS["XM-A"]]


@pytest.fixture
def xm_db(tmp_path, monkeypatch):
    """XinMatch 库 + 隔离的索引缓存目录。

    ``Path.home`` 被指到 tmp_path: 索引缓存落在 ``~/.polyxrd/cache``,
    不能让单测往真实用户目录里写 20 MB 文件。
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return _make_xinmatch_db(tmp_path / "xm" / "cod_inorganics.db")


@pytest.fixture
def phases_db(tmp_path):
    return _make_phases_db(tmp_path / "polyxrd_phases.sqlite")


# ── 1. 探测与判别 ────────────────────────────────────────────

class TestProbe:
    def test_accepts_valid_xinmatch_db(self, xm_db):
        ok, reason = probe(xm_db)
        assert ok is True
        assert reason == ""

    def test_rejects_missing_file(self, tmp_path):
        ok, reason = probe(tmp_path / "nope.db")
        assert ok is False
        assert reason == "file_not_found"

    def test_rejects_non_sqlite(self, tmp_path):
        p = tmp_path / "fake.db"
        p.write_bytes(b"not a database at all")
        ok, reason = probe(p)
        assert ok is False
        assert reason == "not_sqlite"

    def test_rejects_sqlite_without_tables(self, tmp_path):
        p = tmp_path / "other.sqlite"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE whatever (a INTEGER)")
        conn.commit()
        conn.close()
        ok, reason = probe(p)
        assert ok is False
        assert reason.startswith("missing_tables:")
        assert "entries" in reason

    def test_detects_xinmatch_kind_via_db_import(self, xm_db):
        """四表齐 → 落到 ``xinmatch`` 槽位, 而不是被判成 COD 无机物库。"""
        ins = db_import.inspect_db_file(xm_db)
        assert ins.ok is True
        assert ins.kind == "xinmatch"
        assert ins.rows == len(_ENTRIES)
        # 该格式没有预截断强峰列, 界面不该显示"检索更快"
        assert ins.has_top_peaks is False

    def test_not_confused_with_polyxrd_phases_db(self, phases_db):
        """反向: PolyXRD 自家的 phases 库不能被判成 XinMatch 库。"""
        ins = db_import.inspect_db_file(phases_db)
        assert ins.kind != "xinmatch"


# ── 2. 索引缓存 ─────────────────────────────────────────────

class TestIndexCache:
    def test_builds_index_and_writes_cache(self, xm_db):
        db = XinMatchDatabase(xm_db)
        assert db.is_ready()
        cands = db.search_by_d_peaks(_MEAS_D, _MEAS_I, limit=5)
        assert cands, "合成库上应当能检出候选"
        cache = _cache_file_for(xm_db)
        assert cache.exists(), "首次检索后应写出索引缓存"

    def test_second_instance_loads_cache(self, xm_db):
        first = XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=5)
        assert _cache_file_for(xm_db).exists()
        second = XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=5)
        assert [c["cod_id"] for c in first] == [c["cod_id"] for c in second]

    def test_cache_invalidated_when_source_changes(self, xm_db):
        XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=5)
        cache = _cache_file_for(xm_db)
        # 换库 (mtime 变) → 旧缓存必须失效, 而不是拿旧索引配新库
        conn = sqlite3.connect(xm_db)
        conn.execute("DELETE FROM entries WHERE entry_id='XM-C'")
        conn.commit()
        conn.close()
        db = XinMatchDatabase(xm_db)
        cands = db.search_by_d_peaks(_MEAS_D, _MEAS_I, limit=10)
        ids = {c["cod_id"] for c in cands}
        assert "XM-C" not in ids
        assert db.stats().entries == len(_ENTRIES) - 1

    def test_corrupt_cache_is_rebuilt(self, xm_db):
        XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=5)
        cache = _cache_file_for(xm_db)
        cache.write_bytes(b"garbage")
        # 缓存坏了不能让功能不可用 —— 重建即可
        cands = XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=5)
        assert cands

    def test_clear_index_cache(self, xm_db):
        XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=5)
        assert _cache_file_for(xm_db).exists()
        assert clear_index_cache(xm_db) == 1
        assert not _cache_file_for(xm_db).exists()


# ── 3. 打分口径一致性 (本文件的核心用例) ─────────────────────

class TestMetricParity:
    """同一批峰, 两个实现必须给出同一组 Hanawalt 度量。

    口径清单 (任何一项写错都会让这条用例变红):
      · 参考峰 = 强度降序前 ``max_ref_peaks`` 条
      · 反向命中 = 测量峰落入参考峰 ±tol 窗口, 按**最左命中点**去重计数
      · ``n_top = min(n_i, max(n_meas+2, 8), 12)``
      · 去重按 ``_dedupe_by_tol`` 的贪心顺序, 容差取**候选 d 自身**
      · ``top_precision`` 只看去重后前 5 条
      · ``main_peak_match`` 允许放宽到样品前 ``main_peak_topk`` 个最强峰
    """

    @staticmethod
    def _cod_results(phases_db: Path, measured_i=_MEAS_I, **kw) -> dict[str, dict]:
        from polyxrd.services.cif_database import CIFDatabase

        conn = sqlite3.connect(f"file:{phases_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = CIFDatabase(enable_cod_local=False).search_cod_by_d_peaks(
                _MEAS_D, measured_i, conn=conn, limit=50, **kw)
        finally:
            conn.close()
        return {r["ref_id"]: r for r in rows}

    def test_metrics_match_cod_implementation(self, xm_db, phases_db):
        kw = dict(tolerance=0.02, min_match=1, max_ref_peaks=8, main_peak_topk=3)
        cod = self._cod_results(phases_db, **kw)
        xm = {c["cod_id"]: c for c in
              XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=50, **kw)}
        assert set(cod) == set(xm), "两个实现筛出的候选集合必须一致"
        numeric = ("n_ref_used", "n_matched_ref", "n_matched_meas",
                   "n_meas_in_top", "n_top_unique", "n_top_observed",
                   "n_top_k", "top_recall", "top_precision",
                   "intensity_weighted_top_recall", "main_peak_match",
                   "match_ratio", "meas_ratio", "score")
        for eid, c in cod.items():
            for key in numeric:
                assert c[key] == pytest.approx(xm[eid][key], abs=1e-12), (
                    f"{eid}.{key}: COD={c[key]!r} XinMatch={xm[eid][key]!r}")

    def test_ranking_order_matches_cod_implementation(self, xm_db, phases_db):
        kw = dict(tolerance=0.02, min_match=1, max_ref_peaks=8, main_peak_topk=3)
        cod = list(self._cod_results(phases_db, **kw))
        xm = [c["cod_id"] for c in
              XinMatchDatabase(xm_db).search_by_d_peaks(_MEAS_D, _MEAS_I, limit=50, **kw)]
        assert xm == cod

    def test_without_intensities_both_degrade_alike(self, xm_db, phases_db):
        kw = dict(tolerance=0.02, min_match=1, max_ref_peaks=8)
        cod = self._cod_results(phases_db, measured_i=None, **kw)
        xm = {c["cod_id"]: c for c in XinMatchDatabase(xm_db).search_by_d_peaks(
            _MEAS_D, None, limit=50, **kw)}
        assert set(cod) == set(xm)
        for eid, c in cod.items():
            assert c["main_peak_match"] == xm[eid]["main_peak_match"]
            assert c["top_precision"] == pytest.approx(xm[eid]["top_precision"])
            assert c["intensity_weighted_top_recall"] == (
                pytest.approx(xm[eid]["intensity_weighted_top_recall"]))


class TestSearchBehaviour:
    def test_true_phase_ranks_first(self, xm_db):
        cands = XinMatchDatabase(xm_db).search_by_d_peaks(
            _MEAS_D, _MEAS_I, tolerance=0.02, min_match=3,
            limit=10, max_ref_peaks=8, main_peak_topk=3)
        assert cands[0]["cod_id"] == "XM-A"

    def test_min_match_filters_sparse_candidates(self, xm_db):
        """只给 XM-A 的 3 条峰且要求至少命中 3 → 峰位对不上的相被剪掉。"""
        db = XinMatchDatabase(xm_db)
        strict = db.search_by_d_peaks(_MEAS_D[:3], None, min_match=3, limit=10)
        assert all(c["n_matched_meas"] >= 3 for c in strict)

    def test_elements_allowed_filters_scan_layer(self, xm_db):
        db = XinMatchDatabase(xm_db)
        cands = db.search_by_d_peaks(_MEAS_D, _MEAS_I, min_match=2, limit=20,
                                     elements_allowed={"Zn", "O"})
        assert {c["cod_id"] for c in cands} == {"XM-A"}

    def test_missing_db_returns_empty(self, tmp_path):
        db = XinMatchDatabase(tmp_path / "gone.db")
        assert db.is_ready() is False
        assert db.search_by_d_peaks(_MEAS_D, _MEAS_I) == []

    def test_get_phase_carries_cell_and_elements(self, xm_db):
        db = XinMatchDatabase(xm_db)
        detail = db.get_phase("XM-A")
        assert detail is not None
        assert detail["formula"] == "O Zn"
        assert detail["mineral_name"] == "Zincite"
        assert detail["space_group"] == "P 63 m c"
        assert detail["cell_a"] == pytest.approx(3.2495)
        assert detail["cell_gamma"] == pytest.approx(120.0)
        assert detail["elements_list"] == ["O", "Zn"]
        assert len(detail["peaks_d_list"]) == len(_PEAKS["XM-A"])
        # 峰按强度降序返回 (FOM/前截断都依赖这个次序)
        assert detail["peaks_i_list"] == sorted(detail["peaks_i_list"], reverse=True)

    def test_get_phase_unknown_id(self, xm_db):
        assert XinMatchDatabase(xm_db).get_phase("nope") is None

    def test_stats_counts(self, xm_db):
        st = XinMatchDatabase(xm_db).stats()
        assert st.entries == len(_ENTRIES)
        assert st.peaks == sum(len(v) for v in _PEAKS.values())
        assert st.elements == sum(len(e[11].split(",")) for e in _ENTRIES)


# ── 4. 任意位置挂载 ─────────────────────────────────────────

@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把全局配置写的 user_db_paths.json 重定向到 tmp_path。"""
    cfg = get_config()
    monkeypatch.setattr(cfg, "_user_db_paths_file",
                        lambda: tmp_path / "user_db_paths.json")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return cfg


class TestMountAnyPath:
    def test_mount_db_from_unrelated_folder(self, isolated_config, tmp_path):
        """需求原话: 文件放在其他文件夹中, 指定路径就能挂上。"""
        nested = tmp_path / "somewhere" / "else" / "cod_inorganics.db"
        nested.parent.mkdir(parents=True)
        _make_xinmatch_db(nested)

        mounted = db_import.mount_databases(nested)

        assert [m.kind for m in mounted] == ["xinmatch"]
        assert isolated_config.get_xinmatch_db_path() == nested.resolve()
        # 持久化到 user_db_paths.json, 下次启动自动加载
        raw = json.loads((tmp_path / "user_db_paths.json").read_text("utf-8"))
        assert raw["xinmatch_db_path"] == str(nested.resolve())

    def test_mount_folder_with_several_kinds(self, isolated_config, tmp_path):
        """一个目录里放多套库 (常见布局) → 一次全挂上, 不必逐个点。"""
        folder = tmp_path / "data"
        folder.mkdir()
        _make_xinmatch_db(folder / "cod_inorganics.db")
        _make_polyxrd_cod(folder / "COD_inorganics_index.sqlite")

        mounted = db_import.mount_databases(folder)

        kinds = {m.kind for m in mounted}
        assert kinds == {"xinmatch", "cod_inorganics"}
        assert isolated_config.get_xinmatch_db_path() is not None
        assert isolated_config.user_db_path("cod_db_path") is not None

    def test_folder_scan_ignores_backup_files(self, isolated_config, tmp_path):
        """``x.db.bak-20261011`` 这类备份不该被当成候选 (XinMatch 数据目录常见)。"""
        folder = tmp_path / "data"
        folder.mkdir()
        _make_xinmatch_db(folder / "cod_inorganics.db")
        # 两种备份命名都要挡住: 后缀式 (.db.bak-...) 与中缀式 (.bak-....db)
        (folder / "cod_inorganics.db.bak-20261011").write_bytes(b"junk")
        _make_xinmatch_db(folder / "cod_inorganics.bak-20261012.db")

        found = db_import.discover_databases(folder)
        assert [f.path.name for f in found] == ["cod_inorganics.db"]

    def test_folder_scan_prefers_declared_filename(self, isolated_config, tmp_path):
        """同类库多份时按声明的文件名优先序挑, 而不是按体积/字典序撞运气。"""
        folder = tmp_path / "data"
        folder.mkdir()
        # cod_full 更大, 但 cod_inorganics.db 在 preferred_names 里更靠前
        _make_xinmatch_db(folder / "cod_inorganics.db")
        _make_xinmatch_db(folder / "cod_full.db")

        mounted = db_import.mount_databases(folder)

        assert len(mounted) == 1, "同一类库只挂一份"
        assert mounted[0].path.name == "cod_inorganics.db"

    def test_mount_raises_with_reason_for_junk(self, isolated_config, tmp_path):
        junk = tmp_path / "junk.sqlite"
        junk.write_bytes(b"not sqlite")
        with pytest.raises(ValueError) as ei:
            db_import.mount_databases(junk)
        assert "不是可用的数据库文件" in str(ei.value)

    def test_mount_raises_for_empty_folder(self, isolated_config, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError) as ei:
            db_import.mount_databases(empty)
        assert "没有 .sqlite" in str(ei.value)

    def test_missing_path_message(self, isolated_config, tmp_path):
        with pytest.raises(ValueError) as ei:
            db_import.mount_databases(tmp_path / "nowhere.db")
        assert "路径不存在" in str(ei.value)

    def test_unmounted_by_default(self, isolated_config):
        assert isolated_config.get_xinmatch_db_path() is None
        states = {s["kind"]: s for s in db_import.slot_states(validate=False)}
        assert states["xinmatch"]["path"] == ""
        assert states["xinmatch"]["exists"] is False

    def test_state_reports_mounted_rows(self, isolated_config, tmp_path):
        _make_xinmatch_db(tmp_path / "a.db")
        db_import.mount_databases(tmp_path / "a.db")
        states = {s["kind"]: s for s in db_import.slot_states()}
        assert states["xinmatch"]["ok"] is True
        assert states["xinmatch"]["rows"] == len(_ENTRIES)
        assert states["xinmatch"]["imported"] is True


def _make_polyxrd_cod(path: Path) -> Path:
    """最小合法 COD 无机物库 (与 test_db_import 里的构造同形)。"""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE phases (cod_id TEXT PRIMARY KEY, formula TEXT,"
        " space_group TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT,"
        " cell_a REAL, cell_b REAL, cell_c REAL, cell_alpha REAL,"
        " cell_beta REAL, cell_gamma REAL)")
    conn.execute("INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("9001", "SiO2", "P3_121", 2, "3.34,4.26", "100,45",
                  4.913, 4.913, 5.405, 90.0, 90.0, 120.0))
    conn.commit()
    conn.close()
    return path


# ── 5. 检索链接入 (identify_with_xinmatch) ───────────────────

def _pattern_from(peaks: list[tuple[float, float]], wavelength: float = 1.5406):
    """把 d-I 表合成一条 Gauss 峰谱 (2θ 5~80°)。"""
    from polyxrd.models.xrd_data import XRDData

    tt = np.arange(5.0, 80.0, 0.02)
    y = np.full_like(tt, 5.0)
    for d, inten in peaks:
        s = wavelength / (2.0 * d)
        if s > 1.0:
            continue
        pos = 2.0 * np.degrees(np.arcsin(s))
        if not (5.0 <= pos <= 80.0):
            continue
        # FWHM ~0.1° 的 Gauss, 峰高按强度缩放
        y += inten / 1000.0 * 400.0 * np.exp(-4.0 * np.log(2.0) * ((tt - pos) / 0.1) ** 2)
    return XRDData(two_theta=tt, intensity=y, wavelength=wavelength)


class TestIdentifyWithXinMatch:
    def test_identifies_phase_from_mounted_db(self, xm_db, isolated_config):
        from polyxrd.services.phase_identifier import PhaseIdentifier, default_peak_list

        data = _pattern_from(_PEAKS["XM-A"])
        peaks = default_peak_list(data)
        assert len(peaks.peaks) >= 4

        results = PhaseIdentifier().identify_with_xinmatch(
            data, peaks=peaks, top_n=5, tolerance=0.2,
            db=XinMatchDatabase(xm_db))

        assert results, "应当至少检出一个候选"
        assert "XM-A" in results[0].phase.name
        # Phase 要带上可回溯的库内编号 (字符串 ID) 与晶胞
        assert results[0].phase.db_id == "XM-A"
        assert results[0].phase.lattice is not None

    def test_returns_empty_without_db(self, isolated_config, tmp_path):
        from polyxrd.services.phase_identifier import PhaseIdentifier

        data = _pattern_from(_PEAKS["XM-A"])
        assert PhaseIdentifier().identify_with_xinmatch(
            data, db=XinMatchDatabase(tmp_path / "gone.db")) == []


# ── 6. 配置往返 ─────────────────────────────────────────────

class TestConfigSlot:
    def test_set_get_roundtrip(self, tmp_path, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setattr(cfg, "_user_db_paths_file",
                            lambda: tmp_path / "p.json")
        db = tmp_path / "lib.db"
        db.write_bytes(b"x")
        cfg.set_xinmatch_db_path(db)
        assert cfg.get_xinmatch_db_path() == db.resolve()

    def test_clearing_returns_none(self, tmp_path, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setattr(cfg, "_user_db_paths_file",
                            lambda: tmp_path / "p.json")
        db = tmp_path / "lib.db"
        db.write_bytes(b"x")
        cfg.set_xinmatch_db_path(db)
        cfg.set_xinmatch_db_path(None)
        assert cfg.get_xinmatch_db_path() is None

    def test_moved_away_file_returns_none(self, tmp_path, monkeypatch):
        """用户把库挪走后不该抱死路径 —— 检索入口据此优雅退出。"""
        cfg = AppConfig()
        monkeypatch.setattr(cfg, "_user_db_paths_file",
                            lambda: tmp_path / "p.json")
        db = tmp_path / "lib.db"
        db.write_bytes(b"x")
        cfg.set_xinmatch_db_path(db)
        db.unlink()
        assert cfg.get_xinmatch_db_path() is None
