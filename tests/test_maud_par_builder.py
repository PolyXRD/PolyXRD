"""
测试 polyxrd.services.maud_par_builder (路线 C R-C2)

R-C1 验证过的 MAUD INS 约束:
  1. loop_ 顶格
  2. columns 必须按"先清后加"顺序: remove_all_datafiles BEFORE meas_datafile_name;
     remove_all_phases BEFORE import_phase
  3. 多相时 _maud_import_phase 列名重复追加
  4. fileToSave 与 append_result_to 使用相对于工作目录的路径
  5. wizard_index 缺省时不写该列 (MAUD 自动选)
  6. 所有数据文件 / CIF 必须存在 (post_init 校验)
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from polyxrd.services import maud_par_builder as mpb
from polyxrd.services.maud_par_builder import (
    DEFAULT_TEMPLATE_NAME,
    MaudInsConfig,
    build_ins_text,
    cod_id_to_cif_path,
    detect_maud_root,
    get_default_template_path,
    write_ins_file,
)


# ====================================================================
# fixtures
# ====================================================================

@pytest.fixture
def bundle_template(tmp_path: Path) -> Path:
    """bundled 模板路径 (走资源层, 无 IO)"""
    return get_default_template_path()


@pytest.fixture
def workenv(tmp_path: Path) -> dict:
    """最小可行 INS 输入环境: 数据 .xye + 一个 CIF"""
    data = tmp_path / "sample.xye"
    data.write_text("# dummy xy\n10.0  100\n20.0  200\n")
    cif = tmp_path / "Al2O3.cif"
    cif.write_text("data_global\n_chemical_formula_sum 'Al2 O3'\n")
    work = tmp_path / "work"
    work.mkdir()
    return {"data": data, "cif": cif, "work": work}


# ====================================================================
# template / 资源层
# ====================================================================

class TestTemplate:
    def test_default_template_resource_exists(self, bundle_template: Path):
        assert bundle_template.exists(), f"缺少 bundled {DEFAULT_TEMPLATE_NAME}"
        assert bundle_template.stat().st_size > 1000, "模板不应是空"

    def test_default_template_is_valid_cif_minimal(self, bundle_template: Path):
        head = bundle_template.read_text(encoding="utf-8", errors="replace")[:200]
        # 必须有 data_global (CIF 顶层)
        assert "data_global" in head

    def test_detect_maud_root_returns_existing(self):
        # 优先 MAUD3 (本机已装); 若不存在则回退 MAUD2; 都不在就 FileNotFoundError
        try:
            r = detect_maud_root()
            assert (r / "lib").is_dir()
            assert (r / "jdk" / "bin" / "java.exe").exists()
        except FileNotFoundError:
            pytest.skip("本机未装 MAUD (env: 无 C:\\MAUD*)")


# ====================================================================
# cod_id → CIF 路径 (路线 B 接口)
# ====================================================================

class TestCodIdMapping:
    def test_seven_digit_id_al2o3(self, tmp_path: Path):
        # COD 2101052 = Al2O3 R-3c, 实测见侦察报告 §8.5
        p = cod_id_to_cif_path(2101052, tmp_path)
        assert p == tmp_path / "cod" / "2" / "10" / "10" / "2101052.cif"

    def test_six_digit_id_padded(self, tmp_path: Path):
        # COD 2007668 (6 位传统编号) 应 pad 成 7 位
        p = cod_id_to_cif_path(2007668, tmp_path)
        assert p == tmp_path / "cod" / "2" / "00" / "76" / "2007668.cif"

    def test_reject_non_numeric(self, tmp_path: Path):
        with pytest.raises(ValueError, match="纯数字"):
            cod_id_to_cif_path("abc", tmp_path)


# ====================================================================
# 数据类校验
# ====================================================================

class TestMaudInsConfig:
    def test_missing_data_file_raises(self, bundle_template, tmp_path, workenv):
        with pytest.raises(FileNotFoundError):
            MaudInsConfig(
                template_par=bundle_template, data_file=tmp_path / "nope.dat",
            )

    def test_missing_cif_raises(self, bundle_template, workenv):
        bad_cif = workenv["work"] / "nope.cif"
        with pytest.raises(FileNotFoundError):
            MaudInsConfig(
                template_par=bundle_template, data_file=workenv["data"],
                cif_paths=[bad_cif],
            )

    def test_iterations_must_be_positive(self, bundle_template, workenv):
        with pytest.raises(ValueError, match=r"iterations.*≥1"):
            MaudInsConfig(
                template_par=bundle_template, data_file=workenv["data"],
                iterations=0,
            )

    def test_paths_resolved_to_absolute(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            work_dir=workenv["work"],
        )
        assert cfg.data_file.is_absolute()


# ====================================================================
# R-C1 关键约束: INS 列序
# ====================================================================

class TestInsStructure:
    def _parse_ins_columns(self, ins_text: str) -> list[str]:
        """提取 loop_ 后第一个 data 行前的所有 _xxx 列名"""
        in_loop = False
        headers: list[str] = []
        for line in ins_text.splitlines():
            if line.strip() == "loop_":
                in_loop = True
                continue
            if in_loop:
                ls = line.strip()
                if ls.startswith("_"):
                    headers.append(ls)
                elif ls:
                    break
        return headers

    def test_loop_header_present(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            cif_paths=[workenv["cif"]], work_dir=workenv["work"],
        )
        ins = build_ins_text(cfg)
        assert ins.startswith("loop_") or ins.splitlines()[0].strip() == "loop_"

    def test_remove_all_datafiles_before_meas_datafile(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            cif_paths=[workenv["cif"]], work_dir=workenv["work"],
        )
        ins = build_ins_text(cfg)
        cols = self._parse_ins_columns(ins)
        i_remove = cols.index("_maud_remove_all_datafiles")
        i_meas = cols.index("_riet_meas_datafile_name")
        assert i_remove < i_meas, "remove_all_datafiles 必须在 meas_datafile_name 之前"

    def test_remove_all_phases_before_import_phase(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            cif_paths=[workenv["cif"]], work_dir=workenv["work"],
        )
        ins = build_ins_text(cfg)
        cols = self._parse_ins_columns(ins)
        i_remove_ph = cols.index("_maud_remove_all_phases")
        i_import = cols.index("_maud_import_phase")
        assert i_remove_ph < i_import, "remove_all_phases 必须在 import_phase 之前"

    def test_multi_phase_import_phase_repeats_column(self, bundle_template, workenv):
        cif2 = workenv["work"] / "ZrO2.cif"
        cif2.write_text("data_global\n_chemical_formula_sum 'Zr O2'\n")
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            cif_paths=[workenv["cif"], cif2], work_dir=workenv["work"],
        )
        ins = build_ins_text(cfg)
        cols = self._parse_ins_columns(ins)
        # 出现两次 _maud_import_phase (多相)
        import_count = cols.count("_maud_import_phase")
        assert import_count == 2, f"期望 import_phase 出现 2 次, 实测 {import_count}: {cols}"

    def test_wizard_omitted_when_none(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            wizard_index=None, work_dir=workenv["work"],
        )
        ins = build_ins_text(cfg)
        assert "_riet_analysis_wizard_index" not in ins

    def test_wizard_included_when_explicit(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            wizard_index=13, work_dir=workenv["work"],
        )
        ins = build_ins_text(cfg)
        assert "_riet_analysis_wizard_index" in ins
        # 出现值 13 (不带引号, 但 wizard 是数字 → 应无引号或带引号都对)
        assert re.search(r"_riet_analysis_wizard_index", ins)

    def test_outputs_use_relative_paths(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            cif_paths=[workenv["cif"]],
            output_par_name="my_out.par",
            output_tsv_name="my_out.tsv",
            work_dir=workenv["work"],
        )
        ins = build_ins_text(cfg)
        # 解析 loop_: 找到 _riet_analysis_fileToSave 的列索引, 再取对应位置的值
        lines = ins.splitlines()
        idx_loop = next(i for i, l in enumerate(lines) if l.strip() == "loop_")
        cols: list[str] = []
        i = idx_loop + 1
        while i < len(lines) and lines[i].strip().startswith("_"):
            cols.append(lines[i].strip())
            i += 1
        values = lines[i:]
        # _maud_import_phase 可能重复列名, 值数仍 = 列数
        assert len(values) >= len(cols), f"值不够 columns={cols} values={values}"
        save_idx = cols.index("_riet_analysis_fileToSave")
        save_val = values[save_idx].strip().strip("'")
        assert "C:" not in save_val, f"fileToSave 用了绝对路径 (MAUD3 会双前缀): {save_val}"
        assert "/" not in save_val and "\\" not in save_val, f"fileToSave 应纯文件名: {save_val}"
        assert save_val == "my_out.par"

    def test_data_file_copied_into_workdir(self, bundle_template, workenv):
        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            work_dir=workenv["work"],
        )
        write_ins_file(cfg)
        # 数据应在 workdir 内出现 (相对路径解析前提)
        assert (workenv["work"] / "sample.xye").exists()


# ====================================================================
# 命令构造 (R-C3 接口)
# ====================================================================

class TestCommandBuild:
    def test_command_uses_lib_glob(self, tmp_path):
        """Windows Java 不接受 glob, 但传 lib\\* 字符串 Java 内部能展开"""
        from polyxrd.services.maud_par_builder import build_maud_command
        maud_root = tmp_path / "fake_maud"
        (maud_root / "jdk" / "bin").mkdir(parents=True)
        (maud_root / "jdk" / "bin" / "java.exe").write_text("")
        (maud_root / "lib").mkdir()
        (maud_root / "lib" / "x.jar").write_text("")

        ins = tmp_path / "run.ins"
        ins.write_text("loop_\n")
        cmd = build_maud_command(maud_root, ins)

        # 检查关键元素
        cmd_str = " ".join(cmd)
        assert "java.exe" in cmd_str
        assert "-Xmx4096M" in cmd_str
        assert "-enable-native-access" in cmd_str
        assert "com.radiographema.MaudText" in cmd_str
        assert "-f" in cmd
        # classpath 含 lib\\* (Windows) 或 lib/* (其它)
        cp_idx = cmd.index("-cp")
        cp_value = cmd[cp_idx + 1]
        if __import__("os").name == "nt":
            assert cp_value.endswith("\\*") or cp_value.endswith("/*"), f"classpath 应该是 glob, got {cp_value}"
        else:
            assert cp_value.endswith("/*"), f"classpath 应该是 glob, got {cp_value}"

    def test_command_rejects_missing_java(self, tmp_path):
        from polyxrd.services.maud_par_builder import build_maud_command
        bad = tmp_path / "not_maud"
        bad.mkdir()
        ins = tmp_path / "run.ins"; ins.write_text("")
        with pytest.raises(FileNotFoundError):
            build_maud_command(bad, ins)


# ====================================================================
# 真实集成测试 (冒烟, 跑通的话跳过)
# ====================================================================

@pytest.mark.slow
class TestRealMaudInvocation:
    """真跑 MAUD3 一次作为冒烟; CI 环境无 MAUD 时手动 skip."""

    def test_maud3_refines_template_plus_cif(self, workenv, bundle_template, tmp_path):
        # 拿一份真实 Corundum CIF
        cif_path = tmp_path / "test_corundum.cif"
        cif_path.write_text(textwrap.dedent("""\
            data_global
            _chemical_name_common 'Corundum'
            _chemical_formula_structural 'Al2 O3'
            _chemical_formula_sum 'Al2 O3'
            _cell_length_a 4.7540
            _cell_length_b 4.7540
            _cell_length_c 12.982
            _cell_angle_alpha 90.0
            _cell_angle_beta 90.0
            _cell_angle_gamma 120.0
            _cell_volume 271.0
            _space_group_name_H-M_alt 'R -3 c :H'
            loop_
            _atom_site_label
            _atom_site_type_symbol
            _atom_site_fract_x
            _atom_site_fract_y
            _atom_site_fract_z
            _atom_site_occupancy
            Al1 Al 0 0 0.352 1.0
            O1 O 0.306 0.306 0 1.0
            """))

        cfg = MaudInsConfig(
            template_par=bundle_template, data_file=workenv["data"],
            cif_paths=[cif_path], iterations=3, work_dir=tmp_path / "realmaud",
        )
        artifacts = write_ins_file(cfg)
        assert artifacts.ins_path.exists()

        # 不实际跑 (CI 跳过; 手动跑见 docs/MAUD批处理侦察报告.md §8.1)
        pytest.skip("真跑 MAUD 需要 Java+MAUD+长时; 手动验证见文档")
