"""
Rietveld精修服务
================
封装GSAS-II和powerxrd的Rietveld精修功能。

过程日志 (v0.12.0)
------------------
调用方可以传 ``log_cb=callable(str)`` 进来, 精修过程会**边跑边**把过程数据
(引擎选择、背景估计、每个起点的 wR/nfev、抛光评估数、最终指标) 回吐给 UI,
界面就能像终端跑码一样实时显示。不传回调 = 完全静默, 行为与旧版一致。

日志文本刻意用**技术符号 + 数值** (如 ``[start 2/4] wR=52.310% nfev=57``),
不含面向用户的自然语言 —— 服务层不依赖 i18n, 界面要本地化的措辞请自己包。
"""
from __future__ import annotations

import os
import logging
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.phase import Phase, LatticeParams
from polyxrd.models.refinement import RefinementResult, quality_grade_for
from polyxrd.models.xrd_data import XRDData

logger = logging.getLogger("polyxrd.rietveld_refiner")


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

    # ── v2.0.0 (W26/W27): 分阶段精修 ────────────────────────────────────
    _MASK_ALL_ON = {
        "scale": True, "background": True, "profile": True, "cell": True,
        "zero_shift": True, "texture": True, "displacement": True,
        "b_overall": True,
    }

    @classmethod
    def _stage_schedule(cls, pipeline: str) -> list[tuple[str, dict]]:
        """阶段表: [(阶段名, param_mask)]；mask 为 None 表示全放开。"""
        off = dict(cls._MASK_ALL_ON)

        def _mask(**on) -> dict:
            m = {k: False for k in off}
            m.update(on)
            return m

        if pipeline == "le_bail_then_rietveld":
            # W26: "Le Bail 级"预处理 —— 只求把晶胞/背景/标度稳住, 轮廓与位置项先冻结
            return [
                ("stabilize", _mask(scale=True, background=True, cell=True)),
                ("full", None),
            ]
        # W27: 渐进释放 (每个阶段只放开上一阶段的增量自由度)
        return [
            ("scale_bg", _mask(scale=True, background=True)),
            ("profile", _mask(scale=True, background=True, profile=True)),
            ("positions", _mask(scale=True, background=True, profile=True,
                                zero_shift=True, displacement=True)),
            ("cell", _mask(scale=True, background=True, profile=True,
                           zero_shift=True, displacement=True, cell=True)),
            ("structure", None),   # 全放开 (含织构 / 整体 B)
        ]

    def _refine_staged(
        self, data: XRDData, phases: list[Phase], strategy: str,
        max_cycles: int, kwargs: dict,
    ) -> RefinementResult:
        """带热启动的多阶段精修 (W26 流水线 / W27 分阶段释放)。"""
        pipeline = str(kwargs.get("pipeline", "") or "").lower()
        stages = self._stage_schedule(pipeline)
        inner = dict(kwargs)
        inner["_staged_inner"] = True
        inner["release_stages"] = False
        inner.pop("pipeline", None)
        inner.pop("_x0", None)
        log = self.make_logger(kwargs)

        x0 = None
        trace: list[dict] = []
        result: Optional[RefinementResult] = None
        for name, mask in stages:
            kw = dict(inner)
            kw.pop("_x_sink", None)          # 每阶段用独立回收槽
            sink: dict = {}
            kw["_x_sink"] = sink
            kw["wR_threshold"] = None        # 阶段内不做快检早退
            kw["log_stage"] = f"[{name}] "
            if mask is not None:
                kw["_param_mask"] = dict(mask)
            if x0 is not None:
                kw["_x0"] = x0
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kw)
            trace.append({
                "stage": name,
                "wR": float(result.wR),
                "nfev": int(getattr(result, "num_cycles", 0) or 0),
                "mask": (None if mask is None else dict(mask)),
            })
            _new_x = sink.get("x")
            x0 = np.asarray(_new_x, dtype=float) if _new_x is not None else None
            log(f"[stage {name}] wR={float(result.wR):.3f}%")

        if result is None:   # 理论不可达 (阶段表非空), 保守兜底
            result = self._refine_builtin(data, phases, strategy, max_cycles,
                                          **{**inner, "_staged_inner": True})
        result.fit_params["pipeline"] = pipeline or "staged_release"
        result.fit_params["stages"] = trace
        return result

    def __init__(self) -> None:
        self._config = get_config()
        # v0.15.1: CIF → |F|² 参考峰缓存 (key 见 _cif_reference_peaks)
        self._cif_peak_cache: dict = {}
        # v2.0.0 (W23): 每相的"强度标尺"缓存 —— 未归一化的 Σ|F|²·m·LP 最大值 k
        # 与 ZMV (= 晶胞内质量 × 晶胞体积), 供质量分数定量换算使用。
        self._cif_scale_cache: dict = {}
        # 相位 → (k, ZMV) 的便捷索引 (供 _refine_builtin 取用)
        self._cif_scale_by_phase: dict = {}

    # ------------------------------------------------------------------
    # 过程日志工具 (v0.12.0)
    # ------------------------------------------------------------------

    @staticmethod
    def make_logger(kwargs: dict) -> Callable[[str], None]:
        """从 kwargs 里取出 ``log_cb`` 并包成"永不抛异常"的日志函数。

        回调抛异常不该影响精修本身 (日志是旁路), 所以这里吞掉所有异常并
        退化成空操作。
        """
        cb = kwargs.get("log_cb")
        if not callable(cb):
            return lambda _msg: None

        def _log(msg: str) -> None:
            try:
                cb(msg)
            except Exception:  # noqa: BLE001 - 日志失败不影响计算
                pass

        return _log

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
        log = self.make_logger(kwargs)

        # ── M14 options 前处理: 择优取向 (参考峰强度) / 零点初值 ──
        phases_use = phases
        opts = kwargs.get("options")
        if opts is not None:
            po = getattr(opts, "preferred_orientation", None)
            if po and abs(float(po.get("r", 1.0)) - 1.0) > 1e-9:
                d = tuple(po.get("direction", (0, 0, 1)))
                phases_use = [
                    self.apply_preferred_orientation(p, d, float(po["r"]))
                    for p in phases
                ]
            zs = float(getattr(opts, "zero_shift_init", 0.0) or 0.0)
            if abs(zs) > 1e-12:
                kwargs.setdefault("zero_shift", zs)
            # M14 参数掩码: 把 RefineOptions 的 refine_* 开关透传给引擎。
            # builtin 引擎已接入 scale/profile/zero_shift; background/cell 在
            # builtin 中为 no-op (背景为预处理、晶胞固定, 无 fit 维度)。
            kwargs["_param_mask"] = {
                "scale": bool(getattr(opts, "refine_scale", True)),
                "background": bool(getattr(opts, "refine_background", True)),
                "profile": bool(getattr(opts, "refine_profile", True)),
                "cell": bool(getattr(opts, "refine_cell", True)),
                "zero_shift": bool(getattr(opts, "refine_zero_shift", True)),
            }
        kwargs.pop("options", None)

        engines = {
            "auto": self._refine_auto,
            "gsas2": self._refine_gsas2,
            "powerxrd": self._refine_powerxrd,
            "builtin": self._refine_builtin,
            "maud": self._refine_maud,
        }

        refine_func = engines.get(engine)
        if refine_func is None:
            # 使用内置引擎作为fallback
            refine_func = self._refine_builtin

        # ── 过程日志: 起点信息 ─────────────────────────────────────
        try:
            tth = np.asarray(data.two_theta, dtype=float)
            lam = float(getattr(data, "wavelength", 0.0) or 0.0)
            log(f"[start] engine={engine} strategy={strategy} max_cycles={max_cycles}")
            log(
                f"[data] n={tth.size} 2θ={tth.min():.2f}–{tth.max():.2f}° "
                f"λ={lam:.5f} Å"
            )
            log(
                "[phase] {} phase(s): {}".format(
                    len(phases_use),
                    ", ".join(getattr(p, "name", "?") for p in phases_use),
                )
            )
        except Exception:  # noqa: BLE001 - 日志不该阻断精修
            pass

        try:
            result = refine_func(data, phases_use, strategy, max_cycles, **kwargs)
        except Exception as e:
            # 任何引擎失败时使用内置精修 (不再静默: 记录原因供 UI/调试)
            logger.warning("engine=%s refinement failed, fallback to builtin: %s", engine, e)
            log(f"[warn] engine={engine} failed: {type(e).__name__}: {e}")
            log("[warn] fallback to builtin engine")
            result = self._refine_builtin(data, phases_use, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = engine
            result.fit_params["engine_fallback_reason"] = f"{type(e).__name__}: {e}"

        result.time_seconds = time.time() - start_time
        # v1.1.2: 引擎回退不再"只在日志里" —— 记录请求/实际引擎;
        # v2.1-B: 不再往 warnings 塞中文文案, 改为结构化诊断 (UI 用 tr() 渲染)。
        try:
            _req = str(result.fit_params.get("engine_requested", engine))
            _used = str(result.fit_params.get("engine", engine))
            result.fit_params.setdefault("engine_requested", _req)
            if _used != _req:
                _reason = str(result.fit_params.get("engine_fallback_reason", "") or "unknown")
                result.diagnostics.append({
                    "code": "diag.engine_fallback",
                    "params": {"requested": _req, "used": _used, "reason": _reason},
                })
        except Exception:  # noqa: BLE001 - 提示失败不该影响精修结果
            pass
        # v1.1.2 (W19-a): 检测 Kα2 双线是否未剥离 (最强峰高角侧系统性残差)
        if kwargs.get("detect_ka2", True):
            try:
                _ka2 = self.detect_ka2(data)
            except Exception:  # noqa: BLE001
                _ka2 = None
            if _ka2 is not None and _ka2.get("flagged"):
                # v2.1-B: 结构化诊断 (code + params), 文案由 UI 渲染
                result.diagnostics.append({
                    "code": "diag.ka2_detected",
                    "params": {
                        "center": float(_ka2.get("center", 0.0)),
                        "delta": float(_ka2.get("delta", 0.0)),
                        "ratio": float(_ka2.get("ratio", 0.0)) * 100.0,
                    },
                })
                result.fit_params["ka2_detected"] = True
                result.fit_params["ka2_info"] = _ka2
        log(
            "[done] engine={} wR={:.3f}% GOF={:.3f} nfev={} t={:.1f}s".format(
                result.fit_params.get("engine", engine),
                float(result.wR),
                float(result.GOF),
                int(result.num_cycles),
                result.time_seconds,
            )
        )
        return result

    # ------------------------------------------------------------------
    # 自动引擎选择 (v0.11.0 打磨)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # v1.1.2 (W19-a): Kα2 双线检测
    # ------------------------------------------------------------------

    KA2_LAMBDA_RATIO = 1.544390 / 1.540560   # λ(Kα2)/λ(Kα1), Cu 靶

    def detect_ka2(self, data: XRDData) -> Optional[dict]:
        """检测最强峰是否为**未剥离**的 Kα1/Kα2 双线。

        原理: Kα2 峰位 ≈ 2θ + 2·(λ2/λ1 − 1)·tanθ (Cu 下 36° 处 ≈ 0.093°,
        与常见 FWHM 同量级), 强度 ≈ Kα1 的一半。

        做法 (**形状无关的对称性判据**, 比"单峰拟合看残差"稳健得多 ——
        单峰模型会靠加大 FWHM / 提高洛伦兹占比把双线吸收掉):
          取最强峰中心 c (亚步长抛物线精修) 与解析间距 Δ, 比较
              ratio = I(c + Δ) / I(c − Δ)      (扣背景后)
          对称单峰 → ratio ≈ 1; 含 0.5 强度比 Kα2 → ratio ≈ 2 以上。
          (低角轴向发散引起的固有不对称让 ratio < 1, 属安全方向。)

        若需要更详细的形态信息, 返回字典里同时给出左右强度、峰高与 FWHM 估计。

        Returns:
            ``dict(center, delta, fwhm, eta, left_res, right_res, ratio, flagged)``,
            无法判定时返回 None。检测失败绝不影响精修 (内部 try/except)。
        """
        try:
            tt = np.asarray(data.two_theta, dtype=float)
            y = np.asarray(data.intensity, dtype=float)
            if tt.size < 50:
                return None
            bg = self._estimate_background(y, "median", wide_window=True)
            ysub = np.clip(y - bg, 0.0, None)
            i0 = int(np.argmax(ysub))
            h0 = float(ysub[i0])
            if h0 <= 0 or i0 <= 0 or i0 >= tt.size - 1:
                return None
            # 亚步长峰位 (三点抛物线)
            y1, y2, y3 = float(ysub[i0 - 1]), h0, float(ysub[i0 + 1])
            denom = (y1 - 2.0 * y2 + y3)
            frac = 0.5 * (y1 - y3) / denom if abs(denom) > 1e-12 else 0.0
            frac = float(np.clip(frac, -0.5, 0.5))
            step = float(tt[i0 + 1] - tt[i0]) if tt.size > 1 else 0.01
            c0 = float(tt[i0]) + frac * step
            lam1 = float(getattr(data, "wavelength", 0.0) or 1.5406)
            if lam1 <= 0:
                lam1 = 1.5406
            theta = np.radians(c0 / 2.0)
            delta = float(2.0 * (self.KA2_LAMBDA_RATIO - 1.0)
                          * np.tan(theta) * 180.0 / np.pi)
            if not (0.0 < delta < 1.0):
                return None
            left = float(np.interp(c0 - delta, tt, ysub))
            right = float(np.interp(c0 + delta, tt, ysub))
            ratio = (right / left) if left > 1e-9 else float("inf")
            # 半高宽估计 (对称假设, 仅作参考)
            half = 0.5 * h0
            above = np.where(ysub >= half)[0]
            fwhm_est = float(tt[above[-1]] - tt[above[0]]) if above.size > 1 else 0.0
            return {
                "center": c0, "delta": delta, "peak_height": h0,
                "fwhm": fwhm_est,
                "left_res": left, "right_res": right, "ratio": ratio,
                # 判据: 高角侧比低角侧高 35% 以上, 且高角侧强度有实际量级
                "flagged": bool(ratio > 1.35 and right > 0.05 * h0),
            }
        except Exception:  # noqa: BLE001 - 检测失败不应影响精修
            return None

    @staticmethod
    def _phases_have_structure(phases: list[Phase]) -> bool:
        """全部物相都带可用结构 CIF 时才走 GSAS-II (真 Rietveld + 定量才有意义)."""
        return bool(phases) and all(
            p.cif_path and Path(p.cif_path).exists() for p in phases
        )

    def _refine_auto(
        self,
        data: XRDData,
        phases: list[Phase],
        strategy: str,
        max_cycles: int,
        **kwargs,
    ) -> RefinementResult:
        """自动引擎选择:
        全相有结构 CIF 且 GSAS-II 可用 → gsas2 (真 Rietveld + wt% 定量);
        否则回退 builtin (无结构剖面拟合), 并把原因写入 fit_params.
        """
        reasons: list[str] = []
        log = self.make_logger(kwargs)
        if self._phases_have_structure(phases):
            py = self._find_gsas2_python()
            if py is not None:
                log(f"[auto] all phases have structure CIF and GSAS-II found ({py}) -> engine=gsas2")
                try:
                    return self._refine_gsas2(
                        data, phases, strategy, max_cycles, **kwargs
                    )
                except Exception as e:
                    reasons.append(f"gsas2 run failed: {type(e).__name__}: {e}")
            else:
                reasons.append("GSAS-II install not found (E:\\GSASII)")
        else:
            reasons.append("phase without structure CIF present (builtin profile fit suffices)")

        log("[auto] -> engine=builtin (reason: " + "; ".join(reasons) + ")")
        result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
        result.fit_params["engine_requested"] = "auto"
        result.fit_params["engine_fallback_reason"] = "; ".join(reasons)
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
        """使用 GSAS-II 进行 Rietveld 精修 (子进程桥)

        GSAS-II 通过官方 gsas2main 安装器独立安装 (自带 Python + 预编译
        二进制, 与 PolyXRD 的 venv 是两套环境), 因此这里以 JSON 子进程
        方式调用 scripts/gsas2_bridge.py, 而非 in-process import。
        未安装 GSAS-II 或调用失败时回退内置引擎。
        """
        log = self.make_logger(kwargs)
        py = self._find_gsas2_python()
        bridge = Path(__file__).resolve().parents[3] / "scripts" / "gsas2_bridge.py"
        if not py or not bridge.exists():
            logger.warning("GSAS-II unavailable (py=%s, bridge exists=%s), "
                           "fallback to builtin", py, bridge.exists())
            log("[gsas2] unavailable (no python or bridge) -> fallback to builtin")
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = "gsas2"
            result.fit_params["engine_fallback_reason"] = "GSAS-II not installed or bridge missing"
            return result

        import json as _json
        import subprocess
        import tempfile

        two_theta = np.asarray(data.two_theta, dtype=float).tolist()
        intensity = np.asarray(data.intensity, dtype=float).tolist()

        req = {
            "two_theta": two_theta,
            "intensity": intensity,
            "wavelength": float(data.wavelength),
            "refine": "lattice",
            "max_cycles": int(max_cycles),
            "phases": [],
        }
        for phase in phases:
            entry: dict = {"name": phase.name}
            if phase.space_group:
                entry["spacegroup"] = phase.space_group
            if phase.cif_path and Path(phase.cif_path).exists():
                entry["cif_path"] = str(phase.cif_path)
            if phase.lattice is not None:
                entry["lattice"] = {
                    "a": phase.lattice.a, "b": phase.lattice.b,
                    "c": phase.lattice.c, "alpha": phase.lattice.alpha,
                    "beta": phase.lattice.beta, "gamma": phase.lattice.gamma,
                }
            req["phases"].append(entry)

        timeout = float(kwargs.get("gsas2_timeout", 300.0))
        log(f"[gsas2] subprocess bridge start: python={py} "
            f"timeout={timeout:.0f}s phases={len(phases)}")
        try:
            with tempfile.TemporaryDirectory(prefix="polyxrd_g2_") as td:
                req_path = str(Path(td) / "request.json")
                out_path = str(Path(td) / "output.json")
                with open(req_path, "w", encoding="utf-8") as f:
                    _json.dump(req, f)
                proc = subprocess.run(
                    [str(py), str(bridge), req_path, out_path],
                    capture_output=True, text=True, timeout=timeout,
                    env=self._gsas2_env(py),
                )
                if not Path(out_path).exists():
                    logger.warning("GSAS-II bridge produced no output.json, "
                                   "fallback to builtin")
                    log("[gsas2] bridge produced no output.json -> fallback to builtin")
                    result = self._refine_builtin(
                        data, phases, strategy, max_cycles, **kwargs
                    )
                    result.fit_params["engine_requested"] = "gsas2"
                    result.fit_params["engine_fallback_reason"] = "bridge produced no result file"
                    return result
                with open(out_path, "r", encoding="utf-8") as f:
                    out = _json.load(f)
        except Exception as e:
            logger.warning("GSAS-II subprocess error, fallback to builtin: %s", e)
            log(f"[gsas2] subprocess error: {type(e).__name__}: {e} "
                f"-> fallback to builtin")
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = "gsas2"
            result.fit_params["engine_fallback_reason"] = f"subprocess error: {e}"
            return result

        if not out.get("ok"):
            err = str(out.get("error", ""))[:300]
            logger.warning("GSAS-II bridge returned ok=False (%s), "
                           "fallback to builtin", err)
            log(f"[gsas2] bridge returned ok=False: {err} -> fallback to builtin")
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = "gsas2"
            result.fit_params["engine_fallback_reason"] = f"bridge error: {err}"
            return result

        # 收集精修后晶胞 + 定量相分数 (v0.11.0: 桥在全相有 CIF 时输出)
        refined_phases = []
        lat_by_name = {p["name"]: p.get("lattice") for p in out.get("phases", [])}
        fractions = out.get("phase_fractions")
        use_fractions = (
            isinstance(fractions, list) and len(fractions) == len(phases)
        )
        for i, phase in enumerate(phases):
            lat = phase.lattice if phase.lattice is not None else LatticeParams()
            new_lat = lat_by_name.get(phase.name) or {}
            if new_lat and new_lat.get("a") is not None:
                lat = LatticeParams(
                    a=float(new_lat["a"]), b=float(new_lat["b"]),
                    c=float(new_lat["c"]),
                    alpha=float(new_lat.get("alpha", 90.0)),
                    beta=float(new_lat.get("beta", 90.0)),
                    gamma=float(new_lat.get("gamma", 90.0)),
                )
            if use_fractions:
                try:
                    wf = float(fractions[i])
                except (TypeError, ValueError):
                    wf = phase.weight_fraction
            else:
                wf = phase.weight_fraction
            refined_phases.append(Phase(
                name=phase.name,
                formula=phase.formula,
                space_group=phase.space_group,
                lattice=lat,
                weight_fraction=wf,
                reference_peaks=phase.reference_peaks,
                elements=phase.elements,
            ))

        wR = float(out["wR"]) if out.get("wR") is not None else 100.0
        GOF = float(out["GOF"]) if out.get("GOF") is not None else 0.0
        # v1.1.2: 质量分级统一走 models.refinement.quality_grade_for (唯一入口)
        quality = quality_grade_for(wR)

        # v1.1.2: 指标口径修正 —— GSAS-II 桥只回传 wR (可能另有 GOF), **不回传 Rexp**。
        # 本地既没有 GSAS-II 的权方案也没有它的参数计数, 硬算出来的 Rexp 是错的
        # (旧实现即如此, 实测偏小 18~130 倍)。因此:
        #   桥给了 GOF → 由 Rexp = wR/GOF 反推, 标记可解读;
        #   桥没给     → Rexp/GOF 一律置 0 并标记"不可解读"。
        # 轮廓 R (Rp) 是本地可算且口径明确的量, 照常给出。
        metrics_valid = False
        # v2.1-B: metric_note 文案移出服务层 —— 不可解读原因改为结构化诊断码,
        # 由 UI/report 层用 tr() 渲染 (metric_note 字段保留用于旧项目文件兼容)。
        metric_note = ""
        _gsas_diag: list[dict] = []
        Rexp = 0.0
        Rp = 0.0
        ycalc = out.get("ycalc")
        if isinstance(ycalc, list) and len(ycalc) == len(two_theta):
            sim = np.asarray(ycalc, dtype=float)
            sim_data = (data.two_theta, sim)
            resid = (data.two_theta, np.asarray(data.intensity) - sim)
            _m = self._calc_profile_metrics(
                np.asarray(data.intensity, dtype=float), sim,
                n_params=0,
            )
            Rp = float(_m["Rp"])
            if GOF and wR > 0:
                Rexp = float(wR) / float(GOF)
                metrics_valid = True
            else:
                _gsas_diag.append({"code": "diag.metrics_no_rexp", "params": {}})
        else:
            sim_data = (data.two_theta, data.intensity)  # 旧行为
            resid = (data.two_theta, np.zeros_like(data.two_theta))
            _gsas_diag.append({"code": "diag.metrics_no_ycalc", "params": {}})

        return RefinementResult(
            phases=refined_phases,
            observed_data=(data.two_theta, data.intensity),
            simulated_data=sim_data,
            residual_data=resid,
            wR=wR,
            Rexp=Rexp,
            Rb=0.0,   # v2.0.0: Rb(Bragg R) 与 Rp(轮廓 R) 是不同概念, 不再别名
            Rp=Rp,
            metrics_valid=metrics_valid,
            metric_note=metric_note,
            diagnostics=_gsas_diag,
            GOF=GOF,
            quality=quality,
            num_cycles=int(out.get("n_cycles", max_cycles)),
            converged=bool(out.get("ok", False)),
            fit_params={
                "engine": "gsas2",
                "strategy": strategy,
                "gsas2_python": str(py),
                "gpx": out.get("gpx", ""),
                "wR": wR,
                # v0.11.0: 定量阶段结果 (全相有 CIF 时才有)
                "wR_rietveld": out.get("wR_rietveld"),
                "quantified": bool(
                    isinstance(out.get("phase_fractions"), list)
                ),
            },
        )

    @staticmethod
    def _find_gsas2_python() -> Optional[Path]:
        """定位 GSAS-II 自带 Python 解释器。

        优先级: 环境变量 POLYXRD_GSAS2_PYTHON > 常见安装目录。
        """
        env_py = os.environ.get("POLYXRD_GSAS2_PYTHON", "").strip()
        candidates = []
        if env_py:
            candidates.append(Path(env_py))
        for prefix in (
            # gsas2main 安装器默认位置 (官方推荐, 优先)
            str(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
                / "gsas2main"),
            r"D:\GSASII", r"C:\GSASII", r"E:\GSASII",
            r"D:\g2main", r"C:\g2main", r"E:\g2main",
            str(Path.home() / "GSASII"), str(Path.home() / "g2main"),
            str(Path.home() / "gsas2main"),  # gsas2main 默认安装位置
        ):
            candidates.append(Path(prefix) / "python.exe")
            candidates.append(Path(prefix) / "bin" / "python.exe")
        for cand in candidates:
            if cand.exists():
                return cand
        return None

    @staticmethod
    def _gsas2_pythonpath(py: Path) -> str:
        """返回 GSAS-II 源码目录 (含 GSASII 包的父目录)。

        老版 gsas2main 会在自身 site-packages 放 .pth 完成注册, 可直接 import;
        新版 (pixi 环境, 如 C:\\ProgramData\\gsas2main) 不自注册, 必须由调用方
        注入 PYTHONPATH, 否则 `import GSASII` 失败。
        """
        seen: list[Path] = []
        for base in (
            py.parent,
            py.parent.parent,
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "gsas2main",
        ):
            for cand in (Path(base) / "GSAS-II", Path(base)):
                if cand in seen:
                    continue
                seen.append(cand)
                if (cand / "GSASII" / "GSASIIscriptable.py").exists():
                    return str(cand)
        return ""

    @staticmethod
    def _gsas2_env(py: Path) -> dict:
        """构造调用 GSAS-II 桥的子进程环境。

        两件事:
        1. PYTHONPATH 注入 GSAS-II 源码目录 (pixi/新版 gsas2main 不自注册);
        2. PATH 注入 conda 环境内 DLL 目录 —— 否则 numpy.linalg 调用
           LAPACK 时因找不到 DLL 直接崩溃 (0xc06d007f), 表现为桥"静默失败"。
        """
        env = os.environ.copy()
        src = RietveldRefiner._gsas2_pythonpath(py)
        if src:
            old = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{src}{os.pathsep}{old}" if old else src
        root = Path(py).parent
        extra_dirs = [
            root,
            root / "Library" / "bin",
            root / "Library" / "mingw-w64" / "bin",
            root / "Library" / "usr" / "bin",
            root / "Scripts",
            root / "bin",
        ]
        found = [str(d) for d in extra_dirs if d.is_dir()]
        if found:
            old_path = env.get("PATH", "")
            env["PATH"] = os.pathsep.join(
                found + ([old_path] if old_path else [])
            )
        return env

    # ------------------------------------------------------------------
    # MAUD 精修引擎 (路线 C)
    # ------------------------------------------------------------------

    def _refine_maud(
        self,
        data: XRDData,
        phases: list[Phase],
        strategy: str,
        max_cycles: int,
        **kwargs,
    ) -> RefinementResult:
        """使用 MAUD (MaudText 批处理) 进行 Rietveld 精修

        调用 :py:class:`polyxrd.services.refinement_engines.MaudEngine`。
        失败 (缺 MAUD / 缺 CIF / 子进程崩溃 / 超时) 全部回退内置引擎,
        与 GSAS-II / powerxrd 行为一致。

        关键字:
            maud_root: 自定义 MAUD 安装根 (默认自动探测 C:\\MAUD3)
            maud_timeout: 子进程超时秒数 (默认 600)
            maud_wizard_index: wizard 步 (-1/1/3/5/8/13/999); None=MAUD 自動選
            maud_keep_workdir: True 时保留 work_dir (调试用, 默认 False)
            maud_on_progress: 进度回调 (MaudProgress → None)
            maud_cod_root: 当 phase.cod_id 给出时, COD 库根用于 CIF 映射
        """
        log = self.make_logger(kwargs)
        from polyxrd.services.refinement_engines import (
            MaudEngine,
            MaudEngineError,
        )

        # ── first-run 探测 (R-C4) ──
        # 若上一次 MAUD 跑挂 (output.par 缺 R 字段) 或压根没跑过 → 走 wizard 1
        # 强制收敛起步。否则用 MAUD 自动 wizard (None)。
        wizard = kwargs.get("maud_wizard_index")
        if wizard is None and self._maud_needs_first_run():
            wizard = 1  # 强制走 wizard 1 (scale+背景), 避免初次跑卡死

        log(f"[maud] MaudText batch start: wizard_index={wizard} "
            f"iterations={max_cycles} phases={len(phases)}")
        try:
            maud_root = kwargs.get("maud_root")
            engine = MaudEngine(
                maud_root=Path(maud_root) if maud_root else None,
            )
            result = engine.refine(
                data, list(phases),  # 引擎会就地改 phases 的 weight/lattice, 先复制防破坏
                iterations=max_cycles,
                wizard_index=wizard,
                timeout_s=float(kwargs.get("maud_timeout", 600.0)),
                keep_workdir=bool(kwargs.get("maud_keep_workdir", False)),
                on_progress=kwargs.get("maud_on_progress"),
                cod_root=Path(kwargs["maud_cod_root"]) if kwargs.get("maud_cod_root") else None,
            )
        except MaudEngineError as e:
            log(f"[maud] engine error: {e} -> fallback to builtin")
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
        except Exception as e:  # noqa: BLE001
            log(f"[maud] exception: {type(e).__name__}: {e} -> fallback to builtin")
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        # 标记 first-run 完成 (下次可走自动 wizard)
        self._maud_mark_first_run_done()
        log(f"[maud] done wR={result.wR:.3f}% nfev={result.num_cycles}")
        return result

    @staticmethod
    def _maud_needs_first_run(
        search_paths: tuple[Path, ...] = (Path("C:/MAUD3"), Path("C:/MAUD2")),
    ) -> bool:
        """探测是否需要 first-run wizard=1 (R-C4 策略).

        触发条件:
        1. 标记文件 ``~/.polyxrd/.maud_first_run_done`` 不存在
        2. 默认搜索路径下所有 ``examples/*.par`` 都不含 ``_refine_ls_wR_factor_all``

        :param search_paths: 自定义搜索根 (测试用); 默认 C:\\MAUD3 + C:\\MAUD2
        """
        flag = Path.home() / ".polyxrd" / ".maud_first_run_done"
        if flag.exists():
            return False
        for maud in search_paths:
            exdir = maud / "examples"
            if exdir.is_dir():
                for par in exdir.glob("*.par"):
                    try:
                        txt = par.read_text(encoding="utf-8", errors="replace")
                        if "_refine_ls_wR_factor_all" in txt:
                            return False
                    except OSError:
                        continue
        return True

    @staticmethod
    def _maud_mark_first_run_done() -> None:
        """写下 first-run 完成标记 (R-C4)"""
        try:
            flag = Path.home() / ".polyxrd" / ".maud_first_run_done"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(
                f"maud first-run done at {time.time():.0f}\n",
                encoding="utf-8",
            )
        except OSError:
            pass  # 标记失败不影响主流程

    def get_engine_status(self) -> dict:
        """返回各精修引擎的可用状态 (供 GUI 提示)

        含 `auto`: 它不是独立引擎, 而是"按样品条件自动择引擎"的策略项,
        恒为可用; note 里说明当前条件下会自动选中谁, 便于用户在向导里
        选 auto 前就知道会跑什么。
        """
        status: dict = {"builtin": {"available": True, "note": "内置引擎 (始终可用)"}}
        # powerxrd
        try:
            import powerxrd
            status["powerxrd"] = {
                "available": True,
                "version": getattr(powerxrd, "__version__", "4.x"),
                "note": "v4: 仅单相立方晶系; 其余自动回退内置",
            }
        except ImportError:
            status["powerxrd"] = {"available": False, "version": None,
                                  "note": "未安装 (pip install powerxrd)"}
        # gsas2
        py = self._find_gsas2_python()
        if py is not None:
            status["gsas2"] = {
                "available": True,
                "python": str(py),
                "note": "子进程桥 (scripts/gsas2_bridge.py)",
            }
        else:
            status["gsas2"] = {
                "available": False,
                "python": None,
                "note": "未检测到 GSAS-II (gsas2main 安装器), 或用 "
                        "POLYXRD_GSAS2_PYTHON 指定 python.exe",
            }
        # maud
        try:
            from polyxrd.services.maud_par_builder import detect_maud_root
            try:
                maud_root = detect_maud_root()
                status["maud"] = {
                    "available": True,
                    "maud_root": str(maud_root),
                    "note": "MaudText 子进程; 需要每个 phase 提供 cif_path "
                            "或 cod_id (路线 B 自动映射)",
                }
            except FileNotFoundError:
                status["maud"] = {
                    "available": False,
                    "maud_root": None,
                    "note": "未检测到 MAUD (C:\\MAUD2 / C:\\MAUD3)",
                }
        except ImportError:
            status["maud"] = {
                "available": False,
                "maud_root": None,
                "note": "maud_par_builder 模块未加载",
            }

        # auto: 非独立引擎, 恒可用; 说明"若全相有结构 CIF 且 GSAS-II 在, 会走 gsas2"
        gsas_ok = bool(status.get("gsas2", {}).get("available"))
        status["auto"] = {
            "available": True,
            "note": (
                "自动择引擎: 全相有结构 CIF 且 GSAS-II 可用 → gsas2; 否则 builtin"
                + ("" if gsas_ok else " (当前未检测到 GSAS-II, 实际会走 builtin)")
            ),
            "resolves_to": "gsas2" if gsas_ok else "builtin",
        }
        return status

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
        """使用 powerxrd (v4) 进行精修

        powerxrd v4 API (2026-02 重构): 单相 PhaseModel + 晶格子类,
        目前仅内置 CubicLattice。因此本引擎仅在:
          - 单物相
          - 立方晶系 (a=b=c, α=β=γ=90°)
        时启用; 其余情况回退内置引擎。

        精修参数: 晶胞 a + 强度 scale + 背景截距 (无结构时 |F|²=100,
        峰位主导拟合, 适用于晶胞参数测定; 强度/含量定量请用内置引擎)。
        """
        log = self.make_logger(kwargs)
        try:
            from powerxrd.model import PhaseModel
            from powerxrd.lattice import CubicLattice
            from powerxrd.refine import refine as pxr_refine
            _PXR_VERSION = getattr(
                __import__("powerxrd"), "__version__", "4.x"
            )
        except ImportError:
            log("[powerxrd] powerxrd not installed -> fallback to builtin")
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        # powerxrd v4 仅支持单相 + 立方
        if len(phases) != 1:
            log(f"[powerxrd] single phase only (got {len(phases)}) -> fallback to builtin")
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
        phase = phases[0]
        lat = phase.lattice if phase.lattice is not None else None
        if lat is None:
            log("[powerxrd] phase has no lattice -> fallback to builtin")
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
        cubic_ok = (
            abs(lat.a - lat.b) < 1e-9
            and abs(lat.a - lat.c) < 1e-9
            and abs(lat.alpha - 90.0) < 1e-6
            and abs(lat.beta - 90.0) < 1e-6
            and abs(lat.gamma - 90.0) < 1e-6
        )
        if not cubic_ok:
            log("[powerxrd] cubic system only -> fallback to builtin")
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        log(f"[powerxrd] v{_PXR_VERSION} single-phase cubic fit start: "
            f"{phase.name} a={lat.a:.4f}")
        two_theta = np.asarray(data.two_theta, dtype=float)
        intensity = np.asarray(data.intensity, dtype=float)
        bg = self._estimate_background(intensity, "median", wide_window=True)

        try:
            model = PhaseModel(
                lattice=CubicLattice(a=float(lat.a)),
                wavelength=float(data.wavelength),
            )
            model.params["bkg_intercept"] = float(np.median(bg))
            model.params["scale"] = max(
                0.1, float(np.max(intensity - bg)) / 100.0
            )
            model.params["U"] = 0.001
            model.params["W"] = float(max(0.005, kwargs.get("fwhm", 0.15) ** 2))

            refine_keys = ["a", "scale", "bkg_intercept"]
            result = pxr_refine(
                model, two_theta, intensity, refine_keys, print_stage=False
            )

            sim_full = model.pattern(two_theta)
            metrics = self._calc_profile_metrics(
                intensity, sim_full, weight=None, n_params=len(refine_keys),
            )
            wR = metrics["Rwp"]
            Rexp = metrics["Rexp"]
            Rb = 0.0   # 真实 Bragg R 未实现 (不再用轮廓 R 冒充)
            GOF = metrics["GOF"]

            refined_a = float(model.lattice.a)
            refined_phase = Phase(
                name=phase.name,
                formula=phase.formula,
                space_group=phase.space_group,
                lattice=LatticeParams(
                    a=refined_a, b=refined_a, c=refined_a,
                    alpha=90.0, beta=90.0, gamma=90.0,
                ),
                weight_fraction=100.0,
                reference_peaks=phase.reference_peaks,
                elements=phase.elements,
            )
            quality = quality_grade_for(wR)

            return RefinementResult(
                phases=[refined_phase],
                observed_data=(two_theta, intensity),
                simulated_data=(two_theta, sim_full),
                residual_data=(two_theta, intensity - sim_full),
                wR=wR,
                Rexp=Rexp,
                Rb=Rb,
                GOF=GOF,
                quality=quality,
                num_cycles=int(getattr(result, "nfev", 0)),
                converged=bool(getattr(result, "success", True)),
                fit_params={
                    "engine": "powerxrd",
                    "engine_version": str(_PXR_VERSION),
                    "strategy": strategy,
                    "refined_a": refined_a,
                    "initial_a": float(lat.a),
                    "scale": float(model.params["scale"]),
                    "bkg_intercept": float(model.params["bkg_intercept"]),
                    "wR": float(wR),
                },
            )
        except Exception:
            # 任何异常回退内置引擎, 保证精修流程不中断
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

    # ------------------------------------------------------------------
    # 内置精修引擎 (最小实现)
    # ------------------------------------------------------------------

    def _cif_reference_peaks(
        self,
        phase: Phase,
        wavelength: float,
        tth_range: tuple[float, float],
    ) -> Optional[list]:
        """v0.15.1: 从物相携带的 CIF 计算 |F(hkl)|² 参考峰 (pymatgen)。

        M23/M24 结构匹配链路已把 CIF (``phase.cif_path`` 文件或
        ``phase.atomic_sites``) 送到物相上; 本方法在内置精修启动时把它们
        现算成参考峰表 (空间群对称性展开 + Cromer-Mann 散射因子 + LP 校正,
        与 cod_local.get_phase(use_pymatgen_peaks=True) 同一条数学路径),
        取代库内静态峰表 —— 内置引擎由此获得基于结构的强度模型。

        优先级: cif_path 文件全文 → atomic_sites 反生成 CIF 文本。
        任何失败返回 None (调用方回退旧参考峰, 行为不劣化)。

        Results 缓存: quick/fine 两轮共用 (key = cif 来源 + λ + 2θ 范围)。
        """
        if not wavelength or wavelength <= 0:
            return None

        # ── 1. 拿 CIF 文本 ────────────────────────────────────────
        cif_text: Optional[str] = None
        cif_path = getattr(phase, "cif_path", None)
        cache_key = None
        if cif_path:
            p = Path(cif_path)
            if p.exists():
                try:
                    cif_text = p.read_text(encoding="utf-8", errors="ignore")
                    cache_key = (
                        "file", str(p), int(p.stat().st_mtime),
                        round(float(wavelength), 5),
                        round(tth_range[0], 3), round(tth_range[1], 3),
                    )
                except OSError:
                    cif_text = None
        if not cif_text:
            sites = getattr(phase, "atomic_sites", None)
            if not sites:
                return None
            try:
                from polyxrd.services.phase_cif import phase_to_cif_text

                cif_text = phase_to_cif_text(phase)
            except Exception:  # noqa: BLE001
                return None
            import hashlib

            cache_key = (
                "text", hashlib.sha1(cif_text.encode("utf-8", "ignore")).hexdigest(),
                round(float(wavelength), 5),
                round(tth_range[0], 3), round(tth_range[1], 3),
            )

        cached = self._cif_peak_cache.get(cache_key)
        if cached is not None:
            return cached if cached != "fail" else None

        peaks: Optional[list] = None
        _struct_used = None   # v2.0.0 (W23): 留出实际用到的 pymatgen 结构, 供强度标尺/ZMV

        def _pattern_to_rows(pattern):
            rows: list[tuple[tuple, float, float]] = []
            for i in range(len(pattern.x)):
                hkl = (0, 0, 0)
                hkl_info = pattern.hkls[i] if i < len(pattern.hkls) else []
                if hkl_info and isinstance(hkl_info[0], dict):
                    raw = hkl_info[0].get("hkl", (0, 0, 0))
                    if len(raw) == 4:
                        # 六方/三方四指标 (h,k,i,l) → 保留 l (截断会把 002
                        # 记成 (0,0,0), March-Dollase 织构轴 [001] 失效)
                        hkl = (int(raw[0]), int(raw[1]), int(raw[3]))
                    elif len(raw) >= 3:
                        hkl = (int(raw[0]), int(raw[1]), int(raw[2]))
                rows.append((hkl, float(pattern.x[i]), float(pattern.y[i])))
            imax = max((r[2] for r in rows), default=0.0)
            if rows and imax > 0:
                # 归一到 max=100, 与库内参考峰 (COD 粉末强度) 语义一致
                return [(h, t, 100.0 * inten / imax) for h, t, inten in rows]
            return None

        try:
            from pymatgen.analysis.diffraction.xrd import XRDCalculator

            calc = XRDCalculator(wavelength=float(wavelength))

            # ── 路径 1 (v0.15.2): atomic_sites 直构 Structure ──────────
            # 位点已经是展开全胞 (cod_local.get_phase 出口保证)。旧路径强制
            # 走 CIF 全文 → CifParser, 会对"全胞位点 × 空间群操作"做二次
            # 展开 (15R SiC 192 位点 × 192 操作 ≈ 3.7 万候选), 纯 Python
            # 匹配去重实测小时级; 直构路径与 get_phase 同一数学, 秒级。
            sites = getattr(phase, "atomic_sites", None)
            if sites and getattr(phase, "lattice", None) is not None:
                try:
                    from pymatgen.core import Lattice, Structure

                    lat = phase.lattice
                    pmg_lattice = Lattice.from_parameters(
                        lat.a, lat.b, lat.c, lat.alpha, lat.beta, lat.gamma)
                    species = [str(s["element"]) for s in sites]
                    coords = [[float(s["x"]), float(s["y"]), float(s["z"])]
                              for s in sites]
                    struct = Structure(pmg_lattice, species, coords)
                    pattern = calc.get_pattern(struct, two_theta_range=tth_range)
                    peaks = _pattern_to_rows(pattern)
                    _struct_used = struct
                except Exception:  # noqa: BLE001 - 直构失败 → CIF 全文回退
                    peaks = None

            # ── 路径 2: CIF 全文 CifParser (无位点时回退) ─────────────
            if peaks is None and cif_text:
                import warnings

                from pymatgen.io.cif import CifParser

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    parser = CifParser.from_str(cif_text, occupancy_tolerance=1.2)
                    struct = parser.parse_structures(primitive=False)[0]
                pattern = calc.get_pattern(struct, two_theta_range=tth_range)
                peaks = _pattern_to_rows(pattern)
                _struct_used = struct
        except Exception:  # noqa: BLE001 - CIF 解析/模拟失败一律回退旧峰表
            peaks = None

        self._cif_peak_cache[cache_key] = peaks if peaks is not None else "fail"
        # ── v2.0.0 (W23): 记录"强度标尺"与 ZMV ────────────────────────────
        # 定量需要把"相对峰强"还原到物理标度:
        #   k   = 未归一化 Σ|F(hkl)|²·m·LP 的最大值 (pymatgen scaled=False)
        #   ZMV = 晶胞内质量(Z·M) × 晶胞体积 V   ← Rietveld 质量分数 W_p ∝ S_p·(ZMV)_p
        # 参考峰表本身归一到 max=100, 所以物理标度因子 S_p = (拟合幅值)·k/100。
        if peaks is not None and _struct_used is not None:
            try:
                raw = calc.get_pattern(_struct_used, two_theta_range=tth_range,
                                       scaled=False)
                _k = float(np.max(raw.y)) if len(raw.y) else 0.0
                _zmv = (float(_struct_used.composition.weight)
                        * float(_struct_used.volume))
                self._cif_scale_cache[cache_key] = (_k, _zmv)
                self._cif_scale_by_phase[
                    (getattr(phase, "name", ""), getattr(phase, "formula", ""))
                ] = (_k, _zmv)
            except Exception:  # noqa: BLE001 - 取不到标尺就不做严格定量
                self._cif_scale_cache[cache_key] = None
        else:
            self._cif_scale_cache[cache_key] = None
        return peaks

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

        v8 性能优化 (P2):
        - 快速路径 (quick path): 先跑 use_caglioti=False + 3 起点的快检,
          若 wR ≤ wR_threshold (默认 20%, 即质量分级里的"可接受"线) 直接返回;
          否则再启 Caglioti 精细模式, 最终返回两者中 wR 更优者
          (结果只会更好不会变差)
          v0.15.2 把阈值由 55% 下调到 20%: 实测多相试样快检常落在 20%~55% 这一带,
          旧阈值会让它们**永远走不到 Caglioti**, 峰值宽度失配被钉进残差。
          以 4-1/2-1 为例, 放开后 wR 明显下降; 代价是慢, 但精度优先。
        - 单起点 max_nfev 收敛上限从 max_cycles*20 收紧到
          max_nfev_per_start (默认 400): 实测获胜起点通常 ~55 nfev 收敛,
          跑满 1200 的起点均为无效局部极小, 纯耗时间
        - _compute_spectrum_from_ref 分块向量化 (数学等价, 差异 <1e-13)
        """
        from scipy.optimize import least_squares

        # 进度回调 (可选): 多起点与稀疏抛光都是纯 Python 嵌套循环, 累计耗时可达数十秒。
        # 回调让 UI 层能借此周期性地泵事件 —— 否则主线程一直不处理消息, Windows 会
        # 把窗口标成"未响应", 用户就会以为程序卡死并反复点击。
        progress_cb = kwargs.get("progress_cb")

        def _tick(done: int, total: int) -> None:
            if progress_cb is None:
                return
            try:
                progress_cb(done, total)
            except Exception:  # noqa: BLE001 - 进度回调失败不该影响精修本身
                pass

        # 过程日志 (v0.12.0): 快检子调用会带 "[quick]" 前缀, 免得两轮日志混在一起
        log = self.make_logger(kwargs)
        _stage = str(kwargs.get("log_stage", "") or "")

        def _plog(msg: str) -> None:
            log(_stage + msg)

        # ── v2.0.0 (W26/W27): 分阶段 / 流水线调度 ──────────────────────────
        # 两个开关共用同一机制 (带热启动的多阶段拟合), 只是阶段表不同:
        #   pipeline="le_bail_then_rietveld" (W26, 2 阶段)
        #       ① 稳 cell+背景+标度 (轮廓/零点/织构/B 全冻结)  ← "Le Bail 级"预处理
        #       ② 全放开
        #   release_stages=True (W27, 5 阶段渐进释放)
        #       scale+bg → +profile → +零点/位移 → +cell → +织构/B
        # 每阶段用 `_x_sink` 回收解向量, 作为下一阶段热启动; 阶段内关闭快检早退,
        # 保证每阶段真收敛 (否则"未收敛的中间解"会被当起点传下去)。
        _pipeline = str(kwargs.get("pipeline", "") or "").lower()
        if (bool(kwargs.get("release_stages", False))
                or _pipeline == "le_bail_then_rietveld"):
            if not kwargs.get("_staged_inner", False):
                return self._refine_staged(
                    data, phases, strategy, max_cycles, kwargs)

        # ── 0. 快速路径: 无 Caglioti 快检, wR 达标即返回 ────────────
        wR_threshold = kwargs.get("wR_threshold", 20.0)
        best_quick: Optional[RefinementResult] = None
        _x_sink: dict = {}   # 快检最优参数向量回收槽 (供精细模式热启动)
        if wR_threshold is not None and kwargs.get("use_caglioti", True):
            quick_kw = dict(kwargs)
            quick_kw["use_caglioti"] = False
            quick_kw["n_starts"] = min(3, kwargs.get("n_starts", 3))
            quick_kw["wR_threshold"] = None  # 防止递归再次触发快检
            quick_kw["max_nfev_per_start"] = kwargs.get("max_nfev_per_start", 400)
            quick_kw["log_stage"] = "[quick] "
            quick_kw["_x_sink"] = _x_sink
            _plog(f"[quick] 快检启动 (wR_threshold={wR_threshold}%, use_caglioti=False)")
            try:
                best_quick = self._refine_builtin(
                    data, phases, strategy, max_cycles, **quick_kw
                )
            except Exception:
                best_quick = None
            # v1.1.2: 快检门限用**未加权 wR** 判定。
            # 20% 这条线是在单位权口径下标定的 (v0.15.2 由 55% 下调而来);
            # 统计权下加权 wR 天然更高 (弱峰/基线区权重更大), 直接比较会让
            # 原本"形状已够好"的试样永远走不到早退 → 白白变慢。
            # 因此门限保持未加权口径, 上报指标仍用加权口径 (两者都进 fit_params)。
            _gate_wr = (
                float(best_quick.fit_params.get("wR_unweighted", best_quick.wR))
                if best_quick is not None else float("inf")
            )
            if best_quick is not None and _gate_wr <= wR_threshold:
                best_quick.fit_params = {
                    **best_quick.fit_params,
                    "quick_path": True,
                    "wR_threshold": float(wR_threshold),
                }
                _plog(
                    f"[quick] 未加权 wR={_gate_wr:.3f}% ≤ {float(wR_threshold):.1f}% "
                    "→ 达标, 跳过 Caglioti 精细模式"
                )
                return best_quick
            if best_quick is not None:
                _plog(
                    f"[quick] 未加权 wR={_gate_wr:.3f}% > {float(wR_threshold):.1f}% "
                    "→ 启用 Caglioti 精细模式"
                )
            else:
                _plog("[quick] 快检失败 → 直接进入 Caglioti 精细模式")

        two_theta = data.two_theta
        intensity = data.intensity
        wavelength = data.wavelength

        peak_shape = kwargs.get("peak_shape", "pseudo-voigt")
        # v2.0.0 (W25): 起点优先由**观测峰**反推 (显式 kwargs 仍然最优先)
        _seed = (self._seed_from_observed_peaks(data)
                 if bool(kwargs.get("seed_from_peaks", True)) else {})
        # ⚠ 实测教训: 种子**只作为额外候选**, 不替换默认起点 ——
        # 直接替换会让 4-1 这种多相试样从 28.48% 崩到 120.64%
        # (反解出的 U/V 把 least_squares 引到另一个盆地; 多起点的意义正是对冲坏起点)。
        init_fwhm = float(kwargs.get("fwhm", 0.15))
        bg_method = kwargs.get("bg_method", "median")  # v4: median → 显著优于 snip
        init_zero_shift = kwargs.get("zero_shift", 0.0)
        use_caglioti = kwargs.get("use_caglioti", True)
        # n_starts: Caglioti 开启时缩到 4 起点 (快速)
        n_starts_default = 5 if not use_caglioti else 4
        n_starts = kwargs.get("n_starts", n_starts_default)
        # v8: 单起点收敛上限 (实测获胜起点 ~55 nfev, 1200 上限纯属浪费)
        max_nfev_per_start = int(kwargs.get(
            "max_nfev_per_start", min(max_cycles * 20, 400)
        ))
        # v1.1.2 (W14): least_squares 的变量缩放开关 (默认关闭)。
        # 参数确实跨 5 个数量级, 但**实测 x_scale="jac" 反而更差更慢**:
        #   2-1 默认预算: 关 → wR=29.893% / 37.1s; 开 → wR=30.176% / 54.9s
        #   (受限预算下 2-1 30.417%→30.938, 4-1 40.938%→41.108, 同样更差)
        # 原因是 Jacobian 定标改变了信赖域几何, 把解引到略差的局部极小。
        # 故默认保持关闭; 需要时显式传 x_scale="jac" 或正数数组启用。
        _x_scale = kwargs.get("x_scale", None)
        # v1.1.2 (W17): 低角不对称 (split-PV)。默认 0 = 关闭, 行为与旧版逐点一致;
        # 用户可给 0.1~0.3 之间的经验值 (低角侧展宽), 目前不做参数拟合。
        try:
            _asym = float(kwargs.get("asymmetry", 0.0) or 0.0)
        except (TypeError, ValueError):
            _asym = 0.0
        # scipy 不接受 x_scale=None (只接受 'jac' 或正数数组), 关闭时须整个省略该参数
        _lsq_extra: dict = {}
        if _x_scale is not None:
            _lsq_extra["x_scale"] = _x_scale

        # ── 1. 背景估计 (v3: SNIP 窗宽增大, 避免削峰引入假残差) ──
        bg = self._estimate_background(intensity, bg_method, wide_window=True)
        y_exp = intensity - bg
        y_exp_pos = np.where(y_exp > 0, y_exp, 0.0).astype(float)
        y_floor = max(float(np.median(y_exp_pos)) * 0.05, 1.0)
        _plog(
            f"[bg] method={bg_method} median={float(np.median(bg)):.2f} "
            f"I_max={float(np.max(intensity)):.1f} y_floor={y_floor:.3f}"
        )

        # ── 1b. v0.11.0 R-A1: 统计权重 (opt-in) ──────────────────
        # 旧版 residual 与 _calc_wR 都是单位权, 且 residual 用扣背景的
        # y_exp 而 wR 用含背景的 intensity — 目标函数与评价指标不同量.
        # stat_weights 启用后: residual 乘 sqrt(w), 全部 _calc_wR 调用带
        # 同一组 w (wR 与目标函数自洽, 即 docs/精修算法改进方案.md A1).
        #   "poisson": σ² = max(y, 1)
        #   "poirier": σ² = max(y, 1) + bg   (推荐, 低强度区更稳)
        # w 归一到均值 1, 保持 residual 数值量级与旧版可比 (边界/初值不变).
        # v1.1.2: 默认启用 Poisson 统计权 (w = 1/max(y,1))。
        # 理由: Rexp/GOF 只有在"统计权"下才有物理意义 (Rexp ∝ 1/sqrt(Σy));
        # 单位权下 Σw·y² = Σy² 会把 Rexp 压小一个数量级 (实测 130×)。
        # 同时 Rietveld 标准做法本就是加权最小二乘 (目标函数 = 评价指标)。
        # 仍可显式传 stat_weights="none" 退回旧行为 (Rwp 对权重尺度不变)。
        stat_weights_mode = str(kwargs.get("stat_weights", "poisson")).lower()
        if stat_weights_mode not in ("none", "poisson", "poirier"):
            stat_weights_mode = "none"
        if stat_weights_mode == "poisson":
            _var = np.maximum(intensity, 1.0)
        elif stat_weights_mode == "poirier":
            _var = np.maximum(intensity, 1.0) + np.maximum(bg, 0.0)
        else:
            _var = None
        if _var is not None:
            w_fit = 1.0 / _var
            w_fit = w_fit / float(np.mean(w_fit))  # 均值 1 归一
            sqrt_w_fit = np.sqrt(w_fit)
        else:
            w_fit = None
            sqrt_w_fit = None

        # ── 2. 参考峰收集 (v2 不做全局归一化, 避免破坏 wR 分子分母比例一致性)
        #    仅对每个物相做参考峰完整性检查; 原内置库中的参考峰强度已可比较
        #    v0.15.1: 物相带结构 CIF (M23/M24 链路的 cif_path / atomic_sites) 时,
        #    先用 pymatgen 现算 |F(hkl)|² 参考峰取代静态峰表; 取不到结构保持旧行为。
        use_cif_peaks = bool(kwargs.get("use_cif_peaks", True))
        tth_lo = float(np.min(two_theta))
        tth_hi = float(np.max(two_theta))
        phase_peaks: list = []
        n_cif_peaks = 0
        for phase in phases:
            ref_peaks = phase.get_reference_peaks() if hasattr(phase, 'get_reference_peaks') else []
            if not ref_peaks:
                ref_peaks = getattr(phase, 'reference_peaks', [])
            if use_cif_peaks and wavelength and float(wavelength) > 0:
                cif_peaks = self._cif_reference_peaks(
                    phase, float(wavelength), (tth_lo, tth_hi))
                if cif_peaks:
                    ref_peaks = cif_peaks
                    n_cif_peaks += 1
            phase_peaks.append(ref_peaks)
        if n_cif_peaks:
            _plog(
                f"[cif] {n_cif_peaks}/{len(phases)} 相使用 CIF 结构 |F|² 参考峰 "
                "(pymatgen: 对称性展开 + 散射因子 + LP)"
            )

        n_phases = len(phases)
        # v6: params = weights(n) + fwhm + eta + scale + zero_shift + U + V + W (Caglioti)
        # v0.15.2 (A 路线): 末尾再挂 n_phases 个「各向同性晶胞缩放」自由度。
        # 旧版内置引擎的 fit 维度里**根本没有 cell** (见下方 param_mask 注释), 峰位完全
        # 钉死在库/CCIF 晶胞上; 试样晶胞哪怕与库值差 0.1%~0.3%, 60° 附近峰位就偏
        # 0.05°~0.15°, 残差被这一项锁住 → wR 下不来。挂在参数向量末尾, 是为了不动
        # 既有 n_phases+0..6 的索引算术 (降低回归风险)。
        refine_cell = bool(kwargs.get("refine_cell", True))
        # v1.1.2 (W18): cell_mode 决定晶胞自由度的参数化方式
        #   "isotropic" (默认) = 每相 1 个各向同性缩放因子 (旧行为, 不变)
        #   "full"             = 每相 6 个缩放因子 (a,b,c,α,β,γ 各自相对库值的比例),
        #                        由 hkl 反算 d → 2θ, 能修各向异性失配
        cell_mode = str(kwargs.get("cell_mode", "isotropic")).lower()
        if cell_mode not in ("isotropic", "full"):
            cell_mode = "isotropic"
        # v1.1.2 (W18) 峰表↔晶胞一致性检查 (仅 full 模式需要):
        # 用相自带 lattice 由 hkl 重算 2θ, 与峰表存的 2θ 比较; 中位偏差 > 0.5° 判为
        # 不自洽 (hkl 不可信), 该相退回各向同性。内置库静态峰表多数不自洽
        # (Corundum/Zincite/Calcite/Brucite 实测中位差 9~15°, Fluorite 0.0007°),
        # 而 CIF/pymatgen 现算的峰表天然自洽 —— 这正是本守卫要区分的两种来源。
        cell_consistent: list = []
        if cell_mode == "full" and wavelength and float(wavelength) > 0:
            for _peaks in phase_peaks:
                _lat = None
                try:
                    _lat = phases[len(cell_consistent)].lattice
                except (IndexError, AttributeError):
                    _lat = None
                _diffs: list = []
                if _lat is not None:
                    for _p in (_peaks or [])[:400]:
                        try:
                            _hkl = _p[0]
                            if _hkl is None or len(_hkl) not in (3, 4):
                                continue
                            if len(_hkl) == 4:
                                _h, _k, _l = int(_hkl[0]), int(_hkl[1]), int(_hkl[3])
                            else:
                                _h, _k, _l = int(_hkl[0]), int(_hkl[1]), int(_hkl[2])
                            _d = self._calc_d_spacing_from_hkl(
                                float(_lat.a), float(_lat.b), float(_lat.c),
                                float(_lat.alpha), float(_lat.beta), float(_lat.gamma),
                                _h, _k, _l)
                            if _d <= 0:
                                continue
                            _s = float(wavelength) / (2.0 * _d)
                            if _s >= 1.0:
                                continue
                            _t = 2.0 * float(np.degrees(np.arcsin(_s)))
                            _diffs.append(abs(_t - float(_p[1])))
                        except (TypeError, ValueError, IndexError):
                            continue
                cell_consistent.append(
                    bool(_diffs) and float(np.median(_diffs)) < 0.5
                )
        # v1.1.2 (W18) 全有或全无:
        # 只要有一个相的峰表与晶胞不自洽 (hkl 不可信), 就**整体**退回各向同性。
        # 反例实录: 4-1 里只有 CaF2 自洽 (7 条峰), 放它单独上 6 个自由晶胞参数
        # 会去追别相未被建模的残差 → wR 41%→70% (过拟合)。全有或全无可挡住。
        use_full_cell = bool(
            cell_mode == "full" and cell_consistent and all(cell_consistent)
        )
        if cell_mode == "full" and not use_full_cell:
            _plog(
                "[cell] full 模式请求被守卫拒绝 (存在峰表与晶胞不自洽的相: "
                f"{[getattr(p, 'name', '?') for p, c in zip(phases, cell_consistent) if not c]}) "
                "→ 整体退回各向同性缩放"
            )
        n_cell_per_phase = 6 if use_full_cell else 1
        n_cell = (n_cell_per_phase * n_phases) if refine_cell else 0
        _cell_off = n_phases + (7 if use_caglioti else 4)
        n_params = n_phases + 7 + n_cell
        if not use_caglioti:
            n_params = n_phases + 4 + n_cell
        cell_lo, cell_hi = 0.98, 1.02  # 各向同性缩放 ±2% 足够覆盖试样与库值差异

        # v0.15.2 (A 路线续): March-Dollase 择优取向修正 (仅精细模式)。
        # 板状/层状物相 (氢氧化物、云母等) 制样后 00l 织构使实验强度系统性
        # 偏离运动学 |F|² (4-1 Brucite 实测 001:101 = 100:24.6, 模型 64:100),
        # 伪 Voigt + 全局 FWHM 吸收不了 → wR 地板 (4-1 实测卡 48%)。
        # 每相一个 r 参数, 织构轴 [001]: P(α) = (r²cos²α + sin²α/r)^(-3/2),
        # α = 晶面法线与 [001] 夹角; r<1 增强 00l, r>1 减弱; 逐相按均值归一。
        # 快检 (use_caglioti=False) 不启用, 保持快检参数布局与热启动兼容。
        refine_texture = bool(use_caglioti) and bool(
            kwargs.get("refine_texture", True))
        tex_axes: list = []
        for _i, _peaks in enumerate(phase_peaks):
            _lat = phases[_i].lattice if _i < len(phases) else None
            tex_axes.append(self._texture_cos_alpha(_peaks, _lat))
        _tex_idx = [i for i, c in enumerate(tex_axes) if c is not None]
        n_tex = len(_tex_idx) if refine_texture else 0
        _tex_off = _cell_off + n_cell
        n_params += n_tex

        # v1.1.2 (W16): 样品位移 (specimen displacement) —— 与 zero_shift 物理不同:
        #   Δ(2θ) = −2·s·cosθ / R    (s = 样品表面偏离测角仪轴的量, R = 测角仪半径)
        # zero_shift 是**常数**偏移; 位移项随 cosθ 变化, 高角区峰位整体漂移。
        # 只用 zero_shift 会把高角信息吸进常数项、低角反而被拉错。
        # 默认**关闭** (opt-in: refine_displacement=True), 参数挂在向量最末尾,
        # 不触碰既有 n_phases+0..6 / cell / tex 的索引算术。
        refine_displacement = bool(kwargs.get("refine_displacement", False))
        n_disp = 1 if refine_displacement else 0
        _disp_off = _tex_off + n_tex
        displacement_radius_mm = float(kwargs.get("displacement_radius_mm", 240.0))
        n_params += n_disp

        # ── v2.0.0 (W22-a): 每相**整体温度因子 B** (overall B / B_ovr) ─────────
        # 物理: |F|² 经 Debye-Waller 因子 exp(-2B·s²) 衰减, s = sinθ/λ。
        # 因为它只对**每个峰**乘一个只依赖 2θ 的因子, 所以可以直接作用在参考峰表上,
        # 不需要每次迭代重算结构因子 —— 这是"结构自由度"里代价最低、收益最直接的一项
        # (真实 Rietveld 程序的标准自由度; 缺它会让高角强度系统性偏高)。
        # 默认开启 (B 初值 0 = 无修正, 上界 15 Å² 防跑飞); 可用 refine_b_overall=False 关闭。
        refine_b_overall = bool(kwargs.get("refine_b_overall", True))
        n_bovr = n_phases if refine_b_overall else 0
        _bovr_off = _disp_off + n_disp
        n_params += n_bovr

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
        # W25 的观测峰反解值不在此处覆盖 init_* (见下方"额外候选"的处理)
        init_W = float(kwargs.get("W", init_W))
        init_U = float(kwargs.get("U", init_U))
        init_V = float(kwargs.get("V", init_V))

        # ── 4. 构建多起点 x0 候选 ────────────────────────────────
        def _make_x0(weights, fwhm, eta, scale, zs, U=None, V=None, W=None):
            parts = [np.asarray(weights, float),
                     [float(fwhm), float(eta), float(scale), float(zs)]]
            if use_caglioti:
                parts.append([float(U if U is not None else init_U),
                              float(V if V is not None else init_V),
                              float(W if W is not None else init_W)])
            if n_cell:
                parts.append(np.ones(n_cell, dtype=float))  # 晶胞缩放初值 = 1 (库值)
            if n_tex:
                parts.append(np.ones(n_tex, dtype=float))   # 织构 r 初值 = 1 (无取向)
            if n_disp:
                parts.append([0.0])   # v1.1.2 (W16): 样品位移初值 0 mm
            if n_bovr:
                parts.append(np.zeros(n_bovr, dtype=float))  # W22-a: 整体 B 初值 0
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
        # ── v2.0.0 (W25): 观测峰反推的起点作为**额外候选** ──────────────
        # 放在 `[:n_starts]` 截断**之后**, 因此它不会被截掉, 也不会挤掉原有起点 ——
        # 多起点的价值就在于"多一条路": 种子好时它给出更好的盆地,
        # 种子差时原有起点仍然兜底 (4-1 实测: 替换 → 120.6%, 追加 → 28.5%)。
        if _seed and _seed.get("fwhm"):
            try:
                _sf = float(_seed["fwhm"])
                _sU = _seed.get("U")
                _sV = _seed.get("V")
                _sW = float(_seed.get("W") or (_sf ** 2))
                if use_caglioti:
                    candidates.append(_make_x0(
                        w_est, _sf, 0.5, init_scale_est, init_zero_shift,
                        U=(init_U if _sU is None else float(_sU)),
                        V=(init_V if _sV is None else float(_sV)),
                        W=_sW))
                else:
                    candidates.append(_make_x0(
                        w_est, _sf, 0.5, init_scale_est, init_zero_shift))
                _plog(f"[seed] 观测峰反推起点已加入候选 (fwhm={_sf:.4f}, "
                      f"U={_sU}, V={_sV}, W={_sW:.5f}, n_peaks={_seed.get('n_peaks')})")
            except (TypeError, ValueError):
                pass
        # ── v2.0.0 (W26/W27): 外部热启动向量 ──────────────────────────────
        # 分阶段拟合把上一阶段的解作为下一阶段第 1 个起点 (布局相同, 因为阶段只改
        # `_param_mask` 冻结哪些参数, 不改"参数向量长度"——长度由 refine_cell /
        # refine_texture / refine_displacement / refine_b_overall 决定)。
        _x0_in = kwargs.get("_x0")
        if _x0_in is not None:
            try:
                _x0_arr = np.asarray(_x0_in, dtype=float).ravel()
                if _x0_arr.shape[0] == int(n_params):
                    candidates = [_x0_arr] + candidates[:max(1, n_starts - 1)]
                    _plog("[warm] 已并入上一阶段解作为第 1 起点")
            except (TypeError, ValueError):
                pass

        # ── 4b. 热启动 (v0.15.2): 把快检的最优参数接管为精细模式第 1 个起点 ──
        # 快检那一轮其实已经找到过不错的 权重/scale/零点/晶胞缩放; 精细模式再从网格
        # 重头搜, 既慢又可能落进更差的局部极小。这里把快检解补上 Caglioti 初值当起点。
        # (快检布局 = weights + fwhm + eta + scale + zs [+ cell], 比精细模式少 U/V/W)
        if _x_sink.get("x") is not None:
            try:
                wx = np.asarray(_x_sink["x"], dtype=float)
                _wn, _wcell = int(_x_sink.get("n_phases", -1)), int(_x_sink.get("n_cell", 0))
                if (not _x_sink.get("use_caglioti", True) and _wn == n_phases
                        and wx.shape == (n_phases + 4 + _wcell
                                         + int(_x_sink.get("n_disp", 0)),)):
                    w_cand = _make_x0(
                        wx[:n_phases], wx[n_phases], wx[n_phases + 1],
                        wx[n_phases + 2], wx[n_phases + 3],
                        U=init_U, V=init_V,
                        W=float(max(wx[n_phases], 0.02)) ** 2,
                    )
                    if n_cell and _wcell == n_cell:
                        w_cand[_cell_off:_cell_off + n_cell] = wx[
                            n_phases + 4:n_phases + 4 + n_cell]
                    _wdisp = int(_x_sink.get("n_disp", 0))
                    if n_disp and _wdisp == n_disp:
                        w_cand[_disp_off] = wx[n_phases + 4 + _wcell]
                    candidates = [w_cand] + candidates[:max(0, n_starts - 1)]
                    _plog("[warm] 快检解已并入精细模式第 1 起点")
            except Exception as _e:  # noqa: BLE001
                _plog(f"[warm] 热启动候选构造失败, 忽略: {type(_e).__name__}")

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
        if n_cell:
            if use_full_cell:
                # 每相: 3 个长度比例 + 3 个角度比例 (角度 ±3% ≈ 90° 处 ±2.7°)
                lower_parts.append(np.tile(
                    np.array([cell_lo, cell_lo, cell_lo, 0.97, 0.97, 0.97]), n_phases))
                upper_parts.append(np.tile(
                    np.array([cell_hi, cell_hi, cell_hi, 1.03, 1.03, 1.03]), n_phases))
            else:
                lower_parts.append(np.full(n_cell, cell_lo))
                upper_parts.append(np.full(n_cell, cell_hi))
        if n_tex:
            # March-Dollase r: 0.6 ↔ 1.8, 覆盖 Brucite 实测所需 r≈0.66 (r^-4.5=6.35)
            lower_parts.append(np.full(n_tex, 0.6))
            upper_parts.append(np.full(n_tex, 1.8))
        if n_disp:
            # 样品位移 s (mm): ±1.0 mm 覆盖常见制样偏差 (R=240mm 时 100° 处 ≈0.5°)
            lower_parts.append(np.array([-1.0]))
            upper_parts.append(np.array([1.0]))
        if n_bovr:
            # 整体温度因子 B (Å²): 0~15 覆盖绝大多数实验室数据; 0 = 无修正
            lower_parts.append(np.full(n_bovr, 0.0))
            upper_parts.append(np.full(n_bovr, 15.0))
        lower = np.concatenate(lower_parts)
        upper = np.concatenate(upper_parts)

        # ── 5b. M14 参数掩码: 关闭的组用极窄上下界, 冻结该参数 ───────────────
        # builtin 引擎参数向量布局 (Caglioti 关闭): weights(n) + fwhm + eta + scale + zs
        #                          (Caglioti 开启): 再加 U + V + W
        #
        # scipy.optimize.least_squares 要求 lb < ub 严格, 不能直接 lower=upper=init。
        # 用极窄对称区间 [_FREEZE_EPS, _FREEZE_EPS] 包住 init 值, 实际漂移 ≤ ε
        # (相对 XRD 仪器精度 ~0.01° 与强度动态范围, 1e-7 量级不可分辨) — 即"冻结"。
        # 同时 ε > 后续 clip 边距 1e-8, 保证 x0_clipped 与 polish clip 仍为有效区间。
        param_mask = kwargs.get("_param_mask") or {
            "scale": True, "background": True, "profile": True,
            "cell": True, "zero_shift": True, "texture": True,
        }
        init_eta = 0.5  # 所有起点的 eta 初值约定为 0.5
        _FREEZE_EPS = 1e-7

        def _freeze(idx, init_val):
            lower[idx] = init_val - _FREEZE_EPS
            upper[idx] = init_val + _FREEZE_EPS

        if not param_mask.get("scale", True):
            _freeze(n_phases + 2, init_scale_est)
        if not param_mask.get("profile", True):
            _freeze(n_phases + 0, init_fwhm)
            _freeze(n_phases + 1, init_eta)
            if use_caglioti:
                _freeze(n_phases + 4, init_U)
                _freeze(n_phases + 5, init_V)
                _freeze(n_phases + 6, init_W)
        if not param_mask.get("zero_shift", True):
            _freeze(n_phases + 3, init_zero_shift)
        if n_cell and not param_mask.get("cell", True):
            # v0.15.2: cell 现在真的是 fit 维度了 (各向同性缩放), 掩码关闭即冻结为 1.0
            for _j in range(n_cell):
                _freeze(_cell_off + _j, 1.0)
        if n_tex and not param_mask.get("texture", True):
            # v0.15.2: 织构 r 掩码关闭即冻结为 1.0 (无择优取向)
            for _j in range(n_tex):
                _freeze(_tex_off + _j, 1.0)
        if n_disp and not param_mask.get("displacement", True):
            # v1.1.2 (W16): 位移掩码关闭 → 冻结为 0 (无样品位移)
            _freeze(_disp_off, 0.0)
        if n_bovr and not param_mask.get("b_overall", True):
            # W22-a: 整体 B 掩码关闭 → 冻结为 0 (无温度因子修正)
            for _j in range(n_bovr):
                _freeze(_bovr_off + _j, 0.0)
        # mask["background"] 在 builtin 中仍为 no-op:
        #   background 由 _estimate_background 一次性预处理, 非 fit 维度。

        def _unpack(params):
            weights = params[:n_phases]
            fwhm = params[n_phases]
            eta = params[n_phases + 1]
            scale = params[n_phases + 2]
            zs = params[n_phases + 3]
            cs = None
            if use_caglioti:
                U_p = params[n_phases + 4]
                V_p = params[n_phases + 5]
                W_p = params[n_phases + 6]
                cag = (U_p, V_p, W_p)
            else:
                cag = None
            if n_cell:
                cs = np.asarray(params[_cell_off:_cell_off + n_cell], dtype=float)
            tex = None
            if n_tex:
                tex = np.asarray(params[_tex_off:_tex_off + n_tex], dtype=float)
            return weights, fwhm, eta, scale, zs, cag, cs, tex

        def _transform_peaks(cs, tex):
            """晶胞缩放 (峰位) + March-Dollase (峰强) 一并作用到参考峰表。"""
            peaks = phase_peaks
            if n_cell and cs is not None:
                if use_full_cell:
                    peaks = self._apply_full_cell(
                        peaks, cs, phases, wavelength, cell_consistent or None)
                else:
                    peaks = self._scale_phase_peaks(peaks, cs, wavelength)
            if n_tex and tex is not None:
                peaks = self._apply_texture(peaks, tex_axes, tex)
            return peaks

        def _disp_of(params) -> float:
            """v1.1.2 (W16): 从参数向量末尾取样品位移 (不改变 _unpack 的元组长度)。"""
            if not n_disp:
                return 0.0
            try:
                return float(params[_disp_off])
            except (IndexError, TypeError, ValueError):
                return 0.0

        def _transform_peaks_full(cs, tex, disp: float = 0.0):
            """= _transform_peaks + 样品位移 (仅在启用时多一步, 其余路径逐点不变)。"""
            peaks = _transform_peaks(cs, tex)
            if n_disp and disp:
                peaks = self._apply_displacement(
                    peaks, disp, displacement_radius_mm)
            return peaks

        def _bovr_of(params) -> Optional[np.ndarray]:
            """W22-a: 取每相整体温度因子 B (未启用返回 None)。"""
            if not n_bovr:
                return None
            try:
                return np.asarray(params[_bovr_off:_bovr_off + n_bovr], dtype=float)
            except (IndexError, TypeError, ValueError):
                return None

        def _transform_all(cs, tex, disp: float, bovr):
            """晶胞/织构/位移 (峰位) + 整体 B (峰强) 一并作用。"""
            peaks = _transform_peaks_full(cs, tex, disp)
            if bovr is not None and np.any(np.asarray(bovr, dtype=float) > 0.0):
                peaks = self._apply_overall_b(peaks, bovr, wavelength)
            return peaks

        def residual(params):
            weights, fwhm, eta, scale, zs, cag, cs, tex = _unpack(params)
            eff_two_theta = two_theta - zs if abs(zs) > 1e-9 else two_theta
            _disp = _disp_of(params)
            simulated = self._compute_spectrum_from_ref(
                eff_two_theta, _transform_all(cs, tex, _disp, _bovr_of(params)),
                weights, fwhm, eta, scale,
                peak_shape, caglioti=cag, asymmetry=_asym
            )
            r = y_exp - simulated
            if sqrt_w_fit is not None:
                r = r * sqrt_w_fit  # R-A1: 目标函数带统计权
            return r

        def _wr_of(sim_core: np.ndarray) -> float:
            """R-A1 自洽 wR: 与 residual 用同一组统计权 (stat_weights=none 时单位权)"""
            if w_fit is None:
                return self._calc_wR(intensity, sim_core + bg)
            return self._calc_wR(intensity, sim_core + bg, weight=w_fit)

        # ── 6. 多起点最小二乘，取最终 wR 最优者 ──────────────
        best_result = None
        best_wR = float("inf")
        best_simulated = None
        _plog(
            f"[init] n_phases={n_phases} n_params={n_params} n_starts={n_starts} "
            f"max_nfev/start={max_nfev_per_start} peak_shape={peak_shape} "
            f"caglioti={use_caglioti} stat_weights={stat_weights_mode} "
            f"n_cell={n_cell} n_tex={n_tex} "
            f"(tex: {', '.join(getattr(phases[i], 'name', '?') for i in _tex_idx) or '-'})"
        )

        for _start_i, x0_i in enumerate(candidates):
            x0_clipped = np.clip(x0_i, lower + 1e-8, upper - 1e-8)
            _tick(_start_i, n_starts + 1)
            _t0 = time.time()
            try:
                res_opt = least_squares(
                    residual, x0_clipped, bounds=(lower, upper),
                    max_nfev=max_nfev_per_start,
                    method="trf",
                    loss="linear",
                    **_lsq_extra,
                )
            except Exception as e:  # noqa: BLE001
                _plog(
                    f"[start {_start_i + 1}/{n_starts}] 求解失败: "
                    f"{type(e).__name__}: {e}"
                )
                continue

            # 计算该起点的 wR
            opt_w, opt_fw, opt_et, opt_sc, opt_zs, opt_cag, opt_cs, opt_tex = _unpack(res_opt.x)
            eff = two_theta - opt_zs if abs(opt_zs) > 1e-9 else two_theta
            sim_i = self._compute_spectrum_from_ref(
                eff, _transform_all(opt_cs, opt_tex, _disp_of(res_opt.x), _bovr_of(res_opt.x)),
                opt_w, opt_fw, opt_et, opt_sc, peak_shape, caglioti=opt_cag,
                asymmetry=_asym
            )
            wr_i = _wr_of(sim_i)

            improved = wr_i < best_wR
            if improved:
                best_wR = wr_i
                best_result = res_opt
                best_simulated = sim_i
            _plog(
                f"[start {_start_i + 1}/{n_starts}] wR={wr_i:7.3f}% "
                f"nfev={int(getattr(res_opt, 'nfev', 0)):4d} "
                f"cost={float(getattr(res_opt, 'cost', 0.0)):10.4g} "
                f"t={time.time() - _t0:5.2f}s" + ("  ← best" if improved else "")
            )

        if best_result is None:
            _plog("[warn] 所有起点求解失败 → 退化为单起点直接拟合")
            # 退化: 直接返回起点拟合
            best_result = least_squares(
                residual, candidates[0], bounds=(lower, upper),
                max_nfev=max_nfev_per_start, method="trf",
                **_lsq_extra,
            )
            _w, _fw, _et, _sc, _zs, _cag, _cs, _tex = _unpack(best_result.x)
            best_simulated = self._compute_spectrum_from_ref(
                two_theta, _transform_all(_cs, _tex, _disp_of(best_result.x), _bovr_of(best_result.x)),
                _w, _fw, _et, _sc, peak_shape, caglioti=_cag,
                asymmetry=_asym
            )
        _plog(f"[multistart] best wR={best_wR:.3f}% → 进入局部抛光")
        # v1.1.2: 记录抛光前的最优 wR, 供收敛判定 (抛光仍能改进 = 未卡死)
        _wr_multistart = float(best_wR)

        # ── 7. v7 局部抛光 (性能+效果平衡) ───────────────────────
        #    取 24 个手工方向 + 9 个 Caglioti 调整方向，而不是 3^8 网格
        _tick(n_starts, n_starts + 1)   # 多起点跑完, 进入抛光阶段
        _polish_n = 0   # 抛光评估计数 (日志/进度共用; 提前初始化避免异常路径未定义)
        # v2.1 (后续计划 #1 / 基准 7-1): 抛光评估预算按参考峰总数自适应。
        # 每次抛光评估都要在全部数据点上叠加全部参考峰, 单次代价随峰数线性
        # 增长 —— 7-1 (七相, ~3000 条参考峰) 在固定 675 次预算下 25 分钟跑不完。
        # 预算 = clamp(675 × 3000 / N_peaks, 40, 675): 典型峰数下预算不变,
        # 峰数更多则按比例缩减并保底 40 次, 使抛光阶段总耗时大致恒定。
        _n_ref_total = sum(len(pp) for pp in phase_peaks)
        _polish_budget = int(min(675, max(40, 675 * 3000 / max(_n_ref_total, 1))))
        _polish_stop = False   # 预算耗尽 → 逐层跳出候选枚举
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
                if _polish_stop:
                    break
                for sc_m in sc_mult:
                    if _polish_stop:
                        break
                    for w_m in w_mult:
                        if _polish_stop:
                            break
                        for et_m in et_mult:
                            if _polish_stop:
                                break
                            for zs_m in zs_mult:
                                if _polish_stop:
                                    break
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
                                        # 晶胞缩放不参与抛光方向, 原值带过去即可
                                        # (n_cell==0 时 cur_x[_cell_off:] 为空, 无副作用)
                                        x_t = np.concatenate([core, [U_i, V_i, W_i],
                                                              cur_x[_cell_off:]])
                                    else:
                                        x_t = np.concatenate([core, cur_x[_cell_off:]])
                                    # 进一步稀疏: 保留 (fw==1 或 sc==1) 且 (w==1 或 zs==1) 交集约 1/3
                                    if not ((abs(fw_m - 1.0) < 1e-6 or abs(sc_m - 1.0) < 1e-6) and
                                            (abs(w_m - 1.0) < 1e-6 or abs(zs_m - 1.0) < 1e-6)):
                                        continue
                                    x_t = np.clip(x_t, lower + 1e-9, upper - 1e-9)
                                    # 自适应预算: 评估前检查, 达标即收尾 (wR 不劣于多起点)
                                    if _polish_n >= _polish_budget:
                                        _polish_stop = True
                                        break
                                    _uw, _ufw, _uet, _usc, _uzs, _ucag, _ucs, _utex = _unpack(x_t)
                                    eff_t = two_theta - _uzs if abs(_uzs) > 1e-9 else two_theta
                                    sim_t = self._compute_spectrum_from_ref(
                                        eff_t,
                                        _transform_all(_ucs, _utex, _disp_of(x_t), _bovr_of(x_t)),
                                        _uw, _ufw, _uet, _usc, peak_shape,
                                        caglioti=_ucag, asymmetry=_asym
                                    )
                                    wr_t = _wr_of(sim_t)
                                    # 每 8 次评估汇报一次: 抛光约百余次评估, 采样过密
                                    # 会让 processEvents 本身成为开销
                                    _polish_n += 1
                                    if _polish_n % 8 == 0:
                                        _tick(n_starts + 1, n_starts + 1)
                                    if wr_t < best_wR:
                                        best_wR = wr_t
                                        best_polish_x = x_t
                                        best_simulated = sim_t
            best_result_x = best_polish_x
        except Exception as e:  # noqa: BLE001
            _plog(f"[warn] 局部抛光异常, 保留多起点结果: {type(e).__name__}: {e}")
            best_result_x = best_result.x
        _plog(f"[polish] 评估 {_polish_n} 次 (自适应预算 {_polish_budget}, 参考峰 {_n_ref_total} 条)"
              f" → wR={best_wR:.3f}%")

        # v0.15.2: 回收本轮最终参数向量 (供上层"快检 → 精细模式"热启动)
        _sink = kwargs.get("_x_sink")
        if isinstance(_sink, dict):
            try:
                _sink.update({
                    "x": np.asarray(best_result_x, dtype=float).copy(),
                    "use_caglioti": bool(use_caglioti),
                    "n_phases": int(n_phases),
                    "n_cell": int(n_cell),
                    "n_disp": int(n_disp),
                })
            except Exception:  # noqa: BLE001
                pass

        # ── 8. 提取最终结果 ──────────────────────────────────────
        (opt_weights, opt_fwhm, opt_eta, opt_scale, opt_zero_shift,
         opt_cag, opt_cell, opt_tex) = _unpack(best_result_x)
        opt_disp = _disp_of(best_result_x)   # v1.1.2 (W16)
        opt_cell_list = ([float(x) for x in opt_cell] if opt_cell is not None else [])
        opt_tex_list = ([float(x) for x in opt_tex] if opt_tex is not None else [])

        # 归一化权重为百分比
        total_w = np.sum(opt_weights)
        weight_pcts = (opt_weights / total_w * 100.0) if total_w > 0 else opt_weights
        # ── v2.0.0 (W23): 严格质量分数 W_p ∝ S_p·(ZMV)_p ──────────────────
        # 前提: 该相的参考峰来自结构 (CIF/pymatgen), 因而拿得到强度标尺 k 与 ZMV。
        # 任一相缺信息 → 退回旧的"相对强度归一", 并用 weight_basis 标明口径。
        weight_basis = "relative"
        # v2.1-C: 记录哪些相缺结构标尺 (无 |F|²/ZMV) → 定量降级原因可见
        _info = [self._cif_scale_by_phase.get(
            (getattr(p, "name", ""), getattr(p, "formula", ""))) for p in phases]
        _missing_structure = [
            (getattr(p, "name", "") or "?")
            for p, v in zip(phases, _info) if v is None
        ]
        try:
            _amp_p = np.asarray(opt_weights, dtype=float) * float(opt_scale)
            if _info and all(v is not None for v in _info):
                _w_mass = self._mass_fractions(
                    _amp_p, [v[0] for v in _info], [v[1] for v in _info])
                if _w_mass is not None:
                    weight_pcts = np.asarray(_w_mass, dtype=float)
                    weight_basis = "mass"
        except Exception as _e:  # noqa: BLE001 - 定量换算失败不该影响精修本身
            _plog(f"[warn] 质量分数换算失败, 退回相对定量: {type(_e).__name__}: {_e}")

        # 最终模拟谱
        simulated_full = best_simulated + bg
        residuals = intensity - simulated_full
        wR = best_wR

        # ── v0.11.0 R-A4: Chebyshev 多项式背景抛光 (opt-in) ─────────
        # 在 least_squares + 局部抛光之后, 用已拟合谱对 BG 做一次低频校正.
        # 默认 bg_chebyshev_deg=0 = 关闭 → 行为完全等价旧版, 不影响既有测试.
        # 启用后: 只有在 _chebyshev_background_polish 真的改进了 wR (gate)
        # 时才采纳, 否则保持现状 — 双层保护 (内部缩放 + 外部 wR gate).
        # v1.1.2 (W13): Chebyshev 背景抛光默认开启 (deg=6)。
        # 原为 opt-in (默认 0)。背景由 _estimate_background 一次性给出后即冻结,
        # 是"Rwp 有地板"的首要原因之一 (合成自检: 5.041% vs 1.012%)。
        # 该函数自带两道保护: 校正幅度 ≤30% 动态范围 + 仅在 after_wR 更优时采纳,
        # 故默认开启不会让结果变差。显式传 bg_chebyshev_deg=0 可退回旧行为。
        bg_cheb_deg = int(kwargs.get("bg_chebyshev_deg", 6))
        bg_cheb_applied = False
        if bg_cheb_deg > 0:
            try:
                bg_new, _before, after = self._chebyshev_background_polish(
                    intensity, best_simulated, bg, two_theta,
                    degree=bg_cheb_deg, weight=w_fit,
                )
                if np.all(np.isfinite(bg_new)) and after + 1e-9 < wR:
                    simulated_full = best_simulated + bg_new
                    residuals = intensity - simulated_full
                    wR = float(after)
                    bg = bg_new
                    bg_cheb_applied = True
                    _plog(
                        f"[bg-polish] Chebyshev deg={bg_cheb_deg} → wR={wR:.3f}% (采纳)"
                    )
                else:
                    _plog(
                        f"[bg-polish] Chebyshev deg={bg_cheb_deg} 未改进 (after={after:.3f}% "
                        f"≥ {wR:.3f}%) → 忽略"
                    )
            except Exception:
                # 任何异常 → 静默回退 (守门员: 默认值已关; 走正门也不应崩)
                bg_cheb_applied = False

        # v0.15.2: 通用 R 因子组 (Rwp / Rexp / Rb / GOF)
        # GOF 弃用旧的非标准量, 改为标准定义 GOF = Rwp / Rexp
        metrics = self._calc_profile_metrics(
            intensity, simulated_full, sigma2=_var, n_params=n_params,
        )
        wR = metrics["Rwp"]
        Rexp = metrics["Rexp"]
        Rb = 0.0   # 真实 Bragg R 未实现
        GOF = metrics["GOF"]
        # v1.1.2: 未加权 wR —— 供快检门限与"新旧口径"对照使用
        wR_unweighted = float(self._calc_wR(intensity, simulated_full))
        # Rexp/GOF 只有在统计权下才可解读 (Rexp ∝ 1/sqrt(Σy))
        metrics_valid = stat_weights_mode != "none"
        # v2.0.0 (W28): 拟合后诊断 (分段残差 + DW 统计量 + 可读建议)
        _diag = self._fit_diagnostics(two_theta, intensity, simulated_full)

        # 质量等级 (v1.1.2: 统一走 models.refinement.quality_grade_for)
        quality = quality_grade_for(wR)

        # 构建精修后物相
        refined_phases = []
        for i, phase in enumerate(phases):
            lat = phase.lattice if phase.lattice else LatticeParams()
            if cell_mode == "full" and len(opt_cell_list) >= 6 * (i + 1):
                _sc = opt_cell_list[6 * i:6 * i + 6]        # (sa,sb,sc,sα,sβ,sγ)
            else:
                _s1 = opt_cell_list[i] if i < len(opt_cell_list) else 1.0
                _sc = [_s1, _s1, _s1, 1.0, 1.0, 1.0]
            refined_phases.append(Phase(
                name=phase.name,
                formula=phase.formula,
                lattice=LatticeParams(
                    a=lat.a * _sc[0], b=lat.b * _sc[1], c=lat.c * _sc[2],
                    alpha=lat.alpha * _sc[3], beta=lat.beta * _sc[4],
                    gamma=lat.gamma * _sc[5],
                ),
                weight_fraction=float(weight_pcts[i]),
            ))

        # v1.1.2: converged/num_cycles 语义修正
        #   旧实现取的是多起点里那个 res.success —— 但最终结果还经过局部抛光,
        #   抛光可能把"多起点未收敛"的解救回来。这里改为:
        #     converged = (多起点 success) 或 (抛光在起点解之上仍有改进)
        #   并把两者都写进 fit_params, 便于排查。
        _multistart_ok = bool(getattr(best_result, "success", True))
        _polish_improved = float(best_wR) < _wr_multistart - 1e-9
        converged = bool(np.isfinite(wR) and (_multistart_ok or _polish_improved))
        num_cycles = int(getattr(best_result, "nfev", 0))  # 语义 = nfev (见 fit_params)

        # v2.1-C: 定量口径降级原因结构化 (UI 用 tr() 渲染, 用户可见)
        _diag_entries: list[dict] = (
            [] if metrics_valid
            else [{"code": "diag.metrics_no_weights", "params": {}}]
        )
        if weight_basis == "relative":
            _diag_entries.append({
                "code": "diag.weight_basis_relative",
                "params": {
                    "phases": ", ".join(_missing_structure) if _missing_structure else "-",
                },
            })

        result = RefinementResult(
            phases=refined_phases,
            observed_data=(two_theta, intensity),
            simulated_data=(two_theta, simulated_full),
            residual_data=(two_theta, residuals),
            wR=wR,
            Rexp=Rexp,
            Rb=Rb,
            Rp=float(metrics["Rp"]),
            chi2=float(metrics["chi2"]),
            chi2_red=float(metrics["chi2_red"]),
            metrics_valid=bool(metrics_valid),
            # v2.1-B: 文案移出服务层 —— 不可解读原因走结构化诊断码
            # (diag.metrics_no_weights), metric_note 仅用于旧项目文件兼容。
            metric_note="",
            diagnostics=_diag_entries,
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
                # M14 参数掩码: 暴露 mask 与 init/opt, 便于测试冻结与调参
                "param_mask": dict(param_mask),
                "init_scale": float(init_scale_est),
                "init_fwhm": float(init_fwhm),
                "init_eta": float(init_eta),
                "init_zero_shift": float(init_zero_shift),
                "opt_scale": float(opt_scale),
                "opt_fwhm": float(opt_fwhm),
                "opt_eta": float(opt_eta),
                "opt_zero_shift": float(opt_zero_shift),
                # v0.11.0 R-A4: Chebyshev BG 抛光, 默认关闭
                "bg_chebyshev_deg": int(bg_cheb_deg),
                "bg_chebyshev_applied": bool(bg_cheb_applied),
                # v0.11.0 R-A1: 统计权 (目标函数与 wR 自洽), 默认 "none"
                "stat_weights": stat_weights_mode,
                # v1.1.2: 加权/未加权 wR 双口径 (快检门限用未加权)
                "wR_weighted": float(wR),
                "wR_unweighted": float(wR_unweighted),
                # v1.1.2: 收敛语义 (num_cycles 实为 nfev; 多起点与抛光分开记录)
                "nfev": int(num_cycles),
                "num_cycles_semantics": "nfev",
                "converged_multistart": bool(_multistart_ok),
                "converged_polish_improved": bool(_polish_improved),
                "wR_before_polish": float(_wr_multistart),
                # v0.15.2 A 路线: 各向同性晶胞缩放 (每相一个自由度, 1.0 = 库值)
                "refine_cell": bool(refine_cell),
                "cell_scale": opt_cell_list,
                "cell_mode": cell_mode,   # v1.1.2 (W18): "isotropic" | "full"
                "cell_mode_used": "full" if use_full_cell else "isotropic",
                "cell_consistent": list(cell_consistent),
                # v2.0.0 (W23): 定量口径 —— "mass"(严格, W∝S·ZMV) | "relative"(回落)
                "weight_basis": weight_basis,
                "cell_mode_effective": (
                    ["full"] * n_phases if use_full_cell
                    else ["isotropic"] * n_phases
                ),
                # v0.15.2 A 路线续: March-Dollase 织构 (仅 _tex_idx 内的相有值)
                "refine_texture": bool(refine_texture),
                "texture_phases": [getattr(phases[i], "name", "?") for i in _tex_idx],
                "texture_r": opt_tex_list,
                # v1.1.2 (W16): 样品位移 (opt-in, 默认关)
                "refine_displacement": bool(refine_displacement),
                "displacement_mm": float(opt_disp),
                "displacement_radius_mm": float(displacement_radius_mm),
                # v1.1.2 (W17): 低角不对称强度 (0 = 关)
                "asymmetry": float(_asym),
                # v2.0.0 (W22-a): 每相整体温度因子 B (Å²); 0 = 无修正
                "refine_b_overall": bool(refine_b_overall),
                "b_overall": ([float(x) for x in np.asarray(
                    _bovr_of(best_result_x)).ravel()]
                    if _bovr_of(best_result_x) is not None else []),
                # v2.0.0 (W28): 拟合后诊断 (分段 R / DW / 建议)
                "diagnostics": _diag,
                # v2.0.0 (W25): 观测峰种子化起点 (反推出的值; 空 = 用了默认起点)
                "seed_from_peaks": dict(_seed) if _seed else {},
            },
        )
        # W28: 最重要的诊断进结构化诊断 (最多 2 条, 避免刷屏);
        # v2.1-B: diagnoses 已是 {code, params} 结构, 文案由 UI 用 tr() 渲染。
        for _d in (_diag.get("diagnoses", []) if isinstance(_diag, dict) else [])[:2]:
            if isinstance(_d, dict) and _d.get("code") and _d not in result.diagnostics:
                result.diagnostics.append(_d)

        _plog(
            "[result] Rwp={:.3f}% Rexp={:.3f}% Rp={:.3f}% GOF={:.3f} nfev={} quality={}".format(
                float(wR), float(Rexp), float(metrics.get("Rp", 0.0)), float(GOF),
                int(num_cycles), quality,
            )
        )
        _plog(
            "[weights] "
            + ", ".join(
                f"{getattr(phases[i], 'name', '?')}={float(weight_pcts[i]):.2f}%"
                for i in range(min(n_phases, len(weight_pcts)))
            )
        )

        # ── v8: 快速路径结果择优 (快检 wR 更低则返回快检结果) ──────
        if best_quick is not None and best_quick.wR < result.wR:
            best_quick.fit_params = {
                **best_quick.fit_params,
                "caglioti_fallback": True,
            }
            _plog(
                f"[pick] 快检 wR={best_quick.wR:.3f}% < 精细 {result.wR:.3f}% "
                "→ 返回快检结果"
            )
            return best_quick
        if best_quick is not None:
            _plog(
                f"[pick] 精细 wR={result.wR:.3f}% ≤ 快检 {best_quick.wR:.3f}% "
                "→ 返回精细结果"
            )
        return result

    # ------------------------------------------------------------------
    # v0.11.0 R-A4: Chebyshev 多项式背景抛光 (opt-in)
    # ------------------------------------------------------------------

    def _chebyshev_background_polish(
        self,
        intensity: np.ndarray,
        simulated: np.ndarray,
        bg_initial: np.ndarray,
        two_theta: np.ndarray,
        degree: int = 4,
        max_corr_fraction: float = 0.30,
        weight: Optional[np.ndarray] = None,
    ) -> tuple[np.ndarray, float, float]:
        """Chebyshev 多项式背景抛光 (R-A4, opt-in)

        把 ``intensity - simulated - bg_initial`` 视作 BG 估计误差的低频成分,
        用 ``numpy.polynomial.chebyshev`` 拟合, 给出 bg 增量.
        返回 ``(bg_new, before_wR, after_wR)``.

        ``weight``: R-A1 统计权 (stat_weights 启用时由调用方传入), 保证
        before/after wR 与主拟合口径一致; None = 单位权 (旧行为).

        设计原则 (保守, 防恶化):
        1. ``degree <= 0`` 或样本数不足 → 直接返回原 BG, 不动声不响
        2. 拟合权重 = 1/sigma, sigma = sqrt(max(y,1)) (泊松/Poirier 启发):
           让高强度峰区对 BG 拟合贡献低, 避免峰身拉偏 BG
        3. **gate**: corr 范围不超过 ``max_corr_fraction · 动态范围`` (默认 30%);
           若超过则按比例缩放, 防极端标本 (高散射基底) 让 Chebyshev 失控
        4. **调用方**只采纳 ``after_wR < before_wR`` 的结果, 进一步保险

        几何动机: median/SNIP 给的 bg 常低估宽峰肩 (陶瓷 amorphous hump),
        或高角硬 X 射线散射抬升; Chebyshev 多项式提供低频解析分量,
        在已拟合谱的基础上给 BG 一个软校正项。
        """
        n = len(intensity)
        if degree <= 0 or n < 2 * degree + 1:
            before_wR = float(self._calc_wR(intensity, simulated + bg_initial,
                                            weight=weight))
            return bg_initial, before_wR, before_wR

        residual = intensity - simulated - bg_initial
        before_wR = float(self._calc_wR(intensity, simulated + bg_initial,
                                        weight=weight))

        # x 归一到 [-1, 1] (Chebyshev 标准域)
        t_min, t_max = float(two_theta[0]), float(two_theta[-1])
        span = max(t_max - t_min, 1e-9)
        x = 2.0 * (two_theta - t_min) / span - 1.0

        # 泊松/Poirier 启发权: 1/sqrt(y) → 高强度峰区对 BG 拟合权重低
        sigma = np.sqrt(np.maximum(intensity, 1.0))
        w = 1.0 / sigma
        if not np.all(np.isfinite(w)):
            w = np.ones_like(intensity)

        from numpy.polynomial.chebyshev import chebfit, chebval
        coeffs = chebfit(x, residual, deg=degree, w=w)
        corr = chebval(x, coeffs)

        # corr 范围缩放 gate
        y_dyn = max(float(np.max(intensity) - np.median(intensity)), 1.0)
        corr_range = float(np.max(corr) - np.min(corr))
        if corr_range > max_corr_fraction * y_dyn:
            scale = (max_corr_fraction * y_dyn) / corr_range
            corr = corr * scale

        bg_new = bg_initial + corr
        after_wR = float(self._calc_wR(intensity, simulated + bg_new,
                                       weight=weight))

        # 数值稳定性: any NaN/Inf → 回退
        if not (np.all(np.isfinite(bg_new)) and np.isfinite(after_wR)):
            return bg_initial, before_wR, before_wR

        return bg_new, before_wR, after_wR

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
        asymmetry: float = 0.0,  # v1.1.2 (W17): 低角不对称 (split-PV, 0=关)
    ) -> np.ndarray:
        """从参考峰计算模拟谱 (薄壳, 核心见 phase_display.spectrum_from_refs)

        M21 重构: 谱合成内核提取到 phase_display 复用 (物相分析 v2 叠加显示
        与精修共用同一条路径)。数学等价, 行为不变 — 全量回归证明等价性。
        """
        from polyxrd.services.phase_display import spectrum_from_refs

        return spectrum_from_refs(
            np.asarray(two_theta, dtype=float), phase_peaks,
            weights, fwhm, eta, scale, peak_shape, caglioti,
            asymmetry=float(asymmetry or 0.0),
        )

    @staticmethod
    def _apply_full_cell(
        phase_peaks: list, cell_scales_flat, phases: list, wavelength: float,
        consistent: Optional[list] = None,
    ) -> list:
        """全晶胞参数修正峰位 —— v1.1.2 (W18)。

        ``cell_scales_flat`` 长度 = 6 × 相数, 每相 6 个**相对库值的比例**
        (sa, sb, sc, sα, sβ, sγ); 由 hkl 用一般三斜公式反算 d, 再
        2θ = 2·arcsin(λ/(2d))。与各向同性缩放的区别: 各方向独立 → 能吸收
        各向异性失配 (各向同性缩放只能整体平移)。

        边界: 相无晶胞 / 峰无 hkl / d≤0 → 该相或该峰原样保留;
              sin(θ) ≥ 1 (落在不可测区) → 剔除该反射。
        """
        import math as _math

        lam = float(wavelength or 0.0)
        if lam <= 0 or not phase_peaks:
            return phase_peaks
        try:
            scales = np.asarray(cell_scales_flat, dtype=float).reshape(-1, 6)
        except (ValueError, TypeError):
            return phase_peaks
        out: list = []
        for i, peaks in enumerate(phase_peaks):
            lat = phases[i].lattice if i < len(phases) else None
            if lat is None or i >= scales.shape[0]:
                out.append(peaks)
                continue
            # v1.1.2 (W18) 一致性守卫: 峰表 2θ 必须能由 (hkl, lattice) 重算出来,
            # 否则该相的 hkl 不可信 (内置库多数矿物如此, 实测中位差 9~15°),
            # 强上 full 模式会把峰位算飞 → 该相退化为"用 sa 做各向同性缩放"。
            if consistent is not None and not bool(consistent[i]):
                out.append(RietveldRefiner._scale_phase_peaks(
                    [peaks], [float(scales[i][0])], wavelength)[0])
                continue
            s = scales[i]
            # ⚠ 这里**必须**用严格判零: 优化器的有限差分步长 ~1.5e-8, 而
            # np.allclose 默认 rtol=1e-5 会把这么大的扰动也判成"等于 1",
            # 于是早退 → 雅可比列恒为 0 → 晶胞参数永远不动 (实测踩过)。
            if float(np.max(np.abs(np.asarray(s, dtype=float) - 1.0))) < 1e-12:
                out.append(peaks)
                continue
            a = float(lat.a) * float(s[0])
            b = float(lat.b) * float(s[1])
            c = float(lat.c) * float(s[2])
            al = float(lat.alpha) * float(s[3])
            be = float(lat.beta) * float(s[4])
            ga = float(lat.gamma) * float(s[5])
            conv: list = []
            for p in peaks:
                try:
                    hkl = p[0]
                    if hkl is None:
                        conv.append(p)
                        continue
                    if len(hkl) == 4:      # 六方/三方四指标 (h,k,i,l) → 取 l
                        h, k, l = float(hkl[0]), float(hkl[1]), float(hkl[3])
                    elif len(hkl) >= 3:
                        h, k, l = float(hkl[0]), float(hkl[1]), float(hkl[2])
                    else:
                        conv.append(p)
                        continue
                    inten = float(p[2])
                except (TypeError, ValueError, IndexError):
                    conv.append(p)
                    continue
                d = RietveldRefiner._calc_d_spacing_from_hkl(
                    a, b, c, al, be, ga,
                    int(round(h)), int(round(k)), int(round(l)))
                if d <= 0:
                    conv.append(p)
                    continue
                sin_half = lam / (2.0 * d)
                if sin_half >= 1.0:
                    continue
                conv.append((p[0], 2.0 * _math.degrees(_math.asin(sin_half)), inten))
            out.append(conv)
        return out

    def _seed_from_observed_peaks(self, data: XRDData) -> dict:
        """从**观测峰**反推起点 (v2.0.0 / W25)。

        自动精修最大的问题之一是"起点靠手写网格"。观测峰本身已经含了峰宽与峰位信息:
          - 各峰的 FWHM → 按 Caglioti 关系 `FWHM² = U·tan²θ + V·tanθ + W` 最小二乘反解
            `(U, V, W)` 起点 (真实 Rietveld 程序的通行做法);
          - 中角区 FWHM 中位数 → 固定峰宽模式的 `fwhm` 起点, 同时作为 `W` 的兜底;
          - (零点初值需要与模型峰配对, 可靠性低, 本项不动, 仍由调用方给定/默认 0)

        刻意**不用** `PeakFinder`(阈值相对 Imax, 背景高于阈值时会把噪声全判成峰 ——
        实测合成数据上返回 120 个假峰、FWHM 10.7°), 也不用物相识别那条高精度链路
        (`default_peak_list`, 个别试样要 30~40 s)。这里用自带轻量估计: 中值背景扣除 →
        `k·σ` (σ 取残差 MAD) 阈值找局部极大 → 半高宽扫描测 FWHM。毫秒级且背景鲁棒。

        返回 `{"fwhm","U","V","W"}` (不可用时相应键为 None); 任何异常都返回空 dict,
        由调用方回退到原有默认起点。
        """
        try:
            from scipy.ndimage import median_filter

            tt_all = np.asarray(data.two_theta, dtype=float)
            y_all = np.asarray(data.intensity, dtype=float)
            if tt_all.size < 50:
                return {}
            step = float(np.median(np.diff(tt_all))) or 0.02
            win = max(5, int(round(2.0 / step)) | 1)      # ~2° 中值窗作背景
            bg = median_filter(y_all, size=win, mode="nearest")
            ys = y_all - bg
            sigma = 1.4826 * float(np.median(np.abs(ys - np.median(ys))))
            if not np.isfinite(sigma) or sigma <= 0:
                sigma = max(1.0, 0.01 * float(np.max(ys)))
            thr = max(5.0 * sigma, 0.02 * float(np.max(ys)))
            picks = np.where((ys[1:-1] > ys[:-2]) & (ys[1:-1] >= ys[2:])
                             & (ys[1:-1] > thr))[0] + 1
            if picks.size > 40:                            # 只取最强 40 个, 抗噪
                picks = picks[np.argsort(ys[picks])[-40:]]
            pts: list[tuple[float, float]] = []
            n = ys.size
            for i in picks:
                half = ys[i] / 2.0
                # 半高跨越用**线性插值**定位 (只用整数格点的话, 0.02° 步长会把
                # FWHM 量化到 ±0.02°, 足以把 Caglioti 的 U 项拟合到 0)
                lo = int(i)
                while lo > 0 and ys[lo] > half:
                    lo -= 1
                hi = int(i)
                while hi < n - 1 and ys[hi] > half:
                    hi += 1
                if lo >= i or hi <= i or hi <= lo:
                    continue
                yl, yl1 = ys[lo], ys[lo + 1]
                x_lo = tt_all[lo] + ((half - yl) / (yl1 - yl) * step
                                     if yl1 != yl else 0.0)
                yr, yr1 = ys[hi], ys[hi - 1]
                x_hi = tt_all[hi] - ((half - yr) / (yr1 - yr) * step
                                     if yr1 != yr else 0.0)
                fw = float(x_hi - x_lo)
                if 0.01 < fw < 3.0:
                    pts.append((float(tt_all[i]), fw))
            if len(pts) < 3:
                return {}
            tth = np.asarray([p[0] for p in pts], dtype=float)
            fw = np.asarray([p[1] for p in pts], dtype=float)
            # 中角区 (20°~max-10°) 的 FWHM 中位数作固定宽起点: 避开低角不对称与高角弱峰
            hi_lim = max(tth) - 10.0
            mid = (tth >= 20.0) & (tth <= hi_lim)
            fwhm_seed = float(np.median(fw[mid])) if np.any(mid) else float(np.median(fw))
            # Caglioti: y = fw², x1 = tan²θ, x2 = tanθ → [U, V, W]
            tan_t = np.tan(np.radians(tth / 2.0))
            A = np.column_stack([tan_t * tan_t, tan_t, np.ones_like(tan_t)])
            sol, *_ = np.linalg.lstsq(A, fw * fw, rcond=None)
            U, V, W = (float(sol[0]), float(sol[1]), float(sol[2]))
            # 物理合理性守卫: 在该 2θ 范围内 FWHM 必须处处为正且不过分
            grid = np.linspace(float(np.min(tth)), float(np.max(tth)), 64)
            tg = np.tan(np.radians(grid / 2.0))
            fw_pred = np.sqrt(np.clip(U * tg * tg + V * tg + W, 0.0, None))
            if not (np.all(np.isfinite(fw_pred)) and fw_pred.min() > 0.02
                    and fw_pred.max() < 3.0):
                U = V = None
                W = fwhm_seed ** 2
            return {
                "fwhm": fwhm_seed,
                "U": U, "V": V, "W": W,
                "n_peaks": len(pts),
            }
        except Exception:  # noqa: BLE001 - 起点反推失败一律回退默认值
            return {}

    @staticmethod
    def _fit_diagnostics(
        two_theta: np.ndarray, observed: np.ndarray, simulated: np.ndarray,
        min_r_for_advice: float = 8.0,
    ) -> dict:
        """拟合后诊断 (v2.0.0 / W28) —— 让用户知道"模型缺了什么"。

        只做**后处理**, 不改模型。给出:
          - 分段轮廓 R (低角 <30° / 中角 30–60° / 高角 >60°): 暴露"哪个角度区间没拟合好";
          - **Durbin-Watson 统计量** DW = Σ(r_i − r_{i-1})² / Σ r_i²:
            残差若只剩白噪声 DW≈2; DW 明显 <2 (尤其在 1 附近或更低) 说明残差**逐点相关**
            → 模型不完备(缺相/缺物理项), 而不是"差一点点";
          - ``diagnoses``: 按上述量化指标给出的**结构化**建议 (v2.1-B 起为
            ``[{code, params}]``, 文案由 UI 用 tr() 渲染; 仅在整体 R 高于
            ``min_r_for_advice`` 时才给, 免得好拟合上瞎提示)。

        口径说明: 这里的分段 R 与 DW 一律用**未加权**残差 —— 它们的作用是"定位问题区域",
        与用于精度评价的加权 Rwp 分工不同, 返回键名已标明。
        """
        try:
            t = np.asarray(two_theta, dtype=float)
            y = np.asarray(observed, dtype=float)
            c = np.asarray(simulated, dtype=float)
            if t.size < 8 or y.size != t.size or c.size != t.size:
                return {}
            r = y - c
            denom = float(np.sum(r * r))
            dw = float(np.sum(np.diff(r) ** 2) / denom) if denom > 0 else 2.0

            def _r_of(mask) -> float:
                yy = y[mask]
                if yy.size == 0:
                    return 0.0
                s = float(np.sum(yy))
                return (100.0 * float(np.sum(np.abs(r[mask]))) / s) if s > 0 else 0.0

            r_low = _r_of(t < 30.0)
            r_mid = _r_of((t >= 30.0) & (t <= 60.0))
            r_high = _r_of(t > 60.0)
            r_all = _r_of(np.ones_like(t, dtype=bool))

            diags: list[dict] = []
            if r_all > float(min_r_for_advice):
                if dw < 1.0:
                    diags.append({
                        "code": "diag.dw_correlated",
                        "params": {"dw": float(dw)},
                    })
                if r_high > 1.5 * max(r_low, 1e-9):
                    diags.append({
                        "code": "diag.high_angle_residual",
                        "params": {"high": float(r_high), "low": float(r_low)},
                    })
                if r_low > 1.5 * max(r_high, 1e-9):
                    diags.append({
                        "code": "diag.low_angle_residual",
                        "params": {"low": float(r_low), "high": float(r_high)},
                    })
                if not diags:
                    diags.append({
                        "code": "diag.residual_large",
                        "params": {"r": float(r_all), "dw": float(dw)},
                    })
            return {
                "R_low_unweighted": r_low,
                "R_mid_unweighted": r_mid,
                "R_high_unweighted": r_high,
                "R_all_unweighted": r_all,
                "durbin_watson": dw,
                "diagnoses": diags,
            }
        except Exception:  # noqa: BLE001 - 诊断失败不该影响精修
            return {}

    @staticmethod
    def _apply_overall_b(phase_peaks: list, b_per_phase, wavelength: float) -> list:
        """整体温度因子 B 修正峰强 —— v2.0.0 (W22-a)。

        物理: `|F|² → |F|²·exp(−2B·s²)`, `s = sinθ/λ`。
        这是**逐峰乘性**因子 (只依赖该峰的 2θ), 因此无需重算结构因子 —— 相比精修
        原子坐标要"每次迭代重算 |F|²", 这是结构自由度里代价最低的一项。
        缺它会系统性高估高角强度 (B<0 与 B>0 分别对应高角偏强/偏弱)。

        边界: `b_per_phase` 与相数等长; 某相 B≤0 或参数非法 → 该相原样保留;
             波长缺失 → 整体原样返回。
        """
        import math as _math

        lam = float(wavelength or 0.0)
        if lam <= 0 or not phase_peaks:
            return phase_peaks
        try:
            bl = list(np.asarray(b_per_phase, dtype=float).ravel())
        except (TypeError, ValueError):
            return phase_peaks
        out: list = []
        for i, peaks in enumerate(phase_peaks):
            if i >= len(bl) or not np.isfinite(bl[i]) or bl[i] <= 0.0:
                out.append(peaks)
                continue
            b = float(bl[i])
            conv: list = []
            for p in peaks:
                try:
                    tth = float(p[1]); inten = float(p[2])
                except (TypeError, ValueError, IndexError):
                    conv.append(p)
                    continue
                s = _math.sin(_math.radians(tth / 2.0)) / lam
                conv.append((p[0], tth, inten * _math.exp(-2.0 * b * s * s)))
            out.append(conv)
        return out

    @staticmethod
    def _mass_fractions(amp, scale_k, zmv) -> Optional[list]:
        """把"归一化图谱的拟合幅值"换算成**质量分数**（v2.0.0 / W23）。

        Rietveld 质量分数 ∝ `S_p·(ZMV)_p`，其中
          - `S_p` = 该相的物理标度因子
          - `ZMV_p` = 晶胞内质量 (Z·M) × 晶胞体积 V

        本引擎的参考峰表按"每相 max=100"归一化, 拟合出的幅值
        `amp_p = weights_p × scale` 是**相对该归一化图谱**的, 所以需要还原:

            S_p = amp_p · 100 / k_p        (k_p = 未归一化 Σ|F|²·m·LP 的最大值)
            W_p ∝ S_p · ZMV_p

        Args:
            amp: 各相拟合幅值
            scale_k: 各相 k_p; 任一为 None/0 → 返回 None (无法严格定量)
            zmv: 各相同上

        Returns:
            归一化到 100 的质量分数列表; 信息不足时返回 None (调用方退回相对定量)。
        """
        try:
            amp = np.asarray(amp, dtype=float)
            k = np.asarray(scale_k, dtype=float)
            z = np.asarray(zmv, dtype=float)
        except (TypeError, ValueError):
            return None
        if amp.size == 0 or k.size != amp.size or z.size != amp.size:
            return None
        if not np.all(np.isfinite(k)) or not np.all(np.isfinite(z)):
            return None
        if np.any(k <= 0) or np.any(z <= 0):
            return None
        # 还原到物理标度: 归一化图谱 = 100·raw/k, 模型 sim = amp·(100·raw/k) = S·raw
        #   ⇒ S = amp·100/k   (首版写成 amp·k/100 — 比例反了, 实测把 50/50 算成 0.6/99.4)
        s_phys = amp * 100.0 / k
        w = s_phys * z                    # W ∝ S·(ZMV)
        tot = float(np.sum(w))
        if not np.isfinite(tot) or tot <= 0:
            return None
        return [float(x * 100.0 / tot) for x in w]

    @staticmethod
    def _apply_displacement(
        phase_peaks: list, s_mm: float, radius_mm: float = 240.0
    ) -> list:
        """样品位移 (specimen displacement) 峰位修正 —— v1.1.2 (W16)。

        Δ(2θ) = −2·s·cosθ / R   (s 单位 mm, R = 测角仪半径 mm, 结果弧度→度)

        与 ``zero_shift`` 的区别: 零点是**常数**偏移; 样品表面偏离测角仪轴时,
        偏移随 cosθ 变化 —— 低角几乎不动、高角整体漂移, 所以只用零点会把
        高角信息吸进常数项。s > 0 表示样品偏向光源侧 (高角峰向低角移动)。
        仅改峰位, 保留 hkl 与强度; 窗口化/全矩阵两条合成路径都会用到。
        """
        import math as _math

        s = float(s_mm)
        r = float(radius_mm)
        if not phase_peaks or abs(s) < 1e-12 or r <= 0:
            return phase_peaks
        out: list = []
        for peaks in phase_peaks:
            conv: list = []
            for p in peaks:
                try:
                    tth = float(p[1])
                    inten = float(p[2])
                except (TypeError, ValueError, IndexError):
                    conv.append(p)
                    continue
                th = _math.radians(tth / 2.0)
                d_rad = -2.0 * s * _math.cos(th) / r
                conv.append((p[0], tth + _math.degrees(d_rad), inten))
            out.append(conv)
        return out

    @staticmethod
    def _scale_phase_peaks(
        phase_peaks: list, cell_scales, wavelength: float
    ) -> list:
        """按每相各向同性晶胞缩放因子平移参考峰位 (v0.15.2 A 路线)。

        晶胞各向同性缩放 s 等价于 d' = d·s, 由 sinθ = λ/(2d) 得 sinθ' = sinθ/s
        → 2θ' = 2·asin(sinθ/s)。仅改峰位, 保留原 hkl 记法与强度。

        - ``cell_scales`` 与 ``phase_peaks`` 等长; 某相因子为 1.0 时该相峰表原样复用;
        - 波长缺失或 ≤0 时整体原样返回 (不做无意义的几何换算);
        - 缩放后 sinθ' ≥ 1 的反射落在不可测区, 直接剔除。
        """
        lam = float(wavelength or 0.0)
        if lam <= 0 or not phase_peaks:
            return phase_peaks
        import math as _math
        out: list = []
        for peaks, s in zip(phase_peaks, cell_scales):
            try:
                s = float(s)
            except (TypeError, ValueError):
                s = 1.0
            if not peaks or abs(s - 1.0) < 1e-9:
                out.append(peaks)
                continue
            conv: list = []
            for p in peaks:
                try:
                    tth = float(p[1])
                    inten = float(p[2])
                except (TypeError, ValueError, IndexError):
                    conv.append(p)
                    continue
                sin_half = _math.sin(_math.radians(tth / 2.0))
                if sin_half <= 0:
                    conv.append(p)
                    continue
                sin_new = sin_half / s
                if sin_new >= 1.0:
                    continue
                conv.append((p[0], 2.0 * _math.degrees(_math.asin(sin_new)), inten))
            out.append(conv)
        return out

    @staticmethod
    def _texture_cos_alpha(peaks, lattice) -> Optional[np.ndarray]:
        """计算每峰法线与 [001] 织构轴夹角的 cos α (March-Dollase 预计算)。

        cos α = (h·G*[0,2] + k·G*[1,2] + l·G*[2,2]) / (√G*[2,2] · |g|)，
        其中 G* = inv(直接度量矩阵 G)，|g|² = [hkl]·G*·[hkl]。
        四指标 (h,k,i,l) 自动取 (h,k,l)。不可计算的相返回 None:
        无晶格 / hkl 缺失或全零 / 峰数不足 / cos α 无区分度 (std < 0.05,
        此时 r 与 scale 退化耦合, 修正无意义)。
        """
        if not peaks or lattice is None:
            return None
        try:
            a, b, c = float(lattice.a), float(lattice.b), float(lattice.c)
            al = np.radians(float(lattice.alpha))
            be = np.radians(float(lattice.beta))
            ga = np.radians(float(lattice.gamma))
            G = np.array([
                [a * a, a * b * np.cos(ga), a * c * np.cos(be)],
                [a * b * np.cos(ga), b * b, b * c * np.cos(al)],
                [a * c * np.cos(be), b * c * np.cos(al), c * c],
            ])
            Gs = np.linalg.inv(G)
        except Exception:  # noqa: BLE001
            return None
        if len(peaks) < 4:
            return None
        cos_list = []
        for p in peaks:
            try:
                hkl = p[0]
                if len(hkl) == 4:  # 六方/三方四指标 (h,k,i,l) → 取 l
                    hv = (float(hkl[0]), float(hkl[1]), float(hkl[3]))
                elif len(hkl) == 3:
                    hv = (float(hkl[0]), float(hkl[1]), float(hkl[2]))
                else:
                    return None
            except (TypeError, ValueError, IndexError):
                return None
            gv = np.asarray(hv, dtype=float)
            g2 = float(gv @ Gs @ gv)
            if g2 <= 1e-12:
                return None
            num = (hv[0] * Gs[0, 2] + hv[1] * Gs[1, 2] + hv[2] * Gs[2, 2])
            cos_list.append(abs(float(num / (np.sqrt(Gs[2, 2]) * np.sqrt(g2)))))
        arr = np.asarray(cos_list, dtype=float)
        if not np.all(np.isfinite(arr)) or float(arr.std()) < 0.05:
            return None
        return arr

    @staticmethod
    def _apply_texture(phase_peaks: list, tex_axes: list, tex_params) -> list:
        """把 March-Dollase 修正作用到参考峰强度: I' = I·P(α)/mean(P)。

        P(α) = (r²cos²α + sin²α/r)^(-3/2); r=1 时 P≡1 (无修正)。
        tex_params 只对应 tex_axes 中非 None 的相 (顺序一致)。
        """
        if tex_params is None or len(tex_params) == 0:
            return phase_peaks
        out: list = []
        k = 0
        for peaks, cos_a in zip(phase_peaks, tex_axes):
            if cos_a is None or k >= len(tex_params):
                out.append(peaks)
                continue
            r = float(tex_params[k])
            k += 1
            try:
                ca2 = np.asarray(cos_a, dtype=float) ** 2
                corr = (r * r * ca2 + (1.0 - ca2) / r) ** (-1.5)
                mean = float(np.mean(corr))
                if mean <= 0 or not np.isfinite(mean):
                    out.append(peaks)
                    continue
                corr = corr / mean
            except Exception:  # noqa: BLE001
                out.append(peaks)
                continue
            conv: list = []
            for p, f in zip(peaks, corr):
                try:
                    conv.append((p[0], float(p[1]), float(p[2]) * float(f)))
                except (TypeError, ValueError, IndexError):
                    conv.append(p)
            out.append(conv)
        return out

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

        # ── v1.1.2 修正: 漏了归一化因子 ────────────────────────────────
        # 一般三斜公式是 1/d² = (上式) / (1 − cos²α − cos²β − cos²γ + 2cosαcosβcosγ),
        # 分母 = (V/(abc))²。旧实现只算了分子 (上面那个 volume 算完就再没用过, 正是漏项
        # 的旁证) → **非正交晶胞全部算错**: 立方/正交因子=1 侥幸正确 (Fluorite 实测自洽
        # 0.0007°), 而六方/三方 (γ=120°) 因子=0.75 → d 偏大 √(4/3) 倍。
        # 实测: ZnO(100) 27.42°(错) → 31.767°(对); ZnO(101) 31.26 → 36.252;
        #       Brucite(001) 16.09 → 18.602 —— 修正后与文献/PDF 卡一致。
        _norm = (1.0 - cos_a**2 - cos_b**2 - cos_g**2
                 + 2.0 * cos_a * cos_b * cos_g)
        if _norm > 1e-12:
            inv_d_sq = inv_d_sq / _norm

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

    @staticmethod
    def _calc_profile_metrics(
        observed: np.ndarray,
        simulated: np.ndarray,
        sigma2: Optional[np.ndarray] = None,
        n_params: int = 0,
        weight: Optional[np.ndarray] = None,
    ) -> dict:
        """计算通用 R 因子组 (Rwp / Rexp / Rp / chi2 / GOF)。

        - Rwp  = sqrt(Σ w (y_obs - y_calc)² / Σ w y_obs²) × 100  (即原 wR)
        - Rexp = sqrt((N - P) / Σ w y_obs²) × 100  (期望 R, N=数据点, P=参数数)
        - Rp   = Σ|y_obs - y_calc| / Σ y_obs × 100  (轮廓 R, 不加权)
        - GOF  = Rwp / Rexp  (标准 "goodness of fit", 理想值 ≈ 1)
        - chi2 = Σ w (y_obs - y_calc)²; chi2_red = chi2 / (N - P) = GOF²

        权重口径 (v1.1.2 修正):
          ``sigma2`` = **未归一化**的方差数组 σ², 内部取 w = 1/σ²。
          计数统计下 σ² ≈ y (Poisson / Poirier), 此时 Σ w·y² ≈ Σ y —
          这正是标准 Rexp 的分母。旧实现传的是"均一化为均值 1 的权重",
          归一化把统计尺度乘掉了, 导致 Rexp 偏小一个数量级 (实测 130×)。

        ``weight`` 为**遗留**参数 (已归一化的权重), 仅为兼容旧调用方保留;
        新代码一律传 ``sigma2``。Rwp 对 w 的整体尺度不变, 故两者 Rwp 一致。

        输入为**含背景的全谱** (与 Rietveld 惯例一致); w 缺省为单位权。
        """
        observed = np.asarray(observed, dtype=float)
        simulated = np.asarray(simulated, dtype=float)
        if sigma2 is not None:
            weight = 1.0 / np.maximum(np.asarray(sigma2, dtype=float), 1e-12)
        elif weight is None:
            weight = np.ones_like(observed)
        else:
            weight = np.asarray(weight, dtype=float)

        rwp = RietveldRefiner._calc_wR(observed, simulated, weight)
        n_pts = int(observed.size)
        n_free = max(1, n_pts - max(0, int(n_params)))
        denom = float(np.sum(weight * observed ** 2))
        rexp = (
            float(np.sqrt(n_free / denom) * 100)
            if denom > 0 else 100.0
        )
        rp_denom = float(np.sum(observed))
        rp = (
            float(np.sum(np.abs(observed - simulated)) / rp_denom * 100)
            if rp_denom > 0 else 100.0
        )
        gof = float(rwp / rexp) if rexp > 0 else 0.0
        chi2 = float(np.sum(weight * (observed - simulated) ** 2))
        return {
            "Rwp": rwp,
            "Rexp": rexp,
            "Rp": rp,
            "GOF": gof,
            "chi2": chi2,
            "chi2_red": chi2 / float(n_free),
        }

    # ------------------------------------------------------------------
    # Le Bail 晶胞参数精修 (P4)
    # ------------------------------------------------------------------

    def refine_le_bail(
        self,
        data: XRDData,
        phase: Phase,
        refine_param: str = "a",
        scale_range: tuple[float, float] = (0.98, 1.02),
        n_scan: int = 41,
        n_extract_cycles: int = 3,
        fwhm: float = 0.15,
        eta: float = 0.5,
        max_peaks: int = 50,
    ) -> RefinementResult:
        """Le Bail 晶胞参数精修 (无需原子占位 / 结构强度模型)

        算法 (经典 Le Bail 迭代):
        1. 对候选晶胞参数 (选定参数 × 尺度因子 s), 从 hkl 列表计算
           允许衍射峰位 2θ(hkl)
        2. 强度提取迭代: 各衍射峰积分强度 I_k 按最小二乘从观测谱动态
           提取 (I_k ← Σ y_obs·PV_k / Σ PV_k², 窗口 = 峰位 ± 3σ),
           I_k 不依赖结构模型 — 这是 Le Bail 与 Rietveld 的本质区别
        3. 以 Rwp = sqrt(Σ(y_obs-y_calc)²/Σy_obs²) 为目标, 网格扫描
           scale 因子取最优; 良好初始结构模型缺失时也可收敛

        Args:
            data: 实验 XRD 数据
            phase: 待精修物相 (需含 lattice 与 hkl 参考)
            refine_param: 精修的晶胞参数名 ("a"/"b"/"c"/"alpha"/"beta"/"gamma")
            scale_range: 尺度因子扫描范围 (相对值)
            n_scan: 网格扫描点数
            n_extract_cycles: 每个候选晶胞的强度提取迭代次数
            fwhm: 峰宽 (固定)
            eta: pseudo-Voigt 混合系数 (固定)
            max_peaks: 参与拟合的最大衍射峰数

        Returns:
            RefinementResult (phases[0].lattice 为精修后晶胞)
        """
        two_theta = np.asarray(data.two_theta, dtype=float)
        intensity = np.asarray(data.intensity, dtype=float)

        lat = phase.lattice if phase.lattice is not None else LatticeParams()
        if refine_param not in ("a", "b", "c", "alpha", "beta", "gamma"):
            raise ValueError(f"不支持的精修参数: {refine_param}")

        # hkl 列表 (与 _calc_peak_positions 相同的生成方式)
        hkl_list = [
            (h, k, l)
            for h in range(-3, 4)
            for k in range(-3, 4)
            for l in range(-3, 4)
            if not (h == 0 and k == 0 and l == 0)
        ]

        # 背景一次估计 (中值滤波, 与 Rietveld 引擎一致)
        bg = self._estimate_background(intensity, "median", wide_window=True)
        y_obs = np.clip(intensity - bg, 0.0, None)

        sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        gamma = fwhm / 2.0

        def _peak_positions(scale: float) -> list[float]:
            params = dict(
                a=lat.a, b=lat.b, c=lat.c,
                alpha=lat.alpha, beta=lat.beta, gamma=lat.gamma,
            )
            params[refine_param] = params[refine_param] * scale
            positions = self._calc_peak_positions(
                params["a"], params["b"], params["c"],
                params["alpha"], params["beta"], params["gamma"],
                data.wavelength, float(two_theta[0]), float(two_theta[-1]),
            )
            return positions[:max_peaks]

        def _le_bail_eval(scale: float) -> tuple[float, np.ndarray]:
            """给定尺度因子: 强度提取迭代 + 返回 (Rwp, y_calc)

            匹配门控 (关键稳定化): 只有计算峰位处存在显著观测强度的峰
            才参与强度提取, 其余峰强度置零。否则错配峰的窗口落在真实
            峰尾部时会因 Σpv²→0 产生 "尾峰窃取" (强度爆炸), 使 Rwp
            对峰位失敏, 晶胞扫描失效。
            """
            positions = _peak_positions(scale)
            if not positions:
                return 100.0, np.zeros_like(two_theta)
            pos = np.asarray(positions, dtype=float)

            # 峰窗口 (半宽 3σ)
            half_win = max(3, int(np.ceil(3.0 * sigma / max(
                float(np.median(np.diff(two_theta))), 1e-9))))

            # ── 匹配门控: 峰位处观测强度须 ≥ 5% 全谱最大 ───────────
            y_max = float(np.max(y_obs)) if y_obs.size else 0.0
            match_thr = 0.05 * y_max
            c_idx = np.clip(
                np.searchsorted(two_theta, pos), 0, len(two_theta) - 1
            )
            y_at_pos = y_obs[c_idx]
            matched = y_at_pos >= match_thr

            # 初始强度: 峰位处观测强度 (截断非负, 未匹配峰置零)
            I = np.where(matched, np.clip(y_at_pos, 0.0, None), 0.0)

            def _build_calc(I_vals: np.ndarray) -> np.ndarray:
                y_c = np.zeros_like(two_theta)
                for ik, p in zip(I_vals, pos):
                    if ik <= 0.0:
                        continue
                    d = two_theta - p
                    g = np.exp(-0.5 * (d / sigma) ** 2)
                    lz = gamma ** 2 / (d * d + gamma ** 2)
                    y_c += ik * (eta * g + (1.0 - eta) * lz)
                return y_c

            # ── 经典 Le Bail 强度更新 (仅对匹配峰, 带脊正则 + 上限) ──
            for _ in range(max(1, n_extract_cycles)):
                y_calc = _build_calc(I)
                for j in np.nonzero(matched)[0]:
                    p = pos[j]
                    c = int(c_idx[j])
                    lo, hi = max(0, c - half_win), min(len(two_theta), c + half_win + 1)
                    d = two_theta[lo:hi] - p
                    g = np.exp(-0.5 * (d / sigma) ** 2)
                    lz = gamma ** 2 / (d * d + gamma ** 2)
                    pv = eta * g + (1.0 - eta) * lz
                    denom = float(np.sum(pv * pv))
                    if denom <= 1e-12:
                        continue
                    # 减去其他峰在该窗口的贡献, 避免重叠峰重复计数
                    others = y_calc[lo:hi] - I[j] * pv
                    raw = float(np.sum((y_obs[lo:hi] - others) * pv)
                                / (denom * (1.0 + 0.05)))
                    # 上限: 不超过窗口内观测最大强度的 2 倍 (防窃取)
                    cap = 2.0 * float(np.max(y_obs[lo:hi]))
                    I[j] = min(max(raw, 0.0), cap)

            y_calc = _build_calc(I)

            denom = float(np.sum(y_obs ** 2))
            if denom <= 0:
                return 100.0, y_calc
            rwp = float(np.sqrt(np.sum((y_obs - y_calc) ** 2) / denom) * 100.0)
            return rwp, y_calc + bg

        # 网格扫描 scale 因子
        scales = np.linspace(scale_range[0], scale_range[1], max(5, n_scan))
        best_scale = 1.0
        best_rwp = float("inf")
        best_calc = None
        for s in scales:
            rwp, y_c = _le_bail_eval(float(s))
            if rwp < best_rwp:
                best_rwp = rwp
                best_scale = float(s)
                best_calc = y_c

        # 与初始晶胞 (s=1.0) 对比: 只有更优才接受精修结果
        rwp_init, y_init = _le_bail_eval(1.0)
        if best_rwp >= rwp_init:
            best_scale = 1.0
            best_rwp = rwp_init
            best_calc = y_init

        refined_lat = LatticeParams(
            a=lat.a * (best_scale if refine_param == "a" else 1.0),
            b=lat.b * (best_scale if refine_param == "b" else 1.0),
            c=lat.c * (best_scale if refine_param == "c" else 1.0),
            alpha=lat.alpha * (best_scale if refine_param == "alpha" else 1.0),
            beta=lat.beta * (best_scale if refine_param == "beta" else 1.0),
            gamma=lat.gamma * (best_scale if refine_param == "gamma" else 1.0),
        )

        quality = quality_grade_for(best_rwp)

        refined_phase = Phase(
            name=phase.name,
            formula=phase.formula,
            space_group=phase.space_group,
            lattice=refined_lat,
            reference_peaks=phase.reference_peaks,
            elements=phase.elements,
        )

        _m_lb = self._calc_profile_metrics(
            np.asarray(intensity, dtype=float), np.asarray(best_calc, dtype=float),
            sigma2=np.maximum(np.asarray(intensity, dtype=float), 1.0), n_params=1,
        )
        return RefinementResult(
            phases=[refined_phase],
            observed_data=(two_theta, intensity),
            simulated_data=(two_theta, best_calc),
            residual_data=(two_theta, intensity - best_calc),
            wR=best_rwp,
            Rexp=_m_lb["Rexp"],
            Rb=0.0,   # v2.0.0: 真实 Bragg R 未实现
            Rp=_m_lb["Rp"],
            chi2=_m_lb["chi2"],
            chi2_red=_m_lb["chi2_red"],
            metrics_valid=True,
            GOF=_m_lb["GOF"],
            quality=quality,
            num_cycles=n_scan,
            converged=bool(best_rwp < rwp_init),
            fit_params={
                "engine": "le_bail",
                "refine_param": refine_param,
                "initial_value": float(getattr(lat, refine_param)),
                "refined_value": float(getattr(refined_lat, refine_param)),
                "scale": float(best_scale),
                "rwp_initial": float(rwp_init),
                "rwp_refined": float(best_rwp),
                "n_extract_cycles": int(n_extract_cycles),
            },
        )

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

    # ─────────────────────────────────────────────────────────────
    # M14: 择优取向 / DoC / 内标定量 / 选项入口
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def march_dollase_intensity_factor(
        alpha_deg: float, r: float = 1.0
    ) -> float:
        """March-Dollase 择优取向强度修正因子 G(α)。

        G(α) = (r²·cos²α + (1/r)·sin²α)^(−3/2),  α = 散射矢量与该晶面法线
        同择优轴的夹角 (度), r = 取向参数。

        约定 (r=1 时 G=1, 恒无取向):
          r>1 → 与择优轴近垂直的晶面 (α≈90°) 相对增强 (板状织构典型);
          r<1 → 与择优轴近平行的晶面 (α≈0°) 相对增强。
        """
        a = np.radians(float(alpha_deg))
        ca, sa = np.cos(a), np.sin(a)
        denom = r * r * ca * ca + (1.0 / r) * sa * sa
        if denom <= 0:
            return 1.0
        return float(denom ** (-1.5))

    @staticmethod
    def _hkl_angle(hkl: tuple, direction: tuple) -> float:
        """hkl 散射矢量与择优轴方向的夹角 (度); 退化方向返回 90。"""
        h = np.asarray([float(v) for v in hkl], dtype=float)
        d = np.asarray([float(v) for v in direction], dtype=float)
        if np.linalg.norm(h) < 1e-12 or np.linalg.norm(d) < 1e-12:
            return 90.0
        cosv = float(np.dot(h, d) / (np.linalg.norm(h) * np.linalg.norm(d)))
        cosv = float(np.clip(cosv, -1.0, 1.0))
        return float(np.degrees(np.arccos(cosv)))

    @classmethod
    def apply_preferred_orientation(
        cls, phase: Phase, direction=(0, 0, 1), r: float = 1.0
    ) -> Phase:
        """返回应用了 March-Dollase 择优取向修正的物相副本。

        参考峰强度 × G(α); 无 hkl 信息的峰不变。不修改入参。
        """
        if r is None or abs(float(r) - 1.0) < 1e-9:
            return Phase.from_dict(phase.to_dict())
        refs = []
        for hkl, tt, i in phase.get_reference_peaks():
            if hkl and any(hkl):
                g = cls.march_dollase_intensity_factor(
                    cls._hkl_angle(hkl, direction), float(r))
                refs.append((tuple(hkl), float(tt), float(i) * g))
            else:
                refs.append((tuple(hkl), float(tt), float(i)))
        out = Phase.from_dict(phase.to_dict())
        out.reference_peaks = refs
        return out

    @staticmethod
    def degree_of_crystallinity(
        crystalline: np.ndarray,
        amorphous: np.ndarray,
        two_theta: Optional[np.ndarray] = None,
    ) -> float:
        """结晶度 DoC = 晶相面积 / (晶相面积 + 非晶面积)。

        crystalline/amorphous 为同一 2θ 轴上"扣背景后"的分离模型曲线
        (晶峰模型 与 非晶宽隆模型)。返回 0~1 的分数 (×100 = %)。
        """
        c = np.asarray(crystalline, dtype=float)
        a = np.asarray(amorphous, dtype=float)
        if len(c) != len(a):
            raise ValueError("crystalline 与 amorphous 长度必须一致")
        if two_theta is not None:
            area_c = float(np.trapezoid(np.maximum(c, 0.0), two_theta))
            area_a = float(np.trapezoid(np.maximum(a, 0.0), two_theta))
        else:
            area_c = float(np.trapezoid(np.maximum(c, 0.0)))
            area_a = float(np.trapezoid(np.maximum(a, 0.0)))
        total = area_c + area_a
        return area_c / total if total > 0 else 0.0

    @staticmethod
    def internal_standard_scale(
        phases_with_weights: list,
        std_name: str,
        std_wt_pct: float,
    ) -> Optional[float]:
        """由精修结果求内标定标系数 scale = std_wt_pct / w'_std。

        Returns:
            scale 系数; 内标份额为 0/缺失时返回 None (无法定标)。
        """
        w_std = 0.0
        for p in phases_with_weights:
            if p.name == std_name:
                w_std = float(getattr(p, "weight_fraction", 0.0) or 0.0)
                break
        if w_std <= 0:
            return None
        return float(std_wt_pct) / w_std

    def refine_with_internal_standard(
        self,
        data: XRDData,
        phases: list[Phase],
        std_phase: Phase,
        std_wt_pct: float,
        engine: str = "builtin",
        max_cycles: int = 20,
        **kwargs,
    ) -> RefinementResult:
        """掺入已知含量内标的 Rietveld 定量。

        流程: phases+内标 一起精修 → 得到内标相对份额 w'_std →
        scale = std_wt_pct / w'_std → 各相绝对含量 (wt% of sample)。

        Returns:
            RefinementResult (phases 中不含内标; weight_fraction 为绝对 wt%;
            fit_params["internal_standard"] 记录定标信息)
        """
        combined = [p for p in phases if p is not None]
        if std_phase is None:
            raise ValueError("std_phase 不能为 None")
        combined.append(std_phase)
        result = self.refine(data, combined, engine=engine,
                             max_cycles=max_cycles, **kwargs)
        std_name = std_phase.name or ""
        scale = self.internal_standard_scale(
            result.phases, std_name, float(std_wt_pct))
        if scale is None:
            return result  # 内标份额为 0, 无法定标 (原样返回并交由上层判断)

        abs_phases = []
        for p in result.phases:
            if p.name == std_name:
                continue
            np2 = Phase.from_dict(p.to_dict())
            np2.weight_fraction = round(float(p.weight_fraction or 0.0) * scale, 3)
            abs_phases.append(np2)

        from dataclasses import replace
        new_result = replace(
            result,
            phases=abs_phases,
            fit_params={
                **dict(result.fit_params or {}),
                "internal_standard": {
                    "std_phase": std_name,
                    "std_wt_pct": float(std_wt_pct),
                    "scale": round(scale, 5),
                },
            },
        )
        return new_result
