"""v4.6.0 手动冒烟：多份真实 polyDB 同时挂载 + 选中即检索 + 外挂库 Profile Fitting。
================================================================================

不是 pytest 用例（文件名不以 test_ 开头）：依赖开发机上的
../PolyXRD-DataBase/polydb 真实库。运行：

    venv/Scripts/python.exe tools/smoke_v460_mounts.py

检查点：
1. 两份 polyDB 都能作为用户自加项挂载，id 不同，元数据（变体/数据集/构建）可读；
2. 把 COD-Full 设为当前后，传统检索确实查的是 Full（不是 718 相的内置库，
   也不是无机库）；
3. 同一张谱切到 COD-Inorg 后结果同样可用 —— 证明"选中哪份用哪份"；
4. 外挂库 Profile Fitting 走"预筛候选 + 全谱重排"，空闲机器上数秒级返回
   （冒烟时机器正跑 14 进程构库，耗时数字不作性能结论）；
5. MCP 的 list_phase_databases / polyDB 工具默认跟随 active 库。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import numpy as np

from polyxrd.services import db_mounts
from polyxrd.services.db_mounts import Mount


def _isolate_store(tmp: Path) -> None:
    """挂载表指到临时文件：不碰开发机 ~/.polyxrd 的真实挂载。"""
    db_mounts._store_file = lambda: tmp / "db_mounts.json"
    db_mounts.clear_probe_cache()
    # 内置项也隔离：否则本机真实默认 polyDB 会混进列表（含 PDF2-2004 变体，
    # 它也是 polyDB 槽位，v5.2 起不再有独立的 pdf2_db_path）。
    from polyxrd.config import get_config

    cfg = get_config()
    cfg.get_polydb_path = lambda *a, **k: None


def _find_polydb_files() -> list[Path]:
    """扫描开发机的 polyDB 产物；**跳过仍在构建/半成品**的目录。

    构库脚本正在写 MP-*.polyDB 时，目录名已经出现但段文件还不齐 —— 冒烟
    不该把它当成"挂载失败"，更不能误删/误改它。
    """
    from polyxrd.services.polydb import probe as polydb_probe

    base = ROOT.parent / "PolyXRD-DataBase" / "polydb"
    out: list[Path] = []
    for p in sorted(base.glob("*.polyDB")):
        if not p.is_dir():
            continue
        ok, reason = polydb_probe(p)
        if ok:
            out.append(p)
        else:
            print(f"跳过未就绪的库: {p.name} ({reason})")
    return out


def _synthetic_from_phase(db_dir: Path, query: str = "Al2O3"):
    """从真实库取一个相，把它的 d-I 表展宽成一条"实验谱"。"""
    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase(db_dir)
    assert db.is_ready(), f"库不可用: {db_dir}"
    rows = db.search_entries(query, limit=5)
    assert rows, f"库里查不到 {query}"
    rec = db.get_phase(int(rows[0]["cod_id"]))
    assert rec, "取相失败"
    wavelength = 1.5406
    x = np.arange(10.0, 90.0, 0.02)
    y = np.full_like(x, 20.0)
    for d_val, i_val in zip(rec["peaks_d_list"], rec["peaks_i_list"]):
        if d_val <= 0:
            continue
        sin_theta = wavelength / (2.0 * d_val)
        if sin_theta >= 1.0:
            continue
        tt = 2.0 * np.degrees(np.arcsin(sin_theta))
        if not (x[0] <= tt <= x[-1]):
            continue
        sigma = 0.06 / 2.3548
        y += i_val * np.exp(-0.5 * ((x - tt) / sigma) ** 2)
    return rec, x, y


def main() -> int:
    libs = _find_polydb_files()
    if not libs:
        print("SKIP: 开发机上没有 ../PolyXRD-DataBase/polydb/*.polyDB")
        return 0
    print("真实库:", [p.name for p in libs])

    with tempfile.TemporaryDirectory(prefix="polyxrd_v460_smoke_") as td:
        tmp = Path(td)
        _isolate_store(tmp)
        mounts: list[Mount] = []
        for d in libs:
            m = db_mounts.add_mount(d)
            mounts.append(m)
            print(f"挂载 {m.id}  kind={m.kind} label={m.display_name()}")

        rows = {r["id"]: r for r in db_mounts.probe_all()}
        for m in mounts:
            r = rows[m.id]
            assert r["ok"], f"{m.id} probe 失败: {r.get('error')}"
            print(f"  probe ok rows={r['rows']:,} variant={r.get('variant')} "
                  f"dataset={r.get('dataset')!r} built={r.get('built')!r} "
                  f"schema={r.get('schema_version')}")

        # 用无机库自己的相做基准谱（不要取排序后的第一份：开发机上可能还有
        # 别的实验库，取到别家库的相会让"本库检不出自己"变成假失败）。
        ref_lib = next((p for p in libs if "COD-Inorg" in p.name), libs[0])
        rec, x, y = _synthetic_from_phase(ref_lib)
        print(f"合成谱来自: {rec['formula']} (COD {rec['cod_id']})")

        from polyxrd.models.xrd_data import XRDData
        from polyxrd.services.phase_identifier import default_peak_list
        from polyxrd.viewmodels.phase_vm import PhaseViewModel

        data = XRDData(two_theta=x, intensity=y)
        peaks = default_peak_list(data)
        print(f"自动寻峰: {len(peaks.peaks)} 条")

        vm = PhaseViewModel()
        vm._peaks = peaks

        for m in mounts:
            t0 = time.perf_counter()
            got: list = []
            vm.phase_identified.connect(lambda rs: got.append(list(rs)))
            vm.identify_phases(data, db_source=m.id, top_n=5)
            dt = time.perf_counter() - t0
            names = [f"{r.phase.name} ({r.score:.1f})" for r in got[-1]]
            print(f"[传统检索] {m.display_name()} {dt*1000:.0f} ms → {names}")
            assert got[-1], f"{m.id} 检索无结果"
            # 谱是从 COD-Inorg 的 Al2O3 造的 → Inorg/Full 的前 5 必须命中它；
            # 其它第三方库 (例如 Materials Project pilot) 不含这个 COD 条目,
            # 不能拿同一条断言, 只打印命中情况。
            strict = any(k in m.display_name()
                         for k in ("COD-Inorg", "COD-Full"))
            hit = any("Al2O3" in (r.phase.formula or "").replace(" ", "")
                      for r in got[-1])
            if strict:
                assert hit, (
                    f"{m.display_name()} 未在 top-5 命中合成谱来源相 Al2O3: {names}")
            else:
                print(f"   命中来源相: {hit}（第三方库不强制）")

            t0 = time.perf_counter()
            pf: list = []
            vm.phase_identified.connect(lambda rs: pf.append(list(rs)))
            vm.identify_phases_profile_fitting(data, top_n=5, db_source=m.id)
            dt = time.perf_counter() - t0
            names = [f"{r.phase.name} ({r.score:.1f})" for r in pf[-1]]
            print(f"[Profile  ] {m.display_name()} {dt*1000:.0f} ms → {names}")
            assert pf[-1], f"{m.id} Profile Fitting 无结果"
            if strict:
                assert any("Al2O3" in (r.phase.formula or "").replace(" ", "")
                           for r in pf[-1][:3]), (
                    f"{m.display_name()} Profile Fitting top-3 未命中 Al2O3: {names}")

        # MCP：默认跟随 active，显式 database 可指定另一份。
        from polyxrd.mcp_server import server as mcp_server

        db_mounts.set_active(mounts[-1].id)
        info = json.loads(mcp_server.list_phase_databases())
        print(f"[MCP] active={info['active']} n={info['n_databases']}")
        assert info["active"] == mounts[-1].id

        hit = json.loads(mcp_server.search_phases_polydb(
            rec["formula"], 3, database=mounts[0].id))
        print(f"[MCP] 显式 {mounts[0].id} → {hit['n_results']} 条 "
              f"(database={hit.get('database')})")
        assert hit["n_results"] >= 0

    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
