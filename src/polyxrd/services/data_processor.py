"""
数据预处理服务
==============
提供背景扣除、平滑、Kα2剥离等XRD数据预处理功能。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import signal
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

from polyxrd.models.xrd_data import XRDData


class DataProcessor:
    """XRD数据处理器

    提供背景扣除、平滑、归一化等预处理方法。
    所有方法返回新的XRDData实例（不可变设计）。

    Usage:
        processor = DataProcessor()
        bg_removed = processor.subtract_background(data, method='snip')
        smoothed = processor.smooth(bg_removed, method='savgol')
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # 背景扣除
    # ------------------------------------------------------------------

    def subtract_background(
        self,
        data: XRDData,
        method: str = "snip",
        **kwargs,
    ) -> XRDData:
        """背景扣除

        Args:
            data: 输入XRD数据
            method: 背景扣除方法
                - 'snip': SNIP算法 (推荐，适合多数情况)
                - 'als': 不对称最小二乘法
                - 'polyfit': 多项式拟合
                - 'median': 中值滤波
                - 'rolling': 滚动平均
            **kwargs: 各方法的参数

        Returns:
            背景扣除后的XRDData实例
        """
        methods = {
            "snip": self._bg_snip,
            "als": self._bg_als,
            "polyfit": self._bg_polyfit,
            "median": self._bg_median,
            "rolling": self._bg_rolling,
        }

        if method not in methods:
            raise ValueError(
                f"未知的背景扣除方法: {method}. "
                f"可选: {list(methods.keys())}"
            )

        bg = methods[method](data.intensity, **kwargs)
        corrected = data.intensity - bg
        corrected = np.maximum(corrected, 0.0)

        return data.clone(intensity=corrected)

    def _bg_snip(self, intensity: np.ndarray, **kwargs) -> np.ndarray:
        """SNIP (Statistics-sensitive Non-linear Iterative Peak-clipping) 算法

        参考: Ryan & Vidrine, 1988
        """
        niter = kwargs.get("niter", 40)
        max_w = len(intensity) // 2
        if max_w < 1:
            max_w = len(intensity)

        y = intensity.copy()
        for i in range(niter):
            w = max_w * (1 - i / niter)
            if w < 1:
                w = 1

            for j in range(w, len(y) - w):
                a = y[j]
                b = (y[j - w] + y[j + w]) / 2.0
                if b < a:
                    y[j] = b

        # 使用原始值作为上限
        bg = np.minimum(y, intensity)
        return bg

    def _bg_als(self, intensity: np.ndarray, **kwargs) -> np.ndarray:
        """不对称最小二乘法 (Asymmetric Least Squares)

        Eilers & Boelens, 2005
        """
        lam = kwargs.get("lam", 1e6)
        p = kwargs.get("p", 0.01)
        maxiter = kwargs.get("maxiter", 50)

        L = len(intensity)
        D = np.diff(np.eye(L), 2)
        D = lam * D.dot(D.T)
        w = np.ones(L)

        for _ in range(maxiter):
            W = spsolve(csr_matrix(w), w * intensity) if False else None
            # 使用直接方法
            Z = np.zeros(L)
            for i in range(1, L - 1):
                Z[i] = (intensity[i] * w[i] + lam * (Z[i - 1] + Z[i + 1])) / (w[i] + 2 * lam)

            w_new = p * (intensity > Z) + (1 - p) * (intensity < Z)

            # 收敛检查
            if np.linalg.norm(w_new - w) / np.linalg.norm(w) < 1e-6:
                break
            w = w_new

        # 简单ALS实现
        bg = self._als_simple(intensity, lam, p, maxiter)
        return bg

    def _als_simple(
        self, y: np.ndarray, lam: float, p: float, maxiter: int
    ) -> np.ndarray:
        """简单的ALS实现"""
        n = len(y)
        # 构造二阶差分矩阵
        D2 = np.zeros((n - 2, n))
        for i in range(n - 2):
            D2[i, i] = 1
            D2[i, i + 1] = -2
            D2[i, i + 2] = 1

        w = np.ones(n)
        for iteration in range(maxiter):
            W = np.diag(w)
            A = W + lam * (D2.T @ D2)
            try:
                z = np.linalg.solve(A, W @ y)
            except np.linalg.LinAlgError:
                z = np.linalg.lstsq(A, W @ y, rcond=None)[0]

            w_new = p * (y > z) + (1 - p) * (y < z)

            if np.linalg.norm(w_new - w) / (np.linalg.norm(w) + 1e-10) < 1e-6:
                break
            w = w_new

        return z

    def _bg_polyfit(self, intensity: np.ndarray, **kwargs) -> np.ndarray:
        """多项式拟合背景"""
        degree = kwargs.get("degree", 3)
        n = len(intensity)

        # 使用分位数点作为背景锚点
        n_anchors = max(20, n // 20)
        anchor_idx = np.linspace(0, n - 1, n_anchors, dtype=int)
        anchor_intensities = np.array([
            np.percentile(
                intensity[max(0, i - n // 20):min(n, i + n // 20)], 10
            )
            for i in anchor_idx
        ])

        x_anchor = np.arange(n)[anchor_idx]
        coeffs = np.polyfit(x_anchor, anchor_intensities, degree)
        bg = np.polyval(coeffs, np.arange(n))

        return np.maximum(bg, 0)

    def _bg_median(self, intensity: np.ndarray, **kwargs) -> np.ndarray:
        """中值滤波背景"""
        window = kwargs.get("window", 50)
        if window % 2 == 0:
            window += 1
        bg = signal.medfilt(intensity, kernel_size=window)
        return bg

    def _bg_rolling(self, intensity: np.ndarray, **kwargs) -> np.ndarray:
        """滚动平均背景"""
        window = kwargs.get("window", 50)
        kernel = np.ones(window) / window
        bg = np.convolve(intensity, kernel, mode="same")
        return bg

    # ------------------------------------------------------------------
    # 平滑
    # ------------------------------------------------------------------

    def smooth(
        self,
        data: XRDData,
        method: str = "savgol",
        window: int = 11,
        polyorder: int = 3,
        **kwargs,
    ) -> XRDData:
        """数据平滑

        Args:
            data: 输入XRD数据
            method: 平滑方法
                - 'savgol': Savitzky-Golay滤波 (推荐)
                - 'gaussian': 高斯平滑
                - 'moving': 移动平均
                - 'median': 中值滤波
            window: 窗口大小 (必须为奇数)
            polyorder: 多项式阶数 (savgol方法)

        Returns:
            平滑后的XRDData实例
        """
        if window % 2 == 0:
            window += 1

        methods = {
            "savgol": self._smooth_savgol,
            "gaussian": self._smooth_gaussian,
            "moving": self._smooth_moving,
            "median": self._smooth_median,
        }

        if method not in methods:
            raise ValueError(f"未知的平滑方法: {method}")

        smoothed = methods[method](data.intensity, window, polyorder)
        return data.clone(intensity=smoothed)

    def _smooth_savgol(
        self, intensity: np.ndarray, window: int, polyorder: int
    ) -> np.ndarray:
        """Savitzky-Golay 平滑"""
        if window > len(intensity):
            window = len(intensity) if len(intensity) % 2 == 1 else len(intensity) - 1
        if polyorder >= window:
            polyorder = window - 1
        return signal.savgol_filter(intensity, window, polyorder)

    def _smooth_gaussian(
        self, intensity: np.ndarray, window: int, polyorder: int
    ) -> np.ndarray:
        """高斯平滑"""
        sigma = window / 6.0
        kernel = signal.windows.gaussian(window, sigma)
        kernel /= kernel.sum()
        return np.convolve(intensity, kernel, mode="same")

    def _smooth_moving(
        self, intensity: np.ndarray, window: int, polyorder: int
    ) -> np.ndarray:
        """移动平均"""
        kernel = np.ones(window) / window
        return np.convolve(intensity, kernel, mode="same")

    def _smooth_median(
        self, intensity: np.ndarray, window: int, polyorder: int
    ) -> np.ndarray:
        """中值滤波"""
        return signal.medfilt(intensity, kernel_size=window)

    # ------------------------------------------------------------------
    # Kα2剥离
    # ------------------------------------------------------------------

    def strip_kalpha2(
        self,
        data: XRDData,
        k_alpha2_wavelength: float = 1.5444,
        k_alpha2_intensity_ratio: float = 0.5,
    ) -> XRDData:
        """Kα2峰剥离

        对Cu靶，Kα2波长=1.5444 Å，相对Kα1强度约为0.5。

        Args:
            data: 输入XRD数据（使用Kα1波长）
            k_alpha2_wavelength: Kα2波长
            k_alpha2_intensity_ratio: Kα2相对Kα1强度比

        Returns:
            剥离Kα2后的XRDData
        """
        wl1 = data.wavelength
        wl2 = k_alpha2_wavelength

        # 将Kα2的2θ转换为Kα1的2θ
        # sin(θ1)/λ1 = sin(θ2)/λ2
        sin_theta = np.sin(np.radians(data.two_theta / 2.0))
        sin_theta_kalpha2 = sin_theta * wl1 / wl2
        sin_theta_kalpha2 = np.clip(sin_theta_kalpha2, -1, 1)
        two_theta_kalpha2 = 2.0 * np.degrees(np.arcsin(sin_theta_kalpha2))

        # 插值Kα2数据到Kα1的2θ网格
        intensity_kalpha2 = np.interp(
            data.two_theta,
            two_theta_kalpha2,
            data.intensity,
            left=0,
            right=0,
        )

        corrected = data.intensity - k_alpha2_intensity_ratio * intensity_kalpha2
        corrected = np.maximum(corrected, 0.0)

        return data.clone(intensity=corrected)

    # ------------------------------------------------------------------
    # 归一化
    # ------------------------------------------------------------------

    def normalize(
        self,
        data: XRDData,
        method: str = "minmax",
        target_max: float = 100.0,
    ) -> XRDData:
        """数据归一化

        Args:
            data: 输入数据
            method: 归一化方法
                - 'minmax': 线性缩放到[0, target_max]
                - 'max': 以最大值为target_max
                - 'sum': 积分归一化
            target_max: 目标最大值

        Returns:
            归一化后的XRDData
        """
        if method == "minmax":
            y_min = data.intensity.min()
            y_max = data.intensity.max()
            if y_max > y_min:
                normalized = (data.intensity - y_min) / (y_max - y_min) * target_max
            else:
                normalized = data.intensity

        elif method == "max":
            y_max = data.intensity.max()
            if y_max > 0:
                normalized = data.intensity / y_max * target_max
            else:
                normalized = data.intensity

        elif method == "sum":
            total = data.intensity.sum()
            if total > 0:
                normalized = data.intensity / total * target_max
            else:
                normalized = data.intensity

        else:
            raise ValueError(f"未知的归一化方法: {method}")

        return data.clone(intensity=normalized)

    # ------------------------------------------------------------------
    # 其他处理
    # ------------------------------------------------------------------

    def remove_baseline_linear(self, data: XRDData, n_segments: int = 10) -> XRDData:
        """线性基线去除（手动指定端点）

        Args:
            data: 输入数据
            n_segments: 分段数

        Returns:
            基线校正后的XRDData
        """
        n = len(data.intensity)
        x = np.arange(n)

        # 使用分位数点作为基线锚点
        anchor_idx = np.linspace(0, n - 1, n_segments + 1, dtype=int)
        anchor_intensities = np.zeros(len(anchor_idx))

        for i, idx in enumerate(anchor_idx):
            start = max(0, idx - n // 20)
            end = min(n, idx + n // 20)
            anchor_intensities[i] = np.percentile(data.intensity[start:end], 5)

        # 线性插值
        baseline = np.interp(x, anchor_idx, anchor_intensities)
        corrected = data.intensity - baseline
        corrected = np.maximum(corrected, 0.0)

        return data.clone(intensity=corrected)

    def crop(
        self,
        data: XRDData,
        two_theta_min: Optional[float] = None,
        two_theta_max: Optional[float] = None,
    ) -> XRDData:
        """裁剪2θ范围

        Args:
            data: 输入数据
            two_theta_min: 最小2θ (None=不限)
            two_theta_max: 最大2θ (None=不限)

        Returns:
            裁剪后的XRDData
        """
        mask = np.ones(len(data.two_theta), dtype=bool)

        if two_theta_min is not None:
            mask &= data.two_theta >= two_theta_min
        if two_theta_max is not None:
            mask &= data.two_theta <= two_theta_max

        if not mask.any():
            raise ValueError("裁剪范围不包含任何数据点")

        return data.clone(
            two_theta=data.two_theta[mask],
            intensity=data.intensity[mask],
        )
