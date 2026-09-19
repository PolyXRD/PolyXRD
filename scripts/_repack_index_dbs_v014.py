# -*- coding: utf-8 -*-
"""打包 v0.14.0 两个索引版数据库外挂包 (流式 + 回读逐位校验)。

产物 (installer_output/):
  PolyXRD-v0.14.0-Databases-COD-full-index.zip   <- cod_data/cod_index.sqlite (432 MB)
  PolyXRD-v0.14.0-Databases-COD-inorg-index.zip  <- cod_data/COD_inorganics_index.sqlite (362 MB)

结构沿用旧包: 单条目、根路径、deflate。打包后整条回读 + SHA256 逐位比对。
⚠️ PDF2_2004.sqlite 是 ICDD 版权库, 本脚本刻意不处理, 永不上传。
"""

import hashlib
import os
import shutil
import sqlite3
import sys
import time
import zipfile

ROOT = r"E:\TEMP\PolyXRD"
VER = "0.14.0"
JOBS = [
    ("cod_data/cod_index.sqlite", "cod_index.sqlite",
     f"PolyXRD-v{VER}-Databases-COD-full-index.zip"),
    ("cod_data/COD_inorganics_index.sqlite", "COD_inorganics_index.sqlite",
     f"PolyXRD-v{VER}-Databases-COD-inorg-index.zip"),
]
SHA_TXT = os.path.join(ROOT, "installer_output", f"SHA256-{VER}.txt")
CHUNK = 8 * 1024 * 1024


def sha256_file(path):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(CHUNK), b""):
            h.update(c)
            n += len(c)
    return h.hexdigest(), n


def mb(n):
    return f"{n / 1048576:,.1f}"


lines = [f"PolyXRD v{VER} 发布产物校验值 (SHA-256)",
         f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
         "单位说明: MB = 1,048,576 字节 (资源管理器口径)", ""]

for rel, entry, out_name in JOBS:
    src = os.path.join(ROOT, rel)
    out = os.path.join(ROOT, "installer_output", out_name)
    print("=" * 74)
    print(f"打包 {entry} -> {out_name}")
    print("=" * 74)

    print("[1/4] PRAGMA integrity_check ...")
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        t0 = time.time()
        row = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    if not row or row[0] != "ok":
        print(f"  [x] integrity_check = {row!r} -> 中止")
        sys.exit(1)
    print(f"  [OK] ({time.time() - t0:,.1f}s)")

    print("[2/4] 计算源库 SHA256 ...")
    src_hash, src_size = sha256_file(src)
    print(f"  [OK] {src_hash}")
    print(f"       size = {src_size:,} bytes ({mb(src_size)} MB)")

    if os.path.exists(out):
        os.remove(out)
    print("[3/4] 打包 (deflate) ...")
    zi = zipfile.ZipInfo(entry, date_time=time.localtime()[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    t0 = time.time()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        with z.open(zi, "w") as tgt, open(src, "rb") as f:
            shutil.copyfileobj(f, tgt, CHUNK)
    zip_size = os.path.getsize(out)
    print(f"  [OK] {zip_size:,} bytes ({mb(zip_size)} MB)  "
          f"({time.time() - t0:,.1f}s)  压缩比={zip_size / src_size:.3f}")

    print("[4/4] 回读校验 (整条解压 + SHA256) ...")
    t0 = time.time()
    h = hashlib.sha256()
    n = 0
    with zipfile.ZipFile(out) as z:
        if z.namelist() != [entry]:
            print(f"  [x] 条目异常: {z.namelist()}")
            sys.exit(1)
        bad = z.testzip()
        if bad is not None:
            print(f"  [x] CRC 失败: {bad}")
            sys.exit(1)
        with z.open(entry) as f:
            for c in iter(lambda: f.read(CHUNK), b""):
                h.update(c)
                n += len(c)
    if n != src_size or h.hexdigest() != src_hash:
        print("  [x] 回读不一致!")
        sys.exit(1)
    print(f"  [OK] 逐位一致 ({time.time() - t0:,.1f}s)")

    lines += [f"{h.hexdigest()}  {out_name}",
              f"#   size = {zip_size:,} bytes ({mb(zip_size)} MB)",
              f"#   内含: {entry}  {src_size:,} bytes ({mb(src_size)} MB)", ""]

with open(SHA_TXT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"清单 -> {SHA_TXT}")
print("全部完成")
