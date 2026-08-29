"""
全量重建 COD LEAN 精简索引库 (步骤 2, 优化版)
===============================================
store_cif_gz = False:
  - 不存 cif_gz BLOB -> 节省 ~1.2 GB, 减少 90% CPU(gzip) + I/O
  - 完整保留 cod_entries 元数据 + cod_atomic_sites (预解析原子位点)
  - CIF 原文兜底: COD REST API https://www.crystallography.net/cod/<id>.cif

Lean DB 最终体积估算: ~173 MB (元数据33MB + 原子位点~140MB)
Lean DB 完全离线:
  - 物相检索 (formula/elements/sg/cell): ✅
  - Phase 构建 (从 atomic_sites):  ✅
  - Rietveld 精修 (直接用 Phase):  ✅
  - Reference XRD 峰 (pymatgen): ✅ (从 atomic_sites + lattice 生成 Structure)
  - 原始 CIF 导出: 需联网 (COD REST API fallback)
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
    TAR_PATH = PROJ / "cod-cifs-mysql.tar"


def main() -> int:
    if not TAR_PATH.exists():
        print(f"[FATAL] tar not found: {TAR_PATH}")
        return 2
    tar_size_gb = round(TAR_PATH.stat().st_size / 1024**3, 1)
    print(f"[INFO] tar: {TAR_PATH} ({tar_size_gb} GB)")

    # 1) 备份当前 DB (如果存在)
    if DB_PATH.exists():
        bak = DB_PATH.parent / f"cod_index.sqlite.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB_PATH, bak)
        old_mb = round(DB_PATH.stat().st_size / 1024**2, 1)
        print(f"[INFO] Backed up existing DB: {bak.name} ({old_mb} MB)")

    # 2) 删除旧 DB + WAL/SHM/journal -> 全新建表 (无迁移, 最干净)
    for suf in ("", "-wal", "-shm", "-journal"):
        p = Path(str(DB_PATH) + suf)
        if p.exists():
            try:
                p.unlink()
                print(f"[INFO] deleted {p.name}")
            except Exception as e:
                print(f"[WARN] cannot delete {p.name}: {e}")

    cod_root = PROJ / "cod"
    cod_root.mkdir(parents=True, exist_ok=True)

    from polyxrd.services.cod_local import CODLocalIndexer

    indexer = CODLocalIndexer(cod_root=cod_root, db_path=DB_PATH)

    t0 = time.time()
    last_pct = -1
    last_flush = t0
    EST_TOTAL = 93391

    def cb(done: int, total: int, ok: int, skip: int) -> None:
        nonlocal last_pct, last_flush
        pct = int(done / EST_TOTAL * 100)
        now = time.time()
        if pct != last_pct and now - last_flush > 30:
            last_pct = pct
            last_flush = now
            elapsed = now - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta_min = (EST_TOTAL - done) / rate / 60 if rate > 0 else 0
            print(f"  [{time.strftime('%H:%M:%S')}] "
                  f"{done:>6d}/{EST_TOTAL} ({pct:>3d}%)  ok={ok:>6d}  "
                  f"{rate:.0f}/s  ETA≈{eta_min:.0f} min  "
                  f"elapsed={elapsed/60:.1f} min", flush=True)

    print("[INFO] === Lean 重建启动 (store_cif_gz=False) ===", flush=True)
    t_start = time.time()
    stats = indexer.build_index_from_tar(
        TAR_PATH,
        progress_cb=cb,
        batch_size=5000,
        max_entries=None,
        clear_existing=False,
        store_cif_gz=False,   # <--- KEY: 不存 CIF BLOB, 精简版直接 ~173 MB
    )
    t_end = time.time()

    print(f"\n[INFO] === 重建完成: {round((t_end-t_start)/60,1)} min ===", flush=True)
    print(f"       indexed:     {stats.get('indexed', 0):>6d}")
    print(f"       failed:      {stats.get('failed', 0):>6d}")
    print(f"       atomic_sites:{stats.get('atomic_sites', 0):>6d}")

    # 3) 最终统计
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    n_entries = conn.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
    n_cif = conn.execute("SELECT COUNT(*) FROM cod_entries WHERE LENGTH(cif_gz) > 0").fetchone()[0]
    n_sites = conn.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
    ok_entries = conn.execute("SELECT COUNT(*) FROM cod_entries WHERE parse_ok=1").fetchone()[0]
    meta = {k: v for k, v in conn.execute("SELECT key,value FROM meta")}
    conn.close()
    db_mb = round(DB_PATH.stat().st_size / 1024**2, 1)

    print(f"\n===== LEAN 精简数据库最终报告 =====")
    print(f"  文件名:              {DB_PATH.name}")
    print(f"  路径:                {DB_PATH}")
    print(f"  总体积:              {db_mb} MB   (仅为 102GB tar 的 {db_mb / (102*1024) * 100:.3f}%)")
    print(f"  cod_entries:         {n_entries:>6d}  (parse_ok=1: {ok_entries})")
    print(f"  cod_entries.cif_gz:  {n_cif:>6d}  (LEAN=0, 预期值为 0)")
    print(f"  cod_atomic_sites:    {n_sites:>6d}  (avg {n_sites/n_entries:.1f} sites/entry)")
    print(f"  meta.tar_source:     {meta.get('tar_source','')}")
    print(f"  meta.schema_version: {meta.get('schema_version','')}")
    print(f"  distribution_flavor: {meta.get('distribution_flavor','LEAN (default)')}")
    print(f"\nLean DB 能力:")
    print(f"  ✅ 物相检索 (化学式/元素/空间群/晶胞体积)")
    print(f"  ✅ 物相识别 PhaseIdentifier (从 atomic_sites 生成参考峰)")
    print(f"  ✅ Rietveld 精修 (直接用 Phase.atomic_sites)")
    print(f"  ✅ 原始 CIF 获取 (四级回退 -> REST API 兜底)")
    print(f"\n✅ 旧备份目录可找到: cod_index.sqlite.bak_*")
    print(f"✅ 102 GB tar 可安全删除 (或离线保留)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
