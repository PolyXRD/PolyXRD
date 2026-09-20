"""外部精修程序探测与配置 (v0.15 M25)
====================================

三个外部精修引擎 (GSAS-II / MAUD / FullProf) 的统一配置层:

- ``ToolSpec``: 每个程序一份规格 (key/标题/可执行文件名/自动探测函数);
- ``detect``: 本机自动探测 (用户配置优先, 其次常见安装位置);
- ``validate``: 校验用户给定的路径是否可用;
- ``resolve``: 汇总解析结果 ``(path|None, source)`` — source ∈ user/auto/none。

纯逻辑无 Qt 依赖; 配置持久化走 ``AppConfig.get/set_external_tool_path``
(``~/.polyxrd/external_tools.json``)。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from polyxrd.config import get_config

__all__ = [
    "ToolSpec",
    "GSAS2_SPEC",
    "MAUD_SPEC",
    "FULLPROF_SPEC",
    "ALL_SPECS",
    "resolve_tool",
]


@dataclass(frozen=True)
class ToolSpec:
    """外部工具规格。"""

    key: str                                  # 配置 key (config.EXTERNAL_TOOL_KEYS)
    title: str                                # 显示名
    exe_names: tuple[str, ...] = field(default_factory=tuple)  # 校验时的合法文件名
    detect_fn: Optional[Callable[[], Optional[Path]]] = None    # 自动探测

    def validate(self, path: str | Path | None) -> bool:
        """路径存在且 (无 exe 约束 或 文件名匹配 或 是含 JDK 的 MAUD 根)。"""
        if not path:
            return False
        p = Path(path)
        if not p.exists():
            return False
        if p.is_dir() and (p / "jdk" / "bin" / "java.exe").exists():
            return True  # MAUD 安装根目录
        if not self.exe_names:
            return True
        return p.name.lower() in {n.lower() for n in self.exe_names}


def _detect_gsas2() -> Optional[Path]:
    try:
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        return RietveldRefiner._find_gsas2_python()
    except Exception:  # noqa: BLE001
        return None


def _detect_maud() -> Optional[Path]:
    """MAUD: 返回自带 JDK 的 java.exe (根目录下通常没有 Maud.jar)。"""
    try:
        from polyxrd.services.maud_par_builder import detect_maud_root

        root = detect_maud_root()
        java = root / "jdk" / "bin" / "java.exe"
        return java if java.exists() else (root if root.exists() else None)
    except Exception:  # noqa: BLE001
        return None


def _detect_fullprof() -> Optional[Path]:
    """FullProf: 常见安装目录 (C:\\FullProf_Suite 等) → PATH。"""
    exe = "fp2k.exe"
    for prefix in (
        r"C:\FullProf_Suite",
        r"D:\FullProf_Suite",
        r"E:\FullProf_Suite",
        r"C:\Program Files\FullProf_Suite",
        r"C:\Program Files (x86)\FullProf_Suite",
    ):
        cand = Path(prefix) / exe
        if cand.exists():
            return cand
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        cand = Path(d) / exe
        if cand.exists():
            return cand
    return None


GSAS2_SPEC = ToolSpec(
    key="external_gsas2_path",
    title="GSAS-II",
    exe_names=("python.exe", "pythonw.exe"),   # 记录的是自带解释器
    detect_fn=_detect_gsas2,
)
MAUD_SPEC = ToolSpec(
    key="external_maud_path",
    title="MAUD",
    # 用户可配 MAUD 安装根目录或其自带 jdk/bin/java.exe
    exe_names=("java.exe",),
    detect_fn=_detect_maud,
)
FULLPROF_SPEC = ToolSpec(
    key="external_fullprof_path",
    title="FullProf",
    exe_names=("fp2k.exe", "fp2k_w.exe", "wfp2k.exe"),
    detect_fn=_detect_fullprof,
)
ALL_SPECS: tuple[ToolSpec, ...] = (GSAS2_SPEC, MAUD_SPEC, FULLPROF_SPEC)


def resolve_tool(spec: ToolSpec) -> tuple[Optional[Path], str]:
    """解析某工具的当前可用路径。

    Returns:
        ``(path, source)``: source = "user" (用户配置且存在) /
        "auto" (自动探测命中) / "none" (都不可用)。
    """
    user = get_config().get_external_tool_path(spec.key)
    if user is not None and spec.validate(user):
        return user, "user"
    if spec.detect_fn is not None:
        try:
            auto = spec.detect_fn()
        except Exception:  # noqa: BLE001
            auto = None
        if auto is not None and spec.validate(auto):
            return auto, "auto"
    if user is not None:
        return user, "user"  # 配置了但当前不可用 → 仍返回, UI 灯显示异常
    return None, "none"
