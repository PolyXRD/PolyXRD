"""
PolyXRD 包配置
==============
包含应用配置、数据路径、实验参数等。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Optional

from polyxrd import __version__


@dataclass
class AppConfig:
    """应用配置类"""

    # 应用信息
    app_name: str = "PolyXRD"
    # v2.3.0: 从包 __init__.__version__ 取值, 消除双源漂移 (曾漏 bump 卡在 2.1.0)
    app_version: str = __version__
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
    cod_index_db_path: Path = field(default_factory=lambda: AppConfig._PROJECT_ROOT / "cod_data" / "cod_index.sqlite")
    # COD 无机物库: 从 COD 筛选的无机物子集 (71199 物相,含 d-I 峰)
    # 默认指向项目内路径;允许用户通过 UI 导入外部数据库后覆盖
    cod_db_path: Path = field(default_factory=lambda: AppConfig._PROJECT_ROOT / "cod_data" / "COD_inorganics.sqlite")
    # PDF2-2004 数据库: ICDD PDF-2 2004 版, 自用验证库
    # (v2.1 P3: 原先硬编码开发机绝对路径的 pdf2_raw_path 字段已删除 —— 零调用点)
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
        """获取当前 COD 无机物库路径 (支持用户导入的外部库覆盖)。

        v0.14.0 起**瘦身索引式优先** (``COD_inorganics_index.sqlite``):
        与 COD 全库索引同形态 —— 不内嵌 CIF, 由 ``cod/cif`` 目录按需读取
        (本地缺失时回退 COD REST 在线下载), 体积约为内嵌版的 1/3。
        完整内嵌版 (``COD_inorganics.sqlite``) 作为回退, 两者数据逐行一致。
        """
        imported = self.user_db_path("cod_db_path")
        if imported is not None:
            return imported
        # 默认位置: 瘦身索引式优先, 回退完整内嵌版
        for name in ("COD_inorganics_index.sqlite", "COD_inorganics.sqlite"):
            cand = self.cod_db_path.with_name(name)
            if cand.exists():
                return cand
        # 用户目录兜底: 同样瘦身版优先
        for name in ("COD_inorganics_index.sqlite", "COD_inorganics.sqlite"):
            cand = self.user_db_dir() / name
            if cand.exists():
                return cand
        return self.cod_db_path

    def get_cif_db_path(self) -> Path:
        return self.cif_db_path

    def get_cod_svn_path(self) -> Path:
        return self.cod_svn_path

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

    def _save_user_db_paths(self, data: dict) -> None:
        """整体写回 ``user_db_paths.json`` (调用方负责先读-改-合并)。"""
        cfg_file = self._user_db_paths_file()
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _update_user_db_path(self, key: str, path: str | Path | None) -> None:
        """按 key 增量更新 user_db_paths.json (不触碰其它 key)。"""
        data = self._load_user_db_paths()
        if not path:
            data.pop(key, None)
        else:
            data[key] = str(Path(path).resolve())
        self._save_user_db_paths(data)

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

    # ── polyDB 外挂库路径 (v4.0.0) ──────────────────────────

    #: polyDB 变体 → user_db_paths.json 里的槽位 key。
    #: polyDB 是**目录容器**（不是单个文件），两个变体各自独立挂载。
    #: ClassVar: 这是全类共享的常量映射, 不是实例字段 (ruff RUF012)。
    POLYDB_VARIANTS: ClassVar[dict[str, str]] = {
        "cod-inorg": "polydb_inorg_path",
        "cod-full": "polydb_full_path",
    }

    #: polyDB 变体 → 目录名兜底关键字（小写）。正常以 ``meta.json`` 的
    #: ``variant`` 字段为准，只有 meta 读不出时才用文件名判。
    _POLYDB_NAME_HINTS: ClassVar[dict[str, tuple[str, ...]]] = {
        "cod-inorg": ("cod-inorg", "inorg"),
        "cod-full": ("cod-full", "full"),
    }

    #: 记住"用户显式取消挂载过哪些变体"的键。没有它的话, 取消挂载后下次
    #: 启动又被自动发现出来的默认库顶回来, 用户会以为卸载没生效。
    _POLYDB_DISABLED_KEY: ClassVar[str] = "polydb_disabled"

    def _polydb_search_roots(self) -> list[Path]:
        """默认 polyDB 的候选父目录, 顺序即优先级。

        1. ``POLYXRD_POLYDB_DIR`` —— 显式指定（部署脚本/测试用）；
        2. 打包运行：``<exe 所在目录>/databases`` —— 便携版把库放这里，
           解压即可用（安装到 Program Files 时该目录只读，但读取没问题）；
        3. 源码运行：仓库 ``databases/`` + 构库仓库的 ``polydb/`` 产物目录。
        """
        roots: list[Path] = []
        env = os.environ.get("POLYXRD_POLYDB_DIR", "").strip()
        if env:
            roots.append(Path(env))
        if getattr(sys, "frozen", False):
            try:
                roots.append(Path(sys.executable).resolve().parent / "databases")
            except OSError:
                pass
        else:
            repo = Path(__file__).resolve().parents[2]
            roots.append(repo / "databases")
            # 源码态开发: 构库仓库与软件仓库同级 (不写死盘符 —— 换机器/换盘即失效)
            roots.append(repo.parent / "PolyXRD-DataBase" / "polydb")
        return roots

    def discover_polydb(self, variant: str = "cod-inorg") -> Optional[Path]:
        """在候选目录里找该变体最新的一份 polyDB; 找不到返回 None。

        Args:
            variant: ``cod-inorg`` / ``cod-full``。

        Returns:
            polyDB 目录；同一目录下有多份时取**目录名最大**的那份
            （产物名带快照日期，如 ``COD-Inorg-20261021.polyDB``，字符串序即时间序）。
        """
        hints = self._POLYDB_NAME_HINTS.get(variant)
        if not hints:
            return None
        found: list[Path] = []
        for root in self._polydb_search_roots():
            for cand in self._iter_polydb_dirs(root):
                meta_variant = self._read_polydb_variant(cand)
                if meta_variant:
                    if meta_variant == variant:
                        found.append(cand)
                    continue
                # meta 读不出来时退回文件名判据
                low = cand.name.lower()
                if any(h in low for h in hints):
                    found.append(cand)
        if not found:
            return None
        return sorted(found, key=lambda p: p.name)[-1]

    @staticmethod
    def _iter_polydb_dirs(root: Path) -> list[Path]:
        """``root`` 自身是 polyDB 就返回它，否则列出其下的 polyDB 子目录。"""
        def _is_polydb(d: Path) -> bool:
            return (d / "meta.json").is_file() and (d / "index.sqlite").is_file()

        if not root.is_dir():
            return []
        if _is_polydb(root):
            return [root]
        try:
            return [c for c in sorted(root.iterdir())
                    if c.is_dir() and _is_polydb(c)]
        except OSError:
            return []

    @staticmethod
    def _read_polydb_variant(path: Path) -> str:
        try:
            meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(meta.get("variant") or "") if isinstance(meta, dict) else ""

    def get_polydb_path(self, variant: str = "cod-inorg") -> Optional[Path]:
        """当前生效的 polyDB 目录; 一份都没有时返回 None。

        解析顺序: **用户挂载的路径** → **自动发现的默认库**。
        默认库让"解压便携版就能检索"成立, 不需要用户先手工挂载;
        用户显式取消挂载过的变体不再自动发现（见 :meth:`set_polydb_path`）。
        """
        key = self.POLYDB_VARIANTS.get(variant)
        if not key:
            return None
        p = self.user_db_path(key)
        if p is not None:
            return p if p.is_dir() else None
        disabled = self._load_user_db_paths().get(self._POLYDB_DISABLED_KEY) or []
        if isinstance(disabled, list) and variant in disabled:
            return None
        return self.discover_polydb(variant)

    def set_polydb_path(self, path: str | Path | None,
                        variant: str = "cod-inorg") -> None:
        """挂载/取消挂载某个 polyDB 变体 (空值 = 取消挂载)。

        取消挂载会记住"这个变体不要再用默认库", 否则下次启动自动发现又会
        把它挂回来, 界面上表现为"卸载不掉"。
        """
        key = self.POLYDB_VARIANTS.get(variant)
        if not key:
            raise ValueError("未知 polyDB 变体: %s" % variant)
        self._update_user_db_path(key, path)
        self._set_polydb_disabled(variant, disabled=not path)

    def _set_polydb_disabled(self, variant: str, *, disabled: bool) -> None:
        data = self._load_user_db_paths()
        cur = data.get(self._POLYDB_DISABLED_KEY)
        cur = [v for v in cur if isinstance(v, str)] if isinstance(cur, list) else []
        cur = [v for v in cur if v != variant]
        if disabled:
            cur.append(variant)
        if cur:
            data[self._POLYDB_DISABLED_KEY] = cur
        else:
            data.pop(self._POLYDB_DISABLED_KEY, None)
        self._save_user_db_paths(data)

    # ── CIF 落盘缓存 (v4.0.0 收口: 从三处硬编码 Path.home() 提到一处) ──

    def cif_cache_dir(self) -> Path:
        """库内 BLOB 的 CIF 落盘目录 (GSAS-II / MAUD 要求真实磁盘文件)。

        默认 ``~/.polyxrd/cif_cache``。可用环境变量
        ``POLYXRD_CIF_CACHE_DIR`` 覆盖 —— 便携版想放程序目录旁边、或在
        用户目录不可写（只读沙箱 / 受控文件夹）时用, 免得写盘失败后
        精修悄悄拿不到结构。缓存目录必须可写, 否则写失败会回退为"无 CIF"。
        """
        env = os.environ.get("POLYXRD_CIF_CACHE_DIR", "").strip()
        if env:
            return Path(env)
        return Path.home() / ".polyxrd" / "cif_cache"

    # ── 外部精修程序路径 (v0.15 M25) ────────────────────────

    #: 合法的外部工具配置 key (GSAS-II / MAUD / FullProf)
    EXTERNAL_TOOL_KEYS = (
        "external_gsas2_path",
        "external_maud_path",
        "external_fullprof_path",
    )

    def _external_tools_file(self) -> Path:
        return Path.home() / ".polyxrd" / "external_tools.json"

    def _load_external_tools(self) -> dict:
        """读取 external_tools.json (损坏/缺失返回空字典)。三个工具共用
        一个文件, 读写按 key 增量合并, 不整体覆盖。"""
        cfg_file = self._external_tools_file()
        if not cfg_file.exists():
            return {}
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def get_external_tool_path(self, key: str) -> Optional[Path]:
        """读取外部工具可执行文件路径; 未配置返回 None。

        注意与 ``user_db_path`` 不同: 即使路径当前不存在也返回 (UI 层
        负责 validate 提示), 避免用户暂时断开移动硬盘等场景丢配置。
        """
        p = self._load_external_tools().get(key)
        return Path(p) if p else None

    def set_external_tool_path(self, key: str, path: str | Path | None) -> None:
        """设置外部工具路径并持久化 (空值 = 清除该 key)。"""
        if key not in self.EXTERNAL_TOOL_KEYS:
            raise ValueError(f"未知的外部工具 key: {key}")
        cfg_file = self._external_tools_file()
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        data = self._load_external_tools()
        if not path:
            data.pop(key, None)
        else:
            data[key] = str(Path(path))
        cfg_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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
