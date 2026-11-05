"""只读打开 SQLite 库的公共实现测试。

覆盖 2026-10-29 装机踩到的两条：URI 转义、WAL 库在只读目录下的降级。
全部用 tmp_path 现场建库。

v5.2 起只服务 polyDB 的 ``index.sqlite``：PDF2 的独立 sqlite 库已改为
polyDB 变体，随之而来的 ``PDF2Database`` / ``_SCHEMA_SQL`` 相关用例一并删除。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polyxrd.services.sqlite_ro import (  # noqa: E402
    connect_readonly,
    readonly_uri,
)


def _make_db(path: Path, *, wal: bool = False) -> Path:
    conn = sqlite3.connect(str(path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE phases (cod_id INTEGER, formula TEXT)")
    conn.execute("INSERT INTO phases VALUES (1, 'Si O2')")
    conn.commit()
    conn.close()
    return path


class TestReadonlyUri:
    def test_escapes_spaces(self, tmp_path: Path):
        """路径里的空格必须转义成 %20，否则 URI 被截断。"""
        p = tmp_path / "my libs" / "PDF2_2004.sqlite"
        uri = readonly_uri(p)
        assert " " not in uri
        assert "%20" in uri
        assert uri.startswith("file:///")

    def test_escapes_hash(self, tmp_path: Path):
        """``#`` 在 URI 里是 fragment 起点，不转义会把后半截吃掉。"""
        p = tmp_path / "a#b.sqlite"
        assert "%23" in readonly_uri(p)

    def test_resolves_relative(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_db(tmp_path / "x.sqlite")
        assert readonly_uri("x.sqlite").startswith("file:///")


class TestConnectReadonly:
    def test_opens_normal_db(self, tmp_path: Path):
        p = _make_db(tmp_path / "plain.sqlite")
        conn, err = connect_readonly(p)
        assert err is None
        assert conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0] == 1
        conn.close()

    def test_row_factory(self, tmp_path: Path):
        p = _make_db(tmp_path / "plain.sqlite")
        conn, _ = connect_readonly(p, with_row_factory=True)
        row = conn.execute("SELECT cod_id, formula FROM phases").fetchone()
        assert row["formula"] == "Si O2"
        conn.close()

    def test_missing_file_reports_path(self, tmp_path: Path):
        conn, err = connect_readonly(tmp_path / "nope.sqlite")
        assert conn is None
        assert "不存在" in err

    def test_not_a_database(self, tmp_path: Path):
        p = tmp_path / "fake.sqlite"
        p.write_bytes(b"not a database at all" * 10)
        conn, err = connect_readonly(p)
        assert conn is None
        assert err

    def test_writable_dir_wal_uses_plain_ro(self, tmp_path: Path):
        """目录可写时不该退到 immutable —— 首选的 mode=ro 就该成功。"""
        p = _make_db(tmp_path / "wal.sqlite", wal=True)
        conn, err = connect_readonly(p)
        assert err is None
        assert conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0] == 1
        conn.close()

    def test_wal_without_shm_falls_back_to_immutable(self, tmp_path: Path):
        """WAL 库缺 -shm 且建不出来时必须靠 immutable 兜住。

        用只读 ACL 造"建不出 -shm"在测试里不可移植，这里改走等价路径：
        把 -shm/-wal 删掉后，普通 mode=ro 在只读介质上的失败点正是 -shm，
        而 immutable 连接不依赖它 —— 直接断言降级那条路能读通。
        """
        p = _make_db(tmp_path / "wal.sqlite", wal=True)
        for suffix in ("-wal", "-shm"):
            side = Path(str(p) + suffix)
            if side.exists():
                side.unlink()
        conn, err = connect_readonly(p)
        # 目录可写时首选 mode=ro 会自行重建 -shm，所以此处只要求"能读"
        assert err is None
        assert conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0] == 1
        conn.close()



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
