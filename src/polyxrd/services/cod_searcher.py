"""
COD 在线搜索服务
==============
通过 Crystallography Open Database (COD) 检索晶体结构。

支持按化学式、矿物名、空间群、晶胞参数搜索，
并提供 CIF 文件下载、缓存机制和异步搜索能力。

.. note::
    2026-10 起适配 COD 现行网站（``result.php`` 新界面）：

    * 检索端点为 ``/cod/result.php``——``search.html`` 仅为搜索表单页，
      带 query 参数访问也只会返回表单本身；
    * 矿物名检索参数由 ``mineral`` 改为文献文本检索 ``text1``；
    * 空间群数字用 ``space_group_number``，H-M 符号用 ``spacegroup``
      （且必须是空格分隔的全符号，如 ``P 1 21/c 1``）；
    * 晶胞只接受区间参数（``amin/amax/...``），单值 ``a/b/c`` 已被移除；
    * 化学式要求元素按字母序、空格分隔（如 ``O2 Si``，由
      :func:`_normalize_cod_formula` 归一化）；
    * 结果页链接为相对链接（``1010921.cif``），解析见
      :meth:`CODSearcher._parse_search_results`。
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
#: 现行检索端点。注意：``search.html`` 只是搜索表单页（忽略 query 参数），
#: 真正的检索端点是 ``result.php``。
COD_SEARCH_URL = f"{COD_BASE_URL}/result.php"
#: CIF 直接下载基址：``{COD_CIF_URL}/{cod_id}.cif``
#:（旧 ``/cod/cif/{id}.cif`` 路径在现行网站上已不存在）。
COD_CIF_URL = COD_BASE_URL

# 默认请求超时（秒）
DEFAULT_TIMEOUT = 30

# 缓存有效期（秒）
CACHE_TTL = 86400

# 晶胞检索容差：长度（Å）/ 角度（度）。
# COD 现行界面只接受区间参数（amin/amax/...），单值 a/b/c 已被移除，
# 因此单值检索需要展开为「值 ± 容差」的区间。
CELL_LENGTH_TOLERANCE = 0.1
CELL_ANGLE_TOLERANCE = 0.5

# COD 结果页每页条目数（现行界面默认 20；翻页需 CODSESSION，暂不支持）。
ENTRIES_PER_PAGE = 20

# 缓存结构版本：参数体系 / 解析规则变更时 +1，旧缓存（如 2026-10 之前
# search.html 时代的空结果缓存）即使 TTL 未到也会自动miss。
CACHE_SCHEMA_VERSION = 2


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


# ----------------------------------------------------------------------
# 检索参数归一化辅助（适配 COD 现行 result.php 参数体系）
# ----------------------------------------------------------------------

#: 元素token：``Si`` / ``O2`` / ``H`` …
_ELEMENT_TOKEN_RE = re.compile(r"([A-Z][a-z]?)(\d*\.?\d*)")
#: 纯浮点字面量（无前导/尾随点）
_FLOAT_LITERAL_RE = re.compile(r"^\d+(?:\.\d+)?$")
#: HTML 标签
_TAG_RE = re.compile(r"<[^>]+>")
#: H-M 符号分词：字母段 / 数字段 / 单个符号字符
_HM_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[-/]")


def _strip_tags(text: str) -> str:
    """去 HTML 标签并收敛空白。"""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", str(text))).strip()


def _normalize_cod_formula(formula: str) -> str:
    """把化学式归一化为 COD 检索格式：元素按字母序、空格分隔、计数为 1 省略。

    ``SiO2`` → ``O2 Si``；``Mg(OH)2`` → ``H2 Mg O2``。
    无法解析时原样返回（COD 侧自然返回 0 条，不会抛异常）。
    """
    text = str(formula or "").strip()
    if not text:
        return ""

    # 展开括号（支持嵌套，如 "KAl(SO4)2"）
    for _ in range(5):
        def _expand(match: re.Match) -> str:
            inner, times = match.group(1), match.group(2)
            factor = int(times) if times else 1
            parts = []
            for element, count in _ELEMENT_TOKEN_RE.findall(inner):
                n = int(float(count)) if count else 1
                parts.append(f"{element}{n * factor}")
            return " ".join(parts)

        expanded = re.sub(r"\(([A-Za-z0-9]+)\)(\d*)", _expand, text)
        if expanded == text:
            break
        text = expanded

    counts: dict[str, int] = {}
    for element, count in _ELEMENT_TOKEN_RE.findall(text):
        if not element:
            continue
        n = int(float(count)) if count else 1
        counts[element] = counts.get(element, 0) + n
    if not counts:
        return text
    return " ".join(
        f"{element}{counts[element] if counts[element] != 1 else ''}"
        for element in sorted(counts)
    )


def _spaced_hm_symbol(symbol: str) -> str:
    """把 H-M 符号转为 COD 要求的空格分隔形式。

    ``Fm-3m`` → ``F m -3 m``；已含空格的原样返回（用户按 COD 风格输入）。
    """
    text = str(symbol or "").strip()
    if not text or " " in text:
        return text
    return " ".join(_HM_TOKEN_RE.findall(text))


#: 空间群符号（多种写法）→ 国际编号；惰性构建一次。
_SG_NUMBER_MAP: Optional[dict[str, int]] = None


def _build_sg_number_map() -> dict[str, int]:
    """基于 spglib 构建「H-M 符号 → 空间群编号」映射（缺失 spglib 时返回空表）。"""
    mapping: dict[str, int] = {}
    try:
        import spglib  # type: ignore[import-not-untyped]
    except Exception:  # pragma: no cover - spglib 缺失时退化为符号直传
        return mapping
    try:
        for hall_number in range(1, 531):
            info = spglib.get_spacegroup_type(hall_number)
            if info is None:
                continue
            number = int(info.number)
            for symbol in {info.international_short, info.international_full}:
                variants = {
                    symbol,
                    symbol.replace("_", ""),
                    symbol.replace("_", "").replace(" ", ""),
                    symbol.replace(" ", ""),
                    _spaced_hm_symbol(symbol),
                }
                for variant in variants:
                    if variant:
                        mapping.setdefault(variant, number)
    except Exception:  # pragma: no cover - 防御性：spglib 异常不影响检索主流程
        return mapping
    return mapping


def _space_group_params(space_group: str) -> dict[str, str]:
    """空间群条件 → COD 参数。

    * 纯数字 → ``space_group_number``；
    * 符号 → 先经 spglib 映射为编号（消歧），失败则传 ``spacegroup``
      （空格分隔 H-M 符号）。
    """
    text = str(space_group or "").strip()
    if not text:
        return {}
    if text.isdigit():
        return {"space_group_number": text}

    global _SG_NUMBER_MAP
    if _SG_NUMBER_MAP is None:
        _SG_NUMBER_MAP = _build_sg_number_map()
    for key in (text, _spaced_hm_symbol(text), text.replace(" ", "")):
        number = _SG_NUMBER_MAP.get(key)
        if number:
            return {"space_group_number": str(number)}
    return {"spacegroup": _spaced_hm_symbol(text)}


def _to_float(text: str) -> Optional[float]:
    """宽松浮点转换；失败返回 None。"""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _split_length_angle(token: str) -> tuple[Optional[float], Optional[float]]:
    """拆分 COD 结果页里「c 与 alpha 连写」的 token。

    现行结果页晶胞列为 ``a; b; c alpha; beta; gamma``，c 与 alpha 之间只有
    一个 HTML 注释分隔（标签替换为空格后呈 ``7.16 90``；若注释被直接删除
    则呈连写 ``7.1690``、``5.4355.28`` = c=5.43 + alpha=55.28）。
    两种形态都支持；无法可靠拆分时按整段当长度。
    """
    token = str(token).strip()
    if not token:
        return None, None

    # 形态 1：空白分隔（c alpha）
    ws_parts = token.split()
    if len(ws_parts) == 2 and all(_FLOAT_LITERAL_RE.match(p) for p in ws_parts):
        return float(ws_parts[0]), float(ws_parts[1])

    # 形态 2：连写（calpha），枚举所有可拆分点
    best: Optional[tuple[float, float]] = None
    for split in range(1, len(token)):
        left, right = token[:split], token[split:]
        if not (_FLOAT_LITERAL_RE.match(left) and _FLOAT_LITERAL_RE.match(right)):
            continue
        length, angle = float(left), float(right)
        if 0.5 <= length <= 200.0 and 0.0 < angle <= 180.0:
            # 多个候选时取角度最大者（继续右移只会得到更小的角度后缀）
            if best is None or angle > best[1]:
                best = (length, angle)
    if best is not None:
        return best
    value = _to_float(token)
    return (value, None) if value is not None else (None, None)


def _parse_cell_text(text: str) -> dict[str, float]:
    """解析晶胞列文本 → ``{a, b, c, alpha, beta, gamma}``（缺项不回填）。"""
    parts = [part.strip() for part in str(text).split(";")]
    if len(parts) != 5:
        return {}
    lattice: dict[str, float] = {}
    for key, part in zip(("a", "b"), parts[:2]):
        value = _to_float(part)
        if value is not None:
            lattice[key] = value
    c_value, alpha = _split_length_angle(parts[2])
    if c_value is not None:
        lattice["c"] = c_value
    if alpha is not None:
        lattice["alpha"] = alpha
    for key, part in zip(("beta", "gamma"), parts[3:5]):
        value = _to_float(part)
        if value is not None:
            lattice[key] = value
    return lattice


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

        # total_count 取页面声明的总命中数（可能大于本页条目数），解析失败退回本页条数
        total = self._parse_total_count(raw_html)
        result = SearchResult(
            entries=entries,
            total_count=total if total is not None else len(entries),
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
        """构建 COD result.php 请求参数（现行参数体系）"""
        params: dict[str, str] = {}

        # 化学式：元素按字母序空格分隔（COD 要求，如 "O2 Si"）
        if formula:
            params["formula"] = _normalize_cod_formula(formula)
        # 矿物名：现行 COD 已移除 mineral 参数，改用文献文本检索 text1
        if mineral_name:
            params["text1"] = str(mineral_name).strip()
        # 空间群：数字 → space_group_number；符号 → 编号映射或 spacegroup
        if space_group:
            params.update(_space_group_params(space_group))

        # 晶胞：现行 COD 只接受区间参数（amin/amax/...），单值 ± 容差展开
        for key, value in (("a", a), ("b", b), ("c", c)):
            if value is None:
                continue
            params[f"{key}min"] = f"{value - CELL_LENGTH_TOLERANCE:.4f}"
            params[f"{key}max"] = f"{value + CELL_LENGTH_TOLERANCE:.4f}"
        for key, value in (
            ("alp", alpha), ("bet", beta), ("gam", gamma)
        ):
            if value is None:
                continue
            params[f"{key}min"] = f"{value - CELL_ANGLE_TOLERANCE:.4f}"
            params[f"{key}max"] = f"{value + CELL_ANGLE_TOLERANCE:.4f}"

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
        """解析 COD 搜索结果 HTML 页面（现行 result.php 新布局）

        新布局为结果表格，列为：``COD ID | Links | Formula | Space group |
        Cell parameters | Cell volume``；条目链接是**相对链接**
        （``1010921.html`` / ``1010921.cif``）。旧布局（绝对链接
        ``/cod/NNNN.html``）作为兜底仍然支持。

        Args:
            html: COD 搜索结果页面 HTML

        Returns:
            解析出的 COD 条目列表
        """
        entries: list[CODEntry] = []

        # ---- 现行新布局：按表格行解析 ----
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        cell_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
        for row_html in row_pattern.findall(html):
            cells = [_strip_tags(cell) for cell in cell_pattern.findall(row_html)]
            if len(cells) < 5:
                continue
            id_match = re.search(r"\b(\d{3,})\b", cells[0])
            if not id_match:
                continue
            cod_id = int(id_match.group(1))

            formula = cells[2] if len(cells) > 2 else ""
            space_group = cells[3] if len(cells) > 3 else ""
            lattice = _parse_cell_text(cells[4]) if len(cells) > 4 else {}

            cif_url = f"{COD_CIF_URL}/{cod_id}.cif"
            link_match = re.search(
                r"href=[\"']([^\"']+\.cif)[\"']", row_html, re.IGNORECASE
            )
            if link_match:
                cif_url = urllib.parse.urljoin(f"{COD_BASE_URL}/", link_match.group(1))

            entries.append(CODEntry(
                cod_id=cod_id,
                mineral_name="",  # 新布局无矿物名列
                formula=formula,
                space_group=space_group,
                lattice_params=lattice,
                cif_url=cif_url,
            ))

        # ---- 兜底：旧布局绝对链接 / 相对 .cif 链接全文提取 ----
        if not entries:
            legacy_pattern = re.compile(
                r"href=[\"'](?:/cod/)?(\d{3,})\.(?:html|cif)[\"']", re.IGNORECASE
            )
            for cod_id_str in legacy_pattern.findall(html):
                try:
                    cod_id = int(cod_id_str)
                except ValueError:
                    continue
                entries.append(CODEntry(
                    cod_id=cod_id,
                    cif_url=f"{COD_CIF_URL}/{cod_id}.cif",
                ))

        return entries

    @staticmethod
    def _parse_total_count(html: str) -> Optional[int]:
        """解析结果页声明的总命中数；无法识别返回 None。"""
        match = re.search(r"there are (\d+) entries", html)
        if match:
            return int(match.group(1))
        if "no files matching" in html:
            return 0
        return None

    # ------------------------------------------------------------------
    # 缓存机制
    # ------------------------------------------------------------------

    @staticmethod
    def _make_cache_key(params: dict[str, str]) -> str:
        """生成缓存键（含缓存结构版本：参数体系/解析规则变更即使 TTL 未到也自动失效）"""
        sorted_items = sorted(params.items())
        raw = f"v{CACHE_SCHEMA_VERSION}&" + "&".join(f"{k}={v}" for k, v in sorted_items)
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