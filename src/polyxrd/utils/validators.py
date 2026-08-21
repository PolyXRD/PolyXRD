"""
验证器
======
数据和参数验证工具。
"""
from __future__ import annotations

from typing import Any


class ValidationError(Exception):
    """验证错误"""


def validate_wavelength(wavelength: float) -> float:
    """验证X射线波长

    Args:
        wavelength: 波长值（Å）

    Returns:
        验证后的波长

    Raises:
        ValidationError: 当波长无效时
    """
    if not 0.1 <= wavelength <= 20.0:
        raise ValidationError(
            f"波长 {wavelength} 超出有效范围 [0.1, 20.0] Å"
        )
    return wavelength


def validate_two_theta_range(two_theta_min: float, two_theta_max: float) -> tuple[float, float]:
    """验证2θ范围

    Args:
        two_theta_min: 最小2θ
        two_theta_max: 最大2θ

    Returns:
        验证后的范围

    Raises:
        ValidationError: 当范围无效时
    """
    if two_theta_min >= two_theta_max:
        raise ValidationError(
            f"2θ最小值 ({two_theta_min}) 必须小于最大值 ({two_theta_max})"
        )
    if two_theta_min < 0 or two_theta_max > 180:
        raise ValidationError(
            f"2θ范围 [{two_theta_min}, {two_theta_max}] 超出有效范围 [0, 180]"
        )
    return two_theta_min, two_theta_max


def validate_lattice_params(
    a: float, b: float, c: float,
    alpha: float = 90.0, beta: float = 90.0, gamma: float = 90.0,
) -> dict[str, float]:
    """验证晶格参数

    Args:
        a, b, c: 晶胞参数
        alpha, beta, gamma: 晶胞角度

    Returns:
        验证后的参数字典

    Raises:
        ValidationError: 当参数无效时
    """
    if a <= 0 or b <= 0 or c <= 0:
        raise ValidationError("晶胞参数必须为正数")

    for name, angle in [("alpha", alpha), ("beta", beta), ("gamma", gamma)]:
        if not 0 < angle < 180:
            raise ValidationError(f"角度 {name}={angle} 必须在 (0, 180) 范围内")

    return {
        "a": a, "b": b, "c": c,
        "alpha": alpha, "beta": beta, "gamma": gamma,
    }


def validate_peak_params(
    two_theta: float,
    intensity: float,
    fwhm: float = 0.0,
) -> dict[str, float]:
    """验证峰参数

    Args:
        two_theta: 峰位2θ
        intensity: 峰强度
        fwhm: 半高宽

    Returns:
        验证后的参数

    Raises:
        ValidationError: 当参数无效时
    """
    if not 0 <= two_theta <= 180:
        raise ValidationError(f"2θ={two_theta} 超出有效范围 [0, 180]")

    if intensity < 0:
        raise ValidationError(f"强度不能为负值: {intensity}")

    if fwhm < 0:
        raise ValidationError(f"FWHM不能为负值: {fwhm}")

    return {
        "two_theta": two_theta,
        "intensity": intensity,
        "fwhm": fwhm,
    }


def validate_positive(value: float, name: str = "值") -> float:
    """验证值为正数"""
    if value <= 0:
        raise ValidationError(f"{name} 必须为正数，当前值: {value}")
    return value


def validate_in_range(
    value: float,
    min_val: float,
    max_val: float,
    name: str = "值",
) -> float:
    """验证值在范围内"""
    if not min_val <= value <= max_val:
        raise ValidationError(
            f"{name}={value} 超出范围 [{min_val}, {max_val}]"
        )
    return value


def validate_not_empty(value: Any, name: str = "值") -> Any:
    """验证值不为空"""
    if value is None or (isinstance(value, (list, dict, str)) and len(value) == 0):
        raise ValidationError(f"{name} 不能为空")
    return value
