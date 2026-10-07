# -*- coding: utf-8 -*-
"""Generate PolyXRD v2.7.0 Chinese user manual PDF with embedded screenshots."""
import os
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Image, Table, TableStyle, PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage

# ---------------------------------------------------------------------------
# Font registration
# ---------------------------------------------------------------------------
pdfmetrics.registerFont(TTFont('YaHei', 'C:/Windows/Fonts/msyh.ttc'))
pdfmetrics.registerFont(TTFont('YaHeiBold', 'C:/Windows/Fonts/msyhbd.ttc'))
pdfmetrics.registerFont(TTFont('SimHei', 'C:/Windows/Fonts/simhei.ttf'))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = 'D:/Project/XRD/PolyXRD'
SHOTS = os.path.join(ROOT, 'docs/manual/img')
OUTPUT = os.path.join(ROOT, 'docs/manual/PolyXRD使用手册-v2.7.0.pdf')

VERSION = '2.7.0'

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def make_styles():
    base = ParagraphStyle(
        'base', fontName='YaHei', fontSize=10.5, leading=16,
        textColor=colors.HexColor('#222222'), alignment=TA_JUSTIFY,
        spaceAfter=6
    )
    styles = {
        'title': ParagraphStyle(
            'title', parent=base, fontName='YaHeiBold', fontSize=26,
            leading=34, alignment=TA_CENTER, spaceAfter=18,
            textColor=colors.HexColor('#1a4f8b')
        ),
        'subtitle': ParagraphStyle(
            'subtitle', parent=base, fontSize=13, leading=20,
            alignment=TA_CENTER, textColor=colors.HexColor('#555555'),
            spaceAfter=60
        ),
        'h1': ParagraphStyle(
            'h1', parent=base, fontName='YaHeiBold', fontSize=18,
            leading=26, textColor=colors.HexColor('#1a4f8b'),
            spaceBefore=22, spaceAfter=10
        ),
        'h2': ParagraphStyle(
            'h2', parent=base, fontName='YaHeiBold', fontSize=14,
            leading=22, textColor=colors.HexColor('#2a6db5'),
            spaceBefore=16, spaceAfter=8
        ),
        'h3': ParagraphStyle(
            'h3', parent=base, fontName='YaHeiBold', fontSize=11.5,
            leading=18, textColor=colors.HexColor('#333333'),
            spaceBefore=12, spaceAfter=6
        ),
        'body': ParagraphStyle(
            'body', parent=base, alignment=TA_JUSTIFY, spaceAfter=6
        ),
        'caption': ParagraphStyle(
            'caption', parent=base, fontSize=9, leading=13,
            textColor=colors.HexColor('#666666'), alignment=TA_CENTER,
            spaceAfter=14
        ),
        'tip': ParagraphStyle(
            'tip', parent=base, fontSize=9.5, leading=14,
            textColor=colors.HexColor('#1a4f8b'),
            leftIndent=8, rightIndent=8,
            spaceBefore=6, spaceAfter=8
        ),
        'code': ParagraphStyle(
            'code', parent=base, fontName='Courier', fontSize=9,
            leading=13, textColor=colors.HexColor('#333333'),
            backColor=colors.HexColor('#f4f4f4'), leftIndent=8,
            spaceBefore=4, spaceAfter=4
        ),
        'toc': ParagraphStyle(
            'toc', parent=base, fontSize=11, leading=18,
            leftIndent=12, spaceAfter=2
        ),
        'toc1': ParagraphStyle(
            'toc1', parent=base, fontName='YaHeiBold', fontSize=12,
            leading=20, leftIndent=0, spaceAfter=2
        ),
    }
    return styles

STYLES = make_styles()

# ---------------------------------------------------------------------------
# Text helpers (escape XML + markdown-ish markup)
# ---------------------------------------------------------------------------
def esc(s):
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'`(.+?)`', r'<font face="Courier">\1</font>', s)
    return s


def P(text, style='body'):
    return Paragraph(esc(text.replace('\n', '<br/>')), STYLES[style])


def H1(text):
    return Paragraph(esc(text), STYLES['h1'])


def H2(text):
    return Paragraph(esc(text), STYLES['h2'])


def H3(text):
    return Paragraph(esc(text), STYLES['h3'])


def tip(text):
    return Table([[Paragraph(esc(text), STYLES['tip'])]],
                 colWidths=[16 * cm],
                 style=TableStyle([
                     ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef5fd')),
                     ('LEFTPADDING', (0, 0), (-1, -1), 8),
                     ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                     ('TOPPADDING', (0, 0), (-1, -1), 6),
                     ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                     ('LINEBELOW', (0, 0), (-1, -1), 3, colors.HexColor('#2a6db5')),
                 ]))


def warn(text):
    return Table([[Paragraph(esc(text), STYLES['tip'])]],
                 colWidths=[16 * cm],
                 style=TableStyle([
                     ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fdf3ee')),
                     ('LEFTPADDING', (0, 0), (-1, -1), 8),
                     ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                     ('TOPPADDING', (0, 0), (-1, -1), 6),
                     ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                     ('LINEBELOW', (0, 0), (-1, -1), 3, colors.HexColor('#d35400')),
                 ]))


def add_shot(story, filename, caption, max_width=16 * cm):
    path = os.path.join(SHOTS, filename)
    if not os.path.exists(path):
        story.append(P(f'[截图缺失: {filename}]', 'caption'))
        return
    with PILImage.open(path) as im:
        w, h = im.size
    aspect = h / w
    img_width = max_width
    img_height = img_width * aspect
    max_height = 22 * cm
    if img_height > max_height:
        img_height = max_height
        img_width = img_height / aspect
    story.append(Spacer(1, 0.2 * cm))
    story.append(Image(path, width=img_width, height=img_height))
    story.append(P(f'图：{caption}', 'caption'))


def make_table(data, col_widths=None, header=True):
    # data is list of rows; first row = header if header=True
    para_data = []
    for r, row in enumerate(data):
        para_row = []
        for cell in row:
            sty = 'body'
            if header and r == 0:
                sty = 'tip'  # reuse bold-ish; overwritten by table header style below
            para_row.append(Paragraph(esc(str(cell)), STYLES['body']))
        para_data.append(para_row)
    t = Table(para_data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ('FONTNAME', (0, 0), (-1, -1), 'YaHei'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('LEADING', (0, 0), (-1, -1), 13),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a4f8b')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'YaHeiBold'),
        ]
    t.setStyle(TableStyle(style))
    return t


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('YaHei', 9)
    canvas.setFillColor(colors.HexColor('#888888'))
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f'{doc.page}')
    canvas.drawString(2 * cm, 1.2 * cm, f'PolyXRD v{VERSION} 使用手册')
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------
def build_story():
    s = []

    # ---- Cover ----
    s.append(Spacer(1, 6 * cm))
    s.append(P('PolyXRD 使用手册', 'title'))
    s.append(P('X 射线粉末衍射物相分析 · 结构精修 · 多引擎集成', 'subtitle'))
    s.append(P(f'版本 v{VERSION} &nbsp;|&nbsp; 2026 年 10 月', 'subtitle'))
    s.append(Spacer(1, 2 * cm))
    s.append(tip('**说明：**本手册截图来自 PolyXRD v%s 中文界面，部分功能（如深色主题、多语言）在不同主题/语言下布局一致，仅文案语言不同。' % VERSION))
    s.append(PageBreak())

    # ---- TOC ----
    s.append(H1('目录'))
    toc_items = [
        ('第 1 章　软件概述', 'toc1'),
        ('第 2 章　安装与启动', 'toc1'),
        ('第 3 章　主界面导览', 'toc1'),
        ('第 4 章　数据加载与预处理', 'toc1'),
        ('第 5 章　峰检测', 'toc1'),
        ('第 6 章　物相检索匹配（Search/Match）', 'toc1'),
        ('第 7 章　物相组合与勾选', 'toc1'),
        ('第 8 章　结构精修（Rietveld）', 'toc1'),
        ('第 9 章　报告与项目管理', 'toc1'),
        ('第 10 章　基本原理', 'toc1'),
        ('第 11 章　使用技巧与最佳实践', 'toc1'),
        ('第 12 章　常见问题（FAQ）', 'toc1'),
        ('附录 A　v2.7.0 变更要点', 'toc1'),
    ]
    for text, style in toc_items:
        s.append(P(text, style))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 1
    # ===========================================================
    s.append(H1('第 1 章　软件概述'))
    s.append(H2('1.1 PolyXRD 是什么'))
    s.append(P(
        'PolyXRD 是一款 Windows 桌面 **多晶 X 射线衍射（XRD）数据分析软件**，目标是把"原始谱图 → 物相鉴定 → 结构精修 → 定量报告"的整条工作流集成在一个统一的中文/英文/日文三语言界面里，覆盖常规实验室的绝大多数分析需求。'
    ))
    s.append(P(
        'PolyXRD 不是某一个专业软件的替代品，而是"工作流整合器"：内部提供内置引擎做快速分析，同时可与 **FullProf、GSAS-II、MAUD** 等外部专业程序联动，把它们的强项纳入同一条流水线。'
    ))
    s.append(H2('1.2 核心能力一览'))
    s.append(make_table([
        ['模块', '能力'],
        ['数据处理', '多格式加载（.xy/.xye/.txt/.csv/.dat/.mdi/.raw/.xrdml/.brml 等）、扣背景（SNIP/线性/多项式）、平滑（Savitzky-Golay）、Kα2 剥离、归一化、角度裁剪、8 种格式互转'],
        ['峰检测', '自动寻峰（含肩峰识别、亚像素细化）、峰位/强度/半高宽输出、Kα2 自动检测'],
        ['物相检索', '多库检索匹配（内置矿物库 / COD 无机物 / COD 全库 / 用户自建库 / PDF2-2004）、四态元素过滤、FoM 打分排序、最小关联峰惩罚（B-7）、Profile Fitting 全谱匹配、残差峰搜索'],
        ['结构精修', '内置快速拟合 + GSAS-II / MAUD / PowerXRD / auto 四引擎桥接、快速/分步双向导、外部 FullProf 批处理、Le Bail 晶胞精修、内标法定量'],
        ['报告 / 项目', 'Rietveld 报告预览与导出（json/txt/csv/all）、项目保存/恢复、窗口布局记忆'],
    ]))
    s.append(Spacer(1, 0.3 * cm))
    s.append(tip(
        '**设计取向：**PolyXRD 的目标是用一条龙离线工作流覆盖常规实验室分析需求；与 Match!、JADE、FullProf Suite、MAUD、GSAS-II 等专业软件可互相配合使用，本软件可直接生成/导出它们可读的数据与控制文件。'
    ))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 2
    # ===========================================================
    s.append(H1('第 2 章　安装与启动'))
    s.append(H2('2.1 三种发行形态'))
    s.append(make_table([
        ['形态', '适用人群', '说明'],
        ['Setup 安装包 (.exe)', '普通用户（推荐）', '双击安装到本机，开始菜单生成快捷方式'],
        ['便携版 Portable (.zip)', '免安装 / U 盘场景', '解压即用，目录内含启动器与安全模式脚本'],
        ['单文件 exe', '快速分发 / 完全离线', '拷贝到任意 Windows x64 机器直接运行'],
    ]))
    s.append(H2('2.2 安装包（Setup）'))
    s.append(P(
        f'双击 `PolyXRD-Setup-v{VERSION}.exe` 启动安装向导。向导提供 **简体中文 / 繁體中文 / English / 日本語** 四种语言，系统语言为中文时自动选中中文。'
    ))
    s.append(P('**安装流程**：选择语言 → 选择安装位置（可选「为所有用户安装」）→ 选择附加任务（桌面图标）→ 安装 → 完成。'))
    s.append(tip(
        '**安装位置建议：**默认安装到**当前用户目录**（`%LOCALAPPDATA%\\Programs\\PolyXRD`），**无需管理员权限**。若要装到 `C:\\Program Files\\...` 等受保护目录，请在向导的「为所有用户安装」处勾选管理员安装。'
    ))
    s.append(tip(
        '**安装耗时：**安装包约 250 MB，解压后约 1.1 GB、上万个文件。「正在解压文件」阶段进度条推进较慢，**实测约 4～5 分钟**（机械硬盘更久），属正常现象，**勿中途关闭**。'
    ))
    s.append(H2('2.3 便携版（Portable）'))
    s.append(warn(
        '**最重要的一条：必须先「完整解压」，再运行。** 不要在压缩包内直接双击 `PolyXRD.exe`——Windows 会把文件解到临时只读目录，Qt 插件加载失败，典型表现是「窗口一闪就退出」。请右键压缩包 →「全部解压缩」，解到普通可写目录后再运行。'
    ))
    s.append(P('解压后的关键文件：`PolyXRD.exe`（主程序）、`启动 PolyXRD.bat`（推荐入口）、`安全模式启动.bat`（强制软件渲染）、`_internal\\`（运行时依赖库，请勿删除或改名）。'))
    s.append(P(
        '**启动自愈机制**：部分 Windows 11 / 显卡驱动组合下，主窗口在显示瞬间会触发 Qt 原生崩溃。软件采用跨启动自愈：若上一次启动未能存活，**本次自动切换到软件渲染**（日志里出现 `auto safe-render`）。若仍异常，请直接使用 `安全模式启动.bat`。'
    ))
    s.append(P('`PolyXRD.exe --diagnose` 打印运行环境；`--safe-render` 本次强制软件渲染；`--reset-render` 清除自愈状态。启动日志位于 `%USERPROFILE%\\.polyxrd\\logs\\startup-<日期>.log`。'))
    s.append(H2('2.4 数据库挂载（重要）'))
    s.append(P('主程序**不内置**大型衍射数据库——四个库各自独立打包、各自下载、各自挂载，只装其中一个也能正常使用。'))
    s.append(P('**挂载步骤**：1. 点击工具栏「数据库」图标打开数据库管理器；2. 对需要的库点「导入…」，选择对应的 `.sqlite` 文件；3. 显示「已挂载」即成功，路径会被记住，下次启动自动加载。'))
    add_shot(s, '09_database_manager.png', '2-1　数据库管理器：多库槽位独立挂载/卸载，用户库为第 6 项')
    s.append(make_table([
        ['数据源', '规模', '适用场景'],
        ['builtin 内置库', '118 种常见矿物/物相', '快速演示、教学、无数据库时'],
        ['cod_inorganics', '71,199 无机物相', '**日常推荐**（瘦身索引式，d-I 预计算 + Hanawalt 预筛，速度最快）'],
        ['cod_full', '113,223 条 CIF', '需要覆盖全化合物空间'],
        ['user 用户自建库', '用户自定', '导入自己收集的 CIF / 私有物相，与 COD 同构、可检索可精修'],
        ['pdf2', '163,834 物相', '有 ICDD 正版授权时（卡片信息最全）'],
    ]))
    s.append(warn('⚠️ PDF2-2004 数据库为 ICDD 版权数据，请确认已获得正版授权后再挂载使用。'))
    s.append(H2('2.5 用户自建数据库（v2.6.0 新增）'))
    s.append(P(
        '除官方分发的大型库外，PolyXRD 支持把你**自己收集的 CIF 或私有物相**建成一个与 COD 无机物库**同构**的本地库，挂载后即可像官方库一样检索与精修。'
    ))
    s.append(P('**构建方式**：使用配套工具把 CIF 批量灌入一个 SQLite（与 COD 无机物库 schema 一致，含 d-I 峰表预计算）。'))
    s.append(P('**挂载与管理**：数据库管理器新增「用户库」槽位，导入该 `.sqlite` 即出现在物相源下拉的 **第 6 项 `user`**；检索时可在源选择里勾选 `user`，与 builtin / COD 等并列参与检索；用户库条目与官方库共用同一套检索/打分/精修链路。'))
    s.append(tip('用户库的引用以 `Phase.db_id` 字段回溯，展示名中的数字（如 `USER-000001`）**不是** COD ID，请勿当作 COD 编号处理。'))
    s.append(H2('2.6 界面语言'))
    s.append(P('界面默认中文，可在状态栏右下角切换语言（中文 / English / 日本語），切换立即生效。'))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 3
    # ===========================================================
    s.append(H1('第 3 章　主界面导览'))
    s.append(P('主窗口布局：**顶部工具栏 + 四标签页 + 左侧参数面板 + 右侧停靠窗口**。'))
    s.append(make_table([
        ['区域', '内容'],
        ['顶部工具栏', '打开/保存、扣背景、平滑、剥 Kα2、峰检测、传统 Search/Match、Profile Fitting、Rietveld 精修、精修向导、COD 检索、导出、数据库管理'],
        ['左侧参数面板', '当前标签页的参数（波长、背景方法、峰检测阈值等）'],
        ['标签页 × 4', '数据 / 物相分析 / 结构精修 / 报告'],
        ['右侧停靠窗口', '物相列表（矿物名/化学式两个页签，勾选集驱动精修页）'],
        ['状态栏', '精修状态、最佳匹配物相、语言与波长信息'],
    ]))
    add_shot(s, '01_main_data_empty.png', '3-1　主窗口总览：工具栏、数据页签、左侧面板、中央谱图区、右侧物相列表')
    s.append(H2('3.1 数据页谱图主导布局（v2.6.0）'))
    s.append(P(
        '数据页改为「谱图为主」的三向分隔布局——中央大谱图 + 可收起的预处理/峰检测参数面板 + 峰表。面板收起钮可把空间让给谱图，峰表与谱图联动高亮。'
    ))
    s.append(H2('3.2 谱图交互'))
    s.append(P(
        '**滚轮缩放**：以光标为中心缩放；**左键拖拽**：平移谱图；**单击峰位**：弹出峰信息；**工具栏 Home 键**：一键复位到数据全览；**右键谱图**：可调整 Y 轴缩放模式、显示峰标记等。'
    ))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 4
    # ===========================================================
    s.append(H1('第 4 章　数据加载与预处理'))
    s.append(H2('4.1 加载数据'))
    s.append(P('点击工具栏「打开」或菜单 **文件 → 打开数据**，选择谱图文件。支持 `.xy/.xye/.txt/.csv/.dat`（两列/三列文本，自动跳过 `#`/`!` 注释行）、`.mdi/.raw`、`.xrdml/.brml/.xml`、`.json`。'))
    s.append(tip('若加载后衍射峰位置整体偏移，请检查「波长」参数（默认 Cu Kα1 1.5406 Å）是否与实验条件一致；修改后重新加载。'))
    s.append(H2('4.2 预处理步骤（建议顺序）'))
    s.append(make_table([
        ['步骤', '入口', '作用与原理'],
        ['① 扣背景', '工具栏「扣背景」/ 左侧面板选方法', '去除空气散射、荧光、样品台散射等缓变背景。SNIP 算法对晶面密集、背景起伏复杂的谱最稳健'],
        ['② 平滑', '左侧面板「平滑方法」', 'Savitzky-Golay 卷积在去噪的同时保留峰形（窗口宽度 11 点为常用起点）'],
        ['③ 剥 Kα2', '工具栏「剥 Kα2」', '按 Kα2/Kα1 ≈ 0.5 强度比逐点剥除 Kα2 贡献，使后续检索基于单色峰位'],
        ['④ 归一化 / 裁剪', '左侧面板', '强度归一到 0–100 或最大值 100；裁掉低信噪比区段（如 <15° 或 >100°）'],
    ]))
    s.append(H2('4.3 保存、导出与格式转换'))
    s.append(P('菜单 **文件 → 保存/导出**：将处理后的谱保存为文本格式，供 FullProf、GSAS-II、MAUD 等外部程序直接读取。菜单 **文件 → 谱图格式转换**：在 `xy / txt / dat / csv / mdi / raw / xrdml / json` 共 8 种格式之间互转。'))
    add_shot(s, '02_data_loaded.png', '4-1　数据视图：加载样品后的衍射谱与预处理面板')
    add_shot(s, '10_format_convert.png', '4-2　谱图格式转换：选择源文件、目标格式、输出路径后一键转换')
    s.append(PageBreak())

    # ===========================================================
    # Chapter 5
    # ===========================================================
    s.append(H1('第 5 章　峰检测'))
    s.append(H2('5.1 操作'))
    s.append(P('切到「物相分析」标签，点击工具栏「峰检测」（或左侧面板调阈值后自动运行）。'))
    s.append(H2('5.2 参数说明'))
    s.append(make_table([
        ['面板项', '默认值', '说明'],
        ['最小峰高 (%)', '5', '峰高相对于最强峰的最小百分比'],
        ['最小距离', '0.5°', '两峰之间的最小 2θ 间距（防重复检测）。建议设 0.2~1.0；设得过大（如 5°）会丢弃间距近的强线，损害物相识别召回'],
        ['高精度(背景扣除+亚步长)', '关', '勾选后自动背景扣除 + 亚步长峰位精修 + 重叠峰联合拟合，峰位精度可达 ~0.001°'],
    ]))
    s.append(P('面板按钮：**「检测峰」** 执行常规检测，**「拟合峰」** 对已检出的峰做局部拟合精修峰位。'))
    s.append(tip('检出判据本身是「峰高须 > 3 × 局部噪声 σ」（内部参数），因此弱峰的检出主要靠降低「最小峰高」或开启「高精度」。'))
    add_shot(s, '03_phase_peaks.png', '5-1　峰检测结果：谱图上标记检出峰位，峰表列出 2θ、d、强度、FWHM')
    s.append(H2('5.3 原理与技巧'))
    s.append(P(
        '峰检测分两步：① **检出**：估计局部噪声 σ，取「峰高 > 3σ 且 ≥ 最小峰高%」的点为候选；② **精修**：对每个候选峰做局部拟合得到亚像素精度的峰位。勾选「高精度」时先自动扣除背景再走上述流程，肩峰分离与峰位精度显著提升。'
    ))
    s.append(tip('**峰太多**（噪声误检）→ 提高最小高度；**峰太少**（弱峰漏检）→ 降低阈值或开启高精度；**峰检测是检索匹配的输入**，峰位不准会直接拉低匹配度，务必在检索前肉眼复核。'))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 6
    # ===========================================================
    s.append(H1('第 6 章　物相检索匹配（Search/Match）'))
    s.append(H2('6.1 两种检索模式'))
    s.append(make_table([
        ['模式', '入口', '原理', '适用场景'],
        ['传统 Search/Match', '工具栏「传统 Search/Match」', '基于检出的峰位/强度列表与数据库标准卡片做 FoM 打分匹配', '常规检索，速度快'],
        ['Profile Fitting', '工具栏「Profile Fitting」', '不依赖寻峰，直接用全谱与候选相合成谱做形态拟合（PFSM）', '峰严重重叠、弱峰多的样品'],
    ]))
    s.append(H2('6.2 FoM（匹配因子）打分原理'))
    s.append(P('FoM（Figure of Merit）是检索匹配的核心评分，**越低越好**。它综合考量峰位漏检率、强度不一致、强峰命中率惩罚与特异性项。'))
    s.append(P('• **峰位匹配**：在容差角（默认 ±0.15°）内，参考峰与实测峰逐一配对。'))
    s.append(P('• **强度加权**：强度越大的峰权重越高（v2.1 起改为强度加权口径）。'))
    s.append(P('• **可观测性下限**（v2.3）：参考强度 < 最强峰 10% 的弱线不计入漏检罚分。'))
    s.append(P('• **最小关联峰惩罚**（v2.5 B-7）：匹配峰 < 2 的候选，FoM ×2——抑制窄窗口偶然匹配的假阳性。'))
    s.append(H3('v2.7.0 的 FoM 解耦（重要变更）'))
    s.append(P('v2.7.0 对 FoM 的内部计算做了**显式解耦**，把"位置偏差"与"漏检惩罚"拆成两条独立加权项，并新增可观测字段：'))
    s.append(P('`bad = bad_pos + _FOM_MISS_WEIGHT · bad_miss`；`bad_pos = Σ(权重·位置偏差) / Σ权重`；`bad_miss = Σ(权重·漏检) / Σ权重(可见参考峰)`。'))
    s.append(P('• **`_FOM_MISS_WEIGHT`（默认 1.0）**：漏检项的独立权重。默认 1.0 在数值上**完全等价于 v2.6.0 的旧行为**（零回退），把它单独提出来是为让"漏检惩罚强度"成为可独立调节的旋钮。'))
    s.append(P('• **`_FOM_SPEC_WEIGHT` 0.30 → 0.50**：特异性项（真实物相的谱形自洽度）权重上调，是 v2.7.0 **唯一带来净正收益**的改动——B 级 top10 由 44/49（90%）提升到 **45/49（92%）**，A 级与组合指标零回退；0.55 起组合指标反而退化，故 0.50 为最优点。'))
    s.append(P('• **`FoMResult` 新增字段**：`position_dev` / `miss_penalty` / `spec_penalty`，便于逐候选诊断 FoM 拆解。'))
    s.append(tip('诊断工具：随仓库 `scripts/diag_recall_breakdown.py` 可输出每个候选的 `bad / unexp / ic / matched / missed / s*` 逐项分解，配合 `scripts/bench_fom_ablation.py` 消融仪可在 13 试样上快速验证任何 FoM 参数改动。'))
    s.append(H2('6.3 检索质量增强（v2.5/v2.6 特性）'))
    s.append(H3('B-7：最小关联峰惩罚（默认启用）'))
    s.append(P('窄 2θ 窗口内只有 1 条参考峰能对上实测峰时偶然匹配概率高。v2.5 对匹配峰数 < 2 的候选施加 **FoM ×2** 惩罚（而非直接淘汰，避免误杀高对称少峰相如 Zircon）。**这是 v2.5 全部收益的来源**：组合相级 +3、试样级 +2、检索 B 级 top10 +2。'))
    s.append(H3('B-6：逐候选零点自适应校正（默认关闭）'))
    s.append(P('对每条候选在小网格上扫描 2θ 零点偏移，取最优 FoM。两道护栏：幅度 |dz| ≤ 0.15°；改善阈值 dz≠0 的 FoM 须比 dz=0 好 > 10% 才采用。⚠️ 13 试样消融实测为**净负**，默认关闭；参数 `fom_zero_grid` 保留供零点漂移明显的谱按需开启。'))
    s.append(H3('B-5：PFSM 全谱拟合重排（默认关闭）'))
    s.append(P('改用 **ΔRwp（Rwp 下降量）** 作为重排指标 + 双过滤（`delta_rwp < 0.5%` 伪阳性不进；`scale < 0.02` 微量不进）。默认关闭（B 级 MISS 2→3）。**PFSM 只适合做复核**，不适合参与默认排序。'))
    s.append(H3('B-4：择优取向（PO）感知评分（默认启用）'))
    s.append(P('对参考峰密集（≥80 线）的候选做 March-Dollase `r` 网格搜索（织构轴 [001]）。护栏：`_FOM_PO_MIN_REFS = 80`；`_FOM_PO_IMPROVE_FRAC = 0.10`。'))
    s.append(H2('6.4 四态元素过滤'))
    s.append(make_table([
        ['类别', '判定式', '含义'],
        ['必有 (must_have)', 'P ⊆ S', '每个必有元素都必须出现（AND，全部必含）'],
        ['含有 (has)', 'S ∩ H ≠ ∅', '物相至少含其中一个元素'],
        ['可能 (maybe)', '无强制条件', '仅放宽允许池；H 为空时「可能」代行 H 之职'],
        ['没有 (exclude)', 'S ∩ E = ∅', '含任一"没有"元素即淘汰'],
    ]))
    s.append(tip('**闭环规则**：当「必有 ∪ 含有 ∪ 可能」非空时，**未勾选的元素一律视为「没有」**。三者全空时不启用闭环 = 全库搜索。**示例**：已知含 Si、O、Al、Fe，勾必有 Si、O，含有 Al、Fe → 候选必须同时含 Si 和 O，且至少含 Al 或 Fe 中的一个。'))
    s.append(H2('6.5 残差峰搜索（v2.5 新功能）'))
    s.append(P('**迭代式物相分析**：先确认主相，再对未解释的峰追查残余微量相。在候选列表上**右键 →「仅对未解释峰再搜索…」**，软件计算已选相覆盖、提取残差峰、仅对这些残差峰重新检索。另一个入口：在峰归属表中选中若干行后右键 →「仅对标记峰再匹配…」。'))
    add_shot(s, '04_phase_identified.png', '6-1　物相检索结果：候选列表按 FoM 排序，谱图叠加参考峰位')
    add_shot(s, '11_cod_search.png', '6-2　COD 在线检索：按化学式/矿物名/空间群联网查询')
    s.append(H2('6.6 数据库选择'))
    s.append(make_table([
        ['数据源', '规模', '速度', '适用场景'],
        ['builtin', '118 相', '极快', '演示、教学'],
        ['cod_inorganics', '71,199 相', '最快', '日常推荐'],
        ['cod_full', '113,223 相', '中', '全化合物空间'],
        ['user', '用户自定', '中', '私有物相、自己收集的 CIF'],
        ['merged', '内置 + COD 全库', '中', '高召回'],
        ['pdf2', '163,834 相', '中', '有正版授权时'],
    ]))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 7
    # ===========================================================
    s.append(H1('第 7 章　物相组合与勾选'))
    s.append(H2('7.1 勾选物相'))
    s.append(P('在候选列表**勾选**可信物相（可多选）。勾选集会实时同步到主窗口右侧「物相列表」停靠窗、精修页右栏「已选物相」列表、项目文件。右键菜单：导出 CIF、查看详情、搜索未解释峰。'))
    s.append(H2('7.2 自动组合建议（精修组合）'))
    s.append(P('软件提供 `build_refinement_combination` 自动从候选中选出**最优物相组合**用于精修，基于分支定界（B&B）全局搜索：每个候选映射为命中实测峰的掩码，以联合覆盖最多实测峰为目标做全局搜索。'))
    s.append(P('**质量增强项**：自解释率缩放（S14b）让覆盖毯相贡献塌缩；FoM 质量缩放（E1）；池保底回收（E2）；纯金属约束。'))
    s.append(tip('**说明**：E1/E2 经 13 试样消融验证为**中性基础设施**（开启/关闭结果不变）。组合结果的真实改善来自 B-7 最小关联峰惩罚，组合相级从 42/49 提升到 45/49、试样级从 8/13 提升到 10/13。'))
    s.append(H2('7.3 元素约束的作用'))
    s.append(P('引入元素约束后组合质量显著提升：检索阶段化学上不合理的候选被直接过滤；组合阶段"覆盖毯相"不再挤占组合位；弱线真相得以入选。**有元素信息时务必使用元素过滤**——这是提升组合准确率最有效的手段。'))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 8
    # ===========================================================
    s.append(H1('第 8 章　结构精修（Rietveld）'))
    s.append(H2('8.1 Rietveld 精修原理（30 秒版）'))
    s.append(P('Rietveld 法不用单个峰的积分强度，而是用结构模型**逐点计算整张衍射谱**并与实测谱做最小二乘拟合。可精修：标度因子（→物相含量）、晶胞参数（→峰位）、峰形参数、零点偏移、背景多项式、原子坐标与占位。'))
    s.append(P('拟合质量：`R_wp = √( Σ w_i(y_obs,i − y_calc,i)² / Σ w_i·y²_obs,i )`；`GOF (S) = R_wp / R_exp`。合格参考：常规实验室数据 R_wp < 15%、GOF ≈ 1~3。'))
    s.append(warn('**口径铁律**：默认 Poisson 统计权重后，**加权 wR 与旧版「单位权 wR」不可直接比较**。跨版本/跨软件比较 wR 时务必声明口径。'))
    s.append(H2('8.2 快速精修（精修页）'))
    s.append(P('**操作顺序**：1. 确认「已选物相」列表非空；2. 右栏「精修控制」选引擎/策略/循环数/峰形/背景；3. 点「开始精修」。完成后查看模拟谱叠加、残差图、Rwp/GOF、物相质量分数与晶胞参数、底部日志。'))
    add_shot(s, '05_refinement_page.png', '8-1　结构精修页：谱图/残差分栏、右侧控制/结果/含量/外部引擎面板')
    add_shot(s, '06_refinement_done.png', '8-2　精修完成：模拟谱叠加与残差条')
    s.append(H2('8.3 精修引擎'))
    s.append(make_table([
        ['引擎', '性质', '说明'],
        ['auto（推荐）', '自动选择', '按本机安装情况在 gsas2/maud/builtin 间自动择优'],
        ['builtin', '内置快速拟合', '零依赖、秒级完成；快速验证物相组合。**注意：不计算结构因子**，R_wp 偏高属预期'],
        ['gsas2', 'GSAS-II 桥接', '调用本机 GSAS-II 安装，出标准 Rietveld 结果与 wt%'],
        ['maud', 'MAUD 批处理', '生成 .par + .xye，批处理跑完回读结果'],
        ['powerxrd', '轻量开源引擎', '轻量备选'],
    ]))
    s.append(H2('8.4 精修向导（两条独立路径）'))
    s.append(P('与精修页快速精修互为独立路径、结果互不覆盖：**① 快速向导（单页）** 一个对话框内配好引擎/策略/循环数/波长/2θ 范围，点「确定」即启动；**② 分步精修向导（五步）** 选择数据 → 选择物相 → 配置参数 → 预览 → 执行，比快速版多了模板参数管理、CIF 导入与 COD 检索。'))
    add_shot(s, '08_refine_wizard.png', '8-3　快速精修向导：单页配置引擎/策略/循环数')
    add_shot(s, '08b_refine_wizard_steps.png', '8-4　分步精修向导：五步流程')
    s.append(H2('8.5 精修质量指标'))
    s.append(make_table([
        ['指标', '含义'],
        ['wR（加权 R_wp）', '加权轮廓 R，默认使用 Poisson 统计权重'],
        ['R_exp', '期望 R，权重正确后才可解读（w = 1/σ²）'],
        ['GOF (S)', 'R_wp/R_exp，理想值接近 1'],
        ['R_p', '轮廓 R（Σ|Δy|/Σy）'],
    ]))
    s.append(P('质量分级（实验室粉末 XRD 口径）：**< 5 优秀 / < 10 良好 / < 15 一般 / < 25 差 / ≥ 25 需改进**。'))
    s.append(H2('8.6 峰形、背景与峰位物理'))
    s.append(make_table([
        ['项', '说明'],
        ['峰形面积归一', '峰形函数改为面积归一（∫PV = 1），峰宽参数才具备可解释性'],
        ['背景进入拟合', '背景不再「开头估一次即冻结」，默认对背景做 Chebyshev 多项式抛光（6 阶），仅在更优时采纳'],
        ['样品位移', '可精修样品位移（Δ2θ = −2s·cosθ），修正由样品偏心引起的峰位系统偏移'],
        ['低角不对称（可选）', 'split pseudo-Voigt，用于低角区轴向发散导致的峰形不对称'],
        ['全晶胞参数模式（可选）', '由 a/b/c/α/β/γ 直接精修峰位'],
        ['Kα2 双线检测', '自动判断数据中是否存在未剥离的 Kα2，命中则警告先剥 Kα2 再精修'],
    ]))
    s.append(H2('8.7 精修策略与收敛技巧'))
    s.append(P('**分步放开参数**比一次全放开稳健：第一轮只精修标度因子 + 背景；第二轮加入晶胞参数；第三轮加入峰形参数（U/V/W/η）；第四轮加入原子坐标/占位/温度因子。'))
    s.append(H2('8.8 外部精修程序'))
    s.append(P('精修页右栏底部为三行外部程序面板（状态灯 / 路径 / 浏览 / 检测 / 启动）：**FullProf** 批处理精修（一键生成 .dat/.pcr → fp2k → 回读）；**GSAS-II** 拉起 GUI；**MAUD** 拉起 GUI。工作目录固定为 `~/.polyxrd/external_runs/<时间戳>/`（全 ASCII）。'))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 9
    # ===========================================================
    s.append(H1('第 9 章　报告与项目管理'))
    s.append(H2('9.1 Rietveld 报告'))
    s.append(P('「报告」标签实时生成精修报告预览：精修质量指标（wR/GOF/质量等级）、物相列表（化学式 / 质量分数 / 晶胞 / 晶胞体积 / 物相总含量）。可导出 **json**（机器可读）、**txt**、**csv**，或选择 **all** 一次导出全部。'))
    add_shot(s, '07_report_page.png', '9-1　报告页：生成报告预览并选择 json/txt/csv 等格式导出')
    s.append(tip('导出为文本/表格格式（便于 Excel、Python、R 作图脚本继续处理）。需要排版好的 PDF 报告时，请用「打印」功能（Ctrl+P）另存为 PDF。'))
    s.append(H2('9.2 项目保存/恢复'))
    s.append(P('菜单 **文件 → 保存项目 / 打开项目**。项目文件（`.polyxrd` JSON）记录：数据文件路径、处理参数、峰列表、物相勾选集、精修结果与参数。换机或重开软件后可完整还原工作现场。'))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 10
    # ===========================================================
    s.append(H1('第 10 章　基本原理'))
    s.append(H2('10.1 Bragg 定律与衍射位置'))
    s.append(P('晶面间距 d 的晶面族在入射角 θ 处产生相长干涉：`2d·sinθ = n·λ`。测得一系列 2θ 峰位、已知波长 λ，即可反推各晶面的 d 值序列——这是物相"指纹"比对的物理基础。'))
    s.append(H2('10.2 衍射强度'))
    s.append(P('各 (hkl) 衍射的积分强度由结构因子 |F_hkl|²、多重性因子 m、洛伦兹-偏振因子 LP、温度因子 e^(−B·sin²θ/λ²) 共同决定。强度分布是第二重指纹，也是 Rietveld 定量相分析的依据。'))
    s.append(H2('10.3 检索匹配（Search/Match）'))
    s.append(P('传统流程 = **Hanawalt**（以最强 3 峰的 d 值组合查索引）+ **Fink**（8 强峰）+ 逐峰容差匹配与强度相关打分。PolyXRD 对数据库预先计算 d-I 峰表并建立强峰索引，检索时先粗筛再精排（FoM），在十万级卡片上实现秒级响应。'))
    s.append(H2('10.4 背景与峰形'))
    s.append(P('**SNIP 背景算法**：对谱反复做「局部最小 → 裁剪」的尺度递归，把快变峰"削"掉只留慢变背景。峰形用 pseudo-Voigt（Gaussian 与 Lorentzian 线性组合，混合系数 η）描述；峰宽随角度变化用 **Caglioti 公式** `FWHM² = U·tan²θ + V·tanθ + W`。'))
    s.append(H2('10.5 择优取向（PO）'))
    s.append(P('层状/链状硅酸盐在压片制样时晶片倾向于平行排列，导致某些晶面衍射强度系统性偏离。March-Dollase 模型用 `r` 描述取向程度：`r = 1.0` 无取向；`r < 1` [001] 平行晶面增强；`r > 1` [001] 垂直晶面增强。'))
    s.append(H2('10.6 Rietveld 定量原理'))
    s.append(P('物相的质量分数由精修得到的标度因子计算：`wt%_i = (S_i · Z_i · M_i · V_i) / Σ_j (S_j · Z_j · M_j · V_j)`，其中 S = 标度因子，Z = 晶胞内化学式单元数，M = 摩尔质量，V = 晶胞体积。这是 Rietveld 法能同时定性 + 定量的核心。'))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 11
    # ===========================================================
    s.append(H1('第 11 章　使用技巧与最佳实践'))
    s.append(H2('11.1 数据预处理顺序'))
    s.append(P('**正确顺序**：加载 → 扣背景 → 平滑 → 剥 Kα2 → 归一化 → 裁剪。不要先平滑再扣背景：平滑会把峰的边缘"抹"到背景里，导致 SNIP 估高背景。'))
    s.append(H2('11.2 检索匹配最佳实践'))
    s.append(P('1. **先用元素过滤**：已知元素时务必设置，可排除 90% 以上的假阳性；2. **从 cod_inorganics 开始**：速度最快；3. **结合峰位标记复核**；4. **弱峰多的样品**：尝试 Profile Fitting；5. **迭代分析**：先确定主相 → 残差峰搜索。'))
    s.append(H2('11.3 精修最佳实践'))
    s.append(P('1. **物相组合先验证**：用 builtin 引擎快速跑一轮；2. **分步放开参数**：scale+bg → cell → peak shape → atomic；3. **R_wp 先看趋势再看绝对值**；4. **定量结论用标准引擎**：gsas2/maud/fullprof；5. **Kα2 必须先剥离**。'))
    s.append(H2('11.4 常见数据问题与对策'))
    s.append(make_table([
        ['问题', '对策'],
        ['峰位整体偏移', '检查波长参数；检查样品是否偏心（精修样品位移）'],
        ['背景很高且不平', '改用 SNIP 扣背景；增大 SNIP 窗口'],
        ['弱峰被噪声淹没', '先平滑（SG 窗口 11-15）再检测；降低相对高度阈值'],
        ['峰严重重叠', '开启高精度峰检测；或用 Profile Fitting'],
        ['强度系统性偏差', '考虑择优取向（层状硅酸盐）；换一张同物相的卡片'],
    ]))
    s.append(H2('11.5 提高组合准确率的关键'))
    s.append(P('1. **元素过滤是第一位的**；2. **峰检测质量**——峰位不准会拉低所有候选匹配度；3. **多数据库交叉验证**；4. **残差峰搜索**——主相确定后追查残余微量相。'))
    s.append(PageBreak())

    # ===========================================================
    # Chapter 12
    # ===========================================================
    s.append(H1('第 12 章　常见问题（FAQ）'))
    qa = [
        ('Q1：便携版双击后窗口一闪就退出？',
         '按顺序排查：① 是否完整解压后运行（切勿在压缩包内直接运行）；② 改用 `启动 PolyXRD.bat`；③ 若仍异常，改用 `安全模式启动.bat`；④ 跨启动自愈通常会在第二次启动时切到软件渲染；⑤ 查看 `%USERPROFILE%\\.polyxrd\\logs\\startup-<日期>.log`。'),
        ('Q2：物相检索没有结果 / 结果很差？',
         '按顺序检查：① 是否已挂载数据库（含用户自建库）；② 峰检测是否合理；③ 是否应开启元素过滤；④ 波长是否正确；⑤ 尝试换数据库（builtin → cod_inorganics → user → merged）。'),
        ('Q3：builtin 精修 wR 很高？',
         'builtin 是内置快速峰形拟合引擎，不计算结构因子，用于快速验证物相组合。定量结论请改用 gsas2 / maud / auto，或使用外部 FullProf 批处理精修。'),
        ('Q4：wR 比上一版"变大"了？',
         'v2.0.0 起默认启用 Poisson 统计权重，加权 wR 与旧版单位权口径**不可直接比较**。请以同一版本、同一口径下的前后对比为准。'),
        ('Q5：外部程序状态灯是红色？',
         '点该行「检测」自动探测；仍不行则「浏览…」手动指定（FullProf 选 fp2k.exe；GSAS-II 选其自带 python.exe；MAUD 选安装根目录或 java.exe）。'),
        ('Q6：精修不收敛 / 发散？',
         '常见原因：物相初始晶胞错误；标度因子量级差太多；背景方法不当；数据噪声过大；Kα2 未剥离。分步放开参数比一次全放开稳健。'),
        ('Q7：精修结果里物相含量加起来不是 100%？',
         '先确认是否所有已识别晶相都加入了精修——若存在未纳入的非晶相或未识别晶相，总含量自然不足 100%，属正常现象。内置引擎给出的是相对含量（以已纳入相归一），如需绝对含量建议改用 GSAS-II / MAUD / FullProf。'),
        ('Q8：元素过滤怎么设置？',
         '在物相分析页左侧面板找到元素过滤区。四态含义：必有（全部必须含）、含有（至少含一个）、可能（允许出现）、没有（必须不含）。未勾选的元素在闭环规则下视为"没有"。'),
        ('Q9：残差峰搜索怎么用？',
         '先在候选列表勾选已确认的主相，然后右键 →「仅对未解释峰再搜索…」。若在峰归属表里手动选中若干可疑峰，则用「仅对标记峰再匹配…」只对这几行重新检索。'),
        ('Q10：用户自建库怎么建？',
         '把收集到的 CIF 用配套工具批量灌入一个与 COD 无机物库同构的 SQLite（含 d-I 峰表预计算），再在数据库管理器的「用户库」槽位导入即可。用户库物相与官方库共用检索/精修链路。'),
        ('Q11：窗口布局乱了？',
         '窗口状态损坏时旧布局会被自动作废重建；也可删除 `~/.polyxrd` 下的布局配置重置。'),
    ]
    for q, a in qa:
        s.append(H3(q))
        s.append(P(a))

    s.append(Spacer(1, 1 * cm))
    s.append(P('— 手册结束 · PolyXRD v%s —' % VERSION, 'caption'))

    return s


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def main():
    story = build_story()
    doc = BaseDocTemplate(
        OUTPUT,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin + 1 * cm,
        doc.width, doc.height - 1.2 * cm,
        id='normal'
    )
    template = PageTemplate(id='all', frames=frame, onPage=footer)
    doc.addPageTemplates([template])
    doc.build(story)
    print(f'Generated: {OUTPUT}')


if __name__ == '__main__':
    main()
