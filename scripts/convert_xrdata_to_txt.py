"""
批量把 XRData 下的「原始（实测）XRD 谱图文件」转换为 .txt（两列 2θ/强度），
每个转换结果放进其所在目录新建的 txt/ 子文件夹中。

策略
----
- 只用 PolyXRD 自带、已验证的读取链路 (services.pattern_convert.load_pattern)
  处理**真正的实测谱图源格式**：.raw/.RAW(仪器二进制) .mdi .xy .dat .csv
  .xrdml .prf .brml .smz。
- 二进制 .raw 按魔数分流：Rigaku ``RAW2`` / Rigaku ``FI`` / 岛津 ``Shimadzu XRD``
  走各自已验证的解析器；不支持的魔数（如 Rigaku ``RAW1``）直接跳过, 绝不写伪谱图。
- 岛津二进制 .RAW 现已完全解码(起始/终止角@300/304 ×10000、点数@624、强度块
  N×int32 **位于文件末尾, 偏移 = 文件大小 - 4*N**; header 长 968/976/1608 三种
  子类型皆由此统一覆盖, 不可写死 968), 与 PCXRD 导出的配对 txt 做**逐数值**交叉
  验证 18/18 完全一致 (maxΔ2θ=0.0000°, corr=1.00000, 强度比=1.000)。其
  "drive axis=Theta" 单轴(摇摆)模式的记录轴是 θ, 需 ×2 成 2θ —— 由同目录配对
  .txt 的列头 (<Theta> vs <2Theta>) 自动判定并透传 theta_mode。非 2θ 扫描
  (摇摆/极图)由加载器明确 skip, 不污染相分析。
- 每个文件先尝试读取，再用 is_convertible 闸门过滤掉「读出来不是有效谱图」的。
- 输出：``<源文件所在目录>/txt/<主名>.txt``。同一测量若同时存在多格式源文件
  (如 .RAW + .mdi), 主名会撞车 → **追加源扩展名消歧** (``BAUXITE_raw.txt`` /
  ``BAUXITE_mdi.txt``), 否则两者会互相覆盖同一 txt 并在每次重跑时来回翻转。
- 重跑幂等且带**陈旧自检**: 已存在的输出会与当前解析结果比对, 一致才跳过;
  不一致 (例如解析器修复后旧 txt 成了脏数据) 则覆盖重写, 避免脏结果永久留存。
- 不动任何原始文件，只新增 txt/ 子目录与 .txt。
- 全程写一份报告 (convert_xrdata_report.md)：转换了哪些、跳过了哪些(及原因)。
"""
from __future__ import annotations
import sys, time, re
from pathlib import Path
from collections import defaultdict, OrderedDict

ROOT = Path(r"D:\Project\XRD\XRData")
REPORT = Path(r"D:\Project\XRD\PolyXRD\.workbuddy\tmp\convert_xrdata_report.md")

# 真正尝试读取的源格式（其余一律跳过）
SRC_EXTS = {".raw", ".mdi", ".xy", ".dat", ".csv", ".xrdml", ".prf", ".brml", ".smz"}

sys.path.insert(0, r"D:\Project\XRD\PolyXRD\src")
import numpy as np
from polyxrd.services.pattern_convert import load_pattern, convert_pattern_file

# 受支持的二进制 .raw 魔数
#   - 短魔数(4 字节): Rigaku RAW2 / Rigaku RINT-2000 (FI)
#   - 长魔数(12 字节): 岛津 PCXRD 导出 (Shimadzu XRD)
# 其余(如 Rigaku RAW1、未知变体)走启发式会产出伪谱图, 必须拦掉。
_RAW_OK_MAGIC = (b"RAW2", b"FI\x00\x00")
_RAW_OK_MAGIC_LONG = (b"Shimadzu XRD",)


def raw_magic_ok(path: Path) -> bool:
    if path.suffix.lower() != ".raw":
        return True
    head = path.read_bytes()[:12]
    if head[:4] in _RAW_OK_MAGIC:
        return True
    if head[:12] in _RAW_OK_MAGIC_LONG:
        return True
    return False


def shimadzu_theta_mode(path: Path) -> bool:
    """岛津 .raw 若同目录有配对 .txt, 由其列头判定是否单轴(Theta)模式需 ×2。

    列头 ``<2Theta>`` → 2θ (无需翻倍); ``<Theta>``(无 2) → 记录轴是 θ, 翻倍。
    """
    txt = path.with_suffix(".txt")
    if not txt.exists():
        return False
    t = txt.read_text(encoding="utf-8", errors="replace")
    if "<2Theta>" in t:
        return False
    return bool(re.search(r"<\s*Theta\s*>", t))


def is_convertible(d) -> tuple[bool, str]:
    """判定 load_pattern 的结果是否是一条可写出的有效谱图。"""
    try:
        t = np.asarray(d.two_theta, dtype=float)
        y = np.asarray(d.intensity, dtype=float)
    except Exception:
        return False, "无 two_theta/intensity"
    n = len(t)
    if n < 20:
        return False, f"点数过少({n})"
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(y))):
        return False, "含非有限值"
    in_range = np.sum((t >= -0.5) & (t <= 180.5))
    if in_range < 0.9 * n:
        return False, f"2θ 越界({in_range}/{n} 在[0,180])"
    if y.max() <= 0:
        return False, "无正强度"
    neg_frac = float(np.mean(y < -1e-3))
    if neg_frac > 0.05:
        return False, f"负强度占比过高({neg_frac:.1%})"
    return True, ""


def _is_stale(dst: Path, d) -> tuple[bool, str]:
    """已有的输出 txt 是否与**当前**解析结果一致？

    返回 ``(需要重写, 原因)``。典型场景: 解析器修复后, 旧 txt 变成脏数据,
    但单纯「已存在就跳过」的幂等策略会把脏数据永久留下。这里做一致性自检,
    不一致则判定陈旧、触发覆盖重写。
    """
    try:
        arr = np.atleast_2d(np.loadtxt(dst))
    except Exception:
        return True, "无法解析现有txt"
    if arr.ndim != 2 or arr.shape[0] < 1 or arr.shape[1] < 2:
        return True, "现有txt格式异常"
    t_new = np.asarray(d.two_theta, dtype=float)
    y_new = np.asarray(d.intensity, dtype=float)
    if arr.shape[0] != len(t_new):
        return True, f"点数 {arr.shape[0]}→{len(t_new)}"
    xt = arr[:, 0]
    if not np.allclose(xt, t_new, atol=1e-3):
        return True, f"2θ轴不一致(maxΔ={float(np.max(np.abs(xt - t_new))):.4g}°)"
    yi = arr[:, 1]
    scale = max(float(np.max(np.abs(yi))), 1e-9)
    # 允许写盘取整带来的微小差异, 但不放过数量级/形状级的偏差
    if not np.allclose(yi, y_new, rtol=1e-3, atol=max(1e-6, scale * 1e-4)):
        return True, "强度不一致"
    return False, ""


def _build_stem_groups(files) -> dict:
    """按 (目录, 主名) 聚组, 识别「同一测量的多格式文件」造成的输出命名冲突。

    XRData 里不少样品同时存了 ``.RAW``(仪器二进制) 与 ``.mdi``(文本再导出),
    两者主名相同 → 若都写成 ``txt/<主名>.txt`` 会互相覆盖, 且因两者点数
    (如 7251 vs 7250) 不同, 每次重跑都会把对方判为陈旧再度改写, 形成**永久振荡**。
    """
    g = defaultdict(list)
    for p in files:
        g[(p.parent, p.stem.lower())].append(p)
    return g


def _out_name(p: Path, collide: bool) -> str:
    """输出 txt 文件名; 冲突组追加源扩展名消歧 (如 ``BAUXITE_raw.txt`` / ``BAUXITE_mdi.txt``)。"""
    if collide:
        return f"{p.stem}_{p.suffix.lstrip('.').lower()}.txt"
    return f"{p.stem}.txt"


def main():
    converted, skipped = [], []
    per_dir = OrderedDict()          # dir -> converted count
    skip_reason = defaultdict(int)   # reason -> count
    t0 = time.time()

    files = sorted(p for p in ROOT.rglob("*")
                   if p.is_file() and p.suffix.lower() in SRC_EXTS)
    print(f"候选源文件: {len(files)}", flush=True)

    # 输出命名冲突分析: 同目录同主名的多个源文件 (如 .RAW + .mdi) 必须消歧,
    # 否则会互相覆盖同一个 txt 并在每次重跑时来回翻转。
    stem_groups = _build_stem_groups(files)
    collide_keys = {k for k, v in stem_groups.items() if len(v) > 1}

    # 清理冲突组历史上遗留的「纯主名」歧义输出 —— 其内容已被多个源反复覆盖、
    # 不可信, 且新命名生效后不会再有人写它。这是本脚本自身生成的派生产物,
    # 可由源文件随时重算, 删除仅为避免误导。
    for key in collide_keys:
        parent, _stem_lower = key
        legacy = parent / "txt" / f"{stem_groups[key][0].stem}.txt"
        if legacy.exists():
            try:
                legacy.unlink()
                print(f"  清理歧义输出: {legacy.name}", flush=True)
            except OSError as e:
                print(f"  清理失败(跳过): {legacy} -> {e}", flush=True)

    for p in files:
        parent = p.parent
        # 二进制 .raw 必须魔数受支持（岛津/RAW1 启发式会产出伪谱图，直接跳过）
        if not raw_magic_ok(p):
            reason = "跳过: 非受支持二进制.raw(未识别魔数，无合法角度轴)"
            skipped.append((str(p), reason))
            skip_reason[reason] += 1
            continue
        # 岛津二进制: 同目录配对 txt 判定是否单轴(Theta)模式需 ×2
        theta_mode = shimadzu_theta_mode(p) if p.read_bytes()[:12] == b"Shimadzu XRD" else False
        try:
            d = load_pattern(p, theta_mode=theta_mode)
        except Exception as e:
            reason = "读取失败: " + str(e).splitlines()[0][:80]
            skipped.append((str(p), reason))
            skip_reason[reason] += 1
            continue
        ok, why = is_convertible(d)
        if not ok:
            skipped.append((str(p), "闸门拒绝: " + why))
            skip_reason["闸门拒绝: " + why] += 1
            continue
        # 目标：<parent>/txt/<stem>.txt （重跑幂等: 已存在则跳过）
        txtdir = parent / "txt"
        dst = txtdir / _out_name(p, (parent, p.stem.lower()) in collide_keys)
        if dst.exists():
            # 幂等 + 陈旧自检: 一致→跳过; 不一致(解析器修复后的脏数据)→覆盖重写
            stale, why = _is_stale(dst, d)
            if not stale:
                skipped.append((str(p), "已存在同名txt，跳过(幂等)"))
                skip_reason["已存在，跳过(幂等)"] += 1
                continue
            skip_reason["陈旧覆盖重写: " + why] += 1
        try:
            convert_pattern_file(p, dst, fmt="txt", theta_mode=theta_mode)
        except Exception as e:
            skipped.append((str(p), "写出失败: " + str(e).splitlines()[0][:80]))
            skip_reason["写出失败"] += 1
            continue
        converted.append((str(p), str(dst), len(d.two_theta)))
        per_dir[str(parent)] = per_dir.get(str(parent), 0) + 1

    # ---- 报告 ----
    lines = []
    lines.append(f"# XRData → txt 批量转换报告 ({time.strftime('%Y-%m-%d %H:%M')})\n")
    lines.append(f"- 根目录: `{ROOT}`")
    lines.append(f"- 候选源文件: {len(files)}")
    lines.append(f"- **转换成功: {len(converted)}**")
    lines.append(f"- 跳过: {len(skipped)}")
    lines.append(f"- 耗时: {time.time()-t0:.1f}s\n")

    lines.append("## 各目录转换数量\n")
    lines.append("| 目录 | 转换数 |")
    lines.append("| --- | --- |")
    for d, c in per_dir.items():
        rel = Path(d).relative_to(ROOT)
        lines.append(f"| `{rel}` | {c} |")
    lines.append("")

    lines.append("## 跳过原因统计\n")
    lines.append("| 原因 | 数量 |")
    lines.append("| --- | --- |")
    for r, c in skip_reason.items():
        lines.append(f"| {r} | {c} |")
    lines.append("")

    lines.append("## 转换成功清单（前 60 条）\n")
    lines.append("| 源文件 | 输出 txt | 点数 |")
    lines.append("| --- | --- | --- |")
    for src, dst, n in converted[:60]:
        lines.append(f"| `{Path(src).relative_to(ROOT)}` | `{Path(dst).relative_to(ROOT)}` | {n} |")
    if len(converted) > 60:
        lines.append(f"| … | 其余 {len(converted)-60} 条略 | |")
    lines.append("")

    if skipped:
        lines.append("## 跳过清单（前 80 条）\n")
        lines.append("| 源文件 | 原因 |")
        lines.append("| --- | --- |")
        for src, r in skipped[:80]:
            lines.append(f"| `{Path(src).relative_to(ROOT)}` | {r} |")
        if len(skipped) > 80:
            lines.append(f"| … | 其余 {len(skipped)-80} 条略 |")
        lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n转换成功: {len(converted)}; 跳过: {len(skipped)}")
    print(f"报告: {REPORT}")
    # 控制台摘要
    print("\n各目录:")
    for d, c in per_dir.items():
        print(f"  {Path(d).relative_to(ROOT)}: {c}")


if __name__ == "__main__":
    main()
