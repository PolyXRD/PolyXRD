"""物相 → CIF 结构自动匹配 (精修前置)
====================================

物相分析里勾选的候选相来自检索库, 多数只有参考峰 (d-I) 与晶胞参数,
**没有** ``cif_path`` / ``atomic_sites`` —— 而 Rietveld 真结构精修
(GSAS-II / MAUD) 与 ``_refine_auto`` 的引擎选择都依赖 ``cif_path``。
本服务在「开始精修」前把已选物相逐一补齐结构:

1. 已带可用结构 (atomic_sites + 磁盘上的 cif_path) 的相**原样保留**;
2. 相**已有展开后的原子位点**但无 cif_path 时 (内置 polyDB / 用户库 /
   PDF2 候选的典型形态), 用 :func:`phase_cif.phase_to_cif_text` 反生成
   CIF 落盘到 ``cif_cache_dir()`` 并回填 cif_path —— 否则干净安装下
   ``_phases_have_structure`` 恒 False, GSAS-II/MAUD 会被静默跳过;
3. 两者都不满足的相**原样返回**, 以参考峰剖面参与 builtin 精修, 不阻断。

v4.2 变更
---------
旧版第 2–3 步是"按名字里的 COD 编号 / 规范化化学式去 COD 本地 sqlite 里找
结构候选"(约 250 行, 含多形体甄别与 BLOB 落盘)。该库已从发布包移除,
相应分支在 v4.2 一并删除; 现在所有检索库 (polyDB / PDF2 / 用户库) 的候选
本来就自带晶胞与全胞位点, 直接走第 2 步即可。

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
    # v2.1-C: 元素集宽松匹配命中的候选降权 (精确化学式命中优先)
    if cand.get("_fallback"):
        score += 0.25
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


class PhaseStructureResolver:
    """把检索得到的物相批量匹配到 COD 库 CIF 的解析器。

    实例持有 (name, formula) → 解析结果缓存, 供 ``MainViewModel`` 复用
    —— 同一物相第二次精修不再重复生成 CIF 落盘。
    """

    def __init__(self) -> None:
        # (name, formula) → 解析结果；同一物相第二次精修不再重复落盘
        self._cache: dict[tuple[str, str], Phase] = {}

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

        # 0.5) 有位点、无 CIF 文件 → 由位点反生成 CIF 落盘并回填（v4.1.1）
        #      内置 polyDB 候选就是这种形态：晶胞 + 全胞位点，没有 CIF 文件。
        synth = self._synthesize_cif_from_sites(phase)
        if synth is not None:
            self._cache[key] = synth
            return synth, f"{name}: 由原子位点生成 CIF ({Path(synth.cif_path).name})"

        cached = self._cache.get(key)
        if cached is not None:
            if cached is phase:
                return phase, f"{name}: 无可用 CIF (缓存命中)"
            return cached, f"{name}: CIF 命中缓存 ({self._describe(cached)})"

        # 无位点、无 CIF → 只能以参考峰剖面参与 builtin 精修
        self._cache[key] = phase
        return phase, f"{name}: 无可用 CIF, 以参考峰剖面参与精修"

    # ── 工具 ────────────────────────────────────────────────

    @staticmethod
    def _synthesize_cif_from_sites(phase: Phase) -> Optional[Phase]:
        """有位点、无 CIF 文件时反生成 CIF 落盘并回填 ``cif_path``。

        这是 v4.2 之后**唯一**的结构来源：polyDB / 用户库 / PDF2 三类检索
        库的候选都自带完整晶胞 + 全胞位点，但没有 CIF 文件。若不兜底，
        干净安装下 ``_phases_have_structure`` 恒为 False → auto 引擎永远
        退回 builtin，GSAS-II/MAUD 装了也用不上。

        落盘位置 = ``AppConfig.cif_cache_dir()``（可写、可被 GSAS-II 读取）；
        失败时返回 None（调用方回退参考峰剖面，不劣化）。
        """
        sites = getattr(phase, "atomic_sites", None)
        if not sites or getattr(phase, "lattice", None) is None:
            return None
        cif_path = getattr(phase, "cif_path", None)
        if cif_path and Path(cif_path).exists():
            return None
        try:
            import copy
            import hashlib

            from polyxrd.config import get_config
            from polyxrd.services.phase_cif import phase_to_cif_text

            text = phase_to_cif_text(phase)
            if not text.strip():
                return None
            cache_dir = get_config().cif_cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_id = getattr(phase, "db_id", None)
            if isinstance(db_id, int) and db_id > 0:
                stem = f"COD{db_id}"
            else:
                stem = "PHASE-" + hashlib.sha1(
                    (phase.name or phase.formula or "?").encode("utf-8")
                ).hexdigest()[:12]
            out = cache_dir / f"{stem}.cif"
            if (not out.exists()
                    or out.read_text(encoding="utf-8", errors="ignore") != text):
                out.write_text(text, encoding="utf-8")
            copy_phase = copy.deepcopy(phase)
            copy_phase.cif_path = str(out)
            return copy_phase
        except Exception:  # noqa: BLE001 - 生成失败不阻断精修
            return None

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
