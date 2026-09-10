"""
物相识别服务
============
基于匹配因子 (FoM, 0.9.11 加权互斥版) 的物相识别。
支持离线XRD参考数据库匹配和COD在线搜索。
支持四态元素过滤: 必有/含有/可能/没有 (未勾选元素默认并入「没有」)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.fom import confidence_from_score
from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.foam import compute_fom
from polyxrd.utils.formula_parser import (
    parse_formula, elements_match_filter, normalize_element_filter,
)
from polyxrd.utils.resources import get_resource_path

# 纯金属相惩罚: 单元素金属参考峰少易误匹配 (非金属/类金属除外)
_NONMETAL: frozenset[str] = frozenset({
    "H", "He", "N", "O", "F", "Ne", "Cl", "Ar", "Br", "Kr", "I", "Xe", "Rn",
    "S", "P", "C", "Si", "Se", "Te", "As", "Ge", "B",
})
_PURE_METAL_PENALTY = 1.5


def _is_pure_metal(phase: Phase) -> bool:
    """单元素金属 (H/N/O/S/C/Si/卤素/稀有气体等非金属除外)"""
    els = phase.elements or set()
    return len(els) == 1 and not (els & _NONMETAL)


class PhaseIdentifier:
    """物相识别服务

    基于实验峰与参考数据库峰的匹配进行物相识别。
    使用FOM (Figure of Merit) 算法评估匹配质量。

    FOM = Σ|2θ_obs - 2θ_calc| / Σ(2θ_calc) × N_matched × 100

    FOM越低匹配越好:
    - FOM < 0.1: 极好匹配
    - FOM < 0.3: 良好匹配
    - FOM < 0.5: 一般匹配
    - FOM > 0.5: 可能不匹配
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._phase_database: list[Phase] = []
        self._reference_data: list[dict] = []
        self._load_reference_database()

    def _load_reference_database(self) -> None:
        db_path = get_resource_path("database/xrd_reference_database.json")
        if db_path and Path(db_path).exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._reference_data = data.get("phases", [])
                self._phase_database = self._build_phases_from_db(self._reference_data)
                print(f"[PhaseIdentifier] 已加载 {len(self._phase_database)} 种参考物相")
            except Exception as e:
                print(f"[PhaseIdentifier] 加载参考数据库失败: {e}")
                self._load_default_phases()
        else:
            print("[PhaseIdentifier] 参考数据库不存在，使用默认物相")
            self._load_default_phases()

    def _build_phases_from_db(self, ref_data: list[dict]) -> list[Phase]:
        phases = []
        for entry in ref_data:
            peaks = []
            for p in entry.get("peaks", []):
                hkl = tuple(p["hkl"])
                two_theta = p["two_theta"]
                intensity = p.get("intensity", 50)
                peaks.append((hkl, two_theta, intensity))

            lattice_data = entry.get("lattice", {})
            from polyxrd.models.phase import LatticeParams
            lattice = LatticeParams(
                a=lattice_data.get("a", 1.0),
                b=lattice_data.get("b", 1.0),
                c=lattice_data.get("c", 1.0),
                alpha=lattice_data.get("alpha", 90.0),
                beta=lattice_data.get("beta", 90.0),
                gamma=lattice_data.get("gamma", 90.0),
            )

            formula = entry.get("formula", "")
            elements = parse_formula(formula) if formula else set()

            phase = Phase(
                name=entry.get("name", entry.get("key", "")),
                formula=formula,
                space_group=entry.get("space_group", ""),
                lattice=lattice,
                reference_peaks=peaks,
                elements=elements,
            )
            phases.append(phase)
        return phases

    def _load_default_phases(self) -> None:
        wavelength = self._config.default_wavelength
        phases = []

        si = Phase(
            name="Silicon", formula="Si", space_group="Fd-3m", lattice=None,
            reference_peaks=[
                ((1, 1, 1), 28.44, 100), ((2, 2, 0), 47.30, 60),
                ((3, 1, 1), 56.11, 35), ((4, 0, 0), 69.13, 15),
                ((3, 3, 1), 76.36, 12), ((4, 2, 2), 88.04, 10),
            ],
            elements={"Si"},
        )
        phases.append(si)

        sio2 = Phase(
            name="α-Quartz", formula="SiO2", space_group="P3121", lattice=None,
            reference_peaks=[
                ((0, 1, 0), 20.85, 88), ((1, 0, 0), 26.64, 100),
                ((0, 1, 1), 36.50, 55), ((1, 0, 1), 39.33, 12),
                ((1, 1, 0), 50.14, 14), ((1, 1, 2), 59.95, 14),
            ],
            elements={"Si", "O"},
        )
        phases.append(sio2)

        nacl = Phase(
            name="Halite", formula="NaCl", space_group="Fm-3m", lattice=None,
            reference_peaks=[
                ((1, 1, 1), 27.45, 100), ((2, 0, 0), 31.97, 55),
                ((2, 2, 0), 45.68, 65), ((3, 1, 1), 54.93, 15),
            ],
            elements={"Na", "Cl"},
        )
        phases.append(nacl)

        al2o3 = Phase(
            name="Corundum", formula="Al2O3", space_group="R-3c", lattice=None,
            reference_peaks=[
                ((0, 1, 2), 25.58, 100), ((1, 0, 4), 35.16, 85),
                ((1, 1, 3), 43.36, 75), ((0, 2, 4), 52.56, 90),
            ],
            elements={"Al", "O"},
        )
        phases.append(al2o3)

        self._phase_database = phases

    def identify(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        elements: Optional[list[str]] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
    ) -> list[PhaseMatchResult]:
        """执行物相识别

        Args:
            data: XRD数据
            peaks: 峰列表 (可选，自动检测如未提供)
            elements: 已知元素过滤 (可选，逗号分隔的元素列表)
            top_n: 返回候选数量
            tolerance: 2θ匹配容差 (度)

        Returns:
            匹配结果列表，按FOM升序排列 (FOM越低越好)
        """
        element_filter = None
        if elements:
            element_filter = {
                "must": elements,
                "maybe": [],
                "exclude": [],
            }
        return self.identify_with_element_filter(
            data=data, peaks=peaks,
            element_filter=element_filter,
            top_n=top_n, tolerance=tolerance,
        )

    # ── 组合选择辅助: 结构去重 / 实测峰掩码 / 分支定界 ─────────

    @staticmethod
    def _phases_structurally_same(pa, pb, tol: float = 0.15) -> bool:
        """判断两个物相是否为"同一结构的重复条目"。

        旧去重逻辑按 (化学式, 元素集合) 一刀切，会把化学式相同但结构
        不同的真正多型 (石英 vs 方石英, 均 SiO2; 锐钛矿 vs 金红石,
        均 TiO2) 误删。这里改为参考峰位的**双向覆盖**判定:
          A→B 覆盖 ≥70% 且 B→A 覆盖 ≥70% 才视为同一结构。

        只做单向会误判: 峰位稀疏的相 (如纯金属 ~6 峰) 每条峰几乎总能
        在峰位密集的相 (如 Calcite ~98 峰) 中找到 ±tol 配对 → 单向 100%
        "命中" 实为包含而非同构。双向后嵌套情形的一方覆盖仅 ~6% 被拒。
        """
        a = [tt for _, tt, _ in pa.get_reference_peaks()]
        b = [tt for _, tt, _ in pb.get_reference_peaks()]
        if not a or not b:
            return False
        aa = np.sort(np.asarray(a, dtype=float))
        bb = np.sort(np.asarray(b, dtype=float))

        def _cov(x, y) -> float:
            # x 中多少比例的峰在 y 中存在 ±tol 对应
            hit = 0
            for v in x:
                i = int(np.searchsorted(y, v))
                if i < len(y) and abs(y[i] - v) <= tol:
                    hit += 1
                elif i > 0 and abs(y[i - 1] - v) <= tol:
                    hit += 1
            return hit / len(x)

        return _cov(aa, bb) >= 0.7 and _cov(bb, aa) >= 0.7

    @staticmethod
    def _as_observed_peaks(peaks):
        """把 PeakList / list[Peak] 归一化为 [(two_theta, intensity), ...]"""
        items = getattr(peaks, "peaks", peaks) or []
        out = []
        for p in items:
            if p is None:
                continue
            tt = getattr(p, "two_theta", None)
            if tt is None:
                continue
            out.append((float(tt), float(getattr(p, "intensity", 1.0) or 1.0)))
        return out

    def _dedupe_results(self, results, peaks=None, tolerance: float = 0.2) -> list:
        """结构感知 + 数据感知的同公式条目去重。

        同 (formula, elements) 的多条候选, 有两种成因:
          a) 同一结构的重复条目 (如 Fluorite/CaF2 两版本、Brucite 重复)
             → 只留 FOM 最优 (最先出现) 一条
          b) 结构不同的真正多型 (α-Quartz vs Cristobalite vs Tridymite 均
             SiO2; Anatase vs Rutile 均 TiO2; Calcite vs Aragonite 均 CaCO3)
             → 不能一律按公式合并, 否则 5-x 试样(石英+方石英并存)的预期
               物相永远进不了候选池

        数据感知规则 (peaks 提供时): 同一公式组内, 后续多型只有在"解释了
        组内已保留成员解释不到的实测峰"时才保留; 否则视为无独立数据证据的
        噪声 (如纯方解石试样里不会留下文石)。peaks 缺失时保守全保留多型。
        """
        obs_tt = None
        if peaks is not None:
            obs_tt = [o[0] for o in self._as_observed_peaks(peaks)]
            if not obs_tt:
                obs_tt = None

        kept: list = []
        for r in results:
            formula = r.phase.formula or ""
            group = [s for s in kept
                     if s.phase.formula == formula
                     and s.phase.elements == r.phase.elements]
            if not group:
                kept.append(r)
                continue
            # 同一结构重复条目 → 剔除
            if any(self._phases_structurally_same(s.phase, r.phase)
                   for s in group):
                continue
            # 无实测峰信息 → 保守保留多型
            if obs_tt is None:
                kept.append(r)
                continue
            # 数据感知: 必须解释到已保留成员解释不到的实测峰
            r_msk = self._phase_hit_mask(r.phase, obs_tt, tolerance)
            if r_msk == 0:
                continue
            group_msk = 0
            for s in group:
                group_msk |= self._phase_hit_mask(s.phase, obs_tt, tolerance)
            if r_msk & ~group_msk:
                kept.append(r)
        return kept

    @staticmethod
    def _phase_hit_mask(phase, obs_tt, tolerance: float) -> int:
        """物相参考峰命中的实测峰位掩码 (Python int 位集)。

        每条参考峰只要在容差内命中任意实测峰即置位该实测峰对应的位；
        同一实测峰被多条参考峰命中只算一次。
        """
        msk = 0
        for _, tt, _ in phase.get_reference_peaks():
            for j, o in enumerate(obs_tt):
                if abs(tt - o) <= tolerance:
                    msk |= (1 << j)
        return msk

    @staticmethod
    def _branch_and_bound_select(masks, metal_flags, n_obs,
                                 size_targets=None, scores=None) -> list:
        """分支定界: 选择使"联合覆盖实测峰数"最大的物相子集。

        目标函数 (对给定规模 k):
          max  联合覆盖峰数 = |∪ masks_i|          (每峰等权)
          平手 取 Σscore 最小 (score 为 FOM, 越低越好), 再取输入序在前者

        约束:
          - 子集内纯金属数 ≤ max(1, round(0.2·n))  (硬约束, 与旧版防御一致)
          - size_targets=None 时自动定规模: 取"联合覆盖达到全局最大"的
            最小 k (简约原则, 解释不了任何额外峰的冗余相自然被剔除)

        n ≤ 14 时精确枚举 (可视为最坏 C(14,7)=3432 的组合, 微秒级);
        n > 14 时用逐点边际增益最大的贪心构造 + 覆盖平手退避。
        """
        import itertools
        n = len(masks)
        if n == 0:
            return []
        max_pm = min(max(1, round(0.2 * n)), n)

        if size_targets:
            sizes = sorted({s for s in size_targets if 1 <= s <= n}) or [n]
        else:
            sizes = list(range(1, n + 1))

        best_cov_k = {k: -1 for k in sizes}
        best_combo_k = {k: None for k in sizes}

        def _consider(k, combo):
            cov = 0
            for i in combo:
                cov |= masks[i]
            cov = bin(cov).count("1")
            if cov > best_cov_k[k] or (
                cov == best_cov_k[k] and best_combo_k[k] is not None and scores
                and sum(scores[i] for i in combo)
                < sum(scores[i] for i in best_combo_k[k])
            ):
                best_cov_k[k] = cov
                best_combo_k[k] = tuple(combo)

        def _metal_ok(combo):
            if sum(1 for i in combo if metal_flags[i]) > max_pm:
                return False
            return True

        if n <= 14:
            for k in sizes:
                for combo in itertools.combinations(range(n), k):
                    if not _metal_ok(combo):
                        continue
                    _consider(k, combo)
        else:
            # 贪心: 每次取边际增益最大的候选 (纯金属约束内)
            for k in sizes:
                combo = []
                covered = 0
                for _step in range(k):
                    best_i, best_gain = None, -1
                    for i in range(n):
                        if i in combo:
                            continue
                        if sum(1 for j in combo if metal_flags[j]) \
                                + (1 if metal_flags[i] else 0) > max_pm:
                            continue
                        gain = bin(masks[i] & ~covered).count("1")
                        if gain > best_gain:
                            best_gain, best_i = gain, i
                    if best_i is None:
                        break
                    combo.append(best_i)
                    covered |= masks[best_i]
                if combo:
                    _consider(k, combo)

        if size_targets:
            k0 = sizes[0]
            if best_combo_k[k0] is not None:
                return list(best_combo_k[k0])
            # 目标规模不可行 (纯金属约束过紧) → 放松约束再选
            relaxed = PhaseIdentifier._branch_and_bound_select(
                masks, [False] * n, n_obs, size_targets, scores
            )
            return relaxed

        # 自动规模: 最小 k 达到全局最大联合覆盖
        maxcov = max(best_cov_k.values()) if best_cov_k else -1
        if maxcov <= 0:
            return []
        for k in sizes:
            if best_cov_k[k] == maxcov and best_combo_k[k] is not None:
                return list(best_combo_k[k])
        return []

    def _legacy_refinement_combination(self, kept: list,
                                       expected_count: Optional[int]) -> list:
        """旧版启发式 (peaks 未提供时的回退路径)。

        语义与 v0.9.x build_refinement_combination 一致:
        coverage 过滤已完成; 这里做 expected_count 截断 + 纯金属比例防御
        + 低覆盖率纯金属剔除。
        """
        sel = list(kept)
        if expected_count and expected_count > 0:
            sel = sel[:expected_count]
        pm_idx = [i for i, m in enumerate(sel) if _is_pure_metal(m.phase)]
        cap = max(1, round(0.2 * len(sel)))
        if len(pm_idx) > cap:
            drop = set(pm_idx[cap:])
            sel = [m for i, m in enumerate(sel) if i not in drop]
        out = []
        for m in sel:
            if _is_pure_metal(m.phase) and m.coverage < 0.55:
                continue
            out.append(m.phase)
        return out

    def build_refinement_combination(
        self,
        matches: list,
        expected_count: Optional[int] = None,
        min_coverage: float = 0.5,
        peaks=None,
        tolerance: float = 0.2,
    ) -> list:
        """从物相识别结果中生成精修组合 (分支定界全局搜索)

        旧实现是"覆盖率过滤 + expected_count 截断 + 纯金属防御"的贪心
        流水线, 只能沿 FOM 排序从前往后截断, 无法处理多相间的局部重复/
        干扰 (Task #7):
          - 两个候选解释同一批实测峰时, 截断可能丢真相留冗余;
          - 5+ 相试样上"FOM 排序"≠"联合解释能力排序"。

        v0.10 起基于实测峰联合覆盖做分支定界 (B&B):
          1. 预处理 (与旧版一致): 结构去重 / coverage 过滤(全低回退) /
             低覆盖率纯金属剔除
          2. 未提供 peaks → 无法评估联合覆盖, 回退旧启发式
          3. 提供 peaks → 每个候选映射为"命中实测峰的掩码", 以子集联合
             覆盖最多实测峰为目标做全局搜索
             - expected_count 已知 → 恰好该规模、联合覆盖最优的子集
             - expected_count 未知 → 取覆盖不再增长的最小规模 (简约)
             - 纯金属数量上限作为硬约束参与搜索 (而非事后截断)

        Args:
            matches: identify_with_element_filter 的输出 (按 score 升序)
            expected_count: 预期物相数量 (若已知)
            min_coverage: 参考峰匹配覆盖率下限, 低于此视为噪声
                (注意: 与 v0.9.x 口径一致, 与 coverage(%) 百分比比较)
            peaks: 实测峰列表 (PeakList / list[Peak]); 提供后启用 B&B
            tolerance: 参考峰与实测峰匹配容差 (度); 默认 0.2 与主流
                identify_with_element_filter(tolerance=0.2) 调用一致

        Returns:
            list[Phase] - 可直接用于 Rietveld 精修的物相列表 (原 FOM 顺序)
        """
        # 1. 结构/数据感知去重 + coverage 过滤 (全部低于阈值则回退全量)
        filtered = self._dedupe_results(matches, peaks, tolerance)
        kept = [m for m in filtered if m.coverage >= min_coverage]
        if not kept:
            kept = filtered
        if not kept:
            return []

        # 2. 无实测峰 → 无法评估联合覆盖, 回退旧启发式
        if peaks is None:
            return self._legacy_refinement_combination(kept, expected_count)

        obs = self._as_observed_peaks(peaks)
        if not obs:
            return self._legacy_refinement_combination(kept, expected_count)
        obs_tt = [o[0] for o in obs]

        # 3. 候选 → 命中掩码; 低覆盖率纯金属与"解释不了任何实测峰"者剔除
        pool: list = []
        masks: list[int] = []
        for m in kept:
            if _is_pure_metal(m.phase) and m.coverage < 0.55:
                continue
            msk = self._phase_hit_mask(m.phase, obs_tt, tolerance)
            if msk == 0:
                continue
            pool.append(m)
            masks.append(msk)
        if not pool:
            return []

        # 4. B&B 全局选择
        metal_flags = [_is_pure_metal(m.phase) for m in pool]
        if expected_count and expected_count > 0:
            size_targets = [min(expected_count, len(pool))]
        else:
            size_targets = None
        scores = [m.score for m in pool]

        # 规模退化: 若 expected_count > 池内可解释候选数, 池全选
        if size_targets and size_targets[0] >= len(pool):
            return [m.phase for m in pool]

        selected = self._branch_and_bound_select(
            masks, metal_flags, len(obs_tt), size_targets, scores,
        )
        chosen = [pool[i].phase for i in selected]
        if not chosen:
            return self._legacy_refinement_combination(kept, expected_count)
        return chosen

    def identify_with_element_filter(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
    ) -> list[PhaseMatchResult]:
        """执行物相识别（支持三态元素过滤）

        Args:
            data: XRD数据
            peaks: 峰列表 (可选，自动检测如未提供)
            element_filter: 元素过滤条件 {"must": [...], "maybe": [...], "exclude": [...]}
            top_n: 返回候选数量
            tolerance: 2θ匹配容差 (度)

        Returns:
            匹配结果列表，按FOM升序排列 (FOM越低越好)
        """
        if peaks is None:
            from polyxrd.services.peak_finder import PeakFinder
            pf = PeakFinder()
            peaks = pf.find_peaks(data)

        ef = normalize_element_filter(element_filter) if element_filter else None

        results = []
        for phase in self._phase_database:
            if ef and not elements_match_filter(
                phase.elements,
                has=ef["has"], maybe=ef["maybe"], exclude=ef["exclude"],
                must_have=ef["must_have"],
            ):
                continue

            match_result = self._match_phase_fom(
                phase, peaks, tolerance
            )
            results.append(match_result)

        results.sort(key=lambda r: r.score)

        # ── 组合重排: 纯金属比例限制在 20% 以内, 避免过多纯金属挤占前 top_n ──
        if len(results) > 0:
            reordered = []
            non_metal_stack = [r for r in results if not _is_pure_metal(r.phase)]
            metal_stack = [r for r in results if _is_pure_metal(r.phase)]

            # 贪心: 保持相对顺序, 每 5 个中纯金属不超过 1 个 (20%)
            max_metal = max(1, int(0.2 * min(top_n, len(results))) + 0.5)
            metal_count = 0
            nm_i = 0
            m_i = 0
            total = min(len(results), top_n)
            # 先放非金属直到不够，再考虑金属，但保持原 FOM 顺序
            # 更简单: 结果中前 top_n, 若纯金属 >20% 则将超出的纯金属和下一位非金属交换
            for slot in range(min(len(results), top_n + 10)):
                if len(reordered) >= total:
                    break
                # 首选: FOM 最低的可用项
                while nm_i < len(non_metal_stack) and non_metal_stack[nm_i] in reordered:
                    nm_i += 1
                while m_i < len(metal_stack) and metal_stack[m_i] in reordered:
                    m_i += 1

                best = None
                if nm_i < len(non_metal_stack) and m_i < len(metal_stack):
                    if non_metal_stack[nm_i].score <= metal_stack[m_i].score:
                        best = non_metal_stack[nm_i]
                        nm_i += 1
                    elif metal_count < max_metal:
                        best = metal_stack[m_i]
                        m_i += 1
                        metal_count += 1
                    else:
                        # 纯金属已达上限，跳过
                        best = non_metal_stack[nm_i]
                        nm_i += 1
                elif nm_i < len(non_metal_stack):
                    best = non_metal_stack[nm_i]
                    nm_i += 1
                elif m_i < len(metal_stack) and metal_count < max_metal:
                    best = metal_stack[m_i]
                    m_i += 1
                    metal_count += 1
                else:
                    # 纯金属达上限但无更多非金属，依然放（结果少于 top_n 更糟）
                    if m_i < len(metal_stack):
                        best = metal_stack[m_i]
                        m_i += 1
                if best is not None:
                    reordered.append(best)

            # 若重排后结果数量充足则使用，否则回退原排序
            if len(reordered) >= total:
                results = reordered
            # 否则保留 results (原排序, 仅 top_n 裁剪)

        # ── 去重: 结构感知 + 数据感知 (Task #7) ────────────────
        # 内置库中同一化学式可能有多条目:
        #   a) 真重复 (同一结构, 如 CaF2 两版本) → 合并, 只留 FOM 最优
        #   b) 真正多型 (石英 vs 方石英; 锐钛矿 vs 金红石; 方解石 vs 文石)
        #      → 旧实现按 (formula, elements) 一刀切会误删, 使 5-x 等含
        #        石英+方石英试样的预期物相无法进入候选。现改为: 多型仅在
        #        解释了实测峰中本组已保留成员解释不到的峰时才保留。
        results = self._dedupe_results(results, peaks, tolerance)

        return results[:top_n]

    def _match_phase_fom(
        self,
        phase: Phase,
        peaks: PeakList,
        tolerance: float,
    ) -> PhaseMatchResult:
        """基于匹配因子 (FoM) 匹配单个物相。

        0.9.11 起统一走 :func:`polyxrd.services.foam.compute_fom`, 与 COD 路径
        同一口径, 三点改进:
          - 一一对应互斥匹配 (密集物相不再抢峰)
          - 强峰加权 + Σw 归一 (消除高角度/多峰天然占优)
          - 未解释实验峰特异性惩罚 + 匹配对强度余弦一致性
        纯金属相额外 ×1.5 惩罚 (单元素金属参考峰少易误匹配)。

        Args:
            phase: 候选物相
            peaks: 实验峰列表
            tolerance: 容差

        Returns:
            PhaseMatchResult (score 越低越好)
        """
        reference_peaks = phase.get_reference_peaks()
        total_ref_peaks = len(reference_peaks)
        if total_ref_peaks == 0:
            return PhaseMatchResult(
                phase=phase, score=999.0, matched_peaks=0,
                total_peaks=0, confidence="无参考数据", method="fom"
            )

        fom = compute_fom(
            [p.two_theta for p in peaks],
            [p.intensity for p in peaks],
            reference_peaks,
            tol=tolerance,
        )
        score = float(fom.score)
        if _is_pure_metal(phase):
            score *= _PURE_METAL_PENALTY
        score = max(score, 0.01)

        return PhaseMatchResult(
            phase=phase,
            score=round(score, 4),
            matched_peaks=fom.matched,
            total_peaks=total_ref_peaks,
            confidence=confidence_from_score(score),
            method="fom",
        )

    def add_phase(self, phase: Phase) -> None:
        self._phase_database.append(phase)

    def load_custom_database(self, path: str) -> None:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        for phase_data in data.get("phases", []):
            phase = Phase.from_dict(phase_data)
            self._phase_database.append(phase)

    def get_database_info(self) -> dict:
        info = {
            "total_phases": len(self._phase_database),
            "has_reference_db": len(self._reference_data) > 0,
            "reference_count": len(self._reference_data),
            "cod_local_enabled": getattr(self, "_cod_enabled", False),
            "cod_local_ready": getattr(self, "_cod_ready", False),
        }
        db = getattr(self, "_cod_db", None)
        if db is not None:
            info["cod_stats"] = db.stats()
        return info

    # ── 本地 COD 数据库集成 ──────────────────────────────────

    def enable_cod_local(self, cod_db=None) -> None:
        """启用本地 COD 数据库 (索引就绪后调用)。

        - 若索引就绪: identify() 额外对 COD 前 N 条候选做 FOM 匹配，合并结果。
        - identify 参数 use_cod_local=True 时生效 (默认仅内置 + 外部)。

        Args:
            cod_db: 已实例化的 CODLocalDatabase (None 则新建)
        """
        try:
            from polyxrd.services.cod_local import CODLocalDatabase
            self._cod_db = cod_db if cod_db is not None else CODLocalDatabase()
            self._cod_enabled = True
            self._cod_ready = bool(self._cod_db.is_ready())
        except Exception:
            self._cod_db = None
            self._cod_enabled = False
            self._cod_ready = False

    def _search_cod_for_phases(self, peaks, elements,
                               wavelength: float,
                               two_theta_range,
                               top_n_candidates: int = 50,
                               tolerance: float = 0.15):
        """从 COD 索引中筛选候选物相，动态生成 reference_peaks 并计算 FOM。

        策略:
          - 如 elements 有条件，先用元素过滤得到 COD 候选 (最多 top_n_candidates)
          - 对每个候选做 FOM (计算快速，pymatgen 峰生成慢则跳过)
          - 返回 top_n FOM 最好的 PhaseMatchResult
        """
        db = getattr(self, "_cod_db", None)
        if db is None or not db.is_ready():
            return []

        # 1) 按元素和 2θ 初筛 (减少调用 pymatgen 的次数)
        cod_entries = db.search(
            elements=elements,
            limit=max(top_n_candidates, 100),
            parse_ok_only=True,
        )
        if not cod_entries:
            return []

        # 2) 对前 N 条尝试生成 Phase+reference_peaks 并做 FOM
        results = []
        import time as _t
        t0 = _t.time()
        processed = 0
        budget_seconds = 30.0  # 防止长时间阻塞
        for e in cod_entries:
            if processed >= top_n_candidates or (_t.time() - t0) > budget_seconds:
                break
            # 跳过完全没有原子位点或晶胞体积异常的
            if not e.a or not e.b or not e.c or not e.formula:
                continue
            phase = db.get_phase(
                e.cod_id,
                wavelength=wavelength,
                two_theta_range=two_theta_range,
                use_pymatgen_peaks=True,
            )
            if phase is None or not phase.reference_peaks:
                continue
            processed += 1
            match = self._match_phase_fom(phase, peaks, tolerance)
            results.append(match)

        results.sort(key=lambda r: r.score)
        return results[:top_n_candidates]

    def identify_with_cod_local(
        self,
        data: XRDData,
        peaks=None,
        elements: Optional[list[str]] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        cod_candidates: int = 30,
        merge_with_builtin: bool = True,
    ) -> list[PhaseMatchResult]:
        """物相识别: 内置 118 物相 + 本地 COD 扩展。

        Args:
            data: XRD 数据
            peaks: 可选峰列表 (自动检测)
            elements: 已知元素 (大幅降低 COD 候选范围，推荐)
            top_n: 返回候选数
            tolerance: 2θ 容差
            cod_candidates: 最多评估 COD 物相数 (pymatgen 峰计算较慢)
            merge_with_builtin: True → 与内置库结果合并排序; False → 仅 COD
        """
        if peaks is None:
            from polyxrd.services.peak_finder import PeakFinder
            peaks = PeakFinder().find_peaks(data)

        wavelength = self._config.default_wavelength
        t_min, t_max = self._config.default_two_theta_range
        t_range = (max(t_min, 5.0), min(t_max, 90.0))

        combined: list[PhaseMatchResult] = []
        if merge_with_builtin:
            builtin = self.identify(data, peaks=peaks, elements=elements,
                                    top_n=max(top_n, 10), tolerance=tolerance)
            combined.extend(builtin)

        # COD 部分
        if getattr(self, "_cod_ready", False) or (
            getattr(self, "_cod_db", None) and self._cod_db.is_ready()
        ):
            cod_results = self._search_cod_for_phases(
                peaks=peaks,
                elements=elements,
                wavelength=wavelength,
                two_theta_range=t_range,
                top_n_candidates=cod_candidates,
                tolerance=tolerance,
            )
            combined.extend(cod_results)

        combined.sort(key=lambda r: r.score)
        return combined[:top_n]

    def identify_with_cod_inorganics(
        self,
        data: XRDData,
        peaks: Optional[PeakList] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        prefilter_limit: int = 100,
    ) -> list[PhaseMatchResult]:
        """物相识别: COD 无机物库 (71,199 物相, 预计算 d-I 峰)。

        流程:
        1. 实验峰 2θ → d 值 (Bragg: d = λ / (2 sinθ))
        2. CIFDatabase.search_cod_by_d_peaks Hanawalt 法预筛候选
           (主峰原则 + 强度加权召回, top prefilter_limit 条)
        3. 候选转 Phase (d→2θ 参考峰), 统一走 _match_phase_fom 评分,
           与内置库同一 FOM 口径 (含纯金属惩罚)

        Args:
            data: XRD 数据
            peaks: 可选峰列表 (自动检测)
            element_filter: 三态元素过滤 (预筛后应用)
            top_n: 返回候选数
            tolerance: 2θ 容差 (FOM 匹配用)
            prefilter_limit: d-I 预筛保留的候选数
        """
        if peaks is None:
            from polyxrd.services.peak_finder import PeakFinder
            peaks = PeakFinder().find_peaks(data)

        try:
            from polyxrd.services.cif_database import CIFDatabase
        except Exception:
            return []

        cdb = CIFDatabase(enable_cod_local=False)
        if not cdb.cod_db_available():
            return []

        wavelength = self._config.default_wavelength

        # 1. 实验峰 2θ → d 值
        d_list: list[float] = []
        i_list: list[float] = []
        for p in peaks.peaks:
            sin_theta = np.sin(np.radians(p.two_theta / 2.0))
            if sin_theta <= 1e-6:
                continue
            d_list.append(wavelength / (2.0 * sin_theta))
            i_list.append(float(p.intensity))
        if not d_list:
            return []

        # 2. Hanawalt d-I 预筛 (元素约束下推到扫描层)
        ef = normalize_element_filter(element_filter) if element_filter else None
        # 允许池 = 必有 ∪ 含有 ∪ 可能 (闭环语义: 未勾选元素视为「没有」)
        allowed_pool = set(ef["must_have"]) | set(ef["has"]) | set(ef["maybe"]) if ef else set()
        elements_allowed = allowed_pool if allowed_pool else None
        try:
            cands = cdb.search_cod_by_d_peaks(
                d_list, i_list, tolerance=0.02, limit=prefilter_limit,
                elements_allowed=elements_allowed,
            )
        except Exception:
            return []
        if not cands:
            return []

        tt_min, tt_max = float(data.two_theta[0]), float(data.two_theta[-1])

        # COD 库公式为空格分隔的 "元素+系数" 组 (如 "Li1.13 Mn2 O4",
        # 系数可含小数), parse_formula 处理不了 → 本地健壮解析
        import re as _re
        _tok_re = _re.compile(r"^([A-Z][a-z]?)(\d*\.?\d*)$")

        def _elements_from_db_formula(f: str) -> set:
            els: set = set()
            for tok in (f or "").split():
                m = _tok_re.match(tok)
                if m:
                    els.add(m.group(1))
                else:
                    try:
                        els |= parse_formula(tok)
                    except Exception:
                        continue
            return els

        # 3. 候选 → Phase → 统一 FOM 评分
        #    排序以 Hanawalt 预筛质量为主 (主峰原则/强峰精确率/加权召回),
        #    FOM 仅作同分决胜 — 否则"参考峰多的密集物相反超少峰真物相"
        results: list[tuple[dict, PhaseMatchResult]] = []
        for c in cands:
            detail = cdb.get_cod_phase(c["cod_id"])
            if not detail:
                continue
            ref_peaks = []
            for d_val, i_val in zip(detail.get("peaks_d_list", []),
                                    detail.get("peaks_i_list", [])):
                if d_val <= 0:
                    continue
                sin_theta = wavelength / (2.0 * d_val)
                if sin_theta > 1.0:
                    continue
                tt = 2.0 * float(np.degrees(np.arcsin(sin_theta)))
                if tt_min <= tt <= tt_max:
                    ref_peaks.append(((0, 0, 0), tt, float(i_val)))
            if not ref_peaks:
                continue

            formula = detail.get("formula", "") or ""
            phase = Phase(
                name=f"{formula} (COD {c['cod_id']})",
                formula=formula,
                space_group=detail.get("space_group", ""),
                reference_peaks=ref_peaks,
                elements=_elements_from_db_formula(formula),
            )
            if ef and not elements_match_filter(
                phase.elements,
                has=ef["has"], maybe=ef["maybe"], exclude=ef["exclude"],
                must_have=ef["must_have"],
            ):
                continue
            results.append((c, self._match_phase_fom(phase, peaks, tolerance)))

        # ── 排序: Hanawalt 预筛质量 × 匹配因子 加权混合 (0.9.11) ──────
        # 旧口径是字典序 (main_peak_match → top_precision → 召回 → FOM),
        # main_peak_match 是 0/1 二值: 多相样品里只有主物相能拿 1, 其余
        # 真物相被整体压到后面。13 试样基准上改为加权混合后:
        #   Top-1 12%→16%, Top-5 22%→27%, Top-10 24%→29%
        # FOM 已改为加权互斥口径 (不再偏好峰多的密集相), 故可承担主权重。
        # fom_good 用固定尺度 1.2 (与分位数自适应版等效, 但不依赖查询分布)。
        def _cod_rank_score(item: tuple[dict, PhaseMatchResult]) -> float:
            c, r = item
            h = (0.40 * float(c.get("main_peak_match", 0.0))
                 + 0.30 * float(c.get("top_precision", 0.0))
                 + 0.20 * float(c.get("intensity_weighted_top_recall", 0.0))
                 + 0.10 * float(c.get("top_recall", 0.0)))
            fom_good = 1.0 - min(max(float(r.score) / 1.2, 0.0), 1.0)
            return 0.3 * h + 0.7 * fom_good

        results.sort(key=lambda it: -_cod_rank_score(it))
        return [r for _, r in results[:top_n]]