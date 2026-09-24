"""
主ViewModel
===========
协调所有子ViewModel，为视图提供统一接口。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from polyxrd.i18n import tr
from polyxrd.models.peak import PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.refinement import RefinementResult
from polyxrd.services.phase_structure_resolver import PhaseStructureResolver
from polyxrd.viewmodels.data_vm import DataViewModel
from polyxrd.viewmodels.phase_vm import PhaseViewModel
from polyxrd.viewmodels.refinement_vm import RefinementViewModel


class MainViewModel(QObject):
    """主ViewModel

    协调数据、物相、精修三个子ViewModel。

    Signals:
        status_changed: 状态信息变更
        error_occurred: 错误发生
        data_changed: 数据变更
        peaks_changed: 峰变更
        phase_identified: 物相识别完成
        refinement_completed: 精修完成
        refinement_log: 精修过程日志 (v0.12.0, 逐行流式)
    """

    status_changed = Signal(str)
    error_occurred = Signal(str)
    data_changed = Signal(object)
    peaks_changed = Signal(object)
    phase_identified = Signal(list)
    refinement_completed = Signal(object)
    refinement_log = Signal(str)

    def __init__(self) -> None:
        super().__init__()

        self._data_vm = DataViewModel()
        self._phase_vm = PhaseViewModel()
        self._refinement_vm = RefinementViewModel()
        # 精修前置 CIF 自动匹配 (v0.12): 已选物相缺结构时按 COD 编号/
        # 规范化化学式/矿物名查库补齐。实例级缓存 —— 同一物相二次精修不重查。
        self._cif_resolver = PhaseStructureResolver()
        # 当前项目文件路径 (v2.1 P0-1: 保存项目 / 另存为 / 打开项目)
        self._project_file: Optional[str] = None

        # 连接子ViewModel的信号
        self._data_vm.data_loaded.connect(self._on_data_loaded)
        self._data_vm.data_updated.connect(self._on_data_updated)
        self._data_vm.error.connect(self._on_error)
        self._phase_vm.peaks_detected.connect(self._on_peaks_detected)
        self._phase_vm.error.connect(self._on_error)
        self._phase_vm.phase_identified.connect(self._on_phase_identified)
        self._refinement_vm.refinement_completed.connect(self._on_refinement_completed)
        self._refinement_vm.refinement_log.connect(self.refinement_log.emit)
        self._refinement_vm.error.connect(self._on_error)

    # ------------------------------------------------------------------
    # 公共属性
    # ------------------------------------------------------------------

    @property
    def current_data(self):
        return self._data_vm.current_data

    @property
    def processed_data(self):
        return self._data_vm._processed_data

    @property
    def raw_data(self):
        return self._data_vm.raw_data

    @property
    def peaks(self):
        return self._phase_vm.peaks

    @property
    def refinement_result(self):
        return self._refinement_vm.result

    @property
    def selected_phases(self):
        return self._phase_vm.selected_phases

    @property
    def matched_phases(self):
        """识别出的物相 (按匹配分排序)。

        用于用户**没有显式勾选**物相时的兜底: 精修向导/批量精修都靠它取
        "匹配分最高的前几个", 否则用户会莫名其妙被拦住说"请先选择物相"。
        """
        return self._phase_vm.matched_phases

    @property
    def project_file(self):
        """当前项目文件路径 (保存过/打开过则非 None)。"""
        return self._project_file

    # ------------------------------------------------------------------
    # 公共方法 - 项目保存/打开 (v2.1 P0-1)
    # ------------------------------------------------------------------

    def save_project(self, path: str | Path) -> None:
        """把当前会话 (数据/峰/物相/勾选集/精修结果) 存为 .pxrd 项目文件。"""
        from polyxrd.services.project_service import ProjectService

        data = self.current_data
        if data is None:
            self.error_occurred.emit(tr("error.no_data"))
            return

        results = self.matched_phases or []
        svc = ProjectService()
        svc.save_project(
            str(path),
            data=data,
            peaks=self.peaks,
            phases=[r.phase for r in results] or None,
            results=results or None,
            selected_phases=self.selected_phases or None,
            refinement_result=self.refinement_result,
        )
        self._project_file = str(path)
        self.status_changed.emit(tr("status.project_saved", path=str(path)))

    def open_project(self, path: str | Path) -> None:
        """打开 .pxrd 项目文件, 恢复数据与全部分析状态。

        恢复顺序很关键: 先恢复数据 (data_loaded 会触发 _on_data_loaded 的
        旧状态清空), 再恢复峰/物相/勾选集, 最后登记精修结果。
        """
        from polyxrd.services.project_service import ProjectService

        try:
            project = ProjectService().load_project(str(path))
        except Exception as e:
            self.error_occurred.emit(tr("status.project_load_failed", error=e))
            return

        self._project_file = str(path)
        data = project.get("data")
        if data is not None:
            # 先恢复数据 (触发状态清空), 再恢复分析状态
            self._data_vm.restore_data(data)
            self._phase_vm.restore_state(
                peaks=project.get("peaks"),
                results=project.get("results") or [],
                selected=project.get("selected_phases") or [],
            )
            refinement = project.get("refinement_result")
            if refinement is not None:
                self.adopt_refinement_result(refinement)
            self.status_changed.emit(
                tr("status.project_loaded", name=Path(path).name)
            )
        else:
            self.error_occurred.emit(
                tr("status.project_load_failed", error="project has no data")
            )

    # ------------------------------------------------------------------
    # 公共方法 - 数据
    # ------------------------------------------------------------------

    def load_file(self, file_path: str | Path) -> None:
        """加载数据文件"""
        self.status_changed.emit(tr("status.loading_file", path=file_path))
        self._data_vm.load_file(file_path)

    def subtract_background(self, method: str = "snip", **kwargs) -> None:
        """背景扣除"""
        self.status_changed.emit(tr("status.background_subtract", method=method))
        self._data_vm.subtract_background(method=method, **kwargs)

    def smooth_data(self, method: str = "savgol", window: int = 11, **kwargs) -> None:
        """平滑"""
        self.status_changed.emit(tr("status.smoothing", method=method))
        self._data_vm.smooth_data(method=method, window=window, **kwargs)

    def normalize_data(self) -> None:
        """归一化"""
        self._data_vm.normalize()

    def strip_kalpha2(self) -> None:
        """Kα2 剥离 (M20: 工具栏按钮真实接处理管线)"""
        self.status_changed.emit(tr("status.kalpha2_strip"))
        self._data_vm.strip_ka_alpha2()

    def reset_data(self) -> None:
        """重置为原始数据 (便于对比预处理效果)"""
        self.status_changed.emit(tr("menu.data_processing.reset"))
        self._data_vm.reset_to_raw()

    # ------------------------------------------------------------------
    # 分析状态重置 / 清除数据 (M21 数据文件菜单)
    # ------------------------------------------------------------------

    def reset_analysis_state(self) -> None:
        """清空旧数据分析状态 (峰/拟合峰/匹配/选中物相/精修), 保留当前数据。

        供"打开新文件"在加载前调用, 避免旧物相/峰残留叠加到新数据上。
        通过 peaks_changed(空)/phase_identified(空) 通知视图清空。
        """
        self._phase_vm.reset_analysis()
        self._refinement_vm.reset()
        empty_peaks = PeakList(source="auto")
        self.peaks_changed.emit(empty_peaks)
        self.phase_identified.emit([])

    def clear_all_data(self) -> None:
        """显式"关闭/清除数据": 清数据 + 分析状态, 回到空状态。"""
        self.status_changed.emit(tr("status.data_cleared"))
        self._phase_vm.reset_analysis()
        self._refinement_vm.reset()
        self._data_vm.clear_all()
        # clear_all 已 emit data_updated(None) → _on_data_updated → data_changed(None)
        empty_peaks = PeakList(source="auto")
        self.peaks_changed.emit(empty_peaks)
        self.phase_identified.emit([])

    def reload_databases(self) -> None:
        """外挂数据库挂载状态变化后, 让检索侧丢掉指向旧路径的缓存。"""
        self._phase_vm.reload_databases()

    # ------------------------------------------------------------------
    # 公共方法 - 峰检测
    # ------------------------------------------------------------------

    def find_peaks(
        self,
        height: float = 0.05,
        distance: float = 0.5,
        prominence: float = 0.01,
        detect_shoulders: bool = False,
        sensitivity: Optional[float] = None,
    ) -> None:
        """峰检测"""
        data = self.current_data
        if data is None:
            self.error_occurred.emit("请先加载数据")
            return

        self.status_changed.emit(tr("status.finding_peaks"))
        self._phase_vm.find_peaks(
            data, height=height, distance=distance, prominence=prominence,
            detect_shoulders=detect_shoulders, sensitivity=sensitivity,
        )

    def find_peaks_advanced(self, sigma_threshold: float = 3.0,
                            distance_deg: float = 0.12,
                            bg_window_deg: float = 2.0,
                            refine_mode: str = "fit",
                            **kwargs) -> None:
        """M21: 高精度峰检测 (背景扣除 + 亚步长 + 联合拟合)。"""
        data = self.current_data
        if data is None:
            self.error_occurred.emit("请先加载数据")
            return
        self.status_changed.emit(tr("status.finding_peaks_hi"))
        self._phase_vm.find_peaks_advanced(
            data, sigma_threshold=sigma_threshold,
            distance_deg=distance_deg, bg_window_deg=bg_window_deg,
            refine_mode=refine_mode, **kwargs,
        )

    def fit_peaks(self, model: str = "voigt") -> None:
        """峰拟合"""
        data = self.current_data
        if data is None:
            self.error_occurred.emit("请先加载数据")
            return

        self.status_changed.emit(tr("status.fitting_peaks", model=model))
        self._phase_vm.fit_peaks(data, model=model)

    # ------------------------------------------------------------------
    # 公共方法 - 物相识别
    # ------------------------------------------------------------------

    def identify_phases(
        self,
        elements: Optional[list[str]] = None,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        db_source: str = "builtin",
    ) -> None:
        """传统物相识别 (需要先寻峰)

        Args:
            db_source: 数据库源 ("builtin" / "cod_inorganics" /
                "cod_full" / "merged")
        """
        data = self.current_data
        if data is None:
            self.error_occurred.emit("请先加载数据")
            return

        self.status_changed.emit(tr("status.identifying_phases"))
        self._phase_vm.identify_phases(
            data, elements=elements, element_filter=element_filter,
            top_n=top_n, db_source=db_source,
        )

    def identify_phases_profile_fitting(
        self,
        element_filter: Optional[dict] = None,
        top_n: int = 5,
        fwhm: float = 0.15,
    ) -> None:
        """Profile Fitting物相识别 (无需寻峰)"""
        data = self.current_data
        if data is None:
            self.error_occurred.emit("请先加载数据")
            return

        self.status_changed.emit(tr("status.identifying_profile"))
        self._phase_vm.identify_phases_profile_fitting(
            data, element_filter=element_filter, top_n=top_n, fwhm=fwhm
        )

    def select_phase(self, phase: Phase) -> None:
        """选中物相"""
        self._phase_vm.select_phase(phase)
        self._refinement_vm.set_phases(self._phase_vm.selected_phases)

    # ------------------------------------------------------------------
    # 公共方法 - Rietveld精修
    # ------------------------------------------------------------------

    def refine_structure(
        self,
        strategy: str = "sequential",
        engine: str = "builtin",
        max_cycles: int = 20,
        wavelength: Optional[float] = None,
        two_theta_range: Optional[tuple[float, float]] = None,
        **kwargs,
    ) -> None:
        """Rietveld结构精修

        Args:
            strategy: 精修策略 (sequential/auto/manual)
            engine: 精修引擎 (auto/builtin/gsas2/powerxrd/maud)
            max_cycles: 最大循环数
            wavelength: 覆盖 X 射线波长 (Å); None = 沿用数据自带值。
                引擎内部一律读 `data.wavelength`, 所以必须在这里落到数据对象上,
                传成 kwargs 是**无效**的 (会被 **kwargs 静默吞掉)。
            two_theta_range: 只精修该 2θ 窗口 (min, max); None = 全区间。
                同样需要先在数据上裁好区间, 引擎按数据自身范围建模。
        """
        data = self.current_data
        if data is None:
            self.error_occurred.emit("请先加载数据")
            return

        data = self._apply_data_overrides(data, wavelength, two_theta_range)
        if data is None:
            return

        phases = self._phase_vm.selected_phases
        if not phases:
            # 如果没有选中物相，使用匹配分数最高的
            matched = self._phase_vm.matched_phases
            if matched:
                phases = [m.phase for m in matched[:3]]
                self._phase_vm._selected_phases = phases

        if not phases:
            self.error_occurred.emit("请先识别并选择物相")
            return

        # ── 精修前置: 给已选物相自动匹配 CIF 基础结构 (v0.12) ──
        # 检索得到的候选相多数只有参考峰+晶胞, 没有 cif_path/atomic_sites;
        # 不补结构, _refine_auto 永远走 builtin 剖面拟合, GSAS-II/MAUD
        # 真 Rietveld 无从谈起。未命中的相原样保留 (回退剖面拟合), 不阻断。
        phases = self._cif_resolver.resolve(
            phases,
            wavelength=float(data.wavelength),
            two_theta_range=(
                float(data.two_theta[0]), float(data.two_theta[-1]),
            ),
            log_cb=self.refinement_log.emit,
        )

        self.status_changed.emit(tr("status.rietveld_refine", engine=engine))
        self._refinement_vm.refine(
            data, phases, strategy=strategy, engine=engine, max_cycles=max_cycles, **kwargs
        )

    def _apply_data_overrides(
        self,
        data,
        wavelength: Optional[float],
        two_theta_range: Optional[tuple[float, float]],
    ):
        """按向导参数生成一份数据副本 (波长覆盖 / 2θ 窗口裁剪)。

        只在参数确实与原始数据不同时才复制, 避免无谓开销。
        裁剪后点数 < 3 (XRDData 下限) 时发错误信号并返回 None —— 让用户看到
        明确原因, 而不是让引擎抛一个难懂的异常。
        """
        if wavelength is None and two_theta_range is None:
            return data

        need_wl = wavelength is not None and abs(float(wavelength) - float(data.wavelength)) > 1e-9
        win = None
        req = None
        if two_theta_range is not None:
            req_lo, req_hi = float(two_theta_range[0]), float(two_theta_range[1])
            if req_lo > req_hi:
                req_lo, req_hi = req_hi, req_lo
            lo = max(req_lo, float(data.two_theta[0]))
            hi = min(req_hi, float(data.two_theta[-1]))
            req = (req_lo, req_hi)
            if lo > hi:
                # 请求窗口与数据范围完全不相交: 报"请求值"而不是空集边界, 更好懂
                self.error_occurred.emit(
                    tr("error.refine_window_no_overlap",
                       lo=f"{req_lo:.2f}", hi=f"{req_hi:.2f}",
                       dlo=f"{float(data.two_theta[0]):.2f}",
                       dhi=f"{float(data.two_theta[-1]):.2f}")
                )
                return None
            if lo > float(data.two_theta[0]) or hi < float(data.two_theta[-1]):
                win = (lo, hi)

        if not need_wl and win is None:
            return data

        import numpy as np

        from polyxrd.models.xrd_data import XRDData

        tt, ii = np.asarray(data.two_theta), np.asarray(data.intensity)
        if win is not None:
            mask = (tt >= win[0]) & (tt <= win[1])
            if int(mask.sum()) < 3:
                self.error_occurred.emit(
                    tr("error.refine_window_too_few",
                       lo=f"{req[0]:.2f}", hi=f"{req[1]:.2f}",
                       n=int(mask.sum()))
                )
                return None
            tt, ii = tt[mask], ii[mask]

        return XRDData(
            two_theta=tt,
            intensity=ii,
            wavelength=float(wavelength) if need_wl else float(data.wavelength),
            metadata=dict(data.metadata),
        )

    # ------------------------------------------------------------------
    # 公共方法 - 导出
    # ------------------------------------------------------------------
    def export_result(self, export_dir: str, format: str = "all") -> None:
        """导出结果"""
        self._refinement_vm.export_result(export_dir, format=format)

    def adopt_refinement_result(self, result) -> None:
        """登记一个在别处(如分步精修向导)算好的精修结果, 并广播完成信号。

        分步向导自带 refiner, 结果不会经过 `refine_structure`; 若不接回来,
        用户在向导里跑完会发现精修页/报告页仍是空的 —— 与快速向导行为不一致。
        下游(精修页/报告)无需关心结果来自哪条路径。
        """
        self._refinement_vm.adopt_result(result)

    # ------------------------------------------------------------------
    # 信号处理
    # ------------------------------------------------------------------

    def _on_data_loaded(self, data) -> None:
        # 新文件载入 → 清掉旧数据的峰/物相/精修残留 (避免残留叠到新数据)
        self._phase_vm.reset_analysis()
        self._refinement_vm.reset()
        self.peaks_changed.emit(PeakList(source="auto"))
        self.phase_identified.emit([])
        self.status_changed.emit(
            tr("status.data_loaded_count", count=len(data))
        )
        self.data_changed.emit(data)

    def _on_data_updated(self, data) -> None:
        self.data_changed.emit(data)

    def _on_peaks_detected(self, peaks: PeakList) -> None:
        self.status_changed.emit(tr("status.peaks_found", count=len(peaks)))
        self.peaks_changed.emit(peaks)

    def _on_phase_identified(self, results: list[PhaseMatchResult]) -> None:
        if results:
            best = results[0]
            self.status_changed.emit(
                tr("status.phase_identified",
                   name=best.phase.name, score=f"{best.score:.1f}")
            )
        self.phase_identified.emit(results)

    def _on_refinement_completed(self, result: RefinementResult) -> None:
        self.status_changed.emit(
            tr("status.refine_completed",
               wr=f"{result.wR:.3f}", count=len(result.phases))
        )
        self.refinement_completed.emit(result)

    def _on_error(self, message: str) -> None:
        self.error_occurred.emit(message)
