"""
FoM (Figure of Merit) 匹配结果模型
==================================
低分 = 好匹配。字段与 PhaseMatchResult 互补: 记录匹配质量分项,
供排序/诊断/三强峰预检等上层逻辑使用。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FoMResult:
    """一次 物相-实验峰 匹配的质量结果。

    Attributes:
        score: 综合评分 (越小越好, >0)
        matched: 命中参考峰条数
        missed: 未命中参考峰条数
        position_penalty: 位置偏差惩罚项 (Σ|Δ2θ| + 漏峰×容差, 归一化)
        intensity_score: 强度一致性 0~1 (1=完全一致; 0=无强度信息可用)
        method: "fom" (峰表法) 或 "profile" (峰型匹配)
        delta_2theta: 本次使用的匹配窗口 (度)
    """
    score: float = 999.0
    matched: int = 0
    missed: int = 0
    position_penalty: float = 0.0
    intensity_score: float = 0.0
    method: str = "fom"
    delta_2theta: float = 0.15

    @property
    def total(self) -> int:
        return self.matched + self.missed

    @property
    def match_ratio(self) -> float:
        return self.matched / self.total if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "matched": self.matched,
            "missed": self.missed,
            "position_penalty": self.position_penalty,
            "intensity_score": self.intensity_score,
            "method": self.method,
            "delta_2theta": self.delta_2theta,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FoMResult":
        return cls(
            score=data.get("score", 999.0),
            matched=data.get("matched", 0),
            missed=data.get("missed", 0),
            position_penalty=data.get("position_penalty", 0.0),
            intensity_score=data.get("intensity_score", 0.0),
            method=data.get("method", "fom"),
            delta_2theta=data.get("delta_2theta", 0.15),
        )
