"""显式 ``db_path`` 转发与"不污染实例状态"回归测试 (v4.1.0, v5.2 收窄)
==========================================================

列表式多库挂载之后, polyDB 的三个变体 (``cod-inorg`` / ``cod-full`` /
``pdf2-2004``) 共用 ``identify_with_polydb`` 一个引擎。v5.2 删除了 PDF2 的
独立 sqlite 通道 (``identify_with_pdf2`` / ``PDF2Database``), 于是原来"两个
引擎各测一遍"的用例收敛成一组 —— 但契约本身没变, 这里继续钉住:

1. **显式路径只对本次调用生效** —— 传了就按传的查, 不写进配置、不缓存到实例
   (修复前的坑: 显式库粘在实例上, 切回默认库时静默查错库);
2. **省略路径时按变体选槽位** —— ``variant="cod-full"`` 必须拿全库那份,
   ``variant="pdf2-2004"`` 必须拿 PDF2 那份, 不能悄悄退到无机库;
3. **库不可用就返回空, 绝不静默回退** —— 用户选了"COD 全库"但那份没挂载时,
   宁可空结果也不能拿另一份库冒充。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.models.peak import Peak, PeakList            # noqa: E402
from polyxrd.models.xrd_data import XRDData              # noqa: E402


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


class _FakePoly:
    """记录构造入参的 PolyDatabase 替身。"""

    calls: list[dict] = []
    ready = True

    def __init__(self, db_path=None, variant="cod-inorg"):
        type(self).calls.append({"db_path": db_path, "variant": variant})

    def is_ready(self) -> bool:
        return type(self).ready

    def search_by_d_peaks(self, *a, **k):      # 不可用/无候选 → 空
        return []

    def get_phase(self, *a, **k):
        return None


import pytest  # noqa: E402

import polyxrd.services.polydb as polydb_mod         # noqa: E402
from polyxrd.services.phase_identifier import PhaseIdentifier  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch, tmp_path):
    _FakePoly.calls = []
    _FakePoly.ready = True
    monkeypatch.setattr(polydb_mod, "PolyDatabase", _FakePoly)
    # 配置全部隔离到临时目录: 任何"偷偷写配置"的行为都会留下痕迹
    from polyxrd.config import AppConfig
    monkeypatch.setattr(AppConfig, "_user_db_paths_file",
                        lambda self: tmp_path / "user_db_paths.json")
    yield tmp_path


# ── polyDB: 显式路径 / 变体槽位 ──────────────────────────────

def test_polydb_explicit_path_is_used_verbatim(_reset_fakes):
    PhaseIdentifier().identify_with_polydb(
        _make_data(), peaks=_make_peaks(), db_path="D:/libs/COD-Inorg-X.polyDB")
    assert _FakePoly.calls == [{"db_path": "D:/libs/COD-Inorg-X.polyDB",
                                "variant": "cod-inorg"}]


def test_polydb_explicit_path_does_not_write_config(_reset_fakes):
    PhaseIdentifier().identify_with_polydb(
        _make_data(), peaks=_make_peaks(), db_path="D:/libs/X.polyDB")
    assert not (_reset_fakes / "user_db_paths.json").exists(), \
        "显式库不该落进配置文件"


def test_polydb_omitted_path_follows_variant(_reset_fakes):
    """省略路径时不能退到无机库: 变体必须原样传下去。"""
    PhaseIdentifier().identify_with_polydb(
        _make_data(), peaks=_make_peaks(), variant="cod-full")
    assert _FakePoly.calls == [{"db_path": None, "variant": "cod-full"}]


def test_polydb_default_variant_is_inorg(_reset_fakes):
    PhaseIdentifier().identify_with_polydb(_make_data(), peaks=_make_peaks())
    assert _FakePoly.calls == [{"db_path": None, "variant": "cod-inorg"}]


def test_polydb_not_ready_returns_empty(_reset_fakes):
    _FakePoly.ready = False
    res = PhaseIdentifier().identify_with_polydb(
        _make_data(), peaks=_make_peaks(), db_path="D:/gone.polyDB")
    assert res == []


def test_polydb_calls_are_independent(_reset_fakes):
    """连续两次调用: 前一次的显式路径不得粘到后一次。"""
    pi = PhaseIdentifier()
    pi.identify_with_polydb(_make_data(), peaks=_make_peaks(), db_path="D:/a.polyDB")
    pi.identify_with_polydb(_make_data(), peaks=_make_peaks(), variant="cod-full")
    assert [c["db_path"] for c in _FakePoly.calls] == ["D:/a.polyDB", None]
    assert [c["variant"] for c in _FakePoly.calls] == ["cod-inorg", "cod-full"]


# ── PDF2-2004: 走同一个引擎, 变体必须原样带下去 ─────────────

def test_pdf2_variant_is_forwarded(_reset_fakes, tmp_path):
    """PDF2 并入 polyDB 后: 显式路径交给同一个引擎, 按显式路径开库。

    v5.2 之前这段验的是 ``identify_with_pdf2(db_path=...)``。引擎合并后契约
    不变 —— "用户选中的那一行"必须逐字生效, 不能悄悄换成默认无机库。
    显式路径下 ``variant`` 只是槽位提示 (开库后按 meta.json 自我校正),
    所以这里断言的是路径, 不是构造参数。
    """
    target = str(tmp_path / "PDF2-2004.polyDB")
    PhaseIdentifier().identify_with_polydb(
        _make_data(), peaks=_make_peaks(),
        db_path=target, variant="pdf2-2004")
    assert [c["db_path"] for c in _FakePoly.calls] == [target]


def test_pdf2_variant_omitted_path_lets_registry_decide(_reset_fakes):
    """省略路径时按 variant 取槽位 (对应旧 ``pdf2_db_path`` 配置的作用)。

    这一条是 PDF2 变体接线的关键: 变体没传下去就会静默查 COD 无机库,
    结果"有候选"但全是别的相 —— 比报错更难发现。
    """
    PhaseIdentifier().identify_with_polydb(
        _make_data(), peaks=_make_peaks(), variant="pdf2-2004")
    assert _FakePoly.calls == [{"db_path": None, "variant": "pdf2-2004"}]


def test_pdf2_variant_not_ready_returns_empty(_reset_fakes):
    _FakePoly.ready = False
    res = PhaseIdentifier().identify_with_polydb(
        _make_data(), peaks=_make_peaks(),
        db_path="D:/gone.polyDB", variant="pdf2-2004")
    assert res == []
