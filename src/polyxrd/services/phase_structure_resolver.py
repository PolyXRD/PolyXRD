"""物相 → CIF 结构自动匹配 (精修前置)
====================================

物相分析里勾选的候选相来自检索库, 多数只有参考峰 (d-I) 与晶胞参数,
**没有** ``cif_path`` / ``atomic_sites`` —— 而 Rietveld 真结构精修
(GSAS-II / MAUD) 与 ``_refine_auto`` 的引擎选择都依赖 ``cif_path``。
本服务在「开始精修」前把已选物相逐一匹配到库内 CIF 并补齐结构:

1. 已带可用结构 (atomic_sites + 磁盘上的 cif_path) 的相**原样保留**;
2. 名字里带 COD 编号 ("...(COD 1000054)") 的直接按编号取;
3. 其余按规范化化学式 (必要时加矿物名) 在 COD 库里找结构候选,
   按空间群一致 + 晶胞接近度排序, 逐个尝试加载;
4. 命中后把 lattice / atomic_sites / cif_path / reference_peaks
   (pymatgen 模拟峰) 合并进原物相 —— **保留原 name / formula /
   match_score**, 勾选集合与谱图叠加的身份不受影响;
5. cif_path 若只存在于库内 BLOB (无机库 cif_gz), 落盘到
   ``~/.polyxrd/cif_cache/COD<id>.cif`` —— GSAS-II 桥要求磁盘文件。

日志用 ``[cif]`` 前缀的技术行 (与引擎的 [start]/[data]/[phase] 同风格,
不做本地化), 经回调交给精修页的过程日志面板。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from polyxrd.models.phase import Phase
from polyxrd.utils.formula_parser import normalize_cod_formula

__all__ = [
    "normalize_cod_formula",
    "extract_cod_id",
    "PhaseStructureResolver",
]

# 物相名里的 COD 编号: "H2 Mg O2 (COD 1000054)" / "COD:9002348"
_COD_ID_RE = re.compile(r"COD[:\s#]*([0-9]{5,8})")

#: 候选晶胞参数的合格范围 (防脏数据: 实测见过 5.5e-313 / None)
_CELL_MIN, _CELL_MAX = 0.5, 200.0
#: 角度合格范围
_ANG_MIN, _ANG_MAX = 5.0, 175.0


def extract_cod_id(*texts: object) -> Optional[int]:
    """从若干文本 (物相名等) 里提取第一个 COD 编号, 无则 None。"""
    for t in texts:
        m = _COD_ID_RE.search(str(t or ""))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def _cell_ok(v: object, lo: float, hi: float) -> Optional[float]:
    """库里的晶胞值 → 合格 float, 脏数据 (None/越界/非数值) 返回 None。"""
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if lo <= f <= hi:
        return f
    return None


def _candidate_score(cand: dict, phase: Phase) -> float:
    """候选排序分 (越小越好): 空间群一致 > 晶胞接近 > 有内嵌 CIF。"""
    score = 0.0
    sg_p = (getattr(phase, "space_group", "") or "").strip()
    sg_c = (cand.get("space_group") or "").strip()
    # 剥 setting 后缀 ("P m m n :2" ≈ "P m m n") 再比较
    if sg_p and sg_c and sg_p.split(":")[0].strip() == sg_c.split(":")[0].strip():
        score -= 2.0

    # 晶胞接近度: 各可用参数的平均相对偏差
    pairs = (
        ("a", _CELL_MIN, _CELL_MAX),
        ("b", _CELL_MIN, _CELL_MAX),
        ("c", _CELL_MIN, _CELL_MAX),
        ("alpha", _ANG_MIN, _ANG_MAX),
        ("beta", _ANG_MIN, _ANG_MAX),
        ("gamma", _ANG_MIN, _ANG_MAX),
    )
    lat = getattr(phase, "lattice", None)
    diffs: list[float] = []
    n_invalid = 0
    for key, lo, hi in pairs:
        cv = _cell_ok(cand.get(key), lo, hi)
        if cv is None:
            # 库里的脏数据 (None / 5.5e-313) 不可信, 逐项惩罚
            n_invalid += 1
            continue
        pv = float(getattr(lat, key)) if lat is not None else None
        if pv is None or pv <= 0:
            continue
        diffs.append(abs(cv - pv) / pv)
    if diffs:
        score += sum(diffs) / len(diffs)
    else:
        score += 1.0  # 无可比晶胞 → 记中性偏坏, 别排到前面
    score += 0.05 * n_invalid

    if not cand.get("has_cif"):
        score += 0.5
    return score


def _peak_disagreement(cif_phase: Phase, orig: Phase) -> float:
    """候选结构模拟峰 vs 库内 d-I 峰的位置失配度 (越小越可信).

    v0.15.2 新增, 用于**多形体甄别**: 方解石 (R-3c) 与文石 (Pmcn) 晶胞
    参数接近、仅凭"空间群一致 + 晶胞接近度"排序会选错 (2-1 实测把方解石
    匹配到 Pmcn 文石型 CaCO3, 104 主峰 29.4° 无法拟合 → wR 卡 40%)。
    位置失配对**衍射花样**敏感, 可把多形体区分开。

    双向加权平均 2θ 距离 (强峰 I≥5 参与权重)。
    - 库侧 (orig) 无峰: 返回 0 (中性, 所有候选同样无法评判);
    - 模拟侧 (cif_phase) 无峰: 返回 inf —— 模拟不出的结构对精修毫无
      价值, 必须输给任何可评判的候选 (COD 1559793 教训: 垃圾位点结构
      无模拟峰, 曾以 0 分"完美"夺冠)。
    """
    lib = [(float(t), float(i)) for _, t, i in
           (orig.get_reference_peaks() if hasattr(orig, "get_reference_peaks")
            else orig.reference_peaks) or []]
    sim = [(float(t), float(i)) for _, t, i in
           (getattr(cif_phase, "reference_peaks", None) or [])]
    if not sim:
        return float("inf")
    if not lib:
        return 0.0

    def _one_way(src, dst) -> float:
        pen = 0.0
        w = 0.0
        for t, i in src:
            if i < 5.0:
                continue
            w += i
            d = min((abs(t - tt2) for tt2, _ in dst), default=5.0)
            pen += i * min(d, 2.0)
        return pen / w if w else 0.0

    return _one_way(sim, lib) + _one_way(lib, sim)


class PhaseStructureResolver:
    """把检索得到的物相批量匹配到 COD 库 CIF 的解析器。

    实例持有 COD 库连接与 (name, formula) → 解析结果缓存, 供
    ``MainViewModel`` 复用 —— 同一物相第二次精修不再重复查库。
    """

    def __init__(self, cod_db=None) -> None:
        self._db = cod_db
        self._db_ready: Optional[bool] = None  # None = 未探测
        self._cache: dict[tuple[str, str], Phase] = {}

    # ── 库访问 ──────────────────────────────────────────────

    def _get_db(self):
        if self._db is not None:
            return self._db
        if self._db_ready is False:
            return None
        try:
            from polyxrd.services.cod_local import CODLocalDatabase

            db = CODLocalDatabase()
            ready = bool(db.is_ready()) or db._inorg_db() is not None
            self._db, self._db_ready = (db, ready) if ready else (None, False)
        except Exception:
            self._db, self._db_ready = None, False
        return self._db

    # ── 主入口 ──────────────────────────────────────────────

    def resolve(
        self,
        phases: list[Phase],
        *,
        wavelength: float = 1.5406,
        two_theta_range: tuple[float, float] = (5.0, 90.0),
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> list[Phase]:
        """返回与 ``phases`` 等长的结构补齐列表 (不修改入参对象)。

        未命中 CIF 的相**原样返回** (仍以参考峰剖面参与 builtin 精修),
        不会因为匹配失败而阻断精修。
        """
        log = log_cb or (lambda _m: None)
        out: list[Phase] = []
        n_ok = 0
        for phase in phases:
            resolved, note = self._resolve_one(
                phase, wavelength=wavelength, two_theta_range=two_theta_range
            )
            out.append(resolved)
            log(f"[cif] {note}")
            if resolved is not phase:
                n_ok += 1
        log(f"[cif] structure match: {n_ok}/{len(phases)} phases loaded with CIF base structure")
        return out

    # ── 单相解析 ────────────────────────────────────────────

    def _resolve_one(
        self,
        phase: Phase,
        *,
        wavelength: float,
        two_theta_range: tuple[float, float],
    ) -> tuple[Phase, str]:
        name = getattr(phase, "name", "") or "?"
        formula = getattr(phase, "formula", "") or ""

        # 0) 已带可用结构 → 原样保留
        cif_path = getattr(phase, "cif_path", None)
        if getattr(phase, "atomic_sites", None) and cif_path and Path(cif_path).exists():
            return phase, f"{name}: 已有结构, 跳过 ({Path(cif_path).name})"

        key = (name, formula)
        cached = self._cache.get(key)
        if cached is not None:
            if cached is phase:
                return phase, f"{name}: 无可用 CIF (缓存命中)"
            return cached, f"{name}: CIF 命中缓存 ({self._describe(cached)})"

        db = self._get_db()
        if db is None:
            self._cache[key] = phase
            return phase, f"{name}: COD 库不可用, 以参考峰剖面参与精修"

        # 1) 名字里的 COD 编号直取
        cod_id = extract_cod_id(name, formula)
        if cod_id is not None:
            cif_phase = self._load_phase(
                db, cod_id, wavelength, two_theta_range
            )
            if cif_phase is not None:
                merged = self._merge(phase, cif_phase, cod_id)
                self._cache[key] = merged
                return merged, f"{name}: 编号 {cod_id} 命中 ({self._describe(cif_phase)})"
            log_note = f"{name}: 编号 {cod_id} 未取到结构, 改按化学式匹配"
        else:
            log_note = None

        # 2) 规范化化学式 (+ 矿物名) 找候选
        norm = normalize_cod_formula(formula)
        mineral = self._clean_mineral(name)
        if not norm and not mineral:
            self._cache[key] = phase
            return phase, f"{name}: 无化学式可匹配, 以参考峰剖面参与精修"

        try:
            cands = db.find_structure_candidates(norm, mineral_name=mineral)
        except Exception:
            cands = []
        cands.sort(key=lambda c: _candidate_score(c, phase))

        # v0.15.2: 多形体甄别 —— 候选结构模拟峰与库内 d-I 峰的位置失配度
        # 参与择优 (旧逻辑取排序后第一个能加载的候选, 多形体易选错)。
        best: Optional[tuple[float, dict, Phase]] = None
        for cand in cands[:6]:
            cif_phase = self._load_phase(
                db, int(cand["cod_id"]), wavelength, two_theta_range
            )
            if cif_phase is None or not cif_phase.atomic_sites:
                continue
            score = (_peak_disagreement(cif_phase, phase)
                     + 0.3 * _candidate_score(cand, phase))
            if best is None or score < best[0]:
                best = (score, cand, cif_phase)

        if best is not None:
            cand, cif_phase = best[1], best[2]
            merged = self._merge(phase, cif_phase, int(cand["cod_id"]))
            self._cache[key] = merged
            note = (
                f"{name}: {norm or mineral} → COD {cand['cod_id']} "
                f"({self._describe(cif_phase)})"
            )
            if log_note:
                note = f"{log_note}; {note}"
            return merged, note

        # 3) 未命中 → 原样返回
        self._cache[key] = phase
        note = f"{name}: 未找到可用 CIF ({norm or mineral or '无化学式'}), 以参考峰剖面参与精修"
        if log_note:
            note = f"{log_note}; {note}"
        return phase, note

    # ── 工具 ────────────────────────────────────────────────

    @staticmethod
    def _clean_mineral(name: str) -> str:
        """物相名 → 可用的矿物名 (纯数字/含 COD 标记的都不要)。"""
        s = (name or "").strip()
        if not s or s.isdigit() or "COD" in s.upper():
            return ""
        # 去掉尾部修饰: "Calcite (COD 1...)" 已被上面拦掉; "Zincite - ZnO" 之类
        s = re.split(r"[-·—]", s)[0].strip()
        return s if s and not s.isdigit() else ""

    @staticmethod
    def _describe(cif_phase: Phase) -> str:
        sg = (cif_phase.space_group or "").strip() or "sg?"
        lat = cif_phase.lattice
        cell = f"a={lat.a:.3f}" if lat is not None else "a=?"
        n = len(cif_phase.atomic_sites or [])
        return f"{sg}, {cell} Å, {n} 位点"

    def _load_phase(self, db, cod_id: int, wavelength: float,
                    two_theta_range: tuple[float, float]) -> Optional[Phase]:
        """按编号取带结构的物相 (atomic_sites 必须非空才算命中)。"""
        try:
            p = db.get_phase(
                cod_id,
                wavelength=wavelength,
                two_theta_range=two_theta_range,
                use_pymatgen_peaks=True,
            )
        except Exception:
            return None
        if p is None or not getattr(p, "atomic_sites", None):
            return None
        # v0.15.2: 模拟峰为空的结构无法参与 |F|² 精修也无法评判, 不算命中
        if not getattr(p, "reference_peaks", None):
            return None
        p.cif_path = self._ensure_cif_file(db, cod_id, p.cif_path)
        return p

    @staticmethod
    def _ensure_cif_file(db, cod_id: int, cif_path: Optional[str]) -> Optional[str]:
        """保证 cif_path 是磁盘上真实存在的 .cif (GSAS-II/MAUD 的硬要求)。

        库里只有 BLOB (无机库 cif_gz) 时落盘到 ~/.polyxrd/cif_cache/。
        """
        if cif_path and Path(cif_path).exists() and Path(cif_path).suffix.lower() == ".cif":
            return cif_path
        try:
            text = db.get_cif(cod_id)
            if not text:
                return cif_path
            cache_dir = Path.home() / ".polyxrd" / "cif_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            out = cache_dir / f"COD{cod_id}.cif"
            out.write_text(text, encoding="utf-8")
            return str(out)
        except Exception:
            return cif_path

    @staticmethod
    def _merge(orig: Phase, cif: Phase, cod_id: int) -> Phase:
        """以 CIF 结构为基础重建物相; 身份字段 (name/formula/分数) 沿用原相。

        reference_peaks 优先用 CIF 结构模拟峰 (pymatgen, 强度绝对可比),
        空时回退原相的库 d-I 峰 —— 两者都是 0-100 归一, builtin 引擎通用。
        """
        ref_peaks = getattr(cif, "reference_peaks", None) or orig.reference_peaks
        return Phase(
            name=orig.name,
            formula=orig.formula,
            space_group=(getattr(orig, "space_group", "") or "").strip()
            or (cif.space_group or ""),
            lattice=cif.lattice or orig.lattice,
            atomic_sites=list(cif.atomic_sites or []),
            reference_peaks=list(ref_peaks),
            weight_fraction=orig.weight_fraction,
            match_score=orig.match_score,
            cif_path=cif.cif_path,
            elements=orig.elements or cif.elements,
        )
