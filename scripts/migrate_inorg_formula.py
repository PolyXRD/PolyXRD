#!/usr/bin/env python
"""修复 COD 无机物库 ``phases.formula`` 被空间群符号覆盖的问题 (幂等)。

背景
----
COD 无机物库 (`COD_inorganics.sqlite`) 的 ``phases.formula`` 列在部分条目上
被写成了**空间群符号** (如 ``P 63 m c``) 而不是化学式 (如 ``O Zn``)。实测
71,199 条里有 605 条 ``formula == space_group``, 且其中 608/609 的 ``cif_gz``
里明明存着正确的 ``_chemical_formula_sum`` —— 是建库脚本的字段提取 bug, 不是
数据缺失。

后果 (实测于试样 3-1, ZnO 93.59%):
  * 识别结果里 Zincite 的名字/化学式显示成 "P 63 m c", 看不出是 ZnO;
  * ``elements_from_db_formula("P 63 m c")`` 解析出 **{'P'}** (被当成磷),
    而该元素集被下推到 ``search_cod_by_d_peaks`` 的扫描层做 ``issubset`` 判定
    → 一勾 Zn/O 元素过滤, 真 ZnO 在扫描层就被丢掉 (候选 40 → 2)。

修复范围 (保守)
--------------
**只改「可无歧义判定为错」的条目**, 即 ``formula`` 满足以下任一:
  ① 与 ``space_group`` 完全相同; ② 解析不出任何元素。

**刻意不动** 元素集与内嵌 CIF 不一致但库存值本身合法的条目 (实测 1,295 条):
那里混着两类情况 —— COD 自身的元数据错配 (如 cod 1001092 库存 ``Al0.37 Ca2
Fe1.63 O5`` 而 CIF 是 ``H2 O7 Pb2 Sn2``, 换掉会把对的改错), 以及 CIF 漏写
同位素 D (如 1000155 库存 ``D7 La Ni5`` vs CIF ``La Ni5``, 库存值更完整)。
只按 CIF 覆盖会净损失, 故不处理, 仅在报告里列出。

护栏
----
新化学式必须同时通过:
  * 能解析出非空元素集, 且不等于空间群符号;
  * CIF 内 ``_cod_database_code`` (若有) 与 cod_id 一致 (防 CIF/记录错配);
  * 该相在 ``cod_atomic_sites`` 里有位点时, 位点元素集 ⊆ 新化学式元素集
    (化学式不得漏掉 CIF 里确实存在的原子)。

用法
----
    python scripts/migrate_inorg_formula.py --dry-run        # 只看报告 (默认)
    python scripts/migrate_inorg_formula.py --apply          # 备份后写入
    python scripts/migrate_inorg_formula.py --apply --db <path>

写入前默认整库备份为 ``<db>.bak_formula_YYYYMMDD_HHMMSS``。脚本幂等:
第二次运行 ``--apply`` 的改动数应为 0。
"""

from __future__ import annotations

import argparse
import collections
import gzip
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

from polyxrd.services.cod_local import (  # noqa: E402
    _clean_elem_symbol,
    _extract_field,
    formula_sum_from_cif,
    is_db_formula_trusted,
)
from polyxrd.utils.formula_parser import elements_from_db_formula  # noqa: E402

DEFAULT_DB = _ROOT / "cod_data" / "COD_inorganics.sqlite"


def _cif_text(blob) -> str:
    try:
        return gzip.decompress(blob).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - 少数二进制/非 gzip 残留
        try:
            return blob.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return ""


def _site_elements(conn: sqlite3.Connection, cod_id: int) -> set[str]:
    """该相的原子位点元素集 (去电荷后缀: 'O-2'→'O', 'Zn+2'→'Zn')。"""
    try:
        return {
            _clean_elem_symbol(r[0])
            for r in conn.execute(
                "SELECT DISTINCT element FROM cod_atomic_sites WHERE cod_id = ?",
                (cod_id,),
            )
            if r[0]
        }
    except sqlite3.Error:
        return set()


def _untrusted_reason(stored: str, sg: str) -> str:
    """不可信的**可读原因** (仅用于报告)。

    判定本身走 `cod_local.is_db_formula_trusted` (单点实现), 这里只把原因
    分类出来方便看报告; 两者口径必须一致。
    """
    s = (stored or "").strip()
    if not s:
        return "formula 为空"
    if sg and s == (sg or "").strip():
        return "formula == space_group"
    if not elements_from_db_formula(s):
        return "formula 解析不出元素"
    return ""


def audit(db: Path, *, verbose: bool = True) -> dict:
    """扫描全库, 返回 {cod_id: (stored, sg, new_formula|None, reason/skip)}。"""
    conn = sqlite3.connect(str(db))
    conn.text_factory = str
    conn.row_factory = sqlite3.Row

    plan: dict[int, tuple[str, str, str | None, str]] = {}
    stats = collections.Counter()
    samples: dict[str, list] = collections.defaultdict(list)

    for row in conn.execute(
        "SELECT cod_id, formula, space_group, cif_gz FROM phases"
    ):
        cid = int(row["cod_id"])
        stored = row["formula"] or ""
        sg = row["space_group"] or ""
        trusted = is_db_formula_trusted(stored, sg)
        reason = "" if trusted else _untrusted_reason(stored, sg)
        stats[reason or "trusted"] += 1
        if trusted:
            continue

        blob = row["cif_gz"]
        if not blob:
            plan[cid] = (stored, sg, None, "无内嵌 CIF, 跳过")
            stats["skip_no_cif"] += 1
            continue

        txt = _cif_text(blob)
        new = formula_sum_from_cif(txt)
        if not new:
            plan[cid] = (stored, sg, None, "CIF 抽不出有效化学式, 跳过")
            stats["skip_cif_bad"] += 1
            continue
        if new == sg.strip():
            plan[cid] = (stored, sg, None, "CIF 化学式与空间群相同, 跳过")
            stats["skip_cif_is_sg"] += 1
            continue

        # 护栏 1: CIF 内 _cod_database_code 必须与本条一致
        code = _extract_field(txt, ("_cod_database_code",))
        if code:
            digits = "".join(ch for ch in code if ch.isdigit())
            if digits and int(digits) != cid:
                plan[cid] = (
                    stored, sg, None,
                    f"CIF 内 _cod_database_code={digits} 与 cod_id 不符, 跳过",
                )
                stats["skip_code_mismatch"] += 1
                continue

        # 护栏 2: 原子位点元素集必须被新化学式覆盖
        sites = _site_elements(conn, cid)
        new_els = elements_from_db_formula(new)
        if sites and not sites.issubset(new_els):
            plan[cid] = (
                stored, sg, None,
                f"CIF 位点元素 {sorted(sites)} 不被 {sorted(new_els)} 覆盖, 跳过",
            )
            stats["skip_site_mismatch"] += 1
            continue

        plan[cid] = (stored, sg, new, "OK")
        stats["change"] += 1
        if len(samples["OK"]) < 12:
            samples["OK"].append((cid, stored, new, sg, sorted(sites)))

    conn.close()

    if verbose:
        print("=" * 78)
        print("库:", db)
        print("=" * 78)
        order = [
            "trusted", "change",
            "skip_no_cif", "skip_cif_bad", "skip_cif_is_sg",
            "skip_code_mismatch", "skip_site_mismatch",
            "formula == space_group", "formula 为空",
            "formula 解析不出元素",
        ]
        label = {
            "trusted": "formula 可信, 不动",
            "change": "**将改写**",
            "skip_no_cif": "不可信但无 CIF, 跳过",
            "skip_cif_bad": "不可信但 CIF 无有效化学式, 跳过",
            "skip_cif_is_sg": "CIF 化学式亦为空间群记号, 跳过",
            "skip_code_mismatch": "CIF 记录号不符, 跳过",
            "skip_site_mismatch": "CIF 位点元素不被覆盖, 跳过",
            "formula == space_group": "[不可信原因] formula == space_group",
            "formula 为空": "[不可信原因] formula 为空",
            "formula 解析不出元素": "[不可信原因] formula 解析不出元素",
        }
        for k in order:
            if stats.get(k):
                print("  %-38s %6d" % (label[k], stats[k]))
        rest = {k: v for k, v in stats.items() if k not in order}
        for k, v in sorted(rest.items()):
            print("  %-38s %6d" % (k, v))
        # "不可信原因"三行只是分类信息, 已包含在 trusted/change/skip_* 里,
        # 不计入合计 (每条记录只算一次)。
        total = sum(
            v for k, v in stats.items() if not k.startswith("formula ")
        )
        print("  %-38s %6d" % ("合计 (相数)", total))

        if samples["OK"]:
            print()
            print("=" * 78)
            print("将改写样例")
            print("=" * 78)
            for cid, stored, new, sg, sites in samples["OK"]:
                print("  cod=%-9s %-22r → %-22r  SG=%-12r sites=%s"
                      % (cid, stored, new, sg, sites))

        skipped = [(c, v) for c, v in plan.items() if v[2] is None]
        if skipped:
            print()
            print("=" * 78)
            print("跳过样例 (最多 12)")
            print("=" * 78)
            for cid, (stored, sg, _n, why) in skipped[:12]:
                print("  cod=%-9s %-22r SG=%-14r %s" % (cid, stored, sg, why))

    return {"stats": stats, "plan": plan}


def apply(db: Path, plan: dict) -> int:
    changes = [(cid, v[2]) for cid, v in plan.items() if v[2] is not None]
    if not changes:
        print("没有需要改写的条目 (已是最新)。")
        return 0

    bak = db.with_name(
        db.name + ".bak_formula_" + time.strftime("%Y%m%d_%H%M%S")
    )
    print("备份:", bak)
    shutil.copy2(db, bak)
    if bak.stat().st_size != db.stat().st_size:
        raise SystemExit("备份大小不符, 中止")

    conn = sqlite3.connect(str(db))
    try:
        conn.executemany(
            "UPDATE phases SET formula = ? WHERE cod_id = ?",
            [(new, cid) for cid, new in changes],
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("formula_fix",
             "%s count=%d src=_chemical_formula_sum"
             % (time.strftime("%Y-%m-%d %H:%M:%S"), len(changes))),
        )
        conn.commit()
    finally:
        conn.close()
    print("已改写 %d 条。" % len(changes))
    return len(changes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--apply", action="store_true",
                    help="真正写入 (默认只做 dry-run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只看报告, 不写入 (默认行为, 显式给出便于阅读)")
    ap.add_argument("--no-backup", action="store_true",
                    help="写入时不备份 (不建议)")
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print("找不到库:", db)
        return 2

    res = audit(db, verbose=True)
    stats = res["stats"]
    if not args.apply:
        print()
        print("这是 dry-run。加 --apply 才会写入。")
        return 0

    if args.no_backup:
        changes = [(cid, v[2]) for cid, v in res["plan"].items() if v[2]]
        conn = sqlite3.connect(str(db))
        try:
            conn.executemany("UPDATE phases SET formula=? WHERE cod_id=?",
                             [(n, c) for c, n in changes])
            conn.commit()
        finally:
            conn.close()
        print("已改写 %d 条 (未备份)。" % len(changes))
    else:
        apply(db, res["plan"])

    print()
    print("=" * 78)
    print("复核 (再跑一次审计, 应无 change)")
    print("=" * 78)
    res2 = audit(db, verbose=False)
    print("  formula==space_group 遗留 =", res2["stats"].get("skip_cif_bad", 0)
          + res2["stats"].get("skip_cif_is_sg", 0)
          + res2["stats"].get("skip_code_mismatch", 0)
          + res2["stats"].get("skip_site_mismatch", 0)
          + res2["stats"].get("skip_no_cif", 0))
    print("  可改写 (应 0)              =", res2["stats"].get("change", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
