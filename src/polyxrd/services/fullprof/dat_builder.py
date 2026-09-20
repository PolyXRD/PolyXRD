"""FullProf .dat 数据文件生成 (v0.15 M25-5)
==========================================

写 FullProf free-format 计数文件 (与官方样例 ``Examples/ceo2.dat`` 同格式):

- 注释行以 ``!`` 开头, 数据区以单独一行 ``#`` 引导;
- 第一条数据行: ``2θmin  Step  2θmax`` (等步长);
- 之后每行最多 8 个强度计数 (FullProf 兼容实数)。

强度权重走 fp2k 默认 ``w = 1/σ²``, σ = sqrt(I+1) (variance model 0)。
文件名/目录由调用方保证全 ASCII (fp2k 对非 ASCII 路径敏感)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

__all__ = ["build_dat", "data_grid"]

_PER_ROW = 8  # 官方样例每行 8 个计数


def data_grid(data) -> tuple[float, float, float]:
    """从实验谱推导 (thmin, step, thmax), 供 dat/pcr 共用。"""
    tt = np.asarray(data.two_theta, dtype=float)
    ok = np.isfinite(tt)
    tt = tt[ok]
    if tt.size < 10:
        raise ValueError("数据点不足 (<10), 无法导出 FullProf .dat")
    tt = np.sort(tt)
    diffs = np.diff(tt)
    diffs = diffs[diffs > 0]
    step = float(np.median(diffs)) if diffs.size else 0.0
    if step <= 0:
        raise ValueError("2θ 无有效步长, 无法导出 FullProf .dat")
    return float(tt[0]), step, float(tt[-1])


def build_dat(
    data,
    out_path: str | Path,
    *,
    title: str = "PolyXRD observed data",
) -> Path:
    """把实验谱写成 FullProf 等步长计数 .dat, 返回落盘路径。

    非有限值剔除; 重复 2θ 取均值后排序。步长取相邻 2θ 差的中位数。
    """
    tt = np.asarray(data.two_theta, dtype=float)
    yy = np.asarray(data.intensity, dtype=float)
    ok = np.isfinite(tt) & np.isfinite(yy)
    tt, yy = tt[ok], yy[ok]
    if tt.size < 10:
        raise ValueError("数据点不足 (<10), 无法导出 FullProf .dat")

    order = np.argsort(tt)
    tt, yy = tt[order], yy[order]
    # 等步长数据允许少量重复/缺失: 去重取均值
    ut, inverse = np.unique(np.round(tt, 6), return_inverse=True)
    if ut.size != tt.size:
        sums = np.bincount(inverse, weights=yy)
        cnts = np.bincount(inverse)
        yy = sums / cnts
        tt = ut

    diffs = np.diff(tt)
    diffs = diffs[diffs > 0]
    step = float(np.median(diffs)) if diffs.size else 0.0
    if step <= 0:
        raise ValueError("2θ 无有效步长, 无法导出 FullProf .dat")

    wl = float(getattr(data, "wavelength", 1.5406))
    lines: list[str] = [
        "",
        f"! {title}",
        f"! Wavelength (Cu Ka1 assumed in PCR): {wl:.5f} A",
        f"! Points: {tt.size}   2Th range: {tt[0]:.4f} - {tt[-1]:.4f}",
        "#",
        f"{tt[0]:.4f} {step:.6f} {tt[-1]:.4f}",
    ]
    vals = [f"{v:.2f}" for v in np.clip(yy, 0.0, None)]
    for i in range(0, len(vals), _PER_ROW):
        lines.append(" " + "  ".join(vals[i:i + _PER_ROW]))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="ascii")
    return out
