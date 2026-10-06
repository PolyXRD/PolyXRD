"""
FoM (Figure of Merit) 匹配结果模型
==================================
低分 = 好匹配。字段与 PhaseMatchResult 互补: 记录匹配质量分项,
供排序/诊断/三强峰预检等上层逻辑使用。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FoMResult:
    """一次 物相-实验峰 匹配的质量结果。

    Attributes:
        score: 综合评分 (越小越好, >0)
        matched: 命中参考峰条数 (一一对应互斥匹配, 一个实验峰只算一次)
        missed: 未命中参考峰条数
        position_penalty: 位置项 bad = 加权平均位置偏差 + 加权漏峰比
            (典型 0~2; v2.2 S12 强线漏检权重 x2 后极端情况可略超 2)
        intensity_score: 匹配对上的强度余弦一致性 0~1 (1=完全一致; 0=无强度信息)
        method: "fom" (峰表法) 或 "profile" (峰型匹配)
        delta_2theta: 本次使用的匹配窗口 (度)
        unexplained_obs: 未被任何参考峰解释的实验峰条数 (特异性)
        total_obs: 实验峰总条数
        scale: v2.2 S10 强度尺度因子 s* = Σ(w·I_obs·I_ref)/Σ(w·I_ref²)
               (互斥匹配对上的最优最小二乘解; 0 = 未计算)
        scale_rel: s*·I_ref,max / I_obs,max ∈ [0,1] —— 该相最强线经 s* 缩放后
               占最强实测峰的比例 (0 = 未计算); "只配上噪声"的伪匹配该值极小
        position_dev: v2.7.0 峰位项 (Σw·位置偏差核 / Σw), 已归一化 ∈ [0,~1]
        miss_penalty: v2.7.0 漏检项 (Σw·漏检 / Σw), 已归一化 ∈ [0,~2]
        spec_penalty: v2.7.0 特异性项 = 未解释实验峰强度比 ∈ [0,1]
        (position_penalty = position_dev + _FOM_MISS_WEIGHT·miss_penalty,
         即 v2.6.0 的 bad; 拆开后每项可独立标定/诊断)
    """
    score: float = 999.0
    matched: int = 0
    missed: int = 0
    position_penalty: float = 0.0
    intensity_score: float = 0.0
    method: str = "fom"
    delta_2theta: float = 0.15
    unexplained_obs: int = 0
    total_obs: int = 0
    scale: float = 0.0
    scale_rel: float = 0.0
    position_dev: float = 0.0
    miss_penalty: float = 0.0
    spec_penalty: float = 0.0

    @property
    def total(self) -> int:
        return self.matched + self.missed

    @property
    def match_ratio(self) -> float:
        return self.matched / self.total if self.total > 0 else 0.0

    @property
    def specificity(self) -> float:
        """实验峰被解释的比例 (1 = 全部实验峰都能被该物相解释)"""
        if self.total_obs > 0:
            return 1.0 - self.unexplained_obs / self.total_obs
        return 0.0

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "matched": self.matched,
            "missed": self.missed,
            "position_penalty": self.position_penalty,
            "intensity_score": self.intensity_score,
            "method": self.method,
            "delta_2theta": self.delta_2theta,
            "unexplained_obs": self.unexplained_obs,
            "total_obs": self.total_obs,
            "scale": self.scale,
            "scale_rel": self.scale_rel,
            "position_dev": self.position_dev,
            "miss_penalty": self.miss_penalty,
            "spec_penalty": self.spec_penalty,
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
            unexplained_obs=data.get("unexplained_obs", 0),
            total_obs=data.get("total_obs", 0),
            scale=data.get("scale", 0.0),
            scale_rel=data.get("scale_rel", 0.0),
            position_dev=data.get("position_dev", 0.0),
            miss_penalty=data.get("miss_penalty", 0.0),
            spec_penalty=data.get("spec_penalty", 0.0),
        )


# 匹配因子 → 置信度文案的统一分档 (score 越低越好)
CONFIDENCE_BANDS: tuple[tuple[float, str], ...] = (
    (0.15, "极好匹配"),
    (0.40, "良好匹配"),
    (0.70, "一般匹配"),
)


def confidence_from_score(score: float) -> str:
    """把 FoM 分值映射为置信度文案 (builtin / COD / foam 三处共用)。"""
    for limit, label in CONFIDENCE_BANDS:
        if score < limit:
            return label
    return "可能不匹配"
