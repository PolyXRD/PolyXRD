"""
数据导入服务 (M01, Sprint 3)
============================
在既有 DataLoader 之上提供:
  - detect_format: 统一格式探测 (扩展名 + 文本嗅探)
  - load_auto: 全自动加载 (文本/多列列序判定, 非文本委托 DataLoader)
  - 多列表格: 自动识别 (2θ, 强度) 列 (含背景列/计数率列等干扰)
"""
from __future__ import annotations

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
                vals.append(float(t.replace(",", "")))
            except ValueError:
                ok = False
                break
        if ok and len(vals) >= 2:
            rows.append(vals)
    if not rows:
        raise DataFormatError(f"文件 {path} 中没有有效数值数据")
    return rows


def _pick_columns(rows: list[list[float]], x_col=None, y_col=None):
    """选择 (x, y) 列。

    规则:
      - 显式 x_col/y_col 优先;
      - 否则两列数据用 (0, 1);
      - 多列时: x= 首列 (通常 2θ, 单调); y= 其余列中相邻差分变动最剧烈者
        (计数率列), 排除首列与常量列。
    """
    ncol = len(rows[0])
    if x_col is not None and y_col is not None:
        return int(x_col), int(y_col)
    if ncol == 2 or x_col is not None:
        return int(x_col or 0), int(y_col or 1)
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
