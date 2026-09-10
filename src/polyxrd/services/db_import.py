"""外挂数据库导入 (0.10.0)
========================
0.10.0 起发布包**不再内置任何数据库**：数据库单独下载、解压后经 GUI
导入, 路径持久化到 ``~/.polyxrd/user_db_paths.json``。

本模块只做三件事, 全部不依赖 Qt (可单测):
  · **探测** ``inspect_db_file``  —— 打开候选 .sqlite, 判断它属于哪一类库、
    相数多少、是否带预截断强峰列, 以及不合格时缺了什么
  · **落地** ``apply_import``     —— 把通过校验的路径写进配置
  · **呈现** ``slot_states``      —— 列出三个库槽位当前的挂载状态

为什么需要"探测"而不是直接接受任意 .sqlite: 三类库的表名都不同
(``phases`` / ``cod_entries``), 而 COD 无机物库与 PDF2 库**表名相同都是
``phases``** —— 拿 PDF2 库去当 COD 无机物库用不会立刻报错, 只会静默
检索不到东西。所以按"必需列 + 特征列 + 排除列"三者联合判别。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from polyxrd.config import get_config


@dataclass(frozen=True)
class DBKind:
    """一类可导入数据库的判别规格。"""

    key: str
    config_key: str          # user_db_paths.json 里的键
    label_key: str           # i18n 键 (views 层用)
    table: str
    required: tuple[str, ...]     # 必须全部存在的列 (缺一不可)
    signature: tuple[str, ...]    # 特征列 (至少一个)
    excludes: tuple[str, ...]     # 命中任一即**排除** (用于区分同表名)
    min_rows: int = 1
    count_column: str = "cod_id"


# 顺序即优先级: 先匹配到的为准
DB_KINDS: tuple[DBKind, ...] = (
    DBKind(
        key="cod_inorganics",
        config_key="cod_db_path",
        label_key="db_manager.kind.cod_inorganics",
        table="phases",
        required=("cod_id", "formula", "n_peaks", "peaks_d", "peaks_i"),
        signature=("cell_a",),
        # PDF2 的 phases 表多了 name/pearson, 用它把两者区分开
        excludes=("pearson",),
    ),
    DBKind(
        key="pdf2",
        config_key="pdf2_db_path",
        label_key="db_manager.kind.pdf2",
        table="phases",
        required=("cod_id", "formula", "n_peaks", "peaks_d", "peaks_i"),
        signature=("pearson", "name"),
        excludes=(),
    ),
    DBKind(
        key="cod_index",
        config_key="cod_index_db_path",
        label_key="db_manager.kind.cod_index",
        table="cod_entries",
        required=("cod_id", "formula", "elements", "cif_gz"),
        signature=("cif_gz",),
        excludes=(),
        min_rows=1000,
    ),
)

KIND_BY_KEY: dict[str, DBKind] = {k.key: k for k in DB_KINDS}


@dataclass
class DBInspect:
    """一次探测的结果。"""

    path: Path
    ok: bool = False
    kind: Optional[str] = None
    table: str = ""
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    has_top_peaks: bool = False
    size_mb: float = 0.0
    error: str = ""
    # 被判为"表名对上了但列不对/归属别类"时的提示
    hint: str = ""

    @property
    def kind_spec(self) -> Optional[DBKind]:
        return KIND_BY_KEY.get(self.kind) if self.kind else None


def _size_mb(path: Path) -> float:
    try:
        return round(path.stat().st_size / 1e6, 1)
    except OSError:
        return 0.0


def inspect_db_file(path: str | Path) -> DBInspect:
    """探测一个候选数据库文件, 返回它属于哪一类库 (或为什么不合格)。

    只读打开 (``mode=ro``), 绝不修改被测文件。
    """
    p = Path(path)
    res = DBInspect(path=p, size_mb=_size_mb(p))

    if not p.exists():
        res.error = "file_not_found"
        return res
    if not p.is_file():
        res.error = "not_a_file"
        return res
    # SQLite 文件头 = 前 16 字节 "SQLite format 3\0"
    try:
        with open(p, "rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                res.error = "not_sqlite"
                return res
    except OSError as e:
        res.error = f"unreadable: {e}"
        return res

    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.Error as e:
        res.error = f"open_failed: {e}"
        return res
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        matched_table = False
        for kind in DB_KINDS:
            if kind.table not in tables:
                continue
            matched_table = True
            cols = [r[1] for r in conn.execute(
                f"PRAGMA table_info({kind.table})")]
            colset = set(cols)
            if not set(kind.signature) & colset:
                continue
            if set(kind.excludes) & colset:
                continue
            missing = [c for c in kind.required if c not in colset]
            if missing:
                if not res.hint:
                    res.hint = "missing_columns:" + ",".join(missing)
                continue
            rows = int(conn.execute(
                f"SELECT COUNT(*) FROM {kind.table}").fetchone()[0])
            if rows < kind.min_rows:
                if not res.hint:
                    res.hint = f"too_few_rows:{rows}"
                continue
            res.ok = True
            res.kind = kind.key
            res.table = kind.table
            res.rows = rows
            res.columns = cols
            res.has_top_peaks = {"peaks_top_d", "peaks_top_i"} <= colset
            res.hint = ""
            return res
        if not res.hint:
            res.error = ("no_matching_table" if not matched_table
                         else "no_matching_schema")
        else:
            res.error = "schema_mismatch"
        return res
    except sqlite3.Error as e:
        res.error = f"query_failed: {e}"
        return res
    finally:
        conn.close()


def apply_import(ins: DBInspect) -> None:
    """把探测通过的结果写进配置 (持久化, 下次启动自动加载)。"""
    if not ins.ok or not ins.kind_spec:
        raise ValueError("只能导入校验通过的数据库")
    cfg = get_config()
    setter = _SETTERS[ins.kind_spec.config_key]
    setter(str(ins.path))


def clear_import(kind_key: str) -> None:
    """清除某类库的用户导入路径, 回退到默认/内置位置。"""
    spec = KIND_BY_KEY.get(kind_key)
    if spec is None:
        raise KeyError(kind_key)
    _SETTERS[spec.config_key](None)


def _setters() -> dict:
    cfg = get_config()
    return {
        "cod_db_path": cfg.set_cod_db_path,
        "pdf2_db_path": cfg.set_pdf2_db_path,
        "cod_index_db_path": cfg.set_cod_index_db_path,
    }


# 延迟到调用时取 (get_config 是单例, 但避免 import 期就构造)
class _SetterProxy:
    def __getitem__(self, key: str):
        return _setters()[key]


_SETTERS = _SetterProxy()


def _default_paths() -> dict[str, Path]:
    cfg = get_config()
    # cod_index 用 cod_local 的**只读**解析器: 不能走 _index_db_path(),
    # 那会在开发模式下触发一次 ~400 MB 的 bundled 部署复制。
    try:
        from polyxrd.services.cod_local import existing_index_db_path
        index_path = (existing_index_db_path()
                      or cfg.get_cif_db_path() / "cod_index.sqlite")
    except Exception:  # noqa: BLE001 - 状态显示不该因服务异常而崩
        index_path = cfg.get_cif_db_path() / "cod_index.sqlite"
    return {
        "cod_inorganics": cfg.get_cod_db_path(),
        "pdf2": cfg.get_pdf2_db_path(),
        "cod_index": index_path,
    }


def is_user_imported(kind_key: str) -> bool:
    """该槽位当前用的是用户导入的路径, 还是默认/内置路径。"""
    spec = KIND_BY_KEY[kind_key]
    return get_config().user_db_path(spec.config_key) is not None


def slot_states(validate: bool = True) -> list[dict]:
    """三个库槽位的当前状态, 供 GUI 列表显示。

    Args:
        validate: 是否对每个槽位做一次探测 (会打开库读相数)。大库上
            这仍很快 (COUNT(*) + PRAGMA), 但设为 False 可完全跳过。
    """
    out: list[dict] = []
    defaults = _default_paths()
    for kind in DB_KINDS:
        path = defaults[kind.key]
        state = {
            "kind": kind.key,
            "label_key": kind.label_key,
            "path": str(path),
            "exists": path.exists(),
            "imported": is_user_imported(kind.key),
            "rows": 0,
            "has_top_peaks": False,
            "ok": False,
            "error": "",
            "hint": "",
            "size_mb": _size_mb(path),
        }
        if validate and path.exists():
            ins = inspect_db_file(path)
            state.update({
                "ok": ins.ok,
                "rows": ins.rows,
                "has_top_peaks": ins.has_top_peaks,
                "error": ins.error,
                "hint": ins.hint,
            })
        out.append(state)
    return out


@lru_cache(maxsize=32)
def _count_rows_cached(path: str, mtime: float, table: str) -> int:
    """``COUNT(*)`` 带 (路径, mtime, 表名) 缓存 —— 文件被替换后自动失效。

    缓存键里放 mtime 而不是只放路径: 用户"重新下载→覆盖同名文件"是常见
    操作, 只按路径缓存会一直显示旧相数。
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def live_counts() -> dict[str, int]:
    """三类库当前的记录数 (不可用/未挂载 → 0), 供 UI 显示 ``(71,199)`` 这类文案。

    带 mtime 缓存: 大库上 ``COUNT(*)`` 仍有毫秒级开销, 而下拉文案会被反复
    重建 (切语言、切视图都会触发), 不该每次都去查库。
    """
    out: dict[str, int] = {}
    defaults = _default_paths()
    for kind in DB_KINDS:
        p = defaults[kind.key]
        try:
            mt = p.stat().st_mtime
        except OSError:
            out[kind.key] = 0
            continue
        out[kind.key] = _count_rows_cached(str(p), mt, kind.table)
    return out


def reload_caches() -> None:
    """导入/清除后清掉各类库的已缓存连接, 让新路径立即生效。

    `cod_local` 每次查询都新开连接, 无需处理; 需要清的是持有长连接的服务
    实例 (主窗口的 `_cif_db`, 以及任何已构造的 PDF2Database)。
    """
    try:
        from polyxrd.services.pdf2_database import PDF2Database
        PDF2Database().reload()
    except Exception:
        pass


def make_validator() -> Callable[[str], tuple[bool, str]]:
    """给 GUI 用的校验回调: ``path -> (ok, 人类可读说明)``。"""

    def _v(path: str) -> tuple[bool, str]:
        ins = inspect_db_file(path)
        if not ins.ok:
            return False, ins.error + (
                f" ({ins.hint})" if ins.hint else ""
            )
        extra = " 含预截断强峰列 (检索更快)" if ins.has_top_peaks else ""
        return True, f"{ins.kind} / {ins.rows:,} 行 / {ins.size_mb} MB{extra}"

    return _v
