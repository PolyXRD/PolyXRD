"""给 COD / PDF2 物相库补上「预截断强峰列」，加速 d-I 检索。

背景
----
`CIFDatabase.search_cod_by_d_peaks` 的打分只用得上每相 I 值最高的
``max_ref_peaks``(默认 40) 个峰，但扫描层每次都要解析**全部**参考峰：

    COD 无机库  266.5 峰/相 ×  71,199 相 = 1,900 万个峰
    PDF2 库      63.8 峰/相 × 163,834 相 = 1,040 万个峰

本脚本在建库期把每相 I 最高的前 ``--top-n``(默认 64) 个峰按 I 降序另存成
两个 float64 BLOB 列 (``peaks_top_d`` / ``peaks_top_i``)。之后检索自动
改读这两列：解析量降到 24%，还能省掉每相的 argsort。

**结果与迁移前完全一致**（前缀等价性，详见 ``cif_database._PEAK_TOP_N``
上方注释），且请求 ``max_ref_peaks > top_n`` 时会自动回退全长解析。

用法
----
    python build_top_peaks.py              # 检查并迁移（幂等，默认带备份）
    python build_top_peaks.py --status     # 只看状态，不动数据
    python build_top_peaks.py --db <path>  # 只处理指定库
    python build_top_peaks.py --no-backup  # 跳过备份（不建议）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from polyxrd.services.cif_database import (  # noqa: E402
    _PEAK_TOP_N,
    build_top_peak_columns,
    top_peak_column_stats,
)


def _avg_peaks(db_path: Path) -> float | None:
    """平均每相参考峰数 —— 判断该库值不值得做预截断。"""
    import sqlite3

    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT AVG(n_peaks) FROM phases").fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None
    finally:
        conn.close()


def _targets(explicit: str | None) -> list[tuple[str, Path]]:
    if explicit:
        return [("指定库", Path(explicit))]
    from polyxrd.config import get_config

    cfg = get_config()
    return [("COD 无机库", cfg.get_cod_db_path()),
            ("PDF2 库", cfg.get_pdf2_db_path())]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="只处理指定数据库路径")
    ap.add_argument("--top-n", type=int, default=_PEAK_TOP_N,
                    help=f"每相保留的强峰数 (默认 {_PEAK_TOP_N}, 必须 ≥ 12)")
    ap.add_argument("--status", action="store_true", help="只报告状态, 不修改")
    ap.add_argument("--no-backup", action="store_true", help="跳过整库备份")
    ap.add_argument("--vacuum", action="store_true", help="收尾 VACUUM 重整文件")
    args = ap.parse_args()

    if args.top_n < 12:
        print(f"错误: --top-n 必须 ≥ 12 (收到 {args.top_n})", file=sys.stderr)
        return 2

    rc = 0
    for label, path in _targets(args.db):
        print(f"\n=== {label} ===")
        print(f"路径: {path}")
        if not path.exists():
            print("  跳过: 文件不存在")
            continue

        avg = _avg_peaks(path)
        st = top_peak_column_stats(path)
        print(f"  库大小: {st.get('db_size_mb', '?')} MB, 平均 {avg:.1f} 峰/相"
              if avg is not None else f"  库大小: {st.get('db_size_mb', '?')} MB")

        if st.get("available"):
            print(f"  预截断列: 已存在, 已填充 {st['filled']:,} / {st['phases']:,}"
                  f" (待补 {st['pending']:,})")
        else:
            print(f"  预截断列: 无 ({st.get('reason', '')})")

        if avg is not None and avg <= args.top_n * 1.05:
            print(f"  跳过: 平均 {avg:.1f} 峰/相 ≤ top-n {args.top_n}, "
                  "预截断省不下解析量, 只会白涨体积")
            continue

        if args.status:
            continue

        if st.get("available") and st.get("pending", 0) == 0:
            print("  已是最新, 无需迁移")
            continue

        def _progress(done: int, total: int) -> None:
            pct = done * 100 // max(total, 1)
            print(f"\r  填充中: {done:,}/{total:,} ({pct}%)", end="", flush=True)

        t0 = time.perf_counter()
        info = build_top_peak_columns(
            path, top_n=args.top_n,
            backup=not args.no_backup, vacuum=args.vacuum,
            progress=_progress,
        )
        print()
        print(f"  完成: 填充 {info['rows_filled']:,} 相, "
              f"新增列={info['added_columns']}, 耗时 {info['seconds']}s")
        if info["backup_path"]:
            print(f"  备份: {info['backup_path']}")
        print(f"  库大小: {st.get('db_size_mb', '?')} MB → {info['db_size_mb']} MB")
        print(f"  (总耗时 {time.perf_counter() - t0:.1f}s)")

    print("\n提示: 检索侧无需任何配置, 检测到列会自动启用; "
          "传入 max_ref_peaks > top-n 时自动回退全长解析。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
