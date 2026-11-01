"""物相 → 补齐原子位点（精修前置，v5.0.1）
==========================================

检索得到的物相常常只有"参考峰 + 晶胞"、没有原子位点（内置矿物表、PDF2
候选、部分用户库条目都是这种形态）。v5.0.0 精修引擎按**结构因子**算强度
（``I ∝ m|F|²·LP/V²``），缺位点就没法算 —— ``_refine_v5`` 只能整条回退
内置引擎，结果区看到 ``diag.engine_fallback: no structure: Zincite, Calcite``。

本服务在精修前给这些相找结构：按 **(化学式 + 空间群 + 晶胞)** 在 polyDB
里定位同一条目，把 polyDB 的**全胞位点**复制进来。

三道门都过才采纳（宁可不用新引擎，也不能用错结构）::

    化学式（规范化后逐字一致）   + 空间群一致（去空格/setting） + 晶胞 ≤5%, ≤3°
    或  元素集一致（成分可能不同）+ 空间群一致               + 晶胞 ≤2%, ≤1.5°

为什么必须这么严：错结构的 Rwp 往往**比参考峰剖面更好看**（自由度多、峰位
对得上、强度随便凑），属于典型的"静默错"。同族不同相（Zincite/ZnO 高压相）、
同化学式不同多形体（Aragonite/Calcite）都靠上面两道门挡掉。

位点展开：polyDB 的 ``sites.bin`` 存的是 CIF 原样的**非对称单位**，进精修
链路前必须按空间群展开成完整晶胞（v4.1.1 假峰事故）。展开用
:func:`phase_cif.expand_sites_by_symmetry` 的 ``strict=True``：拿不到全胞
位点就**换下一个候选**，绝不把非对称单位当全胞用。

调用方
------
* :class:`polyxrd.services.phase_structure_resolver.PhaseStructureResolver`
  —— GUI 精修前的统一入口（GSAS-II / MAUD / v5 共用），补齐后照旧由位点
  反生成 CIF 落盘；
* :meth:`polyxrd.services.rietveld_refiner.RietveldRefiner._refine_v5`
  —— 非 GUI 路径（批处理 / 基准 / MCP）也走，保证行为一致。

日志用 ``[cif]`` 前缀（与 ``phase_structure_resolver`` 同风格，技术行不做
本地化）。
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Callable, Optional

from polyxrd.models.phase import Phase
from polyxrd.utils.formula_parser import (
    elements_from_db_formula,
    normalize_cod_formula,
)

__all__ = [
    "SiteFill",
    "fill_atomic_sites",
    "normalize_space_group",
]

#: 晶胞长度相对偏差上限（化学式逐字一致时）
CELL_TOL = 0.05
#: 晶胞角度绝对偏差上限（度）
ANGLE_TOL = 3.0
#: 只有元素集一致（成分可能不同 / 固溶体）时的更严门槛
SITE_CELL_TOL = 0.02
SITE_ANGLE_TOL = 1.5
#: 化学式/矿名查询的候选池上限（实测 300 条可覆盖 CaCO₃ 的 114 条同式条目）
_POOL = 300
#: 单次补齐最多接受的候选取相次数（防止某相疯狂试错拖慢精修）
_MAX_TRIES = 6

_SG_SETTING_RE = re.compile(r":(?:h|r|\d+)$")


def normalize_space_group(space_group: object) -> str:
    """空间群符号归一：去空白、小写、剥 setting 后缀（``R -3 c :H`` → ``r-3c``）。"""
    s = re.sub(r"\s+", "", str(space_group or "")).lower()
    return _SG_SETTING_RE.sub("", s)


def _flat_formula(text: object) -> str:
    """化学式归一：COD 写法（``O2 Si``）与用户写法（``SiO2``）都压成 ``o2si``。"""
    raw = str(text or "")
    try:
        norm = normalize_cod_formula(raw) or ""
    except Exception:  # noqa: BLE001 - 规范化失败退回原文
        norm = raw
    return re.sub(r"\s+", "", norm).lower()


def _element_set(text: object) -> frozenset[str]:
    try:
        return frozenset(e for e in elements_from_db_formula(str(text or "")) if e)
    except Exception:  # noqa: BLE001
        return frozenset()


def _cell_of(obj: object) -> Optional[dict]:
    """从 Phase.lattice / dict / polyDB 行里取六参数晶胞，取不到返回 None。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        get = obj.get
        vals = (get("cell_a", get("a")), get("cell_b", get("b")),
                get("cell_c", get("c")), get("cell_alpha", get("alpha", 90.0)),
                get("cell_beta", get("beta", 90.0)),
                get("cell_gamma", get("gamma", 90.0)))
    else:
        get = lambda k, d=None: getattr(obj, k, d)  # noqa: E731
        vals = (get("a"), get("b"), get("c"), get("alpha", 90.0),
                get("beta", 90.0), get("gamma", 90.0))
    try:
        out = tuple(float(v) for v in vals)
    except (TypeError, ValueError):
        return None
    if out[0] <= 0 or out[1] <= 0 or out[2] <= 0:
        return None
    return dict(zip(("a", "b", "c", "alpha", "beta", "gamma"), out))


def _cell_dev(pa: dict, pb: dict) -> tuple[float, float]:
    """两套晶胞的 (长度最大相对偏差, 角度最大绝对偏差)。"""
    d_len = max(abs(pa[k] - pb[k]) / max(pa[k], 1e-9) for k in ("a", "b", "c"))
    d_ang = max(abs(pa[k] - pb[k]) for k in ("alpha", "beta", "gamma"))
    return float(d_len), float(d_ang)


@dataclass
class SiteFill:
    """一次位点补齐的结果说明（供结果区 / 日志展示）。"""

    name: str
    source: str
    matched_by: str
    n_sites: int
    cell_dev: float
    note: str = ""

    def describe(self) -> str:
        txt = f"{self.name}: 补齐位点 ← {self.source} ({self.matched_by}, " \
              f"{self.n_sites} 位点, 晶胞偏差 {self.cell_dev * 100:.2f}%)"
        return f"{txt}；{self.note}" if self.note else txt


def _queries_of(phase: Phase) -> list[str]:
    """查库用的文本，**化学式优先**（"名字去掉 (COD 123) / - 修饰"）。

    顺序有意义：:func:`_fill_one` 是惰性试的，公式命中就收手，省掉一次
    ~0.2 s 的 LIKE 全表扫（实测 2-1 六相从 3.9 s 降到 ~1.6 s）。
    """
    out: list[str] = []
    raw_name = str(getattr(phase, "name", "") or "").strip()
    name = re.split(r"[(\[]", raw_name)[0].strip()
    name = re.split(r"\s+-\s+", name)[0].strip()
    for q in (str(getattr(phase, "formula", "") or "").strip(), name):
        if len(q) >= 2 and q not in out and not q.isdigit():
            out.append(q)
    return out


def _name_bonus(phase: Phase, cand_mineral: str) -> float:
    """矿名相近加分（只在 sg+晶胞已过门时用作并列决胜）。"""
    a = re.sub(r"[^a-z]", "", str(getattr(phase, "name", "") or "").lower())
    b = re.sub(r"[^a-z]", "", str(cand_mineral or "").lower())
    if not a or not b:
        return 0.0
    return 1.0 if (a in b or b in a) else 0.0


def _judge(phase: Phase, cand: dict) -> Optional[tuple[str, float, str]]:
    """判候选是否可用；可用返回 (匹配方式, 晶胞偏差, 备注)，否则 None。"""
    pc = _cell_of(getattr(phase, "lattice", None))
    cc = _cell_of(cand)
    if pc is None or cc is None:
        return None
    sg_p = normalize_space_group(getattr(phase, "space_group", ""))
    sg_c = normalize_space_group(cand.get("space_group", ""))
    if sg_p and sg_c and sg_p != sg_c:
        return None  # 空间群不一致 → 多形体 / 不同相，直接否掉

    f_p = _flat_formula(getattr(phase, "formula", ""))
    f_c = _flat_formula(cand.get("formula", ""))
    exact = bool(f_p) and f_p == f_c
    # 元素集一律从**原始**化学式解析：``_flat_formula`` 去掉空格后
    # "O2Zn2" 这种连写会被 token 解析器当成一个整体而解析失败。
    els_p = _element_set(getattr(phase, "formula", ""))
    els_c = _element_set(cand.get("formula", ""))
    same_els = bool(f_p) and not exact and bool(els_p) and els_p == els_c

    if not (exact or same_els):
        return None

    d_len, d_ang = _cell_dev(pc, cc)
    if exact:
        if d_len > CELL_TOL or d_ang > ANGLE_TOL:
            return None
        if sg_p and sg_c:
            return ("formula+sg+cell", d_len, "")
        return ("formula+cell", d_len, "空间群缺失，按晶胞锁定")
    # 元素相同但配比不同（固溶体）：晶胞要贴得更紧，并如实标注
    if d_len > SITE_CELL_TOL or d_ang > SITE_ANGLE_TOL:
        return None
    if not (sg_p and sg_c):
        return None
    note = f"化学式不一致（参考相 {cand.get('formula', '?')}），定量按该结构计"
    return ("elements+sg+cell", d_len, note)


def _load_sites(db, cod_id: int, space_group: str) -> list[dict]:
    """polyDB 非对称位点 → 全胞位点；展不开（认不出空间群）返回空列表。"""
    try:
        sites = db.get_atomic_sites(int(cod_id))
    except Exception:  # noqa: BLE001 - 侧车缺失不该拖垮精修
        return []
    if not sites:
        return []
    try:
        from polyxrd.services.phase_cif import expand_sites_by_symmetry

        expanded = expand_sites_by_symmetry(sites, space_group, strict=True)
    except Exception:  # noqa: BLE001
        return []
    return list(expanded or [])


def _pool_for(db, query: str, seen: dict[int, dict]) -> list[dict]:
    """按单个查询词取候选池（``seen`` 累积去重，供多次查询合并）。"""
    try:
        rows = db.search_entries(query, limit=_POOL)
    except Exception:  # noqa: BLE001 - 单次查询失败不影响其它查询
        return []
    for r in rows:
        eid = r.get("cod_id")
        if isinstance(eid, int) and eid not in seen:
            seen[eid] = r
    return list(seen.values())


def _fill_one(phase: Phase, db) -> tuple[Phase, Optional[SiteFill]]:
    """给单相补位点；补不上原样返回。

    惰性试查询：先化学式、再矿名，第一个能过关的查询就收手。每次尝试只对
    "过了三道门"的候选取位点，且最多 :data:`_MAX_TRIES` 次。
    """
    name = str(getattr(phase, "name", "") or "?")
    seen: dict[int, dict] = {}
    for query in _queries_of(phase):
        pool = _pool_for(db, query, seen)
        scored: list[tuple[tuple, dict, str, float, str]] = []
        for cand in pool:
            judged = _judge(phase, cand)
            if judged is None:
                continue
            how, dev, note = judged
            key = (
                1.0 if how.startswith("formula") else 0.0,
                _name_bonus(phase, cand.get("mineral_name", "")),
                -dev,
                int(cand.get("n_peaks") or 0),
            )
            scored.append((key, cand, how, dev, note))
        if not scored:
            continue
        scored.sort(key=lambda t: t[0], reverse=True)

        for _key, cand, how, dev, note in scored[:_MAX_TRIES]:
            eid = int(cand["cod_id"])
            sg = cand.get("space_group", "") or ""
            sites = _load_sites(db, eid, sg)
            if not sites:
                continue
            new_phase = copy.deepcopy(phase)
            new_phase.atomic_sites = sites
            if not normalize_space_group(getattr(phase, "space_group", "")):
                # 原相没有空间群 → 用参考相的空间群（位点就是按它展开的）
                new_phase.space_group = sg
            if not getattr(new_phase, "elements", None):
                new_phase.elements = set(_element_set(cand.get("formula", "")))
            src = f"polyDB COD {eid}"
            mineral = (cand.get("mineral_name") or "").strip()
            if mineral:
                src += f" ({mineral})"
            return new_phase, SiteFill(name=name, source=src, matched_by=how,
                                       n_sites=len(sites), cell_dev=dev, note=note)
    return phase, None


def fill_atomic_sites(
    phases: list[Phase],
    *,
    db=None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> tuple[list[Phase], list[SiteFill]]:
    """给缺位点的相补全胞位点（返回与入参等长的新列表）。

    Args:
        phases: 待精修的物相（已带位点的相原样保留，不做任何修改）。
        db: :class:`~polyxrd.services.polydb.PolyDatabase` 实例；``None`` 时
            按配置默认槽位打开（未挂载则整条跳过）。
        log_cb: 技术日志回调（``[cif]`` 前缀）。

    Returns:
        ``(补齐后的相列表, 补齐说明列表)``。补不上的相原样返回 —— 不阻断
        精修，由调用方决定是否回退内置引擎。
    """
    log = log_cb or (lambda _m: None)
    if not phases:
        return [], []

    own_db = False
    if db is None:
        try:
            from polyxrd.services.polydb import PolyDatabase

            db = PolyDatabase()
            own_db = True
        except Exception as e:  # noqa: BLE001 - 库缺失按无来源处理
            log(f"[cif] 位点补齐跳过: 数据库不可用 ({type(e).__name__}: {e})")
            return list(phases), []
    try:
        if not db.is_ready():
            log("[cif] 位点补齐跳过: polyDB 未挂载/不可用")
            return list(phases), []
        out: list[Phase] = []
        fills: list[SiteFill] = []
        for phase in phases:
            if getattr(phase, "atomic_sites", None):
                out.append(phase)
                continue
            try:
                new_phase, fill = _fill_one(phase, db)
            except Exception as e:  # noqa: BLE001 - 补齐失败不阻断精修
                log(f"[cif] {getattr(phase, 'name', '?')}: 位点补齐异常 "
                    f"{type(e).__name__}: {e}")
                new_phase, fill = phase, None
            out.append(new_phase)
            if fill is not None:
                fills.append(fill)
                log(f"[cif] {fill.describe()}")
            else:
                log(f"[cif] {getattr(phase, 'name', '?')}: 库中无匹配结构，保持参考峰剖面")
        return out, fills
    finally:
        if own_db:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass
