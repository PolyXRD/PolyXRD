"""FullProf .pcr 控制文件生成 (v0.15 M25-5)
==========================================

自写模板生成器 (路线 B 兜底), 语法逐段对照官方样例
``C:\\FullProf_Suite\\Examples\\ce1.pcr`` (fp2k 8.20 实测可跑):

- X 射线布拉格-布伦塔诺几何, Cu Kα1/α2 双线, 等步长计数数据;
- 伪-Voigt 峰形 (Th-Cox 默认 5 号函数), 6 次多项式背景;
- 每相: scale / W (Caglioti 常数项) / 晶胞 a,b,c 参与精修, U,V 固定 0
  (防负 FWHM 发散)、夹角固定 (多余自由度, 实测会把 Cell_A 顶到界外),
  原子坐标固定, 背景前 3 项与零点偏移参与精修。

FullProf codeword 语法: 参数行下方的 ``编号.倍率`` (整数部分是用户自选的
参数号, 不必遵循任何约定编号); 这里用自增计数器编号, 背景随 pattern、
scale/U/V/W/晶胞随 phase 各自独立精修。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np

__all__ = ["build_pcr", "normalize_space_group"]


def normalize_space_group(sg: str) -> str:
    """物相库的空间群写法 → fp2k 可解析的 H-M 符号。

    "P6_3/mmc" → "P 63/mmc"; "Fm-3m" → "F m -3 m"; 空串 → "P 1"。
    规则: 下划线删除; 晶格字母后补空格; 字母↔数字边界补空格
    ("/" 阻断, 保持 "63/mmc" 短式不拆散)。
    """
    s = (sg or "").strip()
    s = s.replace("_", "")
    if not s:
        return "P 1"
    s = re.sub(r"^([A-Za-z])", r"\1 ", s)           # 晶格字母
    s = re.sub(r"([A-Za-z])(-?\d)", r"\1 \2", s)    # 字母|数字
    s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)      # 数字|字母
    s = re.sub(r"\s+", " ", s).strip()
    return s or "P 1"


def _element_symbol(site: dict) -> str:
    for key in ("type_symbol", "label", "atom_type"):
        v = str(site.get(key, "") or "").strip()
        if v:
            m = re.match(r"^([A-Za-z]{1,2})", v)
            if m:
                return m.group(1).capitalize()
    return "X"


def _atomic_weight(symbol: str) -> float:
    try:
        from polyxrd.services.refinement_engines.maud_engine import _atomic_weight

        w = _atomic_weight(symbol)
        if w and w > 0:
            return float(w)
    except Exception:  # noqa: BLE001
        pass
    return 1.0


def _site_biso(site: dict) -> float:
    """Biso: B_iso_or_equiv 优先, U_iso × 8π² 次之, 缺失默认 0
    (B=1 会在高角压 ~20% 强度, 造成 R_Bragg 系统性地板)。"""
    for key in ("B_iso_or_equiv", "B_iso", "Biso"):
        try:
            v = float(site.get(key))
            if np.isfinite(v) and v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    for key in ("U_iso_or_equiv", "U_iso"):
        try:
            v = float(site.get(key))
            if np.isfinite(v) and v >= 0:
                return v * 8.0 * np.pi * np.pi
        except (TypeError, ValueError):
            pass
    return 0.0


class _CodeBook:
    """自增参数号分配 (FullProf codeword 整数部分)。

    ``fix_all=True`` 时全部返回 0.0 (不精修), 用于标度校准试跑。
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._n = 0
        self.count = 0  # 被精修的参数个数

    def next(self) -> float:
        if not self._enabled:
            return 0.0
        self._n += 1
        self.count += 1
        return float(self._n)


def build_pcr(
    phases: list,
    out_path: str | Path,
    *,
    thmin: float,
    thmax: float,
    step: float,
    wavelength: float = 1.54056,
    title: str = "PolyXRD Rietveld",
    n_bg: int = 3,
    bg_coefficients: Optional[list[float]] = None,
    ratio_a2_a1: float = 0.5,
    scale: float = 1.0e-3,
    fix_all: bool = False,
    fix_cell: bool = False,
    w_initial: float = 0.010,
    limit_zero_no: int = 1,
    limit_w_no: int = 2,
) -> Path:
    """生成 Rietveld 作业 .pcr。

    Args:
        phases: Phase 列表 (需含 lattice + atomic_sites; 无位点时该相
            仅以晶胞参与, 原子行写占位重元素 — fp2k 至少要 1 个原子行)。
        thmin/thmax/step: 与 .dat 一致的角度范围与步长。
        bg_coefficients: 背景多项式初值 (至多 6 项, 不足补 0)。
        scale: 标度因子初值 (calc/obs 量级相关, 建议经 :mod:`runner`
            的标度校准确定)。
        fix_all: 全部参数固定 (codeword=0) 且 scale 用 ``scale`` —
            用于标度校准试跑。
        fix_cell: 固定晶胞与零点偏移, 其余照常精修 — 保守模式兜底
            (常规精修 Singular matrix 时的重试)。
        w_initial: Caglioti W 初值 (FWHM² 常数项, 单位 deg²; 0.010 ≈
            FWHM 0.10°, 实验室典型值。初值过小会让第一循环大步震荡)。
        limit_zero_no/limit_w_no: "Limits for selected parameters" 块中
            零点/W 的参数编号。**该编号是 fp2k 内部符号表编号, 与本生成器
            的 codeword 整数无关** (实测 1 相时 Zero=2、W-Cagl=7, 按
            Cell_A→Zero→Bg→Scale→W→Cell_C 排序)。默认 1/2 仅占位 —
            错误编号会把界限打在别的参数上 (实测把 Cell_A 限成
            [-0.5,0.5] → 崩)。调用方应先跑一遍从 .out 的 SYMBOLIC NAMES
            表解析真实编号 (runner.discover_limit_numbers)。

    Returns:
        落盘的 .pcr 路径。
    """
    if not phases:
        raise ValueError("phases 不能为空")
    lam1 = float(wavelength)
    lam2 = lam1 * 1.0 + 0.00377  # Cu Kα2 = λ1 + 0.00377 Å (Kα1≈1.54056)
    bg = list(bg_coefficients or [])[:6] + [0.0] * max(0, 6 - len(bg_coefficients or []))

    code = _CodeBook(enabled=not fix_all)
    # 零点偏移: fix_cell (保守模式) 固定 → 不占参数号 (否则 "Number of
    # refined parameters" 与实际不符, fp2k 参数表错位 → 奇异矩阵)
    zero_code = 0.0 if fix_cell else code.next()
    bg_codes = [code.next() for _ in range(n_bg)]  # 2..n) 背景前 n_bg 项

    L: list[str] = []
    stem = Path(out_path).stem
    L.append(f"{title}")
    L.append(f"! Files => DAT-file: {stem}.dat,  PCR-file: {stem}   (generated by PolyXRD v0.15)")
    L.append("!Job Npr Nph Nba Nex Nsc Nor Dum Iwg Ilo Ias Res Ste Nre Cry Uni Cor Opt Aut")
    L.append("   0   5   %d   0   0   0   0   0   0   0   0   0   0   2   0   0   0   1   1" % len(phases))
    L.append("!")
    L.append("!Ipr Ppl Ioc Mat Pcr Ls1 Ls2 Ls3 NLI Prf Ins Rpa Sym Hkl Fou Sho Ana")
    L.append("   0   0   1   0   1   0   4   0   0   1   0   1   1   1   2   0   0")
    L.append("!")
    L.append("! Lambda1  Lambda2    Ratio    Bkpos    Wdt    Cthm     muR   AsyLim   Rpolarz  2nd-muR -> Patt# 1")
    L.append(f" {lam1:.6f} {lam2:.6f} -{ratio_a2_a1:.5f}   25.000 15.0000  0.9100  0.0000   30.00    0.0000  0.0000")
    L.append("!")
    L.append("!NCY  Eps  R_at  R_an  R_pr  R_gl     Thmin       Step       Thmax    PSD    Sent0")
    L.append("  6  0.10  1.00  1.00  1.00  1.00     %12.4f %12.6f %12.4f   0.000   0.000"
             % (thmin, step, thmax))
    L.append("!")
    L.append("      %d    !Number of refined parameters" % 0)  # 占位, 结尾回填
    L.append("!")
    L.append("!  Zero    Code    SyCos    Code   SySin    Code  Lambda     Code MORE ->Patt# 1")
    L.append("  0.00000 %7.1f  0.00000    0.0  0.00000    0.0 0.000000    0.00   1" % zero_code)
    L.append("!")
    L.append("! Microabsorption coefficients for Pattern#  1")
    L.append("!   P0    Cod_P0    Cp   Cod_Cp     Tau  Cod_Tau")
    L.append("  0.0000    0.00  1.0000    0.00  0.0000    0.00")
    L.append("!   Background coefficients/codes  for Pattern#  1  (Polynomial of 6th degree)")
    L.append("  " + "  ".join(f"{b:>10.4f}" for b in bg))
    L.append("  " + "  ".join(
        (f"{bg_codes[i]:>10.1f}" if i < n_bg else "     0.00") for i in range(6)
    ))

    for idx, phase in enumerate(phases, start=1):
        lat = phase.lattice
        a = float(lat.a) if lat is not None else 4.0
        b = float(lat.b) if lat is not None else a
        c = float(lat.c) if lat is not None else a
        al = float(lat.alpha) if lat is not None else 90.0
        be = float(lat.beta) if lat is not None else 90.0
        ga = float(lat.gamma) if lat is not None else 90.0

        sites = list(getattr(phase, "atomic_sites", None) or [])
        if not sites:
            # fp2k 至少要一个原子行: 占位氧原子, 占位不影响峰位计算
            sites = [{"type_symbol": "O", "fract_x": 0.0, "fract_y": 0.0,
                      "fract_z": 0.0, "occupancy": 1.0}]
        atz = sum(_site_occ(s) * _atomic_weight(_element_symbol(s)) for s in sites)

        scale_code = code.next()
        # U/V 固定为 0 (避免负 FWHM 发散); 保守模式连 W 也固定
        # (W 奇异是常规模式发散的主因, 保守模式必须绝对稳)
        u_code = v_code = 0.0
        w_code = 0.0 if fix_cell else code.next()
        if fix_cell:
            cell_codes = [0.0] * 6   # 保守模式: 晶胞全固定
        else:
            # 只精修 a,b,c; 夹角固定 (90°/120° 精修是多余自由度,
            # 实测会把 Cell_A 顶出界 → Singular matrix)
            cell_codes = [code.next() for _ in range(3)] + [0.0, 0.0, 0.0]

        L.append("!-------------------------------------------------------------------------------")
        L.append("!  Data for PHASE number: %3d  ==> Current R_Bragg for Pattern#  1:   0.0000" % idx)
        L.append("!-------------------------------------------------------------------------------")
        L.append("  %s" % ((getattr(phase, "name", "") or f"Phase{idx}").strip() or f"Phase{idx}"))
        L.append("!")
        L.append("!Nat Dis Ang Pr1 Pr2 Pr3 Jbt Irf Isy Str Furth       ATZ    Nvk Npr More")
        L.append("   %d   0   0 1.0 1.0 1.0   0   0   0   0   0        %9.3f   0   5   0"
                 % (len(sites), atz))
        L.append("!")
        L.append("!")
        # SG 行必须带 "<--Space group symbol" 锚点: 没有它 fp2k 把该行当
        # 数值(空间群编号)解析 → "invalid character in a numeric field"
        L.append("%s                  <--Space group symbol"
                 % normalize_space_group(getattr(phase, "space_group", "") or ""))
        L.append("!Atom   Typ       X        Y        Z     Biso       Occ     In Fin N_t Spc /Codes")
        for s in sites:
            sym = _element_symbol(s)
            x = _frac(s, "fract_x")
            y = _frac(s, "fract_y")
            z = _frac(s, "fract_z")
            L.append(
                "%-6s %-4s %8.5f %8.5f %8.5f %10.5f %10.5f   0   0   0    0"
                % (sym, sym[:4], x, y, z, _site_biso(s), _site_occ(s))
            )
            L.append("      0.00     0.00     0.00     0.00     0.00")
        L.append("!-------> Profile Parameters for Pattern #   1  ----> Phase # %3d" % idx)
        L.append("!  Scale          Shape1      Bov      Str1      Str2      Str3   Strain-Model")
        L.append(" %.7E   0.36713   0.00000   0.00000   0.00000   0.00000       0" % scale)
        L.append("      %7.1f     0.000     0.000     0.000     0.000     0.000" % scale_code)
        L.append("!       U         V          W           X          Y        GauSiz   LorSiz Size-Model")
        L.append("   0.000000   0.000000   %.6f   0.000000   0.000000   0.000000   0.000000    0"
                 % w_initial)
        # codes 行只有 7 个 (U,V,W,X,Y,GauSiz,LorSiz) — Size-Model 无精修码,
        # 多写一个会把后续记录整体顶错位 (ce1 golden 对照实测)
        L.append("      %6.1f      %6.1f      %6.1f      0.000      0.000      0.000      0.000"
                 % (u_code, v_code, w_code))
        L.append("!     a          b         c        alpha      beta       gamma      #Cell Info")
        L.append("   %9.6f  %9.6f  %9.6f  %8.4f  %8.4f  %8.4f"
                 % (a, b, c, al, be, ga))
        L.append("      %6.1f      %6.1f      %6.1f      %6.1f      %6.1f      %6.1f"
                 % tuple(cell_codes))
        L.append("!  Pref1    Pref2      Asy1     Asy2     Asy3     Asy4  ")
        L.append("  0.00000  0.00000  0.06233  0.00000  0.00000  0.00000")
        L.append("     0.00     0.00     0.00     0.00     0.00     0.00")
        L.append("!Additional U,V,W parameters for Lambda2")
        # 必须与 λ1 主 U,V,W 同构 (U2=V2=0, W2=W 初值): ce1 样例的
        # 0.007462/-0.005259/0.008199 在高角区会算出负 FWHM² → fp2k 把
        # HG 钳到 1e-10 → W 行奇异 (实测 "Square of FWHM(G) < 0" 连发)
        L.append("   0.000000   0.000000   %.6f   <--  U2,V2,W2 for lambda(2) "
                 % w_initial)
        L.append("  0.000000 0.000000 0.000000")
        # "Limits for selected parameters" 段是必需的: 缺失时 fp2k 把 2Th 行
        # 当 limit 记录读 → "FindFMT: integer field found real" (实测)
        L.append("! Limits for selected parameters:")
        # 该块必须恒为两行 (只发一行或空块时 fp2k 会把 2Th 行当 limit
        # 记录读 → "FindFMT: integer field found real", 实测)。
        # 编号是 fp2k 符号表编号 (见 build_pcr docstring), 默认 1/2 仅供
        # 占位/发现轮; 真实编号由 runner 经 .out 解析后传入。
        L.append("  %d     -0.5000      0.5000      0.0000   0  Zero_shift"
                 % limit_zero_no)
        L.append("  %d      0.0001      1.0000      0.0000   0  W_d"
                 % limit_w_no)
        L.append("!  2Th1/TOF1    2Th2/TOF2  Pattern to plot")
        L.append("      %9.3f     %9.3f       1" % (thmin, thmax))

    text = "\n".join(L) + "\n"
    # 回填精修参数个数
    text = text.replace(
        "      0    !Number of refined parameters",
        "      %d    !Number of refined parameters" % code.count,
        1,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="ascii")
    return out


def _frac(site: dict, key: str) -> float:
    try:
        v = float(site.get(key))
        return v if np.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _site_occ(site: dict) -> float:
    try:
        v = float(site.get("occupancy", 1.0))
        return v if np.isfinite(v) and 0.0 < v <= 1.0 else 1.0
    except (TypeError, ValueError):
        return 1.0
