"""
峰管理服务 (M06, Sprint 1)
==========================
在 PeakList 之上提供不可变式编辑与派生操作:
  - 手动增 / 删 / 改峰 (返回新 PeakList, 不污染原列表)
  - 2θ 区域排除掩码 (供峰表/匹配/定量跳过指定区间)
  - 残差峰: 实测峰中未被已选物相参考峰解释的峰 (多相迭代用)
  - 相对强度重标定 (最强=100)
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Optional

import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.xrd_data import XRDData


class PeakManager:
    """峰列表的编辑与派生计算 (纯函数风格, 方便单测)。"""

    # ── 编辑: 全部返回新 PeakList, 不改入参对象 ──────────────

    @staticmethod
    def _clone(peaks: PeakList) -> list:
        return [replace(p) for p in peaks.peaks]

    @classmethod
    def add_peak(
        cls,
        peaks: PeakList,
        two_theta: float,
        intensity: float = 100.0,
        fwhm: float = 0.1,
        wavelength: float = 1.5406,
        keep_sorted: bool = True,
    ) -> PeakList:
        """手动加峰 (保持 2θ 升序)"""
        from polyxrd.services.peak_finder import PeakFinder
        new = cls._clone(peaks)
        new.append(Peak(
            two_theta=float(two_theta),
            intensity=float(intensity),
            fwhm=float(fwhm),
            d_spacing=PeakFinder._calc_d_spacing(float(two_theta), wavelength),
        ))
        pl = PeakList(peaks=new, source=peaks.source)
        if keep_sorted:
            pl.sort_by_two_theta()
        return pl

    @classmethod
    def delete_peak(cls, peaks: PeakList, index: Optional[int] = None,
                    two_theta: Optional[float] = None) -> PeakList:
        """删除峰: 按索引或按 2θ 就近删除"""
        if index is None and two_theta is None:
            return PeakList(peaks=cls._clone(peaks), source=peaks.source)
        new = cls._clone(peaks)
        if index is not None:
            if 0 <= index < len(new):
                new.pop(index)
        else:
            best = min(range(len(new)),
                       key=lambda i: abs(new[i].two_theta - float(two_theta)))
            if abs(new[best].two_theta - float(two_theta)) <= 1.0:
                new.pop(best)
        return PeakList(peaks=new, source=peaks.source)

    @classmethod
    def edit_peak(cls, peaks: PeakList, index: int, **kwargs) -> PeakList:
        """修改峰属性 (two_theta/intensity/fwhm/...)。two_theta 变更后自动重排。"""
        new = cls._clone(peaks)
        if not (0 <= index < len(new)):
            return PeakList(peaks=new, source=peaks.source)
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        new[index] = replace(new[index], **kwargs)
        pl = PeakList(peaks=new, source=peaks.source)
        pl.sort_by_two_theta()
        return pl

    # ── 区域排除 ─────────────────────────────────────────────

    @staticmethod
    def exclude_regions_mask(
        two_theta: np.ndarray, regions: Iterable[tuple[float, float]]
    ) -> np.ndarray:
        """生成 2θ 排除掩码: 落在任一 [lo, hi] 区间内的点为 False。

        边界: 区间相交自动合并; lo>=hi 的区间忽略并告警。
        """
        tt = np.asarray(two_theta, dtype=float)
        mask = np.ones(len(tt), dtype=bool)
        merged = PeakManager._merge_regions(list(regions))
        for lo, hi in merged:
            mask &= ~((tt >= lo) & (tt <= hi))
        return mask

    @staticmethod
    def _merge_regions(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
        valid = sorted(
            (float(lo), float(hi)) for lo, hi in regions if hi > lo
        )
        merged: list[tuple[float, float]] = []
        for lo, hi in valid:
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        return merged

    @staticmethod
    def filter_peaks_by_mask(peaks: PeakList, mask: np.ndarray,
                             two_theta: np.ndarray) -> PeakList:
        """按区间掩码过滤峰表 (peak.two_theta 落入保留区间才保留)"""
        tt = np.asarray(two_theta, dtype=float)
        keep = [replace(p) for p in peaks.peaks
                if PeakManager._two_theta_in_kept(p.two_theta, tt, mask)]
        return PeakList(peaks=keep, source=peaks.source)

    @staticmethod
    def _two_theta_in_kept(tt_val: float, grid: np.ndarray, mask: np.ndarray) -> bool:
        idx = int(np.argmin(np.abs(grid - tt_val)))
        if abs(grid[idx] - tt_val) <= 0.5 * (grid[1] - grid[0]) + 1e-9:
            return bool(mask[idx])
        # 峰在网格范围外: 保守保留
        return True

    # ── 残差峰 (多相迭代核心) ────────────────────────────────

    @staticmethod
    def compute_residual_peaks(
        observed: PeakList,
        phases: Iterable,
        tolerance: float = 0.15,
        regions: Optional[Iterable[tuple[float, float]]] = None,
    ) -> PeakList:
        """实测峰中未被任何物相参考峰解释的峰 (残差峰)。

        Args:
            observed: 实测峰表
            phases: 已选物相 (每个须有 get_reference_peaks() -> [(hkl,2θ,I),...])
            tolerance: 峰位容差 (度)
            regions: 需整体忽略的 2θ 区间 (如强峰拖尾/排除带)
        Returns:
            新的 PeakList (仅含残差峰)
        """
        if regions:
            grid = np.linspace(
                min(p.two_theta for p in observed.peaks) - 1.0 if observed.peaks else 0,
                max(p.two_theta for p in observed.peaks) + 1.0 if observed.peaks else 1,
                4000,
            )
            mask = PeakManager.exclude_regions_mask(grid, regions)
            observed = PeakManager.filter_peaks_by_mask(observed, mask, grid)

        ref_tts: list[list[float]] = []
        for ph in phases:
            if ph is None:
                continue
            ref = getattr(ph, "get_reference_peaks", None)
            tts = [t for _, t, _ in (ref() if ref else [])]
            if tts:
                ref_tts.append(sorted(tts))

        residual = []
        for p in observed.peaks:
            explained = False
            for refs in ref_tts:
                if PeakManager._nearest_within(p.two_theta, refs, tolerance):
                    explained = True
                    break
            if not explained:
                residual.append(replace(p))
        return PeakList(peaks=residual, source=observed.source)

    @staticmethod
    def _nearest_within(tt: float, sorted_refs: list[float], tol: float) -> bool:
        import bisect
        i = bisect.bisect_left(sorted_refs, tt)
        if i < len(sorted_refs) and abs(sorted_refs[i] - tt) <= tol:
            return True
        if i > 0 and abs(sorted_refs[i - 1] - tt) <= tol:
            return True
        return False

    # ── 相对强度 ──────────────────────────────────────────────

    @classmethod
    def rescale_relative_intensities(cls, peaks: PeakList) -> PeakList:
        """相对强度重标定: 最强峰 = 100, 其余按比例缩放"""
        new = cls._clone(peaks)
        imax = max((p.intensity for p in new), default=0.0)
        if imax > 0:
            for p in new:
                p.intensity = float(p.intensity / imax * 100.0)
        return PeakList(peaks=new, source=peaks.source)
