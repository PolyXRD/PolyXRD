"""只读打开 SQLite 库的统一实现（PDF2 / 用户库 / 导入校验共用）。

这里踩过两个坑，都很隐蔽，且现象一模一样 ——"库明明在那儿，却说打不开"：

1. **URI 没转义**。早先写的是 ``f"file:{path}?mode=ro"``，把裸 Windows 路径
   直接塞进 URI。路径里只要出现 ``#`` / ``?`` / ``%`` 就会被 SQLite 当成分隔符
   (``#`` 起算 fragment、``?`` 起算参数)，后半截被截掉 —— 报
   ``unable to open database file``，而用户看到的现象是"文件明明存在"。
   用 :meth:`pathlib.Path.as_uri` 生成 ``file:///C:/Program%20Files/...``
   才会正确转义空格与特殊字符。

2. **WAL 库的只读打开需要建 ``-shm``**。建库时执行过
   ``PRAGMA journal_mode=WAL``，这个设置是**写进库头**的（不是连接期临时状态）。
   此后任何一次以 ``mode=ro`` 打开，SQLite 都要在同目录建立/映射 ``-shm``。
   如果库被放在只读目录（装到 ``C:\\Program Files``）、只读介质、或用户只拷了
   那一个 ``.sqlite`` 而没带 ``-shm``，就会打不开。此时退到 SQLite 官方 URI
   参数 ``immutable=1``（声明"这个文件不会被别人改"），可以不建 ``-shm``
   直接读 —— 对已经 checkpoint 过的库（``-wal`` 为 0 字节）完全安全。

`immutable=1` 只在普通只读打开失败后才尝试：它放弃了 WAL 里的未提交内容，
能少用就不多用。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Tuple

#: 依次尝试的 URI 参数。顺序有意义：先常规只读，失败才声明 immutable。
_RO_QUERY_SUFFIXES: Tuple[str, ...] = ("?mode=ro", "?mode=ro&immutable=1")


def readonly_uri(db_path: Path | str) -> str:
    """把本地路径转成可安全拼接查询参数的 ``file:`` URI。"""
    return Path(db_path).expanduser().resolve().as_uri()


def connect_readonly(
    db_path: Path | str, *, with_row_factory: bool = False,
) -> Tuple[Optional[sqlite3.Connection], Optional[str]]:
    """只读打开库，返回 ``(连接, 错误描述)``；失败时连接为 None。

    成功时连接**已经过一次真实查询**（``sqlite3.connect`` 本身是惰性的，
    不探一次的话，路径有问题也要等到第一次 SELECT 才暴露）。
    """
    path = Path(db_path)
    if not path.exists():
        return None, f"库文件不存在: {path}"
    uri = readonly_uri(path)
    last_error: Optional[str] = None
    for suffix in _RO_QUERY_SUFFIXES:
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(
                uri + suffix, uri=True, check_same_thread=False,
            )
            conn.execute("PRAGMA user_version").fetchone()
        except sqlite3.Error as exc:
            last_error = f"{exc} (uri={uri}{suffix})"
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            continue
        if with_row_factory:
            conn.row_factory = sqlite3.Row
        return conn, None
    return None, last_error or "无法打开数据库"
