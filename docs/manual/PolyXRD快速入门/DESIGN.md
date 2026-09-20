# DESIGN.md — PolyXRD 快速入门 v0.15.0

## 画布与母版（1280×720）
- **A 标题块**：y 0–120px，标题 36px bold #0B3C6E；步骤页在标题前加绿色步骤徽标（44px 圆角方块白字数字）。
- **B 内容区**：y 120–660px，左右 padding 60px。
- **C 页脚条**：y 660–720px，左「PolyXRD v0.15.0 快速入门」14px #8A94A6，右页码 `NN / 8`。
- 封面 / 结束页自定义版式。

## 色彩池（≤4 hex，与《使用手册》同源便于品牌统一）
| 角色 | hex | 用途 |
|---|---|---|
| 主色 | #0B3C6E | 标题、封面底、色块 |
| 辅色 | #E8F0F8 | 卡片底、步骤条底 |
| 强调色 | #2F8F4E | 步骤徽标、锚点数字、完成态 |
| 中性色 | #333333 / #8A94A6 | 正文 / 页脚 |

面积：主色 ≤60%、辅色 ≤30%、强调色 ≤10%（P6 peak 可 15%）。渐变 `linear-gradient(135deg,#0B3C6E,#1A5FA0)` 仅封面/结束页；封面截图叠 `rgba(6,30,60,0.55)` 蒙版。

## 字体
思源黑体（fallback Microsoft YaHei）；封面 64px、页标题 36px、步骤徽标数字 24px、锚点 96px、正文 20px、页脚 14px。

## 配图清单（material 来源，已核对：软件实拍截图，中文 UI 清晰）
| 文件 | 内容 | 使用页 | 等级 |
|---|---|---|---|
| 01_main_data_empty.png | 主窗口空态 | P1 | L1(蒙版全幅) |
| 02_data_loaded.png | 数据装载后 | P3 | L1 |
| 03_phase_peaks.png | 找峰结果 | P4 | L1 |
| 04_phase_identified.png | 物相鉴定 | P5 | L1 |
| 06_refinement_done.png | 精修完成 | P6 | L2 |
| 07_report_page.png | 报告页 | P7 | L2 |

截图统一 1px #C5D5E8 边框 + 8px 圆角。

## 页面映射表
| # | 文件 | 类型 | 角色 | 版式 | L1 文件 | 字数 | 留白% | 色彩分配 | 关键约束 |
|---|---|---|---|---|---|---|---|---|---|
| 01 | 01.slide | cover | hero | 全屏视觉+骑线文字 | 01_main_data_empty.png | 25 | 35% | 主色55%蒙版 | 白字骑线 |
| 02 | 02.slide | content | transition | 流程步骤条 | Diagram | 90 | 30% | 辅色30% | 五步横向箭头 |
| 03 | 03.slide | content | supporting | 左大图+右侧文字 | 02_data_loaded.png | 150 | 25% | 辅色25% | 图左58% |
| 04 | 04.slide | content | supporting | 上大图+下方卡片 | 03_phase_peaks.png | 150 | 22% | 辅色25% | 图上60% |
| 05 | 05.slide | content | supporting | 左大图+右侧文字 | 04_phase_identified.png | 150 | 25% | 辅色25% | 与 P3 差异：标题栏色块在右 |
| 06 | 06.slide | content | supporting | 巨型数字+洞察 | 06_refinement_done.png | 160 | 28% | 强调色15% | 「4 引擎」96px |
| 07 | 07.slide | content | supporting | 非对称双栏 60:40 | 07_report_page.png | 200 | 18% | 辅色20% | 左图右 FAQ |
| 08 | 08.slide | ending | hero | 居中金句 | — | 30 | 45% | 主色渐变底 | 金句 48px |
