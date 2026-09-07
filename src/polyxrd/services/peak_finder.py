"""
峰检测服务
==========
自动峰检测和峰拟合。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import signal
from scipy.optimize import curve_fit

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.xrd_data import XRDData


class PeakFinder:
    """峰检测和拟合服务

    提供自动峰检测、峰参数提取和峰拟合功能。
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # 峰检测
    # ------------------------------------------------------------------

    def find_peaks(
        self,
        data: XRDData,
        height: float = 0.05,
        distance: float = 5.0,
        prominence: float = 0.01,
        width: Optional[float] = None,
        sensitivity: Optional[float] = None,
        default_fwhm: Optional[float] = None,
        detect_shoulders: bool = False,
        merge_kalpha_doublets: bool = False,
        wavelength1: float = 1.5406,
        wavelength2: float = 1.5444,
        shoulder_smooth_window: Optional[int] = None,
        **kwargs,
    ) -> PeakList:
        """自动峰检测（M05 增强版）

        Args:
            data: XRD数据
            height: 最小峰高 (相对最大值)
            distance: 峰之间最小2θ距离 (度)
            prominence: 峰显著性 (相对最大值)
            width: 最小峰宽
            sensitivity: 灵敏度 (建议 1~10, None=不使用)。
                提供时 prominence 阈值按 max_intensity×0.01/sensitivity 计算,
                灵敏度越高检出的峰越多 (sensitivity=1 ≈ 旧默认)。
            default_fwhm: 峰搜索/肩峰窗口用半高宽估计 (度); None=逐峰半高宽
            detect_shoulders: 在 2×FWHM 窗口内检测被主峰掩盖的肩峰
                (默认关, 与 v0.9.x 行为一致)
            merge_kalpha_doublets: 把相邻 Kα1/Kα2 双峰合并为 Kα1 主峰
            wavelength1/wavelength2: Kα1/Kα2 波长 (Cu 默认)
            shoulder_smooth_window: 肩峰检测二阶导平滑窗口 (奇数)
            **kwargs: 传递给 scipy.signal.find_peaks 的参数

        Returns:
            PeakList
        """
        max_intensity = float(np.max(data.intensity)) if len(data.intensity) else 0.0
        if max_intensity == 0:
            return PeakList(source="auto")

        # 阈值: 向后兼容 (旧默认 prominence=0.01 → abs=0.01×max)
        if sensitivity is not None and sensitivity > 0:
            abs_prominence = max_intensity * 0.01 / float(sensitivity)
        else:
            abs_prominence = prominence * max_intensity
        abs_height = height * max_intensity if height else 0.0

        # 估算2θ步长
        step = self._estimate_step(data)

        distance_samples = max(1, int(distance / step))

        # 主峰检测
        find_kw = dict(height=abs_height, distance=distance_samples,
                       prominence=abs_prominence)
        if width is not None:
            find_kw["width"] = width
        find_kw.update(kwargs)
        peak_indices, properties = signal.find_peaks(
            data.intensity, **find_kw
        )
        main_indices = [int(i) for i in peak_indices]

        # 肩峰检测 (M05): 在 2×FWHM 窗口内找被主峰掩盖的次极大 / 隐藏峰
        if detect_shoulders and main_indices:
            fwhm_map = {
                i: (default_fwhm or self._estimate_fwhm(data, i) or 0.15)
                for i in main_indices
            }
            extra = self._detect_shoulders(
                data, main_indices, fwhm_map,
                smooth_window=shoulder_smooth_window,
            )
            main_indices = sorted(set(main_indices) | set(extra))

        # 提取峰属性
        peaks = []
        for idx in main_indices:
            peak = self._extract_peak_properties(data, idx, properties, step)
            peaks.append(peak)

        # 合并 Kα1/Kα2 双峰 (M05): 默认关, 保持旧行为
        if merge_kalpha_doublets:
            peaks = self._merge_kalpha_doublets(
                peaks, wavelength1=wavelength1, wavelength2=wavelength2
            )

        peak_list = PeakList(peaks=peaks, source="auto")
        peak_list.sort_by_two_theta()
        return peak_list

    # ------------------------------------------------------------------
    # M05 增强: 灵敏度 / 肩峰 / Kα 双峰
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_step(data: XRDData) -> float:
        if len(data.two_theta) > 1:
            step = float(np.mean(np.diff(data.two_theta)))
            return step if step > 0 else 0.01
        return 0.01

    @staticmethod
    def _second_derivative(
        y: np.ndarray, smooth_window: Optional[int] = None
    ) -> np.ndarray:
        """平滑二阶导数 (用于肩峰/隐藏峰检测)"""
        ys = np.asarray(y, dtype=float)
        n = len(ys)
        if smooth_window is None:
            smooth_window = 7
        w = int(smooth_window)
        if w < 5:
            w = 5
        if w % 2 == 0:
            w += 1
        if w >= n:
            d1 = np.gradient(ys)
            return np.gradient(d1)
        try:
            return signal.savgol_filter(ys, w, 3, deriv=2)
        except Exception:
            d1 = np.gradient(ys)
            return np.gradient(d1)

    def _detect_shoulders(
        self,
        data: XRDData,
        main_indices: list[int],
        fwhm_map: dict[int, float],
        min_ratio: float = 0.08,
        min_abs_ratio: float = 0.005,
        smooth_window: Optional[int] = None,
    ) -> list[int]:
        """肩峰检测: 在每个主峰 2×FWHM 窗口内找被掩盖的次极大或隐藏峰。

        规则:
          1. 窗口内排除主极大邻域后找次局部极大, 高度 ≥ max(主峰×min_ratio,
             全谱最大×min_abs_ratio) 则视为肩峰;
          2. 若窗口内没有次极大, 用平滑二阶导的极小值定位"隐藏肩峰"(重叠到
             看不出局部极大, 常见于 Kα 双峰/多相叠峰), 且该点高度同样过阈值;
          3. 与主峰 2θ 距离过近(< 0.35×FWHM)的候选丢弃 (数值抖动)。
        """
        x = data.two_theta
        y = data.intensity
        n = len(y)
        step = self._estimate_step(data)
        ymax = float(np.max(y)) if n else 0.0
        d2 = self._second_derivative(y, smooth_window)

        occupied = set(main_indices)
        extra: list[int] = []
        for idx in main_indices:
            fwhm = fwhm_map.get(idx) or 0.15
            w = max(int(2 * fwhm / step), 3)
            lo, hi = max(0, idx - w), min(n, idx + w + 1)
            base = float(y[idx])
            thr = max(base * min_ratio, ymax * min_abs_ratio)
            excl = max(int(0.5 * fwhm / step), 1)

            # 1) 次局部极大 (窗口内, 排除主极大邻域)
            cands = []
            for j in range(lo + 1, hi - 1):
                if abs(j - idx) <= excl:
                    continue
                if y[j - 1] <= y[j] and y[j] >= y[j + 1] and y[j] >= thr:
                    cands.append(j)
            if cands:
                extra.extend(cands)
                continue

            # 2) 隐藏峰: 平滑二阶导极小值点
            best = None
            min_dist = max(int(0.35 * fwhm / step), 2)
            for j in range(lo + 1, hi - 1):
                if abs(j - idx) <= min_dist:
                    continue
                if d2[j - 1] >= d2[j] and d2[j] <= d2[j + 1]:
                    if y[j] >= thr and (best is None or y[j] > y[best]):
                        best = j
            if best is not None:
                extra.append(best)

        # 去重 + 过滤过近候选
        out: list[int] = []
        for j in extra:
            if j in occupied:
                continue
            near = False
            for k in main_indices:
                fk = fwhm_map.get(k) or 0.15
                if abs(x[k] - x[j]) < 0.35 * fk:
                    near = True
                    break
            if near:
                continue
            occupied.add(j)
            out.append(j)
        return out

    @staticmethod
    def _kalpha_doublet_separation(
        two_theta: float, wavelength1: float, wavelength2: float
    ) -> float:
        """Kα1 峰位处 Kα1-Kα2 双峰间距 Δ2θ (度)"""
        th = np.radians(two_theta / 2.0)
        ratio = wavelength2 / wavelength1
        arg = ratio * np.sin(th)
        arg = float(np.clip(arg, -1.0, 1.0))
        return float(np.degrees(2.0 * (np.arcsin(arg) - th)))

    def _merge_kalpha_doublets(
        self, peaks: list, wavelength1: float = 1.5406, wavelength2: float = 1.5444
    ) -> list:
        """合并相邻 Kα1/Kα2 双峰: 保留 Kα1 (低角、较强) 主峰。

        判定: 高角侧邻峰与低角峰位差 ≈ Kα1-Kα2 间距 (容差 0.5×FWHM),
        且强度比约在 [0.4, 1.0] (Kα2 ≈ 0.5×Kα1)。
        """
        if len(peaks) < 2:
            return list(peaks)
        ordered = sorted(peaks, key=lambda p: p.two_theta)
        out: list = []
        i = 0
        n = len(ordered)
        while i < n:
            p1 = ordered[i]
            if i + 1 < n:
                p2 = ordered[i + 1]
                dtt = p2.two_theta - p1.two_theta
                if dtt > 0:
                    sep = self._kalpha_doublet_separation(
                        p1.two_theta, wavelength1, wavelength2
                    )
                    fwhm = max(float(getattr(p1, "fwhm", 0.0) or 0.0), 0.1)
                    ratio = float(p2.intensity) / max(float(p1.intensity), 1e-6)
                    if abs(dtt - sep) <= 0.5 * fwhm and 0.4 <= ratio <= 1.0:
                        out.append(p1)  # 保留 Kα1
                        i += 2
                        continue
            out.append(p1)
            i += 1
        return out

    def _extract_peak_properties(
        self,
        data: XRDData,
        index: int,
        properties: dict,
        step: float,
    ) -> Peak:
        """提取单个峰的属性"""
        two_theta = data.two_theta[index]
        intensity = data.intensity[index]

        # 从prominences估算FWHM
        fwhm = 0.0
        if "widths" in properties:
            widths = properties["widths"]
            width_samples = widths[list(properties["peak_ids"]).index(index)]
            fwhm = width_samples * step

        # 如果没有FWHM信息，用半高宽方法
        if fwhm == 0:
            fwhm = self._estimate_fwhm(data, index)

        # 估算峰面积
        area = self._estimate_peak_area(data, index, fwhm)

        return Peak(
            two_theta=two_theta,
            intensity=float(intensity),
            fwhm=fwhm,
            area=area,
            d_spacing=self._calc_d_spacing(two_theta, data.wavelength),
        )

    @staticmethod
    def _estimate_fwhm(data: XRDData, index: int) -> float:
        """从峰位置估算FWHM"""
        half_max = data.intensity[index] / 2.0

        # 向左找半高点
        left_idx = index
        while left_idx > 0 and data.intensity[left_idx] > half_max:
            left_idx -= 1

        # 线性插值
        if left_idx < index and left_idx >= 0:
            if data.intensity[left_idx] <= half_max and left_idx + 1 <= index:
                frac = (half_max - data.intensity[left_idx]) / (
                    data.intensity[left_idx + 1] - data.intensity[left_idx]
                )
                left_2theta = data.two_theta[left_idx] + frac * (
                    data.two_theta[left_idx + 1] - data.two_theta[left_idx]
                )
            else:
                left_2theta = data.two_theta[left_idx]
        else:
            left_2theta = data.two_theta[max(0, index - 1)]

        # 向右找半高点
        right_idx = index
        while right_idx < len(data.intensity) - 1 and data.intensity[right_idx] > half_max:
            right_idx += 1

        if right_idx > index and right_idx < len(data.intensity):
            if data.intensity[right_idx] <= half_max and right_idx - 1 >= index:
                frac = (half_max - data.intensity[right_idx - 1]) / (
                    data.intensity[right_idx] - data.intensity[right_idx - 1]
                )
                right_2theta = data.two_theta[right_idx - 1] + frac * (
                    data.two_theta[right_idx] - data.two_theta[right_idx - 1]
                )
            else:
                right_2theta = data.two_theta[min(right_idx, len(data.two_theta) - 1)]
        else:
            right_2theta = data.two_theta[min(len(data.two_theta) - 1, index + 1)]

        return abs(right_2theta - left_2theta)

    @staticmethod
    def _estimate_peak_area(
        data: XRDData,
        index: int,
        fwhm: float,
    ) -> float:
        """估算峰面积"""
        # 取峰附近±2*FWHM范围
        range_2theta = 2 * fwhm
        mask = np.abs(data.two_theta - data.two_theta[index]) <= range_2theta
        if np.sum(mask) > 1:
            return float(np.trapezoid(data.intensity[mask], data.two_theta[mask]))
        return 0.0

    @staticmethod
    def _calc_d_spacing(two_theta: float, wavelength: float) -> float:
        """计算d-spacing"""
        theta_rad = np.radians(two_theta / 2.0)
        sin_theta = np.sin(theta_rad)
        if sin_theta > 0:
            return wavelength / (2.0 * sin_theta)
        return 0.0

    # ------------------------------------------------------------------
    # 峰拟合
    # ------------------------------------------------------------------

    def fit_peaks(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        model: str = "voigt",
    ) -> tuple[PeakList, dict]:
        """对已检测的峰进行精修拟合

        Args:
            data: XRD数据
            peaks: 峰列表 (如果为None，先自动检测)
            model: 峰形模型 (gaussian, lorentzian, voigt, pseudo_voigt)

        Returns:
            (精修后的峰列表, 拟合统计信息)
        """
        if peaks is None or len(peaks) == 0:
            peaks = self.find_peaks(data)

        fitted_peaks = []
        total_residuals = np.zeros_like(data.intensity)

        for peak in peaks:
            try:
                fitted_peak, residuals = self._fit_single_peak(
                    data, peak, model
                )
                fitted_peaks.append(fitted_peak)
                total_residuals += residuals
            except Exception:
                # 拟合失败时保留原峰
                fitted_peaks.append(peak)

        # 计算整体R²
        ss_res = np.sum(total_residuals**2)
        ss_tot = np.sum((data.intensity - np.mean(data.intensity))**2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        result_peaks = PeakList(peaks=fitted_peaks, source="fit")
        stats = {
            "r_squared": r_squared,
            "num_peaks": len(fitted_peaks),
            "model": model,
        }

        return result_peaks, stats

    def _fit_single_peak(
        self,
        data: XRDData,
        peak: Peak,
        model: str = "voigt",
    ) -> tuple[Peak, np.ndarray]:
        """拟合单个峰"""
        # 确定拟合范围
        fwhm = max(peak.fwhm, 0.1)
        range_2theta = 3 * fwhm
        mask = np.abs(data.two_theta - peak.two_theta) <= range_2theta

        if np.sum(mask) < 5:
            return peak, np.zeros_like(data.intensity)

        x = data.two_theta[mask]
        y = data.intensity[mask]

        # 初始参数估计
        amplitude = peak.intensity
        center = peak.two_theta
        sigma = fwhm / 2.355  # FWHM -> sigma
        gamma = fwhm / 2.0  # FWHM -> lorentzian gamma

        # 设置初始参数和边界
        if model == "gaussian":
            p0 = [amplitude, center, sigma]
            bounds = (
                [0, center - 2 * fwhm, 0.001],
                [amplitude * 3, center + 2 * fwhm, fwhm * 5],
            )
            popt = self._fit_gaussian(x, y, p0, bounds)
            fitted_peak = Peak(
                two_theta=float(popt[1]),
                intensity=float(popt[0]),
                fwhm=float(popt[2] * 2.355),
                d_spacing=self._calc_d_spacing(float(popt[1]), data.wavelength),
                fit_params={"model": "gaussian", "sigma": float(popt[2])},
            )
            fitted_curve = self._gaussian(x, *popt)

        elif model == "lorentzian":
            p0 = [amplitude, center, gamma]
            bounds = (
                [0, center - 2 * fwhm, 0.001],
                [amplitude * 3, center + 2 * fwhm, fwhm * 5],
            )
            popt = self._fit_lorentzian(x, y, p0, bounds)
            fitted_peak = Peak(
                two_theta=float(popt[1]),
                intensity=float(popt[0]),
                fwhm=float(popt[2] * 2),
                d_spacing=self._calc_d_spacing(float(popt[1]), data.wavelength),
                fit_params={"model": "lorentzian", "gamma": float(popt[2])},
            )
            fitted_curve = self._lorentzian(x, *popt)

        elif model == "voigt":
            p0 = [amplitude, center, sigma, gamma]
            bounds = (
                [0, center - 2 * fwhm, 0.001, 0.001],
                [amplitude * 3, center + 2 * fwhm, fwhm * 5, fwhm * 5],
            )
            popt = self._fit_voigt(x, y, p0, bounds)
            fitted_peak = Peak(
                two_theta=float(popt[1]),
                intensity=float(popt[0]),
                fwhm=float(popt[2] * 2.355),
                d_spacing=self._calc_d_spacing(float(popt[1]), data.wavelength),
                fit_params={
                    "model": "voigt",
                    "sigma": float(popt[2]),
                    "gamma": float(popt[3]),
                },
            )
            fitted_curve = self._voigt(x, *popt)

        else:  # pseudo_voigt
            fwhm_p = fwhm
            eta = 0.5
            p0 = [amplitude, center, fwhm_p, eta]
            bounds = (
                [0, center - 2 * fwhm, 0.001, 0],
                [amplitude * 3, center + 2 * fwhm, fwhm * 5, 1],
            )
            popt = self._fit_pseudo_voigt(x, y, p0, bounds)
            fitted_peak = Peak(
                two_theta=float(popt[1]),
                intensity=float(popt[0]),
                fwhm=float(popt[2]),
                d_spacing=self._calc_d_spacing(float(popt[1]), data.wavelength),
                fit_params={
                    "model": "pseudo_voigt",
                    "fwhm": float(popt[2]),
                    "eta": float(popt[3]),
                },
            )
            fitted_curve = self._pseudo_voigt(x, *popt)

        # 计算残差
        residuals = np.zeros_like(data.intensity)
        residuals[mask] = y - fitted_curve

        # 计算峰面积
        fitted_peak.area = float(np.trapezoid(fitted_curve, x))

        # 保留hkl和phase信息
        fitted_peak.hkl = peak.hkl
        fitted_peak.phase = peak.phase

        return fitted_peak, residuals

    # ------------------------------------------------------------------
    # 峰形函数
    # ------------------------------------------------------------------

    @staticmethod
    def _gaussian(x: np.ndarray, a: float, mu: float, sigma: float) -> np.ndarray:
        return a * np.exp(-0.5 * ((x - mu) / sigma) ** 2)

    @staticmethod
    def _lorentzian(x: np.ndarray, a: float, mu: float, gamma: float) -> np.ndarray:
        return a * gamma**2 / ((x - mu) ** 2 + gamma**2)

    @staticmethod
    def _voigt(
        x: np.ndarray, a: float, mu: float, sigma: float, gamma: float
    ) -> np.ndarray:
        from scipy.special import wofz
        z = ((x - mu) + 1j * gamma) / (sigma * np.sqrt(2))
        return a * np.real(wofz(z)) / (sigma * np.sqrt(2 * np.pi))

    @staticmethod
    def _pseudo_voigt(
        x: np.ndarray, a: float, mu: float, fwhm: float, eta: float
    ) -> np.ndarray:
        sigma = fwhm / 2.355
        gamma = fwhm / 2.0
        gauss = eta * PeakFinder._gaussian(x, a, mu, sigma)
        lorentz = (1 - eta) * PeakFinder._lorentzian(x, a, mu, gamma)
        return gauss + lorentz

    # ------------------------------------------------------------------
    # 拟合函数
    # ------------------------------------------------------------------

    @staticmethod
    def _fit_gaussian(
        x: np.ndarray,
        y: np.ndarray,
        p0: list,
        bounds: tuple,
    ) -> np.ndarray:
        return curve_fit(
            lambda x_, a, mu, sigma: PeakFinder._gaussian(x_, a, mu, sigma),
            x, y, p0=p0, bounds=bounds, maxfev=10000,
        )[0]

    @staticmethod
    def _fit_lorentzian(
        x: np.ndarray,
        y: np.ndarray,
        p0: list,
        bounds: tuple,
    ) -> np.ndarray:
        return curve_fit(
            lambda x_, a, mu, gamma: PeakFinder._lorentzian(x_, a, mu, gamma),
            x, y, p0=p0, bounds=bounds, maxfev=10000,
        )[0]

    @staticmethod
    def _fit_voigt(
        x: np.ndarray,
        y: np.ndarray,
        p0: list,
        bounds: tuple,
    ) -> np.ndarray:
        return curve_fit(
            lambda x_, a, mu, sigma, gamma: PeakFinder._voigt(x_, a, mu, sigma, gamma),
            x, y, p0=p0, bounds=bounds, maxfev=10000,
        )[0]

    @staticmethod
    def _fit_pseudo_voigt(
        x: np.ndarray,
        y: np.ndarray,
        p0: list,
        bounds: tuple,
    ) -> np.ndarray:
        return curve_fit(
            lambda x_, a, mu, fwhm, eta: PeakFinder._pseudo_voigt(x_, a, mu, fwhm, eta),
            x, y, p0=p0, bounds=bounds, maxfev=10000,
        )[0]
