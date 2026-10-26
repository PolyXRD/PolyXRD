"""v4.2 结构清理静态守卫（P0.2 骨架；P3.1 收紧为硬断言）。

作用
----
1. 扫描 ``src/polyxrd/**/*.py``：**非白名单**文件不得出现旧 COD sqlite 运行时符号
   （``CODLocalDatabase`` / ``CIFDatabase`` / ``CODLocalIndexer`` /
   ``identify_with_cod_inorganics`` / ``identify_with_cod_local`` /
   ``cod_index.sqlite`` / ``COD_inorganics.sqlite``）。
2. 白名单 ``_ALLOWLIST`` 初始 = 当前仍合法持有这些符号的文件（旧模块本身 + P2 未迁完的
   消费者）。每完成一个 P2 任务就从中删除一条；P3.1 删除旧模块后应为空集。
3. import smoke：``import polyxrd.services`` 后 ``sys.modules`` 不含
   ``polyxrd.services.cod_local`` / ``polyxrd.services.cif_database``。
   P3.1 前旧模块仍被导入 → 暂时 xfail；删除旧模块后去掉 xfail 即为硬断言。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src" / "polyxrd"

# P0.2 初始白名单（相对 src/polyxrd 的 posix 路径）。
# 顺序按 P2 迁移计划排列；迁移完成一项就从这里删一行。
_ALLOWLIST = {
    # 旧模块本身（P3.1 删除）
    "services/cif_database.py",
    "services/cod_local.py",
    # P2 待迁消费者
    "services/__init__.py",
    "services/phase_identifier.py",          # P2.1
    "services/pdf2_database.py",             # P2.2
    "services/polydb.py",                    # P2.3
    "services/user_db.py",                   # P2.4
    "services/phase_structure_resolver.py",  # P2.5
    "services/phase_cif_export.py",          # P2.6
    "services/rietveld_refiner.py",          # P2.7
    "views/main_window.py",                  # P2.8
    "views/refinement_wizard.py",            # P2.9
    "mcp_server/server.py",                  # P2.10
    # 其它（config 的 cod_* 路径 / phase_vm 的旧数据源分支，随 P3 一起清）
    "config.py",
    "viewmodels/phase_vm.py",
}

_FORBIDDEN = (
    "CODLocalDatabase",
    "CIFDatabase",
    "CODLocalIndexer",
    "identify_with_cod_inorganics",
    "identify_with_cod_local",
    "cod_index.sqlite",
    "COD_inorganics.sqlite",
)


def _iter_py():
    for path in sorted(_SRC.rglob("*.py")):
        yield path, path.relative_to(_SRC).as_posix()


@pytest.mark.parametrize("path,rel", list(_iter_py()))
def test_no_forbidden_symbols_outside_allowlist(path: Path, rel: str) -> None:
    if rel in _ALLOWLIST:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = [sym for sym in _FORBIDDEN if sym in text]
    assert not hits, f"{rel} 仍含旧符号 {hits}；应迁移到新模块或删除（v4.2 结构清理）"


def test_allowlist_files_still_exist() -> None:
    """白名单里的文件必须仍存在（防止删文件后忘记清白名单）。"""
    missing = [rel for rel in _ALLOWLIST if not (_SRC / rel).exists()]
    assert not missing, f"白名单含已删除文件，请清理 _ALLOWLIST: {missing}"


@pytest.mark.xfail(
    reason="P3.1 删除旧模块后收紧为硬断言（当前 cod_local/cif_database 仍在）",
    strict=False,
)
def test_import_services_does_not_load_legacy_modules() -> None:
    import polyxrd.services  # noqa: F401

    assert "polyxrd.services.cod_local" not in sys.modules
    assert "polyxrd.services.cif_database" not in sys.modules
