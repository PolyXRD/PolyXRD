"""cod_atomic_sites 的 u_iso 列 (实施手册 v3 / M6-W21)
====================================================
1. 新库建表即带 u_iso 列; 2. 旧库 (无该列) 连接时被幂等 ALTER 补列;
3. CIF 解析路径能从 U_iso_or_equiv / B_iso_or_equiv 取到 u_iso, 缺省 0.005 + 标记;
4. 写入路径 (9 元组) 与新 schema 匹配。
"""
from __future__ import annotations

import sqlite3

import pytest

from polyxrd.services.cod_local import (
    _INSERT_SITES_SQL,
    connect,
    parse_atom_sites_from_cif,
)

_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS cod_atomic_sites (
    cod_id     INTEGER NOT NULL,
    site_idx   INTEGER NOT NULL,
    label      TEXT,
    element    TEXT NOT NULL,
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    z          REAL NOT NULL,
    occupancy  REAL DEFAULT 1.0,
    PRIMARY KEY (cod_id, site_idx)
);
"""

_CIF_U = """data_x
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_occupancy
Si1 Si 0.0 0.0 0.0 0.006(2) 1.0
"""

_CIF_B = """data_x
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_B_iso_or_equiv
Si1 Si 0.0 0.0 0.0 0.0789569
"""

_CIF_NONE = """data_x
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0.0 0.0 0.0
"""


def _cols(conn) -> set:
    return {r[1] for r in conn.execute("PRAGMA table_info(cod_atomic_sites)")}


class TestSchema:

    def test_new_db_has_u_iso(self, tmp_path):
        conn = connect(tmp_path / "new.sqlite")
        assert "u_iso" in _cols(conn)
        conn.close()

    def test_old_db_migrated_idempotently(self, tmp_path):
        db = tmp_path / "old.sqlite"
        raw = sqlite3.connect(str(db))
        raw.executescript(_OLD_SCHEMA)
        raw.commit()
        raw.close()
        # 第一次连接 → 补列
        conn = connect(db)
        assert "u_iso" in _cols(conn)
        conn.close()
        # 第二次连接 → 不报错 (幂等)
        conn = connect(db)
        assert "u_iso" in _cols(conn)
        conn.close()

    def test_insert_sql_matches_schema(self, tmp_path):
        conn = connect(tmp_path / "ins.sqlite")
        conn.execute(_INSERT_SITES_SQL,
                     (1, 0, "Si1", "Si", 0.0, 0.0, 0.0, 1.0, 0.006))
        row = conn.execute(
            "SELECT element, u_iso FROM cod_atomic_sites WHERE cod_id=1"
        ).fetchone()
        assert row["element"] == "Si"
        assert row["u_iso"] == pytest.approx(0.006)
        conn.close()


class TestParseAdp:

    def test_u_column(self):
        sites = parse_atom_sites_from_cif(_CIF_U)
        assert len(sites) == 1
        assert sites[0]["u_iso"] == pytest.approx(0.006)
        assert sites[0]["u_iso_default"] is False
        # 规范键齐备 (与 _extract_atomic_sites 一致)
        for k in ("label", "element", "x", "y", "z", "occupancy", "u_iso"):
            assert k in sites[0]

    def test_b_column_converted(self):
        sites = parse_atom_sites_from_cif(_CIF_B)
        assert sites[0]["u_iso"] == pytest.approx(0.001, rel=1e-3)
        assert sites[0]["u_iso_default"] is False

    def test_missing_adp_default(self):
        sites = parse_atom_sites_from_cif(_CIF_NONE)
        assert sites[0]["u_iso"] == pytest.approx(0.005)
        assert sites[0]["u_iso_default"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
