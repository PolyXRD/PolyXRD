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


def _d_from_ab(system, a, c, max_peaks=10):
    """按四方/六方 q 公式生成干净 d 值表 (降序, 取最强 max_peaks 条)。

    与 index_builtin 分步同口径:
      四方  q = (h²+k²)/a² + l²/c²
      六方  q = 4(h²+hk+k²)/(3a²) + l²/c²
    """
    prefac = 1.0 if system == "tetragonal" else 4.0 / 3.0
    ms = [0, 1, 2, 4, 5, 8, 9, 10, 13, 16] if system == "tetragonal" \
        else [0, 1, 3, 4, 7, 9, 12, 13, 16, 19]
    qs = [prefac * m / a**2 + l2 / c**2
          for m in ms for l2 in (0, 1, 4, 9, 16) if not (m == 0 and l2 == 0)]
    return sorted({round(1.0 / math.sqrt(q), 6) for q in qs}, reverse=True)[:max_peaks]


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
    # v3.0.1: 四方/六方分支修复后可严格断言 (此前四方候选根本进不了表,
    # 测试只能退化为 "tetragonal 或 cubic")。
    assert best.system == "tetragonal"
    assert best.a == pytest.approx(a, rel=0.01)
    assert best.c == pytest.approx(c, rel=0.02)


@pytest.mark.parametrize("a,c", [(4.0, 6.0), (3.0, 4.5), (5.2, 7.8)])
def test_index_builtin_tetragonal_synthetic(a, c):
    """P0-6 回归: 四方真解必须排第一且解释全部峰。

    旧实现残差式漏乘 A（``rem = q - prefac*m``），四方/六方候选全被内核
    判据淘汰，只剩立方假解（实测 a=4.0/c=6.0 返回 16 个全立方候选、
    真解缺席）。
    """
    d = _d_from_ab("tetragonal", a, c)
    cells = index_builtin(d)
    assert cells, "四方样品必须给出解"
    best = cells[0]
    assert best.system == "tetragonal"
    assert best.a == pytest.approx(a, abs=2e-3)
    assert best.c == pytest.approx(c, abs=2e-3)
    assert best.n_indexed == len(d)


@pytest.mark.parametrize("a,c", [(3.0, 5.0), (2.5, 4.1), (3.5, 6.2), (4.0, 3.2)])
def test_index_builtin_hexagonal_synthetic(a, c):
    """P0-6 回归: 六方真解必须排第一。

    (3.5, 6.2) 专门覆盖"头两条强峰同属 00l"的退化情形 —— 只用前两峰
    解方程组时 det=0 / 解出错误 A, 真解不进候选表; 改为枚举前 4 条强峰
    的所有峰对后修复。
    """
    d = _d_from_ab("hexagonal", a, c)
    cells = index_builtin(d)
    assert cells, "六方样品必须给出解"
    best = cells[0]
    assert best.system == "hexagonal"
    assert best.a == pytest.approx(a, abs=2e-3)
    assert best.c == pytest.approx(c, abs=2e-3)
    assert best.n_indexed == len(d)


def test_index_builtin_cubic_wins_over_low_symmetry_subcell():
    """高对称优先: 立方真解必须压过体积更小的低对称子胞。

    Si 金刚石 (立方 a=5.4309, V=160.2 Å³) 的 d 值表可被六方
    a=4.4343/c=5.4309 (V=92.5 Å³) 精确复现 —— 纯几何无法区分，
    若只按"体积越小越好"排序立方真解永远排不到第一。``rank_cells``
    的 ``_SYM_BAND`` 规则即为此而设。
    """
    a_true = 5.4309
    d = _d_from_cubic(a_true, [3, 8, 11, 16, 19, 24, 27, 32, 35, 40])
    best = index_builtin(d)[0]
    assert best.system == "cubic"
    assert best.a == pytest.approx(a_true, rel=0.005)


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
