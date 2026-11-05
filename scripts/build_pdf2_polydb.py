#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ICDD PDF-2 2004 → polyDB v1 建库器
=====================================

把 ``C:\\pdf2\\pdf2.dat``（80 字符定宽流，163,834 张卡片）重打包成 PolyXRD
现行外挂库格式 ``<name>.polyDB``，与 COD / PCOD / TCOD / MP 使用**同一套
reader 与同一套打分**。

与 CIF 家族的根本差别
---------------------
CIF 库是「结构 → 算峰」，本库是「读 ICDD 实测峰表 → 落盘」，中间不做任何
峰计算，并在 ``meta.peak_convention`` 里如实写 ``peak_origin: observed``。
晶胞/空间群/化合物名按 PDF2 原样落库；**密度与 Z 不写**（同一卡片内 Z 与
Dx 可互相矛盾，见 ``docs/PDF2-2004重建验收报告-20261028.md``）。

关键口径
--------
* ``k = 100``：按**强度降序**取前 100 条峰（规范 §2）。PDF2 单卡最多 199 条，
  35,945 张（21.9%）卡片会被截掉弱峰；打分层只取最强 40 条
  （``max_ref_peaks``），截断的都在这 40 条之外，因此**候选与排序不受影响**，
  只是展示时弱峰少了（``build.truncated_to_k`` 如实计数，不静默丢弃）。
* 强度按**每相自身最大值**归一到 1000 再量化（``u16 = round(I/1000*65535)``），
  与计算库挡同一把尺子，否则跨库打分不可比。
* ``bins.u8`` 只索引每相最强 40 条（``bins_top_m``），满足「位图候选 ⊇ 精确
  结果」的必要条件。
* PDF2 没有原子坐标 → ``sites.bin`` 为空、``sites_off.i64`` 全 0；
  ``probe()`` 仍判定可用，``get_atomic_sites()`` 返回空列表（与旧库能力一致）。
* ``index.sqlite.entries`` 在规范列之外附带 ``name`` / ``pearson`` /
  ``sg_setting`` / ``red_*`` 四个 **PDF2 专有可选列**。规范允许新增可选列且
  reader 必须容忍缺失；``polydb.get_phase`` 用 ``PRAGMA table_info`` 探测，
  老库无这些列时照常工作。

用法::

    python scripts/build_pdf2_polydb.py                       # 全量，默认输出
    python scripts/build_pdf2_polydb.py --limit 5000 --out D:/tmp/PDF2-slice.polyDB
    python scripts/build_pdf2_polydb.py -v

产物默认落在 ``cod_data/PDF2-2004.polyDB``（该目录已被 .gitignore 屏蔽）。
**ICDD 版权库：永不入库、永不上传 GitHub / Release。**
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.services.pdf2_scan import PDF2Record, iter_pdf2_records  # noqa: E402
from polyxrd.services.polydb import ELEMENTS, Z_OF  # noqa: E402

DEFAULT_RAW = Path(r"C:\pdf2\pdf2.dat")
DEFAULT_OUT = ROOT / "cod_data" / "PDF2-2004.polyDB"

FORMAT_NAME = "polyDB"
SCHEMA_VERSION = 1
VARIANT = "pdf2-2004"
K = 100
BINS_TOP_M = 40
BIN_WIDTH = 0.05
N_BINS = 501
SITE_BYTES = 17


# ────────────────────────── 小工具 ──────────────────────────
def _sha256(path: Path, chunk: int = 4 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _set_bits(bits: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> None:
    if rows.size == 0:
        return
    byte_idx = cols >> 3
    values = (np.uint8(1) << (cols & 7).astype(np.uint8)).astype(np.uint8)
    np.bitwise_or.at(bits, (rows, byte_idx), values)


def elements_of_formula(formula: str) -> list[str]:
    """PDF2 化学式 → 元素符号列表（按 Z 升序、去重）。

    PDF2 的式子是空格分隔的「元素+计数」token（``C10 H7 Bi O2``），所以只看
    每个 token 的字母前缀就够，不会把 ``Co`` 拆成 ``C``+``o``。
    """
    import re

    pat = re.compile(r"^([A-Z][a-z]?)")
    found: list[str] = []
    for tok in (formula or "").split():
        m = pat.match(tok)
        if m and m.group(1) in Z_OF:
            found.append(m.group(1))
    return sorted(set(found), key=lambda s: Z_OF[s])


def _lattice_volume(a, b, c, al, be, ga) -> float | None:
    """六参数 → 体积（度为单位的角度）。参数缺失/非法返回 None。"""
    if not all(v and v > 0 for v in (a, b, c)):
        return None
    ca = np.cos(np.radians(al or 90.0))
    cb = np.cos(np.radians(be or 90.0))
    cg = np.cos(np.radians(ga or 90.0))
    val = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
    if val <= 0:
        return None
    return float(a * b * c * np.sqrt(val))


# ────────────────────────── 采集 ──────────────────────────
def collect(raw_path: Path, limit: int | None, verbose: bool,
            progress=print) -> tuple[list[dict], dict]:
    """第一遍：读全部记录的非峰字段（不含 d-I，控制内存）。

    Returns:
        ``(rows, stats)``；``stats["vol_mismatch"]`` 是**解析布局的哨兵**：
        类型 3 的报告体积与类型 E 六参数自算体积差 >2% 的条数。列位一旦读错
        （例如把类型 3 按 67 列截断），这个数会从 ~986 跳到几万。
    """
    rows: list[dict] = []
    n_total = n_skip = vol_mismatch = 0
    t0 = time.time()
    for rec in iter_pdf2_records(raw_path):
        n_total += 1
        if rec.n_peaks <= 0:
            n_skip += 1
            continue
        formula = rec.formula_norm or rec.formula
        els = elements_of_formula(formula)
        vol = _lattice_volume(rec.cell_a, rec.cell_b, rec.cell_c,
                              rec.cell_alpha, rec.cell_beta, rec.cell_gamma)
        if vol and rec.cell_vol and abs(rec.cell_vol - vol) / vol > 0.02:
            vol_mismatch += 1
        rows.append({
            "eid": int(rec.pdf2_id),
            "formula": formula,
            "formula_red": rec.formula_norm or formula,
            "name": rec.name,
            "mineral": rec.mineral,
            "space_group": rec.space_group,
            "sg_number": int(rec.space_group_num or 0),
            "sg_setting": rec.space_group_setting,
            "elements": ",".join(els),
            "a": rec.cell_a, "b": rec.cell_b, "c": rec.cell_c,
            "alpha": rec.cell_alpha, "beta": rec.cell_beta,
            "gamma": rec.cell_gamma, "volume": vol,
            "pearson": rec.pearson,
            "red_a": rec.red_a, "red_b": rec.red_b, "red_c": rec.red_c,
            "red_alpha": rec.red_alpha, "red_beta": rec.red_beta,
            "red_gamma": rec.red_gamma, "red_vol": rec.red_vol,
            "n_peaks": int(rec.n_peaks),
            "record_offset": int(rec.record_offset),
        })
        if verbose and n_total % 20000 == 0:
            progress("  scan %d ... (ok=%d)" % (n_total, len(rows)))
        if limit is not None and len(rows) >= limit:
            break
    progress("scan done: %d records, %d ok, %d skipped, vol_mismatch=%d (%.1fs)"
             % (n_total, len(rows), n_skip, vol_mismatch, time.time() - t0))
    return rows, {"total": n_total, "skipped": n_skip,
                  "vol_mismatch": vol_mismatch}


# ────────────────────────── 写段 ──────────────────────────
def write_arrays(raw_path: Path, rows: list[dict], out_dir: Path,
                 k: int, progress=print) -> tuple[int, int]:
    """第二遍：按第一遍的 eid 顺序填 (N,K) 峰矩阵并写盘。

    Returns:
        ``(n_peaks_total, n_truncated)``
    """
    n = len(rows)
    d = np.zeros((n, k), dtype=np.float32)
    iq = np.zeros((n, k), dtype=np.uint16)
    want = {r["eid"]: idx for idx, r in enumerate(rows)}
    seen: set[int] = set()
    n_peaks_total = n_truncated = 0

    for rec in iter_pdf2_records(raw_path):
        idx = want.get(int(rec.pdf2_id))
        if idx is None or idx in seen:
            continue
        seen.add(idx)
        pairs = list(zip(rec.peaks_d, rec.peaks_i))
        if not pairs:
            continue
        # 稳定排序：强度降序；同强度保持 ICDD 原始顺序（规范 §4.1）
        pairs.sort(key=lambda p: -p[1])
        n_peaks_total += len(pairs)
        if len(pairs) > k:
            n_truncated += 1
        pairs = pairs[:k]
        dmax = max(p[1] for p in pairs) or 0.0
        for j, (dv, iv) in enumerate(pairs):
            d[idx, j] = dv
            # 每相归一到 1000 → u16；dmax=0 时全 0，不制造假强度
            norm = (iv / dmax * 1000.0) if dmax > 0 else 0.0
            iq[idx, j] = int(round(min(max(norm, 0.0), 1000.0) / 1000.0 * 65535))
        if len(seen) == n:
            break

    d.tofile(out_dir / "peaks_d.f32")
    iq.tofile(out_dir / "peaks_i.u16")
    # PDF2 无原子坐标：空侧车 + 全 0 偏移（仍满足 reader 的必需段）
    (out_dir / "sites.bin").write_bytes(b"")
    np.zeros(n + 1, dtype="<i8").tofile(out_dir / "sites_off.i64")
    progress("arrays written: %d×%d, peaks=%d, truncated=%d"
             % (n, k, n_peaks_total, n_truncated))
    return n_peaks_total, n_truncated


def build_bins(d: np.ndarray, top_m: int) -> np.ndarray:
    n, k = d.shape
    m = min(int(top_m), k)
    bins = np.zeros((N_BINS, (n + 7) // 8), dtype=np.uint8)
    phase = np.repeat(np.arange(n, dtype=np.int64), m)
    flat = np.asarray(d[:, :m]).reshape(-1)
    valid = flat > 0
    phase = phase[valid]
    dv = flat[valid].astype(np.float64)
    bin_idx = np.clip(np.floor(dv / BIN_WIDTH).astype(np.int64), 0, N_BINS - 1)
    _set_bits(bins, bin_idx, phase)
    return bins


def build_elem(elements_list: list[str]) -> tuple[np.ndarray, dict[int, int]]:
    n = len(elements_list)
    arr = np.zeros((118, (n + 7) // 8), dtype=np.uint8)
    rows_idx: list[int] = []
    cols_idx: list[int] = []
    z_counts: dict[int, int] = {}
    for i, els in enumerate(elements_list):
        for s in (els or "").split(","):
            z = Z_OF.get(s.strip())
            if not z:
                continue
            rows_idx.append(z - 1)
            cols_idx.append(i)
            z_counts[z] = z_counts.get(z, 0) + 1
    _set_bits(arr, np.asarray(rows_idx, dtype=np.int64),
              np.asarray(cols_idx, dtype=np.int64))
    return arr, z_counts


def write_index(rows: list[dict], out_dir: Path, progress=print) -> None:
    """entries 表：规范列 + 4 个 PDF2 专有可选列 + row_idx 唯一索引。"""
    db = out_dir / "index.sqlite"
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        -- 沙箱/受限环境下 SQLite 的临时文件目录可能打不开（Windows 上
        -- 报 "unable to open database file"）。163 k 行建索引放内存足够。
        PRAGMA temp_store=MEMORY;
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE entries (
            eid INTEGER PRIMARY KEY, formula TEXT, formula_red TEXT, mineral TEXT,
            space_group TEXT, sg_number INTEGER, elements TEXT,
            a REAL, b REAL, c REAL, alpha REAL, beta REAL, gamma REAL,
            volume REAL, density REAL, z INTEGER, n_peaks INTEGER,
            tier INTEGER DEFAULT 0, dup_group INTEGER DEFAULT 0,
            cif_rel TEXT, src_mtime INTEGER,
            row_idx INTEGER,
            name TEXT, pearson TEXT, sg_setting TEXT,
            red_a REAL, red_b REAL, red_c REAL,
            red_alpha REAL, red_beta REAL, red_gamma REAL, red_vol REAL
        );
        CREATE VIRTUAL TABLE entries_fts USING fts5(
            formula, mineral, content='entries', content_rowid='eid'
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    # 22 规范列 + 10 PDF2 可选列 = 32
    sql = ("INSERT OR REPLACE INTO entries VALUES ("
           + ",".join("?" * 32) + ")")
    batch: list[tuple] = []
    for idx, r in enumerate(rows):
        batch.append((
            r["eid"], r["formula"], r["formula_red"], r["mineral"],
            r["space_group"], r["sg_number"], r["elements"],
            r["a"], r["b"], r["c"], r["alpha"], r["beta"], r["gamma"],
            r["volume"], None, None, r["n_peaks"],   # density / z 有意留空
            0, 0, "", 0, idx,
            r["name"], r["pearson"], r["sg_setting"],
            r["red_a"], r["red_b"], r["red_c"],
            r["red_alpha"], r["red_beta"], r["red_gamma"], r["red_vol"],
        ))
        if len(batch) >= 20000:
            conn.executemany(sql, batch)
            batch.clear()
            progress("  entries %d/%d" % (idx + 1, len(rows)))
    if batch:
        conn.executemany(sql, batch)
    conn.commit()
    conn.executescript("""
        PRAGMA temp_store=MEMORY;
        CREATE INDEX idx_entries_formula ON entries(formula);
        CREATE INDEX idx_entries_mineral ON entries(mineral);
        CREATE INDEX idx_entries_name ON entries(name);
        CREATE INDEX idx_entries_dup ON entries(dup_group);
        CREATE UNIQUE INDEX idx_entries_row ON entries(row_idx);
        INSERT INTO entries_fts(rowid, formula, mineral)
            SELECT eid, formula, mineral FROM entries;
    """)
    conn.commit()
    conn.close()


# ────────────────────────── 主流程 ──────────────────────────
def build(raw_path: Path, out_dir: Path, k: int = K,
          top_m: int = BINS_TOP_M, limit: int | None = None,
          verbose: bool = False, progress=print) -> dict:
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    progress("PDF2 → polyDB: %s → %s (k=%d, bins_top_m=%d)"
             % (raw_path, out_dir, k, top_m))

    rows, scan_stats = collect(raw_path, limit, verbose, progress=progress)
    if not rows:
        raise RuntimeError("没有解析出任何有效卡片")
    n_peaks_total, n_trunc = write_arrays(raw_path, rows, out_dir, k,
                                          progress=progress)

    d = np.memmap(out_dir / "peaks_d.f32", dtype=np.float32, mode="r",
                  shape=(len(rows), k))
    bins = build_bins(np.asarray(d), top_m)
    del d
    bins.tofile(out_dir / "bins.u8")

    write_index(rows, out_dir, progress=progress)

    n = len(rows)
    elem_bits, z_counts = build_elem([r["elements"] for r in rows])
    elem_bits.tofile(out_dir / "elem.u8")

    with_cell = sum(1 for r in rows if r["volume"])
    with_sg = sum(1 for r in rows if r["sg_number"] > 0)
    with_name = sum(1 for r in rows if r["name"])

    shapes = {
        "peaks_d.f32": ("float32", [n, k]),
        "peaks_i.u16": ("uint16", [n, k]),
        "bins.u8": ("uint8", [N_BINS, (n + 7) // 8]),
        "elem.u8": ("uint8", [118, (n + 7) // 8]),
        "sites_off.i64": ("int64", [n + 1]),
    }
    sections: dict = {}
    for name, (dtype, shape) in shapes.items():
        p = out_dir / name
        sections[name] = {"dtype": dtype, "shape": shape,
                          "bytes": p.stat().st_size, "sha256": _sha256(p)}
    for name in ("sites.bin", "index.sqlite"):
        p = out_dir / name
        sections[name] = {"bytes": p.stat().st_size, "sha256": _sha256(p)}

    meta = {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "variant": VARIANT,
        "dataset": "PDF2-2004",
        "peak_convention": {
            "wavelength": 1.5406,
            "tth_min": 5.0,
            "tth_max": None,          # 实测峰表，无统一截断角
            "d_min": 0.0,
            "merge": "as-observed",
            "intensity_scale": 1000.0,
            "peak_select": "intensity_top",
            "k": int(k),
            "quant_i": "u16/65535*1000",
            "bins_top_m": int(top_m),
            # ── 本库独有：峰是实测值，不是结构算出来的 ──
            "peak_origin": "observed",
            "source_norm": "per-phase-maxima->1000",
        },
        "counts": {"phases": n, "k": int(k), "peaks": int(n_peaks_total),
                   "sites": 0},
        "sections": sections,
        "total_bytes": sum(v["bytes"] for v in sections.values()),
        "source": {
            "lib": "ICDD PDF-2 2004",
            "root": str(raw_path),
            "raw_bytes": int(raw_path.stat().st_size),
            "raw_sha256": _sha256(raw_path),
            "copyright": "ICDD commercial database; local use only, never ship.",
        },
        "build": {
            "tool": "build_pdf2_polydb.py",
            "tool_version": "1.0",
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
            "elapsed_s": round(time.time() - t0, 1),
            "truncated_to_k": int(n_trunc),
            "records_read": int(scan_stats["total"]),
            "skipped_no_peaks": int(scan_stats["skipped"]),
            "vol_mismatch": int(scan_stats["vol_mismatch"]),
            "with_cell": int(with_cell),
            "with_sg": int(with_sg),
            "with_name": int(with_name),
            "limit": int(limit) if limit else 0,
        },
        "element_phase_counts": {ELEMENTS[z - 1]: c
                                 for z, c in sorted(z_counts.items())},
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    progress("done: %d phases, %.1f MB, %.1fs"
             % (n, meta["total_bytes"] / 2**20, meta["build"]["elapsed_s"]))
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PDF2-2004 → polyDB 建库")
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--bins-top-m", type=int, default=BINS_TOP_M)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not args.raw.exists():
        print("原始文件不存在: %s" % args.raw, file=sys.stderr)
        return 2
    build(args.raw, args.out, k=args.k, top_m=args.bins_top_m,
          limit=args.limit, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
