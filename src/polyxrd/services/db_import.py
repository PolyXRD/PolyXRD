"""外挂库探测 (0.10.0; v4.1.0 起只剩 PDF2 一种 sqlite 库)
=========================================================

PolyXRD 的原生参考库是 **polyDB 目录容器** (见 :mod:`polyxrd.services.polydb`),
不走本模块。v4.1.0 把旧的 COD sqlite 槽位 (``cod_inorganics`` / ``cod_index``)
连同 XinMatch 兼容槽位一起删除, 所以这里只剩一类可探测的 sqlite 文件:

  · ``pdf2`` —— ICDD PDF-2 2004 的 PolyXRD dump (``phases`` 表 + ``pearson`` 列)。

保留本模块而不是把 PDF2 判别塞进 polyDB 读取器, 是因为判据完全不同:
polyDB 靠"目录里有 meta.json + index.sqlite", sqlite 必须靠"表名 + 列名"。

为什么需要"探测"而不是直接接受任意 .sqlite: PDF2 库的表名是 ``phases``,
旧版 COD 无机库的表名**也是** ``phases`` —— 拿错库不会立刻报错, 只会静默
检索不到东西。所以按"必需列 + 特征列 + 排除列"三者联合判别, 判不出就拒绝。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from polyxrd.config import get_config


@dataclass(frozen=True)
class DBKind:
    """一类可探测 sqlite 库的判别规格。"""

    key: str
    config_key: str          # user_db_paths.json 里的键
    label_key: str           # i18n 键 (views 层用)
    table: str
    required: tuple[str, ...]     # 必须全部存在的列 (缺一不可)
    signature: tuple[str, ...]    # 特征列 (至少一个)
    excludes: tuple[str, ...]     # 命中任一即**排除** (用于区分同表名)
    min_rows: int = 1
    count_column: str = "cod_id"
    #: 可选: 该库需要额外展示的"授权/合规提示" i18n 键。
    #: PDF2-2004 是 ICDD 的商业数据库, 我们只做格式转换与离线索引, 不附带任何
    #: 授权 —— 因此必须把"请自行确认正版授权"写在界面上, 而不是藏在许可协议里。
    notice_key: str = ""


#: 顺序即优先级 (v4.1.0 只剩一项)。
DB_KINDS: tuple[DBKind, ...] = (
    DBKind(
        key="pdf2",
        config_key="pdf2_db_path",
        label_key="db_manager.kind.pdf2",
        table="phases",
        required=("cod_id", "formula", "n_peaks", "peaks_d", "peaks_i"),
        signature=("pearson", "name"),
        excludes=(),
        notice_key="db_manager.notice.pdf2",
    ),
)

KIND_BY_KEY: dict[str, DBKind] = {k.key: k for k in DB_KINDS}

#: 各库在发布包里的文件名 (决定用户该下载哪个 zip, 也用于文档/脚本对账)。
PKG_FILENAME: dict[str, str] = {
    "pdf2": "PDF2_2004.sqlite",
}


def release_package_name(kind_key: str, version: str) -> str:
    """某槽位对应的独立下载包文件名。

    PDF2-2004 属 ICDD 版权库, **永远没有发布包**, 恒返回空串, 由界面显示
    "本库不随发布包分发"。保留这个函数是为了 GUI 展示逻辑不必特判。
    """
    KIND_BY_KEY[kind_key]  # KeyError 即调用方传错了 key
    return ""


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


def clear_import(kind_key: str) -> None:
    """清除某类库的用户导入路径, 回退到内置位置。"""
    spec = KIND_BY_KEY.get(kind_key)
    if spec is None:
        raise KeyError(kind_key)
    _setter(spec.config_key)(None)


#: config_key → AppConfig 上的"写入用户导入路径"方法名。
_PATH_SETTERS = {
    "pdf2_db_path": "set_pdf2_db_path",
}


def _setter(config_key: str):
    """按 config_key 取写入路径的 bound method。

    必须是**每次现取**而不是 import 期缓存: `get_config()` 虽是单例, 但测试会
    直接 monkeypatch 返回的配置实例, 缓存住的旧 bound method 会写到被替换掉的
    对象上去, 表现成"导入成功但配置没变"。
    """
    cfg = get_config()
    return getattr(cfg, _PATH_SETTERS[config_key])


def reload_caches() -> None:
    """挂载/清除后清掉已缓存的连接, 让新路径立即生效。

    v4.2.0 起物相检索（polyDB / PDF2 / 用户库）每次查询都现开连接, 无需处理;
    需要清的是持有长连接的服务实例 (任何已构造的 PDF2Database)。polyDB 读取器
    由 ``db_mounts.probe`` 每次现建, 同样无需在这里处理。
    """
    try:
        from polyxrd.services.pdf2_database import PDF2Database
        PDF2Database().reload()
    except Exception:
        pass
