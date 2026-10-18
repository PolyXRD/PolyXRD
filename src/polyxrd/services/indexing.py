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

#: 四方/六方双峰方程组枚举时，参与配对的前 N 条强峰数量。
#: 取 2 时（旧行为）若头两条峰同属 00l 则方程退化、真解丢失；
#: 取 4 覆盖所有 C(4,2)=6 个峰对，候选数约 6 倍、耗时仍 < 0.5 s。
_PAIR_PEAKS = 4

#: 同解释峰数时的"高对称优先"体积带（相对最小候选体积的倍数）。
#:
#: 纯几何指标化存在**固有歧义**：高对称晶胞总能被某个低对称子胞以更小
#: 体积精确复现同一组 d 值 —— Si 金刚石 (立方 a=5.4309, V=160.2 Å³) 实测
#: 可被六方 a=4.4343 c=5.4309 (V=92.5 Å³) 完整解释，NaCl 面心立方
#: (V=179.4) 亦可被六方 V=73.3 解释。若只按"体积越小越好"排序，立方样品的
#: 真解永远排不到第一。真实指标化软件靠消光规律（空间群）区分，本模块没有
#: 消光信息，故用一条经验规则代替：**解释峰数相同时，若高对称解的晶胞体积
#: 落在最小候选的 2.5 倍以内，则视为同一胞的不同描述 → 优先高对称**；
#: 体积相差 2.5 倍以上（真·不同晶胞，如同一样品的最小胞 vs 超胞）不受此规则
#: 影响，仍按解释率/体积排。
_SYM_BAND = 2.5

#: 晶系对称性优先级（数值越小越对称）。
_SYSTEM_RANK = {"cubic": 0, "tetragonal": 1, "hexagonal": 2}


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

    v3.0.1 修复两处（此前四方/六方分支实际不可用）：
      1. 残差式漏乘 A（量纲与判据不一致）→ 候选全错（详见下方注释）；
      2. 只用前两条强峰解方程组 —— 若它们同属 00l（层状/长 c 轴样品极常见），
         方程组退化或解出错误 A，**真解根本不进候选表**。改为在前
         ``_PAIR_PEAKS`` 条强峰里枚举所有峰对。
    """
    prefac = 1.0 if system == "tetragonal" else 4.0 / 3.0
    mvals = _TET_M if system == "tetragonal" else _HEX_M
    hkl_fun = _hkl_for_tet if system == "tetragonal" else _hkl_for_hex
    results = []
    qs = [1.0 / float(d) ** 2 for d in d_list]
    n_pair = min(_PAIR_PEAKS, len(qs))
    pair_idx = [(i, j) for i in range(n_pair) for j in range(i + 1, n_pair)]
    seen = set()
    # 双峰低指数假设枚举: 两方程 prefac·m·(1/a²) + l²·(1/c²) = q 解出
    # (1/a², 1/c²), 再对全部峰验证。
    for i0, i1 in pair_idx:
        q0, q1 = qs[i0], qs[i1]
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
                                # q = prefac·m·A + l²·C  →  l² = (q − prefac·m·A)/C
                                # v3.0.1 修复: 原先写成 ``q - prefac * m``（漏乘 A），
                                # 与下面判据 ``prefac*m*A + l2c*C`` 量纲不一致 →
                                # 搜索用的假设永远错位，四方/六方候选全被淘汰，
                                # 只剩"碰巧"落进立方分支的结果。
                                rem = q - prefac * m * A
                                if rem < 0.0:
                                    # 理论上等于 0 的残差（该峰恰由 (m,l) 解释）会因
                                    # A = 1/a² 的舍入变成极小负数。绝对阈值不可用:
                                    # 候选 a 自身有 ~1e-8 相对误差 → 残差可达 1e-7·q。
                                    # 这里按 q 的比例取 1e-5（比下面判据 tol_rel*2 小
                                    # 三个量级，只吸收舍入，不放过真实失配）。
                                    if rem < -1e-5 * q:
                                        continue
                                    rem = 0.0
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
    """排序: 解释峰数多 → 高对称优先 → FOM 高（解释率 × 体积惩罚）。

    v3.0.1: 增加"同解释峰数下的高对称优先"归并 —— 否则立方样品会被
    体积更小的低对称子胞压掉（Si / NaCl 实测，见 ``_SYM_BAND`` 注释）。
    只对同一 ``n_indexed`` 分组生效，且受 ``_SYM_BAND`` 体积带限制。
    """
    ordered = sorted(cells, key=lambda c: (-c.n_indexed, -c.fom, c.volume))
    out: list[IndexedCell] = []
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j].n_indexed == ordered[i].n_indexed:
            j += 1
        group = ordered[i:j]
        vols = [c.volume for c in group if c.volume > 0]
        if len(group) > 1 and vols:
            vmin = min(vols)
            inband = [c for c in group if 0 < c.volume <= vmin * _SYM_BAND]
            if len(inband) > 1:
                best = min(_SYSTEM_RANK.get(c.system, 9) for c in inband)
                head = [c for c in inband
                        if _SYSTEM_RANK.get(c.system, 9) == best]
                if len(head) < len(group):
                    keep = {id(c) for c in head}
                    out.extend(head)
                    out.extend([c for c in group if id(c) not in keep])
                else:
                    out.extend(group)
            else:
                out.extend(group)
        else:
            out.extend(group)
        i = j
    return out


def index_treor(d_list, treor_exe=None) -> list[IndexedCell]:
    """外部 Treor90 指标化 (接口预留, v0.15 未实现)。"""
    raise NotImplementedError(
        "Treor90 外部指标化未实现; 请用 index_builtin (立方/四方/六方)")


def index_dicvol(d_list, dicvol_exe=None) -> list[IndexedCell]:
    """外部 Dicvol06 指标化 (接口预留, v0.15 未实现)。"""
    raise NotImplementedError(
        "Dicvol06 外部指标化未实现; 请用 index_builtin (立方/四方/六方)")
