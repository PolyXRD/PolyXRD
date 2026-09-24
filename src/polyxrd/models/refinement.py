"""
精修结果模型
============
Rietveld精修的结果数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from polyxrd.i18n import tr
from polyxrd.i18n.diag_texts import metric_note_text
from polyxrd.models.phase import Phase


def quality_grade_for(wr: float) -> str:
    """按**实验室粉末 XRD**口径给 Rwp 分级 (v1.1.2 起唯一分级入口)。

    历史上有两套阈值: ``RefinementResult.quality_grade`` 用 <2/<5/<10/<20
    (同步辐射口径, 对实验室数据过于苛刻), 而 ``_refine_builtin`` 等引擎
    内部又各写一套 <5/<10/<20 → 同一结果给出两种等级。现统一到此处:

        <5 优秀 / <10 良好 / <15 一般 / <25 差 / ≥25 需改进

    (实验室 XRD 的 Rwp 10~15% 已属可发表水平; 见 docs 精修方案 §2)
    """
    if wr < 5.0:
        return tr("quality.excellent")
    if wr < 10.0:
        return tr("quality.good")
    if wr < 15.0:
        return tr("quality.fair")
    if wr < 25.0:
        return tr("quality.poor")
    return tr("quality.bad")


@dataclass
class RefinementResult:
    """Rietveld精修结果

    Attributes:
        phases: 精修后的物相列表
        observed_data: 实验数据 (x, y)
        simulated_data: 模拟数据 (x, y)
        residual_data: 残差数据 (x, y)
        wR: 加权轮廓 R 因子 (与 Rwp 同一量, 保留字段名兼容旧代码/旧项目文件)
        Rexp: 期望 R 因子 (%) — Rexp = sqrt((N-P) / Σ w·y_obs²) × 100
        Rb: **废弃槽位** —— 历史字段名。旧代码把"轮廓 R"误标为"Bragg R";
            真实 Bragg R (按各 hkl 积分强度 Σ|I_obs-I_calc|/Σ I_obs) 尚未实现,
            本字段现恒为 0。保留仅为兼容旧项目文件读取 (旧文件中它存的是轮廓 R)。
        Rp: 轮廓 R 因子 (%) — Rp = Σ|y_obs - y_calc| / Σ y_obs × 100 (不加权)
        chi2 / chi2_red: 加权残差平方和与其归一值 (= GOF²)
        metrics_valid: Rexp/GOF/chi2 是否可解读 (需统计权重; 单位权下无物理意义)
        metric_note: 指标口径提示 (界面直接展示)
        GOF: 优良度因子 (v0.15.2 起为标准定义 GOF = Rwp / Rexp)
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
    Rexp: float = 0.0
    Rb: float = 0.0
    Rp: float = 0.0
    chi2: float = 0.0
    chi2_red: float = 0.0
    metrics_valid: bool = True
    metric_note: str = ""
    GOF: float = 0.0
    quality: str = ""
    num_cycles: int = 0
    converged: bool = False
    time_seconds: float = 0.0
    fit_params: dict = field(default_factory=dict)
    # v1.1.2: 面向用户的提示 (引擎回退 / 检测到 Kα2 / 指标不可解读等)
    warnings: list[str] = field(default_factory=list)
    # v2.1-B: 结构化诊断 [{code, params}] —— 服务层只产出代码与参数,
    # 文案由 UI/报告层用 tr() 渲染 (服务层不得依赖界面语言)。
    # 旧版 Chinese 文案仍走 warnings 字段读取兼容旧项目文件。
    diagnostics: list[dict] = field(default_factory=list)

    @property
    def rp_value(self) -> float:
        """轮廓 R: 优先新字段 Rp, 旧结果文件回退到历史字段 Rb。"""
        return self.Rp if self.Rp else self.Rb

    @property
    def Rwp(self) -> float:
        """加权轮廓 R 因子 (通用记法) — 与内部字段 wR 同一数值。"""
        return self.wR

    @property
    def quality_grade(self) -> str:
        """质量评级 (根据R因子); 文案随界面语言, 故走 i18n。"""
        return quality_grade_for(self.wR)

    def summary(self) -> str:
        """生成文本摘要报告 (随当前界面语言本地化)。"""
        lines = []
        lines.append("=" * 60)
        lines.append(tr("report.title"))
        lines.append("=" * 60)
        lines.append("")
        lines.append(tr("report.phase_count", count=len(self.phases)))
        lines.append(tr("report.cycles", cycles=self.num_cycles))
        lines.append(
            tr("report.converged") if self.converged else tr("report.not_converged")
        )
        lines.append(tr("report.time", time=f"{self.time_seconds:.1f}"))
        lines.append("")
        lines.append("-" * 40)
        lines.append(tr("report.quality_section"))
        lines.append("-" * 40)
        lines.append(tr("report.rwp_line", value=f"{self.Rwp:.4f}"))
        if self.metrics_valid:
            lines.append(tr("report.rexp_line", value=f"{self.Rexp:.4f}"))
            lines.append(tr("report.rb_line", value=f"{self.rp_value:.4f}"))
            lines.append(tr("report.gof_line", value=f"{self.GOF:.4f}"))
        else:
            lines.append(tr("report.metrics_invalid_line"))
            lines.append(tr("report.rb_line", value=f"{self.rp_value:.4f}"))
        # v2.1-B: 指标提示优先旧字段 (旧项目文件), 新结果由结构化诊断渲染
        _note = self.metric_note or metric_note_text(self)
        if _note:
            lines.append(tr("report.metric_note_line", value=_note))
        lines.append(tr("report.quality_line", value=self.quality_grade))
        lines.append("")
        lines.append("-" * 40)
        lines.append(tr("report.phase_section"))
        lines.append("-" * 40)

        total_fraction = 0.0
        for i, phase in enumerate(self.phases, 1):
            lines.append("")
            lines.append(tr("report.phase_header", index=i, name=phase.name))
            lines.append(tr("report.formula", formula=phase.formula))
            lines.append(
                tr("report.weight_fraction", value=f"{phase.weight_fraction:.2f}")
            )
            total_fraction += phase.weight_fraction

            if phase.lattice:
                lat = phase.lattice
                lines.append(
                    tr("report.cell_params",
                       a=f"{lat.a:.4f}", b=f"{lat.b:.4f}", c=f"{lat.c:.4f}")
                )
                lines.append(
                    tr("report.cell_angles",
                       alpha=f"{lat.alpha:.2f}", beta=f"{lat.beta:.2f}",
                       gamma=f"{lat.gamma:.2f}")
                )
                lines.append(
                    tr("report.cell_volume", volume=f"{lat.volume:.2f}")
                )

        lines.append("")
        lines.append(tr("report.total_fraction", value=f"{total_fraction:.2f}"))
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "phases": [p.to_dict() for p in self.phases],
            "wR": self.wR,
            "Rexp": self.Rexp,
            "Rb": self.Rb,
            "Rp": self.Rp,
            "chi2": self.chi2,
            "chi2_red": self.chi2_red,
            "metrics_valid": self.metrics_valid,
            "metric_note": self.metric_note,
            "GOF": self.GOF,
            "quality": self.quality,
            "quality_grade": self.quality_grade,
            "num_cycles": self.num_cycles,
            "converged": self.converged,
            "time_seconds": self.time_seconds,
            "fit_params": self.fit_params,
            "warnings": list(self.warnings),
            "diagnostics": [dict(d) for d in self.diagnostics if isinstance(d, dict)],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RefinementResult":
        phases = [Phase.from_dict(p) for p in data.get("phases", [])]
        return cls(
            phases=phases,
            wR=data.get("wR", 0),
            Rexp=data.get("Rexp", 0),
            Rb=data.get("Rb", 0),
            Rp=data.get("Rp", 0),
            chi2=data.get("chi2", 0),
            chi2_red=data.get("chi2_red", 0),
            metrics_valid=data.get("metrics_valid", True),
            metric_note=data.get("metric_note", ""),
            GOF=data.get("GOF", 0),
            quality=data.get("quality", ""),
            num_cycles=data.get("num_cycles", 0),
            converged=data.get("converged", False),
            time_seconds=data.get("time_seconds", 0),
            fit_params=data.get("fit_params", {}),
            warnings=list(data.get("warnings", []) or []),
            diagnostics=[
                dict(d) for d in (data.get("diagnostics", []) or [])
                if isinstance(d, dict) and d.get("code")
            ],
        )
