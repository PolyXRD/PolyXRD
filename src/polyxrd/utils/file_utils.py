"""
文件工具
========
文件操作辅助函数。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在

    Args:
        path: 目录路径

    Returns:
        Path对象
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_file_extensions(format: str) -> list[str]:
    """获取格式对应的文件扩展名"""
    extensions = {
        "xy": [".xy"],
        "dat": [".dat"],
        "csv": [".csv"],
        "txt": [".txt"],
        "xrdml": [".xrdml", ".xml"],
        "raw": [".raw"],
        "brml": [".brml"],
        "cif": [".cif"],
        "gpx": [".gpx"],
        "json": [".json"],
        "png": [".png"],
        "pdf": [".pdf"],
        "svg": [".svg"],
        "all": [".*"],
    }
    return extensions.get(format, [".*"])


def detect_xrd_format(file_path: str | Path) -> str:
    """检测XRD文件格式

    Args:
        file_path: 文件路径

    Returns:
        格式标识符
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    format_map = {
        ".xy": "xy",
        ".dat": "dat",
        ".csv": "csv",
        ".txt": "txt",
        ".xrdml": "xrdml",
        ".xml": "xrdml",
        ".raw": "raw",
        ".brml": "brml",
        ".cif": "cif",
        ".gpx": "gpx",
    }

    return format_map.get(suffix, "unknown")


def save_json(data: Any, path: str | Path, indent: int = 2) -> None:
    """保存JSON文件

    Args:
        data: 可序列化的数据
        path: 输出路径
        indent: 缩进空格数
    """
    path = Path(path)
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, default=str)


def load_json(path: str | Path) -> Any:
    """加载JSON文件"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_default_export_dir() -> Path:
    """获取默认导出目录"""
    from polyxrd.config import get_config
    return get_config().get_export_dir()


def get_cif_db_dir() -> Optional[Path]:
    """获取CIF数据库目录"""
    from polyxrd.config import get_config
    path = get_config().get_cif_db_path()
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    return path


def human_readable_size(size_bytes: int) -> str:
    """转换为可读的文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
