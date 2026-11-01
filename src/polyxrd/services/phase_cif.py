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

import numpy as np

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


_BLOCK_NAME_BAD = re.compile(r"[^A-Za-z0-9_.+-]+")


def _safe_block_name(name: object) -> str:
    """``phase.name`` → 合法的 CIF ``data_`` 块名。

    **为什么必须清洗** (v5.0.1 修复): CIF 的 ``data_`` 后只能跟**一个非空白
    token**, 而 PolyXRD 的相名普遍带空格/括号 (``"Zincite - O Zn (COD 9004180)"``)。
    写成 ``data_Zincite - O Zn (COD 9004180)`` 后 PyCifRW 在 char13 处直接报
    ``Star Format error``, GSAS-II 的 ``G2ImportException: No reader could read
    file`` 即源于此 —— 与空间群/位点语义无关，纯粹是块名不合法。
    """
    s = _BLOCK_NAME_BAD.sub("_", str(name or "")).strip("_.")
    if not s:
        s = "phase"
    if s[0].isdigit():
        s = "p" + s
    return s


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


def space_group_ops(space_group: object) -> Optional[list]:
    """空间群符号 → 对称操作列表；**解析不出时返回 ``None``**。

    与 :func:`expand_sites_by_symmetry` 共用同一套符号清洗（剥 setting 后缀
    ``:H`` / ``:R``、去空格：``R -3 c :H`` → ``R-3c``）。

    为什么单独暴露：展开函数对"解析失败"是**原样返回**，调用方看不出
    "本来就是全胞"与"展不开"的区别 —— v4.4.0 验收里 polyDB 的
    ``_expanded_sites`` 正是因此把非对称单位当全胞用了（真实库
    555/77,500 条目命中）。需要区分时先用本函数探路。
    """
    sg_raw = str(space_group or "").strip()
    if not sg_raw:
        return None
    sg_clean = re.sub(r"\s*:\s*[A-Za-z0-9]{1,2}$", "", sg_raw)
    sg_clean = re.sub(r"\s+", "", sg_clean)
    if not sg_clean:
        return None
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        return list(SpaceGroup(sg_clean).symmetry_ops)
    except Exception:  # noqa: BLE001 - 符号认不出 → 交给调用方决定
        return None


def expand_sites_by_symmetry(sites: list[dict], space_group: object,
                             max_sites: int = 2000,
                             strict: bool = False) -> Optional[list[dict]]:
    """把非对称单元位点按空间群对称操作展开成完整晶胞内容 (P1 全胞).

    **为什么需要** (v0.15.2 修复): COD CIF 的原子环一般只列非对称单元,
    依赖空间群对称操作生成全胞。而位点解析 (``cif_utils.parse_atom_sites_from_cif``)
    只取原始非对称单元、``phase_to_cif_text`` 反生成 CIF 时也按 P1 处理 —— 高对称
    结构 (如 R-3c 方解石, 非对称单元仅 3 位点) 的模拟峰会整体错误
    (104 特征峰缺失、假峰出现在 5.18°), 导致精修权重塌缩 (2-1 实测
    wR 卡 40%, 修复后预期 ≤20%)。

    **幂等安全**: 若传入的位点已是完整晶胞, 完整轨道在对称群作用下映射回
    自身 (去重后不变), 因此对"是否已展开"未知的位点无条件调用是安全的。

    :param strict: ``False`` (默认) 时, 空间群缺失 / 解析失败 / P1 / 位点脏数据
        / 保险丝触发都**原样返回** (行为不劣化, 老调用方无需改动)。
        ``True`` 时, **只有**"该空间群本来就无操作可展" (P1 / C1 / 空位点) 才返回
        原样列表, 其余降级路径一律返回 ``None`` —— 让调用方能区分
        "本来就是全胞" 与 "展不开", 避免把非对称单位当全胞用 (v4.1.1 假峰事故)。

        注意 ``strict=True`` 下 ``space_group`` 为空 / 认不出也算"展不开" →
        ``None``: 调用方拿不到空间群就不该假设位点是全胞。
    """
    import numpy as np

    out_sites = list(sites) if sites else []
    if not out_sites:
        return out_sites
    ops = space_group_ops(space_group)
    if ops is None:  # 空间群缺失 / 符号认不出 → 不展开（原样返回）
        return None if strict else out_sites
    if len(ops) <= 1:  # P1 / C1 无对称操作 → 位点本身就是全胞
        return out_sites

    expanded: list[dict] = []
    # v0.15.2 性能修复: 去重由"逐点线性扫描 _frac_close"改为"按元素分组的
    # 向量化矩阵比较"。原实现对大晶胞×高对称群 (数百位点 × ~192 操作 →
    # ~10 万生成点, 每点与最多 2000 个已展开点逐一比较) 是 O(10^8) 级
    # 纯 Python 热点, 实测 4-1 样品 Fluorite 大胞候选卡死 >12min。
    if len(out_sites) * len(ops) > 500_000:  # 病态输入保险丝
        return None if strict else out_sites
    tol = 1e-3
    mat_by_elem: dict[str, "np.ndarray"] = {}
    for s in out_sites:
        try:
            base = np.array([float(s["x"]), float(s["y"]), float(s["z"])])
            elem = str(s.get("element") or _element_from_label(
                str(s.get("label") or "")))
            occ = float(s.get("occupancy", 1.0) or 1.0)
        except (TypeError, ValueError, KeyError):
            return None if strict else out_sites  # 脏位点 → 放弃展开, 保持旧行为
        if not elem:
            return None if strict else out_sites
        # float('NaN') / float('inf') 能毫发无损地过 float()，但会把整个展开
        # 结果污染成 NaN 坐标（去重的 |Δ|<tol 比较对 NaN 恒为 False，36 个
        # 假位点全被保留）。2026-10-27 再验收实测。
        if not (bool(np.isfinite(base).all()) and bool(np.isfinite(occ))):
            return None if strict else out_sites
        mat = mat_by_elem.get(elem)
        for op in ops:
            p = np.asarray(op.operate(base), dtype=float)
            p = p - np.floor(p)
            p = np.where(p < 0, p + 1.0, p)
            # 浮点回绕到 1-1e-16 的坐标会写成 "1.0000"(等价位置但读起来像越界),
            # 且会让下游按坐标比对的逻辑把 x=1.0 与 x=0.0 判成不同点。
            p = np.where(p > 1.0 - 1e-6, 0.0, p)
            if mat is not None and mat.shape[0]:
                d = np.abs(mat - p)
                d = np.minimum(d, 1.0 - d)
                if bool(np.any(np.all(d < tol, axis=1))):
                    continue  # 轨道重复点
            expanded.append({"_elem": elem, "_c": p, "_occ": occ})
            mat = np.vstack((mat, p)) if mat is not None else p.reshape(1, 3)
            mat_by_elem[elem] = mat

    if not expanded or len(expanded) > max_sites:
        # 异常膨胀 → 放弃展开（strict 下报"展不开"，不把非对称单位当全胞）
        return None if strict else out_sites
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


def _site_element(site: dict) -> str:
    return str(site.get("element") or _element_from_label(str(site.get("label") or "")))


def reduce_sites_to_asymmetric(
    sites: list[dict], space_group: object, tol: float = 1e-3
) -> Optional[list[tuple[dict, int]]]:
    """完整晶胞位点 → 非对称单位 ``[(site, 多重度)]``；归并不可信时返回 ``None``。

    **为什么必须归并** (v5.0.1, GSAS-II 定量硬前提): GSAS-II 的 CIF 读取把
    原子表当作**非对称单位**，再按空间群生成整个轨道，胞内质量按
    ``Σ 质量·占有率·多重度`` 累计 (``GSASIIstrIO.GetPhaseData``)。若 CIF 里
    已写全胞 (如 ZnO 的 4 条) 却仍声明 ``P 6_3 m c``，GSAS-II 会把每条再乘
    多重度 2 → 胞内原子数翻倍 → 结构因子与相质量同时错，wt% 系统性偏移。

    归并规则: 逐元素在剩余位点中查"该位点的完整轨道"；轨道必须**全部存在**
    且占有率一致才收下 (多重度 = 轨道里不同位点数)，否则返回 ``None``
    (宁可退回 P1 全胞，也不赌)。

    调用方应用 :func:`_same_site_set` 把返回值再展开一次，与原全胞位点比对。
    """
    ops = space_group_ops(space_group)
    if ops is None or len(ops) <= 1:
        return None
    if not sites:
        return None
    import numpy as np

    pos = np.zeros((len(sites), 3), dtype=float)
    occ = np.zeros(len(sites), dtype=float)
    elems: list[str] = []
    for i, s in enumerate(sites):
        try:
            pos[i] = (float(s["x"]), float(s["y"]), float(s["z"]))
            occ[i] = float(s.get("occupancy", 1.0) or 1.0)
        except (TypeError, ValueError, KeyError):
            return None
        e = _site_element(s)
        if not e or not bool(np.isfinite(pos[i]).all()):
            return None
        elems.append(e)

    idx_by_elem: dict[str, list[int]] = {}
    for i, e in enumerate(elems):
        idx_by_elem.setdefault(e, []).append(i)

    used = np.zeros(len(sites), dtype=bool)
    out: list[tuple[dict, int]] = []
    for i in range(len(sites)):
        if used[i]:
            continue
        e = elems[i]
        pool = [j for j in idx_by_elem[e] if not used[j]]
        orbit: list[int] = []
        for op in ops:
            q = np.asarray(op.operate(pos[i]), dtype=float)
            q = q - np.floor(q)
            d = np.abs(pos[pool] - q)
            d = np.minimum(d, 1.0 - d)
            hits = [pool[k] for k in np.nonzero(np.all(d < tol, axis=1))[0]]
            if not hits:
                return None  # 轨道不闭合 → 位点集与空间群不自洽
            fresh = [j for j in hits if not used[j] and j not in orbit]
            if not fresh:
                continue  # 该操作把位点映回轨道内已有原子 (特殊位置)
            j = fresh[0]
            if abs(occ[j] - occ[i]) > 1e-3:
                return None  # 轨道内占有率不一致 (掺杂/占位无序) → 不敢归并
            orbit.append(j)
        for j in orbit:
            used[j] = True
        # 多重度 = 轨道里不同位点数 (identity 操作已把 i 本身收进 orbit)
        out.append((sites[i], max(1, len(orbit))))
    return out


def _same_site_set(a: list[dict], b: list[dict], tol: float = 1e-3) -> bool:
    """两个位点集合是否逐元素一一对应 (周期性距离, 贪心配对)。"""
    if a is None or b is None or len(a) != len(b):
        return False
    import numpy as np

    def _groups(sites: list[dict]) -> dict[str, "np.ndarray"]:
        g: dict[str, list[list[float]]] = {}
        for s in sites:
            g.setdefault(_site_element(s), []).append(
                [float(s.get("x", 0.0)), float(s.get("y", 0.0)), float(s.get("z", 0.0))]
            )
        return {k: np.asarray(v, dtype=float) for k, v in g.items()}

    ga, gb = _groups(a), _groups(b)
    if set(ga) != set(gb):
        return False
    for elem, pa in ga.items():
        pb = gb[elem]
        if pa.shape != pb.shape:
            return False
        free = np.ones(pb.shape[0], dtype=bool)
        for i in range(pa.shape[0]):
            cand = np.nonzero(free)[0]
            if cand.size == 0:
                return False
            d = np.abs(pb[cand] - pa[i])
            d = np.minimum(d, 1.0 - d)
            ok = cand[np.all(d < tol, axis=1)]
            if ok.size == 0:
                return False
            free[ok[0]] = False
    return True


def _formula_units_z(formula: str, full_sites: list[dict]) -> int:
    """由"全胞原子数 / 化学式原子数"反推 ``_cell_formula_units_Z``。

    GSAS-II 的相质量**不用** Z (它按位点×多重度累计)，但 Z 与原子数不符会
    让密度、``_chemical_formula_sum`` 自相矛盾，其他阅读器 (VESTA/FullProf)
    会据此算错。取各元素比值的最小整数；对不上就退回 1。
    """
    if not formula or not full_sites:
        return 1
    try:
        from polyxrd.utils.formula_parser import parse_formula_detailed

        per_cell: dict[str, float] = {}
        for s in full_sites:
            e = _site_element(s)
            if not e:
                continue
            per_cell[e] = per_cell.get(e, 0.0) + float(s.get("occupancy", 1.0) or 1.0)
        per_form = parse_formula_detailed(formula)
        if not per_cell or not per_form:
            return 1
        ratios = [per_cell[e] / n for e, n in per_form.items() if n > 0 and e in per_cell]
        if not ratios:
            return 1
        z = min(ratios)
        if z < 0.5 or any(abs(r - round(r)) > 0.1 for r in ratios):
            return 1
        return max(1, int(round(z)))
    except Exception:  # noqa: BLE001 - 化学式解析失败不该阻断 CIF 生成
        return 1


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
    lines.append(f"data_{_safe_block_name(phase.name)}")
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
    raw_sites = sites

    # v0.15.2: 非对称单元 → 完整晶胞 (幂等, 已展开的位点原样通过)。
    # 否则 pymatgen/GSAS-II/FullProf 按 P1 读取高对称结构会整体算错强度。
    if sites:
        sites = expand_sites_by_symmetry(sites, phase.space_group)

    # v5.0.1: 落盘形态改为"非对称单位 + 空间群", 而不是"全胞 + 原空间群"。
    # 全胞位点配高对称群会让 GSAS-II 再按多重度展开一次 (胞内原子翻倍),
    # 相质量 (Σ 质量·占有率·多重度) 与结构因子同时翻倍 → wt% 系统性偏移。
    # 归并结果一律做 "再展开 ↔ 原全胞" 闭环校验, 不自洽就退回 P1 + 全胞。
    emit: list[tuple[dict, int]] = [(s, 1) for s in sites]
    emit_sg = sg
    ops = space_group_ops(phase.space_group)
    if sites and ops is not None:
        reduced = reduce_sites_to_asymmetric(sites, phase.space_group)
        if reduced is not None and _same_site_set(
            expand_sites_by_symmetry([s for s, _ in reduced], phase.space_group),
            sites,
        ):
            emit = reduced
        else:
            emit_sg = "P 1"   # 归并不自洽 → 全胞 + P1 (不做二次展开, 语义无歧义)
    if emit_sg:
        lines.append(f"_space_group_name_H-M_alt '{emit_sg}'")
    lines.append(
        f"_cell_formula_units_Z {_formula_units_z(phase.formula, sites or [])}"
    )

    if emit:
        # 展开会重建位点字典 (丢掉 u_iso)，这里按"元素 + 同轨道"从原始位点找回，
        # 让 COD 给出的热参数作为 GSAS-II/MAUD 的初值而非一律 0.005。
        # 归并后的代表点常是原始位点的对称像 (如 (1/3,2/3,0)→(2/3,1/3,1/2))，
        # 所以必须比轨道、不能只比坐标。
        u_pool = [
            (_site_element(s), float(s["x"]), float(s["y"]), float(s["z"]),
             float(s["u_iso"]))
            for s in (raw_sites or [])
            if s.get("u_iso") and "x" in s
        ]

        def _u_iso_of(site: dict) -> float:
            elem = _site_element(site)
            try:
                p = np.asarray((float(site["x"]), float(site["y"]), float(site["z"])))
            except (KeyError, TypeError, ValueError):
                return 0.005
            for e, ux, uy, uz, u in u_pool:
                if e != elem:
                    continue
                base = np.asarray((ux, uy, uz))
                for op in (ops or [None]):
                    q = base if op is None else np.asarray(op.operate(base), dtype=float)
                    q = q - np.floor(q)
                    d = np.abs(q - p)
                    d = np.minimum(d, 1.0 - d)
                    if bool(np.all(d < 1e-3)):
                        return u
            return 0.005

        lines.append("loop_")
        lines.append("_atom_site_label")
        lines.append("_atom_site_type_symbol")
        lines.append("_atom_site_fract_x")
        lines.append("_atom_site_fract_y")
        lines.append("_atom_site_fract_z")
        lines.append("_atom_site_occupancy")
        lines.append("_atom_site_site_symmetry_multiplicity")
        lines.append("_atom_site_U_iso_or_equiv")
        for site, mult in emit:
            lbl = site.get("label") or ""
            elem = site.get("element") or _element_from_label(lbl) or "X"
            x = site.get("x", 0.0)
            y = site.get("y", 0.0)
            z = site.get("z", 0.0)
            occ = site.get("occupancy", 1.0)
            u_iso = site.get("u_iso") or _u_iso_of(site)
            label_str = lbl if lbl else "X1"
            lines.append(
                f"{label_str} {elem} {float(x):.6f} {float(y):.6f} {float(z):.6f} "
                f"{float(occ):.4f} {int(mult)} {u_iso:.4f}"
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