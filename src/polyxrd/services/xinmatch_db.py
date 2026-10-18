"""XinMatch 格式数据库只读适配 (v3.1.0)
=====================================

本模块让 PolyXRD 能**直接挂载 XinMatch 的数据库文件**（无需转换、无需拷贝到
固定目录、无需重启）。库文件放哪都行，只要在「外挂数据库管理」里指过去。

为什么需要单独一层适配
----------------------
XinMatch 的库与 PolyXRD 自有的三套库**表结构完全不同**：

    XinMatch                    PolyXRD (COD 无机物 / PDF2)
    --------------------------  ------------------------------------
    entries(entry_id TEXT PK)   phases(cod_id INTEGER PK)
    peaks(entry_id, d, i, hkl)  phases.peaks_d / peaks_i (逗号串)
    elements(entry_id, element) 无 (靠 formula 现解析)
    element_combo(哈希, 条目串)  无

两处硬差别决定了不能直接复用 ``search_cod_by_d_peaks``：
  · ``entry_id`` 是 **TEXT**（``96-100-0005``），PolyXRD 一律 INTEGER ``cod_id``
  · 峰存成**规范化表**（620 万行）而不是每相一行的逗号串

检索策略：一次性建「紧凑强峰索引」+ 向量化预筛
-----------------------------------------------
直接在 ``peaks.d`` 上做 SQL 区间扫描是**不可行**的：该库 d 轴极密
（每 0.04 Å 窗口约 2.5 万条峰，相当于 37% 的物相都有一条峰落进任意窗口），
20 个测量峰逐窗口 ``GROUP BY`` 实测要 **9 s**，比现有 COD 无机库整条检索链
（5.5 s）还慢。

所以这里换成分两级：

1. **建索引（每库一次，写入磁盘缓存）**
   把每相强度最高的前 ``_S1_TOP_COLS``(=12) 条峰摊成一个 ``(N, 12)`` 的
   float32 矩阵 —— 71206 相只占 3.4 MB。建一次实测 ~3.2 s，存成 ``.npz``
   后再次启动只需 ~0.15 s 载入。
2. **检索（每次 ~0.3 s）**
   预筛阶段在矩阵上做纯 numpy 区间命中（25 个测量峰 × 71k 相 ≈ 0.1 s），
   按「主峰是否命中 → 强度加权命中数 → 命中数」取前 ``rank_limit`` 个候选；
   再对这些候选逐条取全峰、按与 COD 无机库**完全同一口径**的 Hanawalt
   度量打分排序。

这样既保住了召回（预筛不做截断性近似，只按命中质量排序取前 N），又把
耗时压到现有链路的 1/10。打分原子（``_match_positions`` / ``_dedupe_by_tol``
/ ``_interval_hit``）直接从 :mod:`polyxrd.services.cif_database` 复用，避免
两套实现日后漂移；两者的一致性由 ``tests/test_xinmatch_db.py`` 的
「同数据双实现比对」用例守住。

局限（如实记在文档与 UI 里）
----------------------------
XinMatch 库**不含 CIF**，因此条目只有晶胞没有原子坐标：可直接进检索、可
用晶胞做简单指标化核对，但**不能直接进 Rietveld 精修**（精修仍需 CIF 或
用户自建库里的原子位点）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

# 打分原子直接复用 COD 无机库实现 —— 同一口径, 不允许第二套
from polyxrd.services.cif_database import (
    _dedupe_by_tol,
    _interval_hit,
    _match_positions,
)

#: 预筛索引里每相保留的强峰数。12 与 COD 侧 ``n_top`` 的上限一致
#: (``n_top = min(n_i, max(n_meas+2, 8), 12)``), 足以覆盖预筛所需判别力。
_S1_TOP_COLS = 12
#: 索引缓存格式版本: 改动索引布局/语义时 +1, 旧缓存自动失效重建。
_CACHE_VERSION = 1
#: 预筛候选池上限 (进精确打分的相数)。实测 800 已覆盖真实物相, 再大只是变慢。
_RANK_LIMIT = 800
#: 缓存目录 (``~/.polyxrd/cache``), 与 user_db_paths.json 同根, 便于一键清理。
_CACHE_DIR = ".polyxrd/cache"

#: XinMatch 两个库的判别签名: 四张表都在才算 XinMatch 库。
_REQUIRED_TABLES = ("entries", "peaks", "elements")


@dataclass
class XinMatchStats:
    """库概况 (供 UI 显示)。"""

    path: str = ""
    entries: int = 0
    peaks: int = 0
    elements: int = 0
    combos: int = 0
    size_mb: float = 0.0
    #: 是否已完成强峰索引 (UI 可提示"首次检索会建索引")
    indexed: bool = False


def _cache_file_for(path: Path) -> Path:
    """某个 XinMatch 库对应的索引缓存文件。

    用**绝对路径的哈希**而不是文件名做键: 用户完全可能同时挂着
    ``D:/XRD/cod_inorganics.db`` 与 ``E:/backup/cod_inorganics.db``
    两个同名文件, 只按文件名缓存会互相顶掉。
    """
    key = hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:16]
    return Path.home() / _CACHE_DIR / f"xinmatch_{key}.npz"


def probe(db_path: str | Path) -> tuple[bool, str]:
    """轻量判别: 该文件是不是一个可用的 XinMatch 库。

    Returns:
        ``(ok, reason)``。``ok`` 为 False 时 ``reason`` 是机器可读的短标记
        （``file_not_found`` / ``not_sqlite`` / ``missing_tables:entries`` 等),
        由调用方翻译成人话。
    """
    p = Path(db_path)
    if not p.exists():
        return False, "file_not_found"
    if not p.is_file():
        return False, "not_a_file"
    try:
        with open(p, "rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                return False, "not_sqlite"
    except OSError as e:
        return False, f"unreadable: {e}"
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return False, f"open_failed: {e}"
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in _REQUIRED_TABLES if t not in tables]
        if missing:
            return False, "missing_tables:" + ",".join(missing)
    except sqlite3.Error as e:
        return False, f"query_failed: {e}"
    finally:
        conn.close()
    return True, ""


class XinMatchDatabase:
    """XinMatch 数据库只读访问器。

    生命周期: 构造 → :meth:`is_ready` → :meth:`search_by_d_peaks` /
    :meth:`get_phase`。连接与索引都懒加载, 构造本身不碰磁盘。

    Args:
        db_path: 库文件路径。``None`` 时取配置里的挂载路径
            (``~/.polyxrd/user_db_paths.json::xinmatch_db_path``)。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from polyxrd.config import get_config

            db_path = get_config().get_xinmatch_db_path()
        self.path: Optional[Path] = Path(db_path) if db_path else None
        self._conn: Optional[sqlite3.Connection] = None
        self._ready: Optional[bool] = None
        self._idx: Optional[dict] = None
        self._stats: Optional[XinMatchStats] = None
        self._lock = threading.Lock()
        # 元素集合 → 候选掩码 (同一组 allowed 元素在一轮检索里会被复用)
        self._element_mask_cache: dict[frozenset, np.ndarray] = {}

    # ── 基础状态 ──────────────────────────────────────────
    @property
    def available(self) -> bool:
        return self.path is not None and self.path.exists()

    def is_ready(self) -> bool:
        """库可用 (文件在 + 四表齐)。结果缓存, 失败也缓存以免反复探测。"""
        if self._ready is None:
            if not self.available:
                self._ready = False
            else:
                ok, _ = probe(self.path)
                self._ready = ok
        return bool(self._ready)

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        """只读连接 (``mode=ro``): 绝不写用户的库文件。"""
        if self._conn is not None:
            return self._conn
        if not self.is_ready():
            return None
        try:
            self._conn = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True, check_same_thread=False
            )
        except sqlite3.Error:
            return None
        return self._conn

    def reload(self) -> None:
        """丢弃连接与索引 (换库/重新挂载后调用)。"""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
            self._conn = None
            self._idx = None
            self._stats = None
            self._ready = None
            self._element_mask_cache.clear()

    def stats(self) -> XinMatchStats:
        """条目数/峰数/元素数/组合数 + 是否已建索引。"""
        if self._stats is not None:
            return self._stats
        st = XinMatchStats(path=str(self.path or ""))
        if not self.available:
            self._stats = st
            return st
        try:
            st.size_mb = round(self.path.stat().st_size / 1e6, 1)
        except OSError:
            pass
        conn = self._get_conn()
        if conn is None:
            self._stats = st
            return st

        def _count(table: str) -> int:
            try:
                return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error:
                return 0

        st.entries = _count("entries")
        st.peaks = _count("peaks")
        st.elements = _count("elements")
        st.combos = _count("element_combo")
        st.indexed = _cache_file_for(self.path).exists()
        self._stats = st
        return st

    # ── 强峰索引 (懒建 + 磁盘缓存) ─────────────────────────
    def _index(self) -> Optional[dict]:
        """取/建紧凑强峰索引。

        索引内容 (全部 numpy 数组, 无 pickle):
          · ``ids``      条目编号 (list[str])
          · ``dtop``     (N, 12) float32 —— 每相最强 12 条峰的 d 值, 右补 0
          · ``itop``     (N, 12) float32 —— 对应强度, 右补 0
          · ``counts``   (N,) int32 —— 该相峰总数
          · ``formula`` / ``space_group`` / ``elements`` / ``mineral`` (list[str])
          · ``cell``     (N, 6) float32 —— a,b,c,α,β,γ
          · ``meta``     dict —— 源文件 size/mtime 等校验信息
        """
        if self._idx is not None:
            return self._idx
        with self._lock:
            if self._idx is not None:
                return self._idx
            if not self.is_ready():
                return None
            cache = _cache_file_for(self.path)
            try:
                src = self.path.stat()
                sig = {"v": _CACHE_VERSION, "size": src.st_size,
                       "mtime": int(src.st_mtime), "cols": _S1_TOP_COLS}
            except OSError:
                return None
            cached = self._load_index_cache(cache, sig)
            if cached is not None:
                self._idx = cached
                return self._idx
            built = self._build_index(sig)
            if built is None:
                return None
            self._idx = built
            self._save_index_cache(cache, built)
            return self._idx

    def _load_index_cache(self, cache: Path, sig: dict) -> Optional[dict]:
        """读缓存; 版本/源文件指纹不符则当作未命中。"""
        if not cache.exists():
            return None
        try:
            with np.load(cache, allow_pickle=False) as z:
                meta = json.loads(str(z["meta"]))
                if {k: meta.get(k) for k in sig} != sig:
                    return None
                return {
                    "meta": meta,
                    "ids": str(z["ids"]).split("\n"),
                    "formula": str(z["formula"]).split("\n"),
                    "space_group": str(z["space_group"]).split("\n"),
                    "elements": str(z["elements"]).split("\n"),
                    "mineral": str(z["mineral"]).split("\n"),
                    "dtop": z["dtop"],
                    "itop": z["itop"],
                    "counts": z["counts"],
                    "cell": z["cell"],
                }
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            # 缓存损坏 = 当作未命中, 重新构建 (绝不因缓存坏了让整个功能不可用)
            return None

    def _save_index_cache(self, cache: Path, idx: dict) -> None:
        """写缓存。失败只警告不抛 —— 没有缓存也能用, 只是下次要重建。"""
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再原子替换: 大库建一次要 3 s, 中途崩溃留下半个
            # 文件的话下次会读到一个损坏的缓存。临时文件必须**以 .npz 结尾**
            # —— np.savez 对非 .npz 后缀会自作主张再补一个。
            tmp = cache.with_name(cache.stem + ".part.npz")
            np.savez(
                tmp,
                meta=np.array(json.dumps(idx["meta"])),
                ids=np.array("\n".join(idx["ids"])),
                formula=np.array("\n".join(idx["formula"])),
                space_group=np.array("\n".join(idx["space_group"])),
                elements=np.array("\n".join(idx["elements"])),
                mineral=np.array("\n".join(idx["mineral"])),
                dtop=idx["dtop"],
                itop=idx["itop"],
                counts=idx["counts"],
                cell=idx["cell"],
            )
            tmp.replace(cache)
        except (OSError, ValueError):
            pass

    def _build_index(self, sig: dict) -> Optional[dict]:
        """扫库建强峰索引 (实测 ~3.2 s / 71k 相 / 620 万峰)。"""
        conn = self._get_conn()
        if conn is None:
            return None
        try:
            # 1) 每相峰数: 走 (entry_id, intensity) 索引, 实测 0.45 s
            rows = conn.execute(
                "SELECT entry_id, COUNT(*) FROM peaks GROUP BY entry_id "
                "ORDER BY entry_id"
            ).fetchall()
            if not rows:
                return None
            ids = [r[0] for r in rows]
            counts = np.fromiter((r[1] for r in rows), dtype=np.int32,
                                 count=len(rows))
            n = len(ids)

            # 2) 每相最强 N 峰: **逐相 LIMIT** 比全表流式取前 N 更快
            #    (实测 3.19 s vs 5.04 s —— 后者要把 620 万行搬进 Python)
            dtop = np.zeros((n, _S1_TOP_COLS), dtype=np.float32)
            itop = np.zeros((n, _S1_TOP_COLS), dtype=np.float32)
            for r, eid in enumerate(ids):
                pk = conn.execute(
                    "SELECT d, intensity FROM peaks WHERE entry_id=? "
                    "ORDER BY intensity DESC LIMIT ?",
                    (eid, _S1_TOP_COLS),
                ).fetchall()
                if not pk:
                    continue
                arr = np.asarray(pk, dtype=np.float32)
                m = min(len(arr), _S1_TOP_COLS)
                dtop[r, :m] = arr[:m, 0]
                # 强度缺失 (NULL) 一律按 0 处理, 保证 argsort 稳定
                itop[r, :m] = np.nan_to_num(arr[:m, 1], nan=0.0)

            # 3) 条目元数据
            formula = [""] * n
            sg = [""] * n
            elements = [""] * n
            mineral = [""] * n
            cell = np.zeros((n, 6), dtype=np.float32)
            cur = conn.execute(
                "SELECT entry_id, formula, space_group, elements, "
                "mineral_name, a, b, c, alpha, beta, gamma FROM entries"
            )
            pos = {e: i for i, e in enumerate(ids)}
            for row in cur:
                r = pos.get(row[0])
                if r is None:      # peaks 有而 entries 没有的脏数据 → 跳过
                    continue
                formula[r] = row[1] or ""
                sg[r] = row[2] or ""
                elements[r] = row[3] or ""
                mineral[r] = row[4] or ""
                for k in range(6):
                    v = row[5 + k]
                    cell[r, k] = float(v) if v is not None else 0.0

            return {
                "meta": dict(sig, entries=n),
                "ids": ids,
                "formula": formula,
                "space_group": sg,
                "elements": elements,
                "mineral": mineral,
                "dtop": dtop,
                "itop": itop,
                "counts": counts,
                "cell": cell,
            }
        except (sqlite3.Error, ValueError):
            return None

    # ── 元素过滤 ──────────────────────────────────────────
    def _element_mask(self, allowed: set[str]) -> np.ndarray:
        """``allowed`` 元素集合 → 长度 N 的布尔掩码 (库内条目是否可能匹配)。

        语义与 COD 侧**扫描层**一致: 只要求库条目元素 ⊆ 允许池; 空的
        elements 串视为"元素未知"→ 放行, 由下游 ``elements_match_filter``
        用化学式复核 (若在这里淘汰, 真物相会被误杀)。
        """
        key = frozenset(allowed)
        cached = self._element_mask_cache.get(key)
        if cached is not None:
            return cached
        idx = self._index()
        if idx is None:
            return np.zeros(0, dtype=bool)
        pool = {str(e).strip().title() for e in allowed}
        mask = np.ones(len(idx["ids"]), dtype=bool)
        for i, raw in enumerate(idx["elements"]):
            if not raw:
                continue
            els = {t.strip().title() for t in raw.replace(";", ",").split(",")
                   if t.strip()}
            if els and not els.issubset(pool):
                mask[i] = False
        self._element_mask_cache[key] = mask
        return mask

    # ── 单条详情 / 全峰表 ─────────────────────────────────
    def entry_peaks(self, entry_id: str) -> tuple[list[float], list[float]]:
        """某条目的**全部**峰 (按强度降序)。缺失返回两个空列表。"""
        conn = self._get_conn()
        if conn is None:
            return [], []
        try:
            rows = conn.execute(
                "SELECT d, intensity FROM peaks WHERE entry_id=? "
                "ORDER BY intensity DESC", (entry_id,)
            ).fetchall()
        except sqlite3.Error:
            return [], []
        ds = [float(r[0]) for r in rows if r[0] is not None and r[0] > 0]
        is_ = [float(r[1]) if r[1] is not None else 0.0 for r in rows
               if r[0] is not None and r[0] > 0]
        return ds, is_

    def get_phase(self, entry_id: str) -> Optional[dict]:
        """取一条目详情, 供 :meth:`PhaseIdentifier._rank_candidates` 消费。

        返回的键与 ``cif_database.get_cod_phase`` **同构**
        (``peaks_d_list`` / ``peaks_i_list`` / ``cell_*`` / ``formula`` /
        ``space_group``), 外加 XinMatch 特有的 ``mineral_name`` 与
        ``elements_list``。
        """
        idx = self._index()
        if idx is None:
            return None
        try:
            r = idx["ids"].index(entry_id)
        except ValueError:
            r = -1
        if r < 0:
            return None
        ds, is_ = self.entry_peaks(entry_id)
        if not ds:
            return None
        cell = idx["cell"][r]
        raw_el = idx["elements"][r] or ""
        return {
            "entry_id": entry_id,
            "formula": idx["formula"][r],
            "space_group": idx["space_group"][r],
            "mineral_name": idx["mineral"][r],
            "cell_a": float(cell[0]), "cell_b": float(cell[1]),
            "cell_c": float(cell[2]), "cell_alpha": float(cell[3]) or 90.0,
            "cell_beta": float(cell[4]) or 90.0,
            "cell_gamma": float(cell[5]) or 90.0,
            "elements_list": [t.strip() for t in
                              raw_el.replace(";", ",").split(",") if t.strip()],
            "peaks_d_list": ds,
            "peaks_i_list": is_,
        }

    # ── Hanawalt 打分 (与 COD 无机库同一口径) ──────────────
    @staticmethod
    def _score_entry(
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
        """单相 Hanawalt 度量。

        逐行对齐 :meth:`cif_database.CIFDatabase.search_cod_by_d_peaks` 的
        计算口径 (含 ``n_top`` 的封顶方式、``_dedupe_by_tol`` 的贪心顺序、
        ``main_peak_match`` 的 top-K 主峰放宽), 差异只在数据来源。

        Returns:
            度量 dict; 反向命中测量峰数不足 ``min_match`` 的情形由调用方
            用 ``n_matched_meas`` 判断 (这里不提前剪枝, 便于单测逐字段比对)。
        """
        n_meas = int(md.size)
        n_i = int(i_np.size)
        n_d = int(d_np.size)
        if n_i == 0 or n_d == 0 or n_meas == 0:
            return None
        order = np.argsort(-i_np, kind="stable")
        # ── 参考峰: 强度最高的前 max_ref_peaks 条 ──
        sel = order[:max_ref_peaks]
        if n_i > n_d:
            sel = sel[sel < n_d]
        ref_d = d_np[sel]
        n_ref_used = int(ref_d.size)
        if n_ref_used == 0:
            return None
        t_ref = (np.maximum(tol_abs, trel * ref_d) if use_rel
                 else np.full(n_ref_used, tol_abs))
        hit_ref, pos_ref = _match_positions(md, ref_d - t_ref, ref_d + t_ref)
        n_matched_ref = int(hit_ref.sum())
        n_matched_meas = int(np.unique(pos_ref[hit_ref]).size)

        # ── 去重后的强峰: 判"物相最强线是否被观察到" ──
        n_top = min(n_i, max(n_meas + 2, 8), 12)
        top_sel = order[:n_top]
        if n_i > n_d:
            top_sel = top_sel[top_sel < n_d]
        top_d = d_np[top_sel[np.argsort(-i_np[top_sel], kind="stable")]]
        unique_top_d = _dedupe_by_tol(top_d, tol_abs, trel, use_rel)
        if not unique_top_d:
            return None
        ud = np.asarray(unique_top_d, dtype=np.float64)
        t_md = (np.maximum(tol_abs, trel * md) if use_rel
                else np.full(n_meas, tol_abs))
        hit_m = _interval_hit(np.sort(ud), md - t_md, md + t_md)
        n_meas_in_top = int(hit_m.sum())
        covered_i_sum = float(mi[hit_m].sum()) if mi is not None else 0.0

        # 主峰原则: 物相最强去重峰是否落在样品前 K 个最强峰窗口内
        main_peak_match = 0.0
        if mi is not None:
            phase_main_d = float(ud[0])
            for mdk in main_meas_d_topk:
                t_main = (max(tol_abs, trel * phase_main_d) if use_rel
                          else tol_abs)
                if abs(phase_main_d - mdk) <= t_main:
                    main_peak_match = 1.0
                    break
        # top_precision: 最强前 5 个去重峰中有多少被观察到
        k5 = ud[:5]
        t5 = (np.maximum(tol_abs, trel * k5) if use_rel
              else np.full(k5.size, tol_abs))
        n_top_observed = int(_interval_hit(md, k5 - t5, k5 + t5).sum())

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
            "top_precision": n_top_observed / float(k5.size),
            "intensity_weighted_top_recall": (
                covered_i_sum / total_i if total_i > 0 else 0.0),
            "main_peak_match": main_peak_match,
            "match_ratio": n_matched_ref / n_ref_used if n_ref_used else 0.0,
            "meas_ratio": recall,
            "score": (n_top_observed / float(k5.size)) * 100.0
                     + top_recall * 10.0 + recall,
        }

    # ── 检索主入口 ────────────────────────────────────────
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
        """用测得的 d-I 峰表在 XinMatch 库里预筛候选物相。

        语义与 :meth:`cif_database.CIFDatabase.search_cod_by_d_peaks` 对齐
        (同样的容差规则、同样的排序主键、同样的返回字段), 便于上层
        ``_rank_candidates`` 原样复用。

        Args:
            measured_d: 测量峰 d 值 (Å)
            measured_i: 测量峰强度, 与 ``measured_d`` 等长平行。传入后启用
                强度加权召回与主峰匹配判据。
            tolerance: d 匹配容差绝对下限 (Å)
            tolerance_rel: 相对容差分量 (>0 时取 ``max(abs, rel*d)``,
                使 2θ 窗口近似恒定)
            min_match: 最少反向匹配测量峰数
            limit: 返回条数上限
            max_ref_peaks: 每相参与打分的最大强峰数
            main_peak_topk: 主峰判据放宽到样品前 K 个最强峰
            elements_allowed: 允许元素池 (空集/None = 不过滤)
            rank_limit: 进精确打分的候选池大小

        Returns:
            候选 dict 列表, 含 ``cod_id``(=``entry_id``)、``formula``、
            ``space_group``、``n_peaks`` 及各项 Hanawalt 度量。
        """
        idx = self._index()
        if idx is None or not measured_d:
            return []
        md = np.asarray(sorted(float(d) for d in measured_d), dtype=np.float64)
        n_meas = int(md.size)
        if n_meas == 0:
            return []

        # 测量强度按 d 升序重排, 与 md 对齐 (与 COD 侧一致)
        if measured_i is not None and len(measured_i) == len(measured_d):
            pairs = sorted(zip((float(x) for x in measured_d),
                               (float(v) for v in measured_i)),
                           key=lambda p: p[0])
            mi = np.asarray([p[1] for p in pairs], dtype=np.float64)
        else:
            mi = None

        if mi is not None:
            k_top = max(1, int(main_peak_topk or 1))
            ti = np.argsort(-mi)[:k_top]
            main_meas_d_topk = [float(md[i]) for i in ti]
        else:
            main_meas_d_topk = []

        trel = float(tolerance_rel or 0.0)
        use_rel = trel > 0.0
        tol_abs = float(tolerance)
        t_meas = (np.maximum(tol_abs, trel * md) if use_rel
                  else np.full(n_meas, tol_abs))
        w_norm = (mi / mi.sum()) if (mi is not None and mi.sum() > 0) else None

        # ── 阶段 1: 在 (N,12) 强峰矩阵上做向量化区间命中 ──
        dtop = idx["dtop"]
        n = dtop.shape[0]
        hits = np.zeros(n, dtype=np.int32)
        whits = np.zeros(n, dtype=np.float64)
        main_hit = np.zeros(n, dtype=bool)
        main_d = dtop[:, 0]
        for k in range(n_meas):
            lo = float(md[k] - t_meas[k])
            hi = float(md[k] + t_meas[k])
            any_k = ((dtop >= lo) & (dtop <= hi)).any(axis=1)
            hits += any_k
            if w_norm is not None:
                whits += any_k * float(w_norm[k])
            main_hit |= (main_d >= lo) & (main_d <= hi)

        # 元素约束 (扫描层) + 最少命中数
        need = max(1, min(int(min_match), _S1_TOP_COLS))
        cand = hits >= need
        if elements_allowed:
            em = self._element_mask(set(elements_allowed))
            if em.size == n:
                cand &= em
        sel = np.flatnonzero(cand)
        if sel.size == 0:
            return []
        # 排序: 主峰命中 → 强度加权命中 → 命中数 (与 COD 侧排序主键同序)
        # lexsort 以**最后一个键为主键**且按升序, 故用 ``~main_hit`` (True→0)
        # 与取负的数值键模拟降序。
        order = sel[np.lexsort((-hits[sel], -whits[sel], ~main_hit[sel]))]
        order = order[:max(1, int(rank_limit))]

        # ── 阶段 2: 取全峰 + 精确 Hanawalt 打分 ──
        out: list[dict] = []
        for r in order:
            eid = idx["ids"][int(r)]
            ds, is_ = self.entry_peaks(eid)
            if not ds:
                continue
            m = self._score_entry(
                np.asarray(ds, dtype=np.float64),
                np.asarray(is_, dtype=np.float64),
                md=md, mi=mi, main_meas_d_topk=main_meas_d_topk,
                tol_abs=tol_abs, trel=trel, use_rel=use_rel,
                max_ref_peaks=max_ref_peaks,
            )
            if m is None or m["n_matched_meas"] < min_match:
                continue
            rec = {
                "cod_id": eid,
                "ref_id": eid,
                "display_id": eid,
                "formula": idx["formula"][int(r)],
                "space_group": idx["space_group"][int(r)],
                "mineral_name": idx["mineral"][int(r)],
                "n_peaks": int(idx["counts"][int(r)]),
                "n_matched_s1": int(hits[int(r)]),
            }
            rec.update(m)
            out.append(rec)

        # 排序主键与 COD 侧逐项一致 (main_peak_match 最前 = Hanawalt 主峰原则)
        out.sort(
            key=lambda r: (
                r["main_peak_match"],
                r["top_precision"],
                r["intensity_weighted_top_recall"],
                r["top_recall"],
                r["meas_ratio"],
                r["score"],
            ),
            reverse=True,
        )
        return out[:limit]


def clear_index_cache(db_path: str | Path | None = None) -> int:
    """删除索引缓存, 返回删除的文件数。

    Args:
        db_path: 只删该库的缓存; ``None`` 删掉整个 XinMatch 索引缓存。
    """
    if db_path:
        targets = [_cache_file_for(Path(db_path))]
    else:
        targets = list((Path.home() / _CACHE_DIR).glob("xinmatch_*.npz"))
    n = 0
    for p in targets:
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n
