"""物相 → CIF 导出服务 (v0.15.0 M23)
==================================

把「已勾选物相」导出为 CIF 文件。取文顺序:

1. ``phase.cif_path`` 指向磁盘真实文件 → 直接读;
2. 无 CIF 文件但有原子位点 → 由位点反生成 (v4.1.1; polyDB / PDF2 候选);
3. 条目号落在用户库号段 (≥ 9 亿) → 读 ``user_phases.sqlite`` 的 ``cif_gz``;
4. 全部失败 → ``CifUnavailableError`` (UI 层弹「未找到该物相的 CIF」)。

v4.2 变更
---------
旧版第 2–3 步是"按 COD 编号走旧本地库的五级回退 / 按化学式在 COD
库里找结构候选再取文"。该库已从发布包移除, 两个分支在 v4.2 删除 —— 现在
所有检索库的候选要么自带 cif_path, 要么自带晶胞+位点可反生成, 覆盖完整。

纯逻辑、无 Qt 依赖, 便于离屏单测。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from polyxrd.models.phase import Phase
from polyxrd.services.phase_structure_resolver import extract_cod_id

__all__ = [
    "CifUnavailableError",
    "export_phase_cif",
    "get_phase_cif_text",
    "resolve_cod_id",
]


class CifUnavailableError(RuntimeError):
    """无法为该物相取到 CIF 文本 (本地无文件、库内无结构)。"""


def resolve_cod_id(phase: Phase) -> Optional[int]:
    """从物相里尽力解析库条目编号: 显式 db_id / 名字 / 化学式 / cif_path 文件名。"""
    db_id = getattr(phase, "db_id", None)
    if isinstance(db_id, int):
        return db_id
    cod_id = extract_cod_id(
        getattr(phase, "name", "") or "", getattr(phase, "formula", "") or ""
    )
    if cod_id:
        return cod_id
    cif_path = getattr(phase, "cif_path", None)
    if cif_path:
        stem = Path(cif_path).stem
        if stem.isdigit():
            return int(stem)
        m = re.match(r"^COD(\d{5,8})$", stem, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def get_phase_cif_text(phase: Phase) -> tuple[str, Optional[int]]:
    """取物相 CIF 文本。成功返回 ``(cif_text, cod_id|None)``, 失败抛
    ``CifUnavailableError``。"""
    # 1) 磁盘上的 cif_path
    cif_path = getattr(phase, "cif_path", None)
    if cif_path and Path(cif_path).exists():
        try:
            text = Path(cif_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if text.strip():
            return text, resolve_cod_id(phase)

    # 1b) 无 CIF 文件但有原子位点 → 由位点反生成 (v4.1.1)
    #     polyDB / PDF2 / 用户库候选都是这种形态。
    if getattr(phase, "atomic_sites", None) and getattr(phase, "lattice", None):
        try:
            from polyxrd.services.phase_cif import phase_to_cif_text

            text = phase_to_cif_text(phase)
            if text.strip():
                return text, resolve_cod_id(phase)
        except Exception:  # noqa: BLE001 - 反生成失败走用户库/抛错
            pass

    # 2) 用户库条目 (9 亿段 ID) 的 CIF 存在 user_phases.sqlite 的 cif_gz 里
    cod_id = resolve_cod_id(phase)
    if cod_id is not None and cod_id >= 900_000_000:
        try:
            from polyxrd.services import user_db

            text = user_db.get_user_cif(cod_id)
        except Exception:  # noqa: BLE001
            text = None
        if text and text.strip():
            return text, cod_id

    name = getattr(phase, "name", "") or getattr(phase, "formula", "") or "?"
    raise CifUnavailableError(f"未找到物相「{name}」的 CIF (可联网后重试)")


def export_phase_cif(phase: Phase, out_path: str | Path) -> Path:
    """把单个物相的 CIF 写到 ``out_path``, 返回落盘路径。"""
    text, _cod_id = get_phase_cif_text(phase)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def default_cif_filename(phase: Phase, cod_id: Optional[int] = None) -> str:
    """导出默认文件名: ``{mineral}_{cod_id}.cif`` (去掉非法字符)。"""
    name = (getattr(phase, "name", "") or getattr(phase, "formula", "") or "phase")
    stem = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "phase"
    if cod_id:
        return f"{stem}_{cod_id}.cif"
    return f"{stem}.cif"
