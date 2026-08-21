"""
从COD CIF文件批量生成PolyXRD参考数据库和理论XRD图谱。

用法: python generate_xrd_from_cif.py
"""
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

BASE_DIR = r"C:\Users\Administrator\Desktop\WorkSpace\Trae\PolyXRD"
CIF_DIR = os.path.join(BASE_DIR, "cod_cif_download")
DB_PATH = os.path.join(BASE_DIR, "src", "polyxrd", "resources", "database", "xrd_reference_database.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "xrd_patterns_generated")
WAVELENGTH = 1.5406
TWO_THETA_RANGE = (10.0, 90.0)

# Phase metadata mapping
PHASE_META = {
    "1-1_LiFePO4": {
        "name": "LiFePO4", "formula": "LiFePO4",
        "note": "磷酸铁锂 / Olivine cathode",
        "key": "LiFePO4"
    },
    "1-2_NCM_811": {
        "name": "NCM 811", "formula": "LiNi0.8Co0.1Mn0.1O2",
        "note": "镍钴锰三元正极",
        "key": "NCM811"
    },
    "2-1_ZnO": {
        "name": "Zincite", "formula": "ZnO",
        "note": "氧化锌 / Wurtzite",
        "key": "ZnO"
    },
    "2-2_CaCO3": {
        "name": "Calcite", "formula": "CaCO3",
        "note": "碳酸钙 / 方解石",
        "key": "CaCO3"
    },
    "3-1_TiO2_anatase": {
        "name": "Anatase", "formula": "TiO2",
        "note": "二氧化钛-锐钛矿",
        "key": "TiO2_anatase"
    },
    "3-2_TiO2_rutile": {
        "name": "Rutile", "formula": "TiO2",
        "note": "二氧化钛-金红石",
        "key": "TiO2_rutile"
    },
    "3-3_Al2O3": {
        "name": "Corundum", "formula": "Al2O3",
        "note": "氧化铝 / 刚玉",
        "key": "Al2O3"
    },
    "3-4_CaF2": {
        "name": "Fluorite", "formula": "CaF2",
        "note": "氟化钙 / 萤石",
        "key": "CaF2"
    },
    "4-1_Mg(OH)2": {
        "name": "Brucite", "formula": "Mg(OH)2",
        "note": "氢氧化镁 / 水镁石",
        "key": "Mg(OH)2"
    },
    "5-1_SiO2_alpha_quartz": {
        "name": "α-Quartz", "formula": "SiO2",
        "note": "α-石英",
        "key": "SiO2_alpha"
    },
    "5-2_SiO2_cristobalite": {
        "name": "Cristobalite", "formula": "SiO2",
        "note": "方石英",
        "key": "SiO2_cristobalite"
    },
    "5-3_MgCO3": {
        "name": "Magnesite", "formula": "MgCO3",
        "note": "碳酸镁 / 菱镁矿",
        "key": "MgCO3"
    },
    "5-4_CaMg(CO3)2": {
        "name": "Dolomite", "formula": "CaMg(CO3)2",
        "note": "白云石",
        "key": "CaMg(CO3)2"
    },
    "5-5_Fe2O3": {
        "name": "Hematite", "formula": "Fe2O3",
        "note": "氧化铁 / 赤铁矿",
        "key": "Fe2O3"
    },
    "5-6_Muscovite": {
        "name": "Muscovite", "formula": "KAl2Si3O10(OH)2",
        "note": "白云母",
        "key": "Muscovite"
    },
    "5-7_Kaolinite": {
        "name": "Kaolinite", "formula": "Al2Si2O5(OH)4",
        "note": "高岭土",
        "key": "Kaolinite"
    },
    "7-1_Boehmite": {
        "name": "Boehmite", "formula": "AlO(OH)",
        "note": "一水软铝石",
        "key": "Boehmite"
    },
    "7-2_Goethite": {
        "name": "Goethite", "formula": "FeO(OH)",
        "note": "针铁矿",
        "key": "Goethite"
    },
    "7-3_Gibbsite": {
        "name": "Gibbsite", "formula": "Al(OH)3",
        "note": "三水铝石",
        "key": "Gibbsite"
    },
    "7-4_Feldspar": {
        "name": "Feldspar", "formula": "KNaCaAlSi3O8",
        "note": "长石",
        "key": "Feldspar"
    },
    "7-5_Albite": {
        "name": "Albite", "formula": "NaAlSi3O8",
        "note": "钠长石",
        "key": "Albite"
    },
    "7-6_Biotite": {
        "name": "Biotite", "formula": "K(Mg,Fe)3Si3O10(OH)2",
        "note": "黑云母",
        "key": "Biotite"
    },
    "7-7_Clinochlore": {
        "name": "Clinochlore", "formula": "(Mg,Fe)5Al(Si3Al)O10(OH)8",
        "note": "斜绿泥石",
        "key": "Clinochlore"
    },
    "7-8_Hornblende": {
        "name": "Hornblende", "formula": "Ca2(Mg,Fe,Al)5(Al,Si)8O22(OH,F)2",
        "note": "角闪石",
        "key": "Hornblende"
    },
    "7-9_Zircon": {
        "name": "Zircon", "formula": "ZrSiO4",
        "note": "锆石",
        "key": "Zircon"
    },
    "7-10_Ca2Al2SiO7": {
        "name": "Gehlenite", "formula": "Ca2Al2SiO7",
        "note": "钙铝黄长石",
        "key": "Gehlenite"
    },
    "7-11_Fluorapatite": {
        "name": "Fluorapatite", "formula": "Ca5(PO4)3F",
        "note": "氟磷灰石",
        "key": "Fluorapatite"
    },
}


def simulate_xrd_from_cif(cif_path: str, wavelength: float = 1.5406,
                          two_theta_range: tuple = (10.0, 90.0)):
    """从CIF文件模拟XRD图谱，返回峰信息列表。"""
    from pymatgen.core import Structure
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    struct = Structure.from_file(cif_path, occupancy_tolerance=1.1)
    calculator = XRDCalculator(wavelength=wavelength)
    pattern = calculator.get_pattern(struct, two_theta_range=two_theta_range)

    peaks = []
    for i in range(len(pattern.x)):
        hkl_info = pattern.hkls[i] if i < len(pattern.hkls) else []
        hkl = (0, 0, 0)
        if hkl_info:
            if isinstance(hkl_info[0], dict):
                raw_hkl = hkl_info[0].get("hkl", (0, 0, 0))
                if len(raw_hkl) >= 4:
                    hkl = (int(raw_hkl[0]), int(raw_hkl[1]), int(raw_hkl[3]))
                elif len(raw_hkl) >= 3:
                    hkl = (int(raw_hkl[0]), int(raw_hkl[1]), int(raw_hkl[2]))
                else:
                    hkl = (int(raw_hkl[0]), 0, 0)
            else:
                hkl = tuple(hkl_info[:3])

        d_hkl = float(pattern.d_hkls[i]) if i < len(pattern.d_hkls) else 0.0

        peaks.append({
            "hkl": list(hkl),
            "two_theta": round(float(pattern.x[i]), 4),
            "intensity": round(float(pattern.y[i]) if i < len(pattern.y) else 0.0, 2),
            "d_spacing": round(d_hkl, 4),
            "multiplicity": (
                hkl_info[0].get("multiplicity", 1)
                if hkl_info and isinstance(hkl_info[0], dict)
                else 1
            ),
        })

    # Normalize intensities to max=100
    if peaks:
        max_intensity = max(p["intensity"] for p in peaks)
        if max_intensity > 0:
            for p in peaks:
                p["intensity"] = round(p["intensity"] / max_intensity * 100.0, 2)

    # Get lattice parameters
    lattice = struct.lattice
    lattice_params = {
        "a": round(lattice.a, 4),
        "b": round(lattice.b, 4),
        "c": round(lattice.c, 4),
        "alpha": round(lattice.alpha, 4),
        "beta": round(lattice.beta, 4),
        "gamma": round(lattice.gamma, 4),
    }

    # Get space group
    try:
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
        analyzer = SpacegroupAnalyzer(struct)
        space_group = analyzer.get_space_group_symbol()
    except Exception:
        space_group = "Unknown"

    # Get composition formula
    formula = struct.composition.reduced_formula

    return {
        "peaks": peaks,
        "lattice": lattice_params,
        "space_group": space_group,
        "formula": formula,
        "num_atoms": len(struct),
        "volume": round(struct.volume, 2),
    }


def generate_pattern_plot(sim_result: dict, phase_name: str, output_path: str):
    """生成XRD图谱的可视化数据（JSON格式，用于后续绘制）。"""
    two_theta_min, two_theta_max = TWO_THETA_RANGE
    step = 0.01
    n_points = int((two_theta_max - two_theta_min) / step) + 1
    two_theta_grid = np.linspace(two_theta_min, two_theta_max, n_points)

    intensity = np.zeros(n_points)
    fwhm_to_sigma = 2.355
    peak_width = 0.15

    for peak in sim_result["peaks"]:
        two_theta_pos = peak["two_theta"]
        intensity_val = peak["intensity"]
        if two_theta_min <= two_theta_pos <= two_theta_max:
            sigma = peak_width / fwhm_to_sigma
            contribution = intensity_val * np.exp(
                -0.5 * ((two_theta_grid - two_theta_pos) / sigma) ** 2
            )
            intensity += contribution

    if intensity.max() > 0:
        intensity = intensity / intensity.max() * 100.0

    pattern_data = {
        "phase_name": phase_name,
        "two_theta_range": list(TWO_THETA_RANGE),
        "wavelength": WAVELENGTH,
        "two_theta": two_theta_grid.tolist(),
        "intensity": intensity.tolist(),
        "peaks": sim_result["peaks"],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pattern_data, f)

    return pattern_data


def main():
    print("=" * 70)
    print("PolyXRD XRD Pattern Generator from COD CIF Files")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load existing database
    existing_db = {"version": "0.4.0", "wavelength": 1.5406, "phases": []}
    if os.path.exists(DB_PATH):
        with open(DB_PATH, "r", encoding="utf-8") as f:
            existing_db = json.load(f)
        print(f"Loaded existing database: {len(existing_db.get('phases', []))} phases")

    existing_keys = {p.get("key", "") for p in existing_db.get("phases", [])}
    print(f"Existing phase keys: {len(existing_keys)}")

    all_results = []
    generated_count = 0
    failed_count = 0
    skipped_count = 0

    for phase_dir_name in sorted(os.listdir(CIF_DIR)):
        phase_dir = os.path.join(CIF_DIR, phase_dir_name)
        if not os.path.isdir(phase_dir):
            continue

        meta = PHASE_META.get(phase_dir_name, {})
        if not meta:
            print(f"\n[SKIP] {phase_dir_name}: no metadata")
            skipped_count += 1
            continue

        key = meta.get("key", "")
        if key in existing_keys:
            print(f"\n[SKIP] {phase_dir_name} ({key}): already in database")
            skipped_count += 1
            continue

        cif_files = [f for f in os.listdir(phase_dir) if f.endswith(".cif")]
        if not cif_files:
            print(f"\n[WARN] {phase_dir_name}: no CIF files")
            failed_count += 1
            continue

        print(f"\n{'─' * 60}")
        print(f"Processing: {phase_dir_name} ({meta.get('name', '')})")
        print(f"  CIF files found: {len(cif_files)}")

        # Try each CIF file until one works
        sim_result = None
        used_cif = None
        for cif_file in cif_files:
            cif_path = os.path.join(phase_dir, cif_file)
            try:
                sim_result = simulate_xrd_from_cif(cif_path, WAVELENGTH, TWO_THETA_RANGE)
                used_cif = cif_file
                print(f"  ✓ Success: {cif_file} ({len(sim_result['peaks'])} peaks)")
                break
            except Exception as e:
                print(f"  ✗ Failed: {cif_file} - {str(e)[:80]}")

        if sim_result is None:
            print(f"  ✗ All CIF files failed for {phase_dir_name}")
            failed_count += 1
            continue

        # Generate pattern plot data
        pattern_path = os.path.join(OUTPUT_DIR, f"{phase_dir_name}_pattern.json")
        generate_pattern_plot(sim_result, meta.get("name", ""), pattern_path)

        # Build database entry
        db_entry = {
            "key": meta.get("key", phase_dir_name),
            "name": meta.get("name", phase_dir_name),
            "formula": meta.get("formula", sim_result["formula"]),
            "space_group": sim_result["space_group"],
            "lattice": sim_result["lattice"],
            "peaks": sim_result["peaks"],
            "note": meta.get("note", ""),
            "cif_source": used_cif,
            "cod_phase": phase_dir_name,
            "wavelength": WAVELENGTH,
        }

        existing_db["phases"].append(db_entry)
        all_results.append({
            "phase_dir": phase_dir_name,
            "name": meta.get("name", ""),
            "cif_file": used_cif,
            "peaks_count": len(sim_result["peaks"]),
            "space_group": sim_result["space_group"],
            "lattice": sim_result["lattice"],
            "status": "ok",
        })
        generated_count += 1

    # Save updated database
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_db, f, indent=2, ensure_ascii=False)

    # Save generation report
    report = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "wavelength": WAVELENGTH,
        "two_theta_range": list(TWO_THETA_RANGE),
        "total_phases_processed": len(all_results) + skipped_count + failed_count,
        "generated": generated_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "results": all_results,
    }

    report_path = os.path.join(OUTPUT_DIR, "generation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"GENERATION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Generated: {generated_count} new phases")
    print(f"  Skipped:   {skipped_count} (already exist or no metadata)")
    print(f"  Failed:    {failed_count}")
    print(f"  Total DB:  {len(existing_db['phases'])} phases")
    print(f"  Output:    {OUTPUT_DIR}")
    print(f"  Database:  {DB_PATH}")

    for r in all_results:
        print(f"    ✓ {r['phase_dir']}: {r['peaks_count']} peaks, SG={r['space_group']}")

    return generated_count


if __name__ == "__main__":
    n = main()
    print(f"\n{n} phases generated successfully.")