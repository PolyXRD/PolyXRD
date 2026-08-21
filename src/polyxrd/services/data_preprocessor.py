"""
数据预处理服务
==============
背景扣除、平滑、Kα2剥离等。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter
from scipy.interpolate import interp1d

from polyxrd.models.xrd_data import XRDData, BackgroundResult


class DataPreprocessor:
    """数据预处理服务

    提供背景扣除、平滑、Kα2剥离、归一化等功能。
    """

    def subtract_background(
        self,
        data: XRDData,
        method: str = "snip",
        **kwargs,
    ) -> BackgroundResult:
        """背景扣除

        Args:
            data: 输入数据
            method: 背景扣除方法
            **kwargs: 方法参数

        Returns:
            BackgroundResult
        """
        methods = {
            "snip": self._snip_background,
            "als": self._als_background,
            "polyfit": self._polyfit_background,
            "median": self._median_background,
            "rolling": self._rolling_background,
        }

        if method not in methods:
            raise ValueError(f"未知的背景扣除方法: {method}")

        bg_func = methods[method]
        background = bg_func(data.intensity, **kwargs)
        corrected_intensity = np.maximum(data.intensity - background, 0)

        corrected = XRDData(
            two_theta=data.two_theta.copy(),
            intensity=corrected_intensity,
            wavelength=data.wavelength,
            metadata={**data.metadata, "background_corrected": True, "bg_method": method},
        )

        return BackgroundResult(
            background=background,
            corrected=corrected,
            method=method,
            params=kwargs,
        )

    def smooth(
        self,
        data: XRDData,
        method: str = "savgol",
        window: int = 11,
        **kwargs,
    ) -> XRDData:
        """平滑数据

        Args:
            data: 输入数据
            method: 平滑方法
            window: 窗口大小
            **kwargs: 方法参数

        Returns:
            平滑后的XRDData
        """
        if method == "savgol":
            smooth_func = self._savgol_smooth
        elif method == "gaussian":
            smooth_func = self._gaussian_smooth
        elif method == "moving":
            smooth_func = self._moving_average
        elif method == "median":
            smooth_func = self._median_smooth
        else:
            raise ValueError(f"未知的平滑方法: {method}")

        smoothed_intensity = smooth_func(data.intensity, window=window, **kwargs)

        return XRDData(
            two_theta=data.two_theta.copy(),
            intensity=smoothed_intensity,
            wavelength=data.wavelength,
            metadata={**data.metadata, "smoothed": True, "smooth_method": method},
        )

    def strip_ka_alpha2(
        self,
        data: XRDData,
        wavelength_alpha1: float = 1.5406,
        wavelength_alpha2: float = 1.5444,
        ratio: float = 0.5,
    ) -> XRDData:
        """Kα2峰剥离

        Args:
            data: 输入数据 (含Kα1+Kα2)
            wavelength_alpha1: Kα1波长
            wavelength_alpha2: Kα2波长
            ratio: Kα2/Kα1强度比

        Returns:
            Kα1数据
        """
        # 将2θ转换为d-spacing
        theta_rad = np.radians(data.two_theta / 2.0)
        d = wavelength_alpha1 / (2.0 * np.sin(theta_rad))

        # 计算Kα2对应的2θ
        sin_theta_alpha2 = wavelength_alpha2 / (2.0 * d)
        sin_theta_alpha2 = np.clip(sin_theta_alpha2, 0, 1)
        two_theta_alpha2 = 2.0 * np.degrees(np.arcsin(sin_theta_alpha2))

        # 计算Kα2强度
        intensity_alpha2 = ratio * data.intensity

        # 用插值获取Kα2在原始2θ位置的强度
        try:
            interp_func = interp1d(
                data.two_theta,
                intensity_alpha2,
                kind="linear",
                bounds_error=False,
                fill_value=0,
            )
            alpha2_at_data = interp_func(two_theta_alpha2)
        except Exception:
            alpha2_at_data = np.zeros_like(data.intensity)

        # 减去Kα2贡献
        corrected_intensity = np.maximum(data.intensity - alpha2_at_data, 0)

        return XRDData(
            two_theta=data.two_theta.copy(),
            intensity=corrected_intensity,
            wavelength=wavelength_alpha1,
            metadata={**data.metadata, "ka2_stripped": True},
        )

    # ------------------------------------------------------------------
    # 背景扣除算法
    # ------------------------------------------------------------------

    def _snip_background(
        self,
        intensity: np.ndarray,
        iterations: int = 40,
        **kwargs,
    ) -> np.ndarray:
        """SNIP (Statistics-sensitive Non-linear Iterative Peak-clipping) 背景扣除

        引用: Ryan & Vinall, "An algorithm for absolute background
               estimation and elimination"
        """
        y = np.log(np.log(np.sqrt(intensity + 1) + 1) + 1)

        for i in range(iterations):
            y_max = y.max()
            y_min = y.min()
            window = (y_max - y_min) * i / iterations
            # 将高于此阈值的点替换为左右相邻点的平均值
            for j in range(1, len(y) - 1):
                if y[j] > (y[j - 1] + y[j + 1]) / 2 + window:
                    y[j] = (y[j - 1] + y[j + 1]) / 2

        background = (np.exp(np.exp(y) - 1) - 1) ** 2 - 1
        return background

    def _als_background(
        self,
        intensity: np.ndarray,
        lam: float = 1e6,
        p: float = 0.01,
        max_iter: int = 50,
        **kwargs,
    ) -> np.ndarray:
        """ALS (Asymmetric Least Squares) 背景扣除

        引用: Eilers & Boelens, "Baseline Correction with Asymmetric Least Squares Smoothing"
        """
        try:
            from scipy import sparse
            from scipy.sparse.linalg import spsolve

            L = len(intensity)
            D = sparse.diags([1, -2, 1], [0, -1, -2], shape=(L, L - 2))
            D = lam * D.dot(D.transpose())

            w = np.ones(L)
            for i in range(max_iter):
                W = sparse.spdiags(w, 0, L, L)
                Z = W + D
                z = spsolve(Z, w * intensity)
                w_new = p * (intensity - z > 0) + (1 - p) * (intensity - z < 0)
                if np.linalg.norm(w_new - w) / np.linalg.norm(w) < 1e-9:
                    break
                w = w_new

            return z
        except ImportError:
            return self._polyfit_background(intensity, degree=6)

    def _polyfit_background(
        self,
        intensity: np.ndarray,
        degree: int = 6,
        percentile: float = 10.0,
        **kwargs,
    ) -> np.ndarray:
        """多项式拟合背景扣除

        用低百分位数据点拟合多项式作为背景。
        """
        # 选取低百分位数据点（假设为背景）
        threshold = np.percentile(intensity, percentile)
        mask = intensity <= threshold

        x = np.arange(len(intensity))[mask]
        y = intensity[mask]

        if len(x) < degree + 1:
            degree = max(1, len(x) - 1)

        coeffs = np.polyfit(x, y, degree)
        background = np.polyval(coeffs, np.arange(len(intensity)))

        return background

    def _median_background(
        self,
        intensity: np.ndarray,
        window: int = 51,
        **kwargs,
    ) -> np.ndarray:
        """中值滤波背景扣除"""
        return median_filter(intensity, size=window)

    def _rolling_background(
        self,
        intensity: np.ndarray,
        window: int = 51,
        **kwargs,
    ) -> np.ndarray:
        """滚动窗口最小值背景扣除"""
        if window > len(intensity):
            window = len(intensity)

        background = np.zeros_like(intensity)
        half_win = window // 2

        for i in range(len(intensity)):
            start = max(0, i - half_win)
            end = min(len(intensity), i + half_win + 1)
            background[i] = np.min(intensity[start:end])

        return background

    # ------------------------------------------------------------------
    # 平滑算法
    # ------------------------------------------------------------------

    @staticmethod
    def _savgol_smooth(
        intensity: np.ndarray,
        window: int = 11,
        polyorder: int = 3,
        **kwargs,
    ) -> np.ndarray:
        """Savitzky-Golay平滑"""
        window = max(3, window if window % 2 == 1 else window + 1)
        polyorder = min(polyorder, window - 1)
        return signal.savgol_filter(intensity, window, polyorder)

    @staticmethod
    def _gaussian_smooth(
        intensity: np.ndarray,
        window: int = 11,
        sigma: Optional[float] = None,
        **kwargs,
    ) -> np.ndarray:
        """高斯平滑"""
        if sigma is None:
            sigma = window / 6.0
        return signal.fftconvolve(
            intensity,
            signal.windows.gaussian(len(intensity), sigma),
            mode="same",
        )

    @staticmethod
    def _moving_average(
        intensity: np.ndarray,
        window: int = 11,
        **kwargs,
    ) -> np.ndarray:
        """移动平均"""
        kernel = np.ones(window) / window
        return signal.convolve(intensity, kernel, mode="same")

    @staticmethod
    def _median_smooth(
        intensity: np.ndarray,
        window: int = 11,
        **kwargs,
    ) -> np.ndarray:
        """中值平滑"""
        window = max(3, window if window % 2 == 1 else window + 1)
        return median_filter(intensity, size=window)
