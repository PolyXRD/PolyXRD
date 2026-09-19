# -*- coding: utf-8 -*-
"""从 COD_inorganics.sqlite 派生「索引式」瘦身无机库。

思路 (对齐 cod_index.sqlite 的存储形态):
  - phases 表结构/峰表/原子位点全部保留, 仅把内嵌的 cif_gz BLOB 置 NULL
  - CIF 原文改由 cod/cif 四级分片目录 (cif/{d}/{dd}/{dd}/{id}.cif) 按需读取
  - 实测无机库 71,156 条内嵌 CIF 与 cod/cif 文件 100% 重合 (gz_only=0),
    43 条两者皆缺 (meta.cif_missing=43) → 全部置 NULL 零信息损失
  - 保留 cod_atomic_sites (311,126 行, 精修初始模型的核心数据)

产物: cod_data/COD_inorganics_index.sqlite (预期 ~360 MB, 原库 1.19 GB)

用法:
  python scripts/build_inorg_index_db.py            # dry-run, 只打印计划
  python scripts/build_inorg_index_db.py --apply    # 实际构建 (先删旧目标)
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "cod_data" / "COD_inorganics.sqlite"
DEFAULT_TARGET = PROJECT_ROOT / "cod_data" / "COD_inorganics_index.sqlite"
DEFAULT_CIF_DIR = PROJECT_ROOT / "cod" / "cif"


def _cif_file_path(cif_dir: Path, cod_id: int) -> Path:
    s = str(cod_id)
    return cif_dir / s[0] / s[1:3] / s[3:5] / f"{s}.cif"


def _audit(source: sqlite3.Connection, cif_dir: Path) -> dict:
    """四象限统计: (cif_gz 非空, cod/cif 文件存在) 组合。"""
    both = gz_only = file_only = neither = 0
    gz_only_ids: list[int] = []
    for cid, has_gz in source.execute("SELECT cod_id, cif_gz IS NOT NULL FROM phases"):
        has_file = _cif_file_path(cif_dir, cid).exists()
        if has_gz and has_file:
            both += 1
        elif has_gz:
            gz_only += 1
            gz_only_ids.append(cid)
        elif has_file:
            file_only += 1
        else:
            neither += 1
    return {
        "both": both, "gz_only": gz_only, "file_only": file_only,
        "neither": neither, "gz_only_ids": gz_only_ids,
    }


def build(source: Path, target: Path, cif_dir: Path, *, apply: bool) -> int:
    if not source.exists():
        print(f"[ERR] 源库不存在: {source}")
        return 2
    if not cif_dir.exists():
        print(f"[ERR] cod/cif 目录不存在: {cif_dir}")
        return 2

    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    n_phases = src.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
    n_sites = src.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
    n_gz = src.execute("SELECT COUNT(*) FROM phases WHERE cif_gz IS NOT NULL").fetchone()[0]
    audit = _audit(src, cif_dir)
    src.close()

    print(f"源库: {source} ({source.stat().st_size / 1048576:.1f} MB)")
    print(f"目标: {target}")
    print(f"cif 目录: {cif_dir}")
    print(f"phases={n_phases}, atomic_sites={n_sites}, cif_gz 非空={n_gz}")
    print(f"四象限: both={audit['both']} gz_only={audit['gz_only']} "
          f"file_only={audit['file_only']} neither={audit['neither']}")
    if audit["gz_only"]:
        print(f"[WARN] {audit['gz_only']} 条仅内嵌无文件, 置 NULL 会丢失 CIF: "
              f"样例 {audit['gz_only_ids'][:5]}")

    if not apply:
        print("\n(dry-run) 加 --apply 实际构建")
        return 0

    if audit["gz_only"]:
        print("[ABORT] 存在仅内嵌的条目, 需人工确认后再构建 (防止丢数据)")
        return 3

    t0 = time.time()
    if target.exists():
        target.unlink()
        print(f"已删除旧目标: {target}")
    print("复制源库 ...")
    shutil.copy2(source, target)

    db = sqlite3.connect(target)
    try:
        cur = db.execute("UPDATE phases SET cif_gz = NULL")
        print(f"UPDATE cif_gz=NULL: {cur.rowcount} 行 ({time.time() - t0:.0f}s)")
        db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES"
            "('variant', 'slim-index: cif_gz 全部置 NULL, CIF 由 cod/cif 目录按需读取'),"
            "('cif_embedded', '0'),"
            "('slim_build_time', datetime('now', 'localtime')),"
            "('slim_from', ?)",
            (str(source),),
        )
        db.commit()
        print("VACUUM ... (可能需要几分钟)")
        db.execute("VACUUM")
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        n_after = db.execute(
            "SELECT COUNT(*), SUM(cif_gz IS NOT NULL) FROM phases").fetchone()
        sites_after = db.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
        size_mb = target.stat().st_size / 1048576
        print(f"integrity_check={ok}")
        print(f"phases={n_after[0]}, cif_gz 非空残留={n_after[1]}, sites={sites_after}")
        print(f"目标体积: {size_mb:.1f} MB (原 {source.stat().st_size / 1048576:.1f} MB)")
        if ok != "ok" or n_after[0] != n_phases or sites_after != n_sites:
            print("[ERR] 校验失败!")
            return 4
    finally:
        db.close()
    print(f"完成, 用时 {time.time() - t0:.0f}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="实际构建 (默认 dry-run)")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    ap.add_argument("--cif-dir", type=Path, default=DEFAULT_CIF_DIR)
    a = ap.parse_args()
    return build(a.source, a.target, a.cif_dir, apply=a.apply)


if __name__ == "__main__":
    sys.exit(main())
