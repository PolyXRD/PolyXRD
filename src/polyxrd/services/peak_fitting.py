"""
轮廓拟合服务 (M07, Sprint 2)
=============================
用 Pseudo-Voigt 峰形对衍射峰做精确拟合, 输出精确峰位/积分强度/半高宽,
供 FoM 增强 (M10)、RIR 定量 (M13) 与峰型匹配使用。

策略:
  - 单峰拟合: 局部窗口内 least_squares 拟合 PV(高度,中心,半高宽,eta)。
  - 全谱拟合: 先把相邻峰按窗口重叠合并成"重叠簇" (间距 < 2×FWHM),
    每个簇联合拟合 (避免重叠峰相互拉扯); 各簇间互不干扰。
  - 背景: 拟合簇内加常数背景项 (取窗口两侧低值估初值)。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

import numpy as np
from scipy.optimize import least_squares

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.peak_finder import PeakFinder


class ProfileFitter:
    """基于 Pseudo-Voigt 的峰形拟合。"""

    @staticmethod
    def pseudo_voigt(x, height, center, fwhm, eta) -> np.ndarray:
        """Pseudo-Voigt 峰形 (高度参数化)。

        eta=1 → 纯高斯; eta=0 → 纯洛伦兹; 0<eta<1 → 混合。
        """
        x = np.asarray(x, dtype=float)
        if fwhm <= 0:
            return np.zeros_like(x)
        sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))   # 高斯 sigma
        gamma = fwhm / 2.0                                   # 洛伦兹半宽
        g = np.exp(-0.5 * ((x - center) / sigma) ** 2)
        l = 1.0 / (1.0 + ((x - center) / gamma) ** 2)
        return height * (eta * g + (1.0 - eta) * l)

    # ── 单峰拟合 ─────────────────────────────────────────────

    def fit_single_peak(
        self,
        xrd: XRDData,
        center: float,
        width: Optional[float] = None,
        eta0: float = 0.5,
    ) -> Peak:
        """在 center±3×width 窗口内拟合单峰, 返回精确峰参数。"""
        x = np.asarray(xrd.two_theta, dtype=float)
        y = np.asarray(xrd.intensity, dtype=float)
        if width is None or width <= 0:
            width = 0.2
        w = float(width)
        mask = np.abs(x - center) <= 3.0 * w
        if int(np.sum(mask)) < 5:
            idx = int(np.argmin(np.abs(x - center)))
            return Peak(two_theta=float(center),
                        intensity=float(y[idx]) if idx < len(y) else 0.0,
                        fwhm=w)
        xs, ys = x[mask], y[mask]
        height0 = max(float(np.max(ys)), 1e-6)
        bg0 = float(np.percentile(ys, 5))
        p0 = [height0, float(center), w, eta0, bg0]
        lo = [0.0, float(center) - 2 * w, 0.01, 0.0, 0.0]
        hi = [height0 * 3, float(center) + 2 * w, 5 * w, 1.0,
              float(np.max(ys))]
        try:
            sol = least_squares(
                lambda p: self._pv_with_bg(p, xs) - ys,
                p0, bounds=(lo, hi), max_nfev=200,
            )
            p = sol.x
        except Exception:
            p = p0
        return self._make_peak(p, xrd.wavelength)

    # ── 全谱 (重叠簇联合) 拟合 ───────────────────────────────

    def fit_profile(
        self,
        xrd: XRDData,
        peaks: Optional[PeakList] = None,
        window_factor: float = 3.0,
    ) -> PeakList:
        """全谱多峰拟合: 按窗口重叠把峰分组为簇, 簇内联合拟合。

        Args:
            xrd: 原始谱
            peaks: 峰表 (None → 自动峰检测)
            window_factor: 簇合并判据 = window_factor × FWHM
        Returns:
            拟合后的 PeakList (center/height/fwhm/area 均来自模型)
        """
        x = np.asarray(xrd.two_theta, dtype=float)
        y = np.asarray(xrd.intensity, dtype=float)
        if peaks is None or len(peaks) == 0:
            peaks = PeakFinder().find_peaks(xrd)
        ordered = sorted(peaks.peaks, key=lambda p: p.two_theta)
        if not ordered:
            return PeakList(peaks=[], source="fit")

        # 1) 分组: 按窗口 (window_factor×fwhm) 是否重叠合并
        clusters: list[list[Peak]] = []
        for pk in ordered:
            w = max(float(pk.fwhm or 0.0), 0.1)
            if clusters:
                last = clusters[-1][-1]
                if pk.two_theta - last.two_theta <= window_factor * w:
                    clusters[-1].append(pk)
                    continue
            clusters.append([pk])

        fitted: list[Peak] = []
        for cl in clusters:
            fitted.extend(self._fit_cluster_joint(xrd, cl))
        out = PeakList(peaks=fitted, source="fit")
        out.sort_by_two_theta()
        return out

    def _fit_cluster_joint(self, xrd: XRDData, cluster: list[Peak]) -> list:
        """对窗口重叠的一簇峰做联合最小二乘 (避免相互拉扯)。"""
        x = np.asarray(xrd.two_theta, dtype=float)
        y = np.asarray(xrd.intensity, dtype=float)
        m = len(cluster)
        if m == 1:
            return [self.fit_single_peak(
                xrd, cluster[0].two_theta,
                width=max(float(cluster[0].fwhm or 0.0), 0.1))]

        ctr = [float(p.two_theta) for p in cluster]
        fw = [max(float(p.fwhm or 0.0), 0.1) for p in cluster]
        margin = 3.0 * max(fw)
        mask = (x >= min(ctr) - margin) & (x <= max(ctr) + margin)
        if int(np.sum(mask)) < 5 * m:
            return [self.fit_single_peak(
                xrd, p.two_theta, width=max(float(p.fwhm or 0.0), 0.1))
                for p in cluster]
        xs, ys = x[mask], y[mask]

        # 参数布局: 每峰 [height, center, fwhm, eta] + 全局 [bg]
        p0: list[float] = []
        lo: list[float] = []
        hi: list[float] = []
        for k in range(m):
            seg = ys[(xs >= ctr[k] - fw[k]) & (xs <= ctr[k] + fw[k])]
            h0 = max(float(np.max(seg)) if len(seg) else 0.0, 1e-6)
            p0 += [h0, ctr[k], fw[k], 0.5]
            lo += [0.0, ctr[k] - 2 * fw[k], 0.01, 0.0]
            hi += [h0 * 3, ctr[k] + 2 * fw[k], 5 * fw[k], 1.0]
        bg0 = float(np.percentile(ys, 5))
        p0.append(bg0)
        lo.append(0.0)
        hi.append(float(np.max(ys)))

        def residual(p):
            model = p[-1] + np.zeros_like(xs)
            for k in range(m):
                model += self.pseudo_voigt(
                    xs, p[4 * k], p[4 * k + 1], p[4 * k + 2], p[4 * k + 3])
            return model - ys

        try:
            sol = least_squares(residual, p0, bounds=(lo, hi), max_nfev=500)
            p = sol.x
        except Exception:
            p = p0

        out = []
        for k in range(m):
            out.append(self._make_peak(p[4 * k:4 * k + 4], xrd.wavelength))
        return out

    # ── 模型重建 / 拟合优度 ──────────────────────────────────

    @staticmethod
    def model_spectrum(
        grid: np.ndarray, peaks: PeakList, background: float = 0.0
    ) -> np.ndarray:
        """由峰参数重建谱: Σ PV + 常数背景。"""
        g = np.zeros_like(grid, dtype=float)
        for pk in peaks.peaks:
            eta = float((pk.fit_params or {}).get("eta", 0.5))
            fwhm = max(float(pk.fwhm or 0.0), 1e-6)
            g += ProfileFitter.pseudo_voigt(
                grid, float(pk.intensity), float(pk.two_theta), fwhm, eta)
        return g + float(background)

    @staticmethod
    def goodness_of_fit(xrd: XRDData, fitted_y: np.ndarray) -> dict:
        """Rwp / χ² / R² 拟合优度。"""
        y = np.asarray(xrd.intensity, dtype=float)
        f = np.asarray(fitted_y, dtype=float)
        n = len(y)
        if n == 0:
            return {"rwp": 999.0, "chi2": 999.0, "r2": 0.0}
        resid = y - f
        denom = float(np.sum(y ** 2))
        rwp = float(np.sqrt(np.sum(resid ** 2) / denom)) if denom > 1e-12 else 999.0
        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        dof = max(n - 1, 1)
        chi2 = float(ss_res / dof / max(np.mean(y), 1e-12)) if n > 1 else 999.0
        return {"rwp": rwp * 100.0, "chi2": chi2, "r2": r2}

    # ── 内部 ─────────────────────────────────────────────────

    @staticmethod
    def _pv_with_bg(p, x):
        height, center, fwhm, eta, bg = p
        return ProfileFitter.pseudo_voigt(x, height, center, fwhm, eta) + bg

    @staticmethod
    def _make_peak(p, wavelength: float) -> Peak:
        # 兼容 4 参 (height,center,fwhm,eta) 与 5 参 (…,bg)
        if len(p) == 5:
            height, center, fwhm, eta, bg = p
        else:
            height, center, fwhm, eta = p
            bg = 0.0
        grid = np.linspace(center - 5 * fwhm, center + 5 * fwhm, 200)
        model = ProfileFitter.pseudo_voigt(grid, height, center, fwhm, eta)
        area = float(np.trapezoid(model, grid))
        return Peak(
            two_theta=float(center),
            intensity=float(height),
            fwhm=float(fwhm),
            area=area,
            d_spacing=PeakFinder._calc_d_spacing(float(center), wavelength),
            fit_params={"model": "pseudo_voigt", "eta": float(eta),
                        "bg": float(bg)},
        )
