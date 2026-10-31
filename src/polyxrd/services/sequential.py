"""
序贯（迭代式）多相鉴定
======================
单次检索只回答"整张谱最像哪几个相"。真实多相样品需要的是**循环**：确认
最可信的一相 → 把它解释掉的峰从问题上拿走 → 在剩下的峰上再检索 → 确认
下一相 → ……直到剩余峰无相可取。

本模块是这条循环的 GUI 无关引擎，参考 XinMatch `core/search/sequential.py`
的分层思路（不复制代码，按 PolyXRD 的 `Peak` / `Phase` 模型重写）：

:class:`SequentialPhaseIdentifier`
    只管记账：保存**原始**实测峰表（永不修改），按确认顺序保存已确认相，
    每变一次就从原始峰表**整层重算**——每相的峰归属、count 空间比例因子、
    以及逐峰残差强度 ``I_obs − Σ(各相贡献)``。某峰的残差降到自身强度的
    几个百分点即视为"已解释"，退出残差集合；只被解释了一部分的峰保留其
    扣减后的强度（重叠峰是真实物理，不是舍入误差）。

:func:`residual_peak_list`
    把当前残差峰导出成 :class:`~polyxrd.models.peak.PeakList`，直接喂给既有
    检索引擎（`identify_with_*`）；同时提供原峰下标，便于把候选"将解释哪些
    实测峰"映射回原始峰表高亮。

为什么整层重算而不是增量更新
----------------------------
确认顺序有意义：B 相的比例因子是对"A 相之后的剩余强度"拟合的，撤掉 A
必须能改变 B 的数字。每次变更都从原始峰表重算，状态就恒等于
``(实测峰, 相序列)`` 的纯函数——没有累积浮点漂移、没有过期相关系数，
撤销也只是"弹掉最后一相再重算"。代价是每相一次配对 + 一次最小二乘，
实测峰量级几十到几百，属微秒级。

比例因子口径
------------
``PhaseSelection.scale`` 是 **counts / 单位相对参考强度**：
``contribution_i = scale · (I_ref_i / I_ref_max)``，在峰相关集上按 count 空间
最小二乘拟合::

    scale = Σ(I_residual,i · r_i) / Σ(r_i²),    r_i = I_ref,i / I_ref,max

这与 :attr:`~polyxrd.models.phase.PhaseMatchResult.score` 里的归一化强度
比例是两回事：后者两边都归一到 100，只反映形状，不能用来从实测峰里减计数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase

__all__ = [
    "DEFAULT_ABS_FLOOR",
    "DEFAULT_EXPLAINED_FRAC",
    "DEFAULT_MIN_PEAK_FRAC",
    "DEFAULT_TOLERANCE",
    "PhaseSelection",
    "SequentialPhaseIdentifier",
    "phase_key",
    "residual_peak_list",
]

#: 残差强度降到**自身**实测强度的这一比例以下 ⇒ 该峰已被已确认相解释。
#: 用相对值而非绝对值：否则 200 counts 的微量相峰会被 50000 counts 的主峰
#: 顺带"吞掉"。
DEFAULT_EXPLAINED_FRAC: float = 0.05

#: 绝对下限（占全谱最强峰的比例），低于它一律算已解释，防止浮点残渣把
#: 强度 ~1e-9 的"峰"永远留在残差里。
DEFAULT_ABS_FLOOR: float = 0.002

#: 弱于全谱最强峰这一比例的峰**不参与**残差检索（既不算已解释，也不算
#: 剩余待解释）：0.5% 的线在噪声之上没有物相鉴定信息，放进去只会让下一轮
#: 去匹配噪声。这是 search-match 惯用的最小强度截断（常见默认 1%）。
DEFAULT_MIN_PEAK_FRAC: float = 0.01

#: 峰相关窗口（2θ 度）。与界面"容差"默认值一致。
DEFAULT_TOLERANCE: float = 0.30


def _ref_peak_list(phase: Phase) -> list:
    """取一相的参考峰 ``[(hkl, 2θ, I), ...]``（无方法/为空一律容错为空表）。

    与 :mod:`polyxrd.services.phase_display` 的同名工具同口径，但不跨模块
    引私有名：本模块只依赖模型，便于脱离 GUI 单独测试。
    """
    refs = (phase.get_reference_peaks()
            if hasattr(phase, "get_reference_peaks") else None)
    if not refs:
        refs = getattr(phase, "reference_peaks", None)
    return list(refs or [])


def phase_key(phase: Phase) -> tuple:
    """物相去重键（用于"这个相是否已确认过"）。

    优先用库条目 id（COD / PDF2 / 用户库都有）：同名同式的不同条目（不同
    晶型、不同出处）不该被合并，而同一个条目从不同检索引擎回来时名字可能
    被装饰过。没有 id 时退回 (name, formula, space_group)。
    """
    db_id = getattr(phase, "db_id", None)
    if db_id not in (None, ""):
        return ("id", str(db_id))
    return (
        "key",
        (getattr(phase, "name", "") or "").strip(),
        (getattr(phase, "formula", "") or "").strip(),
        (getattr(phase, "space_group", "") or "").strip(),
    )


@dataclass
class PhaseSelection:
    """一个已确认相 + 产生它的峰账本。

    Attributes:
        phase: 已确认物相。
        matched: ``(原始实测峰下标, 参考峰下标)`` 配对，下标一律指向
            :class:`SequentialPhaseIdentifier` 收到的**原始**峰表。
        explained: 到此相为止（含更早的相）已解释的原始峰下标，累积量。
        scale: counts / 单位相对参考强度（见模块 docstring）。
        covered_fraction: 到目前为止已解释的**显著峰**强度占比 (0~1)。
        n_residual_peaks: 确认此相之后仍未解释的显著峰数。
        gain: 本相**新增**的覆盖率（可用来识别"几乎没解释新峰"的假相）。
    """
    phase: Phase
    matched: list[tuple[int, int]] = field(default_factory=list)
    explained: list[int] = field(default_factory=list)
    scale: float = 0.0
    covered_fraction: float = 0.0
    n_residual_peaks: int = 0
    gain: float = 0.0


class SequentialPhaseIdentifier:
    """跟踪已确认相与剩余实测峰（纯状态机，无 GUI / 无数据库依赖）。

    Args:
        observed: 原始实测峰表（对象**不会**被修改）。
        tolerance: 峰相关窗口 (2θ 度)。
        explained_frac: "已解释"的相对阈值，见 :data:`DEFAULT_EXPLAINED_FRAC`。
        abs_floor: 残差绝对下限（占最强峰比例），见 :data:`DEFAULT_ABS_FLOOR`。
        min_peak_frac: 参与检索的最低强度（占最强峰比例），见
            :data:`DEFAULT_MIN_PEAK_FRAC`。

    Raises:
        ValueError: 参数越界（比例必须落在 [0, 1)）。
    """

    def __init__(
        self,
        observed: PeakList,
        *,
        tolerance: float = DEFAULT_TOLERANCE,
        explained_frac: float = DEFAULT_EXPLAINED_FRAC,
        abs_floor: float = DEFAULT_ABS_FLOOR,
        min_peak_frac: float = DEFAULT_MIN_PEAK_FRAC,
    ) -> None:
        if not 0.0 <= explained_frac < 1.0:
            raise ValueError(
                f"explained_frac must be in [0, 1), got {explained_frac}")
        if not 0.0 <= min_peak_frac < 1.0:
            raise ValueError(
                f"min_peak_frac must be in [0, 1), got {min_peak_frac}")
        if tolerance <= 0.0:
            raise ValueError(f"tolerance must be positive, got {tolerance}")
        self._peaks: list[Peak] = list(getattr(observed, "peaks", []) or [])
        self._source: str = getattr(observed, "source", "auto") or "auto"
        self.tolerance = float(tolerance)
        self.explained_frac = float(explained_frac)
        self.abs_floor = float(abs_floor)
        self.min_peak_frac = float(min_peak_frac)
        self._obs = np.array([float(p.intensity) for p in self._peaks],
                             dtype=float)
        self._peak_max = float(self._obs.max()) if self._obs.size else 0.0
        self._phases: list[Phase] = []
        self._selections: list[PhaseSelection] = []
        self._rebuild()

    # ── 只读状态 ─────────────────────────────────────────────
    @property
    def peaks(self) -> list[Peak]:
        """原始实测峰表（副本）。"""
        return list(self._peaks)

    @property
    def phases(self) -> list[Phase]:
        """已确认物相，按确认顺序。"""
        return list(self._phases)

    @property
    def selections(self) -> list[PhaseSelection]:
        """逐相账本，按确认顺序。"""
        return list(self._selections)

    @property
    def n_peaks(self) -> int:
        return len(self._peaks)

    def __len__(self) -> int:
        return len(self._phases)

    @property
    def residual_intensity(self) -> np.ndarray:
        """逐峰残差强度（副本）。"""
        return self._residual.copy()

    @property
    def explained_mask(self) -> np.ndarray:
        return self._explained.copy()

    @property
    def ignored_mask(self) -> np.ndarray:
        return self._ignored.copy()

    @property
    def correlated_mask(self) -> np.ndarray:
        """被任一已确认相**命中**过的峰（部分是已解释的超集）。"""
        return self._correlated.copy()

    @property
    def explained_indices(self) -> list[int]:
        return [i for i, done in enumerate(self._explained) if done]

    @property
    def ignored_indices(self) -> list[int]:
        return [i for i, skip in enumerate(self._ignored) if skip]

    @property
    def residual_indices(self) -> list[int]:
        """仍需物相解释的原始峰下标（低强度峰不算"剩下"，只是没信息量）。"""
        return [i for i in range(len(self._peaks))
                if not self._explained[i] and not self._ignored[i]]

    @property
    def residual_two_thetas(self) -> list[float]:
        """剩余峰的 2θ 列表（兼容旧版 `marked_peaks` 接口）。"""
        return [float(self._peaks[i].two_theta) for i in self.residual_indices]

    @property
    def n_residual_peaks(self) -> int:
        return int(np.count_nonzero(~self._explained & ~self._ignored))

    @property
    def n_explained(self) -> int:
        return int(np.count_nonzero(self._explained))

    @property
    def n_ignored(self) -> int:
        return int(np.count_nonzero(self._ignored))

    @property
    def covered_fraction(self) -> float:
        """已解释的显著峰强度占比 (0~1)。"""
        return float(self._covered)

    # ── 查询 ────────────────────────────────────────────────
    def contains(self, phase: Phase) -> bool:
        """该相是否已确认（按 :func:`phase_key` 判等）。"""
        key = phase_key(phase)
        return any(phase_key(p) == key for p in self._phases)

    def selection_of(self, phase: Phase) -> Optional[PhaseSelection]:
        key = phase_key(phase)
        for sel in self._selections:
            if phase_key(sel.phase) == key:
                return sel
        return None

    # ── 变更 ────────────────────────────────────────────────
    def select(self, phase: Phase) -> PhaseSelection:
        """确认 *phase* 并重算残差；重复确认是幂等的。"""
        key = phase_key(phase)
        for i, existing in enumerate(self._phases):
            if phase_key(existing) == key:
                return self._selections[i]
        self._phases.append(phase)
        self._rebuild()
        return self._selections[-1]

    def remove(self, phase: Phase) -> bool:
        """移出指定相（可在序列任意位置）并重算；返回是否命中。

        后面的相保持相对顺序，比例因子按"剩余相产生的残差"重新拟合，
        因此乱序移除是安全的。
        """
        key = phase_key(phase)
        for i, existing in enumerate(self._phases):
            if phase_key(existing) == key:
                del self._phases[i]
                self._rebuild()
                return True
        return False

    def undo(self) -> Optional[Phase]:
        """撤销最近一次确认，返回被撤销的相。"""
        if not self._phases:
            return None
        phase = self._phases.pop()
        self._rebuild()
        return phase

    def clear(self) -> None:
        """忘掉全部已确认相（残差回到原始峰）。"""
        self._phases.clear()
        self._rebuild()

    def reset(self, observed: Optional[PeakList] = None) -> None:
        """重新开始，可同时换一份峰表。"""
        if observed is not None:
            self._peaks = list(getattr(observed, "peaks", []) or [])
            self._source = getattr(observed, "source", "auto") or "auto"
            self._obs = np.array([float(p.intensity) for p in self._peaks],
                                 dtype=float)
            self._peak_max = float(self._obs.max()) if self._obs.size else 0.0
        self._phases.clear()
        self._rebuild()

    # ── 重算 ────────────────────────────────────────────────
    def _rebuild(self) -> None:
        """从原始峰表重算逐相配对、比例因子、残差与各掩码。"""
        n = len(self._peaks)
        self._residual = self._obs.copy()
        self._ignored = self._ignored_mask()
        self._explained = np.zeros(n, dtype=bool)
        self._correlated = np.zeros(n, dtype=bool)
        self._selections = []
        self._covered = 0.0
        if n == 0:
            return
        threshold = self._explained_threshold()
        significant = ~self._ignored
        total = float(self._obs[significant].sum())
        covered_prev = 0.0
        for phase in self._phases:
            pairs, scale = self._layer_for(phase)
            refs = _ref_peak_list(phase)
            ref_max = self._ref_max(refs)
            for exp_idx, ref_idx in pairs:
                rel = self._ref_rel(refs, ref_idx, ref_max)
                self._residual[exp_idx] = max(
                    0.0, float(self._residual[exp_idx]) - scale * rel)
                self._correlated[exp_idx] = True
            # "已解释"按**累积**残差判定：多相叠加起来够不够解释这一峰，
            # 才是能否把它从残差集合里拿掉的依据。
            self._explained = (self._residual <= threshold) & significant
            covered = (1.0 - float(self._residual[significant].sum()) / total
                       if total > 0 else 0.0)
            self._covered = min(max(covered, 0.0), 1.0)
            self._selections.append(PhaseSelection(
                phase=phase,
                matched=list(pairs),
                explained=self.explained_indices,
                scale=scale,
                covered_fraction=self._covered,
                n_residual_peaks=self.n_residual_peaks,
                gain=self._covered - covered_prev,
            ))
            covered_prev = self._covered

    def _ignored_mask(self) -> np.ndarray:
        """低于检索下限的峰（强度绝对值，与谱图最强峰比较）。"""
        n = len(self._peaks)
        mask = np.zeros(n, dtype=bool)
        if n == 0 or self._peak_max <= 0.0 or self.min_peak_frac <= 0.0:
            return mask
        return self._obs < self.min_peak_frac * self._peak_max

    def _explained_threshold(self) -> np.ndarray:
        """逐峰"已解释"阈值：相对自身强度的比例，带绝对下限。"""
        if not len(self._peaks):
            return np.zeros(0, dtype=float)
        floor = self.abs_floor * self._peak_max if self._peak_max > 0 else 0.0
        return np.maximum(self.explained_frac * self._obs, floor)

    @staticmethod
    def _ref_max(refs: list) -> float:
        """参考峰归一化基准（最强参考线强度）。"""
        vals = [abs(float(r[2])) for r in refs
                if len(r) >= 3 and r[2] is not None]
        top = max(vals) if vals else 0.0
        return top

    @staticmethod
    def _ref_rel(refs: list, ref_idx: int, ref_max: float) -> float:
        """参考峰的相对强度 I_ref / I_ref_max（越界/无基准 → 0）。"""
        if ref_max <= 0.0 or not (0 <= ref_idx < len(refs)):
            return 0.0
        row = refs[ref_idx]
        if len(row) < 3 or row[2] is None:
            return 0.0
        return abs(float(row[2])) / ref_max

    def _layer_for(self, phase: Phase) -> tuple[list[tuple[int, int]], float]:
        """把 *phase* 与当前残差峰做峰位配对并拟合比例因子。

        只有"尚未解释且不算噪声"的峰参与配对——已解释的峰属于更早的相，
        噪声峰没有鉴定信息。返回 ``(原始下标配对, scale)``。
        """
        active = self.residual_indices
        refs = _ref_peak_list(phase)
        if not active or not refs:
            return [], 0.0
        pairs = self._pair(active, refs)
        return pairs, self._fit_scale(refs, pairs)

    def _pair(self, active: list[int],
              refs: list) -> list[tuple[int, int]]:
        """峰位一对一贪心配对（|Δ2θ| 最小者先占位）。

        一对一而非"一参考峰对多实验峰"：后者会让同一参考线的相对强度在
        scale 拟合里被重复计入，把微量相的比例因子抬到不合理的高度。
        Kα1/Kα2 分裂或峰形分裂属于少数情形，此时更近的那半条会先占位，
        另一条若超出窗口就留给后续轮回——比把比例因子算错安全。
        """
        cand: list[tuple[float, int, int]] = []
        for exp_idx in active:
            two_theta = float(self._peaks[exp_idx].two_theta)
            for ref_idx, row in enumerate(refs):
                if len(row) < 3 or row[1] is None:
                    continue
                delta = abs(two_theta - float(row[1]))
                if delta <= self.tolerance:
                    cand.append((delta, exp_idx, ref_idx))
        cand.sort()
        used_exp: set[int] = set()
        used_ref: set[int] = set()
        pairs: list[tuple[int, int]] = []
        for _delta, exp_idx, ref_idx in cand:
            if exp_idx in used_exp or ref_idx in used_ref:
                continue
            used_exp.add(exp_idx)
            used_ref.add(ref_idx)
            pairs.append((exp_idx, ref_idx))
        return pairs

    def _fit_scale(self, refs: list, pairs: list[tuple[int, int]]) -> float:
        """配对峰上的 count 空间最小二乘比例因子。"""
        if not pairs:
            return 0.0
        ref_max = self._ref_max(refs)
        if ref_max <= 0.0:
            return 0.0
        num = 0.0
        den = 0.0
        for exp_idx, ref_idx in pairs:
            rel = self._ref_rel(refs, ref_idx, ref_max)
            if rel <= 0.0:
                continue
            num += float(self._residual[exp_idx]) * rel
            den += rel * rel
        if den <= 0.0:
            return 0.0
        return num / den


def residual_peak_list(identifier: SequentialPhaseIdentifier) -> PeakList:
    """把残差峰导出成 :class:`PeakList`（强度 = 扣减后的剩余计数）。

    峰位 / FWHM / d / hkl 原样带过去；强度换成残差，供检索引擎按"剩余
    强度"重新归一与打分。已解释峰与低于检索下限的峰不导出——它们不是
    "还没找到相"，而是"已经有归属"或"没有信息量"。
    """
    peaks: list[Peak] = []
    residual = identifier.residual_intensity
    for i in identifier.residual_indices:
        src = identifier.peaks[i]
        peaks.append(Peak(
            two_theta=float(src.two_theta),
            intensity=float(residual[i]),
            fwhm=float(getattr(src, "fwhm", 0.0) or 0.0),
            hkl=getattr(src, "hkl", None),
            d_spacing=float(getattr(src, "d_spacing", 0.0) or 0.0),
            phase="",
        ))
    return PeakList(peaks=peaks, source="residual")
