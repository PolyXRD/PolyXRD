"""物相 → CIF 导出服务 (v0.15.0 M23)
==================================

把「已勾选物相」导出为 CIF 文件。取文顺序:

1. ``phase.cif_path`` 指向磁盘真实文件 → 直接读;
2. 名字 / cif_path 文件名里的 COD 编号 → ``CODLocalDatabase.get_cif()``
   (五级回退: 本地 cod/cif 目录 → 全库 BLOB → 无机库 BLOB → tar → COD REST);
3. 化学式 (+ 矿物名) 在 COD 库里找结构候选, 按空间群一致 + 晶胞接近度
   排序 (复用精修 resolver 的打分), 逐个尝试取文;
4. 全部失败 → ``CifUnavailableError`` (UI 层弹「未找到该物相的 CIF」)。

纯逻辑、无 Qt 依赖, 便于离屏单测; 瘦身索引库 (cif_gz 全 NULL) 场景
由 ``cod_local.get_cif`` 的外部 cif/ 目录回退兜底。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from polyxrd.models.phase import Phase
from polyxrd.services.phase_structure_resolver import (
    PhaseStructureResolver,
    _candidate_score,
    extract_cod_id,
)
from polyxrd.utils.formula_parser import normalize_cod_formula

_clean_mineral = PhaseStructureResolver._clean_mineral

__all__ = [
    "CifUnavailableError",
    "export_phase_cif",
    "get_phase_cif_text",
    "resolve_cod_id",
]


class CifUnavailableError(RuntimeError):
    """无法为该物相取到 CIF 文本 (本地无文件、库内无结构)。"""


def _cod_db():
    """惰性拿 CODLocalDatabase; 库不可用返回 None (不抛)。"""
    try:
        from polyxrd.services.cod_local import CODLocalDatabase

        db = CODLocalDatabase()
        if db.is_ready() or db._inorg_db() is not None:
            return db
    except Exception:  # noqa: BLE001
        pass
    return None


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


def _find_cod_id_by_formula(phase: Phase) -> Optional[int]:
    """按规范化化学式 (+矿物名) 在 COD 库找有 CIF 的候选, 返回第一个 cod_id。"""
    formula = normalize_cod_formula(getattr(phase, "formula", "") or "")
    mineral = _clean_mineral(getattr(phase, "name", "") or "")
    if not formula and not mineral:
        return None
    db = _cod_db()
    if db is None:
        return None
    try:
        cands = db.find_structure_candidates(formula, mineral_name=mineral)
    except Exception:  # noqa: BLE001
        return None
    cands.sort(key=lambda c: _candidate_score(c, phase))
    for cand in cands[:3]:
        try:
            cid = int(cand["cod_id"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            if db.get_cif(cid):
                return cid
        except Exception:  # noqa: BLE001
            continue
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

    db = _cod_db()

    # 2) 库编号直取 (五级回退)。用户库条目 (9 亿段 ID) 的 CIF 存在
    #    user_phases.sqlite 的 cif_gz 里, 与 COD 库不互通, 单独走一支。
    cod_id = resolve_cod_id(phase)
    if cod_id is not None and cod_id >= 900_000_000:
        try:
            from polyxrd.services import user_db

            text = user_db.get_user_cif(cod_id)
        except Exception:  # noqa: BLE001
            text = None
        if text and text.strip():
            return text, cod_id
    if cod_id is not None and db is not None:
        try:
            text = db.get_cif(cod_id)
        except Exception:  # noqa: BLE001
            text = None
        if text and text.strip():
            return text, cod_id

    # 3) 化学式匹配
    matched = _find_cod_id_by_formula(phase)
    if matched is not None and db is not None:
        try:
            text = db.get_cif(matched)
        except Exception:  # noqa: BLE001
            text = None
        if text and text.strip():
            return text, matched

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
