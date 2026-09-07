"""
背景估计服务 (M04, Sprint 3)
============================
自动背景 (SNIP / 多项式) + 手动控制点插值 + 背景扣除。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.interpolate import CubicSpline

from polyxrd.models.xrd_data import XRDData


class BackgroundEstimator:
    """背景曲线估计。"""

    # ── 自动: SNIP (逐次峰值裁剪) ─────────────────────────────

    @staticmethod
    def snip_background(
        y: np.ndarray,
        iterations: int = 30,
        max_window: Optional[int] = None,
    ) -> np.ndarray:
        """SNIP 类自动背景 (对数空间逐次最小化两侧均值)。

        对每条 2θ 通道, 迭代执行 y←min(y, 0.5*(y[i-w]+y[i+w])) (w 递增),
        等效于把"峰"逐次裁平, 剩余为背景。窗口 w 从 1 增至 iterations,
        其上限可由 max_window 收紧 (小窗口保留更贴合背景的低频, 保护宽峰)。
        """
        yin = np.asarray(y, dtype=float)
        n = len(yin)
        if n < 5:
            return np.zeros_like(yin)
        maxw = max_window or max(1, min(iterations, n // 4))
        z = np.log1p(np.maximum(yin, 0.0))
        for w in range(1, min(iterations, maxw) + 1):
            left = np.zeros(n)
            right = np.zeros(n)
            left[: n - w] = z[w:]
            right[w:] = z[: n - w]
            # 边界: 无双侧邻域处保留原值 (不裁剪)
            interior = (w <= np.arange(n)) & (np.arange(n) < n - w)
            mean = 0.5 * (left + right)
            z = np.where(interior, np.minimum(z, mean), z)
        return np.expm1(z)

    # ── 自动: 低阶多项式 ───────────────────────────────────────

    @staticmethod
    def poly_background(
        x: np.ndarray,
        y: np.ndarray,
        degree: int = 4,
        anchor_indices: Optional[list] = None,
    ) -> np.ndarray:
        """多项式背景拟合。

        anchor_indices: 强制通过这些数据点 (给 100× 权重)。
        """
        xs = np.asarray(x, dtype=float)
        ys = np.asarray(y, dtype=float)
        idx_all = np.arange(len(xs))
        w = np.ones_like(xs)
        fit_x = xs
        fit_y = ys
        if anchor_indices is not None and len(anchor_indices):
            anchor = np.asarray(anchor_indices, dtype=int)
            anchor = anchor[(anchor >= 0) & (anchor < len(xs))]
            if len(anchor):
                w[anchor] = 100.0
        coef = np.polynomial.polynomial.polyfit(
            fit_x, fit_y, int(degree), w=w)
        return np.polynomial.polynomial.polyval(xs, coef)

    # ── 手动控制点插值 ────────────────────────────────────────

    @staticmethod
    def control_point_background(
        x: np.ndarray, anchors: list[tuple[float, float]]
    ) -> np.ndarray:
        """通过控制点 (2θ, I) 的三次样条背景 (严格过锚点)。"""
        if len(anchors) < 2:
            raise ValueError("控制点至少需要 2 个")
        ax = np.asarray([float(a[0]) for a in anchors])
        ay = np.asarray([float(a[1]) for a in anchors])
        order = np.argsort(ax)
        ax, ay = ax[order], ay[order]
        cs = CubicSpline(ax, ay, extrapolate=False)
        xx = np.asarray(x, dtype=float)
        bg = cs(xx)
        # 样条外推区域 (未覆盖): 用端点值填充
        bg[xx < ax[0]] = float(ay[0])
        bg[xx > ax[-1]] = float(ay[-1])
        return bg

    # ── 编排与扣除 ────────────────────────────────────────────

    @classmethod
    def estimate_background(
        cls, xrd: XRDData, method: str = "snip", **kwargs
    ) -> np.ndarray:
        """对一条谱估计背景曲线 (与强度等长)。"""
        y = np.asarray(xrd.intensity, dtype=float)
        if method == "snip":
            return cls.snip_background(
                y, iterations=kwargs.get("iterations", 30),
                max_window=kwargs.get("max_window"))
        if method == "poly":
            return cls.poly_background(
                xrd.two_theta, y,
                degree=kwargs.get("degree", 4),
                anchor_indices=kwargs.get("anchor_indices"))
        if method == "control":
            anchors = kwargs.get("anchors")
            if not anchors:
                raise ValueError("method=control 需要 anchors=[(2θ, I), ...]")
            return cls.control_point_background(xrd.two_theta, anchors)
        raise ValueError(f"未知背景方法: {method}")

    @classmethod
    def subtract_background(cls, xrd: XRDData, bg: np.ndarray) -> XRDData:
        """扣除背景: y' = y - bg, 负值截 0。"""
        if len(bg) != len(xrd.intensity):
            raise ValueError("背景长度与强度不一致")
        yy = np.asarray(xrd.intensity, dtype=float) - np.asarray(bg, dtype=float)
        return XRDData(
            two_theta=np.asarray(xrd.two_theta, dtype=float).copy(),
            intensity=np.maximum(yy, 0.0),
            wavelength=xrd.wavelength,
            metadata={**xrd.metadata, "background_subtracted": True},
        )
