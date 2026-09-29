"""
COD 本地 CIF 数据库服务
==========================

基于 rsync / txz 压缩包下载的 COD CIF 文件，构建并维护本地 SQLite 索引，
支持按化学式、元素、空间群、晶胞参数快速检索，以及物相识别和精修调用。

目录结构:
    AppConfig.cif_db_path /
        cod/                     <- COD CIF 文件根目录 (92 GB)
            00/ ..., 01/ ..., 99/ ...
        cod_index.sqlite         <- 索引数据库 (~500 MB)
        cod_sync.log             <- 同步日志

用法:
    indexer = CODLocalIndexer()
    indexer.build_index()   # 首次 / 增量构建

    db = CODLocalDatabase()
    entries = db.search(formula="SiO2")          # 按化学式
    entries = db.search_by_elements(["Si", "O"]) # 按元素组成
    entry = db.get_entry(72154)                  # 按 COD ID
    cif_text = db.get_cif(entry.cod_id)          # 取 CIF 内容
    phase = db.get_phase(entry.cod_id)           # 取 Phase 模型对象

参考经验:
    - SQLite 写入用批量事务 (executemany + 每 N 行 commit)
    - 大规模文件扫描用 Path.rglob + 多进程/多线程解析，避免内存爆炸
    - 打包后数据库写到用户目录 (AppData / ~/.polyxrd)，不作为 datas 必带资源
"""
from __future__ import annotations

import json
import gzip
import logging
import math
import re
import shutil
import sqlite3
import sys
import tarfile
import threading
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional, Sequence

from polyxrd.config import AppConfig, get_config
from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.utils.formula_parser import normalize_cod_formula

log = logging.getLogger("polyxrd.cod_local")

# ── 数据库 schema 版本，升级时递增并提供迁移 ────────────────
SCHEMA_VERSION = 1
BATCH_INSERT_SIZE = 5000
PARSE_WORKERS = 8  # 并行解析 CIF 数 (I/O 为主，设 CPU 数 2x 以内)


# ── CIF 字段清洗辅助 (v0.11.0) ────────────────────────────────
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


# ── 数据类 ──────────────────────────────────────────────────

@dataclass
class CODLocalEntry:
    """本地 COD 条目 (轻量检索结果)

    Attributes:
        cod_id: COD 数据库编号，文件名即 {cod_id}.cif
        file: 相对于 cod/ 目录的路径，如 "90/00/9000127.cif"
        mineral_name: 矿物名 / 标题 (从 data_ 行或 _chemical_name_mineral)
        formula: 化学式 sum，如 "Si O2"
        formula_red: 归一化分子式 (消空格、元素排序，便于搜索去重)
        elements: 元素列表 (逗号分隔，便于 LIKE 搜索)，如 "O,Si"
        space_group: 空间群 H-M 符号，如 "F d -3 m"
        space_group_number: 空间群编号 (1-230)，无则 0
        a, b, c, alpha, beta, gamma: 晶胞参数
        volume: 晶胞体积 (Å³)，无则 0.0
        z_value: 化学式单位数 Z，无则 0
        last_updated: 最后修改时间 (unix epoch)
        parse_ok: 1=成功解析核心字段，0=CIF 损坏/缺失关键字段
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


# ── CIF 快速解析 (用正则，避免 pymatgen 开销) ────────────────

_RE_FLOAT = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# 捕获带误差标记的值, e.g. 1.2345(6) -> 1.2345
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
    """CIF 中 _tag_name 后面的值 (支持单引号/行续)"""
    for tag in tags:
        # tag 后紧跟值 (可能引号包裹)
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


_ELEMENT_RE = re.compile(r"([A-Z][a-z]?)\s*(\d*\.?\d*)")


def formula_sum_from_cif(cif_text: str) -> str:
    """从 CIF 全文抽 ``_chemical_formula_sum`` 并归一到库内 formula 写法。

    这是「用 CIF 补/修化学式」的**单点实现** —— `cif_database.get_cod_phase`
    的公式回退与 `scripts/migrate_inorg_formula.py` 都从这里取, 勿在调用方
    各自写正则。

    用途背景: COD 无机物库有 605 条 ``phases.formula`` 被写成了空间群符号
    (如 ``P 63 m c``), 而内嵌 CIF 里的 ``_chemical_formula_sum`` 是好的。

    Returns:
        归一化后的化学式 (如 ``"O Zn"``); CIF 缺该标签或解析失败返回 ``""``。
    """
    raw = _extract_field(cif_text or "", ("_chemical_formula_sum",))
    if not raw:
        return ""
    try:
        return normalize_cod_formula(raw)
    except Exception:  # noqa: BLE001 - 归一化不该把调用方拖崩
        return ""


def formula_sum_from_inorg_cif(conn: sqlite3.Connection, cod_id: int) -> str:
    """从「COD 无机物库」某条的内嵌 ``cif_gz`` 恢复化学式。

    给 ``cif_database.get_cod_phase`` 的公式回退用 (它只持有无机库连接,
    不便自己处理 gzip / 列缺失)。**老版或外部导入的无机库可能没有
    cif_gz 列**, 或该条没有内嵌 CIF → 一律返回 ``""``, 由调用方保留原值。

    单点实现: 化学式的抽取与归一化都走 :func:`formula_sum_from_cif`。
    """
    try:
        row = conn.execute(
            "SELECT cif_gz FROM phases WHERE cod_id = ?", (cod_id,)
        ).fetchone()
        blob = row["cif_gz"] if row is not None else None
        if not blob:
            return ""
        text = gzip.decompress(blob).decode("utf-8", errors="replace")
        return formula_sum_from_cif(text)
    except Exception as e:  # noqa: BLE001 - 缺列/坏 BLOB 都不该影响主流程
        log.debug("inorg cif formula recovery failed for %s: %s", cod_id, e)
        return ""


def is_db_formula_trusted(formula: str, space_group: str = "") -> bool:
    """库内 ``formula`` 是否可作为化学判据 (单点实现)。

    不可信 = 三者任一: 空串 / 与空间群符号完全相同 / 解析不出任何元素。
    实测 COD 无机物库 71,199 条里有 609 条不可信 (605 条 ``formula`` 被
    写成了 ``P 63 m c`` 这类空间群记号), 是建库脚本的字段提取 bug。

    用途: (a) 迁移脚本判断是否改写; (b) 运行时判断是否需要走 CIF 回退;
    (c) 扫描层判断是否该放行 (不可信时不参与 ``issubset`` 淘汰, 见
    ``cif_database.search_cod_by_d_peaks``)。
    """
    f = (formula or "").strip()
    if not f:
        return False
    if space_group and f == space_group.strip():
        return False
    from polyxrd.utils.formula_parser import elements_from_db_formula

    return bool(elements_from_db_formula(f))


def recover_inorg_formula(
    conn: sqlite3.Connection, cod_id: int, formula: str, space_group: str = ""
) -> str:
    """库内 ``formula`` 不可信时, 回退到内嵌 CIF 的化学式; 否则原样返回。

    回退失败 (无可信值/库无 cif_gz 列/该条无内嵌 CIF) 一律**返回原值**,
    绝不返回空串 —— 调用方直接把它当 ``formula`` 用。
    """
    f = (formula or "").strip()
    if is_db_formula_trusted(f, space_group):
        return f
    return formula_sum_from_inorg_cif(conn, cod_id) or f


def _parse_elements(formula_sum: str) -> tuple[str, str]:
    """Parse _chemical_formula_sum-style string like 'Si1 O2' or 'Si O2'
    Returns (normalized "O2Si1", element_csv "O,Si") with element alphabetical order.
    """
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
    # Round counts to integers if close enough for formula (COD often uses floats)
    keys = sorted(counts.keys())
    formula_red = "".join(
        k + (str(int(round(v))) if (v := counts[k]) != 1.0 and abs(v - round(v)) < 0.05
                else ("" if v == 1 else f"{v:g}"))
        for k in keys
    )
    element_csv = ",".join(keys)
    return formula_red, element_csv


# 计算晶胞体积 (通用三斜公式)
def _cell_volume(a: float, b: float, c: float,
                 alpha_deg: float, beta_deg: float, gamma_deg: float) -> float:
    import math
    a_r = math.radians(alpha_deg)
    b_r = math.radians(beta_deg)
    g_r = math.radians(gamma_deg)
    ca, cb, cg = math.cos(a_r), math.cos(b_r), math.cos(g_r)
    return float(a * b * c * math.sqrt(
        1 - ca*ca - cb*cb - cg*cg + 2 * ca * cb * cg
    )) if (a and b and c) else 0.0


def parse_cif_text(text: str, file_rel: str = "", cod_id: int = 0,
                   mtime: int = 0) -> CODLocalEntry:
    """Parse CIF text content into a CODLocalEntry (fast, regex-based).

    This is the core parser used by both file-based and tar-based indexing.
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
    except Exception as e:
        log.debug("parse_cif_text failed on %s: %s", file_rel, e)
        return CODLocalEntry(cod_id=cod_id, file=file_rel,
                             last_updated=mtime or int(time.time()), parse_ok=0)


def parse_cif_light(cif_path: Path) -> CODLocalEntry:
    """Parse a single CIF file into a CODLocalEntry (fast, regex-based).

    Wrapper around parse_cif_text that reads the file and computes metadata.
    """
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
                file_rel = "/".join(parts[idx+1:])
            else:
                file_rel = cif_path.name
        except Exception:
            file_rel = cif_path.name

        stat = cif_path.stat()
        mtime = int(stat.st_mtime)

        try:
            text = cif_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return CODLocalEntry(cod_id=cod_id, file=file_rel, last_updated=mtime, parse_ok=0)

        return parse_cif_text(text, file_rel=file_rel, cod_id=cod_id, mtime=mtime)
    except Exception as e:
        log.debug("parse_cif_light failed on %s: %s", cif_path, e)
        return CODLocalEntry(cod_id=cod_id, file=file_rel, last_updated=int(time.time()), parse_ok=0)


# ── CIF 原子位点解析 ─────────────────────────────────────────

def parse_atom_sites_from_cif(text: str) -> list[dict]:
    """从 CIF 文本提取原子位点 (loop_ _atom_site_*)。

    返回 [{"label": ..., "element": ..., "x": float, "y": float, "z": float, "occupancy": float}, ...]
    """
    sites: list[dict] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        s = lines[i].strip()
        if s.startswith("loop_") and i + 1 < n:
            # 读取后续 _atom_site_ 列定义
            j = i + 1
            col_names: list[str] = []
            while j < n and lines[j].strip().startswith("_atom_site_"):
                col_names.append(lines[j].strip())
                j += 1
            # 检查是否包含 fract_x (排除 aniso 等其他 _atom_site_ loop)
            if any("_atom_site_fract_x" in c for c in col_names):
                col_map = {name: idx for idx, name in enumerate(col_names)}
                # j 现在指向第一行数据
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
                        # element
                        ei = col_map.get("_atom_site_type_symbol")
                        if ei is not None and ei < len(parts):
                            elem = parts[ei]
                        else:
                            li2 = col_map.get("_atom_site_label")
                            elem = parts[li2] if li2 is not None and li2 < len(parts) else ""
                            m = re.match(r"([A-Z][a-z]?)", elem)
                            elem = m.group(1) if m else elem
                        # occupancy
                        oi = col_map.get("_atom_site_occupancy")
                        occ = 1.0
                        if oi is not None and oi < len(parts):
                            try:
                                occ = float(parts[oi].split("(")[0])
                            except (ValueError, IndexError):
                                occ = 1.0
                        # label
                        li2 = col_map.get("_atom_site_label")
                        label = parts[li2] if li2 is not None and li2 < len(parts) else f"{elem}{len(sites)+1}"
                        # ── v1.1.2 (W21): 解析 ADP ──────────────────────────
                        # U_iso_or_equiv 优先; 否则 B_iso_or_equiv/(8π²) (B = 8π²U);
                        # 两者都缺 → 0.005 Å² 并标 u_iso_default。与
                        # cif_database._extract_atomic_sites 保持同一规则。
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
                # 跳到 j 之后继续搜索 (可能有多个 atom_site loop)
                i = j
                continue
        i += 1

    return sites


# ── SQLite 连接/表结构 ────────────────────────────────────────

_SCHEMA_SQL = f"""
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -65536;    -- 64 MB cache
PRAGMA temp_store = MEMORY;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS cod_entries (
    cod_id        INTEGER PRIMARY KEY,
    file          TEXT NOT NULL,
    mineral_name  TEXT,
    formula       TEXT,
    formula_red   TEXT,
    elements      TEXT,
    space_group   TEXT,
    space_group_number INTEGER DEFAULT 0,
    a             REAL DEFAULT 0,
    b             REAL DEFAULT 0,
    c             REAL DEFAULT 0,
    alpha         REAL DEFAULT 90,
    beta          REAL DEFAULT 90,
    gamma         REAL DEFAULT 90,
    volume        REAL DEFAULT 0,
    z_value       INTEGER DEFAULT 0,
    last_updated  INTEGER DEFAULT 0,
    parse_ok      INTEGER DEFAULT 1,
    cif_gz        BLOB
);

CREATE INDEX IF NOT EXISTS idx_formula_red   ON cod_entries(formula_red);
CREATE INDEX IF NOT EXISTS idx_elements      ON cod_entries(elements);
CREATE INDEX IF NOT EXISTS idx_sg_number     ON cod_entries(space_group_number);
CREATE INDEX IF NOT EXISTS idx_sg_name       ON cod_entries(space_group);
CREATE INDEX IF NOT EXISTS idx_volume        ON cod_entries(volume);
CREATE INDEX IF NOT EXISTS idx_parse_ok      ON cod_entries(parse_ok);
CREATE INDEX IF NOT EXISTS idx_name_fts      ON cod_entries(mineral_name);
CREATE INDEX IF NOT EXISTS idx_cif_file      ON cod_entries(file);

CREATE TABLE IF NOT EXISTS cod_atomic_sites (
    cod_id     INTEGER NOT NULL,
    site_idx   INTEGER NOT NULL,
    label      TEXT,
    element    TEXT NOT NULL,
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    z          REAL NOT NULL,
    occupancy  REAL DEFAULT 1.0,
    u_iso      REAL,
    PRIMARY KEY (cod_id, site_idx)
);
CREATE INDEX IF NOT EXISTS idx_sites_cod_id ON cod_atomic_sites(cod_id);
"""

_INSERT_SITES_SQL = """
INSERT OR REPLACE INTO cod_atomic_sites
    (cod_id, site_idx, label, element, x, y, z, occupancy, u_iso)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_SQL = """
INSERT OR REPLACE INTO cod_entries
    (cod_id, file, mineral_name, formula, formula_red, elements,
     space_group, space_group_number, a, b, c, alpha, beta, gamma,
     volume, z_value, last_updated, parse_ok)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_SQL_WITH_CIF = """
INSERT OR REPLACE INTO cod_entries
    (cod_id, file, mineral_name, formula, formula_red, elements,
     space_group, space_group_number, a, b, c, alpha, beta, gamma,
     volume, z_value, last_updated, parse_ok, cif_gz)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_ENTRY_FIELDS = (
    "cod_id", "file", "mineral_name", "formula", "formula_red", "elements",
    "space_group", "space_group_number", "a", "b", "c", "alpha", "beta", "gamma",
    "volume", "z_value", "last_updated", "parse_ok",
)


def _entry_to_tuple(e: CODLocalEntry) -> tuple:
    return tuple(getattr(e, f) for f in _ENTRY_FIELDS)


# ── 数据库文件定位 ────────────────────────────────────────────

# 打包后从 PyInstaller datas 部署到用户目录的源路径 (相对 sys._MEIPASS)
_BUNDLED_COD_DB_SUBPATH = "cod/cod_index.sqlite"
# 用户目录下的期望大小阈值 (低于此值视为未部署/损坏, 需要从 bundled 复制)
_MIN_VALID_DB_BYTES = 50 * 1024 * 1024  # 50 MB (实际 431 MB, 留大量余量)


def app_dir() -> Optional[Path]:
    """打包运行时的**安装目录** (含 PolyXRD.exe 的那层); 非打包返回 None。

    onedir 打包下 ``__file__`` 落在 ``<install>/_internal/polyxrd/...`` ——
    ``Path(__file__).resolve().parents[2]`` 就是安装目录, 而它**通常只读**
    (装到 Program Files 时更是), 绝不能往里写库文件。
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except Exception:  # noqa: BLE001
        return None


def is_inside_app_dir(path: Path) -> bool:
    """路径是否落在安装目录内 (用于拦截"往安装目录写库"的行为)。"""
    root = app_dir()
    if root is None:
        return False
    try:
        Path(path).resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _bundled_cod_db_source() -> Optional[Path]:
    """如果是 PyInstaller 打包运行, 返回 datas 里的 cod_index.sqlite 路径; 否则 None."""
    # PyInstaller onefile / onedir 都设置 sys._MEIPASS 为临时解压/资源根目录
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / _BUNDLED_COD_DB_SUBPATH
        if p.exists():
            return p
    # 开发模式: PolyXRD 根目录 (src/polyxrd/services -> project root)
    #
    # ⚠️ 这条兜底**只在源码模式**下成立。打包后 __file__ 在
    # <install>/_internal/polyxrd/services/, parents[3] 就是安装目录 ——
    # 若那里恰好躺着个残缺的 cod_index.sqlite (实测 2026-09-17: 被
    # CODLocalDatabase 初始化时凭空创建的 60 KB 空库), 它就会被当成
    # "随包索引"复制到用户目录, 把真正的全库索引永久顶掉 (搜索全空)。
    if getattr(sys, "frozen", False):
        return None
    dev_root = Path(__file__).resolve().parents[3]
    # v0.13.2: 三库统一放 cod_data/ 后, 项目根已不再有 cod_index.sqlite
    # (2026-09-18 实测: 移动后此函数返回 None, dev 模式部署来源随之丢失)。
    dev_candidates = (dev_root / "cod_index.sqlite",
                      dev_root / "cod_data" / "cod_index.sqlite")
    for dev in dev_candidates:
        if dev.exists():
            return dev
    return None


def deploy_bundled_cod_db_if_missing(target: Optional[Path] = None) -> Optional[Path]:
    """确保用户目录下有 cod_index.sqlite (如缺失则从打包内资源复制).

    PolyXRD 使用 PyInstaller 分发时, cod_index.sqlite 通过 datas 条目打入安装包.
    首次启动时复制到用户可写目录 ~/.polyxrd/cif_db/cod_index.sqlite (~431 MB).
    复制使用 shutil.copy2, 失败时静默 (用户仍可在应用设置里手动放置或下载).

    Args:
        target: 目标路径. 默认 cfg.get_cif_db_path() / "cod_index.sqlite".

    Returns:
        部署后的目标路径, 或 None (未部署, 目标已存在或无法部署).
    """
    cfg = get_config()
    if target is None:
        target = cfg.get_cif_db_path() / "cod_index.sqlite"
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 若目标已存在且体积合理, 无需部署
    if target.exists():
        try:
            sz = target.stat().st_size
            if sz >= _MIN_VALID_DB_BYTES:
                return None  # 已经是有效大小, 跳过
            log.info("cod_index.sqlite present but too small (%d bytes), will re-deploy", sz)
        except OSError as e:
            log.warning("Cannot stat existing cod_index.sqlite: %s", e)
            return None

    source = _bundled_cod_db_source()
    if source is None:
        log.info("No bundled cod_index.sqlite found (dev mode / missing datas). Skipped deploy.")
        return None
    try:
        tmp_target = target.with_suffix(".tmp")
        log.info("Deploying bundled COD db: %s -> %s", source, target)
        t0 = time.time()
        shutil.copy2(source, tmp_target)
        tmp_target.replace(target)  # atomic rename (避免半拷贝损坏)
        elapsed = time.time() - t0
        log.info("Deployed cod_index.sqlite in %.1f s (%.1f MB)", elapsed,
                 target.stat().st_size / 1024 / 1024)
        return target
    except (OSError, shutil.Error) as e:
        log.warning("Failed to deploy cod_index.sqlite: %s", e)
        # 清理半成文件
        try:
            for p in (target, target.with_suffix(".tmp")):
                if p.exists() and p.stat().st_size < _MIN_VALID_DB_BYTES:
                    p.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _is_usable_index_file(path: Optional[Path]) -> bool:
    """索引文件是否存在且体积合理 (排除 0 条目的空库)。

    ⚠️ 这条判断很关键: 打包版启动时若某条路径被 ``sqlite3.connect()`` 碰过,
    会在用户目录凭空留下一个 0 条目、约 60 KB 的 ``cod_index.sqlite``
    (2026-09-18 实测)。它体积远小于 :data:`_MIN_VALID_DB_BYTES`, 却会被
    "只要 exists 就返回"的旧逻辑选中, 从此**永久顶掉**真正的 431 MB 全库索引
    —— 表现就是状态显示 ``live_counts()['cod_index'] == 0``。
    """
    try:
        return bool(path) and Path(path).is_file() and (
            Path(path).stat().st_size >= _MIN_VALID_DB_BYTES
        )
    except OSError:
        return False


def _cod_data_index_candidates() -> list[Path]:
    """``cod_index.sqlite`` 的"项目内"候选目录 (v0.13.2)。

    2026-09-18 起三库统一放 ``cod_data/`` (无机库 / PDF2 本就在那里, 全库索引
    也被移了过去), 但解析逻辑只会看 ``cod_root.parent`` (项目根) 与
    ``~/.polyxrd/cif_db``, 于是真索引成了"隐形" —— 状态显示 0 条, 且下一次
    ``connect()`` 会在项目根凭空再造一个 0 条目的幽灵库。这里把 ``cod_data``
    提为一等候选:

    1. ``<项目根>/cod_data/cod_index.sqlite`` —— 当前实际布局;
    2. 当前无机库所在目录 —— 用户外挂导入时, 全库索引常与无机库放在一起
       (导入布局的合理推断, 不引入新配置项)。

    全部要过 :func:`_is_usable_index_file` 体积门槛, 不给 60KB 幽灵库留口子。
    """
    out: list[Path] = [AppConfig._PROJECT_ROOT / "cod_data" / "cod_index.sqlite"]
    try:
        p = get_config().get_cod_db_path()
        if p is not None:
            out.append(Path(p).parent / "cod_index.sqlite")
    except Exception:  # noqa: BLE001 - 路径推导不该影响解析主流程
        pass
    return out


def resolved_index_db_path(deploy: bool = True) -> Path:
    """解析 COD 全库索引的**预期**路径。

    用户导入的外挂库 > 用户库目录 ``cif_db/cod_index.sqlite``。

    ``deploy=False`` 时**不做** bundled 部署 —— 这一点很关键: 开发模式下
    ``_bundled_cod_db_source()`` 会指向项目根的 cod_index.sqlite, 一旦
    ``deploy=True`` 就会在这里触发一次 ~400 MB 的复制。打开"外挂数据库
    管理"对话框只是要**看一眼状态**, 不该产生这种副作用。

    候选文件必须通过 :func:`_is_usable_index_file` (体积门槛) 才算命中 ——
    否则一个 0 条目的空库会把真正的索引永久遮蔽, 且部署永远不再触发。
    """
    cfg = get_config()
    user_path = cfg.get_cod_index_sqlite_path()
    if user_path is not None:
        return user_path
    target = cfg.get_cif_db_path() / "cod_index.sqlite"
    if _is_usable_index_file(target):
        return target
    alt = cfg.user_db_dir() / "cod_index.sqlite"
    if _is_usable_index_file(alt):
        return alt
    # v0.13.2: cod_data/ 候选 (三库统一目录, 见 _cod_data_index_candidates)
    for cand in _cod_data_index_candidates():
        if _is_usable_index_file(cand):
            return cand
    if deploy:
        # target 若已存在但体积不合理, deploy 内部会识别并重部署
        deploy_bundled_cod_db_if_missing(target)
    return target


def existing_index_db_path() -> Optional[Path]:
    """只读查找**当前实际存在且可用**的 COD 全库索引文件 (不部署、不复制)。

    顺序: 用户导入 → 目标位置 → 用户目录 (``~/.polyxrd/cif_db``) →
    打包资源/开发模式自带位置 (``_bundled_cod_db_source()``)。找不到返回 None。

    用途是"这个槽位现在能用吗"这类状态显示; 真正的检索路径仍由
    :func:`_index_db_path` 决定 (它会在需要时触发首次部署)。

    ``target`` / ``alt`` 两个自动发现的候选要过 :func:`_is_usable_index_file`
    体积门槛, 免得 0 条目空库把真索引遮蔽; 用户**显式导入**的路径不做门槛
    (导入是用户意图, 状态里如实报 0 条更有用)。
    """
    cfg = get_config()
    user_path = cfg.get_cod_index_sqlite_path()
    if user_path is not None:
        return user_path
    target = cfg.get_cif_db_path() / "cod_index.sqlite"
    if _is_usable_index_file(target):
        return target
    alt = cfg.user_db_dir() / "cod_index.sqlite"
    if _is_usable_index_file(alt):
        return alt
    # v0.13.2: cod_data/ 候选 (2026-09-18 起全库索引与另两库同放 cod_data/)
    for cand in _cod_data_index_candidates():
        if _is_usable_index_file(cand):
            return cand
    return _bundled_cod_db_source()


def _index_db_path(cod_root: Optional[Path] = None) -> Path:
    """Return path for cod_index.sqlite.

    - If COD root is given, place the db alongside it for portability.
    - Otherwise use the user's cif_db_path from AppConfig.
    - Before returning the user path, deploy the bundled DB if missing.
    - 0.10.0: 用户在 GUI 里导入的 COD 全库**优先** (数据库改外挂)。

    v0.13.0 修正: `cod_root` 落在**安装目录**内时不再原地建库。打包运行时
    `get_cod_root()` 可能解析到 `<install>/cod`, 于是 sqlite3.connect() 会在
    <install> 里凭空生成一个 0 条目的空索引 (实测), 之后它既污染安装目录,
    又会被 `_bundled_cod_db_source()` 的旧兜底当成"随包索引"回灌用户目录。
    这种情况一律退回 `resolved_index_db_path()` (用户目录/外挂库)。
    """
    if cod_root is not None:
        cand = Path(cod_root).parent / "cod_index.sqlite"
        if _is_usable_index_file(cand):
            return cand
        # v0.13.2: 项目根的索引被移进 cod_data/ 后, cand 会指向一个不存在的
        # 路径 —— 旧逻辑 "not is_inside_app_dir(cand) 也照返" 会让调用方在
        # 那里 connect() 凭空造出 0 条目幽灵库 (60KB)。先找 cod_data/ 候选。
        #
        # ⚠️ 只对**项目自己的 cod 树**生效 (cod_root.parent == 项目根)。
        #    无条件兜底会把 CODLocalIndexer 指到真实库上 —— 2026-09-18 实测:
        #    test_cod_local 的合成临时树被重定向到 431MB 真库, build_index()
        #    往里插了 12 条假条目 (113,223 → 113,235)。测试/临时树必须
        #    原地取 cand, 让索引器在旁边新建。
        if Path(cod_root).parent == Path(AppConfig._PROJECT_ROOT):
            for alt in _cod_data_index_candidates():
                if _is_usable_index_file(alt):
                    return alt
        if cand.exists() or not is_inside_app_dir(cand):
            return cand
        return resolved_index_db_path(deploy=True)
    return resolved_index_db_path(deploy=True)


def get_cod_root(default: Optional[Path] = None) -> Path:
    """Return the COD CIF root directory (cod/ subdirectory).

    Priority:
      1. passed default
      2. 用户导入的 cod_index.sqlite 旁路 (config.get_cod_index_sqlite_path)
      3. Paths with existing cod_index.sqlite alongside (most reliable)
         — **项目根优先** (v0.11.0 修复: 系统重装后盘符 D:→E:, 旧
         d:\\TEMP 硬编码抢在项目根之前命中老树, 导致下载写 E: 运行读 D:)
      4. AppConfig.cif_db_path / "cod"  (存在的话)
      5. D:/Project/XRD/PolyXRD\\cod  (旧系统盘遗留, 仅兜底)
      6. ~/.polyxrd/cif_db/cod (创建并返回)
    """
    # Phase 1: check candidates that have cod_index.sqlite alongside
    index_candidates: list[Path] = []
    if default:
        index_candidates.append(Path(default))
    cfg = get_config()
    user_idx = cfg.get_cod_index_sqlite_path()
    if user_idx and Path(user_idx).exists():
        index_candidates.append(Path(user_idx).parent / "cod")
        index_candidates.append(Path(user_idx).parent / "cod" / "cif")
    # 项目根优先: 源码树 (dev) 或 _internal (打包后) 下的 cod/
    index_candidates.append(AppConfig._PROJECT_ROOT / "cod")
    index_candidates.append(AppConfig._PROJECT_ROOT / "cod" / "cif")
    index_candidates.append(cfg.get_cif_db_path() / "cod")
    for c in index_candidates:
        idx = c.parent / "cod_index.sqlite" if c.name == "cif" else c.parent / "cod_index.sqlite"
        if c.exists() and idx.exists():
            return c
    # Phase 2: check candidates by directory existence
    for c in index_candidates:
        if c.exists() and any(c.iterdir()):
            return c
    # Phase 3: fallback - try to create
    #
    # ⚠️ 顺序与"跳过安装目录"都很关键 (v0.13.0): 打包后 AppConfig._PROJECT_ROOT
    # 就是安装目录, 旧代码会在这里 `mkdir <install>/cod` 并返回 —— 紧接着
    # CODLocalDatabase 就在安装目录里 connect 出一个 0 条目的空 cod_index.sqlite
    # (2026-09-17 实测的 60 KB 幽灵库)。装到 Program Files 时更是直接写不进去。
    fallbacks = [
        cfg.user_db_dir() / "cod",       # 用户可写目录优先
        cfg.get_cif_db_path() / "cod",
        AppConfig._PROJECT_ROOT / "cod",
    ]
    for fallback in fallbacks:
        if is_inside_app_dir(fallback):
            continue
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except (OSError, PermissionError):
            continue
    # 兜底: 用户可写目录 (即使 mkdir 失败也返回它, 让调用方拿到一个合理位置)
    return cfg.user_db_dir() / "cod"


# ── 数据库连接辅助 ────────────────────────────────────────────

def _migrate_schema(conn: sqlite3.Connection) -> None:
    """对已存在的旧库做 schema 迁移 (幂等, 只做 ALTER TABLE ADD COLUMN).

    - cod_entries 缺 cif_gz 时补齐 (精简数据库模式, 存 gzip 压缩 CIF 全文)
    - 保证 cod_atomic_sites 表存在 (已由 _SCHEMA_SQL 里的 CREATE TABLE IF NOT EXISTS 处理)

    策略参考 SQLite DDL 最佳实践: 优先 ALTER TABLE ... ADD COLUMN (SQLite 3.35+ 支持,
    Python 3.10 自带 sqlite3 满足); 仅新增无默认值/无复杂约束的 BLOB 列, 安全可靠.
    """
    # 1) 检查 cod_entries 是否有 cif_gz 列
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cod_entries)")}
    if "cif_gz" not in cols:
        try:
            conn.execute("ALTER TABLE cod_entries ADD COLUMN cif_gz BLOB")
            log.info("migrate_schema: ALTER TABLE cod_entries ADD COLUMN cif_gz BLOB")
        except sqlite3.OperationalError as e:
            # 如果该 SQLite 版本不支持 ALTER TABLE ADD (极老版本), 回退:
            # RENAME -> CREATE 新表 -> INSERT 迁移.  按 Experience 1526673 保守模板.
            log.warning("ALTER TABLE ADD cif_gz 失败, 改用重建表迁移: %s", e)
            conn.execute("ALTER TABLE cod_entries RENAME TO cod_entries_old")
            conn.execute(_SCHEMA_SQL.split("CREATE TABLE IF NOT EXISTS cod_entries", 1)[1].split(");", 1)[0].replace(
                "CREATE TABLE IF NOT EXISTS cod_entries (\n", ""
            ) + ");") if False else None
            # 保守迁移: 重建完整 cod_entries (含 cif_gz), 然后把旧数据迁移回来
            conn.execute("DROP TABLE IF EXISTS cod_entries_old")
            raise  # 保守起见, 抛错; 现代 SQLite 不会到这里
    # 2) v1.1.2 (W21): cod_atomic_sites 补 u_iso 列 (可空; 旧库读侧给 0.005 默认)
    try:
        site_cols = {r[1] for r in conn.execute("PRAGMA table_info(cod_atomic_sites)")}
        if site_cols and "u_iso" not in site_cols:
            conn.execute("ALTER TABLE cod_atomic_sites ADD COLUMN u_iso REAL")
            log.info("migrate_schema: ALTER TABLE cod_atomic_sites ADD COLUMN u_iso REAL")
    except sqlite3.OperationalError as e:  # 极老 SQLite / 只读库 → 忽略, 读侧有默认值
        log.warning("cod_atomic_sites 加 u_iso 列失败 (读侧将用默认值): %s", e)
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    # Schema 迁移 (对旧库补齐 cif_gz 列)
    _migrate_schema(conn)
    # Store schema version if missing
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    if cur.fetchone() is None:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    return conn


def _entry_from_row(row: sqlite3.Row) -> CODLocalEntry:
    return CODLocalEntry(
        cod_id=row["cod_id"],
        file=row["file"],
        mineral_name=row["mineral_name"] or "",
        formula=row["formula"] or "",
        formula_red=row["formula_red"] or "",
        elements=row["elements"] or "",
        space_group=row["space_group"] or "",
        space_group_number=row["space_group_number"] or 0,
        a=row["a"] or 0.0,
        b=row["b"] or 0.0,
        c=row["c"] or 0.0,
        alpha=row["alpha"] or 90.0,
        beta=row["beta"] or 90.0,
        gamma=row["gamma"] or 90.0,
        volume=row["volume"] or 0.0,
        z_value=row["z_value"] or 0,
        last_updated=row["last_updated"] or 0,
        parse_ok=row["parse_ok"] or 0,
    )


# ──────────────────────────────────────────────────────────────
# CODLocalIndexer: 扫描 CIF 并建索引
# ──────────────────────────────────────────────────────────────

class CODLocalIndexer:
    """扫描 COD CIF 目录，构建 SQLite 索引数据库。

    支持增量更新:
      - 读取现有数据库的 last_updated + file
      - 新文件 / mtime 变化 → 重解析并 REPLACE
      - 已存在且 mtime 相同 → 跳过
    """

    def __init__(self, cod_root: Optional[Path] = None, db_path: Optional[Path] = None):
        self.cod_root = Path(cod_root) if cod_root else get_cod_root()
        self.db_path = Path(db_path) if db_path else _index_db_path(self.cod_root)
        self._lock = threading.Lock()

    # ── 工具: 已有索引查询 ──────────────────────────────────
    def _get_existing_map(self, conn: sqlite3.Connection) -> dict[str, int]:
        cur = conn.execute("SELECT file, last_updated FROM cod_entries")
        return {row["file"]: row["last_updated"] or 0 for row in cur.fetchall()}

    # ── 主入口 ──────────────────────────────────────────────
    def build_index(self, progress_cb=None, max_workers=PARSE_WORKERS,
                    batch_size=BATCH_INSERT_SIZE) -> dict:
        """扫描 + 解析 + 写入 SQLite。

        Args:
            progress_cb: callable(done:int, total:int, processed:int, skipped:int) or None
            max_workers: 并行线程数 (I/O 密集，默认 8)
            batch_size: 批量 commit 大小

        Returns:
            {"indexed": N, "updated": N, "skipped": N, "failed": N, "db_path": path}
        """
        if not self.cod_root.exists():
            raise FileNotFoundError(
                f"COD 根目录不存在: {self.cod_root}。请先下载并解压 COD 压缩包。"
            )

        log.info("Building COD index from %s", self.cod_root)
        start = time.time()

        conn = connect(self.db_path)

        # 1) 枚举所有 .cif (COD cif/ 目录下为 xx/yy/xxxx.cif)
        all_files: list[Path] = []
        for cif in self.cod_root.rglob("*.cif"):
            all_files.append(cif)
        total = len(all_files)
        log.info("Found %d .cif files", total)
        if total == 0:
            conn.close()
            return {"indexed": 0, "updated": 0, "skipped": 0, "failed": 0,
                    "db_path": str(self.db_path), "elapsed": 0.0}

        # 2) 加载现有索引 (增量)
        existing_map = self._get_existing_map(conn)

        # 3) 并行解析 CIF，批量写入
        def _skip_need_parse(cif_path: Path) -> tuple[bool, str]:
            try:
                parts = cif_path.parts
                if "cod" in parts:
                    idx = parts.index("cod")
                    rel = "/".join(parts[idx+1:])
                else:
                    rel = cif_path.name
            except Exception:
                rel = cif_path.name
            mtime = int(cif_path.stat().st_mtime)
            if existing_map.get(rel) == mtime:
                return True, rel  # 跳过
            return False, rel

        processed = 0
        skipped = 0
        failed = 0
        inserted = 0
        batch: list[tuple] = []

        def _flush_batch():
            nonlocal inserted, batch
            if not batch:
                return
            with self._lock:
                conn.executemany(_INSERT_SQL, batch)
                conn.commit()
            inserted += len(batch)
            batch = []

        if progress_cb:
            progress_cb(0, total, 0, 0)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {}
            for cif in all_files:
                do_skip, _rel = _skip_need_parse(cif)
                if do_skip:
                    skipped += 1
                    processed += 1
                    continue
                fut = pool.submit(parse_cif_light, cif)
                future_map[fut] = cif

            for fut in as_completed(future_map):
                entry = fut.result()
                processed += 1
                if entry.parse_ok == 0 and not entry.formula:
                    failed += 1
                    # 仍写入 (至少保留文件索引)，不写入会导致下次仍尝试
                batch.append(_entry_to_tuple(entry))
                if len(batch) >= batch_size:
                    _flush_batch()
                if progress_cb and (processed % 10000 == 0):
                    progress_cb(processed, total, processed - skipped - failed, skipped)

        _flush_batch()
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_build_time', ?)",
                     (str(int(time.time())),))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('entry_count', ?)",
                     (str(inserted),))
        conn.commit()
        conn.close()

        elapsed = time.time() - start
        stats = {
            "indexed": inserted,
            "updated": inserted - skipped,
            "skipped": skipped,
            "failed": failed,
            "total_files": total,
            "db_path": str(self.db_path),
            "cod_root": str(self.cod_root),
            "elapsed": round(elapsed, 1),
        }
        log.info("COD index built: %s", stats)
        if progress_cb:
            progress_cb(processed, total, processed - skipped - failed, skipped)
        return stats

    # ── 从 .tar 文件流式建索引 ────────────────────────────
    def build_index_from_tar(self, tar_path: Path, progress_cb=None,
                             batch_size: int = BATCH_INSERT_SIZE,
                             max_entries: Optional[int] = None,
                             clear_existing: bool = False,
                             store_cif_gz: bool = True) -> dict:
        """从 .tar 文件流式读取 CIF 并建索引（不需要解压到磁盘）。

        适用于 cod-cifs-mysql.tar 等 COD 归档文件。
        - 遍历 tar 成员，逐个读取 .cif 文件内容
        - 调用 parse_cif_text 解析元数据
        - 批量写入 cod_entries + cod_atomic_sites
        - cif_gz BLOB 可选 (store_cif_gz):
            * True  = ~1.4 GB 完整自包含 (离线可用所有 CIF 原文)
            * False = ~173 MB 精简版 (原子位点已预存; CIF 原文走 COD REST API 兜底)
        - file 字段存储 tar 内的相对路径 (如 cif/9/00/34/9003435.cif)

        Args:
            tar_path: .tar 文件路径
            progress_cb: callable(done, total_hint, processed, skipped) or None
            batch_size: 批量 commit 大小
            max_entries: 只索引前 N 个 .cif 文件 (None 表示不限制).
                         用于小样本验证 / 增量补齐.
            clear_existing: True 则先清空 cod_entries + cod_atomic_sites,
                            避免旧元数据干扰 (重建全库时用 True).
            store_cif_gz: True 存 gzip CIF 全文到 cif_gz BLOB (~1.2 GB).
                          False 不存, 节省 ~1.2 GB, CIF 原文靠 cod REST API 兜底.

        Returns:
            {"indexed": N, "skipped": N, "failed": N, "db_path": path}
        """
        tar_path = Path(tar_path)
        if not tar_path.exists():
            raise FileNotFoundError(f"Tar file not found: {tar_path}")

        log.info("Building COD index from tar: %s", tar_path)
        start = time.time()
        conn = connect(self.db_path)

        # 清空现有数据 (重建模式)
        if clear_existing:
            conn.execute("DELETE FROM cod_entries")
            conn.execute("DELETE FROM cod_atomic_sites")
            conn.commit()
            log.info("Cleared existing cod_entries + cod_atomic_sites")

        # 记录 tar 文件来源
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('tar_source', ?)",
            (str(tar_path),),
        )
        conn.commit()

        processed = 0
        skipped = 0
        failed = 0
        inserted = 0
        sites_total = 0
        batch: list[tuple] = []
        sites_batch: list[tuple] = []
        stop_early = False

        def _flush():
            nonlocal inserted, batch, sites_batch, sites_total
            if batch:
                conn.executemany(_INSERT_SQL_WITH_CIF, batch)
                inserted += len(batch)
                batch = []
            if sites_batch:
                conn.executemany(_INSERT_SITES_SQL, sites_batch)
                sites_total += len(sites_batch)
                sites_batch = []
            conn.commit()

        if progress_cb:
            progress_cb(0, max_entries if max_entries else -1, 0, 0)

        with tarfile.open(str(tar_path), "r:") as tf:
            for member in tf:
                if stop_early:
                    break
                if not member.isfile():
                    continue
                if not member.name.endswith(".cif"):
                    continue
                processed += 1
                try:
                    f = tf.extractfile(member)
                    if f is None:
                        failed += 1
                        continue
                    raw = f.read()
                    text = raw.decode("utf-8", errors="replace")
                    cod_id = 0
                    stem = Path(member.name).stem
                    digits = re.match(r"(\d+)", stem)
                    if digits:
                        cod_id = int(digits.group(1))
                    entry = parse_cif_text(
                        text, file_rel=member.name,
                        cod_id=cod_id, mtime=int(member.mtime),
                    )
                    # CIF 全文压缩 (store_cif_gz=False 时存 None, 节省 ~1.2 GB)
                    if store_cif_gz:
                        cif_gz_val = gzip.compress(raw, compresslevel=9)
                    else:
                        cif_gz_val = None
                    batch.append(_entry_to_tuple(entry) + (cif_gz_val,))
                    # 解析原子位点 (无论 store_cif_gz 都存, 精简核心)
                    sites = parse_atom_sites_from_cif(text)
                    for idx, s in enumerate(sites):
                        sites_batch.append((
                            cod_id, idx, s.get("label", ""),
                            s["element"], s["x"], s["y"], s["z"],
                            s.get("occupancy", 1.0),
                            s.get("u_iso"),
                        ))
                    if len(batch) >= batch_size:
                        _flush()
                except Exception as e:
                    failed += 1
                    log.debug("tar member %s failed: %s", member.name, e)

                if progress_cb and (processed % 1000 == 0):
                    progress_cb(processed, max_entries if max_entries else -1,
                                processed - failed, skipped)

                # max_entries 早停
                if max_entries is not None and processed >= max_entries:
                    stop_early = True
                    break

        _flush()
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('last_build_time', ?)",
            (str(int(time.time())),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('entry_count', ?)",
            (str(inserted),),
        )
        conn.commit()
        conn.close()

        elapsed = time.time() - start
        stats = {
            "indexed": inserted,
            "skipped": skipped,
            "failed": failed,
            "total_files": processed,
            "atomic_sites": sites_total,
            "db_path": str(self.db_path),
            "tar_source": str(tar_path),
            "elapsed": round(elapsed, 1),
        }
        log.info("COD tar index built: %s", stats)
        if progress_cb:
            progress_cb(processed, -1, processed - failed, skipped)
        return stats


# ──────────────────────────────────────────────────────────────
# CODLocalDatabase: 查询与 CIF 获取
# ──────────────────────────────────────────────────────────────

class CODLocalDatabase:
    """COD 本地查询服务 (只读为主)"""

    def __init__(self, cod_root: Optional[Path] = None, db_path: Optional[Path] = None):
        self._init_error: Optional[str] = None
        # v0.11.0: 无机物库内嵌结构数据的惰性连接缓存。
        # None = 还没探测; False = 探测过、不可用; Connection = 可用。
        self._inorg_conn: Optional[sqlite3.Connection] = None
        self._inorg_probed = False
        try:
            self.cod_root = Path(cod_root) if cod_root else get_cod_root()
            self.db_path = Path(db_path) if db_path else _index_db_path(self.cod_root)
        except Exception as e:
            # 沙箱权限或其他初始化异常
            self.cod_root = Path(cod_root) if cod_root else Path("cod")
            self.db_path = Path(db_path) if db_path else (self.cod_root.parent / "cod_index.sqlite")
            self._init_error = str(e)

    # ── 无机物库内嵌结构数据 (v0.11.0) ──────────────────────

    def _inorg_db(self) -> Optional[sqlite3.Connection]:
        """打开"COD 无机物库"(config 的 cod_db_path), 仅当它带内嵌结构数据。

        v0.11.0 起无机物库的 phases 表新增 ``cif_gz`` 列 (gzip 的 CIF 全文),
        并带 ``cod_atomic_sites`` 子集表 —— 这样**只挂无机库也能做 Rietveld
        结构精修**, 不必再挂 COD 全库索引 (两库的 COD 编号体系并不重合,
        全库只覆盖约 1/3 的无机相, 见 v0.11.0 侦察)。

        一次性探测并缓存; 库不存在 / 没有 cif_gz 列 / 与全库是同一文件时
        返回 None, 调用方按"没有这条回退"处理。**只读**打开, 不写。
        """
        if self._inorg_probed:
            return self._inorg_conn
        self._inorg_probed = True
        try:
            path = Path(get_config().get_cod_db_path())
        except Exception:
            path = None
        if path is None or not path.exists():
            return None
        try:
            if path.resolve() == self.db_path.resolve():
                return None  # 同一个文件 (全库被当无机库挂了), 别重复打开
        except Exception:
            pass
        try:
            conn = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(phases)")]
            if "cif_gz" not in cols:
                conn.close()
                return None  # 旧版无机库 (未内嵌 CIF), 走原有回退链
            self._inorg_conn = conn
        except Exception:
            self._inorg_conn = None
        return self._inorg_conn

    def _inorg_cif_gz(self, cod_id: int) -> Optional[str]:
        """从无机物库取内嵌 CIF 全文 (cif_gz BLOB → 解压文本)。"""
        conn = self._inorg_db()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT cif_gz FROM phases WHERE cod_id = ?", (cod_id,)
            ).fetchone()
            if row and row["cif_gz"]:
                return gzip.decompress(row["cif_gz"]).decode("utf-8", errors="replace")
        except Exception as e:
            log.debug("inorg cif_gz lookup failed for %d: %s", cod_id, e)
        return None

    def _inorg_is_slim(self) -> bool:
        """无机库是否为瘦身索引式 (v0.14.0)。

        瘦身库与 COD 全库索引同形态: ``phases.cif_gz`` 全为 NULL, CIF 原文由
        ``cod/cif`` 目录按需读取 (缺失时 COD REST 在线下载兜底)。以 meta 表
        ``variant`` 键 (``slim-index`` 打头) 判定; 探测失败一律按原库处理。
        """
        conn = self._inorg_db()
        if conn is None:
            return False
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'variant'"
            ).fetchone()
            return bool(row and str(row["value"]).startswith("slim-index"))
        except Exception as e:
            log.debug("inorg slim variant probe failed: %s", e)
            return False

    def _inorg_has_cif_expr(self) -> str:
        """has_cif 的 SQL 片段 (兼容原库 / 瘦身库)。

        - 原库: 内嵌 ``cif_gz`` 非空才算有 CIF;
        - 瘦身库: 全部按"可获取"处理 (本地 cod/cif 文件或 REST 回退),
          否则 ``cif_gz IS NOT NULL`` 过滤会把搜索结果清空。
        """
        return "(1)" if self._inorg_is_slim() else "(cif_gz IS NOT NULL)"

    # ── 基础设施 ────────────────────────────────────────────
    def is_ready(self) -> bool:
        """索引数据库存在且有至少 1 条记录"""
        if self._init_error:
            return False
        if not self.db_path.exists():
            return False
        try:
            conn = connect(self.db_path)
            cur = conn.execute("SELECT COUNT(*) as n FROM cod_entries")
            n = cur.fetchone()["n"]
            conn.close()
            return n > 0
        except Exception:
            return False

    def stats(self) -> dict:
        if not self.db_path.exists():
            return {"ready": False}
        conn = connect(self.db_path)
        cur = conn.execute(
            "SELECT COUNT(*) n, "
            "SUM(CASE WHEN parse_ok=1 THEN 1 ELSE 0 END) ok, "
            "SUM(CASE WHEN parse_ok=0 THEN 1 ELSE 0 END) bad "
            "FROM cod_entries"
        )
        row = cur.fetchone()
        n = row["n"]
        ok = row["ok"] or 0
        bad = row["bad"] or 0
        meta = {}
        for r in conn.execute("SELECT key,value FROM meta"):
            meta[r["key"]] = r["value"]
        conn.close()
        return {
            "ready": True,
            "total": n,
            "parse_ok": ok,
            "parse_bad": bad,
            "db_path": str(self.db_path),
            "cod_root": str(self.cod_root),
            "index_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1) if self.db_path.exists() else 0,
            **meta,
        }

    # ── 主查询接口 ──────────────────────────────────────────
    def search(self, formula: Optional[str] = None,
               mineral_name: Optional[str] = None,
               space_group: Optional[str] = None,
               space_group_number: Optional[int] = None,
               elements: Optional[Sequence[str]] = None,
               cod_id: Optional[int] = None,
               limit: int = 100,
               parse_ok_only: bool = True) -> list[CODLocalEntry]:
        """组合查询；参数为 AND 关系。"""
        if not self.db_path.exists():
            return []
        conn = connect(self.db_path)
        clauses: list[str] = []
        args: list[Any] = []
        if parse_ok_only:
            clauses.append("parse_ok = 1")
        if formula:
            fr, _ = _parse_elements(formula)
            if fr:
                clauses.append("formula_red = ?")
                args.append(fr)
            else:
                clauses.append("(formula LIKE ? OR formula_red LIKE ?)")
                like = f"%{formula}%"
                args += [like, like]
        if mineral_name:
            clauses.append("mineral_name LIKE ?")
            args.append(f"%{mineral_name}%")
        if space_group:
            clauses.append("space_group LIKE ?")
            args.append(f"%{space_group}%")
        if space_group_number:
            clauses.append("space_group_number = ?")
            args.append(space_group_number)
        if elements:
            for elem in elements:
                clauses.append("elements LIKE ?")
                args.append(f"%{elem}%")
        if cod_id is not None:
            clauses.append("cod_id = ?")
            args.append(cod_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM cod_entries {where} ORDER BY formula_red, cod_id LIMIT ?"
        args.append(int(limit))
        results = [_entry_from_row(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
        return results

    def get_entry(self, cod_id: int) -> Optional[CODLocalEntry]:
        results = self.search(cod_id=cod_id, limit=1, parse_ok_only=False)
        return results[0] if results else None

    # ── 结构候选查询 (v0.12 精修前置 CIF 自动匹配) ──────────

    def find_structure_candidates(self, formula_norm: str,
                                  mineral_name: str = "",
                                  limit: int = 24,
                                  elements: Optional[Sequence[str]] = None) -> list[dict]:
        """按规范化化学式 (可选矿物名 / 元素集) 找**带结构数据**的候选条目。

        供 `phase_structure_resolver` 在精修前把无结构物相匹配到 CIF。
        两个通道, 结果按 cod_id 去重合并:
          1) 无机物库 phases 表 —— formula 是空格分隔 COD 格式, 首选通道
             (v0.14.0 起默认挂瘦身索引式: cif_gz 全空, has_cif 按"可获取"
             处理, CIF 由 cod/cif 目录或 REST 回退提供);
             v2.1-C: 精确式无命中且给了 ``elements`` 时, 追加**元素集宽松
             匹配** (每个元素以独立 token 出现即可, 系数任意) —— 固溶体/
             非整比相 (如 NCM 三元) 的系数与库值差一档导致精确匹配落空,
             宽松匹配能把同系物结构候选找回来;
          2) 全库索引 cod_entries —— formula_red 精确匹配 + mineral_name
             模糊匹配 (内置 118 物相只有矿物名, 走这条通道兜底)。

        Args:
            formula_norm: 规范化化学式 ("Mg(OH)2" → "H2 Mg O2"), 可为空
            mineral_name: 矿物名 (仅全库索引支持), 可为空
            limit: 返回上限
            elements: 元素符号列表 (元素集宽松匹配, 仅无机物库通道)

        Returns:
            [{"cod_id", "formula", "space_group", "a", "b", "c",
              "alpha", "beta", "gamma", "has_cif", "mineral_name",
              "_fallback"}]
            ``_fallback=True`` 表示该条来自元素集宽松匹配 (排序时应降权)。
            库不可用返回 []。**只读**查询, 不抛异常。
        """
        out: dict[int, dict] = {}
        formula_norm = (formula_norm or "").strip()
        mineral_name = (mineral_name or "").strip()
        if not formula_norm and not mineral_name:
            return []

        # 通道 1: 无机物库 (formula 精确; 该库无矿物名列)
        if formula_norm:
            conn = self._inorg_db()
            if conn is not None:
                try:
                    has_cif = self._inorg_has_cif_expr()
                    rows = conn.execute(
                        "SELECT cod_id, formula, space_group, cell_a, cell_b, "
                        "cell_c, cell_alpha, cell_beta, cell_gamma, "
                        f"{has_cif} AS has_cif "
                        "FROM phases WHERE formula = ? "
                        f"ORDER BY {has_cif} DESC, cod_id LIMIT ?",
                        (formula_norm, int(limit)),
                    ).fetchall()
                    for r in rows:
                        out[int(r["cod_id"])] = {
                            "cod_id": int(r["cod_id"]),
                            "formula": r["formula"] or "",
                            "space_group": r["space_group"] or "",
                            "a": r["cell_a"], "b": r["cell_b"], "c": r["cell_c"],
                            "alpha": r["cell_alpha"], "beta": r["cell_beta"],
                            "gamma": r["cell_gamma"],
                            "has_cif": bool(r["has_cif"]),
                            "mineral_name": "",
                        }
                except Exception as e:
                    log.debug("find_structure_candidates inorg query failed: %s", e)

        # v2.1-C: 元素集宽松匹配 (精确式无命中时才做, 全表 GLOB 扫描)。
        # 注意**不能**嵌在 `if formula_norm:` 里 —— resolver 的回退调用
        # 传的就是空 formula_norm + elements, 嵌进去永远不执行。
        if not out and elements:
            els = [str(e).strip() for e in elements
                   if str(e).strip()][:8]
            if els:
                conn = self._inorg_db()
                if conn is not None:
                    try:
                        _hc = self._inorg_has_cif_expr()
                        conds: list[str] = []
                        eargs2: list[Any] = []
                        for el in els:
                            # token = 元素+可选系数(数字/点); 元素后必须跟
                            # 系数/空格/串尾, 避免 "N" 误中 "Na" 这类前缀
                            conds.append(
                                "(formula GLOB ? OR formula GLOB ? "
                                "OR formula GLOB ? OR formula GLOB ? "
                                "OR formula GLOB ? OR formula GLOB ?)"
                            )
                            eargs2.extend((
                                f"{el}[0-9.]*", f"{el}", f"{el} *",
                                f"* {el}[0-9.]*", f"* {el}", f"* {el} *",
                            ))
                        rows = conn.execute(
                            "SELECT cod_id, formula, space_group, cell_a, "
                            "cell_b, cell_c, cell_alpha, cell_beta, "
                            "cell_gamma, "
                            f"{_hc} AS has_cif "
                            f"FROM phases WHERE ({' AND '.join(conds)}) "
                            f"ORDER BY {_hc} DESC, cod_id LIMIT ?",
                            (*eargs2, int(limit) * 2),
                        ).fetchall()
                        for r in rows:
                            cid = int(r["cod_id"])
                            if cid in out:
                                continue
                            out[cid] = {
                                "cod_id": cid,
                                "formula": r["formula"] or "",
                                "space_group": r["space_group"] or "",
                                "a": r["cell_a"], "b": r["cell_b"],
                                "c": r["cell_c"],
                                "alpha": r["cell_alpha"],
                                "beta": r["cell_beta"],
                                "gamma": r["cell_gamma"],
                                "has_cif": bool(r["has_cif"]),
                                "mineral_name": "",
                                "_fallback": True,
                            }
                    except Exception as e:
                        log.debug("find_structure_candidates element-set "
                                  "query failed: %s", e)

        # 通道 2: 全库索引 (formula_red 精确 + mineral_name 模糊)
        if len(out) < int(limit):
            try:
                if not self.db_path.exists():
                    return list(out.values())
                conn = connect(self.db_path)
                clauses: list[str] = ["parse_ok = 1"]
                args: list[Any] = []
                if formula_norm:
                    fr, _ = _parse_elements(formula_norm)
                    if fr:
                        clauses.append("formula_red = ?")
                        args.append(fr)
                if mineral_name:
                    clauses.append("mineral_name LIKE ?")
                    args.append(f"%{mineral_name}%")
                where = "WHERE " + " AND ".join(clauses)
                sql = (
                    "SELECT cod_id, formula, space_group, a, b, c, alpha, "
                    "beta, gamma, file, mineral_name FROM cod_entries "
                    f"{where} ORDER BY cod_id LIMIT ?"
                )
                args.append(int(limit))
                for r in conn.execute(sql, args).fetchall():
                    cid = int(r["cod_id"])
                    if cid in out:
                        # 无机库通道优先, 但矿物名可从全库补全
                        if r["mineral_name"] and not out[cid]["mineral_name"]:
                            out[cid]["mineral_name"] = r["mineral_name"]
                        continue
                    out[cid] = {
                        "cod_id": cid,
                        "formula": r["formula"] or "",
                        "space_group": r["space_group"] or "",
                        "a": r["a"], "b": r["b"], "c": r["c"],
                        "alpha": r["alpha"], "beta": r["beta"],
                        "gamma": r["gamma"],
                        "has_cif": bool(r["file"]),
                        "mineral_name": r["mineral_name"] or "",
                    }
                conn.close()
            except Exception as e:
                log.debug("find_structure_candidates full-index query failed: %s", e)

        return list(out.values())[: int(limit)]

    def search_structures(self, query: str, limit: int = 200) -> list[dict]:
        """通用结构检索 (向导「CIF 数据库」页的列表数据源)。

        与 :meth:`find_structure_candidates` (精修前置自动匹配, 精确匹配)
        不同, 这里面向**人工浏览**: 同一物相的多条 CIF 都要列出来。

        查询语义:
          - 纯数字 / "97-xxxxxxx" / "97 xxxxxxx" → 按 COD 编号
          - 化学式 ("Mg(OH)2" / "H2 Mg O2") → 规范化后精确匹配,
            无命中再按前缀 LIKE (兼容固溶体小数系数)
          - 其它 (矿物名 / 空间群) → 全库索引 mineral_name / space_group LIKE

        Returns:
            与 :meth:`find_structure_candidates` 相同的字典列表
            (cod_id/formula/space_group/晶胞/has_cif/mineral_name)。
        """
        q = (query or "").strip()
        if not q:
            return []
        limit = int(limit)
        out: dict[int, dict] = {}

        def _absorb(cands: list[dict]) -> None:
            for c in cands:
                out.setdefault(int(c["cod_id"]), c)

        # 1) 编号直查: "9004178" / "97-9004178" / "97 9004178" / "979004178"
        #    ⚠️ 前缀必须**剥掉**再取数字。旧实现是把整串里的数字都收集起来,
        #    "97-9004178" 会变成 979004178 → 查不到 → 静默返回空列表
        #    (用户从列表里复制 display_id 去搜就必然落空)。
        #    分隔符统一先去掉; 剩下的 9 位纯数字且以 96/97 打头, 即
        #    "语料库前缀 + 7 位 COD 号" → 取后 7 位。
        #    (COD 号恒为 7 位, 不存在 9 位的真实编号, 故无歧义)
        core = q.replace(" ", "").replace("-", "").replace("_", "")
        if len(core) == 9 and core.isdigit() and core[:2] in ("96", "97"):
            core = core[2:]
        if core.isdigit():
            by_id = self._structure_by_id(int(core))
            if by_id:
                _absorb([by_id])
            return list(out.values())[:limit]

        # 2) 化学式: 精确 → 前缀 LIKE
        norm = normalize_cod_formula(q)
        if norm:
            _absorb(self.find_structure_candidates(norm, limit=limit))
            if len(out) < limit:
                _absorb(self._structure_like(norm, like_field="formula",
                                             limit=limit - len(out)))
        # 3) 矿物名 / 空间群 (仅全库索引有 mineral_name)
        if len(out) < limit:
            _absorb(self._structure_like(q, like_field="mineral_name",
                                         limit=limit - len(out)))
        if len(out) < limit:
            _absorb(self._structure_like(q, like_field="space_group",
                                         limit=limit - len(out)))
        return list(out.values())[:limit]

    def _structure_by_id(self, cod_id: int) -> Optional[dict]:
        """按编号取单条结构候选 (两通道, 无机库优先)。"""
        got = self.find_structure_candidates("", limit=1)
        got = []  # find_structure_candidates 需要至少一个条件, 这里单独查
        try:
            conn = self._inorg_db()
            if conn is not None:
                r = conn.execute(
                    "SELECT cod_id, formula, space_group, cell_a, cell_b, "
                    "cell_c, cell_alpha, cell_beta, cell_gamma, "
                    f"{self._inorg_has_cif_expr()} AS has_cif FROM phases "
                    "WHERE cod_id = ?",
                    (int(cod_id),),
                ).fetchone()
                if r:
                    return {
                        "cod_id": int(r["cod_id"]),
                        "formula": r["formula"] or "",
                        "space_group": r["space_group"] or "",
                        "a": r["cell_a"], "b": r["cell_b"], "c": r["cell_c"],
                        "alpha": r["cell_alpha"], "beta": r["cell_beta"],
                        "gamma": r["cell_gamma"],
                        "has_cif": bool(r["has_cif"]),
                        "mineral_name": "",
                    }
        except Exception as e:
            log.debug("_structure_by_id inorg failed: %s", e)
        try:
            if not self.db_path.exists():
                return None
            conn = connect(self.db_path)
            r = conn.execute(
                "SELECT cod_id, formula, space_group, a, b, c, alpha, beta, "
                "gamma, file, mineral_name FROM cod_entries WHERE cod_id = ?",
                (int(cod_id),),
            ).fetchone()
            conn.close()
            if r:
                return {
                    "cod_id": int(r["cod_id"]),
                    "formula": r["formula"] or "",
                    "space_group": r["space_group"] or "",
                    "a": r["a"], "b": r["b"], "c": r["c"],
                    "alpha": r["alpha"], "beta": r["beta"], "gamma": r["gamma"],
                    "has_cif": bool(r["file"]),
                    "mineral_name": r["mineral_name"] or "",
                }
        except Exception as e:
            log.debug("_structure_by_id full-index failed: %s", e)
        return None

    def _structure_like(self, pattern: str, *, like_field: str,
                        limit: int) -> list[dict]:
        """LIKE 模糊检索结构候选 (formula / mineral_name / space_group)。"""
        if limit <= 0 or like_field not in ("formula", "mineral_name",
                                            "space_group"):
            return []
        like = f"{pattern}%"
        out: list[dict] = []
        try:
            conn = self._inorg_db()
            if conn is not None and like_field == "formula":
                rows = conn.execute(
                    "SELECT cod_id, formula, space_group, cell_a, cell_b, "
                    "cell_c, cell_alpha, cell_beta, cell_gamma, "
                    f"{self._inorg_has_cif_expr()} AS has_cif FROM phases "
                    f"WHERE formula LIKE ? AND {self._inorg_has_cif_expr()} "
                    "ORDER BY cod_id LIMIT ?",
                    (like, int(limit)),
                ).fetchall()
                for r in rows:
                    out.append({
                        "cod_id": int(r["cod_id"]),
                        "formula": r["formula"] or "",
                        "space_group": r["space_group"] or "",
                        "a": r["cell_a"], "b": r["cell_b"], "c": r["cell_c"],
                        "alpha": r["cell_alpha"], "beta": r["cell_beta"],
                        "gamma": r["cell_gamma"],
                        "has_cif": bool(r["has_cif"]),
                        "mineral_name": "",
                    })
                return out
        except Exception as e:
            log.debug("_structure_like inorg failed: %s", e)
        try:
            if not self.db_path.exists():
                return out
            conn = connect(self.db_path)
            col = {"mineral_name": "mineral_name",
                   "space_group": "space_group",
                   "formula": "formula"}[like_field]
            rows = conn.execute(
                f"SELECT cod_id, formula, space_group, a, b, c, alpha, beta, "
                f"gamma, file, mineral_name FROM cod_entries "
                f"WHERE parse_ok = 1 AND {col} LIKE ? "
                f"ORDER BY cod_id LIMIT ?",
                (like, int(limit)),
            ).fetchall()
            conn.close()
            for r in rows:
                out.append({
                    "cod_id": int(r["cod_id"]),
                    "formula": r["formula"] or "",
                    "space_group": r["space_group"] or "",
                    "a": r["a"], "b": r["b"], "c": r["c"],
                    "alpha": r["alpha"], "beta": r["beta"], "gamma": r["gamma"],
                    "has_cif": bool(r["file"]),
                    "mineral_name": r["mineral_name"] or "",
                })
        except Exception as e:
            log.debug("_structure_like full-index failed: %s", e)
        return out

    # ── CIF 内容获取 ────────────────────────────────────────
    def get_cif_path(self, cod_id: int) -> Optional[Path]:
        """Return full path of .cif file for a COD id.

        If the index was built from a .tar file, returns the .tar path
        (use get_cif() to read contents directly from tar).
        """
        entry = self.get_entry(cod_id)
        if not entry or not entry.file:
            stem = f"{cod_id}.cif"
            found = list(self.cod_root.rglob(stem))
            return found[0] if found else None
        full = self.cod_root / entry.file
        if full.exists():
            return full
        # Check if tar-based index
        tar_path = self._get_tar_source()
        if tar_path and tar_path.exists():
            return tar_path  # Return .tar path; use get_cif() to read content
        return None

    def _get_tar_source(self) -> Optional[Path]:
        """If index was built from a .tar file, return its path."""
        try:
            if not self.db_path.exists():
                return None
            conn = connect(self.db_path)
            cur = conn.execute("SELECT value FROM meta WHERE key='tar_source'")
            row = cur.fetchone()
            conn.close()
            return Path(row["value"]) if row else None
        except Exception:
            return None

    # ── COD REST API 回退 (精简库无 cif_gz / 无 tar 时兜底) ───
    @staticmethod
    def _fetch_cif_from_cod_rest(cod_id: int, timeout: float = 15.0) -> Optional[str]:
        """从 COD REST API 下载单条 CIF (兜底通道).

        官方端点: https://www.crystallography.net/cod/<id>.cif
        此方法仅在以下三级回退都失败时才触发:
          1) 本地 cod/ 目录 CIF 文件
          2) SQLite 的 cif_gz BLOB
          3) cod-cifs-mysql.tar 归档
        网络失败时静默返回 None, 不抛出.
        """
        import urllib.request
        import urllib.error
        url = f"https://www.crystallography.net/cod/{cod_id}.cif"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PolyXRD/0.6"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                raw = resp.read()
                return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            log.debug("COD REST download failed for id=%d: %s", cod_id, e)
            return None

    def get_cif(self, cod_id: int) -> Optional[str]:
        """Return CIF text contents.

        Supports 5-level fallback:
          0) Direct path construction cif/{d}/{dd}/{dd}/{id}.cif
             (v0.11.0 修复: 无机库 cod_id 可能不在 cod_entries 索引里,
             旧版在 entry 缺失时直接 return None, 连 REST 都不试)
          1) Directory-based CIF files under cod_root  (unpacked layout)
          2) SQLite BLOB: cif_gz gzip compressed CIF  (full self-contained DB)
          3) Original .tar archive (meta.tar_source points to it)
          4) COD REST API https://www.crystallography.net/cod/<id>.cif (last resort)
        """
        entry = self.get_entry(cod_id)
        rel_path = entry.file if (entry and entry.file) else None
        if rel_path is None:
            # 无索引条目 → 按 COD 官方目录布局直接构造路径
            s = str(int(cod_id))
            rel_path = f"cif/{s[0]}/{s[1:3]}/{s[3:5]}/{s}.cif"

        def _read_direct(rp: str) -> Optional[str]:
            full = self.cod_root / rp
            if full.exists():
                try:
                    return full.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
            return None

        # Level 0/1: direct path (构造路径与索引路径一致时等价, 只读一次)
        text = _read_direct(rel_path)
        if text is not None:
            return text
        if entry is None:
            # v0.11.0: 编号不在全库索引 ≠ 拿不到结构 —— 无机物库自带 cif_gz
            # (两库编号体系不重合, 全库只覆盖约 1/3 的无机相), 先查无机库
            inorg_text = self._inorg_cif_gz(cod_id)
            if inorg_text:
                return inorg_text
            # 索引都没有 → 不可能有 cif_gz/tar_source 两条路, 只剩 REST
            rest = self._fetch_cif_from_cod_rest(cod_id)
            if rest and "data_" in rest:
                log.info("get_cif fallback to COD REST API for id=%d", cod_id)
                return rest
            return None
        # Level 2: cif_gz BLOB (精简模式下可能为 NULL, 跳过)
        try:
            conn = connect(self.db_path)
            cur = conn.execute("SELECT cif_gz FROM cod_entries WHERE cod_id = ?", (cod_id,))
            row = cur.fetchone()
            conn.close()
            if row and row["cif_gz"]:
                raw = gzip.decompress(row["cif_gz"])
                return raw.decode("utf-8", errors="replace")
        except Exception:
            pass
        # Level 2b: 无机物库内嵌 CIF (v0.11.0) —— 两库 COD 编号体系不重合,
        # 全库索引覆盖不到的相, 从无机库自己的 cif_gz 列取 (只挂无机库即可精修)
        inorg_text = self._inorg_cif_gz(cod_id)
        if inorg_text:
            return inorg_text
        # Level 3: fallback read from original .tar
        tar_path = self._get_tar_source()
        if tar_path and tar_path.exists():
            try:
                with tarfile.open(str(tar_path), "r:") as tf:
                    f = tf.extractfile(entry.file)
                    if f is None:
                        # fallback to REST instead of bailing out
                        pass
                    else:
                        raw = f.read()
                        return raw.decode("utf-8", errors="replace")
            except Exception as e:
                log.debug("get_cif from tar failed for %d: %s", cod_id, e)
        # Level 4: COD REST API (online, last resort)
        rest = self._fetch_cif_from_cod_rest(cod_id)
        if rest and "data_" in rest:
            log.info("get_cif fallback to COD REST API for id=%d", cod_id)
            return rest
        return None

    def get_atomic_sites(self, cod_id: int) -> list[dict]:
        """从精简数据库读取原子位点 (不依赖 CIF 全文)。

        返回 [{"label": ..., "element": ..., "x": float, "y": float, "z": float, "occupancy": float}, ...]
        """
        # v1.1.2 (W21): 优先带 u_iso 查询; 旧库/旧包没有该列时回退到不含它的查询
        # (列缺失 → sqlite3.OperationalError), 读侧再补 0.005 默认值。
        _sel_u = ("SELECT label, element, x, y, z, occupancy, u_iso "
                  "FROM cod_atomic_sites WHERE cod_id = ? ORDER BY site_idx")
        _sel_p = ("SELECT label, element, x, y, z, occupancy "
                  "FROM cod_atomic_sites WHERE cod_id = ? ORDER BY site_idx")

        def _fetch(conn, sql: str):
            try:
                return conn.execute(sql, (cod_id,)).fetchall()
            except sqlite3.OperationalError:
                return conn.execute(_sel_p, (cod_id,)).fetchall()

        rows = []
        try:
            conn = connect(self.db_path)
            rows = _fetch(conn, _sel_u)
            conn.close()
        except Exception:
            rows = []
        if not rows:
            # v0.11.0: 无机物库自带的位点子集 (全库索引没有该编号时的回退)
            conn = self._inorg_db()
            if conn is not None:
                try:
                    rows = _fetch(conn, _sel_u)
                except Exception:
                    rows = []
        # v1.1.2 (W21 读侧): 与 cif_database._extract_atomic_sites 保持同一键集合。
        # cod_atomic_sites 目前没有 u_iso 列 (加列走版本化迁移, 见实施手册 W21),
        # 读不到时用 0.005 Å² 默认值并标记 u_iso_default, 使两个结构来源语义一致。
        out: list[dict] = []
        for r in rows:
            try:
                _u = r["u_iso"]
                _is_default = False
            except (IndexError, KeyError):
                _u, _is_default = 0.005, True
            if _u is None:
                _u, _is_default = 0.005, True
            out.append({
                "label": r["label"] or "", "element": r["element"],
                "x": r["x"], "y": r["y"], "z": r["z"],
                "occupancy": r["occupancy"],
                "u_iso": float(_u), "u_iso_default": _is_default,
            })
        return out

    # ── 转 Phase 模型 (供物相识别/精修使用) ──────────────────
    def get_phase(self, cod_id: int, lattice: Optional[LatticeParams] = None,
                  wavelength: float = 1.5406,
                  two_theta_range: tuple[float, float] = (10.0, 80.0),
                  use_pymatgen_peaks: bool = True) -> Optional[Phase]:
        """把 COD 条目转换为 Phase 对象，可直接放入 phase_identifier / rietveld_refiner。

        Args:
            cod_id: COD 编号
            lattice: 可选覆盖晶胞参数
            wavelength: X 射线波长 (Cu Kα = 1.5406 Å)，用于生成 reference_peaks
            two_theta_range: 参考峰计算范围 (度)
            use_pymatgen_peaks: True 则用 pymatgen 模拟 XRDCalculator 生成 reference_peaks
                                 (需要 atomic_sites 完整且 CIF 可被 pymatgen 加载)
        """
        entry = self.get_entry(cod_id)
        _cif_pre: Optional[str] = None
        if entry is None:
            # v0.11.0 修复: 无机库 cod_id 可能不在 cod_entries 索引里
            # (约 1 万个 1xx/4xx/7xx/8xx 编号), 与 get_cif 同样的 Level-0 回退:
            # 直接读 CIF 全文, 从 CIF 自身解析出 cell/formula/space group 重建条目
            _cif_pre = self.get_cif(cod_id)
            if _cif_pre is None:
                return None
            entry = parse_cif_text(_cif_pre, file_rel="", cod_id=int(cod_id), mtime=0)
            log.info(
                "get_phase: cod_id=%d not in cod_index, entry rebuilt from CIF "
                "(formula=%s, sg=%s)", cod_id, entry.formula, entry.space_group,
            )

        # 优先从 DB 读取原子位点 (精简模式, 不需要 CIF 全文)
        sites_fixed = self.get_atomic_sites(cod_id)

        # v0.15.2: DB 位点合法性校验 —— 部分 CIF (多 loop / NoSpherA2 等)
        # 建库时解析错位, 会存出数字"元素"行 (COD 1559793 实测 5331 行,
        # 元素列全是 hkl/坐标数值)。非法元素占比过高 → 视为无位点,
        # 走 CIF 全文解析兜底。
        if sites_fixed:
            from polyxrd.utils.formula_parser import VALID_ELEMENTS
            n_bad = sum(1 for s in sites_fixed
                        if str(s.get("element") or "") not in VALID_ELEMENTS)
            if n_bad > 0.3 * len(sites_fixed):
                log.info(
                    "get_phase: cod_id=%d DB atomic sites invalid "
                    "(%d/%d bad element labels) -> fallback to CIF parse",
                    cod_id, n_bad, len(sites_fixed),
                )
                sites_fixed = []

        # 如果 DB 中没有原子位点, 回退到 CIF 全文解析
        cif_text = _cif_pre
        if not sites_fixed and cif_text is None:
            cif_text = self.get_cif(cod_id)
            if cif_text is None:
                return None
        if not sites_fixed and cif_text:
            from polyxrd.services.cif_database import CIFDatabase
            parsed = CIFDatabase._parse_cif_content(cif_text)
            for s in (parsed.get("atomic_sites") or []):
                elem = _clean_elem_symbol(s.get("element") or s.get("type_symbol") or "")
                x = _cif_num(s.get("x") if "x" in s else s.get("fract_x"))
                y = _cif_num(s.get("y") if "y" in s else s.get("fract_y"))
                z = _cif_num(s.get("z") if "z" in s else s.get("fract_z"))
                occ = _cif_num(s.get("occupancy"))
                label = s.get("label") or f"{elem or 'X'}{len(sites_fixed)+1}"
                if elem and x is not None and y is not None and z is not None:
                    sites_fixed.append({
                        "label": label,
                        "element": elem,
                        "x": x, "y": y, "z": z,
                        "occupancy": occ if occ is not None else 1.0,
                    })
        # 最终兜底: 用 pymatgen 直接解析 CIF (自动展开对称操作, 兼容带电符号/乱序 loop)
        if not sites_fixed and cif_text:
            try:
                _struct = None
                try:
                    from pymatgen.core import Structure as _St
                    _struct = _St.from_str(cif_text, fmt="cif")
                except Exception:
                    # 占有率略超 1 (如 1.002/1.02) 会导致默认解析失败 → 放宽容差重试
                    from pymatgen.io.cif import CifParser
                    _parser = CifParser.from_str(cif_text, occupancy_tolerance=1.2)
                    _struct = _parser.parse_structures(primitive=False)[0]
                for site in _struct:
                    comp = site.species
                    try:
                        elem = comp.specie.symbol  # 单一组分位点
                    except Exception:
                        elem = max(comp, key=lambda sp: comp[sp]).symbol  # 无序位点取主元素
                    fx, fy, fz = site.frac_coords
                    sites_fixed.append({
                        "label": f"{elem}{len(sites_fixed)+1}",
                        "element": elem,
                        "x": float(fx), "y": float(fy), "z": float(fz),
                        "occupancy": 1.0,
                    })
                log.info("get_phase: cod_id=%d atomic sites from pymatgen CIF parse (%d sites)",
                         cod_id, len(sites_fixed))
            except Exception as e:
                log.debug("get_phase: pymatgen CIF fallback failed for %d: %s", cod_id, e)

        lat = lattice or LatticeParams(
            a=entry.a, b=entry.b, c=entry.c,
            alpha=entry.alpha, beta=entry.beta, gamma=entry.gamma,
        )
        name = entry.mineral_name or f"COD_{cod_id}"
        formula = entry.formula or ""
        sg = entry.space_group or ""

        # v0.15.2: 非对称单元 → 完整晶胞 (幂等, 已展开位点原样通过)。
        # DB 位点是 CIF 原子环的原始列表 (通常只有非对称单元), 直接按 P1
        # 建 Structure 会让高对称结构 (R-3c / 体心 / 面心 …) 的模拟峰整体
        # 错误 —— 实测 R-3c 方解石 104 主峰 (29.4°) 整个缺失、假峰 5.18°。
        try:
            from polyxrd.services.phase_cif import expand_sites_by_symmetry

            sites_fixed = expand_sites_by_symmetry(sites_fixed, sg)
        except Exception:  # noqa: BLE001 - 展开失败保持旧行为
            pass

        # v0.15.2: 密度保险丝 —— 展开后位点密度 >0.5 atoms/Å³ 必为解析垃圾
        # (真实晶体极限约 0.2; COD 1559793 垃圾位点实测 32.9/Å³)。
        if sites_fixed:
            try:
                _vol = lat.volume
                if _vol > 0 and len(sites_fixed) / _vol > 0.5:
                    log.info(
                        "get_phase: cod_id=%d site density %.2f/Å³ absurd "
                        "(%d sites, %.1f Å³) -> drop sites",
                        cod_id, len(sites_fixed) / _vol,
                        len(sites_fixed), _vol,
                    )
                    sites_fixed = []
            except Exception:  # noqa: BLE001
                pass

        # 元素集合
        _, element_csv = _parse_elements(formula)
        elements = set(e for e in element_csv.split(",") if e)

        cif_path = self.get_cif_path(cod_id)

        # 生成 reference_peaks (用 pymatgen)
        reference_peaks: list[tuple[tuple[int, int, int], float, float]] = []
        if use_pymatgen_peaks and sites_fixed:
            try:
                from pymatgen.core import Structure, Lattice
                from pymatgen.analysis.diffraction.xrd import XRDCalculator
                # 优先从 DB 原子位点直接构建 Structure (不需要 CIF 全文)
                pmg_lattice = Lattice.from_parameters(
                    lat.a, lat.b, lat.c,
                    lat.alpha, lat.beta, lat.gamma,
                )
                species = [s["element"] for s in sites_fixed]
                coords = [[s["x"], s["y"], s["z"]] for s in sites_fixed]
                struct = Structure(pmg_lattice, species, coords)
                xrd_calc = XRDCalculator(wavelength=wavelength)
                pattern = xrd_calc.get_pattern(struct, two_theta_range=two_theta_range)
                for i in range(len(pattern.x)):
                    hkl_info = pattern.hkls[i] if i < len(pattern.hkls) else []
                    hkl = (0, 0, 0)
                    if hkl_info and isinstance(hkl_info[0], dict):
                        raw = hkl_info[0].get("hkl", (0, 0, 0))
                        if len(raw) == 4:
                            # 六方/三方四指标 (h,k,i,l) → 保留 l (旧代码先被
                            # len>=3 分支截断成 (h,k,i), l 全丢 → 002 记成 (0,0,0))
                            hkl = (int(raw[0]), int(raw[1]), int(raw[3]))
                        elif len(raw) >= 3:
                            hkl = (int(raw[0]), int(raw[1]), int(raw[2]))
                    intensity = float(pattern.y[i]) if i < len(pattern.y) else 0.0
                    reference_peaks.append((hkl, float(pattern.x[i]), intensity))
            except Exception as e:
                log.debug("pymatgen XRD simulation (from DB sites) failed for COD %d: %s", cod_id, e)
                # 回退: 尝试从 CIF 全文
                if cif_text is None:
                    cif_text = self.get_cif(cod_id)
                if cif_text:
                    try:
                        from pymatgen.core import Structure as St2
                        struct2 = St2.from_str(cif_text, fmt="cif")
                        xrd_calc2 = XRDCalculator(wavelength=wavelength)
                        pattern2 = xrd_calc2.get_pattern(struct2, two_theta_range=two_theta_range)
                        for i in range(len(pattern2.x)):
                            hkl_info = pattern2.hkls[i] if i < len(pattern2.hkls) else []
                            hkl = (0, 0, 0)
                            if hkl_info and isinstance(hkl_info[0], dict):
                                raw = hkl_info[0].get("hkl", (0, 0, 0))
                                if len(raw) == 4:
                                    hkl = (int(raw[0]), int(raw[1]), int(raw[3]))
                                elif len(raw) >= 3:
                                    hkl = (int(raw[0]), int(raw[1]), int(raw[2]))
                            intensity = float(pattern2.y[i]) if i < len(pattern2.y) else 0.0
                            reference_peaks.append((hkl, float(pattern2.x[i]), intensity))
                    except Exception as e2:
                        log.debug("pymatgen XRD (from CIF fallback) failed for COD %d: %s", cod_id, e2)

        phase = Phase(
            name=name,
            formula=formula,
            space_group=sg,
            lattice=lat,
            atomic_sites=sites_fixed,
            reference_peaks=reference_peaks,
            cif_path=str(cif_path) if cif_path else None,
            elements=elements,
        )
        # 附加信息: 来源是 COD 和 id
        phase.cod_id = entry.cod_id  # type: ignore[attr-defined]
        return phase

    def __len__(self) -> int:
        s = self.stats()
        return int(s.get("total", 0))

    def __contains__(self, cod_id: int) -> bool:
        return self.get_entry(cod_id) is not None


# ──────────────────────────────────────────────────────────────
# 命令行入口: python -m polyxrd.services.cod_local build / search
# ──────────────────────────────────────────────────────────────

def _cli(argv: list[str]) -> int:
    cmd = argv[0] if argv else "help"
    if cmd == "build":
        # build [--tar <tar_path>] [cod_root]
        use_tar = False
        tar_file = None
        args = argv[1:]
        if args and args[0] == "--tar":
            use_tar = True
            args = args[1:]
            if args:
                tar_file = Path(args[0])
                args = args[1:]
        cod_root = Path(args[0]) if args else None
        indexer = CODLocalIndexer(cod_root=cod_root)

        def cb(done, total, proc, skip):
            if total > 0:
                pct = done / total * 100
                print(f"\r  Indexing: {done}/{total} ({pct:4.1f}%)  ok={proc} skip={skip}",
                      end="", flush=True)
            else:
                print(f"\r  Indexing from tar: {done} files  ok={proc} fail={done-proc}",
                      end="", flush=True)

        if use_tar and tar_file:
            stats = indexer.build_index_from_tar(tar_file, progress_cb=cb)
        else:
            stats = indexer.build_index(progress_cb=cb)
        print()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return 0
    if cmd == "stats":
        db = CODLocalDatabase()
        print(json.dumps(db.stats(), indent=2, ensure_ascii=False))
        return 0
    if cmd == "search" and len(argv) >= 3:
        key, value = argv[1], argv[2]
        db = CODLocalDatabase()
        kw = {key: value}
        results = db.search(limit=int(argv[3]) if len(argv) > 3 else 20, **kw)
        for r in results:
            print(f"{r.cod_id:>8}  {r.formula_red:20s}  {r.space_group:12s}  "
                  f"a={r.a:g} V={r.volume:g}  {r.mineral_name}")
        return 0
    print("Usage: cod_local.py (build [cod_root] | stats | search <key> <val> [limit])\n"
          "       key: formula / mineral_name / space_group / space_group_number / cod_id\n"
          "       example: search formula SiO2 10")
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
