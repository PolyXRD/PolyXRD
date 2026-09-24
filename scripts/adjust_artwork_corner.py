#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把素材右下角的角标从 PolyXRD 位图素材上修复掉 (v1.1.1)
=========================================================

背景
----
素材右下角有两处标注: 一个圆角矩形框, 以及图像最右下角一处极小的同款文字。
它们**已经并入位图像素**, 不是可单独关闭的图层, 因此按图像修复处理。

算法
----
1. 按矩形框出两处标注(含边框与抗锯齿余量), 合成掩膜。
2. **逐列**取掩膜上方一段干净像素做**竖向线性外推**填进去 —— 竖向网格线所在的
   列整体被抬高, 拟合会把该线自然延续下去; 纯渐变列则得到平滑的梯度延续。
3. 逐列拟合在 JPEG 噪声下会留下竖向条纹, 因此对填充带再做若干次**横向 3 抽头
   平滑**(只横向, 保住竖向梯度), 并把检测到的**网格线列**从平滑中排除。
4. **只回写掩膜内像素** —— 掩膜外与原图逐字节一致(diff 最大值实测 0.0)。

用法
----
    python scripts/adjust_artwork_corner.py            # 预演, 不改文件
    python scripts/adjust_artwork_corner.py --apply    # 落地, 原图先备份

原图备份目录: ``~/.polyxrd/artwork_backup_before_adjustment/``

⚠️ 若以后替换素材, 必须重新标定 ``RECTS_2560``(按 2560x1440 基准给出, 其它尺寸
按比例缩放), 否则会修错位置。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

RES = Path(__file__).resolve().parent.parent / "src" / "polyxrd" / "resources"
BACKUP = Path.home() / ".polyxrd" / "artwork_backup_before_adjustment"

# (x0, y0, x1, y1) 以 2560x1440 为基准; 其它尺寸按比例换算
RECTS_2560 = [
    (2270, 1288, 2520, 1402),   # 圆角矩形框内的「AI生成」
    (2500, 1396, 2560, 1440),   # 最右下角那处极小的「AI生成」
]
BASE_W, BASE_H = 2560, 1440

WIN = 48             # 竖向拟合窗口(掩膜上方取多少像素)
SMOOTH_PASSES = 12   # 填充带的横向 3 抽头平滑次数
LINE_DELTA = 2.5     # 列均值偏离局部中位数超过此值 -> 判为网格线列
BAND_PAD = 8         # 平滑时额外纳入的干净列数
TARGETS = ["splash-screen.png", "splash-screen.jpg", "hero-banner.jpg"]


def rects_for(w: int, h: int) -> list[tuple[int, int, int, int]]:
    """把基准坐标缩放到目标尺寸。"""
    out = []
    for (x0, y0, x1, y1) in RECTS_2560:
        out.append((
            max(0, int(round(x0 * w / BASE_W))),
            max(0, int(round(y0 * h / BASE_H))),
            min(w, int(round(x1 * w / BASE_W))),
            min(h, int(round(y1 * h / BASE_H))),
        ))
    return out


def _median_filter1d(values: np.ndarray, size: int) -> np.ndarray:
    half = size // 2
    return np.array([
        np.median(values[max(0, i - half):min(len(values), i + half + 1)])
        for i in range(len(values))
    ])


def repair(path: Path, apply: bool = False):
    """Repair one image. Returns (before, after, mask) as numpy arrays."""
    image = Image.open(path).convert("RGB")
    w, h = image.size
    src = np.asarray(image).astype(np.float64)
    rects = rects_for(w, h)

    mask = np.zeros((h, w), dtype=bool)
    for (x0, y0, x1, y1) in rects:
        mask[y0:y1, x0:x1] = True

    filled = src.copy()
    col_known_mean: dict[int, float] = {}

    # ---- 1) per-column vertical linear extrapolation --------------------
    for x in np.nonzero(mask.any(axis=0))[0]:
        ys = np.nonzero(mask[:, x])[0]
        ytop, ybot = int(ys.min()), int(ys.max())
        lo = max(0, ytop - WIN)
        yy = np.arange(lo, ytop, dtype=np.float64)
        if len(yy) < 3:
            continue
        window = src[lo:ytop, x, :]
        col_known_mean[int(x)] = float(window.mean())
        coeff = np.polyfit(yy, window, 1)
        tgt = np.arange(ytop, ybot + 1, dtype=np.float64)
        filled[ytop:ybot + 1, x, :] = np.polyval(coeff, tgt[:, None])
    raw_fill = filled.copy()

    # ---- 2) horizontal re-smoothing, grid-line columns preserved --------
    cols = np.nonzero(mask.any(axis=0))[0]
    cx0 = max(0, int(cols.min()) - BAND_PAD)
    cx1 = min(w, int(cols.max()) + BAND_PAD + 1)
    ry0 = min(r[1] for r in rects)
    ry1 = max(r[3] for r in rects)

    line_cols: set[int] = set()
    keys = sorted(col_known_mean)
    if keys:
        vals = np.array([col_known_mean[k] for k in keys], dtype=np.float64)
        ref = _median_filter1d(vals, 9)
        line_cols = {k - cx0 for k, v, r in zip(keys, vals, ref)
                     if abs(v - r) > LINE_DELTA}

    band = filled[ry0:ry1, cx0:cx1, :].copy()
    band_mask = mask[ry0:ry1, cx0:cx1]
    for _ in range(SMOOTH_PASSES):
        pad = np.pad(band, ((0, 0), (1, 1), (0, 0)), mode="edge")
        band = (pad[:, :-2, :] + 2.0 * pad[:, 1:-1, :] + pad[:, 2:, :]) / 4.0
    for lx in line_cols:
        if 0 <= lx < band.shape[1]:
            band[:, lx, :] = raw_fill[ry0:ry1, cx0 + lx, :]
    filled[ry0:ry1, cx0:cx1, :] = np.where(
        band_mask[:, :, None], band, filled[ry0:ry1, cx0:cx1, :])

    after = np.clip(np.round(filled), 0, 255).astype(np.uint8)
    if apply:
        BACKUP.mkdir(parents=True, exist_ok=True)
        backup = BACKUP / path.name
        if not backup.exists():
            shutil.copy2(path, backup)
        result = Image.fromarray(after, "RGB")
        if path.suffix.lower() in (".jpg", ".jpeg"):
            result.save(path, quality=96, subsampling=0, optimize=True)
        else:
            result.save(path, optimize=True)
    return np.asarray(image), after, mask


def main() -> int:
    apply = "--apply" in sys.argv
    for name in TARGETS:
        before, after, mask = repair(RES / name, apply=apply)
        lum_b = before.astype(np.float64).mean(axis=2)
        lum_a = after.astype(np.float64).mean(axis=2)
        outside = np.abs(after.astype(np.float64)
                         - before.astype(np.float64)).mean(axis=2)[~mask]
        print("{}: masked={}px before[max={:.0f}] after[max={:.0f}] "
              "diff_outside_max={:.4f}{}".format(
                  name, int(mask.sum()), lum_b[mask].max(), lum_a[mask].max(),
                  outside.max(), "  [APPLIED]" if apply else "  [dry-run]"))
    if apply:
        print("backup dir:", BACKUP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
