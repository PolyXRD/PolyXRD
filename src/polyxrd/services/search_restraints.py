"""
候选检索与约束 (M09)
====================
对应路线图 M09「候选检索与约束」的四个叶子能力, 与 M10 foam 的
search_match 组合使用 (apply_restraints 是 search_match 内
_passes_options 的超集, 增加密度维度):

- estimate_density / effective_density: 密度估算与取值
- apply_restraints: 元素 + 名称 + 密度综合过滤
- find_phases_direct: 名称/化学式模糊直搜 (Find phases/entries, 不区分大小写)
- save_preset / load_preset / list_presets / delete_preset:
  SearchOptions 预设存取 (~/.polyxrd/search_presets.json, 增量合并不覆盖他键)

符号约定: 密度单位 g/cm³; 密度过滤对「无密度且无法估算」的相放行
(宁多勿漏, 与三强峰预检可关的思路一致)。
"""
from __future__ import annotations

import fnmatch
import json
import math
from pathlib import Path
from typing import Iterable, Optional

from polyxrd.models.phase import Phase
from polyxrd.models.search_options import SearchOptions
from polyxrd.utils.formula_parser import (
    elements_match_filter,
    parse_formula_detailed,
)

AVOGADRO = 6.02214076e23

# 标准原子量 (IUPAC 2021, 常规地质样品区间取单一值), g/mol
ATOMIC_MASSES: dict[str, float] = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974,
    "S": 32.06, "Cl": 35.45, "Ar": 39.948, "K": 39.098, "Ca": 40.078,
    "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904,
    "Kr": 83.798, "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224,
    "Nb": 92.906, "Mo": 95.95, "Tc": 98.0, "Ru": 101.07, "Rh": 102.91,
    "Pd": 106.42, "Ag": 107.87, "Cd": 112.41, "In": 114.82, "Sn": 118.71,
    "Sb": 121.76, "Te": 127.60, "I": 126.90, "Xe": 131.29, "Cs": 132.91,
    "Ba": 137.33, "La": 138.91, "Ce": 140.12, "Pr": 140.91, "Nd": 144.24,
    "Pm": 145.0, "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93,
    "Dy": 162.50, "Ho": 164.93, "Er": 167.26, "Tm": 168.93, "Yb": 173.05,
    "Lu": 174.97, "Hf": 178.49, "Ta": 180.95, "W": 183.84, "Re": 186.21,
    "Os": 190.23, "Ir": 192.22, "Pt": 195.08, "Au": 196.97, "Hg": 200.59,
    "Tl": 204.38, "Pb": 207.2, "Bi": 208.98, "Th": 232.04, "U": 238.03,
}


def formula_mass(formula: str) -> Optional[float]:
    """化学式摩尔质量 (g/mol)。解析失败/空式返回 None。

    支持括号/小数系数 (与 parse_formula_detailed 同一套语法)。
    """
    try:
        comp = parse_formula_detailed(formula or "")
    except Exception:  # noqa: BLE001 - 畸形化学式按无法计算处理
        return None
    if not comp:
        return None
    total = 0.0
    for el, n in comp.items():
        m = ATOMIC_MASSES.get(el)
        if m is None:
            return None  # 未知元素 (同位素记号等) → 不可信
        total += m * n
    return total if total > 0 else None


def estimate_density(phase: Phase, z: int = 1) -> Optional[float]:
    """由晶胞体积 + 化学式估算理论密度 ρ = z·M / (N_A·V)。

    Args:
        phase: 需带 lattice (Å) 与可解析 formula。
        z: 每晶胞化学式单元数。库内未存 Z 时默认 1 —— 即**下限估计**
           (真实密度 = z 倍), 用于密度过滤时调用方应意识到这一点。

    Returns:
        g/cm³; 缺晶胞/化学式不可解析/体积非法 → None
    """
    lat = phase.lattice
    if lat is None:
        return None
    a, b, c = lat.a, lat.b, lat.c
    al, be, ga = lat.alpha, lat.beta, lat.gamma
    if not all(v and v > 0 for v in (a, b, c)):
        return None
    # 晶胞体积 (通用三斜公式, 对各晶系均成立)
    ca, cb, cg = (math.cos(math.radians(x)) for x in (al, be, ga))
    vol = a * b * c * (
        1 - ca**2 - cb**2 - cg**2
        + 2 * ca * cb * cg
    ) ** 0.5
    if vol <= 0:
        return None
    m = formula_mass(phase.formula)
    if m is None:
        return None
    return z * m / (AVOGADRO * vol * 1e-24)  # Å³ → cm³


def effective_density(phase: Phase) -> Optional[float]:
    """物相有效密度: 库存实测值 (phase.density) 优先, 否则 Z=1 估算。"""
    if phase.density and phase.density > 0:
        return float(phase.density)
    return estimate_density(phase)


def _name_matches(name: str, pattern: str) -> bool:
    """通配符 (fnmatch) 或子串匹配; 通配与非通配均不区分大小写。

    注意: 带通配符的 pattern (如 "*Corundum*") 在 fnmatchcase 下是
    大小写敏感的 → 对小写化后的两侧再做一次 fnmatch, 保证
    name_pattern="*corundum*" 也能命中 "Corundum"。
    """
    if not pattern:
        return True
    if any(ch in pattern for ch in "*?"):
        if fnmatch.fnmatchcase(name, pattern):
            return True
        return fnmatch.fnmatchcase(name.lower(), pattern.lower())
    return pattern.lower() in name.lower()


def _passes_density(phase: Phase, density_range) -> bool:
    if not density_range:
        return True
    lo, hi = float(density_range[0]), float(density_range[1])
    d = effective_density(phase)
    if d is None:
        return True  # 无密度信息 → 放行 (宁多勿漏)
    return lo <= d <= hi


def apply_restraints(phases: Iterable[Phase], opts: SearchOptions) -> list[Phase]:
    """元素 + 名称 + 密度综合过滤 (M09)。

    元素语义与 foam._passes_options 完全一致 (must_have/must/maybe/exclude);
    密度用 effective_density (库存值优先, Z=1 估算兜底, 无法取值放行)。
    """
    out: list[Phase] = []
    for p in phases:
        if opts.name_pattern and not _name_matches(p.name or "", opts.name_pattern):
            continue
        if not elements_match_filter(
            p.elements or set(),
            has=opts.must,
            maybe=opts.maybe,
            exclude=opts.exclude,
            must_have=opts.must_have,
        ):
            continue
        if not _passes_density(p, opts.density_range):
            continue
        out.append(p)
    return out


def find_phases_direct(
    query: str,
    phases: Iterable[Phase],
    max_results: Optional[int] = None,
) -> list[Phase]:
    """名称/化学式模糊直搜 (等价 Find phases/entries 直搜)。

    规则 (不区分大小写):
      - query 含通配符 (* ?) 时按 fnmatch 匹配名称与化学式
      - 否则做子串匹配, 排序: 名称前缀 > 名称子串 > 化学式子串,
        同级按名称字母序
    Args:
        query: 搜索词, 如 "corundum" / "*quartz*" / "SiO2"
        phases: 候选物相集合 (调用方决定库范围: 内置库/用户库/COD 检索结果)
        max_results: 返回条数上限 (None = 不限)
    """
    q = (query or "").strip()
    if not q:
        return []
    q_low = q.lower()
    has_wild = any(ch in q for ch in "*?")

    hits: list[tuple[int, str, Phase]] = []
    for p in phases:
        name = p.name or ""
        formula = p.formula or ""
        if has_wild:
            if fnmatch.fnmatch(name.lower(), q_low) or \
                    fnmatch.fnmatch(formula.lower(), q_low):
                hits.append((1, name.lower(), p))
            continue
        if name.lower().startswith(q_low):
            hits.append((0, name.lower(), p))
        elif q_low in name.lower():
            hits.append((1, name.lower(), p))
        elif q_low in formula.lower():
            hits.append((2, name.lower(), p))

    hits.sort(key=lambda t: (t[0], t[1]))
    out = [t[2] for t in hits]
    if max_results is not None:
        out = out[:max_results]
    return out


# ─────────────────────────────────────────────────────────────
# 预设存取 (~/.polyxrd/search_presets.json, 增量合并)
# ─────────────────────────────────────────────────────────────

def _presets_file() -> Path:
    return Path.home() / ".polyxrd" / "search_presets.json"


def _load_presets() -> dict:
    f = _presets_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_preset(name: str, opts: SearchOptions) -> Path:
    """保存/覆盖一个搜索预设。返回预设文件路径。"""
    data = _load_presets()
    data[name] = _opts_to_dict(opts)
    f = _presets_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return f


def load_preset(name: str) -> Optional[SearchOptions]:
    """读取预设; 不存在返回 None。损坏条目返回 None (不抛)。"""
    data = _load_presets()
    raw = data.get(name)
    if not isinstance(raw, dict):
        return None
    return _opts_from_dict(raw)


def list_presets() -> list[str]:
    return sorted(_load_presets().keys())


def delete_preset(name: str) -> bool:
    data = _load_presets()
    if name not in data:
        return False
    del data[name]
    f = _presets_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return True


def _opts_to_dict(opts: SearchOptions) -> dict:
    import dataclasses
    d = dataclasses.asdict(opts)
    # tuple → list 以便 JSON 序列化 (load 时还原为 tuple)
    if isinstance(d.get("density_range"), (tuple, list)):
        d["density_range"] = list(d["density_range"])
    return d


def _opts_from_dict(raw: dict) -> SearchOptions:
    allowed = {f for f in SearchOptions.__dataclass_fields__}
    kwargs = {k: v for k, v in raw.items() if k in allowed}
    if isinstance(kwargs.get("density_range"), (list, tuple)) \
            and len(kwargs["density_range"]) == 2:
        kwargs["density_range"] = tuple(kwargs["density_range"])
    return SearchOptions(**kwargs)
