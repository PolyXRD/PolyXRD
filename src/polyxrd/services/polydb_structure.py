"""
polyDB 结构检索（精修向导「从检索库找结构」的服务层）
=====================================================

把"从本地参考库挑一条结构拿去精修"这件事拆成三个与 UI 无关的步骤：

1. :func:`open_database` —— 按 *当前挂载 > 默认无机库 > 全库* 的顺序打开一份
   可用的 polyDB；
2. :func:`search_structures` / :func:`search_structures_by_peaks` —— 两种找相
   入口（按化学式/矿名/空间群/编号查；按实测最强峰做 Hanawalt d-I 预筛）；
3. :func:`phase_from_entry` —— 库内条目 → 可直接精修的 :class:`Phase`
   （晶胞 + **已展开全胞**的原子位点 + 参考峰）。

为什么要单独一层
----------------
"d → 2θ 换算"和"非对称单位位点展开"都是**结构语义**，一旦写进 Qt 控件就只能
靠点界面验证。v4.1.1 的教训正是位点语义搞错：``sites.bin`` 存的是 CIF 原样的
非对称单位，直接当全胞用会让高对称相（Corundum R-3c 实测）凭空多出 6.8° 假峰
且真主峰强度塌到 15.9%。所以这里明确：

* 本模块 **不 import PySide6**，纯 pytest 可断言；
* 位点一律经 :func:`polyxrd.services.phase_cif.expand_sites_by_symmetry`
  展开（幂等，已展开的原样通过）；
* 展开失败退化为"只有晶胞"，不阻断——向导里用户仍能加相，由精修前
  ``PhaseStructureResolver`` 兜底。

与 ``phase_identifier._make_polydb_phase`` 的关系：那条链路面向"自动识别"
（自带候选池与 FOM 打分），这里面向"用户手工挑一条"，所以只复用同一套语义，
不共享打分逻辑。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.services.polydb import PolyDatabase

#: 默认 d 容差 (Å)。与物相检索主链路（``polydb.search_by_d_peaks`` 的默认值）
#: 保持一致，避免"向导里按最强峰查"和"主界面检索"给出两套名次。
DEFAULT_TOLERANCE: float = 0.02

#: 编进 Phase.reference_peaks 的峰数上限。
#: 参考峰只用于展示与精修起步，给太多会把密集物相的列表淹没。
REF_PEAK_CAP: int = 120

#: 「按最强峰检索」默认用几条实测峰、至少命中几条。
DEFAULT_PEAK_COUNT: int = 8
DEFAULT_MIN_MATCH: int = 3


# ── 打开库 ────────────────────────────────────────────────

def open_database(
    db_path: str | Path | None = None,
    variant: str | None = None,
) -> Optional[PolyDatabase]:
    """打开一份可用的 polyDB；一份都没有时返回 ``None``。

    优先级（与界面上的「数据库管理」语义对齐）：

    1. ``db_path`` 显式给定 → 只用它；
    2. ``variant`` 显式给定 → 只认该变体；
    3. 「数据库管理」里被选为当前数据源的那一行，且它是 polyDB；
    4. 默认无机库 ``cod-inorg``；
    5. 全库 ``cod-full``。

    第 3 步不能省：用户可能挂了两份 polyDB 并把检索源切到全库，向导却仍去
    无机库找，会出现"同一个化学式在主界面能查到、在向导里查不到"。
    """
    if db_path is not None:
        db = PolyDatabase(db_path)
        return db if db.is_ready() else None
    if variant:
        db = PolyDatabase(variant=variant)
        return db if db.is_ready() else None
    try:
        from polyxrd.services import db_mounts

        m = db_mounts.active_mount()
        if m is not None and m.kind == "polydb" and m.exists:
            db = PolyDatabase(m.path)
            if db.is_ready():
                return db
    except Exception:  # noqa: BLE001 - 挂载表异常不该让向导打不开库
        pass
    for v in ("cod-inorg", "cod-full"):
        db = PolyDatabase(variant=v)
        if db.is_ready():
            return db
    return None


def library_label(db: Optional[PolyDatabase]) -> str:
    """库的一行描述（变体 + 相数），给状态行用。未打开时返回空串。"""
    if db is None or not db.available:
        return ""
    meta = getattr(db, "meta", None) or {}
    try:
        import json

        meta = json.loads((Path(db.path) / "meta.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - meta 读不出就只报路径
        meta = {}
    variant = str(meta.get("variant") or db.variant or "")
    try:
        n = int((meta.get("counts") or {}).get("phases") or 0)
    except (TypeError, ValueError):
        n = 0
    name = Path(db.path).name if db.path else ""
    parts = [p for p in (name, variant) if p]
    if n:
        parts.append(f"{n:,}")
    return " · ".join(parts)


# ── 找相 ──────────────────────────────────────────────────

def search_structures(
    query: str,
    *,
    db: Optional[PolyDatabase] = None,
    limit: int = 30,
) -> list[dict]:
    """按 化学式 / 矿名 / 空间群 / 编号 模糊查相（只读，返回展示用 dict 列表）。

    直接转调 :meth:`PolyDatabase.search_entries` —— 主界面 MCP 工具用的是
    同一个方法，向导不应另有一套匹配口径。空查询返回空列表（不做全表扫描）。
    """
    if db is None:
        return []
    q = (query or "").strip()
    if not q:
        return []
    try:
        return db.search_entries(q, limit=limit)
    except Exception:  # noqa: BLE001 - 库损坏/半成品时按"无结果"处理
        return []


def search_structures_by_peaks(
    measured_d: Iterable[float],
    measured_i: Optional[Iterable[float]] = None,
    *,
    db: Optional[PolyDatabase] = None,
    tolerance: float = DEFAULT_TOLERANCE,
    min_match: int = DEFAULT_MIN_MATCH,
    limit: int = 30,
    elements_allowed: Optional[set] = None,
) -> list[dict]:
    """按实测 d-I 峰做 Hanawalt 预筛（与主界面检索同一套排序口径）。"""
    if db is None:
        return []
    md = [float(x) for x in measured_d if x and float(x) > 0]
    if len(md) < min_match:
        return []
    mi = None
    if measured_i is not None:
        mi_raw = [float(x) for x in measured_i]
        if len(mi_raw) == len(md):
            mi = mi_raw
    try:
        return db.search_by_d_peaks(
            md, mi, tolerance=tolerance, min_match=min_match,
            limit=limit, elements_allowed=elements_allowed)
    except Exception:  # noqa: BLE001 - 侧车/mmap 异常按"无结果"处理
        return []


# ── 展示 ──────────────────────────────────────────────────

def _clean_mineral(mineral: object, eid: int) -> str:
    """过滤库里的"伪矿名"（``data_`` 行直接是编号的条目）。"""
    name = str(mineral or "").strip()
    if not name:
        return ""
    if name.isdigit() or name == str(eid):
        return ""
    if name.upper() in ("UNKNOWN", "N/A", "NA", "NONE"):
        return ""
    return name


def display_label(entry: dict) -> str:
    """条目的主标题（不含晶胞/编号等附加信息）。"""
    eid = int(entry.get("cod_id") or entry.get("ref_id") or 0)
    mineral = _clean_mineral(entry.get("mineral_name"), eid)
    formula = str(entry.get("formula") or "")
    if mineral and formula and mineral != formula:
        return f"{mineral} ({formula})"
    return mineral or formula or (f"COD {eid}" if eid else "")


def entry_label(entry: dict) -> str:
    """列表一行：``矿名 (式) · 空间群 · a/c · COD 编号``。"""
    eid = int(entry.get("cod_id") or 0)
    parts = [display_label(entry)]
    sg = str(entry.get("space_group") or "").strip()
    if sg:
        parts.append(sg)
    cell = _cell_summary(entry)
    if cell:
        parts.append(cell)
    if eid:
        parts.append(f"COD {eid}")
    return " · ".join(p for p in parts if p)


def _cell_summary(entry: dict) -> str:
    """晶胞短摘要（脏数据容错，非正交相给全三边）。"""
    try:
        a = float(entry.get("cell_a") or 0.0)
        b = float(entry.get("cell_b") or 0.0)
        c = float(entry.get("cell_c") or 0.0)
    except (TypeError, ValueError):
        return ""
    if not (0.5 <= a <= 200 and 0.5 <= b <= 200 and 0.5 <= c <= 200):
        return ""
    if abs(a - b) < 1e-6 and abs(b - c) < 1e-6:
        return f"a={a:.3f} Å"
    return f"a={a:.3f} b={b:.3f} c={c:.3f} Å"


# ── 条目 → Phase ──────────────────────────────────────────

def phase_from_entry(
    eid: int | dict,
    db: PolyDatabase,
    *,
    wavelength: float = 1.5406,
    two_theta_range: Optional[tuple[float, float]] = None,
) -> Optional[Phase]:
    """库内条目 → 带晶胞与**全胞**位点、可直接精修的 :class:`Phase`。

    Args:
        eid: 库内条目号；也可直接传 ``search_entries`` / ``search_by_d_peaks``
            返回的 dict（取其中的 ``cod_id``）。
        db: 已打开的 polyDB。
        wavelength: 参考峰 d → 2θ 用的波长（应与待精修数据一致）。
        two_theta_range: 参考峰裁剪区间；``None`` 表示不裁剪。

    Returns:
        Phase；条目不存在 / 库不可用时 ``None``。
    """
    if isinstance(eid, dict):
        eid = int(eid.get("cod_id") or eid.get("ref_id") or 0)
    eid = int(eid or 0)
    if eid <= 0 or db is None:
        return None
    detail = db.get_phase(eid)
    if not detail:
        return None

    formula = str(detail.get("formula") or "")
    space_group = str(detail.get("space_group") or "")
    mineral = _clean_mineral(detail.get("mineral_name"), eid)
    label = (f"{mineral} - {formula}" if mineral and mineral != formula
             else formula) or f"COD {eid}"

    lattice = _lattice_of(detail)
    sites = _expanded_sites(db, eid, space_group)
    ref_peaks = _reference_peaks(detail, wavelength, two_theta_range)

    elements = {e for e in (detail.get("elements_list") or []) if e}
    if not elements:
        try:
            from polyxrd.utils.formula_parser import elements_from_db_formula

            elements = elements_from_db_formula(formula, space_group=space_group)
        except Exception:  # noqa: BLE001 - 式解析失败不该阻断加相
            elements = set()

    return Phase(
        name=f"{label} (COD {eid})",
        formula=formula,
        space_group=space_group,
        lattice=lattice,
        atomic_sites=sites,
        reference_peaks=ref_peaks,
        elements=elements,
        density=float(detail.get("density") or 0.0) or None,
        db_id=eid,
    )


def _lattice_of(detail: dict) -> Optional[LatticeParams]:
    """详情 dict → 晶胞；三边缺一或越界时返回 ``None``（宁缺勿造）。"""
    try:
        a = float(detail.get("cell_a") or 0.0)
        b = float(detail.get("cell_b") or 0.0)
        c = float(detail.get("cell_c") or 0.0)
    except (TypeError, ValueError):
        return None
    if not (0.5 <= a <= 200 and 0.5 <= b <= 200 and 0.5 <= c <= 200):
        return None

    def _angle(key: str) -> float:
        try:
            v = float(detail.get(key) or 90.0)
        except (TypeError, ValueError):
            return 90.0
        return v if 1.0 <= v <= 179.0 else 90.0

    return LatticeParams(
        a=a, b=b, c=c,
        alpha=_angle("cell_alpha"),
        beta=_angle("cell_beta"),
        gamma=_angle("cell_gamma"),
    )


def _expanded_sites(db: PolyDatabase, eid: int, space_group: str) -> list[dict]:
    """``sites.bin`` 的非对称单位位点 → 完整晶胞位点。

    ``expand_sites_by_symmetry`` 是幂等的：位点若已是全胞，原样通过。展开
    需要空间群符号；库里有空间群号无符号时按"只信原样"处理（不猜）。
    """
    try:
        sites = db.get_atomic_sites(eid)
    except Exception:  # noqa: BLE001 - 侧车缺失不该拖垮加相
        return []
    if not sites:
        return []
    if not (space_group or "").strip():
        return sites
    try:
        from polyxrd.services.phase_cif import expand_sites_by_symmetry

        return expand_sites_by_symmetry(sites, space_group)
    except Exception:  # noqa: BLE001 - 展开失败保持原样, 由精修前 resolver 兜底
        return sites


def _reference_peaks(
    detail: dict,
    wavelength: float,
    two_theta_range: Optional[tuple[float, float]],
) -> list[tuple[tuple[int, int, int], float, float]]:
    """``peaks_d_list`` / ``peaks_i_list`` → ``(hkl, 2θ, I)`` 列表。

    polyDB 的峰是 d-I 对（无 hkl），hkl 固定填 ``(0, 0, 0)`` —— 与
    ``phase_identifier`` 里从库内取参考峰的做法一致。
    """
    d_list = detail.get("peaks_d_list") or []
    i_list = detail.get("peaks_i_list") or []
    wl = float(wavelength or 1.5406)
    if wl <= 0:
        wl = 1.5406
    lo, hi = (-np.inf, np.inf) if two_theta_range is None else two_theta_range
    rows: list[tuple[float, float]] = []
    for d_val, i_val in zip(d_list, i_list):
        try:
            d = float(d_val)
            inten = float(i_val)
        except (TypeError, ValueError):
            continue
        if d <= 0:
            continue
        sin_theta = wl / (2.0 * d)
        if sin_theta > 1.0:
            continue
        tt = float(np.degrees(2.0 * np.arcsin(sin_theta)))
        if not (lo <= tt <= hi):
            continue
        rows.append((tt, inten))
    if not rows:
        return []
    if len(rows) > REF_PEAK_CAP:
        # 只留最强的一部分，再按 2θ 排序 —— 否则密集物相会挤掉强线
        rows = sorted(rows, key=lambda p: -p[1])[:REF_PEAK_CAP]
    rows.sort(key=lambda p: p[0])
    return [((0, 0, 0), tt, inten) for tt, inten in rows]


# ── 实测峰 → d-I 对 ───────────────────────────────────────

def peaks_to_d_i(
    two_theta: Iterable[float],
    intensity: Iterable[float],
    *,
    wavelength: float = 1.5406,
    top: int = DEFAULT_PEAK_COUNT,
) -> tuple[list[float], list[float]]:
    """实测峰 (2θ, I) → (d, I) 对，按强度取前 ``top`` 个。

    取"最强"而不是"全部"：向导里用户没做背景扣除/峰拟合，弱峰多为噪声，
    全给进去会把真物相的 ``main_peak`` 判定拉偏（Hanawalt 主峰原则要求
    最强测量峰必须被参考峰覆盖）。
    """
    wl = float(wavelength or 1.5406)
    if wl <= 0:
        wl = 1.5406
    pairs: list[tuple[float, float]] = []
    for tt, inten in zip(two_theta, intensity):
        try:
            t = float(tt)
            i = float(inten)
        except (TypeError, ValueError):
            continue
        if not (0.0 < t < 180.0):
            continue
        sin_theta = np.sin(np.radians(t / 2.0))
        if sin_theta <= 0:
            continue
        pairs.append((wl / (2.0 * sin_theta), i))
    if not pairs:
        return [], []
    n = max(1, int(top or 1))
    pairs = sorted(pairs, key=lambda p: -p[1])[:n]
    pairs.sort(key=lambda p: p[0])
    return [float(p[0]) for p in pairs], [float(p[1]) for p in pairs]
