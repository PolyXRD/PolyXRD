"""
MAUD 精修引擎包装 (路线 C R-C3 / R-C4)
=====================================

把 PolyXRD 的 ``refine(data, phases, engine='maud')`` 调用桥接到
``com.radiographema.MaudText`` 子进程。设计要点:

1. **数据转换**: ``data.two_theta`` + ``data.intensity`` → 临时 ``.xye`` (MAUD
   标准三列格式, 误差列用 Poisson 估计: σ = sqrt(I)).
2. **CIF 来源**: 优先 ``phase.cif_path`` (RietveldRefiner 调用方下推); 缺则
   跳过该相 (留给路线 B 接入结构生成)。
3. **进度**: Java stdout 8KB 不 flush, 所以 MAUD 跑时改用 .par 文件 mtime 轮询 +
   ``_refine_ls_R_factor_all`` 字段值变化驱动 ``on_progress`` 回调。
4. **结果回读**: .par 写完后 parse
   ``_refine_ls_R_factor_all`` / ``wR_factor_all`` / ``goodness_of_fit_all`` /
   ``number_iteration``, TSV 写完后 parse 每相 Vol% / Wt% / Cell_Par。
5. **失败处理**: 任一环节失败 (Java 缺、路径错、TSV 未生成) 都抛 ``MaudEngineError``,
   由 ``RietveldRefiner.refine()`` 兜底回内置引擎。

参考:
- docs/MAUD批处理侦察报告.md §5.1 / §8.1 / §8.6
- src/polyxrd/services/maud_par_builder.py (INS + 命令生成)
"""

from __future__ import annotations

import csv
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.maud_par_builder import (
    MaudInsArtifacts,
    MaudInsConfig,
    build_maud_command,
    cod_id_to_cif_path,
    detect_maud_root,
    get_default_template_path,
    write_ins_file,
)


logger = logging.getLogger(__name__)


class MaudEngineError(RuntimeError):
    """MAUD 引擎调用任一环节失败的统一异常类型 (供 RietveldRefiner 兜底回 builtin)"""


@dataclass
class MaudProgress:
    """MAUD 实时进度快照 (.par mtime 轮询 + R 字段解析)"""

    elapsed_seconds: float = 0.0
    rwp_percent: float = 0.0     # _refine_ls_R_factor_all (常规 R)
    wrp_percent: float = 0.0     # _refine_ls_wR_factor_all (加权 R, 主收敛指标)
    iterations: int = 0
    par_mtime: float = 0.0
    last_update: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "rwp_percent": self.rwp_percent,
            "wrp_percent": self.wrp_percent,
            "iterations": self.iterations,
            "par_mtime": self.par_mtime,
            "last_update": self.last_update,
            "note": self.note,
        }


# CIF data block 解析: 用于 TSV 中 Phase_Name 反查 lattice 时回写 cif 字段。
# MAUD 的 Phase_Name 在 TSV 里就是 import 时的 CIF 文件名去后缀.
_PHASE_NAME_FROM_CIF_RE = re.compile(r"data_([A-Za-z0-9_\-]+)")


def _format_xrd_data_as_xye(data: XRDData, dest: Path) -> Path:
    """把 PolyXRD XRDData 写成 MAUD 能吃的 .xye (三列: 2θ, I, σ).

    σ 列: Poisson sqrt(max(I, 0)) —— 对 X 射线计数数据合理; 缺 σ 时 MAUD 退回到
    sqrt(I) 内部补, 但显式写出会更稳。
    """
    two_theta = np.asarray(data.two_theta, dtype=float).ravel()
    intensity = np.asarray(data.intensity, dtype=float).ravel()
    if two_theta.size != intensity.size:
        raise MaudEngineError(
            f"data.two_theta 与 data.intensity 长度不一致: "
            f"{two_theta.size} vs {intensity.size}"
        )
    if two_theta.size == 0:
        raise MaudEngineError("data.two_theta 为空, 无可写数据")

    sigma = np.sqrt(np.maximum(intensity, 0.0))
    # MAUD .xye 默认分隔是空白/tab; 用 tab 更稳 (避免科学计数小数点被拆)
    # 注意: 不能写 '#' 注释头 — MAUD 的 ETH 三列读取器不跳过注释行,
    # 会把 '#' 当数值解析抛 NumberFormatException → 整个数据文件加载失败
    arr = np.column_stack([two_theta, intensity, sigma])
    np.savetxt(dest, arr, fmt="%.6f", delimiter="\t", comments="")
    return dest


def _parse_par_rfactors(par_path: Path) -> dict:
    """从 MAUD .par 里读出当前 R / wR / GOF / n_iter.

    解析策略: 逐行正则匹配 ``_refine_ls_*`` 字段。CIF 格式不严格, 这里容错。
    """
    out = {
        "rwp": None,
        "wrp": None,
        "gof": None,
        "iterations": None,
    }
    if not par_path.exists():
        return out
    pat = {
        "rwp": re.compile(r"^_refine_ls_R_factor_all\s+([0-9.eE+\-]+)", re.MULTILINE),
        "wrp": re.compile(r"^_refine_ls_wR_factor_all\s+([0-9.eE+\-]+)", re.MULTILINE),
        "gof": re.compile(r"^_refine_ls_goodness_of_fit_all\s+([0-9.eE+\-]+)", re.MULTILINE),
        "iterations": re.compile(r"^_refine_ls_number_iteration\s+([0-9]+)", re.MULTILINE),
    }
    try:
        text = par_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for key, p in pat.items():
        m = p.search(text)
        if m:
            try:
                out[key] = float(m.group(1)) if key != "iterations" else int(m.group(1))
            except ValueError:
                pass
    # MAUD .par 的 R 因子是小数 (0.5218 = 52.18%); 本模块统一用 % 单位
    # (MAUD2/3 的 results.tsv "Rwp(%)" 列同样为百分数, 两者已对表核实一致)
    for k in ("rwp", "wrp"):
        if out[k] is not None:
            out[k] = float(out[k]) * 100.0
    return out


def _parse_tsv_results(tsv_path: Path) -> list[dict]:
    """MAUD `_riet_append_result_to` TSV 解析 (R-C3 §8.5/§8.6 已采过格式).

    表头: ``Title Rwp(%) Phase_Name Vol.(%) error(%) Wt.(%) error(%)
           Cell_Par(Angstrom) Cell_Par(Angstrom) Size(Angstrom) Microstrain
           Phase_Name Vol.(%) error(%) Wt.(%) error(%) ...``

    每个 phase 占用 9 列: name, vol%, err_vol, wt%, err_wt, cell_a, cell_b,
    size, microstrain. Trigonal/hexagonal (Al2O3 案例) 只输出 a + c → 第 7 列
    是 c, 第 6 列是 a, cell_b 列实际不存在 (CSV 列数 = 8).

    返回每相 dict: name, vol_pct, wt_pct, cell_a, cell_b_or_c, size_a,
    microstrain, error_vol, error_wt.
    """
    if not tsv_path.exists():
        return []
    try:
        with tsv_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            rdr = csv.reader(f, delimiter="\t")
            rows = [r for r in rdr if r and any(c.strip() for c in r)]
    except OSError:
        return []
    if len(rows) < 2:
        return []
    header = [h.strip() for h in rows[0]]
    data_row = rows[1]

    # 找每个 phase 的 "Phase_Name" 列索引
    name_idx = [i for i, h in enumerate(header) if h == "Phase_Name"]
    if not name_idx:
        return []

    out: list[dict] = []
    for j, i in enumerate(name_idx):
        # 每相占 9 列 (name, vol%, err_vol, wt%, err_wt, cell_a, cell_b_or_c,
        # size, microstrain); 最后一个相可能缺列 (尾部空白)。
        # 安全起见, 显式按 header 解析。
        try:
            name = data_row[i].strip() if i < len(data_row) else ""
            vol_pct = _to_float(data_row, i + 1)
            err_vol = _to_float(data_row, i + 2)
            wt_pct = _to_float(data_row, i + 3)
            err_wt = _to_float(data_row, i + 4)
            cell_a = _to_float(data_row, i + 5)
            cell_b = _to_float(data_row, i + 6)
            size = _to_float(data_row, i + 7)
            strain = _to_float(data_row, i + 8)
        except (IndexError, ValueError):
            continue
        # 不完整行: 至少要有 name 和 (wt_pct 或 cell_a) 其一, 否则视为断尾
        if not name and wt_pct is None and cell_a is None:
            continue
        out.append({
            "name": name,
            "vol_pct": vol_pct,
            "error_vol": err_vol,
            "wt_pct": wt_pct,
            "error_wt": err_wt,
            "cell_a": cell_a,
            "cell_b_or_c": cell_b,
            "size_a": size,
            "microstrain": strain,
        })
    return out


def _to_float(row: list[str], idx: int) -> Optional[float]:
    if idx >= len(row):
        return None
    s = row[idx].strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _apply_tsv_to_phases(
    phases: list[Phase],
    tsv_entries: list[dict],
) -> None:
    """把 TSV 结果按 ``phase.name`` 匹配回写 ``weight_fraction`` + ``lattice``.

    匹配规则: TSV Phase_Name 与 phase.name 完全相等 (大小写不敏感); 否则
    按 CIF 文件名去后缀 vs phase.name. 不更新晶格 b/c 角度 (TSV 不报);
    仅在原晶格存在且 TSV cell_a 有效时改 a/c; 立方相只改 a.
    """
    by_name: dict[str, dict] = {}
    for entry in tsv_entries:
        nm = entry.get("name", "")
        by_name[nm.lower()] = entry
        # 也加一份去后缀的别名, 如 'corundum.cif' → 'corundum'
        bare = nm.rsplit(".", 1)[0] if "." in nm else nm
        by_name.setdefault(bare.lower(), entry)

    for phase in phases:
        key = phase.name.strip().lower()
        entry = by_name.get(key)
        if entry is None:
            # 尝试按 CIF 文件名回查
            if phase.cif_path:
                stem = Path(phase.cif_path).stem.lower()
                entry = by_name.get(stem)
        if entry is None:
            continue
        if entry.get("wt_pct") is not None:
            phase.weight_fraction = float(entry["wt_pct"])
        if phase.lattice is not None and entry.get("cell_a") is not None:
            # 先捕捉原晶格类型 (a, b, c, gamma), 再写入 a, 避免 mutate 后失真
            orig_a = phase.lattice.a
            orig_b = phase.lattice.b
            orig_gamma = phase.lattice.gamma
            new_a = float(entry["cell_a"])
            new_b_or_c = entry.get("cell_b_or_c")
            phase.lattice.a = new_a
            # 立方: a=b=c; 六方/三角: b=a, c=cell_b_or_c
            if new_b_or_c is not None:
                if (
                    abs(orig_b - orig_a) < 1e-9
                    and abs(phase.lattice.alpha - 90.0) < 1e-6
                    and abs(phase.lattice.beta - 90.0) < 1e-6
                    and abs(orig_gamma - 90.0) < 1e-6
                ):
                    # 立方相: a=b=c
                    phase.lattice.c = new_b_or_c
                elif (
                    abs(orig_b - orig_a) < 1e-9
                    and (abs(orig_gamma - 120.0) < 1e-6
                         or abs(orig_gamma - 60.0) < 1e-6)
                ):
                    # 六方/三角: b=a, c 是另一个 cell 参数
                    phase.lattice.c = new_b_or_c
                else:
                    # 正交: cell_b_or_c 是 b
                    phase.lattice.b = new_b_or_c


# =============================================================================
# refined.par 相定量解析 (MAUD3 批处理 TSV 不含相定量, 必须从 par 拿)
# =============================================================================

def _par_num(s: str) -> Optional[float]:
    """par 数值: '3.2465792(1.98E-4)' → 3.2465792 (剥不确定度括号)."""
    if s is None:
        return None
    s = re.sub(r"\([^)]*\)", "", s.strip())
    if s in ("", ".", "?"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_par_phases(par_path: Path) -> list[dict]:
    """从 refined.par 解析每相的 name / 体积分数 / 晶胞 / 胞内容质量.

    MAUD2/3 批处理 TSV (_riet_append_result_to) 只含 Title/Rwp 两列, 没有
    相定量行 (旧版 "每相 9 列" 的假设对两版都不成立, 已实测对表)。真实数据:
    - 相体积分数: 样品段 ``loop_ _pd_phase_atom_%`` (Layer.java 字典注释
      "phase scale factor / volume fraction", 精修值 0~1 归一);
    - 相名/晶胞/位点: ``#subordinateObject_<名>`` 相块中的
      ``_pd_phase_name`` / ``_cell_length_*`` / ``_atom_site_*`` +
      ``_atom_type_number_in_cell`` (胞内多重数)。

    返回每相 dict: name, vol_frac, cell_a/b/c, cell_weight (胞内容质量, Da),
    volume (A^3) — 足够换算 wt%: wt_i ∝ vol_frac_i·cell_weight_i/volume_i。
    """
    if not par_path.exists():
        return []
    try:
        text = par_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # 1) 相体积分数 (loop_ _pd_phase_atom_% 后的连续非空行)
    vol_fracs: list[float] = []
    m = re.search(r"loop_\s*\n_pd_phase_atom_%\s*\n((?:[^\n]*\n)+?)\s*\n", text)
    if m:
        for line in m.group(1).strip().splitlines():
            tok = line.split("#")[0].split()[0] if line.split("#")[0].split() else None
            v = _par_num(tok) if tok else None
            if v is not None:
                vol_fracs.append(v)

    # 2) 顺序扫描 subordinateObject 块: 相块 (_pd_phase_name + _cell_length_a)
    #    开启新相; 位点块 (_atom_site_label, 独立的 #subordinateObject_<label>)
    #    归属当前相。
    out: list[dict] = []
    for chunk in text.split("#subordinateObject_")[1:]:
        if "_pd_phase_name" in chunk and "_cell_length_a" in chunk:
            nm_m = re.search(r"_pd_phase_name\s+'([^']*)'", chunk)
            name = nm_m.group(1).strip() if nm_m else ""
            cell_a = _par_num(_tag_value(chunk, "_cell_length_a"))
            cell_b = _par_num(_tag_value(chunk, "_cell_length_b"))
            cell_c = _par_num(_tag_value(chunk, "_cell_length_c"))
            alpha = _par_num(_tag_value(chunk, "_cell_angle_alpha")) or 90.0
            beta = _par_num(_tag_value(chunk, "_cell_angle_beta")) or 90.0
            gamma = _par_num(_tag_value(chunk, "_cell_angle_gamma")) or 90.0
            volume = _cell_volume(cell_a, cell_b, cell_c, alpha, beta, gamma)
            out.append({
                "name": name,
                "vol_frac": None,      # 稍后按序对齐 atom_% 值
                "cell_a": cell_a,
                "cell_b": cell_b,
                "cell_c": cell_c,
                "cell_weight": 0.0,
                "volume": volume,
            })
            continue
        if "_atom_site_label" in chunk and out:
            # 位点块: 块头即 '#subordinateObject_Zn1'' 后的 "Zn1'"
            lab_m = re.match(r"\s*'?([A-Za-z]{1,3})\d*", chunk)
            if not lab_m:
                continue
            sym_m = re.match(r"[A-Z][a-z]?", lab_m.group(1))
            if not sym_m:
                continue
            n_in_cell = _par_num(_tag_value(chunk, "_atom_type_number_in_cell")) or 0.0
            occ = _par_num(_tag_value(chunk, "_atom_site_occupancy"))
            occ = 1.0 if occ is None else occ
            out[-1]["cell_weight"] += (
                _atomic_weight(sym_m.group(0)) * n_in_cell * occ
            )

    for entry in out:
        if entry["cell_weight"] <= 0:
            entry["cell_weight"] = None

    # 3) 按序对齐体积分数 (par 相块顺序 = 样品相表顺序)
    if vol_fracs and len(vol_fracs) == len(out):
        for entry, f in zip(out, vol_fracs):
            entry["vol_frac"] = f
    return out


def _tag_value(text: str, tag: str) -> Optional[str]:
    """取 'tag value' 行的 value 原文 (不含行内 # 注释)."""
    m = re.search(rf"^{re.escape(tag)}\s+([^#\n]+)", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _cell_volume(a, b, c, alpha, beta, gamma) -> Optional[float]:
    """晶胞体积 (A^3); 参数缺失返回 None."""
    if None in (a, b, c):
        return None
    import math
    ca, cb, cg = (math.cos(math.radians(x)) for x in (alpha, beta, gamma))
    v2 = 1 - ca * ca - cb * cb - cg * cg + 2 * ca * cb * cg
    if v2 <= 0:
        return None
    return a * b * c * math.sqrt(v2)


_ATOMIC_WEIGHTS_FALLBACK = {
    "H": 1.008, "C": 12.011, "N": 14.007, "O": 15.999, "Na": 22.990,
    "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06,
    "K": 39.098, "Ca": 40.078, "Ti": 47.867, "V": 50.942, "Cr": 51.996,
    "Mn": 54.938, "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546,
    "Zn": 65.38, "Zr": 91.224, "Ba": 137.327, "W": 183.84, "Pb": 207.2,
}


def _atomic_weight(symbol: str) -> float:
    try:
        from pymatgen.core.periodic_table import Element
        return float(Element(symbol).atomic_mass)
    except Exception:
        return _ATOMIC_WEIGHTS_FALLBACK.get(symbol, 0.0)


def _apply_par_to_phases(
    phases: list[Phase],
    par_entries: list[dict],
) -> bool:
    """把 par 相结果回写 phases: weight_fraction (wt%) + lattice a/b/c.

    wt% 换算: MAUD 精修的是体积分数 vol_frac (归一), 密度 ρ_i = cell_weight_i
    ×1.6605/volume_i, 故 wt_i ∝ vol_frac_i·cell_weight_i/volume_i (标准
    体积分数→质量分数换算, 与 MAUD GUI Phase analysis 面板一致)。

    返回 True 表示至少回写了一相。
    """
    if not par_entries:
        return False
    by_name: dict[str, dict] = {}
    for e in par_entries:
        nm = (e.get("name") or "").strip().lower()
        if nm:
            by_name[nm] = e

    matched = 0
    total_w = 0.0
    weights: list[Optional[float]] = []
    for phase in phases:
        key = phase.name.strip().lower()
        entry = by_name.get(key)
        if entry is None and phase.cif_path:
            entry = by_name.get(Path(phase.cif_path).stem.lower())
        if entry is None:
            weights.append(None)
            continue
        matched += 1
        # 晶胞
        if phase.lattice is not None:
            if entry.get("cell_a") is not None:
                phase.lattice.a = float(entry["cell_a"])
            if entry.get("cell_b") is not None:
                phase.lattice.b = float(entry["cell_b"])
            if entry.get("cell_c") is not None:
                phase.lattice.c = float(entry["cell_c"])
        # wt% 权重: vol_frac × cell_weight / volume
        w = None
        vf = entry.get("vol_frac")
        cw = entry.get("cell_weight")
        vol = entry.get("volume")
        if vf is not None and cw and vol:
            w = float(vf) * float(cw) / float(vol)
            total_w += w
        weights.append(w)

    if matched == 0 or total_w <= 0:
        return False
    for phase, w in zip(phases, weights):
        if w is not None:
            phase.weight_fraction = w / total_w * 100.0
    return True


# =============================================================================
# MaudEngine
# =============================================================================

class MaudEngine:
    """MAUD 批处理包装

    用法:
        engine = MaudEngine()           # 自动从 C:\\MAUD3 探测
        engine = MaudEngine(maud_root=Path(r"C:\\MAUD2"))
        result = engine.refine(data, phases, iterations=30)

    也可单独 :py:meth:`prepare_workdir` / :py:meth:`run` 用于 GUI 调试。
    """

    DEFAULT_ITERATIONS = 30
    DEFAULT_WIZARD_INDEX: Optional[int] = None  # None = MAUD 自動選 (-21 成熟)
    DEFAULT_MAX_MEMORY_MB = 4096
    DEFAULT_TIMEOUT_S = 600.0
    PROGRESS_POLL_INTERVAL_S = 1.5

    def __init__(
        self,
        maud_root: Optional[Path] = None,
        template_par: Optional[Path] = None,
    ) -> None:
        self.maud_root = Path(maud_root) if maud_root else detect_maud_root()
        if not (self.maud_root / "jdk" / "bin" / "java.exe").exists():
            raise MaudEngineError(
                f"MAUD 安装无效: {self.maud_root} 不含 jdk/bin/java.exe"
            )
        self.template_par = Path(template_par) if template_par else get_default_template_path()

    # ------------------------------------------------------------------
    # 公开: 进度 + 子进程
    # ------------------------------------------------------------------

    def prepare_workdir(
        self,
        data: XRDData,
        phases: list[Phase],
        iterations: Optional[int] = None,
        wizard_index: Optional[int] = None,
        work_dir: Optional[Path] = None,
        cod_root: Optional[Path] = None,
    ) -> MaudInsArtifacts:
        """准备临时工作目录 (写 .xye + 选 CIF + 生成 run.ins).

        返回 :py:class:`MaudInsArtifacts`, 供 :py:meth:`run` 使用。
        :param cod_root: 当 phase.cif_path 缺且 phase.cod_id 给出时, 用
            :py:func:`cod_id_to_cif_path` 自动映射 (路线 B 接口预留)。
        """
        if not phases:
            raise MaudEngineError("phases 不能为空 (MAUD 至少需一个相)")

        # 选 CIF 路径: phase.cif_path 优先; 其次 phase.cod_id 映射
        cif_paths: list[Path] = []
        for phase in phases:
            if phase.cif_path and Path(phase.cif_path).exists():
                cif_paths.append(Path(phase.cif_path))
            elif cod_root is not None and getattr(phase, "cod_id", None):
                p = cod_id_to_cif_path(int(phase.cod_id), cod_root)
                if p.exists():
                    cif_paths.append(p)
                else:
                    raise MaudEngineError(
                        f"phase {phase.name!r} 的 COD CIF 不存在: {p}"
                    )
            else:
                raise MaudEngineError(
                    f"phase {phase.name!r} 没有 CIF: 缺 cif_path 且无 cod_id; "
                    f"路线 B 接入后再支持 lattice 自生成"
                )

        # 写 .xye 数据
        wd = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="maud_engine_"))
        wd.mkdir(parents=True, exist_ok=True)
        xye_path = wd / "input.xye"
        _format_xrd_data_as_xye(data, xye_path)

        cfg = MaudInsConfig(
            template_par=self.template_par,
            data_file=xye_path,
            cif_paths=cif_paths,
            iterations=iterations or self.DEFAULT_ITERATIONS,
            wizard_index=wizard_index if wizard_index is not None else self.DEFAULT_WIZARD_INDEX,
            work_dir=wd,
        )
        return write_ins_file(cfg)

    def run(
        self,
        artifacts: MaudInsArtifacts,
        max_memory_mb: Optional[int] = None,
        timeout_s: Optional[float] = None,
        on_progress: Optional[Callable[[MaudProgress], None]] = None,
    ) -> subprocess.CompletedProcess:
        """同步执行 MAUD 子进程; 进度通过 .par 轮询触发 on_progress.

        返回 :py:class:`subprocess.CompletedProcess`. 调用方负责读 .par / TSV。
        """
        cmd = build_maud_command(
            self.maud_root,
            artifacts.ins_path,
            max_memory_mb=max_memory_mb or self.DEFAULT_MAX_MEMORY_MB,
        )
        env = os.environ.copy()
        # MAUD3 需要 cwd=安装根 (JNI lib); MAUD 子进程会自动切到 ins 所在目录
        # 处理 cif/data, 但 -DJava.library.path=. 已经指定安装根。
        # 这里设 cwd=work_dir 是为了相对路径解析 (fileToSave/append_result_to)。
        logger.info("MAUD cmd: %s", " ".join(cmd[:4]) + " ...")
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(artifacts.work_dir),
                capture_output=True,
                text=True,
                timeout=timeout_s or self.DEFAULT_TIMEOUT_S,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise MaudEngineError(
                f"MAUD 超时 ({timeout_s or self.DEFAULT_TIMEOUT_S}s)"
            ) from e
        except FileNotFoundError as e:
            raise MaudEngineError(
                f"MAUD 可执行文件不存在: {e}"
            ) from e

        # 跑完再额外轮询一次 on_progress (确保 GUI 拿到终态)
        if on_progress:
            rfactors = _parse_par_rfactors(artifacts.output_par_path)
            prog = MaudProgress(
                elapsed_seconds=time.time() - start,
                rwp_percent=float(rfactors.get("rwp") or 0.0),
                wrp_percent=float(rfactors.get("wrp") or 0.0),
                iterations=int(rfactors.get("iterations") or 0),
                par_mtime=artifacts.output_par_path.stat().st_mtime
                if artifacts.output_par_path.exists() else 0.0,
                last_update=time.time(),
                note="finished" if proc.returncode == 0 else f"exit={proc.returncode}",
            )
            try:
                on_progress(prog)
            except Exception:  # 进度回调不能影响主流程
                logger.exception("on_progress callback raised")

        if proc.returncode != 0:
            raise MaudEngineError(
                f"MAUD exit={proc.returncode}; "
                f"stderr={proc.stderr[:500] if proc.stderr else ''}"
            )
        return proc

    # ------------------------------------------------------------------
    # 公开: 端到端
    # ------------------------------------------------------------------

    def refine(
        self,
        data: XRDData,
        phases: list[Phase],
        iterations: Optional[int] = None,
        wizard_index: Optional[int] = None,
        max_memory_mb: Optional[int] = None,
        timeout_s: Optional[float] = None,
        keep_workdir: bool = False,
        on_progress: Optional[Callable[[MaudProgress], None]] = None,
        cod_root: Optional[Path] = None,
        work_dir: Optional[Path] = None,
        **kwargs,
    ) -> RefinementResult:
        """端到端: data + phases → RefinementResult.

        Args:
            data: XRD 实验数据
            phases: 待精修物相列表 (每相需有 cif_path 或 cod_id)
            iterations: MAUD 迭代上限 (默认 30)
            wizard_index: MAUD wizard 步; None=MAUD 自動選
            max_memory_mb: JVM 堆 (默认 4096)
            timeout_s: 子进程超时 (默认 600)
            keep_workdir: True 时不自动清理 work_dir (调试用)
            on_progress: 进度回调 (跑完后回调一次; GUI 异步时再用轮询变体)
            cod_root: COD 库根 (用 phase.cod_id 自动映射 CIF 时需)
            work_dir: 用户指定工作目录; 缺省时自动 mkdtemp
                (优先级最高, keep_workdir 仅控制 dir 是否会被外层清理)
            **kwargs: 透传给 builtin 兜底 (RietveldRefiner 风格一致)

        Returns:
            RefinementResult (wR 单位 %; phases 已回写 weight_fraction + lattice)
        """
        # 优先级: 用户传入 work_dir > keep_workdir=True 时建一个跟踪目录 > 否则 mkdtemp
        # 之前版本 keep_workdir=True 时会忽略用户的 work_dir, 这里修正.
        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="maud_engine_"))

        try:
            artifacts = self.prepare_workdir(
                data, phases,
                iterations=iterations,
                wizard_index=wizard_index,
                work_dir=Path(work_dir),
                cod_root=cod_root,
            )
            self.run(
                artifacts,
                max_memory_mb=max_memory_mb,
                timeout_s=timeout_s,
                on_progress=on_progress,
            )
        except MaudEngineError as e:
            logger.warning("MAUD 引擎失败, 由调用方决定是否兜底: %s", e)
            raise

        # 结果回读
        rfactors = _parse_par_rfactors(artifacts.output_par_path)
        tsv_entries = _parse_tsv_results(artifacts.output_tsv_path)
        _apply_tsv_to_phases(phases, tsv_entries)
        # MAUD2/3 的 TSV 不含相定量 — 相体积分数/晶胞从 refined.par 解析回写
        par_entries = _parse_par_phases(artifacts.output_par_path)
        _apply_par_to_phases(phases, par_entries)

        # 复制最终 par 到 work_dir 顶层 (供 GUI 查看); 不动 shutil.rmtree 因为可能 keep_workdir
        rwp = float(rfactors.get("rwp") or 0.0)
        wrp = float(rfactors.get("wrp") or 0.0)
        gof = float(rfactors.get("gof") or 0.0)
        n_iter = int(rfactors.get("iterations") or 0)

        quality = (
            "优秀" if wrp < 5
            else "良好" if wrp < 10
            else "可接受" if wrp < 20
            else "需改进"
        )

        # 残差谱: MAUD 不直接暴露 simulated_data, 用 observed 0 残差占位
        try:
            obs_x = np.asarray(data.two_theta, dtype=float)
            obs_y = np.asarray(data.intensity, dtype=float)
            observed = (obs_x, obs_y)
            simulated = (obs_x, obs_y)  # 简化: 占位
            residual = (obs_x, np.zeros_like(obs_y))
        except Exception:
            observed = simulated = residual = None

        result = RefinementResult(
            phases=list(phases),
            observed_data=observed,
            simulated_data=simulated,
            residual_data=residual,
            wR=wrp,  # 用 wR (加权) 作为主要指标
            GOF=gof,
            quality=quality,
            num_cycles=n_iter,
            converged=(wrp > 0.0 and wrp < 50.0),  # MAUD 没显式收敛标志
            time_seconds=0.0,  # 调用方 (RietveldRefiner) 会覆盖
            fit_params={
                "engine": "maud",
                "maud_root": str(self.maud_root),
                "iterations_requested": iterations or self.DEFAULT_ITERATIONS,
                "wizard_index": wizard_index,
                "r_factor": rwp,
                "wR_factor": wrp,
                "goodness_of_fit": gof,
                "work_dir": str(artifacts.work_dir),
                "output_par": str(artifacts.output_par_path),
                "output_tsv": str(artifacts.output_tsv_path),
                "tsv_entries": tsv_entries,
                "par_phase_entries": par_entries,
                "kept_workdir": keep_workdir,
            },
        )
        return result