"""
Rietveld 精修选项 (M14)
========================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RefineOptions:
    """Rietveld 精修选项。

    生效范围说明:
      - preferred_orientation / zero_shift_init 在 refine() 入口生效
        (择优取向作用于参考峰强度; 零点作为内置引擎拟合初值)。
      - refine_* 开关 (M14 参数掩码): builtin 引擎已接入
          * refine_scale / refine_profile / refine_zero_shift: 关闭时把对应
            参数组夹到极窄上下界 (ε=1e-7) — 等效"冻结", scipy.least_squares
            要求严格 lb<ub, 不能直接 lower=upper。profile 一并冻结 fwhm + eta
            + (Caglioti 开启时) U/V/W。
          * refine_background / refine_cell: 在 builtin 中为 no-op — builtin
            不含背景/晶胞 fit 维度 (背景为 _estimate_background 一次性预处理,
            晶胞固定)。外部引擎 (GSAS-II / powerxrd) 可自行消费这两个开关。
    """
    refine_scale: bool = True
    refine_background: bool = True
    refine_profile: bool = True
    refine_cell: bool = True
    refine_zero_shift: bool = True
    # 择优取向: direction=[h,k,l], r=March-Dollase 取向参数 (1=无取向)
    preferred_orientation: Optional[dict] = None   # {"direction": [...], "r": float}
    # 零点误差初值 (度), 数据前校正符号见 calibration 模块
    zero_shift_init: float = 0.0

    def to_dict(self) -> dict:
        return {
            "refine_scale": self.refine_scale,
            "refine_background": self.refine_background,
            "refine_profile": self.refine_profile,
            "refine_cell": self.refine_cell,
            "refine_zero_shift": self.refine_zero_shift,
            "preferred_orientation": self.preferred_orientation,
            "zero_shift_init": self.zero_shift_init,
        }
