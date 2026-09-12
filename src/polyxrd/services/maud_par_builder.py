"""
MAUD .par / .ins 构建器（路线 C 端到端对接）

================================================================================
PolyXRD → MAUD 引擎中间层。本模块把"用户峰位 + 候选相（COD ID 列表）+ 数据文件
+ 仪器参数"翻译成一个能驱 MAUD 批处理的 INS 控制文件 + 一个临时工作目录。

设计原则:
1. **复用 MAUD Examples 默认模板** (`resources/templates/maud_default.par`, 8 KB)
   —— 已有波长/Bragg-Brentano/Chebyshev 背景, 无相无数据, 是最纯净的起点。
2. **动态注入通过 INS 字段** (`_maud_import_phase`, `_maud_meas_datafile_name`):
   不修改 .par, 而是让 MAUD 在 batch 模式下动态改造。
3. **MAUD3 优先** (v3.04, build 1770) —— 见 docs/MAUD批处理侦察报告.md §8.3 的
   MAUD2 vs MAUD3 差异表。MAUD2 首次成功后可能全局状态漂移。

参考:
- docs/MAUD批处理侦察报告.md §8.1 (已完成 INS 模板示例)
- docs/MAUD批处理侦察报告.md §8.3 (MAUD2/3 兼容性矩阵)
- FullPatt/MAUD-MCP `core/data_manager.py::generate_ins` (BSD-3, 借鉴列序思路)
- Lutterotti MAUD 官方文档
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from polyxrd.utils.resources import get_resource_path


# =============================================================================
# 默认配置
# =============================================================================

DEFAULT_TEMPLATE_NAME = "maud_default.par"
# MAUD3 推荐 JVM 参数 (Azul Zulu 25+ 的强约束, Java 21+ 起强制)
MAUD_JVM_FLAGS = (
    "--enable-native-access=ALL-UNNAMED",
    "--add-opens=java.base/java.net=ALL-UNNAMED",
    "--add-opens=java.base/java.lang=ALL-UNNAMED",
    "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
    "--add-opens=java.base/java.io=ALL-UNNAMED",
    "--add-opens=java.base/java.util=ALL-UNNAMED",
)
# MAUD2 batchProcess 字典列序对应 (R-C1 已探明, 见侦察报告 §8.4)
INS_COLUMN_ORDER = (
    "_riet_analysis_file",
    "_riet_analysis_iteration_number",
    "_riet_analysis_wizard_index",          # 可选; 缺省时 MAUD 自动选 -21/-31
    "_maud_remove_all_datafiles",
    "_riet_meas_datafile_name",
    "_riet_meas_datafile_replace",
    "_maud_remove_all_phases",
    # 下面是可重复列
    "_maud_import_phase",                  # 1..N 个, 每个一行 (列名重复追加)
    "_riet_analysis_fileToSave",
    "_riet_append_result_to",
)
# 列名重复策略: 同一列接受多次出现, 每个 value 配一个列头 (R-C1 §8.1 验过 MAUD3)
REPEATABLE_COLUMNS = frozenset({"_maud_import_phase"})


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class MaudInsConfig:
    """驱动 MAUD batch 模式所需的最少输入 (路线 C 一次精修调用)"""

    # —— 输入 ——
    template_par: Path                            # 模板 .par (必填, 通常为 bundled default.par)
    data_file: Path                               # 实验 .xye / .dat (必填)

    # —— 相 (PolyXRD 物相识别模块的输出) ——
    cif_paths: List[Path] = field(default_factory=list)
    """每个相一份 CIF 绝对路径. 路线 B 给出 cod_id 时, 配合 :func:`cod_id_to_cif_path`."""

    # —— 精修控制 (路线 C 用户可调) ——
    iterations: int = 50                          # _riet_analysis_iteration_number
    wizard_index: Optional[int] = None           # None=MAUD 自動選 (-21 成熟 / -31 原始)

    # —— 输出 ——
    work_dir: Optional[Path] = None               # 临时工作目录 (None=mkdtemp)
    output_par_name: str = "refined.par"          # 输出 par 文件名
    output_tsv_name: str = "results.tsv"          # 输出 TSV 文件名

    # —— 仪器 (RietveldRefiner 调用方传入, 预留给将来更智能的模板替换) ——
    radiation: str = "Cu Kα"                      # 仅注释用, 不直接写入 .par
    data_range_2theta: Optional[tuple] = None     # (low, high), 用于数据范围检查

    def __post_init__(self) -> None:
        if self.iterations < 1:
            raise ValueError(f"iterations 必须 ≥1, got {self.iterations}")
        if not self.data_file.exists():
            raise FileNotFoundError(f"data_file 不存在: {self.data_file}")
        if not self.data_file.is_file():
            raise ValueError(f"data_file 不是文件: {self.data_file}")
        for c in self.cif_paths:
            if not c.exists():
                raise FileNotFoundError(f"CIF 不存在: {c}")
        # 路径转绝对 (防止 INS 解析时 cwd 漂移)
        self.data_file = self.data_file.resolve()
        self.cif_paths = [c.resolve() for c in self.cif_paths]


@dataclass
class MaudInsArtifacts:
    """MAUD batch 调用产出物"""

    ins_path: Path
    work_dir: Path
    output_par_path: Path
    output_tsv_path: Path
    template_par_path: Path    # 模板副本 (在工作目录内)


# =============================================================================
# 默认模板解析
# =============================================================================

def get_default_template_path() -> Path:
    """返回 bundled maud_default.par 的绝对路径"""
    p = get_resource_path(f"templates/{DEFAULT_TEMPLATE_NAME}")
    if not p.exists():
        raise FileNotFoundError(
            f"MAUD 默认模板缺失: {p}\n"
            f"应位于 src/polyxrd/resources/templates/{DEFAULT_TEMPLATE_NAME}"
        )
    return p


def load_template_par(template_path: Optional[Path] = None) -> Path:
    """加载模板 .par 到用户指定或临时目录, 返回工作副本路径.

    永不修改只读 bundled 模板; 总是拷一份.
    """
    src = template_path or get_default_template_path()
    if not src.exists():
        raise FileNotFoundError(f"模板 .par 不存在: {src}")

    work = Path(tempfile.mkdtemp(prefix="maud_template_"))
    dst = work / src.name
    shutil.copy2(src, dst)
    return dst


# =============================================================================
# INS 生成
# =============================================================================

_INS_NEWLINE = "\r\n"  # CIF 习惯 CRLF; MAUD 两种都吃, 这里用 CRLF 跟 MILK/maud_mcp 一致


def _format_ins_value(s: str) -> str:
    """对 INS 中的值加单引号 (含空格/数字开头)"""
    s = str(s)
    # 不含特殊字符的简单 token 可不加引号; 为安全起见一律加引号
    return f"'{s}'"


def build_ins_text(cfg: MaudInsConfig) -> str:
    """把配置渲染成 INS 文本 (含 loop_ 表头 + 一行数据).

    R-C1 关键约束:
    - `remove_all_datafiles true` 必须在 `meas_datafile_name` 之前
    - `remove_all_phases true` 必须在 `import_phase` 之前
    - 多相时 `_maud_import_phase` 列**重复列名追加**, 不另起 loop_
    - `fileToSave` 与 `append_result_to` 用**相对路径** (MAUD3 强制) 解析 vs ins 同目录
    - wizard 字段可省略; MAUD 自动按分析成熟度选 -21 或 -31
    """
    work_dir = Path(cfg.work_dir) if cfg.work_dir else Path(tempfile.mkdtemp(prefix="maud_work_"))
    work_dir.mkdir(parents=True, exist_ok=True)

    # 模板 par 拷入工作目录 (MAUD 会原地存档)
    tpl_dst = load_template_par_into(cfg.template_par, work_dir)
    cfg.template_par = tpl_dst  # 后续改 cfg 引用为工作副本

    # 拷贝前先用 resolve() 比较规范路径, 避免 samefile() 抛 FileNotFoundError
    # (目标文件在拷贝之前还不存在, samefile 会触发 OS 级别的路径检查).
    data_target = _basename_in_work(cfg.data_file, work_dir)
    try:
        _same_path = data_target.resolve() == cfg.data_file.resolve()
    except OSError:
        _same_path = False
    if not _same_path:
        # 用户不在 work_dir, 拷一份; 否则 MAUD 加载时会按相对路径找不到
        shutil.copy2(cfg.data_file, data_target)

    cif_in_work = [_basename_in_work(c, work_dir) for c in cfg.cif_paths]
    for src, dst in zip(cfg.cif_paths, cif_in_work):
        try:
            _same_path = dst.resolve() == src.resolve()
        except OSError:
            _same_path = False
        if not _same_path:
            shutil.copy2(src, dst)

    columns: list[str] = []
    values: list[str] = []

    def col(name: str, value, repeatable: bool = False):
        """追加一个 (列头, 值) 配对.

        - 普通列: 同一 name 第二次调用会抛 RuntimeError (避免 CIF 数据错位)
        - 可重复列 (REPEATABLE_COLUMNS): 每调用一次, columns 与 values 各追加一项
        """
        if name in REPEATABLE_COLUMNS:
            repeatable = True
        if repeatable:
            columns.append(name)
        else:
            if name in columns:
                raise RuntimeError(
                    f"列 {name} 不可重复; 这通常意味着 build_ins_text 内部顺序错了"
                )
            columns.append(name)
        values.append(_format_ins_value(value))

    # 1) 输入 par
    col("_riet_analysis_file", cfg.template_par.name)
    col("_riet_analysis_iteration_number", cfg.iterations)
    if cfg.wizard_index is not None:
        col("_riet_analysis_wizard_index", cfg.wizard_index)

    # 2) 清数据 (必须在 meas_datafile_name 之前)
    col("_maud_remove_all_datafiles", "true")

    # 3) 数据绑定
    col("_riet_meas_datafile_name", data_target.name)
    col("_riet_meas_datafile_replace", "true")

    # 4) 清相 (必须在 import_phase 之前)
    col("_maud_remove_all_phases", "true")

    # 5) 注入相 (多相时重复列名, 每个 CIF 一次 col 调用)
    for c in cif_in_work:
        col("_maud_import_phase", c.name)

    # 6) 输出 (相对路径)
    col("_riet_analysis_fileToSave", cfg.output_par_name)
    col("_riet_append_result_to", cfg.output_tsv_name)

    # 渲染: CIF loop_ 标准是 "列头" + "单行 N 个值", 这里按 columns/values 1:1 渲染
    if len(columns) != len(values):
        raise RuntimeError(
            f"columns ({len(columns)}) 与 values ({len(values)}) 数量不匹配; "
            f"可能是 REPEATABLE_COLUMNS 设置漏了: columns={columns}"
        )
    sep = _INS_NEWLINE
    lines = ["loop_"]
    lines.extend(columns)
    lines.extend(values)
    body = sep.join(lines) + sep
    return body


def write_ins_file(cfg: MaudInsConfig) -> MaudInsArtifacts:
    """渲染 INS 文本并写入 ``work_dir/run.ins``. 同时返回所有产物路径对象.

    工作目录约定: ALL outputs (par, tsv, run.ins) 都在 :pyattr:`work_dir` 内,
    MAUD3 才能正确解析相对路径. 调用方负责 :pyfunc:`tempfile.mkdtemp` 清理。
    """
    work_dir = Path(cfg.work_dir) if cfg.work_dir else Path(tempfile.mkdtemp(prefix="maud_work_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    cfg.work_dir = work_dir

    ins_text = build_ins_text(cfg)

    ins_path = work_dir / "run.ins"
    ins_path.write_text(ins_text, encoding="utf-8", newline="")

    return MaudInsArtifacts(
        ins_path=ins_path,
        work_dir=work_dir,
        output_par_path=work_dir / cfg.output_par_name,
        output_tsv_path=work_dir / cfg.output_tsv_name,
        template_par_path=cfg.template_par,
    )


def _basename_in_work(src: Path, work_dir: Path) -> Path:
    """返回 src 在 work_dir 内的目标路径; 若已在那里, 直接返回."""
    if src.parent.resolve() == work_dir.resolve():
        return src
    return work_dir / src.name


def load_template_par_into(template_path: Path, work_dir: Path) -> Path:
    """把模板 par 拷入 work_dir, 返回工作副本路径."""
    src = Path(template_path)
    if not src.exists():
        raise FileNotFoundError(f"模板 .par 不存在: {src}")
    dst = work_dir / src.name
    if not dst.exists():
        shutil.copy2(src, dst)
    return dst


# =============================================================================
# subprocess 命令 (R-C3 待集成)
# =============================================================================

def build_maud_command(
    maud_root: Path,
    ins_path: Path,
    max_memory_mb: int = 4096,
) -> list[str]:
    """拼出最终 java 命令 (subprocess.run 列表). 调用方负责 capture_output.

    :param maud_root: MAUD 安装根 (例如 ``C:\\\\MAUD3``). 必须含 ``jdk/bin/java.exe`` 与 ``lib/``.
    :param ins_path: 绝对路径指向 .ins 文件 (生成的 run.ins).
    """
    java_exe = maud_root / "jdk" / "bin" / "java.exe"
    if not java_exe.exists():
        raise FileNotFoundError(f"找不到 java.exe: {java_exe}")
    lib_dir = maud_root / "lib"
    if not lib_dir.is_dir():
        raise FileNotFoundError(f"找不到 lib 目录: {lib_dir}")

    # classpath = lib/* 通配 (MAUD 不接受手写 list, glob 才是稳定的)
    if os.name == "nt":
        # Windows Java 不接受 lib/* glob; 用 lib\\* 单条目路径
        # java 实际展开 35 个 jars
        classpath = f"{lib_dir}{os.sep}*"
    else:
        classpath = f"{lib_dir}{os.sep}*"

    return [
        str(java_exe),
        f"-Xmx{max_memory_mb}M",
        *MAUD_JVM_FLAGS,
        f"-DJava.library.path={maud_root}",
        "-cp", classpath,
        "com.radiographema.MaudText",
        "-f", str(ins_path),
    ]


# =============================================================================
# 辅助: COD ID → CIF 绝对路径 (路线 B 接口)
# =============================================================================

def cod_id_to_cif_path(cod_id: int, cod_root: Path) -> Path:
    """把 ICDD/COD 编号映射成本地 ``cod/cif/`` 下的 CIF 路径.

    编码规则 (R-C1 §8.7):
        cod_entries.file = 'cif/X/YY/ZZ/XYYYYYY.cif' (relative)
        cod_root + relative = absolute

    示例: cod_id=2101052 → cif/2/10/10/2101052.cif
    """
    # COD ID 一般是 7 位数字 (COD 编号), 也支持 6 位传统编号
    s = str(cod_id)
    if not s.isdigit():
        raise ValueError(f"COD ID 应为纯数字, got: {cod_id!r}")
    if len(s) > 7:
        s = s.zfill(7)[:7]
    # 头位: 第一位 (X), 三位 (YZ → YY/Z)
    if len(s) < 7:
        s = s.zfill(7)
    # 按 rind-cif/2/10/10/2101052.cif (X/YY/ZZ/XYYYYYY)
    head = s[0]              # '2'
    yy = s[1:3]             # '10'
    zz = s[3:5]             # '10'
    rel = Path(head) / yy / zz / f"{s}.cif"
    return (Path(cod_root) / "cod" / rel).resolve()


def detect_maud_root(prefer: str = "MAUD3") -> Path:
    """默认查找 C:\\\\MAUD3 (优先) 或 C:\\\\MAUD2 (回退)."""
    candidates = [Path(f"C:\\{prefer}"), Path(f"C:\\MAUD2"), Path(f"C:\\MAUD3")]
    for c in candidates:
        if (c / "jdk" / "bin" / "java.exe").exists():
            return c
    raise FileNotFoundError(
        "未检测到 MAUD 安装; 请在 C:\\MAUD2 或 C:\\MAUD3 安装, "
        "或在 config 中显式设置 maud_root"
    )


# =============================================================================
# 公开 API
# =============================================================================

__all__ = [
    # 数据类
    "MaudInsConfig",
    "MaudInsArtifacts",
    # 模板
    "DEFAULT_TEMPLATE_NAME",
    "get_default_template_path",
    "load_template_par",
    "load_template_par_into",
    # INS 构造
    "build_ins_text",
    "write_ins_file",
    # 命令
    "build_maud_command",
    "MAUD_JVM_FLAGS",
    # 辅助
    "cod_id_to_cif_path",
    "detect_maud_root",
]
