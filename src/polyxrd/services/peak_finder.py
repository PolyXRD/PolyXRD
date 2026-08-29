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
        **kwargs,
    ) -> PeakList:
        """自动峰检测

        Args:
            data: XRD数据
            height: 最小峰高 (相对最大值)
            distance: 峰之间最小2θ距离 (度)
            prominence: 峰显著性
            width: 最小峰宽
            **kwargs: 传递给scipy.signal.find_peaks的参数

        Returns:
            PeakList
        """
        # 归一化高度
        max_intensity = np.max(data.intensity)
        if max_intensity == 0:
            return PeakList(source="auto")

        abs_height = height * max_intensity

        # 估算2θ步长
        if len(data.two_theta) > 1:
            step = np.mean(np.diff(data.two_theta))
        else:
            step = 0.01

        distance_samples = max(1, int(distance / step))

        # 使用scipy find_peaks
        peak_indices, properties = signal.find_peaks(
            data.intensity,
            height=abs_height,
            distance=distance_samples,
            prominence=prominence * max_intensity,
            width=width,
            **kwargs,
        )

        # 提取峰属性
        peaks = []
        for idx in peak_indices:
            peak = self._extract_peak_properties(
                data, idx, properties, step
            )
            peaks.append(peak)

        peak_list = PeakList(peaks=peaks, source="auto")
        peak_list.sort_by_two_theta()
        return peak_list

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
