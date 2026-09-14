"""
Rietveld精修服务
================
封装GSAS-II和powerxrd的Rietveld精修功能。
"""
from __future__ import annotations

import os
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.phase import Phase, LatticeParams
from polyxrd.models.refinement import RefinementResult
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

        try:
            result = refine_func(data, phases_use, strategy, max_cycles, **kwargs)
        except Exception as e:
            # 任何引擎失败时使用内置精修 (不再静默: 记录原因供 UI/调试)
            logger.warning("engine=%s 精修失败, 回退 builtin: %s", engine, e)
            result = self._refine_builtin(data, phases_use, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = engine
            result.fit_params["engine_fallback_reason"] = f"{type(e).__name__}: {e}"

        result.time_seconds = time.time() - start_time
        return result

    # ------------------------------------------------------------------
    # 自动引擎选择 (v0.11.0 打磨)
    # ------------------------------------------------------------------

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
        if self._phases_have_structure(phases):
            py = self._find_gsas2_python()
            if py is not None:
                try:
                    return self._refine_gsas2(
                        data, phases, strategy, max_cycles, **kwargs
                    )
                except Exception as e:
                    reasons.append(f"gsas2 执行失败: {type(e).__name__}: {e}")
            else:
                reasons.append("未找到 GSAS-II 安装 (E:\\GSASII)")
        else:
            reasons.append("存在无结构 CIF 的物相 (builtin 剖面拟合即可)")

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
        py = self._find_gsas2_python()
        bridge = Path(__file__).resolve().parents[3] / "scripts" / "gsas2_bridge.py"
        if not py or not bridge.exists():
            logger.warning("GSAS-II 不可用 (py=%s, bridge 存在=%s), 回退 builtin",
                           py, bridge.exists())
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = "gsas2"
            result.fit_params["engine_fallback_reason"] = "GSAS-II 未安装或 bridge 缺失"
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
                    logger.warning("GSAS-II 桥未产出 output.json, 回退 builtin")
                    result = self._refine_builtin(
                        data, phases, strategy, max_cycles, **kwargs
                    )
                    result.fit_params["engine_requested"] = "gsas2"
                    result.fit_params["engine_fallback_reason"] = "桥未产出结果文件"
                    return result
                with open(out_path, "r", encoding="utf-8") as f:
                    out = _json.load(f)
        except Exception as e:
            logger.warning("GSAS-II 子进程异常, 回退 builtin: %s", e)
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = "gsas2"
            result.fit_params["engine_fallback_reason"] = f"子进程异常: {e}"
            return result

        if not out.get("ok"):
            err = str(out.get("error", ""))[:300]
            logger.warning("GSAS-II 桥返回 ok=False (%s), 回退 builtin", err)
            result = self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
            result.fit_params["engine_requested"] = "gsas2"
            result.fit_params["engine_fallback_reason"] = f"桥内错误: {err}"
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
        quality = ("优秀" if wR < 5 else "良好" if wR < 10
                   else "可接受" if wR < 20 else "需改进")

        # v0.11.0: 使用桥回传的计算谱 (无则保持旧行为 — 观测谱占位)
        ycalc = out.get("ycalc")
        if isinstance(ycalc, list) and len(ycalc) == len(two_theta):
            sim = np.asarray(ycalc, dtype=float)
            sim_data = (data.two_theta, sim)
            resid = (data.two_theta, np.asarray(data.intensity) - sim)
        else:
            sim_data = (data.two_theta, data.intensity)  # 旧行为
            resid = (data.two_theta, np.zeros_like(data.two_theta))

        return RefinementResult(
            phases=refined_phases,
            observed_data=(data.two_theta, data.intensity),
            simulated_data=sim_data,
            residual_data=resid,
            wR=wR,
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
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
        except Exception:
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        # 标记 first-run 完成 (下次可走自动 wizard)
        self._maud_mark_first_run_done()
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
        try:
            from powerxrd.model import PhaseModel
            from powerxrd.lattice import CubicLattice
            from powerxrd.refine import refine as pxr_refine
            _PXR_VERSION = getattr(
                __import__("powerxrd"), "__version__", "4.x"
            )
        except ImportError:
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

        # powerxrd v4 仅支持单相 + 立方
        if len(phases) != 1:
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
        phase = phases[0]
        lat = phase.lattice if phase.lattice is not None else None
        if lat is None:
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)
        cubic_ok = (
            abs(lat.a - lat.b) < 1e-9
            and abs(lat.a - lat.c) < 1e-9
            and abs(lat.alpha - 90.0) < 1e-6
            and abs(lat.beta - 90.0) < 1e-6
            and abs(lat.gamma - 90.0) < 1e-6
        )
        if not cubic_ok:
            return self._refine_builtin(data, phases, strategy, max_cycles, **kwargs)

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
            wR = self._calc_wR(intensity, sim_full)
            n_points = len(intensity)
            n_free = max(1, n_points - len(refine_keys))
            ss_res = float(np.sum((intensity - sim_full) ** 2))
            GOF = float(np.sqrt(ss_res / n_free) / (np.mean(np.abs(intensity)) + 1e-10))

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
            quality = ("优秀" if wR < 5 else "良好" if wR < 10
                       else "可接受" if wR < 20 else "需改进")

            return RefinementResult(
                phases=[refined_phase],
                observed_data=(two_theta, intensity),
                simulated_data=(two_theta, sim_full),
                residual_data=(two_theta, intensity - sim_full),
                wR=wR,
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
          若 wR ≤ wR_threshold (默认 55%) 直接返回; 否则再启 Caglioti
          精细模式, 最终返回两者中 wR 更优者 (结果只会更好不会变差)
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

        # ── 0. 快速路径: 无 Caglioti 快检, wR 达标即返回 ────────────
        wR_threshold = kwargs.get("wR_threshold", 55.0)
        best_quick: Optional[RefinementResult] = None
        if wR_threshold is not None and kwargs.get("use_caglioti", True):
            quick_kw = dict(kwargs)
            quick_kw["use_caglioti"] = False
            quick_kw["n_starts"] = min(3, kwargs.get("n_starts", 3))
            quick_kw["wR_threshold"] = None  # 防止递归再次触发快检
            quick_kw["max_nfev_per_start"] = kwargs.get("max_nfev_per_start", 400)
            try:
                best_quick = self._refine_builtin(
                    data, phases, strategy, max_cycles, **quick_kw
                )
            except Exception:
                best_quick = None
            if best_quick is not None and best_quick.wR <= wR_threshold:
                best_quick.fit_params = {
                    **best_quick.fit_params,
                    "quick_path": True,
                    "wR_threshold": float(wR_threshold),
                }
                return best_quick

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
        # v8: 单起点收敛上限 (实测获胜起点 ~55 nfev, 1200 上限纯属浪费)
        max_nfev_per_start = int(kwargs.get(
            "max_nfev_per_start", min(max_cycles * 20, 400)
        ))

        # ── 1. 背景估计 (v3: SNIP 窗宽增大, 避免削峰引入假残差) ──
        bg = self._estimate_background(intensity, bg_method, wide_window=True)
        y_exp = intensity - bg
        y_exp_pos = np.where(y_exp > 0, y_exp, 0.0).astype(float)
        y_floor = max(float(np.median(y_exp_pos)) * 0.05, 1.0)

        # ── 1b. v0.11.0 R-A1: 统计权重 (opt-in) ──────────────────
        # 旧版 residual 与 _calc_wR 都是单位权, 且 residual 用扣背景的
        # y_exp 而 wR 用含背景的 intensity — 目标函数与评价指标不同量.
        # stat_weights 启用后: residual 乘 sqrt(w), 全部 _calc_wR 调用带
        # 同一组 w (wR 与目标函数自洽, 即 docs/精修算法改进方案.md A1).
        #   "poisson": σ² = max(y, 1)
        #   "poirier": σ² = max(y, 1) + bg   (推荐, 低强度区更稳)
        # w 归一到均值 1, 保持 residual 数值量级与旧版可比 (边界/初值不变).
        stat_weights_mode = str(kwargs.get("stat_weights", "none")).lower()
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
            "cell": True, "zero_shift": True,
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
        # mask["background"] / mask["cell"] 在 builtin 中为 no-op:
        #   background 由 _estimate_background 一次性预处理, 非 fit 维度;
        #   cell 在 builtin 中固定 (未加入 fit 维度)。

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

        for _start_i, x0_i in enumerate(candidates):
            x0_clipped = np.clip(x0_i, lower + 1e-8, upper - 1e-8)
            _tick(_start_i, n_starts + 1)
            try:
                res_opt = least_squares(
                    residual, x0_clipped, bounds=(lower, upper),
                    max_nfev=max_nfev_per_start,
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
            wr_i = _wr_of(sim_i)

            if wr_i < best_wR:
                best_wR = wr_i
                best_result = res_opt
                best_simulated = sim_i

        if best_result is None:
            # 退化: 直接返回起点拟合
            best_result = least_squares(
                residual, candidates[0], bounds=(lower, upper),
                max_nfev=max_nfev_per_start, method="trf",
            )
            _w, _fw, _et, _sc, _zs, _cag = _unpack(best_result.x)
            best_simulated = self._compute_spectrum_from_ref(
                two_theta, phase_peaks, _w, _fw, _et, _sc, peak_shape,
                caglioti=_cag
            )

        # ── 7. v7 局部抛光 (性能+效果平衡) ───────────────────────
        #    取 24 个手工方向 + 9 个 Caglioti 调整方向，而不是 3^8 网格
        _tick(n_starts, n_starts + 1)   # 多起点跑完, 进入抛光阶段
        try:
            cur_x = np.array(best_result.x, dtype=float)
            best_polish_x = cur_x.copy()
            _polish_n = 0   # 抛光评估计数 (用于按固定间隔汇报进度)
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

        # ── v0.11.0 R-A4: Chebyshev 多项式背景抛光 (opt-in) ─────────
        # 在 least_squares + 局部抛光之后, 用已拟合谱对 BG 做一次低频校正.
        # 默认 bg_chebyshev_deg=0 = 关闭 → 行为完全等价旧版, 不影响既有测试.
        # 启用后: 只有在 _chebyshev_background_polish 真的改进了 wR (gate)
        # 时才采纳, 否则保持现状 — 双层保护 (内部缩放 + 外部 wR gate).
        bg_cheb_deg = int(kwargs.get("bg_chebyshev_deg", 0))
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
            except Exception:
                # 任何异常 → 静默回退 (守门员: 默认值已关; 走正门也不应崩)
                bg_cheb_applied = False

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

        result = RefinementResult(
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
            },
        )

        # ── v8: 快速路径结果择优 (快检 wR 更低则返回快检结果) ──────
        if best_quick is not None and best_quick.wR < result.wR:
            best_quick.fit_params = {
                **best_quick.fit_params,
                "caglioti_fallback": True,
            }
            return best_quick
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
    ) -> np.ndarray:
        """从参考峰计算模拟谱 (薄壳, 核心见 phase_display.spectrum_from_refs)

        M21 重构: 谱合成内核提取到 phase_display 复用 (物相分析 v2 叠加显示
        与精修共用同一条路径)。数学等价, 行为不变 — 全量回归证明等价性。
        """
        from polyxrd.services.phase_display import spectrum_from_refs

        return spectrum_from_refs(
            np.asarray(two_theta, dtype=float), phase_peaks,
            weights, fwhm, eta, scale, peak_shape, caglioti,
        )

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

        quality = "优秀" if best_rwp < 5 else ("良好" if best_rwp < 10
                  else ("可接受" if best_rwp < 20 else "需改进"))

        refined_phase = Phase(
            name=phase.name,
            formula=phase.formula,
            space_group=phase.space_group,
            lattice=refined_lat,
            reference_peaks=phase.reference_peaks,
            elements=phase.elements,
        )

        return RefinementResult(
            phases=[refined_phase],
            observed_data=(two_theta, intensity),
            simulated_data=(two_theta, best_calc),
            residual_data=(two_theta, intensity - best_calc),
            wR=best_rwp,
            GOF=0.0,
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
