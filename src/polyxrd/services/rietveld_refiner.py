"""
Rietveld精修服务
================
封装GSAS-II和powerxrd的Rietveld精修功能。
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.peak import Peak
from polyxrd.models.phase import Phase, LatticeParams
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData


class RietveldRefiner:
    """Rietveld结构精修服务

    支持两种精修引擎:
    - GSAS-II: 专业Rietveld精修软件 (通过GSASIIscriptable API)
    - powerxrd: Python实现的轻量级精修

    精修策略:
    - sequential: 顺序精修 (背景→晶格→原子)
    - auto: 自动精修
    - manual: 手动控制
    """

    def __init__(self) -> None:
        self._config = get_config()

    def refine(
        self,
        data: XRDData,
        phases: list[Phase],
        strategy: str = "sequential",
        engine: str = "gsas2",
        max_cycles: int = 20,
        **kwargs,
    ) -> RefinementResult:
        """执行Rietveld精修

        Args:
            data: 实验XRD数据
            phases: 待精修的物相列表
            strategy: 精修策略
            engine: 精修引擎
            max_cycles: 最大精修循环数
            **kwargs: 其他参数

        Returns:
            RefinementResult
        """
        start_time = time.time()

        engines = {
            "gsas2": self._refine_gsas2,
            "powerxrd": self._refine_powerxrd,
            "builtin": self._refine_builtin,
        }

        refine_func = engines.get(engine)
        if refine_func is None:
            # 使用内置引擎作为fallback
            refine_func = self._refine_builtin

        try:
            result = refine_func(data, phases, strategy, max_cycles, **kwargs)
        except Exception:
            # 任何引擎失败时使用内置精修
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        result.time_seconds = time.time() - start_time
        return result

    # ------------------------------------------------------------------
    # GSAS-II 精修引擎
    # ------------------------------------------------------------------

    def _refine_gsas2(
        self,
        data: XRDData,
        phases: list[Phase],
        strategy: str,
        max_cycles: int,
        **kwargs,
    ) -> RefinementResult:
        """使用GSAS-II进行Rietveld精修"""
        try:
            import GSASIIscriptable as G2sc
        except ImportError:
            # GSAS-II不可用，使用内置引擎
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        # 创建项目
        gpr = G2sc.G2Project()

        # 添加数据
        hist = gpr.add_data(
            {"data": data.two_theta, "intensity": data.intensity},
            "experimental_data",
        )

        # 添加相
        for i, phase in enumerate(phases):
            phase_dict = self._phase_to_gsas2_dict(phase)
            gpr.add_phase(phase_dict, hist)

        # 设置精修参数
        rsd = gpr.add_refinement(hist, phases)

        # 执行精修
        cycles = rsd.do_refinements(max_cycles=max_cycles)

        # 收集结果
        two_theta = data.two_theta
        simulated = rsd.get_simulated()
        residuals = rsd.get_residuals()
        wR = rsd.get_wR()
        GOF = rsd.get_GOF()

        # 获取精修后的相参数
        refined_phases = self._get_refined_phases(gpr, phases)

        return RefinementResult(
            phases=refined_phases,
            observed_data=(two_theta, data.intensity),
            simulated_data=(two_theta, simulated),
            residual_data=(two_theta, residuals),
            wR=wR,
            GOF=GOF,
            quality="",
            num_cycles=cycles,
            converged=cycles < max_cycles,
        )

    # ------------------------------------------------------------------
    # powerxrd 精修引擎
    # ------------------------------------------------------------------

    def _refine_powerxrd(
        self,
        data: XRDData,
        phases: list[Phase],
        strategy: str,
        max_cycles: int,
        **kwargs,
    ) -> RefinementResult:
        """使用powerxrd进行精修"""
        try:
            from powerxrd import Rietveld
        except ImportError:
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        # 构建Rietveld对象
        rvd = Rietveld(
            data.two_theta,
            data.intensity,
            wavelength=data.wavelength,
        )

        # 添加相
        for phase in phases:
            if phase.lattice:
                rvd.add_phase(
                    phase.lattice.a,
                    phase.lattice.b,
                    phase.lattice.c,
                    phase.lattice.alpha,
                    phase.lattice.beta,
                    phase.lattice.gamma,
                    phase.atomic_sites,
                    phase.weight_fraction,
                )

        # 执行精修
        result = rvd.refine(max_cycles=max_cycles)

        refined_phases = []
        for i, phase in enumerate(phases):
            if i < len(result.phases):
                rp = Phase(
                    name=phase.name,
                    formula=phase.formula,
                    lattice=LatticeParams(
                        a=result.phases[i].a,
                        b=result.phases[i].b,
                        c=result.phases[i].c,
                        alpha=result.phases[i].alpha,
                        beta=result.phases[i].beta,
                        gamma=result.phases[i].gamma,
                    ),
                    weight_fraction=result.phases[i].weight_fraction,
                )
                refined_phases.append(rp)

        return RefinementResult(
            phases=refined_phases,
            observed_data=(data.two_theta, data.intensity),
            simulated_data=(data.two_theta, result.simulated),
            residual_data=(data.two_theta, result.residuals),
            wR=result.wR,
            GOF=result.GOF,
            quality="",
            num_cycles=result.cycles,
            converged=result.converged,
        )

    # ------------------------------------------------------------------
    # 内置精修引擎 (最小实现)
    # ------------------------------------------------------------------

    def _refine_builtin(
        self,
        data: XRDData,
        phases: list[Phase],
        strategy: str,
        max_cycles: int,
        **kwargs,
    ) -> RefinementResult:
        """内置精修引擎 (v2 改进版)

        关键改进 (相对 v1):
        1) 每个物相参考峰单独归一化 (max I=100)，防止单相 1000 vs 200 强度不平衡
           导致 weight * scale 耦合退化
        2) 智能初始化 weights: 基于实验谱在每个单相最强峰 2θ 的真实强度
           比例估计，而非均一分布
        3) 引入 zero_shift 作为真拟合参数 (之前有字段但未加入)
        4) 多起点最小二乘 (3 个启动向量): 默认起点 / 估计起点 / 反向权重起点
           避免 least_squares 在 nfev=9 就陷入局部最优
        5) 增加 weight 的上界约束 (每个 weight ≤30), 避免"单相权重无限膨胀"吸收 scale
        """
        from scipy.optimize import least_squares

        two_theta = data.two_theta
        intensity = data.intensity
        wavelength = data.wavelength

        peak_shape = kwargs.get("peak_shape", "pseudo-voigt")
        init_fwhm = kwargs.get("fwhm", 0.15)
        bg_method = kwargs.get("bg_method", "median")  # v4: median → 显著优于 snip
        init_zero_shift = kwargs.get("zero_shift", 0.0)
        use_caglioti = kwargs.get("use_caglioti", True)
        # n_starts: Caglioti 开启时缩到 4 起点 (快速)
        n_starts_default = 5 if not use_caglioti else 4
        n_starts = kwargs.get("n_starts", n_starts_default)

        # ── 1. 背景估计 (v3: SNIP 窗宽增大, 避免削峰引入假残差) ──
        bg = self._estimate_background(intensity, bg_method, wide_window=True)
        y_exp = intensity - bg
        y_exp_pos = np.where(y_exp > 0, y_exp, 0.0).astype(float)
        y_floor = max(float(np.median(y_exp_pos)) * 0.05, 1.0)

        # ── 2. 参考峰收集 (v2 不做全局归一化, 避免破坏 wR 分子分母比例一致性)
        #    仅对每个物相做参考峰完整性检查; 原内置库中的参考峰强度已可比较
        phase_peaks = []
        for phase in phases:
            ref_peaks = phase.get_reference_peaks() if hasattr(phase, 'get_reference_peaks') else []
            if not ref_peaks:
                ref_peaks = getattr(phase, 'reference_peaks', [])
            phase_peaks.append(ref_peaks)

        n_phases = len(phases)
        # v6: params = weights(n) + fwhm + eta + scale + zero_shift + U + V + W (Caglioti)
        n_params = n_phases + 7
        if not use_caglioti:
            n_params = n_phases + 4

        # ── 3. 智能权重估计 ──────────────────────────────────────
        # 对每个物相，找到其参考峰最接近实验最大峰处的实验强度比
        # 作为权重初值
        estimated_weights = np.ones(n_phases) / n_phases
        try:
            exp_max_idx = int(np.argmax(y_exp_pos))
            exp_max_tth = two_theta[exp_max_idx]
            exp_max_val = y_exp_pos[exp_max_idx] + 1e-6

            # 统计每个物相最强参考峰的位置（在测量范围内）
            peak_signals = []
            for peaks in phase_peaks:
                if not peaks:
                    peak_signals.append(1.0)
                    continue
                in_range = [p for p in peaks
                            if len(p) >= 3 and two_theta[0] <= p[1] <= two_theta[-1]]
                if not in_range:
                    peak_signals.append(1.0)
                    continue
                # 按实验 y_exp 在各参考峰 2θ 处的 最近邻采样强度之和 作估计
                s = 0.0
                for p in in_range:
                    idx = int(np.searchsorted(two_theta, p[1]))
                    idx = min(max(idx, 0), len(two_theta) - 1)
                    # 最近邻 + 两侧取平均（更稳）
                    lo = max(0, idx - 1)
                    hi = min(len(two_theta) - 1, idx + 1)
                    s += float(np.mean(y_exp_pos[lo:hi + 1])) * (p[2] / 100.0)
                peak_signals.append(max(s, 1e-6))

            total_sig = sum(peak_signals)
            if total_sig > 0:
                estimated_weights = np.array([s / total_sig for s in peak_signals])
        except Exception:
            pass  # 回退均一分布

        # 初始 scale 估计：让 max(weight * phase_sim_max) ≈ exp_max_val
        try:
            init_scale_est = 1.0
            tmp_cag = (0.0, 0.0, init_fwhm ** 2) if use_caglioti else None
            tmp_sim = self._compute_spectrum_from_ref(
                two_theta, phase_peaks, estimated_weights,
                init_fwhm, 0.5, 1.0, peak_shape, caglioti=tmp_cag
            )
            sim_max = float(np.max(tmp_sim)) + 1e-6
            init_scale_est = exp_max_val / sim_max
            init_scale_est = max(0.01, min(1000.0, init_scale_est))
        except Exception:
            init_scale_est = 1.0

        # Caglioti 初值: W ≈ fwhm^2, U 和 V 初值 0 (典型 UVW: U=0.01, V=-0.005, W=0.02)
        init_W = init_fwhm ** 2
        init_U = kwargs.get("U", 0.005)
        init_V = kwargs.get("V", -0.001)

        # ── 4. 构建多起点 x0 候选 ────────────────────────────────
        def _make_x0(weights, fwhm, eta, scale, zs, U=None, V=None, W=None):
            parts = [np.asarray(weights, float),
                     [float(fwhm), float(eta), float(scale), float(zs)]]
            if use_caglioti:
                parts.append([float(U if U is not None else init_U),
                              float(V if V is not None else init_V),
                              float(W if W is not None else init_W)])
            return np.concatenate(parts)

        candidates = []
        # 起点 1: 估计权重 + 估计 scale + Caglioti 基准
        w_est = np.array(estimated_weights) * 1.0
        candidates.append(_make_x0(w_est, init_fwhm, 0.5, init_scale_est, init_zero_shift))
        # 起点 2: 均一权重 + U=V=0 (退化为固定 FWHM)
        candidates.append(_make_x0(np.ones(n_phases) / n_phases,
                                   init_fwhm, 0.5, init_scale_est, init_zero_shift,
                                   U=0.0, V=0.0, W=init_W))
        # 起点 3: 反向权重
        if n_phases >= 2:
            w_rev = np.flip(w_est)
            w_rev = w_rev / max(1e-9, float(w_rev.sum()))
            candidates.append(_make_x0(w_rev, init_fwhm, 0.5, init_scale_est, init_zero_shift))
        else:
            candidates.append(_make_x0(w_est, init_fwhm * 1.3, 0.7,
                                       init_scale_est * 1.2, init_zero_shift,
                                       U=0.008, V=-0.002, W=init_W*1.1))
        # 起点 4: scale 偏大 1.5x, 较大 FWHM
        candidates.append(_make_x0(w_est, init_fwhm * 0.9, 0.3,
                                   init_scale_est * 1.5, init_zero_shift,
                                   U=0.002, V=-0.0005, W=init_W))
        # 起点 5: scale 偏小 0.5x
        candidates.append(_make_x0(w_est, init_fwhm * 1.1, 0.7,
                                   init_scale_est * 0.5, init_zero_shift,
                                   U=0.01, V=-0.004, W=init_W))
        candidates = candidates[:n_starts]

        # ── 5. 参数边界 ──────────────────────────────────────────
        weight_upper = 30.0 if n_phases >= 2 else 1000.0
        lower_parts = [np.zeros(n_phases),
                       np.array([0.02, 0.0, 0.001, -0.5])]
        upper_parts = [np.ones(n_phases) * weight_upper,
                       np.array([2.0, 1.0, 10000.0, 0.5])]
        if use_caglioti:
            # U/V/W 范围: 经验合理 (FWHM 为正值的 2θ 依赖宽度系数)
            lower_parts.append(np.array([-0.05, -0.10, 1e-4]))
            upper_parts.append(np.array([0.20, 0.10, 4.0]))
        lower = np.concatenate(lower_parts)
        upper = np.concatenate(upper_parts)

        def _unpack(params):
            weights = params[:n_phases]
            fwhm = params[n_phases]
            eta = params[n_phases + 1]
            scale = params[n_phases + 2]
            zs = params[n_phases + 3]
            if use_caglioti:
                U_p = params[n_phases + 4]
                V_p = params[n_phases + 5]
                W_p = params[n_phases + 6]
                return weights, fwhm, eta, scale, zs, (U_p, V_p, W_p)
            return weights, fwhm, eta, scale, zs, None

        def residual(params):
            weights, fwhm, eta, scale, zs, cag = _unpack(params)
            eff_two_theta = two_theta - zs if abs(zs) > 1e-9 else two_theta
            simulated = self._compute_spectrum_from_ref(
                eff_two_theta, phase_peaks, weights, fwhm, eta, scale, peak_shape,
                caglioti=cag
            )
            return y_exp - simulated

        # ── 6. 多起点最小二乘，取最终 wR 最优者 ──────────────
        best_result = None
        best_wR = float("inf")
        best_simulated = None

        for x0_i in candidates:
            x0_clipped = np.clip(x0_i, lower + 1e-8, upper - 1e-8)
            try:
                res_opt = least_squares(
                    residual, x0_clipped, bounds=(lower, upper),
                    max_nfev=max_cycles * 20,
                    method="trf",
                    loss="linear",
                )
            except Exception:
                continue

            # 计算该起点的 wR
            opt_w, opt_fw, opt_et, opt_sc, opt_zs, opt_cag = _unpack(res_opt.x)
            eff = two_theta - opt_zs if abs(opt_zs) > 1e-9 else two_theta
            sim_i = self._compute_spectrum_from_ref(
                eff, phase_peaks, opt_w, opt_fw, opt_et, opt_sc, peak_shape,
                caglioti=opt_cag
            )
            wr_i = self._calc_wR(intensity, sim_i + bg)

            if wr_i < best_wR:
                best_wR = wr_i
                best_result = res_opt
                best_simulated = sim_i

        if best_result is None:
            # 退化: 直接返回起点拟合
            best_result = least_squares(
                residual, candidates[0], bounds=(lower, upper),
                max_nfev=max_cycles * 20, method="trf",
            )
            _w, _fw, _et, _sc, _zs, _cag = _unpack(best_result.x)
            best_simulated = self._compute_spectrum_from_ref(
                two_theta, phase_peaks, _w, _fw, _et, _sc, peak_shape,
                caglioti=_cag
            )

        # ── 7. v7 局部抛光 (性能+效果平衡) ───────────────────────
        #    取 24 个手工方向 + 9 个 Caglioti 调整方向，而不是 3^8 网格
        try:
            cur_x = np.array(best_result.x, dtype=float)
            best_polish_x = cur_x.copy()
            # 各参数步长（相对值）
            w_mult  = [0.9, 1.0, 1.1]
            fw_mult = [0.92, 1.0, 1.08]
            sc_mult = [0.92, 1.0, 1.08]
            et_mult = [0.9, 1.0, 1.1]
            zs_mult = [0.5, 1.0, 1.5]
            # Caglioti 方向
            if use_caglioti:
                U_V_W_mult = [
                    (1.0, 1.0, 1.0),
                    (0.5, 1.0, 1.0), (1.5, 1.0, 1.0),  # U
                    (1.0, 0.5, 1.0), (1.0, 1.5, 1.0),  # V
                    (1.0, 1.0, 0.95), (1.0, 1.0, 1.05), # W
                    (0.0, 0.0, 1.0),                     # 退化为固定 FWHM
                    (0.02, -0.01, 0.9 * max(cur_x[n_phases + 6] / 1e-9, 1.0)),  # 典型仪器展宽
                ]
            else:
                U_V_W_mult = [(None, None, None)]

            # 构建一个紧凑采样: 对 fw × sc 做 3×3，其余参数默认，eta × zs 采样时再叠 Caglioti
            for fw_m in fw_mult:
                for sc_m in sc_mult:
                    for w_m in w_mult:
                        for et_m in et_mult:
                            for zs_m in zs_mult:
                                for (Um, Vm, Wm) in U_V_W_mult:
                                    w_grp = cur_x[:n_phases] * w_m
                                    fw_i = cur_x[n_phases] * fw_m
                                    et_i = max(0.0, min(1.0, cur_x[n_phases + 1] * et_m))
                                    sc_i = cur_x[n_phases + 2] * sc_m
                                    zs_i = cur_x[n_phases + 3] * zs_m
                                    core = np.concatenate([w_grp, [fw_i, et_i, sc_i, zs_i]])
                                    if use_caglioti:
                                        # Um/Vm 为系数乘; Wm 乘. 若 Um 非数值用定值 (0)
                                        if isinstance(Um, (int, float)):
                                            U_i = cur_x[n_phases + 4] * Um if abs(cur_x[n_phases + 4]) > 1e-9 else Um
                                            V_i = cur_x[n_phases + 5] * Vm if abs(cur_x[n_phases + 5]) > 1e-9 else Vm
                                            if abs(Wm) < 1e-6 or not isinstance(Wm, (int, float)):
                                                W_i = cur_x[n_phases + 6]
                                            else:
                                                W_i = cur_x[n_phases + 6] * Wm
                                        else:
                                            U_i, V_i, W_i = cur_x[n_phases + 4], cur_x[n_phases + 5], cur_x[n_phases + 6]
                                        x_t = np.concatenate([core, [U_i, V_i, W_i]])
                                    else:
                                        x_t = core
                                    # 进一步稀疏: 保留 (fw==1 或 sc==1) 且 (w==1 或 zs==1) 交集约 1/3
                                    if not ((abs(fw_m - 1.0) < 1e-6 or abs(sc_m - 1.0) < 1e-6) and
                                            (abs(w_m - 1.0) < 1e-6 or abs(zs_m - 1.0) < 1e-6)):
                                        continue
                                    x_t = np.clip(x_t, lower + 1e-9, upper - 1e-9)
                                    _uw, _ufw, _uet, _usc, _uzs, _ucag = _unpack(x_t)
                                    eff_t = two_theta - _uzs if abs(_uzs) > 1e-9 else two_theta
                                    sim_t = self._compute_spectrum_from_ref(
                                        eff_t, phase_peaks, _uw, _ufw, _uet, _usc, peak_shape,
                                        caglioti=_ucag
                                    )
                                    wr_t = self._calc_wR(intensity, sim_t + bg)
                                    if wr_t < best_wR:
                                        best_wR = wr_t
                                        best_polish_x = x_t
                                        best_simulated = sim_t
            best_result_x = best_polish_x
        except Exception:
            best_result_x = best_result.x

        # ── 8. 提取最终结果 ──────────────────────────────────────
        opt_weights, opt_fwhm, opt_eta, opt_scale, opt_zero_shift, opt_cag = _unpack(best_result_x)

        # 归一化权重为百分比
        total_w = np.sum(opt_weights)
        weight_pcts = (opt_weights / total_w * 100.0) if total_w > 0 else opt_weights

        # 最终模拟谱
        simulated_full = best_simulated + bg
        residuals = intensity - simulated_full
        wR = best_wR

        # GOF
        n_points = len(intensity)
        n_free = max(1, n_points - n_params)
        ss_res = np.sum(residuals ** 2)
        GOF = float(np.sqrt(ss_res / n_free) / (np.mean(np.abs(intensity)) + 1e-10))

        # 质量等级
        if wR < 5:
            quality = "优秀"
        elif wR < 10:
            quality = "良好"
        elif wR < 20:
            quality = "可接受"
        else:
            quality = "需改进"

        # 构建精修后物相
        refined_phases = []
        for i, phase in enumerate(phases):
            lat = phase.lattice if phase.lattice else LatticeParams()
            refined_phases.append(Phase(
                name=phase.name,
                formula=phase.formula,
                lattice=LatticeParams(
                    a=lat.a, b=lat.b, c=lat.c,
                    alpha=lat.alpha, beta=lat.beta, gamma=lat.gamma,
                ),
                weight_fraction=float(weight_pcts[i]),
            ))

        converged = bool(getattr(best_result, "success", True))
        num_cycles = int(getattr(best_result, "nfev", 0))

        return RefinementResult(
            phases=refined_phases,
            observed_data=(two_theta, intensity),
            simulated_data=(two_theta, simulated_full),
            residual_data=(two_theta, residuals),
            wR=wR,
            GOF=GOF,
            quality=quality,
            num_cycles=num_cycles,
            converged=converged,
            fit_params={
                "engine": "builtin",
                "strategy": strategy,
                "peak_shape": peak_shape,
                "fwhm": float(opt_fwhm),
                "eta": float(opt_eta),
                "scale": float(opt_scale),
                "zero_shift": float(opt_zero_shift),
                "bg_method": bg_method,
                "multistart": n_starts,
                "weight_upper": weight_upper,
                "caglioti": (tuple(float(x) for x in opt_cag) if opt_cag is not None else None),
            },
        )

    def _estimate_background(
        self, intensity: np.ndarray, method: str = "snip", wide_window: bool = False
    ) -> np.ndarray:
        """估计背景线. wide_window=True 时使用更宽 SNIP 窗避免削峰"""
        n = len(intensity)
        if method == "snip":
            window = max(5, n // 20 if wide_window else n // 50)
            bg = np.zeros(n)
            for i in range(n):
                start = max(0, i - window // 2)
                end = min(n, i + window // 2 + 1)
                bg[i] = np.min(intensity[start:end])
            from scipy.ndimage import uniform_filter1d
            bg = uniform_filter1d(bg, size=window)
        elif method == "median":
            from scipy.signal import medfilt
            bg = medfilt(intensity, kernel_size=min(51, n // 4 * 2 + 1))
        elif method == "rolling":
            window = max(5, n // 20 if wide_window else n // 50)
            bg = np.minimum.accumulate(intensity.reshape(-1))
            from scipy.ndimage import uniform_filter1d
            bg = uniform_filter1d(bg, size=window)
        else:
            window = max(5, n // 20 if wide_window else n // 50)
            bg = np.zeros(n)
            for i in range(n):
                start = max(0, i - window // 2)
                end = min(n, i + window // 2 + 1)
                bg[i] = np.min(intensity[start:end])
            from scipy.ndimage import uniform_filter1d
            bg = uniform_filter1d(bg, size=window)
        return bg

    def _compute_spectrum_from_ref(
        self,
        two_theta: np.ndarray,
        phase_peaks: list,
        weights: np.ndarray,
        fwhm: float,
        eta: float,
        scale: float,
        peak_shape: str = "pseudo-voigt",
        caglioti: tuple = None,  # (U, V, W) FWHM² = U tan²θ + V tanθ + W；None 时退化为固定 FWHM
    ) -> np.ndarray:
        """从参考峰计算模拟谱

        v6: 支持 Caglioti 峰宽函数 (仪器展宽 + 样品展宽 2θ 依赖)
        FWHM(2θ) = sqrt(U tan²θ + V tanθ + W)
        若 U=V=0，则 FWHM=sqrt(W) 等价固定 FWHM；与旧代码一致
        """
        simulated = np.zeros_like(two_theta)

        # ── 预计算每个 2θ 点的 sigma / gamma ─────────────────────
        if caglioti is not None and any(caglioti):
            U, V, W = caglioti
            # 正切 (避免除零)
            safe = np.where(np.abs(two_theta - 90.0) < 0.01, 90.01, two_theta)
            tan_theta = np.tan(np.radians(safe / 2.0))  # tan(θ), θ = 2θ/2
            fwhm_sq = np.clip(U * tan_theta * tan_theta + V * tan_theta + W, 0.0001, None)
            fwhm_arr = np.sqrt(fwhm_sq)
            sigma_arr = fwhm_arr / (2.0 * np.sqrt(2.0 * np.log(2.0)))
            gamma_arr = fwhm_arr / 2.0
            # 为每个参考峰在其 2θ 位置取 FWHM
            peak_wise = True
        else:
            peak_wise = False
            sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
            gamma = fwhm / 2.0

        for i, peaks in enumerate(phase_peaks):
            w = weights[i] * scale
            for peak_data in peaks:
                if len(peak_data) >= 3:
                    hkl, peak_2theta, ref_intensity = peak_data[0], peak_data[1], peak_data[2]
                else:
                    continue

                if peak_2theta < two_theta[0] or peak_2theta > two_theta[-1]:
                    continue

                if peak_wise:
                    # 在参考峰 2θ 位置计算局部 FWHM
                    tan_p = np.tan(np.radians(peak_2theta / 2.0))
                    fw_p = float(np.clip(U*tan_p*tan_p + V*tan_p + W, 0.0001, None)) ** 0.5
                    sigma_p = fw_p / (2.0 * np.sqrt(2.0 * np.log(2.0)))
                    gamma_p = fw_p / 2.0
                    delta = two_theta - peak_2theta
                    gauss = np.exp(-0.5 * (delta / sigma_p) ** 2)
                    lorentz = gamma_p**2 / (delta ** 2 + gamma_p**2)
                else:
                    delta = two_theta - peak_2theta
                    gauss = np.exp(-0.5 * (delta / sigma) ** 2)
                    lorentz = gamma**2 / (delta ** 2 + gamma**2)

                if peak_shape == "gaussian":
                    profile = gauss
                elif peak_shape == "lorentzian":
                    profile = lorentz
                elif peak_shape == "voigt":
                    profile = eta * gauss + (1 - eta) * lorentz
                else:  # pseudo-voigt
                    profile = eta * gauss + (1 - eta) * lorentz

                simulated += w * ref_intensity * profile

        return simulated

    def _compute_spectrum(
        self,
        two_theta: np.ndarray,
        wavelength: float,
        phase_params: list[dict],
    ) -> np.ndarray:
        """计算模拟XRD谱

        使用简化的pseudo-Voigt峰形模型。
        """
        simulated = np.zeros_like(two_theta)

        total_weight = sum(pp["weight"] for pp in phase_params)
        if total_weight == 0:
            total_weight = 1.0

        for pp in phase_params:
            # 从晶格参数计算峰位
            peaks_2theta = self._calc_peak_positions(
                pp["a"], pp["b"], pp["c"],
                pp["alpha"], pp["beta"], pp["gamma"],
                wavelength, two_theta.min(), two_theta.max(),
            )

            weight_frac = pp["weight"] / total_weight

            for peak_2theta in peaks_2theta:
                # pseudo-Voigt峰形
                fwhm = pp["fwhm"]
                eta = pp["eta"]
                sigma = fwhm / 2.355
                gamma = fwhm / 2.0

                # 高斯部分
                gauss = np.exp(-0.5 * ((two_theta - peak_2theta) / sigma) ** 2)
                # 洛伦兹部分
                lorentz = gamma**2 / ((two_theta - peak_2theta) ** 2 + gamma**2)
                # 混合
                peak_shape = eta * gauss + (1 - eta) * lorentz

                simulated += weight_frac * peak_shape * 100

        return simulated

    def _calc_peak_positions(
        self,
        a: float, b: float, c: float,
        alpha: float, beta: float, gamma: float,
        wavelength: float,
        two_theta_min: float,
        two_theta_max: float,
    ) -> list[float]:
        """从晶格参数计算允许的衍射峰位置

        使用简化的立方晶系近似或通用公式。
        """
        from polyxrd.utils.math_utils import two_theta_to_d, d_to_two_theta

        # 生成一组Miller指数 (hkl)
        hkl_list = []
        for h in range(-3, 4):
            for k in range(-3, 4):
                for l in range(-3, 4):
                    if h == 0 and k == 0 and l == 0:
                        continue
                    hkl_list.append((h, k, l))

        # 简化：计算每个hkl的d-spacing (假设立方或用1/d²公式)
        two_theta_positions = []
        two_theta_min_rad = np.radians(two_theta_min / 2.0)
        two_theta_max_rad = np.radians(two_theta_max / 2.0)

        for h, k, l in hkl_list:
            # 通用晶胞的d-spacing计算
            d = self._calc_d_spacing_from_hkl(
                a, b, c, alpha, beta, gamma, h, k, l
            )
            if d <= 0:
                continue

            # 检查是否在2θ范围内
            sin_theta = wavelength / (2.0 * d)
            if 0 < sin_theta <= 1:
                theta = np.arcsin(sin_theta)
                peak_2theta = 2 * np.degrees(theta)
                if two_theta_min <= peak_2theta <= two_theta_max:
                    two_theta_positions.append(peak_2theta)

        # 去重并排序 (去除过近的峰)
        if two_theta_positions:
            two_theta_positions.sort()
            filtered = [two_theta_positions[0]]
            for pos in two_theta_positions[1:]:
                if pos - filtered[-1] > 0.05:  # 峰间距 > 0.05°
                    filtered.append(pos)
            return filtered[:50]  # 最多返回50个峰

        return []

    @staticmethod
    def _calc_d_spacing_from_hkl(
        a: float, b: float, c: float,
        alpha: float, beta: float, gamma: float,
        h: int, k: int, l: int,
    ) -> float:
        """从Miller指数和晶胞参数计算d-spacing

        使用一般三斜晶胞公式。
        """
        alpha_r = np.radians(alpha)
        beta_r = np.radians(beta)
        gamma_r = np.radians(gamma)

        cos_a = np.cos(alpha_r)
        cos_b = np.cos(beta_r)
        cos_g = np.cos(gamma_r)
        sin_a = np.sin(alpha_r)
        sin_b = np.sin(beta_r)
        sin_g = np.sin(gamma_r)

        volume = a * b * c * np.sqrt(
            1 - cos_a**2 - cos_b**2 - cos_g**2 + 2 * cos_a * cos_b * cos_g
        )

        # 1/d² 公式 (通用)
        inv_d_sq = (
            (h**2 * sin_a**2) / a**2
            + (k**2 * sin_b**2) / b**2
            + (l**2 * sin_g**2) / c**2
            + (2 * k * l * (cos_b * cos_g - cos_a)) / (b * c)
            + (2 * h * l * (cos_a * cos_g - cos_b)) / (a * c)
            + (2 * h * k * (cos_a * cos_b - cos_g)) / (a * b)
        )

        if inv_d_sq <= 0:
            return 0.0

        # d = 1 / sqrt(1/d²)
        # 对于立方晶系: inv_d_sq = (h²+k²+l²)/a², d = a/sqrt(h²+k²+l²)
        # 对 Si(111), a=5.431: d = 5.431/sqrt(3) ≈ 3.136 Å
        return 1.0 / float(np.sqrt(inv_d_sq))

    @staticmethod
    def _calc_wR(
        observed: np.ndarray,
        simulated: np.ndarray,
        weight: Optional[np.ndarray] = None,
    ) -> float:
        """计算加权R因子

        wR = sqrt(Σ w_i (y_i - y_ci)² / Σ w_i y_i²) * 100%
        """
        if weight is None:
            weight = np.ones_like(observed)

        numerator = np.sum(weight * (observed - simulated) ** 2)
        denominator = np.sum(weight * observed ** 2)

        if denominator == 0:
            return 100.0

        return float(np.sqrt(numerator / denominator) * 100)

    def _phase_to_gsas2_dict(self, phase: Phase) -> dict:
        """将Phase转换为GSAS-II字典格式"""
        d = {
            "name": phase.name,
            "formula": phase.formula,
        }
        if phase.lattice:
            lat = phase.lattice
            d["cell"] = [lat.a, lat.b, lat.c, lat.alpha, lat.beta, lat.gamma]
        if phase.atomic_sites:
            d["atom_sites"] = phase.atomic_sites
        return d

    def _get_refined_phases(
        self,
        gpr,
        original_phases: list[Phase],
    ) -> list[Phase]:
        """从GSAS-II项目获取精修后的相参数"""
        refined = []
        for i, phase in enumerate(original_phases):
            try:
                # 尝试获取精修后的参数
                cell = gpr.get_cell(i)
                lat = LatticeParams(
                    a=cell[0], b=cell[1], c=cell[2],
                    alpha=cell[3], beta=cell[4], gamma=cell[5],
                )
                weight = gpr.get_phase_weight(i)
                refined.append(Phase(
                    name=phase.name,
                    formula=phase.formula,
                    lattice=lat,
                    weight_fraction=weight,
                ))
            except Exception:
                refined.append(phase)
        return refined

    # ── COD 本地条目加载 ──────────────────────────────────────

    def load_phase_from_cod(self, cod_id: int,
                           wavelength: float = 1.5406,
                           two_theta_range: tuple[float, float] = (10.0, 80.0)
                           ) -> Optional[Phase]:
        """从本地 COD 数据库加载物相 (Phase)，用于精修。

        等价于 ``CODLocalDatabase.get_phase()`` 的便捷封装。
        - atomic_sites 保证可导入到内置引擎（已 CIF 解析后的 dict）
        - reference_peaks 由 pymatgen XRDCalculator 计算
        - cif_path 指向磁盘上的 .cif 文件 (GSAS-II / powerxrd 直接可用)

        Args:
            cod_id: COD 条目编号
            wavelength: X 射线波长 (Cu Kα = 1.5406 Å)
            two_theta_range: reference_peaks 计算范围

        Returns:
            Phase 实例；失败返回 None
        """
        try:
            from polyxrd.services.cod_local import CODLocalDatabase
        except Exception:
            return None
        db = CODLocalDatabase()
        return db.get_phase(
            cod_id,
            wavelength=wavelength,
            two_theta_range=two_theta_range,
            use_pymatgen_peaks=True,
        )

    def cod_quick_search(
        self,
        formula: Optional[str] = None,
        elements: Optional[list[str]] = None,
        space_group: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """快速查询 COD 本地索引，返回可用于精修的候选条目列表。"""
        try:
            from polyxrd.services.cod_local import CODLocalDatabase
        except Exception:
            return []
        db = CODLocalDatabase()
        if not db.is_ready():
            return []
        entries = db.search(
            formula=formula,
            elements=elements,
            space_group=space_group,
            limit=limit,
            parse_ok_only=True,
        )
        return [
            {
                "cod_id": e.cod_id,
                "name": e.mineral_name or f"COD_{e.cod_id}",
                "formula": e.formula,
                "space_group": e.space_group,
                "space_group_number": e.space_group_number,
                "a": e.a, "b": e.b, "c": e.c,
                "volume": e.volume,
                "file": e.file,
            } for e in entries
        ]
