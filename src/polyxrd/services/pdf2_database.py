"""
PDF2-2004 数据库服务
====================

将 ICDD PDF-2 2004 版二进制/定宽文本数据库 (pdf2 - 2004.dat + codens.dat)
解析为 SQLite 索引，提供与 COD 无机物库相同的检索接口
(search_by_d_peaks / get_phase / search_phases)，可直接接入
CIFDatabase 的热切换机制和 PhaseIdentifier 的物相识别流程。

PDF-2 2004 定宽格式 (每行 80 字符 ASCII):
    每个物相记录由若干子记录组成，以 PddddddX<code> 标识:
      X1 — 主记录起始 (含 M 编号)
      X4 — 分子量 + 附加数值
      X5 — 元素符号 / CAS 号
      X6 — 矿物/化合物名称
      X7 — 化学式 (原始写法)
      X8 — 化学式 (规范化)
      X9 — 文献引用
      XF — 辐射类型 + 标记
      XG — 质量标记
      XI — d-I 峰数据 (每行 3 对, d=7 字段+I=3 字段)
      X+ — Hanawalt 组 (按强度降序)
      X* — Hanawalt 组 (按 d 升序)
      XB — 注释 (可选)
      XK — 录入/维护信息

用法:
    builder = PDF2DatabaseBuilder()
    builder.build(raw_path, sqlite_path)   # 首次构建

    db = PDF2Database(sqlite_path)
    results = db.search_by_d_peaks(d_list, i_list, ...)
    phase = db.get_phase(pdf2_id)
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import struct
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
        "name", "space_group", "cell_a", "cell_b", "cell_c",
        "cell_alpha", "cell_beta", "cell_gamma",
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
        self.space_group: str = ""
        self.cell_a: Optional[float] = None
        self.cell_b: Optional[float] = None
        self.cell_c: Optional[float] = None
        self.cell_alpha: Optional[float] = None
        self.cell_beta: Optional[float] = None
        self.cell_gamma: Optional[float] = None
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

        # 数据区 = 同 field 的 0~66 列。第 67~70 列是**标志区**, 不是数据:
        # 实测出现孤立 "G"、续行标记 "DB 1"/"SM 2"/" P " 等 —— 混进 formula
        # 会把 "G" 当成元素, 污染元素过滤 (实测 4342/163834 条被污染)。
        # 峰行 (XI) 数据只占 0~55 列, 名称/化学式极少超过 60 列, 67 截断安全。
        data = line[:67].rstrip()

        if code == "1":
            # X1: 主记录起始, 不含额外信息
            pass
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
            # X6: 矿物/化合物名称
            name = data.strip()
            if name.startswith("$"):
                name = name[1:]
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
    space_group         TEXT,
    cell_a              REAL,
    cell_b              REAL,
    cell_c              REAL,
    cell_alpha          REAL,
    cell_beta           REAL,
    cell_gamma          REAL,
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
"""


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
            统计字典 {total, ok, bad, elapsed_s}
        """
        import time
        t0 = time.time()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()

        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(_SCHEMA_SQL)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")

        total = ok = bad = 0
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

            batch.append((
                rec.pdf2_id, formula, rec.space_group,
                rec.cell_a, rec.cell_b, rec.cell_c,
                rec.cell_alpha, rec.cell_beta, rec.cell_gamma,
                rec.n_peaks, peaks_d_str, peaks_i_str,
                rec.record_offset, rec.record_size,
                ref_id, display_id,
            ))

            if len(batch) >= 5000:
                conn.executemany(
                    "INSERT OR REPLACE INTO phases VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                batch.clear()
                ok += 5000
                if progress_cb:
                    progress_cb(ok)
                conn.commit()

        if batch:
            conn.executemany(
                "INSERT OR REPLACE INTO phases VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            ok += len(batch)
            batch.clear()

        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES "
            "('source', 'ICDD PDF-2 2004')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES "
            "('build_date', ?)",
            (str(int(t0)),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES "
            "('raw_file', ?)",
            (str(self.raw_path),),
        )
        conn.commit()
        conn.close()

        elapsed = time.time() - t0
        stats = {
            "total": total,
            "ok": ok,
            "bad": bad,
            "elapsed_s": round(elapsed, 1),
        }
        log.info(
            "PDF2 build done: %d total, %d ok, %d bad, %.1fs",
            total, ok, bad, elapsed,
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
        return {
            "ready": True,
            "total": total,
            "source": meta.get("source", "unknown"),
            "db_path": str(self._db_path),
            "db_size_mb": round(self._db_path.stat().st_size / 1024 / 1024, 1),
        }

    # ── 查询接口 (与 COD 兼容) ──────────────────────────────

    def get_phase(self, cod_id: int) -> Optional[dict]:
        """获取指定物相详情 (含 d-I 峰)。

        与 CIFDatabase.get_cod_phase 接口一致。
        """
        conn = self._get_conn()
        if conn is None:
            return None
        cur = conn.execute(
            "SELECT cod_id, ref_id, display_id, formula, space_group, "
            "cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, "
            "n_peaks, peaks_d, peaks_i "
            "FROM phases WHERE cod_id = ?",
            (cod_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        data = dict(row)
        if data.get("peaks_d"):
            data["peaks_d_list"] = [
                float(x) for x in data["peaks_d"].split(",") if x.strip()
            ]
        else:
            data["peaks_d_list"] = []
        if data.get("peaks_i"):
            data["peaks_i_list"] = [
                float(x) for x in data["peaks_i"].split(",") if x.strip()
            ]
        else:
            data["peaks_i_list"] = []
        data["source"] = "pdf2"
        return data

    def search_phases(self, query: str, *, limit: int = 50) -> list[dict]:
        """按化学式 / 名称 / PDF2 ID 搜索物相。

        与 CIFDatabase.search_cod_phases 接口一致。
        """
        conn = self._get_conn()
        if conn is None:
            return []
        q = query.strip()
        if not q:
            return []
        if q.isdigit():
            num = int(q)
            cur = conn.execute(
                "SELECT cod_id, ref_id, display_id, formula, space_group, "
                "n_peaks FROM phases WHERE cod_id = ? LIMIT ?",
                (num, limit),
            )
        else:
            norm_q = " ".join(sorted(q.split()))
            cur = conn.execute(
                "SELECT cod_id, ref_id, display_id, formula, space_group, "
                "n_peaks FROM phases "
                "WHERE formula = ? OR formula = ? "
                "OR formula LIKE ? OR display_id LIKE ? "
                "LIMIT ?",
                (q, norm_q, f"%{q}%", f"%{q}%", limit),
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
