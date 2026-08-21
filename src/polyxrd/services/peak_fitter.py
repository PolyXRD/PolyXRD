"""
峰拟合服务
==========
对检测到的峰进行精修拟合分析。
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from polyxrd.models.peak import FitResult, Peak, PeakList
from polyxrd.models.xrd_data import XRDData


class PeakFitter:
    """XRD峰拟合器

    支持多种峰形模型：
    - gaussian: 高斯函数
    - lorentzian: 洛伦兹函数
    - voigt: Voigt函数
    - pseudo_voigt: 伪Voigt
    - emg: 指数修正高斯

    使用lmfit库进行非线性最小二乘拟合。

    Usage:
        fitter = PeakFitter()
        result = fitter.fit_multiple_peaks(data, peaks, model='voigt')
    """

    def __init__(self) -> None:
        self._model_funcs = {
            "gaussian": self._gaussian,
            "lorentzian": self._lorentzian,
            "voigt": self._voigt,
            "pseudo_voigt": self._pseudo_voigt,
            "emg": self._emg,
        }

    def fit_peak(
        self,
        data: XRDData,
        peak: Peak,
        model: str = "voigt",
        fit_range: Optional[tuple[float, float]] = None,
        **kwargs,
    ) -> FitResult:
        """拟合单个峰

        Args:
            data: XRD数据
            peak: 待拟合的峰（提供初始参数）
            model: 峰形模型
            fit_range: 拟合范围 (2θ_min, 2θ_max)，默认峰位±2°
            **kwargs: 拟合选项

        Returns:
            FitResult: 拟合结果
        """
        if model not in self._model_funcs:
            raise ValueError(f"未知的峰形模型: {model}")

        # 确定拟合范围
        if fit_range is None:
            fwhm = peak.fwhm if peak.fwhm > 0 else 0.3
            margin = max(2.0, fwhm * 5)
            fit_range = (peak.two_theta - margin, peak.two_theta + margin)

        # 截取数据
        mask = (data.two_theta >= fit_range[0]) & (data.two_theta <= fit_range[1])
        x_fit = data.two_theta[mask]
        y_fit = data.intensity[mask]

        if len(x_fit) < 5:
            raise ValueError("拟合数据点不足（至少需要5个点）")

        # 使用lmfit拟合
        try:
            import lmfit.models as lm_models

            model_obj = self._create_lmfit_model(model)
            params = self._create_initial_params(model, peak, x_fit, y_fit)

            result = model_obj.fit(y_fit, params, x=x_fit)

            # 解析结果
            fitted_peak = self._parse_lmfit_result(result, peak, model)
            fitted_peak.fitted = True

            # 计算R²
            y_pred = result.best_fit
            ss_res = np.sum((y_fit - y_pred) ** 2)
            ss_tot = np.sum((y_fit - np.mean(y_fit)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

            residuals = (y_fit - y_pred).tolist()

            return FitResult(
                peaks=[fitted_peak],
                r_squared=r_squared,
                chi_squared=result.chisqr if result.chisqr else 0,
                residuals=residuals,
                converged=result.success,
                num_iterations=result.nfev if hasattr(result, "nfev") else 0,
            )

        except ImportError:
            # 如果lmfit不可用，使用scipy.optimize
            return self._fit_with_scipy(x_fit, y_fit, peak, model, **kwargs)

    def fit_multiple_peaks(
        self,
        data: XRDData,
        peaks: list[Peak],
        model: str = "voigt",
        global_fit: bool = True,
        **kwargs,
    ) -> FitResult:
        """多峰同时拟合

        Args:
            data: XRD数据
            peaks: 待拟合的峰列表
            model: 峰形模型
            global_fit: 是否全局拟合（同时拟合所有峰）
            **kwargs: 拟合选项

        Returns:
            FitResult: 拟合结果
        """
        if global_fit and len(peaks) > 1:
            return self._fit_global(data, peaks, model)

        # 逐个拟合
        fitted_peaks = []
        all_residuals = []

        for peak in peaks:
            try:
                result = self.fit_peak(data, peak, model)
                fitted_peaks.extend(result.peaks)
                all_residuals.extend(result.residuals)
            except Exception:
                # 保持原始峰
                fitted_peaks.append(peak)

        # 计算总体R²
        y_all = data.intensity
        y_pred = np.zeros_like(y_all)
        for peak in fitted_peaks:
            fwhm = peak.fwhm if peak.fwhm > 0 else 0.3
            sigma = fwhm / 2.355
            y_pred += peak.intensity * np.exp(
                -0.5 * ((data.two_theta - peak.two_theta) / sigma) ** 2
            )

        ss_res = np.sum((y_all - y_pred) ** 2)
        ss_tot = np.sum((y_all - np.mean(y_all)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        return FitResult(
            peaks=fitted_peaks,
            r_squared=r_squared,
            chi_squared=0,
            residuals=all_residuals,
            converged=True,
            num_iterations=len(peaks),
        )

    def _fit_global(
        self,
        data: XRDData,
        peaks: list[Peak],
        model: str,
    ) -> FitResult:
        """全局多峰拟合"""
        try:
            import lmfit.models as lm_models

            # 创建复合模型
            model_obj = None
            params = None

            for i, peak in enumerate(peaks):
                component = self._create_lmfit_model(model, prefix=f"p{i}_")
                if model_obj is None:
                    model_obj = component
                else:
                    model_obj = model_obj + component

                p = self._create_initial_params(model, peak, data.two_theta, data.intensity, prefix=f"p{i}_")
                if params is None:
                    params = p
                else:
                    params.update(p)

            if model_obj is None or params is None:
                raise ValueError("无法创建拟合模型")

            result = model_obj.fit(data.intensity, params, x=data.two_theta)

            # 解析结果
            fitted_peaks = []
            for i, peak in enumerate(peaks):
                prefix = f"p{i}_"
                fitted_peak = Peak(
                    two_theta=result.params[f"{prefix}center"].value,
                    intensity=result.params[f"{prefix}amplitude"].value,
                    fwhm=result.params[f"{prefix}sigma"].value * 2.355
                    if f"{prefix}sigma" in result.params
                    else peak.fwhm,
                    d_spacing=peak.d_spacing,
                    hkl=peak.hkl,
                    phase=peak.phase,
                    fitted=True,
                )
                fitted_peak.profile_params = {
                    k: v.value
                    for k, v in result.params.items()
                    if k.startswith(prefix)
                }
                fitted_peaks.append(fitted_peak)

            y_pred = result.best_fit
            ss_res = np.sum((data.intensity - y_pred) ** 2)
            ss_tot = np.sum((data.intensity - np.mean(data.intensity)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

            return FitResult(
                peaks=fitted_peaks,
                r_squared=r_squared,
                chi_squared=result.chisqr if result.chisqr else 0,
                residuals=(data.intensity - y_pred).tolist(),
                converged=result.success,
                num_iterations=result.nfev if hasattr(result, "nfev") else 0,
            )

        except ImportError:
            # 回退到逐个拟合
            return self.fit_multiple_peaks(data, peaks, model, global_fit=False)

    def _fit_with_scipy(
        self,
        x: np.ndarray,
        y: np.ndarray,
        peak: Peak,
        model: str,
        **kwargs,
    ) -> FitResult:
        """使用scipy.optimize进行拟合"""
        from scipy.optimize import curve_fit

        func = self._model_funcs[model]

        # 初始参数
        fwhm = peak.fwhm if peak.fwhm > 0 else 0.3
        sigma = fwhm / 2.355

        if model in ("gaussian", "lorentzian", "voigt", "pseudo_voigt", "emg"):
            p0 = [peak.intensity, peak.two_theta, sigma]

            # 边界约束
            bounds = (
                [0, x.min(), 0.001],
                [peak.intensity * 1.5, x.max(), 5.0],
            )

            try:
                popt, pcov = curve_fit(func, x, y, p0=p0, bounds=bounds, maxfev=10000)
                fitted_peak = Peak(
                    two_theta=float(popt[1]),
                    intensity=float(popt[0]),
                    fwhm=float(popt[2] * 2.355) if model == "gaussian" else float(popt[2] * 2.0),
                    d_spacing=peak.d_spacing,
                    hkl=peak.hkl,
                    phase=peak.phase,
                    fitted=True,
                    profile_params={"amplitude": float(popt[0]), "center": float(popt[1]), "width": float(popt[2])},
                )

                y_pred = func(x, *popt)
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = np.sum((y - np.mean(y)) ** 2)
                r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

                return FitResult(
                    peaks=[fitted_peak],
                    r_squared=r_squared,
                    chi_squared=float(np.sum((y - y_pred) ** 2) / len(y)),
                    residuals=(y - y_pred).tolist(),
                    converged=True,
                    num_iterations=1000,
                )
            except RuntimeError:
                return FitResult(peaks=[peak], converged=False)

        return FitResult(peaks=[peak], converged=False)

    def _create_lmfit_model(self, model_type: str, prefix: str = ""):
        """创建lmfit模型"""
        import lmfit.models as lm_models

        models = {
            "gaussian": lm_models.GaussianModel,
            "lorentzian": lm_models.LorentzianModel,
            "voigt": lm_models.VoigtModel,
            "pseudo_voigt": lm_models.PseudoVoigtModel,
            "emg": lm_models.ExponentialGaussianModel,
        }

        model_class = models.get(model_type)
        if model_class is None:
            raise ValueError(f"lmfit中不存在模型: {model_type}")

        return model_class(prefix=prefix)

    def _create_initial_params(
        self,
        model_type: str,
        peak: Peak,
        x: np.ndarray,
        y: np.ndarray,
        prefix: str = "",
    ):
        """创建初始参数"""
        import lmfit.models as lm_models

        model_obj = self._create_lmfit_model(model_type, prefix)

        fwhm = peak.fwhm if peak.fwhm > 0 else 0.3

        params = model_obj.make_params()

        # 设置初始值
        params[f"{prefix}amplitude"].set(value=peak.intensity, min=0, max=peak.intensity * 2)
        params[f"{prefix}center"].set(
            value=peak.two_theta,
            min=peak.two_theta - 1.0,
            max=peak.two_theta + 1.0,
        )

        # 根据模型类型设置宽度参数
        if model_type == "gaussian":
            sigma = fwhm / 2.355
            params[f"{prefix}sigma"].set(value=sigma, min=0.001, max=sigma * 5)
        elif model_type == "lorentzian":
            params[f"{prefix}sigma"].set(value=fwhm / 2, min=0.001, max=fwhm * 5)
        elif model_type == "voigt":
            sigma = fwhm / 2.355
            params[f"{prefix}sigma"].set(value=sigma, min=0.001, max=sigma * 5)
            params[f"{prefix}gamma"].set(value=fwhm / 2, min=0.001, max=fwhm * 5)
        elif model_type == "pseudo_voigt":
            sigma = fwhm / 2.355
            params[f"{prefix}sigma"].set(value=sigma, min=0.001, max=sigma * 5)
            params[f"{prefix}fraction"].set(value=0.5, min=0, max=1)
        elif model_type == "emg":
            sigma = fwhm / 2.355
            params[f"{prefix}sigma"].set(value=sigma, min=0.001, max=sigma * 5)
            params[f"{prefix}tau"].set(value=1.0, min=0.01, max=100)

        # 添加可能的额外参数
        try:
            params[f"{prefix}offset"].set(value=0, vary=True, min=-np.max(y) * 0.1, max=np.max(y) * 0.1)
        except KeyError:
            pass

        return params

    def _parse_lmfit_result(self, result, peak: Peak, model_type: str) -> Peak:
        """解析lmfit拟合结果"""
        two_theta = result.params["center"].value
        amplitude = result.params["amplitude"].value

        # 计算FWHM
        if model_type == "gaussian":
            fwhm = result.params["sigma"].value * 2.355
        elif model_type == "lorentzian":
            fwhm = result.params["sigma"].value * 2.0
        elif model_type == "voigt":
            sigma = result.params["sigma"].value
            gamma = result.params["gamma"].value
            fwhm = 2 * np.sqrt(2 * np.log(2)) * sigma * np.sqrt(1 + (gamma / (sigma * np.sqrt(2 * np.log(2)))) ** 2)
        elif model_type == "pseudo_voigt":
            sigma = result.params["sigma"].value
            fwhm = sigma * 2.355  # 近似
        else:
            fwhm = peak.fwhm

        return Peak(
            two_theta=float(two_theta),
            intensity=float(amplitude),
            fwhm=float(fwhm),
            d_spacing=peak.d_spacing,
            hkl=peak.hkl,
            phase=peak.phase,
            fitted=True,
            profile_params={k: v.value for k, v in result.params.items()},
        )

    # ------------------------------------------------------------------
    # 峰形函数
    # ------------------------------------------------------------------

    @staticmethod
    def _gaussian(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
        """高斯函数"""
        return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)

    @staticmethod
    def _lorentzian(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
        """洛伦兹函数"""
        return amplitude * sigma**2 / ((x - center) ** 2 + sigma**2)

    @staticmethod
    def _voigt(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
        """Voigt函数（近似）"""
        from scipy.special import wofz

        z = ((x - center) + 1j * sigma) / (sigma * np.sqrt(2))
        return amplitude * np.real(wofz(z)) / (sigma * np.sqrt(2 * np.pi))

    @staticmethod
    def _pseudo_voigt(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
        """伪Voigt（线性组合近似）"""
        fG = 2.0 * sigma * np.sqrt(2 * np.log(2))
        fL = 2.0 * sigma
        f = (fG**5 + 2.69269 * fG**4 * fL + 2.42843 * fG**3 * fL**2 +
             4.47163 * fG**2 * fL**3 + 0.07842 * fG * fL**4 + fL**5) ** 0.2
        eta = 1.36603 * (fL / f) - 0.47719 * (fL / f)**2 + 0.11116 * (fL / f)**3

        gauss_part = np.exp(-2 * np.log(2) * ((x - center) / (f / 2)) ** 2)
        lorentz_part = 1 / (1 + ((x - center) / (f / 2)) ** 2)

        return amplitude * (eta * lorentz_part + (1 - eta) * gauss_part)

    @staticmethod
    def _emg(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
        """指数修正高斯"""
        tau = 1.0
        u = (sigma / tau - (x - center) / sigma) / np.sqrt(2)
        from scipy.special import erf

        return (amplitude / tau) * np.exp(0.5 * (sigma / tau) ** 2) * (1 - erf(u))
