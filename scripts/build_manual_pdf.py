"""Build PolyXRD v2.7.0 使用手册 PDF from markdown + screenshots."""
import re
import subprocess
import sys
from pathlib import Path

import markdown

MANUAL_DIR = Path(__file__).resolve().parent.parent / "docs" / "manual"
MD_PATH = MANUAL_DIR / "PolyXRD使用手册-v2.7.0.md"
OUT_HTML = MANUAL_DIR / "PolyXRD使用手册-v2.7.0.html"
OUT_PDF = MANUAL_DIR / "PolyXRD使用手册-v2.7.0.pdf"
IMG_DIR = MANUAL_DIR / "img"

# (anchor_in_md, image_file, caption) — insert figure after the heading line
FIGURES = [
    ("## 第 3 章　主界面导览", "01_main_data_empty.png", "图 3-1　主窗口：顶部工具栏、左侧参数面板、中央谱图区（v2.6.0 谱图主导布局）"),
    ("### 2.4 数据库挂载（重要）", "09_database_manager.png", "图 2-1　数据库管理器：每个库独立导入 / 挂载"),
    ("### 2.5 用户自建数据库（v2.6.0 新增）", "09b_user_db_dialog.png", "图 2-2　用户自建数据库：导入自己收集的 CIF / 私有物相"),
    ("### 4.1 加载数据", "02_data_loaded.png", "图 4-1　加载数据后：谱图自动绘出，X 轴自适应收缩到数据范围"),
    ("### 4.3 保存、导出与格式转换", "10_format_convert.png", "图 4-2　谱图格式转换：选择目标格式批量或单个转换"),
    ("### 5.1 操作", "03_phase_peaks.png", "图 5-1　峰检测：竖标记为检出峰位，右侧参数可实时调节灵敏度"),
    ("### 6.7 检索结果解读", "04_phase_identified.png", "图 6-1　识别结果：候选列表含 FoM / 化学式 / 空间群"),
    ("### 6.6 数据库选择", "11_cod_search.png", "图 6-2　COD 在线检索：按化学式 / 矿物名 / 空间群查询"),
    ("### 8.2 快速精修（精修页）", "05_refinement_page.png", "图 8-1　精修页：上=实验/模拟对比谱，下=残差条"),
    ("精修完成后", "06_refinement_done.png", "图 8-2　精修完成：模拟谱叠加、残差图、Rwp/GOF、物相质量分数"),
    ("### 8.4 精修向导（两条独立路径）", "08_refine_wizard.png", "图 8-3　快速精修向导（单页）"),
    ("分步精修向导（五步）", "08b_refine_wizard_steps.png", "图 8-4　分步精修向导（第 1/5 步）"),
    ("### 9.1 Rietveld 报告", "07_report_page.png", "图 9-1　报告页：报告预览 + 导出格式选择"),
]

CSS = """
:root { color-scheme: light; }
@page { size: A4 portrait; margin: 16mm 15mm 18mm 15mm; }
* { box-sizing: border-box; }
html { background: #ffffff; }
body { background: #ffffff; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 10pt; color: #222; line-height: 1.6; margin: 0; }
h1 { font-size: 26pt; color: #1a4f8b; margin: 0 0 8px 0; }
h2 { font-size: 16pt; color: #1a4f8b; border-bottom: 2.5px solid #1a4f8b; padding-bottom: 4px; margin: 0 0 14px 0; break-after: avoid; }
h3 { font-size: 12.5pt; color: #2a6db5; margin: 18px 0 6px 0; break-after: avoid; }
h4 { font-size: 11pt; color: #2a6db5; margin: 12px 0 4px 0; break-after: avoid; }
p { margin: 6px 0; }
.chapter { break-before: page; }
figure { margin: 10px 0 12px 0; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #d0d7e2; border-radius: 3px; }
figcaption { font-size: 9pt; color: #666; margin-top: 5px; }
blockquote { background: #eef5fd; border-left: 4px solid #2a6db5; padding: 7px 11px; margin: 9px 0; break-inside: avoid; }
blockquote p { margin: 3px 0; }
blockquote p:first-child { margin-top: 0; }
blockquote p:last-child { margin-bottom: 0; }
table { border-collapse: collapse; font-size: 9.5pt; width: 100%; margin: 8px 0; break-inside: avoid; }
th { background: #1a4f8b; color: #fff; padding: 5px 8px; border: 1px solid #9aa7b8; text-align: left; }
td { padding: 5px 8px; border: 1px solid #b9c2cf; vertical-align: top; }
tr:nth-child(even) td { background: #f4f7fb; }
code { background: #f0f2f5; font-family: Consolas, monospace; font-size: 9.5pt; padding: 0 3px; border-radius: 2px; }
pre { background: #f5f6f8; border: 1px solid #e2e5ea; padding: 8px 12px; margin: 8px 0; font-size: 10.5pt; break-inside: avoid; white-space: pre-wrap; word-wrap: break-word; }
pre code { background: none; padding: 0; font-size: 10pt; }
hr { border: none; border-top: 1px solid #d0d7e2; margin: 14px 0; }
a { color: #2a6db5; text-decoration: none; }
ul, ol { margin: 6px 0 6px 20px; padding: 0; }
li { margin: 3px 0; }
strong { color: #1a4f8b; }
em { color: #555; }
.cover { text-align: center; padding-top: 150px; break-after: page; }
.cover .sub { font-size: 13pt; color: #555; margin-top: 6px; }
.cover .badge { display: inline-block; margin-top: 26px; padding: 6px 22px; border: 1.5px solid #1a4f8b; border-radius: 18px; color: #1a4f8b; font-size: 11pt; }
.cover .foot { margin-top: 120px; color: #999; font-size: 10pt; }
"""

COVER_HTML = """<div class="cover">
<h1>PolyXRD 软件使用手册</h1>
<p class="sub">X 射线衍射物相分析 · 结构精修 · 多引擎集成</p>
<p class="sub">版本 v2.7.0 ｜ 2026 年 10 月</p>
<p class="badge">完整工作流：数据加载 → 预处理 → 峰检测 → 物相检索 → Rietveld 精修 → 报告</p>
<p class="foot">—— 内部配套文档 ——</p>
</div>
"""

TOC_HTML = """<div class="chapter">
<h2 id="toc">目录</h2>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch01"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 1 章</b>软件概述</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch02"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 2 章</b>安装与启动</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch03"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 3 章</b>主界面导览</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch04"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 4 章</b>数据加载与预处理</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch05"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 5 章</b>峰检测</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch06"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 6 章</b>物相检索匹配（Search/Match）</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch07"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 7 章</b>物相组合与勾选</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch08"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 8 章</b>结构精修（Rietveld）</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch09"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 9 章</b>报告与项目管理</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch10"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 10 章</b>基本原理</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch11"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 11 章</b>使用技巧与最佳实践</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch12"><b style="color:#1a4f8b;display:inline-block;width:70px;">第 12 章</b>常见问题（FAQ）</a></p>
<p style="margin:4px 0;font-size:11pt;"><a href="#ch13"><b style="color:#1a4f8b;display:inline-block;width:70px;">附录 A</b>v2.7.0 变更要点</a></p>
</div>
"""


def insert_figures(md_text: str) -> str:
    """Insert figure HTML after specific anchor lines in markdown."""
    for anchor, img_file, caption in FIGURES:
        img_path = IMG_DIR / img_file
        if not img_path.exists():
            continue
        # Use relative path from the HTML output location
        fig_html = (
            f'\n\n<figure><img src="img/{img_file}" style="width:96%">'
            f"<figcaption>{caption}</figcaption></figure>\n"
        )
        # Find the anchor line and insert figure after the next blank line
        idx = md_text.find(anchor)
        if idx < 0:
            continue
        # Find end of the anchor line
        eol = md_text.find("\n", idx)
        if eol < 0:
            continue
        # Insert after the paragraph following the heading
        # Find next blank line (end of first paragraph)
        para_end = md_text.find("\n\n", eol)
        if para_end < 0:
            insert_pos = eol + 1
        else:
            insert_pos = para_end + 2
        md_text = md_text[:insert_pos] + fig_html + md_text[insert_pos:]
    return md_text


def strip_md_metadata(md_text: str) -> str:
    """Remove the markdown header block (title, TOC) — we'll use HTML versions."""
    # Remove everything before the first "## 第 1 章"
    idx = md_text.find("## 第 1 章")
    if idx > 0:
        md_text = md_text[idx:]
    # Remove the old markdown TOC if present
    return md_text


def add_chapter_divs(html_body: str) -> str:
    """Add class='chapter' to h2 sections for page breaks + give each an id for PDF bookmarks."""
    # Replace <h2> with <div class="chapter"><h2 id="..."> and close before next <h2> or end
    parts = html_body.split("<h2>")
    if len(parts) <= 1:
        return html_body
    result = parts[0]
    for i, part in enumerate(parts[1:], 1):
        # 取标题文字 (去掉 </h2> 之前的所有标签) 作为书签标题
        title = re.sub(r"<[^>]+>", "", part.split("</h2>")[0]).strip()
        # 章节 id: ch01..ch13 (顺序即页序); 目录与附录一并编号
        cid = f"ch{i:02d}"
        if i == 1:
            # First h2 after cover+toc — already in a chapter div
            result += f'<div class="chapter"><h2 id="{cid}">' + part
        else:
            # Close previous chapter, start new one
            result += f'</div>\n<div class="chapter"><h2 id="{cid}">' + part
    result += "</div>"
    return result


def main():
    md_text = MD_PATH.read_text(encoding="utf-8")
    md_text = strip_md_metadata(md_text)
    md_text = insert_figures(md_text)

    # Convert markdown to HTML
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )

    # Post-process: convert blockquote > markers to styled divs
    # markdown already converts > to <blockquote>

    # Add chapter page breaks
    html_body = add_chapter_divs(html_body)

    # Assemble full HTML
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light">
<title>PolyXRD v2.7.0 软件使用手册</title>
<style>
{CSS}
</style>
</head>
<body>
{COVER_HTML}
{TOC_HTML}
{html_body}
</body>
</html>"""

    OUT_HTML.write_text(full_html, encoding="utf-8")
    print(f"HTML written: {OUT_HTML}")

    # 配图引用校验: 每张存在的图都应被引用一次, 否则说明 FIGURES 锚点失效
    html_text = full_html
    for _anchor, img_file, _cap in FIGURES:
        if (IMG_DIR / img_file).exists() and f"img/{img_file}" not in html_text:
            print(f"WARN: {img_file} 未被插入 HTML (锚点失效?)")

    # ── 校验所有配图锚点都命中 ──
    # 历史 bug: 锚点写成"精修完成后"而正文是"**完成后查看**", 匹配不到 →
    # 06_refinement_done.png 被静默跳过, 精修完成页配图整个丢失。
    for anchor, img_file, _cap in FIGURES:
        if not (IMG_DIR / img_file).exists():
            print(f"WARN: 配图缺失, 跳过: {img_file}")
            continue
        if anchor not in MD_PATH.read_text(encoding="utf-8"):
            print(f"WARN: 锚点未命中, {img_file} 不会插入 -> 请同步修改 FIGURES 中的 anchor")
    # 配图实际引用数校验 (html 生成后)

    edge_candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    edge = next((p for p in edge_candidates if p.exists()), None)
    if edge is None:
        print("ERROR: Microsoft Edge not found. Cannot convert to PDF.")
        sys.exit(1)

    # 先删旧 PDF: Edge 失败时不会覆盖, 若只判断"文件存在"会把上一次的
    # 旧 PDF 误报为本次产物 (2026-10-03 实踩: HTML 已更新但 PDF 时间戳未变)。
    # 注意: --headless=new 在本机 (Edge 1543) 能截图但 --print-to-pdf 静默失败,
    #      必须用旧版 --headless。
    if OUT_PDF.exists():
        OUT_PDF.unlink()

    attempts = [
        ["--headless", "--disable-gpu", "--no-pdf-header-footer"],
        # 备选: 旧版 headless + 更长虚拟时间预算 (图片多的页面需要)
        ["--headless", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=20000"],
        # 备选: headless=new
        ["--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=20000"],
    ]
    last_err = ""
    for flags in attempts:
        cmd = [str(edge), *flags, f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()]
        print(f"Trying: {edge.name} {' '.join(flags)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            last_err = "timeout after 120s"
            continue
        if OUT_PDF.exists() and OUT_PDF.stat().st_size > 100_000:
            print(f"PDF written: {OUT_PDF} ({OUT_PDF.stat().st_size} B)")
            break
        last_err = (result.stderr or result.stdout or "")[:300]
        if OUT_PDF.exists():
            OUT_PDF.unlink()
    else:
        print("PDF generation failed on all attempts")
        print(f"  last error: {last_err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
