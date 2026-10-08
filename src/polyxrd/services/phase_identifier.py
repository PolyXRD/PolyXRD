"""
物相识别服务
============
基于匹配因子 (FoM, 0.9.11 加权互斥版) 的物相识别。
支持离线XRD参考数据库匹配和COD在线搜索。
支持四态元素过滤: 必有/含有/可能/没有 (未勾选元素默认并入「没有」)。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

# S03: 组合目标的质量项权重。目标 = 覆盖 − λ·ΣFoM;
# λ = _COMBO_FOM_WEIGHT × 平均观测权重 (强度归一后 mean(w) ∈ (0,1]),
# 量纲上使 FoM 合计只可能在覆盖差 <~5% 时翻盘 (保留覆盖优先)。
# S14 网格标定 (0.05→1.0 × 6 档): 相级命中对 λ 完全不敏感
# (覆盖项主导, FoM 项在 13 试样上从未翻盘) → 维持 0.05 不变。
_COMBO_FOM_WEIGHT = 0.05

# v2.5 E1: 按 FoM 质量缩放各相 cover_vector, 让少峰但 FoM 优的相
#   在联合覆盖中不被多峰相稀释。factor = 1 + boost*(1 - norm_fom),
#   norm_fom 为池内 FoM 分数 min-max 归一 (0=最优, 1=最差)。
#   boost=0 退回原行为 (纯覆盖主导)。
#   v2.5 消融: 关 E1 后组合 44/49 与 10/13 完全不变 → 确为中性基础设施。
_COMBO_FOM_COVER_BOOST = 0.5

# v2.5 E2: 池保底回收阈值。matched_peaks >= 此值的候选即使 FoM 排名在
#   pool_top_n 之外也强制进入 B&B 池。2 = 与 B-1 最小关联峰口径一致。
#   v2.5 消融: 关 E2 后组合 44/49 与 10/13 完全不变 → 确为中性基础设施。
_COMBO_KEEP_MATCHED = 2

# v2.5 E3: B&B 目标中匹配峰数奖励权重。每多匹配 1 个实测峰给此权重的奖励,
#   让弱线相 (self-recall 低但 matched_peaks 高) 能与强线覆盖毯相竞争。
#   0 = 关闭 (退回纯覆盖+FoM)。
_COMBO_MATCHED_WEIGHT = 0.0

# S14: 覆盖尺度一致性锐化指数。c = (min/max)^p; p=1 为线性 min/max,
# p=2 对"弱线配强峰"的失配惩罚更狠 (400+ 线密集相在强度维也稠密,
# 线性 ratio 压不塌其覆盖毯)。
# S14 网格标定 (13 试样, held-out 5-1/7-1/7-2, 见组合基准报告附录):
#   p=2/α=1 → cal 21/31 (+4) 但 held 9/18 (−2), 违反 held-out 不降约束 → 否决;
#   p=1/α=1 → cal 19/31 (+2), held 10/18 (−1, 全部来自 7-1 Anatase 被
#   同构 rutile 型 PbO2 以微弱覆盖优势顶替), 总 28→29。取 p=1。
_COVER_CONSIST_POW = 1.0

# S14: 一致性强度插值 α ∈ [0,1]: c_eff = (1-α) + α·c^p。
# α=0 → 无一致性项 (S11+S12 原状, 28/49); α=1 → 全强度 (29/49)。
# λ (_COMBO_FOM_WEIGHT) 在 0.05→1.0 六档上完全不敏感 → 维持 0.05。
_COVER_CONSIST_ALPHA = 1.0

# S14b: 自解释率缩放 (覆盖毯坍缩主修)。密集弱线相 (库内百余条弱线) 靠
# "运气线"撞上强观测峰即可在覆盖目标 Σ_j max_i vec_i[j] 里拿高分
# (实测 2-1: Gypsum 自身 cover 仅 7.5%、主线 11.59°(I=100) 未命中任何观测峰,
# covvec 却=2.0, 2.5 倍于 cover=76% 的 Calcite → 组合丢 Calcite 留 Gypsum)。
# 根因: 覆盖目标只奖励"解释观测峰", 从不惩罚"自己的峰表没被解释"。
# 修法: 每候选相算**强度加权自解释率** r = Σ_k b_k·q_k / Σ_k b_k
#   (b_k = 参考强度归一, q_k = 该参考峰对全部实测峰的最佳命中质量),
#   覆盖向量乘 (ε + (1-ε)·r^β)。真实相强线大多命中 → r≈0.8-1 几乎无影响;
#   覆盖毯相强线未命中 → r≈0.05, 贡献按 r^β 塌缩 (按 b 加权使惩罚由强线主导,
#   噪声弱线的零星命中拉不回来)。
# β=1/ε=0 起步 (v2.3.1); 13 试样基准验证见 docs/基准报告-物相检索与精修-v2.3.md。
_COMBO_SELF_RECALL_BETA = 1.0
_COMBO_SELF_RECALL_EPS = 0.0

# S14c: 检索 FoM 可观测性下限 (S09 min_visible_frac 默认启用)。
# 运动学强度谱的密集相 (Muscovite 267 线 / Albite 313 线 / Hornblende 211 线)
# 大量弱线在实验中本就不可见, 全部计入漏检罚分 → 真相被压出 top20。
# I_ref/Imax < 0.1 的参考线不计漏检; 13 试样实证: A 级零回归,
# B 级 top3 29→31、top10 40→42、MRR 0.455→0.478。
# scale="auto" (S10) 与 scale_penalty 实测变差 (B 级 top3 −3), 维持默认关闭。
_FOM_MIN_VISIBLE_FRAC = 0.1

# B-3: FoM 特异性项局部噪声自适应幅度下限 (替代全局下限)。
# 寻峰无幅度下限 (min_signal_abs=0 / min_prominence_frac=0) 时, 自动检峰里
# 噪声峰 ~88% 总数但仅贡献 ~28% 总强度, v2.1 强度加权口径下特异性项仍被
# 噪声累积强度淹没 (惩罚项 0.084 vs 干净峰表 0.040)。B-3 按 2θ 局部窗口
# (5° 内) MAD×k 阈值过滤 obs 峰强度, 强度 < 阈值的峰不计入特异性项 ——
# 安静区局部 MAD 小→弱峰保留, 噪声区局部 MAD 大→假峰剔除。
# 0 = 关 (默认行为与 v2.3 一致); 3.0 ≈ 3σ 显著性。
# ⚠️ 默认关闭 (k=0.0): 13 试样 A/B 标尺实测, 单独启用 k=3 仅 B 级 top10 +1
#  (42→43)、MISS 零变化, 却使 7-2 Clinochlore A5→7/B12→16、5-1 Cristobalite
#  B11→12 退化; 与 B-4 叠加更放大 Clinochlore 退化 (见下 B-4 注释)。能力以
#  参数 fom_local_mad_k 保留, 供噪声谱按需开启。
_FOM_LOCAL_MAD_K = 0.0
_FOM_LOCAL_MAD_WINDOW = 5.0

# B-4: PO (择优取向) 感知检索评分。
# 层状/链状硅酸盐 (Muscovite 2M1 / Hornblende) 在压片制样时晶面强烈择优
# 取向, 实测强度与运动学计算强度系统性偏离 → 参考峰强线被压成弱线、漏检
# 罚分飙升 → v2.3 最后 4 个 MISS (Muscovite×2 / Hornblende / Zircon)。
# B-4 在检索阶段对"参考峰密集" (≥ _FOM_PO_MIN_REFS 条) 的候选做 r∈grid
# March-Dollase 网格搜索 (织构轴 [001]), 选最优 r 的 FoM 作为该候选最终分。
# 两道保守护栏 (13 试样 A/B 标尺扫参标定):
#   护栏1 _FOM_PO_MIN_REFS: 只对极密集峰表 (≥80 线) 候选做 PO —— Muscovite
#     267 / Hornblende 211 是典型 PO 受害者; 放宽到 30 会让 7-2 Clinochlore
#     等中等密度相被 r 网格误优化而整体变差 (B top3 −2 / MRR_B −0.026),
#     收紧到 150 则少收 5-2b Muscovite。实测 80~100 为平台, 取 80。
#   护栏2 _FOM_PO_IMPROVE_FRAC: r≠1.0 的 FoM 须比 r=1.0 好 > 10% 才采用。
#     阈值由 0.05 提到 0.10 反而更优: 0.05 放行大量"轻微虚假优化"的伪匹配候选
#     挤掉真相 (5-2b Muscovite 仍 MISS), 0.10 只接受实质改善。
# r=1.0 = 无取向 (与 v2.3 一致); r<1 → [001] 平行晶面增强; r>1 → 垂直增强。
_FOM_PO_GRID = (0.6, 0.8, 1.0, 1.3)
_FOM_PO_AXIS = (0, 0, 1)
_FOM_PO_MIN_REFS = 80
_FOM_PO_IMPROVE_FRAC = 0.10

# B-5: PFSM (峰型拟合重排) 接入排序链路。
# FoM 基于峰位匹配, 对密集峰表相 (Cristobalite 71 线) 容易因"弱线漏检"
# 把真相压到 top14 (5-1 Cristobalite 被 top12 组合截断 = MISS)。PFSM 直接
# 比实测谱 vs 单相合成谱的形态相关性, 不依赖峰位一一匹配, 对弱线多的相
# 更稳健。``profile_fitting_score`` 已存在但未接入排序。
# B-5 在 FoM 排序后对 top ``_FOM_PFSM_TOP_N`` 候选算 PFSM corr, 按综合分
#   (1-w)·FoM_rank + w·PFSM_rank 重排 (rank 升序, 越低越前)。
# 0 = 关 (默认行为退回 FoM-only 排序)。
# 实测: w=0.2 在 5-1 让 Cristobalite 排 14→11 (进 top12), 但组合算法仍选
# Zircon 而非 Cristobalite → B-5 未能解决 5-1 组合缺失; 同时退化 3-1
# (Corundum 2→6, Fluorite 3→7) 与 5-2b (Muscovite 10→19). 5-1 的真问题在
# build_refinement_combination 的选择策略, 非搜索截断. 故默认关闭, 留参数供按需开启.
# v2.5 C3 复测: 改用 ΔRwp 排序 + 双过滤后, w=0.3 仍使 B 级 MISS 2→3
# (Clinochlore 被挤出 top20)、B top3 32→31 → 默认仍关, 基础设施保留。
_FOM_PFSM_TOP_N = 50
_FOM_PFSM_WEIGHT = 0.0

# B-5 PFSM 双过滤 (仿 Match! "Minimum Rwp reduction required" +
# "Minimum intensity scale factor"):
#   - delta_rwp < _FOM_PFSM_MIN_RWP_REDUCTION (%) 的候选视为伪阳性, 不进重排;
#   - scale < _FOM_PFSM_MIN_SCALE 的候选视为微量/噪声, 不进重排。
# 开启 PFSM 时 (fom_pfsm_weight > 0) 生效; 排序指标用 ΔRwp (替代旧的 corr,
# 因 corr 对背景/峰形整体形状敏感, 微量相弱贡献被主相淹没; ΔRwp 直接度量
# "该相对解释残差的贡献", 物理意义更明确)。
_FOM_PFSM_MIN_RWP_REDUCTION = 0.5
_FOM_PFSM_MIN_SCALE = 0.02

# B-6: per-entry 零点偏移网格搜索 (仿 Match! Automatic zero point adaptation)。
# 样品位移 / 仪器零点残差会使峰位整体偏移, 全局校正只能修一个平均偏移;
# per-entry 在小网格上扫 dz 取最优 FoM, 让真值相"对得更准"。
# 两道护栏 (借鉴 B-4 PO 经验):
#   护栏1 幅度限制: |dz| ≤ 0.15°, 超过 = 数据质量问题而非零点问题;
#   护栏2 改善阈值: dz≠0 的 FoM 须比 dz=0 好 > 10% 才采用, 避免"轻微优化"
#     的伪匹配挤掉真相 (与 B-4 PO 同款 0.10 口径; 0.05 实测让 7-2 少峰相
#     Hornblende/Zircon 被密集相挤到 top20 外, A 级 MISS 0→2)。
# **v2.5 验收消融 (13 试样) 实测为净负 → 默认关闭** (与 B-3 同款处置):
#   唯一收益 = B top10 42→44, 但该收益与 B-7 重叠 (关 B-6 保 B-7 时 B top10
#   仍为 44); 代价 = A MISS 0→1 (7-2 Zircon)、A top3 33→32、MRR_A 0.499→0.493、
#   MRR_B 0.488→0.485、组合相级 45→44 (7-2 Clinochlore 被挤掉)。
#   参数 `fom_zero_grid` 保留, 供零点漂移明显的谱按需开启
#   (grid=(±0.05,0) + frac=0.20 亦验证为次优解, 逊于直接关闭)。
_FOM_ZERO_GRID: Optional[tuple] = None
_FOM_ZERO_IMPROVE_FRAC = 0.10

# B-7: 最小关联峰数惩罚 (仿 Match! "Min. no. of corr. peaks" 默认 2)。
# 窄 2θ 窗口内只有 1 条参考峰能对上实测峰时, 偶然匹配概率高 → 伪阳性。
# 用 ×2 惩罚而非直接淘汰, 避免误杀高对称少峰相 (Zircon 等)。
# **v2.5 验收消融: 本版组合改善 (42→44 相级 / 8→10 试样级) 与检索 B top10
# +2 的唯一真实来源**; E1/E2/B-6 对结果均无贡献 (见 docs/CHANGELOG §[2.5.0])。
_FOM_MIN_CORR_PEAKS = 2
_FOM_LOW_CORR_PENALTY = 2.0


def _combo_fom_weight(obs_int) -> float:
    """S03: λ = _COMBO_FOM_WEIGHT × 平均观测权重。

    w_j = obs_int[j]/max(obs_int) (与覆盖向量同口径); 强度缺失/全 0 → 1。
    scores 缺失时 B&B 内部自然退化为纯覆盖 (fom_weight×0)。
    """
    try:
        arr = np.asarray([float(v) for v in obs_int], dtype=float)
    except (TypeError, ValueError):
        return _COMBO_FOM_WEIGHT
    if arr.size == 0:
        return _COMBO_FOM_WEIGHT
    mx = float(arr.max())
    if not (mx > 1e-12):
        return _COMBO_FOM_WEIGHT
    return _COMBO_FOM_WEIGHT * float(arr.mean() / mx)

_logger = logging.getLogger(__name__)

from polyxrd.config import get_config
from polyxrd.models.fom import confidence_from_score
from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.foam import compute_fom
from polyxrd.utils.formula_parser import (
    parse_formula, elements_from_db_formula, elements_match_filter,
    normalize_element_filter,
)
from polyxrd.utils.resources import get_resource_path

# 纯金属相惩罚: 单元素金属参考峰少易误匹配 (非金属/类金属除外)
_NONMETAL: frozenset[str] = frozenset({
    "H", "He", "N", "O", "F", "Ne", "Cl", "Ar", "Br", "Kr", "I", "Xe", "Rn",
    "S", "P", "C", "Si", "Se", "Te", "As", "Ge", "B",
})
_PURE_METAL_PENALTY = 1.5

# ── COD 候选最终排序口径 (0.9.11 修订) ────────────────────────
# _cod_rank_score = (1-w)·fom_good + w·h,  h 为 Hanawalt 预筛度量 (0..1)。
# w = _COD_RANK_H_WEIGHT。0.9.11 初版取 w=0.30 且 fom_good 用固定尺度 1.2,
# 但 13 试样基准显示: 多相样品里**每个**候选都解释不了大部分实测峰, FoM 普遍
# > 1.2 → fom_good 全部饱和到 0 → 混合式退化成 0.3·h, 即把 FoM 信息整体丢弃,
# 反而比纯 FoM 排序差 (Top-3 7→9, Top-10 12→15)。故下调 w 并改用指数变换
# exp(-fom/_COD_RANK_FOM_TAU), 使 FoM 在 1~3 的常见区间内仍有区分度。
_COD_RANK_H_WEIGHT = 0.10
_COD_RANK_FOM_TAU = 0.8


def cod_rank_score(item: tuple[dict, PhaseMatchResult]) -> float:
    """COD 候选的最终排序分 (越大越好)。

    item = (预筛候选 dict, _match_phase_fom 结果)。预筛 dict 提供 Hanawalt
    度量 h ∈ [0,1]; 结果提供 FoM (越低越好)。

    fom_good = exp(-FoM/τ) 而非 1-clip(FoM/1.2): 后者在多相样品里会因
    "每个物相都解释不了大部分实测峰" (FoM 普遍 >1.2) 而整体饱和到 0,
    把 FoM 信息完全丢弃。
    """
    c, r = item
    h = (0.40 * float(c.get("main_peak_match", 0.0))
         + 0.30 * float(c.get("top_precision", 0.0))
         + 0.20 * float(c.get("intensity_weighted_top_recall", 0.0))
         + 0.10 * float(c.get("top_recall", 0.0)))
    fom_good = float(np.exp(-max(float(r.score), 0.0) / _COD_RANK_FOM_TAU))
    return (1.0 - _COD_RANK_H_WEIGHT) * fom_good + _COD_RANK_H_WEIGHT * h


def _is_pure_metal(phase: Phase) -> bool:
    """单元素金属 (H/N/O/S/C/Si/卤素/稀有气体等非金属除外)"""
    els = phase.elements or set()
    return len(els) == 1 and not (els & _NONMETAL)


def default_peak_list(data: XRDData) -> PeakList:
    """物相识别在未显式传入峰列表时使用的默认寻峰。

    0.9.11: 改用高精度检测器 (peak_detection.detect_peaks_from_data)。
    它用**局部噪声 σ 倍数**而非"全局最大强度的百分比"做阈值, 且最小峰间距
    为 0.10° —— 而传统 PeakFinder.find_peaks 的 height/prominence 阈值是相对
    Imax 的全局值, 遇到"某一条极强峰 + 其余弱峰"的谱 (如含云母基面反射的
    岩石样) 会把其余峰全部判为噪声。13 试样基准: 平均检出峰 8.8→64,
    Top-1 7→10, Top-20 15→22, Top-40 22→28。

    检测器不可用 (缺依赖/异常) 时回退到传统寻峰, 保证不中断。
    """
    try:
        from polyxrd.services.peak_detection import detect_peaks_from_data
        pl = detect_peaks_from_data(data)
        if len(pl.peaks):
            return pl
    except Exception:
        pass
    from polyxrd.services.peak_finder import PeakFinder
    return PeakFinder().find_peaks(data)


class PhaseIdentifier:
    """物相识别服务

    基于实验峰与参考数据库峰的匹配进行物相识别。
    使用FOM (Figure of Merit) 算法评估匹配质量。

    FOM = Σ|2θ_obs - 2θ_calc| / Σ(2θ_calc) × N_matched × 100

    FOM越低匹配越好:
    - FOM < 0.1: 极好匹配
    - FOM < 0.3: 良好匹配
    - FOM < 0.5: 一般匹配
    - FOM > 0.5: 可能不匹配
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._phase_database: list[Phase] = []
        self._reference_data: list[dict] = []
        self._load_reference_database()

    def _load_reference_database(self) -> None:
        # 无机/合金小库 + 有机/药物相库 合并进同一可检索列表
        db_paths = [
            get_resource_path("database/xrd_reference_database.json"),
            get_resource_path("database/organic_reference_database.json"),
        ]
        self._reference_data = []
        self._phase_database = []
        for db_path in db_paths:
            if db_path and Path(db_path).exists():
                try:
                    with open(db_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._reference_data.extend(data.get("phases", []))
                except Exception as e:
                    _logger.warning("PhaseIdentifier: failed to load %s: %s", db_path, e)
        if self._reference_data:
            self._phase_database = self._build_phases_from_db(self._reference_data)
            _logger.info("PhaseIdentifier: loaded %d reference phases", len(self._phase_database))
        else:
            _logger.warning("PhaseIdentifier: reference databases missing, using default phases")
            self._load_default_phases()

    def _build_phases_from_db(self, ref_data: list[dict]) -> list[Phase]:
        phases = []
        for entry in ref_data:
            peaks = []
            for p in entry.get("peaks", []):
                hkl = tuple(p["hkl"])
                two_theta = p["two_theta"]
                intensity = p.get("intensity", 50)
                peaks.append((hkl, two_theta, intensity))

            lattice_data = entry.get("lattice") or {}
            from polyxrd.models.phase import LatticeParams
            if lattice_data:
                lattice = LatticeParams(
                    a=lattice_data.get("a", 1.0),
                    b=lattice_data.get("b", 1.0),
                    c=lattice_data.get("c", 1.0),
                    alpha=lattice_data.get("alpha", 90.0),
                    beta=lattice_data.get("beta", 90.0),
                    gamma=lattice_data.get("gamma", 90.0),
                )
            else:
                # 实验谱提取的相没有晶胞 (无 Rietveld 精修能力, 仅用于检索匹配)
                lattice = None

            formula = entry.get("formula", "")
            elements = parse_formula(formula) if formula else set()

            phase = Phase(
                name=entry.get("name", entry.get("key", "")),
                formula=formula,
                space_group=entry.get("space_group", ""),
                lattice=lattice,
                reference_peaks=peaks,
                elements=elements,
            )
            phases.append(phase)
        return phases

    def _load_default_phases(self) -> None:
        wavelength = self._config.default_wavelength
        phases = []

        si = Phase(
            name="Silicon", formula="Si", space_group="Fd-3m", lattice=None,
            reference_peaks=[
                ((1, 1, 1), 28.44, 100), ((2, 2, 0), 47.30, 60),
                ((3, 1, 1), 56.11, 35), ((4, 0, 0), 69.13, 15),
                ((3, 3, 1), 76.36, 12), ((4, 2, 2), 88.04, 10),
            ],
            elements={"Si"},
        )
        phases.append(si)

        sio2 = Phase(
            name="α-Quartz", formula="SiO2", space_group="P3121", lattice=None,
            reference_peaks=[
                ((0, 1, 0), 20.85, 88), ((1, 0, 0), 26.64, 100),
                ((0, 1, 1), 36.50, 55), ((1, 0, 1), 39.33, 12),
                ((1, 1, 0), 50.14, 14), ((1, 1, 2), 59.95, 14),
            ],
            elements={"Si", "O"},
        )
        phases.append(sio2)

        nacl = Phase(
            name="Halite", formula="NaCl", space_group="Fm-3m", lattice=None,
            reference_peaks=[
                ((1, 1, 1), 27.45, 100), ((2, 0, 0), 31.97, 55),
                ((2, 2, 0), 45.68, 65), ((3, 1, 1), 54.93, 15),
            ],
            elements={"Na", "Cl"},
        )
        phases.append(nacl)

        al2o3 = Phase(
            name="Corundum", formula="Al2O3", space_group="R-3c", lattice=None,
            reference_peaks=[
                ((0, 1, 2), 25.58, 100), ((1, 0, 4), 35.16, 85),
                ((1, 1, 3), 43.36, 75), ((0, 2, 4), 52.56, 90),
            ],
            elements={"Al", "O"},
        )
        phases.append(al2o3)

        self._phase_database = phases

    def identify(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        elements: Optional[list[str]] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
    ) -> list[PhaseMatchResult]:
        """执行物相识别

        Args:
            data: XRD数据
            peaks: 峰列表 (可选，自动检测如未提供)
            elements: 已知元素过滤 (可选，逗号分隔的元素列表)
            top_n: 返回候选数量
            tolerance: 2θ匹配容差 (度)

        Returns:
            匹配结果列表，按FOM升序排列 (FOM越低越好)
        """
        element_filter = None
        if elements:
            element_filter = {
                "must": elements,
                "maybe": [],
                "exclude": [],
            }
        return self.identify_with_element_filter(
            data=data, peaks=peaks,
            element_filter=element_filter,
            top_n=top_n, tolerance=tolerance,
        )

    # ── 组合选择辅助: 结构去重 / 实测峰掩码 / 分支定界 ─────────

    @staticmethod
    def _phases_structurally_same(pa, pb, tol: float = 0.15) -> bool:
        """判断两个物相是否为"同一结构的重复条目"。

        旧去重逻辑按 (化学式, 元素集合) 一刀切，会把化学式相同但结构
        不同的真正多型 (石英 vs 方石英, 均 SiO2; 锐钛矿 vs 金红石,
        均 TiO2) 误删。这里改为参考峰位的**双向覆盖**判定:
          A→B 覆盖 ≥70% 且 B→A 覆盖 ≥70% 才视为同一结构。

        只做单向会误判: 峰位稀疏的相 (如纯金属 ~6 峰) 每条峰几乎总能
        在峰位密集的相 (如 Calcite ~98 峰) 中找到 ±tol 配对 → 单向 100%
        "命中" 实为包含而非同构。双向后嵌套情形的一方覆盖仅 ~6% 被拒。
        """
        a = [tt for _, tt, _ in pa.get_reference_peaks()]
        b = [tt for _, tt, _ in pb.get_reference_peaks()]
        if not a or not b:
            return False
        aa = np.sort(np.asarray(a, dtype=float))
        bb = np.sort(np.asarray(b, dtype=float))

        def _cov(x, y) -> float:
            # x 中多少比例的峰在 y 中存在 ±tol 对应
            hit = 0
            for v in x:
                i = int(np.searchsorted(y, v))
                if i < len(y) and abs(y[i] - v) <= tol:
                    hit += 1
                elif i > 0 and abs(y[i - 1] - v) <= tol:
                    hit += 1
            return hit / len(x)

        return _cov(aa, bb) >= 0.7 and _cov(bb, aa) >= 0.7

    @staticmethod
    def _as_observed_peaks(peaks):
        """把 PeakList / list[Peak] 归一化为 [(two_theta, intensity), ...]"""
        items = getattr(peaks, "peaks", peaks) or []
        out = []
        for p in items:
            if p is None:
                continue
            tt = getattr(p, "two_theta", None)
            if tt is None:
                continue
            out.append((float(tt), float(getattr(p, "intensity", 1.0) or 1.0)))
        return out

    @staticmethod
    def _formula_key(formula: str) -> str:
        """S05: 归一化成分分组键 (复用 parse_formula_detailed, 不另写解析)。

        先把水合物的常见分隔写法 (·/./:/* + nH2O) 规范成解析器可正确
        处理的 (H2O)n 形式, 再交给 parse_formula_detailed 做成分归一;
        解析失败 → 回退小写去空格原文 (宁宽松勿漏判)。
        仅用于去重分组, 不改写 phase.formula (展示/导出不受影响)。
        """
        import re as _re
        from polyxrd.utils.formula_parser import parse_formula_detailed
        s = formula or ""
        s = _re.sub(r"[·•.:*\s]+(\d*)\s*(H2O)\b", r"(\2)\1", s, flags=_re.I)
        try:
            comp = parse_formula_detailed(s)
        except Exception:
            comp = None
        if not comp:
            return (formula or "").replace(" ", "").lower()
        return " ".join(f"{el}{float(v):g}" for el, v in sorted(comp.items()))

    def _dedupe_results(self, results, peaks=None, tolerance: float = 0.2) -> list:
        """结构感知 + 数据感知的同成分条目去重。

        同 (归一化成分, elements) 的多条候选, 有两种成因:
          a) 同一结构的重复条目 (如 Fluorite/CaF2 两版本、Brucite 重复)
             → 只留 FOM 最优 (最先出现) 一条
          b) 结构不同的真正多型 (α-Quartz vs Cristobalite vs Tridymite 均
             SiO2; Anatase vs Rutile 均 TiO2; Calcite vs Aragonite 均 CaCO3)
             → 不能一律按公式合并, 否则 5-x 试样(石英+方石英并存)的预期
               物相永远进不了候选池

        数据感知规则 (peaks 提供时): 同一公式组内, 后续多型只有在"解释了
        组内已保留成员解释不到的实测峰"时才保留; 否则视为无独立数据证据的
        噪声 (如纯方解石试样里不会留下文石)。peaks 缺失时保守全保留多型。
        """
        obs_tt = None
        if peaks is not None:
            obs_tt = [o[0] for o in self._as_observed_peaks(peaks)]
            if not obs_tt:
                obs_tt = None

        kept: list = []
        kept_keys: list = []
        for r in results:
            formula = r.phase.formula or ""
            key = self._formula_key(formula)
            group = [s for s, sk in zip(kept, kept_keys)
                     if sk == key
                     and s.phase.elements == r.phase.elements]
            if not group:
                kept.append(r)
                kept_keys.append(key)
                continue
            # 同一结构重复条目 → 剔除
            if any(self._phases_structurally_same(s.phase, r.phase)
                   for s in group):
                continue
            # 无实测峰信息 → 保守保留多型
            if obs_tt is None:
                kept.append(r)
                kept_keys.append(key)
                continue
            # 数据感知: 必须解释到已保留成员解释不到的实测峰
            r_msk = self._phase_hit_mask(r.phase, obs_tt, tolerance)
            if r_msk == 0:
                continue
            group_msk = 0
            for s in group:
                group_msk |= self._phase_hit_mask(s.phase, obs_tt, tolerance)
            if r_msk & ~group_msk:
                kept.append(r)
                kept_keys.append(key)
        return kept

    @staticmethod
    def _phase_hit_mask(phase, obs_tt, tolerance: float) -> int:
        """物相参考峰命中的实测峰位掩码 (Python int 位集)。

        每条参考峰只要在容差内命中任意实测峰即置位该实测峰对应的位；
        同一实测峰被多条参考峰命中只算一次。
        (v2.2 起仅供 `_dedupe_results` 使用; 组合目标改用 `_phase_cover_vector`。)
        """
        msk = 0
        for _, tt, _ in phase.get_reference_peaks():
            for j, o in enumerate(obs_tt):
                if abs(tt - o) <= tolerance:
                    msk |= (1 << j)
        return msk

    @staticmethod
    def _phase_cover_vector(phase, obs_tt, obs_int, tolerance: float) -> "np.ndarray":
        """S02+S14: 物相对实测峰的"强度 × 命中质量 × 尺度一致性"覆盖向量。

        cover_j = max_k[q_jk · c_jk] · w_j
          q_jk = 1 - |Δ_jk| / tol                      (参考峰 k 命中质量)
          c_jk = (1-α) + α·[min(a_j, s*·b_k) / max(a_j, s*·b_k)]^p   (S14 尺度一致性)
          a_j = obs_int[j] / max(obs_int)              (观测强度归一)
          b_k = I_ref_k / I_ref_max                    (参考强度归一)
          s* = Σ(w_j·a_j·b_k) / Σ(w_j·b_k²)            (命中对上的最小二乘尺度)
        w_j = obs_int[j] / max(obs_int)                (缺强度/全 0 时取 1)

        S14 尺度一致性的作用: 密集弱线相即使峰位全沾上, 但强度对不上
        (弱线配到强观测峰) 时单峰贡献被压低 —— "覆盖毯"塌缩 (13 试样基准
        5-2/5-2b 回退的根因, 见 docs/基准报告-物相组合-v1.md 附录)。
        s* 只由互斥最优命中对估计, 强线主导 (w_j 大), 噪声弱峰不拉偏。

        边界: obs_int 全 0/缺失 → 等权 (w_j=1) 且 q=c=1 (退回旧布尔口径)。
        """
        ref_peaks = [(float(tt), float(i)) for _, tt, i in phase.get_reference_peaks()
                     if i is not None]
        n = len(obs_tt)
        vec = np.zeros(n, dtype=float)
        if n == 0 or not ref_peaks:
            return vec
        oi = np.asarray(obs_int, dtype=float) if len(obs_int) == n \
            else np.ones(n, dtype=float)
        max_int = float(oi.max()) if oi.size else 0.0
        degenerate = not (max_int > 1e-12)
        if degenerate:
            # 旧布尔口径: 等权 + 命中即 1
            obs = np.asarray([float(t) for t in obs_tt], dtype=float)
            for rt, _ in ref_peaks:
                vec = np.maximum(vec, (np.abs(obs - rt) <= tolerance).astype(float))
            return vec

        weights = oi / max_int
        a = weights.copy()
        ref_i = np.asarray([i for _, i in ref_peaks], dtype=float)
        ref_max = float(ref_i.max())
        b = ref_i / ref_max if ref_max > 1e-12 else np.ones_like(ref_i)
        obs = np.asarray([float(t) for t in obs_tt], dtype=float)

        # 每个实测峰的互斥最优命中 (与 S02 相同: q 最大者)
        best_q = np.zeros(n, dtype=float)
        best_k = np.full(n, -1, dtype=int)
        for k, (rt, _) in enumerate(ref_peaks):
            d = np.abs(obs - rt)
            q = np.where(d <= tolerance, 1.0 - d / tolerance, 0.0)
            upd = q > best_q
            best_q[upd] = q[upd]
            best_k[upd] = k

        matched = best_q > 0
        if not matched.any():
            return vec
        # s*: 命中对上的最小二乘强度尺度 (强观测峰权重大)
        bb = b[best_k[matched]]
        den = float(np.sum(weights[matched] * bb * bb))
        if den > 1e-12:
            s_star = float(np.sum(weights[matched] * a[matched] * bb)) / den
        else:
            s_star = 1.0
        if not (s_star > 1e-12):
            s_star = 1.0

        idx = np.nonzero(matched)[0]
        pow_p = _COVER_CONSIST_POW
        alpha = _COVER_CONSIST_ALPHA
        for j in idx:
            sb = s_star * b[best_k[j]]
            hi = max(float(a[j]), float(sb))
            consist = (min(float(a[j]), float(sb)) / hi) if hi > 1e-12 else 1.0
            if pow_p != 1.0:
                consist = consist ** pow_p
            if alpha != 1.0:
                consist = (1.0 - alpha) + alpha * consist
            vec[j] = best_q[j] * consist * float(weights[j])
        return vec

    @staticmethod
    def _phase_self_recall(phase, obs_tt, tolerance: float) -> float:
        """S14b: 相参考峰表被实测数据解释的**强度加权**自解释率 r ∈ [0,1]。

        r = Σ_k b_k·q_k / Σ_k b_k
          b_k = I_ref_k / I_ref_max         (参考强度归一; 惩罚由强线主导)
          q_k = max_j (1 − |Δ_kj| / tol)    (该参考峰对实测峰的最佳命中质量, 无命中=0)

        与 m.coverage (逐线计数百分比) 的区别: 按参考强度加权后, 密集弱线相
        "少量弱线沾上强观测峰、主线全落空"的覆盖毯形态得到 r≈0 的重罚,
        而真实相 (主线命中) 保持 r≈0.8–1。
        """
        ref_peaks = [(float(tt), float(i)) for _, tt, i in phase.get_reference_peaks()
                     if i is not None]
        if not ref_peaks or not obs_tt:
            return 1.0
        ref_i = np.asarray([i for _, i in ref_peaks], dtype=float)
        ref_max = float(ref_i.max())
        if not (ref_max > 1e-12):
            return 1.0
        b = ref_i / ref_max
        obs = np.asarray([float(t) for t in obs_tt], dtype=float)
        q = np.zeros(len(ref_peaks), dtype=float)
        for k, (rt, _) in enumerate(ref_peaks):
            d = np.abs(obs - rt)
            within = d <= tolerance
            if within.any():
                q[k] = float((1.0 - d[within] / tolerance).max())
        den = float(b.sum())
        if not (den > 1e-12):
            return 1.0
        return float(np.dot(b, q) / den)

    @staticmethod
    def _branch_and_bound_select(masks, metal_flags, n_obs,
                                 size_targets=None, scores=None,
                                 cover_vectors=None,
                                 fom_weight: float = 0.0,
                                 matched_peaks=None,
                                 matched_weight: float = 0.0) -> list:
        """分支定界: 选择使"联合覆盖"最大的物相子集。

        目标函数 (对给定规模 k):
          cover_vectors 给定 (S02 口径):
              cov = Σ_j max_{i∈S} cover_i[j]   (强度 × 命中质量的联合覆盖)
          cover_vectors=None (兼容旧调用):
              cov = |∪ masks_i|                (每峰等权, 布尔)
          S03: obj = cov − fom_weight · Σ_{i∈S} FoM_i
              (fom_weight=0 时退回纯覆盖; 覆盖优先, 仅覆盖接近时质量翻盘)
          平手 取 Σscore 最小 (score 为 FOM, 越低越好), 再取输入序在前者

        约束:
          - 子集内纯金属数 ≤ max(1, round(0.2·n))  (硬约束, 与旧版防御一致)
          - size_targets=None 时自动定规模: 取"联合覆盖达到全局最大"的
            最小 k (简约原则, 解释不了任何额外峰的冗余相自然被剔除)

        n ≤ 14 时精确枚举 (可视为最坏 C(14,7)=3432 的组合, 微秒级);
        n > 14 时用逐点边际增益最大的贪心构造 + 覆盖平手退避。
        两条路径在 cover_vectors 给定时**同口径** (逐点 max)。
        """
        import itertools
        n = len(masks)
        if n == 0:
            return []
        max_pm = min(max(1, round(0.2 * n)), n)

        if size_targets:
            sizes = sorted({s for s in size_targets if 1 <= s <= n}) or [n]
        else:
            sizes = list(range(1, n + 1))

        best_cov_k = {k: -1.0 for k in sizes}
        best_combo_k = {k: None for k in sizes}
        use_cover = cover_vectors is not None

        def _cov_of(combo) -> float:
            if not use_cover:
                cov = 0
                for i in combo:
                    cov |= masks[i]
                return float(bin(cov).count("1"))
            if not combo:
                return 0.0
            joint = np.max(np.vstack([cover_vectors[i] for i in combo]), axis=0)
            return float(joint.sum())

        def _consider(k, combo):
            cov = _cov_of(combo)
            obj = cov
            if fom_weight and scores:
                obj = cov - fom_weight * sum(scores[i] for i in combo)
            # v2.5 E3: 匹配峰数奖励 — 多峰匹配 (matched_peaks 高) 是真相强信号,
            #   即使弱线相被 self-recall 压塌, 匹配峰数也能把它拉回竞争。
            if matched_weight and matched_peaks:
                obj = obj + matched_weight * sum(
                    float(matched_peaks[i]) for i in combo)
            if obj > best_cov_k[k] + 1e-12 or (
                abs(obj - best_cov_k[k]) <= 1e-12 and best_combo_k[k] is not None and scores
                and sum(scores[i] for i in combo)
                < sum(scores[i] for i in best_combo_k[k])
            ):
                best_cov_k[k] = obj
                best_combo_k[k] = tuple(combo)

        def _metal_ok(combo):
            if sum(1 for i in combo if metal_flags[i]) > max_pm:
                return False
            return True

        if n <= 14:
            for k in sizes:
                for combo in itertools.combinations(range(n), k):
                    if not _metal_ok(combo):
                        continue
                    _consider(k, combo)
        else:
            # 贪心: 每次取边际增益最大的候选 (纯金属约束内)
            for k in sizes:
                combo = []
                covered = 0
                joint = np.zeros(n_obs, dtype=float) if use_cover else None
                for _step in range(k):
                    best_i, best_gain = None, -1.0
                    for i in range(n):
                        if i in combo:
                            continue
                        if sum(1 for j in combo if metal_flags[j]) \
                                + (1 if metal_flags[i] else 0) > max_pm:
                            continue
                        if use_cover:
                            gain = float(np.maximum(joint, cover_vectors[i]).sum()
                                         - joint.sum())
                        else:
                            gain = bin(masks[i] & ~covered).count("1")
                        if gain > best_gain:
                            best_gain, best_i = gain, i
                    if best_i is None:
                        break
                    combo.append(best_i)
                    if use_cover:
                        joint = np.maximum(joint, cover_vectors[best_i])
                    else:
                        covered |= masks[best_i]
                if combo:
                    _consider(k, combo)

        if size_targets:
            k0 = sizes[0]
            if best_combo_k[k0] is not None:
                return list(best_combo_k[k0])
            # 目标规模不可行 (纯金属约束过紧) → 放松约束再选
            relaxed = PhaseIdentifier._branch_and_bound_select(
                masks, [False] * n, n_obs, size_targets, scores
            )
            return relaxed

        # 自动规模: 最小 k 达到全局最大联合覆盖
        maxcov = max(best_cov_k.values()) if best_cov_k else -1
        if maxcov <= 0:
            return []
        for k in sizes:
            if best_cov_k[k] == maxcov and best_combo_k[k] is not None:
                return list(best_combo_k[k])
        return []

    def _legacy_refinement_combination(self, kept: list,
                                       expected_count: Optional[int]) -> list:
        """旧版启发式 (peaks 未提供时的回退路径)。

        语义与 v0.9.x build_refinement_combination 一致:
        coverage 过滤已完成; 这里做 expected_count 截断 + 纯金属比例防御
        + 低覆盖率纯金属剔除。
        """
        sel = list(kept)
        if expected_count and expected_count > 0:
            sel = sel[:expected_count]
        pm_idx = [i for i, m in enumerate(sel) if _is_pure_metal(m.phase)]
        cap = max(1, round(0.2 * len(sel)))
        if len(pm_idx) > cap:
            drop = set(pm_idx[cap:])
            sel = [m for i, m in enumerate(sel) if i not in drop]
        out = []
        for m in sel:
            if _is_pure_metal(m.phase) and m.coverage < 0.55:
                continue
            out.append(m.phase)
        return out

    def build_refinement_combination(
        self,
        matches: list,
        expected_count: Optional[int] = None,
        min_coverage: float = 0.5,
        peaks=None,
        tolerance: float = 0.2,
        pool_top_n: Optional[int] = None,
        log_cb=None,
    ) -> list:
        """从物相识别结果中生成精修组合 (分支定界全局搜索)

        旧实现是"覆盖率过滤 + expected_count 截断 + 纯金属防御"的贪心
        流水线, 只能沿 FOM 排序从前往后截断, 无法处理多相间的局部重复/
        干扰 (Task #7):
          - 两个候选解释同一批实测峰时, 截断可能丢真相留冗余;
          - 5+ 相试样上"FOM 排序"≠"联合解释能力排序"。

        v0.10 起基于实测峰联合覆盖做分支定界 (B&B):
          1. 预处理 (与旧版一致): 结构去重 / coverage 过滤(全低回退) /
             低覆盖率纯金属剔除
          2. 未提供 peaks → 无法评估联合覆盖, 回退旧启发式
          3. 提供 peaks → 每个候选映射为"命中实测峰的掩码", 以子集联合
             覆盖最多实测峰为目标做全局搜索
             - expected_count 已知 → 恰好该规模、联合覆盖最优的子集
             - expected_count 未知 → 取覆盖不再增长的最小规模 (简约)
             - 纯金属数量上限作为硬约束参与搜索 (而非事后截断)

        Args:
            matches: identify_with_element_filter 的输出 (按 score 升序)
            expected_count: 预期物相数量 (若已知)
            min_coverage: 参考峰匹配覆盖率下限, 低于此视为噪声
                (注意: 与 v0.9.x 口径一致, 与 coverage(%) 百分比比较)
            peaks: 实测峰列表 (PeakList / list[Peak]); 提供后启用 B&B
            tolerance: 参考峰与实测峰匹配容差 (度); 默认 0.2 与主流
                identify_with_element_filter(tolerance=0.2) 调用一致

        Returns:
            list[Phase] - 可直接用于 Rietveld 精修的物相列表 (原 FOM 顺序)
        """
        # 1. 结构/数据感知去重 + coverage 过滤 (全部低于阈值则回退全量)
        filtered = self._dedupe_results(matches, peaks, tolerance)
        kept = [m for m in filtered if m.coverage >= min_coverage]
        if not kept:
            kept = filtered
        if not kept:
            return []

        # 2. 无实测峰 → 无法评估联合覆盖, 回退旧启发式
        if peaks is None:
            return self._legacy_refinement_combination(kept, expected_count)

        obs = self._as_observed_peaks(peaks)
        if not obs:
            return self._legacy_refinement_combination(kept, expected_count)
        obs_tt = [o[0] for o in obs]
        obs_int = [o[1] for o in obs]

        # 3. 候选 → 命中掩码 / 覆盖向量; 低覆盖率纯金属与
        #    "解释不了任何实测峰"者剔除
        #    S04: 池先按 FoM 升序截断至 pool_top_n —— 排名靠后的密集相
        #    不允许靠覆盖数量挤入 (expected_count 有效取 max(8, 2n), 否则 12);
        #    只影响进入 B&B 的候选, 不影响返回 UI 的完整候选列表。
        if pool_top_n is None:
            pool_top_n = (max(8, 2 * expected_count)
                          if expected_count and expected_count > 0 else 12)
        cut = max(int(pool_top_n), 1)
        pool_src = list(kept[:cut])
        dropped = kept[cut:]
        # v2.5 E2: matched_peaks >= _COMBO_KEEP_MATCHED 的相不被池裁剪丢弃
        #   (与 B-1 最小关联峰口径一致: 多峰匹配 = 真候选信号, 即使 FoM 排名
        #    靠后也应进入 B&B, 否则 5-2b Muscovite(rank11) / 7-1 Kaolinite(rank15)
        #    这类真相会被一刀切)。只追加, 不重排。
        rescued = [m for m in dropped
                   if getattr(m, "matched_peaks", 0) >= _COMBO_KEEP_MATCHED]
        if rescued:
            pool_src.extend(rescued)
            if log_cb:
                names = ", ".join(f"{m.phase.name}" for m in rescued)
                log_cb(f"[combo] 池保底回收 (matched>={_COMBO_KEEP_MATCHED}): [{names}]")
        dropped = [m for m in dropped if m not in rescued]
        if log_cb and dropped:
            names = ", ".join(
                f"{m.phase.name}(rank {i + cut + 1})"
                for i, m in enumerate(dropped))
            log_cb(f"[combo] 被池裁剪丢弃 (pool_top_n={pool_top_n}): [{names}]")

        pool: list = []
        masks: list[int] = []
        cover_vectors: list = []
        beta = _COMBO_SELF_RECALL_BETA
        eps = _COMBO_SELF_RECALL_EPS
        for m in pool_src:
            if _is_pure_metal(m.phase) and m.coverage < 0.55:
                continue
            msk = self._phase_hit_mask(m.phase, obs_tt, tolerance)
            if msk == 0:
                continue
            pool.append(m)
            masks.append(msk)
            cv = self._phase_cover_vector(m.phase, obs_tt, obs_int, tolerance)
            if beta > 0.0:
                # S14b: 自解释率缩放 — "只解释别人、解释不了自己"的覆盖毯相塌缩
                r = self._phase_self_recall(m.phase, obs_tt, tolerance)
                cv = cv * (eps + (1.0 - eps) * (r ** beta))
            cover_vectors.append(cv)
        if not pool:
            return []

        # v2.5 E1: 按 FoM 质量缩放 cover_vector —— 少峰但 FoM 优的相
        #   不被多峰相的覆盖毯稀释。池内 min-max 归一, factor∈[1, 1+boost]。
        if _COMBO_FOM_COVER_BOOST > 0.0:
            sc = np.array([float(m.score) for m in pool], dtype=float)
            smin, smax = float(sc.min()), float(sc.max())
            rng = smax - smin
            if rng > 1e-12:
                norm = (sc - smin) / rng          # 0=最优, 1=最差
                factors = 1.0 + _COMBO_FOM_COVER_BOOST * (1.0 - norm)
                for i, f in enumerate(factors):
                    cover_vectors[i] = cover_vectors[i] * float(f)

        # 4. B&B 全局选择 (S02: 目标 = 强度 × 命中质量的联合覆盖)
        metal_flags = [_is_pure_metal(m.phase) for m in pool]
        if expected_count and expected_count > 0:
            size_targets = [min(expected_count, len(pool))]
        else:
            size_targets = None
        scores = [m.score for m in pool]
        matched_list = [getattr(m, "matched_peaks", 0) for m in pool]

        # 规模退化: 若 expected_count >= 池内可解释候选数, 池全选
        if size_targets and size_targets[0] >= len(pool):
            return [m.phase for m in pool]

        selected = self._branch_and_bound_select(
            masks, metal_flags, len(obs_tt), size_targets, scores,
            cover_vectors=cover_vectors,
            fom_weight=_combo_fom_weight(obs_int),
            matched_peaks=matched_list,
            matched_weight=_COMBO_MATCHED_WEIGHT,
        )
        chosen = [pool[i].phase for i in selected]
        if log_cb:
            parts = []
            joint = np.zeros(len(obs_tt))
            for i in selected:
                cv = float(cover_vectors[i].sum()) if i < len(cover_vectors) else 0.0
                parts.append(f"{pool[i].phase.name}(cover={cv:.2f}, FoM={pool[i].score:.3f})")
                if i < len(cover_vectors):
                    joint = np.maximum(joint, cover_vectors[i])
            log_cb("[combo] pool=%d(top_n=%s) 结果=[%s] 联合覆盖=%.2f/%d"
                   % (len(pool), pool_top_n, "; ".join(parts),
                      float(joint.sum()), len(obs_tt)))
        if not chosen:
            return self._legacy_refinement_combination(kept, expected_count)
        return chosen

    def identify_with_element_filter(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        fom_obs_range=None,
        fom_scale=None,
        fom_scale_penalty: float = 0.0,
        fom_min_visible_frac: float = _FOM_MIN_VISIBLE_FRAC,
        fom_local_mad_k: float = _FOM_LOCAL_MAD_K,
        fom_local_mad_window: float = _FOM_LOCAL_MAD_WINDOW,
        fom_po_grid: Optional[tuple] = _FOM_PO_GRID,
        fom_po_axis: tuple = _FOM_PO_AXIS,
        fom_pfsm_top_n: int = _FOM_PFSM_TOP_N,
        fom_pfsm_weight: float = _FOM_PFSM_WEIGHT,
        fom_zero_grid: Optional[tuple] = _FOM_ZERO_GRID,
    ) -> list[PhaseMatchResult]:
        """执行物相识别（支持三态元素过滤）

        Args:
            data: XRD数据
            peaks: 峰列表 (可选，自动检测如未提供)
            element_filter: 元素过滤条件 {"must": [...], "maybe": [...], "exclude": [...]}
            top_n: 返回候选数量
            tolerance: 2θ匹配容差 (度)
            fom_local_mad_k: B-3 局部 MAD 倍数, 默认 ``_FOM_LOCAL_MAD_K``
                (0.0 = 默认关闭, 行为退回 v2.3); >0 启用特异性项局部噪声过滤。
            fom_local_mad_window: B-3 局部窗口宽度 (度), 默认 5.0。
            fom_po_grid: B-4 March-Dollase r 网格 (默认 ``_FOM_PO_GRID`` =
                (0.6, 0.8, 1.0, 1.3), 织构轴 [001]); None = 不启用 PO 搜索。
            fom_po_axis: B-4 织构轴方向, 默认 (0,0,1)。
            fom_pfsm_top_n: B-5 PFSM 重排的候选数 (默认 ``_FOM_PFSM_TOP_N``=50);
                对 FoM 排序后的 top N 候选算 PFSM corr 重排; 0 = 关 (FoM-only)。
            fom_pfsm_weight: B-5 PFSM 重排权重 w ∈ [0, 1] (默认 ``_FOM_PFSM_WEIGHT``
                = 0.0, 即默认关闭; >0 才启用 PFSM 重排);
                综合分 = (1-w)·FoM_rank + w·PFSM_rank, 按升序重排。
            fom_zero_grid: B-6 per-entry 零点偏移网格 (默认 ``_FOM_ZERO_GRID``
                = None, 即默认关闭 —— 13 试样消融实测净负, 见常量注释);
                传入如 (-0.05, 0.0, 0.05) 可按需启用零点搜索。

        Returns:
            匹配结果列表，按FOM升序排列 (FOM越低越好)
        """
        if peaks is None:
            peaks = default_peak_list(data)

        ef = normalize_element_filter(element_filter) if element_filter else None

        results = []
        for phase in self._phase_database:
            if ef and not elements_match_filter(
                phase.elements,
                has=ef["has"], maybe=ef["maybe"], exclude=ef["exclude"],
                must_have=ef["must_have"],
            ):
                continue

            match_result = self._match_phase_fom(
                phase, peaks, tolerance,
                obs_range=fom_obs_range,
                scale=fom_scale,
                scale_penalty=fom_scale_penalty,
                min_visible_frac=fom_min_visible_frac,
                obs_local_mad_k=fom_local_mad_k,
                obs_local_mad_window=fom_local_mad_window,
                po_grid=fom_po_grid,
                po_axis=fom_po_axis,
                zero_grid=fom_zero_grid,
            )
            results.append(match_result)

        results.sort(key=lambda r: r.score)

        # ── B-5: PFSM (峰型拟合) 重排 top N 候选 ───────────────────
        # 对 FoM 排序后的 top fom_pfsm_top_n 候选算 profile_fitting_score
        # (实测谱 vs 单相合成谱), 按综合分 (1-w)·FoM_rank + w·PFSM_rank 重排。
        # v2.5 起 PFSM 排序指标改用 ΔRwp (替代旧的 corr): corr 对背景/峰形整体
        # 形状敏感, 微量相弱贡献被主相淹没; ΔRwp 直接度量"该相对解释残差的贡献"。
        # 双过滤 (仿 Match!): delta_rwp < 0.5% 或 scale < 0.02 的候选不进重排。
        if (fom_pfsm_top_n > 0 and fom_pfsm_weight > 0
                and len(results) > 1
                and data is not None and getattr(data, "two_theta", None) is not None):
            from polyxrd.services.foam import profile_fitting_score
            n_pfsm = min(fom_pfsm_top_n, len(results))
            top = results[:n_pfsm]
            try:
                # baseline_rwp = 100.0 (无任何相时残差=全谱, Rwp=100%)
                pfsm = [profile_fitting_score(data, r.phase, baseline_rwp=100.0)
                        for r in top]
            except Exception:
                pfsm = None
            if pfsm is not None:
                # 双过滤: 只保留 delta_rwp 与 scale 达标的候选参与重排
                keep_mask = [
                    float(p.get("delta_rwp", 0.0)) >= _FOM_PFSM_MIN_RWP_REDUCTION
                    and float(p.get("scale", 0.0)) >= _FOM_PFSM_MIN_SCALE
                    for p in pfsm
                ]
                kept_idx = [i for i, k in enumerate(keep_mask) if k]
                if kept_idx:
                    # FoM rank = 0..n-1 (已升序)
                    fom_ranks = list(range(n_pfsm))
                    # PFSM rank: delta_rwp 越高越好 → 按 -delta_rwp 升序取 rank
                    drwp_order = sorted(kept_idx,
                                        key=lambda i: -float(pfsm[i].get("delta_rwp", 0.0)))
                    pfsm_ranks = [n_pfsm] * n_pfsm  # 未通过过滤 → 排末尾
                    for rank, i in enumerate(drwp_order):
                        pfsm_ranks[i] = rank
                    w = float(fom_pfsm_weight)
                    combined = [
                        (i, (1.0 - w) * fom_ranks[i] + w * pfsm_ranks[i])
                        for i in range(n_pfsm)
                    ]
                    combined.sort(key=lambda x: x[1])
                    results = [top[i] for i, _ in combined] + results[n_pfsm:]

        # ── 组合重排: 纯金属比例限制在 20% 以内, 避免过多纯金属挤占前 top_n ──
        if len(results) > 0:
            reordered = []
            non_metal_stack = [r for r in results if not _is_pure_metal(r.phase)]
            metal_stack = [r for r in results if _is_pure_metal(r.phase)]

            # 贪心: 保持相对顺序, 每 5 个中纯金属不超过 1 个 (20%)
            max_metal = max(1, int(0.2 * min(top_n, len(results))) + 0.5)
            metal_count = 0
            nm_i = 0
            m_i = 0
            total = min(len(results), top_n)
            # 先放非金属直到不够，再考虑金属，但保持原 FOM 顺序
            # 更简单: 结果中前 top_n, 若纯金属 >20% 则将超出的纯金属和下一位非金属交换
            for slot in range(min(len(results), top_n + 10)):
                if len(reordered) >= total:
                    break
                # 首选: FOM 最低的可用项
                while nm_i < len(non_metal_stack) and non_metal_stack[nm_i] in reordered:
                    nm_i += 1
                while m_i < len(metal_stack) and metal_stack[m_i] in reordered:
                    m_i += 1

                best = None
                if nm_i < len(non_metal_stack) and m_i < len(metal_stack):
                    if non_metal_stack[nm_i].score <= metal_stack[m_i].score:
                        best = non_metal_stack[nm_i]
                        nm_i += 1
                    elif metal_count < max_metal:
                        best = metal_stack[m_i]
                        m_i += 1
                        metal_count += 1
                    else:
                        # 纯金属已达上限，跳过
                        best = non_metal_stack[nm_i]
                        nm_i += 1
                elif nm_i < len(non_metal_stack):
                    best = non_metal_stack[nm_i]
                    nm_i += 1
                elif m_i < len(metal_stack) and metal_count < max_metal:
                    best = metal_stack[m_i]
                    m_i += 1
                    metal_count += 1
                else:
                    # 纯金属达上限但无更多非金属，依然放（结果少于 top_n 更糟）
                    if m_i < len(metal_stack):
                        best = metal_stack[m_i]
                        m_i += 1
                if best is not None:
                    reordered.append(best)

            # 若重排后结果数量充足则使用，否则回退原排序
            if len(reordered) >= total:
                results = reordered
            # 否则保留 results (原排序, 仅 top_n 裁剪)

        # ── 去重: 结构感知 + 数据感知 (Task #7) ────────────────
        # 内置库中同一化学式可能有多条目:
        #   a) 真重复 (同一结构, 如 CaF2 两版本) → 合并, 只留 FOM 最优
        #   b) 真正多型 (石英 vs 方石英; 锐钛矿 vs 金红石; 方解石 vs 文石)
        #      → 旧实现按 (formula, elements) 一刀切会误删, 使 5-x 等含
        #        石英+方石英试样的预期物相无法进入候选。现改为: 多型仅在
        #        解释了实测峰中本组已保留成员解释不到的峰时才保留。
        results = self._dedupe_results(results, peaks, tolerance)

        return results[:top_n]

    def _match_phase_fom(
        self,
        phase: Phase,
        peaks: PeakList,
        tolerance: float,
        obs_range=None,
        scale=None,
        scale_penalty: float = 0.0,
        min_visible_frac: float = 0.0,
        obs_local_mad_k: float = 0.0,
        obs_local_mad_window: float = 5.0,
        po_grid: Optional[tuple] = None,
        po_axis: tuple = (0, 0, 1),
        zero_grid: Optional[tuple] = _FOM_ZERO_GRID,
    ) -> PhaseMatchResult:
        """基于匹配因子 (FoM) 匹配单个物相。

        0.9.11 起统一走 :func:`polyxrd.services.foam.compute_fom`, 与 COD 路径
        同一口径, 三点改进:
          - 一一对应互斥匹配 (密集物相不再抢峰)
          - 强峰加权 + Σw 归一 (消除高角度/多峰天然占优)
          - 未解释实验峰特异性惩罚 + 匹配对强度余弦一致性
        纯金属相额外 ×1.5 惩罚 (单元素金属参考峰少易误匹配)。

        B-3: ``obs_local_mad_k > 0`` 时, 用 :func:`polyxrd.services.foam.local_mad_threshold`
        按 2θ 局部窗口 MAD×k 算每峰噪声阈值, 传入 compute_fom 的
        ``obs_noise_floor`` 过滤特异性项 (强度 < 阈值的峰不计入未解释强度,
        安静区弱峰保留、噪声区假峰剔除)。

        B-4: ``po_grid`` 非空且候选有 hkl 信息时, 对每个 r∈po_grid 做
        March-Dollase 择优取向校正 (:meth:`RietveldRefiner.apply_preferred_orientation`,
        织构轴 = ``po_axis`` 默认 [001]), 用校正后强度算 FoM, 取最优 r
        的 FoM 作为该候选最终分。r=1.0 = 无取向 (与 v2.3 一致)。无 hkl 信息
        的候选跳过 PO 搜索 (用原参考峰表)。

        B-6: ``zero_grid`` 非空时, 对 (PO 校正后的) 参考峰在 dz 网格上做
        per-entry 零点偏移搜索 (仿 Match! 自动零点校正), 取最优 dz 的 FoM。
        默认 None = 不启用 (13 试样消融实测净负, 见 ``_FOM_ZERO_GRID`` 注释)。
        护栏: |dz| ≤ 0.15° 且改善 > ``_FOM_ZERO_IMPROVE_FRAC`` (0.10) 才采用。

        Args:
            phase: 候选物相
            peaks: 实验峰列表
            tolerance: 容差
            obs_local_mad_k: B-3 局部 MAD 倍数, 0 = 关 (默认行为与 v2.3 一致)
            obs_local_mad_window: B-3 局部窗口宽度 (度)
            po_grid: B-4 March-Dollase r 网格 (如 (0.6, 0.8, 1.0, 1.3));
                None = 不启用 PO 搜索
            po_axis: B-4 织构轴方向, 默认 (0,0,1) = c 轴
            zero_grid: B-6 零点偏移网格 (如 (-0.10, -0.05, 0.0, 0.05, 0.10));
                None = 不启用零点搜索

        Returns:
            PhaseMatchResult (score 越低越好)
        """
        reference_peaks = phase.get_reference_peaks()
        total_ref_peaks = len(reference_peaks)
        if total_ref_peaks == 0:
            return PhaseMatchResult(
                phase=phase, score=999.0, matched_peaks=0,
                total_peaks=0, confidence="无参考数据", method="fom"
            )

        obs_tt = [p.two_theta for p in peaks]
        obs_i = [p.intensity for p in peaks]
        obs_noise_floor = None
        if obs_local_mad_k > 0 and len(obs_tt) >= 3:
            from polyxrd.services.foam import local_mad_threshold
            obs_noise_floor = local_mad_threshold(
                obs_tt, obs_i,
                window_deg=float(obs_local_mad_window),
                k=float(obs_local_mad_k),
            )

        # B-4: March-Dollase r 网格搜索, 选最优 r 的 FoM
        # 保守口径 1: 只对参考峰数 ≥ _FOM_PO_MIN_REFS 的密集峰表候选做 PO 搜索
        #   (Muscovite 267 线 / Hornblende 211 线等才需要; 简单峰表相不做)
        # 保守口径 2: 先算 r=1.0 (无取向) 的 FoM, 只在 r≠1.0 的改善 > 5% 时
        #   才采用 —— 避免伪匹配候选在 r 网格上"轻微优化"挤掉真相。
        has_hkl = any(h and any(h) for h, _, _ in reference_peaks)
        if (po_grid and has_hkl
                and total_ref_peaks >= _FOM_PO_MIN_REFS):
            from polyxrd.services.rietveld_refiner import RietveldRefiner
            fom_base = compute_fom(
                obs_tt, obs_i, reference_peaks, tol=tolerance,
                obs_range=obs_range, scale=scale,
                scale_penalty=scale_penalty,
                min_visible_frac=min_visible_frac,
                obs_noise_floor=obs_noise_floor,
            )
            best_fom = fom_base
            best_refs_for_zero = reference_peaks
            for r_val in po_grid:
                r_f = float(r_val)
                if abs(r_f - 1.0) < 1e-6:
                    continue  # 已算 (fom_base)
                corrected_phase = RietveldRefiner.apply_preferred_orientation(
                    phase, direction=tuple(po_axis), r=r_f)
                corrected_refs = corrected_phase.get_reference_peaks()
                fom_r = compute_fom(
                    obs_tt, obs_i, corrected_refs, tol=tolerance,
                    obs_range=obs_range, scale=scale,
                    scale_penalty=scale_penalty,
                    min_visible_frac=min_visible_frac,
                    obs_noise_floor=obs_noise_floor,
                )
                if fom_r.score < best_fom.score * (1.0 - _FOM_PO_IMPROVE_FRAC):
                    best_fom = fom_r
                    best_refs_for_zero = corrected_refs
            fom = best_fom
            refs_for_zero = best_refs_for_zero
        else:
            fom = compute_fom(
                obs_tt,
                obs_i,
                reference_peaks,
                tol=tolerance,
                obs_range=obs_range,
                scale=scale,
                scale_penalty=scale_penalty,
                min_visible_frac=min_visible_frac,
                obs_noise_floor=obs_noise_floor,
            )
            refs_for_zero = reference_peaks

        # B-6: per-entry 零点偏移网格搜索 (在 PO 选出的最佳参考峰上扫 dz)
        # 护栏1: |dz| ≤ 0.15°; 护栏2: 改善 > _FOM_ZERO_IMPROVE_FRAC 才采用。
        best_dz = 0.0
        if zero_grid:
            fom_base = fom
            for dz_val in zero_grid:
                dz = float(dz_val)
                if abs(dz) < 1e-9:
                    continue  # dz=0 已算 (fom_base)
                if abs(dz) > 0.15:
                    continue  # 护栏1: 幅度过大 = 数据质量问题
                fom_dz = compute_fom(
                    obs_tt, obs_i, refs_for_zero, tol=tolerance,
                    obs_range=obs_range, scale=scale,
                    scale_penalty=scale_penalty,
                    min_visible_frac=min_visible_frac,
                    obs_noise_floor=obs_noise_floor,
                    zero_shift=dz,
                )
                if fom_dz.score < fom_base.score * (1.0 - _FOM_ZERO_IMPROVE_FRAC):
                    fom = fom_dz
                    best_dz = dz

        score = float(fom.score)
        # B-7: 关联峰数 < 2 时惩罚 (抑制窄窗口偶然匹配的伪阳性)
        if fom.matched < _FOM_MIN_CORR_PEAKS:
            score *= _FOM_LOW_CORR_PENALTY
        if _is_pure_metal(phase):
            score *= _PURE_METAL_PENALTY
        score = max(score, 0.01)

        return PhaseMatchResult(
            phase=phase,
            score=round(score, 4),
            matched_peaks=fom.matched,
            total_peaks=total_ref_peaks,
            confidence=confidence_from_score(score),
            method="fom",
            zero_shift=best_dz,
        )

    def add_phase(self, phase: Phase) -> None:
        self._phase_database.append(phase)

    def load_custom_database(self, path: str) -> None:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        for phase_data in data.get("phases", []):
            phase = Phase.from_dict(phase_data)
            self._phase_database.append(phase)

    def get_database_info(self) -> dict:
        info = {
            "total_phases": len(self._phase_database),
            "has_reference_db": len(self._reference_data) > 0,
            "reference_count": len(self._reference_data),
            "cod_local_enabled": getattr(self, "_cod_enabled", False),
            "cod_local_ready": getattr(self, "_cod_ready", False),
        }
        db = getattr(self, "_cod_db", None)
        if db is not None:
            info["cod_stats"] = db.stats()
        return info

    # ── 本地 COD 数据库集成 ──────────────────────────────────

    def enable_cod_local(self, cod_db=None) -> None:
        """启用本地 COD 数据库 (索引就绪后调用)。

        - 若索引就绪: identify() 额外对 COD 前 N 条候选做 FOM 匹配，合并结果。
        - identify 参数 use_cod_local=True 时生效 (默认仅内置 + 外部)。

        Args:
            cod_db: 已实例化的 CODLocalDatabase (None 则新建)
        """
        try:
            from polyxrd.services.cod_local import CODLocalDatabase
            self._cod_db = cod_db if cod_db is not None else CODLocalDatabase()
            self._cod_enabled = True
            self._cod_ready = bool(self._cod_db.is_ready())
        except Exception:
            self._cod_db = None
            self._cod_enabled = False
            self._cod_ready = False

    def _search_cod_for_phases(self, peaks, elements,
                               wavelength: float,
                               two_theta_range,
                               top_n_candidates: int = 50,
                               tolerance: float = 0.15):
        """从 COD 索引中筛选候选物相，动态生成 reference_peaks 并计算 FOM。

        策略:
          - 如 elements 有条件，先用元素过滤得到 COD 候选 (最多 top_n_candidates)
          - 对每个候选做 FOM (计算快速，pymatgen 峰生成慢则跳过)
          - 返回 top_n FOM 最好的 PhaseMatchResult
        """
        db = getattr(self, "_cod_db", None)
        if db is None or not db.is_ready():
            return []

        # 1) 按元素和 2θ 初筛 (减少调用 pymatgen 的次数)
        cod_entries = db.search(
            elements=elements,
            limit=max(top_n_candidates, 100),
            parse_ok_only=True,
        )
        if not cod_entries:
            return []

        # 2) 对前 N 条尝试生成 Phase+reference_peaks 并做 FOM
        results = []
        import time as _t
        t0 = _t.time()
        processed = 0
        budget_seconds = 30.0  # 防止长时间阻塞
        for e in cod_entries:
            if processed >= top_n_candidates or (_t.time() - t0) > budget_seconds:
                break
            # 跳过完全没有原子位点或晶胞体积异常的
            if not e.a or not e.b or not e.c or not e.formula:
                continue
            phase = db.get_phase(
                e.cod_id,
                wavelength=wavelength,
                two_theta_range=two_theta_range,
                use_pymatgen_peaks=True,
            )
            if phase is None or not phase.reference_peaks:
                continue
            processed += 1
            match = self._match_phase_fom(phase, peaks, tolerance)
            results.append(match)

        results.sort(key=lambda r: r.score)
        return results[:top_n_candidates]

    def identify_with_cod_local(
        self,
        data: XRDData,
        peaks=None,
        elements: Optional[list[str]] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        cod_candidates: int = 30,
        merge_with_builtin: bool = True,
    ) -> list[PhaseMatchResult]:
        """物相识别: 内置 118 物相 + 本地 COD 扩展。

        Args:
            data: XRD 数据
            peaks: 可选峰列表 (自动检测)
            elements: 已知元素 (大幅降低 COD 候选范围，推荐)
            top_n: 返回候选数
            tolerance: 2θ 容差
            cod_candidates: 最多评估 COD 物相数 (pymatgen 峰计算较慢)
            merge_with_builtin: True → 与内置库结果合并排序; False → 仅 COD
        """
        if peaks is None:
            peaks = default_peak_list(data)

        wavelength = self._config.default_wavelength
        t_min, t_max = self._config.default_two_theta_range
        t_range = (max(t_min, 5.0), min(t_max, 90.0))

        combined: list[PhaseMatchResult] = []
        if merge_with_builtin:
            builtin = self.identify(data, peaks=peaks, elements=elements,
                                    top_n=max(top_n, 10), tolerance=tolerance)
            combined.extend(builtin)

        # COD 部分
        if getattr(self, "_cod_ready", False) or (
            getattr(self, "_cod_db", None) and self._cod_db.is_ready()
        ):
            cod_results = self._search_cod_for_phases(
                peaks=peaks,
                elements=elements,
                wavelength=wavelength,
                two_theta_range=t_range,
                top_n_candidates=cod_candidates,
                tolerance=tolerance,
            )
            combined.extend(cod_results)

        combined.sort(key=lambda r: r.score)
        return combined[:top_n]

    def _rank_candidates(
        self,
        cands: list[dict],
        *,
        fetch,
        make_phase,
        ef,
        data: XRDData,
        peaks: PeakList,
        top_n: int,
        tolerance: float,
        wavelength: float,
    ) -> list[PhaseMatchResult]:
        """预筛候选 → Phase → 统一 FOM 评分 → 排序。

        COD 无机库与用户库**表结构同构**, 预筛之后的这一段完全共用:
          - ``fetch(cod_id)`` → 详情 dict (``get_cod_phase``, 可带外部 conn)
          - ``make_phase(detail, cand, ref_peaks)`` → Phase (两库命名/附带字段不同)

        排序以 Hanawalt 预筛质量为主 (主峰原则/强峰精确率/加权召回),
        FOM 仅作同分决胜 — 否则"参考峰多的密集物相反超少峰真物相"。
        """
        tt_min, tt_max = float(data.two_theta[0]), float(data.two_theta[-1])

        results: list[tuple[dict, PhaseMatchResult]] = []
        for c in cands:
            detail = fetch(c["cod_id"])
            if not detail:
                continue
            ref_peaks = []
            for d_val, i_val in zip(detail.get("peaks_d_list", []),
                                    detail.get("peaks_i_list", [])):
                if d_val <= 0:
                    continue
                sin_theta = wavelength / (2.0 * d_val)
                if sin_theta > 1.0:
                    continue
                tt = 2.0 * float(np.degrees(np.arcsin(sin_theta)))
                if tt_min <= tt <= tt_max:
                    ref_peaks.append(((0, 0, 0), tt, float(i_val)))
            if not ref_peaks:
                continue

            phase = make_phase(detail, c, ref_peaks)
            if ef and not elements_match_filter(
                phase.elements,
                has=ef["has"], maybe=ef["maybe"], exclude=ef["exclude"],
                must_have=ef["must_have"],
            ):
                continue
            results.append((c, self._match_phase_fom(phase, peaks, tolerance)))

        # ── 排序: Hanawalt 预筛质量 × 匹配因子 加权混合 (0.9.11) ──────
        # 旧口径是字典序 (main_peak_match → top_precision → 召回 → FOM),
        # main_peak_match 是 0/1 二值: 多相样品里只有主物相能拿 1, 其余
        # 真物相被整体压到后面。改为加权混合后 13 试样基准 Top-10 24%→29%。
        # 0.9.11 修订: 初版 h 权重 0.30 + fom_good 用固定尺度 1.2, 但多相样品
        # 里几乎所有候选的 FoM 都 > 1.2 → fom_good 饱和为 0 → 退化成 0.3·h,
        # FoM 信息被整体丢弃 (Top-10 15→12)。改用 w=0.10 + exp(-fom/0.8)。
        results.sort(key=lambda it: -cod_rank_score(it))
        return [r for _, r in results[:top_n]]

    def identify_with_cod_inorganics(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        prefilter_limit: int = 100,
        prefilter_tolerance: float = 0.02,
        prefilter_tolerance_rel: float = 0.0,
        prefilter_min_match: int = 3,
        prefilter_max_ref_peaks: int = 40,
    ) -> list[PhaseMatchResult]:
        """物相识别: COD 无机物库 (71,199 物相, 预计算 d-I 峰)。

        流程:
        1. 实验峰 2θ → d 值 (Bragg: d = λ / (2 sinθ))
        2. CIFDatabase.search_cod_by_d_peaks Hanawalt 法预筛候选
           (主峰原则 + 强度加权召回, top prefilter_limit 条)
        3. 候选转 Phase (d→2θ 参考峰), 统一走 _match_phase_fom 评分,
           与内置库同一 FOM 口径 (含纯金属惩罚)

        Args:
            data: XRD 数据
            peaks: 可选峰列表 (自动检测)
            element_filter: 三态元素过滤 (预筛后应用)
            top_n: 返回候选数
            tolerance: 2θ 容差 (FOM 匹配用)
            prefilter_limit: d-I 预筛保留的候选数。预筛排序键 (Hanawalt
                度量) 缺少特异性判据, 是弱判别器; 下游 _match_phase_fom
                才是强判别器。故该值宜偏大 —— 宁可多放候选进来让 FOM
                筛, 也不要在此处把真物相截掉。默认 100 为兼容值。
            prefilter_tolerance: 预筛 d 容差绝对下限 (Å)
            prefilter_tolerance_rel: 预筛 d 容差相对分量 (>0 时实际容差取
                max(abs, rel*d), 使 2θ 窗口近似恒定)
            prefilter_min_match: 预筛最少反向匹配测量峰数
            prefilter_max_ref_peaks: 预筛每物相参与匹配的最大主要峰数
        """
        if peaks is None:
            peaks = default_peak_list(data)

        try:
            from polyxrd.services.cif_database import CIFDatabase
        except Exception:
            return []

        cdb = CIFDatabase(enable_cod_local=False)
        if not cdb.cod_db_available():
            return []

        wavelength = self._config.default_wavelength

        # 1. 实验峰 2θ → d 值
        d_list: list[float] = []
        i_list: list[float] = []
        for p in peaks.peaks:
            sin_theta = np.sin(np.radians(p.two_theta / 2.0))
            if sin_theta <= 1e-6:
                continue
            d_list.append(wavelength / (2.0 * sin_theta))
            i_list.append(float(p.intensity))
        if not d_list:
            return []

        # 2. Hanawalt d-I 预筛 (元素约束下推到扫描层)
        ef = normalize_element_filter(element_filter) if element_filter else None
        # 允许池 = 必有 ∪ 含有 ∪ 可能 (闭环语义: 未勾选元素视为「没有」)
        allowed_pool = set(ef["must_have"]) | set(ef["has"]) | set(ef["maybe"]) if ef else set()
        elements_allowed = allowed_pool if allowed_pool else None
        try:
            cands = cdb.search_cod_by_d_peaks(
                d_list, i_list, tolerance=prefilter_tolerance,
                tolerance_rel=prefilter_tolerance_rel,
                min_match=prefilter_min_match,
                max_ref_peaks=prefilter_max_ref_peaks,
                main_peak_topk=3,
                limit=prefilter_limit,
                elements_allowed=elements_allowed,
            )
        except Exception:
            return []
        if not cands:
            return []

        return self._rank_candidates(
            cands,
            fetch=cdb.get_cod_phase,
            make_phase=lambda d, c, rp: Phase(
                name=f"{d.get('formula', '') or ''} (COD {c['cod_id']})",
                formula=d.get("formula", "") or "",
                space_group=d.get("space_group", ""),
                reference_peaks=rp,
                elements=elements_from_db_formula(d.get("formula", "") or ""),
            ),
            ef=ef, data=data, peaks=peaks, top_n=top_n,
            tolerance=tolerance, wavelength=wavelength,
        )

    def identify_with_user_db(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        prefilter_limit: int = 100,
        prefilter_tolerance: float = 0.02,
        prefilter_tolerance_rel: float = 0.0,
        prefilter_min_match: int = 3,
        prefilter_max_ref_peaks: int = 40,
    ) -> list[PhaseMatchResult]:
        """物相识别: 用户自建库 (``user_phases.sqlite``, v2.6.0)。

        流程与 ``identify_with_cod_inorganics`` 完全一致 (同一套 d-I 预筛 +
        同一套 FOM 排序), 差别只有两点:
          1. 数据源换成用户库只读连接;
          2. 返回的 Phase **带晶胞与全胞原子位点**, 可直接进内置引擎精修
             (用户库条目本来就存了原子坐标, 不必再回库/读 CIF)。
        """
        if peaks is None:
            peaks = default_peak_list(data)

        try:
            from polyxrd.services import user_db
            from polyxrd.services.cif_database import CIFDatabase
        except Exception:
            return []

        conn = user_db.user_conn()
        if conn is None:
            return []

        try:
            cdb = CIFDatabase(enable_cod_local=False)
            wavelength = self._config.default_wavelength

            # 1. 实验峰 2θ → d 值
            d_list: list[float] = []
            i_list: list[float] = []
            for p in peaks.peaks:
                sin_theta = np.sin(np.radians(p.two_theta / 2.0))
                if sin_theta <= 1e-6:
                    continue
                d_list.append(wavelength / (2.0 * sin_theta))
                i_list.append(float(p.intensity))
            if not d_list:
                return []

            # 2. Hanawalt d-I 预筛 (复用 COD 无机库同一实现, 仅换连接)
            ef = normalize_element_filter(element_filter) if element_filter else None
            allowed_pool = (set(ef["must_have"]) | set(ef["has"]) | set(ef["maybe"])
                            if ef else set())
            elements_allowed = allowed_pool if allowed_pool else None
            cands = cdb.search_cod_by_d_peaks(
                d_list, i_list, tolerance=prefilter_tolerance,
                tolerance_rel=prefilter_tolerance_rel,
                min_match=prefilter_min_match,
                max_ref_peaks=prefilter_max_ref_peaks,
                limit=prefilter_limit,
                elements_allowed=elements_allowed,
                conn=conn,
            )
            if not cands:
                return []

            # 3. 候选 → Phase (带晶胞/位点) → FOM 评分
            return self._rank_candidates(
                cands,
                fetch=lambda cid: cdb.get_cod_phase(cid, conn=conn),
                make_phase=self._make_user_phase,
                ef=ef, data=data, peaks=peaks, top_n=top_n,
                tolerance=tolerance, wavelength=wavelength,
            )
        except Exception:  # noqa: BLE001 - 检索失败不该抛到 UI
            return []
        finally:
            conn.close()

    @staticmethod
    def _make_user_phase(detail: dict, cand: dict, ref_peaks: list) -> Phase:
        """用户库候选 → 可直接精修的 Phase (晶胞 + 全胞原子位点)。"""
        from polyxrd.models.phase import LatticeParams
        from polyxrd.services import user_db

        cid = int(cand["cod_id"])
        formula = detail.get("formula", "") or ""
        # 名称保持语言中立 (与 COD 分支的 "(COD 1234567)" 同构), 且 ID 前缀
        # USER- 自带来源信息; 别在这里拼 tr(...) —— Phase 名会被序列化进
        # 项目文件, 存进术语随语言变的名字以后读不出来。
        name = f"{formula} ({user_db.display_id_of(cid)})"
        lattice = LatticeParams(
            a=float(detail.get("cell_a") or 0.0),
            b=float(detail.get("cell_b") or 0.0),
            c=float(detail.get("cell_c") or 0.0),
            alpha=float(detail.get("cell_alpha") or 90.0),
            beta=float(detail.get("cell_beta") or 90.0),
            gamma=float(detail.get("cell_gamma") or 90.0),
        )
        return Phase(
            name=name,
            formula=formula,
            space_group=detail.get("space_group", "") or "",
            lattice=lattice if lattice.a else None,
            atomic_sites=user_db.get_user_atomic_sites(cid),
            reference_peaks=ref_peaks,
            elements=elements_from_db_formula(formula),
            db_id=cid,
        )

    def identify_with_pdf2(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        prefilter_limit: int = 100,
        prefilter_tolerance: float = 0.02,
        prefilter_tolerance_rel: float = 0.0,
        prefilter_min_match: int = 3,
        prefilter_max_ref_peaks: int = 40,
    ) -> list[PhaseMatchResult]:
        """物相识别: PDF2-2004 数据库 (ICDD PDF-2 2004 版)。

        与 identify_with_cod_inorganics 流程完全一致, 唯一区别是
        数据源从 COD 无机物库切换为 PDF2-2004 SQLite 索引。
        用于自用验证: 对照 COD 库结果与 PDF2 商用数据库的差异。

        Args:
            data: XRD 数据
            peaks: 可选峰列表 (自动检测)
            element_filter: 三态元素过滤
            top_n: 返回候选数
            tolerance: 2θ 容差 (FOM 匹配用)
            prefilter_limit: d-I 预筛保留的候选数
            prefilter_tolerance: 预筛 d 容差绝对下限 (Å)
            prefilter_tolerance_rel: 预筛 d 容差相对分量
            prefilter_min_match: 预筛最少反向匹配测量峰数
            prefilter_max_ref_peaks: 预筛每物相参与匹配的最大主要峰数
        """
        if peaks is None:
            peaks = default_peak_list(data)

        try:
            from polyxrd.services.pdf2_database import PDF2Database
        except Exception:
            return []

        pdb = PDF2Database()
        if not pdb.is_available():
            return []

        wavelength = self._config.default_wavelength

        # 1. 实验峰 2θ → d 值
        d_list: list[float] = []
        i_list: list[float] = []
        for p in peaks.peaks:
            sin_theta = np.sin(np.radians(p.two_theta / 2.0))
            if sin_theta <= 1e-6:
                continue
            d_list.append(wavelength / (2.0 * sin_theta))
            i_list.append(float(p.intensity))
        if not d_list:
            return []

        # 2. Hanawalt d-I 预筛
        ef = normalize_element_filter(element_filter) if element_filter else None
        allowed_pool = set(ef["must_have"]) | set(ef["has"]) | set(ef["maybe"]) if ef else set()
        elements_allowed = allowed_pool if allowed_pool else None
        try:
            cands = pdb.search_by_d_peaks(
                d_list, i_list, tolerance=prefilter_tolerance,
                tolerance_rel=prefilter_tolerance_rel,
                min_match=prefilter_min_match,
                max_ref_peaks=prefilter_max_ref_peaks,
                limit=prefilter_limit,
                elements_allowed=elements_allowed,
            )
        except Exception:
            return []
        if not cands:
            return []

        tt_min, tt_max = float(data.two_theta[0]), float(data.two_theta[-1])

        # 3. 候选 → Phase → 统一 FOM 评分
        results: list[tuple[dict, PhaseMatchResult]] = []
        for c in cands:
            detail = pdb.get_phase(c["cod_id"])
            if not detail:
                continue
            ref_peaks = []
            for d_val, i_val in zip(detail.get("peaks_d_list", []),
                                    detail.get("peaks_i_list", [])):
                if d_val <= 0:
                    continue
                sin_theta = wavelength / (2.0 * d_val)
                if sin_theta > 1.0:
                    continue
                tt = 2.0 * float(np.degrees(np.arcsin(sin_theta)))
                if tt_min <= tt <= tt_max:
                    ref_peaks.append(((0, 0, 0), tt, float(i_val)))
            if not ref_peaks:
                continue

            formula = detail.get("formula", "") or ""
            # 名称优先级: 矿物名 (Match! 习惯) > PDF2 主名称 > 化学式。
            # 主名称常见 "Calcium Carbonate Oxide" 这类冗长写法, 矿物名
            # "Calcite" 更贴近检索习惯。
            disp_name = (
                detail.get("mineral") or detail.get("name") or formula
            ).strip()
            phase = Phase(
                name=f"{disp_name} (PDF2 {c['cod_id']})" if disp_name
                else f"PDF2 {c['cod_id']}",
                formula=formula,
                space_group=detail.get("space_group", "") or "",
                lattice=pdb.get_lattice(c["cod_id"]),
                reference_peaks=ref_peaks,
                elements=elements_from_db_formula(formula),
            )
            if ef and not elements_match_filter(
                phase.elements,
                has=ef["has"], maybe=ef["maybe"], exclude=ef["exclude"],
                must_have=ef["must_have"],
            ):
                continue
            results.append((c, self._match_phase_fom(phase, peaks, tolerance)))

        # 排序口径必须与 COD 路径**同一个函数** —— 0.9.11 曾在这里复制了一份
        # 旧口径, 排序一改就会悄悄漂移。PDF2 与 COD 共用 cod_rank_score。
        results.sort(key=lambda it: -cod_rank_score(it))
        return [r for _, r in results[:top_n]]
