"""
精修结果模型
============
Rietveld精修的结果数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from polyxrd.models.phase import Phase


@dataclass
class RefinementResult:
    """Rietveld精修结果

    Attributes:
        phases: 精修后的物相列表
        observed_data: 实验数据 (x, y)
        simulated_data: 模拟数据 (x, y)
        residual_data: 残差数据 (x, y)
        wR: 加权R因子 (%)
        GOF: 优良度因子
        quality: 质量评级
        num_cycles: 精修循环次数
        converged: 是否收敛
        time_seconds: 精修耗时
        fit_params: 精修参数字典
    """
    phases: list[Phase] = field(default_factory=list)
    observed_data: Optional[tuple[np.ndarray, np.ndarray]] = None
    simulated_data: Optional[tuple[np.ndarray, np.ndarray]] = None
    residual_data: Optional[tuple[np.ndarray, np.ndarray]] = None
    wR: float = 0.0
    GOF: float = 0.0
    quality: str = ""
    num_cycles: int = 0
    converged: bool = False
    time_seconds: float = 0.0
    fit_params: dict = field(default_factory=dict)

    @property
    def quality_grade(self) -> str:
        """质量评级 (根据R因子)"""
        if self.wR < 2.0:
            return "优秀"
        elif self.wR < 5.0:
            return "良好"
        elif self.wR < 10.0:
            return "一般"
        elif self.wR < 20.0:
            return "差"
        else:
            return "很差"

    def summary(self) -> str:
        """生成文本摘要报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("PolyXRD Rietveld精修报告")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"物相数量: {len(self.phases)}")
        lines.append(f"精修循环: {self.num_cycles}")
        lines.append(f"收敛状态: {'是' if self.converged else '否'}")
        lines.append(f"耗时: {self.time_seconds:.1f} 秒")
        lines.append("")
        lines.append("-" * 40)
        lines.append("精修质量指标")
        lines.append("-" * 40)
        lines.append(f"  wR (加权R因子): {self.wR:.4f} %")
        lines.append(f"  GOF (优良度):   {self.GOF:.4f}")
        lines.append(f"  质量评级:       {self.quality_grade}")
        lines.append("")
        lines.append("-" * 40)
        lines.append("物相分析")
        lines.append("-" * 40)

        total_fraction = 0.0
        for i, phase in enumerate(self.phases, 1):
            lines.append(f"\n物相 {i}: {phase.name}")
            lines.append(f"  化学式: {phase.formula}")
            lines.append(f"  质量分数: {phase.weight_fraction:.2f} %")
            total_fraction += phase.weight_fraction

            if phase.lattice:
                lat = phase.lattice
                lines.append(
                    f"  晶胞参数: a={lat.a:.4f}, b={lat.b:.4f}, c={lat.c:.4f} Å"
                )
                lines.append(
                    f"            α={lat.alpha:.2f}, β={lat.beta:.2f}, γ={lat.gamma:.2f}°"
                )
                lines.append(f"  晶胞体积: {lat.volume:.2f} ų")

        lines.append("")
        lines.append(f"物相总含量: {total_fraction:.2f} %")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "phases": [p.to_dict() for p in self.phases],
            "wR": self.wR,
            "GOF": self.GOF,
            "quality": self.quality,
            "quality_grade": self.quality_grade,
            "num_cycles": self.num_cycles,
            "converged": self.converged,
            "time_seconds": self.time_seconds,
            "fit_params": self.fit_params,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RefinementResult":
        phases = [Phase.from_dict(p) for p in data.get("phases", [])]
        return cls(
            phases=phases,
            wR=data.get("wR", 0),
            GOF=data.get("GOF", 0),
            quality=data.get("quality", ""),
            num_cycles=data.get("num_cycles", 0),
            converged=data.get("converged", False),
            time_seconds=data.get("time_seconds", 0),
            fit_params=data.get("fit_params", {}),
        )
