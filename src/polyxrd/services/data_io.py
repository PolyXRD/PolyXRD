"""
数据导入服务 (M01, Sprint 3)
============================
在既有 DataLoader 之上提供:
  - detect_format: 统一格式探测 (扩展名 + 文本嗅探)
  - load_auto: 全自动加载 (文本/多列列序判定, 非文本委托 DataLoader)
  - 多列表格: 自动识别 (2θ, 强度) 列 (含背景列/计数率列等干扰)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

import numpy as np

from polyxrd.models.xrd_data import XRDData

TEXT_EXT = {".txt", ".xy", ".dat", ".csv", ".smz"}


class DataFormatError(ValueError):
    """数据格式不支持或解析失败。"""


def detect_format(path: Union[str, Path]) -> str:
    """按扩展名 + 文件头文本嗅探格式。

    Returns:
        "txt"|"csv"|"xy"|"dat"|"mdi"|"xrdml"|"raw"|"brml"|"shimadzu"|"unknown"
    """
    p = Path(path)
    ext = p.suffix.lower()
    try:
        with open(p, "rb") as f:
            head = f.read(2048)
    except Exception:
        head = b""
    if ext in (".xrdml", ".xml"):
        return "xrdml"
    if ext == ".brml":
        return "brml"
    if ext == ".raw":
        return "raw"
    if ext == ".mdi":
        return "mdi"
    text_head = head.decode("utf-8", errors="ignore").lower()
    if "target" in text_head and "voltage" in text_head or "<2theta>" in text_head:
        return "shimadzu"
    if ext == ".csv":
        return "csv"
    if ext == ".xy":
        return "xy"
    if ext == ".dat":
        return "dat"
    if ext == ".smz":
        return "smz"
    if ext == ".txt":
        return "txt"
    if text_head.startswith("<"):
        return "xrdml"
    return "unknown"


_RE_THOUSANDS_INT = re.compile(r"[+-]?\d{1,3}(,\d{3})+")
_RE_THOUSANDS_DEC = re.compile(r"[+-]?\d{1,3}(,\d{3})+\.\d+")
_RE_EU_DECIMAL = re.compile(r"[+-]?\d{1,3}(\.\d{3})*,\d+")


def _parse_number(tok: str) -> float:
    """解析单个数值 token (含千位分隔符与欧式小数逗号)。

    v4.0.0 修复: 原实现无条件 ``float(t.replace(",", ""))`` —— 对分号分隔的
    欧式导出 (``20,5;100``) 会把小数逗号当千位分隔符删掉, 2θ 20.5° 读成 205°
    (越界报错), 强度 100,5 读成 1005 (**静默 10 倍误差**, 不报错)。
    现在: 先按原生 float, 再认千位分隔 (逗号后恰好 3 位), 最后认欧式小数。
    """
    t = tok.strip()
    try:
        return float(t)
    except ValueError:
        pass
    if _RE_THOUSANDS_INT.fullmatch(t):
        return float(t.replace(",", ""))
    if _RE_THOUSANDS_DEC.fullmatch(t):
        return float(t.replace(",", ""))
    if _RE_EU_DECIMAL.fullmatch(t):
        return float(t.replace(".", "").replace(",", "."))
    raise ValueError(t)


def _read_numeric_rows(path: Path):
    """读取纯文本并返回数值行列表 + 分隔符, 跳过注释/空/表头。"""
    # v1.1.1: utf-8-sig —— 仪器/Excel 导出的 UTF-8 文本常带 BOM, 用 utf-8 读会在
    # 首行留下 \ufeff, 使第一列数值 float() 解析失败 (表现为"文件读进来是空的")。
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        lines = f.readlines()
    if not lines:
        raise DataFormatError(f"空文件: {path}")
    # 分隔符嗅探
    delimiter = None
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(("#", "%", "//", ";", "!")):
            continue
        if delimiter is None:
            if "\t" in s:
                delimiter = "\t"
            elif "," in s:
                delimiter = ","
            elif ";" in s:
                delimiter = ";"
            else:
                delimiter = " "
        break
    rows = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(("#", "%", "//", ";", "!", "<")):
            continue
        parts = [t for t in s.replace(",", " ").replace(";", " ").split()] \
            if delimiter == " " else [t for t in s.split(delimiter) if t.strip()]
        vals = []
        ok = True
        for t in parts:
            try:
                vals.append(_parse_number(t))
            except ValueError:
                ok = False
                break
        if ok and len(vals) >= 2:
            rows.append(vals)
    if not rows:
        raise DataFormatError(f"文件 {path} 中没有有效数值数据")
    # v4.0.0: 列数不一致的残行 (尾随注释/多余列) 会让 np.asarray 抛
    # "setting an array element with a sequence"。统一保留出现最多的列数。
    lengths = [len(r) for r in rows]
    if len(set(lengths)) > 1:
        modal = max(set(lengths), key=lengths.count)
        rows = [r for r in rows if len(r) == modal]
        if len(rows) < 1:
            raise DataFormatError(f"文件 {path} 的列数不一致, 无法解析")
    return rows


def _pick_columns(rows: list[list[float]], x_col=None, y_col=None):
    """选择 (x, y) 列。

    规则:
      - 显式 x_col/y_col 优先 (可只指定其中之一);
      - 否则两列数据用 (0, 1);
      - 多列时: x= 首列 (通常 2θ, 单调); y= 其余列中相邻差分变动最剧烈者
        (计数率列), 排除首列与常量列。
    """
    ncol = len(rows[0])
    # v4.0.0 修复: 原实现只显式给了 y_col (x_col=None) 且列数 >2 时,
    # 走进自动分支把 y_col 完全忽略, 静默选错强度列。
    if y_col is not None:
        xc = int(x_col) if x_col is not None else 0
        yc = int(y_col)
        if not (0 <= xc < ncol and 0 <= yc < ncol):
            raise DataFormatError(
                f"列索引越界: x_col={xc}, y_col={yc}, 文件只有 {ncol} 列")
        return xc, yc
    if x_col is not None:
        xc = int(x_col)
        if not (0 <= xc < ncol):
            raise DataFormatError(f"列索引越界: x_col={xc}, 文件只有 {ncol} 列")
        return xc, 1 if ncol > 1 else 0
    if ncol == 2:
        return 0, 1
    arr = np.asarray(rows, dtype=float)
    # 依相邻差之和挑选"信号"列 (排除与首列几乎相同的列)
    diffs = np.abs(np.diff(arr, axis=0)).sum(axis=0)
    cands = [j for j in range(1, ncol) if diffs[j] > 1e-9]
    if not cands:
        cands = list(range(1, ncol))
    y = max(cands, key=lambda j: diffs[j])
    return 0, y


def load_auto(
    path: Union[str, Path],
    wavelength: Optional[float] = None,
    x_col: Optional[int] = None,
    y_col: Optional[int] = None,
    **kwargs,
) -> XRDData:
    """全自动加载: 文本/CSV 多列列序识别; 其它格式委托 DataLoader。

    Args:
        path: 文件路径
        wavelength: 波长 (None → 默认 Cu Kα1 1.5406 或从文件头识别)
        x_col/y_col: 显式指定列 (None → 自动)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    fmt = detect_format(p)

    if fmt in TEXT_EXT or fmt in ("txt", "csv", "xy", "dat", "smz"):
        rows = _read_numeric_rows(p)
        # v4.0.0: 有效行 <3 时 XRDData 会抛 "数据点数量必须 >= 3" (不提示来源),
        # 这里提前给可定位的 DataFormatError。
        if len(rows) < 3:
            raise DataFormatError(
                f"文件 {p} 只有 {len(rows)} 个有效数据行, 至少需要 3 行"
                " (检查列分隔符/是否多列错行)")
        xc, yc = _pick_columns(rows, x_col, y_col)
        arr = np.asarray(rows, dtype=float)
        xx, yy = arr[:, xc], arr[:, yc]
        return XRDData(
            two_theta=xx,
            intensity=yy,
            wavelength=wavelength or 1.5406,
            metadata={"source_file": str(p), "format": fmt,
                      "x_col": xc, "y_col": yc, "num_points": len(xx)},
        )

    # 非文本: 委托现有 DataLoader (xrdml/raw/brml/shimadzu/...)
    from polyxrd.services.data_loader import DataLoader
    return DataLoader().load(p, wavelength=wavelength, **kwargs)
