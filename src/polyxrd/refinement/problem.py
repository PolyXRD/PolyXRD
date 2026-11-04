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
from .profile import (Kalpha2, ProfileParams, size_coefficient,
                      size_from_coefficient)
from .quantitative import QuantResult, hill_howard
from .structure import AtomSite, Cell, ReflectionTable, StructureModel, build_reflections
from .symmetry import apply_cell_ties, orbit_decomposition

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
    b_overall: float = 0.0
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
        self._atom_map: Dict[int, _AtomMap] = {}
        self.params = params if params is not None else self.build_parameters()
        if not self._atom_map:
            self._atom_map = self._build_atom_maps()

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
            # 择优取向：**没给惯习面就不放这个自由度**。``po_hkl is None`` 时
            # March–Dollase 权重恒为 1（``build_reflections`` 不写 cosα），
            # 这一列雅可比全零 —— 放出来白占一个自由度、还让 rank 检查报亏。
            # 用户后来补 po_hkl 时需重建参数书（UI 侧本来就重建）。
            # r 的界取 0.2…5.0（v5.1）：March–Dollase 的物理区间，超出这个
            # 范围基本不是"择优"而是模型在吸收别的误差（假择优会把 r 推到
            # 边界并让 stage 4 反复试探，5-3 实测单次精修从 30 s 涨到 20 min）。
            ps.add(Parameter(f"{p}.po.r", float(ph.po_r), 0.2, 5.0,
                             stage=st["po"], fixed=ph.po_hkl is None,
                             label=f"{ph.label} 择优 r"))
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
            ph.size_nm = size_from_coefficient(
                g(f"{p}.sizec", 0.0) or 0.0, self.wavelength, self.profile.k_size)
            ph.strain = float(g(f"{p}.strain", ph.strain) or 0.0)
            ph.po_r = float(g(f"{p}.po.r", ph.po_r) or 1.0)
            ph.b_overall = float(g(f"{p}.bovr", ph.b_overall) or 0.0)
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
        return [replace(site, x=float(xyz[i, 0]), y=float(xyz[i, 1]),
                        z=float(xyz[i, 2]),
                        occupancy=float(occ[slot[i]]), b_iso=float(bis[slot[i]]))
                for i, site in enumerate(sites)]

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
                                   strain=ph.strain, po_r=ph.po_r,
                                   b_overall=ph.b_overall))
        self._basis = design_matrix(
            self.two_theta, specs, self.profile,
            wavelength=self.wavelength, kalph2=self.kalph2,
            cutoff_fwhm=self.cutoff_fwhm, shift=self.shift, disp=self.disp)
        self._bg_basis = background_basis(self.two_theta, self.bg)
        self._design_key = key
        return self._basis, self._bg_basis

    def _make_design_key(self) -> tuple:
        cells = tuple(ph.structure_key() for ph in self.phases)
        prof = (self.profile.u, self.profile.v, self.profile.w, self.profile.x,
                self.profile.y, self.profile.z, self.profile.eta,
                self.profile.asymmetry)
        sample = tuple((ph.size_nm, ph.strain, ph.po_r, ph.b_overall)
                       for ph in self.phases)
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
