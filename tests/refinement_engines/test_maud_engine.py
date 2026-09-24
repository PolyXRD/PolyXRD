"""
测试 polyxrd.services.refinement_engines.maud_engine (R-C3/R-C4)

测试分两层:
1. 纯函数层: _format_xrd_data_as_xye, _parse_par_rfactors, _parse_tsv_results,
   _apply_tsv_to_phases, _to_float. 不依赖 MAUD / Java.
2. 集成层: MaudEngine.refine 用 mock subprocess 模拟 MAUD 输出. 不真跑 MAUD.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.refinement_engines import MaudEngine, MaudEngineError
from polyxrd.services.refinement_engines.maud_engine import (
    _apply_tsv_to_phases,
    _format_xrd_data_as_xye,
    _parse_par_rfactors,
    _parse_tsv_results,
    _to_float,
    MaudProgress,
)


# ====================================================================
# fixtures
# ====================================================================

@pytest.fixture
def synthetic_xrd_data() -> XRDData:
    """最小可用的 XRDData: 100 个数据点, Cu Kα, 0~50°"""
    tt = np.linspace(5.0, 50.0, 100)
    # 在 25.5° 加个假峰 (Al2O3 (012))
    intensity = 50 + 800 * np.exp(-((tt - 25.5) / 0.3) ** 2)
    intensity += 30 * np.exp(-((tt - 37.8) / 0.4) ** 2)  # (110) 类
    return XRDData(
        two_theta=tt,
        intensity=intensity,
        wavelength=1.5406,
    )


@pytest.fixture
def al2o3_phase() -> Phase:
    return Phase(
        name="corundum",
        formula="Al2O3",
        space_group="R -3 c :H",
        lattice=LatticeParams(a=4.7589, b=4.7589, c=12.991, alpha=90, beta=90, gamma=120),
        cif_path=None,  # 测试时由 fixture 注入
        weight_fraction=0.0,
    )


@pytest.fixture
def zro2_phase() -> Phase:
    return Phase(
        name="T-PSZ",
        formula="ZrO2",
        space_group="P 1 21/c 1",
        lattice=LatticeParams(a=3.642, b=3.642, c=5.270, alpha=90, beta=90, gamma=120),
        weight_fraction=0.0,
    )


def write_fake_par_with_rfactors(
    par_path: Path, rwp: float = 8.7, wrp: float = 9.05, gof: float = 1.3, n_iter: int = 20,
) -> None:
    """写一份带 R 字段的假 .par (只放关键行, 让 _parse_par_rfactors 拿到值).

    rwp/wrp 参数以 % 传入; MAUD .par 实际存小数, 这里做 /100 转换。
    """
    par_path.write_text(
        f"data_global\n"
        f"_refine_ls_R_factor_all {rwp / 100.0}\n"
        f"_refine_ls_wR_factor_all {wrp / 100.0}\n"
        f"_refine_ls_goodness_of_fit_all {gof}\n"
        f"_refine_ls_number_iteration {n_iter}\n"
        f"data_Sample_x\n"
        f"_pd_spec_description 'fake'\n"
    )


def write_fake_tsv(tsv_path: Path) -> None:
    """写一份带两个相的 MAUD 风格 TSV (复刻 alzrc 实测格式)"""
    tsv_path.write_text(
        "Title\tRwp(%)\tPhase_Name\tVol.(%)\terror(%)\tWt.(%)\terror(%)\t"
        "Cell_Par(Angstrom)\tCell_Par(Angstrom)\tSize(Angstrom)\tMicrostrain\t"
        "Phase_Name\tVol.(%)\terror(%)\tWt.(%)\terror(%)\t"
        "Cell_Par(Angstrom)\tCell_Par(Angstrom)\tSize(Angstrom)\tMicrostrain\n"
        "test\t8.730221\tcorundum\t82.426155\t0.31856802\t74.82885\t0.28920528\t"
        "4.758742\t12.990941\t4972.764\t2.3632713E-4\t"
        "T-PSZ\t17.573847\t0.053830028\t25.171148\t0.077101134\t"
        "3.6298525\t5.231013\t1249.2888\t0.0013892185\n"
    )


# ====================================================================
# 纯函数: _format_xrd_data_as_xye
# ====================================================================

class TestXyeWriter:
    def test_basic_format(self, tmp_path: Path, synthetic_xrd_data: XRDData):
        out = tmp_path / "in.xye"
        _format_xrd_data_as_xye(synthetic_xrd_data, out)
        assert out.exists()
        lines = out.read_text().strip().splitlines()
        # 无 header (MAUD ETH 读取器不认 '#' 注释行), 100 行纯数据
        assert len(lines) == 100
        # 数据行: 三列 (2θ, I, σ)
        parts = lines[0].split("\t")
        assert len(parts) == 3, f"应为三列, got {parts}"
        # np.linspace(5, 50, 100)[0] == 5.0 (精确)
        assert float(parts[0]) == pytest.approx(5.0)
        assert float(parts[1]) > 0
        assert float(parts[2]) >= 0  # σ = sqrt(I), 非负

    def test_length_mismatch_raises(self, tmp_path: Path):
        # XRDData.__post_init__ 也会拦截, 但引擎内层也再校验一次 (防外部构造)
        # 用 object.__new__ 绕开 __post_init__ 让引擎拿到"问题数据"
        bad = object.__new__(XRDData)
        bad.two_theta = np.array([1.0, 2.0, 3.0])
        bad.intensity = np.array([1.0, 2.0])  # 长度不一致
        bad.wavelength = 1.5406
        with pytest.raises(MaudEngineError, match="长度不一致"):
            _format_xrd_data_as_xye(bad, tmp_path / "bad.xye")

    def test_empty_data_raises(self, tmp_path: Path):
        # 绕开 XRDData.__post_init__ 让引擎拿到空数据
        empty = object.__new__(XRDData)
        empty.two_theta = np.array([])
        empty.intensity = np.array([])
        empty.wavelength = 1.5406
        with pytest.raises(MaudEngineError, match="为空"):
            _format_xrd_data_as_xye(empty, tmp_path / "empty.xye")

    def test_negative_intensity_clamped(self, tmp_path: Path):
        """σ = sqrt(max(I, 0)), 不能让负数开方"""
        # 绕开 XRDData.__post_init__ 让"负强度"也能进入引擎
        weird = object.__new__(XRDData)
        weird.two_theta = np.array([10.0, 20.0])
        weird.intensity = np.array([100.0, -5.0])  # 第二点负 (基线扣除过度)
        weird.wavelength = 1.5406
        out = tmp_path / "weird.xye"
        _format_xrd_data_as_xye(weird, out)
        lines = out.read_text().strip().splitlines()
        # 第二点 σ 应该是 sqrt(0)=0 (被钳到 0)
        assert float(lines[1].split("\t")[2]) == 0.0


# ====================================================================
# 纯函数: _parse_par_rfactors
# ====================================================================

class TestParRfactorParser:
    def test_basic_extraction(self, tmp_path: Path):
        p = tmp_path / "r.par"
        write_fake_par_with_rfactors(p, rwp=8.7, wrp=9.05, gof=1.3, n_iter=20)
        rf = _parse_par_rfactors(p)
        assert rf["rwp"] == pytest.approx(8.7)
        assert rf["wrp"] == pytest.approx(9.05)
        assert rf["gof"] == pytest.approx(1.3)
        assert rf["iterations"] == 20

    def test_missing_file_returns_none(self, tmp_path: Path):
        rf = _parse_par_rfactors(tmp_path / "nope.par")
        assert all(v is None for v in rf.values())

    def test_partial_fields(self, tmp_path: Path):
        """只写了 R_factor, 其他缺失 → 应得 None 而非崩"""
        p = tmp_path / "partial.par"
        p.write_text("data_global\n_refine_ls_R_factor_all 0.055\n")
        rf = _parse_par_rfactors(p)
        assert rf["rwp"] == pytest.approx(5.5)  # par 小数 → 引擎统一转 %
        assert rf["wrp"] is None
        assert rf["gof"] is None
        assert rf["iterations"] is None


# ====================================================================
# 纯函数: _parse_tsv_results
# ====================================================================

class TestTsvParser:
    def test_two_phase_parsing(self, tmp_path: Path):
        p = tmp_path / "results.tsv"
        write_fake_tsv(p)
        entries = _parse_tsv_results(p)
        assert len(entries) == 2
        assert entries[0]["name"] == "corundum"
        assert entries[0]["wt_pct"] == pytest.approx(74.82885)
        assert entries[0]["vol_pct"] == pytest.approx(82.426155)
        assert entries[0]["cell_a"] == pytest.approx(4.758742)
        assert entries[0]["cell_b_or_c"] == pytest.approx(12.990941)
        assert entries[1]["name"] == "T-PSZ"
        assert entries[1]["wt_pct"] == pytest.approx(25.171148)

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert _parse_tsv_results(tmp_path / "nope.tsv") == []

    def test_only_header_returns_empty(self, tmp_path: Path):
        p = tmp_path / "header_only.tsv"
        p.write_text("Title\tRwp(%)\tPhase_Name\n")
        assert _parse_tsv_results(p) == []

    def test_truncated_row_skipped(self, tmp_path: Path):
        """MAUD 偶发末尾空列 (短行) → 解析跳到该相, 不崩"""
        p = tmp_path / "trunc.tsv"
        # 短行: name="" 且所有数值列都缺 → 应被跳过
        p.write_text(
            "Title\tRwp(%)\tPhase_Name\tVol.(%)\tWt.(%)\tCell\n"
            "test\t5.0\t\t\t\t\n"  # 6 列, name 空, 数值列缺
        )
        assert _parse_tsv_results(p) == []

    def test_partial_row_kept_with_available_fields(self, tmp_path: Path):
        """行部分有效 (有 name + wt_pct 但缺 cell) → 仍入条目, 缺字段为 None"""
        p = tmp_path / "partial.tsv"
        # name=i+0, vol=i+1, err_vol=i+2, wt=i+3, err_wt=i+4, cell_a=i+5, ...
        # 想要 wt=80, cell_a=None: name=corundum(i=2), vol=""(3), err_vol=""(4),
        # wt="80"(5), err_wt=""(6), cell_a=""(7), cell_b=""(8)
        p.write_text(
            "Title\tRwp(%)\tPhase_Name\tVol.(%)\terror(%)\tWt.(%)\terror(%)\t"
            "Cell_Par(Angstrom)\tCell_Par(Angstrom)\n"
            "test\t5.0\tcorundum\t\t\t80\t\t\t\n"
        )
        entries = _parse_tsv_results(p)
        assert len(entries) == 1
        assert entries[0]["name"] == "corundum"
        assert entries[0]["wt_pct"] == pytest.approx(80.0)
        assert entries[0]["cell_a"] is None  # 缺


# ====================================================================
# 纯函数: _apply_tsv_to_phases
# ====================================================================

class TestTsvApplyToPhases:
    def test_apply_weight_fraction_and_lattice(self, al2o3_phase: Phase):
        tsv = [
            {
                "name": "corundum",
                "vol_pct": 82.4,
                "wt_pct": 74.8,
                "cell_a": 4.7589,
                "cell_b_or_c": 12.991,
                "size_a": 5000.0,
                "microstrain": 1e-4,
            }
        ]
        _apply_tsv_to_phases([al2o3_phase], tsv)
        assert al2o3_phase.weight_fraction == pytest.approx(74.8)
        # Al2O3 是六方/三角: cell_b_or_c 是 c
        assert al2o3_phase.lattice.a == pytest.approx(4.7589)
        assert al2o3_phase.lattice.c == pytest.approx(12.991)
        assert al2o3_phase.lattice.b == pytest.approx(4.7589)  # b=a, 未动

    def test_no_match_leaves_phase_unchanged(self, al2o3_phase: Phase):
        original_a = al2o3_phase.lattice.a
        original_wt = al2o3_phase.weight_fraction
        _apply_tsv_to_phases([al2o3_phase], [])
        assert al2o3_phase.lattice.a == original_a
        assert al2o3_phase.weight_fraction == original_wt

    def test_cubic_lattice_assignment(self):
        cu = Phase(
            name="Cu",
            formula="Cu",
            lattice=LatticeParams(a=3.615, b=3.615, c=3.615, alpha=90, beta=90, gamma=90),
            weight_fraction=0.0,
        )
        tsv = [{
            "name": "Cu", "vol_pct": 100, "wt_pct": 100.0,
            "cell_a": 3.620, "cell_b_or_c": 3.625,  # MAUD 偶尔这样报
            "size_a": 500.0, "microstrain": 0.0,
        }]
        _apply_tsv_to_phases([cu], tsv)
        assert cu.lattice.a == pytest.approx(3.620)
        # 立方: cell_b_or_c 被赋给 c
        assert cu.lattice.c == pytest.approx(3.625)
        assert cu.lattice.b == pytest.approx(3.615)  # 不动
        assert cu.weight_fraction == pytest.approx(100.0)

    def test_orthorhombic_lattice_assignment(self):
        ortho = Phase(
            name="ortho",
            formula="ABC",
            lattice=LatticeParams(a=4.0, b=5.0, c=6.0, alpha=90, beta=90, gamma=90),
            weight_fraction=0.0,
        )
        tsv = [{
            "name": "ortho", "wt_pct": 50.0,
            "cell_a": 4.1, "cell_b_or_c": 5.1,  # 给 b
        }]
        _apply_tsv_to_phases([ortho], tsv)
        assert ortho.lattice.a == pytest.approx(4.1)
        assert ortho.lattice.b == pytest.approx(5.1)
        assert ortho.lattice.c == pytest.approx(6.0)  # 未动


# ====================================================================
# 纯函数: _to_float
# ====================================================================

class TestToFloat:
    def test_normal_number(self):
        assert _to_float(["1.0", "2.5", "3"], 1) == 2.5

    def test_scientific_notation(self):
        assert _to_float(["1.0E-4"], 0) == pytest.approx(1e-4)

    def test_empty_string_returns_none(self):
        assert _to_float(["1.0", "", "3"], 1) is None

    def test_out_of_range_returns_none(self):
        assert _to_float(["1.0"], 5) is None

    def test_non_numeric_returns_none(self):
        assert _to_float(["abc"], 0) is None


# ====================================================================
# MaudEngine.prepare_workdir
# ====================================================================

class TestPrepareWorkdir:
    def test_raises_without_cif(self, tmp_path: Path, synthetic_xrd_data: XRDData,
                                 al2o3_phase: Phase):
        """Phase 没有 cif_path / cod_id 时应抛错 (路线 B 接入前)"""
        al2o3_phase.cif_path = None
        with patch(
            "polyxrd.services.refinement_engines.maud_engine.detect_maud_root",
            return_value=tmp_path / "fake_maud",
        ):
            # 不创建 fake_maud, 但因为先抛错, 不该走到 java 检查
            engine = object.__new__(MaudEngine)
            engine.maud_root = tmp_path / "fake_maud"
            engine.template_par = tmp_path / "tpl.par"
            engine.template_par.write_text("dummy")
            with pytest.raises(MaudEngineError, match="没有 CIF"):
                engine.prepare_workdir(synthetic_xrd_data, [al2o3_phase], work_dir=tmp_path / "wd")

    def test_writes_xye_and_ins(self, tmp_path: Path, synthetic_xrd_data: XRDData,
                                 al2o3_phase: Phase, bundle_template):
        # 给 phase 一个真实可用的 CIF (test_corundum.cif)
        cif = tmp_path / "corundum.cif"
        cif.write_text(
            "data_global\n_chemical_formula_sum 'Al2 O3'\n"
            "_cell_length_a 4.758\n_cell_length_c 12.991\n"
        )
        al2o3_phase.cif_path = str(cif)
        wd = tmp_path / "wd"
        wd.mkdir()

        engine = object.__new__(MaudEngine)
        engine.maud_root = tmp_path / "fake_maud"
        engine.template_par = bundle_template

        artifacts = engine.prepare_workdir(
            synthetic_xrd_data, [al2o3_phase],
            iterations=10, wizard_index=None,
            work_dir=wd,
        )
        assert artifacts.ins_path.exists()
        assert (wd / "input.xye").exists()
        assert (wd / "corundum.cif").exists()
        assert (wd / "maud_default.par").exists()  # 模板副本

    def test_empty_phases_raises(self, tmp_path: Path, synthetic_xrd_data: XRDData):
        engine = object.__new__(MaudEngine)
        engine.maud_root = tmp_path / "fake_maud"
        engine.template_par = tmp_path / "tpl.par"
        engine.template_par.write_text("dummy")
        with pytest.raises(MaudEngineError, match="phases 不能为空"):
            engine.prepare_workdir(synthetic_xrd_data, [], work_dir=tmp_path / "wd")


# ====================================================================
# MaudEngine.run (mock subprocess)
# ====================================================================

def make_fake_maud_root(base: Path) -> Path:
    """建一个假 MAUD 安装根: 含 jdk/bin/java.exe + lib/, 绕过 build_maud_command 的存在性检查"""
    maud = base / "fake_maud"
    (maud / "jdk" / "bin").mkdir(parents=True)
    (maud / "jdk" / "bin" / "java.exe").write_bytes(b"")  # 假二进制
    (maud / "lib").mkdir()
    (maud / "lib" / "x.jar").write_bytes(b"")
    return maud


class TestRun:
    def test_successful_run(self, tmp_path: Path, bundle_template):
        maud_root = make_fake_maud_root(tmp_path)
        engine = object.__new__(MaudEngine)
        engine.maud_root = maud_root
        engine.template_par = bundle_template

        # 构造 artifacts (复用真实 write_ins_file)
        cif = tmp_path / "c.cif"
        cif.write_text("data_global\n")
        xye = tmp_path / "x.xye"
        xye.write_text("# dummy\n10.0 100 10.0\n")
        from polyxrd.services.maud_par_builder import MaudInsConfig, write_ins_file
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=xye,
            cif_paths=[cif], iterations=3, work_dir=tmp_path / "wd",
        )
        artifacts = write_ins_file(cfg)

        # mock subprocess.run: 写一份假 .par + .tsv 模拟 MAUD 完成
        def fake_run(cmd, **kw):
            # 模拟 MAUD 完成: 写 .par + .tsv
            write_fake_par_with_rfactors(artifacts.output_par_path)
            write_fake_tsv(artifacts.output_tsv_path)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout="(MAUD finished)", stderr="",
            )

        with patch("subprocess.run", side_effect=fake_run):
            proc = engine.run(artifacts, timeout_s=30.0)

        assert proc.returncode == 0
        assert artifacts.output_par_path.exists()
        assert artifacts.output_tsv_path.exists()

    def test_nonzero_return_raises(self, tmp_path: Path, bundle_template):
        maud_root = make_fake_maud_root(tmp_path)
        engine = object.__new__(MaudEngine)
        engine.maud_root = maud_root
        engine.template_par = bundle_template

        cif = tmp_path / "c.cif"
        cif.write_text("data_global\n")
        xye = tmp_path / "x.xye"
        xye.write_text("# dummy\n10.0 100 10.0\n")
        from polyxrd.services.maud_par_builder import MaudInsConfig, write_ins_file
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=xye,
            cif_paths=[cif], iterations=3, work_dir=tmp_path / "wd",
        )
        artifacts = write_ins_file(cfg)

        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="", stderr="JVM crash",
            )

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(MaudEngineError, match="exit=1"):
                engine.run(artifacts)

    def test_timeout_raises(self, tmp_path: Path, bundle_template):
        maud_root = make_fake_maud_root(tmp_path)
        engine = object.__new__(MaudEngine)
        engine.maud_root = maud_root
        engine.template_par = bundle_template

        cif = tmp_path / "c.cif"
        cif.write_text("data_global\n")
        xye = tmp_path / "x.xye"
        xye.write_text("# dummy\n10.0 100 10.0\n")
        from polyxrd.services.maud_par_builder import MaudInsConfig, write_ins_file
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=xye,
            cif_paths=[cif], iterations=3, work_dir=tmp_path / "wd",
        )
        artifacts = write_ins_file(cfg)

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["java"], timeout=1.0),
        ):
            with pytest.raises(MaudEngineError, match="超时"):
                engine.run(artifacts, timeout_s=1.0)

    def test_progress_callback_invoked(self, tmp_path: Path, bundle_template):
        """on_progress 应被调用一次 (跑完时)"""
        maud_root = make_fake_maud_root(tmp_path)
        engine = object.__new__(MaudEngine)
        engine.maud_root = maud_root
        engine.template_par = bundle_template

        cif = tmp_path / "c.cif"
        cif.write_text("data_global\n")
        xye = tmp_path / "x.xye"
        xye.write_text("# dummy\n10.0 100 10.0\n")
        from polyxrd.services.maud_par_builder import MaudInsConfig, write_ins_file
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=xye,
            cif_paths=[cif], iterations=3, work_dir=tmp_path / "wd",
        )
        artifacts = write_ins_file(cfg)

        def fake_run(cmd, **kw):
            write_fake_par_with_rfactors(artifacts.output_par_path, wrp=12.0, n_iter=10)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        progress_calls: list[MaudProgress] = []
        with patch("subprocess.run", side_effect=fake_run):
            engine.run(artifacts, on_progress=lambda p: progress_calls.append(p))

        assert len(progress_calls) == 1
        assert progress_calls[0].wrp_percent == pytest.approx(12.0)
        assert progress_calls[0].note == "finished"


# ====================================================================
# MaudEngine.refine (端到端 mock)
# ====================================================================

@pytest.fixture
def bundle_template():
    from polyxrd.services.maud_par_builder import get_default_template_path
    return get_default_template_path()


class TestRefineEndToEnd:
    def test_end_to_end_with_mock(
        self, tmp_path: Path, synthetic_xrd_data: XRDData,
        al2o3_phase: Phase, zro2_phase: Phase, bundle_template,
    ):
        # 两相 CIF
        cif_al = tmp_path / "corundum.cif"
        cif_al.write_text("data_global\n_chemical_formula_sum 'Al2 O3'\n")
        cif_zr = tmp_path / "tpsz.cif"
        cif_zr.write_text("data_global\n_chemical_formula_sum 'Zr O2'\n")
        al2o3_phase.cif_path = str(cif_al)
        zro2_phase.cif_path = str(cif_zr)

        maud_root = make_fake_maud_root(tmp_path)
        engine = object.__new__(MaudEngine)
        engine.maud_root = maud_root
        engine.template_par = bundle_template

        wd = tmp_path / "e2e_wd"
        wd.mkdir()

        # mock subprocess.run + 在 run 之后写假 .par / .tsv
        def fake_run(cmd, **kw):
            # kw['cwd'] 是 work_dir
            cwd = Path(kw["cwd"])
            par = cwd / "refined.par"
            tsv = cwd / "results.tsv"
            write_fake_par_with_rfactors(par, rwp=8.7, wrp=9.05, gof=1.3, n_iter=20)
            write_fake_tsv(tsv)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="ok", stderr="",
            )

        with patch("subprocess.run", side_effect=fake_run):
            result = engine.refine(
                synthetic_xrd_data, [al2o3_phase, zro2_phase],
                iterations=10, keep_workdir=True,
            )

        assert isinstance(result, RefinementResult)
        assert result.wR == pytest.approx(9.05)
        assert result.GOF == pytest.approx(1.3)
        assert result.num_cycles == 20
        assert result.converged is True  # wrp=9.05 < 50
        assert result.fit_params["engine"] == "maud"
        # 相回写: Wt% 从 TSV
        assert al2o3_phase.weight_fraction == pytest.approx(74.82885)
        assert zro2_phase.weight_fraction == pytest.approx(25.171148)
        # Al2O3 晶胞 a/c 被 TSV 更新
        assert al2o3_phase.lattice.a == pytest.approx(4.758742)
        assert al2o3_phase.lattice.c == pytest.approx(12.990941)

    def test_engine_error_propagates(
        self, tmp_path: Path, synthetic_xrd_data: XRDData,
        al2o3_phase: Phase, bundle_template,
    ):
        cif = tmp_path / "c.cif"
        cif.write_text("data_global\n")
        al2o3_phase.cif_path = str(cif)

        maud_root = make_fake_maud_root(tmp_path)
        engine = object.__new__(MaudEngine)
        engine.maud_root = maud_root
        engine.template_par = bundle_template

        wd = tmp_path / "wd2"
        wd.mkdir()

        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(
                args=cmd, returncode=99, stdout="", stderr="crash",
            )

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(MaudEngineError):
                engine.refine(
                    synthetic_xrd_data, [al2o3_phase],
                    iterations=5, keep_workdir=True,
                )

    def test_refine_with_progress_callback(
        self, tmp_path: Path, synthetic_xrd_data: XRDData,
        al2o3_phase: Phase, bundle_template,
    ):
        cif = tmp_path / "c.cif"
        cif.write_text("data_global\n")
        al2o3_phase.cif_path = str(cif)

        maud_root = make_fake_maud_root(tmp_path)
        engine = object.__new__(MaudEngine)
        engine.maud_root = maud_root
        engine.template_par = bundle_template

        progress_calls: list[MaudProgress] = []

        def fake_run(cmd, **kw):
            write_fake_par_with_rfactors(
                Path(kw["cwd"]) / "refined.par", wrp=7.5, n_iter=15,
            )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = engine.refine(
                synthetic_xrd_data, [al2o3_phase],
                iterations=10, keep_workdir=True,
                on_progress=lambda p: progress_calls.append(p),
            )

        assert result.wR == pytest.approx(7.5)
        assert len(progress_calls) == 1
        assert progress_calls[0].wrp_percent == pytest.approx(7.5)

    def test_init_validates_maud_root(self, tmp_path: Path):
        """init 时若 java.exe 不存在, 应抛错"""
        fake = tmp_path / "no_maud"
        fake.mkdir()
        with pytest.raises(MaudEngineError, match="不含 jdk/bin/java.exe"):
            MaudEngine(maud_root=fake)


# ====================================================================
# MaudProgress 数据类
# ====================================================================

class TestMaudProgress:
    def test_to_dict(self):
        p = MaudProgress(
            elapsed_seconds=10.5, rwp_percent=8.7,
            iterations=20, note="running",
        )
        d = p.to_dict()
        assert d["elapsed_seconds"] == 10.5
        assert d["rwp_percent"] == 8.7
        assert d["iterations"] == 20
        assert d["note"] == "running"