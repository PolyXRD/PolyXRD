"""
参考库管理 / 用户库 (M12, Sprint 3)
===================================
UserDatabase: 用户物相库 (json 存储, Phase 条目增删改查)
import_from_cif: CIF → Phase (晶胞/原子位点 + pymatgen 参考峰)
import_diffraction_peaks: d/I 或 2θ/I 峰表 → Phase
check_formula_sum / export_entry / shift_reference_database
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

import numpy as np

from polyxrd.models.phase import Phase, LatticeParams
from polyxrd.utils.formula_parser import parse_formula, parse_formula_detailed


class UserDatabase:
    """JSON 文件承载的用户物相库。

    entries 为 Phase 列表; save/load 幂等; 不触碰 COD/内置库。
    """

    def __init__(self, path: Optional[Union[str, Path]] = None) -> None:
        self._path = Path(path) if path else None
        self.entries: list[Phase] = []
        if self._path and self._path.exists():
            self.load(self._path)

    # ── 持久化 ───────────────────────────────────────────────

    def save(self, path=None) -> None:
        p = Path(path) if path else self._path
        if p is None:
            raise ValueError("未指定保存路径")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    def load(self, path=None) -> None:
        p = Path(path) if path else self._path
        if p is None or not p.exists():
            raise FileNotFoundError(f"数据库不存在: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.from_dict(data)

    def to_dict(self) -> dict:
        return {"app": "polyxrd", "kind": "user_database", "version": "1.0",
                "entries": [ph.to_dict() for ph in self.entries]}

    def from_dict(self, data: dict) -> None:
        self.entries = [Phase.from_dict(d) for d in data.get("entries", [])]

    # ── 条目操作 ─────────────────────────────────────────────

    def add_phase(self, phase: Phase, replace_same_name: bool = False) -> int:
        """新增条目。replace_same_name=True 时同名覆盖。返回索引。"""
        if replace_same_name and phase.name:
            for i, p in enumerate(self.entries):
                if p.name == phase.name:
                    self.entries[i] = phase
                    return i
        self.entries.append(phase)
        return len(self.entries) - 1

    def remove_phase(self, index=None, name: Optional[str] = None) -> bool:
        if name is not None:
            idxs = [i for i, p in enumerate(self.entries) if p.name == name]
            if idxs:
                self.entries.pop(idxs[0])
                return True
            return False
        if index is not None and 0 <= index < len(self.entries):
            self.entries.pop(index)
            return True
        return False

    def update_phase(self, index: int, phase: Phase) -> None:
        if not (0 <= index < len(self.entries)):
            raise IndexError(f"索引越界: {index}")
        self.entries[index] = phase

    def find(self, formula: Optional[str] = None,
             elements: Optional[list] = None,
             name: Optional[str] = None,
             name_contains: Optional[str] = None) -> list[Phase]:
        """按公式/元素(须含全部)/名称(精确或包含)线性过滤。"""
        out = []
        for p in self.entries:
            if formula and p.formula != formula:
                continue
            if elements and not set(elements).issubset(p.elements or set()):
                continue
            if name and p.name != name:
                continue
            if name_contains and (name_contains.lower() not in
                                  (p.name or "").lower()):
                continue
            out.append(p)
        return out

    # ── 导出 ─────────────────────────────────────────────────

    def export_entry(self, target, out_path, fmt: str = "json") -> Path:
        """导出单条目: fmt=json|txt(峰表 2θ/I)。target 为索引或名称。"""
        if isinstance(target, str):
            hits = self.find(name=target)
            if not hits:
                raise KeyError(f"未找到条目: {target}")
            phase = hits[0]
        else:
            if not (0 <= int(target) < len(self.entries)):
                raise IndexError(f"索引越界: {target}")
            phase = self.entries[int(target)]
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            with open(p, "w", encoding="utf-8") as f:
                json.dump(phase.to_dict(), f, ensure_ascii=False, indent=1)
        elif fmt in ("txt", "peaks"):
            with open(p, "w", encoding="utf-8") as f:
                for _, tt, i in phase.get_reference_peaks():
                    f.write(f"{tt:.4f}\t{i:.1f}\n")
        else:
            raise ValueError(f"不支持的导出格式: {fmt}")
        return p


# ─────────────────────────────────────────────────────────────
# CIF 导入 / 工具函数
# ─────────────────────────────────────────────────────────────

def import_from_cif(
    cif_path,
    wavelength: float = 1.5406,
    two_theta_range=(10.0, 90.0),
) -> Phase:
    """解析 CIF 为 Phase (晶胞/原子位点 + pymatgen 计算参考峰)。

    依赖 pymatgen (已安装)。返回的 Phase 含 reference_peaks,
    可直接用于匹配与精修 (导出 CIF 供外部 Rietveld 时用 export_cif)。
    """
    from pymatgen.core import Structure
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    s = Structure.from_file(str(cif_path))
    lat = s.lattice
    formula = s.composition.reduced_formula
    try:
        sg = s.get_space_group_info()[0]
    except Exception:
        sg = ""
    sites = []
    for site in s:
        el = site.specie.symbol if hasattr(site, "specie") else \
            str(site.species_string).split("+")[0]
        frac = site.frac_coords
        sites.append({"label": el + str(len(sites) + 1), "element": el,
                      "x": float(frac[0]), "y": float(frac[1]),
                      "z": float(frac[2]),
                      "occupancy": float(getattr(site, "occupancy", 1.0))})
    calc = XRDCalculator(wavelength=wavelength)
    pat = calc.get_pattern(s, two_theta_range=tuple(two_theta_range))
    refs = []
    for i in range(len(pat.x)):
        hkl_info = pat.hkls[i] if i < len(pat.hkls) else []
        hkl = (0, 0, 0)
        if hkl_info and isinstance(hkl_info[0], dict):
            raw = hkl_info[0].get("hkl", (0, 0, 0))
            hkl = tuple(int(v) for v in raw[:3]) if len(raw) >= 3 else (0, 0, 0)
        refs.append((hkl, float(pat.x[i]), float(pat.y[i])))
    return Phase(
        name=f"{formula} (CIF)",
        formula=formula,
        space_group=sg,
        lattice=LatticeParams(a=float(lat.a), b=float(lat.b), c=float(lat.c),
                              alpha=float(lat.alpha), beta=float(lat.beta),
                              gamma=float(lat.gamma)),
        atomic_sites=sites,
        reference_peaks=refs,
        elements=set(parse_formula(formula)),
        cif_path=str(cif_path),
    )


def check_formula_sum(phase: Phase) -> bool:
    """化学式合法性: 能解析、无非正/非法元素、原子总数 > 0。"""
    formula = (phase.formula or "").strip()
    if not formula:
        return False
    try:
        counts = parse_formula_detailed(formula)
    except Exception:
        return False
    if not counts:
        return False
    return all(v > 0 for v in counts.values())


def import_diffraction_peaks(
    phase: Phase,
    peak_file,
    wavelength: float = 1.5406,
    angle: str = "auto",
) -> Phase:
    """从文本 (2θ I) 或 (d I) 峰表填充 phase.reference_peaks。

    angle: "2theta" | "d" | "auto"
      auto: 值域主要在 [3,120] 且递增 → 2θ; 若呈递减且值 < 40 视为 d。
    """
    rows = []
    # v1.1.1: utf-8-sig。用 utf-8 读带 BOM 的峰表时首行会变成 "\ufeff10.5", float()
    # 抛 ValueError 被下面的 continue 吞掉 —— 症状是"第一个峰凭空消失"。
    with open(peak_file, "r", encoding="utf-8-sig", errors="ignore") as f:
        for ln in f:
            parts = ln.replace(",", " ").split()
            try:
                vals = [float(t) for t in parts]
            except ValueError:
                continue
            if len(vals) >= 2:
                rows.append((vals[0], vals[1]))
    if not rows:
        raise ValueError(f"峰表无有效数据: {peak_file}")
    col0 = np.array([r[0] for r in rows])
    if angle == "auto":
        mono = bool(np.all(np.diff(col0) > 0))
        if np.max(col0) < 40.0 and (not mono or np.mean(np.diff(col0)) < 0):
            mode = "d"        # 递减的 d 序列
        else:
            mode = "2theta"
    else:
        mode = angle

    refs = []
    for x0, i in rows:
        if mode == "d":
            sin_t = wavelength / (2.0 * x0) if x0 > 0 else 2.0
            if not (0 < sin_t <= 1.0):
                continue
            tt = float(np.degrees(2.0 * np.arcsin(sin_t)))
        else:
            tt = float(x0)
        refs.append(((0, 0, 0), round(tt, 4), float(i)))
    refs.sort(key=lambda r: r[1])
    phase.reference_peaks = refs
    return phase


def shift_reference_database(db: UserDatabase, dz: float) -> UserDatabase:
    """整库参考峰 2θ 偏移 dz (返回新库, 不改原库)。"""
    import copy
    out = UserDatabase()
    for ph in db.entries:
        np_ = copy.deepcopy(ph)
        np_.reference_peaks = [
            (tuple(h), round(float(tt) + float(dz), 4), float(i))
            for h, tt, i in ph.get_reference_peaks()
        ]
        out.entries.append(np_)
    return out
