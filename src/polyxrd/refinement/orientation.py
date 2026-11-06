"""择优取向：自动惯习面选择（March–Dollase，逐相）。

**为什么需要**：层状矿物（Brucite 001、Muscovite 001、Kaolinite 001）在压片
样品里强择优。v5 没有 PO 入口时，这部分强度失配只能被峰宽/晶胞吸收 —— 4-1 /
5-2 / 5-2b / 5-3 输给 builtin 的差距基本都在这里（基准报告 §十五）。

**做法（不跑整拟合）**：对每一相

1. 先用无 PO 的表做一次带权的线性解（各相标度 + 背景），得到"去掉该相后"
   的残差 ``res_i``；
2. 对候选惯习面 × ``r`` 网格，算该相的单相列 ``col``，用**投影收益**排序::

       score = (w·col · w·res_i)² / (w·col · w·col)

   这等价于"其它相与背景都不动，只把这一列加进线性层"时加权平方和的下降量
   —— 不需要重跑 LM，也不需要重算其它相；
3. 采纳判据是**相对 isotropic 的提升** ``gain = score_best/score₀ − 1``，
   低于 ``min_gain``（默认 0.2）就判定"无择优"，保持 r=1.0 不精修 ——
   过拟合比不修更危险，它会静默改变定量（§十六）。另加一道有界的兜底
   ``delta = (score_best − score₀)/‖w·res_i‖² ≥ 0.005``，防 score₀ 趋零
   时比值虚高。

   三个护栏都是 2026-11-04 实测踩出来的：

   - **残差必须是"去掉该相"的**。``res_i`` 要由**其余相列 + 背景**的 lstsq
     得到，它对其它列正交；这样 ``score`` 才真的是"把这一列加进线性层"的
     加权平方和下降量。若图省事写成 ``y − (y_model − col_i·s_i)``，该相自己
     的贡献会留在残差里 —— 任何列都与它高度对齐、gain 恒 ≈0，反过来（用
     "残差平方和占比"定义 gain 时）则所有相都被判成有择优。
   - **弱相门**：``score₀/‖w·res_i‖² < 0.01`` 直接跳过。弱相 baseline 得分
     接近 0，任何 PO 都能让比值上百倍 —— 5-3 的石英曾这样被误判成
     110/r=0.4，stage 4 追着假择优跑到边界，单次精修从 30 s 涨到 20 min。
   - **阈值取在空档里**：真择优 gain 0.62…16.4，各向同性 0.00…0.03，
     "结构失配冒充择优"（Cristobalite 条目 bug）0.07…0.11 —— 0.11 与 0.62
     之间是空档，取 0.2 两侧都留余量。

     2026-11-06 修正为 **0.15**：S3（CaF2+石英+锐钛矿+刚玉+金红石）的 CaF2
     有真择优 (110)/r=2.2，``gain=0.190`` 却因差 0.01 被丢弃 —— 代价是整条
     精修 Rwp **22.97% → 12.53%**（同一组数据、只差这个判据）。原因是
     ``gain`` 是相对 ``score₀`` 的**比值**：强相（CaF2 ``score₀`` 4.1e4、
     占总残差 33%）只要绝对收益大就足以让 Rwp 掉 10 pp，比值却仍压在 0.2
     以下。0.15 仍在 0.11 与 0.62 的空档内，且合成谱 r=0.65（gain 0.185、
     delta 0.121）自此可被采纳，r=0.80 以下（gain ≤0.037）依旧被拒。

候选方向取**低指数面**（001/100/110/101）：层状矿物是 001、针状是 100/010、
板状是 110。不做全局搜索 —— March–Dollase 只有一个自由度，方向选错时 r 会
跑向边界，得分自然低，低指数候选已覆盖常见惯习。
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from .background import BackgroundParams, background_basis
from .pattern import PhaseSpec, phase_pattern
from .profile import Kalpha2, ProfileParams

#: 默认候选惯习面（低指数）
DEFAULT_CANDIDATES: Tuple[Tuple[int, int, int], ...] = (
    (0, 0, 1), (1, 0, 0), (1, 1, 0), (1, 0, 1),
)

#: 默认 r 网格（March–Dollase 的物理区间大致 0.3…3）
DEFAULT_R_GRID: Tuple[float, ...] = (0.4, 0.6, 0.8, 1.25, 1.6, 2.2)


def _weighted(weights: np.ndarray, v: np.ndarray) -> np.ndarray:
    return np.asarray(v, dtype=float) * np.sqrt(weights)


def select_po_directions(
    two_theta,
    intensity,
    blocks: Sequence,
    profile: ProfileParams,
    *,
    wavelength: float = 1.54056,
    kalph2: Optional[Kalpha2] = None,
    cutoff_fwhm: Optional[float] = 12.0,
    candidates: Sequence[Sequence[int]] = DEFAULT_CANDIDATES,
    r_grid: Sequence[float] = DEFAULT_R_GRID,
    min_gain: float = 0.15,
    min_delta: float = 0.005,
    log=None,
    trace: Optional[list] = None,
) -> Dict[int, dict]:
    """逐相挑惯习面与 ``r`` 起点；返回 ``{相下标: {hkl, r, score, gain}}``。

    只返回**通过门槛**的相（未通过的相不在字典里 = 保持无 PO）。函数会就地
    写入 ``block.po_hkl`` / ``block.po_r`` / 刷新 ``block.table``，调用方直接
    用它建 ``PatternProblem`` 即可。

    :param min_gain: 主判据 = 相对 isotropic（r=1）的得分提升比例，默认 0.15
        （2026-11-06 由 0.2 下调，见模块 docstring 的标定说明）。
        标定依据（7 试样 21 相，基准报告 §十六）：真择优 0.62…16.4，各向同性
        与"结构失配冒充择优"（Cristobalite 条目）0.00…0.11 —— 中间是空档。
    :param min_delta: 兜底判据 = 纹理额外解释的剩余失配比例，默认 0.005。
        防"score₀ 趋零 → 比值虚高"，也顺手排掉几乎无信号的相。
    :param trace: 诊断用。传入 list 时追加每相的评分明细（score0 / best /
        ssr / gain / delta），阈值标定与基准脚本据此判断，生产路径不传。
    """
    tt = np.asarray(two_theta, dtype=float).reshape(-1)
    y = np.asarray(intensity, dtype=float).reshape(-1)
    if tt.size == 0 or y.size != tt.size or not blocks:
        return {}
    w = 1.0 / np.maximum(y, 1.0)
    sw = np.sqrt(w)
    tmin, tmax = float(tt[0]), float(tt[-1])
    span = max(tmax - tmin, 1.0)
    bg = BackgroundParams("tent", max(4, int(round(span / 12.0))))
    try:
        bg_basis = background_basis(tt, bg)
    except Exception:  # noqa: BLE001 - 背景基构造失败就不带背景做排序
        bg_basis = np.zeros((tt.size, 1))

    # ① 无 PO 的线性解（各相标度 + 背景）
    cols = []
    for b in blocks:
        b.po_hkl = None
        b.po_r = 1.0
        b.table = None
        tab = b.ensure_table((tmin, tmax), (wavelength,))
        cols.append(phase_pattern(
            tt, PhaseSpec(table=tab, size_nm=b.size_nm, strain=b.strain),
            profile, wavelength=wavelength, kalph2=kalph2,
            cutoff_fwhm=cutoff_fwhm))
    picked: Dict[int, dict] = {}
    for i, b in enumerate(blocks):
        # 残差必须是"**去掉该相**后的模型残差"：它对其它的相列与背景正交，
        # 于是 score 才是"把这一列加进线性层"的真实平方和下降量。
        # 反例（2026-11-04 踩过）：用 y − (y_model − col_i·s_i) 会把该相自己
        # 的贡献留在残差里 —— 任何列都与它高度对齐、gain 恒 ≈1，结果所有相
        # 都被判成有择优（3-1 的 ZnO r=0.937 却报 gain 0.79）。
        keep = [j for j in range(len(cols)) if j != i]
        other = np.column_stack([cols[j] for j in keep] + [bg_basis])
        try:
            sol_i, *_ = np.linalg.lstsq(other * sw[:, None], y * sw, rcond=None)
        except Exception:  # noqa: BLE001
            continue
        res_i = y - other @ sol_i
        wres = _weighted(w, res_i)

        def _score(col: np.ndarray) -> float:
            wc = _weighted(w, col)
            den = float(wc @ wc)
            if den <= 1e-30:
                return 0.0
            return float((wc @ wres) ** 2 / den)

        score0 = _score(cols[i])
        ssr = float(wres @ wres)
        # 弱相/无信号门：该相在"去掉自己"的残差里连 1% 都解释不了，
        # 就没有资格判择优（分母小会让相对提升虚高，5-3 的石英曾爆到 32 倍）
        if ssr <= 1e-30 or score0 / ssr < 0.01:
            b.po_hkl = None
            b.po_r = 1.0
            b.table = None
            if trace is not None:
                trace.append({"index": i, "label": b.label, "score0": score0,
                              "best": score0, "ssr": ssr, "gain": 0.0,
                              "delta": 0.0, "hkl": None, "r": 1.0,
                              "skipped": "weak"})
            if log is not None:
                log(f"[v5] po {b.label}: 信号不足，不判择优")
            continue
        best = {"score": score0, "hkl": None, "r": 1.0}
        for hkl in candidates:
            hkl = tuple(int(v) for v in hkl)
            b.po_hkl = hkl
            b.table = None
            try:
                tab = b.ensure_table((tmin, tmax), (wavelength,))
            except Exception:  # noqa: BLE001 - 单方向构造失败跳过
                continue
            for r in r_grid:
                col = phase_pattern(
                    tt, PhaseSpec(table=tab, size_nm=b.size_nm, strain=b.strain,
                                  po_r=float(r)),
                    profile, wavelength=wavelength, kalph2=kalph2,
                    cutoff_fwhm=cutoff_fwhm)
                sc = _score(col)
                if sc > best["score"]:
                    best = {"score": sc, "hkl": hkl, "r": float(r)}
        # gain = 相对"无 PO"的平方和下降提升（isotropic 为 0）
        gain = best["score"] / score0 - 1.0 if score0 > 1e-30 else 0.0
        # delta = 纹理额外解释的**剩余失配比例**（有界 0…1，等价于 F 检验的
        # 分子归一化）。它单独用会系统性压低弱相（同样的择优，弱相贡献的
        # 平方和本来就少），所以只当兜底。
        delta = (best["score"] - score0) / ssr
        if trace is not None:
            trace.append({"index": i, "label": b.label, "score0": score0,
                          "best": best["score"], "ssr": ssr, "gain": gain,
                          "delta": delta, "hkl": best["hkl"], "r": best["r"]})
        if best["hkl"] is None or gain < float(min_gain) \
                or delta < float(min_delta):
            b.po_hkl = None
            b.po_r = 1.0
            b.table = None
            if log is not None:
                log(f"[v5] po {b.label}: 无显著择优（gain={gain:.3f}）")
            continue
        b.po_hkl = best["hkl"]
        b.po_r = float(best["r"])
        b.table = None
        picked[b.index] = {"hkl": best["hkl"], "r": float(best["r"]),
                           "gain": round(float(gain), 3)}
        if log is not None:
            log(f"[v5] po {b.label}: hkl={best['hkl']} r={best['r']:.2f} "
                f"gain={gain:.3f}")
    return picked
