"""
R-C6 尝试 3: 用默认模板 default.par + _maud_import_phase 动态注入 + auto wizard
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_alzrc_dat(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    raw = path.read_text(encoding="latin-1", errors="replace").splitlines()
    hdr_idx = None
    for i, l in enumerate(raw[:5]):
        parts = l.replace("\t", " ").split()
        if len(parts) >= 4 and all(_is_float(p) for p in parts[:4]):
            hdr_idx = i
            break
    hdr = raw[hdr_idx].replace("\t", " ").split()
    n, step, start_2theta, wl = (int(float(hdr[0])), float(hdr[1]),
                                  float(hdr[2]), float(hdr[3]))
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
    return two_theta, np.array(ints[:n], dtype=float), wl


def main() -> int:
    from polyxrd.services.refinement_engines import MaudEngine, MaudEngineError
    from polyxrd.services.refinement_engines.maud_engine import (
        _parse_par_rfactors, _parse_tsv_results, _apply_tsv_to_phases,
    )
    from polyxrd.models.phase import LatticeParams, Phase

    src_dat = Path(r"C:/MAUD2/alzrc.dat")
    if not src_dat.exists():
        print("FAIL: 缺 alzrc.dat", file=sys.stderr)
        return 1

    tt, I, wl = _parse_alzrc_dat(src_dat)
    from polyxrd.models.xrd_data import XRDData
    data = XRDData(two_theta=tt, intensity=I, wavelength=wl)

    work = Path(tempfile.mkdtemp(prefix="maud_v3_"))
    print(f"work_dir: {work}")

    # Corundum CIF (从 maud_tpl 拷)
    src_cif_al = Path(r"C:/Users/Administrator/AppData/Local/Temp/maud_tpl/corundum_cod.cif")
    if not src_cif_al.exists():
        print(f"FAIL: 缺 {src_cif_al}", file=sys.stderr)
        return 1
    cif_al_dst = work / "corundum_cod.cif"
    shutil.copy2(src_cif_al, cif_al_dst)

    # T-PSZ CIF (手工写)
    cif_zr_dst = work / "tpsz.cif"
    cif_zr_dst.write_text(textwrap.dedent("""\
        data_global
        _chemical_name_common 'T-PSZ'
        _chemical_formula_structural 'Zr O2'
        _chemical_formula_sum 'O2 Zr'
        _cell_length_a 3.642
        _cell_length_b 3.642
        _cell_length_c 5.270
        _cell_angle_alpha 90
        _cell_angle_beta 90
        _cell_angle_gamma 90
        _cell_volume 69.93
        _space_group_name_H-M_alt 'P 42/n m c :H'
        loop_
        _atom_site_label
        _atom_site_type_symbol
        _atom_site_fract_x
        _atom_site_fract_y
        _atom_site_fract_z
        _atom_site_occupancy
        Zr1 Zr 0 0 0 1.0
        O1 O 0 0.5 0.25 1.0
        O2 O 0.5 0 0.25 1.0
    """))

    # alzrc.par 拷入工作目录作为 template (已经包含 phases)
    src_par = Path(r"C:/Users/Administrator/AppData/Local/Temp/maud_ins_smoke/alzrc.par")
    if not src_par.exists():
        print(f"FAIL: 缺 {src_par}", file=sys.stderr)
        return 1

    # INS: 用 default.par (无相) + _maud_import_phase × 2
    par_dst = work / "maud_default.par"
    shutil.copy2(
        Path(r"E:/TEMP/PolyXRD/src/polyxrd/resources/templates/maud_default.par"),
        par_dst,
    )
    xye_dst = work / "input.xye"
    np.savetxt(xye_dst, np.column_stack([tt, I, np.sqrt(np.maximum(I, 0))]),
               fmt="%.6f", delimiter="\t",
               header="# PolyXRD alzrc 2660 pts", comments="")

    # 关键: 写 _maud_working_directory (MAUD 旧版要求)
    (work / "run.ins").write_text(textwrap.dedent("""\
        loop_
        _riet_analysis_file
        _riet_analysis_iteration_number
        _maud_working_directory
        _maud_remove_all_datafiles
        _riet_meas_datafile_name
        _riet_meas_datafile_replace
        _maud_remove_all_phases
        _maud_import_phase
        _maud_import_phase
        _riet_analysis_fileToSave
        _riet_append_result_to
        'maud_default.par'
        30
        '%s'
        true
        'input.xye'
        true
        true
        'corundum_cod.cif'
        'tpsz.cif'
        'refined.par'
        'results.tsv'
    """ % work.as_posix()))

    # 用 MaudEngine.run 跑
    from polyxrd.services.refinement_engines.maud_engine import MaudInsArtifacts
    engine = MaudEngine(maud_root=Path(r"C:/MAUD3"))
    artifacts = MaudInsArtifacts(
        ins_path=work / "run.ins",
        work_dir=work,
        output_par_path=work / "refined.par",
        output_tsv_path=work / "results.tsv",
        template_par_path=par_dst,
    )
    try:
        engine.run(artifacts, timeout_s=180.0)
    except MaudEngineError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    rf = _parse_par_rfactors(artifacts.output_par_path)
    tsv = _parse_tsv_results(artifacts.output_tsv_path)

    # phases 用于 TSV → lattice 回写
    al = Phase(name="corundum", formula="Al2O3",
               lattice=LatticeParams(a=4.758, b=4.758, c=12.991, alpha=90, beta=90, gamma=120))
    zr = Phase(name="T-PSZ", formula="ZrO2",
               lattice=LatticeParams(a=3.642, b=3.642, c=5.270, alpha=90, beta=90, gamma=120))
    _apply_tsv_to_phases([al, zr], tsv)

    print()
    print("=" * 60)
    print(f"  wR: {rf.get('wrp'):.3f}%")
    print(f"  R:  {rf.get('rwp'):.3f}%")
    print(f"  GOF: {rf.get('gof'):.3f}")
    print(f"  n_cycles: {rf.get('iterations')}")
    print()
    print(f"  {al.name}: wt%={al.weight_fraction:.2f} a={al.lattice.a:.4f} c={al.lattice.c:.4f}")
    print(f"  {zr.name}: wt%={zr.weight_fraction:.2f} a={zr.lattice.a:.4f} c={zr.lattice.c:.4f}")
    print("=" * 60)
    ok = rf.get("wrp") is not None and rf["wrp"] > 0.0 and rf["wrp"] < 30.0
    print(f"VERIFY: wR={rf.get('wrp'):.3f}% {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())