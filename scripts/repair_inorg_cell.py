"""修复 COD 无机物库 ``phases.cell_*`` 与内嵌 CIF 不一致的问题。

背景
----
建库脚本在写 ``cell_a`` / ``cell_b`` / ``cell_c`` / ``cell_alpha`` / ``cell_beta``
/ ``cell_gamma`` 时存在**数组错位**，导致相当一部分行落入了别的条目的晶胞值
（典型症状：9 位浮点垃圾 ``6.37e-314``、角度为 NULL、``a`` 恰好是真实值的 2 倍）。
实测：71,156 条有 CIF 的行里，**15,156 条 a 与 CIF 偏差 > 0.5%**。

**峰表不受影响**：``peaks_d`` / ``peaks_i`` 是用内嵌 CIF 生成的（立方行上
``max(d)/a_CIF == 1/sqrt(3)``，即 (111) 面），故 FoM / 排序 / 精修全部正确。
坏掉的只是**展示**（CIF 数据库列表、精修向导的候选晶胞摘要）。

做法
----
用**内嵌 CIF 的** ``_cell_length_*`` / ``_cell_angle_*`` 重写这 6 列。
CIF 是该库唯一自洽的晶胞来源（``_cod_database_code`` 与 ``cod_id`` 一致）。

守卫
----
1. 无 ``cif_gz`` → 跳过；
2. CIF 的 ``_cod_database_code`` 与 ``cod_id`` 不符 → 跳过（宁可留着不修）；
3. CIF 里读不到 ``_cell_length_a`` → 跳过；
4. 角度缺省按 CIF 语义取 90.0（与 ``cod_local.parse_cif_text`` 口径一致）。

幂等
----
第二次运行会报告「已一致」，不会重复改写。

用法
----
    python scripts/repair_inorg_cell.py            # 干跑（默认）
    python scripts/repair_inorg_cell.py --apply    # 实际改写（自动备份）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import math
import os
import shutil
import sqlite3
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from polyxrd.services.cod_local import (  # noqa: E402
    _extract_field,
    _cif_num,
)

_INORG_REL = os.path.join("cod_data", "COD_inorganics.sqlite")
# 相对容差 0.5%：与审计口径一致。低于此的差异在 3 位小数展示下不可见，
# 不做无谓改写（最小改动面原则）；NULL / 非有限值一律视为需修。
_TOL = 5e-3


def _finite(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _same(cur, new) -> bool:
    """当前值与 CIF 值是否已一致（两端都可能为 None）。"""
    c = _finite(cur)
    if new is None:
        # CIF 没给角度 → 视为 90.0；CIF 没给长度 → 不比较
        return True
    if c is None:
        return False
    if new != 0 and c != 0:
        return abs(c - new) / abs(new) <= _TOL
    return abs(c - new) <= _TOL


def cell_from_cif(txt: str) -> Optional[dict]:
    """从 CIF 文本取晶胞 6 参数；缺 a 视为不可用。"""
    a = _cif_num(_extract_field(txt, ("_cell_length_a",)))
    if a is None or not math.isfinite(a) or a <= 0:
        return None
    b = _cif_num(_extract_field(txt, ("_cell_length_b",))) or a
    c = _cif_num(_extract_field(txt, ("_cell_length_c",))) or a
    al = _cif_num(_extract_field(txt, ("_cell_angle_alpha",))) or 90.0
    be = _cif_num(_extract_field(txt, ("_cell_angle_beta",))) or 90.0
    ga = _cif_num(_extract_field(txt, ("_cell_angle_gamma",))) or 90.0
    return {"a": a, "b": b, "c": c, "alpha": al, "beta": be, "gamma": ga}


def main() -> int:
    ap = argparse.ArgumentParser(description="修复无机库 cell_* 列")
    ap.add_argument("--apply", action="store_true",
                    help="实际改写数据库（默认只干跑）")
    ap.add_argument("--dry-run", action="store_true",
                    help="干跑（这是默认行为，显式给出便于脚本化调用）")
    ap.add_argument("--db", default=os.path.join(_ROOT, _INORG_REL),
                    help="无机物库路径")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 行（调试）")
    args = ap.parse_args()
    args.apply = bool(args.apply and not args.dry_run)

    if not os.path.exists(args.db):
        print(f"[x] 找不到数据库: {args.db}")
        return 2

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.text_factory = str

    stats = {
        "total": 0, "no_cif": 0, "cif_bad": 0, "id_mismatch": 0,
        "cif_no_cell": 0, "ok": 0, "need_fix": 0,
        "fix_len": 0, "fix_ang": 0,
    }
    updates: list[tuple] = []
    samples: list[tuple] = []
    id_bad: list[int] = []

    sql = ("SELECT cod_id, cell_a, cell_b, cell_c, cell_alpha, cell_beta, "
           "cell_gamma, cif_gz FROM phases")
    for row in conn.execute(sql):
        if args.limit and stats["total"] >= args.limit:
            break
        stats["total"] += 1
        cid = int(row["cod_id"])
        blob = row["cif_gz"]
        if not blob:
            stats["no_cif"] += 1
            continue
        try:
            txt = gzip.decompress(blob).decode("utf-8", "replace")
        except Exception:
            stats["cif_bad"] += 1
            continue

        # 守卫 2: CIF 归属校验
        code = (_extract_field(txt, ("_cod_database_code",)) or "").strip()
        if code and code.isdigit() and int(code) != cid:
            stats["id_mismatch"] += 1
            if len(id_bad) < 5:
                id_bad.append((cid, int(code)))
            continue

        new = cell_from_cif(txt)
        if new is None:
            stats["cif_no_cell"] += 1
            continue

        cur = (row["cell_a"], row["cell_b"], row["cell_c"],
               row["cell_alpha"], row["cell_beta"], row["cell_gamma"])
        vals = (new["a"], new["b"], new["c"], new["alpha"], new["beta"], new["gamma"])
        bad_len = not all(_same(c, v) for c, v in zip(cur[:3], vals[:3]))
        bad_ang = not all(_same(c, v) for c, v in zip(cur[3:], vals[3:]))
        if not bad_len and not bad_ang:
            stats["ok"] += 1
            continue

        stats["need_fix"] += 1
        stats["fix_len"] += int(bad_len)
        stats["fix_ang"] += int(bad_ang)
        updates.append((vals[0], vals[1], vals[2], vals[3], vals[4], vals[5], cid))
        if len(samples) < 15:
            samples.append((cid, cur, vals))

    print("=" * 78)
    print("无机库 cell_* 与内嵌 CIF 一致性修复" + ("  [APPLY]" if args.apply else "  [DRY-RUN]"))
    print("=" * 78)
    for k in ("total", "no_cif", "cif_bad", "id_mismatch", "cif_no_cell",
              "ok", "need_fix", "fix_len", "fix_ang"):
        print(f"  {k:<16} {stats[k]:>7d}")
    if id_bad:
        print(f"  归属不符抽样: {id_bad}")
    if samples:
        print("\n抽样 (cod | 现有 a/b/c | CIF a/b/c):")
        for cid, cur, new in samples:
            print(f"  {cid} | {cur[0]} / {cur[1]} / {cur[2]}")
            print(f"  {'':9s} | {new[0]} / {new[1]} / {new[2]}")

    if not args.apply:
        print("\n干跑结束，未改动数据库。确认无误后加 --apply。")
        conn.close()
        return 0

    if not updates:
        print("\n无需改写，数据库已是最新。")
        conn.close()
        return 0

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{args.db}.bak_cell_{stamp}"
    print(f"\n备份 → {bak}")
    conn.close()
    shutil.copy2(args.db, bak)

    conn = sqlite3.connect(args.db)
    try:
        conn.executemany(
            "UPDATE phases SET cell_a=?, cell_b=?, cell_c=?, cell_alpha=?, "
            "cell_beta=?, cell_gamma=? WHERE cod_id=?", updates)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, "
                         "value TEXT)")
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                         ("cell_fix",
                          f"{_dt.datetime.now():%Y-%m-%d %H:%M:%S} "
                          f"count={len(updates)} src=_cell_length_*"))
        except sqlite3.Error as e:
            print(f"  [warn] 写 meta 失败: {e}")
        conn.commit()
        print(f"已改写 {len(updates)} 行。")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
