"""
PDF2-2004 数据库服务
====================

将 ICDD PDF-2 2004 版二进制/定宽文本数据库 (pdf2 - 2004.dat + codens.dat)
解析为 SQLite 索引，提供与 COD 无机物库相同的检索接口
(search_by_d_peaks / get_phase / search_phases)，可直接接入
CIFDatabase 的热切换机制和 PhaseIdentifier 的物相识别流程。

PDF-2 2004 定宽格式 (每行 80 字符 ASCII):
    每个物相记录由若干子记录组成，以 PddddddX<code> 标识:
      X1 — 主记录起始 (M 编号 + 已发布标记)
      X2 — 最强线 d 值 (E 记法) + 卡片质量标记
      X3 — **空间群** + 对称性数值 (见下)
      X4 — 分子量 + 附加数值
      X5 — 元素符号 / CAS 号
      X6 — 矿物/化合物名称
      X7 — 化学式 (原始写法)
      X8 — 化学式 (规范化)
      X9 — 文献引用
      XA — Pearson 符号 (晶系+点阵) + 数值
      XC — 约化晶胞 → 常规晶胞 的变换矩阵
      XD — **约化晶胞** a,b,c,α,β,γ + 体积
      XE — **常规晶胞** a,b,c,α,β,γ + a/b, c/b
      XF — 辐射类型 + 标记
      XG — 质量标记
      XH — (罕见)
      XI — d-I 峰数据 (每行 3 对, d=7 字段+I=3 字段)
      X+ — Hanawalt 组 (按强度降序)
      X* — Hanawalt 组 (按 d 升序)
      XB — 注释 (可选)
      XK — 录入/维护信息

**类型 3 / E 的精确列位** (实测 85,013 条记录逐条核对, 见 tests/test_pdf2_space_group.py):

    类型 3:  cols 0~7   空间群符号 (Hermann-Mauguin 短符号, 8 字符左对齐;
                        未知时填 Bravais 点阵字母 P/A/B/C/I/F/R 或留空)
             cols 8~10  标志位 ('E' / '*' / 空; '*' 表示符号含未定字符)
             cols 11~13 空间群号 (右对齐, 0 = 未定)
             col  14    设置字母 (A~F, 空 = 标准设置; 如 14A=P21/c, 14B=P21/a)
             col  15~   Z / 计算密度 / 实测密度 / 常规晶胞体积 (末字段为体积)

    类型 E:  a(8) b(8) c(8) α(8) β(8) γ(8) [a/b, c/b]  —— 即**常规晶胞**
    类型 D:  a b c α β γ + **体积** (末尾另有 1 个与数据无关的序号列)
    类型 A:  Pearson 符号 (cF/oP/hR/aP...), '?' 表示未定

    ⚠️ 类型 3 的 Z / 密度字段**有意不入库**: 45,557 条"约化胞 ≠ 常规胞"
    的卡片里约 20% 无法用任何单一晶胞自洽复现 (Z 来自原始文献、Dx 由
    ICDD 另算, 二者可互相矛盾)。只保留体积 —— 它与类型 E 六参数算出的
    体积在 133,925 条中 132,939 条 (99.264%) 吻合到 <0.5%。

    实测覆盖率 (163,834 相): 晶胞 81.8%, 空间群 72.8%, 主名称 100%,
    矿物名 10.8%。老 Hanawalt 卡片 (1930~50 年代) 本就没有晶胞, 缺失属正常。

    ⚠️ 类型 E 的常规晶胞已验证: 对外暴露的 cell_a..cell_gamma 取**类型 E**,
    不是约化晶胞 (类型 D) —— 方解石 E = 4.983/4.983/17.019/90/90/120 与
    文献一致, D 是菱面体原胞 (a=4.983, c=6.361, γ=60)。

    ⚠️ 类型 3 末尾的报告体积**有 986 条 (0.736%) 与 E 胞对不上**, 且分布是
    双峰的 —— 99.264% 精确吻合 (<0.5%), 0.736% 差 >10%, **中间 0.5~10%
    一条都没有**。这是 ICDD 的数据口径差异而非解析错误 (解析错会糊在中间):
      · 321 条 hR 相: 报告的是菱面体原胞体积 (E 胞的 1/3)
        —— 如 700280 R-3m, E 胞 V=780.0, 报告 260.01 = V_D;
      · 654 条 aP/tI/mP 相: 报告的是 E 胞的 2 倍 (原始文献用了超胞)
        —— 如 21213 mP, E 胞 V=743.94, 报告 1487.88 = 2×。
    故 cell_vol 一律用**入库六参数自算** (与 a,b,c,α,β,γ 自洽), 报告值只
    用来驱动建库哨兵 vol_mismatch。

用法:
    builder = PDF2DatabaseBuilder()
    builder.build(raw_path, sqlite_path)   # 首次构建

    db = PDF2Database(sqlite_path)
    results = db.search_by_d_peaks(d_list, i_list, ...)
    phase = db.get_phase(pdf2_id)
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("polyxrd.pdf2")

RECORD_LINE_SIZE = 80
_D_FIELD_SIZE = 7
_I_FIELD_SIZE = 3
_PAIR_OFFSETS = (0, 23, 46)  # 每行 3 对 d-I，列宽 23 字符 (d=7 + I=3 + pad=13)


# ──────────────────────────────────────────────────────────────
# 解析器
# ──────────────────────────────────────────────────────────────

class _PDF2Record:
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

    def __init__(self):
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
    """解析一行 XI d-I 数据 (每行 3 对)。

    格式: d(7字符) I(3字符) × 3, 末尾有行号+记录ID。
    d=0 或空行 → 跳过。
    """
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
    """解析可能带 'E' 后缀的数值 token; 非法返回 None。"""
    m = _RE_FLOAT_E.match(tok)
    return float(m.group(1)) if m else None


def _parse_cell_fields(data: str, n_expected: int) -> Optional[tuple[float, ...]]:
    """从一行中取前 n_expected 个数值 → (a, b, c, α, β, γ)。

    类型 D/E 都是空格分隔的定宽数值, 用 split 比硬编码列宽稳健。
    """
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


def _parse_symmetry_line(data: str, rec: _PDF2Record) -> None:
    """解析类型 3 行: 空间群 + 常规晶胞体积。

    列位 (实测 85,013 条记录逐条核对):
        0~7   空间群符号 (若空间群号 = 0, 这里放的是 Bravais 点阵字母)
        8~10  标志 ('E'/'*')
        11~13 空间群号 (0 = 未定)
        14    设置字母 (A~F)
        15~   Z / 计算密度 / 实测密度 / **常规晶胞体积** (末字段)

    ⚠️ cols 15~ 里的 Z 与两个密度字段**故意不入库**: 实测 45,557 条
    "约化胞 ≠ 常规胞" 的卡片中, 约 2,586 条只能用常规胞复现 Dx、2,850 条
    只能用约化胞、3,770 条两者都不成立 —— Z 取自原始文献、Dx 由 ICDD 另
    算, 同一卡片内两者可以互相矛盾 (刚玉 Al2O3 报 Z=2 但 Dx=3.97 是按
    Z=6 的六方胞算的)。存一个自相矛盾的密度只会误导筛选, 故只取末字段
    体积 —— 它与类型 E 的六参数算出的体积 100% 吻合 (见建库哨兵
    vol_mismatch)。
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
        # 号 = 0 → 空间群未定。0~7 列此时是 P/A/B/C/I/F/R (Bravais 点阵),
        # 若直接当符号收下, 就会把点阵字母 "F" 当成空间群 F —— 只有
        # "R-3c / 167" 这类才是真值。故此处显式清空。
        rec.space_group = ""
        rec.space_group_num = 0
        rec.space_group_setting = ""

    tail = data[_SG_TAIL_START:].split()
    if not tail:
        return
    # 末字段为常规晶胞体积, 判据 = 含小数点。Z 永远是纯整数 (2/4/8/16/32),
    # 而报告体积一律写成两位小数 (94.67 / 2645.77 / 3884.70) —— 用小数点
    # 区分可避免把"只有 Z 没有体积"的行把 Z 误当成体积。
    if "." in tail[-1]:
        vol = _num(tail[-1])
        if vol is not None and vol > 0.0:
            rec.cell_vol = vol


def _parse_pearson_line(data: str, rec: _PDF2Record) -> None:
    """解析类型 A 行: Pearson 符号 (如 cF / oP / hR / aP, '?' 表示未定)。"""
    toks = data.split()
    if toks:
        rec.pearson = toks[0][:3]


# ── 记录标记定位 ─────────────────────────────────────────────
# PDF-2 2004 原始文件是**无换行的 80 字符定宽流**, 每条子记录标记固定
# 落在 field 的第 71 列 (0-based) 起 —— 实测 400,000 个标记无一例外。
# 标记 token 结构: <序列字母><6位卡片号><序列字母><子记录类型><序号?>
#
# ⚠️ 两个字母都会变, 不能硬编码:
#   - 第 1 位是数据集标识 (P=在库, D=已删除...)
#   - 第 3 位随卡片递增 (石英 470715 全用 X, 方解石 010837 全用 R,
#     211487 用 H) —— 32 MB 样本实测分布 X 35% / C 15% / O 14% / M 11% ...
# 旧版正则硬编码 P...X... 只匹配到约 35% 的卡片, 且跨卡片串数据
# (方解石 010837 的 formula 在 D010837R7 上, 完全抓不到)。
_RE_RECORD_ID = re.compile(
    r".{71}([A-Z])(\d{6})([A-Z])([A-Z0-9+*])(\d{0,2})")

# ── 各子记录的数据区右边界 ───────────────────────────────────
# 第 67~70 列对**多数**子记录是标志区, 不是数据: 实测出现孤立 "G"、
# 续行标记 "DB 1"/"SM 2"/" P " 等 —— 混进 formula 会把 "G" 当成元素,
# 污染元素过滤 (实测 4342/163834 条被污染), 所以默认截到 67 列。
#
# 但**类型 3 是例外**: 它的晶胞体积字段恰好落在 63~68 列 (全库 35,020 行
# 逐行核对, 末位非空格字符 100% 在第 68 列), 按 67 列截断会把 "365.97"
# 砍成 "365." → 体积全丢, 还顺带让建库哨兵 vol_mismatch 永远静默为 0
# (2026-09-10 由 tests/test_pdf2_space_group.py 抓出)。
_DATA_END_DEFAULT = 67
_DATA_END_BY_CODE = {"3": 69}


def _data_area(line: str, code: str) -> str:
    """取一行子记录的数据区 (按类型选右边界, 见 _DATA_END_BY_CODE)。"""
    return line[: _DATA_END_BY_CODE.get(code, _DATA_END_DEFAULT)].rstrip()



def parse_pdf2_record(lines: list[str], offset: int) -> Optional[_PDF2Record]:
    """解析一个完整的 PDF2 记录 (从 X1 行到 XK 行)。

    Args:
        lines: 该记录的所有 80 字符定宽行
        offset: 该记录在原始文件中的字节偏移

    Returns:
        _PDF2Record 或 None (解析失败)
    """
    rec = _PDF2Record()
    rec.record_offset = offset
    rec.record_size = len(lines) * RECORD_LINE_SIZE

    for line in lines:
        # 标记固定在第 71 列 (见 _RE_RECORD_ID 注释), 数据 = 同 field 前缀
        m = _RE_RECORD_ID.match(line)
        if not m:
            continue
        rec.pdf2_id = int(m.group(2))
        code = m.group(4)
        data = _data_area(line, code)

        if code == "1":
            # X1: 主记录起始, 不含额外信息
            pass
        elif code == "3":
            # X3: 空间群 + Z / 密度 / 常规晶胞体积
            _parse_symmetry_line(data, rec)
        elif code == "4":
            # X4: 分子量 + 其他数值
            parts = data.split()
            for p in parts:
                try:
                    rec.molecular_weight = float(p)
                    break
                except ValueError:
                    continue
        elif code == "5":
            # X5: 元素符号 / CAS 号
            stripped = data.strip()
            if stripped and ("-" in stripped or stripped.isdigit()):
                rec.cas_number = stripped
        elif code == "6":
            # X6: 名称。cols 67~68 是名称类别: P=主名称 M=矿物名 C=俗名/商品名
            # Z=沸石名 (实测占比 P 78% / M 16% / C 3% / Z 0.3%)。
            # 必须按类别分开存: 旧版按行的先后覆盖 name, 结果方解石的名字
            # 变成矿物名 "Calcite" 而不是主名称 "Calcium Carbonate Oxide"。
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
            # X7: 化学式 (原始写法)
            rec.formula = data.strip()
        elif code == "8":
            # X8: 化学式 (规范化)
            rec.formula_norm = data.strip()
        elif code == "9":
            # X9: 文献引用
            rec.reference = data.strip()
        elif code == "F":
            # XF: 辐射类型 + 标记
            parts = data.strip().split()
            if parts:
                rec.radiation = parts[0]
        elif code == "G":
            # XG: 质量标记
            rec.quality = data.strip()[:2]
        elif code == "I":
            # XI: d-I 峰数据
            peaks = _parse_xi_peaks(line)
            rec.peaks_d.extend(p[0] for p in peaks)
            rec.peaks_i.extend(p[1] for p in peaks)
        elif code == "A":
            # XA: Pearson 符号 (晶系 + 点阵类型)
            _parse_pearson_line(data, rec)
        elif code == "C":
            # XC: 约化晶胞 ↔ 常规晶胞 的变换矩阵。实测对菱面体相 (方解石
            # D010837RC 给单位矩阵) 与 D/E 两胞明显不同构, 语义无法自证,
            # 宁可不入库也不记一个可能误导的字段。
            pass
        elif code == "D":
            # XD: 约化晶胞 a,b,c,α,β,γ + 体积 (末列另有无关键序号)
            cell = _parse_cell_fields(data, 6)
            if cell:
                (rec.red_a, rec.red_b, rec.red_c,
                 rec.red_alpha, rec.red_beta, rec.red_gamma) = cell
                toks = data.split()
                if len(toks) > 6:
                    rec.red_vol = _num(toks[6])
        elif code == "E":
            # XE: **常规晶胞** a,b,c,α,β,γ (后随 a/b, c/b 比值, 不消费)
            cell = _parse_cell_fields(data, 6)
            if cell:
                (rec.cell_a, rec.cell_b, rec.cell_c,
                 rec.cell_alpha, rec.cell_beta, rec.cell_gamma) = cell
        elif code == "B":
            # XB: 注释
            rec.comment = data.strip()
        elif code == "K":
            # XK: 维护信息, 记录结束
            break

    if rec.pdf2_id == 0:
        return None
    rec.n_peaks = len(rec.peaks_d)
    if not rec.formula and rec.formula_norm:
        rec.formula = rec.formula_norm
    return rec


def iter_pdf2_records(raw_path: Path):
    """逐记录迭代 PDF2-2004 .dat 文件。

    Yields:
        (_PDF2Record, offset, size)
    """
    file_size = raw_path.stat().st_size
    buf: list[str] = []
    rec_start_offset = 0

    with open(raw_path, "rb") as f:
        offset = 0
        while offset < file_size:
            chunk = f.read(RECORD_LINE_SIZE * 4096)
            if not chunk:
                break
            # 按 80 字符切行
            n_lines = len(chunk) // RECORD_LINE_SIZE
            for i in range(n_lines):
                start = i * RECORD_LINE_SIZE
                end = start + RECORD_LINE_SIZE
                raw_line = chunk[start:end]
                line = raw_line.decode("ascii", errors="replace")

                # 检测新记录起始 (类型 1 行 = 主记录)
                m = _RE_RECORD_ID.match(line)
                if m and m.group(4) == "1" and buf:
                    # 前一个记录结束
                    rec = parse_pdf2_record(buf, rec_start_offset)
                    if rec:
                        yield rec
                    buf = []
                    rec_start_offset = offset + start

                buf.append(line)
            offset += n_lines * RECORD_LINE_SIZE

    # 最后一个记录
    if buf:
        rec = parse_pdf2_record(buf, rec_start_offset)
        if rec:
            yield rec


# ──────────────────────────────────────────────────────────────
# SQLite 建库
# ──────────────────────────────────────────────────────────────

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS phases (
    cod_id              INTEGER PRIMARY KEY,
    formula             TEXT,
    name                TEXT,
    mineral             TEXT,
    space_group         TEXT,
    space_group_num     INTEGER,
    space_group_setting TEXT,
    cell_a              REAL,
    cell_b              REAL,
    cell_c              REAL,
    cell_alpha          REAL,
    cell_beta           REAL,
    cell_gamma          REAL,
    cell_vol            REAL,
    red_a               REAL,
    red_b               REAL,
    red_c               REAL,
    red_alpha           REAL,
    red_beta            REAL,
    red_gamma           REAL,
    red_vol             REAL,
    pearson             TEXT,
    n_peaks             INTEGER,
    peaks_d             TEXT,
    peaks_i             TEXT,
    record_offset       INTEGER,
    record_size         INTEGER,
    ref_id              TEXT,
    display_id          TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);
CREATE TABLE IF NOT EXISTS parse_errors (
    cod_id      INTEGER PRIMARY KEY,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_formula ON phases(formula);
CREATE INDEX IF NOT EXISTS idx_sg_num ON phases(space_group_num);
"""

# 列顺序与 _SCHEMA_SQL 必须一致 (建库用 VALUES 占位插入)
_INSERT_SQL = (
    "INSERT OR REPLACE INTO phases VALUES "
    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
    "?, ?, ?, ?, ?, ?, ?, ?)"
)
_N_COLUMNS = 29


class PDF2DatabaseBuilder:
    """PDF2-2004 → SQLite 索引构建器。"""

    def __init__(self, raw_path: Path, db_path: Path):
        self.raw_path = Path(raw_path)
        self.db_path = Path(db_path)

    def build(self, progress_cb=None) -> dict:
        """构建 SQLite 索引。

        Args:
            progress_cb: 可选回调 (n_processed: int) -> None

        Returns:
            统计字典 {total, ok, bad, elapsed_s, with_cell, with_sg,
                     sg_unknown, with_name, vol_mismatch}

            其中 vol_mismatch = 用类型 E 常规晶胞算出的体积与类型 3 报告体积
            相差 >2% 的记录数 —— 作为**解析布局的哨兵指标**: 列位一旦读错,
            这个数会从 ~986 跳到几万 (2026-09-10 就靠它发现类型 3 的体积字段
            落在 63~68 列、被 67 列截断而整体丢失)。
            正常值 ≈ 986 / 133,935 (0.74%), 全部是 ICDD 报告体积按别的晶胞
            口径给出所致 (见模块 docstring), 不是解析问题。
        """
        import time
        from polyxrd.utils.math_utils import lattice_volume

        t0 = time.time()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()

        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(_SCHEMA_SQL)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")

        total = ok = bad = 0
        with_cell = with_sg = sg_unknown = vol_mismatch = with_name = 0
        batch: list[tuple] = []

        for rec in iter_pdf2_records(self.raw_path):
            total += 1
            if rec.n_peaks == 0:
                bad += 1
                conn.execute(
                    "INSERT OR IGNORE INTO parse_errors VALUES (?, ?)",
                    (rec.pdf2_id, "no peaks"),
                )
                continue
            # 公式规范化: 与 COD 一致 (空格分隔 "元素+系数" 组)
            formula = rec.formula_norm or rec.formula
            peaks_d_str = ",".join(f"{d:.5f}" for d in rec.peaks_d)
            peaks_i_str = ",".join(f"{i:.1f}" for i in rec.peaks_i)
            display_id = f"PDF2-{rec.pdf2_id:06d}"
            ref_id = f"PDF2-{rec.pdf2_id:06d}"

            # 常规晶胞体积以自有 a,b,c,α,β,γ 算出为准 (与入库字段自洽);
            # 类型 3 报告值只用来交叉校验解析是否正确。
            vol_calc: Optional[float] = None
            if rec.cell_a and rec.cell_b and rec.cell_c:
                vol_calc = lattice_volume(
                    rec.cell_a, rec.cell_b, rec.cell_c,
                    rec.cell_alpha or 90.0, rec.cell_beta or 90.0,
                    rec.cell_gamma or 90.0,
                )
                if not (vol_calc > 0):
                    vol_calc = None
            if vol_calc is not None:
                if rec.cell_vol and abs(rec.cell_vol - vol_calc) / vol_calc > 0.02:
                    vol_mismatch += 1
                rec.cell_vol = vol_calc
                with_cell += 1
            if rec.space_group_num > 0:
                with_sg += 1
            else:
                sg_unknown += 1
            if rec.name:
                with_name += 1

            batch.append((
                rec.pdf2_id, formula, rec.name, rec.mineral,
                rec.space_group, rec.space_group_num, rec.space_group_setting,
                rec.cell_a, rec.cell_b, rec.cell_c,
                rec.cell_alpha, rec.cell_beta, rec.cell_gamma, rec.cell_vol,
                rec.red_a, rec.red_b, rec.red_c,
                rec.red_alpha, rec.red_beta, rec.red_gamma, rec.red_vol,
                rec.pearson,
                rec.n_peaks, peaks_d_str, peaks_i_str,
                rec.record_offset, rec.record_size,
                ref_id, display_id,
            ))
            assert len(batch[-1]) == _N_COLUMNS

            if len(batch) >= 5000:
                conn.executemany(_INSERT_SQL, batch)
                batch.clear()
                ok += 5000
                if progress_cb:
                    progress_cb(ok)
                conn.commit()

        if batch:
            conn.executemany(_INSERT_SQL, batch)
            ok += len(batch)
            batch.clear()

        meta_rows = {
            "source": "ICDD PDF-2 2004",
            "build_date": str(int(t0)),
            "raw_file": str(self.raw_path),
            "with_cell": str(with_cell),
            "with_sg": str(with_sg),
            "sg_unknown": str(sg_unknown),
            "with_name": str(with_name),
            "vol_mismatch": str(vol_mismatch),
        }
        conn.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)", list(meta_rows.items())
        )
        conn.commit()
        conn.close()

        elapsed = time.time() - t0
        stats = {
            "total": total,
            "ok": ok,
            "bad": bad,
            "elapsed_s": round(elapsed, 1),
            "with_cell": with_cell,
            "with_sg": with_sg,
            "sg_unknown": sg_unknown,
            "with_name": with_name,
            "vol_mismatch": vol_mismatch,
        }
        log.info(
            "PDF2 build done: %d total, %d ok, %d bad, cell=%d sg=%d vol_mismatch=%d, %.1fs",
            total, ok, bad, with_cell, with_sg, vol_mismatch, elapsed,
        )
        return stats


# ──────────────────────────────────────────────────────────────
# 查询服务
# ──────────────────────────────────────────────────────────────

class PDF2Database:
    """PDF2-2004 SQLite 查询服务 (只读)。

    提供与 CIFDatabase 的 COD 查询相同的接口,
    可直接接入 PhaseIdentifier 物相识别流程。
    """

    def __init__(self, db_path: Optional[Path] = None):
        from polyxrd.config import get_config
        self._config = get_config()
        self._db_path = Path(db_path) if db_path else self._config.get_pdf2_db_path()
        self._conn: Optional[sqlite3.Connection] = None

    # ── 连接管理 ────────────────────────────────────────────

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        """懒加载 SQLite 连接。"""
        if self._conn is not None:
            return self._conn
        if not self._db_path.exists():
            return None
        self._conn = sqlite3.connect(
            f"file:{self._db_path}?mode=ro", uri=True, check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def reload(self) -> None:
        """关闭当前连接,下次访问时重新连接。"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def is_available(self) -> bool:
        """数据库是否可用。"""
        return self._db_path.exists()

    def phase_count(self) -> int:
        """物相总数。"""
        conn = self._get_conn()
        if conn is None:
            return 0
        cur = conn.execute("SELECT COUNT(*) FROM phases")
        return int(cur.fetchone()[0])

    def stats(self) -> dict:
        """数据库统计信息。"""
        if not self._db_path.exists():
            return {"ready": False}
        conn = self._get_conn()
        if conn is None:
            return {"ready": False}
        cur = conn.execute("SELECT COUNT(*) FROM phases")
        total = int(cur.fetchone()[0])
        meta: dict[str, str] = {}
        for r in conn.execute("SELECT key, value FROM meta"):
            meta[r["key"]] = r["value"]
        out = {
            "ready": True,
            "total": total,
            "source": meta.get("source", "unknown"),
            "db_path": str(self._db_path),
            "db_size_mb": round(self._db_path.stat().st_size / 1024 / 1024, 1),
        }
        # 建库时写入的对称性/晶胞覆盖率 (老库可能没有, 缺失即不报)
        for key in ("with_cell", "with_sg", "sg_unknown", "with_name",
                    "vol_mismatch", "build_date"):
            if key in meta:
                out[key] = int(meta[key]) if meta[key].isdigit() else meta[key]
        return out

    def coverage(self) -> dict:
        """实时统计空间群/晶胞/名称覆盖率 (不依赖建库时写入的 meta)。"""
        conn = self._get_conn()
        if conn is None:
            return {}
        row = conn.execute(
            "SELECT COUNT(*) AS n, "
            "SUM(CASE WHEN space_group IS NOT NULL AND space_group <> '' "
            "         THEN 1 ELSE 0 END) AS n_sg, "
            "SUM(CASE WHEN cell_a IS NOT NULL THEN 1 ELSE 0 END) AS n_cell, "
            "SUM(CASE WHEN name IS NOT NULL AND name <> '' THEN 1 ELSE 0 END) AS n_name, "
            "SUM(CASE WHEN mineral IS NOT NULL AND mineral <> '' THEN 1 ELSE 0 END) AS n_min "
            "FROM phases"
        ).fetchone()
        if row is None:
            return {}
        n = row["n"] or 1
        return {
            "total": row["n"],
            "space_group": row["n_sg"],
            "cell": row["n_cell"],
            "name": row["n_name"],
            "mineral": row["n_min"],
            "pct_space_group": round(100.0 * (row["n_sg"] or 0) / n, 1),
            "pct_cell": round(100.0 * (row["n_cell"] or 0) / n, 1),
        }

    # ── 查询接口 (与 COD 兼容) ──────────────────────────────

    def get_phase(self, cod_id: int) -> Optional[dict]:
        """获取指定物相详情 (含 d-I 峰与对称性信息)。

        与 CIFDatabase.get_cod_phase 接口一致, 并额外提供 PDF2 独有的
        name / mineral / space_group_num / pearson / 约化晶胞 / 密度 等字段。
        """
        conn = self._get_conn()
        if conn is None:
            return None
        cur = conn.execute(
            "SELECT cod_id, ref_id, display_id, formula, name, mineral, "
            "space_group, space_group_num, space_group_setting, "
            "cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, "
            "cell_vol, red_a, red_b, red_c, red_alpha, red_beta, red_gamma, "
            "red_vol, pearson, "
            "n_peaks, peaks_d, peaks_i "
            "FROM phases WHERE cod_id = ?",
            (cod_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        data = dict(row)
        for key, out_key in (("peaks_d", "peaks_d_list"), ("peaks_i", "peaks_i_list")):
            if data.get(key):
                data[out_key] = [
                    float(x) for x in data[key].split(",") if x.strip()
                ]
            else:
                data[out_key] = []
        data["source"] = "pdf2"
        return data

    def get_lattice(self, cod_id: int):
        """取晶胞参数为 LatticeParams (缺失返回 None)。

        Rietveld 精修的起始晶胞就靠它 —— PDF2 命中相若无晶胞, 精修只能
        从默认立方胞起步。
        """
        from polyxrd.models.phase import LatticeParams

        conn = self._get_conn()
        if conn is None:
            return None
        row = conn.execute(
            "SELECT cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma "
            "FROM phases WHERE cod_id = ?", (cod_id,)
        ).fetchone()
        if row is None or row["cell_a"] is None:
            return None
        return LatticeParams(
            a=float(row["cell_a"]), b=float(row["cell_b"] or row["cell_a"]),
            c=float(row["cell_c"] or row["cell_a"]),
            alpha=float(row["cell_alpha"] or 90.0),
            beta=float(row["cell_beta"] or 90.0),
            gamma=float(row["cell_gamma"] or 90.0),
        )

    def search_phases(self, query: str, *, limit: int = 50) -> list[dict]:
        """按化学式 / 名称 / 矿物名 / PDF2 ID 搜索物相。

        与 CIFDatabase.search_cod_phases 接口一致 (额外带 name/mineral)。
        """
        conn = self._get_conn()
        if conn is None:
            return []
        q = query.strip()
        if not q:
            return []
        cols = ("cod_id, ref_id, display_id, formula, name, mineral, "
                "space_group, space_group_num, n_peaks")
        if q.isdigit():
            cur = conn.execute(
                f"SELECT {cols} FROM phases WHERE cod_id = ? LIMIT ?",
                (int(q), limit),
            )
        else:
            norm_q = " ".join(sorted(q.split()))
            like = f"%{q}%"
            cur = conn.execute(
                f"SELECT {cols} FROM phases "
                "WHERE formula = ? OR formula = ? "
                "OR formula LIKE ? OR display_id LIKE ? "
                "OR name LIKE ? OR mineral LIKE ? "
                "LIMIT ?",
                (q, norm_q, like, like, like, like, limit),
            )
        return [dict(r) for r in cur]

    def search_by_d_peaks(
        self,
        measured_d: list[float],
        measured_i: list[float] | None = None,
        *,
        tolerance: float = 0.02,
        tolerance_rel: float = 0.0,
        min_match: int = 3,
        limit: int = 50,
        max_ref_peaks: int = 40,
        elements_allowed: set | None = None,
    ) -> list[dict]:
        """用测得的 d 值列表搜索匹配物相。

        与 CIFDatabase.search_cod_by_d_peaks 算法一致:
        Hanawalt 主峰原则 + 强度加权召回 + 双向匹配。
        复用同一实现以保持口径统一。
        """
        from polyxrd.services.cif_database import CIFDatabase

        # 用正常构造器而非 __new__ 裸实例: 后者跳过 __init__, 一旦
        # search_cod_by_d_peaks 触碰 _cod_enabled/_cod_db 就会 AttributeError。
        cdb = CIFDatabase(enable_cod_local=False)
        cdb._cod_conn = self._get_conn()
        try:
            return cdb.search_cod_by_d_peaks(
                measured_d, measured_i,
                tolerance=tolerance,
                tolerance_rel=tolerance_rel,
                min_match=min_match,
                limit=limit,
                max_ref_peaks=max_ref_peaks,
                elements_allowed=elements_allowed,
            )
        finally:
            cdb._cod_conn = None


# ──────────────────────────────────────────────────────────────
# 便捷入口
# ──────────────────────────────────────────────────────────────

def build_pdf2_database(
    raw_path: str | Path,
    db_path: str | Path,
    progress_cb=None,
) -> dict:
    """构建 PDF2-2004 SQLite 索引。

    Args:
        raw_path: pdf2 - 2004.dat 文件路径
        db_path: 输出 SQLite 文件路径
        progress_cb: 进度回调 (n_processed: int) -> None

    Returns:
        统计字典 {total, ok, bad, elapsed_s}
    """
    builder = PDF2DatabaseBuilder(Path(raw_path), Path(db_path))
    return builder.build(progress_cb=progress_cb)


def get_pdf2_database() -> PDF2Database:
    """获取全局 PDF2Database 单例 (基于配置路径)。"""
    return PDF2Database()
