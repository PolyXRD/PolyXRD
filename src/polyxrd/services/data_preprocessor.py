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

from polyxrd.models.xrd_data import XRDData, BackgroundResult

#: Kα2/Kα1 波长比（物理常数，2θ 轴上表现为约 0.25% 的位移）
KA2_ALPHA2_RATIO = 1.00249

#: 背景扣除方法名（**唯一真源**）——
#: UI 下拉框必须用 setItemData 携带这些 key，不能用译文当 key。
BG_METHODS: tuple[str, ...] = ("snip", "als", "polyfit", "median", "rolling")

#: 平滑方法名（同上）
SMOOTH_METHODS: tuple[str, ...] = ("savgol", "gaussian", "moving", "median")


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

        # 方法名归一: UI 侧历史上直接把译文/大小写混写传进来（P0-1）。
        # 空值/None → 回落文档声明的默认方法，未知名字才报错（带可选项）。
        method = str(method or "").strip().lower() or "snip"
        if method not in methods:
            raise ValueError(
                f"未知的背景扣除方法: {method}（可选: {', '.join(BG_METHODS)}）")

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
        method = str(method or "").strip().lower() or "savgol"
        if method == "savgol":
            smooth_func = self._savgol_smooth
        elif method == "gaussian":
            smooth_func = self._gaussian_smooth
        elif method == "moving":
            smooth_func = self._moving_average
        elif method == "median":
            smooth_func = self._median_smooth
        else:
            raise ValueError(
                f"未知的平滑方法: {method}（可选: {', '.join(SMOOTH_METHODS)}）")

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
        wavelength_alpha1: Optional[float] = None,
        wavelength_alpha2: Optional[float] = None,
        ratio: float = 0.5,
        *,
        iterations: int = 2,
        skip_on_mismatch: bool = True,
    ) -> XRDData:
        """Kα2峰剥离 (Rachinger 移位相减法)

        Args:
            data: 输入数据 (含Kα1+Kα2)
            wavelength_alpha1: Kα1 波长；``None`` → 取 ``data.wavelength``
                （v3.0.1 起不再把 Cu 1.5406 写死）
            wavelength_alpha2: Kα2 波长；``None`` → ``α1 × 1.00249``

            .. note:: 剥离**几何本身与绝对波长无关** —— 角度映射
               ``sin(x/2) = (λ2/λ1)·sin(u/2)`` 只用到比值（已实测 Cu/Co/Fe/Mo
               四种靶的移位量在固定 d 值下仅随 2θ 变化，与 λ1 的具体数值无关）。
               绝对波长的作用只有一个：它是写回结果 ``XRDData.wavelength``
               的值。此前写死 Cu，会把 Co/Fe/Mo 靶数据的结果标成 Cu 波长，
               下游所有 ``d = λ/(2sinθ)`` 换算随之整体错位。
            ratio: Kα2/Kα1强度比
            iterations: Rachinger 递推次数 (1 次即经典单遍，2 次可把残余
                α2 的 α2 (≈ r² = 25%) 也扣掉; 不宜过多，会放大高频噪声)
            skip_on_mismatch: 剥离后若出现**显著负值**（超过谱最大值 1%），
                说明数据不符合 Kα1+Kα2 双线模型（单色器/仅 Kα1/已剥离过），
                此时不剥离、原样返回并在 metadata 标记，避免系统性削峰。

        Returns:
            Kα1数据
        """
        lam1 = float(wavelength_alpha1) if wavelength_alpha1 else float(
            getattr(data, "wavelength", 0.0) or 0.0)
        if lam1 <= 0.0:
            lam1 = 1.5406
        lam2 = float(wavelength_alpha2) if wavelength_alpha2 else (
            lam1 * KA2_ALPHA2_RATIO)

        ratio = float(ratio)
        x = np.asarray(data.two_theta, dtype=float)
        y = np.asarray(data.intensity, dtype=float)
        if x.size < 3 or y.size != x.size:
            return data

        # 角度映射: α1 角 u 与其 α2 伴线角 x 满足
        #   sin(x/2) = (λ2/λ1) · sin(u/2)        (同一 d 值: 2d·sinθ = λ)
        # 反解出 u, 再按 Rachinger 递推  K_{n+1}(x) = I(x) − r·K_n(u)。
        #
        # v3.0.1 修复: 原实现把 ``d = λ1/(2sin(x/2))`` 当成"x 处 α1 峰的 d"，
        # 再**正算** α2 位置（即查 x+Δ）—— 移位方向相反，减掉的是更高角处的
        # 强度：卫星峰原封不动留在原位（合成双线实测 844 → 824，本应降到
        # 背景 20），主峰肩部反被削出负坑（最小残差 −27.5%·Imax）。
        sin_half = np.clip((lam1 / lam2) * np.sin(np.radians(x / 2.0)), 0.0, 1.0)
        alpha1_angle = 2.0 * np.degrees(np.arcsin(sin_half))

        raw = y.astype(float, copy=True)
        for _ in range(max(1, int(iterations))):
            prev = np.interp(alpha1_angle, x, raw, left=0.0, right=0.0)
            raw = y - ratio * prev

        # 模型自检: 负偏移超过谱最大值 1% → 该数据不是 Kα1+Kα2 双线
        peak_max = float(np.max(data.intensity)) if data.intensity.size else 0.0
        if skip_on_mismatch and peak_max > 0:
            overshoot = -float(np.min(raw)) / peak_max
            if overshoot > 0.01:
                return XRDData(
                    two_theta=data.two_theta.copy(),
                    intensity=data.intensity.copy(),
                    wavelength=lam1,
                    metadata={
                        **data.metadata,
                        "ka2_stripped": False,
                        "ka2_skipped": f"negative_overshoot={overshoot:.3f}",
                    },
                )

        corrected_intensity = np.maximum(raw, 0)

        return XRDData(
            two_theta=data.two_theta.copy(),
            intensity=corrected_intensity,
            wavelength=lam1,
            metadata={**data.metadata, "ka2_stripped": True,
                      "ka2_alpha1": lam1, "ka2_alpha2": lam2},
        )

    # ------------------------------------------------------------------
    # 背景扣除算法
    # ------------------------------------------------------------------

    def _snip_background(
        self,
        intensity: np.ndarray,
        iterations: int = 40,
        max_window: Optional[int] = None,
        **kwargs,
    ) -> np.ndarray:
        """SNIP (Statistics-sensitive Non-linear Iterative Peak-clipping) 背景估计

        引用: Ryan & Vinall, "An algorithm for absolute background
              estimation and elimination"

        v3.0.1 修复: 原实现把 SNIP 的"像素半窗 w"写成了"数值阈值
        ``(y_max-y_min)*i/iterations``"，且用原地邻点均值替换 —— 阈值随迭代
        涨到整个动态范围，峰顶被逐点削平并扩散，**峰几乎被整体当成背景**。
        实测 (7001 点, 真背景 115, 峰高 800): 峰心背景估成 898, 扣后峰高仅 17.5。

        现改为委托 ``BackgroundEstimator.snip_background``（同仓库已有的正确
        向量化实现: 半窗按像素递增、``y←min(y, 0.5(y[i-w]+y[i+w]))``），
        同时把 40×N 的 Python 双层循环换成 numpy 向量化（实测 92 ms → 2.9 ms）。
        """
        from polyxrd.services.background import BackgroundEstimator

        y = np.asarray(intensity, dtype=float)
        if y.size < 5:
            return np.zeros_like(y)
        return BackgroundEstimator.snip_background(
            y,
            iterations=int(iterations),
            max_window=max_window,
        )

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
        """中值滤波背景扣除

        v4.0.0 修复: 窗口大于谱点数时 ``median_filter`` 会用 0 填充,
        短谱 (点数 < window) 的背景被整体估成 0 (实测 5 点谱 size=51 → 全 0),
        等于"不扣背景"或把信号当背景。现把窗口收缩到不超过谱点数。
        """
        y = np.asarray(intensity, dtype=float)
        window = max(3, min(int(window), y.size))
        return median_filter(y, size=window)

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
        """Savitzky-Golay平滑

        v4.0.0 修复: 窗口未随谱点数收缩 → 短谱 (点数 < window) 直接抛
        ``ValueError: window_length must be less than or equal to the size of x``。
        稀点/窄区间导入的谱 (例如 2θ 步长 2°、几十点的概览扫描) 走默认
        window=11 就会崩。现按点数收缩为最大奇数窗口, 点数 < 3 时原样返回。
        """
        y = np.asarray(intensity, dtype=float)
        n = y.size
        window = max(3, int(window) if int(window) % 2 == 1 else int(window) + 1)
        if window > n:
            window = n if n % 2 == 1 else n - 1
        if window < 3:
            return y.copy()
        polyorder = min(int(polyorder), window - 1)
        return signal.savgol_filter(y, window, polyorder)

    @staticmethod
    def _gaussian_smooth(
        intensity: np.ndarray,
        window: int = 11,
        sigma: Optional[float] = None,
        **kwargs,
    ) -> np.ndarray:
        """高斯平滑

        v3.0.1 修复两处缺陷:
        1. 卷积核长度误用 ``len(intensity)``（σ 只有约 1.8 个采样点，几乎不平滑）
           → 改用 ``window`` 长度；
        2. **未除以核和** → 强度被整体放大。实测常数谱 100 平滑后变 459.21
           （增益 = σ·√(2π) ≈ 4.59），后续归一化/定量/精修强度标度全被污染。
           现除 ``win.sum()``，保证常数谱平滑后仍是原常数。
        """
        window = max(3, int(window if window % 2 == 1 else window + 1))
        if sigma is None:
            sigma = window / 6.0
        win = signal.windows.gaussian(window, max(float(sigma), 1e-6))
        total = float(win.sum())
        y = np.asarray(intensity, dtype=float)
        if total <= 0:
            return y.copy()
        win = win / total
        # 边界须按边缘值延拓（零填充会让谱两端强度塌陷：常数谱 100 的
        # 首末各 window//2 点会掉到 52~76，扣背景/归一化后造成假低端)。
        half = window // 2
        padded = np.pad(y, half, mode="edge")
        out = signal.fftconvolve(padded, win, mode="same")
        return out[half:half + y.size]

    @staticmethod
    def _moving_average(
        intensity: np.ndarray,
        window: int = 11,
        **kwargs,
    ) -> np.ndarray:
        """移动平均

        v4.0.0 修复: 原实现 ``signal.convolve(..., mode="same")`` 两端按零填充,
        常数谱 100 平滑后首末各 window//2 点掉到 54.5 (45% 塌陷) —— 与
        v3.0.1 已修好的高斯平滑是同一类缺陷, 会让归一化/扣背景后的低角端
        出现假低强度。现改为与 ``_gaussian_smooth`` 一致的边缘值延拓 +
        核归一, 常数谱保持恒定; 并把窗口收缩到不超过谱点数。
        """
        y = np.asarray(intensity, dtype=float)
        n = y.size
        window = max(1, int(window))
        if window <= 1 or n == 0:
            return y.copy()
        window = min(window, n)
        kernel = np.ones(window) / float(window)
        half = window // 2
        padded = np.pad(y, half, mode="edge")
        out = signal.convolve(padded, kernel, mode="same")
        return out[half:half + n]

    @staticmethod
    def _median_smooth(
        intensity: np.ndarray,
        window: int = 11,
        **kwargs,
    ) -> np.ndarray:
        """中值平滑 (窗口收缩到不超过谱点数, 避免短谱被 0 填充吞掉)"""
        y = np.asarray(intensity, dtype=float)
        window = max(3, int(window) if int(window) % 2 == 1 else int(window) + 1)
        window = min(window, y.size if y.size % 2 == 1 else y.size - 1)
        if window < 3:
            return y.copy()
        return median_filter(y, size=window)
