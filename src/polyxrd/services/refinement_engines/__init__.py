"""
PolyXRD 精修引擎子包
====================
按引擎类型隔离的 Rietveld / Le Bail 后端实现。

当前包含:
- :mod:`polyxrd.services.refinement_engines.maud_engine` — MAUD 批处理后端
  (通过 ``com.radiographema.MaudText`` 子进程调用, 解析 .par / .tsv 回填结果)

本模块只做**最小重导出**, 便于::

    from polyxrd.services.refinement_engines import MaudEngine, MaudEngineError

注意: ``polyxrd.services.maud_par_builder`` 中的工具函数 (如
``detect_maud_root`` / ``write_ins_file``) **不在此重导出**, 需要时请直接
从源模块导入 —— 否则 monkeypatch 会打在错误的命名空间上。
"""

from polyxrd.services.refinement_engines.maud_engine import (
    MaudEngine,
    MaudEngineError,
    MaudProgress,
)

__all__ = [
    "MaudEngine",
    "MaudEngineError",
    "MaudProgress",
]
