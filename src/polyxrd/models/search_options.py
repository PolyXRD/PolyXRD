"""
搜索-匹配选项模型 (M09/M10)
============================
对应"候选检索约束 + 搜索匹配参数"。默认值=最宽松, 与旧行为一致;
字段均可选, 留 None/False 表示不启用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchOptions:
    """一次 search-match 的约束与参数。

    元素语义 (与内置库一致): 物相元素须 ⊆ (must∪maybe), 且与 exclude 无交集。
    score 语义: foam score 越低越好 (与既有 FOM 相同)。
    """
    # 化学组成约束
    must: list = field(default_factory=list)
    maybe: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    # 名称 (大小写敏感通配, 如 "*corundum*")
    name_pattern: Optional[str] = None
    # 匹配质量
    score_threshold: Optional[float] = None   # 只保留 score <= 阈值 (越低越严)
    max_entries: Optional[int] = None          # 返回条数上限
    check_three_strongest: bool = False        # 参考谱前3强峰预检
    three_strongest_hits: int = 1              # 预检要求的最少命中数
    # 峰位关联窗口
    delta_2theta: Optional[float] = None       # None → 由 delta_2theta_auto 决定
    delta_2theta_auto: bool = True             # 窗口 = 系数×平均 FWHM
    delta_2theta_factor: float = 1.0
    default_fwhm: float = 0.15                 # 峰无 FWHM 时的兜底
    # 评分开关
    use_intensity: bool = True                 # FoM 是否计入强度一致性
    metal_penalty: float = 1.5                 # 纯金属相 FoM 惩罚系数 (对齐基线)
    tol_fallback: float = 0.15                 # 自动窗口失效时的兜底容差
