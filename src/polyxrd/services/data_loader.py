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


class DataLoader:
    """XRD数据加载器

    支持格式:
    - .xy: 两列文本 (2θ, intensity)
    - .dat: 三列文本 (2θ, intensity, 可能有背景)
    - .csv: CSV格式
    - .txt: 通用文本格式
    - .xrdml: XML格式 (Bruker)
    - .xml: 通用XRD XML
    - .raw: 二进制格式
    - .brml: Bruker专用格式
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
        """加载二进制RAW格式"""
        import struct

        with open(file_path, "rb") as f:
            header = f.read(100)  # 读取头部
            # 跳过头部数据
            # ...具体格式取决于仪器

            # 读取数据部分
            # 假设是float32数组
            data = f.read()

        # 尝试解析
        try:
            values = np.frombuffer(data, dtype=np.float32)
            if len(values) >= 2:
                # 前半2theta，后半intensity
                n = len(values) // 2
                two_theta = values[:n]
                intensity = values[n:n * 2]
            else:
                raise ValueError("二进制数据太短")
        except Exception as e:
            raise ValueError(f"无法解析RAW文件: {e}") from e

        return two_theta, intensity, {}

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
