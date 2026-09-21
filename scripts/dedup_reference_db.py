# -*- coding: utf-8 -*-
"""参考库同名条目去重 (v0.15.2)。

背景: xrd_reference_database.json 中存在 12 组同名重复 (旧手工条目 +
v0.15.2 重算条目并存)。旧条目部分晶胞压缩 (如 legacy ZnO a=3.22, 实测
3.2494), 峰位整体偏移 +0.3°, 拉低物相识别 FoM、污染强峰归属。

策略: 同名组内保留 peaks_version == 'v0.15.2-symmetry-expanded' 的条目;
全组都没有该标记时保留第一个。可选 --write 落盘, 否则只打印预览。

用法:
    venv/Scripts/python.exe scripts/dedup_reference_db.py          # 预览
    venv/Scripts/python.exe scripts/dedup_reference_db.py --write  # 落盘
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "src" / "polyxrd" / "resources" / "database" / "xrd_reference_database.json"
MARK = "v0.15.2-symmetry-expanded"


def main() -> int:
    write = "--write" in sys.argv
    data = json.loads(DB.read_text(encoding="utf-8"))
    phases = data.get("phases", [])

    groups: dict[str, list[dict]] = {}
    for p in phases:
        groups.setdefault(p.get("name") or p.get("key") or "?", []).append(p)

    keep: list[dict] = []
    dropped: list[tuple[str, str, str]] = []
    for name, items in groups.items():
        if len(items) == 1:
            keep.append(items[0])
            continue
        regen = [p for p in items if p.get("peaks_version") == MARK]
        best = regen[0] if regen else items[0]
        keep.append(best)
        for p in items:
            if p is not best:
                dropped.append((name, p.get("key") or "?",
                                p.get("peaks_source") or p.get("cif_source") or "?"))

    print(f"同名组 {sum(1 for v in groups.values() if len(v) > 1)} 组, "
          f"条目 {len(phases)} -> {len(keep)} (剔除 {len(dropped)})")
    for name, key, src in dropped:
        print(f"  - {name:<14} key={key:<18} src={src}")

    if write:
        bak = DB.with_suffix(".json.bak_dedup")
        shutil.copy2(DB, bak)
        data["phases"] = keep
        data["version"] = "0.5.1"
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        print(f"已写回 {DB} (版本 0.5.1, 备份 {bak.name})")
    else:
        print("(预览模式, 加 --write 落盘)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
