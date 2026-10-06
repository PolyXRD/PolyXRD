"""用户自建数据库 (v2.6.0)
========================
用户把自己收集的 CIF 文件 (多选或整个文件夹) 导入一个本地 SQLite 库,
与「COD 无机物库」同一套 ``phases`` 表结构 —— 含 d-I 峰表 / 预截断强峰列
(peaks_top_*) / 内嵌 CIF 全文 (cif_gz) / 原子坐标 (cod_atomic_sites)。

为什么做成同构库: 检索 (Hanawalt d-I 预筛)、详情 (晶胞+位点→精修直构)、
CIF 导出 (cif_gz) 三条链路全部复用现有实现, 用户库条目勾选后可以
**直接进内置引擎精修** (atomic_sites 直构 Structure, 不需要 CIF 落盘)。

条目 ID 空间: 900_000_001 起自增 —— COD 真实 ID 是 7 位数字, 9 亿段
永不冲突; phase_cif_export 也按 ``cod_id >= 900_000_000`` 识别"该条目
的 CIF 要回用户库取"。

本模块不依赖 Qt, 可离屏单测。
"""
from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from polyxrd.config import get_config

USER_DB_FILENAME = "user_phases.sqlite"
#: 用户条目 ID 起点 (COD 真实 ID ≤ 9,999,999)
USER_ID_BASE = 900_000_000
#: 每相预截断强峰数 (与 cif_database._PEAK_TOP_N=64 对齐; 打分逻辑最多用 top-12)
_TOP_N = 64
#: 导入时模拟谱用的默认波长与 2θ 范围 (与检索默认口径一致)
DEFAULT_WAVELENGTH = 1.5406
DEFAULT_TT_RANGE = (5.0, 100.0)
#: 位点密度上限 (atoms/Å³)。真实晶体极限 ~0.20 (锇 0.14 / 金刚石 0.176),
#: 取 0.22 留余量。**这条主要拦"均匀过度展开"** —— 例如 ``R -3 c :R`` 菱形
#: 设置被按六方 36 操作展开时整胞等倍放大, 元素配比仍然正确, 只有密度能识破
#: (cod_local.get_phase 的同类保险丝为 0.5, 这里收得更紧)。
_DENSITY_MAX = 0.22
#: 化学式配比容差 (摩尔分数 L1 距离)。实测正确候选 ≤0.001, 错误候选 ≥0.12
_COMP_TOL = 0.03

_SCHEMA = """
CREATE TABLE IF NOT EXISTS phases (
    cod_id        INTEGER PRIMARY KEY,
    formula       TEXT,
    space_group   TEXT,
    cell_a        REAL,
    cell_b        REAL,
    cell_c        REAL,
    cell_alpha    REAL,
    cell_beta     REAL,
    cell_gamma    REAL,
    n_peaks       INTEGER,
    peaks_d       TEXT,
    peaks_i       TEXT,
    peaks_top_d   BLOB,
    peaks_top_i   BLOB,
    cif_gz        BLOB,
    ref_id        TEXT,
    display_id    TEXT,
    source_file   TEXT
);

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
CREATE INDEX IF NOT EXISTS idx_user_sites_cod_id ON cod_atomic_sites(cod_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# ── 路径 / 连接 ──────────────────────────────────────────────

def user_db_path() -> Path:
    """用户库固定路径: ``~/.polyxrd/cif_db/user_phases.sqlite``。"""
    return get_config().get_cif_db_path() / USER_DB_FILENAME


def user_db_exists() -> bool:
    return user_db_path().exists()


def _connect_write() -> sqlite3.Connection:
    p = user_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def user_conn() -> sqlite3.Connection | None:
    """只读连接 (与 CIFDatabase._get_cod_conn 同风格); 库不存在返回 None。"""
    p = user_db_path()
    if not p.exists():
        return None
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def user_stats() -> dict:
    """用户库概览, 供挂载页 / 下拉文案显示。"""
    p = user_db_path()
    out = {"path": str(p), "exists": p.exists(), "rows": 0,
           "size_mb": 0.0}
    if not p.exists():
        return out
    out["size_mb"] = round(p.stat().st_size / 1e6, 1)
    try:
        conn = user_conn()
        assert conn is not None
        try:
            out["rows"] = int(
                conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    return out


def _fmt_amt(amt: float) -> str:
    """组成计数格式化: 1 隐去; 整数去尾零; 否则保留 3 位。"""
    if abs(amt - 1.0) < 1e-9:
        return ""
    if abs(amt - round(amt)) < 1e-9:
        return str(int(round(amt)))
    return f"{amt:.3f}".rstrip("0")


def _formula_from_sites(sites: list[dict]) -> str:
    """全胞位点 → 约简化学式 (元素字母排序, 计数>1 才写数字)。

    math.gcd 逐对约简: Si 全胞 8 原子 → "Si"; quartz 3Si+6O → "O2 Si"。
    与 COD 无机库的 "O2 Si" 排序口径一致。
    """
    from collections import Counter
    from math import gcd

    cnt = Counter(s.get("element") or "" for s in sites)
    cnt.pop("", None)
    if not cnt:
        return ""
    counts = list(cnt.values())
    g = counts[0]
    for c in counts[1:]:
        g = gcd(g, c)
        if g == 1:
            break
    return " ".join(
        f"{el}{_fmt_amt(cnt[el] / g)}" for el in sorted(cnt)
    )


def _next_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(cod_id) FROM phases").fetchone()
    cur = row[0] or USER_ID_BASE
    return max(int(cur), USER_ID_BASE) + 1


def is_user_id(cod_id: object) -> bool:
    """该 ID 是否属于用户库 (9 亿段)。"""
    try:
        return int(cod_id) >= USER_ID_BASE  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def display_id_of(cod_id: int) -> str:
    """库内 ID → 展示名 ``USER-000001``。"""
    try:
        return f"USER-{int(cod_id) - USER_ID_BASE + 1:06d}"
    except (TypeError, ValueError):
        return "USER-??????"


# ── CIF → 条目 ───────────────────────────────────────────────

@dataclass
class ImportReport:
    """一次批量导入的结果 (逐文件状态 + 汇总), 供对话框展示。"""

    imported: list[str] = field(default_factory=list)
    skipped_dup: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (文件, 原因)

    @property
    def total(self) -> int:
        return len(self.imported) + len(self.skipped_dup) + len(self.failed)


def _structure_from_cif(text: str):
    """CIF 文本 → pymatgen Structure。先严格解析, 失败放宽容差重试。"""
    from pymatgen.core import Structure

    try:
        return Structure.from_str(text, fmt="cif")
    except Exception:
        import warnings

        from pymatgen.io.cif import CifParser

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parser = CifParser.from_str(text, occupancy_tolerance=1.2)
            return parser.parse_structures(primitive=False)[0]


_SG_PATTERNS = (
    r"_symmetry_space_group_name_H-M\s+['\"]?([^'\"\n]+)",
    r"_space_group_name_H-M_alt\s+['\"]?([^'\"\n]+)",
    r"_space_group_name_Hall\s+['\"]?([^'\"\n]+)",
)


def _space_group_of(text: str) -> str:
    """从 CIF 文本取空间群 H-M 符号 (取不到返回空串)。"""
    for pat in _SG_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            sg = m.group(1).strip()
            if sg and sg not in (".", "?"):
                return sg
    return ""


_CHARGE_RE = re.compile(r"\s*[0-9]*[+-]$")
_ELEM_NUM_RE = re.compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")


def _plain_symbol(elem: object) -> str:
    """元素符号规范化: ``'Ca2+'``/``'V+3'``/``'O-2'`` → ``'Ca'``/``'V'``/``'O'``。

    CIF 的 ``_atom_site_type_symbol`` 常带氧化态 (COD 尤其普遍), 直接入库会
    让 formula 显示成 "Ca2+ F1-"、也让元素比对/精修物种判定变脆。
    """
    t = _CHARGE_RE.sub("", str(elem or "").strip())
    m = re.match(r"([A-Z][a-z]?)", t)
    return m.group(1) if m else ""


def _normalize_sites(sites: list[dict]) -> list[dict]:
    """位点元素符号规范化 + 丢弃无元素的脏行 (返回新列表, 不改原对象)。"""
    out: list[dict] = []
    for s in sites:
        el = _plain_symbol(s.get("element")) or _plain_symbol(s.get("label"))
        if not el:
            continue
        d = dict(s)
        d["element"] = el
        out.append(d)
    return out


def _fractions_from_formula(formula: str) -> dict[str, float]:
    """CIF 化学式 (``'Ce Cr0.234 Ni1.766'``) → 摩尔分数。

    只做"配比"用 —— 摩尔分数对 Z 不敏感, 所以可以直接和全胞位点比对。
    """
    acc: dict[str, float] = {}
    for el, num in _ELEM_NUM_RE.findall(str(formula or "")):
        try:
            v = float(num) if num else 1.0
        except ValueError:
            continue
        if v > 0:
            acc[el] = acc.get(el, 0.0) + v
    tot = sum(acc.values())
    if tot <= 0:
        return {}
    return {k: v / tot for k, v in acc.items()}


def _sites_fractions(sites: list[dict]) -> dict[str, float]:
    """位点 (含占位) → 摩尔分数。占位加权 = XRD 里真正参与散射的比例。"""
    acc: dict[str, float] = {}
    for s in sites:
        el = _plain_symbol(s.get("element"))
        if not el:
            continue
        try:
            occ = float(s.get("occupancy", 1.0) or 1.0)
        except (TypeError, ValueError):
            occ = 1.0
        acc[el] = acc.get(el, 0.0) + max(occ, 0.0)
    tot = sum(acc.values())
    if tot <= 0:
        return {}
    return {k: v / tot for k, v in acc.items()}


def _comp_distance(sites: list[dict], ref: dict[str, float]) -> float:
    """位点配比 vs 化学式配比的 L1 距离 (0 = 完全一致)。

    参考式**按候选实际存在的元素重归一** —— CIF 化学式常含未定位的 H
    (如 ``H2 Mg4.98 O10 Si2.01`` 而原子环里没有 H), 硬比会把两个候选
    一起判死; 重归一后仍能识破"候选丢元素"(丢元素会让剩余比例整体偏移)。
    """
    got = _sites_fractions(sites)
    if not got or not ref:
        return 9.99
    keys = set(got)
    sub = {k: ref.get(k, 0.0) for k in keys}
    tot = sum(sub.values())
    if tot <= 0:
        return 9.99  # 候选元素完全不在化学式里 → 可疑
    return sum(abs(got[k] - sub[k] / tot) for k in keys)


def _orbit_closed(sites: list[dict], space_group: str) -> bool:
    """位点集在该空间群下是否已闭合 (每个点的完整轨道都在集合内)。

    用途: 识破 pymatgen 把非 P1 结构误判成 P1 (只说"1 条对称操作") —— 此时
    它返回的位点数 = 不对称单元, 再按标准对称操作展开会"变多", 于是判为
    未闭合。自研链 (expand_sites_by_symmetry) 的输出天然闭合。
    """
    if not sites:
        return False
    if len(sites) > 4000:  # 大胞放弃精确校验 (避免 4000×192 的逐点比较)
        return True
    try:
        from polyxrd.services.phase_cif import expand_sites_by_symmetry

        return len(expand_sites_by_symmetry(sites, space_group)) == len(sites)
    except Exception:  # noqa: BLE001
        return True


def _entry_from_cif(text: str, name: str):
    """CIF 文本 → (entry, full_sites, cell)。

    双候选位点 (各有翻车场景, 实测 40 个真实 COD CIF):
      候选 A = 自研链: 原子环位点 + ``expand_sites_by_symmetry`` (标准对称
               操作展开, 天然轨道闭合)
      候选 B = pymatgen ``CifParser`` 解析 (尊重 CIF 的 setting)
      raw    = 原子环原始位点

    实测归因 (见 _pick_sites 的判据顺序):
      · 21/40 两链配比都对;
      · 11/40 **只有 A 对** —— pymatgen 会吞掉同一坐标上的少数占据物种
        (例: Cr0.117/Ni0.883 同点, B 只剩 Ni);
      · 2/40 **只有 B 对** —— ``R -3 c :R`` 菱形设置下自研链按六方 36 操作
        展开, 整胞被等倍放大 (元素配比仍对, 只有密度能识破);
      · pymatgen 把非 P1 误判为 P1 时 (手写 CIF 常见) B 未展开。
    """
    from polyxrd.services.cod_local import parse_atom_sites_from_cif
    from polyxrd.services.cod_local import parse_cif_text
    from polyxrd.services.phase_cif import expand_sites_by_symmetry

    entry = parse_cif_text(text, file_rel=name, cod_id=0)
    if not (entry.a and entry.b and entry.c):
        # 无晶胞 = 无法算峰表/无法精修, 直接判废
        raise ValueError("no_cell_params")

    raw = _normalize_sites(parse_atom_sites_from_cif(text))
    sg = entry.space_group or _space_group_of(text)
    cand_a = _normalize_sites(
        expand_sites_by_symmetry(raw, sg)) if raw else []

    cand_b: list[dict] = []
    try:
        cand_b = _normalize_sites(_sites_of(_structure_from_cif(text)))
    except Exception:  # noqa: BLE001 - pymatgen 失败时只用候选 A
        cand_b = []

    cell = (entry.a, entry.b, entry.c,
            entry.alpha or 90.0, entry.beta or 90.0, entry.gamma or 90.0)
    sites = _pick_sites(raw, cand_a, cand_b, cell,
                        formula=entry.formula, space_group=sg)
    return entry, sites, cell


def _pick_sites(
    raw: list[dict], cand_a: list[dict], cand_b: list[dict], cell: tuple,
    *, formula: str = "", space_group: str = "",
) -> list[dict]:
    """位点择优 (判据按"物理 → 结构 → 计数"三层, 见 _entry_from_cif)。

    1. **硬过滤**: 位点数 < raw (丢了原子) 或 密度 > ``_DENSITY_MAX``
       (均匀过度展开) 的候选直接弃用;
    2. **化学式配比**: 与 CIF ``_chemical_formula_sum`` 摩尔分数比对, 取
       L1 距离 ≤ ``_COMP_TOL`` 者 (识破"丢元素 / 吞少数占据");
    3. **轨道闭合性**: 排除未按空间群展开的候选 (pymatgen P1 误判);
    4. **位点数最少者**: 元素配比相同时, 均匀放大的整胞不是真胞。
    全部候选都被过滤 → 退回 CIF 原子环原样 (raw): 其元素配比与不对称
    单元一致, 精修链 ``get_phase`` 还会按空间群再展开一次, 比"一个原子
    都不存"更可用。raw 也空 → 返回 [] (只登记晶胞, 峰表留空, 检索预筛
    自动跳过)。
    """
    from polyxrd.models.phase import LatticeParams

    try:
        vol = LatticeParams(
            a=cell[0], b=cell[1], c=cell[2],
            alpha=cell[3], beta=cell[4], gamma=cell[5],
        ).volume
    except Exception:  # noqa: BLE001
        vol = 0.0

    cands: list[tuple[str, list[dict]]] = []
    for src, s in (("A", cand_a), ("B", cand_b)):
        if not s or len(s) < len(raw):
            continue
        if vol > 0 and len(s) / vol > _DENSITY_MAX:
            continue
        cands.append((src, s))
    if not cands:
        # 两链都被密度/丢原子判废 → 退回 CIF 原子环原样 (见 docstring ②)
        if not raw:
            return []
        if vol > 0 and len(raw) / vol > _DENSITY_MAX:
            return []  # 连原子环本身都不合理 → 只登记晶胞
        return raw
    if len(cands) == 1:
        return cands[0][1]

    ref = _fractions_from_formula(formula)
    if ref:
        matched = [(src, s) for src, s in cands
                   if _comp_distance(s, ref) <= _COMP_TOL]
        if matched:
            cands = matched

    closed = [(src, s) for src, s in cands
              if _orbit_closed(s, space_group)]
    if closed:
        cands = closed

    return min(cands, key=lambda t: len(t[1]))[1]


def _peaks_from_sites(cell: tuple, sites: list[dict], wavelength, tt_range):
    """全胞位点 + 晶胞 → XRDCalculator 峰表 (d/I/top BLOB)。"""
    import numpy as np

    try:
        from pymatgen.analysis.diffraction.xrd import XRDCalculator
        from pymatgen.core import Lattice, Structure

        pmg_lat = Lattice.from_parameters(*cell)
        species = [s["element"] for s in sites]
        coords = [[s["x"], s["y"], s["z"]] for s in sites]
        struct = Structure(pmg_lat, species, coords)
        pattern = XRDCalculator(wavelength=wavelength).get_pattern(
            struct, two_theta_range=tt_range)
    except Exception:
        return None
    if len(pattern.x) == 0:
        return None
    import math

    d_list, i_list = [], []
    for tt, iv in zip(pattern.x, pattern.y):
        sin_t = math.sin(math.radians(float(tt) / 2.0))
        if sin_t <= 0:
            continue
        d_list.append(wavelength / (2.0 * sin_t))
        i_list.append(float(iv))
    if not d_list:
        return None
    imax = max(i_list) or 1.0
    i_norm = [100.0 * iv / imax for iv in i_list]
    order = sorted(range(len(d_list)), key=lambda k: -i_norm[k])[:_TOP_N]
    top_d = np.array([d_list[k] for k in order], dtype=np.float64).tobytes()
    top_i = np.array([i_norm[k] for k in order], dtype=np.float64).tobytes()
    return d_list, i_norm, top_d, top_i


def _sites_of(struct) -> list[dict]:
    """Structure → 全胞位点列表 (直接可被精修引擎直构; get_phase 的对称
    展开对全胞位点幂等)。

    **每个物种各出一行**: 无序固溶体 (如 Cr0.117/Ni0.883 同坐标) 若只取
    多数物种会丢掉少数元素 —— 实测 40 个真实 COD CIF 里有 11 个因此与
    CIF 化学式对不上 (元素配比整体偏移 → 峰强比例错)。拆成多行后占位
    之和不变, XRD 散射因子按各自占位加权, 与 CIF 口径一致。
    """
    sites: list[dict] = []
    for site in struct:
        comp = site.species
        fx, fy, fz = site.frac_coords
        try:
            items = [(str(sp.symbol), float(v)) for sp, v in comp.items()]
        except Exception:  # noqa: BLE001
            continue
        for elem, occ in items:
            if not elem or occ <= 0:
                continue
            sites.append({
                "label": f"{elem}{len(sites) + 1}",
                "element": elem,
                "x": float(fx), "y": float(fy), "z": float(fz),
                "occupancy": occ if occ <= 1.5 else 1.0,
            })
    return sites


def import_cif_files(
    paths: list[str | Path],
    *,
    wavelength: float = DEFAULT_WAVELENGTH,
    tt_range: tuple[float, float] = DEFAULT_TT_RANGE,
    progress=None,
) -> ImportReport:
    """批量导入 CIF 文件进用户库。

    Args:
        paths: CIF 文件路径列表 (已由对话框多选 / 文件夹展开)
        wavelength: 模拟 d-I 峰表用的波长
        tt_range: 模拟 2θ 范围
        progress: 可选回调 ``progress(done, total, name)``

    Returns:
        ImportReport (逐文件成功/去重跳过/失败)
    """
    report = ImportReport()
    if not paths:
        return report
    conn = _connect_write()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('wavelength', ?)",
            (str(wavelength),))
        for done, p in enumerate(paths, 1):
            name = Path(p).name
            if progress is not None:
                progress(done - 1, len(paths), name)
            try:
                text = Path(p).read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                report.failed.append((name, f"read_failed: {e}"))
                continue
            if not text.strip():
                report.failed.append((name, "empty_file"))
                continue
            # 内容去重: 同一 CIF 重复导入直接跳过 (换名不算新相)
            sha = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
            if conn.execute(
                "SELECT 1 FROM meta WHERE key=?", (f"sha1:{sha}",)
            ).fetchone():
                report.skipped_dup.append(name)
                continue
            try:
                entry, sites, cell = _entry_from_cif(text, name)
            except ValueError as e:
                report.failed.append((name, str(e)))
                continue
            except Exception as e:  # noqa: BLE001
                report.failed.append((name, f"cif_parse_failed: {e}"))
                continue

            # 位点已按密度择优 (_entry_from_cif 内部完成); 为空说明两条
            # 解析链都翻车 (或 CIF 无原子环) → 峰表留空, 晶胞照常入库
            peaks = None
            if sites:
                peaks = _peaks_from_sites(cell, sites, wavelength, tt_range)
            if peaks is None:
                # 无位点 (如只有晶胞的 CIF): 只登记晶胞信息, 峰表留空
                # (检索预筛会跳过, 但详情/CIF 导出可用)
                d_list: list[float] = []
                i_list: list[float] = []
                top_d = b""
                top_i = b""
            else:
                d_list, i_list, top_d, top_i = peaks

            sg = entry.space_group or _space_group_of(text)
            # formula: 优先 CIF 的 _chemical_formula_sum (COD 口径);
            # 缺失时从全胞位点元素计数约简 (Si 8 原子 → "Si";
            # quartz 3Si+6O → "O2 Si")
            formula = entry.formula or ""
            if not formula and sites:
                formula = _formula_from_sites(sites)
            if not formula:
                formula = ""
            uid = _next_id(conn)
            display = display_id_of(uid)
            conn.execute(
                "INSERT OR REPLACE INTO phases(cod_id, formula, space_group,"
                " cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma,"
                " n_peaks, peaks_d, peaks_i, peaks_top_d, peaks_top_i,"
                " cif_gz, ref_id, display_id, source_file)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, formula, sg,
                 cell[0], cell[1], cell[2], cell[3], cell[4], cell[5],
                 len(d_list),
                 ",".join(f"{v:.5f}" for v in d_list),
                 ",".join(f"{v:.3f}" for v in i_list),
                 top_d, top_i,
                 gzip.compress(text.encode("utf-8", "ignore")),
                 display, display, name),
            )
            for idx, s in enumerate(sites):
                conn.execute(
                    "INSERT OR REPLACE INTO cod_atomic_sites"
                    " (cod_id, site_idx, label, element, x, y, z, occupancy, u_iso)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, idx, s.get("label"), s["element"],
                     s["x"], s["y"], s["z"],
                     s.get("occupancy") or 1.0, s.get("u_iso")),
                )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                (f"sha1:{sha}", name))
            conn.commit()
            report.imported.append(name)
        if progress is not None:
            progress(len(paths), len(paths), "")
    finally:
        conn.close()
    return report


def import_cif_folder(
    folder: str | Path,
    *,
    wavelength: float = DEFAULT_WAVELENGTH,
    tt_range: tuple[float, float] = DEFAULT_TT_RANGE,
    progress=None,
) -> ImportReport:
    """导入一个文件夹下的全部 .cif (不递归; 子目录请多选或分次导入)。"""
    d = Path(folder)
    if not d.is_dir():
        rep = ImportReport()
        rep.failed.append((str(folder), "not_a_directory"))
        return rep
    # Windows 文件系统大小写不敏感: "*.cif" 与 "*.CIF" 会匹配到同一批文件,
    # 直接拼接会把每个文件处理两遍 (第二遍全被 sha1 去重跳过, 白耗一次
    # XRD 模拟)。resolve 后用 set 去重。
    seen: dict = {}
    for f in list(d.glob("*.cif")) + list(d.glob("*.CIF")):
        seen.setdefault(str(f.resolve()).lower(), f)
    cifs = sorted(seen.values(), key=lambda f: f.name.lower())
    return import_cif_files(
        cifs, wavelength=wavelength, tt_range=tt_range, progress=progress)


# ── 列表 / 导出 / 清理 ───────────────────────────────────────

def list_entries(limit: int = 5000) -> list[dict]:
    """已导入条目列表 (供对话框表格显示), 按 cod_id 升序。"""
    conn = user_conn()
    if conn is None:
        return []
    try:
        cur = conn.execute(
            "SELECT cod_id, display_id, formula, space_group,"
            " cell_a, cell_b, cell_c, n_peaks, source_file"
            " FROM phases ORDER BY cod_id LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def get_user_cif(cod_id: int) -> str | None:
    """取用户库条目的 CIF 全文 (cif_gz 解压); 无该条目返回 None。

    phase_cif_export 按 ``cod_id >= USER_ID_BASE`` 调这里,
    让用户库相的「导出 CIF」与 GSAS/MAUD 桥接自动工作。
    """
    conn = user_conn()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT cif_gz FROM phases WHERE cod_id = ?", (cod_id,)).fetchone()
        if row is None or not row["cif_gz"]:
            return None
        return gzip.decompress(row["cif_gz"]).decode("utf-8", "replace")
    except (sqlite3.Error, OSError):
        return None
    finally:
        conn.close()


def get_user_atomic_sites(cod_id: int) -> list[dict]:
    """取用户库条目的原子位点 (全胞)。"""
    conn = user_conn()
    if conn is None:
        return []
    try:
        cur = conn.execute(
            "SELECT label, element, x, y, z, occupancy FROM cod_atomic_sites"
            " WHERE cod_id = ? ORDER BY site_idx", (cod_id,))
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def remove_entries(cod_ids: list[int]) -> int:
    """删除指定条目 (含位点); 返回实际删除的条数。"""
    if not cod_ids:
        return 0
    conn = _connect_write()
    try:
        n = 0
        for uid in cod_ids:
            cur = conn.execute("DELETE FROM phases WHERE cod_id = ?", (uid,))
            conn.execute("DELETE FROM cod_atomic_sites WHERE cod_id = ?", (uid,))
            n += cur.rowcount if cur.rowcount > 0 else 0
        conn.commit()
        return n
    finally:
        conn.close()


def clear_user_db() -> None:
    """清空用户库 (整文件删除, 下次导入自动重建)。"""
    p = user_db_path()
    for suffix in ("", "-wal", "-shm"):
        q = Path(str(p) + suffix)
        if q.exists():
            q.unlink()


def export_user_db(dest: str | Path) -> Path:
    """把用户库导出为可分发/可挂载的 .sqlite (WAL checkpoint 后复制)。"""
    src = user_db_path()
    if not src.exists():
        raise FileNotFoundError("用户数据库尚未创建 (先导入至少一个 CIF)")
    dest = Path(dest)
    if dest.resolve() == src.resolve():
        raise ValueError("导出路径不能与用户库相同")
    # 先 checkpoint, 把 -wal 里的内容合回主文件, 复制出的才是完整库
    try:
        conn = sqlite3.connect(str(src))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except sqlite3.Error:
        pass
    shutil.copy2(src, dest)
    return dest


#: 挂载外部库时要求存在的表 (本模块导出的格式)
_REQUIRED_TABLES = {"phases", "cod_atomic_sites"}


def inspect_user_db_file(path: str | Path) -> tuple[bool, str]:
    """校验某文件是不是可挂载的用户库。返回 ``(ok, 说明)``。"""
    p = Path(path)
    if not p.exists():
        return False, "file_not_found"
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not _REQUIRED_TABLES.issubset(names):
                return False, "not_a_user_db"
            n = int(conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error as e:
        return False, f"sqlite_error: {e}"
    if n <= 0:
        return False, "empty_phases"
    return True, str(n)


def mount_user_db(src: str | Path) -> Path:
    """把外部用户库 ``.sqlite`` 挂载为当前用户库 (换机器 / 同事分享)。

    与 COD/PDF2 三个外挂库「导入即挂载」的语义一致: 文件复制到固定槽位
    ``~/.polyxrd/cif_db/user_phases.sqlite``。目标已存在时先备份为
    ``user_phases.sqlite.bak`` (可回滚), 再覆盖。
    """
    p = Path(src)
    if p.suffix.lower() not in (".sqlite", ".db", ".sqlite3"):
        raise ValueError("只能挂载 .sqlite 文件")
    if p.resolve() == user_db_path().resolve():
        raise ValueError("该文件就是当前用户库, 无需挂载")
    ok, info = inspect_user_db_file(p)
    if not ok:
        raise ValueError(f"不是有效的用户库: {info}")

    dest = user_db_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):  # 先清掉旧库的 WAL 残渣
        q = Path(str(dest) + suffix)
        if q.exists():
            q.unlink()
    if dest.exists():
        shutil.copy2(dest, Path(str(dest) + ".bak"))
    shutil.copy2(p, dest)
    return dest
