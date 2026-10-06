"""
物相数据模型
============
晶相/物相数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class LatticeParams:
    """晶胞参数

    Attributes:
        a, b, c: 晶胞长度 (Å)
        alpha, beta, gamma: 晶胞角度 (度)
    """
    a: float = 1.0
    b: float = 1.0
    c: float = 1.0
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0

    @property
    def volume(self) -> float:
        """晶胞体积 (Å³)"""
        alpha_r = np.radians(self.alpha)
        beta_r = np.radians(self.beta)
        gamma_r = np.radians(self.gamma)
        cos_a = np.cos(alpha_r)
        cos_b = np.cos(beta_r)
        cos_g = np.cos(gamma_r)
        return self.a * self.b * self.c * np.sqrt(
            1 - cos_a**2 - cos_b**2 - cos_g**2 + 2 * cos_a * cos_b * cos_g
        )

    def to_dict(self) -> dict:
        return {
            "a": self.a, "b": self.b, "c": self.c,
            "alpha": self.alpha, "beta": self.beta, "gamma": self.gamma,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LatticeParams":
        return cls(
            a=data.get("a", 1.0),
            b=data.get("b", 1.0),
            c=data.get("c", 1.0),
            alpha=data.get("alpha", 90.0),
            beta=data.get("beta", 90.0),
            gamma=data.get("gamma", 90.0),
        )


@dataclass
class Phase:
    """晶相/物相

    Attributes:
        name: 物相名称
        formula: 化学式
        space_group: 空间群
        lattice: 晶胞参数
        atomic_sites: 原子位点列表
        reference_peaks: 参考峰 (hkl, 2θ, 相对强度)
        weight_fraction: 质量分数
        match_score: 匹配分数
        cif_path: 关联的CIF文件路径
        elements: 物相所含元素集合
    """
    name: str = ""
    formula: str = ""
    space_group: str = ""
    lattice: Optional[LatticeParams] = None
    atomic_sites: list[dict] = field(default_factory=list)
    reference_peaks: list[tuple[tuple[int, int, int], float, float]] = field(default_factory=list)
    weight_fraction: float = 0.0
    match_score: float = 0.0
    cif_path: Optional[str] = None
    elements: set[str] = field(default_factory=set)
    # 密度 (g/cm³); COD/PDF2 库有实测/计算值时填入, 无则 None
    # (可由 services.search_restraints.estimate_density 按晶胞+化学式估算)
    density: Optional[float] = None
    # 来源库条目 ID (v2.6.0)。COD/PDF2 为库内 cod_id; 用户库为 9 亿段 ID
    # (services.user_db.USER_ID_BASE 起)。有它才能稳定回溯 CIF / 原子坐标,
    # 不必再从展示名里猜数字。
    db_id: Optional[int] = None

    def get_reference_peaks(self) -> list[tuple[tuple[int, int, int], float, float]]:
        """获取参考峰的 (hkl, 2θ, 强度) 列表

        Returns:
            [(hkl, two_theta, intensity), ...]
        """
        return self.reference_peaks

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "formula": self.formula,
            "space_group": self.space_group,
            "lattice": self.lattice.to_dict() if self.lattice else None,
            "atomic_sites": self.atomic_sites,
            "reference_peaks": [
                {"hkl": list(hkl), "two_theta": two_theta, "intensity": intensity}
                for hkl, two_theta, intensity in self.reference_peaks
            ],
            "weight_fraction": self.weight_fraction,
            "match_score": self.match_score,
            "cif_path": self.cif_path,
            "elements": sorted(self.elements),
            "density": self.density,
            "db_id": self.db_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Phase":
        lattice_data = data.get("lattice")
        lattice = LatticeParams.from_dict(lattice_data) if lattice_data else None

        reference_peaks = []
        for rp in data.get("reference_peaks", []):
            reference_peaks.append((
                tuple(rp["hkl"]),
                rp["two_theta"],
                rp.get("intensity", 0),
            ))

        elements = set(data.get("elements", []))

        return cls(
            name=data.get("name", ""),
            formula=data.get("formula", ""),
            space_group=data.get("space_group", ""),
            lattice=lattice,
            atomic_sites=data.get("atomic_sites", []),
            reference_peaks=reference_peaks,
            weight_fraction=data.get("weight_fraction", 0),
            match_score=data.get("match_score", 0),
            cif_path=data.get("cif_path"),
            elements=elements,
            density=data.get("density"),
            db_id=data.get("db_id"),
        )


@dataclass
class PhaseMatchResult:
    """物相匹配结果

    Attributes:
        phase: 匹配的物相
        score: 匹配分数
            - FOM模式: FOM值 (越低越好)
            - Profile Fitting模式: 相关系数×100 (越高越好)
        matched_peaks: 匹配的峰数
        total_peaks: 物相的总峰数
        confidence: 置信度描述
        r_factor: R因子 (Profile Fitting模式使用, 越低越好)
        method: 识别方法 ("fom" 或 "profile_fitting")
        zero_shift: B-6 per-entry 零点校正采用的 2θ 偏移 (度); 0.0 = 未启用或
            dz=0 最优
    """
    phase: Phase
    score: float
    matched_peaks: int = 0
    total_peaks: int = 0
    confidence: str = ""
    r_factor: float = 0.0
    method: str = "fom"
    zero_shift: float = 0.0

    @property
    def coverage(self) -> float:
        """峰覆盖率 (%)"""
        if self.total_peaks > 0:
            return 100.0 * self.matched_peaks / self.total_peaks
        return 0.0

    @property
    def score_display(self) -> str:
        """格式化分数字符串"""
        if self.method == "profile_fitting":
            return f"{self.score:.1f}%"
        else:
            return f"{self.score:.3f}"

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.to_dict(),
            "score": self.score,
            "matched_peaks": self.matched_peaks,
            "total_peaks": self.total_peaks,
            "coverage": self.coverage,
            "confidence": self.confidence,
        }
