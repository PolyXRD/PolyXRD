"""WPSM — Whole Pattern Search Match（全谱拟合检索）。

v3.0.0 新增。定位: **检索阶段的低自由度全谱拟合排序**, 与峰表 FoM 并列的一种
可选判据, 不是精修 (不碰原子坐标/占位/温度因子)。

原理
----
对每条候选相, 由其 d–I 参考峰按实测 2θ 网格合成理论谱, 在**受限**参数集下对
**原始谱**做 Poisson 加权最小二乘拟合, 用 Rwp 排序:

    y_calc(x) = scale · Σ_i I_i · pV(x − (2θ_i + shift − Δ·(360/π)·tanθ_i); H_i, η)
                + (bg0 + bg1·t + bg2·t²),   t = x − x_mid
    H_i² = U tan²θ_i + V tanθ_i + W            (Caglioti; caglioti=False 时 H 为常数)
    Rwp  = sqrt( Σ w_i (y_i − y_c,i)² / Σ w_i y_i² ),   w_i = 1/y_i
    FoM  = exp(−Rwp / σ)

与 XinMatch FPFM 的四条实证结论对齐 (详见 docs/v3.0.0-WPSM-全谱拟合检索评估与
落地方案.md):

1. **背底吸收进拟合内部** —— bg0/bg1/bg2 是自由参数, 不预先扣背底;
2. **Caglioti U/V/W** —— 峰宽随 2θ 变化, 而非单一常数 FWHM;
3. **cell_delta 与 shift 可辨识** —— 前者 2θ 签名 ∝ tanθ, 后者是常数;
4. **预筛 top-N + 全谱精排** —— 由调用方预筛, 本模块只做精排。

与 FPFM 的两点**有意偏离** (均可 ablation, 见 ``WpsmConfig``):

- **D1 背底边界收紧**: FPFM 给 bg1/bg2 的边界是 ±y_max, 与 t、t² 相乘后可让背底
  在边缘摆到 ~10³·y_max。WPSM 默认按 ``±y_max/half^k`` 缩放
  (``bg_bound_mode="scaled"``), 使背底多项式在扫描边缘的摆幅不超过 ~y_max ——
  直接针对"错误候选靠调背底虚低 Rwp"这一已知陷阱。``"raw"`` 退回 FPFM 口径。
- **D2 复用精修引擎的谱合成**: 理论谱由 ``phase_display.spectrum_from_refs``
  生成 (面积归一 pV + Caglioti + 可选低角不对称 + 窗口化截断), 与 Rietveld
  精修**逐位同源**。代价是每次评估多一次 Python 级逐峰循环; 收益是"检索给出的
  Rwp"与"精修给出的 Rwp"可直接比较, 且峰形语义在全软件内唯一。

注意 **η 语义与 FPFM 相反**: 本模块沿用 PolyXRD 口径, ``eta`` 是**高斯**分量
占比 (FPFM 的 eta 是洛伦兹占比)。初值 0.5、边界 (0.05, 0.95) 对称, 故数值起点
一致, 仅解释相反。

不做的三件事 (本版明确范围外):
  - March-Dollase 择优取向 —— 需要 hkl, 而 COD 无机库/PDF2/用户库的 phases 表
    没有 hkl (FPFM 自身也默认关闭 march_po);
  - 多相联合拟合 —— 单相拟合已足够排序;
  - 非晶/宽化相的专门建模 —— 由 Caglioti 宽度上界吸收。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

import numpy as np
from scipy.optimize import least_squares

# 一阶 Bragg 展开: d → d(1+Δ) 时 Δ(2θ) = −Δ·(360/π)·tanθ  (度)
_CELL_TTH_FACTOR = 360.0 / math.pi

# Kα2/Kα1 波长比 (Cu: 1.54443 / 1.54056)。与
# RietveldRefiner._expand_ka2_satellites 的 alpha2_ratio 默认值一致。
_KA2_ALPHA2_RATIO = 1.00249


@dataclass
class WpsmConfig:
    """WPSM 精排参数与边界。

    初值/边界照搬 FPFM 决策表, 随后按 13 试样消融定参 (红线: 先消融后调参)。
    """

    # ── 两阶段 ──
    #: 精排候选数上限 (由调用方预筛后传入)。FPFM 决策表初值为 150;
    #: PolyXRD 13 试样实测 150 **更差且更慢** (B 级 top10 45→42, Rwp 动态
    #: 范围被大量劣质候选压缩), 故收口为 100 —— 与
    #: phase_identifier._WPSM_PRESCREEN 一致。
    prescreen_top_n: int = 100
    top_n: int = 20                # 输出候选数

    # ── 峰位 ──
    shift_bound: float = 0.3       # 零点位移边界 (°)
    cell_refine: bool = True       # 是否精修 cell_delta
    cell_bound: float = 0.005      # |Δ| 上界 (相对晶胞缩放)

    # ── 峰形 ──
    fwhm_init: float = 0.2         # 单宽模型初值 / Caglioti 定标角处的目标宽度
    fwhm_bounds: tuple = (0.08, 0.6)
    eta_init: float = 0.5          # 高斯分量占比
    eta_bounds: tuple = (0.05, 0.95)
    caglioti: bool = True
    # U/V/W 边界按 H² = U tan²θ + V tanθ + W 反推:
    #   W 下界 0.0025 → H ≥ 0.05°; W 上界 0.36 → H ≤ 0.6° (tanθ=0 处)
    caglioti_u_bounds: tuple = (-0.05, 0.20)
    caglioti_v_bounds: tuple = (-0.20, 0.20)
    caglioti_w_bounds: tuple = (0.0025, 0.36)
    caglioti_u_init: float = 0.006
    caglioti_v_init: float = -0.004
    asymmetry: float = 0.0         # 低角不对称 (split-PV), 0 = 关

    # ── 背底 ──
    bg_order: int = 2              # 二次多项式 (固定, 不做高阶)
    bg_bound_mode: str = "scaled"  # "scaled" (D1 收紧) | "raw" (FPFM 口径)
    bg_bound_pad: float = 1.0      # scaled 边界的放宽倍数

    # ── 谱合成 ──
    cutoff_fwhm: float = 12.0      # 逐峰截断半窗 (FWHM 倍数)
    ka2: bool = True               # Kα1/Kα2 双线
    ka2_intensity_ratio: float = 0.5

    # ── 判据 ──
    fom_sigma: float = 0.25        # FoM = exp(−Rwp/σ)
    #: 计分域。``"global"`` = 全谱 (FPFM 口径); ``"window"`` = 只在候选自身
    #: 反射的局部窗口内计分。
    #: **为什么需要 window**: 全局 Rwp 衡量的是"整个谱还剩下多少没解释",
    #: 多相样品里单相拟合必然剩 ~60-85%, 于是 Rwp 主要由"该相含量多少"决定
    #: 而非"该相配不配" —— 3-1 实测: 主相 Zincite Rwp 37% / 1.4% Corundum
    #: 81.5% / 0.6% Fluorite 81.8%, 真值微量相从第 2、3 名掉到 7、16 名。
    #: 这正是公开文献列出的 Rwp 缺陷之二 (偏向强散射相)。窗口域把"别处没
    #: 解释"排除, 判据回到"我声称有峰的地方拟合得多好"。
    score_domain: str = "global"
    score_half_deg: float = 1.5    # 窗口半宽下限 (度); 实际取 max(此值, n_sigma×H_i)
    score_n_fwhm: float = 3.0      # 窗口半宽的 FWHM 倍数
    #: 计分方式。``"rwp"`` = exp(−Rwp/σ); ``"delta"`` = 1 − Rwp/Rwp_bg,
    #: 即"扣掉候选峰后同一域内的残差"与"含候选峰的残差"之比 —— 按候选自身
    #: 的**局部**信号水平归一, 进一步抹平含量差异 (文献里"ΔRwp"口径的
    #: 局部化版本)。
    score_mode: str = "rwp"

    # ── 求解器 ──
    max_nfev: int = 60
    xtol: float = 1e-6
    ftol: float = 1e-8


@dataclass
class WpsmFit:
    """单候选的 WPSM 拟合结果。"""

    key: object = None             # 调用方传入的候选标识 (原样带回)
    scale: float = 0.0
    shift_deg: float = 0.0
    fwhm: float = 0.0              # 定标角处的代表宽度 (Caglioti 开启时)
    eta: float = 0.0
    bg0: float = 0.0
    bg1: float = 0.0
    bg2: float = 0.0
    #: Caglioti U/V/W (deg²)。单宽模型时 U=V=0、W=fwhm² (恒等编码 H ≡ fwhm)。
    u: float = 0.0
    v: float = 0.0
    w: float = 0.0
    cell_delta: float = 0.0
    rwp: float = float("inf")
    rexp: float = float("inf")
    gof: float = float("inf")
    fom: float = 0.0
    #: 失败原因 (空串 = 成功)。发散/无峰等退化情形填此项而非抛异常。
    reason: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.reason


# --------------------------------------------------------------------------- #
# 判据
# --------------------------------------------------------------------------- #
def compute_rwp(
    observed,
    calculated,
    n_params: int = 0,
    mask=None,
) -> tuple[float, float, float]:
    """(Rwp, Rexp, GOF) —— Poisson 加权, 只取 y_obs > 0 的点。

    ``w_i = 1/y_i`` 故 ``Σ w_i y_i² = Σ y_i``, 于是
    ``Rexp = sqrt(N/Σ y_i)``。

    Args:
        n_params: 参与精修的参数个数 P。``Rexp`` 按 IUCr CIF 词典口径
            ``sqrt((N−P)/Σ w y²)`` 计算; 传 0 则为 FPFM 口径
            (``sqrt(N/Σ w y²)``), 与 XinMatch 数值可比。
        mask: 可选的**域掩码** (bool 数组, 与 y 同长)。给定后只在该域内
            计分 (再与 ``y > 0`` 取交集) —— 用于 ``score_domain="window"``
            的局部判据, 把"别处解释不了"排除在计分之外。

    Returns:
        ``(inf, inf, inf)`` 当无正强度点或分母为 0。
    """
    y = np.asarray(observed, dtype=np.float64)
    yc = np.asarray(calculated, dtype=np.float64)
    mask = (y > 0.0) if mask is None else (
        np.asarray(mask, dtype=bool) & (y > 0.0))
    if not np.any(mask):
        return float("inf"), float("inf"), float("inf")
    ym = y[mask]
    ycm = yc[mask]
    w = 1.0 / ym
    num = float(np.sum(w * (ym - ycm) ** 2))
    den = float(np.sum(w * ym ** 2))
    if den <= 0.0:
        return float("inf"), float("inf"), float("inf")
    n = int(mask.sum())
    rwp = math.sqrt(num / den)
    n_eff = max(n - int(n_params), 1)
    rexp = math.sqrt(n_eff / den)
    gof = rwp / rexp if rexp > 0.0 else float("inf")
    return rwp, rexp, gof


def compute_fom(rwp: float, sigma: float = 0.25) -> float:
    """Rwp → FoM ∈ (0, 1]，``exp(−Rwp/σ)``。Rwp 非有限时为 0。"""
    if not math.isfinite(rwp) or sigma <= 0.0:
        return 0.0
    return float(math.exp(-rwp / sigma))


# --------------------------------------------------------------------------- #
# 反射展开: d–I → (2θ, I) 含 Kα2 双线
# --------------------------------------------------------------------------- #
def expand_reflections(
    peaks: Iterable,
    tth_lo: float,
    tth_hi: float,
    *,
    ka2: bool = True,
    ka2_intensity_ratio: float = 0.5,
    alpha2_ratio: float = _KA2_ALPHA2_RATIO,
) -> tuple[np.ndarray, np.ndarray]:
    """参考峰 → (centres, amps), 可选 Kα2 伴峰, 并按 2θ 范围过滤。

    ``peaks`` 元素为 ``(hkl, 2θ, I)``; ``I`` 为 ``None`` / 非正 / 非数值时跳过。
    范围留 1° 余量 (与 FPFM 一致), 使精修把峰推出边界时不会被裁掉。

    与 ``RietveldRefiner._expand_ka2_satellites`` 同式
    (``2θ2 = 2·arcsin(α2·sin θ1)``, 强度 ×ratio); 此处为纯函数形式,
    由 ``tests/test_wpsm.py`` 断言两者输出一致以防漂移。
    """
    centres: list[float] = []
    amps: list[float] = []
    for pk in peaks or []:
        try:
            if len(pk) < 3:
                continue
            tt = float(pk[1])
            inten = float(pk[2])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(tt) or not math.isfinite(inten) or inten <= 0.0:
            continue
        lo_ok = tt >= tth_lo - 1.0
        hi_ok = tt <= tth_hi + 1.0
        if lo_ok and hi_ok:
            centres.append(tt)
            amps.append(inten)
        if ka2:
            s1 = math.sin(math.radians(tt / 2.0))
            s2 = float(alpha2_ratio) * s1
            if s2 < 1.0:
                tt2 = 2.0 * math.degrees(math.asin(s2))
                if tth_lo - 1.0 <= tt2 <= tth_hi + 1.0:
                    centres.append(tt2)
                    amps.append(inten * float(ka2_intensity_ratio))
    if not centres:
        return np.empty(0), np.empty(0)
    order = np.argsort(np.asarray(centres, dtype=np.float64))
    return (np.asarray(centres, dtype=np.float64)[order],
            np.asarray(amps, dtype=np.float64)[order])


# --------------------------------------------------------------------------- #
# 单候选拟合
# --------------------------------------------------------------------------- #
def _theory(
    x: np.ndarray,
    centres: np.ndarray,
    amps: np.ndarray,
    tan_theta: np.ndarray,
    *,
    p: Sequence[float],
    use_uvw: bool,
    use_cell: bool,
    cfg: WpsmConfig,
    x_mid: float,
) -> np.ndarray:
    """按参数向量合成理论谱 (峰 + 二次背底)。"""
    from polyxrd.services.phase_display import spectrum_from_refs

    scale, shift = float(p[0]), float(p[1])
    k = 2
    if use_uvw:
        uvw = (float(p[2]), float(p[3]), float(p[4]))
        fwhm = cfg.fwhm_init          # Caglioti 生效时被忽略
        k = 5
    else:
        uvw = None
        fwhm = float(p[2])
        k = 3
    eta = float(p[k])
    bg0, bg1, bg2 = float(p[k + 1]), float(p[k + 2]), float(p[k + 3])
    k += 4
    cell_delta = float(p[k]) if use_cell else 0.0

    # 峰位: 零点位移 + 晶胞缩放 (一阶 tanθ 签名)
    centres_eff = centres + shift
    if cell_delta != 0.0:
        centres_eff = centres_eff - cell_delta * _CELL_TTH_FACTOR * tan_theta

    phases = [[(None, float(c), float(a))
               for c, a in zip(centres_eff, amps)]]
    yc = spectrum_from_refs(
        x, phases, [1.0],
        fwhm=fwhm,
        eta=eta,
        scale=scale,
        peak_shape="pseudo-voigt",
        caglioti=uvw,
        cutoff_fwhm=cfg.cutoff_fwhm,
        asymmetry=cfg.asymmetry,
    )
    t = x - x_mid
    return yc + bg0 + bg1 * t + bg2 * t * t


def fit_candidate(
    x,
    y,
    peaks: Iterable,
    *,
    cfg: Optional[WpsmConfig] = None,
    key: object = None,
    wavelength: float = 1.5406,
) -> WpsmFit:
    """对单条候选做受限全谱拟合。

    Args:
        x: 2θ 网格 (度), 升序
        y: **原始**强度 (不要求预先扣背底)
        peaks: 参考峰 ``[(hkl, 2θ, I), ...]``
        cfg: 拟合配置; ``None`` 用默认
        key: 候选标识, 原样写入结果的 ``key``
        wavelength: 仅用于记录 (参考峰的 2θ 已含波长信息)

    Returns:
        :class:`WpsmFit`。任何退化情形都返回 ``fom=0`` + ``reason``, 不抛异常
        —— 一个发散候选不得搞挂整轮检索。
    """
    cfg = cfg or WpsmConfig()
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    out = WpsmFit(key=key)
    if x.size < 10 or x.size != y.size:
        out.reason = "grid"
        return out

    lo, hi = float(x[0]), float(x[-1])
    centres, amps = expand_reflections(
        peaks, lo, hi,
        ka2=cfg.ka2,
        ka2_intensity_ratio=cfg.ka2_intensity_ratio,
    )
    if centres.size == 0:
        out.reason = "no_reflection"
        return out
    mask = y > 0.0
    if not np.any(mask):
        out.reason = "no_positive"
        return out

    x_mid = 0.5 * (lo + hi)
    tan_theta = np.clip(np.tan(np.radians(centres / 2.0)), 0.0, 8.0)

    use_uvw = bool(cfg.caglioti)
    use_cell = bool(cfg.cell_refine)

    # Caglioti 初值: 让定标角 (扫描中点) 处的宽度等于 fwhm_init
    tm = math.tan(math.radians(0.25 * (lo + hi)))
    u0 = float(cfg.caglioti_u_init)
    v0 = float(cfg.caglioti_v_init)
    w0 = cfg.fwhm_init ** 2 - u0 * tm * tm - v0 * tm
    w0 = min(max(w0, cfg.caglioti_w_bounds[0]), cfg.caglioti_w_bounds[1])

    # 初始 scale: 让理论谱最大值对齐实测最大值
    y0 = _theory(x, centres, amps, tan_theta,
                 p=[1.0, 0.0] + ([u0, v0, w0] if use_uvw else [cfg.fwhm_init])
                 + [cfg.eta_init, 0.0, 0.0, 0.0] + ([0.0] if use_cell else []),
                 use_uvw=use_uvw, use_cell=use_cell, cfg=cfg, x_mid=x_mid)
    tmax = float(y0.max())
    ymax = float(y.max())
    scale0 = ymax / tmax if tmax > 0.0 else 1.0

    # ── 参数向量: [scale, shift, (u,v,w | fwhm), eta, bg0, bg1, bg2, (Δ)] ──
    p0 = [scale0, 0.0]
    lo_b = [0.0, -cfg.shift_bound]
    hi_b = [scale0 * 10.0, cfg.shift_bound]
    if use_uvw:
        p0 += [u0, v0, w0]
        (u_lo, u_hi), (v_lo, v_hi), (w_lo, w_hi) = (
            cfg.caglioti_u_bounds, cfg.caglioti_v_bounds, cfg.caglioti_w_bounds)
        lo_b += [u_lo, v_lo, w_lo]
        hi_b += [u_hi, v_hi, w_hi]
    else:
        p0 += [cfg.fwhm_init]
        lo_b += [cfg.fwhm_bounds[0]]
        hi_b += [cfg.fwhm_bounds[1]]

    # 初始背底: 低分位包络
    bg0_0 = float(np.percentile(y, 5))
    p0 += [cfg.eta_init, bg0_0, 0.0, 0.0]
    lo_b += [cfg.eta_bounds[0]]
    hi_b += [cfg.eta_bounds[1]]
    half = max(0.5 * (hi - lo), 1e-6)
    if str(cfg.bg_bound_mode).lower() == "scaled":
        # D1: 让 bg 多项式在扫描边缘的摆幅不超过 ~ymax (乘 bg_bound_pad 放宽)
        b1 = float(cfg.bg_bound_pad) * ymax / half
        b2 = float(cfg.bg_bound_pad) * ymax / (half * half)
        lo_b += [-ymax, -b1, -b2]
        hi_b += [ymax, b1, b2]
    else:  # "raw" = FPFM 口径
        lo_b += [-ymax, -ymax, -ymax]
        hi_b += [ymax, ymax, ymax]

    if use_cell:
        p0 += [0.0]
        lo_b += [-cfg.cell_bound]
        hi_b += [cfg.cell_bound]

    n_params = len(p0)

    def residuals(p) -> np.ndarray:
        yc = _theory(x, centres, amps, tan_theta,
                     p=p, use_uvw=use_uvw, use_cell=use_cell,
                     cfg=cfg, x_mid=x_mid)
        r = np.zeros_like(y)
        ym = y[mask]
        r[mask] = (ym - yc[mask]) / np.sqrt(ym)
        return r

    try:
        sol = least_squares(
            residuals,
            np.asarray(p0, dtype=np.float64),
            bounds=(np.asarray(lo_b, dtype=np.float64),
                    np.asarray(hi_b, dtype=np.float64)),
            method="trf",
            xtol=cfg.xtol,
            ftol=cfg.ftol,
            max_nfev=int(cfg.max_nfev),
        )
    except Exception:  # noqa: BLE001 — 发散候选不得中断检索
        out.reason = "solver"
        return out

    p = sol.x
    scale, shift = float(p[0]), float(p[1])
    k = 2
    if use_uvw:
        u, v, w = float(p[2]), float(p[3]), float(p[4])
        k = 5
        tm_arr = np.array([tm], dtype=np.float64)
        fwhm_rep = float(np.sqrt(np.clip(u * tm_arr * tm_arr + v * tm_arr + w,
                                         1e-8, None))[0])
    else:
        u = v = 0.0
        fwhm_rep = float(p[2])
        w = fwhm_rep * fwhm_rep
        k = 3
    eta = float(p[k])
    bg0, bg1, bg2 = float(p[k + 1]), float(p[k + 2]), float(p[k + 3])
    k += 4
    cell_delta = float(p[k]) if use_cell else 0.0

    yc_final = _theory(x, centres, amps, tan_theta,
                       p=list(p), use_uvw=use_uvw, use_cell=use_cell,
                       cfg=cfg, x_mid=x_mid)
    rwp, rexp, gof = compute_rwp(y, yc_final, n_params=0)

    # ── 计分域 / 计分方式 (见 WpsmConfig.score_domain / score_mode) ──
    domain = None
    rwp_domain = rwp
    rwp_bg = float("nan")
    if str(cfg.score_domain).lower() == "window":
        centres_eff = centres + shift
        if cell_delta != 0.0:
            centres_eff = centres_eff - cell_delta * _CELL_TTH_FACTOR * tan_theta
        if use_uvw:
            h_i = np.sqrt(np.clip(u * tan_theta ** 2 + v * tan_theta + w,
                                  1e-8, None))
        else:
            h_i = np.full(centres.size, max(fwhm_rep, 1e-6))
        half = np.maximum(float(cfg.score_half_deg),
                          float(cfg.score_n_fwhm) * h_i)
        domain = np.zeros(x.size, dtype=bool)
        for c, hw in zip(centres_eff, half):
            lo_i = int(np.searchsorted(x, c - hw))
            hi_i = int(np.searchsorted(x, c + hw, side="right"))
            domain[lo_i:hi_i] = True
        if int(domain.sum()) < 10:
            domain = None          # 域太小 → 退回全局, 避免噪声支配
        else:
            rwp_domain = compute_rwp(y, yc_final, n_params=0, mask=domain)[0]

    if str(cfg.score_mode).lower() == "delta":
        t_arr = x - x_mid
        y_bg = bg0 + bg1 * t_arr + bg2 * t_arr * t_arr
        rwp_bg = compute_rwp(y, np.broadcast_to(y_bg, y.shape).astype(float),
                             n_params=0, mask=domain)[0]
        fom = (1.0 - rwp_domain / rwp_bg
               if math.isfinite(rwp_bg) and rwp_bg > 0.0
               and math.isfinite(rwp_domain) else 0.0)
        fom = float(min(max(fom, 0.0), 1.0))
    else:
        fom = compute_fom(rwp_domain, cfg.fom_sigma)

    out.scale = scale
    out.shift_deg = shift
    out.fwhm = fwhm_rep
    out.eta = eta
    out.bg0 = bg0
    out.bg1 = bg1
    out.bg2 = bg2
    out.u = u
    out.v = v
    out.w = w
    out.cell_delta = cell_delta
    out.rwp = float(rwp)              # 全局 Rwp (与精修口径可比, 用于展示)
    out.rexp = float(rexp)
    out.gof = float(gof)
    out.fom = float(fom)              # 排序分 (按 score_domain/score_mode)
    out.extra["n_reflections"] = int(centres.size)
    out.extra["n_params"] = n_params
    out.extra["scale0"] = float(scale0)
    out.extra["wavelength"] = float(wavelength)
    out.extra["rwp_domain"] = float(rwp_domain)
    out.extra["rwp_bg"] = float(rwp_bg)
    out.extra["score_domain"] = str(cfg.score_domain)
    out.extra["score_mode"] = str(cfg.score_mode)
    out.extra["n_domain"] = int(x.size if domain is None else int(domain.sum()))
    return out


# --------------------------------------------------------------------------- #
# 批量精排
# --------------------------------------------------------------------------- #
def wpsm_rerank(
    x,
    y,
    items: Sequence[tuple],
    *,
    cfg: Optional[WpsmConfig] = None,
    peak_getter: Optional[Callable] = None,
    top_n: Optional[int] = None,
    timing: Optional[dict] = None,
) -> list[WpsmFit]:
    """对一批候选做全谱精排并按 FoM 降序返回。

    Args:
        x, y: 原始谱 (2θ / 强度)
        items: ``[(key, peaks_or_obj), ...]``; ``peaks_or_obj`` 可直接是参考峰
            序列, 也可以是任意对象 (此时须给 ``peak_getter``)
        peak_getter: ``obj → [(hkl, 2θ, I), ...]`` 的抽取函数
        top_n: 输出条数; ``None`` 用 ``cfg.top_n``
        timing: 可选字典, 写入 ``n_candidates`` / ``total`` 秒

    Returns:
        ``[WpsmFit, ...]`` 按 ``fom`` 降序。失败的候选 ``fom=0`` 自然沉底。
    """
    import time

    cfg = cfg or WpsmConfig()
    t0 = time.perf_counter()
    n_out = int(cfg.top_n if top_n is None else top_n)
    cand = list(items or [])
    if cfg.prescreen_top_n > 0:
        cand = cand[: int(cfg.prescreen_top_n)]

    fits: list[WpsmFit] = []
    for key, obj in cand:
        try:
            peaks = peak_getter(obj) if peak_getter is not None else obj
            fits.append(fit_candidate(x, y, peaks, cfg=cfg, key=key))
        except Exception:  # noqa: BLE001
            bad = WpsmFit(key=key, reason="exception")
            fits.append(bad)

    fits.sort(key=lambda f: float(f.fom), reverse=True)
    if timing is not None:
        timing.update({"n_candidates": len(cand),
                       "total": time.perf_counter() - t0})
    return fits[:n_out] if n_out > 0 else fits
