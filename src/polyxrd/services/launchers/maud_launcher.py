"""MAUD GUI 启动器 (v0.15 M25-4)
=================================

降级语义: 批处理精修走 :class:`polyxrd.services.refinement_engines.maud_engine.MaudEngine`
(路线 A/B/C 已验证); 本启动器只做「导出 + 拉起」— 把实验谱 (.xye) 与
物相 CIF 导出到工作目录后, 用 MAUD 自带 JDK 拉起 MAUD GUI, 由用户在
GUI 中继续操作。

- MAUD 安装定位复用 ``maud_par_builder.detect_maud_root``;
- java 命令拼装沿用 ``build_maud_command`` 的 classpath/JVM 约定
  (lib/* glob + Java.library.path), GUI 主类为 ``com.radiographema.Maud``。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

__all__ = ["export_inputs", "build_gui_command", "launch_gui"]


def export_inputs(
    data,
    phases: list,
    workdir: str | Path,
    *,
    stem: str = "polyxrd",
) -> tuple[Path, list[Path]]:
    """导出实验谱 ``{stem}.xye`` 与各物相 CIF 到工作目录。

    Returns:
        ``(xye_path, cif_paths)``
    """
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)

    from polyxrd.services.refinement_engines.maud_engine import (
        _format_xrd_data_as_xye,
    )

    xye_path = _format_xrd_data_as_xye(data, wd / f"{stem}.xye")

    cif_paths: list[Path] = []
    try:
        from polyxrd.services.phase_cif_export import (
            default_cif_filename,
            get_phase_cif_text,
        )
    except Exception:  # noqa: BLE001
        return xye_path, cif_paths

    for idx, ph in enumerate(phases, start=1):
        try:
            text, cod_id = get_phase_cif_text(ph)
            name = default_cif_filename(ph, cod_id)
            out = wd / f"{idx:02d}_{name}"
            out.write_text(text, encoding="utf-8")
            cif_paths.append(out)
        except Exception:  # noqa: BLE001 — 单个相拿不到 CIF 时跳过
            continue
    return xye_path, cif_paths


def build_gui_command(maud_root: Path, max_memory_mb: int = 4096) -> list[str]:
    """拼出 MAUD GUI 启动命令 (与批处理同 classpath, GUI 主类)。"""
    java_exe = maud_root / "jdk" / "bin" / "java.exe"
    if not java_exe.exists():
        raise FileNotFoundError(f"找不到 java.exe: {java_exe}")
    lib_dir = maud_root / "lib"
    if not lib_dir.is_dir():
        raise FileNotFoundError(f"找不到 lib 目录: {lib_dir}")
    classpath = f"{lib_dir}{__import__('os').sep}*"
    return [
        str(java_exe),
        f"-Xmx{max_memory_mb}M",
        f"-DJava.library.path={maud_root}",
        "-cp", classpath,
        "com.radiographema.Maud",
    ]


def resolve_maud_root(custom: Optional[str] = None) -> Path:
    """解析 MAUD 根目录: 用户配置 (maud.bat / 根目录 / java.exe) → 自动探测。"""
    if custom:
        p = Path(custom)
        if p.name.lower() == "maud.bat" and p.exists():
            return p.parent              # maud.bat → 根
        if p.name.lower() == "java.exe" and p.exists():
            return p.parents[2]          # jdk/bin/java.exe → 根
        if (p / "jdk" / "bin" / "java.exe").exists():
            return p
    from polyxrd.services.maud_par_builder import detect_maud_root

    return detect_maud_root()


def launch_gui(
    data,
    phases: list,
    workdir: str | Path,
    *,
    stem: str = "polyxrd",
    custom: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> subprocess.Popen:
    """导出输入文件并拉起 MAUD GUI (非阻塞)。

    Raises:
        RuntimeError: MAUD 未安装或安装不完整。
    """
    log = on_log or (lambda _m: None)
    try:
        maud_root = resolve_maud_root(custom)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"未找到 MAUD 安装: {exc}") from exc

    xy_path, cif_paths = export_inputs(data, phases, workdir, stem=stem)
    log(f"[maud] export: {xy_path.name} + {len(cif_paths)} CIF")

    # v0.15.1: 默认走官方 maud.bat (与用户双击启动行为一致), 无 bat 才拼 java 命令
    bat = maud_root / "maud.bat"
    if bat.exists():
        cmd = [str(bat)]
        log(f"[maud] launch MAUD GUI: {bat}")
    else:
        cmd = build_gui_command(maud_root)
        log(f"[maud] launch MAUD GUI: {maud_root.name}")
    kwargs: dict = {"cwd": str(workdir)}
    import os

    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    return subprocess.Popen(cmd, **kwargs)
