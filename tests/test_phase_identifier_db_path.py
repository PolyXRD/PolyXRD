"""v4.0.0 显式 ``db_path`` 回归测试 (列表式多库挂载).

覆盖 4 个不变量:
1. ``identify_with_cod_local(db_path=...)`` **不污染** ``PhaseIdentifier``
   实例状态: 显式库只对本次调用生效; 之后 ``db_path=None`` 仍查配置库
   (修复前显式库会粘在 ``self._cod_db`` 上, 切回内置「COD 全库」静默查错库)。
2. 显式库的只读连接用完即关 (不残留 sqlite 句柄, 不阻止用户替换库文件)。
3. 显式路径无效时**不静默回退**到全局库, 也不破坏实例既有 COD 状态。
4. ``CIFDatabase(cod_db_path=...)`` 只读: 不改配置、不写库文件、不产生
   ``-wal`` / ``-journal`` 侧车。
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.xrd_data import XRDData


def _make_data() -> XRDData:
    return XRDData(
        two_theta=np.linspace(20.0, 80.0, 800),
        intensity=np.zeros(800) + 0.01,
        wavelength=1.5406,
    )


def _make_peaks(tts: list[float] | None = None) -> PeakList:
    tts = tts or [28.44, 47.30, 56.11]
    return PeakList(peaks=[Peak(two_theta=t, intensity=1.0 - 0.2 * k)
                           for k, t in enumerate(tts)])


# ── COD 索引 fixture (真实 CODLocalIndexer 建库, 两次) ──────────


def _build_cod_index(tmp: Path, name: str, keys: list[str]) -> Path:
    from polyxrd.services.cif_database import _BUILTIN_MINERALS
    from polyxrd.services.cod_local import CODLocalIndexer

    cod_root = tmp / f"cod_{name}"
    for i, (key, info) in enumerate(_BUILTIN_MINERALS.items()):
        if key not in keys:
            continue
        cif = info.get("cif", "")
        if not cif:
            continue
        lines = cif.splitlines()
        extra: list[str] = []
        if not any("_chemical_formula_sum" in ln for ln in lines):
            extra.append(f"_chemical_formula_sum '{info.get('formula', key)}'")
        if not any("_chemical_name_mineral" in ln for ln in lines):
            extra.append(f"_chemical_name_mineral '{info.get('name', key)}'")
        for idx, ln in enumerate(lines):
            if ln.startswith("data_"):
                for j, ad in enumerate(extra):
                    lines.insert(idx + 1 + j, ad)
                break
        folder = cod_root / f"{i + 1:02d}" / "00"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{i + 1}.cif").write_text("\n".join(lines), encoding="utf-8")
    db_path = tmp / f"{name}_index.sqlite"
    stats = CODLocalIndexer(cod_root=cod_root, db_path=db_path).build_index()
    assert stats["indexed"] > 0
    return db_path


@pytest.fixture(scope="module")
def cod_index_pair(tmp_path_factory):
    """两份独立 COD 索引: A = 全部内置矿, B = 另一份 (内容不同)。"""
    from polyxrd.services.cif_database import _BUILTIN_MINERALS

    tmp = tmp_path_factory.mktemp("cod_pair")
    keys = list(_BUILTIN_MINERALS.keys())
    db_a = _build_cod_index(tmp, "A", keys)
    db_b = _build_cod_index(tmp, "B", keys[-1:])
    return db_a, db_b


# ── 1-3: identify_with_cod_local 显式路径 ────────────────────


def test_explicit_cod_local_does_not_poison_instance(cod_index_pair, monkeypatch):
    from polyxrd.services.cod_local import CODLocalDatabase
    from polyxrd.services.phase_identifier import PhaseIdentifier

    db_a, db_b = cod_index_pair
    pi = PhaseIdentifier()
    global_db = CODLocalDatabase(db_path=db_a)
    pi.enable_cod_local(cod_db=global_db)
    assert pi._cod_db is global_db

    captured: dict = {}

    def fake_search(**kwargs):
        captured["db"] = kwargs.get("db")
        return []

    monkeypatch.setattr(pi, "_search_cod_for_phases", fake_search)
    data, peaks = _make_data(), _make_peaks()

    # 显式 B: 本次必须查 B, 且不得写回 self._cod_db
    pi.identify_with_cod_local(
        data, peaks=peaks, top_n=3, merge_with_builtin=False, db_path=str(db_b),
    )
    assert captured["db"] is not None
    assert Path(captured["db"].db_path) == Path(db_b)
    assert pi._cod_db is global_db, "显式库污染了实例状态"
    # 2) 显式库的只读连接在 finally 里关闭
    assert captured["db"]._ro_conn is None, "显式库连接未关闭"

    # 切回历史行为 (db_path=None): 必须仍查配置库 A
    pi.identify_with_cod_local(
        data, peaks=peaks, top_n=3, merge_with_builtin=False,
    )
    assert captured["db"] is global_db


def test_explicit_cod_local_missing_path_does_not_fallback(cod_index_pair, monkeypatch):
    from polyxrd.services.cod_local import CODLocalDatabase
    from polyxrd.services.phase_identifier import PhaseIdentifier

    db_a, _ = cod_index_pair
    pi = PhaseIdentifier()
    global_db = CODLocalDatabase(db_path=db_a)
    pi.enable_cod_local(cod_db=global_db)

    calls: list = []
    monkeypatch.setattr(pi, "_search_cod_for_phases",
                        lambda **kw: calls.append(kw) or [])

    res = pi.identify_with_cod_local(
        _make_data(), peaks=_make_peaks(), top_n=3, merge_with_builtin=False,
        db_path=str(Path(db_a).with_name("does_not_exist.sqlite")),
    )
    assert res == []
    assert calls == [], "显式路径无效时静默回退到了全局库"
    assert pi._cod_db is global_db
    assert pi._cod_ready is True


# ── 4: CIFDatabase(cod_db_path=...) 只读覆盖 ─────────────────

_PHASES_DDL = """
CREATE TABLE phases (
    cod_id INTEGER PRIMARY KEY, ref_id TEXT, display_id TEXT, formula TEXT,
    space_group TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT,
    cell_a REAL, cell_b REAL, cell_c REAL,
    cell_alpha REAL, cell_beta REAL, cell_gamma REAL)
"""


def _make_phases_db(path: Path, cod_id: int, formula: str,
                    d_list: list[float], i_list: list[float]) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(_PHASES_DDL)
    conn.execute(
        "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cod_id, str(cod_id), str(cod_id), formula, "P 1", len(d_list),
         ",".join(f"{d:.6f}" for d in d_list),
         ",".join(f"{i:.4f}" for i in i_list),
         5.0, 5.0, 5.0, 90.0, 90.0, 90.0),
    )
    conn.commit()
    conn.close()
    return path


def _fingerprint(path: Path) -> tuple:
    st = path.stat()
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecars = sorted(p.name for p in Path(path).parent.iterdir()
                      if p.name.startswith(path.name + "-"))
    return (h, st.st_mtime_ns, st.st_size, tuple(sidecars))


def test_cif_database_explicit_override_is_readonly(tmp_path, monkeypatch):
    from polyxrd.config import get_config
    from polyxrd.services.cif_database import CIFDatabase
    from polyxrd.services.phase_identifier import PhaseIdentifier

    # 5 条峰, 与实测峰一一对应 → 必过 prefilter_min_match=3
    d_list = [3.135, 1.921, 1.632, 1.381, 1.240]
    i_list = [100.0, 60.0, 35.0, 20.0, 12.0]
    db_file = _make_phases_db(tmp_path / "explicit_inorg.sqlite",
                              1011240, "Fe2 O3", d_list, i_list)
    tts = [float(2.0 * np.degrees(np.arcsin(1.5406 / (2.0 * d)))) for d in d_list]

    cfg_path_before = get_config().get_cod_db_path()
    fp_before = _fingerprint(db_file)

    cdb = CIFDatabase(enable_cod_local=False, cod_db_path=db_file)
    assert cdb.cod_db_file() == db_file

    res = PhaseIdentifier().identify_with_cod_inorganics(
        _make_data(), peaks=_make_peaks(tts), top_n=3, db_path=db_file,
    )
    assert any("1011240" in m.phase.name for m in res), \
        [m.phase.name for m in res]

    assert _fingerprint(db_file) == fp_before, "只读检索写入了库文件/侧车"
    assert get_config().get_cod_db_path() == cfg_path_before, "显式库改写了配置"

    # 另一份显式库: 结果必须只来自它
    other = _make_phases_db(tmp_path / "other.sqlite", 2024001, "Si O2",
                            d_list, i_list)
    res2 = PhaseIdentifier().identify_with_cod_inorganics(
        _make_data(), peaks=_make_peaks(tts), top_n=3, db_path=other,
    )
    assert res2 and all("2024001" in m.phase.name for m in res2), \
        [m.phase.name for m in res2]


# ── 5: 其余两条链路的 db_path 转发 ───────────────────────────


def test_pdf2_and_xinmatch_forward_explicit_db_path(tmp_path, monkeypatch):
    import polyxrd.services.pdf2_database as pdf2_mod
    import polyxrd.services.xinmatch_db as xm_mod
    from polyxrd.services.phase_identifier import PhaseIdentifier

    pi = PhaseIdentifier()
    seen: dict = {}

    class _FakePdf2:
        def __init__(self, db_path=None):
            seen["pdf2"] = db_path

        def is_available(self):
            return False

    class _FakeXm:
        def __init__(self, db_path=None):
            seen["xm"] = db_path

        def is_ready(self):
            return False

    monkeypatch.setattr(pdf2_mod, "PDF2Database", _FakePdf2)
    monkeypatch.setattr(xm_mod, "XinMatchDatabase", _FakeXm)

    pi.identify_with_pdf2(_make_data(), peaks=_make_peaks(),
                          db_path=str(tmp_path / "pdf2.sqlite"))
    pi.identify_with_xinmatch(_make_data(), peaks=_make_peaks(),
                              db_path=str(tmp_path / "xm.sqlite"))
    assert seen["pdf2"] == str(tmp_path / "pdf2.sqlite")
    assert seen["xm"] == str(tmp_path / "xm.sqlite")

    # db_path=None 时仍按配置解析 (构造不传参)
    pi.identify_with_pdf2(_make_data(), peaks=_make_peaks())
    pi.identify_with_xinmatch(_make_data(), peaks=_make_peaks())
    assert seen["pdf2"] is None
    assert seen["xm"] is None
