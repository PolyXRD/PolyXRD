"""
R-C6 冒烟测试 2: 复制 recon 里 ins_F 的成功路径, 用预加载的 alzrc.par
(已含相 + 数据 + 仪器), 只调 Rietveld 精修, 不动数据绑定。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_alzrc_dat(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """解析 MAUD .dat (第 1 行样品名, 第 2 行 5 个 header 数字, 后是强度).

    alzrc.dat header 格式:
        n_points step start_2theta wavelength ?
    """
    raw = path.read_text(encoding="latin-1", errors="replace").splitlines()
    hdr_idx = None
    for i, l in enumerate(raw[:5]):
        parts = l.replace("\t", " ").split()
        if len(parts) >= 4 and all(_is_float(p) for p in parts[:4]):
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError(f"无法解析 {path} header")
    hdr = raw[hdr_idx].replace("\t", " ").split()
    n = int(float(hdr[0]))           # 2660 数据点数
    step = float(hdr[1])             # 0.05 °
    start_2theta = float(hdr[2])     # 22 ° (起始角)
    wl = float(hdr[3])               # 1.540598 Å
    ints: list[float] = []
    for l in raw[hdr_idx + 1:]:
        for tok in l.replace("\t", " ").split():
            if _is_float(tok):
                ints.append(float(tok))
                if len(ints) >= n:
                    break
        if len(ints) >= n:
            break
    two_theta = start_2theta + np.arange(n) * step
    intensity = np.array(ints[:n], dtype=float)
    return two_theta, intensity, wl


def main() -> int:
    from polyxrd.models.phase import LatticeParams, Phase
    from polyxrd.models.xrd_data import XRDData
    from polyxrd.services.refinement_engines import MaudEngine, MaudEngineError

    src_dir = Path(r"C:/Users/Administrator/AppData/Local/Temp/maud_ins_smoke")
    src_par = src_dir / "alzrc.par"
    src_dat = src_dir / "alzrc.dat"
    if not src_par.exists() or not src_dat.exists():
        print(f"FAIL: 缺预加载 {src_par} / {src_dat}", file=sys.stderr)
        return 1

    # 拷到 work_dir
    work = Path(tempfile.mkdtemp(prefix="maud_replay_"))
    shutil.copy2(src_par, work / "alzrc.par")
    shutil.copy2(src_dat, work / "alzrc.dat")

    # 写 ins: 模仿 ins_F (loop_, 5 列)
    (work / "run.ins").write_text(
        "loop_\n"
        "_riet_analysis_file\n"
        "_riet_analysis_iteration_number\n"
        "_riet_analysis_fileToSave\n"
        "_riet_meas_datafile_name\n"
        "_riet_append_simple_result_to\n"
        "'alzrc.par'\n"
        "20\n"
        "'refined.par'\n"
        "'alzrc.dat'\n"
        "'results.tsv'\n"
    )

    # 用 _parse_alzrc_dat 解析 (避免 np.loadtxt 误判 header)
    tt, I, wl = _parse_alzrc_dat(src_dat)
    data = XRDData(two_theta=tt, intensity=I, wavelength=wl)

    # 准备 Phases (从 alzrc.par 里读出来)
    # alzrc.par 是 2 相: corundum + T-PSZ
    # 这里手工构造; 真正的 engine 应自动从 .par 读
    al = Phase(
        name="corundum",
        formula="Al2O3",
        lattice=LatticeParams(a=4.758, b=4.758, c=12.991, alpha=90, beta=90, gamma=120),
        cif_path=None,
        weight_fraction=0.0,
    )
    zr = Phase(
        name="T-PSZ",
        formula="ZrO2",
        lattice=LatticeParams(a=3.642, b=3.642, c=5.270, alpha=90, beta=90, gamma=120),
        cif_path=None,
        weight_fraction=0.0,
    )

    # 用 engine 但绕过 prepare_workdir (因为已写好 ins)
    from polyxrd.services.refinement_engines.maud_engine import (
        MaudInsArtifacts,
        _parse_par_rfactors,
        _parse_tsv_results,
        _apply_tsv_to_phases,
    )
    engine = MaudEngine(maud_root=Path(r"C:/MAUD3"))
    artifacts = MaudInsArtifacts(
        ins_path=work / "run.ins",
        work_dir=work,
        output_par_path=work / "refined.par",
        output_tsv_path=work / "results.tsv",
        template_par_path=work / "alzrc.par",
    )

    try:
        engine.run(artifacts, timeout_s=180.0)
    except MaudEngineError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    rf = _parse_par_rfactors(artifacts.output_par_path)
    tsv = _parse_tsv_results(artifacts.output_tsv_path)
    _apply_tsv_to_phases([al, zr], tsv)

    print("=" * 60)
    print("R-C6 replay 结果")
    print("=" * 60)
    print(f"  wR: {rf['wrp']:.3f}%")
    print(f"  R:  {rf['rwp']:.3f}%")
    print(f"  GOF: {rf['gof']:.3f}")
    print(f"  n_cycles: {rf['iterations']}")
    print()
    for entry in tsv:
        print(f"  {entry['name']}: vol%={entry.get('vol_pct'):.2f} "
              f"wt%={entry.get('wt_pct'):.2f} a={entry.get('cell_a')} c={entry.get('cell_b_or_c')}")
    print()
    print(f"  work_dir: {work}")
    print("=" * 60)

    ok = rf.get("wrp") is not None and rf["wrp"] < 30.0
    print(f"VERIFY: wR={rf.get('wrp'):.3f}% {'< 30%' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())