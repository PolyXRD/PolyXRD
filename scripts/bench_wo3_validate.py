# -*- coding: utf-8 -*-
"""WO3 谱线验证（P2-4 / P2-5）：判别峰、单相与两相定量、对照臂。

用法::

    python scripts/bench_wo3_validate.py                 # 跑全部
    python scripts/bench_wo3_validate.py --only peaks    # 只跑判别峰
    python scripts/bench_wo3_validate.py --only 2-1      # 只跑单相/两相
    python scripts/bench_wo3_validate.py --data DIR      # 换数据目录

数据: ``D:/Project/XRD/test_xrd/WO3``（Rigaku ASCII dump，Cu Kα，20–90°）。

结论口径（2026-11-05，详见 ``docs/基准报告-精修-v5.0.0.md`` 与待办 P2-5）：

* 主相 = WO3。**反向一致性**：观测峰表（22~23 个）被 α/γ-WO3 参考线
  ``21/21`` 全解释；正向（参考线→观测峰）只有 10/20，因为 28.61/28.91、
  33.25/33.55、41.42/41.87、49.89~50.71 是密集双线，观测上并成一个峰 ——
  所以"命中率"必须按反向算。
* **两相 Rietveld 给出的份额不能当作该相存在的证据** —— 大胞相自带独立峰宽
  参数，能把样品展宽造成的失配摊平（W20O58 分到 15.6 %，而其最强判别峰
  24.66°/I=0.67 在两条谱上都是"陡降尾巴 + 噪声"，不是峰；对照组 MoO3 1.3 %）。
* 因此判亚氧化物必须看**判别性峰是否真的存在**，见 ``--only peaks``。
  负对照：α-WO3 自己的 4 个判别峰同样全为"无"（数据是多型 γ），说明该判据
  不是"一律判无"。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

DEFAULT_DATA = Path(r"D:\Project\XRD\test_xrd\WO3")
LAM = 1.5406

#: 主相两种多型（同一化合物，故不可互相排除）
WO3_POLY = {2106382: "WO3 γ (P2₁/n)", 2106293: "WO3 α (P-1)"}
#: 亚氧化物（P2-5 的目标）
SUB_OXIDES = {1538317: "W20O58 (O2.9 W)", 1528166: "W18O49",
              1538315: "W18O49 (O2.72 W)", 1527783: "W5O14"}
#: 对照臂：谱里不该出现的相，用来测"拟合自由度"能骗到多少份额
CONTROLS = {1011043: "MoO3 (对照)", 1548686: "WO2 (对照)",
            2106293: "α-WO3 (同相异型对照)"}


def _load(path: Path):
    from polyxrd.services.data_loader import DataLoader

    data = DataLoader().load(path)
    if not getattr(data, "wavelength", 0.0):
        data.wavelength = LAM
    return data


def _ref_peaks(db, eid: int, lo=20.0, hi=90.0):
    """参考峰 (2θ, 相对强度)。库里存 d + 强度 → Bragg 换算。

    ⚠ ``PolyDatabase.peaks_of_rows`` 返回的是 **d 值**不是 2θ，第一版就栽在
    这里（直接当 2θ 用会得到一片 <20° 的垃圾）。
    """
    row = db.row_of_eid(int(eid))
    if row is None or row < 0:
        return np.zeros(0), np.zeros(0)
    d, inten = db.peaks_of_rows(np.array([row], dtype=np.int64))
    d = np.asarray(d, float).ravel()
    inten = np.asarray(inten, float).ravel()
    ok = (d > 0) & (inten > 0)
    d, inten = d[ok], inten[ok]
    if not len(d):
        return np.zeros(0), np.zeros(0)
    tt = np.degrees(2.0 * np.arcsin(np.clip(LAM / (2.0 * d), -1.0, 1.0)))
    m = (tt >= lo) & (tt <= hi)
    order = np.argsort(tt[m])
    return tt[m][order], inten[m][order]


def _noise_sigma(y):
    """由二阶差分估噪声 sigma（稳健，不受局部斜率影响）。

    平滑曲线上 ``y[i+1]-2y[i]+y[i-1] ≈ 0``，只剩噪声，``var(d2)=6σ²``。
    """
    d2 = y[1:-1] - 2.0 * y[:-2] + y[2:] if y.size > 4 else np.zeros(0)
    if not d2.size:
        return 0.0
    return float(1.4826 * np.median(np.abs(d2)) / np.sqrt(6.0))


def _net_at(t, y, t0, valley=0.40):
    """t0 处相对局部谷底的净高度（仅用于**报告**该处到底有多少强度）。

    不用它做判据：``±0.30°`` 的线性肩基点在致密谱里会落到邻峰顶上
    （α-WO3 的 34.47° 因此算出 lin=−757），判据统一交给 prominence。
    """
    step = float(np.median(np.diff(t))) if t.size > 1 else 0.02
    k2 = max(1, int(round(valley / step)))
    i = int(np.argmin(np.abs(t - t0)))
    j_lo, j_hi = max(0, i - k2), min(y.size, i + k2 + 1)
    return float(y[i] - np.min(y[j_lo:j_hi]))


def _obs_peaks(tt, ii, lo=20.0, hi=90.0, rel=0.010, snr=5.0):
    """观测峰列表 ``[(2θ, 相对突出度)]``，判据 = **prominence**。

    ⚠ 第一版直接判「绝对局部极大」，在陡降段被噪声骗了：data1 的
    ``24.64:978 > 24.66:896 > 24.68:812`` 被判成"24.66° 有峰"，可这一段是
    从 24.34°(4744) 单调衰减到 25.0°(~250) 的尾巴。

    ⚠ 第二版改「相对两侧肩点 ±0.30° 线性基线的净高」也不行：这套谱峰间距
    只有 0.3~0.5°，肩点经常正好落在邻峰顶上（α-WO3 的 34.47° 由此被判成
    lin=−757），结果全谱"无峰"。

    现用 scipy 的 prominence（地形突出度）：单调坡上的噪声包没有突出度
    （左肩无下坡 ⇒ 突出度 0），而坐在大峰肩上的真峰有"翻过山坳"的突出度。
    两者都能分开，且不需要挑窗口。
    """
    from scipy.signal import find_peaks

    m = (tt >= lo) & (tt <= hi)
    t, y = tt[m], ii[m]
    if y.size < 9:
        return []
    y = y - float(np.percentile(y, 1))
    ys = np.convolve(y, np.array([0.25, 0.5, 0.25]), mode="same")
    ys[:2] = y[:2]
    ys[-2:] = y[-2:]
    ymax = float(ys.max())
    if ymax <= 0:
        return []
    sig = _noise_sigma(y)
    prom = max(float(snr) * sig, float(rel) * ymax)
    idx, props = find_peaks(ys, prominence=prom)
    return [(float(t[i]), float(p) / ymax)
            for i, p in zip(idx, props["prominences"])]


def _discriminating(db, eid: int, main_eids, rel_min=0.05, gap=0.30):
    """该相 I≥rel_min 且与主相**任一**参考线相距 >gap 的峰（即"只有它有"）。"""
    tt, ii = _ref_peaks(db, eid)
    if not len(tt):
        return []
    rel = ii / ii.max()
    main = np.concatenate([_ref_peaks(db, e)[0] for e in main_eids] or [np.zeros(0)])
    out = []
    for t, r in zip(tt, rel):
        if r < rel_min:
            continue
        if main.size and np.min(np.abs(main - t)) <= gap:
            continue
        out.append((float(t), float(r)))
    return sorted(out, key=lambda x: -x[1])


def _explain_rate(obs, ref_tt, prom_min=0.02, tol=0.30):
    """**反向**一致性：观测峰里有多少能被参考线解释。

    ⚠ 不能用正向（参考线→观测峰）：γ-WO3 在 28.61/28.91、33.25/33.55、
    41.42/41.87、49.89~50.71 都是密集双线，观测上并成一个峰，正向查只有
    10/20。反向查"每个观测峰都被某条参考线解释"才是"主相 = WO3"的正确检验。
    """
    strong = [(t, p) for t, p in obs if p >= prom_min]
    if not strong or not len(ref_tt):
        return 0, len(strong)
    ref = np.asarray(ref_tt)
    hit = sum(1 for t, _ in strong if np.min(np.abs(ref - t)) <= tol)
    return hit, len(strong)


def cmd_peaks(db, spectra):
    print("── 判别性峰（I≥5 %，与 α/γ-WO3 任一线相距 >0.30°）──")
    print("   观测峰表判据：scipy prominence > max(5σ, 1%Imax)；"
          "'有' = ±0.20° 内存在观测峰")
    g_tt, g_ii = _ref_peaks(db, 2106382)
    a_tt, _ = _ref_peaks(db, 2106293)
    main_ref = np.concatenate([g_tt, a_tt])
    ops, raws = {}, {}
    for fn, (tt, ii) in spectra.items():
        ops[fn] = _obs_peaks(tt, ii)
        m = (tt >= 20.0) & (tt <= 90.0)
        raws[fn] = (tt[m], ii[m] - float(np.percentile(ii[m], 1)))
        h, n = _explain_rate(ops[fn], main_ref)
        near = [t for t, _ in ops[fn] if abs(t - 24.66) <= 0.20]
        print(f"   自检 {fn}: 检出 {len(ops[fn])} 峰；观测峰被 α/γ-WO3 解释 "
              f"{h}/{n}；24.66°±0.20 {'有' if near else '无'}（应为无）")
    # 检测限：峰表门槛折算成"该相至少多少重量分数才可能被看见"（粗估，等质量吸收）
    y0 = raws[list(raws)[0]][1]
    sig0 = _noise_sigma(y0)
    floor_rel = max(5.0 * sig0, 0.010 * float(y0.max())) / float(y0.max())
    print(f"   检测限：门槛 max(5σ,1%Imax) = {floor_rel * 100:.1f}% Imax"
          f"（σ={sig0:.0f}，Imax={y0.max():.0f}）⇒ I/Imax=0.67 的 24.66° 线"
          f"需 ≥{floor_rel / 0.67 * 100:.0f} % 份额才可分辨")
    print(f"   负对照：α-WO3 自身 4 个判别峰应全为'无'（数据是多型 γ）")
    for eid, name in {**SUB_OXIDES, **{2106293: "α-WO3"}}.items():
        # 判别性要同时对 **α 与 γ** 两种多型判距：只要贴近任一多型的线，
        # 就不能算"只有这个相才有"（标题口径与代码必须一致）。
        # 例外：α 自己是对照组，只排除 γ，否则自己判自己必然 0 个。
        main = [2106382] if eid == 2106293 else list(WO3_POLY)
        disc = _discriminating(db, eid, main)
        print(f"\n{name}: 判别峰 {len(disc)} 个")
        for t, r in disc[:5]:
            cells = []
            for fn, (tt, ii) in spectra.items():
                o = np.asarray([a for a, _ in ops[fn]]) if ops[fn] else np.zeros(0)
                d = float(np.min(np.abs(o - t))) if o.size else 99.0
                if d <= 0.20:
                    j = int(np.argmin(np.abs(o - t)))
                    cells.append(f"{fn.replace('WO raw ', '')}=有(突出度{ops[fn][j][1]:4.2f})")
                    continue
                j = int(np.argmin(np.abs(o - t))) if o.size else -1
                who = ""
                if j >= 0:
                    near_ref = float(np.min(np.abs(main_ref - o[j]))) if main_ref.size else 99.0
                    who = (f"，该峰 {o[j]:.2f}°"
                           + ("=γ/α-WO3" if near_ref <= 0.30 else " 非主相"))
                net = _net_at(*raws[fn], t)
                cells.append(f"{fn.replace('WO raw ', '')}=无(最近Δ{d:4.2f}°{who}，"
                             f"本处净高{net:5.0f})")
            print(f"   {t:7.2f}°  I/Imax={r:4.2f}   " + "  ".join(cells))


def cmd_single(db, spectra):
    from bench_engines_v500 import build_phases
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    print("── 单相 Rietveld（v5 引擎 fast 档）──")
    for fn, data in spectra.items():
        for eid, name in WO3_POLY.items():
            phases, miss = build_phases(db, data, [(eid, name)])
            if miss:
                print(f"  {fn}: {miss}")
                continue
            res = RietveldRefiner().refine(data, phases, engine="refinement",
                                           perf_profile="fast", max_cycles=12)
            print(f"  {fn:22} {name:16} Rwp={res.wR:6.2f} %  GOF={res.GOF or 0:5.2f}")


def cmd_two_phase(db, spectra, extra=None):
    from bench_engines_v500 import build_phases
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    arms = {2106382: "WO3 γ"}
    arms.update(extra or SUB_OXIDES)
    print("── 两相 Rietveld：加入相的份额与 Rwp ──")
    for fn, data in spectra.items():
        phases, _ = build_phases(db, data, [(2106382, "WO3 γ")])
        res = RietveldRefiner().refine(data, phases, engine="refinement",
                                       perf_profile="fast", max_cycles=12)
        print(f"  {fn:22} 单相 WO3            Rwp={res.wR:6.2f} %")
        for eid, name in arms.items():
            if eid == 2106382:
                continue
            phases, miss = build_phases(db, data, [(2106382, "WO3 γ"), (eid, name)])
            if miss:
                print(f"  {fn:22} + {name:18} 缺: {miss}")
                continue
            res = RietveldRefiner().refine(data, phases, engine="refinement",
                                           perf_profile="fast", max_cycles=12)
            wt = [float(p.weight_fraction) for p in res.phases]
            print(f"  {fn:22} + {name:18} 份额={wt[-1]:6.2f} %  "
                  f"Rwp={res.wR:6.2f} %")


def cmd_guard(db, data):
    """P2-10 的**端到端**验收：判别峰守卫能不能把 W20O58 的假份额拦下来。

    判据落在 ``refinement.report.build_report`` → ``PHASE_UNSUPPORTED``，
    经服务层以 ``v5_findings`` 返回。期望：
    单相 WO3 不报；+W20O58 报；+MoO3（对照，库里有但谱里没有）也报。
    """
    from bench_engines_v500 import build_phases
    from polyxrd.services.rietveld_refiner import RietveldRefiner

    arms = [(None, None), (1538317, "W20O58"), (1011043, "MoO3 (对照)")]
    print("── 判别峰守卫（P2-10）：份额有没有谱线支撑 ──")
    for fn, d in data.items():
        for eid, name in arms:
            want = [(2106382, "WO3 γ")]
            if eid is not None:
                want.append((eid, name))
            phases, miss = build_phases(db, d, want)
            if miss:
                print(f"  {fn:22} {name:18} 缺: {miss}")
                continue
            res = RietveldRefiner().refine(d, phases, engine="refinement",
                                           perf_profile="fast", max_cycles=12)
            wt = [float(p.weight_fraction) for p in res.phases]
            finds = (res.fit_params or {}).get("v5_findings") or []
            hit = [f for f in finds
                   if f.get("code") in ("PHASE_UNSUPPORTED",
                                        "PHASE_FRACTION_UNVERIFIABLE")]
            tag = "单相 WO3" if eid is None else f"+{name}"
            verdict = "报" if hit else "不报"
            detail = ""
            if hit:
                ev = hit[0].get("evidence") or {}
                frac = 100 * float(ev.get("fraction", 0))
                if hit[0].get("code") == "PHASE_UNSUPPORTED":
                    detail = (f"  ← {ev.get('phase')} {frac:.2f} wt%，"
                              f"最强线 {float(ev.get('strongest_2theta', 0)):.2f}° "
                              f"不在谱上（无支撑）")
                else:
                    detail = (f"  ← {ev.get('phase')} {frac:.2f} wt%，"
                              f"{float(ev.get('n_strong', 0)):.0f} 条强线全部"
                              f"与主相重合（最小间距 "
                              f"{float(ev.get('min_gap', 0)):.2f}°，份额不可独立验证）")
            print(f"  {fn:22} {tag:18} 份额={wt[-1]:6.2f} %  Rwp={res.wR:6.2f} %"
                  f"  守卫={verdict}{detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--only", default="all",
                    choices=["all", "peaks", "single", "two", "control", "guard"])
    args = ap.parse_args()

    from polyxrd.services.polydb import PolyDatabase

    db = PolyDatabase()
    d = Path(args.data)
    files = sorted(p for p in d.glob("*.txt"))
    if not files:
        print(f"数据目录无谱文件: {d}")
        return 1
    data = {p.stem: _load(p) for p in files}          # 每个文件只读一次
    spectra = {k: (np.asarray(v.two_theta, float), np.asarray(v.intensity, float))
               for k, v in data.items()}
    print(f"数据: {d}  谱: {list(spectra)}\n")

    if args.only in ("all", "peaks"):
        cmd_peaks(db, spectra)
    if args.only in ("all", "single"):
        cmd_single(db, data)
    if args.only in ("all", "two"):
        cmd_two_phase(db, data)
    if args.only in ("all", "control"):
        print("\n── 对照臂：不该出现的相能骗到多少份额 ──")
        cmd_two_phase(db, data, extra=CONTROLS)
    if args.only in ("all", "guard"):
        cmd_guard(db, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
