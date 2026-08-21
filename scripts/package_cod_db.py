"""Package the COD inorganic SQLite database for standalone distribution.

This script produces a self-contained release package that can be imported
into PolyXRD via the menu [Phase Analysis → Import Phase Database].

Output layout (under dist/polyxrd_match_db_v{VERSION}/):
    COD_inorganics.sqlite      # the 71199-phase SQLite DB
    README.md                    # usage instructions
    VERSION.txt                  # version + phase count metadata

Usage:
    python scripts/package_match_db.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import get_config


def main() -> int:
    config = get_config()
    db_path = config.get_cod_db_path()

    if not db_path.exists():
        print(f"ERROR: COD inorganic database not found at {db_path}")
        return 1

    # Collect metadata directly from the SQLite file
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.execute("SELECT COUNT(*) FROM phases")
    phase_count = int(cur.fetchone()[0])
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [r[0] for r in cur.fetchall()]
    conn.close()

    version = config.app_version
    dist_dir = ROOT / "dist" / f"polyxrd_cod_db_v{version}"
    dist_dir.mkdir(parents=True, exist_ok=True)

    # Copy the SQLite file (in read mode, fast on same filesystem)
    import shutil
    dest_db = dist_dir / "COD_inorganics.sqlite"
    if dest_db.exists():
        dest_db.unlink()
    print(f"Copying {db_path} -> {dest_db} ...")
    shutil.copy2(db_path, dest_db)
    size_mb = dest_db.stat().st_size / (1024 * 1024)
    print(f"  size: {size_mb:.1f} MB, {phase_count} phases")

    # VERSION.txt
    version_file = dist_dir / "VERSION.txt"
    version_file.write_text(
        json.dumps(
            {
                "database": "COD_inorganics",
                "version": version,
                "phase_count": phase_count,
                "tables": tables,
                "built_at": datetime.now().isoformat(timespec="seconds"),
                "compatible_polyxrd": f">={version}",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # README.md
    readme = dist_dir / "README.md"
    readme.write_text(
        f"""# PolyXRD COD 无机物相数据库

**版本**: v{version}
**物相数**: {phase_count}
**文件大小**: {size_mb:.1f} MB

## 数据来源

由 `scripts/build_cod_sqlite.py` 从原始私有二进制
(`user_database.mtu`) 逆向生成的 SQLite 数据库,包含 71199 个无机物相的:
- 化学式(formula,按元素字母排序存储,如 SiO2 存为 "O2 Si")
- 空间群(space_group)
- 晶胞参数(cell_a/b/c/alpha/beta/gamma)
- 衍射峰 d-I 数据(peaks_d / peaks_i)
- 编号:`display_id`(97-xxxxxxx 格式,后 7 位为 COD 真实 ID)
       `ref_id`(COD 原生 96-XXX-YYYY 格式)

## 安装方式

1. 将 `COD_inorganics.sqlite` 放到任意目录(如 `~/PolyXRD_db/`)
2. 启动 PolyXRD v{version} 或更高版本
3. 菜单 [Phase Analysis → Import Phase Database...]
   (中:[物相分析 → 导入物相数据库...])
4. 选择 `COD_inorganics.sqlite` 文件
5. 导入成功后显示物相数,路径自动持久化到 `~/.polyxrd/user_db_paths.json`
6. 下次启动 PolyXRD 会自动加载,无需重复导入

## 数据库表结构

Tables: {tables}

主要字段:
- `phases` 表:
  - `cod_id INTEGER`(COD 真实 ID)
  - `display_id TEXT`(PolyXRD 编号 97-xxxxxxx)
  - `ref_id TEXT`(COD 原生 96-XXX-YYYY)
  - `formula TEXT`(化学式,元素字母排序)
  - `space_group TEXT`(空间群)
  - `cell_a/b/c/alpha/beta/gamma REAL`(晶胞参数)
  - `n_peaks INTEGER`(峰数)
  - `peaks_d TEXT`(逗号分隔的 d 值)
  - `peaks_i TEXT`(逗号分隔的 I 值)

## 兼容性

- PolyXRD v{version} 及以上
- SQLite 3.x(只读访问,兼容主流操作系统)

## 许可

数据来源于 COD (Crystallography Open Database) 和 COD 软件,
仅供科研和教学使用。
""",
        encoding="utf-8",
    )

    print(f"\nPackage created at: {dist_dir}")
    print(f"  - COD_inorganics.sqlite ({size_mb:.1f} MB)")
    print(f"  - README.md")
    print(f"  - VERSION.txt")
    print(f"\nPhase count: {phase_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
