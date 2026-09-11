"""
RIR (Reference Intensity Ratio) 半定量分析 (M13, Sprint 2)
==========================================================
原理: w_i ∝ I_i / (I/Icor)_i
  I_i     = 物相 i 参考谱最强峰在实测谱中的强度 (峰高; 推荐先做 M07 拟合)
  I/Icor  = 该相最强峰相对刚玉(α-Al2O3)最强峰的强度比 (来自库/文献/实验)

局限 (note 中提示): RIR 假设无择优取向/微吸收, 用单峰代表整相;
重叠峰会让结果有偏; 精确含量请用 Rietveld (M14)。
"""
from __future__ import annotations

from typing import Optional


from polyxrd.models.peak import PeakList
from polyxrd.models.phase import Phase
from polyxrd.models.rir import RIRResult


class RIRAnalyzer:
    """RIR 半定量。"""

    # ── 主流程 ───────────────────────────────────────────────

    def rir_quantify(
        self,
        phases: list,
        peaks: PeakList,
        iicor: Optional[dict] = None,
        tol: float = 0.15,
    ) -> RIRResult:
        """相对 RIR 定量 (无内标, 归一化到 100%)。

        Args:
            phases: 已确认的物相列表 (每个含 reference_peaks)
            peaks: 实测峰表 (建议先经 M07 拟合得到峰高/面积)
            iicor: {物相名或化学式: I/Icor}; 缺失的相默认 1.0 并提示
            tol: 最强峰匹配容差 (度)
        """
        iicor_map = dict(iicor or {})
        notes = []

        raw: dict[str, float] = {}
        used: dict[str, float] = {}
        for ph in phases:
            if ph is None:
                continue
            key = ph.name or ""
            ic = self._resolve_iicor(ph, iicor_map)
            if ic is None:
                ic = 1.0
                notes.append(f"{key}: 无 I/Icor, 暂按 1.0")
            refs = ph.get_reference_peaks()
            if not refs:
                notes.append(f"{key}: 无参考峰, 含量按 0")
                raw[key] = 0.0
                continue
            # 参考谱最强峰 (相对强度最大)
            tt_main, i_main = max(((float(tt), float(i))
                                   for _, tt, i in refs if i is not None),
                                  key=lambda x: x[1])
            obs = self._nearest_peak_intensity(peaks, tt_main, tol)
            if obs is None:
                notes.append(f"{key}: 最强峰 {tt_main:.2f}° 未在实测峰中找到, 含量按 0")
                raw[key] = 0.0
            else:
                raw[key] = obs / ic if ic > 0 else 0.0
            used[key] = ic

        total = sum(raw.values())
        if total <= 0:
            return RIRResult(weights={k: 0.0 for k in raw},
                             quality="error",
                             note="; ".join(notes) or "无可用峰强度",
                             iicor_used=used, absolute=False)
        weights = {k: round(v / total * 100.0, 2) for k, v in raw.items()}
        quality = "ok" if not notes else "low"
        return RIRResult(weights=weights, quality=quality,
                         note="; ".join(notes), iicor_used=used,
                         absolute=False)

    # ── 内标绝对定量 ─────────────────────────────────────────

    def internal_standard_quantify(
        self,
        phases: list,
        std_phase,
        std_wt_pct: float,
        peaks: PeakList,
        iicor: Optional[dict] = None,
        tol: float = 0.15,
    ) -> RIRResult:
        """掺入已知含量内标 → 绝对定量 (wt% of sample)。

        流程: 把内标并入集合做 RIR 归一 → 得到内标的相对份额 w'_std,
        再由 scale = std_wt_pct / w'_std 折算其余各相绝对含量。
        """
        combined = [p for p in phases if p is not None]
        if std_phase is not None:
            combined.append(std_phase)
        rel = self.rir_quantify(combined, peaks, iicor=iicor, tol=tol)
        std_key = (std_phase.name or "") if std_phase is not None else ""
        w_std = rel.weights.get(std_key, 0.0)
        if w_std <= 0:
            return RIRResult(
                weights={p.name: 0.0 for p in phases if p is not None},
                quality="error",
                note=f"内标 {std_key} 相对份额为 0, 无法定标 (检查内标峰是否匹配)",
                iicor_used=rel.iicor_used, absolute=True)
        scale = float(std_wt_pct) / w_std
        weights = {}
        for p in phases:
            if p is None:
                continue
            w = rel.weights.get(p.name or "", 0.0) * scale
            weights[p.name or ""] = round(w, 2)
        return RIRResult(weights=weights, quality=rel.quality,
                         note=f"内标 {std_key} {std_wt_pct}% 定标 (scale={scale:.3f})",
                         iicor_used=rel.iicor_used, absolute=True)

    # ── 内部 ─────────────────────────────────────────────────

    @staticmethod
    def _resolve_iicor(phase: Phase, iicor_map: dict) -> Optional[float]:
        for key in (phase.name or "", phase.formula or ""):
            if key in iicor_map:
                return float(iicor_map[key])
        return None

    @staticmethod
    def _nearest_peak_intensity(peaks: PeakList, tt: float, tol: float
                                ) -> Optional[float]:
        best = None
        best_d = float("inf")
        for p in peaks.peaks:
            d = abs(p.two_theta - tt)
            if d < best_d:
                best_d = d
                best = p
        if best is not None and best_d <= tol:
            return float(best.intensity or 0.0)
        return None
