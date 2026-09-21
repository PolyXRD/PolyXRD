"""
Phase → CIF 生成器 (路线 B / R-B1)

把 PolyXRD :py:class:`polyxrd.models.phase.Phase` 对象序列化为标准 CIF 1.1
文本 (含晶胞、空间群、原子位点、占有率), 输出到 .cif 文件或字符串。

设计原则:
1. **CIF 1.1 兼容**: 字段名/语义符合 IUCr CIF 规范, 可被 MAUD / GSAS-II / FullProf / pymatgen 直接读取
2. **最少必要字段**: 仅写 Rietveld 精修所需字段 (data_global + cell + space group + atom loop);
   不写可有可无的 _refine_ls_*, _computing_* 等, 让接收方按需补
3. **位点格式**: ``_atom_site_label _atom_site_type_symbol _atom_site_fract_x/y/z _atom_site_occupancy``
   (MAUD 解析至少需要这 6 列; _B_iso_or_equiv 可选)
4. **回写兼容**: 同时支持把 ``Phase.atomic_sites`` 字典列表 (COD parse 格式) 写入; 缺元素自动从 label 前缀推断

参考:
- IUCr CIF 1.1 spec (data_/loop_/_atom_site_*)
- docs/MAUD批处理侦察报告.md §9.3 (动态 CIF 注入受 MAUD 限制, 必须先生成嵌入式的 par)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

from polyxrd.models.phase import Phase, LatticeParams


def _format_value(v) -> str:
    """CIF 值格式: 字符串加单引号, 数字裸值."""
    if isinstance(v, str):
        return f"'{v}'"
    if isinstance(v, (int, float)):
        if isinstance(v, int) or (isinstance(v, float) and v.is_integer()):
            return str(int(v))
        return f"{v:.4f}"
    return f"'{v}'"


def _space_group_to_hall_or_hm(phase: Phase) -> Optional[str]:
    """从 phase.space_group 提取出 Hermann-Mauguin 符号 (CIF 兼容).

    剥离 setting 后缀 (:H/:R/:P/:S/:1/:2 等) — MAUD 3 的空间群查找不认
    'P 63 m c :H' 这类带冒号记号, 会报 "No Space Group found for the name"。
    """
    sg = (phase.space_group or "").strip()
    if not sg:
        return None
    sg = re.sub(r"\s*:\s*[A-Za-z0-9]{1,2}\s*$", "", sg).strip()
    return sg or None


def _element_from_label(label: str) -> str:
    """从原子位点 label 推断元素符号.

    例: "Al1" → "Al", "O2" → "O", "Ca1a" → "Ca"
    空字符串 → "" (不允许猜 "X", 调用方决定 fallback)
    """
    s = label.strip()
    if not s:
        return ""
    m = re.match(r"([A-Z][a-z]?)", s)
    return m.group(1) if m else ""


def expand_sites_by_symmetry(sites: list[dict], space_group: object,
                             max_sites: int = 2000) -> list[dict]:
    """把非对称单元位点按空间群对称操作展开成完整晶胞内容 (P1 全胞).

    **为什么需要** (v0.15.2 修复): COD CIF 的原子环一般只列非对称单元,
    依赖空间群对称操作生成全胞。而 ``cod_local.get_phase`` 直建 pymatgen
    Structure、``phase_to_cif_text`` 反生成 CIF 时都按 P1 处理 —— 高对称
    结构 (如 R-3c 方解石, 非对称单元仅 3 位点) 的模拟峰会整体错误
    (104 特征峰缺失、假峰出现在 5.18°), 导致精修权重塌缩 (2-1 实测
    wR 卡 40%, 修复后预期 ≤20%)。

    **幂等安全**: 若传入的位点已是完整晶胞, 完整轨道在对称群作用下映射回
    自身 (去重后不变), 因此对"是否已展开"未知的位点无条件调用是安全的。

    空间群缺失 / 解析失败 / P1 / 位点脏数据时**原样返回** (行为不劣化)。
    """
    import numpy as np

    out_sites = list(sites) if sites else []
    if not out_sites:
        return out_sites
    sg_raw = str(space_group or "").strip()
    if not sg_raw:
        return out_sites
    # 剥 setting 后缀 (:H/:R/:1/:2 …) 并去空格 ("R -3 c :H" → "R-3c")
    sg_clean = re.sub(r"\s*:\s*[A-Za-z0-9]{1,2}$", "", sg_raw)
    sg_clean = re.sub(r"\s+", "", sg_clean)
    if sg_clean in ("P1", "C1"):  # P1 无对称操作
        return out_sites
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        ops = SpaceGroup(sg_clean).symmetry_ops
    except Exception:  # noqa: BLE001 - 空间群解析失败 → 不展开
        return out_sites
    if not ops or len(ops) <= 1:
        return out_sites

    expanded: list[dict] = []
    # v0.15.2 性能修复: 去重由"逐点线性扫描 _frac_close"改为"按元素分组的
    # 向量化矩阵比较"。原实现对大晶胞×高对称群 (数百位点 × ~192 操作 →
    # ~10 万生成点, 每点与最多 2000 个已展开点逐一比较) 是 O(10^8) 级
    # 纯 Python 热点, 实测 4-1 样品 Fluorite 大胞候选卡死 >12min。
    if len(out_sites) * len(ops) > 500_000:  # 病态输入保险丝
        return out_sites
    tol = 1e-3
    mat_by_elem: dict[str, "np.ndarray"] = {}
    for s in out_sites:
        try:
            base = np.array([float(s["x"]), float(s["y"]), float(s["z"])])
            elem = str(s.get("element") or _element_from_label(
                str(s.get("label") or "")))
            occ = float(s.get("occupancy", 1.0) or 1.0)
        except (TypeError, ValueError, KeyError):
            return out_sites  # 脏位点 → 放弃展开, 保持旧行为
        if not elem:
            return out_sites
        mat = mat_by_elem.get(elem)
        for op in ops:
            p = np.asarray(op.operate(base), dtype=float)
            p = p - np.floor(p)
            p = np.where(p < 0, p + 1.0, p)
            if mat is not None and mat.shape[0]:
                d = np.abs(mat - p)
                d = np.minimum(d, 1.0 - d)
                if bool(np.any(np.all(d < tol, axis=1))):
                    continue  # 轨道重复点
            expanded.append({"_elem": elem, "_c": p, "_occ": occ})
            mat = np.vstack((mat, p)) if mat is not None else p.reshape(1, 3)
            mat_by_elem[elem] = mat

    if not expanded or len(expanded) > max_sites:
        return out_sites  # 异常膨胀 → 放弃展开
    counters: dict[str, int] = {}
    result: list[dict] = []
    for o in expanded:
        counters[o["_elem"]] = counters.get(o["_elem"], 0) + 1
        result.append({
            "label": f"{o['_elem']}{counters[o['_elem']]}",
            "element": o["_elem"],
            "x": float(o["_c"][0]),
            "y": float(o["_c"][1]),
            "z": float(o["_c"][2]),
            "occupancy": o["_occ"],
        })
    return result


def phase_to_cif_text(phase: Phase) -> str:
    """生成 CIF 1.1 文本 (返回字符串). 不写盘, 由调用方负责.

    :param phase: PolyXRD Phase (须含 lattice; atomic_sites 可空, 自动从 elements 推)
    """
    if phase.lattice is None:
        raise ValueError(
            f"phase {phase.name!r} 没有 lattice, 无法生成 CIF"
        )
    lat = phase.lattice
    sg = _space_group_to_hall_or_hm(phase)

    lines: list[str] = []
    lines.append(f"data_{phase.name or 'phase'}")
    lines.append(f"_chemical_name_common '{phase.name}'")
    if phase.formula:
        lines.append(f"_chemical_formula_sum '{phase.formula}'")
    lines.append(f"_cell_length_a {lat.a:.4f}")
    lines.append(f"_cell_length_b {lat.b:.4f}")
    lines.append(f"_cell_length_c {lat.c:.4f}")
    lines.append(f"_cell_angle_alpha {lat.alpha:.4f}")
    lines.append(f"_cell_angle_beta {lat.beta:.4f}")
    lines.append(f"_cell_angle_gamma {lat.gamma:.4f}")
    try:
        vol = lat.volume
        lines.append(f"_cell_volume {vol:.3f}")
    except Exception:
        pass
    if sg:
        lines.append(f"_space_group_name_H-M_alt '{sg}'")
    lines.append("_cell_formula_units_Z 1")

    sites = list(phase.atomic_sites) if phase.atomic_sites else []
    if not sites and phase.elements:
        # 每个 unique element 用独立的计数 (O1, O2, Zn1, Zn2)
        elem_counter: dict[str, int] = {}
        for elem in sorted(phase.elements):
            elem_counter[elem] = elem_counter.get(elem, 0) + 1
            sites.append({
                "label": f"{elem}{elem_counter[elem]}",
                "element": elem,
                "x": 0.0, "y": 0.0, "z": 0.0,
                "occupancy": 1.0,
            })

    # v0.15.2: 非对称单元 → 完整晶胞 (幂等, 已展开的位点原样通过)。
    # 否则 pymatgen/GSAS-II/FullProf 按 P1 读取高对称结构会整体算错强度。
    if sites:
        sites = expand_sites_by_symmetry(sites, phase.space_group)

    if sites:
        lines.append("loop_")
        lines.append("_atom_site_label")
        lines.append("_atom_site_type_symbol")
        lines.append("_atom_site_fract_x")
        lines.append("_atom_site_fract_y")
        lines.append("_atom_site_fract_z")
        lines.append("_atom_site_occupancy")
        for site in sites:
            lbl = site.get("label") or ""
            elem = site.get("element") or _element_from_label(lbl) or "X"
            x = site.get("x", 0.0)
            y = site.get("y", 0.0)
            z = site.get("z", 0.0)
            occ = site.get("occupancy", 1.0)
            label_str = lbl if lbl else "X1"
            lines.append(
                f"{label_str} {elem} {float(x):.4f} {float(y):.4f} {float(z):.4f} {float(occ):.4f}"
            )

    return "\r\n".join(lines) + "\r\n"


def phase_to_cif_file(phase: Phase, dest: Union[str, Path]) -> Path:
    """写 CIF 到 dest. 父父目录自动建. 返回 dest 路径."""
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(phase_to_cif_text(phase), encoding="utf-8")
    return p


def cif_to_phase(cif_text: str, fallback_name: str = "phase") -> Phase:
    """从 CIF 文本反构 Phase (用于 cod_atomic_sites → Phase).

    这是 :py:func:`cod_local.parse_atom_sites_from_cif` 的更上层封装:
    - 同时解析晶胞/空间群/化学式
    - 把原子位点装到 Phase.atomic_sites

    :param cif_text: CIF 完整文本
    :param fallback_name: 当 CIF 无 _chemical_name_common 时使用
    """
    name = fallback_name
    formula = ""
    space_group = ""
    cell = LatticeParams()
    sites: list[dict] = []

    lines = cif_text.splitlines()
    in_atom_loop = False
    atom_cols: list[str] = []

    for raw_line in lines:
        s = raw_line.strip()
        if not s or s.startswith("#"):
            continue
        # loop_ 边界: 重置
        if s == "loop_":
            in_atom_loop = False
            atom_cols = []
            continue
        # _atom_site_* 列头 (累积到 atom_cols)
        if s.startswith("_atom_site_"):
            atom_cols.append(s)
            in_atom_loop = True
            continue
        # 数据行 (非 _ 开头, 在 atom loop 内)
        if not s.startswith("_") and in_atom_loop and atom_cols:
            parts = s.split()
            if len(parts) >= len(atom_cols):
                row = dict(zip(atom_cols, parts))
                lbl = row.get("_atom_site_label", "X1")
                elem = row.get("_atom_site_type_symbol") or _element_from_label(lbl)
                try:
                    sites.append({
                        "label": lbl,
                        "element": elem,
                        "x": float(row.get("_atom_site_fract_x", "0").split("(")[0]),
                        "y": float(row.get("_atom_site_fract_y", "0").split("(")[0]),
                        "z": float(row.get("_atom_site_fract_z", "0").split("(")[0]),
                        "occupancy": float(row.get("_atom_site_occupancy", "1").split("(")[0]),
                    })
                except ValueError:
                    pass
            continue
        # 跳出 atom loop: 遇到 _ 开头但不是 _atom_site_ → fallthrough 到单值字段
        if in_atom_loop and s.startswith("_"):
            in_atom_loop = False
            atom_cols = []
        # 单值字段
        if s.startswith("_chemical_name_common"):
            name = s.split(None, 1)[1].strip().strip("'\"") or name
        elif s.startswith("_chemical_formula_sum"):
            formula = s.split(None, 1)[1].strip().strip("'\"")
        elif s.startswith("_space_group_name_H-M_alt"):
            space_group = s.split(None, 1)[1].strip().strip("'\"")
        elif s.startswith("_cell_length_a"):
            try:
                cell.a = float(s.split()[1].split("(")[0])
            except (ValueError, IndexError):
                pass
        elif s.startswith("_cell_length_b"):
            try:
                cell.b = float(s.split()[1].split("(")[0])
            except (ValueError, IndexError):
                pass
        elif s.startswith("_cell_length_c"):
            try:
                cell.c = float(s.split()[1].split("(")[0])
            except (ValueError, IndexError):
                pass
        elif s.startswith("_cell_angle_alpha"):
            try:
                cell.alpha = float(s.split()[1].split("(")[0])
            except (ValueError, IndexError):
                pass
        elif s.startswith("_cell_angle_beta"):
            try:
                cell.beta = float(s.split()[1].split("(")[0])
            except (ValueError, IndexError):
                pass
        elif s.startswith("_cell_angle_gamma"):
            try:
                cell.gamma = float(s.split()[1].split("(")[0])
            except (ValueError, IndexError):
                pass

    return Phase(
        name=name,
        formula=formula,
        space_group=space_group,
        lattice=cell,
        atomic_sites=sites,
    )