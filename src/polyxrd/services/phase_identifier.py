"""
物相识别服务
============
基于FOM (Figure of Merit) 算法的物相识别。
支持离线XRD参考数据库匹配和COD在线搜索。
支持三态元素过滤: 必须/可能/不含。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.formula_parser import parse_formula, elements_match_filter
from polyxrd.utils.resources import get_resource_path


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

    def build_refinement_combination(
        self,
        matches: list,
        expected_count: Optional[int] = None,
        min_coverage: float = 0.5,
    ) -> list:
        """从物相识别结果中生成精修组合，进一步过滤冗余和噪声

        在 identify_with_element_filter 返回结果基础上，进一步优化：
          1. 剔除参考峰覆盖率低于 min_coverage 的噪声物相
          2. 若用户给了 expected_count (预期物相数)，只取前 expected_count 个
             且剔除 w<1% 的尾项（避免精修时引入无意义自由度）
          3. 剔除纯金属占比超过 20% 的组合（再次防御性检查）
          4. 返回最终 Phase 对象列表，可直接传给 RietveldRefiner.refine()

        Args:
            matches: identify_with_element_filter 的输出
            expected_count: 预期物相数量（若已知）
            min_coverage: 参考峰匹配覆盖率下限 (0-1)，低于此视为噪声

        Returns:
            list[Phase] - 可直接用于 Rietveld 精修的物相列表
        """
        _nonmetal_exclude = {"H","He","N","O","F","Ne","Cl","Ar","Br","Kr","I","Xe","Rn",
                             "S","P","C","Si","Se","Te","As","Ge","B"}
        def _is_pure_metal(phase) -> bool:
            return (len(phase.elements) == 1
                    and not (phase.elements & _nonmetal_exclude))

        # 1. 过滤 coverage 低于阈值的物相
        filtered = [m for m in matches if m.coverage >= min_coverage]
        if not filtered:
            filtered = list(matches)  # 若全低于阈值则回退

        # 2. 若有预期数量，按 expected_count 截断
        if expected_count and expected_count > 0:
            filtered = filtered[:expected_count]

        # 3. 纯金属比例二次防御：>20% 则从尾往前移除纯金属直至达标
        phases_temp = [m.phase for m in filtered]
        pm_indices = [i for i, p in enumerate(phases_temp) if _is_pure_metal(p)]
        max_pm = max(1, int(0.2 * len(phases_temp) + 0.5))
        if len(pm_indices) > max_pm:
            to_remove = set(pm_indices[max_pm:])
            phases_temp = [p for i, p in enumerate(phases_temp) if i not in to_remove]

        # 4. 剔除 coverage <0.55 的纯金属（即使比例够了也删）
        final = []
        for m, p in zip(filtered, phases_temp):
            if _is_pure_metal(p) and m.coverage < 0.55:
                continue
            final.append(p)

        return final

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

        must = element_filter.get("must", []) if element_filter else []
        maybe = element_filter.get("maybe", []) if element_filter else []
        exclude = element_filter.get("exclude", []) if element_filter else []

        # ── 自动扩展 exclude: must∪maybe 补集内的元素一律排除 ──────────
        # 如果用户给了 must/maybe 但没给 exclude, 自动推导: 任何不在
        # must+maybe 中的元素都不可能出现在试样中 (例如 must=Zn/Ca, 则 S/P/Si
        # 等一律排除, 避免 CaSO4/CaSiO3 等干扰物相进入候选)
        if element_filter and (must or maybe):
            allowed = set(must) | set(maybe)
            # 自动推导: 遍历数据库中所有物相的元素, 不在 allowed 的加入 exclude
            extra_exclude = set()
            for phase in self._phase_database:
                for el in phase.elements:
                    if el not in allowed:
                        extra_exclude.add(el)
            if extra_exclude:
                exclude_set = set(exclude) | extra_exclude
                exclude = list(exclude_set)

        results = []
        for phase in self._phase_database:
            if element_filter and (must or exclude):
                if not elements_match_filter(phase.elements, must, maybe, exclude):
                    continue

            match_result = self._match_phase_fom(
                phase, peaks, tolerance
            )
            results.append(match_result)

        results.sort(key=lambda r: r.score)

        # ── 组合重排: 纯金属比例限制在 20% 以内, 避免过多纯金属挤占前 top_n ──
        _nonmetal_exclude = {"H","He","N","O","F","Ne","Cl","Ar","Br","Kr","I","Xe","Rn",
                             "S","P","C","Si","Se","Te","As","Ge","B"}
        def _is_pure_metal(phase) -> bool:
            return (len(phase.elements) == 1
                    and not (phase.elements & _nonmetal_exclude))

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

        # ── 去重: 同化学式只保留 FOM 最优 (第一个) 一个 ──────────────
        # 消除内置库中同一化学式有多个条目的问题 (如 Fluorite/CaF2 有两版本)
        seen_formulas: dict[str, bool] = {}
        deduped: list = []
        for r in results:
            formula = r.phase.formula or ""
            key = (formula, tuple(sorted(r.phase.elements)))
            if key not in seen_formulas:
                seen_formulas[key] = True
                deduped.append(r)
        results = deduped

        return results[:top_n]

    def _match_phase_fom(
        self,
        phase: Phase,
        peaks: PeakList,
        tolerance: float,
    ) -> PhaseMatchResult:
        """基于FOM算法匹配单个物相

        FOM (Figure of Merit):
        FOM = Σ|2θ_obs - 2θ_calc| / Σ(2θ_calc) × N_matched × 100

        Args:
            phase: 候选物相
            peaks: 实验峰列表
            tolerance: 容差

        Returns:
            PhaseMatchResult (score为FOM值，越低越好)
        """
        reference_peaks = phase.get_reference_peaks()
        total_ref_peaks = len(reference_peaks)

        if total_ref_peaks == 0:
            return PhaseMatchResult(
                phase=phase, score=999.0, matched_peaks=0,
                total_peaks=0, confidence="无参考数据", method="fom"
            )

        matched = 0
        sum_deviation = 0.0
        sum_ref_2theta = 0.0
        total_intensity_score = 0.0

        for hkl, ref_2theta, ref_intensity in reference_peaks:
            min_dist = float("inf")
            matched_intensity = 0.0

            for peak in peaks:
                dist = abs(peak.two_theta - ref_2theta)
                if dist < min_dist:
                    min_dist = dist
                    matched_intensity = peak.intensity

            if min_dist <= tolerance:
                matched += 1
                sum_deviation += min_dist
                sum_ref_2theta += ref_2theta

                if ref_intensity > 0 and matched_intensity > 0:
                    int_ratio = min(matched_intensity, ref_intensity) / max(matched_intensity, ref_intensity)
                    total_intensity_score += int_ratio

        if matched == 0 or sum_ref_2theta == 0:
            return PhaseMatchResult(
                phase=phase, score=999.0, matched_peaks=0,
                total_peaks=total_ref_peaks, confidence="不匹配", method="fom"
            )

        # FOM = 相对偏差，未匹配参考峰按容差计入偏差 (标准 FOM 做法)
        # 归一化用所有参考峰 2θ 之和，避免少峰物相因偶然单峰偏差小而占优
        sum_ref_2theta_all = sum(
            ref_2theta for _, ref_2theta, _ in reference_peaks
        )
        unmatched = total_ref_peaks - matched
        sum_deviation_effective = sum_deviation + unmatched * tolerance
        if sum_ref_2theta_all > 0:
            fom = (sum_deviation_effective / sum_ref_2theta_all) * 100.0
        else:
            fom = 999.0
        match_ratio = matched / total_ref_peaks
        avg_intensity_score = total_intensity_score / matched if matched > 0 else 0

        # combined_score: match_ratio 越高 -> (1-ratio*0.3) 越小 -> 分值越低(越好)
        combined_score = fom * (1.0 - match_ratio * 0.3) * (1.0 - avg_intensity_score * 0.1)

        # ── 纯金属惩罚: 单元素金属物相因 reference_peaks 少易误匹配, 加 1.5x 惩罚 ──
        # 非金属气态/固态非金属例外 (H,N,O,S,P,C,Si,Se,Te,As,Ge,B,卤素,稀有气体)
        _nonmetal_exclude = {"H","He","N","O","F","Ne","Cl","Ar","Br","Kr","I","Xe","Rn",
                             "S","P","C","Si","Se","Te","As","Ge","B"}
        if len(phase.elements) == 1 and not (phase.elements & _nonmetal_exclude):
            combined_score *= 1.5

        combined_score = max(combined_score, 0.01)

        if combined_score < 0.1:
            confidence = "极好匹配"
        elif combined_score < 0.3:
            confidence = "良好匹配"
        elif combined_score < 0.5:
            confidence = "一般匹配"
        else:
            confidence = "可能不匹配"

        return PhaseMatchResult(
            phase=phase,
            score=round(combined_score, 4),
            matched_peaks=matched,
            total_peaks=total_ref_peaks,
            confidence=confidence,
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
        must = element_filter.get("must", []) if element_filter else []
        maybe = element_filter.get("maybe", []) if element_filter else []
        exclude = element_filter.get("exclude", []) if element_filter else []
        elements_allowed = (set(must) | set(maybe)) if (must or maybe) else None
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
            if must or maybe or exclude:
                # 与内置引擎 "自动扩展 exclude" 同哲学:
                # 物相元素须完全落在 must∪maybe 内, 且不与 exclude 相交
                allowed = set(must) | set(maybe)
                if not phase.elements or not phase.elements.issubset(allowed):
                    continue
                if any(elem in phase.elements for elem in exclude):
                    continue
            results.append((c, self._match_phase_fom(phase, peaks, tolerance)))

        def _hanawalt_key(item: tuple[dict, PhaseMatchResult]):
            c, r = item
            return (
                -float(c.get("main_peak_match", 0.0)),
                -float(c.get("top_precision", 0.0)),
                -float(c.get("intensity_weighted_top_recall", 0.0)),
                -float(c.get("top_recall", 0.0)),
                r.score,  # FOM 同分决胜 (越低越好)
            )

        results.sort(key=_hanawalt_key)
        return [r for _, r in results[:top_n]]