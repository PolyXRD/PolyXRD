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
   在**子进程**里跑，避免同进程内其他测试直接 import 旧模块造成的假阴性。
"""

from __future__ import annotations

import subprocess
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
    # 其它（config 的 cod_* 路径常量，随 P3.1 一起清）
    "config.py",
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


def test_import_services_does_not_load_legacy_modules() -> None:
    """``import polyxrd.services`` 不得把旧 COD sqlite 模块拉进内存（硬断言）.

    P2.1–P2.10 迁完后，``services/__init__.py`` 已改为导出
    ``CifMineralLibrary``；旧模块虽仍在仓库里（P3.1 删除），但**不再被
    包入口导入**。子进程跑以排除同进程其他测试的 ``sys.modules`` 污染。
    """
    code = (
        "import sys, polyxrd.services\n"
        "bad = [m for m in ('polyxrd.services.cod_local', "
        "'polyxrd.services.cif_database') if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_SRC.parents[1]),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.returncode == 0, f"子进程导入失败:\n{out.stderr}"
    pulled = out.stdout.strip()
    assert pulled == "", f"import polyxrd.services 仍拉入旧模块: {pulled}"
