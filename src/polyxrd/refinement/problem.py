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
from .intensity import Roughness, apply_microabsorption, radius_per_phase
from .linear import LinearSolve, design_stack, solve_linear
from .optimize import FitResult, minimize_residual
from .parameters import Parameter, ParameterSet
from .pattern import DEFAULT_CUTOFF_FWHM, PhaseSpec, phase_pattern
from .profile import (Kalpha2, ProfileParams, size_coefficient,
                      size_from_coefficient)
from .quantitative import QuantResult, hill_howard
from .structure import AtomSite, Cell, ReflectionTable, StructureModel, build_reflections
from .symmetry import apply_cell_ties, orbit_decomposition

#: 弱相晶胞冻结阈值：初始反射表强度份额（Σ|F|²·多重度·LP / 全谱）低于它
#: 就认为"没有足够的独立强线支撑晶胞"，把该相 6 个晶胞参数固定到 CIF 值。
#: 2% 是本轮 GRANODIO 实测（Hornblende 0.23%、Zircon 0.51%）与正常相
#: （≥10%）之间的安全分界。
WEAK_PHASE_CELL_SHARE = 0.02

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
    #: Legendre（纤维对称）织构系数 (c2, c4, c6, c8)；空元组 = 不用该模型。
    #: 长度决定放开几个自由度，是"模型开关"而不是"结果"
    po_c: Tuple[float, ...] = ()
    b_overall: float = 0.0
    #: P0-B″ 各向异性展宽（P₂/P₄ 系数）+ 开关。``aniso_on=False`` 时参数仍进
    #: 参数册但固定为 0，PhaseSpec 收到 0 → 逐位保持旧行为（opt-in）。
    aniso_on: bool = False
    aniso_c2: float = 0.0
    aniso_c4: float = 0.0
    scale: float = 1.0
    table: Optional[ReflectionTable] = None
    _table_key: tuple = field(default=(), repr=False)
    #: 上一次 ``_sites_from_params`` 用过的原子参数指纹（P0 提速）：数值雅可比
    #: 每次只扰动一个参数，其余相的原子值不变 → 直接复用位点表，省掉重复的
    #: ``replace``/``einsum``（S2 实测 3.3 s / 55 s）。
    _site_key: tuple = field(default=(), repr=False)

    @property
    def prefix(self) -> str:
        return f"phase{self.index}"

    def cell_key(self) -> tuple:
        c = self.structure.cell
        return (round(c.a, 9), round(c.b, 9), round(c.c, 9),
                round(c.alpha, 9), round(c.beta, 9), round(c.gamma, 9),
                tuple(self.po_hkl) if self.po_hkl else None)

    def site_key(self) -> tuple:
        """位点指纹 —— **必须和晶胞一起进缓存键**。

        结构因子 ``|F|²`` 同时依赖晶胞与位点（坐标 / 占位 / ``Biso``），
        而 v5.0 的两级缓存只拿 ``cell_key()`` 当键。后果是结构自由度（stage 6）
        在 LM 内部**完全失效**：``apply()`` 把坐标写进 ``ph.structure`` 了，
        但反射表和设计矩阵都按旧键命中缓存，计算谱一位不动、雅可比列恒为零。
        实测（合成 LFP）：把 ``atom1.x`` 挪 0.05，2001 个点的残差变化 **0 个**；
        手工重建反射表后 ``|F|²`` 最大变化 1.17 —— 说明结构因子本身是接通的，
        纯粹被缓存挡住了。

        坐标按 1e-6 取整：低于这个量级的移动对结构因子没有数值意义，
        取整反而能让"浮点抖动"不把缓存反复冲掉。
        """
        return tuple((s.element, round(s.occupancy, 6), round(s.b_iso, 6),
                      round(s.x, 6), round(s.y, 6), round(s.z, 6))
                     for s in self.structure.sites)

    def structure_key(self) -> tuple:
        """``(晶胞, 位点)`` —— 反射表与设计矩阵真正该用的键。"""
        return self.cell_key() + (self.site_key(),)

    def ensure_table(
        self,
        two_theta_range: Tuple[float, float],
        wavelengths,
        *,
        noise_ratio: float = 1e-9,
        pad: float = 2.0,
    ) -> ReflectionTable:
        """按结构键（晶胞 + 位点）缓存反射表（B3 一级缓存）。"""
        key = self.structure_key() + (round(two_theta_range[0] - pad, 6),
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


@dataclass
class _AtomMap:
    """一相的位点自由度映射（Wyckoff 轨道归并的结果，见 ``symmetry``）。

    :param reps: 独立位点（轨道代表），编号即参数名里的 ``atom{k}``
    :param slot: 长度 = 全胞位点数；每个位点所属的独立位点编号
    :param rep_site: 长度 = 独立位点数；代表位点在全胞位点里的下标
    :param base_all: ``(M,3)`` 全胞位点的**初始**分数坐标（作锚点，保证幂等）
    :param mat_all: ``(M,3,3)`` 「参量位移 → 分数位移」，已含轨道操作的旋转
    :param base_rep: ``(K,3)`` 独立位点的初始分数坐标
    :param trivial: True = 没做轨道归并（无空间群），走逐位点快路径
    """

    reps: List[AtomSite]
    slot: List[int]
    rep_site: List[int]
    base_all: np.ndarray
    mat_all: np.ndarray
    base_rep: np.ndarray
    trivial: bool = True


class PatternProblem:
    """多相全谱拟合问题（变量投影）。

    :param two_theta: 观测网格（度，单调递增）
    :param y_obs: 观测强度
    :param phases: ``PhaseBlock`` 列表
    :param profile: 仪器峰形（样品层由各相 ``size_nm/strain`` 覆盖）
    :param bg: 背景基描述
    :param kalph2: Kα2 描述；None → 单色
    :param weights: 观测权重；None → ``1/max(y,1)``（Poisson）
    :param roughness_model: 表面粗糙度模型名（``none`` / ``sidey`` / ``suortti``
        / ``sparks``）；实际幅度由参数 ``inst.rough`` 给出
    :param mu_linear: 各相线吸收系数（1/cm，与 ``phases`` 同序）。给齐且
        ``grain_radius_um`` 有正值时定量会做 Brindley 微吸收修正
    :param grain_radius_um: 微吸收用的颗粒半径（µm）。**标量（全相共用）或
        逐相序列**均可；序列长度必须与相数一致（不符直接 ``ValueError``，
        fail fast 优于静默错位）。逐相半径是物理必需：混合样各相粒度可以
        差一个量级（IUCr CPD：刚玉 28 µm vs 锌矿 1.4 µm），τ 的自变量是
        ``(μ_j − μ̄)·R_j``，拿一个 R 套所有相方向都可能反
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
        roughness_model: str = "none",
        mu_linear: Optional[Sequence[float]] = None,
        grain_radius_um: "float | Sequence[float]" = 0.0,
        tail_on: bool = False,
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
        #: P0-C 低角拖尾开关（opt-in；关闭时 inst.tail 固定为 0，逐位不变）
        self.tail_on = bool(tail_on)

        if weights is None:
            self.weights = 1.0 / np.maximum(self.y_obs, 1.0)
        else:
            w = np.asarray(weights, dtype=float)
            if w.size != self.y_obs.size:
                raise ValueError("weights 长度与观测不符")
            self.weights = w

        self.shift = 0.0
        self.disp = 0.0
        # 表面粗糙度（整样品）：由 ``inst.rough`` + 模型名决定，关闭时零开销
        self.rough_model = str(roughness_model or "none")
        self.roughness = Roughness(model=self.rough_model)
        # 微吸收（Brindley）：逐相 μ（1/cm）+ 颗粒半径（µm），只进定量不进拟合。
        # 半径两种形态：标量 → grain_radius_um（历史口径）；序列 → grain_radii_um
        # （P0-G 逐相）。全相同值的序列折回标量，保证与历史行为逐位一致。
        self.mu_linear: Tuple[float, ...] = tuple(float(v) for v in (mu_linear or ()))
        if isinstance(grain_radius_um, (list, tuple, np.ndarray)):
            rad = radius_per_phase(grain_radius_um, len(self.phases))
            if len(set(rad.tolist())) == 1:
                self.grain_radius_um = float(rad[0])
                self.grain_radii_um: Tuple[float, ...] = ()
            else:
                self.grain_radius_um = 0.0
                self.grain_radii_um = tuple(float(v) for v in rad)
        else:
            self.grain_radius_um = float(grain_radius_um or 0.0)
            self.grain_radii_um = ()
        self._atom_map: Dict[int, _AtomMap] = {}
        self.params = params if params is not None else self.build_parameters()
        if not self._atom_map:
            self._atom_map = self._build_atom_maps()

        self._basis: Optional[np.ndarray] = None
        self._bg_basis: Optional[np.ndarray] = None
        self._design_key: tuple = ()
        # 按列缓存：全局量（峰形/位移/粗糙度/Kα2/网格）不变时，扰动相 i
        # 只重建第 i 列。数值雅可比逐参数扰动，5 相问题的晶胞/PO 段参数
        # 都是单相归属 —— 全量重建会把 4 列白白重算（2026-11-06 实测 5-3
        # 的 _numeric_jacobian 占 91% 时间）。
        self._global_key: tuple = ()
        self._col_keys: List[tuple] = []
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
            # 整体温度因子 B（逐相）：**放 stage 3 而不是 5**。它与宽度参数
            # 不同域（强度 vs 峰宽），不共线；放 stage 5 会让 fast 档（只有
            # 2、3 两个阶段）永远碰不到它 —— 而真实试样的 0.7 pp 收益正是
            # 在默认档上量的（基准报告 §十二 实验 5）。
            "bovr": 3,
        }
        if stages:
            st.update(stages)

        # 轨道分解要在建位点自由度之前算好（它决定放几组、哪几轴能放）
        maps = self._build_atom_maps()

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
        # P0-C：低角拖尾面积占比（0~0.4）。与 split-PV 不共线（一个是宽度、
        # 一个是"主峰之外多出的一块面积"），但两者都吃低角残差，一起放开
        # 可能互相抵消 —— 因此 opt-in，且与 asym 同阶段。
        ps.add(Parameter("inst.tail", float(self.profile.tail), 0.0, 0.4,
                         stage=st["asym"], fixed=not self.tail_on,
                         label="低角拖尾占比"))
        # 表面粗糙度（Sidey 单参数）：S_R = (θ/90)^(s/θ)，θ 用度。
        # 与"择优取向"的分野：PO 逐相、依赖 hkl；SR 整样品、只依赖 2θ。
        # 界 0~2：s=0.5 已能把 2θ=10° 压掉 ~26%（实测粗粉量级），2.0 是
        # "表面全是坑"的极限，再大就不是 SR 而是别的系统性误差了。
        # 只允许非负 —— 负 s 会**放大**低角强度，物理上对应"表面比体相更平整"，
        # 不存在这种机制（那是择优取向/装样密实的领域）。
        if self.rough_model and self.rough_model.strip().lower() not in (
                "", "none", "off", "0"):
            # **放 stage 3（profile）而不是 4（po）**：``fast`` 档只有 2、3 两个
            # 阶段（``V5_TIERS["fast"]["protocol"]``），挂到 4 就等于"默认档永远
            # 碰不到它"，s 会停在播种值上白降 Rwp —— 与 ``bovr`` 同一个坑（见上）。
            # 物理上也更贴 profile 段：u/v/w 改峰宽、SR 改峰高（2θ 的包络），
            # 两者不共线；DBWS 的经典做法也是把 SR 与 profile 一起放开。
            ps.add(Parameter("inst.rough", 0.0, 0.0, 2.0, stage=st["profile"],
                             label="表面粗糙度 s"))
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

        # 弱相晶胞冻结（2026-11-08，GRANODIO 暴露）：按**初始反射表**的
        # Σ|F|²·多重度·LP 份额判断"这一相有没有足够强的独立线支撑晶胞"。
        # < WEAK_PHASE_CELL_SHARE 的相（例：GRANODIO 的 Hornblende 0.23%、
        # Zircon 0.51%）晶胞参数直接**固定**在 CIF 值上，不进入拟合向量 ——
        # 否则它们会被噪声推动（曾出现 b=2.37 Å / c=33.8 Å 的非物理解）。
        # 注意：份额用初始表（与最终 wt 无关），因此判据在参数构建时就可算出，
        # 不需要二次精修；真正含量高的相不受影响。
        _int_shares: dict = {}
        try:
            _tot = sum(float(np.sum(np.asarray(b.table.intensity, float)))
                       for b in self.phases if b.table is not None)
            for b in self.phases:
                _s = (float(np.sum(np.asarray(b.table.intensity, float)))
                      if b.table is not None else 0.0)
                _int_shares[b.index] = (_s / _tot if _tot > 0.0 else 1.0)
        except Exception:  # noqa: BLE001 - 算不出就不冻结（行为不劣化）
            _int_shares = {}

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
            # 晶胞边界：起点来自 CIF，正常情况下精修移动 <1%；给边长 ±20%
            # 的宽松护栏即可。没有界时**弱相晶胞会跑飞**：GRANODIO 七相里
            # Hornblende(0.23%) 被推到 b=2.37 Å / beta=131°、Zircon(0.51%) 推到
            # c=33.8 Å —— 都是非物理解，且会污染同组其它相（2026-11-07 实测）。
            def _cell_bounds(v: float, is_angle: bool) -> tuple:
                v = float(v)
                if is_angle:
                    # 角度**不收紧**：空间群约束/笛卡尔 tie 会把 γ=90°（脏 CIF）
                    # 拉到 120°，收紧的界会把 tie 结果夹回去（对称性单测已抓到这个
                    # 反例）。角度的非物理漂移留给"弱相冻结"专项处理。
                    return (1e-3, 180.0 - 1e-3)
                return (max(1e-3, 0.8 * v), 1.2 * v)

            for tag, val in (
                ("a", c.a), ("b", c.b), ("c", c.c),
                ("alpha", c.alpha), ("beta", c.beta), ("gamma", c.gamma),
            ):
                lo, hi = _cell_bounds(val, tag in ("alpha", "beta", "gamma"))
                _weak_cell = _int_shares.get(ph.index, 1.0) < WEAK_PHASE_CELL_SHARE
                ps.add(Parameter(f"{p}.cell.{tag}", float(val), lo, hi,
                                 stage=st["cell"], fixed=_weak_cell,
                                 label=f"{ph.label} {tag}"))
            # 样品展宽：**尺寸用洛伦兹系数参数化，不用 D(nm)**。
            # β_size = Kλ/(D cosθ) 与 inst.y 是同一个函数形状，而且 dβ/dD ∝ 1/D²
            # 在 D→∞ 处彻底平坦：2-2 的 phase1.size 跑到 99988 nm，数值差分列
            # 在浮点上归零 → 秩 15/16、SVD0=5e-15（基准报告 §十七）。
            # 改用 coef（度·cosθ）后，"无展宽"= coef 0 是正常点，列恒为 1/cosθ。
            # 上界 4.0 度 ≈ D 2 nm，低到不能再低；`PhaseBlock.size_nm` 仍是物理量，
            # 由 `apply()` 从系数反算（供报告/定量读取）。
            _coef = size_coefficient(ph.size_nm, self.wavelength, self.profile.k_size)
            ps.add(Parameter(f"{p}.sizec", _coef, 0.0, 4.0,
                             stage=st["sample"],
                             label=f"{ph.label} 晶粒展宽 1/cosθ (度)"))
            ps.add(Parameter(f"{p}.strain", float(ph.strain), 0.0, 0.2,
                             stage=st["sample"], label=f"{ph.label} 应变 ε"))
            # P0-B″：各向异性展宽 P₂/P₄（cosφ = 法向与 c* 轴的夹角）。
            # 界 ±0.8：P₂(1)=1、P₂(0)=−1/2 ⇒ 因子落在 [0.2, 1.8]（裁剪 0.2~5），
            # 足以覆盖 MAUD 那种 hk0 2× 展宽，又不会把峰宽翻到背景量级。
            # opt-in：未开启时固定为 0，不占自由度、数值逐位不变。
            ps.add(Parameter(f"{p}.aniso.c2", float(ph.aniso_c2), -0.8, 0.8,
                             stage=st["sample"], fixed=not ph.aniso_on,
                             label=f"{ph.label} 各向异性 P2"))
            ps.add(Parameter(f"{p}.aniso.c4", float(ph.aniso_c4), -0.8, 0.8,
                             stage=st["sample"], fixed=not ph.aniso_on,
                             label=f"{ph.label} 各向异性 P4"))
            # 择优取向：**没给惯习面就不放这个自由度**。``po_hkl is None`` 时
            # March–Dollase 权重恒为 1（``build_reflections`` 不写 cosα），
            # 这一列雅可比全零 —— 放出来白占一个自由度、还让 rank 检查报亏。
            # 用户后来补 po_hkl 时需重建参数书（UI 侧本来就重建）。
            # r 的界取 0.2…5.0（v5.1）：March–Dollase 的物理区间，超出这个
            # 范围基本不是"择优"而是模型在吸收别的误差（假择优会把 r 推到
            # 边界并让 stage 4 反复试探，5-3 实测单次精修从 30 s 涨到 20 min）。
            # Legendre 织构启用时 MD 的 r 必须钉住：``P = W_MD(r)·P_leg``
            # 两者作用在同一个 cosα 上，一起放开会互相抵消（秩亏 + 定量漂移）。
            ps.add(Parameter(f"{p}.po.r", float(ph.po_r), 0.2, 5.0,
                             stage=st["po"],
                             fixed=ph.po_hkl is None or bool(ph.po_c),
                             label=f"{ph.label} 择优 r"))
            # Legendre（纤维对称）织构级数：``po_c`` 的长度就是自由度个数
            # —— 空元组 = 只用 March–Dollase（旧行为，逐位不变）。系数上限
            # ±1.5 是"别让级数在 cosα 上振出第二个假峰"的护栏（S3 的萤石
            # 只有 18 条反射，MAUD 的 6 阶 Harmonic 在那里给了 −5.8 的系数）。
            for _k, _v in enumerate(ph.po_c):
                _l = 2 * (_k + 1)
                ps.add(Parameter(f"{p}.po.c{_l}", float(_v), -1.5, 1.5,
                                 stage=st["po"], fixed=ph.po_hkl is None,
                                 label=f"{ph.label} 织构 c{_l}"))
            # 整体温度因子 B（每相）：|F|²·exp(−2B s²)，只依赖各反射自身 d，
            # 因此不需要重算结构因子。与原子级 biso（stage 6）的区别是它把
            # 所有位点一起压 —— 缺它会系统性高估高角强度（builtin W22-a 同口径，
            # 默认 0 = 无修正，上界 15 Å² 防跑飞）。
            ps.add(Parameter(f"{p}.bovr", float(ph.b_overall), 0.0, 15.0,
                             stage=st["bovr"], label=f"{ph.label} 整体 B (Å²)"))

            if with_atoms:
                # 只对**独立位点**放坐标自由度。``StructureModel`` 存的是已展开的
                # P1 全胞：同一 Wyckoff 轨道上的原子是同一个自由度，逐原子放开
                # 必然共线（刚玉 30 位点 → 90 个坐标列，秩只有 2）。
                # 轨道归并由 ``symmetry.orbit_decomposition`` 做；代表点落在特殊
                # 位置上时，方向也被限制在稳定子不变子空间里 —— 用不了的轴直接
                # 钉死（``fixed=True``），免得往拟合里塞恒零列。
                amap = maps.get(ph.index)
                reps = amap.reps if amap else self._independent_sites(ph)
                for k, site in enumerate(reps):
                    mat = self._rep_matrix(amap, k)
                    for a, (tag, val) in enumerate(
                            (("x", site.x), ("y", site.y), ("z", site.z))):
                        locked = mat is not None and float(np.abs(mat[:, a]).max()) < 1e-12
                        ps.add(Parameter(
                            f"{p}.atom{k}.{tag}", float(val), -1.0, 2.0,
                            fixed=locked, stage=st["atom"],
                            label=(f"{ph.label} {site.label or k} {tag}"
                                   + ("（特殊位置锁定）" if locked else ""))))
                    ps.add(Parameter(
                        f"{p}.atom{k}.occ", float(site.occupancy), 0.0, 1.0,
                        fixed=float(site.occupancy) >= 1.0 - 1e-9,
                        stage=st["atom"],
                        label=(f"{ph.label} {site.label or k} 占位"
                               + ("（满占位，与标度退化）"
                                  if float(site.occupancy) >= 1.0 - 1e-9 else ""))))
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
        self._atom_map = maps
        return ps

    @staticmethod
    def _rep_matrix(amap: Optional["_AtomMap"], k: int) -> Optional[np.ndarray]:
        """独立位点 ``k`` 的位移矩阵（轨道成员共享，未归并时返回 ``None``）。"""
        if amap is None or amap.trivial or k >= len(amap.rep_site):
            return None
        return amap.mat_all[amap.rep_site[k]]

    @staticmethod
    def _independent_sites(ph: PhaseBlock) -> List[AtomSite]:
        """按 (元素, 坐标, 占位, B) 去重 —— 只去掉**真的完全相同**的位点。

        兼容入口：真正的轨道归并在 :meth:`_build_atom_maps`（见
        ``symmetry.orbit_decomposition``）。本函数只做精确去重，供不需要
        空间群的调用方使用。
        """
        seen: Dict[tuple, AtomSite] = {}
        for s in ph.structure.sites:
            key = (s.element, round(s.x, 6), round(s.y, 6), round(s.z, 6),
                   round(s.occupancy, 6), round(s.b_iso, 6))
            if key not in seen:
                seen[key] = s
        return list(seen.values())

    # ── 位点自由度（Wyckoff 轨道）────────────────────────────────
    def _build_atom_maps(self) -> Dict[int, "_AtomMap"]:
        """每相一次的轨道分解：全胞位点 → 独立位点 + 位移矩阵。

        只在建参数书之前算一次（``ph.structure`` 还是 CIF 原样），之后每次
        ``apply()`` 都拿冻结的 ``base`` 做锚点，因此对**多次**反复写回是幂等的。

        没有空间群（P1 / 符号认不出）时退化成"一位点一自由量"，
        ``_AtomMap.trivial=True``，走与 v5.0 完全一样的快路径。
        """
        maps: Dict[int, _AtomMap] = {}
        for ph in self.phases:
            sites = list(ph.structure.sites)
            if not sites:
                maps[ph.index] = _AtomMap(
                    reps=[], slot=[], rep_site=[], base_all=np.zeros((0, 3)),
                    mat_all=np.zeros((0, 3, 3)), base_rep=np.zeros((0, 3)))
                continue
            ops = None
            try:
                from polyxrd.services.phase_cif import space_group_ops

                ops = space_group_ops(
                    getattr(ph.structure, "space_group", "") or "")
            except Exception:  # noqa: BLE001 - 认不出空间群 → 逐位点放开
                ops = None
            dec = orbit_decomposition(
                ops,
                [[s.x, s.y, s.z] for s in sites],
                [s.element for s in sites],
                [s.occupancy for s in sites],
            )
            base_all = np.array([[s.x, s.y, s.z] for s in sites], dtype=float)
            # 每个全胞位点自己的"参量位移 → 分数位移"：轨道成员的变换 = R_op · M
            mat_all = np.zeros((len(sites), 3, 3), dtype=float)
            for i, oi in enumerate(dec.op_of):
                m = dec.mats[dec.rep_of[i]]
                if oi is None or ops is None:
                    mat_all[i] = m
                else:
                    mat_all[i] = np.asarray(ops[oi].rotation_matrix,
                                            dtype=float) @ m
            reps = [sites[i] for i in dec.rep_site]
            base_rep = np.array([[s.x, s.y, s.z] for s in reps], dtype=float) \
                if reps else np.zeros((0, 3))
            maps[ph.index] = _AtomMap(
                reps=reps, slot=list(dec.rep_of), rep_site=list(dec.rep_site),
                base_all=base_all, mat_all=mat_all, base_rep=base_rep,
                trivial=dec.trivial)
        return maps

    # ── 参数 → 状态 ────────────────────────────────────────────
    def apply(self) -> None:
        """把 ``self.params`` 的当前值写进内部状态（profile / 晶胞 / 位点）。"""
        # 先重算跟随约束（六方 b=a 等）：调用方可能绕过 assign 直接 set。
        self.params.refresh_constraints()
        g = self.params.get
        self.shift = float(g("inst.zero", 0.0) or 0.0)
        self.disp = float(g("inst.disp", 0.0) or 0.0)
        # 粗糙度参数不存在（模型关闭）时 get 回退 0 —— Roughness 随即判 off
        self.roughness = Roughness(model=self.rough_model,
                                   s=float(g("inst.rough", 0.0) or 0.0))
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
            tail=float(g("inst.tail", self.profile.tail) or 0.0),
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
            ph.size_nm = size_from_coefficient(
                g(f"{p}.sizec", 0.0) or 0.0, self.wavelength, self.profile.k_size)
            ph.strain = float(g(f"{p}.strain", ph.strain) or 0.0)
            ph.po_r = float(g(f"{p}.po.r", ph.po_r) or 1.0)
            if ph.po_c:
                ph.po_c = tuple(float(g(f"{p}.po.c{2 * (k + 1)}", v) or 0.0)
                                for k, v in enumerate(ph.po_c))
            ph.b_overall = float(g(f"{p}.bovr", ph.b_overall) or 0.0)
            ph.aniso_c2 = float(g(f"{p}.aniso.c2", ph.aniso_c2) or 0.0)
            ph.aniso_c4 = float(g(f"{p}.aniso.c4", ph.aniso_c4) or 0.0)
            ph.scale = float(g(f"{p}.scale", ph.scale) or 0.0)

    def freeze_instrument_lorentz(self) -> List[str]:
        """钉住 ``inst.x`` / ``inst.y``，让样品展宽独占 ``tanθ`` / ``1/cosθ``。

        洛伦兹分量是逐字相加的::

            ell = X·tanθ + Y/cosθ + Z + Kλ/(D·cosθ) + 4ε·tanθ

        ``X`` 与 ``4ε``、``Y`` 与 ``Kλ/D`` 是**完全相同的基函数** —— 一起放开
        时方程里只有它们的和可辨识（v5.1 之前一直靠"大多数时候两者都停在 0"
        侥幸避开）。惯例取"仪器洛伦兹由标样标定、样品展宽归样品"：stage 5
        启用时把 X/Y 钉在种子值（默认 0），D/ε 才有唯一解。

        注意这**不是**精度取舍：X/Y 被钉住后 D 会吸收仪器那部分 1/cosθ 展宽，
        报出的尺寸是文献里的"表观晶粒尺寸"，这正是 Rietveld 的标准口径。

        :return: 实际被钉住的参数名（参数册里没有的不算）。
        """
        frozen: List[str] = []
        for name in ("inst.x", "inst.y"):
            if name in self.params:
                self.params[name].fixed = True
                frozen.append(name)
        return frozen

    def _sites_from_params(self, ph: PhaseBlock) -> List[AtomSite]:
        """把 atom 自由度套回全胞位点（同一 Wyckoff 轨道共享一组自由度）。

        两条路径：

        * **未归并**（无空间群，``trivial``）：一位点一自由量，坐标直接取参数
          —— 与 v5.0 完全一致，包括"参数以外的东西原样保留"的语义。
        * **已归并**：代表位点的位移先经稳定子投影（``mat_all``），再按各自的
          轨道操作旋转到成员位点上。位移以**初始**坐标 ``base_all`` 为锚点，
          所以反复调用是幂等的，不会因为上一轮的写回而漂移。
        """
        p = ph.prefix
        g = self.params.get
        if f"{p}.atom0.x" not in self.params:
            return list(ph.structure.sites)

        # 指纹命中 → 这一相的原子参数没变（雅可比扰动的是别的参数/别的相），
        # 直接复用现有位点表。注意：晶胞变了不影响分数坐标，所以仍可命中。
        ckey = tuple(round(float(self.params.get(n, 0.0) or 0.0), 10)
                     for n in self.params.names() if n.startswith(p + ".atom"))
        if ckey and ckey == ph._site_key:
            return list(ph.structure.sites)

        amap = self._atom_map.get(ph.index)
        if amap is None:
            amap = self._build_atom_maps()[ph.index]
        sites = list(ph.structure.sites)
        if not sites or not amap.slot:
            return sites

        if amap.trivial:
            out: List[AtomSite] = []
            for site, k in zip(sites, amap.slot):
                out.append(replace(
                    site,
                    x=float(g(f"{p}.atom{k}.x", site.x)),
                    y=float(g(f"{p}.atom{k}.y", site.y)),
                    z=float(g(f"{p}.atom{k}.z", site.z)),
                    occupancy=float(g(f"{p}.atom{k}.occ", site.occupancy)),
                    b_iso=float(g(f"{p}.atom{k}.biso", site.b_iso)),
                ))
            ph._site_key = ckey
            return out

        k_rep = len(amap.reps)
        par = np.empty((k_rep, 3), dtype=float)
        occ = np.empty(k_rep, dtype=float)
        bis = np.empty(k_rep, dtype=float)
        for k in range(k_rep):
            site = amap.reps[k]
            par[k, 0] = float(g(f"{p}.atom{k}.x", site.x))
            par[k, 1] = float(g(f"{p}.atom{k}.y", site.y))
            par[k, 2] = float(g(f"{p}.atom{k}.z", site.z))
            occ[k] = float(g(f"{p}.atom{k}.occ", site.occupancy))
            bis[k] = float(g(f"{p}.atom{k}.biso", site.b_iso))

        slot = np.asarray(amap.slot, dtype=int)
        delta = par - amap.base_rep                       # (K,3) 参量相对起点
        xyz = amap.base_all + np.einsum(
            "sij,sj->si", amap.mat_all, delta[slot])      # (M,3) 分数坐标
        # 越界才回绕：落在 [0,1) 里的坐标保持**逐位不变**，不给结构加浮点噪声
        over = (xyz < 0.0) | (xyz >= 1.0)
        if bool(over.any()):
            xyz = np.where(over, xyz - np.floor(xyz), xyz)
        ph._site_key = ckey
        return [replace(site, x=float(xyz[i, 0]), y=float(xyz[i, 1]),
                        z=float(xyz[i, 2]),
                        occupancy=float(occ[slot[i]]), b_iso=float(bis[slot[i]]))
                for i, site in enumerate(sites)]

    # ── 设计矩阵（B3 二级缓存）────────────────────────────────
    def _global_design_key(self) -> tuple:
        """影响**所有列**的量。变了 → 全部列重算；不变 → 只重算变了的相。"""
        prof = (self.profile.u, self.profile.v, self.profile.w, self.profile.x,
                self.profile.y, self.profile.z, self.profile.eta,
                self.profile.asymmetry, self.profile.tail)
        ka = self.kalph2
        ka_key = ((ka.wavelength, ka.ratio, ka.separation)
                  if ka is not None else None)
        tt = self.two_theta
        return prof + (self.shift, self.disp, self.roughness.key(),
                       ka_key,
                       self.wavelength, self.cutoff_fwhm,
                       (int(tt.size),
                        float(tt[0]) if tt.size else 0.0,
                        float(tt[-1]) if tt.size else 0.0))

    def _col_key(self, ph) -> tuple:
        """单列的完整输入：结构键 + 样品层标量。"""
        return ph.structure_key() + (ph.size_nm, ph.strain, ph.po_r,
                                     tuple(round(float(c), 10) for c in ph.po_c),
                                     ph.b_overall, ph.aniso_c2, ph.aniso_c4)

    def design(self) -> Tuple[np.ndarray, np.ndarray]:
        """返回 ``(相基 (N,n_phase), 背景基 (N,n_bg))``。

        缓存分两层：

        * **全局层**：``_global_design_key()`` 不变时列缓存有效；变了全部重算。
        * **按列层**：每列按 ``_col_key()`` 缓存。数值雅可比逐参数扰动 ——
          晶胞 / PO / 尺寸应变 / 位点参数都只属于一个相，扰动它时其余
          n−1 列逐位不变，重算是纯浪费。

        每列走的是与 ``design_matrix`` 完全相同的 ``phase_pattern`` 路径，
        数值逐位一致。
        """
        gkey = self._global_design_key()
        n_ph = len(self.phases)
        full_miss = (self._basis is None
                     or len(self._col_keys) != n_ph
                     or gkey != self._global_key)

        tmin = float(self.two_theta[0]) if self.two_theta.size else 0.0
        tmax = float(self.two_theta[-1]) if self.two_theta.size else 0.0

        if full_miss:
            self._basis = np.zeros((self.two_theta.size, n_ph), dtype=float)
            self._col_keys = [()] * n_ph
            self._global_key = gkey

        for i, ph in enumerate(self.phases):
            ckey = self._col_key(ph)
            if not full_miss and ckey == self._col_keys[i]:
                continue
            ph.ensure_table((tmin, tmax), (self.wavelength,))
            spec = PhaseSpec(table=ph.table, size_nm=ph.size_nm,
                             strain=ph.strain, po_r=ph.po_r, po_c=ph.po_c,
                             b_overall=ph.b_overall,
                             aniso_c2=ph.aniso_c2, aniso_c4=ph.aniso_c4)
            self._basis[:, i] = phase_pattern(
                self.two_theta, spec, self.profile,
                wavelength=self.wavelength, kalph2=self.kalph2,
                cutoff_fwhm=self.cutoff_fwhm, shift=self.shift,
                disp=self.disp, rough=self.roughness)
            self._col_keys[i] = ckey

        if full_miss:
            # 背景基只在全局层失配时重建（取决于背景阶数与网格，极廉价）；
            # 纯列命中时直接复用 —— 与旧的全键命中口径一致。
            self._bg_basis = background_basis(self.two_theta, self.bg)
        return self._basis, self._bg_basis

    def _make_design_key(self) -> tuple:
        cells = tuple(ph.structure_key() for ph in self.phases)
        prof = (self.profile.u, self.profile.v, self.profile.w, self.profile.x,
                self.profile.y, self.profile.z, self.profile.eta,
                self.profile.asymmetry, self.profile.tail)
        sample = tuple((ph.size_nm, ph.strain, ph.po_r,
                        tuple(round(float(c), 10) for c in ph.po_c),
                        ph.b_overall, ph.aniso_c2, ph.aniso_c4)
                       for ph in self.phases)
        return cells + prof + sample + (self.shift, self.disp,
                                       self.roughness.key())

    def invalidate(self) -> None:
        self._basis = None
        self._design_key = ()
        self._global_key = ()
        self._col_keys = []
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
                           bg_basis=bgb, diagnose=False)
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
                           bg_basis=bgb, diagnose=False)
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
        """Hill–Howard 重量分数（用当前线性层解出的标度）。

        给了 ``mu_linear`` 且颗粒半径有正值时，额外施加 Brindley
        微吸收修正（``W ∝ S·f/τ``）。**这一步不改变 Rwp** —— τ 作用在强度上
        时会被标度吸收；它只在把标度翻译成重量分数时起作用（详见
        ``refinement/intensity.py`` 模块讨论）。半径可以是逐相序列
        （``grain_radii_um``，P0-G），全相同值时退化为标量口径。
        """
        if self.last_linear is None:
            self.residual(None)
        scales = [float(v) for v in self.last_linear.scales]
        mu = self.mu_linear if len(self.mu_linear) == len(self.phases) else None
        radius = self.grain_radii_um or self.grain_radius_um
        return hill_howard([ph.label for ph in self.phases], scales,
                           [ph.structure for ph in self.phases],
                           min_fraction=min_fraction,
                           mu=mu, radius_um=radius)

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
