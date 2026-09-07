"""
原始数据处理管线 (M03, Sprint 2)
=================================
顺序建议: trim → strip_kalpha2 → smooth → (可选) increase_resolution。
所有函数返回新 XRDData (不修改入参)。谱级校正保持 2θ 轴与强度同长。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.signal import savgol_filter

from polyxrd.models.xrd_data import XRDData


class RawProcessing:
    """XRD 原始数据的基本处理 (纯函数)。"""

    # ── trim ──────────────────────────────────────────────────

    @staticmethod
    def trim(xrd: XRDData, t_min: float, t_max: float) -> XRDData:
        """裁剪 2θ 范围到 [t_min, t_max] (取最近点)。

        边界: 范围超出数据端点时截到端点; t_min>=t_max 抛 ValueError。
        """
        if t_min >= t_max:
            raise ValueError(f"无效裁剪范围: t_min={t_min} >= t_max={t_max}")
        return xrd.crop(max(float(t_min), float(xrd.two_theta[0])),
                        min(float(t_max), float(xrd.two_theta[-1])))

    # ── 平滑 ──────────────────────────────────────────────────

    @staticmethod
    def smooth_savitzky_golay(
        xrd: XRDData,
        window: int = 11,
        polyorder: int = 3,
        reps: int = 1,
    ) -> XRDData:
        """Savitzky-Golay 平滑 (温和, 默认 reps=1; 过度平滑会吞弱峰)。"""
        n = len(xrd.intensity)
        if window < 5 or window % 2 == 0:
            raise ValueError(f"window 须为 >=5 的奇数, 实际 {window}")
        if polyorder >= window:
            raise ValueError(f"polyorder({polyorder}) 必须 < window({window})")
        y = np.asarray(xrd.intensity, dtype=float)
        for _ in range(int(reps)):
            if window >= n:
                return xrd.copy()
            y = savgol_filter(y, window, polyorder, mode="interp")
        return RawProcessing._with_intensity(xrd, y)

    # ── Kα2 剥离 (Rachinger 迭代去卷积) ───────────────────────

    @staticmethod
    def strip_kalpha2(
        xrd: XRDData,
        wavelength1: float = 1.5406,
        wavelength2: float = 1.5444,
        ratio: float = 2.0,
    ) -> XRDData:
        """按 Rachinger 方法扣除 Kα2 贡献。

        双峰间距随 2θ 变化: Δ2θ(t) = 2[asin((λ2/λ1)·sinθ) − θ] (度)。
        从低角向高角迭代: new[t] = y[t] − (Iα2/Iα1)·new[t−Δ(t)] (向前插值
        用已校正值, 数值稳定)。
        边界: t−Δ(t) 低于起始角时不扣除 (起始区无 Kα2 信息); 结果负值截 0。
        """
        x = np.asarray(xrd.two_theta, dtype=float)
        y = np.asarray(xrd.intensity, dtype=float)
        n = len(x)
        step = float(np.mean(np.diff(x))) if n > 1 else 0.01
        new = np.array(y, dtype=float)
        th = np.radians(x / 2.0)
        r = wavelength2 / wavelength1
        arg = np.clip(r * np.sin(th), -1.0, 1.0)
        delta = np.degrees(2.0 * (np.arcsin(arg) - th))  # Δ2θ(度), >=0
        k_shift = delta / step
        inv_ratio = 1.0 / ratio if ratio > 0 else 0.0
        for i in range(n):
            j = i - k_shift[i]
            if j >= 1:
                j0 = int(np.floor(j))
                frac = j - j0
                if j0 + 1 < n:
                    # 用已校正的前段值线性插值
                    base = new[j0] * (1.0 - frac) + new[j0 + 1] * frac
                else:
                    base = new[j0]
                new[i] = y[i] - inv_ratio * base
        new = np.maximum(new, 0.0)
        return RawProcessing._with_intensity(xrd, new)

    # ── 分辨率插值 ────────────────────────────────────────────

    @staticmethod
    def increase_resolution(xrd: XRDData, factor: int = 2) -> XRDData:
        """三次样条插值提高数据分辨率 (缩小步长)。

        边界: factor 取 1~4 (过大易把噪声"固化", 见 tips); 输入必须 >=3 点。
        """
        factor = int(factor)
        if not (1 <= factor <= 4):
            raise ValueError(f"factor 建议 1~4 (过大噪声会固化), 实际 {factor}")
        if factor == 1:
            return xrd.copy()
        x = np.asarray(xrd.two_theta, dtype=float)
        y = np.asarray(xrd.intensity, dtype=float)
        if len(x) < 3:
            return xrd.copy()
        new_x = np.linspace(float(x[0]), float(x[-1]), (len(x) - 1) * factor + 1)
        cs = CubicSpline(x, y, extrapolate=False)
        new_y = cs(new_x)
        return RawProcessing._with_intensity(xrd, new_y, new_x=new_x)

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _with_intensity(xrd: XRDData, intensity: np.ndarray,
                        new_x: Optional[np.ndarray] = None) -> XRDData:
        xx = xrd.two_theta if new_x is None else new_x
        return XRDData(
            two_theta=np.asarray(xx, dtype=float).copy(),
            intensity=np.asarray(intensity, dtype=float).copy(),
            wavelength=xrd.wavelength,
            metadata={**xrd.metadata},
        )
