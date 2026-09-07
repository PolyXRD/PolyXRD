"""
报告与导出服务 (M18, Sprint 3)
==============================
自包含生成 (无 GUI/浏览器依赖, 便于单测与复用):
  - export_svg_pattern : 衍射谱图 SVG (实验曲线 + 峰标记 + 参考棒)
  - render_html_report : 单文件 HTML 报告 (SVG + 峰表 + 候选表 + 定量表)
  - export_peak_table_csv
  - export_refined_cif  (晶胞+原子位点 → CIF; 无原子则仅晶胞注释)
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.models.peak import PeakList
from polyxrd.models.xrd_data import XRDData


# ── SVG 谱图 ────────────────────────────────────────────────

def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export_svg_pattern(
    xrd: XRDData,
    peaks: Optional[PeakList] = None,
    ref_peaks: Optional[list] = None,
    title: str = "",
    width: int = 800,
    height: int = 300,
) -> str:
    """生成谱图 SVG。

    ref_peaks: 参考棒 (list[(2θ, I)]) 在底部画竖线 (相对强度)。
    """
    x = np.asarray(xrd.two_theta, dtype=float)
    y = np.asarray(xrd.intensity, dtype=float)
    if len(x) == 0:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d"/>' % (width, height)
    pad_l, pad_r, pad_t, pad_b = 50, 16, 26, 40
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    x0, x1 = float(x.min()), float(x.max())
    ymax = float(y.max()) or 1.0
    ymax *= 1.06

    def px(v): return pad_l + (v - x0) / (x1 - x0) * plot_w
    def py(v): return pad_t + (1.0 - v / ymax) * plot_h

    pts = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in zip(x, y))
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">' % (width, height, width, height),
        f'<title>{_esc(title or "XRD pattern")}</title>',
        f'<polyline points="{pts}" fill="none" stroke="#185FA5" stroke-width="1.2"/>',
    ]
    # 实验峰标记 (顶部小三角)
    if peaks is not None:
        for p in peaks.peaks:
            if not (x0 <= p.two_theta <= x1):
                continue
            cx = px(p.two_theta)
            top = py(min(p.intensity, ymax))
            parts.append(
                f'<polygon points="{cx:.1f},{top-7:.1f} {cx-4:.1f},{top:.1f} '
                f'{cx+4:.1f},{top:.1f}" fill="#D85A30"/>')
    # 参考棒 (底部竖线)
    if ref_peaks:
        bottom = pad_t + plot_h
        for tt, i in ref_peaks:
            if not (x0 <= float(tt) <= x1) or float(i) <= 0:
                continue
            h = 14.0 * min(1.0, float(i) / 100.0)
            cx = px(float(tt))
            parts.append(
                f'<line x1="{cx:.1f}" y1="{bottom - h:.1f}" x2="{cx:.1f}" '
                f'y2="{bottom:.1f}" stroke="#0F6E56" stroke-width="1.4"/>')
    # 坐标轴
    parts.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" '
        f'y2="{pad_t + plot_h}" stroke="#444" stroke-width="0.8"/>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" '
                 f'y2="{pad_t + plot_h}" stroke="#444" stroke-width="0.8"/>')
    parts.append(f'<text x="{(pad_l + pad_l + plot_w) / 2:.0f}" y="{height - 10}" '
                 f'font-family="sans-serif" font-size="12" text-anchor="middle">'
                 f'2θ (deg)</text>')
    parts.append(f'<text x="{pad_l + plot_w / 2:.0f}" y="16" '
                 f'font-family="sans-serif" font-size="13" text-anchor="middle">'
                 f'{_esc(title)}</text>')
    parts.append('</svg>')
    return "\n".join(parts)


# ── HTML 报告 ───────────────────────────────────────────────

def render_html_report(
    xrd: XRDData,
    peaks: Optional[PeakList] = None,
    matches: Optional[list] = None,
    quantified: Optional[dict] = None,
    title: str = "PolyXRD 分析报告",
    out: Optional[str] = None,
) -> str:
    """渲染单文件 HTML 报告并返回字符串 (out 给定时写入文件)。"""
    svg = export_svg_pattern(xrd, peaks=peaks, title=title)
    peak_rows = ""
    if peaks is not None:
        for i, p in enumerate(peaks.peaks, 1):
            peak_rows += (
                f"<tr><td>{i}</td><td>{p.two_theta:.4f}</td>"
                f"<td>{p.intensity:.1f}</td><td>{p.fwhm:.4f}</td>"
                f"<td>{p.d_spacing:.4f}</td></tr>")
    match_rows = ""
    if matches:
        for m in matches:
            name = getattr(m, "name", None) or m.phase.name
            formula = m.phase.formula or ""
            score = getattr(m, "score", float("nan"))
            cov = getattr(m, "coverage", 0.0)
            match_rows += (
                f"<tr><td>{_esc(name)}</td><td>{_esc(formula)}</td>"
                f"<td>{score:.3f}</td><td>{cov:.1f}%</td></tr>")
    quan_rows = ""
    if quantified:
        for name, wt in quantified.items():
            quan_rows += f"<tr><td>{_esc(name)}</td><td>{float(wt):.2f}%</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{_esc(title)}</title>
<style>
 body{{font-family:'Microsoft YaHei',sans-serif;margin:24px;color:#222}}
 h1{{font-size:18px;border-bottom:2px solid #185FA5;padding-bottom:6px}}
 svg{{max-width:100%;border:1px solid #ddd;border-radius:6px}}
 table{{border-collapse:collapse;margin:10px 0;width:100%;font-size:13px}}
 th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left}}
 th{{background:#E6F1FB}}
 h2{{font-size:15px;margin-top:22px}}
</style></head><body>
<h1>{_esc(title)}</h1>
<p>数据点: {len(xrd)} | 2θ 范围: {float(xrd.two_theta[0]):.2f}–{float(xrd.two_theta[-1]):.2f}°</p>
{svg}
<h2>峰表 ({len(peaks) if peaks else 0})</h2>
<table><tr><th>#</th><th>2θ</th><th>强度</th><th>FWHM</th><th>d</th></tr>{peak_rows}</table>
<h2>匹配候选</h2>
<table><tr><th>物相</th><th>化学式</th><th>Score</th><th>覆盖率</th></tr>{match_rows}</table>
<h2>定量结果</h2>
<table><tr><th>物相</th><th>含量</th></tr>{quan_rows}</table>
<p style="color:#888;font-size:12px;margin-top:26px">PolyXRD 自动生成</p>
</body></html>"""
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
    return html


# ── 峰表 CSV / CIF 导出 ────────────────────────────────────

def export_peak_table_csv(peaks: PeakList, path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "two_theta", "intensity", "fwhm", "d_spacing"])
        for i, pk in enumerate(peaks.peaks, 1):
            w.writerow([i, f"{pk.two_theta:.4f}", f"{pk.intensity:.1f}",
                        f"{pk.fwhm:.4f}", f"{pk.d_spacing:.4f}"])


def export_refined_cif(phase, path) -> None:
    """把精修后的 Phase 导出 CIF (晶胞+原子位点)。无原子位点则注释说明。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    name = (phase.name or phase.formula or "phase").replace(" ", "_")
    lines = [f"# PolyXRD export: {phase.name}", f"data_{name}", ""]
    if phase.lattice is not None:
        lat = phase.lattice
        lines += [
            f"_cell_length_a    {lat.a:.6f}",
            f"_cell_length_b    {lat.b:.6f}",
            f"_cell_length_c    {lat.c:.6f}",
            f"_cell_angle_alpha {lat.alpha:.4f}",
            f"_cell_angle_beta  {lat.beta:.4f}",
            f"_cell_angle_gamma {lat.gamma:.4f}",
            "",
        ]
    if phase.space_group:
        lines.append(f"_symmetry_space_group_name_H-M  '{phase.space_group}'")
        lines.append("")
    sites = phase.atomic_sites or []
    if sites:
        lines += ["loop_",
                  "_atom_site_label",
                  "_atom_site_type_symbol",
                  "_atom_site_fract_x",
                  "_atom_site_fract_y",
                  "_atom_site_fract_z",
                  "_atom_site_occupancy"]
        for s in sites:
            lines.append(
                f"{s.get('label', s.get('element', 'X'))} "
                f"{s.get('element', 'X')} "
                f"{float(s.get('x', 0)):.6f} "
                f"{float(s.get('y', 0)):.6f} "
                f"{float(s.get('z', 0)):.6f} "
                f"{float(s.get('occupancy', 1.0)):.4f}")
    else:
        lines.append("# 无原子位点信息 (仅晶胞) — 如需 Rietveld 请补充结构。")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
