"""
高精度峰检测引擎 (M21 Request2)
===============================
针对旧 peak_finder.find_peaks 的两大精度缺陷重设计:

  1. 峰位锁定在数据网格 (0.02°) —— 引入亚步长(子像素)峰位精修:
     局部抛物线 + 质心 校正, 峰位精度可达 ~0.001° 量级。
  2. 无背景扣除 → 弯曲基线淹没弱峰 / 高角噪声误判 —— 引入自适应背景
     (局部极小值基线) + 自适应噪声σ阈值 + 分区域灵敏度。

流程:
  raw → 背景估计与扣除 → 找局部极大 (种子) → 过 σ 阈值筛选 →
  亚步长峰位精修(抛物线/质心) → 逐峰局部联合峰形拟合(可选, 精修
  center/FWHM/area) → PeakList。

纯逻辑、可单测, 不依赖 Qt。旧 find_peaks 保留不动。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal as sp_signal
from scipy.optimize import curve_fit

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.xrd_data import XRDData


@dataclass
class PeakDetectOptions:
    """峰检测参数。所有长度阈值默认按 2θ 度为单位, 内部换算为样本。"""

    # 背景扣除
    bg_method: str = "minima"          # "minima"(局部极小值) | "median" | "off"
    bg_window_deg: float = 2.0         # 背景估计窗口 (度), 越大基线越平滑
    bg_smooth_poly: int = 2            # 背景基线平滑多项式阶

    # 检出阈值
    sigma_threshold: float = 5.0       # 局部峰高须 > sigma_threshold × 噪声σ
    min_prominence_frac: float = 0.0   # 额外: 峰高须 > 该相对主峰比例 (0=关)
    min_signal_abs: float = 0.0        # 绝对强度下限 (背景扣除后), 0=关

    # 峰间分离 / 尺寸
    distance_deg: float = 0.10         # 两峰最小 2θ 间距 (度), 过近取强者
    min_fwhm_deg: float = 0.02         # 剔除过窄(纯噪声)峰
    max_fwhm_deg: float = 5.0          # 剔除过宽(背景漂移残留)

    # 峰位精修
    refine_mode: str = "parabola"      # "parabola"(±1样本地物线) | "centroid" | "fit"
    refine_by_fit: bool = True         # refine_mode=fit 时执行局部联合拟合

    # 噪声估计
    noise_win_deg: float = 3.0         # 局部噪声σ估计窗口 (度)

    # 波长 (d 计算)
    wavelength: float = 1.5406

    def effective_step(self, two_theta: np.ndarray) -> float:
        """估算 2θ 采样步长 (度)。"""
        if two_theta.size > 1:
            s = float(np.mean(np.diff(two_theta)))
            return s if s > 0 else 0.01
        return 0.01


def _as_samples(deg: float, step: float) -> int:
    return max(1, int(round(deg / step)))


def estimate_background(
    x: np.ndarray, y: np.ndarray, window_deg: float, method: str = "minima",
) -> np.ndarray:
    """自适应背景估计。

    - minima: 逐窗口取局部极小值再插值/平滑 —— 对 XRD 峰下方基线稳健。
    - median: 逐窗口滚动中位数 (实现简单, 但对疏峰略偏)。
    返回与 y 同长背景数组。
    """
    n = len(y)
    if n < 5:
        return np.zeros_like(y, dtype=float)
    step = float(np.mean(np.diff(x))) if n > 1 else 0.01
    w = _as_samples(window_deg, step)
    w = max(1, min(w, n - 1))
    if method == "off":
        return np.zeros_like(y, dtype=float)
    if method == "median":
        # 奇窗口滚动中位数; 窗口须小于峰宽避免吃掉宽峰 -> 用较小倍数
        return sp_signal.medfilt(y, kernel_size=int(w) | 1)
    # minima: 每个样本取其左右 ±w/2 窗口内的极小值作候选背景点, 再样条平滑
    half = max(1, w // 2)
    # 分段取样极小值 (避免 O(n·w))
    ys = np.asarray(y, dtype=float)
    step_s = max(half // 2, 1)
    idx = list(range(0, n, step_s))
    bg_pts = []
    bg_x = []
    for i in idx:
        lo = max(0, i - half); hi = min(n, i + half + 1)
        j = lo + int(np.argmin(ys[lo:hi]))
        bg_pts.append(float(ys[j])); bg_x.append(float(x[j]))
    if len(bg_pts) < 4:
        return np.full(n, float(np.percentile(ys, 5)))
    # 单调拉低到极小包络后再平滑(过峰区)
    bg_arr = np.interp(x, bg_x, bg_pts)
    # 二次 Savitzky-Golay 平滑背景 (宽度 ~ w//2)
    sw = max(5, int(w // 2))
    if sw % 2 == 0:
        sw += 1
    sw = min(sw, n - 1 if (n - 1) % 2 == 0 else n - 2)
    if sw >= 5 and n > sw:
        try:
            bg_arr = sp_signal.savgol_filter(bg_arr, sw, 2)
        except Exception:
            pass
    # 背景不低于信号最小值 (避免负背景)
    return np.clip(bg_arr, float(np.min(ys)), None)


def estimate_noise_sigma(ys: np.ndarray, window_deg: float, step: float) -> np.ndarray:
    """逐点局部噪声σ估计: 用残差(信号-滚动中位数)的 MAD→σ 滚动。

    返回与 ys 同长的 σ 数组, 供阈值在高低噪区自适应。
    """
    n = len(ys)
    w = _as_samples(window_deg, step)
    w = max(3, (w | 1))
    if n < w + 4:
        return np.full(n, max(float(np.std(ys)) * 0.5, 1e-6))
    med = sp_signal.medfilt(ys, kernel_size=min(w, n - 1 if (n - 1) % 2 == 1 else w))
    resid = ys - med
    # 滚动 MAD (绝对中位差) → σ = 1.4826·MAD
    # 用均匀卷积近似滚动窗口绝对中位数成本高; 改分块: 整谱一个基线σ + 每区缩放
    # 简化稳健实现: 全谱 MAD 做基准, 再按局部 std 比率调制
    mad = float(np.median(np.abs(resid - np.median(resid)))) + 1e-9
    base_sigma = 1.4826 * mad
    # 局部标准差 (窗口), 用于捕捉噪声剧烈变化区
    wloc = max(7, min(int(w * 0.5) | 1, n - 1))
    k = np.ones(wloc) / wloc
    local_var = np.convolve(resid ** 2, k, mode="same")
    local_std = np.sqrt(np.maximum(local_var, 0.0))
    local_std = np.maximum(local_std, base_sigma * 0.5)
    # σ 平滑下限 = base, 上限抑制峰区虚高 (峰处 local_std 大但那是信号)
    sigma = np.minimum(local_std, base_sigma * 4.0)
    sigma = np.maximum(sigma, base_sigma)
    return np.asarray(sigma, dtype=float)


def _parabola_vertex(x0: float, x1: float, x2: float,
                     y0: float, y1: float, y2: float) -> tuple[float, float]:
    """三点抛物线顶点 (亚步长峰位)。返回 (x_vertex, y_vertex)。"""
    denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
    if abs(denom) < 1e-12:
        return x1, y1
    a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
    b = (x2 * x2 * (y0 - y1) + x1 * x1 * (y2 - y0) + x0 * x0 * (y1 - y2)) / denom
    if abs(a) < 1e-12:
        return x1, y1
    xv = -b / (2.0 * a)
    yv = a * xv * xv + b * xv + (y0 - a * x0 * x0 - b * x0)
    return float(xv), float(yv)


def _fwhm_from_hm(x: np.ndarray, y: np.ndarray, center: float, peak: float) -> float:
    """由半高求 FWHM (度): 从峰心向两侧找信号 ≤ 半高处的线性插值交点。

    稳健实现: 若一侧找不到 ≤ 半高的点 (峰截断在数据边界), 用该侧端点。
    """
    if peak <= 0:
        return float(x[-1] - x[0])  # 无意义, 返回宽值交由过滤丢弃
    half = peak * 0.5
    n = len(x)
    ic = int(np.clip(np.searchsorted(x, center), 0, n - 1))
    # 从峰心向左
    left_x = None
    for i in range(ic, 0, -1):
        if y[i] <= half < y[i - 1]:
            xa, xb = x[i - 1], x[i]
            ya, yb = y[i - 1], y[i]
            left_x = xa + (half - ya) / (yb - ya) * (xb - xa)
            break
        if y[i] <= half:   # 已进入半高以下 (无 y[i-1] 跨线), 记端点
            left_x = x[i]
            break
    if left_x is None:
        left_x = x[0]
    # 从峰心向右
    right_x = None
    for i in range(ic, n - 1):
        if y[i] >= half > y[i + 1]:
            xa, xb = x[i], x[i + 1]
            ya, yb = y[i], y[i + 1]
            right_x = xa + (half - ya) / (yb - ya) * (xb - xa)
            break
        if y[i] < half and y[i + 1] <= half:
            right_x = x[i]
            break
    if right_x is None:
        right_x = x[n - 1]
    fw = float(right_x - left_x)
    if fw <= 0:
        fw = float(x[1] - x[0]) * 2.0
    return fw


def detect_peaks_advanced(
    x: np.ndarray,
    y: np.ndarray,
    opts: Optional[PeakDetectOptions] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """高精度峰检测核心 (对 2θ/intensity 数组)。

    Returns:
      centers : 精修后峰位 (2θ)
      heights : 背景扣除后的峰高
      fwhms   : 峰 FWHM (度)
      areas   : 峰面积 (背景扣除后)
    数组按 2θ 升序。
    """
    if opts is None:
        opts = PeakDetectOptions()
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim == 0 or x.size < 3:
        return (np.array([]),) * 4
    n = x.size
    step = opts.effective_step(x)

    # 1) 背景扣除
    if opts.bg_method == "off":
        ys = y.astype(float)
    else:
        bg = estimate_background(x, y, opts.bg_window_deg, opts.bg_method)
        ys = y - bg

    # 2) 平滑(轻)以找种子, 但峰位用原信号
    sw = max(3, _as_samples(0.1, step) | 1)
    sw = min(sw, n - 1 if (n - 1) % 2 == 1 else (n if (n - 1) % 2 == 1 else sw))
    ys_s = ys
    try:
        if n > sw and sw >= 5:
            ys_s = sp_signal.savgol_filter(ys, sw, 3)
    except Exception:
        pass

    # 3) 噪声σ (自适应)
    sigma = estimate_noise_sigma(ys, opts.noise_win_deg, step)

    # 4) 找种子局部极大 (过 σ 阈值)
    ymax = float(np.max(ys)) if n else 0.0
    rel_prom = (opts.min_prominence_frac * ymax) if opts.min_prominence_frac > 0 else 0.0
    thr_sig = opts.sigma_threshold * sigma + rel_prom + opts.min_signal_abs
    d_min = _as_samples(opts.distance_deg, step)
    seeds, props = sp_signal.find_peaks(
        ys_s,
        distance=d_min,
        height=np.maximum(thr_sig, 0.0),
    )

    # 5) 亚步长峰位精修 + FWHM
    centers = []
    heights = []
    fwhms = []
    for i in seeds:
        i = int(i)
        # 抛物线
        if opts.refine_mode == "centroid":
            # 以顶点为心的 ±w 质心
            w = max(2, _as_samples(0.08, step))
            lo = max(0, i - w); hi = min(n, i + w + 1)
            seg = ys[lo:hi]
            t = np.maximum(seg, 0.0)
            s = float(np.sum(t))
            if s > 0:
                c = float(np.sum(x[lo:hi] * t) / s)
            else:
                c = float(x[i])
        else:
            if 0 < i < n - 1:
                c, _ = _parabola_vertex(x[i - 1], x[i], x[i + 1],
                                        ys[i - 1], ys[i], ys[i + 1])
                # 若抛物线越界到离谱, 回退网格
                if not (x[i - 1] <= c <= x[i + 1]):
                    c = float(x[i])
            else:
                c = float(x[i])
        h = float(np.max(ys[max(0, i - 1):min(n, i + 2)]))
        # FWHM (用扣除后信号)
        fw = _fwhm_from_hm(x, ys, c, h)
        # 尺寸过滤
        if fw < opts.min_fwhm_deg or fw > opts.max_fwhm_deg:
            continue
        centers.append(c)
        heights.append(h)
        fwhms.append(fw)

    # 6) 面积 (每峰 ±2×FWHM 积分, 扣除背景后)
    areas = []
    for c, fw in zip(centers, fwhms):
        if fw <= 0:
            areas.append(0.0); continue
        mask = np.abs(x - c) <= 2.0 * fw
        if np.sum(mask) > 1:
            areas.append(float(np.trapezoid(np.maximum(ys[mask], 0.0), x[mask])))
        else:
            areas.append(0.0)

    # 7) 可选的局部峰形拟合精修 center/FWHM (重叠峰联合)
    if opts.refine_mode == "fit" or (opts.refine_by_fit and len(centers) > 0):
        centers, fwhms = _refine_by_fit(x, ys, np.asarray(centers),
                                        np.asarray(fwhms), np.asarray(heights), step)

    # 排序
    order = np.argsort(centers)
    return (np.asarray(centers)[order], np.asarray(heights)[order],
            np.asarray(fwhms)[order], np.asarray(areas)[order])


def _pv_model(x: np.ndarray, amp: float, center: float, fwhm: float,
              eta: float) -> np.ndarray:
    """伪 Voigt (不加背景, 峰已扣背景)。"""
    sigma = fwhm / 2.35482
    gamma = fwhm / 2.0
    g = amp * np.exp(-0.5 * ((x - center) / sigma) ** 2)
    l = amp * gamma ** 2 / ((x - center) ** 2 + gamma ** 2)
    return eta * g + (1.0 - eta) * l


def _refine_by_fit(x: np.ndarray, ys: np.ndarray, centers: np.ndarray,
                   fwhms: np.ndarray, heights: np.ndarray, step: float) -> tuple:
    """对峰区做局部多峰联合伪Voigt拟合, 精修 center/FWHM。

    思路: 每个峰取 ±max(2×FWHM, 0.6°) 窗口; 窗口内若有多个检测峰则一起拟
    (重叠簇联合, 避免单峰逐拟互相拉扯)。返回 (new_centers, new_fwhms)。
    拟合失败回退原值。
    """
    if centers.size == 0:
        return centers, fwhms
    # 按窗口聚类: 简单的窗口归并 (从低角开始)
    order = np.argsort(centers)
    cs = centers[order]; fs = fwhms[order]; hs = heights[order]
    used = np.zeros(cs.size, dtype=bool)
    new_c = list(cs)
    new_f = list(fs)
    for k in range(cs.size):
        if used[k]:
            continue
        window = 2.0 * max(fs[k], 0.05)
        window = max(window, 0.6)
        grp = [k]
        j = k + 1
        while j < cs.size and (cs[j] - cs[k]) <= window:
            grp.append(j); j += 1
        # 反向也纳入更近的低角
        j = k - 1
        while j >= 0 and (cs[k] - cs[j]) <= window:
            grp.append(j); j -= 1
        grp = sorted(set(grp))
        for g in grp:
            used[g] = True
        lo = float(np.min(cs[grp])) - 2.0 * max(float(np.max(fs[grp])), 0.05)
        hi = float(np.max(cs[grp])) + 2.0 * max(float(np.max(fs[grp])), 0.05)
        lo = max(float(x[0]), lo); hi = min(float(x[-1]), hi)
        m = (x >= lo) & (x <= hi)
        if np.sum(m) < 5:
            continue
        xx = x[m]; yy = ys[m]
        # 每峰3参: amp, center, fwhm + 共享eta
        n_grp = len(grp)
        try:
            def model(xx_, *p):
                out = np.zeros_like(xx_, dtype=float)
                n = len(p) // 3
                eta = 0.6
                for i in range(n):
                    a, c, f = p[3 * i], p[3 * i + 1], p[3 * i + 2]
                    out += _pv_model(xx_, a, c, f, eta)
                return out
            p0 = []
            low = []
            high = []
            for i in range(n_grp):
                a0 = max(hs[grp[i]], 1e-3); c0 = cs[grp[i]]; f0 = max(fs[grp[i]], 0.02)
                p0 += [a0, c0, f0]
                low += [0.0, c0 - 2.0 * f0, 0.005]
                high += [a0 * 5.0 + 1.0, c0 + 2.0 * f0, 3.0]
            popt, _ = curve_fit(model, xx, yy, p0=p0,
                                bounds=(low, high), maxfev=20000)
            for gi, i in enumerate(grp):
                new_c[i] = float(popt[3 * gi + 1])
                new_f[i] = max(float(popt[3 * gi + 2]), 0.005)
        except Exception:
            pass  # 回退未精修值
    # 恢复原始数组顺序 (调用方按需排序)
    return np.asarray(new_c), np.asarray(new_f)


def detect_peaks_from_data(
    data: XRDData,
    opts: Optional[PeakDetectOptions] = None,
) -> PeakList:
    """对 XRDData 直接调用高精度峰检测, 返回 PeakList。"""
    if opts is None:
        opts = PeakDetectOptions(wavelength=data.wavelength or 1.5406)
    if data.two_theta is None or len(data.two_theta) < 3:
        return PeakList(source="advanced")
    if np.max(data.intensity) <= 0:
        return PeakList(source="advanced")
    centers, heights, fwhms, areas = detect_peaks_advanced(
        np.asarray(data.two_theta), np.asarray(data.intensity), opts)
    wl = data.wavelength or 1.5406
    peaks = []
    for c, h, fw, ar in zip(centers, heights, fwhms, areas):
        th = np.radians(c / 2.0)
        d = (wl / (2.0 * np.sin(th))) if np.sin(th) > 0 else 0.0
        peaks.append(Peak(two_theta=float(c), intensity=float(h),
                          fwhm=float(fw), area=float(ar), d_spacing=float(d)))
    pl = PeakList(peaks=peaks, source="advanced")
    pl.sort_by_two_theta()
    return pl
