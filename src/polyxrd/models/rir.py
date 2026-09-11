"""
RIR 半定量模型 (M13)
====================
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RIRResult:
    """RIR 半定量结果。

    Attributes:
        weights: 物相名 → 质量分数 (%)。无内标时为相对含量 (归一化到 100,
            不含内标物相时按其 RIR 归一); 有内标时为绝对含量 (wt% of sample)。
        quality: "ok" | "low" | "error" (峰缺失/参数缺失时降级)
        note: 人类可读提示
        iicor_used: 实际使用的 {物相名: I/Icor}
        absolute: 是否为绝对定量 (含内标)
    """
    weights: dict = field(default_factory=dict)
    quality: str = "ok"
    note: str = ""
    iicor_used: dict = field(default_factory=dict)
    absolute: bool = False

    def to_dict(self) -> dict:
        return {
            "weights": dict(self.weights),
            "quality": self.quality,
            "note": self.note,
            "iicor_used": dict(self.iicor_used),
            "absolute": self.absolute,
        }
