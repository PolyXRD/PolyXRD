"""
指标化 (M15)
============
由粉末衍射 d 值列表求解晶胞参数的内置兜底实现 (无需外部程序)。

- to_d_spacings : 2θ → d (布拉格定律)
- index_builtin : 内置指标化 (立方/四方/六方逐一尝试, 按解释峰数与
  晶胞体积排序) —— "三强峰法 + 最小晶胞体积搜索" 的实现口径:
  用最大 d 峰的低指数假设生成候选基矢, 以全部峰的符合度打分, 同分取最小体积
- rank_cells    : 候选晶胞排序
- index_treor / index_dicvol : 外部程序接口 (Treor90/Dicvol06),
  本版仅留接口, 未实现时抛 NotImplementedError

约定: d 单位 Å; 晶胞参数 Å/°; 四方/六方只输出 a=c 固定轴角的解。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class IndexedCell:
    """指标化得到的晶胞候选"""
    system: str                      # cubic / tetragonal / hexagonal
    a: float
    c: float = 0.0                   # 立方时 = 0
    volume: float = 0.0
    n_indexed: int = 0               # 被解释的峰数
    n_total: int = 0
    fom: float = 0.0                 # 解释率 × (1 / 归一体积) 简化口径
    hkl_of_peaks: list = field(default_factory=list)  # 每峰 (h,k,l) 或 None

    def to_dict(self) -> dict:
        return {
            "system": self.system, "a": self.a, "c": self.c,
            "volume": self.volume, "n_indexed": self.n_indexed,
            "n_total": self.n_total, "fom": self.fom,
        }


def to_d_spacings(two_theta, wavelength: float) -> list[float]:
    """2θ (°) 列表 → d 值 (Å)。d = λ / (2 sin θ), θ = 2θ/2。

    无效行 (2θ≤0 或 >180) 跳过。
    """
    lam = float(wavelength)
    if lam <= 0:
        raise ValueError(f"波长非法: {wavelength}")
    out = []
    for tt in two_theta:
        tt = float(tt)
        if not (0 < tt < 180):
            continue
        d = lam / (2.0 * math.sin(math.radians(tt / 2.0)))
        out.append(d)
    return out


# 各晶系允许的 (h²+k²+l²) / (h²+k²) / (h²+hk+k²) 低指数值
_CUBIC_N2 = [n for n in range(1, 100)
             if any((n - i * i - j * j - k * k) == 0
                    for i in range(10) for j in range(10) for k in range(10))]
_TET_M = [0, 1, 2, 4, 5, 8, 9, 10, 13, 16]   # h²+k²
_HEX_M = [0, 1, 3, 4, 7, 9, 12, 13, 16, 19]  # h²+hk+k²
_L2 = [0, 1, 4, 9, 16]                        # l²


# (v2.1 P3: 已删除未调用的 _sum3_squares —— _CUBIC_N2 预计算覆盖同逻辑)


def _closest_valid(target: float, valid: list[int], tol: float):
    """离 target 最近的合法整数值; 超出 tol 返回 None。"""
    n = int(round(target))
    best = None
    for cand in (n - 1, n, n + 1):
        if cand in valid:
            if best is None or abs(cand - target) < abs(best - target):
                best = cand
    if best is not None and abs(best - target) <= tol:
        return best
    return None


def _index_cubic(d_list, tol_rel=0.005):
    """立方: q = 1/d² = N²/a²。对最大 d 峰尝试各 N² 假设。"""
    results = []
    d0 = d_list[0]
    for n2 in _CUBIC_N2:
        a = d0 * math.sqrt(n2)
        if not (1.0 < a < 50.0):
            continue
        hkl_map = []
        n_ok = 0
        ok = True
        for d in d_list:
            target = (a / d) ** 2
            n = _closest_valid(target, _CUBIC_N2, tol=max(0.05, tol_rel * 2 * target))
            if n is None:
                hkl_map.append(None)
                ok = False
                continue
            n_ok += 1
            hkl_map.append(_hkl_for_n2(n))
        if n_ok < max(2, int(0.5 * len(d_list))):
            continue
        vol = a ** 3
        results.append(("cubic", a, 0.0, vol, n_ok, hkl_map))
    return results


def _hkl_for_n2(n2: int):
    for i in range(10):
        for j in range(i, 10):
            for k in range(j, 10):
                if i * i + j * j + k * k == n2:
                    return (i, j, k)
    return None


def _hkl_for_tet(m: int, l2: int):
    for h in range(5):
        for k in range(h, 5):
            if h * h + k * k == m:
                for l in range(5):
                    if l * l == l2:
                        return (h, k, l)
    return None


def _hkl_for_hex(m: int, l2: int):
    for h in range(5):
        for k in range(5):
            if h * h + h * k + k * k == m:
                for l in range(5):
                    if l * l == l2:
                        return (h, k, l)
    return None


def _index_ab(d_list, system, tol_rel=0.005):
    """四方 (q = m/a² + l²/c²) / 六方 (q = 4m/(3a²) + l²/c²)。

    用最大 d 峰与次大 d 峰的低指数假设对生成候选 (a, c), 全峰验证。
    """
    prefac = 1.0 if system == "tetragonal" else 4.0 / 3.0
    mvals = _TET_M if system == "tetragonal" else _HEX_M
    hkl_fun = _hkl_for_tet if system == "tetragonal" else _hkl_for_hex
    results = []
    d0, d1 = d_list[0], d_list[1] if len(d_list) > 1 else d_list[0]
    q0, q1 = 1.0 / d0**2, 1.0 / d1**2
    seen = set()
    # 双峰低指数假设枚举: 两方程 prefac·m·(1/a²) + l²·(1/c²) = q 解出
    # (1/a², 1/c²), 再对全部峰验证 (多余的中间草稿已删除)。
    for m0 in mvals:
        for l20 in _L2:
            if m0 == 0 and l20 == 0:
                continue
            for m1 in mvals:
                for l21 in _L2:
                    if m1 == 0 and l21 == 0:
                        continue
                    # 两方程解 (1/a², 1/c²):
                    # prefac·m0·A + l20·C = q0 ; prefac·m1·A + l21·C = q1
                    det = (prefac * m0) * l21 - (prefac * m1) * l20
                    if abs(det) < 1e-12:
                        continue
                    A = (q0 * l21 - q1 * l20) / det
                    C = (prefac * m0 * q1 - prefac * m1 * q0) / det
                    if A <= 0:
                        continue
                    a = 1.0 / math.sqrt(A)
                    c = 1.0 / math.sqrt(C) if C > 0 else 0.0
                    if not (1.0 < a < 50.0) or (C > 0 and not (1.0 < c < 80.0)):
                        continue
                    if C <= 0:  # 峰表未约束 c → 无效
                        continue
                    key = (round(a, 3), round(c, 3))
                    if key in seen:
                        continue
                    seen.add(key)
                    hkl_map = []
                    n_ok = 0
                    for d in d_list:
                        q = 1.0 / d**2
                        m_best = l_best = None
                        err_best = None
                        for m in mvals:
                            rem = q - prefac * m
                            if rem < 0:
                                continue
                            l2c = _closest_valid(rem / max(C, 1e-12), _L2,
                                                 tol=0.06)
                            if l2c is None:
                                continue
                            err = abs(prefac * m * A + l2c * C - q)
                            if err_best is None or err < err_best:
                                err_best = err
                                m_best, l_best = m, l2c
                        if err_best is not None and \
                                err_best <= tol_rel * 2 * q:
                            n_ok += 1
                            hkl_map.append(hkl_fun(m_best, l_best))
                        else:
                            hkl_map.append(None)
                    if n_ok < max(3, int(0.6 * len(d_list))):
                        continue
                    vol = a * a * c if system == "tetragonal" \
                        else a * a * c * math.sin(math.radians(120.0))
                    results.append((system, a, c, vol, n_ok, hkl_map))
    return results


def index_builtin(d_list, *, tol_rel: float = 0.005) -> list[IndexedCell]:
    """内置指标化: 立方/四方/六方逐一尝试, 返回按解释峰数/体积排序的候选。

    Args:
        d_list: d 值列表 (Å, 降序 = 大 d 在前; 内部会排序去重)
        tol_rel: 相对 2θ/q 容差 (默认 0.5%)
    """
    ds = sorted({round(float(d), 6) for d in d_list if d and d > 0},
                reverse=True)
    if len(ds) < 3:
        return []
    raw = []
    raw += _index_cubic(ds, tol_rel)
    raw += _index_ab(ds, "tetragonal", tol_rel)
    raw += _index_ab(ds, "hexagonal", tol_rel)
    cells = []
    for system, a, c, vol, n_ok, hkl_map in raw:
        fom = n_ok / len(ds) * (100.0 / max(vol, 1e-9)) ** (1.0 / 3.0)
        cells.append(IndexedCell(
            system=system, a=round(a, 5), c=round(c, 5), volume=round(vol, 3),
            n_indexed=n_ok, n_total=len(ds), fom=round(fom, 5),
            hkl_of_peaks=hkl_map,
        ))
    return rank_cells(cells)


def rank_cells(cells: list[IndexedCell]) -> list[IndexedCell]:
    """排序: 解释峰数多 → FOM 高 (解释率 × 体积惩罚); 同级保持稳定。"""
    return sorted(cells, key=lambda c: (-c.n_indexed, -c.fom, c.volume))


def index_treor(d_list, treor_exe=None) -> list[IndexedCell]:
    """外部 Treor90 指标化 (接口预留, v0.15 未实现)。"""
    raise NotImplementedError(
        "Treor90 外部指标化未实现; 请用 index_builtin (立方/四方/六方)")


def index_dicvol(d_list, dicvol_exe=None) -> list[IndexedCell]:
    """外部 Dicvol06 指标化 (接口预留, v0.15 未实现)。"""
    raise NotImplementedError(
        "Dicvol06 外部指标化未实现; 请用 index_builtin (立方/四方/六方)")
