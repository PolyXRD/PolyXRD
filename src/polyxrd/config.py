"""
PolyXRD 包配置
==============
包含应用配置、数据路径、实验参数等。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Optional


@dataclass
class AppConfig:
    """应用配置类"""

    # 应用信息
    app_name: str = "PolyXRD"
    app_version: str = "0.9.0"
    app_org: str = "PolyXRD"

    # 窗口设置
    window_width: int = 1280
    window_height: int = 800

    # 默认参数
    default_wavelength: float = 1.5406  # Cu Kα1
    default_two_theta_range: tuple[float, float] = (5.0, 80.0)
    default_d_min: float = 1.0
    default_d_max: float = 100.0

    # 文件格式
    supported_formats: list[str] = field(default_factory=lambda: [
        ".xy", ".dat", ".csv", ".txt", ".xrdml", ".xml", ".raw", ".brml",
    ])

    # Rietveld精修参数
    default_rietveld_strategy: str = "sequential"
    default_max_cycles: int = 20
    default_tolerance: float = 0.0001

    # 峰检测默认参数
    default_peak_height: float = 0.05
    default_peak_distance: float = 5.0
    default_peak_prominence: float = 0.01

    # 背景扣除默认参数
    default_bg_method: str = "snip"
    default_smooth_method: str = "savgol"
    default_smooth_window: int = 11

    # 数据库
    # 项目内路径,便于整体迁移;如需移到其他盘,只改这一处即可
    _PROJECT_ROOT: ClassVar[Path] = Path(__file__).resolve().parents[2]
    cif_db_path: Path = field(default_factory=lambda: AppConfig._PROJECT_ROOT / "cod_data" / "cif_db")
    cod_svn_path: Path = field(default_factory=lambda: AppConfig._PROJECT_ROOT / "cod_data" / "cod_svn")
    cod_index_db_path: Path = field(default_factory=lambda: AppConfig._PROJECT_ROOT / "cod_data" / "cod_index.db")
    # COD 无机物库: 从 COD 筛选的无机物子集 (71199 物相,含 d-I 峰)
    # 默认指向项目内路径;允许用户通过 UI 导入外部数据库后覆盖
    cod_db_path: Path = field(default_factory=lambda: AppConfig._PROJECT_ROOT / "cod_data" / "COD_inorganics.sqlite")
    export_dir: Path = field(default_factory=lambda: Path.home() / "PolyXRD_exports")
    log_dir: Path = field(default_factory=lambda: Path.home() / ".polyxrd" / "logs")

    def get_export_dir(self) -> Path:
        return self.export_dir

    def get_cif_db_path(self) -> Path:
        return self.cif_db_path

    def get_cod_svn_path(self) -> Path:
        return self.cod_svn_path

    def get_cod_index_db_path(self) -> Path:
        return self.cod_index_db_path

    def get_cod_db_path(self) -> Path:
        """获取当前 COD 数据库路径。

        优先级:用户导入的外部数据库 > 项目内默认路径。
        用户导入路径持久化在 ~/.polyxrd/user_db_paths.json。
        """
        user_path = self._load_user_cod_db_path()
        if user_path:
            return Path(user_path)
        return self.cod_db_path

    def set_cod_db_path(self, path: str | Path) -> None:
        """设置用户导入的 COD 数据库路径,并持久化。

        传入空字符串或 None 可清除自定义路径,回退到项目内默认。
        """
        cfg_file = self._user_db_paths_file()
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        if not path:
            cfg_file.write_text("{}", encoding="utf-8")
            return
        path = str(Path(path).resolve())
        data = {"cod_db_path": path}
        cfg_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _user_db_paths_file(self) -> Path:
        return Path.home() / ".polyxrd" / "user_db_paths.json"

    def _load_user_cod_db_path(self) -> Optional[str]:
        """读取用户持久化的数据库路径,返回 None 表示未设置。"""
        cfg_file = self._user_db_paths_file()
        if not cfg_file.exists():
            return None
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            path = data.get("cod_db_path")
            if path and Path(path).exists():
                return path
        except (json.JSONDecodeError, OSError):
            pass
        return None


# 单例模式
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """获取全局配置"""
    global _config
    if _config is None:
        _config = AppConfig()
        _config.cif_db_path.mkdir(parents=True, exist_ok=True)
        _config.export_dir.mkdir(parents=True, exist_ok=True)
        _config.log_dir.mkdir(parents=True, exist_ok=True)
    return _config
