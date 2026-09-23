"""
精修模板系统
============
提供Rietveld精修预设模板管理，支持内置模板和用户自定义模板。

内置模板涵盖常见实验场景：标准晶态、快速物相分析、多相混合物、
低结晶度样品、同步辐射数据、常规Cu靶数据等。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from polyxrd.config import get_config


@dataclass
class RefinementTemplate:
    """精修模板

    封装一组Rietveld精修参数预设，用于快速启动精修。

    Attributes:
        name: 模板名称 (同时是**用户模板的标识/文件名**, 所以不能翻译)
        description: 模板描述
        key: 内置模板的**稳定标识** (如 ``standard`` / ``quick``)。内置模板的
            显示名走 ``template.builtin.<key>`` 翻译键 —— ``name`` 仍是中文,
            因为它同时被 ``save_template`` 当文件名、被 ``get_template_by_name``
            当查找键, 一旦本地化就会随语言漂移。用户模板留空 = 显示 ``name``。
        engine: 精修引擎 (gsas2 / powerxrd / builtin)
        strategy: 精修策略 (sequential / auto / manual)
        background_method: 背景扣除方法 (snip / als / polynomial / median / rolling)
        peak_shape: 峰形模型 (voigt / pseudo-voigt / lorentzian / gaussian)
        max_cycles: 最大精修循环数
        params: 额外参数字典
        is_builtin: 是否为内置模板
    """

    name: str = ""
    description: str = ""
    key: str = ""
    engine: str = "builtin"
    strategy: str = "sequential"
    background_method: str = "snip"
    peak_shape: str = "pseudo-voigt"
    max_cycles: int = 20
    params: dict[str, Any] = field(default_factory=dict)
    is_builtin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RefinementTemplate":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            key=data.get("key", ""),
            engine=data.get("engine", "builtin"),
            strategy=data.get("strategy", "sequential"),
            background_method=data.get("background_method", "snip"),
            peak_shape=data.get("peak_shape", "pseudo-voigt"),
            max_cycles=data.get("max_cycles", 20),
            params=data.get("params", {}),
            is_builtin=data.get("is_builtin", False),
        )

    def to_config(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "strategy": self.strategy,
            "background_method": self.background_method,
            "peak_shape": self.peak_shape,
            "max_cycles": self.max_cycles,
            "params": dict(self.params),
        }


_BUILTIN_TEMPLATES: list[RefinementTemplate] = [
    RefinementTemplate(
        name="自动选择（推荐）",
        key="auto",
        description=(
            "按样品条件自动选引擎: 全部物相都有结构 CIF 且 GSAS-II 可用时走 "
            "GSAS-II（真 Rietveld + wt% 定量），否则回退内置引擎（无结构剖面拟合）。"
            "不确定选哪个时用这个。"
        ),
        engine="auto",
        strategy="sequential",
        background_method="snip",
        peak_shape="pseudo-voigt",
        max_cycles=20,
        params={},
        is_builtin=True,
    ),
    RefinementTemplate(
        name="标准晶态样品",
        key="standard",
        description="适用于结晶度良好的常规样品，使用GSAS-II引擎和Voigt峰形",
        engine="gsas2",
        strategy="sequential",
        background_method="snip",
        peak_shape="voigt",
        max_cycles=20,
        params={"rwp_tolerance": 0.0001, "refine_lattice": True, "refine_atoms": True},
        is_builtin=True,
    ),
    RefinementTemplate(
        name="快速物相分析",
        key="quick",
        description="快速物相识别与定量分析，使用内置引擎自动精修",
        engine="builtin",
        strategy="auto",
        background_method="als",
        peak_shape="pseudo-voigt",
        max_cycles=10,
        params={"quick_scan": True, "min_rwp": 5.0},
        is_builtin=True,
    ),
    RefinementTemplate(
        name="多相混合物",
        key="multiphase",
        description="多相混合物定量分析，支持多个物相的序贯精修",
        engine="gsas2",
        strategy="sequential",
        background_method="polynomial",
        peak_shape="voigt",
        max_cycles=30,
        params={"refine_weight_fractions": True, "poly_order": 6},
        is_builtin=True,
    ),
    RefinementTemplate(
        name="低结晶度样品",
        key="low_cryst",
        description="适用于无定形或低结晶度样品，使用powerxrd和Lorentzian峰形",
        engine="powerxrd",
        strategy="auto",
        background_method="median",
        peak_shape="lorentzian",
        max_cycles=15,
        params={"fwhm_refine": True, "strain_analysis": True},
        is_builtin=True,
    ),
    RefinementTemplate(
        name="同步辐射数据",
        key="synchrotron",
        description="同步辐射高精度数据精修，使用GSAS-II引擎和SNIP背景",
        engine="gsas2",
        strategy="sequential",
        background_method="snip",
        peak_shape="voigt",
        max_cycles=50,
        params={"high_precision": True, "refine_thermal": True, "refine_sites": True, "rwp_tolerance": 0.00001},
        is_builtin=True,
    ),
    RefinementTemplate(
        name="常规Cu靶数据",
        key="cu_target",
        description="常规Cu靶X射线衍射数据，使用内置引擎和滚动平均背景",
        engine="builtin",
        strategy="sequential",
        background_method="rolling",
        peak_shape="pseudo-voigt",
        max_cycles=25,
        params={"window_size": 50, "refine_lattice": True},
        is_builtin=True,
    ),
]


class RefinementTemplateManager:
    """精修模板管理器

    管理内置模板和用户自定义模板的保存/加载。
    用户模板保存在 ~/.polyxrd/refinement_templates/ 目录下。

    Attributes:
        USER_TEMPLATES_DIR: 用户模板保存目录
    """

    USER_TEMPLATES_DIR: str = "refinement_templates"

    def __init__(self) -> None:
        self._config = get_config()
        self._user_templates: list[RefinementTemplate] = []
        self._load_user_templates()

    @property
    def user_templates_dir(self) -> Path:
        return self._config.cif_db_path.parent / self.USER_TEMPLATES_DIR

    # ------------------------------------------------------------------
    # 模板查询
    # ------------------------------------------------------------------

    def get_builtin_templates(self) -> list[RefinementTemplate]:
        return [RefinementTemplate(**t.to_dict()) for t in _BUILTIN_TEMPLATES]

    def get_user_templates(self) -> list[RefinementTemplate]:
        return list(self._user_templates)

    def get_all_templates(self) -> list[RefinementTemplate]:
        return self.get_builtin_templates() + self.get_user_templates()

    def get_template_by_name(self, name: str) -> Optional[RefinementTemplate]:
        for t in self.get_all_templates():
            if t.name == name:
                return t
        return None

    # ------------------------------------------------------------------
    # 模板保存/加载
    # ------------------------------------------------------------------

    def save_template(self, template: RefinementTemplate) -> None:
        self.user_templates_dir.mkdir(parents=True, exist_ok=True)
        path = self.user_templates_dir / f"{template.name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(template.to_dict(), f, indent=2, ensure_ascii=False)
        template.is_builtin = False
        if template not in self._user_templates:
            self._user_templates.append(template)

    def load_template(self, name: str) -> Optional[RefinementTemplate]:
        path = self.user_templates_dir / f"{name}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            t = RefinementTemplate.from_dict(data)
            t.is_builtin = False
            return t
        return None

    def delete_user_template(self, name: str) -> bool:
        path = self.user_templates_dir / f"{name}.json"
        if path.exists():
            path.unlink()
        self._user_templates = [t for t in self._user_templates if t.name != name]
        return True

    def _load_user_templates(self) -> None:
        self._user_templates = []
        if not self.user_templates_dir.exists():
            return
        for path in sorted(self.user_templates_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                t = RefinementTemplate.from_dict(data)
                t.is_builtin = False
                self._user_templates.append(t)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    # ------------------------------------------------------------------
    # 从配置创建模板
    # ------------------------------------------------------------------

    def create_from_config(
        self,
        config: dict[str, Any],
        name: str = "",
        description: str = "",
    ) -> RefinementTemplate:
        return RefinementTemplate(
            name=name or "自定义模板",
            description=description or "从当前精修配置创建的模板",
            engine=config.get("engine", "builtin"),
            strategy=config.get("strategy", "sequential"),
            background_method=config.get("background_method", "snip"),
            peak_shape=config.get("peak_shape", "pseudo-voigt"),
            max_cycles=config.get("max_cycles", 20),
            params=config.get("params", {}),
            is_builtin=False,
        )

    def create_from_refinement_result(
        self,
        result: Any,
        name: str = "",
        description: str = "",
    ) -> RefinementTemplate:
        params = {}
        if hasattr(result, "fit_params") and result.fit_params:
            params.update(result.fit_params)
        if hasattr(result, "phases") and result.phases:
            params["phase_count"] = len(result.phases)
        return RefinementTemplate(
            name=name or "精修结果模板",
            description=description or "从精修结果创建的模板",
            engine=params.get("engine", "builtin"),
            strategy=params.get("strategy", "sequential"),
            max_cycles=getattr(result, "num_cycles", 20) or 20,
            params=params,
            is_builtin=False,
        )