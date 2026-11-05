#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动日志判读器（P0-1 配套，无 Qt 依赖）。

================================================================================
解决什么
================================================================================
现场那 15 次启动里 7 次 access violation（原生异常，Python 层无 traceback），
日志停在 ``showing main window``。v5.2 已加三段探针（``context`` / ``first-paint``
/ ``ui-tick0`` / ``settled``），但现场拿到日志后仍要靠人一条条对。

本工具把判定表固化下来，**一条命令给出每个 pid 卡在哪个阶段**，并按 context
变量（admin / remote_session / cif_db 存在可写 / opengl / qpa / dpi_scale）
交叉统计，用于回答 P0-1 §4-4 那两个问题：
  * 失败是否只出现在某种账号/环境组合下；
  * 某次"成功"是真好还是只是恰好没撞上。

================================================================================
用法
================================================================================
    python scripts/diagnose_startup_log.py <startup-*.log> [...]
    python scripts/diagnose_startup_log.py --json <log>     # 机读输出

判定表（自下而上 = 越靠近崩溃点越靠后）：

| 最后出现的行 | 判定阶段 | 该查什么 |
|---|---|---|
| （无） | 进程未进入 main / 更早 | 导入期、Python 环境 |
| context 但无 showing main window | 主窗口构造 | MainWindow 初始化、DB 挂载 |
| showing 但无 shown | **平台窗口创建** | qpa、DPI、远程桌面、显卡驱动 |
| shown 但无 ui-tick0 | 窗口映射/合成器 | DWM、双屏、缩放 |
| ui-tick0 但无 first-paint | **首帧绘制 / GL 上下文** | 渲染后端、着色器、子控件 |
| first-paint 但无 settled | 首帧后 50 ms 内 | 事件循环早期、异步初始化 |
| settled | 启动完成 | ——（若仍崩，问题在后续用户操作） |

注意：判定"失败"的判据是**同一 pid 未出现 settled 且日志到此为止**；工具本身
不猜进程是否还在跑（现场日志是事后取，pid 已不存在）。给 ``--alive-pid`` 可
显式排除仍在运行的进程。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: 探针里程碑（按时间顺序）
MILESTONES: Tuple[str, ...] = (
    "context",
    "showing main window",
    "shown",
    "ui-tick0",
    "first-paint",
    "settled",
)

_LINE_RE = re.compile(
    r"^\[(?P<ts>[\d\-: ]+)\]\s+\[pid=(?P<pid>\d+)\]\s+(?P<msg>.*)$")
_KV_RE = re.compile(r"(\w+)=('[^']*'|\"[^\"]*\"|\S+)")


@dataclass
class LaunchRecord:
    pid: int
    first_ts: str = ""
    last_ts: str = ""
    seen: List[str] = field(default_factory=list)   # 里程碑（按出现顺序）
    context: Dict[str, str] = field(default_factory=dict)
    lines: List[str] = field(default_factory=list)


def _parse_context(msg: str) -> Dict[str, str]:
    """``context: admin=True remote_session=False ...`` → dict。"""
    body = msg.split("context:", 1)[-1]
    return {k: v.strip("'\"") for k, v in _KV_RE.findall(body)}


def parse_log(text: str) -> List[LaunchRecord]:
    """按 pid 归并日志行，保留里程碑与 context。"""
    recs: Dict[int, LaunchRecord] = {}
    for raw in text.splitlines():
        m = _LINE_RE.match(raw.strip())
        if not m:
            continue
        pid = int(m.group("pid"))
        msg = m.group("msg").strip()
        rec = recs.setdefault(pid, LaunchRecord(pid=pid))
        rec.last_ts = m.group("ts")
        if not rec.first_ts:
            rec.first_ts = m.group("ts")
        rec.lines.append(msg)
        if msg.startswith("context:"):
            rec.context = _parse_context(msg)
            rec.seen.append("context")
            continue
        for ms in MILESTONES[1:]:
            if msg.startswith(ms):
                rec.seen.append(ms)
                break
    return list(recs.values())


def judge(rec: LaunchRecord, alive: bool = False) -> Tuple[str, str]:
    """返回 (判定阶段, 处置提示)。``alive=True`` 表示进程还在跑，不算失败。"""
    have = set(rec.seen)
    if "settled" in have:
        return "completed", "启动完成（问题若仍存在，在用户操作之后）"
    if alive:
        return "running", "进程仍在运行，暂不判定"
    if "first-paint" in have:
        return "after-first-paint", "首帧后 50 ms 内：查事件循环早期的异步初始化"
    if "ui-tick0" in have:
        return "first-paint", ("首帧绘制 / GL 上下文：查渲染后端、"
                               "子控件绘制、着色器")
    if "shown" in have:
        return "mapped", "窗口映射/合成器：查 DWM、双屏、缩放"
    if "showing main window" in have:
        return "show-call", ("**平台窗口创建**：查 Qt 平台插件(qpa)、DPI、"
                             "远程桌面、显卡驱动")
    if "context" in have:
        return "construct", "主窗口构造：查 MainWindow 初始化、DB 挂载"
    return "pre-context", "更早：导入期 / Python 环境 / 配置 mkdir"


#: 判定 → 中文阶段名（报告用）
STAGE_NAMES = {
    "completed": "启动完成",
    "running": "运行中",
    "after-first-paint": "首帧后 50 ms 内",
    "first-paint": "首帧绘制 / GL",
    "mapped": "窗口映射 / 合成器",
    "show-call": "平台窗口创建（show）",
    "construct": "主窗口构造",
    "pre-context": "context 之前",
}


def _ctx_key(ctx: Dict[str, str]) -> str:
    """context 的可比键（只取决定性的几项）。"""
    keys = ("admin", "remote_session", "exists", "writable", "qpa",
            "opengl", "dpi_scale")
    return " | ".join(f"{k}={ctx.get(k, '?')}" for k in keys)


def summarize(recs: List[LaunchRecord],
              alive_pids: Optional[set] = None) -> dict:
    alive_pids = alive_pids or set()
    rows = []
    by_stage: Dict[str, int] = {}
    by_ctx: Dict[str, Dict[str, int]] = {}
    for rec in recs:
        stage, hint = judge(rec, alive=rec.pid in alive_pids)
        rows.append({"pid": rec.pid, "stage": stage,
                     "stage_name": STAGE_NAMES.get(stage, stage),
                     "hint": hint, "context": rec.context,
                     "first_ts": rec.first_ts, "last_ts": rec.last_ts,
                     "milestones": list(rec.seen)})
        by_stage[stage] = by_stage.get(stage, 0) + 1
        if stage in ("completed", "running"):
            continue
        ck = _ctx_key(rec.context)
        bucket = by_ctx.setdefault(ck, {"fail": 0, "ok": 0})
        bucket["fail"] += 1
    # 成功计数（同一 context 键下）
    for rec in recs:
        stage, _ = judge(rec, alive=rec.pid in alive_pids)
        if stage == "completed":
            by_ctx.setdefault(_ctx_key(rec.context), {"fail": 0, "ok": 0})[
                "ok"] += 1
    total = len(recs)
    fails = sum(by_stage.get(s, 0) for s in STAGE_NAMES
                if s not in ("completed", "running"))
    return {
        "total_launches": total,
        "failures": fails,
        "by_stage": by_stage,
        "by_context": by_ctx,
        "rows": rows,
    }


def format_report(summary: dict) -> str:
    out = ["=" * 72, "PolyXRD 启动日志判读", "=" * 72,
           f"启动次数: {summary['total_launches']}    失败: {summary['failures']}"]
    if summary["by_stage"]:
        out.append("阶段分布:")
        for stage, n in sorted(summary["by_stage"].items(),
                               key=lambda kv: -kv[1]):
            out.append(f"  {STAGE_NAMES.get(stage, stage):<24} {n}")
    out.append("")
    out.append("逐次:")
    for r in summary["rows"]:
        out.append(f"  pid={r['pid']:<7} {r['stage_name']:<24} "
                   f"{r['first_ts']} → {r['last_ts']}")
        if r["stage"] not in ("completed", "running"):
            out.append(f"          ↳ {r['hint']}")
    if summary["by_context"]:
        out.append("")
        out.append("按环境分组（失败/成功）:")
        for ck, cnt in sorted(summary["by_context"].items(),
                              key=lambda kv: -kv[1]["fail"]):
            out.append(f"  [{cnt['fail']}F/{cnt['ok']}OK] {ck}")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PolyXRD 启动日志判读（P0-1 三段探针）")
    ap.add_argument("logs", nargs="+", help="startup-*.log 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--alive-pid", type=int, action="append", default=[],
                    help="仍在运行的 pid（不计为失败）")
    args = ap.parse_args(argv)

    text = ""
    for p in args.logs:
        path = Path(p)
        if not path.exists():
            print(f"日志不存在: {p}", file=sys.stderr)
            return 2
        text += path.read_text(encoding="utf-8", errors="replace") + "\n"
    recs = parse_log(text)
    if not recs:
        print("未解析到任何带 pid 的启动日志行", file=sys.stderr)
        return 1
    summary = summarize(recs, alive_pids=set(args.alive_pid))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_report(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
