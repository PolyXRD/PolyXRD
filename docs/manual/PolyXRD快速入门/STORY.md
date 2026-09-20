# STORY.md — PolyXRD 快速入门 v0.15.0

## ① 用户意图对齐
- **目标受众**：第一次打开 PolyXRD 的用户；5 分钟上手场景（新员工培训 / 现场速查）。
- **核心目标**：照着做即可完成一次完整分析并导出报告。
- **PPT 长度**：8 页。
- **视觉调性**：科技蓝白 / 步骤指引 / 截图实证 / 轻快直接。
- **内容边界**：必讲——5 步流程 + 3 条高频 FAQ；不讲原理推导、不讲向导与外置引擎细节；禁碰——与竞品对比。

## ② 页面布局骨架
单章结构：目录省略，无 section 扉页（目录未声明章节 → 无扉页要求）。
Hero 页：P1 封面、P6 精修结果、P8 结束页 → 3/8≈37%……超 35% 上限 → 将 P6 降为 supporting（peak），Hero = P1/P8 = 2/8 = 25% 合规，P6 为 peak 但 role=supporting（巨型数字锚点由版式承担）。
rhythm：P1 peak / P2 transition(流程总览) / P3 valley / P4 valley / P5 valley / P6 peak / P7 valley / P8 peak。P3-P5 连续 valley → P6 peak 打破，合规。
非对称版式：P3 左大图+右侧文字、P4 上大图+下方卡片、P5 左大图+右侧文字、P6 巨型数字+洞察、P7 非对称双栏 → 5/8≈63% ≥40% 合规；「左大图+右侧文字」2 次 ≤40% 上限。
对称版式 1 页（P2 流程横向步骤条）≤2 合规。相邻版式不重复；N卡片横排 0 次。

## ③ 页面大纲
| # | title | type | role | rhythm | layout | visual | visual_role | density | anti_pattern | description |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 | PolyXRD 快速入门 | cover | hero | peak | 全屏视觉+骑线文字 | L1: 01_main_data_empty.png 蒙版 | atmosphere | 字25/图1/留白35% | 禁止标题块塞小图 | 五步完成第一份物相分析报告 |
| 02 | 五步流程总览 | content | transition | transition | 流程步骤条 | Diagram(五步横向流程) | anchor | 字90/图0/留白30% | 禁止等宽卡片横排 | 装载数据→扣背景找峰→物相鉴定→精修→报告，全流程 ≤10 分钟 |
| 03 | 第 1 步 · 装载数据 | content | supporting | valley | 左大图+右侧文字 | L1: 02_data_loaded.png 占左58% | anchor | 字150/图1/留白25% | 禁止 50:50 等分 | 先核波长再谈分析——波长默认 Cu Kα1 |
| 04 | 第 2 步 · 扣背景与找峰 | content | supporting | valley | 上大图+下方卡片 | L1: 03_phase_peaks.png 占上60% | evidence | 字150/图1/留白22% | 禁止三等分卡片 | 默认参数即可，峰太少再放宽信噪比 |
| 05 | 第 3 步 · 物相鉴定 | content | supporting | valley | 左大图+右侧文字 | L1: 04_phase_identified.png 占左58% | anchor | 字150/图1/留白25% | 禁止与 P3 版式完全相同(翻转布局) | 内置库 FoM 排序，逐条采纳多相 |
| 06 | 第 4 步 · 结构精修 | content | supporting | peak | 巨型数字+洞察 | 大数字「4 引擎」+ L2: 06_refinement_done.png | anchor | 字160/图1/留白28% | 禁止把指标塞角落 | builtin 一键精修看含量；发布级用 GSAS-II/MAUD/FullProf |
| 07 | 第 5 步 · 导出报告 + FAQ | content | supporting | valley | 非对称双栏 60:40 | L2: 07_report_page.png | evidence | 字200/图1/留白18% | 禁止等分双栏 | 一键 HTML 报告；右侧三条 FAQ 速查 |
| 08 | 完成 | ending | hero | peak | 居中金句 | 大字 | anchor | 字30/图0/留白45% | 禁止罗列功能 | 第一份报告已到手，详见《使用手册》 |
