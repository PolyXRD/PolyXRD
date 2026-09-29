"""重打 Databases-COD-inorg 外挂包 (v0.13.2, 载荷 = 修复后的无机库)

现有 v0.13.1 包的内部结构是**单条目、根路径** ``COD_inorganics.sqlite`` (deflate),
本脚本 1:1 复刻该结构, 换成修复 formula + cell_* 之后的库。

流程: integrity_check -> 记录源 SHA256 -> 打包 -> 回读校验 -> 写 SHA256 清单。
v0.13.1 旧包不覆盖 (保持已发布产物的自洽), 新包用 v0.13.2 命名。
"""

import hashlib
import os
import shutil
import sqlite3
import sys
import time
import zipfile

ROOT = r"D:/Project/XRD/PolyXRD"
SRC = os.path.join(ROOT, "cod_data", "COD_inorganics.sqlite")
OUT = os.path.join(ROOT, "installer_output",
                   "PolyXRD-v0.13.2-Databases-COD-inorg.zip")
ENTRY = "COD_inorganics.sqlite"
SHA_TXT = os.path.join(ROOT, "installer_output", "SHA256-v0.13.2.txt")
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


print("=" * 74)
print("重打 Databases-COD-inorg.zip  →  v0.13.2")
print("=" * 74)

# 1) 库完整性
print("[1/4] PRAGMA integrity_check ...")
conn = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
try:
    t0 = time.time()
    row = conn.execute("PRAGMA integrity_check").fetchone()
finally:
    conn.close()
if not row or row[0] != "ok":
    print(f"  [x] integrity_check = {row!r}  → 中止, 不打包")
    sys.exit(1)
print(f"  [OK] integrity_check = ok  ({time.time() - t0:,.1f}s)")

# 2) 源哈希
print("[2/4] 计算源库 SHA256 ...")
t0 = time.time()
src_hash, src_size = sha256_file(SRC)
print(f"  [OK] {src_hash}")
print(f"       size = {src_size:,} bytes ({mb(src_size)} MB)  "
      f"({time.time() - t0:,.1f}s)")

# 3) 打包 (流式, 单条目根路径, 与旧包结构一致)
if os.path.exists(OUT):
    print(f"  [!] 目标已存在, 覆盖: {OUT}")
    os.remove(OUT)
print("[3/4] 打包 (deflate) ...")
zi = zipfile.ZipInfo(ENTRY, date_time=(2026, 9, 18, 13, 30, 0))
zi.compress_type = zipfile.ZIP_DEFLATED
zi.external_attr = 0o644 << 16
t0 = time.time()
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
    with z.open(zi, "w") as tgt, open(SRC, "rb") as f:
        shutil.copyfileobj(f, tgt, CHUNK)
zip_size = os.path.getsize(OUT)
print(f"  [OK] {zip_size:,} bytes ({mb(zip_size)} MB)  "
      f"({time.time() - t0:,.1f}s)")
print(f"       压缩比 = {zip_size / src_size:.3f}")

# 4) 回读校验: 解压出的字节必须与源库逐位一致
print("[4/4] 回读校验 (整条解压 + SHA256) ...")
t0 = time.time()
h = hashlib.sha256()
n = 0
with zipfile.ZipFile(OUT) as z:
    names = z.namelist()
    if names != [ENTRY]:
        print(f"  [x] 条目异常: {names}")
        sys.exit(1)
    bad = z.testzip()
    if bad is not None:
        print(f"  [x] CRC 校验失败: {bad}")
        sys.exit(1)
    with z.open(ENTRY) as f:
        for c in iter(lambda: f.read(CHUNK), b""):
            h.update(c)
            n += len(c)
out_hash = h.hexdigest()
if n != src_size or out_hash != src_hash:
    print(f"  [x] 不一致: size {n:,} vs {src_size:,}, "
          f"hash {out_hash} vs {src_hash}")
    sys.exit(1)
print(f"  [OK] 逐位一致: {n:,} bytes, {out_hash}  ({time.time() - t0:,.1f}s)")

# 5) SHA256 清单 (沿用 v0.13.1 的版式)
now = time.strftime("%Y-%m-%d %H:%M:%S")
with open(SHA_TXT, "w", encoding="utf-8") as f:
    f.write("PolyXRD v0.13.2 发布产物校验值 (SHA-256)\n")
    f.write(f"生成时间: {now}\n")
    f.write("单位说明: MB = 1,048,576 字节 (资源管理器口径)\n")
    f.write("\n")
    f.write(f"{out_hash}  {os.path.basename(OUT)}\n")
    f.write(f"#   size = {zip_size:,} bytes ({mb(zip_size)} MB)\n")
    f.write(f"#   内含: {ENTRY}  {src_size:,} bytes ({mb(src_size)} MB)\n")
    f.write(f"#   载荷 = v0.13.2 修复后的无机库 (formula 609→72, cell_* 31,634 行)\n")
    f.write("#   注: Setup / Portable / 其余两个库包仍为 v0.13.1, 重打包后补入本清单\n")
print(f"\n清单 → {SHA_TXT}")
print("=" * 74)
print("完成")
print("=" * 74)
