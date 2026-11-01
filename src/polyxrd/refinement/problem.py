"""把"参数向量 → 计算谱 → 残差"串起来的最小问题对象。

这是变量投影的**外层**：给定非线性参数 ``x``，装配设计矩阵、闭式解线性层、
返回加权残差。它不含任何优化算法（那在 ``optimize.py``），也不含阶段协议之外
的业务判断，因此可以用合成数据做 round-trip 单测：真参数 → 合成谱 → 精修 →
回收参数。

缓存分两级（B3）
----------------
1. **反射表**：只在**晶胞参数**变化时重建（``enumerate_hkl`` + 结构因子是
   最贵的一步）。峰形、择优 ``r``、标度、背景的变化都**不**触发重建 ——
   这是 ``ReflectionTable`` 把 ``po_detail`` 与峰形参数排除在外的设计回报。
2. **设计矩阵**：在反射表 + 峰形 + 样品展宽 + 零位这批"形状量"都未变时复用。

两级缓存让阶段 2（只动峰形）每次评估省掉反射重建，实测从 ~40 ms 降到 ~12 ms。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .background import BackgroundParams, background_basis
from .diagnostics import Diagnostics, diagnose
from .linear import LinearSolve, design_stack, solve_linear
from .optimize import FitResult, minimize_residual
from .parameters import Parameter, ParameterSet
from .pattern import DEFAULT_CUTOFF_FWHM, PhaseSpec, design_matrix
from .profile import Kalpha2, ProfileParams
from .quantitative import QuantResult, hill_howard
from .structure import AtomSite, Cell, ReflectionTable, StructureModel, build_reflections
from .symmetry import apply_cell_ties

__all__ = [
    "PhaseBlock",
    "PatternProblem",
    "FitSummary",
    "finalize_summary",
    "pattern_metrics",
]

#: 各项指标的分母保护（整条谱全 0 时避免除零）
_EPS_DENOM = 1e-30


def pattern_metrics(
    y_obs: np.ndarray,
    y_calc: np.ndarray,
    weights: Optional[np.ndarray] = None,
    n_params: int = 0,
) -> Dict[str, float]:
    """Rietveld 常规吻合指标。

    * ``Rwp``：加权剩余，**分母 Σw·y²**（Rietveld 惯例，不是 Σw·(y−ȳ)²）
    * ``Rp``：未加权剩余
    * ``Rexp``：期望剩余 ``sqrt((N−P)/Σw·y²)``，代表"数据本身的噪声底"
    * ``GOF``：``Rwp/Rexp``，实验室口径 <2 优秀、<4 可接受
    * ``chi2``：``Σw·r²/(N−P)``

    ``Rwp < Rexp``（GOF<1）几乎总是**过拟合**或权重高估，不要当成好结果。
    """
    y = np.asarray(y_obs, dtype=float)
    yc = np.asarray(y_calc, dtype=float)
    n = y.size
    if n == 0:
        return {"Rwp": float("nan"), "Rp": float("nan"), "Rexp": float("nan"),
                "GOF": float("nan"), "chi2": float("nan"), "n": 0}
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    r = y - yc
    denom_w = float(np.sum(w * y * y)) or _EPS_DENOM
    denom = float(np.sum(np.abs(y))) or _EPS_DENOM
    chi2_sum = float(np.sum(w * r * r))
    dof = max(n - int(n_params), 1)
    rwp = math.sqrt(chi2_sum / denom_w) * 100.0
    rexp = math.sqrt(dof / denom_w) * 100.0
    return {
        "Rwp": rwp,
        "Rp": float(np.sum(np.abs(r)) / denom) * 100.0,
        "Rexp": rexp,
        "GOF": (rwp / rexp) if rexp > 0 else float("nan"),
        "chi2": chi2_sum / dof,
        "n": int(n),
        "n_params": int(n_params),
    }


@dataclass
class PhaseBlock:
    """一相的可变状态（晶胞、样品展宽、择优、标度、反射表缓存）。"""

    label: str
    structure: StructureModel
    index: int = 0
    po_hkl: Optional[Tuple[float, float, float]] = None
    size_nm: float = 0.0
    strain: float = 0.0
    po_r: float = 1.0
    scale: float = 1.0
    table: Optional[ReflectionTable] = None
    _table_key: tuple = field(default=(), repr=False)

    @property
    def prefix(self) -> str:
        return f"phase{self.index}"

    def cell_key(self) -> tuple:
        c = self.structure.cell
        return (round(c.a, 9), round(c.b, 9), round(c.c, 9),
                round(c.alpha, 9), round(c.beta, 9), round(c.gamma, 9),
                tuple(self.po_hkl) if self.po_hkl else None)

    def ensure_table(
        self,
        two_theta_range: Tuple[float, float],
        wavelengths,
        *,
        noise_ratio: float = 1e-9,
        pad: float = 2.0,
    ) -> ReflectionTable:
        """按晶胞键缓存反射表（B3 一级缓存）。"""
        key = self.cell_key() + (round(two_theta_range[0] - pad, 6),
                                 round(two_theta_range[1] + pad, 6),
                                 tuple(np.atleast_1d(wavelengths).astype(float)
                                       .ravel().tolist()))
        if self.table is not None and key == self._table_key:
            return self.table
        po_dir = None
        if self.po_hkl:
            from .structure import po_direction_from_hkl
            po_dir = po_direction_from_hkl(self.po_hkl, self.structure.cell)
        self.table = build_reflections(
            self.structure,
            two_theta_range=(two_theta_range[0] - pad, two_theta_range[1] + pad),
            wavelengths=wavelengths,
            po_direction=po_dir,
            noise_ratio=noise_ratio,
        )
        self._table_key = key
        return self.table

    def invalidate(self) -> None:
        self.table = None
        self._table_key = ()


@dataclass
class FitSummary:
    """一次（可分阶段的）精修的结果汇总。"""

    result: FitResult
    params: ParameterSet
    metrics: Dict[str, float]
    stages: List[dict] = field(default_factory=list)
    linear: Optional[LinearSolve] = None
    y_calc: Optional[np.ndarray] = None
    diagnostics: Optional[Diagnostics] = None
    quant: Optional[QuantResult] = None

    @property
    def status(self) -> str:
        return self.result.status

    def summary_line(self) -> str:
        return (f"{self.result.status}: Rwp={self.metrics['Rwp']:.2f}% "
                f"GOF={self.metrics['GOF']:.2f} nfev={self.result.nfev}")

    def as_dict(self) -> dict:
        """给日志/报告用的扁平结构（不含大数组）。"""
        return {
            "status": self.status,
            "Rwp": self.metrics["Rwp"],
            "Rp": self.metrics["Rp"],
            "Rexp": self.metrics["Rexp"],
            "GOF": self.metrics["GOF"],
            "chi2": self.metrics["chi2"],
            "stages": self.stages,
            "params": {p.name: p.value for p in self.params},
            "sigmas": {p.name: p.sigma for p in self.params if p.sigma},
            "warnings": list(self.diagnostics.warnings) if self.diagnostics else [],
            "quant": self.quant.percent() if self.quant else (),
        }


class PatternProblem:
    """多相全谱拟合问题（变量投影）。

    :param two_theta: 观测网格（度，单调递增）
    :param y_obs: 观测强度
    :param phases: ``PhaseBlock`` 列表
    :param profile: 仪器峰形（样品层由各相 ``size_nm/strain`` 覆盖）
    :param bg: 背景基描述
    :param kalph2: Kα2 描述；None → 单色
    :param weights: 观测权重；None → ``1/max(y,1)``（Poisson）
    """

    def __init__(
        self,
        two_theta,
        y_obs,
        phases: Sequence[PhaseBlock],
        *,
        profile: Optional[ProfileParams] = None,
        bg: Optional[BackgroundParams] = None,
        wavelength: float = 1.54056,
        kalph2: Optional[Kalpha2] = None,
        weights: Optional[np.ndarray] = None,
        cutoff_fwhm: Optional[float] = DEFAULT_CUTOFF_FWHM,
        params: Optional[ParameterSet] = None,
    ) -> None:
        self.two_theta = np.asarray(two_theta, dtype=float)
        self.y_obs = np.asarray(y_obs, dtype=float)
        if self.two_theta.size != self.y_obs.size:
            raise ValueError("two_theta 与 y_obs 长度不符")
        if not phases:
            raise ValueError("至少需要一相")
        self.phases: List[PhaseBlock] = list(phases)
        self.profile = profile or ProfileParams()
        self.bg = bg or BackgroundParams()
        self.wavelength = float(wavelength)
        self.kalph2 = kalph2
        self.cutoff_fwhm = cutoff_fwhm

        if weights is None:
            self.weights = 1.0 / np.maximum(self.y_obs, 1.0)
        else:
            w = np.asarray(weights, dtype=float)
            if w.size != self.y_obs.size:
                raise ValueError("weights 长度与观测不符")
            self.weights = w

        self.shift = 0.0
        self.disp = 0.0
        self._atom_slots: Dict[int, List[Optional[int]]] = {}
        self.params = params if params is not None else self.build_parameters()
        if not self._atom_slots:
            self._atom_slots = self._build_atom_slots()

        self._basis: Optional[np.ndarray] = None
        self._bg_basis: Optional[np.ndarray] = None
        self._design_key: tuple = ()
        self.last_linear: Optional[LinearSolve] = None

    # ── 参数书构建 ──────────────────────────────────────────────
    def build_parameters(
        self,
        *,
        stages: Optional[Dict[str, int]] = None,
        with_atoms: bool = True,
    ) -> ParameterSet:
        """按命名约定生成完整参数书（阶段默认见 ``STAGE_LABELS``）。"""
        st = {
            "scale": 1, "bg": 1,
            "cell": 2, "zero": 2,
            "profile": 3, "asym": 3,
            "po": 4,
            "sample": 5,
            "atom": 6,
        }
        if stages:
            st.update(stages)

        ps = ParameterSet()
        # 仪器
        ps.add(Parameter("inst.zero", 0.0, -1.0, 1.0, stage=st["zero"],
                         label="零位偏移 (°)"))
        # 样品位移：Δ2θ = disp·cosθ（Bragg–Brentano 样品高度偏差 h → 2h/R·cosθ）。
        # 与零位的分野：zero 是常数、disp 随角衰减。两者一起放开才补得掉
        # "零位已修、低角仍偏"的残差 —— 实测口径是交叉样本 a 系统性偏 −0.11%
        # 且两个零位不同的试样偏得一样多（这正是 cosθ 项的指纹）。
        # 界 ±0.5°：h=1 mm / R=240 mm 也才 0.48°，物理上到顶了。
        ps.add(Parameter("inst.disp", 0.0, -0.5, 0.5, stage=st["zero"],
                         label="样品位移 cosθ 项 (°)"))
        ps.add(Parameter("inst.asym", float(self.profile.asymmetry), 0.0, 0.4,
                         stage=st["asym"], label="低角不对称"))
        # 精修里**不设** inst.eta：η 由 TCH 的宽度比导出（与 GSAS-II 一致）。
        # 设一个独立的 η 会与 x/y 抢同一自由度（η 与 FWHM 强相关），是病态的根源。
        # Caglioti U/V/W：U、V 允许为负（U<0 在实测里很常见 —— tan²θ 项在
        # 高角压峰宽），W 是常数项必须 >0。
        # Lorentz X/Y/Z：**宽度项必须 ≥0**。允许负值会让 TCH 的 L 在部分角域
        # 变负 → 被 clip 到 0 → 模型出现"分段"行为，且与 W 强补偿（实测
        # y 跑到 -0.052、x 跑到 0.022 而 GOF 仍是 1.00 —— 纯粹是退化解）。
        # 模式必须**静态钉住**（见 ProfileParams.use_tch）：精修一律走 TCH，
        # η 由宽度比导出、不设独立的 eta 参数（独立 η 会与 x/y 抢同一自由度）。
        for tag, val, lo, hi in (("u", self.profile.u, -1.0, 1.0),
                                 ("v", self.profile.v, -1.0, 1.0),
                                 ("w", self.profile.w, 1e-9, 1.0),
                                 ("x", self.profile.x, 0.0, 1.0),
                                 ("y", self.profile.y, 0.0, 1.0),
                                 ("z", self.profile.z, 0.0, 1.0)):
            ps.add(Parameter(f"inst.{tag}", float(val), lo, hi,
                             stage=st["profile"], label=f"Caglioti/Lorentz {tag.upper()}"))

        for ph in self.phases:
            p = ph.prefix
            # 标度与背景系数**不进非线性向量**：它们由线性层每轮闭式解出
            # （变量投影）。放进 x 会让雅可比多出一整列恒零 → Hessian 奇异。
            # 这里保留成 fixed 参数只为"展示 + 定量（Hill–Howard）读取"，
            # 每次求解后用 ``_sync_linear`` 把解回写。
            ps.add(Parameter(f"{p}.scale", float(ph.scale), 0.0, np.inf,
                             fixed=True, stage=st["scale"],
                             label=f"{ph.label} 标度（线性层）"))
            c = ph.structure.cell
            for tag, val, lo, hi in (
                ("a", c.a, 0.0, np.inf), ("b", c.b, 0.0, np.inf),
                ("c", c.c, 0.0, np.inf),
                ("alpha", c.alpha, 1e-3, 180.0 - 1e-3),
                ("beta", c.beta, 1e-3, 180.0 - 1e-3),
                ("gamma", c.gamma, 1e-3, 180.0 - 1e-3),
            ):
                ps.add(Parameter(f"{p}.cell.{tag}", float(val), lo, hi,
                                 stage=st["cell"],
                                 label=f"{ph.label} {tag}"))
            ps.add(Parameter(f"{p}.size", float(ph.size_nm), 0.0, 100000.0,
                             stage=st["sample"], label=f"{ph.label} 晶粒 (nm)"))
            ps.add(Parameter(f"{p}.strain", float(ph.strain), 0.0, 0.2,
                             stage=st["sample"], label=f"{ph.label} 应变 ε"))
            # 择优取向：**没给惯习面就不放这个自由度**。``po_hkl is None`` 时
            # March–Dollase 权重恒为 1（``build_reflections`` 不写 cosα），
            # 这一列雅可比全零 —— 放出来白占一个自由度、还让 rank 检查报亏。
            # 用户后来补 po_hkl 时需重建参数书（UI 侧本来就重建）。
            ps.add(Parameter(f"{p}.po.r", float(ph.po_r), 0.05, 20.0,
                             stage=st["po"], fixed=ph.po_hkl is None,
                             label=f"{ph.label} 择优 r"))

            if with_atoms:
                # 只对**独立位点**（非对称单元）放坐标自由度：全胞展开后同一
                # Wyckoff 轨道上的原子是同一个自由度，逐原子放开必然共线。
                for k, site in enumerate(self._independent_sites(ph)):
                    for tag, val, lo, hi in (
                        ("x", site.x, -1.0, 2.0), ("y", site.y, -1.0, 2.0),
                        ("z", site.z, -1.0, 2.0),
                    ):
                        ps.add(Parameter(f"{p}.atom{k}.{tag}", float(val), lo, hi,
                                         stage=st["atom"],
                                         label=f"{ph.label} {site.label or k} {tag}"))
                    ps.add(Parameter(f"{p}.atom{k}.occ", float(site.occupancy),
                                     0.0, 1.0, stage=st["atom"],
                                     label=f"{ph.label} {site.label or k} 占位"))
                    ps.add(Parameter(f"{p}.atom{k}.biso", float(site.b_iso),
                                     0.0, 50.0, stage=st["atom"],
                                     label=f"{ph.label} {site.label or k} B"))

        for k in range(self.bg.n_coeffs):
            ps.add(Parameter(f"bg.c{k}", 0.0, -np.inf, np.inf, fixed=True,
                             stage=st["bg"],
                             label=f"背景 c{k}（线性层）"))
        # 按空间群约束胞参：六方只放 a/c、立方只放 a，其余由对称性定死或跟随。
        # 不做这一步，高对称相放开 6 个胞参必然秩亏（详见 symmetry 模块）。
        for ph in self.phases:
            apply_cell_ties(ps, ph.prefix,
                            getattr(ph.structure, "space_group", "") or "",
                            getattr(ph.structure, "cell", None))
        self._atom_slots = self._build_atom_slots()
        return ps

    @staticmethod
    def _independent_sites(ph: PhaseBlock) -> List[AtomSite]:
        """按 (元素, 坐标, 占位, B) 去重 —— 只去掉**真的完全相同**的位点。

        注意：这**不是** Wyckoff 轨道归并。``StructureModel`` 存的是已展开的
        全胞（P1），同一轨道上的原子坐标各不相同，所以这里照样会全部返回。
        高对称相（刚玉 30 个 O、方解石 30 个位点）放开坐标会有大量共线自由度，
        真 Rietveld 需要"按轨道只放独立位点"—— 该归并尚未实现（v5.1 待办）。
        默认协议止步于样品展宽，不会碰到这一步。
        """
        seen: Dict[tuple, AtomSite] = {}
        for s in ph.structure.sites:
            key = (s.element, round(s.x, 6), round(s.y, 6), round(s.z, 6),
                   round(s.occupancy, 6), round(s.b_iso, 6))
            if key not in seen:
                seen[key] = s
        return list(seen.values())

    # ── 参数 → 状态 ────────────────────────────────────────────
    def apply(self) -> None:
        """把 ``self.params`` 的当前值写进内部状态（profile / 晶胞 / 位点）。"""
        # 先重算跟随约束（六方 b=a 等）：调用方可能绕过 assign 直接 set。
        self.params.refresh_constraints()
        g = self.params.get
        self.shift = float(g("inst.zero", 0.0) or 0.0)
        self.disp = float(g("inst.disp", 0.0) or 0.0)
        self.profile = replace(
            self.profile,
            u=float(g("inst.u", self.profile.u) or 0.0),
            v=float(g("inst.v", self.profile.v) or 0.0),
            w=float(g("inst.w", self.profile.w) or 0.0),
            x=float(g("inst.x", self.profile.x) or 0.0),
            y=float(g("inst.y", self.profile.y) or 0.0),
            z=float(g("inst.z", self.profile.z) or 0.0),
            eta=float(g("inst.eta", self.profile.eta) or 0.0),
            asymmetry=float(g("inst.asym", self.profile.asymmetry) or 0.0),
            # 钉住模式：否则 x/y 一旦从 0 变非 0，η 就从"用户值"跳成"TCH 导出值"
            use_tch=True,
        )
        for ph in self.phases:
            p = ph.prefix
            c0 = ph.structure.cell
            cell = Cell(
                a=float(g(f"{p}.cell.a", c0.a) or c0.a),
                b=float(g(f"{p}.cell.b", c0.b) or c0.b),
                c=float(g(f"{p}.cell.c", c0.c) or c0.c),
                alpha=float(g(f"{p}.cell.alpha", c0.alpha) or c0.alpha),
                beta=float(g(f"{p}.cell.beta", c0.beta) or c0.beta),
                gamma=float(g(f"{p}.cell.gamma", c0.gamma) or c0.gamma),
            )
            sites = self._sites_from_params(ph)
            ph.structure = replace(ph.structure, cell=cell, sites=tuple(sites))
            ph.size_nm = float(g(f"{p}.size", ph.size_nm) or 0.0)
            ph.strain = float(g(f"{p}.strain", ph.strain) or 0.0)
            ph.po_r = float(g(f"{p}.po.r", ph.po_r) or 1.0)
            ph.scale = float(g(f"{p}.scale", ph.scale) or 0.0)

    def _sites_from_params(self, ph: PhaseBlock) -> List[AtomSite]:
        """把 atom 自由度套回全胞位点（等价位点共享同一个自由度）。"""
        p = ph.prefix
        g = self.params.get
        if f"{p}.atom0.x" not in self.params:
            return list(ph.structure.sites)

        slots = self._atom_slots.get(ph.index)
        if slots is None:
            slots = self._build_atom_slots()[ph.index]
        out: List[AtomSite] = []
        for site, slot in zip(ph.structure.sites, slots):
            if slot is None:
                out.append(site)     # 无自由度的位点原样保留
                continue
            k = slot
            out.append(replace(
                site,
                x=float(g(f"{p}.atom{k}.x", site.x)),
                y=float(g(f"{p}.atom{k}.y", site.y)),
                z=float(g(f"{p}.atom{k}.z", site.z)),
                occupancy=float(g(f"{p}.atom{k}.occ", site.occupancy)),
                b_iso=float(g(f"{p}.atom{k}.biso", site.b_iso)),
            ))
        return out

    def _build_atom_slots(self) -> Dict[int, List[Optional[int]]]:
        """``{相下标: [每个全胞位点对应的独立位点编号]}``。"""
        slots: Dict[int, List[Optional[int]]] = {}
        for ph in self.phases:
            indep = self._independent_sites(ph)
            lookup: Dict[tuple, int] = {}
            for k, s in enumerate(indep):
                lookup[(s.element, round(s.x, 6), round(s.y, 6), round(s.z, 6),
                        round(s.occupancy, 6), round(s.b_iso, 6))] = k
            row: List[Optional[int]] = []
            for s in ph.structure.sites:
                row.append(lookup.get(
                    (s.element, round(s.x, 6), round(s.y, 6), round(s.z, 6),
                     round(s.occupancy, 6), round(s.b_iso, 6))))
            slots[ph.index] = row
        return slots

    # ── 设计矩阵（B3 二级缓存）────────────────────────────────
    def design(self) -> Tuple[np.ndarray, np.ndarray]:
        """返回 ``(相基 (N,n_phase), 背景基 (N,n_bg))``。"""
        key = self._make_design_key()
        if self._basis is not None and key == self._design_key:
            return self._basis, self._bg_basis

        tmin = float(self.two_theta[0]) if self.two_theta.size else 0.0
        tmax = float(self.two_theta[-1]) if self.two_theta.size else 0.0
        specs = []
        for ph in self.phases:
            ph.ensure_table((tmin, tmax), (self.wavelength,))
            specs.append(PhaseSpec(table=ph.table, size_nm=ph.size_nm,
                                   strain=ph.strain, po_r=ph.po_r))
        self._basis = design_matrix(
            self.two_theta, specs, self.profile,
            wavelength=self.wavelength, kalph2=self.kalph2,
            cutoff_fwhm=self.cutoff_fwhm, shift=self.shift, disp=self.disp)
        self._bg_basis = background_basis(self.two_theta, self.bg)
        self._design_key = key
        return self._basis, self._bg_basis

    def _make_design_key(self) -> tuple:
        cells = tuple(ph.cell_key() for ph in self.phases)
        prof = (self.profile.u, self.profile.v, self.profile.w, self.profile.x,
                self.profile.y, self.profile.z, self.profile.eta,
                self.profile.asymmetry)
        sample = tuple((ph.size_nm, ph.strain, ph.po_r) for ph in self.phases)
        return cells + prof + sample + (self.shift, self.disp)

    def invalidate(self) -> None:
        self._basis = None
        self._design_key = ()
        for ph in self.phases:
            ph.invalidate()

    # ── 残差与计算谱 ───────────────────────────────────────────
    def residual(self, x: Optional[Sequence[float]] = None,
                 stage: Optional[int] = None) -> np.ndarray:
        """变量投影后的**加权**残差 ``(y − y_calc)·√w``。"""
        if x is not None:
            self.params.assign(x, stage)
        self.apply()
        basis, bgb = self.design()
        lin = solve_linear(basis, self.y_obs, weights=self.weights,
                           bg_basis=bgb)
        self.last_linear = lin
        self._sync_linear(lin)
        return lin.resid

    def _sync_linear(self, lin: LinearSolve) -> None:
        """把线性层的解回写到 fixed 参数（供展示与 Hill–Howard 定量使用）。"""
        for i, ph in enumerate(self.phases):
            name = f"{ph.prefix}.scale"
            if name in self.params and i < lin.scales.size:
                self.params.set(name, float(lin.scales[i]))
                ph.scale = float(lin.scales[i])
        for k, c in enumerate(lin.bg_coefs):
            name = f"bg.c{k}"
            if name in self.params:
                self.params.set(name, float(c))

    def calc_pattern(self) -> np.ndarray:
        """当前参数下的计算谱（含背景）。

        **必须每次重解线性层**。``last_linear`` 可能来自上一个设计矩阵 ——
        改了晶胞 / 峰形 / 择优之后设计矩阵就变了，复用它等于把旧谱当新谱
        返回。实测踩过：改 ``inst.u`` 后计算谱一个点都不变，误判成"峰宽参数
        没接进模型"，白查半天。
        """
        basis, bgb = self.design()
        lin = solve_linear(basis, self.y_obs, weights=self.weights,
                           bg_basis=bgb)
        self.last_linear = lin
        self._sync_linear(lin)
        return lin.y_calc

    def metrics(self, *, count_linear: bool = True,
                stage: Optional[int] = None) -> Dict[str, float]:
        """当前解得吻合指标；``P`` 计入线性层自由度（标度 + 背景）。

        :param stage: 只统计``stage <= stage`` 的自由参数。**收敛后必须传**：
        ``build_parameters`` 会把结构自由度（stage 6）一并建册，若协议只跑到
        stage 5，这些参数一个都没被精修却会被算进 ``P`` —— ``Rexp`` 偏小、
        ``GOF`` 偏大，报告里出现"参数多、GOF 差"的错觉。

        线性层**每次重解**，不复用 ``last_linear``：它是上一次 ``residual`` 的
        快照，一旦外部改过非线性参数（手工改了 size、restore 了快照、换了
        峰宽）而没有重解，缓存里的 ``y_calc`` 就是旧的 —— 实测表现为"把 size
        从 0 拖到 500 nm，Rwp 一位小数都不变"，看代码又查不出所以然。
        重解是一次 ``lstsq``（列数 = 相数 + 背景阶数），代价可忽略。
        """
        basis, bgb = self.design()
        lin = solve_linear(basis, self.y_obs, weights=self.weights, bg_basis=bgb)
        self.last_linear = lin
        self._sync_linear(lin)
        n_lin = basis.shape[1] + (bgb.shape[1] if bgb is not None else 0)
        n_nonlin = self.params.free_indices(stage).size
        n_p = (n_lin if count_linear else 0) + n_nonlin
        return pattern_metrics(self.y_obs, lin.y_calc, self.weights, n_p)

    def quantitative(self, *, min_fraction: float = 0.0) -> QuantResult:
        """Hill–Howard 重量分数（用当前线性层解出的标度）。"""
        if self.last_linear is None:
            self.residual(None)
        scales = [float(v) for v in self.last_linear.scales]
        return hill_howard([ph.label for ph in self.phases], scales,
                           [ph.structure for ph in self.phases],
                           min_fraction=min_fraction)

    # ── 拟合 ───────────────────────────────────────────────────
    def fit(
        self,
        *,
        stages: Optional[Sequence[int]] = None,
        protocol=None,
        max_iter_per_stage: int = 100,
        method: str = "auto",
        callback=None,
    ) -> FitSummary:
        """按阶段依次放开参数，逐段精修。

        ``stages`` 的每一项是**该段放开到第几阶段**（``Parameter.stage <= n``）。
        给 ``None``（默认）走 ``protocol`` —— D1 交付的六段协议，带**逐段回滚**
        与**提前收敛**；也可以直接传名字 ``"quick"`` / ``"position"``。
        给显式列表则走"裸阶段"模式（无回滚、无提前停），供测试与脚本精确控制。

        顺序不是玄学：**峰位必须先于峰形**。晶胞未定时就放开 Caglioti，LM 会把
        "峰位算错了" 解释成 "峰太宽"，把 x/y 拉到物理荒唐值（实测 x=-0.45，
        而真值 0.004）后卡在假极小。这一点与 GSAS-II 的实际操作顺序一致。
        """
        if stages is None or protocol is not None:
            from .protocol import run_protocol

            return run_protocol(self, protocol=protocol, method=method,
                                callback=callback,
                                max_iter_per_stage=max_iter_per_stage)

        log: List[dict] = []
        last: Optional[FitResult] = None
        for st in stages:
            x0 = self.params.to_vector(st)
            if x0.size == 0:
                continue
            bounds = self.params.bounds(st)
            res = minimize_residual(
                lambda x, _st=st: self.residual(x, _st), x0,
                bounds=bounds, method=method, max_iter=max_iter_per_stage,
            )
            self.params.assign(res.x, st)
            self.apply()
            self.invalidate()
            self.residual(None)
            m = self.metrics(stage=st)
            log.append({"stage": st, "n_params": int(x0.size),
                        "Rwp": m["Rwp"], "GOF": m["GOF"],
                        "status": res.status, "nfev": res.nfev})
            last = res

        if last is None:
            # 没有自由参数：直接算一次残差
            r = self.residual(None)
            last = FitResult(x=np.zeros(0), cost=0.5 * float(r @ r), resid=r,
                             n_data=r.size, method="none")
        return finalize_summary(self, last, log, stages[-1] if stages else None)


def finalize_summary(
    problem: "PatternProblem",
    result: FitResult,
    log: List[dict],
    stage: Optional[int] = None,
) -> FitSummary:
    """收敛后的统一收尾：指标 + 病态诊断 + sigma 回写 + Hill–Howard 定量。

    抽成模块级函数是为了让"裸阶段"（``fit(stages=...)``）与"协议"
    （``protocol.run_protocol``）共用**同一份**收尾逻辑 —— 两处各写一遍必然
    会漂移，而 sigma 回写这种"长度恰好相等就静默覆盖"的坑最难查。
    """
    m = problem.metrics(stage=stage)
    idx = problem.params.free_indices(stage)
    names = [problem.params.names()[i] for i in idx]
    # 注意**不要**把 params.sigmas() 传进来：那里此时可能全是 0，会覆盖掉
    # diagnose 现场算出的 sigma（长度恰好相等，静默覆盖，查起来很痛）。
    diag = (diagnose(result.jac, names,
                     at_bounds=problem.params.at_bound(stage),
                     reduced_chi2=result.reduced_chi2)
            if result.jac is not None else None)
    if diag is not None:
        for i in idx:
            nm = problem.params.names()[i]
            if nm in diag.sigmas:
                problem.params[i].sigma = float(diag.sigmas[nm])
    return FitSummary(result=result, params=problem.params, metrics=m,
                      stages=log, linear=problem.last_linear,
                      y_calc=problem.calc_pattern(),
                      diagnostics=diag, quant=problem.quantitative())
