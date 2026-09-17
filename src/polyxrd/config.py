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
    app_version: str = "0.13.0"
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
    # 最小峰间距 (度)。XRD 峰 FWHM 仅 0.05~0.5°, 旧值 5.0° 会丢弃相邻强线
    # (ZnO 31.8/34.4/36.3 只剩 36.3), 严重损害物相识别召回。见 0.9.11 基准。
    default_peak_distance: float = 0.5
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
    # PDF2-2004 数据库: ICDD PDF-2 2004 版, 自用验证库
    pdf2_raw_path: Path = field(default_factory=lambda: Path("E:/TEMP/XRD-PDF2-2004/pdf2 - 2004.dat"))
    pdf2_db_path: Path = field(default_factory=lambda: AppConfig._PROJECT_ROOT / "cod_data" / "PDF2_2004.sqlite")
    export_dir: Path = field(default_factory=lambda: Path.home() / "PolyXRD_exports")
    log_dir: Path = field(default_factory=lambda: Path.home() / ".polyxrd" / "logs")

    def get_export_dir(self) -> Path:
        return self.export_dir

    # ── 外挂数据库路径解析 (0.10.0) ──────────────────────────

    def user_db_dir(self) -> Path:
        """用户可写的数据库落脚目录 (``~/.polyxrd/cif_db``)。

        PyInstaller 打包后 :attr:`_PROJECT_ROOT` 指向安装目录内的 ``_internal``,
        而安装器用的是 ``PrivilegesRequired=lowest`` (装在 Program Files 时普通
        用户无写权限)。所以"解压后随手把 .sqlite 放哪"需要一个始终可写的默认
        落点 —— 就是这里。放在这里的库即使没走 GUI 导入也会被自动发现。
        """
        return Path.home() / ".polyxrd" / "cif_db"

    def _resolve_db_path(self, key: str, default: Path,
                         alt_names: tuple[str, ...]) -> Path:
        """统一的库路径解析: 用户导入 > 默认位置 > 用户目录兜底。

        默认位置**存在**时优先于用户目录兜底 —— 开发/内嵌整包场景下项目内
        的库才是预期数据源, 不该被用户目录里同名的旧库悄悄顶掉。
        """
        imported = self.user_db_path(key)
        if imported is not None:
            return imported
        if default.exists():
            return default
        for name in alt_names:
            cand = self.user_db_dir() / name
            if cand.exists():
                return cand
        return default

    def get_cod_db_path(self) -> Path:
        """获取当前 COD 无机物库路径 (支持用户导入的外部库覆盖)。"""
        return self._resolve_db_path(
            "cod_db_path", self.cod_db_path, ("COD_inorganics.sqlite",))

    def get_cif_db_path(self) -> Path:
        return self.cif_db_path

    def get_cod_svn_path(self) -> Path:
        return self.cod_svn_path

    def get_cod_index_db_path(self) -> Path:
        return self.cod_index_db_path

    def set_cod_db_path(self, path: str | Path) -> None:
        """设置用户导入的 COD 数据库路径,并持久化。

        传入空字符串或 None 可清除自定义路径,回退到项目内默认。
        """
        self._update_user_db_path("cod_db_path", path)

    def _user_db_paths_file(self) -> Path:
        return Path.home() / ".polyxrd" / "user_db_paths.json"

    def _load_user_db_paths(self) -> dict:
        """读取 user_db_paths.json, 返回字典 (损坏/缺失时返回空字典)。

        COD 与 PDF2 共用这一个文件, 所以**读写都必须按 key 增量合并**,
        整体覆盖写会把另一个库的路径悄悄抹掉。
        """
        cfg_file = self._user_db_paths_file()
        if not cfg_file.exists():
            return {}
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _update_user_db_path(self, key: str, path: str | Path | None) -> None:
        """按 key 增量更新 user_db_paths.json (不触碰其它 key)。"""
        cfg_file = self._user_db_paths_file()
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        data = self._load_user_db_paths()
        if not path:
            data.pop(key, None)
        else:
            data[key] = str(Path(path).resolve())
        cfg_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def user_db_path(self, key: str) -> Optional[Path]:
        """读取某个数据库槽位的用户导入路径。

        未设置、或设了但**文件已不存在** (用户挪走了外挂库) 都返回 None
        —— 这样上层会自动回退到默认路径, 而不是抱一个死路径报错。
        """
        p = self._load_user_db_paths().get(key)
        if p and Path(p).exists():
            return Path(p)
        return None

    def _load_user_cod_db_path(self) -> Optional[str]:
        """读取用户持久化的 COD 路径,返回 None 表示未设置。"""
        p = self.user_db_path("cod_db_path")
        return str(p) if p else None

    # ── PDF2-2004 数据库路径 ────────────────────────────────

    def get_pdf2_raw_path(self) -> Path:
        """PDF2-2004 原始 .dat 文件路径。"""
        return self.pdf2_raw_path

    def get_pdf2_db_path(self) -> Path:
        """获取当前 PDF2-2004 SQLite 索引路径。

        优先级:用户导入的外部库 > 项目内默认路径 > 用户目录兜底
        (与 :meth:`get_cod_db_path` 对称)。
        """
        return self._resolve_db_path(
            "pdf2_db_path", self.pdf2_db_path, ("PDF2_2004.sqlite",))

    def set_pdf2_db_path(self, path: str | Path) -> None:
        """设置 PDF2-2004 SQLite 路径并持久化 (空值 = 清除, 回退默认)。"""
        self._update_user_db_path("pdf2_db_path", path)

    # ── COD 全库索引路径 (cod_index.sqlite) ─────────────────

    def get_cod_index_sqlite_path(self) -> Optional[Path]:
        """用户导入的 COD 全库索引 (cod_index.sqlite) 路径。

        与 COD 无机物库/PDF2 不同, 这个库原本由 `cod_local` 从打包资源
        部署到 `cif_db_path/cod_index.sqlite`, 并在多个候选目录间搜索。
        0.10.0 起数据库改外挂, 所以这里加一条**用户导入优先**的旁路:
        只有用户显式导入且文件确实存在时才返回, 否则返回 None 让
        `cod_local._index_db_path()` 走原有搜索/部署逻辑。
        """
        return self.user_db_path("cod_index_db_path")

    def set_cod_index_db_path(self, path: str | Path | None) -> None:
        """设置用户导入的 COD 全库索引路径并持久化 (空值 = 清除)。"""
        self._update_user_db_path("cod_index_db_path", path)


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
