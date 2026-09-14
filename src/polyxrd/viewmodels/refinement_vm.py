"""
Rietveld精修ViewModel
=====================
Rietveld精修的状态管理。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from polyxrd.models.phase import Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.services.export_service import ExportService
from polyxrd.services.rietveld_refiner import RietveldRefiner


class RefinementViewModel(QObject):
    """Rietveld精修ViewModel

    Signals:
        refinement_started: 精修开始
        refinement_progress: 精修进度
        refinement_completed: 精修完成
        refinement_failed: 精修失败
        error: 错误发生
    """

    refinement_started = Signal()
    refinement_progress = Signal(int)
    refinement_completed = Signal(object)
    refinement_failed = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._refiner = RietveldRefiner()
        self._exporter = ExportService()
        self._result: Optional[RefinementResult] = None
        self._selected_phases: list[Phase] = []

    @property
    def result(self) -> Optional[RefinementResult]:
        return self._result

    def set_phases(self, phases: list[Phase]) -> None:
        """设置待精修物相"""
        self._selected_phases = phases

    def reset(self) -> None:
        """清空精修结果与待精修物相 (换新数据/关闭时调用)。"""
        self._result = None
        self._selected_phases = []

    def refine(
        self,
        data,
        phases: Optional[list[Phase]] = None,
        strategy: str = "sequential",
        engine: str = "builtin",
        max_cycles: int = 20,
        **kwargs,
    ) -> None:
        """执行Rietveld精修"""
        if phases is None:
            phases = self._selected_phases

        if not phases:
            self.error.emit("请先选择物相")
            return

        self.refinement_started.emit()
        self.refinement_progress.emit(0)

        try:
            result = self._refiner.refine(
                data,
                phases,
                strategy=strategy,
                engine=engine,
                max_cycles=max_cycles,
                **kwargs,
            )
            self._result = result
            self.refinement_progress.emit(100)
            self.refinement_completed.emit(result)
        except Exception as e:
            self.refinement_failed.emit(str(e))
            self.error.emit(f"精修失败: {e}")

    def get_summary(self) -> str:
        """获取精修摘要"""
        if self._result:
            return self._result.summary()
        return "没有精修结果。"

    def adopt_result(self, result: Optional[RefinementResult]) -> None:
        """接收一个**在别处算好**的精修结果, 当成本 VM 的当前结果。

        用途: 分步精修向导 (`views/refinement_wizard.py`) 自带一个
        `RietveldRefiner` 并在自己的执行页跑完整精修 —— 它是自包含的, 不走本 VM。
        若不把结果接回来, 用户在向导里跑完会看到"精修页/报告页什么都没有",
        两个向导的行为就不一致了。

        这里只做状态登记与信号广播, **不触发任何计算**, 因此代价可忽略。
        广播的信号与 `refine()` 末尾完全一致, 保证下游(精修页/报告)无需区分
        结果是"本 VM 算的"还是"向导算的"。
        """
        if result is None:
            return
        self._result = result
        self.refinement_progress.emit(100)
        self.refinement_completed.emit(result)

    def export_result(self, path: str, format: str = "all") -> None:
        """导出精修结果"""
        if self._result is None:
            self.error.emit("没有精修结果可导出")
            return

        try:
            self._exporter.export_rietveld_result(
                self._result, path, format=format
            )
        except Exception as e:
            self.error.emit(f"导出失败: {e}")
