"""
TDD RED: 小样本 tar 索引验证 (前 1000 条 CIF)
------------------------------------------------
这个测试预期会因为以下 2 个原因而失败:
  1) cod_local.connect() 只会 CREATE TABLE IF NOT EXISTS, 不会对
     已存在但缺少 cif_gz 列的旧表执行迁移 (schema 不一致)
  2) build_index_from_tar 没有 max_entries 参数, 无法只跑前 N 条

验证点:
  a) cif_gz 列存在且已填充 (非 NULL, 非零长度)
  b) cod_atomic_sites 有记录
  c) get_cif() 能从 cif_gz BLOB 解压出合法 CIF (含 data_ 行)
  d) get_phase() 从 cod_atomic_sites 构建 Phase, 并生成 reference_peaks
  e) 统计整体数据库体积 (1000 条应 < 5 MB)
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

TAR_SRC = Path(r"d:\TEMP\PolyXRD\cod\cod-cifs-mysql.tar")
if not TAR_SRC.exists():
    TAR_SRC = Path(r"d:\TEMP\PolyXRD\cod-cifs-mysql.tar")

SAMPLE_ENTRIES = 1000


def main() -> int:
    if not TAR_SRC.exists():
        print(f"[FATAL] tar not found: {TAR_SRC}")
        return 2
    print(f"[INFO] tar source: {TAR_SRC}")

    # ── 独立临时目录, 避免污染生产库 ────────────────────────
    tmp = Path(tempfile.mkdtemp(prefix="cod_sample_"))
    db_path = tmp / "cod_index_sample.sqlite"
    cod_root = tmp / "cod"
    cod_root.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] sample db: {db_path}")

    try:
        # 1) 导入 build_index_from_tar; 先检查它是否支持 max_entries
        sys.path.insert(0, str(Path(r"d:\TEMP\PolyXRD\src")))
        from polyxrd.services.cod_local import CODLocalIndexer

        indexer = CODLocalIndexer(cod_root=cod_root, db_path=db_path)
        try:
            stats = indexer.build_index_from_tar(
                TAR_SRC,
                progress_cb=lambda done, total, ok, skip: (
                    print(f"\r  progress: {done} files (ok={ok})", end="", flush=True)
                    if done % 100 == 0 else None
                ),
                max_entries=SAMPLE_ENTRIES,
            )
            print()
        except TypeError as e:
            # RED 原因 2: 没有 max_entries 参数
            print(f"\n[RED] build_index_from_tar missing max_entries: {e}")
            print("       -> 必须在 cod_local.py 中新增 max_entries 参数支持")
            return 1

        print(f"[INFO] build stats: {stats}")

        # 2) 直接查库看 schema 和数据 (不依赖 get_cif 等方法, 验证底层)
        conn = sqlite3.connect(str(db_path))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(cod_entries)")}
        sites_count = conn.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
        n_entries = conn.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
        n_with_cif = conn.execute(
            "SELECT COUNT(*) FROM cod_entries WHERE cif_gz IS NOT NULL"
        ).fetchone()[0] if "cif_gz" in cols else -1
        n_with_cif_nonzero = (
            conn.execute(
                "SELECT COUNT(*) FROM cod_entries WHERE LENGTH(cif_gz) > 0"
            ).fetchone()[0]
            if "cif_gz" in cols
            else -1
        )
        cif_total_kb = (
            conn.execute("SELECT COALESCE(SUM(LENGTH(cif_gz))/1024,0) FROM cod_entries").fetchone()[0]
            if "cif_gz" in cols
            else -1
        )
        db_size_mb = round(db_path.stat().st_size / 1024 / 1024, 2)
        conn.close()

        print(f"\n[CHECK] cod_entries columns: {cols}")

        # a) cif_gz 列存在?
        if "cif_gz" not in cols:
            print("[RED] cod_entries missing `cif_gz` column")
            print("       -> connect() 必须对旧库做迁移 ALTER TABLE ADD COLUMN cif_gz BLOB")
            return 1
        print("[GREEN a] cif_gz column exists")

        # a2) 条目数 >= 100 (至少有)
        if n_entries < 100:
            print(f"[RED] 只索引了 {n_entries} 条, 可能 max_entries 没生效或 tar 遍历异常")
            return 1
        print(f"[GREEN] entries indexed: {n_entries}")

        # b) cif_gz 非 NULL, 非零长度
        if n_with_cif < n_entries * 0.9:
            print(f"[RED] cif_gz 填充率过低: {n_with_cif}/{n_entries} (期望 > 90%)")
            return 1
        if n_with_cif_nonzero < n_entries * 0.9:
            print(f"[RED] cif_gz 零长度过多: {n_with_cif_nonzero}/{n_entries}")
            return 1
        print(f"[GREEN a] cif_gz filled: {n_with_cif_nonzero}/{n_entries}, size={cif_total_kb} KB, avg={cif_total_kb*1024/n_with_cif_nonzero:.0f} bytes/entry")

        # c) cod_atomic_sites 有数据
        if sites_count < n_entries * 0.9:
            print(f"[RED] cod_atomic_sites 太少: {sites_count} (期望 > {int(n_entries*0.9)})")
            return 1
        print(f"[GREEN b] atomic sites: {sites_count} (avg {sites_count/n_entries:.1f} sites/entry)")

        # d) get_cif() 从 cif_gz 解压: 取第一条能正常解压且含 data_
        from polyxrd.services.cod_local import CODLocalDatabase
        db = CODLocalDatabase(cod_root=cod_root, db_path=db_path)
        samples = db.search(limit=3, parse_ok_only=False)
        ok_cif = 0
        for e in samples:
            cif = db.get_cif(e.cod_id)
            if cif and "data_" in cif:
                ok_cif += 1
            else:
                print(f"   [WARN] cod_id={e.cod_id} get_cif returned {None if cif is None else len(cif)} chars")
        if ok_cif == 0:
            print("[RED] get_cif() from cif_gz BLOB 全失败")
            return 1
        print(f"[GREEN c] get_cif() decompressed OK: {ok_cif}/{len(samples)}")

        # e) get_phase() 构建 Phase + 生成 reference_peaks
        any_ok = False
        for e in samples:
            if not e.a or not e.formula:
                continue
            phase = db.get_phase(e.cod_id, use_pymatgen_peaks=True)
            if phase and phase.reference_peaks:
                any_ok = True
                print(f"   [INFO] cod_id={e.cod_id}: {phase.name}, sites={len(phase.atomic_sites)}, peaks={len(phase.reference_peaks)}")
                break
        if not any_ok:
            print("[RED] get_phase() 不能生成 reference_peaks")
            return 1
        print("[GREEN d] get_phase() -> reference_peaks OK (pymatgen XRD)")

        # f) 体积验证
        print(f"[CHECK] 1000 条样本库体积: {db_size_mb} MB  (期望 < 5 MB)")
        if db_size_mb > 5:
            print(f"[WARN] 1000 条已达 {db_size_mb} MB, 全量 93K 可能超标 (> 150 MB)")
        else:
            est_mb = round(db_size_mb * 93000 / n_entries, 0)
            print(f"[GREEN e] 体积合理, 估算全量 93K ≈ {est_mb} MB")

        print("\n===== 样本库 ALL GREEN =====")
        print(f"临时文件位于: {tmp}")
        return 0
    finally:
        # 保留临时目录给用户看，不删
        pass


if __name__ == "__main__":
    sys.exit(main())
