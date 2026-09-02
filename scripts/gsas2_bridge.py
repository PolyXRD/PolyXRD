"""
GSAS-II 子进程精修桥 v2 (P0 集成)
=================================
由 GSAS-II 自带 Python 解释器运行, 配合 PolyXRD 的 RietveldRefiner
(engine="gsas2") 使用。PolyXRD 的 venv 与 GSAS-II 自带 Python 是两套
独立环境 (二进制编译产物按 Python/numpy 版本匹配), 因此采用 JSON 子进程
通信而非 in-process import。

用法:
    <gsas2-python> gsas2_bridge.py <request.json> <output.json>

request.json:
{
  "two_theta": [..], "intensity": [..], "wavelength": 1.5406,
  "phases": [
    {"name": "Zincite", "spacegroup": "P 63 m c",
     "lattice": {"a":..,"b":..,"c":..,"alpha":..,"beta":..,"gamma":..},
     "cif_path": "..."}    # cif_path 存在时用 CIF 完整结构 (Rietveld)
  ],
  "refine": "lattice",      # 目前仅支持晶胞/LeBail 模式
  "max_cycles": 5
}

output.json:
{"ok": true, "wR": .., "GOF": .., "n_cycles": ..,
 "phases": [{"name": .., "lattice": {"a":.., ...}}]}
{"ok": false, "error": "..."}

v2 相对 v1 的健壮性改动 (离线探针 _g2probe5/6/7 实证):
  1. 仪器峰形匹配: 从数据最强峰估计 FWHM -> 换算 GW (centideg^2) 写入
     .prm, 避免模板宽峰形掩盖晶胞梯度 / 窄峰形导致 LM 一步过冲
     (Invalid metric tensor)。
  2. 峰位定种: 立方晶系 (单相) 时, 检测数据峰位 -> 按空间群消光规则
     (GSASIIspc.GenHKLf) 生成允许反射序列 -> 序列对齐 + 中位数自洽
     反推晶胞, 使远离真值的用户晶胞也能被拉回收敛盆地。
  3. 多起点安全评分: 对晶胞尺度 0.96..1.04 网格 (晶胞冻结, 只精修
     背景+LeBail强度, 无发散风险) 逐个评分, 选 wR 最小种子再精修;
     避免从盆地外起步时 LM 原地不动 (zero gradient plateau)。
  4. 精修轮次: Cell+背景 4 段 x 每段 10 cycle (probe7 验证 40 轮收敛),
     其后叠加 U/V/W 峰形精修 (非致命, 失败不影响晶胞结果)。

注意: Le Bail 精修中不可同时精修 Sample Scale 与相 Scale/HAP Scale
(100% 相关 -> SVD 丢弃, wR 卡死), 桥内一律不精修 Scale。
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import traceback

import numpy as np


# ----------------------------------------------------------------------
# 数据特征估计
# ----------------------------------------------------------------------

def _estimate_gw(tt: np.ndarray, intens: np.ndarray) -> float:
    """从最强峰估计仪器高斯宽度 GW (centideg^2)。

    GSAS-II CW profile: sig = GU*tan^2 + GV*tan + GW (centideg^2),
    sigma_deg = sqrt(sig)/100 (GSASIIpwd.getWidthsCW)。
    数据峰近似高斯时 sigma_deg ~ FWHM/2.3548 => GW = (FWHM/2.3548*100)^2。
    失败 (无强峰/数据退化) 返回默认 5.0 (sigma ~ 0.022 deg)。
    """
    n = len(tt)
    if n < 20:
        return 5.0
    try:
        bg = float(np.median(np.concatenate([intens[: max(5, n // 30)],
                                             intens[-max(5, n // 30):]])))
    except Exception:
        bg = 0.0
    imax = int(np.argmax(intens))
    ymax = float(intens[imax])
    if ymax - bg < 1e-9:
        return 5.0
    half = bg + (ymax - bg) * 0.5
    # 由峰顶向两侧找半高交叉点 (线性插值亚点精度)
    def cross(side: int) -> float:
        i = imax
        while 0 <= i < n and ((side < 0 and intens[i] >= half) or
                              (side > 0 and intens[i] >= half)):
            i += side
        if not (0 <= i < n) or not (0 <= i - side < n):
            return None
        a, b = i - side, i
        ya, yb = float(intens[a]), float(intens[b])
        if abs(yb - ya) < 1e-12:
            return float(tt[a])
        return float(tt[a]) + (half - ya) / (yb - ya) * (tt[b] - tt[a])

    xl, xr = cross(-1), cross(+1)
    if xl is None or xr is None or xr - xl <= 0:
        return 5.0
    fwhm = xr - xl
    # 峰过窄 (< 2 个数据点) 说明不是可解峰
    if fwhm < 2.0 * (tt[1] - tt[0]):
        return 5.0
    gw = ((fwhm / 2.3548) * 100.0) ** 2
    return float(min(max(gw, 1.0), 2500.0))


def _find_peaks(tt: np.ndarray, intens: np.ndarray,
                bg: float, rel: float = 0.08) -> list[float]:
    """返回按 2θ 升序排列的强峰位置 (局部极大 + 阈值过滤 + 去簇)。"""
    ymax = float(np.max(intens))
    thr = bg + rel * (ymax - bg)
    # 局部极大 (相邻 2 点比较), 消除平台
    c = intens[1:-1]
    lm = np.where((c >= intens[:-2]) & (c >= intens[2:]) & (c >= thr))[0] + 1
    if len(lm) == 0:
        return []
    # 去簇: 0.3° 内只保留最强
    kept = []
    cluster = [lm[0]]
    for i in lm[1:]:
        if tt[i] - tt[cluster[0]] < 0.3:
            cluster.append(i)
        else:
            kept.append(cluster[int(np.argmax(intens[cluster]))])
            cluster = [i]
    kept.append(cluster[int(np.argmax(intens[cluster]))])
    kept.sort()
    return [float(tt[i]) for i in kept]


def _cubic_seed_a(peaks: list[float], sg_symbol: str, lam: float,
                  a_ref: float) -> float | None:
    """立方晶系峰位定种: 由观测峰 2θ 与空间群允许反射序列反推 a。

    仅当满足全部条件时返回可信种子, 否则返回 None (走尺度网格):
      * 空间群可解析且中心为 P/I/F
      * 观测峰 >= 4
      * 序列对齐后各峰反推 a 的中位绝对偏差 < 0.6% (自洽)
    """
    if len(peaks) < 4 or not sg_symbol:
        return None
    centering = sg_symbol.strip().split()[0][:1].upper()
    if centering not in ("P", "I", "F"):
        return None
    try:
        from GSASII import GSASIIspc as G2spc
        err, sg = G2spc.SpcGroup(sg_symbol)
        if err:
            return None

        def allowed(hkl):
            iabsnt, mulp, _u, _p = G2spc.GenHKLf(hkl, sg)
            return (not iabsnt) and mulp > 0

        seen_q: set[int] = set()
        qlist: list[tuple[int, list[int]]] = []
        # 立方 q = h^2+k^2+l^2 唯一决定 2θ 次序; h,k,l<=14 覆盖到 a 缩一半仍够
        triples = sorted(
            ((h, k, l) for h in range(15) for k in range(15) for l in range(15)
             if (h or k or l) and h >= k >= l),
            key=lambda t: (t[0] * t[0] + t[1] * t[1] + t[2] * t[2], t),
        )
        for h, k, l in triples:
            q = h * h + k * k + l * l
            if q in seen_q or not allowed([h, k, l]):
                continue
            seen_q.add(q)
            qlist.append((q, [h, k, l]))
            if len(qlist) >= 40:
                break
        if len(qlist) < 4:
            return None
        qs = np.array([q for q, _ in qlist], dtype=float)
    except Exception:
        return None

    th = np.radians(np.asarray(peaks, dtype=float) / 2.0)
    sint = np.sin(th)
    if np.any(sint <= 0) or np.any(sint > 1.0):
        return None
    # 序列对齐: 观测峰 i 对应允许反射 i+k (k 容差吸收弱峰缺失)
    best = (None, float("inf"))
    n_obs = len(peaks)
    for k in range(-4, 5):
        lo, hi = max(0, -k), min(n_obs, len(qlist) - k)
        if hi - lo < 4:
            continue
        a_i = lam * np.sqrt(qs[lo + k:hi + k]) / (2.0 * sint[lo:hi])
        med = float(np.median(a_i))
        if med <= 0:
            continue
        mad = float(np.median(np.abs(a_i - med)))
        if mad / med < best[1]:
            best = (med, mad / med)
    if best[0] is None or best[1] > 0.006:
        return None
    return best[0]


# ----------------------------------------------------------------------
# 工程构建
# ----------------------------------------------------------------------

def _make_inst_prm_lines(lam: float, gw: float) -> list[str]:
    """CW PseudoVoigt 仪器参数: U=V=0, W=gw (由数据峰形估计)。"""
    return [
        "            123456789012345678901234567890123456789012345678901234567890",
        "INS   BANK      1",
        "INS   HTYPE   PXCR",
        "INS  1 IRAD     3",
        f"INS  1 ICONS  {lam:9.6f} {lam:9.6f}       0.0         0"
        "       0.7    0       0.5",
        "INS  1I HEAD  DUMMY INCIDENT SPECTRUM FOR X-RAY DIFFRACTOMETER",
        "INS  1I ITYP    0    0.0000  180.0000         1",
        "INS  1PRCF1     3    8      0.01",
        f"INS  1PRCF11    0.000000E+00   0.000000E+00   {gw:12.6E}   0.000000E+00",
        "INS  1PRCF12   0.000000E+00   0.000000E+00   0.000000E+00   0.000000E+00",
    ]


def _build_project(req: dict, xy_path: str, iparm_path: str,
                   iparm_lines: list[str], scale: float,
                   tag: str) -> tuple[str, object]:
    """构建临时 GSAS 工程, 返回 (gpx_path, gpx)。

    所有相 (无 CIF 的) 晶胞长度乘以 scale; CIF 相保持原样。
    """
    tmpdir = tempfile.mkdtemp(prefix=f"polyxrd_g2_{tag}_")
    gpx_path = os.path.join(tmpdir, "proj.gpx")
    if not os.path.exists(iparm_path):
        with open(iparm_path, "w", encoding="ascii") as f:
            f.write("\n".join(iparm_lines) + "\n")

    from GSASII import GSASIIscriptable as G2sc
    gpx = G2sc.G2Project(newgpx=gpx_path)
    hist = gpx.add_powder_histogram(xy_path, iparams=iparm_path)
    for p in req.get("phases", []):
        name = p.get("name") or "phase"
        cif = p.get("cif_path")
        if cif and os.path.exists(cif):
            gpx.add_phase(cif, phasename=name, histograms=[hist])
            continue
        lat = p.get("lattice") or {}
        a = float(lat.get("a", 5.0)) * scale
        b = float(lat.get("b", 5.0)) * scale
        c = float(lat.get("c", 5.0)) * scale
        phase = gpx.add_phase(
            phasename=name,
            spacegroup=p.get("spacegroup") or "P 1",
            cell=[a, b, c,
                  float(lat.get("alpha", 90.0)),
                  float(lat.get("beta", 90.0)),
                  float(lat.get("gamma", 90.0))],
            histograms=[hist],
        )
        del phase
    gpx.set_refinement({"set": {"LeBail": True}}, histogram="all", phase="all")
    ctrl = gpx.data["Controls"]["data"]
    ctrl["newLeBail"] = True
    ctrl["max cyc"] = 1
    ctrl["shift factor"] = 0.5
    gpx.save()
    return gpx_path, gpx


_CELL_BKG = {"LeBail": True, "Cell": True,
             "Background": {"no. coeffs": 6, "refine": True}}


def _score_seed(req, xy_path, iparm_path, iparm_lines, scale):
    """种子评分: DoLeBail + 1 轮 Cell+背景 LSQ (max cyc=1)。

    Cell 精修在单轮内实际几乎不移动晶胞 (探针实证 <=1e-5 A), 因此无
    发散风险, 而 wR 能区分收敛盆地 (探针实证: 盆地内 wR 明显更低)。
    """
    from GSASII import GSASIIstrMain as G2strMain
    gpx_path, gpx = _build_project(req, xy_path, iparm_path, iparm_lines,
                                   scale, "seed")
    ok, _ = G2strMain.DoLeBail(gpx_path, dlg=None, cycles=1)
    if not ok:
        return None
    try:
        gpx.reload()
        gpx.do_refinements([{"set": dict(_CELL_BKG)}])
        gpx.reload()
        return gpx.histogram(0).get_wR()
    except Exception:
        return None


def _final_refine(req, xy_path, iparm_path, iparm_lines, scale):
    """从选定种子做最终精修 (Cell+背景 4x10 轮 + 非致命 U/V/W), 返回结果 dict。"""
    from GSASII import GSASIIstrMain as G2strMain
    from GSASII import GSASIIscriptable as G2sc

    gpx_path, gpx = _build_project(req, xy_path, iparm_path, iparm_lines,
                                   scale, "final")
    ok, _ = G2strMain.DoLeBail(gpx_path, dlg=None, cycles=1)
    if not ok:
        raise RuntimeError("Le Bail 强度提取失败")
    gpx.reload()
    ctrl = gpx.data["Controls"]["data"]
    ctrl["max cyc"] = 10
    ctrl["shift factor"] = 0.5
    gpx.save()

    rounds = 0
    gpx.do_refinements([{"set": dict(_CELL_BKG)} for _ in range(4)])
    rounds += 4
    # 附加 U/V/W 峰形精修: 非致命, 失败不影响晶胞结果
    try:
        gpx.reload()
        ctrl = gpx.data["Controls"]["data"]
        ctrl["max cyc"] = 5
        gpx.save()
        gpx.do_refinements([{"set": dict(_CELL_BKG, **{
            "Instrument Parameters": ["U", "V", "W"]})} for _ in range(2)])
        rounds += 2
    except Exception:
        pass
    gpx.reload()

    out_phases = []
    for p in req.get("phases", []):
        name = p.get("name") or "phase"
        try:
            cell = gpx.phase(name).get_cell() or {}
            lat_out = {k: cell.get(k) for k in
                       ("length_a", "length_b", "length_c",
                        "angle_alpha", "angle_beta", "angle_gamma")}
            if lat_out.get("length_a") is None:
                lat_out = None
            else:
                lat_out = {
                    "a": lat_out["length_a"], "b": lat_out["length_b"],
                    "c": lat_out["length_c"], "alpha": lat_out["angle_alpha"],
                    "beta": lat_out["angle_beta"], "gamma": lat_out["angle_gamma"],
                }
        except Exception:
            lat_out = None
        out_phases.append({"name": name, "lattice": lat_out})

    wR = None
    try:
        wR = gpx.histogram(0).get_wR()
    except Exception:
        wR = None
    return {"phases": out_phases, "wR": wR, "rounds": rounds, "gpx": gpx_path}


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def _write(out_path: str, data: dict) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: gsas2_bridge.py <request.json> <output.json>", file=sys.stderr)
        return 2
    req_path, out_path = sys.argv[1], sys.argv[2]
    try:
        with open(req_path, "r", encoding="utf-8") as f:
            req = json.load(f)
    except Exception as e:
        _write(out_path, {"ok": False, "error": f"请求读取失败: {e}"})
        return 1

    # 确保 GSAS-II 可导入
    try:
        from GSASII import GSASIIscriptable as G2sc  # noqa: F401
    except ImportError:
        prefix = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
        for cand in (os.environ.get("GSASII_ROOT", ""),
                     os.path.join(prefix, "GSAS-II")):
            if cand and os.path.isdir(cand) and cand not in sys.path:
                sys.path.insert(0, cand)
                break
        try:
            from GSASII import GSASIIscriptable as G2sc  # noqa: F401
        except Exception as e:
            _write(out_path, {"ok": False, "error": f"GSASIIscriptable 导入失败: {e}"})
            return 1

    # 规避导出器原生崩溃链 (与 GSAS 自带 python 无关的第三方扩展)
    from GSASII import GSASIIfiles as G2fil
    if hasattr(G2fil, "LoadExportRoutines"):
        G2fil.LoadExportRoutines = lambda parent: []  # noqa: E731

    try:
        tt_in = [float(x) for x in req["two_theta"]]
        intens_in = [float(x) for x in req["intensity"]]
    except Exception as e:
        _write(out_path, {"ok": False, "error": f"谱数据解析失败: {e}"})
        return 1
    if len(tt_in) < 10 or len(tt_in) != len(intens_in):
        _write(out_path, {"ok": False, "error": "谱数据长度不足或与强度不一致"})
        return 1
    # 过滤非有限值
    tt = np.asarray(tt_in, dtype=float)
    I = np.asarray(intens_in, dtype=float)
    finite = np.isfinite(tt) & np.isfinite(I)
    tt, I = tt[finite], I[finite]
    if len(tt) < 10:
        _write(out_path, {"ok": False, "error": "谱数据无有限值"})
        return 1

    lam = float(req.get("wavelength", 1.5406))
    gw = _estimate_gw(tt, I)
    iparm_lines = _make_inst_prm_lines(lam, gw)

    workdir = tempfile.mkdtemp(prefix="polyxrd_gsas_")
    xy_path = os.path.join(workdir, "data.xy")
    iparm_path = os.path.join(workdir, "inst.prm")
    with open(xy_path, "w", encoding="ascii") as f:
        for t, v in zip(tt.tolist(), I.tolist()):
            f.write(f"{t:g} {v:g}\n")
    with open(iparm_path, "w", encoding="ascii") as f:
        f.write("\n".join(iparm_lines) + "\n")

    # ---- 候选种子: 峰位定种 + 尺度网格 ----
    scales: list[float] = []
    phases = req.get("phases", [])
    single_lattice_phase = (
        len(phases) == 1 and not phases[0].get("cif_path")
        and bool(phases[0].get("lattice"))
    )
    if single_lattice_phase:
        scales = [1.0 + 0.02 * k for k in (-2, -1, 0, 1, 2)]
        # 峰位定种 (立方)
        lat = phases[0]["lattice"]
        try:
            bg = float(np.median(np.concatenate([I[: len(I) // 30],
                                                 I[-len(I) // 30:]])))
        except Exception:
            bg = 0.0
        peaks = _find_peaks(tt, I, bg)
        sg = phases[0].get("spacegroup") or ""
        a_ref = float(lat.get("a", 5.0))
        seed_a = _cubic_seed_a(peaks, sg, lam, a_ref)
        if seed_a is not None and 0.7 < seed_a / a_ref < 1.4:
            scales.append(seed_a / a_ref)
        scales = sorted(set(round(s, 6) for s in scales))
    else:
        scales = [1.0]

    # ---- 评分选种子 ----
    best_scale, best_wR = None, float("inf")
    for s in scales:
        w = _score_seed(req, xy_path, iparm_path, iparm_lines, s)
        if w is not None and w < best_wR:
            best_scale, best_wR = s, w
    if best_scale is None:
        best_scale = 1.0  # 全部评分失败 -> 退回用户晶胞

    # ---- 最终精修 (失败时依次回退更保守种子) ----
    result = None
    last_err = None
    for s in (best_scale, 1.0):
        try:
            result = _final_refine(req, xy_path, iparm_path, iparm_lines, s)
            if result["wR"] is not None:
                break
        except Exception as e:
            last_err = str(e)[:300]
    if result is None or result["wR"] is None:
        msg = f"GSAS-II 精修失败 (gw={gw:.1f})"
        if last_err:
            msg += f": {last_err}"
        _write(out_path, {"ok": False, "error": msg})
        return 1

    _write(out_path, {
        "ok": True,
        "wR": float(result["wR"]),
        "GOF": None,
        "n_cycles": int(result["rounds"]),
        "phases": result["phases"],
        "gpx": result["gpx"],
        "engine_meta": {
            "gw_est": round(gw, 3),
            "seed_scale": best_scale,
            "seed_wR": best_wR,
        },
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
