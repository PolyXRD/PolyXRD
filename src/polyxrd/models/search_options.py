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

    元素语义 (四类, 0.9.11): 记 S = 物相元素集合
      - must_have (必有): P ⊆ S        每个必有元素都必须出现 (AND)
      - must      (含有): S ∩ H ≠ ∅    至少含一个; 含有为空时 maybe 代行其职
      - maybe     (可能): 无强制条件     仅放宽允许池
      - exclude   (没有): S ∩ E = ∅    含任一即淘汰
    未勾选元素默认并入「没有」(等价 S ⊆ P∪H∪M), 仅在 必有/含有/可能
    至少勾中一项时启用; 三者全空 = 全库搜索, 只勾「没有」= 开放世界。
    score 语义: foam score 越低越好 (与既有 FOM 相同)。
    """
    # 化学组成约束
    must_have: list = field(default_factory=list)   # 必有 (AND)
    must: list = field(default_factory=list)        # 含有 (至少一个)
    maybe: list = field(default_factory=list)       # 可能 (可选)
    exclude: list = field(default_factory=list)     # 没有
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
