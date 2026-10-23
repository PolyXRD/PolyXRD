#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.0.0 发布冒烟（离屏，可重复）：polyDB 挂载 → 体检 → 检索 → 精修 → 导出 → 项目存取。

为什么单独写一个"发布冒烟"而不是只跑 pytest：
  pytest 是分模块的单元/集成测试；发布验收要的是**整条用户链路**在**发布形态**
  的库上真跑通一遍。这里用真实 polyDB 库（COD-Inorg / COD-Full）走完整的
  MainViewModel 路径，任一步失败即退出码 1。

用法:
    python scripts/smoke_release_v400.py                       # 两个库都测
    python scripts/smoke_release_v400.py --skip-full           # 只测无机库（快）
    python scripts/smoke_release_v400.py --sample D:/x.txt --keep-workdir

说明:
  · 默认把「用户目录」重定向到临时目录（`USERPROFILE`/`HOME`），不会写真实
    ``~/.polyxrd``；`--keep-workdir` 可保留现场（含导出的 CSV）。
  · 全程 offscreen（`QT_QPA_PLATFORM=offscreen`），可在无桌面/CI 上跑。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_POLY_ROOT = ROOT.parent / "PolyXRD-DataBase" / "polydb"
DEFAULT_SAMPLE = Path(r"D:/Project/XRD/test_xrd/txt/4-1.txt")


def _fail(results: dict, step: str, detail: str) -> None:
    results["steps"].append({"step": step, "ok": False, "detail": detail})
    print(f"[FAIL] {step}: {detail}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poly-root", default=str(DEFAULT_POLY_ROOT))
    ap.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    ap.add_argument("--skip-full", action="store_true")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--keep-workdir", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    work = Path(args.workdir) if args.workdir else Path(
        tempfile.mkdtemp(prefix="polyxrd_smoke_"))
    home = work / "home"
    (home / ".polyxrd").mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(home)
    os.environ["HOME"] = str(home)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("POLYXRD_SAFE_RENDER", "1")

    results: dict = {"workdir": str(work), "steps": [], "timings": {}}
    t_start = time.perf_counter()

    def ok(step: str, detail: str = "") -> None:
        results["steps"].append({"step": step, "ok": True, "detail": detail})
        print(f"[ OK ] {step}" + (f": {detail}" if detail else ""), flush=True)

    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])  # noqa: F841 - 必须持有引用
        from polyxrd.services import db_mounts

        # 1) 挂载 polyDB（等价于 GUI「挂载文件夹…」一次挂两个库）
        poly_root = Path(args.poly_root)
        if not poly_root.is_dir():
            _fail(results, "mount", f"polyDB 根目录不存在: {poly_root}")
            return 1
        t0 = time.perf_counter()
        mounted = db_mounts.mount_any(poly_root)
        results["timings"]["mount_s"] = round(time.perf_counter() - t0, 2)
        names = [m.display_name() for m in mounted]
        if len([m for m in mounted if m.kind == "polydb"]) < 1:
            _fail(results, "mount", f"未挂载到 polyDB: {names}")
            return 1
        ok("mount", f"{len(mounted)} 个库: {names}")

        # 2) 体检（探测行数/体积/可用性）
        t0 = time.perf_counter()
        rows = db_mounts.probe_all()
        results["timings"]["probe_s"] = round(time.perf_counter() - t0, 2)
        poly_rows = [r for r in rows if r["kind"] == "polydb"]
        # 内置的 polyDB 槽位（polydb:cod-inorg / polydb:cod-full）在未配置时
        # 显示 unmounted 属正常；只要求"用户自己加进来的那几行"探测通过。
        custom = [r for r in poly_rows if not r["builtin"]]
        bad = [(r["id"], r.get("error")) for r in custom if not r["ok"]]
        if len(custom) < 1 or bad:
            _fail(results, "probe", f"自定义 polyDB 探测失败: bad={bad} rows={len(custom)}")
            return 1
        def _pick(word: str):
            for r in custom:
                if word.lower() in r["mount"].display_name().lower():
                    return r
            return None
        inorg = _pick("inorg")
        full = _pick("full")
        if inorg is None:
            _fail(results, "probe", f"没找到 COD-Inorg 库: {[r['mount'].display_name() for r in custom]}")
            return 1
        ok("probe", " · ".join(f"{r['mount'].display_name()}={r['rows']} 相/{r['size_mb']} MB"
                               for r in custom))

        # 3) 设为当前（列表式挂载的显式动作）
        db_mounts.set_active(inorg["id"])
        if db_mounts.active_id() != inorg["id"]:
            _fail(results, "set_active", "active id 未写入")
            return 1
        ok("set_active", inorg["id"])

        # 4) 外挂库管理对话框：离屏构建 + 填表，确保 UI 不崩、行数与探测一致
        from polyxrd.views.widgets.database_dialog import DatabaseManagerDialog

        dlg = DatabaseManagerDialog()
        dlg.reload()
        nrows = dlg._table.rowCount() if hasattr(dlg, "_table") else -1
        dlg.close()
        if nrows < len(rows):
            _fail(results, "dialog", f"表格行数 {nrows} < 探测行数 {len(rows)}")
        else:
            ok("dialog", f"{nrows} 行")

        # 5) 主链路：载入 → 寻峰 → polyDB 检索
        from polyxrd.viewmodels.main_vm import MainViewModel

        vm = MainViewModel()
        errors: list[str] = []
        vm.error_occurred.connect(lambda m: errors.append(str(m)))
        sample = Path(args.sample)
        if not sample.is_file():
            _fail(results, "load", f"试样不存在: {sample}")
            return 1
        vm.load_file(str(sample))
        vm.find_peaks()
        if not vm.peaks or not vm.peaks.peaks:
            _fail(results, "find_peaks", "未检出峰")
            return 1
        ok("find_peaks", f"{len(vm.peaks.peaks)} 个峰")

        t0 = time.perf_counter()
        vm.identify_phases(db_source=inorg["id"], top_n=10)
        dt = time.perf_counter() - t0
        results["timings"]["identify_inorg_s"] = round(dt, 2)
        matched = vm.matched_phases or []
        if not matched:
            _fail(results, "identify(inorg)", f"无候选 (errors={errors[:3]})")
            return 1
        top = matched[0]
        ok("identify(inorg)", f"{len(matched)} 候选 / top1={top.phase.name} / {dt:.2f}s")

        if full is not None and not args.skip_full:
            t0 = time.perf_counter()
            vm.identify_phases(db_source=full["id"], top_n=5)
            dt = time.perf_counter() - t0
            results["timings"]["identify_full_s"] = round(dt, 2)
            matched_full = vm.matched_phases or []
            if not matched_full:
                _fail(results, "identify(full)", f"无候选 (errors={errors[:3]})")
                return 1
            ok("identify(full)", f"{len(matched_full)} 候选 / top1={matched_full[0].phase.name} / {dt:.2f}s")

        # 6) 选中相 + 内置引擎精修（快速档）
        phase = (vm.matched_phases or [])[0].phase
        vm.select_phase(phase)
        t0 = time.perf_counter()
        vm.refine_structure(engine="builtin", strategy="sequential", max_cycles=3)
        dt = time.perf_counter() - t0
        results["timings"]["refine_s"] = round(dt, 2)
        res = vm.refinement_result
        if res is None or not getattr(res, "wR", 0):
            _fail(results, "refine", f"无精修结果 (errors={errors[:3]})")
            return 1
        ok("refine", f"wR={res.wR:.2f}% / Rexp={getattr(res, 'Rexp', 0):.2f} / {dt:.2f}s")

        # 7) 导出（CSV/JSON/TXT）
        out_dir = work / "export"
        t0 = time.perf_counter()
        vm.export_result(str(out_dir), format="all")
        dt = time.perf_counter() - t0
        results["timings"]["export_s"] = round(dt, 2)
        files = sorted(p.name for p in out_dir.glob("*")) if out_dir.is_dir() else []
        if not files:
            _fail(results, "export", f"未产出文件 (errors={errors[:3]})")
            return 1
        ok("export", ", ".join(files))

        # 8) 项目存取（.polyxrd 全序列化）
        proj = work / "smoke.polyxrd"
        vm.save_project(proj)
        from polyxrd.viewmodels.main_vm import MainViewModel as VM2

        vm2 = VM2()
        vm2.open_project(proj)
        if not (vm2.peaks and vm2.peaks.peaks):
            _fail(results, "project_roundtrip", "重开后峰丢失")
            return 1
        ok("project_roundtrip", f"{proj.name} / {len(vm2.peaks.peaks)} 峰 / "
                                f"{len(vm2.matched_phases or [])} 候选")

        return 0 if all(s["ok"] for s in results["steps"]) else 1
    except Exception as e:  # noqa: BLE001 - 冒烟脚本要把异常变成可读报告
        traceback.print_exc()
        _fail(results, "exception", f"{type(e).__name__}: {e}")
        return 1
    finally:
        results["elapsed_s"] = round(time.perf_counter() - t_start, 1)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        print("\n=== 冒烟汇总 ===")
        for s in results["steps"]:
            print(("  PASS " if s["ok"] else "  FAIL ") + s["step"] +
                  ((" — " + s["detail"]) if s["detail"] else ""))
        print("  用时: %ss" % results["elapsed_s"])
        if not args.keep_workdir and not args.workdir:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
