"""
COD 在线搜索服务
==============
通过 Crystallography Open Database (COD) REST API 搜索晶体结构。

支持按化学式、矿物名、空间群、晶胞参数搜索，
并提供 CIF 文件下载、缓存机制和异步搜索能力。
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from polyxrd.config import get_config

# COD API 基础地址
COD_BASE_URL = "https://www.crystallography.net/cod"
COD_SEARCH_URL = f"{COD_BASE_URL}/search.html"
COD_CIF_URL = f"{COD_BASE_URL}/cif"

# 默认请求超时（秒）
DEFAULT_TIMEOUT = 30

# 缓存有效期（秒）
CACHE_TTL = 86400


@dataclass
class CODEntry:
    """COD 数据库条目

    Attributes:
        cod_id: COD 数据库编号
        mineral_name: 矿物名称
        formula: 化学式
        space_group: 空间群
        lattice_params: 晶胞参数字典 (a, b, c, alpha, beta, gamma)
        cif_url: CIF 文件下载链接
    """
    cod_id: int = 0
    mineral_name: str = ""
    formula: str = ""
    space_group: str = ""
    lattice_params: dict[str, float] = field(default_factory=dict)
    cif_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cod_id": self.cod_id,
            "mineral_name": self.mineral_name,
            "formula": self.formula,
            "space_group": self.space_group,
            "lattice_params": self.lattice_params,
            "cif_url": self.cif_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CODEntry":
        return cls(
            cod_id=data.get("cod_id", 0),
            mineral_name=data.get("mineral_name", ""),
            formula=data.get("formula", ""),
            space_group=data.get("space_group", ""),
            lattice_params=data.get("lattice_params", {}),
            cif_url=data.get("cif_url", ""),
        )


@dataclass
class SearchResult:
    """搜索结果

    Attributes:
        entries: COD 条目列表
        total_count: 匹配的总条目数
        search_time: 搜索耗时（秒）
    """
    entries: list[CODEntry] = field(default_factory=list)
    total_count: int = 0
    search_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "total_count": self.total_count,
            "search_time": self.search_time,
        }


class CODSearcher:
    """COD 在线搜索服务

    通过 COD REST API 搜索晶体结构，支持按化学式、矿物名、
    空间群、晶胞参数等条件检索。

    内置本地缓存机制，避免重复请求相同搜索。

    Usage:
        searcher = CODSearcher()
        result = searcher.search(formula="SiO2")
        cif_content = searcher.get_cif(result.entries[0].cod_id)
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._config = get_config()
        self._cache_dir: Path = self._config.cif_db_path / "cod_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._search_history: list[dict[str, Any]] = []
        self._load_history()

    # ------------------------------------------------------------------
    # 公共搜索接口
    # ------------------------------------------------------------------

    def search(
        self,
        formula: Optional[str] = None,
        mineral_name: Optional[str] = None,
        space_group: Optional[str] = None,
        a: Optional[float] = None,
        b: Optional[float] = None,
        c: Optional[float] = None,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        gamma: Optional[float] = None,
    ) -> SearchResult:
        """搜索 COD 数据库

        Args:
            formula: 化学式 (如 "SiO2")
            mineral_name: 矿物名称 (如 "Quartz")
            space_group: 空间群 (如 "P3121")
            a: 晶胞参数 a (Å)
            b: 晶胞参数 b (Å)
            c: 晶胞参数 c (Å)
            alpha: 晶胞角度 alpha (度)
            beta: 晶胞角度 beta (度)
            gamma: 晶胞角度 gamma (度)

        Returns:
            SearchResult 搜索结果

        Raises:
            ValueError: 无任何搜索条件时
            ConnectionError: 网络不可用时
            TimeoutError: 请求超时时
            RuntimeError: API 返回错误时
        """
        params = self._build_params(
            formula=formula,
            mineral_name=mineral_name,
            space_group=space_group,
            a=a, b=b, c=c,
            alpha=alpha, beta=beta, gamma=gamma,
        )

        if not params:
            raise ValueError("至少需要提供一个搜索条件")

        cache_key = self._make_cache_key(params)
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._add_to_history(params, cached)
            return cached

        start_time = time.time()
        raw_html = self._fetch_search_results(params)
        entries = self._parse_search_results(raw_html)
        elapsed = time.time() - start_time

        result = SearchResult(
            entries=entries,
            total_count=len(entries),
            search_time=round(elapsed, 3),
        )

        self._set_cached(cache_key, result)
        self._add_to_history(params, result)
        return result

    def get_cif(self, cod_id: int) -> Optional[str]:
        """下载指定 COD 条目的 CIF 文件内容

        Args:
            cod_id: COD 数据库编号

        Returns:
            CIF 文件内容字符串，失败返回 None
        """
        cache_path = self._cache_dir / f"cif_{cod_id}.cif"

        if cache_path.exists():
            content = cache_path.read_text(encoding="utf-8")
            if content and "data_" in content:
                return content

        url = f"{COD_CIF_URL}/{cod_id}.cif"
        try:
            content = self._http_get(url)
            if content and "data_" in content:
                cache_path.write_text(content, encoding="utf-8")
                return content
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # 历史记录
    # ------------------------------------------------------------------

    def get_history(self) -> list[dict[str, Any]]:
        """获取搜索历史记录"""
        return list(self._search_history)

    def clear_history(self) -> None:
        """清空搜索历史"""
        self._search_history.clear()
        self._save_history()

    def clear_cache(self) -> None:
        """清空本地缓存"""
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_params(
        formula: Optional[str],
        mineral_name: Optional[str],
        space_group: Optional[str],
        a: Optional[float],
        b: Optional[float],
        c: Optional[float],
        alpha: Optional[float],
        beta: Optional[float],
        gamma: Optional[float],
    ) -> dict[str, str]:
        """构建 COD API 请求参数"""
        params: dict[str, str] = {}

        if formula:
            params["formula"] = formula
        if mineral_name:
            params["mineral"] = mineral_name
        if space_group:
            params["sg"] = space_group
        if a is not None:
            params["a"] = str(a)
        if b is not None:
            params["b"] = str(b)
        if c is not None:
            params["c"] = str(c)
        if alpha is not None:
            params["alpha"] = str(alpha)
        if beta is not None:
            params["beta"] = str(beta)
        if gamma is not None:
            params["gamma"] = str(gamma)

        return params

    def _fetch_search_results(self, params: dict[str, str]) -> str:
        """发送搜索请求并返回原始 HTML"""
        query_string = urllib.parse.urlencode(params)
        url = f"{COD_SEARCH_URL}?{query_string}"
        return self._http_get(url)

    def _http_get(self, url: str) -> str:
        """执行 HTTP GET 请求

        Args:
            url: 请求 URL

        Returns:
            响应文本内容

        Raises:
            ConnectionError: 网络不可用
            TimeoutError: 请求超时
            RuntimeError: HTTP 错误
        """
        req = urllib.request.Request(url, headers={
            "User-Agent": "PolyXRD/0.3.0 (Crystallography Searcher)",
            "Accept": "text/html,application/xhtml+xml",
        })

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except urllib.error.URLError as e:
            reason = str(e.reason) if hasattr(e, "reason") else str(e)
            if "timed out" in reason.lower() or "timeout" in reason.lower():
                raise TimeoutError(f"请求超时 ({self._timeout}s): {url}") from e
            if "name or service not known" in reason.lower() or "getaddrinfo" in reason.lower():
                raise ConnectionError(f"网络不可用: {reason}") from e
            raise ConnectionError(f"网络请求失败: {reason}") from e
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} 错误: {url}") from e
        except OSError as e:
            raise ConnectionError(f"网络连接错误: {e}") from e

    @staticmethod
    def _parse_search_results(html: str) -> list[CODEntry]:
        """解析 COD 搜索结果 HTML 页面

        Args:
            html: COD 搜索结果页面 HTML

        Returns:
            解析出的 COD 条目列表
        """
        entries: list[CODEntry] = []

        cod_id_pattern = re.compile(
            r'href=["\']/cod/([A-Za-z0-9_]+)\.html["\']', re.IGNORECASE
        )

        # 尝试按表格行解析
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        rows = row_pattern.findall(html)

        if rows:
            for row_html in rows:
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL)
                if not cells:
                    continue

                cell_texts = []
                for cell in cells:
                    text = re.sub(r"<[^>]+>", "", cell).strip()
                    cell_texts.append(text)

                cod_id = 0
                mineral = ""
                formula = ""
                space_group = ""

                for text in cell_texts:
                    text_lower = text.lower()
                    if not cod_id:
                        id_match = re.match(r"^\d+$", text.strip())
                        if id_match:
                            cod_id = int(text.strip())

                    if not mineral and (
                        "mineral" in text_lower
                        or text.istitle()
                    ):
                        mineral = text.strip()

                    if not formula and re.search(
                        r"[A-Z][a-z]?\d*[A-Z][a-z]?\d*", text
                    ):
                        formula_candidate = text.strip()
                        if 2 <= len(formula_candidate) <= 30:
                            formula = formula_candidate

                    if not space_group and re.match(
                        r"^[A-Z]-\d", text.strip()
                    ):
                        space_group = text.strip()

                if cod_id:
                    cif_url = f"{COD_CIF_URL}/{cod_id}.cif"
                    entry = CODEntry(
                        cod_id=cod_id,
                        mineral_name=mineral,
                        formula=formula,
                        space_group=space_group,
                        cif_url=cif_url,
                    )
                    entries.append(entry)

        # 如果表格解析失败，回退到正则全文提取
        if not entries:
            cod_ids = cod_id_pattern.findall(html)
            for cod_id_str in cod_ids:
                try:
                    cod_id = int(cod_id_str)
                except ValueError:
                    continue

                cif_url = f"{COD_CIF_URL}/{cod_id}.cif"
                entries.append(CODEntry(
                    cod_id=cod_id,
                    cif_url=cif_url,
                ))

        return entries

    # ------------------------------------------------------------------
    # 缓存机制
    # ------------------------------------------------------------------

    @staticmethod
    def _make_cache_key(params: dict[str, str]) -> str:
        """生成缓存键"""
        sorted_items = sorted(params.items())
        raw = "&".join(f"{k}={v}" for k, v in sorted_items)
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> Optional[SearchResult]:
        """从缓存读取搜索结果"""
        cache_file = self._cache_dir / f"search_{cache_key}.pkl"
        if not cache_file.exists():
            return None

        try:
            mtime = cache_file.stat().st_mtime
            if time.time() - mtime > CACHE_TTL:
                cache_file.unlink(missing_ok=True)
                return None

            with open(cache_file, "rb") as f:
                data = pickle.load(f)

            if isinstance(data, dict) and "entries" in data:
                entries = [CODEntry.from_dict(e) for e in data["entries"]]
                return SearchResult(
                    entries=entries,
                    total_count=data.get("total_count", 0),
                    search_time=data.get("search_time", 0.0),
                )
        except Exception:
            return None

        return None

    def _set_cached(self, cache_key: str, result: SearchResult) -> None:
        """缓存搜索结果"""
        cache_file = self._cache_dir / f"search_{cache_key}.pkl"
        try:
            with open(cache_file, "wb") as f:
                pickle.dump(result.to_dict(), f)
        except Exception:
            pass

    def _add_to_history(
        self, params: dict[str, str], result: SearchResult
    ) -> None:
        """添加搜索到历史记录"""
        record = {
            "params": params,
            "total_count": result.total_count,
            "search_time": result.search_time,
            "timestamp": time.time(),
        }
        self._search_history.insert(0, record)
        self._search_history = self._search_history[:100]
        self._save_history()

    def _load_history(self) -> None:
        """从磁盘加载搜索历史"""
        history_file = self._cache_dir / "search_history.json"
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    self._search_history = json.load(f)
            except Exception:
                self._search_history = []

    def _save_history(self) -> None:
        """保存搜索历史到磁盘"""
        history_file = self._cache_dir / "search_history.json"
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(self._search_history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


class CODSearchWorker:
    """COD 异步搜索 Worker

    利用 threading 实现后台搜索，避免阻塞主线程。
    通过回调函数返回结果或错误。

    Usage:
        worker = CODSearchWorker()
        worker.finished.connect(on_result)
        worker.failed.connect(on_error)
        worker.start(formula="SiO2")
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._searcher = CODSearcher(timeout=timeout)
        self._cancelled = False
        self._callbacks: dict[str, list] = {
            "finished": [],
            "failed": [],
            "progress": [],
        }

    @property
    def searcher(self) -> CODSearcher:
        return self._searcher

    def connect(self, signal: str, callback) -> None:
        """注册回调函数

        Args:
            signal: 信号名 ("finished", "failed", "progress")
            callback: 回调函数
        """
        if signal in self._callbacks:
            self._callbacks[signal].append(callback)

    def _emit(self, signal: str, *args, **kwargs) -> None:
        """发射信号（调用对应回调列表）"""
        for cb in self._callbacks.get(signal, []):
            try:
                cb(*args, **kwargs)
            except Exception:
                pass

    def start(
        self,
        formula: Optional[str] = None,
        mineral_name: Optional[str] = None,
        space_group: Optional[str] = None,
        a: Optional[float] = None,
        b: Optional[float] = None,
        c: Optional[float] = None,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        gamma: Optional[float] = None,
    ) -> None:
        """在后台线程中执行搜索

        Args:
            formula: 化学式
            mineral_name: 矿物名称
            space_group: 空间群
            a, b, c: 晶胞参数
            alpha, beta, gamma: 晶胞角度
        """
        self._cancelled = False

        def _run() -> None:
            try:
                self._emit("progress", "正在搜索 COD 数据库...")
                result = self._searcher.search(
                    formula=formula,
                    mineral_name=mineral_name,
                    space_group=space_group,
                    a=a, b=b, c=c,
                    alpha=alpha, beta=beta, gamma=gamma,
                )
                if self._cancelled:
                    return
                self._emit("finished", result)
            except Exception as e:
                if not self._cancelled:
                    self._emit("failed", e)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def cancel(self) -> None:
        """取消正在进行的搜索"""
        self._cancelled = True