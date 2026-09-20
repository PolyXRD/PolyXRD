# DESIGN.md — PolyXRD 使用手册（详细版）v0.15.0

## 画布与母版（1280×720）
- **A 标题块**：y 0–120px，padding-top 20，标题 36px bold，色 #0B3C6E。
- **B 内容区**：y 120–660px（540px 可用），左右 padding 60px。
- **C 页脚条**：y 660–720px，左「PolyXRD v0.15.0 使用手册」14px #8A94A6，右页码 `NN / 14` 14px #8A94A6。
- 封面 / 章节扉页 / 结束页用自定义版式，省略 C 区。

## 色彩池（≤4 hex）
| 角色 | hex | 用途 |
|---|---|---|
| 主色 | #0B3C6E（深工程蓝） | 标题、封面/扉页底色、色块 |
| 辅色 | #E8F0F8（浅蓝灰） | 卡片底、分区背景 |
| 强调色 | #2F8F4E（数据绿） | 锚点数字、关键指标、绿色状态灯呼应 |
| 中性色 | #333333 / #8A94A6 | 正文 / 页脚 |

面积分配：主色 ≤60%（封面/扉页可满底）、辅色 ≤30%、强调色 ≤10%（P10 hero 可到 18%）。
渐变方案：`linear-gradient(135deg, #0B3C6E 0%, #1A5FA0 100%)` 仅用于封面与扉页标题底；半透明：封面截图上叠 `rgba(6,30,60,0.55)` 蒙版保证白字可读。

## 字体
- 标题/锚点：思源黑体 bold（fallback Microsoft YaHei）。
- 正文：思源黑体 regular；行高 1.5–1.6。
- 阶梯：封面主标 72px、扉页大字 64px、锚点数字 96px、页标题 36px、卡片头 24px、正文 20px、页脚 14px。

## 配图清单（全部 material 来源，已逐张核对：软件实拍截图，含中文 UI，清晰度足够）
| 文件 | 内容 | 使用页 | 等级 |
|---|---|---|---|
| 01_main_data_empty.png | 主窗口空态 1440×1075 | P1 | L1(蒙版全幅) |
| 02_data_loaded.png | 数据装载后 1440×1075 | P4 | L1 |
| 03_phase_peaks.png | 找峰结果 1440×1075 | P5 | L1 |
| 04_phase_identified.png | 物相鉴定 1440×1075 | P6 | L1 |
| 05_refinement_page.png | 精修页布局 1440×1075 | P8 | L2 |
| 06_refinement_done.png | 精修完成 1440×1075 | (备用) | — |
| 07_report_page.png | 报告页 1440×1075 | P10 | L2 |
| 08_refine_wizard.png | 精修向导 1150×780 | P9 | L1 |
| 09_database_manager.png | 数据库管理 860×600 | P13 | L2 |

截图统一加 1px #C5D5E8 边框 + 8px 圆角，objectFit: cover；不放全屏背景（封面除外，P1 允许）。

## 页面映射表
| # | 文件 | 类型 | 角色 | 版式 | L1 文件 | 字数 | 留白% | 色彩分配 | 关键约束 |
|---|---|---|---|---|---|---|---|---|---|
| 01 | 01.slide | cover | hero | 全屏视觉+骑线文字 | 01_main_data_empty.png | 30 | 35% | 主色55%+蒙版 | 白字+蒙版可读性 |
| 02 | 02.slide | catalog | supporting | 左标题+右内容 | — | 120 | 25% | 辅色25% | 每章 ≥30 字 |
| 03 | 03.slide | section | transition | 居中大字 | — | 30 | 45% | 主色渐变底 | 编号 01 大字 |
| 04 | 04.slide | content | hero | 左大图+右侧文字 | 02_data_loaded.png | 180 | 25% | 主色40%+辅色20% | 图占右60%、加绿锚点 |
| 05 | 05.slide | content | supporting | 图表+洞察 | 03_phase_peaks.png | 200 | 20% | 辅色25% | 图占55%左 |
| 06 | 06.slide | content | supporting | 上大图+下方卡片 | 04_phase_identified.png | 220 | 20% | 辅色25% | 图占上60% |
| 07 | 07.slide | section | transition | 居中大字 | — | 30 | 45% | 主色渐变底 | 编号 02 |
| 08 | 08.slide | content | supporting | 非对称双栏 60:40 | 05_refinement_page.png | 240 | 18% | 辅色20%+强调 | 宽侧图+窄侧引擎卡 |
| 09 | 09.slide | content | supporting | 图表+洞察 | 08_refine_wizard.png | 200 | 20% | 辅色25% | 图占55% |
| 10 | 10.slide | content | hero | 巨型数字+洞察 | 07_report_page.png | 180 | 30% | 强调色18% | Rwp 96px 锚点 |
| 11 | 11.slide | section | transition | 居中大字 | — | 30 | 45% | 主色渐变底 | 编号 03 |
| 12 | 12.slide | content | supporting | 非对称双栏 65:35 | Diagram(公式) | 260 | 18% | 辅色20% | 公式区左65% |
| 13 | 13.slide | content | supporting | 左标题+右内容 | 09_database_manager.png | 260 | 18% | 辅色20% | 左窄标题栏30% |
| 14 | 14.slide | ending | hero | 居中金句 | — | 40 | 45% | 主色渐变底 | 金句 48px |
