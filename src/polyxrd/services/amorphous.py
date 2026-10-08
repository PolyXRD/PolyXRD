# -*- coding: utf-8 -*-
"""非晶/近非晶谱图诊断 (P2-2)。

背景: 近非晶样品 (淀粉、高聚物、炭原丝、含玻璃相混合物) 不出尖锐 Bragg 峰,
只有宽弥散包络。此前这类样品被强行做结晶相匹配, 必然 MISS, 既误导用户,
也让召回统计把"物理上无解"记成算法失败。

## 设计原则 (重要, 勿改坏)

本模块**只用"解释匹配失败", 绝不用于抢先判定/抑制匹配**。原因是在真实语料上
标定了 6 版判据, 没有任何单一指标能干净分离:

  - 结晶分量占比(按 FWHM 开窗)  : 淀粉 1.0 vs Cu-007 0.646  → 反了
  - 固定窗(2°)局部超出占比     : SILICA 0.054 ≈ 淀粉 0.026  (密集谱被滑动均值跟掉)
  - 相对基线超出比             : SILICA 0.038、NCM811 0.094 仍落在非晶区间
  - 中位 FWHM                 : 淀粉涟漪 0.04° = SILICA 0.04° (相对 prominence 测, 无区分度)
  - 动态范围 / 窄窗集中度      : SILICA(结晶) 8.1 < Poly(非晶) 16.2; NCM811 20.1 < data024 26.1

根因是真实世界的两类干扰: **低对比度结晶谱** (石英标准样峰弱、NCM811 背景巨大)
看起来很"弥散"; 而部分聚合物的宽极大看起来像峰。因此:

  **判定 = 谱图弥散(指标) AND 未获可接受匹配(外部传入的 top_match)**
  两个条件同时成立才标近非晶。这样 SILICA / NCM811 因有良好匹配被 veto 掉,
  而 STARCH / Poly / 炭原丝 被正确标出。

## 指标 (均为纯数据计算, 不依赖峰检测, 也不依赖峰宽)

  - ``sharp_content``      : 超出 2° 局部均值的净强度占比 (尖锐度)
  - ``dynamic_range``      : max/正值中位数 动态范围 (峰 vs 本底对比度)
      —— 本底必须取**正值**中位数: 计数型谱 (Cu-007 等) 零值可占多数,
         全谱 median=0 会让动态范围塌成 0 → 把结晶谱误判成非晶。
  - ``narrow_concentration``: 最强 15 个局部极大 ±0.15° 内的净面积占比
  - ``broad_hump`` / ``hump_rel``: 弥散包络峰位与相对强度

用法::

    from polyxrd.services.amorphous import assess_amorphous
    info = assess_amorphous(data, top_match=results[0] if results else None)
    info["level"]  # 'crystalline' | 'partially_amorphous' | 'amorphous'
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# ── 阈值 (真实语料标定, 见 .workbuddy/tmp/calibrate_amorphous.py) ──
_DIFFUSE_DYNAMIC_RANGE = 30.0   # 动态范围 <30 → 谱图偏弥散
_DIFFUSE_SHARP_CONTENT = 0.15   # 或 尖锐度 <0.15 → 谱图偏弥散
_ACCEPTABLE_CONFIDENCE = ("极好匹配", "良好匹配", "一般匹配")  # top_match 达此即视为"有匹配"

LEVEL_AMORPHOUS = "amorphous"
LEVEL_PARTIAL = "partially_amorphous"
LEVEL_CRYSTALLINE = "crystalline"

_HUMP_WINDOW_DEG = 2.0
_NARROW_HALF_DEG = 0.15
_TOP_PEAKS = 15


def _moving_average(y: np.ndarray, width: int) -> np.ndarray:
    if width <= 1:
        return np.asarray(y, dtype=float)
    k = np.ones(int(width)) / float(width)
    return np.convolve(np.asarray(y, dtype=float), k, mode="same")


def assess_amorphous(
    data,
    peaks=None,
    top_match=None,
    hump_window_deg: float = _HUMP_WINDOW_DEG,
) -> dict:
    """评估谱图的非晶程度, 供"解释匹配失败"使用 (不用于抢先抑制匹配)。

    Args:
        data: XRDData (需 ``two_theta`` / ``intensity``)
        peaks: 可选, 仅用于统计峰数 (不参与判定)
        top_match: 可选 PhaseMatchResult, 检索的最佳匹配; 若其置信度可接受,
            则 veto 掉非晶判定 (有可辨结晶相就不标非晶)
        hump_window_deg: 弥散包络平滑窗宽 (度)

    Returns:
        dict, 含 ``level`` / 各指标 / ``note``
    """
    tt = np.asarray(getattr(data, "two_theta", []), dtype=float)
    ii = np.asarray(getattr(data, "intensity", []), dtype=float)
    n_peaks = len(getattr(peaks, "peaks", []) or [])
    if tt.size < 8 or ii.size < 8:
        return _result(LEVEL_CRYSTALLINE, False, 0.0, 0.0, 0.0, n_peaks, None, None,
                       "数据点过少 (<8), 无法评估非晶度")

    step = float(np.median(np.diff(tt))) if tt.size > 1 else 1.0
    ii = np.clip(ii, 0.0, None)
    if float(ii.max()) <= 0:
        return _result(LEVEL_CRYSTALLINE, False, 0.0, 0.0, 0.0, n_peaks, None, None,
                       "数据全为零/负值, 无法评估非晶度")

    # ── 局部均值作基线 (宽窗跟随弥散包络, 不跟随窄峰) ──
    w = max(2, int(round(hump_window_deg / max(step, 1e-6))))
    smooth = _moving_average(ii, w)
    net = np.clip(ii - smooth, 0.0, None)
    net_total = float(np.sum(net))
    base_sum = float(np.sum(smooth))

    sharp_content = float(net_total / base_sum) if base_sum > 0 else 0.0
    # 本底取"正值中位数"而非全谱中位数: 计数型谱 (Cu-007 等) 零值可占多数,
    # 全谱 median=0 会把动态范围算成 0 → 误判为非晶。正值中位数必 >0。
    pos = ii[ii > 0]
    med = float(np.median(pos)) if pos.size else 0.0
    dynamic_range = float(ii.max() / med) if med > 0 else 0.0

    # ── 窄窗集中度: 最强若干局部极大 ±0.15° 内的净面积占比 ──
    narrow = 0.0
    idx_local = _local_maxima(ii, step)
    for i in idx_local[:_TOP_PEAKS]:
        m = (tt >= tt[i] - _NARROW_HALF_DEG) & (tt <= tt[i] + _NARROW_HALF_DEG)
        narrow += float(np.sum(net[m]))
    narrow_conc = float(narrow / net_total) if net_total > 0 else 0.0

    # ── 弥散包络 ──
    hi = int(np.argmax(smooth))
    hump = float(tt[hi])
    hump_rel = float(smooth[hi] / max(float(ii.max()), 1e-9))

    # ── 判定: 谱图弥散 AND 无可接受匹配 ──
    diffuse = (dynamic_range < _DIFFUSE_DYNAMIC_RANGE
               or sharp_content < _DIFFUSE_SHARP_CONTENT)
    has_match = _has_acceptable_match(top_match)

    if diffuse and not has_match:
        level = LEVEL_AMORPHOUS
    elif diffuse and has_match:
        level = LEVEL_PARTIAL
    else:
        level = LEVEL_CRYSTALLINE

    return _result(level, diffuse, sharp_content, dynamic_range, narrow_conc, n_peaks,
                   hump, hump_rel, _note(level, diffuse, has_match))


def _local_maxima(y: np.ndarray, step: float) -> list[int]:
    """返回按强度降序的局部极大索引 (最小间距 0.3°)。"""
    min_dist = max(1, int(round(0.3 / max(step, 1e-6))))
    n = len(y)
    cand = [i for i in range(1, n - 1) if y[i] >= y[i - 1] and y[i] > y[i + 1]]
    out = []
    for i in cand:
        if all(abs(i - j) >= min_dist for j in out):
            out.append(i)
    out.sort(key=lambda i: -y[i])
    return out


def _has_acceptable_match(top_match) -> bool:
    if top_match is None:
        return False
    conf = str(getattr(top_match, "confidence", "") or "")
    if conf in _ACCEPTABLE_CONFIDENCE:
        return True
    # 无 confidence 字段时退化为 FoM + 匹配峰数
    score = float(getattr(top_match, "score", 9.9))
    matched = int(getattr(top_match, "matched_peaks", 0) or 0)
    return score <= 0.55 and matched >= 2


def _note(level: str, diffuse: bool, has_match: bool) -> str:
    if level == LEVEL_AMORPHOUS:
        return ("近非晶: 谱图弥散 (动态范围/尖锐度低) 且未获得可接受的结晶相匹配 —— "
                "结晶相检索在此不适用, 漏检属物理无解, 不应计为算法失败")
    if level == LEVEL_PARTIAL:
        return "含非晶/弥散背景, 但已匹配到可辨结晶相 (建议按 结晶相+非晶背景 两相处理)"
    if diffuse:
        return "谱图偏弥散, 但已获得可接受匹配 —— 以匹配结果为准 (勿据此判非晶)"
    return "结晶良好"


def _result(level, diffuse, sharp_content, dynamic_range, narrow_conc, n_peaks,
            hump, hump_rel, note) -> dict:
    return {
        "level": level,
        # 纯谱图形状判据 (不含匹配 veto)。下游统计"物理无解"时用这个更稳:
        # 它不受最佳匹配是真是假影响, 只回答"这张谱像不像非晶"。
        "diffuse": bool(diffuse),
        "sharp_content": round(float(sharp_content), 4),
        "dynamic_range": round(float(dynamic_range), 2),
        "narrow_concentration": round(float(narrow_conc), 4),
        "n_peaks": int(n_peaks),
        "broad_hump": None if hump is None else round(float(hump), 2),
        "hump_rel": None if hump_rel is None else round(float(hump_rel), 3),
        "note": note,
    }
