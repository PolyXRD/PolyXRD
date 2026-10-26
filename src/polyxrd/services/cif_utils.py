"""纯 CIF 文本解析工具（v4.2 结构清理，从 ``cod_local.py`` 抽取）。

约束（P1.1）
------------
- **不得** import ``sqlite3``、**不得** import PySide6、**不得**读配置路径；
- 只做 CIF 文本 ↔ 通用字段/位点 的解析与化学式归一；
- 函数体逐字沿用旧 ``cod_local`` 实现，保证口径零漂移；
- 依赖的 ``polyxrd.utils.formula_parser`` 为纯计算工具（与旧模块顶层导入一致）。

删除说明
--------
旧 ``cod_local`` 中与数据库连接相关的能力（``formula_sum_from_inorg_cif`` /
``recover_inorg_formula`` 的 CIF 回退 / 旧本地库类 取相-取CIF / 索引器）属旧 sqlite
专用，随旧模块在 v4.2.0 删除，不迁入本模块（见 ``docs/v4.2-结构清理方案.md`` §3.1）。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from polyxrd.utils.formula_parser import elements_from_db_formula, normalize_cod_formula

log = logging.getLogger("polyxrd.cif_utils")

_RE_FLOAT = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_ELEMENT_RE = re.compile(r"([A-Z][a-z]?)\s*(\d*\.?\d*)")


# ── 字段清洗 ──────────────────────────────────────────────────
def _clean_elem_symbol(sym) -> str:
    """清洗元素符号: 'W+' -> 'W', 'Sn4+' -> 'Sn', 'O-' -> 'O'."""
    m = re.match(r"[A-Z][a-z]?", str(sym or "").strip())
    return m.group(0) if m else str(sym or "").strip()


def _cif_num(v) -> Optional[float]:
    """CIF 数值解析: 剥离不确定度 '0.144(10)' -> 0.144; '.'/'?' -> None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"\([^)]*\)", "", str(v).strip())
    if s in ("", ".", "?"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── 数据类 ────────────────────────────────────────────────────
@dataclass
class CODLocalEntry:
    """CIF 条目（轻量解析结果）。

    字段名与旧 ``cod_local.CODLocalEntry`` 完全一致，便于调用方无感迁移。
    """

    cod_id: int = 0
    file: str = ""
    mineral_name: str = ""
    formula: str = ""
    formula_red: str = ""
    elements: str = ""
    space_group: str = ""
    space_group_number: int = 0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0
    volume: float = 0.0
    z_value: int = 0
    last_updated: int = 0
    parse_ok: int = 1


# 迁移期别名（方案 §3.1：``CODLocalEntry`` 可改名 ``CIFEntry``，保留别名一版）
CIFEntry = CODLocalEntry


# ── 快速解析（正则，避免 pymatgen 开销） ──────────────────────
def _parse_val(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = text.split("(", 1)[0].strip().strip("'\"")
    m = _RE_FLOAT.search(cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_int(text: str) -> Optional[int]:
    if not text:
        return None
    cleaned = text.split("(", 1)[0].strip().strip("'\"")
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _extract_field(content: str, tags: Sequence[str]) -> Optional[str]:
    """CIF 中 ``_tag_name`` 后面的值（支持单引号 / 行续）。"""
    for tag in tags:
        pat = re.compile(
            rf"^{re.escape(tag)}\s+('(?:[^']|'')*'|[^\r\n]+)",
            re.MULTILINE,
        )
        m = pat.search(content)
        if m:
            val = m.group(1).strip()
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1].replace("''", "'")
            if val and val != "?" and val != ".":
                return val
    return None


def formula_sum_from_cif(cif_text: str) -> str:
    """从 CIF 全文抽 ``_chemical_formula_sum`` 并归一到库内 formula 写法。

    CIF 缺该标签或解析失败返回 ``""``。
    """
    raw = _extract_field(cif_text or "", ("_chemical_formula_sum",))
    if not raw:
        return ""
    try:
        return normalize_cod_formula(raw)
    except Exception:  # noqa: BLE001 - 归一化不该把调用方拖崩
        return ""


def is_db_formula_trusted(formula: str, space_group: str = "") -> bool:
    """库内 ``formula`` 是否可作为化学判据（空 / 与空间群同串 / 解析不出元素 → 不可信）。"""
    f = (formula or "").strip()
    if not f:
        return False
    if space_group and f == space_group.strip():
        return False
    return bool(elements_from_db_formula(f))


def _parse_elements(formula_sum: str) -> tuple[str, str]:
    """解析 ``_chemical_formula_sum`` 风格串，返回 (归一式, 元素 CSV)。"""
    if not formula_sum:
        return "", ""
    counts: dict[str, float] = {}
    for elem, cnt in _ELEMENT_RE.findall(formula_sum):
        if not elem:
            continue
        try:
            counts[elem] = counts.get(elem, 0.0) + (float(cnt) if cnt else 1.0)
        except ValueError:
            continue
    if not counts:
        return "", ""
    keys = sorted(counts.keys())
    formula_red = "".join(
        k + (str(int(round(v))) if (v := counts[k]) != 1.0 and abs(v - round(v)) < 0.05
                else ("" if v == 1 else f"{v:g}"))
        for k in keys
    )
    element_csv = ",".join(keys)
    return formula_red, element_csv


def _cell_volume(a: float, b: float, c: float,
                 alpha_deg: float, beta_deg: float, gamma_deg: float) -> float:
    """通用三斜晶胞体积（Å³）；缺参数返回 0.0。"""
    a_r = math.radians(alpha_deg)
    b_r = math.radians(beta_deg)
    g_r = math.radians(gamma_deg)
    ca, cb, cg = math.cos(a_r), math.cos(b_r), math.cos(g_r)
    return float(a * b * c * math.sqrt(
        1 - ca * ca - cb * cb - cg * cg + 2 * ca * cb * cg
    )) if (a and b and c) else 0.0


def parse_cif_text(text: str, file_rel: str = "", cod_id: int = 0,
                   mtime: int = 0) -> CODLocalEntry:
    """把 CIF 文本解析为 :class:`CODLocalEntry`（快速、正则实现）。

    与旧 ``cod_local.parse_cif_text`` 逐字一致。
    """
    try:
        if not cod_id:
            stem = Path(file_rel).stem if file_rel else ""
            digits = re.match(r"(\d+)", stem)
            if digits:
                cod_id = int(digits.group(1))

        formula = _extract_field(text, (
            "_chemical_formula_sum", "_chemical_formula_analytical",
            "_chemical_formula_structural", "_chemical_formula_moiety",
        )) or ""

        mineral_name = _extract_field(text, (
            "_chemical_name_mineral", "_chemical_name_common",
            "_chemical_name_systematic",
        )) or ""

        if not mineral_name:
            m = re.search(r"^data_([^\s]+)", text, re.MULTILINE)
            if m:
                mineral_name = m.group(1).replace("_", " ")[:120]

        sg = _extract_field(text, (
            "_symmetry_space_group_name_H-M",
            "_space_group_name_H-M_alt",
        )) or ""
        sg_num = _parse_int(_extract_field(text, (
            "_symmetry_Int_Tables_number",
            "_space_group_IT_number",
        )) or "") or 0

        a = _parse_val(_extract_field(text, ("_cell_length_a",))) or 0.0
        b = _parse_val(_extract_field(text, ("_cell_length_b",))) or 0.0
        c = _parse_val(_extract_field(text, ("_cell_length_c",))) or 0.0
        alpha = _parse_val(_extract_field(text, ("_cell_angle_alpha",))) or 90.0
        beta = _parse_val(_extract_field(text, ("_cell_angle_beta",))) or 90.0
        gamma = _parse_val(_extract_field(text, ("_cell_angle_gamma",))) or 90.0
        vol = _parse_val(_extract_field(text, ("_cell_volume",))) or 0.0
        if not vol and a and b and c:
            vol = _cell_volume(a, b, c, alpha, beta, gamma)
        z = _parse_int(_extract_field(text, ("_cell_formula_units_Z",))) or 0

        formula_red, elements = _parse_elements(formula)

        parse_ok = int(bool(a and b and c and formula))
        return CODLocalEntry(
            cod_id=cod_id,
            file=file_rel,
            mineral_name=mineral_name,
            formula=formula,
            formula_red=formula_red,
            elements=elements,
            space_group=sg,
            space_group_number=sg_num,
            a=a, b=b, c=c,
            alpha=alpha, beta=beta, gamma=gamma,
            volume=vol,
            z_value=z,
            last_updated=mtime,
            parse_ok=parse_ok,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("parse_cif_text failed on %s: %s", file_rel, e)
        return CODLocalEntry(cod_id=cod_id, file=file_rel,
                             last_updated=mtime, parse_ok=0)


def parse_cif_light(cif_path: Path) -> CODLocalEntry:
    """解析单个 CIF 文件为 :class:`CODLocalEntry`（读文件 + 元数据）。"""
    cod_id = 0
    file_rel = ""
    try:
        stem = cif_path.stem
        digits = re.match(r"(\d+)", stem)
        if digits:
            cod_id = int(digits.group(1))
        try:
            parts = cif_path.parts
            if "cod" in parts:
                idx = parts.index("cod")
                file_rel = "/".join(parts[idx + 1:])
            else:
                file_rel = cif_path.name
        except Exception:  # noqa: BLE001
            file_rel = cif_path.name

        stat = cif_path.stat()
        mtime = int(stat.st_mtime)

        try:
            text = cif_path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return CODLocalEntry(cod_id=cod_id, file=file_rel, last_updated=mtime, parse_ok=0)

        return parse_cif_text(text, file_rel=file_rel, cod_id=cod_id, mtime=mtime)
    except Exception as e:  # noqa: BLE001
        log.debug("parse_cif_light failed on %s: %s", cif_path, e)
        return CODLocalEntry(cod_id=cod_id, file=file_rel, last_updated=0, parse_ok=0)


def parse_atom_sites_from_cif(text: str) -> list[dict]:
    """从 CIF 文本提取原子位点（``loop_ _atom_site_*``）。

    返回 ``[{"label", "element", "x", "y", "z", "occupancy", "u_iso", "u_iso_default"}]``。
    与旧 ``cod_local.parse_atom_sites_from_cif`` 逐字一致（含 U_iso/B_iso 折算与默认值规则）。
    """
    sites: list[dict] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        s = lines[i].strip()
        if s.startswith("loop_") and i + 1 < n:
            j = i + 1
            col_names: list[str] = []
            while j < n and lines[j].strip().startswith("_atom_site_"):
                col_names.append(lines[j].strip())
                j += 1
            if any("_atom_site_fract_x" in c for c in col_names):
                col_map = {name: idx for idx, name in enumerate(col_names)}
                while j < n:
                    ds = lines[j].strip()
                    if ds.startswith("_") or ds.startswith("loop_") or not ds or ds.startswith("#"):
                        break
                    parts = ds.split()
                    if len(parts) < len(col_names):
                        j += 1
                        continue
                    try:
                        xi = col_map.get("_atom_site_fract_x")
                        yi = col_map.get("_atom_site_fract_y")
                        zi = col_map.get("_atom_site_fract_z")
                        if xi is None or yi is None or zi is None:
                            j += 1
                            continue
                        x = float(parts[xi].split("(")[0])
                        y = float(parts[yi].split("(")[0])
                        z = float(parts[zi].split("(")[0])
                        ei = col_map.get("_atom_site_type_symbol")
                        if ei is not None and ei < len(parts):
                            elem = parts[ei]
                        else:
                            li2 = col_map.get("_atom_site_label")
                            elem = parts[li2] if li2 is not None and li2 < len(parts) else ""
                            m = re.match(r"([A-Z][a-z]?)", elem)
                            elem = m.group(1) if m else elem
                        oi = col_map.get("_atom_site_occupancy")
                        occ = 1.0
                        if oi is not None and oi < len(parts):
                            try:
                                occ = float(parts[oi].split("(")[0])
                            except (ValueError, IndexError):
                                occ = 1.0
                        li2 = col_map.get("_atom_site_label")
                        label = parts[li2] if li2 is not None and li2 < len(parts) else f"{elem}{len(sites) + 1}"
                        _ui = col_map.get("_atom_site_U_iso_or_equiv")
                        _bi = col_map.get("_atom_site_B_iso_or_equiv")
                        u_val = None
                        try:
                            if _ui is not None and _ui < len(parts):
                                u_val = float(parts[_ui].split("(")[0])
                            elif _bi is not None and _bi < len(parts):
                                u_val = float(parts[_bi].split("(")[0]) / (8.0 * math.pi ** 2)
                        except (ValueError, IndexError):
                            u_val = None
                        u_def = u_val is None
                        if u_val is None:
                            u_val = 0.005
                        sites.append({
                            "label": label,
                            "element": elem,
                            "x": x, "y": y, "z": z,
                            "occupancy": occ,
                            "u_iso": float(u_val),
                            "u_iso_default": bool(u_def),
                        })
                    except (ValueError, IndexError):
                        pass
                    j += 1
                i = j
                continue
        i += 1

    return sites
