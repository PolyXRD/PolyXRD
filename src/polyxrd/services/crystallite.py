"""
晶粒尺寸估计服务 (M16, Sprint 3)
================================
Scherrer 公式 + 仪器展宽扣除 (高斯/洛伦兹两种近似)。
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np

from polyxrd.models.peak import Peak, PeakList

RAD = np.pi / 180.0


class CrystalliteEstimator:
    """基于峰展宽的晶粒尺寸估计。"""

    # ── Scherrer ──────────────────────────────────────────────

    @staticmethod
    def scherrer_size(
        fwhm_deg: float,
        two_theta_deg: float,
        wavelength: float = 1.5406,
        K: float = 0.9,
    ) -> float:
        """Scherrer 粒径 (nm)。

        D = K·λ / (β·cosθ)
          λ, D 单位一致 (用 Å → nm); β 为峰展宽 (弧度), 由 FWHM(°) 换算。

        注意: 此处用 FWHM 近似 β。若用积分宽度 β_int, 关系随峰形变化
        (高斯: β_int=√(2π)·σ → FWHM·√π/√(2ln2)? 由调用方保证 β 语义一致)。
        """
        beta = abs(float(fwhm_deg)) * RAD
        theta = np.radians(float(two_theta_deg) / 2.0)
        if beta <= 1e-12 or abs(np.cos(theta)) < 1e-12:
            return 0.0
        d_angstrom = float(K * wavelength / (beta * np.cos(theta)))
        return d_angstrom / 10.0  # Å → nm

    # ── 仪器展宽扣除 ──────────────────────────────────────────

    @staticmethod
    def subtract_instrumental_broadening(
        beta_obs_deg: float,
        beta_std_deg: float,
        method: str = "gaussian",
    ) -> float:
        """扣除仪器(标样)展宽后的样品本征展宽 (度)。

        gaussian : β = sqrt(β_obs² − β_std²)   (卷积近似)
        lorentz  : β = β_obs − β_std
        """
        o = abs(float(beta_obs_deg))
        s = abs(float(beta_std_deg))
        if s >= o:
            return 0.0
        if method == "lorentz":
            return o - s
        return float(np.sqrt(o * o - s * s))

    # ── 逐峰估计 ──────────────────────────────────────────────

    @classmethod
    def estimate_from_peaks(
        cls,
        peaks: Iterable,
        wavelength: float = 1.5406,
        beta_std_deg: float = 0.0,
        K: float = 0.9,
        beta_std_method: str = "gaussian",
    ) -> list[dict]:
        """对峰表逐峰估算粒径。

        Args:
            peaks: Peak 列表/PeakList (须含 two_theta 与 fwhm)
            beta_std_deg: 仪器标样本征 FWHM (0 = 不扣除)
        Returns:
            [{"two_theta":…, "fwhm":…, "beta":…, "size_nm":…}, ...]
        """
        items = getattr(peaks, "peaks", None) or list(peaks)
        out = []
        for p in items:
            if p is None:
                continue
            fwhm = float(getattr(p, "fwhm", 0.0) or 0.0)
            tt = float(getattr(p, "two_theta", 0.0) or 0.0)
            if fwhm <= 0 or tt <= 0:
                continue
            beta = cls.subtract_instrumental_broadening(
                fwhm, beta_std_deg, method=beta_std_method)
            size = cls.scherrer_size(beta, tt, wavelength=wavelength, K=K)
            out.append({"two_theta": round(tt, 3),
                        "fwhm": round(fwhm, 4),
                        "beta": round(beta, 4),
                        "size_nm": round(size, 2) if size > 0 else 0.0})
        return out
