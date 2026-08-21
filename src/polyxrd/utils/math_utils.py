"""
数学工具函数
============
XRD分析中常用的数学工具。
"""
from __future__ import annotations

import numpy as np


def two_theta_to_d(two_theta: float | np.ndarray, wavelength: float = 1.5406) -> float | np.ndarray:
    """2θ 转换为 d-spacing

    Args:
        two_theta: 2θ角度（度）
        wavelength: X射线波长（Å）

    Returns:
        d-spacing（Å）
    """
    theta_rad = np.radians(np.asarray(two_theta) / 2.0)
    sin_theta = np.sin(theta_rad)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(sin_theta > 0, wavelength / (2.0 * sin_theta), np.inf)
    return float(d) if np.ndim(d) == 0 else d


def d_to_two_theta(d: float | np.ndarray, wavelength: float = 1.5406) -> float | np.ndarray:
    """d-spacing 转换为 2θ

    Args:
        d: d-spacing（Å）
        wavelength: X射线波长（Å）

    Returns:
        2θ角度（度）

    Raises:
        ValueError: 当d值无效时
    """
    sin_theta = wavelength / (2.0 * np.asarray(d))
    if np.any(np.abs(sin_theta) > 1.0):
        raise ValueError(f"d值无效：sin(θ)={sin_theta.max():.4f} 超出[-1,1]范围")
    theta = np.arcsin(np.clip(sin_theta, -1, 1))
    result = np.degrees(2.0 * theta)
    return float(result) if np.ndim(result) == 0 else result


def two_theta_to_q(two_theta: float | np.ndarray, wavelength: float = 1.5406) -> float | np.ndarray:
    """2θ 转换为散射矢量 q

    q = 4π sin(θ) / λ

    Args:
        two_theta: 2θ角度（度）
        wavelength: X射线波长（Å）

    Returns:
        q值（1/Å）
    """
    theta_rad = np.radians(np.asarray(two_theta) / 2.0)
    q = (4.0 * np.pi * np.sin(theta_rad)) / wavelength
    return float(q) if np.ndim(q) == 0 else q


def scherrer_formula(
    crystallite_size: float,
    wavelength: float = 1.5406,
    two_theta: float = 30.0,
    k: float = 0.9,
) -> float:
    """Scherrer公式计算晶粒大小

    FWHM = K * λ / (D * cos(θ))

    Args:
        crystallite_size: 晶粒大小（Å）
        wavelength: X射线波长（Å）
        two_theta: 衍射角（度）
        k: Scherrer常数

    Returns:
        半高宽（弧度）
    """
    theta_rad = np.radians(two_theta / 2.0)
    fwhm_rad = k * wavelength / (crystallite_size * np.cos(theta_rad))
    return float(np.degrees(fwhm_rad))


def williamson_hall(
    two_theta: np.ndarray,
    fwhm: np.ndarray,
    wavelength: float = 1.5406,
) -> tuple[float, float]:
    """Williamson-Hall图分析

    用于分离晶粒大小和微观应变。

    Args:
        two_theta: 峰位2θ数组
        fwhm: 半高宽数组（度）
        wavelength: X射线波长（Å）

    Returns:
        (strain, size) 应变和晶粒大小
    """
    theta_rad = np.radians(two_theta / 2.0)
    sin_theta = np.sin(theta_rad)
    cos_theta = np.cos(theta_rad)

    fwhm_rad = np.radians(fwhm)

    # Williamson-Hall公式: FWHM * cos(θ) = K*λ/D + 4*ε*sin(θ)
    x = sin_theta
    y = fwhm_rad * cos_theta

    # 线性拟合
    if len(x) >= 2:
        coeffs = np.polyfit(x, y, 1)
        strain = coeffs[0] / 4.0
        size = 0.9 * wavelength / (coeffs[1] + 1e-10)
        return float(strain), float(size)
    else:
        return 0.0, 0.0


def lattice_volume(a: float, b: float, c: float, alpha: float = 90.0, beta: float = 90.0, gamma: float = 90.0) -> float:
    """计算晶胞体积

    Args:
        a, b, c: 晶胞参数（Å）
        alpha, beta, gamma: 晶胞角度（度）

    Returns:
        晶胞体积（Å³）
    """
    alpha_r = np.radians(alpha)
    beta_r = np.radians(beta)
    gamma_r = np.radians(gamma)

    cos_a = np.cos(alpha_r)
    cos_b = np.cos(beta_r)
    cos_g = np.cos(gamma_r)

    volume = a * b * c * np.sqrt(
        1 - cos_a**2 - cos_b**2 - cos_g**2 + 2 * cos_a * cos_b * cos_g
    )
    return float(volume)


def cubic_a_from_density(
    density: float,
    formula_mass: float,
    z: int = 4,
) -> float:
    """从密度计算立方晶胞参数

    Args:
        density: 密度（g/cm³）
        formula_mass: 化学式量（g/mol）
        z: 每个晶胞的化学式单位数

    Returns:
        晶胞参数a（Å）
    """
    N_A = 6.02214076e23  # Avogadro常数
    a3 = (z * formula_mass) / (N_A * density * 1e-24)  # cm³ -> Å³
    return float(a3 ** (1.0 / 3.0))


def fwhm_to_sigma(fwhm: float) -> float:
    """FWHM 转换为高斯sigma"""
    return fwhm / 2.35482


def sigma_to_fwhm(sigma: float) -> float:
    """高斯sigma 转换为 FWHM"""
    return sigma * 2.35482


def gaussian(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
    """高斯函数"""
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def lorentzian(x: np.ndarray, amplitude: float, center: float, gamma: float) -> np.ndarray:
    """洛伦兹函数"""
    return amplitude * gamma**2 / ((x - center) ** 2 + gamma**2)


def voigt(x: np.ndarray, amplitude: float, center: float, sigma: float, gamma: float) -> np.ndarray:
    """Voigt函数"""
    from scipy.special import wofz
    z = ((x - center) + 1j * gamma) / (sigma * np.sqrt(2))
    return amplitude * np.real(wofz(z)) / (sigma * np.sqrt(2 * np.pi))
