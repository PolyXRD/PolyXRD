"""
仪器校正服务 (M08, Sprint 1)
============================
零点偏移与样品位移校正、误差直方图估计、内标校正。

符号约定 (务必一致):
  - 本模块"误差"定义为: 峰位观测值相对真值的偏高量。
    obs_tt = true_tt + error  →  校正: true_tt = obs_tt - error
  - zero_point_shift(xrd, dz) 把每个峰位减 dz (dz>0 表示仪器零点使峰偏高)。
  - specimen_displacement 预测函数返回同样语义的仪器误差 offset(2θ)。
  注意: 数据前校正(减误差)与 Rietveld 模型内加误差项方向相反 (见项目文档)。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Union

import numpy as np

from polyxrd.models.xrd_data import XRDData

RAD2DEG = 180.0 / np.pi


def _as_deg(rad: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    return rad * RAD2DEG


def _theta_deg(tt: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    return np.asarray(tt, dtype=float) / 2.0


class Calibration:
    """仪器误差的预测、估计与扣除。"""

    # ── 零点偏移 (常数) ──────────────────────────────────────

    @staticmethod
    def zero_point_offset(tt: Union[float, np.ndarray], dz: float
                          ) -> Union[float, np.ndarray]:
        """常数零点误差: 峰被抬高 dz (度) 时误差恒为 +dz。"""
        return np.full(np.shape(tt), float(dz)) if np.ndim(tt) else float(dz)

    @staticmethod
    def zero_point_shift(xrd: XRDData, dz: float) -> XRDData:
        """扣除常数零点误差: tt_new = tt_obs - dz (轴整体平移, 步长不变)"""
        return replace(
            xrd,
            two_theta=np.asarray(xrd.two_theta, dtype=float) - float(dz),
        )

    # ── 样品位移 (依 2θ 变化) ────────────────────────────────

    @staticmethod
    def specimen_displacement_offset(
        two_theta: Union[float, np.ndarray],
        displacement: float,
        radius: float = 240.0,
        mode: str = "reflection",
    ) -> Union[float, np.ndarray]:
        """样品位移引起的峰位误差 (度): error = tt_obs - tt_true。

        mode="reflection" (Bragg-Brentano 平板样品, 默认):
          Δ(2θ) = -2·(s/R)·cosθ  (rad) → error(°) = -2·(s/R)·cosθ·180/π
          s>0 表示样品表面相对聚焦圆下移 → 峰移向低角 (误差为负)。
        mode="transmission" (透射 Debye-Scherrer):
          轴向位移近似 Δ(2θ) = (s·cos²θ)/(R·sinθ) (rad), 符号随几何。
          此处取 error(°) = (s·cos²θ)/(R·sinθ)·180/π (s>0 样品移离光轴)。
        """
        tt = np.asarray(two_theta, dtype=float)
        th = np.radians(_theta_deg(tt))
        if mode == "reflection":
            off = -2.0 * (displacement / radius) * np.cos(th)
        elif mode == "transmission":
            with np.errstate(divide="ignore", invalid="ignore"):
                off = (displacement / radius) * np.cos(th) ** 2 / np.sin(th)
            off = np.where(np.sin(th) < 1e-9, 0.0, off)
        else:
            raise ValueError(f"未知 mode: {mode} (reflection|transmission)")
        out = _as_deg(off)
        return float(out) if np.ndim(two_theta) == 0 else out

    @staticmethod
    def specimen_displacement_shift(
        xrd: XRDData,
        displacement: float,
        radius: float = 240.0,
        mode: str = "reflection",
    ) -> XRDData:
        """扣除样品位移误差: 逐点 tt_true ≈ tt_obs - offset(tt_obs)。

        注意: 轴随之变为非等步长 (位移误差与 cosθ 有关)。
        """
        tt = np.asarray(xrd.two_theta, dtype=float)
        off = Calibration.specimen_displacement_offset(tt, displacement, radius, mode)
        return replace(xrd, two_theta=tt - off)

    # ── 误差估计 (直方图法) ──────────────────────────────────

    @staticmethod
    def _extract_ref_two_theta(refs: Iterable) -> list[float]:
        """归一化参考峰: 接受 list[Phase/Peak/dict] 或 [(tt,I)] / [tt]"""
        out: list[float] = []
        for r in refs:
            if r is None:
                continue
            if hasattr(r, "two_theta"):          # Peak
                out.append(float(r.two_theta))
            elif hasattr(r, "get_reference_peaks"):  # Phase
                for _, tt, _ in r.get_reference_peaks():
                    out.append(float(tt))
            elif isinstance(r, dict):
                tt = r.get("two_theta", r.get("tt"))
                if tt is not None:
                    out.append(float(tt))
            else:
                v = float(r)
                out.append(v)
        return out

    @classmethod
    def estimate_from_histogram(
        cls,
        observed_tt: Iterable[float],
        ref_tt: Iterable,
        tol: float = 0.6,
        bin_width: float = 0.02,
        search_window: float = 0.5,
    ) -> float:
        """由"实测峰 vs 参考峰"的 Δ2θ 直方图众数估计常数零点误差 dz。

        对每条实测峰, 在 ±search_window 内找最近参考峰, 记录 delta=obs-ref;
        将 deltas 分箱 (bin_width), 返回计数最多的箱中心作为 dz。
        (dz>0: 实测峰系统偏高; 对应 zero_point_shift(xrd, dz) 扣除)
        """
        refs = np.array(sorted(cls._extract_ref_two_theta(ref_tt)), dtype=float)
        if len(refs) == 0:
            return 0.0
        deltas: list[float] = []
        for o in cls._extract_ref_two_theta(observed_tt):
            o = float(o)
            i = int(np.searchsorted(refs, o))
            best = None
            if i < len(refs):
                best = refs[i]
            if i > 0 and (best is None or abs(refs[i - 1] - o) < abs(best - o)):
                best = refs[i - 1]
            if best is None:
                continue
            d = o - best
            if abs(d) <= search_window:
                deltas.append(d)
        if not deltas:
            return 0.0
        lo_edge = np.floor(min(deltas) / bin_width) * bin_width - bin_width
        hi_edge = np.ceil(max(deltas) / bin_width) * bin_width + bin_width
        edges = np.arange(lo_edge, hi_edge + bin_width / 2, bin_width)
        hist, _ = np.histogram(deltas, bins=edges)
        idx = int(np.argmax(hist))
        center = (edges[idx] + edges[idx + 1]) / 2.0
        return float(round(center, 4))

    # ── 内标校正 ─────────────────────────────────────────────

    @classmethod
    def calibrate_to_internal_standard(
        cls,
        observed_tt: Iterable[float],
        std_phase,
        tol: float = 0.6,
    ) -> float:
        """用已知内标物相的参考峰对齐实测峰, 反推零点误差 dz。

        等价于: 参考峰取 std_phase.get_reference_peaks(), 再走直方图法。
        返回值传给 zero_point_shift / 后续识别前校正。
        """
        return cls.estimate_from_histogram(
            observed_tt,
            cls._extract_ref_two_theta([std_phase]),
            tol=tol,
        )
