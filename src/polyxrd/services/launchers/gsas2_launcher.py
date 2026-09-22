"""GSAS-II GUI 启动器 (v0.15 M25-3)
====================================

降级语义: 不在启动器内做批处理精修 (那是 ``RietveldRefiner`` + 
``scripts/gsas2_bridge.py`` 的职责), 而是把实验谱 (.xy) 与各物相 CIF
导出到工作目录后, 直接拉起 GSAS-II 主 GUI (``GSASII/G2.py``), 由用户
在 GUI 中导入数据/建工程。

- GSAS-II 解释器与源码目录定位复用 ``RietveldRefiner`` 的探测逻辑
  (含 pixi 版 gsas2main 的 PYTHONPATH/DLL 注入);
- 工作目录由调用方经 ``fullprof.runner.new_run_dir`` 风格创建 (全 ASCII)。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

import numpy as np

__all__ = ["export_inputs", "find_gsas2_gui_entry", "launch_gui"]


def export_inputs(
    data,
    phases: list,
    workdir: str | Path,
    *,
    stem: str = "polyxrd",
) -> tuple[Path, list[Path]]:
    """导出实验谱 ``{stem}.xy`` 与各物相 CIF 到工作目录。

    CIF 优先走 :mod:`polyxrd.services.phase_cif_export` (COD 全文),
    拿不到 CIF 的相跳过并继续 (启动器不因单个相失败而中止)。

    Returns:
        ``(xy_path, cif_paths)``
    """
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)

    tt = np.asarray(data.two_theta, dtype=float)
    yy = np.asarray(data.intensity, dtype=float)
    ok = np.isfinite(tt) & np.isfinite(yy)
    xy_path = wd / f"{stem}.xy"
    lines = [f"{t:.5f} {y:.5f}" for t, y in zip(tt[ok], yy[ok])]
    xy_path.write_text("\n".join(lines) + "\n", encoding="ascii")

    cif_paths: list[Path] = []
    try:
        from polyxrd.services.phase_cif_export import (
            default_cif_filename,
        )
    except Exception:  # noqa: BLE001 — 纯导出能力缺失时静默降级
        return xy_path, cif_paths

    for idx, ph in enumerate(phases, start=1):
        try:
            from polyxrd.services.phase_cif_export import get_phase_cif_text

            text, cod_id = get_phase_cif_text(ph)
            name = default_cif_filename(ph, cod_id)
            out = wd / f"{idx:02d}_{name}"
            out.write_text(text, encoding="utf-8")
            cif_paths.append(out)
        except Exception:  # noqa: BLE001 — 单个相拿不到 CIF 时跳过
            continue
    return xy_path, cif_paths


def find_gsas2_gui_entry() -> tuple[Optional[Path], Optional[Path]]:
    """定位 ``(gsas2_python, G2.py)``; 任一缺失返回 ``(None, None)``。"""
    try:
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        py = RietveldRefiner._find_gsas2_python()
        src = RietveldRefiner._gsas2_pythonpath(py) if py else ""
    except Exception:  # noqa: BLE001
        return None, None
    if not py:
        return None, None
    for g2 in (
        Path(src) / "GSASII" / "G2.py" if src else None,
        Path(src) / "GSASII" / "GSASII.py" if src else None,
    ):
        if g2 and g2.exists():
            return py, g2
    return py, None


def launch_gui(
    data,
    phases: list,
    workdir: str | Path,
    *,
    stem: str = "polyxrd",
    on_log: Optional[Callable[[str], None]] = None,
) -> subprocess.Popen:
    """导出输入文件并拉起 GSAS-II 主 GUI (非阻塞)。

    Raises:
        RuntimeError: GSAS-II 未安装或 GUI 入口缺失。
    """
    log = on_log or (lambda _m: None)
    py, g2 = find_gsas2_gui_entry()
    if py is None:
        raise RuntimeError("未找到 GSAS-II 安装, 请在设置中配置路径")
    if g2 is None:
        raise RuntimeError("GSAS-II 源码目录缺少 GUI 入口 (G2.py)")

    xy_path, cif_paths = export_inputs(data, phases, workdir, stem=stem)
    log(f"[gsas2] export: {xy_path.name} + {len(cif_paths)} CIF")
    log(f"[gsas2] launch GSAS-II GUI: {py.name} {g2.name}")

    try:
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        env = RietveldRefiner._gsas2_env(py)
    except Exception:  # noqa: BLE001
        env = os.environ.copy()
    kwargs: dict = {"cwd": str(workdir), "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    return subprocess.Popen([str(py), str(g2)], **kwargs)
