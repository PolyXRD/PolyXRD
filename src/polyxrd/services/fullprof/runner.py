"""FullProf fp2k 运行器与 .sum 结果解析 (v0.15 M25-5)
====================================================

用法::

    res = run(workdir, fp_exe=Path("C:/FullProf_Suite/fp2k.exe"))
    res.rwp, res.gof, res.phases  # 写回精修日志区

约定 (全部实测于 fp2k 8.20, 2025-02, 本机 C:\\FullProf_Suite):

- fp2k 按 ``{pcr同名}.dat`` 找数据文件 → dat/pcr 必须同 stem;
- 非交互运行: ``fp2k <stem>``, stdin 直接给 EOF 即可, 退出码 0;
- 结果在 ``{stem}.sum``: ``=> Rp: .. Rwp: .. Rexp: .. Chi2: ..`` 行、
  ``=> Phase:  n  <name>`` / ``=> Bragg R-factor: .. Vol: .. Fract(%): ..`` 行;
- 正常结束标志: ``Run finished at:``;
- 标度校准读 ``{stem}.out`` 的 SumYdif/SumYobs/SumYcal 表格 (``parse_sums``)。

工作目录强制 ``~/.polyxrd/external_runs/<ts>/`` (C 盘 Program 目录无写权限、
fp2k 对非 ASCII 路径敏感), 由 ``new_run_dir()`` 统一创建。
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

__all__ = ["FullProfResult", "new_run_dir", "parse_sum", "run", "find_fp_exe",
           "auto_refine", "parse_sums", "discover_limit_numbers"]

_SUMTABLE_RE = re.compile(
    r"SumYdif\s+SumYobs\s+SumYcal\s+SumwYobsSQ\s+Residual\s+Condition\s*\n"
    r"\s*([0-9.Ee+-]+)\s+([0-9.Ee+-]+)\s+([0-9.Ee+-]+)")

_SYMBOL_RE = re.compile(
    r"Parameter number\s+(\d+)\s+-> Symbolic Name:\s*(\S+)")


def discover_limit_numbers(
        out_path: str | Path) -> tuple[Optional[int], Optional[int]]:
    """从 .out 的 ``SYMBOLIC NAMES AND INITIAL VALUES`` 表解析限位编号。

    Returns:
        ``(zero_no, w_no)`` — fp2k 内部参数表里 Zero-point 与
        W-Cagl (Caglioti W) 的编号, 供 "Limits for selected parameters"
        块使用。**该编号与本方生成的 codeword 整数无关** (1 相实测:
        Cell_A=1, Zero=2, Bck=3..5, Scale=6, W=7, Cell_C=8)。
        解析不到的项为 None。
    """
    try:
        text = Path(out_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    zero_no: Optional[int] = None
    w_no: Optional[int] = None
    for m in _SYMBOL_RE.finditer(text):
        no = int(m.group(1))
        name = m.group(2)
        if zero_no is None and "Zero" in name:
            zero_no = no
        elif w_no is None and "W-Cagl" in name:
            w_no = no
    return zero_no, w_no


def parse_sums(out_path: str | Path) -> tuple[Optional[float], Optional[float]]:
    """从 .out 读 ``(SumYobs, SumYcal)`` (标度校准用); 无则 ``(None, None)``。

    注意: 不能用 ``SumYnet`` 行 — 那是 Σ(w·Ynet²), 不是 Σy_calc。
    Σy_calc 在 ``SumYdif/SumYobs/SumYcal`` 表格数据行第 3 列 (实测 fp2k 8.20)。
    取**第一张**表 (完整图; fp2k 还会对"仅 Bragg 点"再出一张表, 其 SumYobs
    偏小 ~30%)。校准试跑恒为 fix_all 单循环, 第一张即唯一有效表。
    """
    try:
        text = Path(out_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    matches = _SUMTABLE_RE.findall(text)
    if not matches:
        return None, None
    _ydif, yobs, ycal = matches[0]
    try:
        yobs_f = float(yobs)
        ycal_f = float(ycal)
    except ValueError:
        return None, None
    return (yobs_f if yobs_f > 0 else None, ycal_f if ycal_f > 0 else None)


def auto_refine(
    data,
    phases: list,
    workdir: str | Path,
    *,
    fp_exe: str | Path,
    stem: str = "run",
    on_log: Optional[Callable[[str], None]] = None,
    wavelength: float = 1.54056,
    timeout: float = 600.0,
) -> FullProfResult:
    """一站式 FullProf 精修: dat/pcr 生成 + 标度自动校准 + fp2k 运行。

    流程 (fp2k 单次 <1s, 多跑几遍代价可忽略):

      1) **标度校准**: ``fix_all=True`` 全固定 PCR (scale=1) 试跑, 读 .out
         的 SumYdif/SumYobs/SumYcal 表格 (``parse_sums``), 得
         ``scale = SumYobs / SumYcal``。量级对了最小二乘才收敛。
      2) **正式精修第一遍**: 限位编号用占位号 97/98 (fp2k 对不存在的参数
         号直接忽略, 实测无害), 但因此 W 无界仍可能冲负 → Singular。
      3) **限位编号发现**: 从第一遍 .out 的 SYMBOLIC NAMES 表解析
         Zero/W 真实编号 (``discover_limit_numbers``), 重新生成 PCR
         (W 限 [0.0001, 1.0]) 再跑 — 这是主收敛路径。
      4) **保守模式兜底**: 固定晶胞+零点, 仅精修 scale/W/背景。

    背景初值取数据 5% 分位 (从 0 起步会逼着 scale 上下 10σ 振荡, 实测);
    W 初值 0.010 (≈ FWHM 0.10°, 实验室典型)。

    工作目录必须全 ASCII; 内部强制 ``~/.polyxrd/external_runs/`` 由调用方
    经 :func:`new_run_dir` 创建。
    """
    import numpy as np

    from polyxrd.services.fullprof.dat_builder import build_dat, data_grid
    from polyxrd.services.fullprof.pcr_builder import build_pcr

    log = on_log or (lambda _m: None)
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)

    build_dat(data, wd / f"{stem}.dat", title="PolyXRD FullProf run")
    thmin, step, thmax = data_grid(data)

    # 背景初值: 数据低位分位 (计数型数据背景 ≈ 低分位)
    arr = np.asarray(data.intensity, dtype=float)
    finite = arr[np.isfinite(arr)]
    bg0 = float(np.percentile(finite, 5.0)) if finite.size else 0.0
    bg_coeffs = [max(bg0, 0.0), 0.0, 0.0]

    common = dict(thmin=thmin, thmax=thmax, step=step,
                  wavelength=wavelength, bg_coefficients=bg_coeffs)

    # ── 1) 标度校准试跑 (全固定, scale=1) ──────────────────────
    cal_stem = f"{stem}_cal"
    build_dat(data, wd / f"{cal_stem}.dat", title="scale calibration")
    build_pcr(
        phases, wd / f"{cal_stem}.pcr",
        title="PolyXRD scale calibration", fix_all=True, scale=1.0, **common,
    )
    log(f"[fullprof] scale-calibration trial run ({cal_stem}) ...")
    cal_out = wd / f"{cal_stem}.out"
    subprocess.run(
        [str(fp_exe), cal_stem], cwd=str(wd), capture_output=True,
        text=True, timeout=min(timeout, 120.0), stdin=subprocess.DEVNULL,
    )
    sum_yobs, sum_ycal = parse_sums(cal_out)
    scale = 1.0e-3
    if sum_ycal and sum_ycal > 0 and sum_yobs and sum_yobs > 0:
        scale = sum_yobs / sum_ycal
        log(f"[fullprof] calib: sum_yobs={sum_yobs:.3g}, sum_ycal={sum_ycal:.3g} "
            f"-> scale={scale:.4g}")
    else:
        log("[fullprof] calib failed (no SumYcal table), using default scale=1e-3")

    # ── 2) 正式精修第一遍 (限位编号占位) ───────────────────────
    build_pcr(
        phases, wd / f"{stem}.pcr",
        title="PolyXRD FullProf Rietveld", scale=scale,
        limit_zero_no=97, limit_w_no=98, **common,
    )
    res = run(wd, fp_exe=fp_exe, stem=stem, timeout=timeout, on_log=on_log)

    # ── 3) 限位编号发现 + 重跑 (主收敛路径) ────────────────────
    zero_no: Optional[int] = None
    w_no: Optional[int] = None
    if not res.ok:
        zero_no, w_no = discover_limit_numbers(wd / f"{stem}.out")
        if zero_no is not None and w_no is not None:
            log(f"[fullprof] limit codes found: Zero={zero_no}, W={w_no} -> rerun")
            build_pcr(
                phases, wd / f"{stem}.pcr",
                title="PolyXRD FullProf Rietveld", scale=scale,
                limit_zero_no=zero_no, limit_w_no=w_no, **common,
            )
            res = run(wd, fp_exe=fp_exe, stem=stem, timeout=timeout,
                      on_log=on_log)

    # ── 4) 保守模式兜底 (W 扫描) ──────────────────────────────
    # 全矩阵精修 (放开晶胞) 对初值敏感, 可能 Singular matrix 中止而不写
    # .sum; 固定晶胞+零点+W, 仅精修 scale/背景 — 绝对稳。峰宽未知 →
    # 对 W 扫描取最优 (fp2k 单次 <1s)。宽=√W, 0.010≈FWHM 0.10°。
    if not res.ok:
        log("[fullprof] no convergence, retrying conservative (fix cell/zero, scan W) ...")
        safe_stem = f"{stem}_safe"
        build_dat(data, wd / f"{safe_stem}.dat", title="PolyXRD FullProf run")
        best: Optional[FullProfResult] = None
        for w0 in (0.010, 0.020, 0.040):
            build_pcr(
                phases, wd / f"{safe_stem}.pcr",
                title="PolyXRD FullProf Rietveld (conservative)",
                scale=scale, fix_cell=True, w_initial=w0, **common,
            )
            r = run(wd, fp_exe=fp_exe, stem=safe_stem,
                    timeout=timeout, on_log=on_log)
            if r.ok and (best is None
                         or (r.rwp or 9e9) < (best.rwp or 9e9)):
                best = r
            if r.ok:
                log(f"[fullprof] conservative W={w0:.3f}: Rwp={r.rwp:.2f}%")
        if best is not None:
            res = best
        else:
            res.log_lines.append(
                "[fullprof] 保守模式也未收敛, 返回常规模式结果 (error=%s)"
                % (res.error or "未知"))
    return res


_SUM_R_LINE = re.compile(
    r"Rp:\s*([\d.]+)\s+Rwp:\s*([\d.]+)\s+Rexp:\s*([\d.]+)\s+Chi2:\s*([\d.]+)"
)
_SUM_PHASE_LINE = re.compile(r"=>\s*Phase:\s*(\d+)\s+(.+?)\s*$")
_SUM_FRACT_LINE = re.compile(
    r"Bragg R-factor:\s*([\d.]+)\s+Vol:\s*([\d.]+)\s*\(?\s*([\d.]*)\s*\)?\s*"
    r"Fract\(%\):\s*([\d.]+)"
)


@dataclass
class FullProfResult:
    """fp2k 单次运行结果。"""

    ok: bool = False
    exit_code: Optional[int] = None
    rwp: Optional[float] = None
    rexp: Optional[float] = None
    rp: Optional[float] = None
    gof: Optional[float] = None          # Chi2 即 GoF²
    chi2: Optional[float] = None
    phases: list[dict] = field(default_factory=list)  # {index,name,r_bragg,vol,fract}
    workdir: Optional[Path] = None
    sum_path: Optional[Path] = None
    error: str = ""
    log_lines: list[str] = field(default_factory=list)


def new_run_dir(tool: str = "fullprof") -> Path:
    """外部精修工作目录: ~/.polyxrd/external_runs/<tool>_<ts>/ (全 ASCII)。"""
    base = Path.home() / ".polyxrd" / "external_runs"
    d = base / f"{tool}_{time.strftime('%Y%m%d_%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_fp_exe(custom: Optional[str | Path] = None) -> Optional[Path]:
    """FullProf fp2k.exe 定位: 用户配置 → 常见目录 → external_tools 自动探测。"""
    if custom:
        p = Path(custom)
        if p.is_file():
            return p
        for name in ("fp2k.exe", "fp2k_w.exe"):
            cand = p / name
            if cand.exists():
                return cand
    try:
        from polyxrd.services.external_tools import FULLPROF_SPEC, resolve_tool

        path, _src = resolve_tool(FULLPROF_SPEC)
        if path is not None and path.is_file():
            return path
    except Exception:  # noqa: BLE001
        pass
    return None


def parse_sum(sum_path: str | Path) -> dict:
    """解析 .sum → {rwp, rexp, rp, chi2, phases:[...], finished:bool}。"""
    out: dict = {"rwp": None, "rexp": None, "rp": None, "chi2": None,
                 "phases": [], "finished": False}
    try:
        text = Path(sum_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    r_match = None
    current: Optional[dict] = None
    for line in text.splitlines():
        m = _SUM_R_LINE.search(line)
        if m:
            # 取最后一次出现的常规 R 因子行 (最终循环)
            r_match = m
        pm = _SUM_PHASE_LINE.search(line)
        if pm:
            current = {"index": int(pm.group(1)),
                       "name": pm.group(2).strip(),
                       "r_bragg": None, "vol": None, "fract": None}
            out["phases"].append(current)
        fm = _SUM_FRACT_LINE.search(line)
        if fm and current is not None:
            current["r_bragg"] = float(fm.group(1))
            current["vol"] = float(fm.group(2))
            current["fract"] = float(fm.group(4))
        if "Run finished at:" in line:
            out["finished"] = True
    if r_match:
        out["rp"] = float(r_match.group(1))
        out["rwp"] = float(r_match.group(2))
        out["rexp"] = float(r_match.group(3))
        out["chi2"] = float(r_match.group(4))
    return out


def run(
    workdir: str | Path,
    *,
    fp_exe: str | Path,
    stem: Optional[str] = None,
    timeout: float = 600.0,
    on_log: Optional[Callable[[str], None]] = None,
) -> FullProfResult:
    """在工作目录内运行 fp2k 并解析 .sum。

    工作目录必须已含同 stem 的 .pcr/.dat (stem 缺省取目录内第一个 .pcr)。
    """
    log = on_log or (lambda _m: None)
    res = FullProfResult(workdir=Path(workdir))
    exe = Path(fp_exe)
    if not exe.is_file():
        res.error = f"fp2k 不存在: {exe}"
        log(f"[fullprof] {res.error}")
        return res

    wd = Path(workdir)
    if stem is None:
        pcrs = sorted(wd.glob("*.pcr"))
        if not pcrs:
            res.error = f"工作目录无 .pcr: {wd}"
            log(f"[fullprof] {res.error}")
            return res
        stem = pcrs[0].stem
    if not (wd / f"{stem}.dat").exists():
        res.error = f"缺少数据文件 {stem}.dat"
        log(f"[fullprof] {res.error}")
        return res

    log(f"[fullprof] fp2k start: {exe.name} {stem} (workdir={wd.name})")
    start = time.time()
    try:
        proc = subprocess.run(
            [str(exe), stem],
            cwd=str(wd),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        res.error = f"fp2k 超时 ({timeout:.0f}s)"
        log(f"[fullprof] {res.error}")
        return res
    except OSError as exc:
        res.error = f"fp2k 启动失败: {exc}"
        log(f"[fullprof] {res.error}")
        return res

    res.exit_code = proc.returncode
    elapsed = time.time() - start

    sum_path = wd / f"{stem}.sum"
    res.sum_path = sum_path if sum_path.exists() else None
    parsed = parse_sum(sum_path) if sum_path.exists() else {}
    res.rp, res.rwp, res.rexp, res.chi2 = (
        parsed.get("rp"), parsed.get("rwp"),
        parsed.get("rexp"), parsed.get("chi2"),
    )
    res.phases = parsed.get("phases", [])
    res.gof = res.chi2

    if parsed.get("finished") and res.rwp is not None:
        res.ok = True
    elif proc.returncode != 0:
        tail = (proc.stdout or "").strip().splitlines()[-5:]
        res.error = f"fp2k 退出码 {proc.returncode}: " + " | ".join(tail)
    else:
        tail = (proc.stdout or "").strip().splitlines()[-5:]
        res.error = "fp2k 未产出最终结果: " + " | ".join(tail)

    res.log_lines.append(
        f"[fullprof] fp2k 结束: exit={proc.returncode}, 耗时 {elapsed:.1f}s, "
        f"{'OK' if res.ok else res.error}"
    )
    if res.ok:
        res.log_lines.append(
            f"[fullprof] Rwp={res.rwp:.2f}%  Rexp={res.rexp:.2f}%  "
            f"Rp={res.rp:.2f}%  Chi2(GoF²)={res.chi2:.2f}"
        )
        for ph in res.phases:
            res.log_lines.append(
                f"[fullprof] 相 {ph['index']} {ph['name']}: "
                f"R_Bragg={ph.get('r_bragg')}%  "
                f"Vol={ph.get('vol')} Å³  含量={ph.get('fract')}%"
            )
    for line in res.log_lines:
        log(line)
    return res
