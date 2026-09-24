"""v0.15 M25 FullProf 集成单测
================================

- dat/pcr 生成器纯函数 (含 PCR 格式红线: SG 锚点/7-token UVW/
  Limits 两行/编码 ASCII);
- runner 解析器 (.sum R 因子/物相表, .out SumYcal 表格, 符号表限位
  编号发现), fp2k 本体不参与 (Popen 边界在 runner.run 内, 不 mock 进程
  只喂样例文本)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.fullprof.dat_builder import build_dat, data_grid
from polyxrd.services.fullprof.pcr_builder import build_pcr, normalize_space_group
from polyxrd.services.fullprof.runner import (
    FullProfResult,
    discover_limit_numbers,
    parse_sum,
    parse_sums,
)


@pytest.fixture()
def zno() -> Phase:
    return Phase(
        name="ZnO", formula="ZnO", space_group="P 63 m c",
        lattice=LatticeParams(a=3.2495, b=3.2495, c=5.2069,
                              alpha=90.0, beta=90.0, gamma=120.0),
        atomic_sites=[
            {"type_symbol": "Zn", "fract_x": 1 / 3, "fract_y": 2 / 3,
             "fract_z": 0.0, "occupancy": 1.0},
            {"type_symbol": "O", "fract_x": 1 / 3, "fract_y": 2 / 3,
             "fract_z": 0.3819, "occupancy": 1.0},
        ],
    )


@pytest.fixture()
def spectrum() -> XRDData:
    x = np.arange(15.0, 50.0, 0.02)
    y = 40.0 + 100.0 * np.exp(-0.5 * ((x - 31.8) / 0.06) ** 2)
    return XRDData(two_theta=x, intensity=y, wavelength=1.54056)


# ── dat_builder ──────────────────────────────────────────────────

def test_data_grid_from_spectrum(spectrum):
    thmin, step, thmax = data_grid(spectrum)
    assert thmin == pytest.approx(15.0)
    assert thmax == pytest.approx(49.98)
    assert step == pytest.approx(0.02)


def test_build_dat_free_format(tmp_path, spectrum):
    out = build_dat(spectrum, tmp_path / "t.dat", title="T")
    text = out.read_text(encoding="ascii")
    assert "! T" in text
    # 头部注释后应有 thmin/step/thmax 行
    data_lines = [l for l in text.splitlines()
                  if l.strip() and not l.startswith(("!", "#")) and " " in l]
    first = data_lines[0].split()
    assert len(first) == 3
    assert float(first[0]) == pytest.approx(15.0)
    assert float(first[1]) == pytest.approx(0.02)


# ── pcr_builder ──────────────────────────────────────────────────

def test_normalize_space_group_variants():
    assert normalize_space_group("P6_3/mmc") == "P 63/mmc"
    assert normalize_space_group("Fm-3m") == "F m -3 m"
    assert normalize_space_group("P 63 m c") == "P 63 m c"  # 已规范化
    assert normalize_space_group("") == "P 1"


def test_build_pcr_format_redlines(tmp_path, zno, spectrum):
    """PCR 格式红线: SG 锚点行、UVW codes 7 token、Limits 两行、ASCII。"""
    thmin, step, thmax = data_grid(spectrum)
    out = build_pcr([zno], tmp_path / "t.pcr", thmin=thmin, thmax=thmax,
                    step=step, scale=1.0e-3)
    raw = out.read_bytes()
    raw.decode("ascii")  # 全 ASCII (fp2k 对非 ASCII 敏感)

    text = raw.decode("ascii")
    assert "<--Space group symbol" in text
    assert "Limits for selected parameters" in text
    limits = text.split("Limits for selected parameters")[1].splitlines()
    nonempty = [l for l in limits[:4]
                if l.strip() and not l.strip().endswith(":")
                and not l.startswith("!")]
    assert len(nonempty) == 2  # 恒两行: 少于两行 fp2k 会把 2Th 行当 limit 记录
    # UVW codes 行 (W 列非 0 的那行) 必须恰好 7 个 token
    uvw = [l for l in text.splitlines() if l.split() and
           l.split()[0].replace(".", "").isdigit() and len(l.split()) == 7]
    assert uvw, "应存在 7-token codes 行"
    # U2,V2,W2 与 λ1 同构 (U2=V2=0)
    u2_line = [l for l in text.splitlines() if "U2,V2,W2" in l][0]
    vals = u2_line.split()[:3]
    assert float(vals[0]) == 0.0 and float(vals[1]) == 0.0


def test_build_pcr_fix_all_and_fix_cell(tmp_path, zno, spectrum):
    thmin, step, thmax = data_grid(spectrum)
    kw = dict(thmin=thmin, thmax=thmax, step=step)
    p_all = build_pcr([zno], tmp_path / "a.pcr", fix_all=True, scale=1.0, **kw)
    t_all = p_all.read_text()
    assert " 0.0" in t_all  # 全固定
    p_cell = build_pcr([zno], tmp_path / "b.pcr", fix_cell=True, scale=1.0, **kw)
    t_cell = p_cell.read_text()
    # fix_cell: 晶胞行 codes 全 0 (值行后第一行)
    assert "      0.0         0.0         0.0" in t_cell


def test_build_pcr_w_initial(tmp_path, zno, spectrum):
    thmin, step, thmax = data_grid(spectrum)
    out = build_pcr([zno], tmp_path / "w.pcr", w_initial=0.025, **dict(
        thmin=thmin, thmax=thmax, step=step))
    assert "0.025000" in out.read_text()


def test_build_pcr_limit_numbers(tmp_path, zno, spectrum):
    thmin, step, thmax = data_grid(spectrum)
    out = build_pcr([zno], tmp_path / "l.pcr", limit_zero_no=97,
                    limit_w_no=98, **dict(thmin=thmin, thmax=thmax, step=step))
    text = out.read_text()
    assert "\n  97     -0.5000" in text
    assert "\n  98      0.0001" in text


# ── runner 解析器 (样例文本, 无真实 fp2k) ─────────────────────────

def test_parse_sum_factors_and_phases(tmp_path):
    sum_text = (
        "=> Rp: 12.5 Rwp: 15.3 Rexp: 6.2 Chi2: 6.08\n"
        "=> Phase:  1     ZnO\n"
        "=> Bragg R-factor:  25.8  Vol:  47.615( 0.02) Fract(%): 100.00\n"
        " => Run finished at:     Date: 20/09/2026  Time: 09:00:00\n"
    )
    p = tmp_path / "t.sum"
    p.write_text(sum_text, encoding="utf-8")
    d = parse_sum(p)
    assert d["rp"] == pytest.approx(12.5)
    assert d["rwp"] == pytest.approx(15.3)
    assert d["rexp"] == pytest.approx(6.2)
    assert d["chi2"] == pytest.approx(6.08)
    assert d["finished"] is True
    assert d["phases"][0]["name"] == "ZnO"
    assert d["phases"][0]["vol"] == pytest.approx(47.615)
    assert d["phases"][0]["fract"] == pytest.approx(100.0)


def test_parse_sums_first_table(tmp_path):
    """必须取第一张 SumYdif/SumYobs/SumYcal 表 (第二张是 Bragg-only)。"""
    out_text = (
        " =>    SumYdif       SumYobs      SumYcal      SumwYobsSQ     Residual    Condition\n"
        "     0.6521E+06    0.8020E+06    0.9218E+09    0.8020E+06    0.8566E+06    0.2262E+14\n"
        " ==> RELIABILITY FACTORS FOR POINTS WITH BRAGG CONTRIBUTIONS\n"
        " =>    SumYdif       SumYobs      SumYcal      SumwYobsSQ     Residual    Condition\n"
        "     0.4187E+06    0.5685E+06    0.5685E+06    0.5685E+06    0.6232E+06    0.2262E+14\n"
    )
    p = tmp_path / "t.out"
    p.write_text(out_text, encoding="utf-8")
    yobs, ycal = parse_sums(p)
    assert yobs == pytest.approx(0.8020e6)
    assert ycal == pytest.approx(0.9218e9)


def test_parse_sums_missing(tmp_path):
    p = tmp_path / "none.out"
    p.write_text("nothing here", encoding="utf-8")
    assert parse_sums(p) == (None, None)


def test_discover_limit_numbers():
    """SYMBOLIC NAMES 表 → 限位编号 (1 相实测 Zero=2, W-Cagl=7)。"""
    out_text = (
        "      ->  Parameter number    1   -> Symbolic Name:      Cell_A_ph1_pat1     3.2495000\n"
        "      ->  Parameter number    2   -> Symbolic Name:            Zero_pat1     0.0000000\n"
        "      ->  Parameter number    6   -> Symbolic Name:       Scale_ph1_pat1    0.10000000E-02\n"
        "      ->  Parameter number    7   -> Symbolic Name:    W-Cagl_ph1_pat1    0.60000001E-02\n"
        "      ->  Parameter number    8   -> Symbolic Name:      Cell_C_ph1_pat1     5.2069001\n"
    )
    from pathlib import Path as P

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = P(td) / "t.out"
        p.write_text(out_text, encoding="utf-8")
        zero_no, w_no = discover_limit_numbers(p)
    assert zero_no == 2
    assert w_no == 7


def test_fullprof_result_defaults():
    r = FullProfResult()
    assert r.ok is False
    assert r.phases == []
