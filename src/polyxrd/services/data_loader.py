"""
数据加载器服务
==============
支持多种XRD数据格式的加载。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.config import get_config
from polyxrd.models.xrd_data import XRDData
from polyxrd.utils.file_utils import detect_xrd_format


#: 靶材 → Kα1 波长 (Å)。二进制/文本头里通常只留一个 "Cu"/"Co" 之类的记号,
#: 靠它还原波长比在数值堆里猜 1.54 更可靠 (头里还常有个 1.0 的标度因子会撞车)。
ANODE_WAVELENGTHS = {
    "CU": 1.5406,
    "CO": 1.78897,
    "CR": 2.28970,
    "FE": 1.93604,
    "MN": 2.10314,
    "NI": 1.65791,
    "MO": 0.70930,
    "AG": 0.55941,
}


def wavelength_from_anode(text: str) -> Optional[float]:
    """从文件头文本里找靶材记号并返回 Kα1 波长 (找不到返回 None)。"""
    upper = text.upper()
    for symbol, wl in ANODE_WAVELENGTHS.items():
        if symbol in upper:
            return wl
    return None


class DataLoader:
    """XRD数据加载器

    支持格式:
    - .xy: 两列文本 (2θ, intensity)
    - .dat: 三列文本 (2θ, intensity, 可能有背景)
    - .csv: CSV格式
    - .txt: 通用文本格式
    - .xrdml: XML格式 (Bruker)
    - .xml: 通用XRD XML
    - .raw: 二进制格式 (RAW2: 定长头 + float32 强度; 其它变体走启发式兜底)
    - .brml: Bruker专用格式
    - .mdi: MDI 文本格式 (定宽整数强度, 头含 start/step/stop)
    """

    def __init__(self) -> None:
        self._config = get_config()

    def load(
        self,
        file_path: str | Path,
        wavelength: Optional[float] = None,
        **kwargs,
    ) -> XRDData:
        """加载XRD数据文件

        Args:
            file_path: 文件路径
            wavelength: X射线波长 (如果为None，使用默认值)
            **kwargs: 传递给具体加载器的参数

        Returns:
            XRDData对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 格式不支持或数据无效
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        fmt = detect_xrd_format(file_path)
        wl = wavelength or self._config.default_wavelength

        if fmt == "txt":
            fmt = self._detect_txt_subformat(file_path)

        loaders = {
            "xy": self._load_text,
            "dat": self._load_text,
            "csv": self._load_text,
            "txt": self._load_text,
            "shimadzu": self._load_shimadzu,
            "smz": self._load_text,
            "xrdml": self._load_xrdml,
            "raw": self._load_raw,
            "brml": self._load_brml,
            "mdi": self._load_mdi,
        }

        loader = loaders.get(fmt)
        if loader is None:
            raise ValueError(f"不支持的文件格式: {fmt}")

        two_theta, intensity, metadata = loader(file_path, fmt=fmt, **kwargs)

        detected_wl = metadata.get("wavelength")
        if detected_wl is not None and wavelength is None:
            wl = detected_wl

        data = XRDData(
            two_theta=two_theta,
            intensity=intensity,
            wavelength=wl,
            metadata={
                "source_file": str(file_path),
                "format": fmt,
                "num_points": len(two_theta),
                **metadata,
            },
        )
        return data

    # ------------------------------------------------------------------
    # 文本格式加载器
    # ------------------------------------------------------------------

    def _load_text(
        self, file_path: Path, fmt: str = "xy", **kwargs
    ) -> tuple[np.ndarray, np.ndarray]:
        """加载文本格式 (.xy, .dat, .csv, .txt)"""
        delimiter = kwargs.get("delimiter", None)
        skip_rows = kwargs.get("skip_rows", 0)
        two_theta_col = kwargs.get("two_theta_col", 0)
        intensity_col = kwargs.get("intensity_col", 1)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if delimiter is None:
            delimiter = self._detect_delimiter(lines)

        data_lines = []
        header_skipped = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "%", "//", ";", "!")):
                continue
            if "<" in stripped and ">" in stripped:
                if data_lines:
                    continue
                header_skipped += 1
                continue
            if header_skipped < skip_rows:
                header_skipped += 1
                continue
            parts = self._split_line(stripped, delimiter)
            if len(parts) < 2:
                if data_lines:
                    continue
                header_skipped += 1
                continue
            try:
                values = [float(p) for p in parts]
                if len(values) >= 2:
                    data_lines.append(values)
            except ValueError:
                if data_lines:
                    continue
                header_skipped += 1

        if not data_lines:
            raise ValueError(f"文件 {file_path} 中没有有效数据")

        two_theta = np.array([d[two_theta_col] for d in data_lines])
        intensity = np.array([d[intensity_col] for d in data_lines])

        return two_theta, intensity, {}

    def _detect_txt_subformat(self, file_path: Path) -> str:
        """检测txt文件的子格式（岛津/简易/通用）"""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(8192)
            content_lower = content.lower()
            if "target" in content_lower and "voltage" in content_lower:
                return "shimadzu"
            if "<2theta>" in content_lower:
                return "shimadzu"
        except Exception:
            pass
        return "txt"

    @staticmethod
    def _split_line(line: str, delimiter: str) -> list[str]:
        """使用指定分隔符分割行，支持正则表达式"""
        if delimiter in (r"\s+", "whitespace"):
            parts = re.split(r"\s+", line.strip())
        elif delimiter.startswith("re:") or delimiter.startswith("\\"):
            pattern = delimiter[3:] if delimiter.startswith("re:") else delimiter
            parts = re.split(pattern, line.strip())
        else:
            parts = line.split(delimiter)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _detect_delimiter(lines: list[str]) -> str:
        """自动检测分隔符"""
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "%", "//", ";", "!")):
                if "\t" in stripped:
                    return "\t"
                elif "," in stripped:
                    return ","
                elif ";" in stripped:
                    return ";"
                elif len(stripped.split()) >= 2:
                    return r"\s+"
                else:
                    return r"\s+"
        return r"\s+"

    # ------------------------------------------------------------------
    # 岛津(Shimadzu)格式加载器
    # ------------------------------------------------------------------

    def _load_shimadzu(
        self, file_path: Path, fmt: str = "shimadzu", **kwargs
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """加载岛津XRD仪器导出的txt格式

        岛津格式包含完整的实验参数头部信息，如:
        - target (靶材), voltage (电压), current (电流)
        - scan range (扫描范围), sampling pitch (采样步长)
        - wavelength (波长) 等
        """
        metadata = {}
        two_theta_col = kwargs.get("two_theta_col", 0)
        intensity_col = kwargs.get("intensity_col", 1)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        header_patterns = {
            "target": r"target\s*[:=]\s*(\S+)",
            "voltage": r"voltage\s*[:=]\s*([\d.]+)",
            "current": r"current\s*[:=]\s*([\d.]+)",
            "scan_start": r"scan range\s*[:=]\s*([\d.]+)",
            "scan_end": r"scan range\s*[:=]\s*[\d.]+\s*-\s*([\d.]+)",
            "scan_speed": r"scan speed\s*[:=]\s*([\d.]+)",
            "sampling_pitch": r"(?:sampling\s+pitch|sampling interval)\s*[:=]\s*([\d.]+)",
            "preset_time": r"(?:preset\s+time|counting time)\s*[:=]\s*([\d.]+)",
            "wavelength": r"wavelength\s*[:=]\s*([\d.]+)",
            "tube": r"tube\s*[:=]\s*(\S+)",
        }

        for key, pattern in header_patterns.items():
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    metadata[key] = float(match.group(1))
                except ValueError:
                    metadata[key] = match.group(1)

        target = metadata.get("target", "")
        wavelength_map = {
            "Cu": 1.5406,
            "Cu-Ka": 1.5406,
            "Cuka": 1.5406,
            "Fe": 1.9373,
            "Co": 1.7903,
            "Ni": 1.6516,
            "Mo": 0.7107,
            "Ag": 0.5608,
            "Al": 1.4398,
        }
        target_clean = str(target).replace("-", "").replace(" ", "").lower()
        for k, v in wavelength_map.items():
            if k.lower() in target_clean:
                metadata["wavelength"] = v
                metadata["wavelength_source"] = f"target_mapping:{k}"
                break

        lines = content.splitlines()
        data_lines = []
        header_found = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "%", "//", ";", "!")):
                continue
            if "<" in stripped and ">" in stripped:
                header_found = True
                continue
            parts = self._split_line(stripped, r"\s+")
            if len(parts) < 2:
                continue
            try:
                values = [float(p) for p in parts]
                if len(values) >= 2:
                    data_lines.append(values)
            except ValueError:
                continue

        if not data_lines:
            raise ValueError(f"岛津文件 {file_path} 中没有有效数据")

        two_theta = np.array([d[two_theta_col] for d in data_lines])
        intensity = np.array([d[intensity_col] for d in data_lines])

        metadata["instrument"] = "Shimadzu"
        metadata["file_format"] = "shimadzu_txt"

        return two_theta, intensity, metadata

    # ------------------------------------------------------------------
    # XRDM格式加载器
    # ------------------------------------------------------------------

    def _load_xrdml(
        self, file_path: Path, fmt: str = "xrdml", **kwargs
    ) -> tuple[np.ndarray, np.ndarray]:
        """加载XRDML格式 (Bruker XML)"""
        try:
            tree = ET.parse(str(file_path))
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"XML解析错误: {e}") from e

        # 查找2theta和intensity数组
        ns = {"xrd": "http://www.xrdml.com/XRDMeasurement/2.1"}

        two_theta = None
        intensity = None

        # 尝试多种XML结构
        for element in root.iter():
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "positions":
                # 2theta positions
                for child in element.iter():
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "axis" and child.get("axisName") == "2Theta":
                        positions_text = child.text or ""
                        if positions_text.strip():
                            two_theta = np.array([
                                float(v) for v in positions_text.split()
                            ])

            if tag == "intensities":
                intens_text = element.text or ""
                if intens_text.strip():
                    intensity = np.array([
                        float(v) for v in intens_text.split()
                    ])

        # 备选方案：查找 count/element/count 结构
        if two_theta is None or intensity is None:
            two_theta_vals = []
            intensity_vals = []

            # 尝试: <scan axis="2Theta" ... /> 然后 <dataPoints>
            for scan in root.iter():
                tag = scan.tag.split("}")[-1] if "}" in scan.tag else scan.tag
                if "scan" in tag.lower() or "dataPoint" in tag:
                    pass

            # 简单扫描所有数字序列
            all_text = []
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    all_text.extend(elem.text.split())

            # 尝试将数字分成两列
            numbers = []
            for t in all_text:
                try:
                    numbers.append(float(t))
                except ValueError:
                    pass

            if len(numbers) >= 6:
                # 假设前半是2theta，后半是intensity
                n = len(numbers) // 2
                two_theta = np.array(numbers[:n])
                intensity = np.array(numbers[n:n * 2])

        if two_theta is None or intensity is None:
            raise ValueError(f"无法从XRDML文件 {file_path} 提取2θ和强度数据")

        if len(two_theta) != len(intensity):
            # 尝试截断到最短
            min_len = min(len(two_theta), len(intensity))
            two_theta = two_theta[:min_len]
            intensity = intensity[:min_len]

        return two_theta, intensity, {}

    # ------------------------------------------------------------------
    # 二进制格式加载器
    # ------------------------------------------------------------------

    def _load_raw(
        self, file_path: Path, fmt: str = "raw", **kwargs
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """加载二进制 RAW 格式。

        先按 ``RAW2`` 定长头解析 (实测结构, 见 test_xrd/geshi/4-1.raw):
          - ``0x000``: 4 字节魔数 ``b"RAW2"``, 后接定长文本头
          - ``0x102``: int16 LE = 数据点数 n (据此反推数据段偏移 ``len - n*4``)
          - ``0x10C``: float32 LE = 步长     ``0x110``: float32 LE = 起始 2θ
          - 数据段: n 个 little-endian float32 强度
        实测该文件 = 316 字节头 + 7251 个 float32 (start=5.0, step=0.02, 首值 207),
        与同目录 ``4-1.dat`` 完全一致。

        未被识别的 RAW 变体 (Bruker 等) 仍走旧的"前半 2θ / 后半强度"启发式,
        保持既有行为不回归。
        """
        raw = file_path.read_bytes()
        if raw[:4] == b"RAW2":
            return self._load_raw2(raw, file_path)

        # ---- 旧启发式兜底 (未识别的 RAW 变体) ----
        data = raw[100:]
        values = np.frombuffer(data, dtype=np.float32)
        if len(values) < 2:
            raise ValueError(f"无法解析RAW文件 (数据段过短): {file_path}")
        # 前半2theta，后半intensity
        n = len(values) // 2
        return values[:n], values[n:n * 2], {}

    # RAW2 头内固定偏移 (实测)
    _RAW2_COUNT_OFF = 0x102   # int16 LE: 点数
    _RAW2_STEP_OFF = 0x10C    # float32 LE: 步长
    _RAW2_START_OFF = 0x110   # float32 LE: 起始 2θ
    _RAW2_HDR_LEN = 316       # 点数不可信时的兜底头长

    def _load_raw2(
        self, raw: bytes, file_path: Path
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """RAW2 定长头 + float32 强度。"""
        import struct

        offset = None
        n = 0
        if len(raw) >= self._RAW2_COUNT_OFF + 2:
            n_hdr = struct.unpack_from("<h", raw, self._RAW2_COUNT_OFF)[0]
            cand = len(raw) - n_hdr * 4
            # 头长必须落在合理范围, 否则说明这个 int16 不是点数
            if n_hdr >= 16 and 64 <= cand <= 4096:
                offset, n = cand, n_hdr
        if offset is None:
            offset = self._RAW2_HDR_LEN
            n = (len(raw) - offset) // 4
        if n < 2:
            raise ValueError(f"RAW2 文件数据段过短: {file_path}")

        intensity = np.frombuffer(
            raw[offset:offset + n * 4], dtype="<f4"
        ).astype(float)

        start, step = self._raw2_axis(raw)
        if start is None:
            raise ValueError(
                f"RAW2 文件头中未找到可信的起始 2θ / 步长: {file_path}"
            )
        two_theta = start + step * np.arange(n, dtype=float)

        meta: dict = {"raw2_header_len": offset}
        wl = wavelength_from_anode(
            raw[:offset].decode("latin-1", errors="ignore")
        )
        if wl is not None:
            meta["wavelength"] = wl
        return two_theta, intensity, meta

    @classmethod
    def _raw2_axis(cls, raw: bytes):
        """取 RAW2 头的 (start, step)。定长偏移优先, 失败再扫相邻 float32 对。"""
        import math
        import struct

        def _f(off: int):
            try:
                return struct.unpack_from("<f", raw, off)[0]
            except struct.error:
                return None

        step = _f(cls._RAW2_STEP_OFF)
        start = _f(cls._RAW2_START_OFF)
        ok = (
            step is not None and start is not None
            and math.isfinite(step) and math.isfinite(start)
            and 0.0 < step <= 1.0 and 0.0 <= start < 180.0
        )
        if not ok:
            step = start = None
            for off in range(64, max(72, min(len(raw) - 8, 4096)), 4):
                s, t = _f(off), _f(off + 4)
                if s is None or t is None:
                    continue
                if not (math.isfinite(s) and math.isfinite(t)):
                    continue
                # 步长要"像个步长" (排除头里 0.000169 之类的杂散浮点)
                if 0.001 <= s <= 0.5 and 0.1 <= t < 90.0:
                    step, start = s, t
                    break
        if step is None:
            return None, None
        # RAW2 头把起始角/步长都存成 float32: 0.02 会变成 0.019999999552965164,
        # 乘上几千个序号后累积漂移能到 3e-6° (末点 150.000 会读成 149.999997)。
        # 用 8 位有效数字归一, 既抹掉 float32 噪声, 又保留真实的小数步长(如 0.019999)。
        return float(f"{start:.8g}"), float(f"{step:.8g}")

    def _load_mdi(
        self, file_path: Path, fmt: str = "mdi", **kwargs
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """加载 MDI 文本格式 (定宽整数强度)。

        实测结构 (test_xrd/geshi/4-1.mdi):
          行1: 日期 + 样品名
          行2: ``start  step  <scale>  <anode>  wavelength  stop  count``
          其余: 定宽整数强度 (每行 8 个, 栏宽 8)

        注意 (实测坑): 该文件 ``count=7250`` 却带着 5.000→150.000 / 步长 0.020
        的扫描区间 —— 也就是转换时丢了**第一个**通道 (207)。若直接按 start 起算,
        整条谱会平移一个步长 (所有峰位置错 0.02°)。故当 ``start + step*(n-1)``
        对不上头里的 stop 时, 改以 stop 反推 start, 与 ``.dat/.txt/.xy`` 对齐。
        """
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            raise ValueError(f"MDI 文件内容不足: {file_path}")

        head = lines[1]
        head_nums: list[float] = []
        for tok in head.split():
            try:
                head_nums.append(float(tok))
            except ValueError:
                continue
        if len(head_nums) < 2:
            raise ValueError(f"MDI 文件头无法解析 start/step: {file_path}")
        start, step = head_nums[0], head_nums[1]

        values: list[float] = []
        for ln in lines[2:]:
            for tok in ln.split():
                try:
                    values.append(float(tok))
                except ValueError:
                    continue
        if len(values) < 2:
            raise ValueError(f"MDI 文件没有有效强度数据: {file_path}")
        intensity = np.asarray(values, dtype=float)
        n = len(intensity)

        # 用头里的 stop 校正"丢首点"造成的整体错位
        if step > 0:
            want = start + step * (n - 1)
            span = step * max(n - 1, 1)
            cands = [c for c in head_nums[2:] if abs(c - want) <= 0.05 * span]
            if cands:
                stop = min(cands, key=lambda c: abs(c - want))
                if abs(start + step * (n - 1) - stop) > step / 2:
                    start = stop - step * (n - 1)

        two_theta = start + step * np.arange(n, dtype=float)
        meta: dict = {}
        wl = wavelength_from_anode(head)
        if wl is not None:
            meta["wavelength"] = wl
        return two_theta, intensity, meta

    def _load_brml(
        self, file_path: Path, fmt: str = "brml", **kwargs
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """加载Bruker .brml格式 (基于ZIP的XML格式)"""
        import zipfile
        import io

        try:
            with zipfile.ZipFile(str(file_path), "r") as zf:
                # 尝试查找数据文件
                data_files = [f for f in zf.namelist() if "data" in f.lower()]
                if not data_files:
                    # 尝试所有XML文件
                    xml_files = [f for f in zf.namelist() if f.endswith(".xml")]
                    if xml_files:
                        data_files = [xml_files[0]]

                if not data_files:
                    raise ValueError(f"BRML文件 {file_path} 中找不到数据文件")

                # 读取第一个数据文件
                with zf.open(data_files[0]) as f:
                    xml_content = f.read().decode("utf-8", errors="ignore")

        except (zipfile.BadZipFile, KeyError) as e:
            raise ValueError(f"BRML文件解析失败: {e}") from e

        # 用XML解析器处理
        try:
            tree = ET.parse(io.StringIO(xml_content))
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"BRML XML解析错误: {e}") from e

        # 提取数据
        two_theta = []
        intensity = []

        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if "positions" in tag.lower() or "2theta" in tag.lower():
                if elem.text and elem.text.strip():
                    vals = [float(v) for v in elem.text.split()]
                    if len(vals) > len(two_theta):
                        two_theta = vals
            if "intensities" in tag.lower() or "counts" in tag.lower():
                if elem.text and elem.text.strip():
                    vals = [float(v) for v in elem.text.split()]
                    if len(vals) > len(intensity):
                        intensity = vals

        if not two_theta or not intensity:
            raise ValueError("无法从BRML文件提取有效数据")

        min_len = min(len(two_theta), len(intensity))
        return np.array(two_theta[:min_len]), np.array(intensity[:min_len]), {}


def save_xy(
    data: XRDData,
    file_path: str | Path,
    fmt: str = "xy",
    **kwargs,
) -> None:
    """保存XRD数据

    Args:
        data: XRD数据
        file_path: 输出文件路径
        fmt: 输出格式
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "xy":
        with open(file_path, "w", encoding="utf-8") as f:
            for two_theta, intensity in zip(data.two_theta, data.intensity):
                f.write(f"{two_theta:.6f}\t{intensity:.4f}\n")

    elif fmt == "csv":
        import csv
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["2theta", "intensity"])
            for two_theta, intensity in zip(data.two_theta, data.intensity):
                writer.writerow([f"{two_theta:.6f}", f"{intensity:.4f}"])

    elif fmt == "xrdml":
        # 写入XRDML格式
        with open(file_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<xrdMeasurement xmlns="http://www.xrdml.com/XRDMeasurement/2.1">\n')
            f.write("  <scan>\n")
            f.write("    <dataPoints>\n")
            f.write("      <positions axis=\"2Theta\">\n")
            f.write("        <startPosition>1.0</startPosition>\n")
            f.write(f"        <endPosition>{data.two_theta[-1]:.6f}</endPosition>\n")
            f.write(f"        <positions>{' '.join(f'{v:.6f}' for v in data.two_theta)}</positions>\n")
            f.write("      </positions>\n")
            f.write(f"      <intensities>{' '.join(f'{v:.1f}' for v in data.intensity)}</intensities>\n")
            f.write("    </dataPoints>\n")
            f.write("  </scan>\n")
            f.write("</xrdMeasurement>\n")

    else:
        raise ValueError(f"不支持的输出格式: {fmt}")
