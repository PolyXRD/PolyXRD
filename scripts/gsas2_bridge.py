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
from typing import Optional

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

#: 常用靶材 Kα1/Kα2 (Å)。GSAS-II 用 ``INS 1 ICONS`` 里第二个波长 +
#: ``I(L2)/I(L1)`` 生成双线; 只给单波长时拟合会把 Kα1 峰做得过高约 1.5x
#: (2-1 实测 ycalc 122507 vs yobs 78491 @ZnO 101), Rwp 直接卡在 53%。
_KA_DOUBLET = ((1.54056, 1.54439), (1.78897, 1.79285), (1.93604, 1.93998),
               (2.28970, 2.29361), (0.70930, 0.71359), (1.39222, 1.39592))


def _ka2_of(lam: float) -> Optional[float]:
    """Kα1 → 同靶 Kα2 波长; 认不出 (同步辐射/单色器) 返回 ``None``。"""
    for k1, k2 in _KA_DOUBLET:
        if abs(float(lam) - k1) < 0.004:
            return k2
    return None


def _make_inst_prm_lines(lam: float, gw: float,
                         gx: Optional[float] = None) -> list[str]:
    """CW PseudoVoigt 仪器参数 (单位: 平方百分度 / 百分度)。

    ``gw`` = W (高斯项, σ² 单位 0.01°²); ``gx`` = X (洛伦兹项 FWHM, 0.01°)。

    v5.0.1: 原先 X=Y=Z=0 即**纯高斯**峰形。实测数据峰形由洛伦兹主导
    (PolyXRD 内置引擎拟合 eta≈1.00), 纯高斯无法匹配峰尾。

    ``INS 1 ICONS`` 按固定列宽排列 (GSASIIfiles 用 ``s[:10]`` / ``s[10:20]``
    / ``s[40:50]`` / ``s[55:65]`` 切片读): 前两列各 10 字符 (2 空格 + 8 位
    数字), 依次 wave1 / wave2 / zero / 占位 / 极化 / 占位 / I(L2)/I(L1)。
    """
    if gx is None:
        gx = math.sqrt(max(gw, 0.0)) if gw > 0 else 0.0
    ka2 = _ka2_of(lam)
    icons = (f"  {float(lam):8.6f} {float(ka2 or lam):8.6f}"
             f"{0.0:10.1f}{0:10d}{0.7:10.2f}{0:5d}{0.5:10.3f}")
    return [
        "            123456789012345678901234567890123456789012345678901234567890",
        "INS   BANK      1",
        "INS   HTYPE   PXCR",
        "INS  1 IRAD     3",
        "INS  1 ICONS" + icons,
        "INS  1I HEAD  DUMMY INCIDENT SPECTRUM FOR X-RAY DIFFRACTOMETER",
        "INS  1I ITYP    0    0.0000  180.0000         1",
        "INS  1PRCF1     3    8      0.01",
        f"INS  1PRCF11    0.000000E+00   0.000000E+00   {gw:12.6E}   0.000000E+00",
        f"INS  1PRCF12    {gx:12.6E}   0.000000E+00   0.000000E+00   0.000000E+00",
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

    # ── v5.2 (P1-9③): 样品位移 / 择优取向入口 ──
    # 服务层从 RefineOptions/kwargs 透传过来; 桥侧应用失败只降级、不致命
    # (这些是"锦上添花"的物理量, 不该让整条精修回退 builtin)。
    try:
        _apply_sample_displace(hist, req)
    except Exception as e:  # noqa: BLE001
        print(f"[bridge] sample displace skipped: {e}", file=sys.stderr)
    try:
        _apply_pref_ori(gpx, req)
    except Exception as e:  # noqa: BLE001
        print(f"[bridge] pref ori skipped: {e}", file=sys.stderr)

    gpx.set_refinement({"set": {"LeBail": True}}, histogram="all", phase="all")
    ctrl = gpx.data["Controls"]["data"]
    ctrl["newLeBail"] = True
    ctrl["max cyc"] = 1
    ctrl["shift factor"] = 0.5
    gpx.save()
    return gpx_path, gpx


_CELL_BKG = {"LeBail": True, "Cell": True,
             "Background": {"no. coeffs": 6, "refine": True}}


def _apply_sample_displace(hist, req: dict) -> None:
    """v5.2 (P1-9③): req["sample_displace"] → Bragg-Brentano 样品位移。

    GSAS-II 的 ``Sample Parameters['DisplaceX']`` 是 [值(µm), 精修标志]；
    给了初值即打开精修标志，让 LSQ 自己找准确的位移量。
    未给 / 键不存在 / 结构不符时静默跳过（不许影响主流程）。
    """
    disp = req.get("sample_displace")
    if not isinstance(disp, (int, float)) or not np.isfinite(disp):
        return
    sp = hist.data.get("Sample Parameters") or {}
    dx = sp.get("DisplaceX")
    if not (isinstance(dx, list) and len(dx) >= 2):
        return
    dx[0] = float(disp)
    dx[1] = True


def _apply_pref_ori(gpx, req: dict) -> None:
    """v5.2 (P1-9③): req["pref_ori"] = {"hkl": [h,k,l], "r": float} → March-Dollase。

    HAP 的 ``Pref.Ori.`` 结构（GSASIIstrIO 口径，MD 模式）:
      [0]='MD', [1]=MD 系数 r 本身, [2]=精修标志, [3]=MDAxis (hkl)。
    与 RefineOptions.preferred_orientation 的"全局一个方向"对齐 ——
    应用于工程内**所有相**（v5 引擎的 _po_direction 也是全相同语义）。
    r=1（无择优）时不设置。
    """
    po = req.get("pref_ori")
    if not isinstance(po, dict):
        return
    r = float(po.get("r", 1.0))
    if not np.isfinite(r) or abs(r - 1.0) < 1e-9:
        return
    hkl = [int(v) for v in po.get("hkl", (0, 0, 1))]
    for ph in gpx.phases():
        for hname, hap in (ph.data.get("Histograms") or {}).items():
            p = hap.get("Pref.Ori.")
            if not (isinstance(p, list) and len(p) >= 4):
                continue
            p[0] = "MD"
            p[1] = r
            p[2] = True   # 打开精修: 起点给对方向, r 让 LSQ 自己找
            p[3] = hkl

#: Rietveld 定量阶段的 set 字典 —— **必须显式 LeBail=False**。
#: ``do_refinements`` 的 ``set`` 会重新打开 Le Bail, 把上面
#: ``ph.set_refinements({"LeBail": False})`` 关掉的再打开; 此时相分数退化
#: 成"自由强度比", 2026-11-01 实测 2-1 给出 22/78 (真值 50/50, 真 Rietveld
#: 应为 48/52)。
_CELL_BKG_RIET = {"LeBail": False, "Cell": True,
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
            "Instrument Parameters": ["U", "V", "W", "X"]})} for _ in range(2)])
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

    # Le Bail 最终 wR 必须在定量阶段**之前**捕获 (定量切到 Rietveld 模式
    # 后 wR 必然升高, 不能作为主指标回传)
    wR = None
    try:
        wR = gpx.histogram(0).get_wR()
    except Exception:
        wR = None
    # v5.2 (P1-9④): Rvals 里的 GOF/Nobs/Nvar 一并回传 —— 此前 main() 硬编码
    # "GOF": None, 诊断表整列恒 0, 不能当"GOF 更好"的判据。位置兼容两代:
    # Controls['Rvals'] 与 Controls['data']['Rvals']。
    rvals = _read_rvals(gpx)

    # ── v0.11.0 定量阶段: 全相有 CIF 结构时关 LeBail, 用 |F|² 精修相分数 ──
    # Le Bail 模式下相分数无语义 (强度是自由变量); 只有回到真 Rietveld
    # (结构因子 × 相 Scale) 才能得到可解释的 wt%.
    # 整段 try/except 包裹: 任何失败只损失 wt%, 不影响晶胞/LeBail wR 结果.
    phase_fractions = None
    wR_rietveld = None
    ycalc = None
    try:
        req_phases = req.get("phases", [])
        if req_phases and all(p.get("cif_path") for p in req_phases):
            gpx.reload()
            ctrl = gpx.data["Controls"]["data"]
            ctrl["max cyc"] = 8
            # 关 LeBail (强度改由结构因子 |F|² 计算) + 打开相分数精修。
            # 注意: 相名 (如 ' ?') 在 reload 后 gpx.phase(name) 可能查不到,
            # 这里直接迭代工程里的全部相 (与 req 顺序一致) 绕开名字查找.
            proj_phases = list(gpx.phases())
            for ph in proj_phases:
                ph.set_refinements({"LeBail": False})
                ph.set_HAP_refinements({"Scale": True}, histograms="all")
            # 冻结 U/V/W: Le Bail 阶段已把它们精修到近乎共线 (实测 U-V 97.5%、
            # V-W 98.5%), Rietveld 里再放开会命中 SVD 奇异, chi^2 从 3.9e6 直接
            # 飙到 4.9e12, 随后 "Invalid metric tensor", 整段定量失败。
            try:
                gpx.histogram(0).clear_refinements(
                    {"Instrument Parameters": ["U", "V", "W"]})
            except Exception as e:  # noqa: BLE001 - 拿不到峰形键不影响定量
                print(f"[bridge] freeze U/V/W skipped: {e}", file=sys.stderr)
            gpx.save()
            # set 字典用 _CELL_BKG_RIET: 带 LeBail=False, 否则上面关掉的又开回来
            dbg = bool(os.environ.get("POLYXRD_G2_DEBUG"))

            def _dbg(msg):
                """定量阶段诊断落盘 (子进程 stderr 在上层会被合并丢弃)。"""
                if not dbg:
                    return
                path = os.environ.get("POLYXRD_G2_DEBUG_FILE") or "g2dbg.log"
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(msg + "\n")
                except Exception:
                    pass

            if dbg:
                for ph in gpx.phases():
                    _hv = ph.getHAPvalues(gpx.histogram(0).name)
                    _dbg(f"before {ph.name}: LeBail={_hv.get('LeBail')} scale={_hv.get('Scale')}")

            # ---- 相 Scale 量级初始化 (v5.0.1) ----
            # Rietveld 的 Y = H·Σ S_p·C_p + bg 对 S 是线性的, 但 S 从 1.0 起步
            # 常差 3~5 个数量级; LM 第一步给出天文步长 (实测 chi² 3.9e6 → 9e11)
            # 又被 lambda 压回原处 → 精修报"成功"却一步未动, scale 停在 1.0,
            # 相分数退化成"胞内质量比"(2-1 得到 21/79, 与结构因子无关)。
            # 这里先冻结 Scale 只精修背景拿一次 Ycalc, 再用
            # Σ(yobs-bg)/Σ(ycalc-bg) 把各相 Scale 一次拉到正确量级;
            # 相对比例仍交给随后几轮 Rietveld LSQ。
            try:
                for ph in proj_phases:
                    ph.set_HAP_refinements({"Scale": False}, histograms="all")
                gpx.save()
                gpx.do_refinements([{"set": dict(
                    _CELL_BKG_RIET, Cell=False,
                    **{"Instrument Parameters": ["Zero"]})}])
                rounds += 1
                _h = gpx.histogram(0)
                _yobs = np.asarray(_h.getdata("Yobs"), dtype=float)
                _ycalc = np.asarray(_h.getdata("Ycalc"), dtype=float)
                _bg = np.asarray(_h.getdata("Background"), dtype=float)
                _num = float(np.sum(_yobs - _bg))
                _den = float(np.sum(_ycalc - _bg))
                if _den > 0 and _num > 0:
                    _k = _num / _den
                    for ph in gpx.phases():
                        _hap = ph.data["Histograms"][_h.name]["Scale"]
                        _hap[0] = float(_hap[0]) * _k
                        _hap[1] = True
                    gpx.save()
                    _dbg(f"scale-init k={_k:.6g} num={_num:.5g} den={_den:.5g}")
            except Exception as e:  # noqa: BLE001 - 初始化失败仍走原路径
                print(f"[bridge] scale init skipped: {e}", file=sys.stderr)

            # Le Bail → Rietveld 切换时若同时放开晶胞, 第一步 LSQ 也会把晶胞
            # 拉爆 (实测 "Invalid metric tensor ... values (A): -0.1220")。
            # 所以先固定晶胞只放 Scale+背景, 再放晶胞。
            for _r, _cell_on in enumerate((False, False, True, True)):
                gpx.do_refinements([{"set": dict(
                    _CELL_BKG_RIET, Cell=_cell_on,
                    # Zero 属于仪器参数 (句典里没有独立的 'Zero' 键), 与
                    # 已冻结的 U/V/W/X 互不影响; 不修零点时 36° 处错位
                    # 0.02° → Rwp 直接从 24% 恶化到 47%。
                    **{"Instrument Parameters": ["Zero"]})}])
                rounds += 1
                if dbg:
                    gpx.reload()
                    try:
                        _w = gpx.histogram(0).get_wR()
                    except Exception:
                        _w = None
                    _sc = [ph.getHAPvalues(gpx.histogram(0).name).get("Scale")
                           for ph in gpx.phases()]
                    _dbg(f"round {_r} cell={_cell_on}: wR={_w} scales={_sc}")
            rounds += 1
            gpx.reload()
            hist = gpx.histogram(0)
            proj_phases = list(gpx.phases())  # reload 后重新取对象
            masses = []
            scales = []
            cell_masses = []
            for idx, p in enumerate(req_phases):
                if idx < len(proj_phases):
                    ph = proj_phases[idx]
                else:
                    ph = gpx.phase(p.get("name") or "phase")
                if ph is None:
                    raise RuntimeError(f"phase not found: {p.get('name')!r}")
                frac = ph.getHAPvalues(hist.name)["Scale"][0]
                mass = ph.data["General"]["Mass"]
                scales.append(float(frac))
                cell_masses.append(float(mass))
                masses.append(float(frac) * float(mass))
            total = sum(masses)
            if total > 0:
                phase_fractions = [100.0 * m / total for m in masses]
            try:
                wR_rietveld = float(gpx.histogram(0).get_wR())
            except Exception:
                wR_rietveld = None
            if os.environ.get("POLYXRD_G2_DEBUG"):
                # 定量诊断钩子: 相分数只由 "Scale × 胞内质量" 决定, 两者都不透明
                # 时只能盲目调参, 故留一条可观测通道。
                for p, s, cm in zip(req_phases, scales, cell_masses):
                    _dbg(f"final {p.get('name')}: scale={s:.6g} cell_mass={cm:.4f}")
                _dbg(f"wR_rietveld={wR_rietveld} fracs={phase_fractions}")
    except Exception as e:
        print(f"[bridge] quantify stage failed: {e}", file=sys.stderr)
        phase_fractions = None

    # v0.11.0: 回传计算谱 (修 PolyXRD 侧残差图"假装完美"的假回传)
    try:
        hist0 = gpx.histogram(0)
        ycalc = [float(v) for v in hist0.getdata("Ycalc")]
    except Exception:
        ycalc = None
    return {"phases": out_phases, "wR": wR, "rounds": rounds, "gpx": gpx_path,
            "phase_fractions": phase_fractions, "wR_rietveld": wR_rietveld,
            "ycalc": ycalc,
            "GOF": (float(rvals["GOF"]) if rvals.get("GOF") is not None else None),
            "Nobs": int(rvals.get("Nobs") or 0),
            "Nvar": int(rvals.get("Nvar") or 0)}


def _read_rvals(gpx) -> dict:
    """v5.2 (P1-9④): 从工程树里取 Rvals（GOF/Nobs/Nvar）。

    正确位置是 **Covariance 树**（``GSASIIstrMain`` 把 covData = {'Rvals':…}
    存进 ``Covariance['data']``，2026-11-05 端到端实测 Controls 里没有）；
    ``Controls['Rvals']`` / ``Controls['data']['Rvals']`` 是老版本候选，
    一并兼容。任何失败返回 {} —— 指标缺失只降级，不影响晶胞/wR 主结果。
    """
    try:
        c = gpx.data.get("Covariance") or {}
        for cand in (c.get("data") or {},):
            rv = cand.get("Rvals") if isinstance(cand, dict) else None
            if isinstance(rv, dict) and rv.get("GOF") is not None:
                return rv
        c = gpx.data.get("Controls") or {}
        for cand in (c.get("data") or {}, c):
            rv = cand.get("Rvals") if isinstance(cand, dict) else None
            if isinstance(rv, dict) and rv.get("GOF") is not None:
                return rv
    except Exception:  # noqa: BLE001
        pass
    return {}


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
        # v5.2 (P1-9④): 真实 GOF/Nobs/Nvar (此前硬编码 None, 诊断表整列恒 0)
        "GOF": result.get("GOF"),
        "Nobs": result.get("Nobs", 0),
        "Nvar": result.get("Nvar", 0),
        "n_cycles": int(result["rounds"]),
        "phases": result["phases"],
        "phase_fractions": result.get("phase_fractions"),
        "wR_rietveld": result.get("wR_rietveld"),
        "ycalc": result.get("ycalc"),
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
