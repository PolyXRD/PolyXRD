"""polyDB 只读读取器单测（v4.0.0）
================================

polyDB 是 PolyXRD 自有的外挂物相库格式（``docs/外挂库格式规范-polyDB-v4.md``）：
目录容器 + 列存二进制 + d 分箱位图倒排。这里用**现场构造的迷你库**钉住
reader 的对外契约，不依赖本机安装的 77,500 相实测库（CI 上也能跑）：

1. :func:`probe` 的结构校验（缺段 / 字节数不符 / schema 版本）；
2. :meth:`PolyDatabase.search_by_d_peaks` 的候选剪枝**必须与全量暴力打分
   逐条一致**（这条是 2026-10 的真实回归：旧近似上界在真实库上会低估，
   5-1 试样 top-100 丢 3 个物相）；
3. :meth:`PolyDatabase._bound_keys` 的前三键必须与 :func:`_hanawalt_metric`
   完全相等（旧实现按"最近测量峰 + 列命中数"近似，遇到两个测量峰落进同一
   参考峰容差窗就会算错）；
4. 元数据 / 原子位点 / 元素位图过滤的取数正确性。
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

from polyxrd.services import polydb as P  # noqa: E402

K = 12
BINS = 501
TOKEN = b""


def _write_polydb(root: Path, phases: list[dict], k: int = K) -> Path:
    """按规范写一个最小可用 polyDB 目录。"""
    root.mkdir(parents=True, exist_ok=True)
    n = len(phases)
    nbytes = (n + 7) // 8
    d_arr = np.zeros((n, k), np.float32)
    i_arr = np.zeros((n, k), np.uint16)
    bins = np.zeros((BINS, nbytes), np.uint8)
    elem = np.zeros((118, nbytes), np.uint8)
    sites_bin = bytearray()
    sites_off = [0]
    for r, ph in enumerate(phases):
        peaks = sorted(ph["peaks"], key=lambda p: -p[1])[:k]
        for j, (d, inten) in enumerate(peaks):
            d_arr[r, j] = d
            i_arr[r, j] = int(round(max(0.0, min(1000.0, inten)) / 1000.0 * 65535))
        for d, _i in peaks:
            b = min(int(d / P._BIN_WIDTH), BINS - 1)
            bins[b, r >> 3] |= np.uint8(1 << (r & 7))
        for el in ph.get("elements", []):
            z = P.Z_OF.get(el)
            if z:
                elem[z - 1, r >> 3] |= np.uint8(1 << (r & 7))
        for (z, x, y, zz, occ) in ph.get("sites", []):
            sites_bin += bytes([z]) + np.asarray([x, y, zz, occ], dtype="<f4").tobytes()
        sites_off.append(len(sites_bin))

    (root / "peaks_d.f32").write_bytes(d_arr.tobytes())
    (root / "peaks_i.u16").write_bytes(i_arr.tobytes())
    (root / "bins.u8").write_bytes(bins.tobytes())
    (root / "elem.u8").write_bytes(elem.tobytes())
    (root / "sites.bin").write_bytes(bytes(sites_bin))
    (root / "sites_off.i64").write_bytes(
        np.asarray(sites_off, dtype="<i8").tobytes())

    conn = sqlite3.connect(str(root / "index.sqlite"))
    conn.execute(
        "CREATE TABLE entries ("
        " eid INTEGER PRIMARY KEY, formula TEXT, formula_red TEXT, mineral TEXT,"
        " space_group TEXT, sg_number INTEGER, elements TEXT,"
        " a REAL, b REAL, c REAL, alpha REAL, beta REAL, gamma REAL,"
        " volume REAL, density REAL, z INTEGER, n_peaks INTEGER,"
        " tier INTEGER DEFAULT 0, dup_group INTEGER DEFAULT 0,"
        " cif_rel TEXT, src_mtime INTEGER, row_idx INTEGER)")
    conn.execute("CREATE UNIQUE INDEX idx_entries_row ON entries(row_idx)")
    for r, ph in enumerate(phases):
        conn.execute(
            "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ph["eid"], ph.get("formula", "X"), ph.get("formula", "X"),
             ph.get("mineral", ""), ph.get("space_group", ""),
             ph.get("sg_number", 0), ",".join(ph.get("elements", [])),
             ph.get("a", 5.0), ph.get("b", 5.0), ph.get("c", 5.0),
             90.0, 90.0, 90.0, ph.get("volume", 125.0),
             ph.get("density", 1.0), ph.get("z", 1), len(ph["peaks"]),
             0, 0, "", 0, r))
    conn.commit()
    conn.close()

    sections = {
        "peaks_d.f32": {"dtype": "float32", "shape": [n, k]},
        "peaks_i.u16": {"dtype": "uint16", "shape": [n, k]},
        "bins.u8": {"dtype": "uint8", "shape": [BINS, nbytes]},
        "elem.u8": {"dtype": "uint8", "shape": [118, nbytes]},
        "sites_off.i64": {"dtype": "int64", "shape": [n + 1]},
    }
    for name, sec in sections.items():
        sec["bytes"] = (root / name).stat().st_size
    meta = {
        "format": "polyDB",
        "schema_version": 1,
        "variant": "synthetic",
        "peak_convention": {"wavelength": 1.5406, "d_min": 1.0, "k": k,
                            "bins_top_m": 40},
        "counts": {"phases": n, "k": k,
                   "peaks": int((d_arr > 0).sum()),
                   "sites": len(sites_off) and sum(
                       (o2 - o1) // 17 for o1, o2 in zip(sites_off, sites_off[1:]))},
        "sections": dict(sections, **{
            "sites.bin": {"dtype": "raw", "bytes": (root / "sites.bin").stat().st_size},
            "index.sqlite": {"bytes": (root / "index.sqlite").stat().st_size},
        }),
        "total_bytes": sum(f.stat().st_size for f in root.iterdir() if f.is_file()),
    }
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return root


def _phase(eid, peaks, elements=("Si", "O"), **kw):
    out = {"eid": eid, "peaks": peaks, "elements": list(elements),
           "formula": kw.pop("formula", "Si O2"), "mineral": "",
           "space_group": "P 1", "a": 5.0, "b": 5.0, "c": 5.0,
           "volume": 125.0, "density": 2.0, "z": 1}
    out.update(kw)
    return out


@pytest.fixture()
def small_db(tmp_path) -> Path:
    """12 相迷你库：1 个"真值相" + 11 个干扰相。"""
    truth = _phase(1000001, [(3.34, 1000), (4.26, 620), (1.82, 420),
                             (2.46, 380), (2.28, 300), (1.54, 220)],
                   formula="Si O2", mineral="Quartz")
    noise = []
    for j in range(11):
        peaks = [(2.0 + 0.37 * j + 0.05 * t, 500 - 20 * t) for t in range(6)]
        noise.append(_phase(2000000 + j, peaks, formula="Al2 O3"))
    return _write_polydb(tmp_path / "mini.polyDB", [truth] + noise)


def _brute_top_eids(db: P.PolyDatabase, md, mi, *, limit=6):
    """全量暴力打分（无剪枝）→ 前 limit 个 eid，键与 reader 完全一致。"""
    md = np.asarray(sorted(float(x) for x in md), dtype=np.float64)
    pairs = sorted(zip([float(x) for x in md], [float(v) for v in mi]),
                   key=lambda p: p[0])
    mi_s = np.asarray([p[1] for p in pairs], dtype=np.float64)
    main_topk = [float(md[j]) for j in np.argsort(-mi_s)[:3]]
    recs = []
    for r in range(db.stats().phases):
        d_all, i_all = db.peaks_of_rows(np.asarray([r]))
        m = d_all[0] > 0
        met = P._hanawalt_metric(
            d_all[0][m], i_all[0][m], md=md, mi=mi_s,
            main_meas_d_topk=main_topk, tol_abs=0.02, trel=0.0,
            use_rel=False, max_ref_peaks=40)
        if met is None or met["n_matched_meas"] < 3:
            continue
        recs.append(((met["main_peak_match"], met["top_precision"],
                      met["intensity_weighted_top_recall"], met["top_recall"],
                      met["meas_ratio"], met["score"], -r), r))
    recs.sort(reverse=True)
    return [db.eid_of_rows([r])[0] for _k, r in recs[:limit]]


class TestProbe:
    def test_probe_accepts_good_db(self, small_db):
        ok, reason = P.probe(small_db)
        assert ok and reason == ""

    def test_probe_rejects_missing_file(self, small_db):
        (small_db / "bins.u8").unlink()
        ok, reason = P.probe(small_db)
        assert not ok and reason == "missing:bins.u8"

    def test_probe_rejects_size_mismatch(self, small_db):
        (small_db / "peaks_d.f32").write_bytes(b"\x00" * 8)
        ok, reason = P.probe(small_db)
        assert not ok and reason.startswith("size_mismatch:")

    def test_probe_rejects_bad_schema(self, small_db):
        meta = json.loads((small_db / "meta.json").read_text(encoding="utf-8"))
        meta["schema_version"] = 99
        (small_db / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        ok, reason = P.probe(small_db)
        assert not ok and reason.startswith("unsupported_schema:")

    def test_probe_rejects_non_dir(self, tmp_path):
        f = tmp_path / "x.polyDB"
        f.write_bytes(b"x")
        ok, reason = P.probe(f)
        assert not ok and reason == "not_a_directory"


class TestReader:
    def test_stats(self, small_db):
        db = P.PolyDatabase(small_db)
        assert db.is_ready()
        st = db.stats()
        assert st.phases == 12 and st.k == K and st.bins == BINS
        assert st.variant == "synthetic"

    def test_search_matches_bruteforce(self, small_db):
        db = P.PolyDatabase(small_db)
        md = [3.34, 4.26, 1.82, 2.46]
        mi = [1000.0, 620.0, 420.0, 380.0]
        got = [r["cod_id"] for r in db.search_by_d_peaks(
            md, mi, tolerance=0.02, min_match=3, limit=6)]
        assert got == _brute_top_eids(db, md, mi, limit=6)
        assert got[0] == 1000001          # 真值相排第一

    def test_bound_keys_equal_exact_prefix(self, small_db):
        """前置键必须与精确打分前三键**逐项相等**（旧近似上界在这里会翻车）。"""
        db = P.PolyDatabase(small_db)
        # 两个测量峰只差 0.01 Å：会同时落进同一条参考峰的容差窗
        md = np.asarray([1.800, 1.810, 2.460, 2.470, 3.340], dtype=np.float64)
        mi = np.asarray([420.0, 410.0, 380.0, 375.0, 1000.0], dtype=np.float64)
        rows = np.arange(db.stats().phases)
        bounds = db._bound_keys(rows, md, mi, 0.02, 3)
        for r in rows:
            d_all, i_all = db.peaks_of_rows(np.asarray([r]))
            m = d_all[0] > 0
            met = P._hanawalt_metric(
                d_all[0][m], i_all[0][m], md=md, mi=mi,
                main_meas_d_topk=[3.34, 2.46, 1.80], tol_abs=0.02,
                trel=0.0, use_rel=False, max_ref_peaks=40)
            if met is None:
                continue
            assert bounds[r, 0] == pytest.approx(met["main_peak_match"])
            assert bounds[r, 1] == pytest.approx(met["top_precision"])
            assert bounds[r, 2] == pytest.approx(
                met["intensity_weighted_top_recall"], abs=1e-12)

    def test_get_phase_and_sites(self, tmp_path):
        ph = _phase(1000001, [(3.34, 1000), (4.26, 620)], formula="Si O2",
                    mineral="Quartz",
                    sites=[(14, 0.25, 0.25, 0.25, 1.0),
                           (8, 0.5, 0.5, 0.5, 0.75)])
        path = _write_polydb(tmp_path / "sites.polyDB", [ph])
        db = P.PolyDatabase(path)
        detail = db.get_phase(1000001)
        assert detail["formula"] == "Si O2"
        assert detail["mineral_name"] == "Quartz"
        assert detail["cod_id"] == 1000001
        assert len(detail["peaks_d_list"]) == 2
        sites = db.get_atomic_sites(1000001)
        assert [s["element"] for s in sites] == ["Si", "O"]
        assert sites[1]["occupancy"] == pytest.approx(0.75)
        assert db.get_atomic_sites(424242) == []
        assert db.get_phase(424242) is None
        assert db.eid_of_row(0) == 1000001

    def test_element_filter(self, tmp_path):
        a = _phase(1, [(3.0, 1000), (2.0, 500), (1.5, 300)], elements=["Si", "O"])
        b = _phase(2, [(3.0, 1000), (2.0, 500), (1.5, 300)], elements=["Fe", "O"])
        db = P.PolyDatabase(_write_polydb(tmp_path / "elem.polyDB", [a, b]))
        got = db.search_by_d_peaks([3.0, 2.0, 1.5], [1000.0, 500.0, 300.0],
                                   tolerance=0.02, min_match=3, limit=5,
                                   elements_allowed={"Si", "O"})
        assert [r["cod_id"] for r in got] == [1]

    def test_reload_and_close(self, small_db):
        db = P.PolyDatabase(small_db)
        assert db.search_by_d_peaks([3.34], [1000.0], min_match=1)
        db.reload()
        assert db.search_by_d_peaks([3.34], [1000.0], min_match=1)
        db.close()
        assert db._conn is None and db._arrays is None


class TestBoundSoundness:
    """剪枝安全性：随机库 + 随机查询下 search 前 N 与暴力前 N 必须逐条一致。"""

    def test_random_library_search_equals_bruteforce(self, tmp_path):
        rng = np.random.default_rng(7)
        phases = []
        for r in range(60):
            n_peak = int(rng.integers(3, 12))
            ds = np.sort(rng.uniform(1.0, 5.0, size=n_peak))[::-1]
            inten = np.sort(rng.uniform(100.0, 1000.0, size=n_peak))[::-1]
            phases.append(_phase(500000 + r, list(zip(ds.tolist(), inten.tolist()))))
        db = P.PolyDatabase(_write_polydb(tmp_path / "rand.polyDB", phases))
        for trial in range(5):
            md = np.sort(rng.uniform(1.0, 5.0, size=6)).tolist()
            mi = rng.uniform(100.0, 1000.0, size=6).tolist()
            got = [r["cod_id"] for r in db.search_by_d_peaks(
                md, mi, tolerance=0.02, min_match=3, limit=8)]
            assert got == _brute_top_eids(db, md, mi, limit=8)
