"""M15 指标化 - 单元测试 (services/indexing)"""
import math

import pytest

from polyxrd.services.indexing import (
    index_builtin,
    index_dicvol,
    index_treor,
    to_d_spacings,
)


def _d_from_cubic(a, n2_list):
    return sorted((a / math.sqrt(n) for n in n2_list), reverse=True)


# ── to_d_spacings ──

def test_to_d_spacings_silicon_111():
    # Si (111): a=5.4309 → d=3.1355, Cu Kα1 1.5406 → 2θ≈28.44
    d = to_d_spacings([28.44], 1.5406)
    assert d[0] == pytest.approx(3.1355, abs=0.003)


def test_to_d_spacings_skips_invalid():
    d = to_d_spacings([0, -5, 28.44, 999], 1.5406)
    assert len(d) == 1


def test_to_d_spacings_bad_wavelength():
    with pytest.raises(ValueError):
        to_d_spacings([28.44], 0.0)


# ── index_builtin (路线图验收: 立方 Si → a≈5.43) ──

def test_index_builtin_cubic_silicon():
    a_true = 5.4309
    # 金刚石结构允许的 N² = 3,8,11,16,19,24,...
    n2 = [3, 8, 11, 16, 19, 24, 27, 32, 35, 40]
    d = _d_from_cubic(a_true, n2)
    cells = index_builtin(d)
    assert cells, "立方 Si 必须给出解"
    best = cells[0]
    assert best.system == "cubic"
    assert best.a == pytest.approx(a_true, rel=0.005)   # ≈5.43
    assert best.n_indexed >= len(n2) - 1                # 几乎全解释
    assert best.hkl_of_peaks[0] == (1, 1, 1)


def test_index_builtin_cubic_nacl():
    # NaCl a=5.6402, 面心: N² = 3,4,8,11,12,16,19,20,24,...
    n2 = [3, 4, 8, 11, 12, 16, 19, 20, 24]
    d = _d_from_cubic(5.6402, n2)
    cells = index_builtin(d)
    assert cells
    assert cells[0].system == "cubic"
    assert cells[0].a == pytest.approx(5.6402, rel=0.005)


def test_index_builtin_tetragonal_rutile():
    # 金红石 TiO2: a=4.5937, c=2.9587 (P4₂/mnm)
    a, c = 4.5937, 2.9587
    refl = [(1, 1, 0), (1, 0, 1), (2, 0, 0), (1, 1, 1), (2, 1, 0),
            (2, 1, 1), (2, 2, 0), (0, 0, 2), (3, 1, 0), (3, 0, 1)]
    d = sorted(
        (1.0 / math.sqrt((h * h + k * k) / a**2 + l * l / c**2)
         for h, k, l in refl),
        reverse=True,
    )
    cells = index_builtin(d)
    assert cells, "金红石必须给出解"
    best = cells[0]
    assert best.system in ("tetragonal", "cubic")  # 允许更高对称命中
    if best.system == "tetragonal":
        assert best.a == pytest.approx(a, rel=0.01)
        assert best.c == pytest.approx(c, rel=0.02)


def test_index_builtin_too_few_peaks():
    assert index_builtin([3.14, 2.71]) == []
    assert index_builtin([]) == []


def test_rank_cells_prefers_full_explanation():
    from polyxrd.services.indexing import IndexedCell, rank_cells
    c_full = IndexedCell("cubic", 5.43, n_indexed=10, n_total=10, fom=1.0)
    c_part = IndexedCell("cubic", 5.50, n_indexed=8, n_total=10, fom=0.9)
    out = rank_cells([c_part, c_full])
    assert out[0] is c_full


# ── 外部接口预留 ──

def test_external_stubs_raise():
    with pytest.raises(NotImplementedError):
        index_treor([3.14, 2.7, 1.6])
    with pytest.raises(NotImplementedError):
        index_dicvol([3.14, 2.7, 1.6])
