"""
谱图格式读写 / 相互转换
======================
把 (2θ, 强度) 谱图在多种文件格式之间互转 —— 既是「文件 → 另一种格式」的
批量/单文件转换，也是各导出入口的单一实现。

- 读入口: ``load_pattern(path)`` → :class:`XRDData`
- 写出口: ``write_pattern(data, path, fmt=None)`` (fmt 省略时按扩展名推断)
- 一步转换: ``convert_pattern_file(src, dst=None, fmt=None)`` → ``Path``

目标格式统一在 :data:`TARGET_FORMATS` 里声明 (UI 下拉与过滤器都从这里取,
避免"界面上有、代码里没有"的漂移)。
"""
from __future__ import annotations

import csv
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import numpy as np

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.data_io import DataFormatError, load_auto

#: (key, 扩展名)。顺序 = UI 下拉顺序, 常用的放前面。
TARGET_FORMATS: tuple[tuple[str, str], ...] = (
    ("xy", ".xy"),
    ("txt", ".txt"),
    ("dat", ".dat"),
    ("csv", ".csv"),
    ("mdi", ".mdi"),
    ("raw", ".raw"),
    ("xrdml", ".xrdml"),
    ("json", ".json"),
)

TARGET_EXTS: dict[str, str] = {k: e for k, e in TARGET_FORMATS}

# RAW2 头内固定偏移 (与 services.data_loader.DataLoader._load_raw2 保持成对)
_RAW2_HDR_LEN = 316
_RAW2_ANODE_OFF = 0x100     # 2 字节靶材记号 ("Cu"), 供读回时还原波长
_RAW2_COUNT_OFF = 0x102     # int16 LE: 点数
_RAW2_STEP_OFF = 0x10C      # float32 LE: 步长
_RAW2_START_OFF = 0x110     # float32 LE: 起始 2θ
_RAW2_COUNT_MAX = 32767     # int16 上限 —— RAW2 的格式自带限制

#: 描述文本**不能**出现 CU/CO/CR/FE/MN/NI/MO/AG 这类字母组合, 否则读回时会被
#: 当成靶材记号 (读端是子串匹配)。"PolyXRD pattern export" 已逐项核对过。
_RAW2_BANNER = b"PolyXRD pattern export"


# ----------------------------------------------------------------------
# 读
# ----------------------------------------------------------------------

def load_pattern(path: Union[str, Path]) -> XRDData:
    """读取任意受支持的谱图文件。

    与 ``load_auto`` 的差别: 这里额外认得**本程序自己导出的 .json**
    (load_auto 不认识 json, 否则会把项目/库的 json 也卷进来)。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    if p.suffix.lower() == ".json":
        return _read_json(p)
    return load_auto(p)


def _read_json(path: Path) -> XRDData:
    """读本程序导出的 .json 谱图。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataFormatError(f"JSON 解析失败: {path} ({exc})") from exc
    if not isinstance(payload, dict) or "two_theta" not in payload:
        raise DataFormatError(
            f"{path} 不是谱图 JSON (缺 two_theta 字段); 该格式仅用于本程序导出的谱图"
        )
    return XRDData.from_dict(payload)


# ----------------------------------------------------------------------
# 写
# ----------------------------------------------------------------------

def write_pattern(
    data: XRDData,
    path: Union[str, Path],
    fmt: Optional[str] = None,
) -> Path:
    """按 ``fmt`` (缺省取扩展名) 写出谱图, 返回实际写入路径。"""
    p = Path(path)
    key = (fmt or p.suffix.lstrip(".")).lower()
    if key == "xrdml":
        key = "xrdml"
    if key not in TARGET_EXTS:
        raise DataFormatError(
            "不支持的导出格式: %s (可选: %s)"
            % (key, ", ".join(TARGET_EXTS))
        )
    if not p.suffix and fmt:
        p = p.with_suffix("." + key)
    p.parent.mkdir(parents=True, exist_ok=True)
    _WRITERS[key](data, p)
    return p


def convert_pattern_file(
    src: Union[str, Path],
    dst: Union[str, Path, None] = None,
    fmt: Optional[str] = None,
) -> Path:
    """把 ``src`` 转成 ``dst`` (或同目录同名的另一个扩展名)。

    Args:
        src: 源文件 (任意受支持的可读格式)
        dst: 目标路径; None → 与源同目录、同主名、扩展名换成 ``fmt``
        fmt: 目标格式 key; dst 给了且 fmt 为 None 时按 dst 扩展名推断

    Returns:
        实际写出的路径
    """
    src = Path(src)
    data = load_pattern(src)
    if dst is None:
        key = (fmt or "xy").lower()
        if key not in TARGET_EXTS:
            raise DataFormatError(f"不支持的导出格式: {key}")
        dst = src.with_suffix(TARGET_EXTS[key])
    else:
        dst = Path(dst)

    # 防呆: 转换是"读源 → 写目标", 目标不能就是源文件本身, 否则等于静默毁掉原文件。
    # (本特性开发中就因为 dst 缺省推导撞上源文件, 把样例 .mdi 覆盖并删掉了。)
    try:
        same = dst.resolve() == src.resolve()
    except OSError:
        same = dst == src
    if same:
        raise DataFormatError(
            f"输出文件与源文件是同一个文件, 会覆盖源文件: {dst}"
        )
    return write_pattern(data, dst, fmt)


# ---- 各格式的写出器 ---------------------------------------------------

def _uniform_step(two_theta: np.ndarray) -> float:
    """取等间距 2θ 的步长; 非等间距时抛错 (MDI/RAW2 是等间距通道格式)。"""
    diffs = np.diff(np.asarray(two_theta, dtype=float))
    if diffs.size == 0:
        raise DataFormatError("数据点不足, 无法写入等间距格式")
    step = float(np.median(diffs))
    if step <= 0 or not np.allclose(diffs, step, rtol=1e-6, atol=step * 1e-6):
        raise DataFormatError(
            "数据不是等间距 2θ, 无法写入 MDI/RAW2; 请改用 .xy/.txt/.dat/.csv"
        )
    return step


def _fmt_pair(x: float, y: float) -> str:
    """两列文本的一行。

    整数强度按整数列写 (与原厂 .dat/.txt/.xy 导出同构, 便于与原文件逐字节比对);
    含小数时改保留 3 位小数, 不丢信息。
    """
    if abs(y - round(y)) < 1e-9:
        return f"{x:8.3f}{int(round(y)):10d}"
    return f"{x:8.3f}{y:10.3f}"


def _write_two_column(data: XRDData, path: Path) -> None:
    """写 .xy/.txt/.dat: 两列定宽文本 (CRLF, 与原厂导出一致)。

    注意 ``newline=""`` 不能省 —— 否则 Windows 文本模式会把 ``\\n`` 再翻成
    ``\\r\\n``, 写出 ``\\r\\r\\n`` 的坏行尾。
    """
    lines = [
        _fmt_pair(float(x), float(y))
        for x, y in zip(data.two_theta, data.intensity)
    ]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")


def _write_csv(data: XRDData, path: Path) -> None:
    """写 .csv: 带表头的两列。"""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["2theta", "intensity"])
        for x, y in zip(data.two_theta, data.intensity):
            writer.writerow([f"{float(x):.6f}", f"{float(y):.6f}"])


def _write_mdi(data: XRDData, path: Path, anode: str = "Cu") -> None:
    """写 MDI 文本格式。

    结构 (与实测样例同构):
      行1: ``       日期 样品名``
      行2: ``start step scale anode wavelength stop count``
      余:  定宽整数强度, 每行 8 个、栏宽 8

    注意: MDI 是**整数通道**格式, 强度按四舍五入取整; count 写的是**实际点数**,
    且 start/stop 按实际首末 2θ 写 —— 这样读回时不会再被"丢首点校正"整体平移。
    """
    x = np.asarray(data.two_theta, dtype=float)
    y = np.asarray(data.intensity, dtype=float)
    step = _uniform_step(x)
    n = int(x.size)
    start, stop = float(x[0]), float(x[-1])
    wl = float(data.wavelength or 1.5406)

    head0 = "       %s %s" % (datetime.now().strftime("%m/%d/%y"), "Sample ID")
    head1 = (
        f"{start:9.5f}{step:10.6f}{1.0:5.1f} {anode[:2]:2}"
        f"{wl:10.6f}{stop:9.4f}{n:7d}"
    )

    body: list[str] = []
    row: list[str] = []
    for value in y:
        row.append(f"{int(round(value)):8d}")
        if len(row) == 8:
            body.append("".join(row))
            row = []
    if row:
        body.append("".join(row))

    text = "\r\n".join([head0, head1, *body]) + "\r\n"
    path.write_text(text, encoding="utf-8", newline="")


def _write_raw(data: XRDData, path: Path, anode: str = "Cu") -> None:
    """写 RAW2 二进制: 316 字节定长头 + n 个 little-endian float32 强度。

    头长、点数偏移、步长/起始偏移都与读端成对, 保证自读自写可无损往返。
    点数超 int16 (32767) 时明确报错 —— 这是 RAW2 格式自身的限制。
    """
    x = np.asarray(data.two_theta, dtype=float)
    y = np.asarray(data.intensity, dtype=float)
    step = _uniform_step(x)
    n = int(x.size)
    if n > _RAW2_COUNT_MAX:
        raise DataFormatError(
            f"RAW2 点数上限 {_RAW2_COUNT_MAX} (int16), 当前 {n} 点; "
            "请改用 .xy/.txt/.dat/.csv"
        )

    header = bytearray(_RAW2_HDR_LEN)
    header[0:4] = b"RAW2"
    header[4:4 + len(_RAW2_BANNER)] = _RAW2_BANNER
    header[_RAW2_ANODE_OFF:_RAW2_ANODE_OFF + 2] = anode[:2].ljust(2).encode("ascii")
    struct.pack_into("<h", header, _RAW2_COUNT_OFF, n)
    struct.pack_into("<f", header, _RAW2_STEP_OFF, float(step))
    struct.pack_into("<f", header, _RAW2_START_OFF, float(x[0]))

    with open(path, "wb") as fh:
        fh.write(bytes(header))
        fh.write(np.asarray(y, dtype="<f4").tobytes())


def _write_xrdml(data: XRDData, path: Path) -> None:
    """写 Bruker 风格 .xrdml (复用既有 save_xy 的写出实现)。"""
    from polyxrd.services.data_loader import save_xy

    save_xy(data, path, fmt="xrdml")


def _write_json(data: XRDData, path: Path) -> None:
    """写谱图 .json (角度/强度/波长/元数据; 可由 load_pattern 读回)。"""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data.to_dict(), fh, indent=2, ensure_ascii=False, default=str)


_WRITERS = {
    "xy": _write_two_column,
    "txt": _write_two_column,
    "dat": _write_two_column,
    "csv": _write_csv,
    "mdi": _write_mdi,
    "raw": _write_raw,
    "xrdml": _write_xrdml,
    "json": _write_json,
}
