"""polyDB v4 只读读取器（v4.0.0）
==================================

polyDB 是 PolyXRD 自有的外挂物相库格式（规范见
``docs/外挂库格式规范-polyDB-v4.md``）：目录容器 + 列存二进制 + 位图倒排。

本模块只做三件事：
  · :func:`probe` —— 轻量判别"这个目录是不是一个可用的 polyDB"；
  · :class:`PolyDatabase` —— mmap 只读访问：位图预筛 / 取峰 / 取位点 / 统计；
  · 与 ``phase_search.fetch_phase_record`` **同构**的返回字典，便于上游
    :meth:`PhaseIdentifier._rank_candidates` 原样复用（打分口径一字不改）。

设计要点
--------
* **零解析、零启动**：数组段用 ``np.memmap(mode="r")``，打开不读数据页；
  预筛只碰测量峰命中的那几个 d 箱（宽 0.05 Å），与库规模近似无关。
* **只读**：连接一律 ``file:...?mode=ro``；数组一律只读 mmap，绝不写回用户库。
* **元素过滤走位图**：``elem.u8`` 是 (118, N/8) 位图，按"条目元素 ⊆ 允许池"
  语义做位运算，避免逐相解析化学式。

为什么不复用 XinMatch 适配器：本项目 v4.0.0 起只维护 polyDB 一种外挂格式，
不为历史格式保留兼容层（见 ``docs/优化线路图-20261021.md``）。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

#: 打分原子直接复用 phase_search —— 同一口径, 不允许第二套
from polyxrd.services.phase_search import (
    dedupe_by_tol,
    interval_hit,
    match_positions,
)

_logger = logging.getLogger(__name__)

#: 元素符号（Z=1..118），与建库器保持一致
#:
#: ⚠️ 这张表就是 ``elem.u8`` 位图的行序（下标 = Z-1），**必须与建库端
#: ``tools/build_polydb.py`` 的 ``ELEMENTS`` 逐字一致**。2026-10-29 查出旧表
#: 漏了 **Rh（Z=45）**，导致 Rh 之后所有元素在读取端整体前移一位 ——
#: 查 W 实际拿到的是 Ta、查 Ta 拿到的是 Hf、查 Pb 拿到的是 Tl……
#: 表现是"元素限定后检不出物相"或给出同族近邻元素的相，而且只在 Z≥45
#: 的元素上发作（W/Ta/Pb/稀土/U 这些恰恰是 XRD 常见的重原子）。
ELEMENTS: tuple[str, ...] = tuple((
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
    "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe "
    "Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au "
    "Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr "
    "Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split())
Z_OF: dict[str, int] = {s: i + 1 for i, s in enumerate(ELEMENTS)}

#: 预筛默认候选池上限（进精确打分的相数）
_RANK_LIMIT = 1500
#: 位图箱宽（与建库器一致）
_BIN_WIDTH = 0.05
#: 前置键计算用的"强峰列数"：精确打分取 top-12 造 unique 峰表，必须覆盖同一集合
_BOUND_COLS = 12
#: 自适应扩池的起点与上限。实测 13 试样：起点 2000 时个别试样要扩两轮（单次
#: 最慢 2 s），起点 3000 只需一轮，耗时集中在 0.3–0.6 s。
_BOUND_FLOOR = 3000
#: 硬上限（与格式规范 §6「上限 12000」一致）。只有在前置键没能证明"剩下的行
#: 挤不进前 keep 名"时才会一路扩到这里；正常试样在起点就 break。
_BOUND_CEIL = 12000

_REQUIRED_FILES = ("meta.json", "index.sqlite", "peaks_d.f32", "peaks_i.u16",
                   "bins.u8", "elem.u8", "sites.bin", "sites_off.i64")
_REQUIRED_SECTIONS = ("peaks_d.f32", "peaks_i.u16", "bins.u8", "elem.u8")


@dataclass
class PolyDBStats:
    """库概况（供 UI 显示 / 体检）。"""

    path: str = ""
    format: str = ""
    schema_version: int = 0
    variant: str = ""
    phases: int = 0
    peaks: int = 0
    sites: int = 0
    k: int = 0
    bins: int = 0
    size_mb: float = 0.0
    peak_convention: dict = field(default_factory=dict)
    build: dict = field(default_factory=dict)


def probe(db_path: str | Path) -> tuple[bool, str]:
    """轻量判别：该目录是不是一个可用的 polyDB。

    Returns:
        ``(ok, reason)``；失败时 ``reason`` 为机器可读短标记
        （``not_a_directory`` / ``missing:meta.json`` / ``bad_meta`` /
        ``missing_section:bins.u8`` / ``phase_count_mismatch`` 等）。
    """
    p = Path(db_path)
    if not p.exists():
        return False, "file_not_found"
    if not p.is_dir():
        return False, "not_a_directory"
    for name in _REQUIRED_FILES:
        if not (p / name).exists():
            return False, "missing:" + name
    try:
        with open(p / "meta.json", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return False, "bad_meta"
    if meta.get("format") != "polyDB":
        return False, "bad_format:%s" % meta.get("format")
    if int(meta.get("schema_version", 0)) != 1:
        return False, "unsupported_schema:%s" % meta.get("schema_version")
    sections = meta.get("sections") or {}
    for key in _REQUIRED_SECTIONS:
        if key not in sections:
            return False, "missing_section:" + key
    try:
        n = int((meta.get("counts") or {}).get("phases", 0))
        shape = sections["peaks_d.f32"].get("shape") or [0, 0]
        k = int(shape[1])
    except (TypeError, ValueError, IndexError):
        return False, "bad_meta"
    if n <= 0 or k <= 0:
        return False, "empty_db"
    # 段字节数必须与 meta 一致（防止拷贝中断的半成品）
    for name, sec in sections.items():
        f = p / name
        if not f.exists():
            return False, "missing:" + name
        if int(sec.get("bytes", -1)) != f.stat().st_size:
            return False, "size_mismatch:" + name
    return True, ""


class PolyDatabase:
    """polyDB 只读访问器。

    生命周期：构造 → :meth:`is_ready` → :meth:`search_by_d_peaks` /
    :meth:`get_phase` / :meth:`get_atomic_sites`。数组与连接都懒加载，
    构造本身只读 1 KB 的 ``meta.json``。

    Args:
        db_path: polyDB 目录。``None`` 时读配置里的挂载路径
            （``get_config().get_polydb_path(variant)``，缺失则不可用）。
        variant: ``cod-inorg`` / ``cod-full``。仅在 ``db_path`` 省略时用于
            决定读哪一个配置槽位。
    """

    def __init__(self, db_path: str | Path | None = None,
                 variant: str = "cod-inorg") -> None:
        self.variant = variant
        if db_path is None:
            try:
                from polyxrd.config import get_config
                db_path = get_config().get_polydb_path(variant)
            except Exception:  # noqa: BLE001 - 配置未实现/缺键时按未挂载处理
                db_path = None
        self.path: Optional[Path] = Path(db_path) if db_path else None
        self.meta: dict = {}
        self._conn: Optional[sqlite3.Connection] = None
        self._arrays: Optional[dict] = None
        self._ready: Optional[bool] = None
        self._stats: Optional[PolyDBStats] = None
        self._elem_mask_cache: dict[frozenset, np.ndarray] = {}
        self._eid_arr: Optional[np.ndarray] = None
        self._lock = threading.Lock()

    # ── 基础状态 ──────────────────────────────────────────
    @property
    def available(self) -> bool:
        return self.path is not None and self.path.is_dir()

    def is_ready(self) -> bool:
        """目录在 + 必需文件齐 + meta 合法（结果缓存，失败也缓存）。"""
        if self._ready is None:
            if not self.available:
                self._ready = False
            else:
                ok, _ = probe(self.path)
                self._ready = ok
        return bool(self._ready)

    def reload(self) -> None:
        """丢弃连接与 mmap（换库/重新挂载后调用）。"""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
            self._conn = None
            self._arrays = None
            self._stats = None
            self._ready = None
            self.meta = {}
            self._elem_mask_cache.clear()
            self._eid_arr = None

    def close(self) -> None:
        self.reload()

    def __enter__(self) -> "PolyDatabase":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ── 懒加载 ────────────────────────────────────────────
    def _get_conn(self) -> Optional[sqlite3.Connection]:
        if self._conn is not None:
            return self._conn
        if not self.is_ready():
            return None
        try:
            self._conn = sqlite3.connect(
                "file:%s?mode=ro" % (self.path / "index.sqlite"),
                uri=True, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        except sqlite3.Error:
            self._conn = None
        return self._conn

    def _get_arrays(self) -> Optional[dict]:
        """mmap 各数组段（只读）。首次调用后常驻。"""
        if self._arrays is not None:
            return self._arrays
        with self._lock:
            if self._arrays is not None:
                return self._arrays
            if not self.is_ready():
                return None
            try:
                with open(self.path / "meta.json", encoding="utf-8") as fh:
                    self.meta = json.load(fh)
                c = self.meta["counts"]
                n = int(c["phases"])
                k = int(c["k"])
                sec = self.meta["sections"]
                nbins = int(sec["bins.u8"]["shape"][0])
                nbytes = (n + 7) // 8
                arr = {
                    "n": n, "k": k, "nbins": nbins, "nbytes": nbytes,
                    "d": np.memmap(self.path / "peaks_d.f32", np.float32, "r",
                                   shape=(n, k)),
                    "i": np.memmap(self.path / "peaks_i.u16", np.uint16, "r",
                                   shape=(n, k)),
                    "bins": np.memmap(self.path / "bins.u8", np.uint8, "r",
                                      shape=(nbins, nbytes)),
                    "elem": np.memmap(self.path / "elem.u8", np.uint8, "r",
                                      shape=(118, nbytes)),
                    "sites_off": np.fromfile(self.path / "sites_off.i64",
                                             dtype="<i8"),
                }
                self._arrays = arr
            except (OSError, ValueError, KeyError) as e:
                raise RuntimeError("polyDB 数组段载入失败: %s" % e) from e
            return self._arrays

    # ── 统计 ──────────────────────────────────────────────
    def stats(self) -> PolyDBStats:
        if self._stats is not None:
            return self._stats
        st = PolyDBStats(path=str(self.path or ""))
        if not self.available:
            self._stats = st
            return st
        try:
            st.size_mb = round(sum(f.stat().st_size for f in self.path.iterdir()
                                   if f.is_file()) / 1e6, 1)
        except OSError:
            pass
        try:
            arr = self._get_arrays()
        except RuntimeError:
            arr = None
        if arr is None:
            self._stats = st
            return st
        c = self.meta.get("counts", {})
        st.format = str(self.meta.get("format", ""))
        st.schema_version = int(self.meta.get("schema_version", 0))
        st.variant = str(self.meta.get("variant", ""))
        st.phases = int(c.get("phases", arr["n"]))
        st.peaks = int(c.get("peaks", 0))
        st.sites = int(c.get("sites", 0))
        st.k = int(arr["k"])
        st.bins = int(arr["nbins"])
        st.peak_convention = dict(self.meta.get("peak_convention") or {})
        st.build = dict(self.meta.get("build") or {})
        self._stats = st
        return st

    # ── 元素位图过滤 ──────────────────────────────────────
    def _element_mask(self, allowed: Iterable[str]) -> Optional[np.ndarray]:
        """``allowed`` 元素池 → 长度 N 的布尔掩码（条目元素 ⊆ 允许池）。"""
        arr = self._get_arrays()
        if arr is None:
            return None
        pool = frozenset(str(e).strip().title() for e in allowed if str(e).strip())
        if not pool:
            return None
        cached = self._elem_mask_cache.get(pool)
        if cached is not None:
            return cached
        n, nbytes = arr["n"], arr["nbytes"]
        allowed_z = {Z_OF[s] for s in pool if s in Z_OF}
        bad = np.zeros((nbytes,), dtype=np.uint8)
        for z in range(1, 119):
            if z in allowed_z:
                continue
            bad |= np.asarray(arr["elem"][z - 1])
        # 位序必须与建库端一致：byte j>>3 的 bit j&7（低位先行）
        mask = np.unpackbits(bad, count=n, bitorder="little").view(bool)
        mask = ~mask
        if len(self._elem_mask_cache) > 16:      # 简单上限，避免无界增长
            self._elem_mask_cache.clear()
        self._elem_mask_cache[pool] = mask
        return mask

    # ── 预筛 ──────────────────────────────────────────────
    def prescreen(
        self,
        measured_d: list[float],
        measured_i: list[float] | None = None,
        *,
        tolerance: float = 0.02,
        min_match: int = 3,
        rank_limit: int = _RANK_LIMIT,
        elements_allowed: Iterable[str] | None = None,
    ) -> np.ndarray:
        """位图倒排预筛，返回候选行号数组（按命中质量降序，≤rank_limit）。

        完整实现见 :meth:`ordered_candidates`；这里只做截断，保留旧调用签名。
        """
        rows, _bounds = self.ordered_candidates(
            measured_d, measured_i, tolerance=tolerance, min_match=min_match,
            elements_allowed=elements_allowed, limit=rank_limit)
        return rows

    def ordered_candidates(
        self,
        measured_d: list[float],
        measured_i: list[float] | None = None,
        *,
        tolerance: float = 0.02,
        tolerance_rel: float = 0.0,
        min_match: int = 3,
        elements_allowed: Iterable[str] | None = None,
        limit: int | None = None,
        main_peak_topk: int = 3,
    ) -> tuple[np.ndarray, np.ndarray]:
        """候选行号（按精确排序主键的**前三个分量**降序）+ 对应键三元组。

        **两级漏斗**：

        1. **资格（必要条件的超集）**：位图 ``counts >= min_match``。位图索引
           每相最强 ``bins_top_m``(=40) 条峰、窗口按 ``±tolerance`` 展开，而
           精确打分只看最强 ``max_ref_peaks``(=40) 条峰，故凡是精确打分能凑够
           ``min_match`` 个测量峰的物相，位图必然也命中 ≥min_match —— 资格集
           是精确结果的**超集**，不会因索引截断丢物相。
        2. **前置键分层**：资格集实测占全库 98% 以上（25 个测量峰 × 40 条参考
           峰，凑 3 个命中太容易），真正决定谁进池的是**排序**。所以按精确
           打分主键的前三个分量排：

                mh   = main_peak_match（该相最强峰是否命中实测最强峰之一）
                p5   = top_precision（最强 5 个去重峰里有几个被观察到）
                wrec = intensity_weighted_top_recall（被解释测量峰的强度权重和）

           这三个分量由 :meth:`_bound_keys` **精确**算出（不是近似上界），
           因此"下一行的三元组严格更小 ⇒ 该行及之后的行都不可能挤进前 keep
           名"成立，可安全截断；边界处由 :meth:`search_by_d_peaks` 自适应扩池
           复核。

        Returns:
            ``(rows, bounds)``：``rows`` 为行号降序数组，``bounds`` 形状
            ``(len(rows), 3)``，列序 ``[mh, p5, wrec]``。
        """
        arr = self._get_arrays()
        if arr is None or not measured_d:
            return np.zeros(0, dtype=np.int64), np.zeros((0, 3))
        md = np.asarray(sorted(float(x) for x in measured_d), dtype=np.float64)
        if md.size == 0:
            return np.zeros(0, dtype=np.int64), np.zeros((0, 3))
        n = arr["n"]
        # uint16: 测量峰数可能超过 255（默认寻峰在复杂谱上能出 60~90 条，
        # 但调用方可以传更多）—— uint8 会静默回绕，直接让候选资格算错。
        counts = np.zeros(n, dtype=np.uint16)
        mi = None
        if measured_i is not None and len(measured_i) == len(measured_d):
            pairs = sorted(zip((float(x) for x in measured_d),
                               (float(v) for v in measured_i)), key=lambda p: p[0])
            mi = np.asarray([p[1] for p in pairs], dtype=np.float64)

        bins = arr["bins"]
        nbins = arr["nbins"]
        for k in range(md.size):
            lo = md[k] - tolerance
            hi = md[k] + tolerance
            b0 = max(0, int(lo / _BIN_WIDTH))
            b1 = min(nbins - 1, int(hi / _BIN_WIDTH))
            if hi >= 25.0:
                b1 = nbins - 1            # 并入 overflow 箱
            hit = np.zeros(n, dtype=bool)
            for b in range(b0, b1 + 1):
                hit |= np.unpackbits(np.asarray(bins[b]), count=n,
                                     bitorder="little").view(bool)
            counts += hit.astype(np.uint16)

        cand = np.flatnonzero(counts >= max(1, min(int(min_match), 12)))
        if cand.size == 0:
            return cand, np.zeros((0, 3))
        if elements_allowed:
            em = self._element_mask(elements_allowed)
            if em is not None and em.size == n:
                cand = cand[em[cand]]
                if cand.size == 0:
                    return cand, np.zeros((0, 3))
        bounds = self._bound_keys(cand, md, mi, tolerance, main_peak_topk,
                                  tolerance_rel=tolerance_rel)
        # 主键 = 前置键降序（mh → p5 → wrec），命中数只作末位决胜
        idx = np.lexsort((-counts[cand], -bounds[:, 2],
                          -bounds[:, 1], -bounds[:, 0]))
        order = cand[idx]
        bounds = bounds[idx]
        if limit is not None:
            k = max(1, int(limit))
            return order[:k], bounds[:k]
        return order, bounds

    def _bound_keys(self, rows: np.ndarray, md: np.ndarray,
                    mi: Optional[np.ndarray], tolerance: float,
                    main_peak_topk: int = 3,
                    chunk: int = 16384,
                    tolerance_rel: float = 0.0) -> np.ndarray:
        """为候选行**精确**算出排序主键的前三个分量 ``[mh, p5, wrec]``。

        为什么必须是精确值而不是近似上界
        --------------------------------
        截断的安全性依赖"排序键的上界"：只有保证 ``bound >= exact``，"下一行的
        界严格更小 ⇒ 它及之后的行都不可能挤进前 keep 名"才成立。

        0.2–3.x 的旧实现用的是"最近测量峰 + 条数截断"的近似界，实测在真实库
        (COD-Inorg, 77,500 相) 上**并不成立**：暴力打分 top-300 的候选里
        200~294 行的分量被低估、最大低估 0.375；5-1 试样因此从 top-100 里丢了
        3 个本该入选的物相。根因是它用"列命中数"近似"被解释测量峰数"——当两个
        测量峰落进同一条参考峰的容差窗时，列命中数 < 被解释测量峰数。

        现在改为精确复刻 :func:`_hanawalt_metric` 的前三个分量：

        * **贪心去重**：与 :func:`dedupe_by_tol` 同规则（只与已保留项比、容差取
          候选自身 ``_tol(d)``、``<=`` 判据、顺序敏感）；
        * **窗口并集**：对前 5 个去重峰的容差窗做差分数组并集，得到 ``obs``
          （= ``n_top_observed``）与强度权重和；
        * 每相只读前 ``_BOUND_COLS``(=12) 列 —— 精确打分造 unique 峰表同样只取
          最强 12 条，列集合完全覆盖。

        代价是每块 12 列的两两比较（66 组向量化比较）+ 5 次 searchsorted，实测
        77,500 相约 60~90 ms，与旧近似界同一量级。
        """
        arr = self._get_arrays()
        if arr is None or rows.size == 0:
            return np.zeros((0, 3))
        md = np.asarray(md, dtype=np.float64)
        nm = int(md.size)
        if nm == 0:
            return np.zeros((0, 3))
        ms = np.sort(md)
        trel = float(tolerance_rel or 0.0)
        use_rel = trel > 0.0
        dcols = _BOUND_COLS
        # 精确打分的 n_top = min(n_i, max(n_meas+2, 8), 12)；n_i>=12 时前 12 列
        # 就是 top-12，n_i<12 时前 12 列里的有效列数就是 n_i。
        kcap = min(dcols, max(nm + 2, 8))
        # 归一化强度权重，按 d 升序排列（与 ms 一一对应）
        w_sorted: Optional[np.ndarray] = None
        if mi is not None and mi.size == nm and float(np.sum(mi)) > 0:
            wnorm = np.asarray(mi, dtype=np.float64) / float(np.sum(mi))
            w_sorted = wnorm[np.argsort(md)]
        main_meas = ([float(md[j]) for j in np.argsort(-mi)[:max(1, main_peak_topk)]]
                     if mi is not None and mi.size == nm else [float(md[-1])])
        out = np.zeros((rows.size, 3), dtype=np.float64)
        for s in range(0, rows.size, chunk):
            e = min(s + chunk, rows.size)
            r = e - s
            d = np.asarray(arr["d"][rows[s:e], :dcols], dtype=np.float64)
            valid = d > 0
            nvalid = valid.sum(axis=1)
            n_top = np.minimum(nvalid, kcap)
            jj = np.arange(dcols)[None, :]
            col_ok = valid & (jj < n_top[:, None])
            tol_col = (np.maximum(tolerance, trel * d) if use_rel
                       else np.full(d.shape, float(tolerance)))
            # ── ① 贪心去重（只与已保留项比，容差用候选自身）──
            kept = np.zeros((r, dcols), dtype=bool)
            kept[:, 0] = col_ok[:, 0]
            for j in range(1, dcols):
                near = np.zeros(r, dtype=bool)
                for i in range(j):
                    near |= kept[:, i] & (np.abs(d[:, j] - d[:, i])
                                          <= tol_col[:, j])
                kept[:, j] = col_ok[:, j] & ~near
            # 去重后的峰表（按名次散射到 12 个槽位，最多 12 条）：
            #   · 前 5 条 = 精确打分的 k5，用于 top_precision 的分子 obs；
            #   · 全部 12 条 = 精确打分的 unique_top_d，用于 intensity_weighted
            #     _top_recall（注意：wrec 的分子是"被**所有**去重强峰覆盖的测量峰
            #     强度"，不是只被前 5 条覆盖的那部分 —— 0.2 版就在这点上写错）。
            rank = np.cumsum(kept, axis=1) - 1
            ud = np.full((r, dcols), np.nan)
            for j in range(dcols):
                sel = kept[:, j]
                if not sel.any():
                    continue
                idx = np.flatnonzero(sel)
                ud[idx, rank[sel, j]] = d[sel, j]
            ud_ok = ~np.isnan(ud)
            eden = np.maximum(ud_ok[:, :5].sum(axis=1), 1).astype(np.float64)
            # ── ② 容差窗：obs（前 5 条各自是否被观察到）与 wrec（全部去重强峰）──
            # 精确口径两个都易错，逐条对齐 `_hanawalt_metric`：
            #   obs = "前 5 条去重强峰里有几条被观察到"（每条最多算 1，不是被覆盖的
            #         测量峰个数 —— 两个测量峰落进同一窗时仍只算 1）；
            #   wrec = 被**全部** 12 条去重强峰覆盖的测量峰强度权重和 / 总强度。
            obs = np.zeros(r, dtype=np.int64)
            diff = (np.zeros((r, nm + 1), dtype=np.int16)
                    if w_sorted is not None else None)
            for c in range(dcols):
                ok = ud_ok[:, c]
                if not ok.any():
                    continue
                dc = np.nan_to_num(ud[:, c], nan=0.0)
                tc = (np.maximum(tolerance, trel * dc) if use_rel
                      else np.full(r, float(tolerance)))
                lo = np.searchsorted(ms, dc - tc, side="left")
                hi = np.searchsorted(ms, dc + tc, side="right")
                if c < 5:                       # top_precision 只看最强 5 条
                    obs[ok] += (hi[ok] > lo[ok]).astype(np.int64)
                if diff is not None:
                    # 加权召回按"被任一强峰覆盖的测量峰"计权, 同一测量峰只能
                    # 算一次 —— 用差分数组做窗口并集, 避免重叠窗重复加权。
                    idx = np.flatnonzero(ok)
                    diff[idx, lo[ok]] += 1
                    diff[idx, hi[ok]] -= 1
            out[s:e, 1] = obs / eden
            if diff is not None:
                covered = np.cumsum(diff, axis=1)[:, :nm] > 0
                wsum = covered.astype(np.float64) @ w_sorted
                out[s:e, 2] = np.minimum(wsum, 1.0)
            # ── ③ main_peak_match（容差口径与 _hanawalt_metric 完全一致）──
            first = d[:, 0]
            mh = np.zeros(r, dtype=np.float64)
            if mi is not None and mi.size == nm:
                for mdk in main_meas:
                    if use_rel:
                        lim = np.maximum(np.maximum(tolerance, trel * first),
                                         max(tolerance, trel * float(mdk)))
                    else:
                        lim = np.full(r, float(tolerance))
                    mh = np.maximum(mh, (np.abs(first - mdk) <= lim)
                                    .astype(np.float64))
            out[s:e, 0] = mh
        return out

    # ── 取数 ──────────────────────────────────────────────
    def peaks_of_rows(self, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """批量取峰（含空槽，调用方用 d>0 过滤）。"""
        arr = self._get_arrays()
        if arr is None:
            return np.zeros((0, 0)), np.zeros((0, 0))
        rows = np.asarray(rows, dtype=np.int64)
        d = np.asarray(arr["d"][rows], dtype=np.float64)
        i = np.asarray(arr["i"][rows], dtype=np.float64) / 65535.0 * 1000.0
        return d, i

    def row_of_eid(self, eid: int) -> int:
        """``entries.eid`` → 数组段行号（``entries.row_idx``）。缺失返回 -1。

        注意：``eid`` 是 INTEGER PRIMARY KEY，等价于 rowid，因此**不能**用
        ``rowid-1`` 当行号 —— 必须走显式的 ``row_idx`` 列。
        """
        conn = self._get_conn()
        if conn is None:
            return -1
        try:
            r = conn.execute("SELECT row_idx FROM entries WHERE eid=?",
                             (int(eid),)).fetchone()
        except sqlite3.Error:
            return -1
        return int(r[0]) if r and r[0] is not None else -1

    def get_phase(self, eid: int) -> Optional[dict]:
        """取一条相详情，键与 ``phase_search.fetch_phase_record`` 同构。"""
        conn = self._get_conn()
        arr = self._get_arrays()
        if conn is None or arr is None:
            return None
        try:
            r = conn.execute(
                "SELECT row_idx, eid, formula, formula_red, mineral, space_group, "
                "sg_number, elements, a, b, c, alpha, beta, gamma, volume, "
                "density, z, n_peaks, cif_rel FROM entries WHERE eid=?",
                (int(eid),)).fetchone()
        except sqlite3.Error:
            return None
        if r is None or r["row_idx"] is None:
            return None
        row = int(r["row_idx"])
        if row < 0 or row >= arr["n"]:
            return None
        d = np.asarray(arr["d"][row], dtype=np.float64)
        i = np.asarray(arr["i"][row], dtype=np.float64) / 65535.0 * 1000.0
        m = d > 0
        return {
            "cod_id": int(r["eid"]),
            "ref_id": int(r["eid"]),
            "display_id": int(r["eid"]),
            "formula": r["formula"] or "",
            "formula_red": r["formula_red"] or "",
            "mineral_name": r["mineral"] or "",
            "space_group": r["space_group"] or "",
            "sg_number": int(r["sg_number"] or 0),
            "elements_list": [t.strip() for t in (r["elements"] or "").split(",") if t.strip()],
            "cell_a": float(r["a"] or 0.0), "cell_b": float(r["b"] or 0.0),
            "cell_c": float(r["c"] or 0.0),
            "cell_alpha": float(r["alpha"] or 90.0),
            "cell_beta": float(r["beta"] or 90.0),
            "cell_gamma": float(r["gamma"] or 90.0),
            "volume": float(r["volume"] or 0.0),
            "density": float(r["density"] or 0.0),
            "z": int(r["z"] or 0),
            "n_peaks": int(r["n_peaks"] or int(m.sum())),
            "cif_rel": r["cif_rel"] or "",
            "peaks_d_list": d[m].tolist(),
            "peaks_i_list": i[m].tolist(),
            "source": "polydb",
        }

    @staticmethod
    def _legacy_display_id(eid: int) -> str:
        """旧 COD 展示编号（v4.2.1 兼容 MCP 老客户端）。"""
        return f"97-{eid:07d}"

    @staticmethod
    def _legacy_ref_id(eid: int) -> str:
        """旧 COD 参考编号（v4.2.1 兼容 MCP 老客户端）。"""
        return f"96-{eid // 10000:03d}-{eid % 10000:04d}"

    @staticmethod
    def _parse_eid_query(q: str) -> Optional[int]:
        """把 ``1011097`` / ``97-1011097`` / ``96-101-1097`` 解析为 eid。

        v4.2.0 的 ``search_entries`` 只认纯数字，导致旧 MCP 客户端常用的
        两种带前缀编号静默返回空；这里恢复旧行为的兼容解析（v4.2.1）。
        """
        compact = (q or "").replace(" ", "").replace("_", "")
        core = compact.replace("-", "")
        if not core.isdigit():
            return None
        if len(core) == 9 and core[:2] in ("96", "97"):
            return int(core[2:])
        if len(core) == 7:
            return int(core)
        return None

    def search_entries(self, query: str, limit: int = 20) -> list[dict]:
        """按 化学式 / 约化式 / 矿名 / 空间群 / 编号 模糊查相（只读）。

        供 MCP 工具与 UI 的"按文本找相"用（v4.2 起取代原 COD sqlite 的
        ``search_cod_phases``）。SQL LIKE + 主键等值，不碰 mmap 段。

        v4.2.1 兼容增强：
          * ``1011097`` / ``97-1011097`` / ``96-101-1097`` 均按 eid 精确查；
          * 返回值补 ``ref_id`` / ``display_id``（旧客户端字段契约）；
          * 化学式查询先用 :func:`normalize_cod_formula` 规范化（``SiO2`` →
            ``O2 Si``），空间群比较忽略空格（``Fd-3m`` ↔ ``F d -3 m``）。
        """
        conn = self._get_conn()
        if conn is None:
            return []
        q = (query or "").strip()
        if not q:
            return []
        n = max(1, min(int(limit or 20), 500))
        cols = ("eid, formula, formula_red, mineral, space_group, sg_number, "
                "a, b, c, alpha, beta, gamma, volume, density, n_peaks")
        eid = self._parse_eid_query(q)
        try:
            if eid is not None:
                rows = conn.execute(
                    f"SELECT {cols} FROM entries WHERE eid = ?", (eid,)
                ).fetchall()
            else:
                pat = f"%{q}%"
                clauses = [
                    "formula LIKE ?", "formula_red LIKE ?", "mineral LIKE ?",
                    "REPLACE(space_group, ' ', '') LIKE ?",
                ]
                params = [pat, pat, pat, f"%{q.replace(' ', '')}%"]
                norm = ""
                try:
                    from polyxrd.utils.formula_parser import normalize_cod_formula

                    norm = normalize_cod_formula(q) or ""
                except Exception:  # noqa: BLE001 - 规范化失败退回原 LIKE
                    norm = ""
                order = "ORDER BY n_peaks DESC"
                order_params: list = []
                if norm:
                    flat = norm.replace(" ", "")
                    clauses += [
                        "REPLACE(formula, ' ', '') = ?",
                        "REPLACE(formula, ' ', '') LIKE ?",
                    ]
                    params += [flat, f"%{flat}%"]
                    # 精确化学式（如 SiO2 -> O2 Si）必须排在模糊命中之前，
                    # 否则 n_peaks 高的杂相会把真物相挤出 limit。
                    order = ("ORDER BY (REPLACE(formula, ' ', '') = ?) DESC, "
                             "n_peaks DESC")
                    order_params = [flat]
                rows = conn.execute(
                    f"SELECT {cols} FROM entries WHERE (" + " OR ".join(clauses)
                    + ") " + order + " LIMIT ?",
                    (*params, *order_params, n),
                ).fetchall()
        except sqlite3.Error:
            return []
        out: list[dict] = []
        for r in rows[:n]:
            eid_i = int(r["eid"])
            out.append({
                "cod_id": eid_i,
                "ref_id": self._legacy_ref_id(eid_i),
                "display_id": self._legacy_display_id(eid_i),
                "formula": r["formula"] or "",
                "formula_red": r["formula_red"] or "",
                "mineral_name": r["mineral"] or "",
                "space_group": r["space_group"] or "",
                "sg_number": int(r["sg_number"] or 0),
                "cell_a": float(r["a"] or 0.0),
                "cell_b": float(r["b"] or 0.0),
                "cell_c": float(r["c"] or 0.0),
                "cell_alpha": float(r["alpha"] or 90.0),
                "cell_beta": float(r["beta"] or 90.0),
                "cell_gamma": float(r["gamma"] or 90.0),
                "volume": float(r["volume"] or 0.0),
                "density": float(r["density"] or 0.0),
                "n_peaks": int(r["n_peaks"] or 0),
            })
        return out

    def get_atomic_sites(self, eid: int) -> list[dict]:
        """取**非对称单位**原子位点（CIF 原样）。缺失返回空列表。

        ⚠ 调用方需按空间群展开后才能进"全胞"语义的精修链路：
        本项目的 ``phase_identifier._make_polydb_phase`` 出口已用
        ``phase_cif.expand_sites_by_symmetry`` 展开。直接拿本方法结果去
        构造 pymatgen ``Structure`` 会给高对称相造出假峰（v4.1.1 修复）。
        """
        arr = self._get_arrays()
        if arr is None:
            return []
        row = self.row_of_eid(eid)
        if row < 0:
            return []
        off = arr["sites_off"]
        if row + 1 >= off.size:
            return []
        start, end = int(off[row]), int(off[row + 1])
        cnt = (end - start) // 17
        if cnt <= 0:
            return []
        try:
            with open(self.path / "sites.bin", "rb") as fh:
                fh.seek(start)
                buf = fh.read(end - start)
        except OSError:
            return []
        out = []
        for j in range(cnt):
            base = j * 17
            z = buf[base]
            x, y, zz, occ = np.frombuffer(buf[base + 1:base + 17], dtype="<f4")
            out.append({
                "label": ELEMENTS[z - 1] if 0 < z <= len(ELEMENTS) else "?",
                "element": ELEMENTS[z - 1] if 0 < z <= len(ELEMENTS) else "?",
                "x": float(x), "y": float(y), "z": float(zz),
                "occupancy": float(occ),
                "u_iso": None,
            })
        return out

    # ── 检索主入口（与 search_phases_by_d_peaks 同签名/同排序口径） ──
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
        main_peak_topk: int = 1,
        elements_allowed: set | None = None,
        rank_limit: int = _RANK_LIMIT,
    ) -> list[dict]:
        """Hanawalt d-I 预筛 + 精确打分，返回候选 dict 列表。

        语义与 :func:`phase_search.search_phases_by_d_peaks` 对齐
        （同样的容差规则、排序主键、返回字段），差异只在候选生成方式。
        """
        arr = self._get_arrays()
        if arr is None or not measured_d:
            return []
        md = np.asarray(sorted(float(x) for x in measured_d), dtype=np.float64)
        n_meas = int(md.size)
        if n_meas == 0:
            return []
        if measured_i is not None and len(measured_i) == len(measured_d):
            pairs = sorted(zip((float(x) for x in measured_d),
                               (float(v) for v in measured_i)), key=lambda p: p[0])
            mi = np.asarray([p[1] for p in pairs], dtype=np.float64)
        else:
            mi = None
        main_topk = []
        if mi is not None:
            kk = max(1, int(main_peak_topk or 1))
            main_topk = [float(md[j]) for j in np.argsort(-mi)[:kk]]

        rows_all, bounds = self.ordered_candidates(
            measured_d, measured_i, tolerance=tolerance,
            tolerance_rel=tolerance_rel, min_match=min_match,
            elements_allowed=elements_allowed, main_peak_topk=main_peak_topk)
        if rows_all.size == 0:
            return []

        trel = float(tolerance_rel or 0.0)
        use_rel = trel > 0.0
        tol_abs = float(tolerance)
        # 「前多少名必须精确」= 调用方真实要的条数（不是候选池上限）
        keep = max(1, int(limit))

        def _score(sel: np.ndarray) -> list[dict]:
            """对一批行做精确打分（与旧库同一套 `_hanawalt_metric`）。"""
            if sel.size == 0:
                return []
            d_all, i_all = self.peaks_of_rows(sel)
            buf: list[dict] = []
            for idx in range(sel.size):
                d_np = d_all[idx]
                i_np = i_all[idx]
                m = d_np > 0
                d_np, i_np = d_np[m], i_np[m]
                if d_np.size == 0:
                    continue
                met = _hanawalt_metric(
                    d_np, i_np, md=md, mi=mi, main_meas_d_topk=main_topk,
                    tol_abs=tol_abs, trel=trel, use_rel=use_rel,
                    max_ref_peaks=max_ref_peaks)
                if met is None or met["n_matched_meas"] < min_match:
                    continue
                buf.append(dict(met, _row=int(sel[idx])))
            return buf

        def _key(r: dict) -> tuple:
            return (r["main_peak_match"], r["top_precision"],
                    r["intensity_weighted_top_recall"], r["top_recall"],
                    r["meas_ratio"], r["score"])

        def _order_key(r: dict) -> tuple:
            """排序键 = 打分键 + 行号决胜。

            多相样品里同一套峰的"仿真相"常有几十上百个条目**打分完全并列**
            （实测 1-2 的第 96~105 名键完全相同）。并列时若不定决胜规则，
            截断边界上取哪几条就变成运气，A/B 比对会出现"假漏检"。这里用
            行号（建库顺序，= 旧库的扫描顺序）决胜，与旧库逐位一致。
            """
            return _key(r) + (-r["_row"],)

        # ── 自适应扩池：先按前置键排序取一批精确打分，再核查"剩下的行还有没有
        #    可能挤进前 keep 名"；前置键严格小于门槛就收工。这样既不用全库
        #    扫描，也不会因为拍脑袋定候选池大小而丢掉本该入围的物相。
        #
        #    循环条件只写 `scored < rows_all.size`：是否停由"前置键证明安全"
        #    决定，_BOUND_CEIL 只作异常库的兜底上限。旧写法把 `scored <
        #    _BOUND_CEIL` 放进 while 条件，会在"尚未证明安全"时静默停手
        #    （上限还被写成 4000 ⇒ 实际最多只精确打分 6000 相）。
        out = _score(rows_all[:min(rows_all.size, max(keep * 4, _BOUND_FLOOR))])
        scored = min(rows_all.size, max(keep * 4, _BOUND_FLOOR))
        while scored < rows_all.size:
            out.sort(key=_order_key, reverse=True)
            if len(out) >= keep:
                kth = _key(out[keep - 1])
                nb = bounds[scored]
                if (nb[0], nb[1], nb[2]) < (kth[0], kth[1], kth[2]):
                    break
            if scored >= _BOUND_CEIL:
                _logger.warning(
                    "polyDB 自适应扩池触顶（scored=%d/%d, keep=%d）："
                    "排序键边界无法证明安全，结果可能漏掉低排名物相",
                    scored, rows_all.size, keep)
                break
            nxt = min(rows_all.size, max(scored * 2, scored + 1000))
            out.extend(_score(rows_all[scored:nxt]))
            scored = nxt
        out.sort(key=_order_key, reverse=True)

        eids = self.eid_of_rows([r["_row"] for r in out[:limit]])
        final: list[dict] = []
        for rec, eid in zip(out[:limit], eids):
            rec = {k: v for k, v in rec.items() if k != "_row"}
            rec.update(cod_id=eid, ref_id=eid, display_id=eid)
            final.append(rec)
        out = final
        # 补齐展示字段（只对最终 limit 条查询，避免 N 次元数据查询）
        for rec in out[:limit]:
            conn = self._get_conn()
            if conn is None:
                break
            try:
                r = conn.execute(
                    "SELECT formula, space_group, sg_number, mineral, n_peaks "
                    "FROM entries WHERE eid=?",
                    (rec["cod_id"],)).fetchone()
            except sqlite3.Error:
                break
            if r:
                rec["formula"] = r["formula"] or ""
                rec["space_group"] = r["space_group"] or ""
                # v5.1: 国际表编号。同物相的替代设置（P n m a / P b n m、
                # C m c m / B b m m / A m a m）共享同一编号，而空间群**字符串**
                # 写法各异 —— 折叠去重必须用编号，否则同一物相的不同设置会被
                # 当成不同相、白占 top-N 名额（`_cod_comp_key` 优先用这个）。
                rec["sg_number"] = int(r["sg_number"] or 0)
                rec["mineral_name"] = r["mineral"] or ""
                rec["n_peaks"] = int(r["n_peaks"] or 0)
        return out[:limit]

    def eid_of_rows(self, rows: Iterable[int]) -> list[int]:
        """批量 ``row_idx`` → ``eid``（走缓存的 eid 数组，避免 N 次 SQL）。"""
        arr = self._eid_array()
        out: list[int] = []
        for r in rows:
            r = int(r)
            out.append(int(arr[r]) if 0 <= r < arr.size else -1)
        return out

    def _eid_array(self) -> np.ndarray:
        """``row_idx → eid`` 映射表（一次性载入，N×8 B）。"""
        with self._lock:
            if self._eid_arr is not None:
                return self._eid_arr
            conn = self._get_conn()
            if conn is None:
                return np.zeros(0, dtype=np.int64)
            try:
                vals = conn.execute(
                    "SELECT eid FROM entries ORDER BY row_idx").fetchall()
            except sqlite3.Error:
                return np.zeros(0, dtype=np.int64)
            self._eid_arr = np.asarray([int(v[0]) for v in vals], dtype=np.int64)
            return self._eid_arr

    def eid_of_row(self, row: int) -> int:
        """数组段行号 → ``eid``（走 ``entries.row_idx`` 唯一索引）。"""
        conn = self._get_conn()
        if conn is None:
            return -1
        try:
            r = conn.execute("SELECT eid FROM entries WHERE row_idx=?",
                             (int(row),)).fetchone()
        except sqlite3.Error:
            return -1
        return int(r[0]) if r else -1

    def __len__(self) -> int:
        try:
            return int(self.stats().phases)
        except Exception:  # noqa: BLE001
            return 0


def _hanawalt_metric(
    d_np: np.ndarray,
    i_np: np.ndarray,
    *,
    md: np.ndarray,
    mi: np.ndarray | None,
    main_meas_d_topk: list[float],
    tol_abs: float,
    trel: float,
    use_rel: bool,
    max_ref_peaks: int,
) -> Optional[dict]:
    """单相 Hanawalt 度量 —— 逐行对齐 :func:`phase_search.search_phases_by_d_peaks`。

    只依赖数据数组，不碰数据库；因此 polyDB / 旧库共用同一套打分。
    """
    n_meas = int(md.size)
    n_i = int(i_np.size)
    if n_i == 0 or n_meas == 0:
        return None
    order = np.argsort(-i_np, kind="stable")
    ref_d = d_np[order[:max_ref_peaks]]
    n_ref_used = int(ref_d.size)
    if n_ref_used == 0:
        return None
    t_ref = (np.maximum(tol_abs, trel * ref_d) if use_rel
             else np.full(n_ref_used, tol_abs))
    hit_ref, pos_ref = match_positions(md, ref_d - t_ref, ref_d + t_ref)
    n_matched_ref = int(hit_ref.sum())
    n_matched_meas = int(np.unique(pos_ref[hit_ref]).size)

    n_top = min(n_i, max(n_meas + 2, 8), 12)
    top_d = d_np[order[:n_top]]
    unique_top_d = dedupe_by_tol(top_d, tol_abs, trel, use_rel)
    if not unique_top_d:
        return None
    ud = np.asarray(unique_top_d, dtype=np.float64)
    t_md = (np.maximum(tol_abs, trel * md) if use_rel else np.full(n_meas, tol_abs))
    hit_m = interval_hit(np.sort(ud), md - t_md, md + t_md)
    n_meas_in_top = int(hit_m.sum())
    covered_i_sum = float(mi[hit_m].sum()) if mi is not None else 0.0

    main_peak_match = 0.0
    if mi is not None:
        phase_main_d = float(ud[0])
        for mdk in main_meas_d_topk:
            # 相对容差时取"物相主峰 tol"与"测量主峰 tol"的较大值 —— 与
            # phase_search.search_phases_by_d_peaks 的 max(tol(phase), tol(md))
            # 逐字一致（旧实现只取物相侧，trel>0 时两条链路的 mh 会分叉）。
            if use_rel:
                t_main = max(max(tol_abs, trel * phase_main_d),
                             max(tol_abs, trel * float(mdk)))
            else:
                t_main = tol_abs
            if abs(phase_main_d - mdk) <= t_main:
                main_peak_match = 1.0
                break
    k5 = ud[:5]
    t5 = (np.maximum(tol_abs, trel * k5) if use_rel else np.full(k5.size, tol_abs))
    n_top_observed = int(interval_hit(md, k5 - t5, k5 + t5).sum())

    total_i = float(mi.sum()) if mi is not None else 0.0
    top_recall = n_meas_in_top / n_meas if n_meas else 0.0
    recall = n_matched_meas / n_meas if n_meas else 0.0
    return {
        "n_ref_used": n_ref_used,
        "n_matched_ref": n_matched_ref,
        "n_matched_meas": n_matched_meas,
        "n_meas_in_top": n_meas_in_top,
        "n_top_unique": len(unique_top_d),
        "n_top_observed": n_top_observed,
        "n_top_k": int(min(len(unique_top_d), 5)),
        "top_recall": top_recall,
        "top_precision": n_top_observed / float(max(1, k5.size)),
        "intensity_weighted_top_recall": (covered_i_sum / total_i if total_i > 0 else 0.0),
        "main_peak_match": main_peak_match,
        "match_ratio": n_matched_ref / n_ref_used if n_ref_used else 0.0,
        "meas_ratio": recall,
        "score": (n_top_observed / float(max(1, k5.size))) * 100.0
                 + top_recall * 10.0 + recall,
    }
