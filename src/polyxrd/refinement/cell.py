"""晶胞几何 —— 直接/倒易基矢、d 值、2θ 换算（v5.0.0）。

全部向量化实现：一次算完 ``(N, 3)`` 的 hkl 批量，不做 Python 逐点循环。
口径与 ``rietveld_refiner._calc_d_spacing_from_hkl`` 一致（三斜通式），
但这里是数组版，供精修热循环使用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class Cell:
    """晶胞参数（长度 Å，角度 °）。"""

    a: float
    b: float
    c: float
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0

    # ---- 派生量 ----------------------------------------------------------
    @property
    def alpha_r(self) -> float:
        return np.radians(self.alpha)

    @property
    def beta_r(self) -> float:
        return np.radians(self.beta)

    @property
    def gamma_r(self) -> float:
        return np.radians(self.gamma)

    def volume(self) -> float:
        """晶胞体积 (Å³)，三斜通式。"""
        ca, cb, cg = np.cos(self.alpha_r), np.cos(self.beta_r), np.cos(self.gamma_r)
        return float(
            self.a * self.b * self.c
            * np.sqrt(max(1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg, 0.0))
        )

    # ---- 基矢 ------------------------------------------------------------
    def direct_vectors(self) -> np.ndarray:
        """直接基矢 (3, 3)，行向量 ``[a1; a2; a3]``（标准粉末约定）。"""
        ca, cb, cg = np.cos(self.alpha_r), np.cos(self.beta_r), np.cos(self.gamma_r)
        sg = np.sin(self.gamma_r)
        if abs(sg) < 1e-12:  # 退化晶胞（γ≈0）
            sg = 1e-12
        a1 = np.array([self.a, 0.0, 0.0])
        a2 = np.array([self.b * cg, self.b * sg, 0.0])
        cz = np.sqrt(max(sg * sg - cb * cb - ca * ca + 2.0 * ca * cb * cg, 0.0)) / sg
        if not np.isfinite(cz) or cz <= 0.0:
            cz = 1e-12
        cx = self.c * cb
        cy = self.c * (ca - cb * cg) / sg
        a3 = np.array([cx, cy, self.c * cz])
        return np.vstack([a1, a2, a3])

    def reciprocal_vectors(self) -> np.ndarray:
        """倒易基矢 (3, 3) **不含 2π**（``b_i·a_j = δ_ij``）。

        角度计算（择优取向的 cosα）与 |g| = 1/d 都用这套约定；
        与含 2π 的约定只差一个全局常数，不影响夹角。
        """
        A = self.direct_vectors()
        try:
            B = np.linalg.inv(A).T
        except np.linalg.LinAlgError:  # 奇异（退化晶胞）→ 伪逆兜底
            B = np.linalg.pinv(A).T
        return B

    def with_scales(
        self, sa: float = 1.0, sb: Optional[float] = None, sc: Optional[float] = None,
        salpha: float = 1.0, sbeta: Optional[float] = None, sgamma: Optional[float] = None,
    ) -> "Cell":
        """按比例缩放得到新晶胞（角度按比例缩放，默认与 a/b 同步）。"""
        return Cell(
            a=self.a * float(sa),
            b=self.b * float(sb if sb is not None else sa),
            c=self.c * float(sc if sc is not None else sa),
            alpha=self.alpha * float(salpha),
            beta=self.beta * float(sbeta if sbeta is not None else salpha),
            gamma=self.gamma * float(sgamma if sgamma is not None else salpha),
        )


def d_spacings(hkl: np.ndarray, cell: Cell) -> np.ndarray:
    """由 hkl 批量算晶面间距 d (Å)。

    :param hkl: ``(N, 3)`` 整数或浮点数组
    :return: ``(N,)`` 的 d；``d <= 0`` 的非法反射返回 ``inf``
    """
    hkl = np.asarray(hkl, dtype=float).reshape(-1, 3)
    B = cell.reciprocal_vectors()
    # ⚠ B 的**行**就是倒易基矢 b_i，故 g = Σ h_i·b_i = hkl @ B（不能再转置）。
    #   转置只在正交晶胞下偶然等价 —— 六方/单斜/三斜会算错 d（2026-10-31 实测
    #   LiNiO2 R-3m：d(101) 2.8206 vs 正确 2.4549）。
    g = hkl @ B                        # (N, 3) 倒易矢量（笛卡尔）
    g_mag = np.linalg.norm(g, axis=1)   # (N,) |g| = 1/d
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(g_mag > 1e-12, 1.0 / g_mag, np.inf)
    return d


def reciprocal_magnitudes(hkl: np.ndarray, cell: Cell) -> np.ndarray:
    """``|g| = 1/d`` 批量值（(N,)）。"""
    hkl = np.asarray(hkl, dtype=float).reshape(-1, 3)
    g = hkl @ cell.reciprocal_vectors()   # 同上：行向量约定，不转置
    return np.linalg.norm(g, axis=1)


def two_theta_from_d(d, wavelength: float) -> np.ndarray:
    """``2θ = 2·asin(λ/(2d))``；不可测（λ/(2d) > 1）返回 ``nan``。"""
    d = np.asarray(d, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        sin_theta = float(wavelength) / (2.0 * d)
    sin_theta = np.where(np.isfinite(sin_theta) & (sin_theta <= 1.0) & (sin_theta > 0.0),
                         sin_theta, np.nan)
    return np.degrees(2.0 * np.arcsin(sin_theta))


def two_theta_from_g(g_mag: np.ndarray, wavelength: float) -> np.ndarray:
    """``2θ = 2·asin(λ·|g|/2)``（比走 d 少一次除法，热路径用）。"""
    g = np.asarray(g_mag, dtype=float)
    with np.errstate(invalid="ignore"):
        s = float(wavelength) * g / 2.0
    s = np.where(np.isfinite(s) & (s <= 1.0) & (s > 0.0), s, np.nan)
    return np.degrees(2.0 * np.arcsin(s))


def lorentz_polarization(two_theta) -> np.ndarray:
    """LP 因子 ``(1+cos²2θ)/(sin²θ·cosθ)``（Bragg–Brentano，无单色器偏振项）。"""
    tth = np.radians(np.asarray(two_theta, dtype=float))
    theta = tth / 2.0
    c2 = np.cos(tth)
    st, ct = np.sin(theta), np.cos(theta)
    denom = st * st * ct
    with np.errstate(divide="ignore", invalid="ignore"):
        lp = (1.0 + c2 * c2) / denom
    return np.where(np.isfinite(lp), lp, 0.0)


def cell_angle_cosines(hkl: np.ndarray, direction: Sequence[float], cell: Cell) -> np.ndarray:
    """各反射倒易矢量与给定方向（笛卡尔）的夹角余弦 —— 择优取向用。

    :param direction: 择优面法向（笛卡尔，通常取该 hkl 的倒易矢量）
    """
    hkl = np.asarray(hkl, dtype=float).reshape(-1, 3)
    g = hkl @ cell.reciprocal_vectors()             # (N, 3)，行向量约定
    g_mag = np.linalg.norm(g, axis=1)
    v = np.asarray(direction, dtype=float).reshape(3)
    v_mag = float(np.linalg.norm(v))
    if v_mag <= 1e-12:
        return np.zeros(hkl.shape[0], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos = (g @ v) / (g_mag * v_mag)
    return np.where(np.isfinite(cos), np.clip(cos, -1.0, 1.0), 0.0)
