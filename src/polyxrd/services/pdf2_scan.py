"""ICDD PDF-2 2004 定宽流解析器（纯解析，不落库）
=================================================

本模块只把 ``C:\\pdf2\\pdf2.dat`` 那种 **80 字符定宽、无换行**的 ICDD
PDF-2 2004 原始流解析成 :class:`PDF2Record`，不涉及任何存储格式。

历史上解析与「建 SQLite 索引 + SQLite 查询」混在 ``pdf2_database.py`` 里。
v5.2 起 PDF2 统一走 polyDB 外挂库格式（见
``docs/外挂库格式规范-polyDB-v4.md``），旧的 sqlite 通道已删除，解析器单独
留在这里供 :mod:`scripts.build_pdf2_polydb` 使用。

格式要点（列位全部经 85,013~163,834 条记录逐条核对）
---------------------------------------------------
每个物相记录由若干子记录组成，以 ``PddddddX<code>`` 标识（标记固定落在
第 71 列起，前后两个字母都会变，不能硬编码）：

    X1 主记录起始 / X2 最强线 / X3 **空间群 + 常规胞体积** /
    X4 分子量 / X5 元素·CAS / X6 **名称（按类别 P/M/C/Z 分开）** /
    X7 原始化学式 / X8 规范化化学式 / X9 文献 / XA Pearson /
    XC 变换矩阵（不入库）/ XD 约化胞 / XE **常规胞** / XF 辐射 /
    XG 质量标记 / XI **d-I 峰表** / XB 注释 / XK 记录结束
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, Optional

RECORD_LINE_SIZE = 80
_D_FIELD_SIZE = 7
_I_FIELD_SIZE = 3
_PAIR_OFFSETS = (0, 23, 46)  # 每行 3 对 d-I，列宽 23 字符 (d=7 + I=3 + pad=13)


class PDF2Record:
    """单个 PDF2 物相记录的解析结果。"""

    __slots__ = (
        "pdf2_id", "formula", "formula_norm",
        "name", "mineral", "space_group", "cell_a", "cell_b", "cell_c",
        "cell_alpha", "cell_beta", "cell_gamma",
        "space_group_num", "space_group_setting", "space_group_flag",
        "cell_vol",
        "red_a", "red_b", "red_c", "red_alpha", "red_beta", "red_gamma",
        "red_vol", "pearson",
        "n_peaks", "peaks_d", "peaks_i",
        "molecular_weight", "cas_number", "radiation",
        "quality", "reference", "comment",
        "record_offset", "record_size",
    )

    def __init__(self) -> None:
        self.pdf2_id: int = 0
        self.formula: str = ""
        self.formula_norm: str = ""
        self.name: str = ""
        self.mineral: str = ""
        # ── 常规晶胞 (类型 E) + 空间群 (类型 3) ──
        self.space_group: str = ""
        self.space_group_num: int = 0
        self.space_group_setting: str = ""
        self.space_group_flag: str = ""
        self.cell_a: Optional[float] = None
        self.cell_b: Optional[float] = None
        self.cell_c: Optional[float] = None
        self.cell_alpha: Optional[float] = None
        self.cell_beta: Optional[float] = None
        self.cell_gamma: Optional[float] = None
        self.cell_vol: Optional[float] = None
        # ── 约化晶胞 (类型 D) ──
        self.red_a: Optional[float] = None
        self.red_b: Optional[float] = None
        self.red_c: Optional[float] = None
        self.red_alpha: Optional[float] = None
        self.red_beta: Optional[float] = None
        self.red_gamma: Optional[float] = None
        self.red_vol: Optional[float] = None
        self.pearson: str = ""
        # ── 峰/文本 ──
        self.n_peaks: int = 0
        self.peaks_d: list[float] = []
        self.peaks_i: list[float] = []
        self.molecular_weight: Optional[float] = None
        self.cas_number: str = ""
        self.radiation: str = ""
        self.quality: str = ""
        self.reference: str = ""
        self.comment: str = ""
        self.record_offset: int = 0
        self.record_size: int = 0


def _parse_xi_peaks(line: str) -> list[tuple[float, float]]:
    """解析一行 XI d-I 数据（每行 3 对，d 7 字符 + I 3 字符）。"""
    peaks: list[tuple[float, float]] = []
    for offset in _PAIR_OFFSETS:
        d_str = line[offset:offset + _D_FIELD_SIZE].strip()
        i_str = line[offset + _D_FIELD_SIZE:offset + _D_FIELD_SIZE + _I_FIELD_SIZE].strip()
        if not d_str:
            continue
        try:
            d_val = float(d_str)
        except ValueError:
            continue
        if d_val <= 0.0 or d_val > 100.0:
            continue
        try:
            i_val = float(i_str) if i_str else 0.0
        except ValueError:
            i_val = 0.0
        if i_val > 100.0:
            i_val = 100.0
        peaks.append((d_val, i_val))
    return peaks


# ── 对称性字段 (类型 3 / A / D / E) ──────────────────────────
# 数值字段允许带尾随 'E' (ICDD 用来标记"估计值"), 如 "2.680E"。
_RE_FLOAT_E = re.compile(r"^(\d*\.?\d+)E?$")

_SG_SYM_SLICE = slice(0, 8)
_SG_FLAG_SLICE = slice(8, 11)
_SG_NUM_SLICE = slice(11, 14)
_SG_SETTING_INDEX = 14
_SG_TAIL_START = 15


def _num(tok: str) -> Optional[float]:
    m = _RE_FLOAT_E.match(tok)
    return float(m.group(1)) if m else None


def _parse_cell_fields(data: str, n_expected: int) -> Optional[tuple[float, ...]]:
    """从一行取前 n_expected 个数值 → (a, b, c, α, β, γ)。"""
    toks = data.split()
    if len(toks) < n_expected:
        return None
    vals: list[float] = []
    for t in toks[:n_expected]:
        v = _num(t)
        if v is None:
            return None
        vals.append(v)
    return tuple(vals)


def _parse_symmetry_line(data: str, rec: PDF2Record) -> None:
    """解析类型 3 行：空间群 + 常规晶胞体积。

    cols 0~7 空间群符号 / 8~10 标志 / 11~13 空间群号（0=未定）/
    col 14 设置字母 / 15~ Z·密度·**常规晶胞体积**（末字段）。

    Z 与两个密度字段**有意不入库**（同一卡片内可互相矛盾，见
    ``docs/PDF2-2004重建验收报告-20261028.md``）。
    """
    sym = data[_SG_SYM_SLICE].strip()
    flag = data[_SG_FLAG_SLICE].strip()
    num_raw = data[_SG_NUM_SLICE].strip()
    num = int(num_raw) if num_raw.isdigit() else 0

    rec.space_group_flag = flag
    if num > 0:
        rec.space_group = sym
        rec.space_group_num = num
        rec.space_group_setting = data[_SG_SETTING_INDEX].strip()
    else:
        # 号 = 0 时 0~7 列是 Bravais 点阵字母（P/A/B/C/I/F/R），不是空间群符号。
        rec.space_group = ""
        rec.space_group_num = 0
        rec.space_group_setting = ""

    tail = data[_SG_TAIL_START:].split()
    if not tail:
        return
    # 末字段为常规晶胞体积，判据 = 含小数点（Z 永远是纯整数）。
    if "." in tail[-1]:
        vol = _num(tail[-1])
        if vol is not None and vol > 0.0:
            rec.cell_vol = vol


def _parse_pearson_line(data: str, rec: PDF2Record) -> None:
    toks = data.split()
    if toks:
        rec.pearson = toks[0][:3]


# ── 记录标记定位 ─────────────────────────────────────────────
# 标记固定落在 field 第 71 列 (0-based) 起 —— 实测 400,000 个标记无一例外。
# 结构: <数据集字母><6 位卡片号><序列字母><子记录类型><序号?>
_RE_RECORD_ID = re.compile(
    r".{71}([A-Z])(\d{6})([A-Z])([A-Z0-9+*])(\d{0,2})")

# 第 67~70 列对多数子记录是标志区（"G"/"DB 1"/"SM 2"），混进 formula 会污染
# 元素过滤；但类型 3 的晶胞体积恰好落在 63~68 列，必须截到 69。
_DATA_END_DEFAULT = 67
_DATA_END_BY_CODE = {"3": 69}


def _data_area(line: str, code: str) -> str:
    return line[: _DATA_END_BY_CODE.get(code, _DATA_END_DEFAULT)].rstrip()


def parse_pdf2_record(lines: list[str], offset: int) -> Optional[PDF2Record]:
    """解析一个完整记录（X1..XK）；``pdf2_id == 0`` 视为失败返回 None。"""
    rec = PDF2Record()
    rec.record_offset = offset
    rec.record_size = len(lines) * RECORD_LINE_SIZE

    for line in lines:
        m = _RE_RECORD_ID.match(line)
        if not m:
            continue
        rec.pdf2_id = int(m.group(2))
        code = m.group(4)
        data = _data_area(line, code)

        if code == "1":
            pass
        elif code == "3":
            _parse_symmetry_line(data, rec)
        elif code == "4":
            for p in data.split():
                try:
                    rec.molecular_weight = float(p)
                    break
                except ValueError:
                    continue
        elif code == "5":
            stripped = data.strip()
            if stripped and ("-" in stripped or stripped.isdigit()):
                rec.cas_number = stripped
        elif code == "6":
            # cols 67~68 是名称类别: P=主名称 M=矿物名 C=俗名 Z=沸石名。
            name = data.strip()
            if name.startswith("$"):
                name = name[1:]
            kind = line[67:69].strip()
            if kind == "M":
                rec.mineral = name
            elif kind in ("", "P"):
                rec.name = name
            elif not rec.name:
                rec.name = name
        elif code == "7":
            rec.formula = data.strip()
        elif code == "8":
            rec.formula_norm = data.strip()
        elif code == "9":
            rec.reference = data.strip()
        elif code == "F":
            parts = data.strip().split()
            if parts:
                rec.radiation = parts[0]
        elif code == "G":
            rec.quality = data.strip()[:2]
        elif code == "I":
            for d_val, i_val in _parse_xi_peaks(line):
                rec.peaks_d.append(d_val)
                rec.peaks_i.append(i_val)
        elif code == "A":
            _parse_pearson_line(data, rec)
        elif code == "C":
            # 变换矩阵语义无法自证，有意不入库。
            pass
        elif code == "D":
            cell = _parse_cell_fields(data, 6)
            if cell:
                (rec.red_a, rec.red_b, rec.red_c,
                 rec.red_alpha, rec.red_beta, rec.red_gamma) = cell
                toks = data.split()
                if len(toks) > 6:
                    rec.red_vol = _num(toks[6])
        elif code == "E":
            cell = _parse_cell_fields(data, 6)
            if cell:
                (rec.cell_a, rec.cell_b, rec.cell_c,
                 rec.cell_alpha, rec.cell_beta, rec.cell_gamma) = cell
        elif code == "B":
            rec.comment = data.strip()
        elif code == "K":
            break

    if rec.pdf2_id == 0:
        return None
    rec.n_peaks = len(rec.peaks_d)
    if not rec.formula and rec.formula_norm:
        rec.formula = rec.formula_norm
    return rec


def iter_pdf2_records(raw_path: str | Path) -> Iterator[PDF2Record]:
    """逐记录迭代 PDF2-2004 定宽流（163,834 相，约 588 MB）。"""
    raw_path = Path(raw_path)
    file_size = raw_path.stat().st_size
    buf: list[str] = []
    rec_start_offset = 0

    with open(raw_path, "rb") as f:
        offset = 0
        while offset < file_size:
            chunk = f.read(RECORD_LINE_SIZE * 4096)
            if not chunk:
                break
            n_lines = len(chunk) // RECORD_LINE_SIZE
            for i in range(n_lines):
                start = i * RECORD_LINE_SIZE
                line = chunk[start:start + RECORD_LINE_SIZE].decode(
                    "ascii", errors="replace")
                m = _RE_RECORD_ID.match(line)
                if m and m.group(4) == "1" and buf:
                    rec = parse_pdf2_record(buf, rec_start_offset)
                    if rec:
                        yield rec
                    buf = []
                    rec_start_offset = offset + start
                buf.append(line)
            offset += n_lines * RECORD_LINE_SIZE

    if buf:
        rec = parse_pdf2_record(buf, rec_start_offset)
        if rec:
            yield rec


__all__ = ["PDF2Record", "RECORD_LINE_SIZE", "iter_pdf2_records",
           "parse_pdf2_record"]
