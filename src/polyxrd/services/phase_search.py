"""d 值峰匹配打分（纯函数，无 IO）
=================================
本模块是 v4.2 结构清理中从 ``cif_database.py`` 抽出的**检索打分核心**：
给定一个带 ``phases`` 表的 sqlite 连接和一组测量 d 值，逐相打分并排序。

设计约束
--------
* **不打开任何数据库**：连接由调用方传入。``phases`` 表的列契约固定为
  ``cod_id, ref_id, display_id, formula, space_group, n_peaks, peaks_d,
  peaks_i``（可选预截断列 ``peaks_top_d/peaks_top_i``）—— COD 无机库、
  PDF2 库、用户库三者同构，``cod_id`` 是上游遗留的**主键列名**，随表结构
  沿用，不代表本模块依赖 COD。
* 不 import sqlite3 / PySide6 / 不读配置路径；唯一外部依赖是
  ``polyxrd.utils.formula_parser``（纯正则）。
* 打分口径与旧本地库类（v4.2 删除）的同名检索方法**逐字段一致**，
  由 ``tests/data/phase_search_golden.json`` + ``tests/test_phase_search.py``
  守住（golden 在搬移前用旧实现冻结）。

排序主键（均降序）
------------------
``main_peak_match → top_precision → intensity_weighted_top_recall →
top_recall → meas_ratio → score``

把 ``main_peak_match`` 放最前是 Hanawalt 主峰原则：物相主峰应对上样品最强
峰。当 ``measured_i`` 未提供时该项恒 0，排序退化为
``(top_precision, top_recall, meas_ratio, score)``。
"""
from __future__ import annotations

import numpy as np

from polyxrd.utils.formula_parser import elements_from_db_formula

__all__ = [
    "PEAK_TOP_N",
    "TOP_PEAK_COLUMNS",
    "dedupe_by_tol",
    "has_top_peak_columns",
    "interval_hit",
    "match_positions",
    "parse_float_csv",
    "search_phases_by_d_peaks",
    "tol_scalar",
    "top_peaks_of",
]


# ──────────────────────────────────────────────────────────────
# 向量化辅助（0.9.12 检索加速）
# ──────────────────────────────────────────────────────────────
#
# 扫描层原本是逐相 Python 循环。对 COD 无机库全表（71,199 相，平均每相 266
# 个参考峰，合计 1,900 万个峰值）× 50 个测量峰实测，四个热点为：
#   · 峰串解析 [float(x) for x in s.split(",")]        ~10.3s
#   · 逐相 sorted(range(n), key=lambda k: i[k])         ~8s
#   · 容差标量函数调用 1,367 万次                        ~5.9s
#   · 去重 any(...) 生成器 + 逐峰 bisect_left 循环        ~5.6s
# 下面这几个 helper 把前三项换成 NumPy 批量操作；第四项每相最多 12 项，
# 仍是顺序贪心，但去掉了逐项容差函数调用。
#
# **语义必须与旧实现逐条一致** —— 包括并列时的先后、去重顺序、
# n_matched_meas 的"最左命中下标去重"口径、以及 max() 对 NaN 的处理。


def parse_float_csv(s) -> np.ndarray:
    """把 ``"3.13,1.92,1.63"`` 形式的峰串解析成 float64 数组。

    等价于旧实现 ``[float(x) for x in s.split(",") if x.strip()]``：
    空字段/纯空白字段被丢弃，字段两侧空白被忽略。

    若传入 bytes/bytearray/memoryview（数据库以 BLOB 存 float64 时的形态），
    直接 ``np.frombuffer`` 零拷贝解释，不做文本解析。

    注意不要用 ``np.fromstring(s, sep=",")`` —— 它对本函数的输入**不**
    等价：``"4.9,  ,2.4"`` 会被解析成 ``[4.9, -1.0, 2.4]``（凭空注入一个
    -1 Å 假峰），``"4.9,,2.4"`` 则会被静默截断成 ``[4.9]``。对衍射数据
    而言这两种失败模式都不可接受。
    """
    if isinstance(s, (bytes, bytearray, memoryview)):
        return np.frombuffer(s, dtype=np.float64)
    try:
        return np.array(s.split(","), dtype=np.float64)
    except ValueError:
        # 含空字段等畸形输入 → 回退到与旧实现完全一致的逐项过滤解析
        return np.fromiter(
            (float(x) for x in s.split(",") if x.strip()), dtype=np.float64
        )


def tol_scalar(d, tol_abs: float, trel: float, use_rel: bool) -> float:
    """单个 d 值的有效容差。

    对应旧实现 ``tolerance if trel <= 0.0 else max(tolerance, trel * d)``。
    用 ``v > tol_abs`` 而不是内置 ``max()`` 之外的写法，是为了连 NaN 的
    行为都一致（``max(tol, nan)`` 返回 ``tol``，因为 ``nan > tol`` 为假）。
    """
    if not use_rel:
        return tol_abs
    v = trel * d
    return v if v > tol_abs else tol_abs


def interval_hit(sorted_data, lo, hi) -> np.ndarray:
    """对每个查询区间 ``[lo[i], hi[i]]``，判断升序数组是否有元素落入其中。

    返回长度 ``len(lo)`` 的布尔掩码。等价于旧实现的

        idx = bisect.bisect_left(data, lo)
        if idx < len(data) and data[idx] <= hi: ...

    Args:
        sorted_data: 升序排列的数据数组（已排序，本函数不再排序）
        lo, hi: 查询区间下/上界，与查询一一对应
    """
    data = np.asarray(sorted_data, dtype=np.float64)
    lo_a = np.asarray(lo, dtype=np.float64)
    hi_a = np.asarray(hi, dtype=np.float64)
    if data.size == 0:
        return np.zeros(lo_a.shape, dtype=bool)
    pos = np.searchsorted(data, lo_a, side="left")
    in_range = pos < data.size
    # 越界下标钳到末位，只为让下面的 gather 合法；in_range 已排除这些项
    return in_range & (data[np.minimum(pos, data.size - 1)] <= hi_a)


def match_positions(sorted_data, lo, hi):
    """同 :func:`interval_hit`，但额外返回每个区间的命中下标。

    返回 ``(hit, pos)``：``hit`` 是布尔掩码，``pos`` 是全长度下标数组 ——
    只有 ``hit`` 为真的位置有意义，其余位置的下标不可用（被钳过）。

    旧实现把 ``bisect.bisect_left(data, lo)``（即区间内**最左**命中点的
    下标）收进集合再去重计数，所以调用方只需 ``pos[hit]`` 即可复刻
    ``len(matched_meas_idx)`` 口径 —— 多个参考峰指向同一个最左命中点时
    只算一个。
    """
    data = np.asarray(sorted_data, dtype=np.float64)
    lo_a = np.asarray(lo, dtype=np.float64)
    hi_a = np.asarray(hi, dtype=np.float64)
    n = data.size
    if n == 0:
        return (np.zeros(lo_a.shape, dtype=bool),
                np.zeros(lo_a.shape, dtype=np.intp))
    pos = np.searchsorted(data, lo_a, side="left")
    hit = (pos < n) & (data[np.minimum(pos, n - 1)] <= hi_a)
    return hit, pos


def dedupe_by_tol(ds, tol_abs: float, trel: float, use_rel: bool) -> list[float]:
    """按给定顺序贪心去重近重复 d 值，返回纯 Python list。

    严格复刻旧实现：

        for d, _i in top_pairs:            # 已按 I 降序
            if not any(abs(d - ud) <= _tol(d) for ud in unique_top_d):
                unique_top_d.append(d)

    两个易错点必须保住：
      · 容差取**候选 d 自身**的 ``tol_scalar(d)``，不是已保留项的 —— 判据不对称
      · 比较是 ``<=``，且顺序敏感（先到者留下）

    返回 list 而非 ndarray：调用方要用 ``if unique_top_d:`` 判空，
    ndarray 的长度 >1 时真值判断会抛 ValueError。
    """
    tols = (
        [tol_abs if not (trel * d > tol_abs) else trel * d for d in ds]
        if use_rel else None
    )
    unique: list[float] = []
    for i, d in enumerate(ds):
        t = tol_abs if tols is None else tols[i]
        for u in unique:
            du = d - u
            if -t <= du <= t:
                break
        else:
            unique.append(d)
    return unique


# ──────────────────────────────────────────────────────────────
# 预截断强峰列（0.9.12 检索加速 第二级）
# ──────────────────────────────────────────────────────────────
#
# 向量化之后实测真正的瓶颈是**每相都要解析全部参考峰**，而打分只用得上
# I 最高的 max_ref_peaks（默认 40）个：
#
#   · COD 无机库: 266.5 峰/相 × 71,199 相 = 1,900 万个峰，其中 85% 白解析
#   · PDF2 库:     63.8 峰/相 × 163,834 相 — 本来就 ~64 峰，**没有收益**
#
# 所以建库期把每相 I 最高的前 PEAK_TOP_N 个峰按 I 降序另存一份，检索时
# 直接读它（零拷贝），连每相的 argsort 都省掉。
#
# **为什么结果仍然完全一致**：打分逻辑只消费
#   · ref_d = d[order[:max_ref_peaks]]  —— I 最高的前 40 个
#   · top_d = d[order[:n_top]]，n_top ≤ 12  —— 同上集合的子集
# 只要 max_ref_peaks ≤ PEAK_TOP_N 且 PEAK_TOP_N ≥ 12，预截断数组的前缀就
# **逐元素等于**全长数组的前缀（含并列时的先后，因为建库用的是同一个
# ``np.argsort(-i, kind="stable")[:N]``）。超出这个范围时自动回退全长解析，
# 不给"静默变结果"留口子。

PEAK_TOP_N = 64
TOP_PEAK_COLUMNS = ("peaks_top_d", "peaks_top_i")


def has_top_peak_columns(conn) -> bool:
    """该连接对应的 ``phases`` 表是否已有预截断强峰列。"""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(phases)")}
    except Exception:
        return False
    return set(TOP_PEAK_COLUMNS).issubset(cols)


def top_peaks_of(d: np.ndarray, i: np.ndarray,
                 top_n: int = PEAK_TOP_N) -> tuple[np.ndarray, np.ndarray]:
    """取 I 最高的前 ``top_n`` 个峰，按 I 降序返回 (d, i) —— 建库用。

    与 :func:`search_phases_by_d_peaks` 内的取法**逐元素等价**：
    ``order = argsort(-i, kind="stable")[:top_n]``，再按
    ``k < len(ref_d_all)`` 过滤（旧实现就有这道过滤，必须保留）。
    """
    if d.size == 0 or i.size == 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    order = np.argsort(-np.asarray(i, dtype=np.float64), kind="stable")[:top_n]
    if i.size > d.size:
        order = order[order < d.size]
    return (np.asarray(d, dtype=np.float64)[order],
            np.asarray(i, dtype=np.float64)[order])


# ──────────────────────────────────────────────────────────────
# 检索主入口
# ──────────────────────────────────────────────────────────────

_SQL_FULL = (
    "SELECT cod_id, ref_id, display_id, formula, space_group, "
    "n_peaks, peaks_d, peaks_i FROM phases"
)
_SQL_TOP = (
    "SELECT cod_id, ref_id, display_id, formula, space_group, "
    "n_peaks, peaks_top_d, peaks_top_i FROM phases"
)


def search_phases_by_d_peaks(
    conn,
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
) -> list[dict]:
    """用测得的 d 值列表在 ``phases`` 表中搜索匹配物相。

    为避免高密度物相（含数百个弱峰）产生误匹配，只取每个物相中 I 值最高的
    前 ``max_ref_peaks`` 个主要峰参与匹配。统计双向匹配：

      - recall(meas_ratio)：测量峰中被主要参考峰（前 ``max_ref_peaks``）
        覆盖的比例
      - top_recall：取物相最强的少数峰（去重后，前 n_top 个独立峰），
        统计测量峰中有多少落在这些"物相最强峰"内。低对称物相会产出大量
        近重复 d 值（同一 d 的多个 hkl），去重后只看独立强峰，可避免此类
        物相因重复峰虚高得分。
      - top_precision：物相最强的前 K(=5) 个去重峰中有多少"被观察到"
        （Hanawalt 思想：最强线必须出现在样品中）。混合样品中，只有真主
        物相的最强线会全部出现在测量峰里，故 top_precision 可有效区分真
        物相与"碰巧覆盖多个测量峰"的密集杂相。
      - intensity_weighted_top_recall：若传入 ``measured_i``，按测量峰强度
        加权的 top_recall，即"物相最强去重峰覆盖的测量峰强度之和 / 测量峰
        总强度"。当 top_precision 并列时，真主物相（其最强峰解释了样品最强
        峰）会因加权召回率高而胜出，可有效避免密集低强度峰物相（如 MgCO3）
        误抢占 CaCO3 主峰位置。
      - main_peak_match：若传入 ``measured_i``，等于 1.0 当物相最强去重峰
        落在样品最强峰（I 最大）±tolerance 内，否则 0.0。Hanawalt 主峰
        原则：主物相的最强线应对上样品的最强线。

    排序主键（默认）：main_peak_match → top_precision →
    intensity_weighted_top_recall → top_recall → meas_ratio → score，
    均降序。``score = top_precision*100 + top_recall*10 + recall``，仅作
    次级参考。返回前 ``limit`` 个。

    Args:
        conn: 已打开的 sqlite 连接（表 ``phases``；COD 无机库 / PDF2 库 /
            用户库同构）。本模块不负责打开或关闭它。
        measured_d: 测得的 d 值列表（Å）
        measured_i: 测得峰强度列表（可选，与 ``measured_d`` 等长平行）。
            传入后启用强度加权召回率与主峰匹配判据，显著提升混合样品中主
            物相识别正确率。None 时退化为仅按 d 值覆盖度排序。
        tolerance: d 值匹配容差（Å），绝对下限，同时用作去重阈值
        tolerance_rel: d 值的相对容差（比例）。>0 时实际容差取
            ``max(tolerance, tolerance_rel*d)``，使匹配窗口在 2θ 空间近似
            恒定（低角度放宽、高角度收紧）。默认 0 = 纯绝对容差。
        min_match: 最少反向匹配测量峰数，低于此数的物相被丢弃
        limit: 返回结果上限
        max_ref_peaks: 每个物相参与匹配的最大主要峰数（I 值最高的）
        main_peak_topk: 主峰匹配比对的样品最强峰个数。COD 等参考库的"最强
            峰"排序常与实验谱略有出入（同一物相两条强线谁是 #1 可能互换），
            只比对单一最强峰会把真物相误杀；比对前 K 个即可保留 Hanawalt
            主峰原则的判别力又避免这种脆性。默认 1（严格）。
        elements_allowed: 元素集合约束。在扫描层下推，避免候选名额被无效
            化学成分占用。formula 解析不出元素（空集）的行**放行**，交给
            上层用 CIF 的 ``_chemical_formula_sum`` 复核 —— 见下方注释。

    Returns:
        匹配物相列表，每项含 cod_id, ref_id, display_id, formula,
        space_group, n_peaks, n_ref_used, n_matched_ref, n_matched_meas,
        n_meas_in_top, n_top_unique, n_top_observed, n_top_k, top_recall,
        top_precision, match_ratio（正向）, meas_ratio（反向 recall）, score,
        intensity_weighted_top_recall, main_peak_match
    """
    if conn is None or not measured_d:
        return []

    # ── 有效容差: 绝对下限 + 相对分量 (0.9.11) ────────────────
    # 纯绝对 d 容差在 2θ 空间里极不均匀: 固定 0.02 Å 在 d=4 Å (2θ≈22°)
    # 只对应 ~0.11° 的 2θ 窗口 (比峰宽还窄 → 漏配真峰), 而在 d=1 Å
    # (2θ≈101°) 却对应 ~2.8° (过宽 → 误配)。相对分量 tol_rel·d 让高角度
    # 收紧、低角度放宽, 与"恒定 2θ 窗口"的物理直觉一致。
    # 标量写法与数组写法两个入口分别由 tol_scalar / np.maximum 承担,
    # 二者对正常取值一致 (NaN 的差别见 tol_scalar 文档)。
    trel = float(tolerance_rel or 0.0)
    use_rel = trel > 0.0
    tol_abs = float(tolerance)

    # 预排序测量 d 值, 区间匹配全部走 searchsorted
    meas_sorted = sorted(measured_d)
    n_meas = len(meas_sorted)
    # 若提供 measured_i, 做强度加权召回与主峰匹配。需保持 d↔I 对应关系。
    use_intensity = measured_i is not None and len(measured_i) == n_meas
    if use_intensity:
        # 按 d 升序的 (d, I) 对, 与 meas_sorted 对齐
        di_pairs = sorted(zip(measured_d, measured_i), key=lambda p: p[0])
        meas_i_sorted = [p[1] for p in di_pairs]
        total_i = sum(meas_i_sorted)
        # 样品最强峰: d↔I 对齐中 I 最大的索引 (在 meas_sorted 中的位置)
        main_meas_i_in_sorted = max(range(n_meas), key=lambda k: meas_i_sorted[k])
        main_meas_d = meas_sorted[main_meas_i_in_sorted]
        # 样品最强峰集合 (前 main_peak_topk 个最强峰的 d), 用于放宽主峰匹配
        if main_peak_topk and main_peak_topk > 1:
            tk = max(1, int(main_peak_topk))
            ti = np.argsort(-np.asarray(meas_i_sorted, dtype=np.float64))[:tk]
            main_meas_d_topk = [float(meas_sorted[i]) for i in ti]
        else:
            main_meas_d_topk = [main_meas_d] if main_meas_d is not None else []
    else:
        meas_i_sorted = None
        total_i = 0.0
        main_meas_d = None
        main_meas_d_topk = []
    # ── 0.9.11+: 扫描层向量化 ────────────────────────────
    # 语义**逐条对齐**旧实现 (含并列时的先后、去重顺序、计数口径),
    # 由 tests/test_phase_search.py 以冻结 golden 逐字段比对守住。
    md = np.asarray(meas_sorted, dtype=np.float64)
    mi_np = np.asarray(meas_i_sorted, dtype=np.float64) if use_intensity else None
    results: list[dict] = []
    # 若库里有预截断强峰列 (见 PEAK_TOP_N) 且本次请求的 max_ref_peaks
    # 落在其覆盖范围内, 就只读那几列 —— 省掉 85% 的峰串解析和每相的
    # argsort。结果与全长解析**完全一致** (前缀等价性证明见 PEAK_TOP_N)。
    use_top = has_top_peak_columns(conn) and max_ref_peaks <= PEAK_TOP_N
    cur = conn.execute(_SQL_TOP if use_top else _SQL_FULL)
    # 元素约束下推 (化学过滤在扫描层完成, 避免候选名额被无效化学成分占用)。
    # 走 `formula_parser.elements_from_db_formula` 的**单点实现** ——
    # 0.9.11 曾在这里复制了一份 token 正则, 口径容易漂移。
    #
    # 空集 = 该行 formula **不可信** (COD 无机物库实测有 605 条被写成了
    # 空间群符号, 如 "P 63 m c"; 另有极少数为空) → **放行**交给判定层用
    # CIF 的 _chemical_formula_sum 复核。若在此按 issubset 淘汰, 真物相会
    # 在扫描层就被误杀 (实测: 勾 Zn/O 过滤时 ZnO 就是这样丢的, 候选 40 → 2)。
    for row in cur:
        if elements_allowed is not None:
            els = elements_from_db_formula(
                row["formula"], space_group=row["space_group"] or ""
            )
            if els and not els.issubset(elements_allowed):
                continue
        if use_top:
            d_np = parse_float_csv(row["peaks_top_d"])
            i_np = parse_float_csv(row["peaks_top_i"])
        else:
            peaks_d_str = row["peaks_d"]
            peaks_i_str = row["peaks_i"]
            if not peaks_d_str or not peaks_i_str:
                continue
            d_np = parse_float_csv(peaks_d_str)
            i_np = parse_float_csv(peaks_i_str)
        if d_np.size == 0 or i_np.size == 0:
            continue
        n_i = i_np.size
        n_d = d_np.size
        # 强度降序 (kind="stable" ⇒ 并列时保持原始先后, 与
        # sorted(..., key=..., reverse=True) 的稳定性一致)。
        # 预截断列已按 I 降序存好 ⇒ order 恒等, 直接 arange 跳过排序。
        order = (np.arange(n_i) if use_top
                 else np.argsort(-i_np, kind="stable"))
        # 取 I 值最高的前 max_ref_peaks 个峰 (与原实现同样只在
        # k < len(ref_d_all) 的范围内有效)
        sel = order[:max_ref_peaks]
        if n_i > n_d:
            sel = sel[sel < n_d]
        ref_d = d_np[sel]
        n_ref_used = int(ref_d.size)
        # 反向匹配: 测量峰中被主要参考峰覆盖的数量
        t_ref = (np.maximum(tol_abs, trel * ref_d) if use_rel
                 else np.full(n_ref_used, tol_abs))
        hit_ref, pos_ref = match_positions(md, ref_d - t_ref, ref_d + t_ref)
        n_matched_ref = int(hit_ref.sum())
        # 去重后 = "被覆盖的测量峰个数" (多个参考峰可命中同一测量峰;
        # pos_ref 中未命中的位置无意义, 先按 hit_ref 掩掉)
        n_matched_meas = int(np.unique(pos_ref[hit_ref]).size)
        if n_matched_meas < min_match:
            continue
        # ── top_recall: 物相最强的少数峰 (去重后) ──
        n_top = min(n_i, max(n_meas + 2, 8), 12)
        top_sel = order[:n_top]
        if n_i > n_d:
            top_sel = top_sel[top_sel < n_d]
        # 按 I 降序处理 (并列保持原顺序), 丢弃 ±tolerance 内的近重复
        top_d = d_np[top_sel[np.argsort(-i_np[top_sel], kind="stable")]]
        unique_top_d = dedupe_by_tol(top_d, tol_abs, trel, use_rel)
        # 测量峰中有多少落在"物相最强去重峰"内 (窗口以测量峰为中心)
        if unique_top_d:
            ud = np.asarray(unique_top_d, dtype=np.float64)
            t_md = (np.maximum(tol_abs, trel * md) if use_rel
                    else np.full(n_meas, tol_abs))
            hit_m = interval_hit(np.sort(ud), md - t_md, md + t_md)
            n_meas_in_top = int(hit_m.sum())
            covered_i_sum = float(mi_np[hit_m].sum()) if use_intensity else 0.0
            # main_peak_match: 物相最强去重峰是否落在样品前 K 个最强峰窗口内
            if use_intensity:
                phase_main_d = float(ud[0])
                main_peak_match = 0.0
                for mdk in main_meas_d_topk:
                    t_main = max(tol_scalar(phase_main_d, tol_abs, trel, use_rel),
                                 tol_scalar(mdk, tol_abs, trel, use_rel))
                    if abs(phase_main_d - mdk) <= t_main:
                        main_peak_match = 1.0
                        break
            else:
                main_peak_match = 0.0
            # top_precision: 最强前 5 个去重峰中有多少被观察到 (窗口以物相峰为中心)
            k5 = ud[:5]
            t5 = (np.maximum(tol_abs, trel * k5) if use_rel
                  else np.full(k5.size, tol_abs))
            n_top_observed = int(interval_hit(md, k5 - t5, k5 + t5).sum())
            top_precision = n_top_observed / float(k5.size)
        else:
            n_meas_in_top = 0
            covered_i_sum = 0.0
            main_peak_match = 0.0
            n_top_observed = 0
            top_precision = 0.0
        top_recall = n_meas_in_top / n_meas if n_meas else 0.0
        # 强度加权 top_recall: 加权和/总强度 (0..1)
        intensity_weighted_top_recall = (
            covered_i_sum / total_i if (use_intensity and total_i > 0) else 0.0
        )
        recall = n_matched_meas / n_meas if n_meas else 0.0
        ref_ratio = n_matched_ref / n_ref_used if n_ref_used else 0.0
        # 主得分: top_precision (物相最强线被观察到?) 占主导, top_recall 次之
        score = top_precision * 100.0 + top_recall * 10.0 + recall
        results.append({
            "cod_id": row["cod_id"],
            "ref_id": row["ref_id"],
            "display_id": row["display_id"],
            "formula": row["formula"],
            "space_group": row["space_group"],
            "n_peaks": row["n_peaks"],
            "n_ref_used": n_ref_used,
            "n_matched_ref": n_matched_ref,
            "n_matched_meas": n_matched_meas,
            "n_meas_in_top": n_meas_in_top,
            "n_top_unique": len(unique_top_d),
            "n_top_observed": n_top_observed,
            "n_top_k": int(min(len(unique_top_d), 5)),
            "top_recall": top_recall,
            "top_precision": top_precision,
            "intensity_weighted_top_recall": intensity_weighted_top_recall,
            "main_peak_match": main_peak_match,
            "match_ratio": ref_ratio,
            "meas_ratio": recall,
            "score": score,
        })
    # 排序主键: main_peak_match → top_precision → intensity_weighted_top_recall
    # → top_recall → meas_ratio → score, 均降序。main_peak_match 放最前是
    # Hanawalt 主峰原则 —— 物相主峰应对上样品最强峰。即便物相次峰未全部被
    # 观察到 (如弱含量物相), 主峰对上即可优先。这避免了像 SiO2-quartz
    # (top_p=0.2, 主峰对上) 被挤出 top-200, 而让密集杂相 (top_p=1.0, 主峰
    # 不对位) 误排前列。当 measured_i 未提供时, main_peak_match /
    # intensity_weighted_top_recall 均为 0, 等价于原
    # (top_precision, top_recall, ...) 排序。
    results.sort(
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
    return results[:limit]


# ──────────────────────────────────────────────────────────────
# 旧下划线命名的兼容别名
# ──────────────────────────────────────────────────────────────
# P2 迁移 cif_database / polydb 调用点时用公开名；保留别名让两者在过渡期
# 可互换 import，避免一次性改动过大。
_parse_float_csv = parse_float_csv
_tol_scalar = tol_scalar
_interval_hit = interval_hit
_match_positions = match_positions
_dedupe_by_tol = dedupe_by_tol
_top_peaks_of = top_peaks_of
_PEAK_TOP_N = PEAK_TOP_N
