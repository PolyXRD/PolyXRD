"""
物相分析ViewModel
==================
峰检测、物相识别的状态管理。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from polyxrd.i18n import tr
from polyxrd.models.peak import PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.services.peak_finder import PeakFinder
from polyxrd.services.phase_identifier import PhaseIdentifier
from polyxrd.services.profile_fitting import ProfileFittingService


class PhaseViewModel(QObject):
    """物相分析ViewModel

    Signals:
        peaks_detected: 峰检测完成
        peaks_fitted: 峰拟合完成
        phase_identified: 物相识别完成
        phase_selected: 选中物相
        error: 错误发生
    """

    peaks_detected = Signal(object)
    peaks_fitted = Signal(object, object)
    phase_identified = Signal(list)
    phase_selected = Signal(object)
    error = Signal(str)
    info = Signal(str)
    # M21: 勾选集合变更 (多相叠加)
    selection_changed = Signal(list)
    assignment_changed = Signal(object, object)   # (assignments, ref_hit)
    # v3.2.0: 外挂库建索引进度 (done, total, stage)。首次挂百万相级的
    # XinMatch 库要建 5~10 min 索引, 界面必须知道它还活着。
    index_progress = Signal(int, int, str)

    def __init__(self) -> None:
        super().__init__()
        self._peak_finder = PeakFinder()
        self._identifier = PhaseIdentifier()
        self._profile_fitting = ProfileFittingService()

        self._peaks: Optional[PeakList] = None
        self._fitted_peaks: Optional[PeakList] = None
        self._matched_phases: list[PhaseMatchResult] = []
        self._selected_phases: list[Phase] = []
        # P2-2: 非晶/近非晶诊断 (只用于解释"没匹配上", 不参与也不抑制检索)
        self._amorphous_info: Optional[dict] = None

    @property
    def peaks(self) -> Optional[PeakList]:
        return self._peaks

    @property
    def fitted_peaks(self) -> Optional[PeakList]:
        return self._fitted_peaks

    @property
    def matched_phases(self) -> list[PhaseMatchResult]:
        return self._matched_phases

    @property
    def selected_phases(self) -> list[Phase]:
        return self._selected_phases

    @property
    def amorphous_info(self) -> Optional[dict]:
        """P2-2: 最近一次检索后的非晶/近非晶诊断 (未检索 → None)。

        只用于向用户解释"为什么没匹配上", 绝不用于抢先抑制检索:
        判定 = 谱图弥散 AND 未获可接受匹配, 二者缺一不可。
        """
        return self._amorphous_info

    def reload_databases(self) -> None:
        """外挂数据库被导入/取消挂载后, 丢掉持有旧路径的缓存。

        v4.2.0 起本地 COD sqlite 运行时已移除, `PhaseIdentifier` 不再缓存
        库连接 (每次调用现开/现关), 所以这里只需让 `db_import.reload_caches`
        清 PDF2 侧的模块级实例与 polyDB 挂载点。
        """
        from polyxrd.services import db_import
        db_import.reload_caches()

    def set_data_source(self, data):
        """设置数据源 (用于后续操作)"""
        self._current_data = data

    def find_peaks(
        self,
        data,
        height: float = 0.05,
        distance: float = 0.5,
        prominence: float = 0.01,
        detect_shoulders: bool = False,
        sensitivity: Optional[float] = None,
    ) -> None:
        """自动峰检测 (M20: 支持 M05 增强参数)"""
        try:
            peaks = self._peak_finder.find_peaks(
                data,
                height=height,
                distance=distance,
                prominence=prominence,
                detect_shoulders=detect_shoulders,
                sensitivity=sensitivity,
            )
            self._peaks = peaks
            self.peaks_detected.emit(peaks)
        except Exception as e:
            self.error.emit(tr("error.peak_finder_failed", error=e))

    def find_peaks_advanced(
        self,
        data,
        sigma_threshold: float = 3.0,
        distance_deg: float = 0.12,
        bg_window_deg: float = 2.0,
        refine_mode: str = "fit",
        **kwargs,
    ) -> None:
        """M21: 高精度峰检测 (背景扣除 + 亚步长峰位 + 联合拟合精修)。

        替代 find_peaks 的低精度网格峰位; 旧方法保留。产出自带背景扣除,
        峰位可到 ~0.001°。
        """
        from polyxrd.services.peak_detection import (
            PeakDetectOptions,
            detect_peaks_from_data,
        )
        try:
            opts = PeakDetectOptions(
                sigma_threshold=sigma_threshold,
                distance_deg=distance_deg,
                bg_window_deg=bg_window_deg,
                refine_mode=refine_mode,
                wavelength=getattr(data, "wavelength", None) or 1.5406,
            )
            for k, v in kwargs.items():
                if hasattr(opts, k):
                    setattr(opts, k, v)
            peaks = detect_peaks_from_data(data, opts)
            self._peaks = peaks
            self.peaks_detected.emit(peaks)
        except Exception as e:
            self.error.emit(tr("error.peak_finder_hi_failed", error=e))

    def fit_peaks(
        self,
        data,
        model: str = "voigt",
    ) -> None:
        """峰拟合"""
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit(tr("error.no_peaks"))
            return
        try:
            fitted, stats = self._peak_finder.fit_peaks(
                data, self._peaks, model=model
            )
            self._fitted_peaks = fitted
            self.peaks_fitted.emit(fitted, stats)
        except Exception as e:
            self.error.emit(tr("error.peak_fit_failed", error=e))

    #: 外挂库做 Profile Fitting 时的候选池上限。
    #: 全谱拟合是 O(候选数 × 网格点数), 7.7 万相穷举不可行；d-I 预筛拿前
    #: 200 个候选再全谱重排。一次点击通常数秒 (视库规模/磁盘/CPU 而定),
    #: 换机器可能更慢; 改大只会线性变慢, 召回收益递减。
    PROFILE_EXTERNAL_POOL = 200

    def _resolve_mount(self, db_source: str):
        """`db_source` → 挂载项 (解析不出 / 注册表异常都返回 None)。"""
        try:
            from polyxrd.services import db_mounts

            return db_mounts.resolve_mount(db_source)
        except Exception:  # noqa: BLE001 - 注册表异常不该阻断识别主链路
            return None

    def _ensure_mount_usable(self, mount) -> bool:
        """检查选中的库当前是否真的能检索; 不能则发出**明确原因**并返回 False。

        为什么必须在分发前探测: 路径存在但内容损坏 (半成品 polyDB / 被截断的
        sqlite / 只读网盘掉线) 时, 各引擎的既有行为是"返回空候选"。界面于是
        显示"没匹配到物相", 用户会以为样品里没有这个相 —— 实际是库打不开。
        v4.0.0 的代码评估里把这条列为遗留缺陷, 这里补上。

        内置库未挂载时 (`path is None`) 也会走到这里: 下拉里该项本来就被
        置灰, 能选中说明状态刚变化, 报错比静默返回空结果更符合直觉。
        """
        if mount is None:
            return True
        if not mount.exists:
            self.error.emit(tr("error.db_missing", name=mount.display_name()))
            return False
        try:
            from polyxrd.services import db_mounts

            res = db_mounts.probe(mount)
        except Exception as e:  # noqa: BLE001 - 探测异常按不可用处理
            res = {"ok": False, "error": f"{e}"}
        if res.get("ok"):
            return True
        detail = str(res.get("error") or "")
        extra = str(res.get("detail") or "")
        if extra:
            detail = f"{detail} ({extra})" if detail else extra
        self.error.emit(tr("error.db_unusable",
                           name=mount.display_name(), detail=detail or "unknown"))
        return False

    def _identify_with_source(
        self,
        data,
        *,
        peaks,
        element_filter,
        elements=None,
        top_n: int,
        tolerance: float,
        db_source: str,
        prefilter_limit: Optional[int] = None,
    ) -> Optional[list[PhaseMatchResult]]:
        """按 `db_source` 分发到对应检索引擎 (识别主链路与 Profile Fitting 共用)。

        v4.0.0: 数据源 = 「挂载列表」里某一行的 id。先解析成 (kind, 挂载项),
        再按 kind 分发 —— 同一类型挂多份库时只有"用户自加的那一份"才传显式
        路径; 内置项继续按配置解析, 与历史行为逐字一致。

        Args:
            peaks: 参与检索的峰表 (None → 各引擎自行寻峰, Profile Fitting 用)。
            prefilter_limit: 预筛候选池大小; None 用各引擎默认值 (100)。
                外挂库做 Profile Fitting 时要先把池子放大, 否则 `top_n=200`
                实际只会在前 100 个候选里挑。

        Returns:
            结果列表; 选中的库不可用 / 引擎抛异常时返回 None (错误已 emit)。
        """
        mount = self._resolve_mount(db_source)
        if not self._ensure_mount_usable(mount):
            return None
        # 按**引擎**分发而不是按 kind: 自定义类型可以复用现成引擎
        # (MountKind.engine = "polydb" / "pdf2" / "user"), 只要容器结构与
        # 引擎预期一致; 没有引擎的类型必须明确报错, 不能静默退回内置库。
        engine = (mount.engine if mount is not None else "") or ""
        # 兼容历史语义: 内置项不传显式路径 (按配置解析); 用户自加项传路径。
        explicit = None
        if mount is not None and not mount.builtin:
            explicit = mount.path
        # polyDB 是目录容器, 两个变体是两份独立的库: 必须把路径/变体带下去,
        # 否则「COD 全库 (polyDB)」会被当成无机库那一份来查。
        poly_path = None
        if engine == "polydb" and mount is not None and mount.exists:
            poly_path = mount.path
            explicit = None
        pool = ({"prefilter_limit": int(prefilter_limit)}
                if prefilter_limit else {})
        if engine and engine not in ("pdf2", "user", "polydb"):
            self.error.emit(tr(
                "error.db_unusable",
                name=(mount.display_name() if mount is not None else db_source),
                detail=f"unsupported engine: {engine}"))
            return None
        try:
            if engine == "pdf2":
                results = self._identifier.identify_with_pdf2(
                    data,
                    peaks=peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                    db_path=explicit,
                    **pool,
                )
            elif engine == "user":
                # v2.6.0: 用户自建库 (同构 sqlite)。与 COD 无机库同一套
                # 预筛/评分, 但返回的 Phase 自带晶胞+原子坐标, 可直接精修。
                results = self._identifier.identify_with_user_db(
                    data,
                    peaks=peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                    **pool,
                )
            elif engine == "polydb":
                # v4.0.0: polyDB 外挂库（目录容器 + 位图倒排预筛），v4.1.0 起
                # 它是**默认参考库**。与 COD 无机库同一套打分，只是候选池靠
                # 位图+上界分层生成；条目带非对称单位原子位点，命中相可直接精修。
                results = self._identifier.identify_with_polydb(
                    data,
                    peaks=peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                    db_path=str(poly_path) if poly_path else None,
                    # 路径缺省时靠 variant 选槽位: 「COD 全库 (polyDB)」这一行
                    # 若被卸下, 绝不能悄悄退到无机库那一份去查。
                    variant=(mount.variant if mount and mount.variant
                             else "cod-inorg"),
                    **pool,
                )
            elif element_filter:
                results = self._identifier.identify_with_element_filter(
                    data,
                    peaks=peaks,
                    element_filter=element_filter,
                    top_n=top_n,
                    tolerance=tolerance,
                )
            else:
                results = self._identifier.identify(
                    data,
                    peaks=peaks,
                    elements=elements,
                    top_n=top_n,
                    tolerance=tolerance,
                )
        except Exception as e:  # noqa: BLE001 - 检索失败发信号, 不崩 UI
            self.error.emit(tr("error.identify_failed", error=e))
            return None
        return results

    def _profile_candidates(self, data, db_source: str, engine: str,
                            element_filter, pool: int):
        """Profile Fitting 的候选池 (Phase 列表); None = 已报错需中止。

        为什么 polyDB 单独走 `prescreen_with_polydb`: 常规检索的 FoM 打分是
        整条链最贵的一段, 而 Profile Fitting 本来就要按全谱相关系数重排,
        FoM 排序对它是废动作。直接取预筛行能把"200 候选"从数十秒压到
        数秒 (复杂谱/慢机器差异更大)。

        其它引擎 (PDF2/用户库/自定义) 继续复用常规检索拿候选 —— 它们的
        预筛规模小或没有独立的"只预筛"接口, 收益不足以再复制一套取相逻辑。
        """
        if engine == "polydb" and hasattr(self._identifier,
                                          "prescreen_with_polydb"):
            mount = self._resolve_mount(db_source)
            poly_path = (mount.path
                         if mount is not None and mount.exists else None)
            return self._identifier.prescreen_with_polydb(
                data,
                peaks=None,
                element_filter=element_filter,
                limit=pool,
                db_path=str(poly_path) if poly_path else None,
                variant=(mount.variant if mount is not None and mount.variant
                         else "cod-inorg"),
            )
        pre = self._identify_with_source(
            data,
            peaks=None,
            element_filter=element_filter,
            top_n=pool,
            tolerance=0.15,
            db_source=db_source,
            prefilter_limit=pool,
        )
        if pre is None:
            return None
        return [r.phase for r in pre
                if r is not None and getattr(r, "phase", None) is not None]

    def identify_phases(
        self,
        data,
        elements: Optional[list[str]] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        tolerance: float = 0.15,
        db_source: str = "builtin",
        marked_peaks: Optional[list[float]] = None,
    ) -> None:
        """物相识别 (支持多数据库源)。

        Args:
            db_source: 数据源 = 「外挂数据库管理」列表里某一行的 id, 由
                :mod:`polyxrd.services.db_mounts` 解析成 (kind, path) 后分发:

                - ``builtin``: 内置 118 物相库 (无外挂库时的兜底);
                - ``pdf2`` / ``user``: ICDD PDF-2 / 用户自建库;
                - ``polydb:cod-inorg`` / ``polydb:cod-full``: 内置的两个
                  polyDB 变体;
                - **任意挂载项 id** (``<kind>:<摘要>``, 例如
                  ``polydb:1a2b3c4d``): 用户自加的库, 同一类型可挂多份,
                  各自独立检索 (选中哪一行就用哪一行)。

                老字面量 (``cod_inorganics`` / ``cod_index`` / ``cod_full`` /
                ``xinmatch`` / ``polydb``) 经别名表映射到语义等价的新库。
            marked_peaks: 标记峰 2θ 序列 (v2.2 S13)。None → 全部实测峰;
                传入时仅保留与标记位最近 (≤0.30°) 的实测峰参与检索,
                用于残差相/微量相追查 (候选列表右键"仅对标记峰再匹配")。
        """
        if self._peaks is None or len(self._peaks) == 0:
            self.error.emit(tr("error.no_peaks"))
            return
        use_peaks = self._peaks
        if marked_peaks is not None:
            from polyxrd.services.foam import marked_peak_indices

            all_peaks = list(self._peaks.peaks)
            keep = marked_peak_indices(
                [p.two_theta for p in all_peaks], marked_peaks)
            if not keep:
                self.error.emit(tr("error.no_peaks"))
                return
            use_peaks = PeakList(peaks=[all_peaks[k] for k in keep],
                                 source=self._peaks.source)
        results = self._identify_with_source(
            data,
            peaks=use_peaks,
            element_filter=element_filter,
            elements=elements,
            top_n=top_n,
            tolerance=tolerance,
            db_source=db_source,
        )
        if results is None:
            return
        self._matched_phases = results
        self._amorphous_info = self._assess_amorphous(data, use_peaks, results)
        self.phase_identified.emit(results)

    @staticmethod
    def _assess_amorphous(data, peaks, results) -> Optional[dict]:
        """P2-2: 检索后评估非晶度 (纯附加信息, 失败一律返回 None 不影响主流程)。

        仅在"谱图弥散且没匹配上"时标 ``amorphous``; 已拿到可接受结晶相匹配的
        低对比度结晶谱 (如石英标样 SILICA、NCM811) 会被 veto, 不会误标。
        """
        try:
            from polyxrd.services.amorphous import assess_amorphous

            return assess_amorphous(data, peaks=peaks,
                                    top_match=results[0] if results else None)
        except Exception:
            return None

    def select_phase(self, phase: Phase) -> None:
        """选中物相"""
        if phase not in self._selected_phases:
            self._selected_phases.append(phase)
        self.phase_selected.emit(phase)

    def clear_selection(self) -> None:
        """清空选中物相"""
        self._selected_phases.clear()

    def reset_analysis(self) -> None:
        """清空全部分析状态 (峰/拟合峰/匹配结果/选中相), 换新数据时调用。

        不发信号 (由主 VM 统一在数据切换后发 data_changed/peaks_changed/
        phase_identified 空集通知各视图重绘)。"""
        self._peaks = None
        self._fitted_peaks = None
        self._matched_phases = []
        self._selected_phases = []
        self._amorphous_info = None

    def restore_state(
        self,
        peaks: Optional[PeakList] = None,
        results: Optional[list[PhaseMatchResult]] = None,
        selected: Optional[list[Phase]] = None,
    ) -> None:
        """从项目文件恢复分析状态 (v2.1 P0-1)。

        调用时机: 数据已恢复之后 (restore_data 触发的 reset_analysis 已执行完)。
        发峰/物相/勾选三类信号让各视图按"有数据"路径重绘。
        """
        self._peaks = peaks
        self._matched_phases = list(results or [])
        self._selected_phases = list(selected or [])
        if self._peaks is not None:
            self.peaks_detected.emit(self._peaks)
        self.phase_identified.emit(list(self._matched_phases))
        self.selection_changed.emit(list(self._selected_phases))

    # ── M21: 多选集合管理 (勾选叠加) ───────────────
    MAX_SELECTED = 8

    def update_selection(self, phase: Phase, checked: bool) -> None:
        """勾选/取消一个物相, 维持有序集合 (去重按 name+formula)。

        勾选时若达上限则忽略 (提示由视图层负责)。变更后 emit selection_changed。
        """
        key = (getattr(phase, "name", ""), getattr(phase, "formula", ""))
        idx = next((i for i, p in enumerate(self._selected_phases)
                    if (getattr(p, "name", ""), getattr(p, "formula", "")) == key),
                   None)
        if checked:
            if idx is None:
                if len(self._selected_phases) >= self.MAX_SELECTED:
                    return
                self._selected_phases.append(phase)
        else:
            if idx is not None:
                del self._selected_phases[idx]
        self.selection_changed.emit(list(self._selected_phases))

    def is_selected(self, phase: Phase) -> bool:
        key = (getattr(phase, "name", ""), getattr(phase, "formula", ""))
        return any((getattr(p, "name", ""), getattr(p, "formula", "")) == key
                   for p in self._selected_phases)

    def current_assignment(self, tolerance: float = 0.30):
        """当前选中相 + 实测峰 → (assignments, ref_hit)。无峰/无选中 → ([], 空)。"""
        from polyxrd.services.phase_display import assign_peaks

        if not self._selected_phases or not self._peaks:
            return [], [[] for _ in self._selected_phases]
        return assign_peaks(self._peaks.peaks, self._selected_phases,
                            tolerance=tolerance)

    def search_residual_peaks(self, data, tolerance: float = 0.30,
                              element_filter: Optional[dict] = None,
                              top_n: int = 5,
                              db_source: str = "builtin") -> None:
        """仅对当前选中相解释不到的实测峰 (残差峰) 再做一次物相检索。

        用于迭代式物相分析: 先确认主相, 再对未解释的峰追查残余微量相。
        无选中相或无残差峰时直接返回 (不触发检索)。

        Args:
            db_source: 复用用户当前选中的数据库源。v4.6.0 之前这里写死
                `identify_phases` 的默认值 `builtin` —— 用户选了外挂库
                做首轮检索, 追残差相时却悄悄退回内置 118 相库, 结论不可比。
        """
        if not self._peaks:
            self.error.emit(tr("error.no_peaks"))
            return
        if not self._selected_phases:
            self.error.emit(tr("error.no_phase_selected"))
            return
        assignments, _ = self.current_assignment(tolerance=tolerance)
        residual_2t = [a.two_theta for a in assignments
                       if a.phase_index is None]
        if not residual_2t:
            self.info.emit(tr("error.no_residual_peaks"))
            return
        self.identify_phases(
            data,
            element_filter=element_filter,
            top_n=top_n,
            tolerance=tolerance,
            db_source=db_source,
            marked_peaks=residual_2t,
        )

    def add_custom_phase(self, phase: Phase) -> None:
        """添加自定义物相"""
        self._identifier.add_phase(phase)

    def identify_phases_profile_fitting(
        self,
        data,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        fwhm: float = 0.15,
        db_source: str = "builtin",
    ) -> None:
        """基于峰形拟合的物相识别 (无需寻峰)。

        v4.6.0: 数据源不再固定为内置 118 相库 ——

        * `builtin` (或无挂载项能解析): 对内置参考库做全谱拟合 (原行为);
        * 外挂库 (polyDB / PDF2 / 用户库): 先用该库的 d-I 预筛取
          :data:`PROFILE_EXTERNAL_POOL` 个候选, 再对这批候选做全谱拟合重排。
          7.7 万相逐相生成理论谱不可行, 所以"预筛 + 重排"是外挂库上唯一的
          可行做法; 预筛用的是与常规检索同一套 Hanawalt 口径, 排序由全谱
          相关系数决定, 与手工把库裁小再按原方法拟合等价。
        """
        mount = self._resolve_mount(db_source)
        engine = (mount.engine if mount is not None else "") or ""
        try:
            if not engine:
                # 内置库 / 无法解析的源: 沿用原路径 (118 相穷举)
                results = self._profile_fitting.identify(
                    data,
                    element_filter=element_filter,
                    top_n=top_n,
                    fwhm=fwhm,
                )
            else:
                if not self._ensure_mount_usable(mount):
                    return
                pool = max(int(self.PROFILE_EXTERNAL_POOL),
                           max(1, int(top_n)) * 4)
                phases = self._profile_candidates(
                    data, db_source, engine, element_filter, pool)
                if phases is None:
                    return
                name = (mount.display_name() if mount is not None
                        else (db_source or "builtin"))
                if not phases:
                    self.info.emit(tr("vw.phase_view.db_profile_external",
                                      name=name, n=0))
                    self._matched_phases = []
                    self.phase_identified.emit([])
                    return
                results = self._profile_fitting.score_phases(
                    data, phases, fwhm=fwhm)[:max(1, int(top_n))]
                self.info.emit(tr("vw.phase_view.db_profile_external",
                                  name=name, n=len(phases)))
            # 标记方法
            for r in results:
                r.method = "profile_fitting"
            self._matched_phases = results
            self.phase_identified.emit(results)
        except Exception as e:
            self.error.emit(f"Profile Fitting 物相识别失败: {e}")
