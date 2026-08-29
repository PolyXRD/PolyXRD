"""
把完整 COD 库 (含 cif_gz, ~1.4 GB) 收缩为精简发行版 (~173 MB):
  - cod_entries.cif_gz 全部置 NULL (省 ~1.2 GB)
  - 保留 cod_atomic_sites (~3.2M 行) 用于离线 Phase 构建/精修
  - VACUUM 回收空闲页

CIF 原文获取路径 (get_cif 四级回退, 见 cod_local.py):
  1) 本地 cod/ 目录 CIF 文件
  2) SQLite cif_gz (此脚本清空后, 将不再命中)
  3) 原 tar 归档 (如果用户仍保留 tar)
  4) COD REST API https://www.crystallography.net/cod/<id>.cif (兜底, 需联网)
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

DB = Path(r"d:\TEMP\PolyXRD\cod_index.sqlite")


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> int:
    if not DB.exists():
        print(f"[FATAL] {DB} not found")
        return 2

    before = DB.stat().st_size
    print(f"[INFO] Before: {human(before)} ({before} bytes)")

    # 先统计 cif_gz 占用
    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA journal_mode = DELETE")  # 切回 DELETE, VACUUM 必须无 WAL
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
    n_cif = conn.execute("SELECT COUNT(*) FROM cod_entries WHERE LENGTH(cif_gz)>0").fetchone()[0]
    cif_bytes = conn.execute("SELECT COALESCE(SUM(LENGTH(cif_gz)),0) FROM cod_entries").fetchone()[0]
    n_sites = conn.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
    print(f"[INFO] cod_entries: {n}, cod_atomic_sites: {n_sites}")
    print(f"[INFO] cif_gz filled: {n_cif}, sum={human(cif_bytes)}")
    print()

    print("[1/3] UPDATE cod_entries SET cif_gz = NULL ...")
    t = time.time()
    conn.execute("UPDATE cod_entries SET cif_gz = NULL")
    conn.commit()
    print(f"       done in {time.time()-t:.1f} s")

    print("[2/3] UPDATE meta: store_cif_gz=0 (标记发行版) ...")
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('store_cif_gz','0')")
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('distribution_flavor','lean')")
    conn.commit()

    # 关闭后才能 VACUUM
    conn.close()
    print("[3/3] VACUUM (回收空闲页, 可能要 30-120 秒) ...")
    t = time.time()
    conn2 = sqlite3.connect(str(DB), timeout=300)
    conn2.isolation_level = None  # 必须 autocommit
    conn2.execute("VACUUM")
    conn2.close()
    print(f"       done in {time.time()-t:.1f} s")

    after = DB.stat().st_size
    saved = before - after
    print()
    print(f"[INFO] After : {human(after)} ({after} bytes)")
    print(f"[INFO] Saved : {human(saved)} ({saved/(before or 1)*100:.1f}% of original)")
    print(f"[INFO] Lean DB ready for distribution (~{round(after/1024/1024,0)} MB)")
    print(f"[INFO] Verify with: python -m polyxrd.services.cod_local stats")
    return 0


if __name__ == "__main__":
    sys.exit(main())
