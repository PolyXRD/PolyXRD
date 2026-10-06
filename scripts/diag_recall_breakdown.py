"""v2.7.0 诊断: 真值相为什么排不上去? —— 只读, 不改算法。

对 3 个失败试样 (5-2b / 7-1 / 7-2) 输出:
  1. identify(top_n=20, tol=0.2) 的真实排名与 score;
  2. 每个真值相的 FoM 分解 (matched / missed / bad / ic / unexp / s* / scale_rel);
  3. 排在真值相前面的候选的同样分解 —— 对比"谁靠什么赢"。

unexp(未解释实验峰强度比) 由 score 反解:
    score = (bad + 0.30*unexp) * (1 - 0.20*ic)
 => unexp = (score/(1-0.20*ic) - bad) / 0.30
(仅在未触发 B-7 ×2 / 纯金属 ×1.5 时精确; 触发时会标注)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA = Path(r"D:/Project/XRD/test_xrd\txt")

TRUTH = {
    "5-2b": ["α-Quartz", "Cristobalite", "Calcite", "Hematite", "Muscovite"],
    "7-1": ["α-Quartz", "Boehmite", "Anatase", "Goethite", "Kaolinite",
            "Gibbsite", "Hematite"],
    "7-2": ["Quartz", "Albite", "Biotite", "Clinochlore", "Hornblende",
            "Zircon"],
}

_SPEC_W = 0.30
_IC_W = 0.20


def breakdown(phase, peaks, tol=0.2, min_visible_frac=0.1):
    from polyxrd.services.foam import compute_fom
    refs = phase.get_reference_peaks()
    if not refs:
        return None
    obs_tt = [p.two_theta for p in peaks]
    obs_i = [p.intensity for p in peaks]
    r = compute_fom(obs_tt, obs_i, refs, tol=tol,
                    min_visible_frac=min_visible_frac,
                    scale=None, scale_penalty=0.0)
    den = (1.0 - _IC_W * float(r.intensity_score))
    raw = float(r.score) / den if den > 1e-12 else float(r.score)
    unexp = (raw - float(r.position_penalty)) / _SPEC_W
    return {
        "score": float(r.score),
        "matched": int(r.matched),
        "missed": int(r.missed),
        "bad": float(r.position_penalty),
        "ic": float(r.intensity_score),
        "unexp": max(0.0, unexp),
        "s": float(r.scale),
        "scale_rel": float(r.scale_rel),
        "n_ref": len(refs),
    }


def fmt(b):
    if b is None:
        return "  (无参考峰)"
    return (f"  score={b['score']:.4f}  bad={b['bad']:.4f}  "
            f"unexp={b['unexp']:.4f}  ic={b['ic']:.3f}  "
            f"matched={b['matched']}  missed={b['missed']}  "
            f"n_ref={b['n_ref']}  s*={b['s']:.3f}  scale_rel={b['scale_rel']:.3f}")


def main():
    from polyxrd.services.data_loader import DataLoader
    from polyxrd.services.phase_identifier import (
        PhaseIdentifier, default_peak_list,
    )

    pi = PhaseIdentifier()
    for sample, truths in TRUTH.items():
        data = DataLoader().load(DATA / f"{sample}.txt")
        if not getattr(data, "wavelength", 0.0):
            data.wavelength = 1.5406
        gpl = default_peak_list(data)
        print(f"\n{'='*78}\n【{sample}】 检出峰 {len(gpl.peaks)} 条 "
              f"(真值 {len(truths)} 相)\n{'='*78}")

        res = pi.identify_with_element_filter(
            data, peaks=gpl, top_n=20, tolerance=0.2)
        names = [m.phase.name or "" for m in res]
        print("top-20 排名 (identify 真实口径):")
        for i, m in enumerate(res, 1):
            mark = "  <<< 真值" if any(
                t.replace("α-", "").replace(" ", "").lower()
                in (m.phase.name or "").replace(" ", "").lower()
                or (m.phase.name or "").replace(" ", "").lower()
                in t.replace("α-", "").replace(" ", "").lower()
                for t in truths) else ""
            print(f"  {i:2d}. {m.score:8.4f}  {m.phase.name}{mark}")

        print("\n真值相 FoM 分解:")
        for t in truths:
            ph = None
            for p in pi._phase_database:
                if (p.name or "").replace(" ", "").lower() == \
                        t.replace("α-", "").replace(" ", "").lower() or \
                   t.replace("α-", "").replace(" ", "").lower() in \
                        (p.name or "").replace(" ", "").lower():
                    ph = p
                    break
            rank = None
            for i, n in enumerate(names, 1):
                if (n or "").replace(" ", "").lower() == \
                        t.replace("α-", "").replace(" ", "").lower() or \
                   t.replace("α-", "").replace(" ", "").lower() in \
                        (n or "").replace(" ", "").lower():
                    rank = i
                    break
            tag = f"第 {rank} 名" if rank else "**MISS(>20)**"
            print(f"\n  · {t}  →  {tag}")
            if ph is not None:
                print(fmt(breakdown(ph, gpl)))
            else:
                print("  (内置库未找到该相)")

        # 排在末位真值前面的"赢家"分解
        print("\n  —— 前 5 名候选的分解 (对照) ——")
        for i, m in enumerate(res[:5], 1):
            b = breakdown(m.phase, gpl)
            print(f"  [{i}] {m.phase.name}")
            print(fmt(b))


if __name__ == "__main__":
    main()
