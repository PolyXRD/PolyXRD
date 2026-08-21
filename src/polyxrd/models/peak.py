"""
峰数据模型
==========
定义衍射峰的数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Peak:
    """衍射峰

    Attributes:
        two_theta: 峰位2θ (度)
        intensity: 峰强度
        fwhm: 半高宽 (度)
        hkl: Miller指数 (h, k, l)
        d_spacing: d-spacing (Å)
        phase: 所属物相名称
        fit_params: 拟合参数
        area: 峰面积
        symmetry: 对称性 (multiplicity)
        fitted: 是否已拟合
        profile_params: 峰形精修参数
    """
    two_theta: float
    intensity: float
    fwhm: float = 0.0
    hkl: Optional[tuple[int, int, int]] = None
    d_spacing: float = 0.0
    phase: str = ""
    fit_params: dict = field(default_factory=dict)
    area: float = 0.0
    symmetry: int = 1
    fitted: bool = False
    profile_params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.d_spacing == 0.0 and self.two_theta > 0:
            self._compute_d_spacing()

    def _compute_d_spacing(self, wavelength: float = 1.5406) -> None:
        """从2θ计算d-spacing"""
        theta_rad = np.radians(self.two_theta / 2.0)
        sin_theta = np.sin(theta_rad)
        if sin_theta > 0:
            self.d_spacing = wavelength / (2.0 * sin_theta)

    @property
    def hkl_str(self) -> str:
        """Miller指数字符串表示"""
        if self.hkl is None:
            return ""
        return f"({self.hkl[0]}{self.hkl[1]}{self.hkl[2]})"

    @property
    def k_alpha_wavelength(self) -> float:
        """Kα平均波长 (Å)"""
        return 1.5418  # Cu Kα1 + Kα2

    def to_dict(self) -> dict:
        return {
            "two_theta": self.two_theta,
            "intensity": self.intensity,
            "fwhm": self.fwhm,
            "hkl": list(self.hkl) if self.hkl else None,
            "d_spacing": self.d_spacing,
            "phase": self.phase,
            "area": self.area,
            "fitted": self.fitted,
            "profile_params": self.profile_params,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Peak":
        hkl = tuple(data["hkl"]) if data.get("hkl") else None
        return cls(
            two_theta=data["two_theta"],
            intensity=data["intensity"],
            fwhm=data.get("fwhm", 0.0),
            hkl=hkl,
            d_spacing=data.get("d_spacing", 0.0),
            phase=data.get("phase", ""),
            area=data.get("area", 0.0),
            fitted=data.get("fitted", False),
            profile_params=data.get("profile_params", {}),
        )


@dataclass
class PeakList:
    """峰列表集合"""
    peaks: list[Peak] = field(default_factory=list)
    source: str = "auto"  # auto/manual/fit

    def __len__(self) -> int:
        return len(self.peaks)

    def __iter__(self):
        return iter(self.peaks)

    def add(self, peak: Peak) -> None:
        self.peaks.append(peak)

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.peaks):
            del self.peaks[index]

    def sort_by_two_theta(self) -> None:
        self.peaks.sort(key=lambda p: p.two_theta)

    def get_by_phase(self, phase_name: str) -> list[Peak]:
        return [p for p in self.peaks if p.phase == phase_name]

    def export_csv(self, path: str) -> None:
        """导出CSV"""
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["index", "2theta", "intensity", "fwhm", "hkl", "d_spacing", "phase"])
            for i, peak in enumerate(self.peaks):
                writer.writerow([
                    i + 1,
                    f"{peak.two_theta:.4f}",
                    f"{peak.intensity:.1f}",
                    f"{peak.fwhm:.4f}",
                    peak.hkl_str,
                    f"{peak.d_spacing:.4f}",
                    peak.phase,
                ])


@dataclass
class FitResult:
    """峰拟合结果

    Attributes:
        peaks: 拟合后的峰列表
        r_squared: R²决定系数
        chi_squared: 卡方值
        residuals: 残差列表
        converged: 是否收敛
        num_iterations: 迭代次数
    """
    peaks: list[Peak] = field(default_factory=list)
    r_squared: float = 0.0
    chi_squared: float = 0.0
    residuals: list[float] = field(default_factory=list)
    converged: bool = False
    num_iterations: int = 0

    def to_dict(self) -> dict:
        return {
            "peaks": [p.to_dict() for p in self.peaks],
            "r_squared": self.r_squared,
            "chi_squared": self.chi_squared,
            "converged": self.converged,
            "num_iterations": self.num_iterations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FitResult":
        peaks = [Peak.from_dict(p) for p in data.get("peaks", [])]
        return cls(
            peaks=peaks,
            r_squared=data.get("r_squared", 0.0),
            chi_squared=data.get("chi_squared", 0.0),
            converged=data.get("converged", False),
            num_iterations=data.get("num_iterations", 0),
        )
