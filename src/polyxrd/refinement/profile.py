"""峰形内核：面积归一 pV/G/L + Caglioti(tanθ) + TCH 尺寸-应变 + split 不对称。

设计要点（口径钉死，勿改）
--------------------------
1. **面积归一**：``∫G = ∫L = ∫PV = 1``，与 FWHM / η 无关。Rietveld 要求
   峰**积分强度** ∝ m·LP·|F|²·S，峰宽只影响形状不影响面积。旧实现里
   "峰高=1" 的写法会让积分面积 ∝ FWHM，Caglioti 一开峰宽参数就被拟合到
   错误数值（`phase_display._area_normalized_profile` 的 W11 已修正过同类问题）。

       G(Δ) = exp(−Δ²/2σ²) / (σ√(2π)),  σ = FWHM/(2√(2ln2))
       L(Δ) = (γ/π) / (Δ² + γ²),        γ = FWHM/2
       PV   = η·G + (1−η)·L

2. **Caglioti 用 tanθ，不是 tan(2θ)**：``FWHM² = U·tan²θ + V·tanθ + W``
   中的 θ 是布拉格角 ``θ = 2θ/2``。历史 bug：``shape.caglioti`` 传的是 2θ，
   于是 2θ=90° 时 tan(2θ)=∞ 直接把峰宽算爆。本模块只接受 2θ 输入、内部除以 2。

3. **TCH（Thompson–Cox–Hastings）合成**：高斯分量与洛伦兹分量先各自算 FWHM
   （单位：**度，以 2θ 计**），再用 TCH 五次式合成总 FWHM 与 η：

       F⁵ = G⁵ + 2.69269·G⁴L + 2.42843·G³L² + 4.47163·G²L³ + 0.07842·GL⁴ + L⁵
       η  = 1.36603·r − 0.47719·r² + 0.11116·r³,  r = L/F

   这是 GSAS-II / FullProf 的标准做法；η 由宽度比**导出**而非独立拟合，避免了
   "η 与 FWHM 强相关" 的病态条件数。

4. **仪器 / 样品解耦**（方案 D3）：
   - 仪器高斯：``G_inst² = U·tan²θ + V·tanθ + W``（Caglioti）
   - 仪器洛伦兹：``L_inst = X·tanθ + Y/cosθ + Z``（GSAS-II profile 2 口径，
     X/Y/Z 单位**度**）
   - 样品（TCH 尺寸-应变，LFP 直接口径）：
     ``β_size = K·λ/(D·cosθ)``、``β_strain = 4ε·tanθ``，二者都是洛伦兹型，
     直接加到 ``L`` 上。**注意单位换算**：这两式算出的是**弧度**，而 FWHM 以
     2θ 的**度**计，故须乘 180/π。

5. **split 不对称**（低角轴向发散）：左侧 FWHM×(1+a·f)，右侧 ×(1−a·f)，
   ``f = tan10° / max(tanθ, tan10°)``。每半边用面积归一到 1 的曲线限制在半边
   → 每半边积分恒 0.5 → **总面积不变**（不对称不会改变峰面积）。

6. **Kα2 双线**：``2θ(Kα2) = 2·asin(λ2/λ1 · sinθ1)``（严格的 Bragg 换算，
   不是线性位移）。强度比默认 1:0.497（Cu）。双线各占面积的
   ``1/(1+r)`` 与 ``r/(1+r)``，保证总面积不变。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "PROFILE_KINDS",
    "SQRT_2LN2",
    "SQRT_PI_4LN2",
    "ProfileParams",
    "caglioti_fwhm",
    "tch_widths",
    "tch_combine",
    "area_normalized_profile",
    "split_asymmetry_factor",
    "split_scale_factors",
    "ka2_wavelength",
    "ka2_two_theta",
    "Kalpha2",
    "profile_centers",
]

PROFILE_KINDS: Tuple[str, ...] = ("pseudo-voigt", "gaussian", "lorentzian")

#: FWHM → 高斯 σ：``σ = FWHM/(2√(2ln2)) = 0.4246609·FWHM``
FWHM_TO_SIGMA = float(1.0 / (2.0 * np.sqrt(2.0 * np.log(2.0))))
#: 峰高 → 积分面积的 pV 归一常数：``A = h·FWHM·(1.06447 + 0.50633·η)``
SQRT_PI_4LN2 = float(np.sqrt(np.pi / (4.0 * np.log(2.0))))
#: 兼容旧名（`phase_display` 口径），实际值 = FWHM→σ
SQRT_2LN2 = FWHM_TO_SIGMA

#: 弧度 → 度。尺寸/应变公式给出弧度 FWHM，而峰形全部以 2θ 的度计。
_RAD2DEG = 180.0 / np.pi


@dataclass(frozen=True)
class ProfileParams:
    """峰形参数（全部为**度**，以 2θ 计；角度项按 θ=2θ/2 使用）。

    仪器层（所有相共享）:

    :param u: Caglioti U，``U·tan²θ``
    :param v: Caglioti V，``V·tanθ``
    :param w: Caglioti W（常数项）。U=V=W=0 → 退回固定 ``fwhm``
    :param x: 洛伦兹角度项 ``X·tanθ``（GSAS-II LX）
    :param y: 洛伦兹 1/cosθ 项（GSAS-II LY）
    :param z: 洛伦兹常数项（GSAS-II LZ）

    样品层（逐相）:

    :param size_nm: 相干散射域尺寸 D（nm）；0 或负数 = 不启用
    :param strain: 微观应变 ε（无量纲）；0 = 不启用
    :param k_size: Scherrer 常数 K，默认 0.9

    形状层:

    :param fwhm: 固定 FWHM（Caglioti 全 0 时生效）
    :param eta: 固定 η（TCH 未启用时生效）
    :param kind: ``pseudo-voigt`` / ``gaussian`` / ``lorentzian``
    :param asymmetry: split 不对称幅度 a（0 = 对称），有效范围 [0, 0.4]
    :param use_tch: 强制 TCH 合成开关。``None`` = 自动（洛伦兹分量非零或有
        尺寸/应变时启用）。**精修时必须显式钉住**：让它在迭代中因 x/y 从 0
        变非 0 而自动翻转，会让 η 从"用户给的值"跳成"TCH 导出值"，模型在参数
        空间里出现断层，LM 会卡在断层边缘不再下降（实测 Rwp 一步不动）。
    """

    u: float = 0.0
    v: float = 0.0
    w: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    size_nm: float = 0.0
    strain: float = 0.0
    k_size: float = 0.9
    fwhm: float = 0.15
    eta: float = 0.5
    kind: str = "pseudo-voigt"
    asymmetry: float = 0.0
    #: P0-C：低角"拖尾"面积占比 t（0 = 关闭）。峰面积按 ``(1−t)`` 主峰 +
    #: ``t`` 个**左移 0.25·FWHM、宽 3.2 倍**的洛伦兹分量分配（面积守恒）。
    #: 这是轴向发散/样品透明在实测谱里的粗粒度等效 —— split-PV 只能改左右
    #: **宽度**，改不了"峰心左侧多出一块慢衰减尾巴"的形状。
    tail: float = 0.0
    use_tch: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.kind not in PROFILE_KINDS:
            raise ValueError(f"未知峰形 {self.kind!r}，应为 {PROFILE_KINDS}")

    # ── 状态查询 ────────────────────────────────────────────────
    @property
    def uses_caglioti(self) -> bool:
        return abs(self.u) + abs(self.v) + abs(self.w) > 1e-15

    @property
    def uses_tch(self) -> bool:
        """是否启用 TCH 合成。

        显式 ``use_tch`` 优先；未指定时按"洛伦兹分量非零或尺寸/应变非零"推断。
        """
        if self.use_tch is not None:
            return bool(self.use_tch)
        return (abs(self.x) + abs(self.y) + abs(self.z) > 1e-15
                or self.size_nm > 0.0 or abs(self.strain) > 1e-15)

    @property
    def uses_split(self) -> bool:
        return abs(self.asymmetry) > 1e-12

    def with_samples(self, *, size_nm: Optional[float] = None,
                     strain: Optional[float] = None) -> "ProfileParams":
        """派生一份只改样品层的副本（逐相峰形用）。"""
        kw = {}
        if size_nm is not None:
            kw["size_nm"] = float(size_nm)
        if strain is not None:
            kw["strain"] = float(strain)
        return replace(self, **kw)

    def as_dict(self) -> dict:
        return {
            "u": self.u, "v": self.v, "w": self.w,
            "x": self.x, "y": self.y, "z": self.z,
            "size_nm": self.size_nm, "strain": self.strain,
            "k_size": self.k_size, "fwhm": self.fwhm, "eta": self.eta,
            "kind": self.kind, "asymmetry": self.asymmetry,
            "tail": self.tail, "use_tch": self.use_tch,
        }


# ── 峰宽：Caglioti / TCH ────────────────────────────────────────

def _bragg_theta(two_theta) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 ``(tanθ, cosθ, 1/cosθ)``；θ = 2θ/2（**不是** 2θ）。"""
    th = np.radians(np.asarray(two_theta, dtype=float)) / 2.0
    t = np.tan(th)
    c = np.cos(th)
    inv_c = 1.0 / np.maximum(c, 1e-6)
    return t, c, inv_c


def caglioti_fwhm(two_theta, u: float, v: float, w: float) -> np.ndarray:
    """``FWHM = sqrt(U·tan²θ + V·tanθ + W)``，θ = 2θ/2。

    负根（拟合跑飞或物理不支持的区域）截断到 ``1e-4`` 度而非 NaN ——
    让 wR 变成"平的高墙"而不是 NaN 洪水，LM 才能退回来。
    """
    t, _c, _ic = _bragg_theta(two_theta)
    val = u * t * t + v * t + w
    return np.sqrt(np.maximum(val, 1e-8))


def tch_widths(
    two_theta,
    wavelength: float,
    params: ProfileParams,
) -> Tuple[np.ndarray, np.ndarray]:
    """返回 ``(fwhm, eta)``，均为 ndarray、单位**度**。

    分三步：
      1. 仪器高斯 ``G = sqrt(U tan²θ + V tanθ + W)``（Caglioti 全 0 → 用 ``params.fwhm``）
      2. 仪器洛伦兹 ``L = X tanθ + Y/cosθ + Z``
         再加样品项 ``Kλ/(D cosθ)`` 与 ``4ε tanθ``（弧度 → 度）
      3. TCH 合成 → ``(fwhm, eta)``

    未启用 TCH（``L`` 恒为 0 且无样品项）时直接返回固定 ``(fwhm, eta)``，
    保持与旧引擎的数值兼容。
    """
    tt = np.asarray(two_theta, dtype=float)
    t, cos_th, inv_c = _bragg_theta(tt)

    if params.uses_caglioti:
        g = caglioti_fwhm(tt, params.u, params.v, params.w)
    else:
        g = np.full(tt.shape, max(float(params.fwhm), 1e-6))

    if not params.uses_tch:
        return g, np.full(tt.shape, float(np.clip(params.eta, 0.0, 1.0)))

    ell = params.x * t + params.y * inv_c + params.z
    wl = float(wavelength) if wavelength and wavelength > 0 else 1.0

    # 样品：Scherrer 尺寸 + 微观应变（弧度 → 度）
    if params.size_nm > 0.0:
        d_ang = float(params.size_nm) * 10.0              # nm → Å
        ell = ell + (abs(params.k_size) * wl / (d_ang * np.maximum(cos_th, 1e-6))
                     * _RAD2DEG)
    if abs(params.strain) > 1e-15:
        ell = ell + abs(4.0 * params.strain) * t * _RAD2DEG

    ell = np.maximum(ell, 0.0)
    fwhm, eta = tch_combine(g, ell)
    # TCH 退化（G 与 L 都 ≤0）时给个正下限，避免 0 宽峰除零
    fwhm = np.maximum(fwhm, 1e-5)
    return fwhm, eta


#: ``size`` 参数化的下限：系数小于此值即认为"展宽不可分辨"。
#: 单位是度（``β_size = coef/cosθ``）；1e-6 度 ≈ D > 7 mm，远超任何 XRD 分辨率。
SIZE_COEF_MIN = 1e-6


def size_coefficient(size_nm: float, wavelength: float, k: float = 0.9) -> float:
    """Scherrer 尺寸折算成**洛伦兹系数**（度·cosθ）：``β_size = coef/cosθ``。

    为什么精修里必须用系数而不是 D（2026-11-04，基准报告 §十七）：``D`` 与
    ``inst.y`` 是**同一个函数形状**（都进 ``ell`` 的 ``1/cosθ`` 项），而且
    ``β(D) = Kλ/(D cosθ)`` 在 ``D → ∞`` 处彻底平坦 —— ``dβ/dD ∝ 1/D²``。
    实测 2-2 的 ``phase1.size`` 跑到 99988 nm（上界 100000），数值差分的列
    **在浮点上归零**，秩打成 15/16、SVD0=5e-15。改成系数后 ``coef=0``
    是"无展宽"这个**正常点**，雅可比列恒为 ``1/cosθ``，永不塌缩。
    """
    if not size_nm or float(size_nm) <= 0.0 or not wavelength or wavelength <= 0:
        return 0.0
    return float(k) * float(wavelength) / (float(size_nm) * 10.0) * _RAD2DEG


def size_from_coefficient(coef: float, wavelength: float, k: float = 0.9) -> float:
    """``size_coefficient`` 的逆变换；**只有系数恰为 0 才返回 0**（= 不启用展宽）。

    注意这里**不能**按 ``SIZE_COEF_MIN`` 截断：那会在 0 附近造出一个台阶，
    雅可比列在台阶以内恒为零 —— 等价于把刚修掉的"平坦区"又搬回来
    （2026-11-04 由 ``test_size_column_survives_tiny_coefficient`` 抓到）。
    "太小 → 报未分辨"是**展示层**的事（``goal`` / ``report`` 用
    ``SIZE_COEF_MIN``），不是模型层的事。
    """
    if not coef or float(coef) <= 0.0 or not wavelength or wavelength <= 0:
        return 0.0
    a_rad = max(float(coef) / _RAD2DEG, 1e-12)
    return float(k) * float(wavelength) / a_rad / 10.0


def tch_combine(gwhm, lwhm) -> Tuple[np.ndarray, np.ndarray]:
    """Thompson–Cox–Hastings：由高斯/洛伦兹分量 FWHM 合成 ``(FWHM, η)``。

    纯高斯（``L→0``）→ ``F=G, η=0``（η 是**洛伦兹占比**，故纯高斯 η=0）；
    纯洛伦兹（``G→0``）→ ``F=L, η=1``。两处都对。
    """
    g = np.maximum(np.asarray(gwhm, dtype=float), 0.0)
    ell = np.maximum(np.broadcast_to(np.asarray(lwhm, dtype=float), g.shape), 0.0)
    f5 = (g ** 5
          + 2.69269 * g ** 4 * ell
          + 2.42843 * g ** 3 * ell ** 2
          + 4.47163 * g ** 2 * ell ** 3
          + 0.07842 * g * ell ** 4
          + ell ** 5)
    fwhm = np.power(np.maximum(f5, 0.0), 0.2)
    safe = np.maximum(fwhm, 1e-12)
    r = np.where(fwhm > 1e-11, ell / safe, 0.0)
    eta = 1.36603 * r - 0.47719 * r ** 2 + 0.11116 * r ** 3
    return fwhm, np.clip(eta, 0.0, 1.0)


# ── 面积归一峰形 ──────────────────────────────────────────────

def _pv_peak_value(width, eta):
    """面积归一 pV 在 ``Δ=0`` 处的值（即峰高）。

    ``h = η/(1.06447·w) + (1−η)/(1.5708·w)`` —— 由 ``G(0)=1/(σ√(2π))``、
    ``L(0)=1/(πγ)``、``σ=0.42466w``、``γ=0.5w`` 代入整理而来。
    """
    w = np.maximum(np.asarray(width, dtype=float), 1e-9)
    e = np.clip(np.asarray(eta, dtype=float), 0.0, 1.0)
    return e / (SQRT_PI_4LN2 * w) + (1.0 - e) / (np.pi / 2.0 * w)


def split_scale_factors(width_low, width_high, eta):
    """split-PV 两半的**高度归一系数** ``(k_lo, k_hi)``。

    赤裸的 split（左右各用自己宽度、各自面积归一到 0.5）在峰心 ``Δ=0`` 处
    **不连续** —— 峰值 = ``1/宽度``，左右宽度差多少，峰顶就跳多少。实测
    ``a=0.25``（2θ≈20°）时跳变 66%，峰顶是台阶而不是峰。这在 GUI 上一眼看得
    出来，残差也在每条峰心处留下人为跳变。

    修正：每半乘一个标度 ``k``，要求

      * **连续**：``k_lo·h_lo = k_hi·h_hi``
      * **面积守恒**：每半原面积 0.5 ⇒ ``k_lo + k_hi = 2``

    解出 ``k_lo = 2h_hi/(h_lo+h_hi)``、``k_hi = 2h_lo/(h_lo+h_hi)``。于是
    宽的一侧自动分到更多面积（``a=0.25`` 时低角侧 62.5%），这正是"低角侧更宽"
    应有的物理结果 —— 旧实现给的 50/50 反而丢了这个信息。
    """
    h_lo = _pv_peak_value(width_low, eta)
    h_hi = _pv_peak_value(width_high, eta)
    tot = np.maximum(h_lo + h_hi, 1e-30)
    return 2.0 * h_hi / tot, 2.0 * h_lo / tot


def area_normalized_profile(
    delta,
    fwhm,
    eta,
    kind: str = "pseudo-voigt",
    fwhm_low=None,
    fwhm_high=None,
) -> np.ndarray:
    """面积归一的 G / L / PV 评估（``∫ = 1``）。

    :param delta: 与峰心的差 ``2θ − 2θ₀``，度；任意形状
    :param fwhm: 总 FWHM（度），可广播
    :param eta: 洛伦兹占比，可广播（TCH 导出值即为数组）
    :param kind: ``pseudo-voigt`` / ``gaussian`` / ``lorentzian``
    :param fwhm_low: 给出时对 ``delta < 0`` 侧使用该宽度（split-PV）
    :param fwhm_high: 给出时对 ``delta > 0`` 侧使用该宽度

    split 模式下：**总面积仍为 1**，且**峰心连续**（见
    :func:`split_scale_factors`）。旧 ``phase_display`` 版本只做了面积归一、没做
    高度归一，峰顶会跳 —— 本函数是有意修正的版本，两者在 split 分支上**数值
    不同**，非 split 分支完全一致。
    """
    delta = np.asarray(delta, dtype=float)
    split = fwhm_low is not None and fwhm_high is not None
    if not split:
        width = np.maximum(np.asarray(fwhm, dtype=float), 1e-9)
    else:
        w_lo = np.maximum(np.asarray(fwhm_low, dtype=float), 1e-9)
        w_hi = np.maximum(np.asarray(fwhm_high, dtype=float), 1e-9)
        width = np.where(delta < 0.0, w_lo, w_hi)

    width = np.maximum(width, 1e-9)

    if kind == "gaussian":
        sigma = np.maximum(width * FWHM_TO_SIGMA, 1e-12)
        prof = np.exp(-0.5 * (delta / sigma) ** 2) / (sigma * np.sqrt(2.0 * np.pi))
    elif kind == "lorentzian":
        gamma = width / 2.0
        prof = (gamma / np.pi) / (delta * delta + gamma * gamma)
    else:
        sigma = np.maximum(width * FWHM_TO_SIGMA, 1e-12)
        gamma = width / 2.0
        gauss = np.exp(-0.5 * (delta / sigma) ** 2) / (sigma * np.sqrt(2.0 * np.pi))
        lorentz = (gamma / np.pi) / (delta * delta + gamma * gamma)
        e = np.clip(np.asarray(eta, dtype=float), 0.0, 1.0)
        prof = e * gauss + (1.0 - e) * lorentz

    if split:
        k_lo, k_hi = split_scale_factors(w_lo, w_hi, eta)
        prof = prof * np.where(delta < 0.0, k_lo, k_hi)
    return prof


def split_asymmetry_factor(two_theta, amplitude: float) -> np.ndarray:
    """Finger 式低角不对称幅度因子 ``f(θ) ∈ [0, 1]``。

    ``f = a·tan10° / max(tanθ, tan10°)``：低角封顶于 ``a``，高角按 ``tanθ``
    衰减（2θ=90° 处约 ``0.176a``）。语义 = "2θ≈20° 处的展宽比例"。

    旧实现用 ``a/max(tanθ, 0.3)``，45° 处仍有 ``0.3a`` → 高角也不对称，与
    "低角轴向发散" 的物理不符（实测 r90=1.92，已修正）。
    """
    a = float(np.clip(amplitude, 0.0, 0.4))
    t, _c, _ic = _bragg_theta(two_theta)
    tan10 = float(np.tan(np.radians(10.0)))
    return np.clip(a * tan10 / np.maximum(t, tan10), 0.0, 0.4)


# ── Kα2 双线 ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Kalpha2:
    """Kα1/Kα2 双线描述。

    :param wavelength: Kα1 波长 (Å)
    :param ratio: I(Kα2)/I(Kα1)，Cu 靶 0.497、Co 靶 0.5、Mo 靶 0.5
    :param separation: 为 True 时用严格 Bragg 换算放置 Kα2 峰；False 则只用 Kα1
    """

    wavelength: float = 1.54056
    ratio: float = 0.497
    separation: bool = True

    def component_weights(self) -> Tuple[float, float]:
        """``(w1, w2)``，满足 ``w1 + w2 = 1``（总面积守恒）。"""
        if not self.separation or self.ratio <= 0.0:
            return 1.0, 0.0
        r = float(self.ratio)
        return 1.0 / (1.0 + r), r / (1.0 + r)


def ka2_wavelength(wavelength: float, *, ratio_of_ka1: float = 1.00249
                   ) -> float:
    """由 Kα1 估 Kα2 波长（默认 Cu：1.54056 → 1.54439 Å，比值 1.00249）。

    ``λ(Kα2)/λ(Kα1)``：Cu 1.00249、Mo 1.00605 —— 各靶都略大于 1，统一取
    Cu 值对常规角域够用；需要精确值时调用方直接传 ``ka2_two_theta`` 的
    显式波长。

    历史 bug（2026-11-01 修）：旧默认 0.99937 会把伴峰放到主峰**左侧**
    约 0.0006·2tanθ 处（真值在右侧 0.0025·2tanθ），方向和量级全错 ——
    v5 在双线数据上被迫让 U·tan²θ 当双线"替身"（u=0.182 vs 物理值
    0.008）的根因之一，见基准报告 §十二。
    """
    return float(wavelength) * float(ratio_of_ka1)


def ka2_two_theta(two_theta_ka1, wavelength1: float, wavelength2: float) -> np.ndarray:
    """Kα2 峰位：``2θ₂ = 2·asin( (λ₂/λ₁)·sinθ₁ )``（严格 Bragg，非线性）。

    低角近似 ``Δ2θ ≈ 2·tanθ·(Δλ/λ)`` 在 2θ>60° 偏差可达 0.02°，故用严式。
    若 ``(λ₂/λ₁)sinθ₁ > 1``（不可能出现，λ₂>λ₁ 时 sinθ₁<1 但比值放大）→ 截断。
    """
    tt = np.asarray(two_theta_ka1, dtype=float)
    s = np.sin(np.radians(tt) / 2.0) * (float(wavelength2) / float(wavelength1))
    s = np.clip(s, -1.0, 1.0)
    return 2.0 * np.degrees(np.arcsin(s))


def profile_centers(
    two_theta: Sequence[float],
    kalph: Kalpha2,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """展开成 ``(centers, weights, is_ka2)``，供合成谱或线性层使用。

    ``separation=False`` → 只有 Kα1 一条（权重 1）。
    """
    tt = np.asarray(two_theta, dtype=float).reshape(-1)
    w1, w2 = kalph.component_weights()
    if w2 <= 0.0:
        return tt, np.ones_like(tt), np.zeros(tt.shape, dtype=bool)
    lam1 = float(kalph.wavelength)
    lam2 = ka2_wavelength(lam1)
    tt2 = ka2_two_theta(tt, lam1, lam2)
    centers = np.concatenate([tt, tt2])
    weights = np.concatenate([np.full(tt.shape, w1), np.full(tt.shape, w2)])
    is2 = np.concatenate([np.zeros(tt.shape, bool), np.ones(tt.shape, bool)])
    return centers, weights, is2


# ── Kα2 存在性判别（基准报告-精修-v5.0.0.md §十二 12.2-3）──────

def detect_ka2_doublet(
    two_theta,
    intensity,
    wavelength: float = 1.54056,
    *,
    fwhm: Optional[float] = None,
    ratio_band: Tuple[float, float] = (0.22, 0.78),
) -> dict:
    """判别观测谱是否含**未剥离**的 Kα1/Kα2 双线。

    与 ``RietveldRefiner.detect_ka2``（W19-a，最强峰残差诊断）是两个问题：
    这里回答的是"数据里到底有没有双线"，供 v5 引擎决定
    ``Kalpha2.separation`` 的取值 —— 无双线数据却建模双线时，U·tan²θ 会
    被迫当双线的"替身"（3-1 实测 u 从 0.008 涨到 0.182），宽度参数失去
    物理可解读性。

    判据（**镜像位对称性**，对洛伦兹拖尾稳健）：
      对高角区（Δ2θ > 1.15×FWHM 处）每个强峰 p：
        r_right = I(p + Δ) / I(p)    Δ 为解析双线间距（严格 Bragg 式）
        r_left  = I(p − Δ) / I(p)    镜像位（同偏移量的左侧）
      真伴峰 → r_right ∈ 伴峰强度比带 且 r_right ≫ r_left（≥1.3×）；
      单峰洛伦兹拖尾 → r_right ≈ r_left → 排除；单峰高斯拖尾 →
      r_right 本身就在带外 → 排除。多重峰（相邻 hkl）不满足解析 Δ 角度
      规律 + 镜像位常被邻居抬升 → 大多重不中。

    决策规则（保守）：检出伴峰 ≥2 且命中率 ≥50% → True；
    全部强峰零命中 → False；其余（高角区不足 / 强峰 <2 / 混合命中）
    → None（调用方维持现状，即建模双线）。

    Returns:
        ``dict(flagged, examined, hits, ratios, fwhm, region)``；
        ``flagged ∈ {True, False, None}``，检测失败绝不抛异常。
    """
    out: dict = {"flagged": None, "examined": 0, "hits": 0, "ratios": [],
                 "fwhm": fwhm, "region": None}
    tt = np.asarray(two_theta, dtype=float).reshape(-1)
    y = np.asarray(intensity, dtype=float).reshape(-1)
    if tt.size < 100 or tt.size != y.size:
        return out
    step = float(np.median(np.diff(tt)))
    if step <= 0:
        return out

    # 轻度平滑 + 宽窗滑动中值背景（无双线判据对背景形状不敏感，够用）
    k = max(3, int(round(0.02 / step)))
    k += (k + 1) % 2
    ys = np.convolve(y, np.ones(k) / k, mode="same")
    wb = max(31, int(round(4.0 / step)))
    wb += (wb + 1) % 2
    pad = wb // 2
    yp = np.pad(ys, pad, mode="edge")
    bg = np.median(
        np.lib.stride_tricks.sliding_window_view(yp, wb), axis=1)
    ysub = np.clip(ys - bg, 0.0, None)

    # FWHM 估计：未给则取全局最高峰的半高全宽（双线会把宽度测大一档，
    # 方向保守 —— 判"双线分开"的门限随之抬高，不会误报）
    if fwhm is None:
        i0 = int(np.argmax(ysub))
        f = 0.12
        if ysub[i0] > 0:
            half = 0.5 * float(ysub[i0])
            l = i0
            while l > 0 and ysub[l] > half:
                l -= 1
            r = i0
            while r < tt.size - 1 and ysub[r] > half:
                r += 1
            f = float(tt[r] - tt[l])
    else:
        f = float(fwhm)
    f = float(np.clip(f, 0.04, 0.6))
    out["fwhm"] = f

    # 高角区：双线间距 > 1.15×FWHM 且右侧留足伴峰搜索空间
    lam1 = float(wavelength)
    lam2 = ka2_wavelength(lam1)
    d2 = ka2_two_theta(tt, lam1, lam2) - tt
    hi = (d2 > 1.15 * f) & (tt < tt[-1] - 1.0)
    idx_hi = np.nonzero(hi)[0]
    if idx_hi.size < 10 or (tt[idx_hi[-1]] - tt[idx_hi[0]]) < 3.0:
        return out  # 角域太窄，双线根本分不开 → 无法判定
    out["region"] = (float(tt[idx_hi[0]]), float(tt[idx_hi[-1]]))

    # 候选主峰：高角区局部极大，≥15% 区域最大高度，按高度取前 8 且互相分开
    yhi = ysub[idx_hi]
    loc = (yhi[1:-1] >= yhi[:-2]) & (yhi[1:-1] > yhi[2:])
    cand = idx_hi[1:-1][loc]
    cand = cand[ysub[cand] >= 0.15 * float(yhi.max())]
    cand = list(cand[np.argsort(ysub[cand])[::-1]])
    prim: list = []
    for i in cand:
        if all(abs(tt[i] - tt[j]) >= max(1.5 * f, 4 * step) for j in prim):
            prim.append(int(i))
        if len(prim) >= 8:
            break
    if len(prim) < 2:
        return out
    out["examined"] = len(prim)

    r_lo, r_hi = float(ratio_band[0]), float(ratio_band[1])
    w = max(2, int(round(0.4 * f / step)))
    for i in prim:
        h1 = float(ysub[i])
        if h1 <= 0:
            continue
        c2 = tt[i] + d2[i]
        j2 = int(np.searchsorted(tt, c2 + 0.4 * f))
        seg = ysub[max(i + 2, j2 - 2 * w):j2]
        if seg.size < 2:
            continue
        r_right = float(seg.max()) / h1
        if not (r_lo <= r_right <= r_hi):
            continue
        c0 = tt[i] - d2[i]
        j1 = int(np.searchsorted(tt, c0 - 0.4 * f))
        seg_l = ysub[j1:j1 + 2 * w]
        r_left = (float(seg_l.max()) / h1) if seg_l.size else 0.0
        if r_right < 1.3 * max(r_left, 1e-6):
            continue
        out["hits"] += 1
        out["ratios"].append(round(r_right, 3))

    if out["hits"] >= 2 and out["hits"] >= 0.5 * out["examined"]:
        out["flagged"] = True
    elif out["hits"] == 0:
        out["flagged"] = False
    return out
