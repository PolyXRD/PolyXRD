"""外挂数据库导入 (0.10.0) 单测
=============================

覆盖 ``services/db_import.py`` 的探测/落地/呈现三层, 以及两个容易踩的坑:

1. **同表名歧义** —— COD 无机物库与 PDF2 库的 `phases` 表列高度重合, 拿混
   了不会报错只会静默检索不到东西。所以按"必需列 + 特征列 + 排除列"联合
   判别, 这里逐条钉死 (尤其 PDF2 → cod_inorganics 的反向误判)。
2. **UI 刷新不得有副作用** —— `_default_paths()` 只读解析 cod_index 位置,
   绝不能走 `cod_local._index_db_path()` (开发模式下会复制 ~400 MB)。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.config import AppConfig, get_config          # noqa: E402
from polyxrd.services import db_import                    # noqa: E402

COD_DB = ROOT / "cod_data" / "COD_inorganics.sqlite"
PDF2_DB = ROOT / "cod_data" / "PDF2_2004.sqlite"
# v2.1 P1-4: 旧值指向 v0.13.2 之前的仓库根布局 (cod_index.sqlite), 导致本机
# 存有 cod_data/cod_index.sqlite 时该用例长期"假跳过"。现指向三库统一目录。
INDEX_DB = ROOT / "cod_data" / "cod_index.sqlite"


# ── 合成库工具 ────────────────────────────────────────────────

def _make_db(path: Path, ddl: str, rows: list[tuple] = (), insert: str = "") -> Path:
    conn = sqlite3.connect(path)
    conn.execute(ddl)
    if insert and rows:
        conn.executemany(insert, rows)
    conn.commit()
    conn.close()
    return path


COD_COLS = """
    cod_id TEXT PRIMARY KEY, formula TEXT, space_group TEXT, n_peaks INTEGER,
    peaks_d TEXT, peaks_i TEXT, cell_a REAL, cell_b REAL, cell_c REAL,
    cell_alpha REAL, cell_beta REAL, cell_gamma REAL
"""
COD_ROW = ("9001", "SiO2", "P3_121", 2, "3.34,4.26", "100,45",
           4.913, 4.913, 5.405, 90.0, 90.0, 120.0)
COD_INSERT = "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"

PDF2_COLS = """
    cod_id TEXT PRIMARY KEY, formula TEXT, name TEXT, mineral TEXT,
    pearson TEXT, n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT, cell_a REAL
"""
PDF2_ROW = ("00-046-1045", "SiO2", "Quartz, syn", "Quartz", "hP9", 2,
            "3.34,4.26", "100,22", 4.913)
PDF2_INSERT = "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?)"


def _make_cod_db(path: Path) -> Path:
    """最小合法 COD 无机物库 (1 相)。"""
    return _make_db(path, f"CREATE TABLE phases ({COD_COLS})", [COD_ROW], COD_INSERT)


def _make_pdf2_db(path: Path) -> Path:
    """最小合法 PDF2 库 (1 相, 带 pearson/name 特征列)。"""
    return _make_db(path, f"CREATE TABLE phases ({PDF2_COLS})", [PDF2_ROW], PDF2_INSERT)


@pytest.fixture
def tmp_cfg(tmp_path, monkeypatch):
    """把 user_db_paths.json 重定向到临时目录, 不碰用户真实配置。"""
    target = tmp_path / "user_db_paths.json"
    monkeypatch.setattr(AppConfig, "_user_db_paths_file", lambda self: target)
    return target


# ── 探测: 真实库 ──────────────────────────────────────────────

@pytest.mark.skipif(not COD_DB.exists(), reason="COD 无机物库不在本机")
def test_inspect_real_cod_inorganics():
    ins = db_import.inspect_db_file(COD_DB)
    assert ins.ok and ins.kind == "cod_inorganics"
    assert ins.rows == 71_199
    assert ins.has_top_peaks is True          # 已迁移 top-N 强峰列
    assert ins.error == ""


@pytest.mark.skipif(not PDF2_DB.exists(), reason="PDF2 库不在本机")
def test_inspect_real_pdf2():
    ins = db_import.inspect_db_file(PDF2_DB)
    assert ins.ok and ins.kind == "pdf2"
    assert ins.rows == 163_834
    # PDF2 自带的 peaks_d 只有 ~64 个/相, 不需要 top-N 列
    assert ins.has_top_peaks is False


@pytest.mark.skipif(not INDEX_DB.exists(), reason="cod_index 不在本机")
def test_inspect_real_cod_index():
    ins = db_import.inspect_db_file(INDEX_DB)
    assert ins.ok and ins.kind == "cod_index"
    assert ins.rows == 113_223


# ── 探测: 合成库 / 歧义与失败路径 ─────────────────────────────

def test_pdf2_is_not_mistaken_for_cod_inorganics(tmp_path):
    """两者表名同为 phases, PDF2 多出的 pearson 列必须把它排除掉。"""
    p = _make_pdf2_db(tmp_path / "fake_pdf2.sqlite")
    ins = db_import.inspect_db_file(p)
    assert ins.ok and ins.kind == "pdf2", ins


def test_cod_inorganics_is_not_mistaken_for_pdf2(tmp_path):
    """反向: 没有 pearson/name 的 phases 表不该被判成 PDF2。"""
    p = _make_cod_db(tmp_path / "fake_cod.sqlite")
    ins = db_import.inspect_db_file(p)
    assert ins.ok and ins.kind == "cod_inorganics", ins


def test_missing_required_column_reports_hint(tmp_path):
    p = _make_db(
        tmp_path / "no_peaks.sqlite",
        "CREATE TABLE phases (cod_id TEXT, formula TEXT, n_peaks INTEGER, cell_a REAL)",
    )
    ins = db_import.inspect_db_file(p)
    assert not ins.ok
    assert ins.error == "schema_mismatch"
    assert "peaks_d" in ins.hint and "peaks_i" in ins.hint


def test_cod_index_too_few_rows_rejected(tmp_path):
    p = _make_db(
        tmp_path / "tiny_index.sqlite",
        "CREATE TABLE cod_entries (cod_id TEXT, formula TEXT, elements TEXT, cif_gz BLOB)",
        [("1", "SiO2", "Si O", b"x")],
        "INSERT INTO cod_entries VALUES (?,?,?,?)",
    )
    ins = db_import.inspect_db_file(p)
    assert not ins.ok
    assert ins.error == "schema_mismatch"
    assert ins.hint.startswith("too_few_rows:")


def test_empty_sqlite_no_matching_table(tmp_path):
    p = _make_db(tmp_path / "empty.sqlite", "CREATE TABLE unrelated (x INTEGER)")
    ins = db_import.inspect_db_file(p)
    assert not ins.ok and ins.error == "no_matching_table"


def test_non_sqlite_file_rejected(tmp_path):
    p = tmp_path / "notdb.sqlite"
    p.write_text("this is plain text, not sqlite", encoding="utf-8")
    ins = db_import.inspect_db_file(p)
    assert not ins.ok and ins.error == "not_sqlite"


def test_missing_file_and_directory(tmp_path):
    assert db_import.inspect_db_file(tmp_path / "nope.sqlite").error == "file_not_found"
    assert db_import.inspect_db_file(tmp_path).error == "not_a_file"


def test_inspect_is_read_only(tmp_path):
    """探测过程绝不能改动被测文件 (mode=ro)。"""
    p = _make_cod_db(tmp_path / "ro.sqlite")
    before = (p.stat().st_size, p.stat().st_mtime_ns)
    db_import.inspect_db_file(p)
    assert (p.stat().st_size, p.stat().st_mtime_ns) == before
    assert not (tmp_path / "ro.sqlite-wal").exists()


# ── 落地: apply / clear 往返 ──────────────────────────────────

def test_apply_and_clear_roundtrip(tmp_cfg, tmp_path):
    p = _make_cod_db(tmp_path / "cod.sqlite")
    ins = db_import.inspect_db_file(p)
    assert ins.ok and ins.kind == "cod_inorganics"

    db_import.apply_import(ins)
    cfg = get_config()
    assert cfg.get_cod_db_path() == p.resolve()
    assert db_import.is_user_imported("cod_inorganics") is True

    db_import.clear_import("cod_inorganics")
    assert db_import.is_user_imported("cod_inorganics") is False
    # v0.14.0: 回退默认 = 瘦身索引式优先, 无瘦身版时回退完整内嵌版
    expected = cfg.cod_db_path.with_name("COD_inorganics_index.sqlite")
    assert cfg.get_cod_db_path() == (expected if expected.exists()
                                     else cfg.cod_db_path)


def test_apply_import_rejects_unvalidated(tmp_path):
    p = _make_db(tmp_path / "bad.sqlite", "CREATE TABLE nope (x INTEGER)")
    ins = db_import.inspect_db_file(p)
    assert not ins.ok
    with pytest.raises(ValueError):
        db_import.apply_import(ins)


def test_importing_one_slot_keeps_others(tmp_cfg, tmp_path):
    """三个槽位共用同一个 json, 按 key 增量写, 不能互相抹掉。"""
    cod = _make_cod_db(tmp_path / "cod.sqlite")
    pdf = _make_pdf2_db(tmp_path / "pdf2.sqlite")
    db_import.apply_import(db_import.inspect_db_file(cod))
    db_import.apply_import(db_import.inspect_db_file(pdf))

    cfg = get_config()
    assert cfg.get_cod_db_path() == cod.resolve()
    assert cfg.get_pdf2_db_path() == pdf.resolve()

    db_import.clear_import("pdf2")
    assert cfg.get_cod_db_path() == cod.resolve()      # 另一个槽位幸存
    assert db_import.is_user_imported("pdf2") is False


def test_user_path_ignored_when_file_vanished(tmp_cfg, tmp_path):
    """用户挪走/删掉外挂库后应自动回退默认, 而不是抱住死路径。"""
    p = _make_cod_db(tmp_path / "gone.sqlite")
    db_import.apply_import(db_import.inspect_db_file(p))
    cfg = get_config()
    assert cfg.get_cod_db_path() == p.resolve()

    p.unlink()
    # v0.14.0: 回退默认 = 瘦身索引式优先, 无瘦身版时回退完整内嵌版
    expected = cfg.cod_db_path.with_name("COD_inorganics_index.sqlite")
    assert cfg.get_cod_db_path() == (expected if expected.exists()
                                     else cfg.cod_db_path)


# ── 呈现: slot_states / live_counts ──────────────────────────

def test_slot_states_shape(tmp_cfg):
    states = db_import.slot_states()
    assert [s["kind"] for s in states] == ["cod_inorganics", "pdf2", "cod_index"]
    for s in states:
        for key in ("label_key", "path", "exists", "imported", "rows",
                    "has_top_peaks", "ok", "error", "hint", "size_mb"):
            assert key in s, key


def test_slot_states_without_validate_skips_db_read(tmp_cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(db_import, "inspect_db_file",
                        lambda p: calls.append(p) or db_import.DBInspect(path=Path(p)))
    db_import.slot_states(validate=False)
    assert calls == []


def test_live_counts_uses_mtime_cache(tmp_cfg, tmp_path):
    db_import._count_rows_cached.cache_clear()

    p = _make_cod_db(tmp_path / "count.sqlite")
    db_import._count_rows_cached(str(p), p.stat().st_mtime, "phases")
    hits_before = db_import._count_rows_cached.cache_info().hits
    db_import._count_rows_cached(str(p), p.stat().st_mtime, "phases")
    assert db_import._count_rows_cached.cache_info().hits == hits_before + 1


def test_live_counts_reads_new_file_after_replacement(tmp_cfg, tmp_path, monkeypatch):
    """覆盖同名文件 (重新下载) 后相数必须跟着变 —— mtime 参与缓存键。"""
    monkeypatch.setattr(db_import, "_default_paths",
                        lambda: {"cod_inorganics": tmp_path / "c.sqlite",
                                 "pdf2": tmp_path / "p.sqlite",
                                 "cod_index": tmp_path / "i.sqlite"})
    db_import._count_rows_cached.cache_clear()

    c = _make_db(tmp_path / "c.sqlite", f"CREATE TABLE phases ({COD_COLS})")
    assert db_import.live_counts() == {"cod_inorganics": 0, "pdf2": 0, "cod_index": 0}

    c.unlink()
    _make_cod_db(tmp_path / "c.sqlite")
    assert db_import.live_counts()["cod_inorganics"] == 1
    assert db_import.live_counts()["cod_inorganics"] == 1   # 命中缓存, 值不变


def test_default_paths_does_not_deploy_bundled_db(tmp_cfg):
    """核心回归: 解析 cod_index 位置必须纯只读, 不许触发首次部署复制。"""
    cfg = get_config()
    target = cfg.get_cif_db_path() / "cod_index.sqlite"
    existed = target.exists()
    size_before = target.stat().st_size if existed else -1

    db_import._default_paths()

    assert target.exists() == existed, "默认路径解析不应创建 cod_index.sqlite"
    if existed:
        assert target.stat().st_size == size_before


def test_clear_import_unknown_key(tmp_cfg):
    with pytest.raises(KeyError):
        db_import.clear_import("no_such_kind")


# ── 三库独立下载包 (0.10.0: 拆包) ────────────────────────────

def test_pkg_suffixes_present_and_distinct():
    """能发布的槽位各自对应一个独立下载包, 后缀不能重复; PDF2 必须无包。

    PDF2-2004 是 ICDD 版权商品库, 政策上**永不随 Release 分发** —— 所以这里
    反过来断言它的 `pkg_suffix` 为空。哪天有人手滑给它加回后缀, 这条会红。
    """
    suffixes = [k.pkg_suffix for k in db_import.DB_KINDS if k.key != "pdf2"]
    assert all(suffixes), f"有槽位缺 pkg_suffix: {suffixes}"
    assert len(set(suffixes)) == len(suffixes), f"下载包后缀重复: {suffixes}"

    pdf2 = db_import.KIND_BY_KEY["pdf2"]
    assert pdf2.pkg_suffix == "", (
        "PDF2 不得有发布包 —— 该库受 ICDD 版权保护, 只本地保留"
    )


def test_release_package_name_shape():
    n = db_import.release_package_name("cod_inorganics", "0.10.0")
    # v0.14.0: 无机物库发布包改发瘦身索引式 → 后缀带 -index
    assert n == "PolyXRD-v0.10.0-Databases-COD-inorg-index.zip", n
    assert db_import.release_package_name("cod_index", "0.10.0").endswith(
        "-COD-full-index.zip")
    # 版本号必须来自入参, 不能硬编码在源码里
    assert "v9.9.9" in db_import.release_package_name("cod_index", "9.9.9")
    # PDF2 没有发布包 → 空串 (界面据此改显示"自行准备")
    assert db_import.release_package_name("pdf2", "0.10.0") == ""
    assert db_import.release_package_name("pdf2", "9.9.9") == ""


def test_pkg_filename_matches_inspected_file(tmp_path):
    """PKG_FILENAME 必须与实际库文件名一致 —— 用户照着文档改名会导不进来。"""
    # v0.14.0: 无机物库发布包改发瘦身索引式
    assert db_import.PKG_FILENAME["cod_inorganics"] == "COD_inorganics_index.sqlite"
    assert db_import.PKG_FILENAME["cod_index"] == "cod_index.sqlite"
    assert db_import.PKG_FILENAME["pdf2"] == "PDF2_2004.sqlite"
    # 每个 kind 都要有对应的文件名, 否则 GUI 那行提示会是空的
    for k in db_import.DB_KINDS:
        assert db_import.PKG_FILENAME.get(k.key), k.key


def test_slot_states_expose_package_info(tmp_cfg):
    # 包名带版本号 → 从与实现同源的 release_package_name 推导,
    # 避免每次发版都要手改测试 (0.11.0 升版时这里曾漏改)。
    version = get_config().app_version
    expected = {
        "cod_inorganics": db_import.release_package_name("cod_inorganics", version),
        "cod_index": db_import.release_package_name("cod_index", version),
        # PDF2 无发布包 (ICDD 版权) → 空串, 界面改显示"自行准备"
        "pdf2": "",
    }
    # 顺带钉死: 包名必须带当前版本号, 且两个 COD 包名确实不同
    assert expected["cod_inorganics"] == f"PolyXRD-v{version}-Databases-COD-inorg-index.zip"
    assert expected["cod_index"] == f"PolyXRD-v{version}-Databases-COD-full-index.zip"

    states = {s["kind"]: s for s in db_import.slot_states(validate=False)}
    for kind, want in expected.items():
        assert states[kind]["pkg_name"] == want, states[kind]["pkg_name"]
        assert states[kind]["pkg_filename"] == db_import.PKG_FILENAME[kind]
    # 两个 COD 包名不同; 空串只允许出现一次 (只有 PDF2)
    names = [s["pkg_name"] for s in states.values()]
    assert len({n for n in names if n}) == 2
    assert names.count("") == 1
