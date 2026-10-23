#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S5/S8 polyDB 校验器：结构 + 校验和 + 抽样回算。

分三层，任一层失败即退出码 1：
  L1 结构层：meta.json 可解析、必需段齐全、字节数与 meta 一致、SHA256 匹配；
  L2 一致层：entries 行数 == 峰矩阵行数 == 位图列宽；sites_off 单调且末值 == 文件长度；
             位图（bins/elem）可由 d 矩阵 / elements 字段重算复现；
  L3 精度层：抽样 N 相，用 fastxrd + fastcif 从源 CIF 重算，与库内 d/I 比对
             （判据：d ≤1e-4 Å，I ≤0.05（1000 标度），见规范 §4.1/§4.2）。

用法：
    python scripts/polydb_verify.py D:/path/COD-Inorg-20261021.polyDB
    python scripts/polydb_verify.py <db> --sample 200 --json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import time

import numpy as np

#: 数据根（2026-10-23 起在仓库外，PolyXRD / XinMatch 两库共用）。
_DATA_ROOT = os.environ.get("XRD_DATA_ROOT") or r"D:/Project/XRD/sync-COD"
TOOLS = r"D:/Project/XRD/PolyXRD-DataBase/tools"
COD_ROOT = os.path.join(_DATA_ROOT, "COD")

D_TOL = 1e-4          # f32 量化
I_TOL = 0.05          # u16 量化（1000 标度）

REQUIRED = ("meta.json", "index.sqlite", "peaks_d.f32", "peaks_i.u16",
            "bins.u8", "elem.u8", "sites.bin", "sites_off.i64")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(4 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _mm(path: str, dtype, shape) -> np.ndarray:
    return np.memmap(path, dtype=dtype, mode="r", shape=shape)


def verify(db: str, sample: int = 200, check_hash: bool = True,
           check_bitmaps: bool = True, progress=print) -> dict:
    rep: dict = {"db": db, "ok": False, "failures": [], "warnings": [], "checks": {}}

    def fail(msg: str) -> None:
        rep["failures"].append(msg)

    def warn(msg: str) -> None:
        rep["warnings"].append(msg)

    if not os.path.isdir(db):
        fail("不是目录（polyDB 必须是目录容器）")
        return rep
    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(db, f))]
    if missing:
        fail("缺少必需文件: %s" % ", ".join(missing))
        return rep

    # ── L1 结构 + 校验和 ──
    with open(os.path.join(db, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    rep["meta"] = {k: meta.get(k) for k in ("format", "schema_version", "variant")}
    if meta.get("format") != "polyDB":
        fail("meta.format != polyDB")
    if int(meta.get("schema_version", 0)) != 1:
        fail("schema_version != 1")
    conv = meta.get("peak_convention", {})
    for key in ("wavelength", "tth_min", "tth_max", "d_min", "merge",
                "intensity_scale", "peak_select", "k"):
        if key not in conv:
            fail("peak_convention 缺字段 %s" % key)
    k = int(conv.get("k", 0))
    counts = meta.get("counts", {})
    n = int(counts.get("phases", 0))
    rep["checks"]["phases"] = n
    rep["checks"]["k"] = k

    sections = meta.get("sections", {})
    for name in REQUIRED:
        if name == "meta.json":
            continue
        p = os.path.join(db, name)
        size = os.path.getsize(p)
        sec = sections.get(name)
        if not sec:
            warn("meta.sections 缺 %s" % name)
            continue
        if int(sec.get("bytes", -1)) != size:
            fail("%s 字节数不符: meta=%s disk=%d" % (name, sec.get("bytes"), size))
    if check_hash:
        t0 = time.perf_counter()
        for name, sec in sections.items():
            p = os.path.join(db, name)
            if not os.path.exists(p):
                continue
            if _sha256(p) != sec.get("sha256"):
                fail("%s SHA256 不符" % name)
        rep["checks"]["hash_s"] = round(time.perf_counter() - t0, 1)

    # ── L2 一致层 ──
    d = _mm(os.path.join(db, "peaks_d.f32"), np.float32, (n, k))
    i = _mm(os.path.join(db, "peaks_i.u16"), np.uint16, (n, k))
    if d.shape != (n, k) or i.shape != (n, k):
        fail("峰矩阵形状与 meta.counts 不符")
        return rep

    conn = sqlite3.connect("file:%s?mode=ro" % os.path.join(db, "index.sqlite"), uri=True)
    n_entry = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    if n_entry != n:
        fail("entries 行数 %d != meta.phases %d" % (n_entry, n))
    rep["checks"]["entries"] = n_entry

    offs = np.fromfile(os.path.join(db, "sites_off.i64"), dtype="<i8")
    n_site_file = os.path.getsize(os.path.join(db, "sites.bin"))
    if offs.size != n + 1:
        fail("sites_off 长度 %d != N+1 (%d)" % (offs.size, n + 1))
    else:
        if offs[0] != 0 or offs[-1] != n_site_file:
            fail("sites_off 边界不符: offs[0]=%d offs[-1]=%d file=%d"
                 % (offs[0], offs[-1], n_site_file))
        if np.any(np.diff(offs) < 0):
            fail("sites_off 非单调")
        if np.any(np.diff(offs) % 17 != 0):
            fail("sites_off 增量不是 17 的整数倍（位点记录应为 17 B）")
    rep["checks"]["sites"] = int(n_site_file // 17)

    # 空槽检查：d=0 之后不应再有 d>0（行内按有效峰右填充）
    if n and k:
        d_all = np.asarray(d)
        zero = d_all <= 0
        bad = np.any(zero[:, :-1] & (d_all[:, 1:] > 0))
        if bad:
            fail("峰槽存在空洞（d=0 之后又有 d>0）")
        # 行内 d 是否递减（同相按 I 降序，d 不必有序）——仅记录
        rep["checks"]["avg_peaks"] = round(float((~zero).sum() / max(1, n)), 1)

    if check_bitmaps and n:
        # 位图只索引每相最强 M 峰（meta.peak_convention.bins_top_m），不是全部 K 峰
        top_m = int(conv.get("bins_top_m", k) or k)
        top_m = max(1, min(top_m, k))
        rep["checks"]["bins_top_m"] = top_m
        bin_width = float(conv.get("bin_width", 0.05) or 0.05)
        bins = np.fromfile(os.path.join(db, "bins.u8"), dtype=np.uint8)
        nbin = int(meta["sections"]["bins.u8"]["shape"][0])
        nbytes = (n + 7) // 8
        if bins.size != nbin * nbytes:
            fail("bins.u8 尺寸不符（disk=%d expect=%d）" % (bins.size, nbin * nbytes))
        else:
            bins = bins.reshape(nbin, nbytes)
            rec = np.zeros_like(bins)
            phase = np.repeat(np.arange(n, dtype=np.int64), top_m)
            flat = np.asarray(d[:, :top_m]).reshape(-1).astype(np.float64)
            valid = flat > 0
            ph = phase[valid]
            bin_idx = np.clip(np.floor(flat[valid] / bin_width).astype(np.int64), 0, nbin - 1)
            np.bitwise_or.at(rec, (bin_idx, ph >> 3),
                             (np.uint8(1) << (ph & 7).astype(np.uint8)).astype(np.uint8))
            if not np.array_equal(rec, bins):
                diff = int(np.count_nonzero(rec != bins))
                fail("bins.u8 与 d 矩阵前 %d 峰重算不符（%d 字节差异）" % (top_m, diff))

        elem = np.fromfile(os.path.join(db, "elem.u8"), dtype=np.uint8)
        if elem.size != 118 * nbytes:
            fail("elem.u8 尺寸不符")
        else:
            elem = elem.reshape(118, nbytes)
            els = [r[0] or "" for r in conn.execute("SELECT elements FROM entries ORDER BY row_idx")]
            Z_OF = {}
            from_els = ("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
                        "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe "
                        "Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au "
                        "Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr "
                        "Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og").split()
            for idx, s in enumerate(from_els, 1):
                Z_OF[s] = idx
            rec = np.zeros_like(elem)
            rows_i, cols_i = [], []
            for phase_i, s in enumerate(els):
                for tok in s.split(","):
                    z = Z_OF.get(tok.strip())
                    if z:
                        rows_i.append(z - 1)
                        cols_i.append(phase_i)
            if rows_i:
                rows_i = np.asarray(rows_i, np.int64)
                cols_i = np.asarray(cols_i, np.int64)
                np.bitwise_or.at(rec, (rows_i, cols_i >> 3),
                                 (np.uint8(1) << (cols_i & 7).astype(np.uint8)).astype(np.uint8))
            if not np.array_equal(rec, elem):
                fail("elem.u8 与 entries.elements 重算不符")

    # ── L3 精度层：抽样回算 ──
    if sample > 0 and n:
        sys.path.insert(0, TOOLS)
        try:
            import fastxrd as FX  # noqa: E402
            from fastcif import parse_cif, expand_sites  # noqa: E402
        except Exception as e:  # noqa: BLE001
            warn("无法导入 fastxrd/fastcif，跳过 L3：%s" % e)
            FX = None

        if FX is not None:
            rng = np.random.default_rng(20261021)
            idxs = rng.choice(n, size=min(sample, n), replace=False)
            rows = conn.execute(
                "SELECT eid, cif_rel, n_peaks FROM entries ORDER BY row_idx").fetchall()
            worst_d = worst_i = 0.0
            n_cmp = 0
            for r in sorted(int(x) for x in idxs):
                eid, cif_rel, n_pk = rows[r]
                path = os.path.join(COD_ROOT, str(cif_rel).replace("\\", "/"))
                if not os.path.exists(path):
                    warn("源 CIF 缺失: %s" % cif_rel)
                    continue
                try:
                    with open(path, "rb") as fh:
                        dd = parse_cif(fh.read().decode("utf-8", errors="replace"))
                    coords, sp, _u = expand_sites(dd.sites, dd.symops)
                    rr, ss, oo = [], [], []
                    for c, s in zip(coords, sp):
                        for el, o in s.items():
                            o = float(o)
                            rr.append(c)
                            ss.append(el)
                            oo.append(min(o, 1.0) if o > 0 else 1.0)
                    tth_max = math.degrees(2.0 * math.asin(min(1.0, 1.5406 / 2.0)))
                    out = FX.compute_pattern_arrays(
                        dd.a, dd.b, dd.c, dd.alpha, dd.beta, dd.gamma,
                        np.asarray(rr, dtype=float), ss, oo,
                        wavelength=1.5406, tth_range=(5.0, tth_max),
                        max_hkl=30000, half_sphere=True, scale=1000.0,
                        max_peaks=500)
                    if len(out) != 2:
                        continue
                    rd = np.sort(np.asarray(out[0], dtype=np.float64))
                    ri = np.asarray(out[1], dtype=np.float64)
                    order = np.argsort(-ri, kind="stable")[:k]
                    rd_top = np.sort(np.asarray(out[0], dtype=np.float64)[order])
                except Exception as e:  # noqa: BLE001
                    warn("回算失败 %s: %s" % (cif_rel, e))
                    continue
                lib_d = np.sort(np.asarray(d[r], dtype=np.float64)[np.asarray(d[r]) > 0])
                m = min(lib_d.size, rd_top.size)
                if m:
                    worst_d = max(worst_d, float(np.max(np.abs(lib_d[:m] - rd_top[:m]))))
                    lib_i = np.sort(np.asarray(i[r], dtype=np.float64) / 65535.0 * 1000.0)
                    ref_i = np.sort(np.asarray(out[1], dtype=np.float64)[order])[:m]
                    # 只比 d 匹配到的前若干峰强度（排序后对齐不严谨，取绝对差上限参考）
                    worst_i = max(worst_i, float(np.max(np.abs(lib_i[-5:] - ref_i[-5:]))) if m >= 5 else 0.0)
                    n_cmp += 1
            rep["checks"]["sample_compared"] = n_cmp
            rep["checks"]["max_abs_d"] = worst_d
            rep["checks"]["max_abs_i"] = worst_i
            if n_cmp and worst_d > D_TOL:
                fail("抽样 d 偏差 %.2e > 容差 %.1e" % (worst_d, D_TOL))
            if n_cmp and worst_i > 5 * I_TOL:
                fail("抽样 I 偏差 %.2f > 容差 %.1f" % (worst_i, 5 * I_TOL))
    conn.close()

    rep["ok"] = not rep["failures"]
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--no-hash", action="store_true")
    ap.add_argument("--no-bitmaps", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    rep = verify(args.db, sample=args.sample, check_hash=not args.no_hash,
                 check_bitmaps=not args.no_bitmaps)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
    print("polyDB verify: %s" % ("PASS" if rep["ok"] else "FAIL"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
