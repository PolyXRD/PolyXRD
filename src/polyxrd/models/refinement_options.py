"""
Rietveld 精修选项 (M14)
========================
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def parse_grain_radii(text: str) -> Optional[list[float]]:
    """解析 GUI 的「逐相颗粒半径」输入（P0-G）。

    支持英文/中文逗号与分号分隔；留空返回 ``None``（= 全部用全局缺省）。
    非法或非正值拋 ``ValueError``，由调用方决定是拦下还是退回全局半径。
    """
    if not text or not text.strip():
        return None
    vals: list[float] = []
    for part in text.replace("，", ",").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        val = float(part)
        if not (val > 0.0) or val != val or val in (float("inf"), float("-inf")):
            raise ValueError(f"颗粒半径必须是有限正值: {part}")
        vals.append(val)
    return vals or None


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
    # ── 系统性强度误差 (v5.2)，两个都默认关 ──────────────────────
    # 表面粗糙度: "none" / "sidey"(单参数，默认首选) / "suortti" / "sparks"。
    # 只在 refinement 引擎生效；refine_roughness=False 时按 grain 的 s 固定修正。
    roughness_model: str = "none"
    refine_roughness: bool = False
    # 微吸收 (Brindley): 需要真实颗粒半径 (µm)。**不设默认半径** —— 半径是
    # 可测量的物理量，猜一个 10 µm 会把本来定量对的样品打偏 5 pp 以上
    # （基准报告 §22.6）。microabsorption=False 或 radius<=0 → 不修正。
    microabsorption: bool = False
    grain_radius_um: float = 0.0
    #: 逐相颗粒半径（P0-G）：与 ``phases`` 等长的 µm 序列；None → 全部用
    #: ``grain_radius_um``。单一半径的 Brindley 自由度不够（评估报告 §12.4）。
    grain_radii_um: Optional[list[float]] = None

    def to_dict(self) -> dict:
        return {
            "refine_scale": self.refine_scale,
            "refine_background": self.refine_background,
            "refine_profile": self.refine_profile,
            "refine_cell": self.refine_cell,
            "refine_zero_shift": self.refine_zero_shift,
            "preferred_orientation": self.preferred_orientation,
            "zero_shift_init": self.zero_shift_init,
            "roughness_model": self.roughness_model,
            "refine_roughness": self.refine_roughness,
            "microabsorption": self.microabsorption,
            "grain_radius_um": self.grain_radius_um,
            "grain_radii_um": (
                list(self.grain_radii_um) if self.grain_radii_um else None
            ),
        }
