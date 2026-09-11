"""
数据模型
========
定义XRD分析中的核心数据模型。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class XRDData:
    """XRD实验数据

    封装原始/预处理的XRD数据。

    Attributes:
        two_theta: 2θ角度数组
        intensity: 强度数组
        wavelength: X射线波长（Å）
        metadata: 元数据字典
    """
    two_theta: np.ndarray
    intensity: np.ndarray
    wavelength: float = 1.5406
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if len(self.two_theta) != len(self.intensity):
            raise ValueError(
                f"2θ数组长度({len(self.two_theta)})与强度数组长度({len(self.intensity)})不一致"
            )
        if len(self.two_theta) < 3:
            raise ValueError("数据点数量必须 >= 3")
        if not (0 <= self.two_theta[0] < 180):
            raise ValueError(f"起始2θ ({self.two_theta[0]}) 超出有效范围 [0, 180)")
        if not (0 < self.two_theta[-1] <= 180):
            raise ValueError(f"结束2θ ({self.two_theta[-1]}) 超出有效范围 (0, 180]")

    @property
    def d_spacing(self) -> np.ndarray:
        """d-spacing数组"""
        sin_theta = np.sin(np.radians(self.two_theta / 2.0))
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(sin_theta > 0, self.wavelength / (2.0 * sin_theta), np.inf)

    @property
    def q_vector(self) -> np.ndarray:
        """散射矢量q数组"""
        return (4.0 * np.pi * np.sin(np.radians(self.two_theta / 2.0))) / self.wavelength

    def __len__(self) -> int:
        return len(self.two_theta)

    def __getitem__(self, idx):
        return XRDData(
            two_theta=self.two_theta[idx],
            intensity=self.intensity[idx],
            wavelength=self.wavelength,
            metadata=self.metadata,
        )

    def copy(self) -> "XRDData":
        """创建副本"""
        return XRDData(
            two_theta=self.two_theta.copy(),
            intensity=self.intensity.copy(),
            wavelength=self.wavelength,
            metadata=dict(self.metadata),
        )

    def normalize(self) -> "XRDData":
        """归一化强度到[0, 1]"""
        max_intensity = np.max(self.intensity)
        if max_intensity > 0:
            return XRDData(
                two_theta=self.two_theta.copy(),
                intensity=self.intensity / max_intensity,
                wavelength=self.wavelength,
                metadata={**self.metadata, "normalized": True},
            )
        return self.copy()

    def crop(self, two_theta_min: float, two_theta_max: float) -> "XRDData":
        """裁剪2θ范围"""
        mask = (self.two_theta >= two_theta_min) & (self.two_theta <= two_theta_max)
        return XRDData(
            two_theta=self.two_theta[mask],
            intensity=self.intensity[mask],
            wavelength=self.wavelength,
            metadata={**self.metadata, "cropped": (two_theta_min, two_theta_max)},
        )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "two_theta": self.two_theta.tolist(),
            "intensity": self.intensity.tolist(),
            "wavelength": self.wavelength,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "XRDData":
        """从字典创建"""
        return cls(
            two_theta=np.array(data["two_theta"]),
            intensity=np.array(data["intensity"]),
            wavelength=data.get("wavelength", 1.5406),
            metadata=data.get("metadata", {}),
        )


@dataclass
class BackgroundResult:
    """背景扣除结果"""
    background: np.ndarray
    corrected: XRDData
    method: str
    params: dict = field(default_factory=dict)


@dataclass
class PeakFitResult:
    """峰拟合结果"""
    params: list[dict]  # 每个峰的参数
    residuals: np.ndarray
    r_squared: float
    model: str = "voigt"
