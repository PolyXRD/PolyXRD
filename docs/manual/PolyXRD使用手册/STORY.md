# STORY.md — PolyXRD 使用手册（详细版）v0.15.0

## ① 用户意图对齐
- **目标受众**：实验室研究人员 / XRD 分析初学者，用于软件培训与日常查阅。
- **核心目标**：看完能独立完成「装载数据→物相鉴定→精修→报告」全流程，并理解各步骤背后的原理与常见故障处理。
- **PPT 长度**：14 页（含封面、目录、3 个章节扉页、结束页）。
- **视觉调性**：科技蓝白 / 工程严谨 / 截图实证 / 克制留白。
- **内容边界**：必讲——主界面、数据装载、物相鉴定、精修（内置+外置引擎）、报告、数据库、Rietveld 原理、FAQ；不讲——MAUD3-MCP 集成细节、路线图；禁碰——与 Match!/Diamond 的直接贬低性对比。

## ② 页面布局骨架
14 页分三章：Ch01 快速上手（P4-P6）、Ch02 结构精修与产出（P7-P10）、Ch03 原理与支持（P11-P13）。
目录声明 3 章 → 3 个 section 扉页（P3=01、P7=02、P11=03），编号连续。
Hero 页：P1 封面、P4 主界面（视觉高潮）、P14 结束页 → 3/14≈21% 合规；互不相邻。
rhythm：P1 peak / P2 valley / P3 transition / P4 peak / P5 valley / P6 valley / P7 transition / P8 valley / P9 valley / P10 peak / P11 transition / P12 valley / P13 valley / P14 peak。P5-P6 连续 valley 后 P7 transition 打破；P8-P9 后 P10 peak 打破。
非对称版式：P4 左大图+右侧文字、P6 上大图+下方卡片、P8 非对称双栏、P10 巨型数字+洞察、P12 非对称双栏、P13 左标题+右内容 → 6/14≈43% ≥40% 合规。
对称版式（≤2 页）：P5 图表+洞察、P9 图表+洞察。
相邻版式均不重复；「N卡片横排」0 次。

## ③ 页面大纲
| # | title | type | role | rhythm | layout | visual | visual_role | density | anti_pattern | description |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 | PolyXRD 使用手册 | cover | hero | peak | 全屏视觉+骑线文字 | L1: 01_main_data_empty.png 全幅蒙版 | atmosphere | 字30/图1/留白35% | 禁止标题块塞小图 | v0.15.0 软件使用手册——从数据到物相结构的一站式 XRD 分析 |
| 02 | 目录 | catalog | supporting | valley | 左标题+右内容 | L3: 无 | — | 字120/图0/留白25% | 禁止等宽卡片横排 | 三章：快速上手 / 精修与产出 / 原理与支持 |
| 03 | 01 快速上手 | section | transition | transition | 居中大字 | L3: 编号大字 | atmosphere | 字30/图0/留白45% | 禁止四卡片预览 | 三步完成一次物相定性分析 |
| 04 | 主界面与数据装载 | content | hero | peak | 左大图+右侧文字 | L1: 02_data_loaded.png 占右60% | anchor | 字180/图1/留白25% | 禁止 50:50 等分 | 主界面三页签：数据/物相/精修报告；装载后核波长——波长错了全盘皆错 |
| 05 | 扣背景与找峰 | content | supporting | valley | 图表+洞察 | L1: 03_phase_peaks.png 占55% | evidence | 字200/图1/留白20% | 禁止无图的纯文字 | SNIP 扣背景→二阶导数找峰；峰位质量决定鉴定上限 |
| 06 | 物相鉴定 | content | supporting | valley | 上大图+下方卡片 | L1: 04_phase_identified.png 占上60% | evidence | 字220/图1/留白20% | 禁止三等分卡片 | FoM 排序候选→叠加理论峰→采纳入库；多相需逐条采纳 |
| 07 | 02 结构精修与产出 | section | transition | transition | 居中大字 | L3: 编号大字 | atmosphere | 字30/图0/留白45% | 禁止正文段落 | 从定性到定量：四引擎 Rietveld 精修 |
| 08 | 四引擎精修体系 | content | supporting | valley | 非对称双栏(60:40) | L2: 05_refinement_page.png | evidence | 字240/图1/留白18% | 禁止等分双栏 | builtin 快速保守；GSAS-II/MAUD/FullProf 发布级——按需求选引擎 |
| 09 | 分步精修向导 | content | supporting | valley | 图表+洞察 | L1: 08_refine_wizard.png 占55% | evidence | 字200/图1/留白20% | 禁止纯文字页 | 向导分步放开参数，每步检查收敛，新手友好 |
| 10 | 精修结果与报告 | content | hero | peak | 巨型数字+洞察 | 大数字 Rwp + L2: 07_report_page.png | anchor | 字180/图1/留白30% | 禁止把指标塞进角落 | Rwp 越低拟合越好；一键导出 HTML 报告——含量表可直接进论文 |
| 11 | 03 原理与支持 | section | transition | transition | 居中大字 | L3: 编号大字 | atmosphere | 字30/图0/留白45% | 禁止四卡片预览 | 知其所以然：Rietveld 方法与数据库体系 |
| 12 | Rietveld 方法原理 | content | supporting | valley | 非对称双栏(65:35) | Diagram(公式区) | evidence | 字260/图0/留白18% | 禁止整页公式推导 | 最小化观测-计算差；Rwp/GoF 两个指标看收敛质量；builtin 无原子坐标故 wR 偏高属正常 |
| 13 | 数据库与常见问题 | content | supporting | valley | 左标题+右内容 | L2: 09_database_manager.png | evidence | 字260/图1/留白18% | 禁止等宽四卡 | 五库体系 + 四条高频 FAQ——外部引擎红灯先查路径 |
| 14 | 开始使用 | ending | hero | peak | 居中金句 | 大字 | anchor | 字40/图0/留白45% | 禁止罗列功能 | 装载数据、找到物相、精修到位——五分钟完成第一份报告 |
