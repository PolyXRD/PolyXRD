"""
脚本自动化 / 批处理 (M19, Sprint 3)
===================================
把服务层串成可复用管线:
  - apply_steps: 按步骤名顺序处理一条谱 (smooth/strip_kalpha2/background/
    trim 等), 返回处理后的 XRDData
  - process_files: 批量处理多文件 → 统一输出峰检测汇总 (可写 CSV)
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Optional, Union

import numpy as np

from polyxrd.models.peak import PeakList
from polyxrd.models.xrd_data import XRDData

_KNOWN_STEPS = ("smooth", "strip_kalpha2", "background", "trim",
                "increase_resolution")


def apply_steps(xrd: XRDData, steps: Iterable[tuple]) -> XRDData:
    """按步骤管线处理谱。

    steps: [(step_name, kwargs), ...]
      smooth("window","polyorder","reps")          → RawProcessing
      strip_kalpha2("wavelength1","wavelength2")   → Rachinger 去 Kα2
      background("method","iterations")            → 估计并扣除
      trim("t_min","t_max")
      increase_resolution("factor")
    """
    from polyxrd.services.background import BackgroundEstimator
    from polyxrd.services.raw_processing import RawProcessing

    out = xrd
    for name, kw in steps:
        kw = dict(kw or {})
        if name == "smooth":
            out = RawProcessing.smooth_savitzky_golay(
                out, window=int(kw.get("window", 9)),
                polyorder=int(kw.get("polyorder", 3)),
                reps=int(kw.get("reps", 1)))
        elif name == "strip_kalpha2":
            out = RawProcessing.strip_kalpha2(
                out, wavelength1=float(kw.get("wavelength1", 1.5406)),
                wavelength2=float(kw.get("wavelength2", 1.5444)),
                ratio=float(kw.get("ratio", 2.0)))
        elif name == "background":
            bg = BackgroundEstimator.estimate_background(
                out, method=kw.get("method", "snip"),
                iterations=int(kw.get("iterations", 30)))
            out = BackgroundEstimator.subtract_background(out, bg)
        elif name == "trim":
            out = RawProcessing.trim(
                out, float(kw["t_min"]), float(kw["t_max"]))
        elif name == "increase_resolution":
            out = RawProcessing.increase_resolution(
                out, factor=int(kw.get("factor", 2)))
        else:
            raise ValueError(f"未知步骤: {name} (可选 {_KNOWN_STEPS})")
    return out


def process_files(
    paths: Iterable[Union[str, Path]],
    steps: Optional[Iterable[tuple]] = None,
    peak_options: Optional[dict] = None,
    summary_csv: Optional[Union[str, Path]] = None,
) -> list[dict]:
    """批量加载→管线→峰检测, 输出逐文件摘要。

    Returns: [{"source", "points", "two_theta_range", "n_peaks",
               "peaks": PeakList}, ...]
    """
    from polyxrd.services.data_io import load_auto
    from polyxrd.services.peak_finder import PeakFinder

    results = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        data = load_auto(p)
        if steps:
            data = apply_steps(data, steps)
        pf = PeakFinder()
        peaks = pf.find_peaks(data, **(peak_options or {}))
        results.append({
            "source": str(p),
            "points": len(data),
            "two_theta_range": f"{float(data.two_theta[0]):.2f}-"
                               f"{float(data.two_theta[-1]):.2f}",
            "n_peaks": len(peaks),
            "peaks": peaks,
        })
    if summary_csv:
        _write_summary(results, Path(summary_csv))
    return results


def _write_summary(results: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "points", "two_theta_range", "n_peaks",
                    "peak_positions"])
        for r in results:
            pos = ";".join(f"{p.two_theta:.2f}" for p in r["peaks"].peaks)
            w.writerow([r["source"], r["points"], r["two_theta_range"],
                        r["n_peaks"], pos])
