"""
全量重建 COD 精简索引库 (步骤 2)
==================================
1) 备份现有 cod_index.sqlite 为 cod_index.sqlite.bak_YYYYMMDD
2) 从 102 GB tar 流式重建:
   - cif_gz: gzip 压缩 CIF 全文存入 BLOB
   - cod_atomic_sites: 预解析原子位点
   - cod_entries: 元数据 (formula/elements/sg/cell 等)
3) 显示进度, 完成后打印统计
"""
from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

PROJ = Path(r"d:\TEMP\PolyXRD")
sys.path.insert(0, str(PROJ / "src"))

DB_PATH = PROJ / "cod_index.sqlite"
TAR_PATH = PROJ / "cod" / "cod-cifs-mysql.tar"
if not TAR_PATH.exists():
    # 备选位置
    TAR_PATH = PROJ / "cod-cifs-mysql.tar"


def main() -> int:
    if not TAR_PATH.exists():
        print(f"[FATAL] tar not found: {TAR_PATH}")
        return 2
    tar_size_gb = round(TAR_PATH.stat().st_size / 1024**3, 1)
    print(f"[INFO] tar: {TAR_PATH} ({tar_size_gb} GB)")

    # 1) 备份旧库
    if DB_PATH.exists():
        bak = DB_PATH.parent / f"cod_index.sqlite.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB_PATH, bak)
        old_size_mb = round(DB_PATH.stat().st_size / 1024**2, 1)
        print(f"[INFO] Old DB backed up: {bak} (was {old_size_mb} MB)")
    else:
        print(f"[INFO] No existing DB at {DB_PATH}, start fresh")

    # 2) 删旧库 (保证干净的 CREATE TABLE, 不走迁移 ALTER TABLE)
    if DB_PATH.exists():
        # 保留 WAL / SHM 一并删
        for suf in ("", "-wal", "-shm", "-journal"):
            p = Path(str(DB_PATH) + suf)
            if p.exists():
                try:
                    p.unlink()
                except Exception as e:
                    print(f"[WARN] cannot delete {p}: {e}")

    cod_root = PROJ / "cod"
    cod_root.mkdir(parents=True, exist_ok=True)

    from polyxrd.services.cod_local import CODLocalIndexer

    indexer = CODLocalIndexer(cod_root=cod_root, db_path=DB_PATH)

    t0 = time.time()
    last_pct = -1

    def cb(done: int, total: int, ok: int, skip: int) -> None:
        nonlocal last_pct
        # total = -1 (tar 模式无总数), 用已知 93391 估算
        est_total = 93391
        pct = int(done / est_total * 100) if total == -1 else int(done / total * 100)
        if pct != last_pct and (done % 2000 == 0 or pct % 5 == 0):
            last_pct = pct
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta_min = (est_total - done) / rate / 60 if rate > 0 else 0
            print(f"  progress: {done:>6d}/{est_total} ({pct:>3d}%)  ok={ok:>6d}  "
                  f"rate={rate:.0f}/s  ETA≈{eta_min:.0f} min  elapsed={elapsed/60:.1f} min")

    print("[INFO] 开始全量重建 (约 15-25 分钟)...")
    stats = indexer.build_index_from_tar(
        TAR_PATH,
        progress_cb=cb,
        batch_size=5000,
        max_entries=None,
        clear_existing=False,  # 新库已清空, 无需再次 delete
    )

    print()
    print(f"[INFO] 重建完成, 用时 {stats.get('elapsed', 0)} s")
    print(f"       indexed:     {stats.get('indexed', 0):>6d}")
    print(f"       failed:      {stats.get('failed', 0):>6d}")
    print(f"       atomic_sites:{stats.get('atomic_sites', 0):>6d}")

    # 3) 统计最终体积
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    n_cif = conn.execute("SELECT COUNT(*) FROM cod_entries WHERE LENGTH(cif_gz) > 0").fetchone()[0]
    cif_kb = conn.execute("SELECT COALESCE(SUM(LENGTH(cif_gz))/1024,0) FROM cod_entries").fetchone()[0]
    n_sites = conn.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
    meta = {k: v for k, v in conn.execute("SELECT key,value FROM meta")}
    conn.close()
    db_mb = round(DB_PATH.stat().st_size / 1024**2, 1)

    print(f"\n===== 最终精简库 {DB_PATH.name} =====")
    print(f"  总体积:              {db_mb} MB")
    print(f"  cod_entries 总数:    {stats.get('indexed', 0):>6d}")
    print(f"  cif_gz 填充 (非零):  {n_cif:>6d}  (size={cif_kb/1024:.1f} MB, avg={cif_kb*1024/n_cif:.0f} B)")
    print(f"  cod_atomic_sites:    {n_sites:>6d}  (avg {n_sites/stats.get('indexed',1):.1f} sites/entry)")
    print(f"  相对 102 GB tar:     {db_mb / (102*1024) * 100:.3f} %")
    print(f"  meta.tar_source:     {meta.get('tar_source','')}")
    print(f"  meta.last_build_time:{meta.get('last_build_time','')}")
    print(f"\n[OK] 旧备份仍保留: {bak if DB_PATH.exists() and 'bak' in locals() else '(无旧库)'}")
    print("     可手动删除以释放 ~33 MB 空间; 102 GB tar 现在也可删除 (或留作备份)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
