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

    def refine(
        self,
        data,
        phases: Optional[list[Phase]] = None,
        strategy: str = "sequential",
        engine: str = "gsas2",
        max_cycles: int = 20,
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
