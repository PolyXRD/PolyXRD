"""D1 分阶段精修协议 + D2 起点种子化 —— 让"一键精修"真的跑得完。

为什么需要协议层（而不是一个 ``least_squares`` 从头放到尾）
---------------------------------------------------------
Rietveld 的自由度之间**不是平等的**：晶胞错 0.01 Å 造成的峰位偏差，可以被
Caglioti 的 ``x/y`` 完美吸收（把峰变宽就行），于是 LM 会收敛到一个
"Rwp 6%、参数全错"的假极小。真实程序（GSAS-II / FullProf / MAUD）都靠
**分行放开 + 逐行热启动**绕开这一点 —— 见 ``parameters.STAGE_LABELS``。

协议层补的两件事（裸 ``fit(stages=(2, 3))`` 没有）：

1. **逐段回滚**：某一段把 Rwp 弄差了（> ``rollback_tol``）就撤回这一段，
   记 ``rolled_back=True``。理由很实际 —— 加参数**必然**让残差平方和下降，
   所以"Rwp 变差"只可能是优化器跑飞了；而跑飞的那一段若留下，后面全被带偏。
2. **提前收敛**：连续 ``patience`` 段相对改善 < ``converge_tol`` 就停。真实数据
   上阶段 4/5/6 常常只改善 0.01%，白烧时间。

起点种子化（D2）
----------------
自动精修最大的坑是"起点靠手写网格"。观测谱自己就含了峰宽与峰位信息：

* 逐峰 FWHM → 按 ``FWHM² = U·tan²θ + V·tanθ + W`` 最小二乘反解 ``(U,V,W)``；
* 观测峰位 ↔ 计算峰位匹配 → 中位偏差 = 零位偏移；
* SNIP 剥背景 → 峰检测在**弯曲背景**上不至于把背景鼓包当峰。

刻意**不**做"峰强比 → 相分数"种子化：标度本来就在线性层里每轮闭式最优解，
再种一遍只是把同一个数算两次，还会让人误以为它是个需要调的量。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .parameters import STAGE_LABELS
from .problem import FitSummary, PatternProblem, finalize_summary

__all__ = [
    "PeakSeed",
    "ProfileSeed",
    "SeedBundle",
    "StageSpec",
    "STAGE_ORDER",
    "ZeroSeed",
    "DEFAULT_PROTOCOL",
    "PROTOCOLS",
    "find_observed_peaks",
    "resolve_protocol",
    "run_protocol",
    "run_tiered",
    "seed_caglioti",
    "seed_problem",
    "seed_zero",
    "snip_baseline",
]

#: 协议可用的全部阶段编号（累积语义：``stage <= n`` 全放开）
STAGE_ORDER: Tuple[int, ...] = tuple(sorted(STAGE_LABELS))


@dataclass(frozen=True)
class StageSpec:
    """协议里的一段：放开到第 ``stage`` 阶段，跑 ``max_iter`` 步 LM。

    :param stage: 累积放开到第几阶段（见 ``STAGE_LABELS``）
    :param label: 展示名；留空则取 ``STAGE_LABELS[stage]``
    :param max_iter: 本段最多迭代步数
    :param method: 覆盖全局优化器选择（``"auto"`` = 跟随调用方）
    """

    stage: int
    label: str = ""
    max_iter: int = 100
    method: str = "auto"

    def __post_init__(self) -> None:
        if self.stage < 1:
            raise ValueError(f"stage 必须 ≥1，收到 {self.stage}")
        if self.max_iter < 1:
            raise ValueError(f"max_iter 必须 ≥1，收到 {self.max_iter}")
        if not self.label:
            object.__setattr__(
                self, "label",
                STAGE_LABELS.get(self.stage, f"阶段 {self.stage}"))

    def as_dict(self) -> dict:
        return {"stage": self.stage, "label": self.label,
                "max_iter": self.max_iter, "method": self.method}


#: 默认协议：由粗到精、仪器先于样品、全局先于局域。
#:
#: **刻意不含结构自由度（stage 6）**：把 6 个位点的 x/y/z/occ/biso（30 个参数）
#: 在一条实验室谱上一次放开，Hessian 必然秩亏（实测 47 参数秩 14），LM 的步长
#: 被边界投影吃掉、λ 一路涨到 1e8，白烧一百多次评估而 Rwp 一点不动。真实
#: Rietveld 里结构自由度是**用户显式选择**才放的（见 ``"structure"`` 协议）——
#: 这也正是产品分层的分界（``goal.Tier``）。
#:
#: 4（择优）与 5（样品展宽）刻意分成两段：``r`` 与 TCH 的尺寸项都在改「峰强
#: 与峰宽的整体走势」，同时放开会互相抵消出一族等价的假解（实测 Rwp 一样但
#: 尺寸从 120 nm 跑到 20 nm）。
DEFAULT_PROTOCOL: Tuple[StageSpec, ...] = (
    StageSpec(2, max_iter=100),
    StageSpec(3, max_iter=80),
    StageSpec(4, max_iter=40),
    StageSpec(5, max_iter=60),
)

PROTOCOLS: Dict[str, Tuple[StageSpec, ...]] = {
    # 一键（最快）：只定峰位与峰形。日常「先看个数」用，也最不容易跑飞。
    "quick": (StageSpec(2, max_iter=80),
              StageSpec(3, max_iter=60)),
    "default": DEFAULT_PROTOCOL,
    # 只定峰位（晶胞 + 零位），给「先确认晶胞对不对」的场景。
    "position": (StageSpec(2, max_iter=150),),
    # 真 Rietveld：在 default 之上追加结构自由度 + 全参数收尾。
    # 只有结构可信、且确实有足够反射数支撑时才该用。
    "structure": (StageSpec(2, max_iter=80),
                  StageSpec(3, max_iter=60),
                  StageSpec(5, max_iter=60),
                  StageSpec(6, max_iter=120),
                  StageSpec(7, max_iter=150)),
}


# ── 协议解析 ────────────────────────────────────────────────────
def resolve_protocol(
    protocol: Union[str, Sequence, None] = None,
) -> Tuple[StageSpec, ...]:
    """把名字 / 阶段整数列表 / ``StageSpec`` 序列统一成 ``StageSpec`` 元组。"""
    if protocol is None:
        return DEFAULT_PROTOCOL
    if isinstance(protocol, str):
        try:
            return PROTOCOLS[protocol]
        except KeyError:
            raise ValueError(
                f"未知协议 {protocol!r}；可用: {', '.join(sorted(PROTOCOLS))}"
            ) from None
    specs: List[StageSpec] = []
    for item in protocol:
        if isinstance(item, StageSpec):
            specs.append(item)
        elif isinstance(item, (int, np.integer)):
            specs.append(StageSpec(int(item)))
        else:
            raise TypeError(f"协议元素必须是 StageSpec 或 int，收到 {item!r}")
    if not specs:
        raise ValueError("协议不能为空")
    stages = [s.stage for s in specs]
    if any(b < a for a, b in zip(stages, stages[1:])):
        raise ValueError(f"协议阶段必须递增，收到 {stages}")
    return tuple(specs)


# ── 执行 ────────────────────────────────────────────────────────
def run_protocol(
    problem: PatternProblem,
    *,
    protocol: Union[str, Sequence, None] = None,
    method: str = "auto",
    callback=None,
    rollback_tol: float = 0.02,
    converge_tol: float = 1e-3,
    patience: int = 2,
    max_iter_per_stage: Optional[int] = None,
) -> FitSummary:
    """按协议逐段精修（热启动 + 逐段回滚 + 提前收敛）。

    :param problem: 待精修的 ``PatternProblem``（**就地**修改参数）
    :param protocol: 协议名 / 阶段列表 / ``StageSpec`` 序列；``None`` → 默认
    :param method: ``"auto"`` / ``"lm"`` / ``"trf"``
    :param callback: 每段结束回调，收到该段的日志 dict（供 UI 进度条）
    :param rollback_tol: 该段使 Rwp 相对变差超过此比例 → 撤回该段
    :param converge_tol: 相对改善低于此比例视为"没进展"
    :param patience: 连续多少段没进展就提前收工
    :param max_iter_per_stage: 给定时**覆盖**协议里每段的 ``max_iter``

    返回的 ``FitSummary.stages`` 比裸 ``fit()`` 多几个键：``label`` /
    ``rolled_back`` / ``seconds`` / ``Rwp_before``，便于 UI 直接铺表。
    """
    specs = resolve_protocol(protocol)
    log: List[dict] = []
    prev_rwp = math.inf
    last = None
    last_stage: Optional[int] = None
    flat = 0

    for i, spec in enumerate(specs):
        x0 = problem.params.to_vector(spec.stage)
        if x0.size == 0:
            log.append({"stage": spec.stage, "label": spec.label, "n_params": 0,
                        "Rwp": prev_rwp if math.isfinite(prev_rwp) else float("nan"),
                        "GOF": float("nan"), "status": "skipped", "nfev": 0,
                        "rolled_back": False, "seconds": 0.0,
                        "Rwp_before": prev_rwp if math.isfinite(prev_rwp) else float("nan")})
            if callback is not None:
                callback(log[-1])
            continue

        # 每段开始快照：回滚要用它把参数恢复成"这一段之前"的样子
        snap = problem.params.snapshot()
        rwp_before = prev_rwp
        bounds = problem.params.bounds(spec.stage)
        n_iter = int(max_iter_per_stage or spec.max_iter)
        sel = spec.method if spec.method != "auto" else method

        t0 = time.perf_counter()
        from .optimize import minimize_residual

        res = minimize_residual(
            lambda x, _st=spec.stage: problem.residual(x, _st), x0,
            bounds=bounds, method=sel, max_iter=n_iter)

        problem.params.assign(res.x, spec.stage)
        problem.apply()
        problem.invalidate()
        problem.residual(None)
        m = problem.metrics(stage=spec.stage)

        rolled = False
        if (math.isfinite(prev_rwp)
                and m["Rwp"] > prev_rwp * (1.0 + rollback_tol) + 1e-9):
            problem.params.restore(snap)
            problem.apply()
            problem.invalidate()
            problem.residual(None)
            m = problem.metrics(stage=spec.stage)
            rolled = True

        entry = {"stage": spec.stage, "label": spec.label,
                 "n_params": int(x0.size), "Rwp": m["Rwp"], "GOF": m["GOF"],
                 "status": res.status, "nfev": res.nfev,
                 "rolled_back": rolled,
                 "Rwp_before": rwp_before if math.isfinite(rwp_before) else float("nan"),
                 "seconds": round(time.perf_counter() - t0, 3)}
        log.append(entry)
        if callback is not None:
            callback(entry)

        if rolled:
            flat += 1
        else:
            drop = ((prev_rwp - m["Rwp"]) / max(prev_rwp, 1e-12)
                    if math.isfinite(prev_rwp) else 1.0)
            flat = flat + 1 if (math.isfinite(prev_rwp) and drop < converge_tol) else 0
            prev_rwp = m["Rwp"]
            last = res
            last_stage = spec.stage

        if flat >= patience and i < len(specs) - 1:
            break

    if last is None:
        # 一段都没真正跑（全 skipped 或全回滚）：用当前参数算一次残差即可
        r = problem.residual(None)
        from .optimize import FitResult

        last = FitResult(x=np.zeros(0), cost=0.5 * float(r @ r), resid=r,
                         n_data=r.size, method="none")
    return finalize_summary(problem, last, log, last_stage)


def run_tiered(
    problem: PatternProblem,
    *,
    tier=None,
    protocol: Union[str, Sequence, None] = None,
    seed: bool = True,
    method: str = "auto",
    callback=None,
    max_iter_per_stage: Optional[int] = None,
) -> FitSummary:
    """**一键入口**：自动定档 → 自动选协议 → 种子化 → 跑完 → 交报告。

    这是方案 §2「层 3 易用层」的最小可用形态，典型用法::

        summary = run_tiered(prob)
        print(build_report(prob, summary).text())

    定档规则见 ``goal.classify_tier``：有位点且结构自由度会被释放 → ``structure``
    协议；否则 → ``default``（峰位 → 峰形 → 择优 → 样品展宽，结构固定）。

    ``seed=True`` 会用观测谱给峰宽曲线与零位一个起点（D2）。合成数据上它把
    起点 Rwp 从 59.8% 拉到 57.8%、省掉若干次无效迭代；真实谱上收益更大，
    但如果观测谱里主相峰太弱导致峰检测失败，``SeedBundle.notes`` 会说明回退。
    """
    from .goal import Tier, classify_tier, protocol_for_tier

    if tier is None:
        # 未指定档位 → 按**默认协议跑到哪一阶段**判档。默认协议止步于样品展宽，
        # 所以有位点的样品落在 Le Bail 级；想进真 Rietveld 必须显式给
        # ``tier=Tier.RIETVELD``（或自己传 ``protocol="structure"``）。
        # 这里不能用 ``classify_tier(problem)``（stage=None 会把"建册但没跑"的
        # 结构自由度当成已释放，直接把一次结构固定的精修报成真 Rietveld）。
        tier = classify_tier(problem,
                             stage=max(s.stage for s in DEFAULT_PROTOCOL))
    else:
        tier = Tier(tier)
    if protocol is None:
        protocol = protocol_for_tier(tier)
    if seed:
        seed_problem(problem, apply=True)
    return run_protocol(problem, protocol=protocol, method=method,
                        callback=callback,
                        max_iter_per_stage=max_iter_per_stage)


# ── D2 起点种子化 ───────────────────────────────────────────────
@dataclass(frozen=True)
class PeakSeed:
    """一个观测峰的轻量描述（不依赖任何峰拟合库）。"""

    two_theta: float
    height: float
    fwhm: float

    def as_dict(self) -> dict:
        return {"two_theta": self.two_theta, "height": self.height,
                "fwhm": self.fwhm}


@dataclass(frozen=True)
class ProfileSeed:
    """Caglioti 起点。``ok=False`` 表示只定了常数项 ``W``。"""

    u: float
    v: float
    w: float
    fwhm: float
    n_peaks: int = 0
    ok: bool = False
    note: str = ""

    def as_dict(self) -> dict:
        return {"u": self.u, "v": self.v, "w": self.w, "fwhm": self.fwhm,
                "n_peaks": self.n_peaks, "ok": self.ok, "note": self.note}


@dataclass
class SeedBundle:
    """一次起点种子化的产物，可回显也可回灌到 ``PatternProblem``。"""

    peaks: List[PeakSeed] = field(default_factory=list)
    profile: Optional[ProfileSeed] = None
    zero: float = 0.0
    zero_tilt: float = 0.0
    zero_pairs: int = 0
    notes: List[str] = field(default_factory=list)

    def apply(self, problem: PatternProblem) -> List[str]:
        """写进参数书（``inst.zero`` / ``inst.u|v|w``），返回实际生效的说明。"""
        applied: List[str] = []
        if self.profile is not None:
            for tag, val in (("u", self.profile.u), ("v", self.profile.v),
                             ("w", self.profile.w)):
                name = f"inst.{tag}"
                if name not in problem.params:
                    continue
                before = float(problem.params.get(name))
                problem.params.set(name, val)
                after = float(problem.params.get(name))
                applied.append(f"{name}: {before:.4g} → {after:.4g}")
                if abs(after - float(val)) > 1e-12:
                    applied.append(f"{name} 被边界裁到 {after:.4g}")
        if self.zero and "inst.zero" in problem.params:
            before = float(problem.params.get("inst.zero"))
            problem.params.set("inst.zero", self.zero)
            after = float(problem.params.get("inst.zero"))
            applied.append(f"inst.zero: {before:.4g} → {after:.4g}")
        problem.apply()
        problem.invalidate()
        return applied

    def as_dict(self) -> dict:
        return {"n_peaks": len(self.peaks),
                "profile": self.profile.as_dict() if self.profile else None,
                "zero": self.zero, "zero_tilt": self.zero_tilt,
                "zero_pairs": self.zero_pairs,
                "notes": list(self.notes)}


def _local_step(x: np.ndarray) -> float:
    """网格步长（中位数，抗个别缺测点）。"""
    d = np.diff(np.asarray(x, dtype=float))
    d = d[d > 0]
    return float(np.median(d)) if d.size else 0.0


def snip_baseline(
    two_theta,
    y,
    *,
    window_deg: float = 5.0,
    log_scale: bool = True,
) -> np.ndarray:
    """SNIP 剥背景（Ryan et al. 1988）—— 弯曲背景下的峰检测前提。

    做法是**从大窗口到小窗口**做迭代下限滤波::

        v_i ← min(v_i, (v_{i−p} + v_{i+p})/2),  p = p_max … 1

    之所以要在 ``log-log-sqrt`` 域里做：线性域里"减半"对强峰和弱峰的意义完全
    不同，强峰的肩部会把弱峰整个吃掉；对数域里这一步等价于"取几何平均的
    下限"，与峰的绝对强度无关。

    纯索引步长实现（假定网格近似均匀）—— 实测 0.01~0.05° 步长的实验室谱上，
    与按角度精确重采样相比基线差异 < 0.5%，不值得为它引入插值开销。

    :param window_deg: 最大裁剪窗口（度）；应为最强峰 FWHM 的 2~3 倍以上
    """
    x = np.asarray(two_theta, dtype=float).reshape(-1)
    yy = np.maximum(np.asarray(y, dtype=float).reshape(-1), 0.0)
    n = yy.size
    if n < 5 or x.size != n:
        return yy.copy()
    step = _local_step(x) or 1.0
    p_max = int(min(max(1, n // 2 - 1), round(window_deg / step / 2.0)))

    if log_scale:
        v = np.log(np.log(np.sqrt(yy + 1.0) + 1.0) + 1.0)
    else:
        v = yy.copy()

    for p in range(p_max, 0, -1):
        if n <= 2 * p:
            continue
        v[p:n - p] = np.minimum(v[p:n - p], 0.5 * (v[:n - 2 * p] + v[2 * p:]))

    if not log_scale:
        return np.minimum(v, yy)
    # 反变换 y = (exp(exp(v)−1) − 1)² − 1，clamp 防溢出（v 实际 < ~3）
    inner = np.exp(np.clip(np.exp(np.clip(v, 0.0, 30.0)) - 1.0, 0.0, 30.0)) - 1.0
    return np.maximum(np.minimum(inner ** 2 - 1.0, yy), 0.0)


def _crossing(x: np.ndarray, y: np.ndarray, i_a: int, i_b: int,
              level: float) -> float:
    """``y = level`` 在 ``(i_a, i_b)`` 上的线性插值交点（夹在两点之间）。"""
    ya, yb = float(y[i_a]), float(y[i_b])
    if yb == ya:
        return float(x[i_b])
    frac = float(np.clip((level - ya) / (yb - ya), 0.0, 1.0))
    return float(x[i_a] + frac * (x[i_b] - x[i_a]))


def find_observed_peaks(
    two_theta,
    y,
    *,
    max_peaks: int = 40,
    snr: float = 5.0,
    fwhm_range: Tuple[float, float] = (0.01, 3.0),
    baseline: str = "median",
    baseline_window_deg: float = 2.0,
) -> List[PeakSeed]:
    """轻量峰检测：中值/SNIP 扣背景 → ``k·σ`` 阈值找局部极大 → 半高宽扫描。

    刻意**不用**重峰查找器（``PeakFinder`` 的阈值是相对 Imax，背景高于阈值时
    会把噪声全判成峰 —— 实测合成数据返回 120 个假峰、FWHM 10.7°），也不用
    物相识别那条高精度链路（个别试样 30~40 s）。这里是毫秒级且背景鲁棒。

    :param max_peaks: 只保留最强若干个（抗噪，也给下游省时间）
    :param snr: 阈值倍数（``σ`` 取残差 MAD 鲁棒估计，不是标准差 —— 峰本身
        会把标准差抬高一个量级）
    """
    x = np.asarray(two_theta, dtype=float).reshape(-1)
    yy = np.asarray(y, dtype=float).reshape(-1)
    if x.size != yy.size or x.size < 20:
        return []
    step = _local_step(x)
    if step <= 0:
        return []

    if baseline == "snip":
        bg = snip_baseline(x, yy, window_deg=2.0 * baseline_window_deg)
    else:
        from scipy.ndimage import median_filter

        win = max(5, int(round(baseline_window_deg / step)) | 1)
        bg = median_filter(yy, size=win, mode="nearest")
    ys = yy - bg

    sigma = 1.4826 * float(np.median(np.abs(ys - np.median(ys))))
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = max(1.0, 0.01 * float(np.max(ys)))
    thr = max(snr * sigma, 0.02 * float(np.max(ys)))

    idx = np.where((ys[1:-1] > ys[:-2]) & (ys[1:-1] >= ys[2:])
                   & (ys[1:-1] > thr))[0] + 1
    if idx.size == 0:
        return []
    if idx.size > max_peaks:
        idx = idx[np.argsort(ys[idx])[-max_peaks:]]

    lo_w, hi_w = fwhm_range
    out: List[PeakSeed] = []
    n = ys.size
    for i in idx:
        i = int(i)
        if ys[i] <= 0:
            continue
        half = 0.5 * float(ys[i])
        lo = i
        while lo > 0 and ys[lo] > half:
            lo -= 1
        hi = i
        while hi < n - 1 and ys[hi] > half:
            hi += 1
        if lo >= i or hi <= i:
            continue
        x_lo = _crossing(x, ys, lo, lo + 1, half)
        x_hi = _crossing(x, ys, hi - 1, hi, half)
        fw = float(x_hi - x_lo)
        if lo_w < fw < hi_w:
            out.append(PeakSeed(float(x[i]), float(ys[i]), fw))
    out.sort(key=lambda p: p.two_theta)
    return out


def seed_caglioti(
    peaks: Sequence[PeakSeed],
    *,
    fwhm_range: Tuple[float, float] = (0.02, 3.0),
    pattern_range: Optional[Tuple[float, float]] = None,
    min_height_ratio: float = 0.03,
    u_bound: float = 1.0,
    v_bound: float = 1.0,
    w_max: float = 1.0,
) -> ProfileSeed:
    """逐峰 FWHM → Caglioti ``(U, V, W)`` 最小二乘起点。

    反解 ``FWHM² = U·tan²θ + V·tanθ + W``（θ = 2θ/2）。三点起解，少于三点
    只定常数项 ``W = FWHM²``（``u=v=0``），并标记 ``ok=False``。

    三个刻意的处理（都是被实测打出来的）：

    1. **按峰高加权**：弱峰的半高宽根本测不准（背景与邻峰把肩部吃掉），等权
       最小二乘会让一堆弱峰把 ``U`` 拽到荒唐值。
    2. **丢掉过弱的峰**（``< min_height_ratio·max``）：同上。
    3. **反解值必须落在参数书允许的域内**（``0 < W``、``|U|,|V| ≤ 1``）。
       这一条不是洁癖：``ProblemProblem` 的 ``inst.w`` 下界是 ``1e-9``，若种子
       给 ``W=-0.0103``，``ParameterSet.set`` 会把它悄悄夹到 1e-9，而 ``U/V``
       照旧保留 —— 于是外推到低角得到 ``FWHM=0.20°`` 而真值 0.13°，起点比不给
       还糟（实测 Rwp 从 6.9% 劣化到 19%）。宁可退回 ``u=v=0, W=median²``。

    :param pattern_range: 抛物线必须**在整个谱范围**上处于合理区间（不只是观测
        峰覆盖的角域），否则外推段会给出负 ``FWHM²``
    """
    lo, hi = fwhm_range
    pts = [(float(p.two_theta), float(p.fwhm), float(p.height))
           for p in peaks if lo <= p.fwhm <= hi]
    if not pts:
        return ProfileSeed(0.0, 0.0, 0.05 * 0.05, 0.0, 0, False,
                           "无可用峰，回落 w=0.0025")

    hmax = max(p[2] for p in pts)
    strong = [p for p in pts if p[2] >= min_height_ratio * hmax] or pts
    tth = np.asarray([p[0] for p in strong], dtype=float)
    fw = np.asarray([p[1] for p in strong], dtype=float)
    hh = np.asarray([p[2] for p in strong], dtype=float)
    med = float(np.median(fw))
    fallback = ProfileSeed(0.0, 0.0, med * med, med, int(tth.size), False, "")

    if tth.size < 3:
        return ProfileSeed(0.0, 0.0, med * med, med, int(tth.size), False,
                           f"仅 {tth.size} 个峰，只定常数项 W")

    tan_t = np.tan(np.radians(tth / 2.0))
    A = np.column_stack([tan_t * tan_t, tan_t, np.ones_like(tan_t)])
    wgt = np.sqrt(hh / max(hmax, 1e-30))          # 按峰高的平方根加权
    try:
        sol, *_ = np.linalg.lstsq(A * wgt[:, None], fw * fw * wgt, rcond=None)
    except np.linalg.LinAlgError:  # pragma: no cover
        return ProfileSeed(fallback.u, fallback.v, fallback.w, med,
                           int(tth.size), False, "Caglioti 反解失败，只定常数项 W")
    u, v, w = float(sol[0]), float(sol[1]), float(sol[2])

    if not (math.isfinite(w) and 0.0 < w <= w_max):
        return ProfileSeed(0.0, 0.0, med * med, med, int(tth.size), False,
                           f"反解 W={w:.4g} 落在参数域外，只定常数项 W")
    if abs(u) > u_bound or abs(v) > v_bound:
        return ProfileSeed(0.0, 0.0, med * med, med, int(tth.size), False,
                           f"反解 U={u:.4g}/V={v:.4g} 超参数域，只定常数项 W")

    t0, t1 = pattern_range if pattern_range else (float(tth.min()),
                                                  float(tth.max()))
    grid = np.linspace(min(t0, float(tth.min())), max(t1, float(tth.max())), 96)
    tg = np.tan(np.radians(grid / 2.0))
    pred = u * tg * tg + v * tg + w
    if (not np.all(np.isfinite(pred))
            or pred.min() < lo * lo or pred.max() > hi * hi):
        return ProfileSeed(0.0, 0.0, med * med, med, int(tth.size), False,
                           "Caglioti 抛物线越界（外推失控），只定常数项 W")
    return ProfileSeed(u, v, w, med, int(tth.size), True, "")


@dataclass(frozen=True)
class ZeroSeed:
    """零位起点，以及"看起来像零位其实是晶胞偏了"的那一部分。

    模型里 ``2θ_obs = 2θ_calc + z + tilt·tanθ``：
    ``z`` 是仪器零位（常数项），``tilt`` 是**晶胞尺度偏差的等价量**
    （``Δd/d = −tilt/2``，单位：度/单位 tanθ）。只取截距 ``z`` 做零位起点，
    把 ``tilt`` 留给晶胞阶段 —— 否则会用一个假的零位去补偿错的晶胞。
    """

    shift: float = 0.0
    tilt: float = 0.0
    n_pairs: int = 0

    def as_dict(self) -> dict:
        return {"shift": self.shift, "tilt": self.tilt,
                "n_pairs": self.n_pairs}

    @property
    def cell_scale_hint(self) -> float:
        """等价晶胞相对偏差 ``Δd/d``（正 = 计算用的晶胞偏大）。"""
        return -0.5 * math.radians(self.tilt)


def seed_zero(
    observed_centers: Sequence[float],
    calculated_centers: Sequence[float],
    *,
    max_shift: float = 0.6,
    min_pairs: int = 3,
    passes: int = 3,
    max_two_theta: float = 45.0,
) -> ZeroSeed:
    """观测峰位 ↔ 计算峰位匹配 → 分离出零位起点。

    **为什么不能直接取中位偏差**：晶胞错 0.3% 时，峰位偏差随 ``tanθ`` 单调
    增长（20° 处 −0.06°、60° 处 −0.19°），中位数 ≈ −0.1°；把它当零位，等于
    用一个假零位去补偿错的晶胞，后面峰位阶段就在两个错误之间找平衡。

    **算法**（两参数不动点迭代，不是「减中位数再拟合」）：

    1. 用当前模型 ``pred = z + tilt·tanθ`` 把观测峰搬到计算峰附近再匹配；
    2. 匹配残差 ``r_i = (obs_i − pred_i) − cal[匹配到]`` 正好是 ``(z*, tilt*)``
       相对 ``(z, tilt)`` 的**增量**，对 ``[1, tanθ]`` 再拟合一组增量并累加；
    3. 迭代 ``passes`` 次（初值 0 → 第一次就给出主干，之后只是确认）。

    关键在**别先减中位数**：真偏移 0.2° 时最近邻会把残差压到「半个峰距」以内，
    减完中位数后剩下的东西与真实对应关系无关，斜率信息就被抹掉了（实测斜率
    从应有的 0.33 掉到 0.04，零位反而被拉走 0.03°）。

    **为什么只匹配到 ``max_two_theta``**：高角峰距 0.15~0.3°，与晶胞偏差造成的
    0.25° 位移同量级，最近邻必然配错一批（实测配错后 ``tilt`` 从 +0.33 翻成
    −0.03、零位从 0 漂到 0.17°）。限制在 45° 以内，峰距 ≫ 位移，匹配无歧义：
    实测「零位 0 / 0.15°」两种情形的估计分别是 0.001° / 0.176°（误差 ≤0.03°）。

    代价是 ``tilt`` 只有 12~31 对峰支撑、会高估约 1.6 倍，所以它只当**提示**
    用（"疑似晶胞偏 x%"，交给晶胞阶段），绝不写进零位。
    """
    obs = np.asarray(observed_centers, dtype=float).reshape(-1)
    cal = np.sort(np.asarray(calculated_centers, dtype=float).reshape(-1))
    if obs.size == 0 or cal.size == 0:
        return ZeroSeed()

    if math.isfinite(max_two_theta) and max_two_theta > 0:
        near = obs[obs <= max_two_theta]
        if near.size >= min_pairs:
            obs = near

    if cal.size == 1:
        d = obs - cal[0]
        keep = np.abs(d) <= max_shift
        return (ZeroSeed(float(np.median(d[keep])), 0.0, int(np.count_nonzero(keep)))
                if np.count_nonzero(keep) >= min_pairs else ZeroSeed())

    tan_t = np.tan(np.radians(obs / 2.0))
    z, tilt = 0.0, 0.0
    n_pairs = 0
    for _ in range(max(1, passes)):
        target = obs - (z + tilt * tan_t)
        j = np.searchsorted(cal, target)
        j = np.clip(j, 1, cal.size - 1)
        left, right = cal[j - 1], cal[j]
        pick = np.where(np.abs(target - left) <= np.abs(target - right),
                        j - 1, j)
        resid = target - cal[pick]
        keep = np.abs(resid) <= max_shift
        n_pairs = int(np.count_nonzero(keep))
        if n_pairs < min_pairs:
            return ZeroSeed()
        A = np.column_stack([np.ones(n_pairs), tan_t[keep]])
        try:
            step, *_ = np.linalg.lstsq(A, resid[keep], rcond=None)
        except np.linalg.LinAlgError:  # pragma: no cover
            break
        if not np.all(np.isfinite(step)):
            break
        z += float(step[0])
        tilt += float(step[1])

    if not math.isfinite(z):
        z, tilt = 0.0, 0.0
    return ZeroSeed(float(np.clip(z, -1.0, 1.0)), float(tilt), n_pairs)


def seed_problem(
    problem: PatternProblem,
    *,
    peaks: Optional[Sequence[PeakSeed]] = None,
    use_profile: bool = True,
    use_zero: bool = True,
    max_peaks: int = 40,
    snr: float = 5.0,
    baseline: str = "median",
    apply: bool = False,
) -> SeedBundle:
    """从观测谱给出全部起点（峰宽曲线 / 零位），可选直接写回。

    :param apply: True → 直接 ``bundle.apply(problem)`` 后返回
    """
    peaks = list(peaks) if peaks is not None else find_observed_peaks(
        problem.two_theta, problem.y_obs, max_peaks=max_peaks, snr=snr,
        baseline=baseline)
    notes: List[str] = []
    if not peaks:
        notes.append("未检出峰：峰宽/零位起点保持原值")

    prof = None
    if use_profile:
        tmin = float(problem.two_theta[0])
        tmax = float(problem.two_theta[-1])
        prof = seed_caglioti(peaks, pattern_range=(tmin, tmax))
        notes.append(
            f"峰宽起点：U={prof.u:.4g} V={prof.v:.4g} W={prof.w:.4g}"
            f"（{prof.n_peaks} 峰，{'完整 Caglioti' if prof.ok else prof.note}）")

    zero = ZeroSeed()
    if use_zero and peaks:
        tmin = float(problem.two_theta[0])
        tmax = float(problem.two_theta[-1])
        centers = []
        for ph in problem.phases:
            ph.ensure_table((tmin, tmax), (problem.wavelength,))
            centers.append(np.asarray(ph.table.two_theta, dtype=float))
        cal = np.concatenate(centers) if centers else np.zeros(0)
        zero = seed_zero([p.two_theta for p in peaks], cal)
        notes.append(f"零位起点：{zero.shift:+.4f}°（匹配 {zero.n_pairs} 对峰）")
        if zero.n_pairs and abs(zero.tilt) > 1e-3:
            notes.append(
                f"峰位另有 {zero.tilt:+.3f}°/tanθ 的线性偏差"
                f"（疑似晶胞偏 {100 * zero.cell_scale_hint:+.2f}%，仅供参考），"
                "交给晶胞阶段处理，不并入零位")

    bundle = SeedBundle(peaks=peaks, profile=prof, zero=zero.shift,
                        zero_tilt=zero.tilt, zero_pairs=zero.n_pairs,
                        notes=notes)
    if apply:
        bundle.notes.extend(bundle.apply(problem))
    return bundle
