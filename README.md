<div align="center">
  <img src="src/polyxrd/resources/app-icon.png" alt="PolyXRD Logo" width="120" />
  <h1>PolyXRD</h1>
  <p>
    <b>多晶 X 射线衍射 (XRD) 图谱综合分析套件</b>
    <br />
    峰检测 &nbsp;·&nbsp; 多物相定性检索 &nbsp;·&nbsp; Rietveld 结构精修 &nbsp;·&nbsp; Le Bail 晶胞精修 &nbsp;·&nbsp; 指标化 &nbsp;·&nbsp; 3D 结构可视化 &nbsp;·&nbsp; 三库外挂检索 (COD 无机物 / COD 全库 / PDF2-2004)
  </p>
  <p>
    <a href="https://github.com/PolyXRD/PolyXRD/releases"><img src="https://img.shields.io/badge/Release-v2.1.0-blue?style=flat-square" /></a>
    &nbsp;
    <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-lightgrey?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/UI-PySide6%20(Qt6)-41cd52?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Tests-1100%2B%20collected-brightgreen?style=flat-square" />
  </p>
</div>

---

## 📖 项目说明

**PolyXRD** 是一个面向材料学 / 化学 / 晶体学研究者的 **多晶 X 射线衍射 (XRD) 图谱综合分析桌面软件**。它把"**加载原始 XRD 数据 → 预处理 → 峰检测 → 多物相定性检索 → Rietveld 结构精修 → 晶胞精修 → 全谱拟合 → 出报告**"整条工作流集成在一个统一的、带 **中文/英文/日文** 三语言界面的 PySide6 (Qt6) 桌面应用里。

**v1.0.1（2026-09-22）为首个 1.0 正式版**：主路线图 **M01–M25 全部交付**（含此前降级为 P3 的 M15 指标化与 M17 三维结构可视化），并经全量回归（993 项收集 / 991 通过 / 2 跳过）。

**v1.1.1（2026-09-22/23，当前工作版本）三件事**：

1. **国际化补全** — 此前英/日界面大面积残留中文，根因是翻译表三语键集本身就**不相等**（zh 562 / en 550 / ja 510），叠加视图层约 21 处硬编码中文与 31 个"幽灵键"（翻译表里不存在的键 → 界面直接显示裸键名）。补齐 **384 个翻译键**，三语对齐到 **901 × 3**，并把 ViewModel（37 处状态/错误）、报告正文与质量等级、服务层诊断日志、103 个元素名一并纳入。语言菜单中 `zh_CN` 显示为 **「简体中文」**，并**预留 `zh_TW`「繁體中文」**（补一个 `translations/zh_TW.py` 即可启用，无需改调用点）。**另修掉"切一次语言界面仍留中文"的根因**：新语言此前只刷新菜单栏/工具栏/标签页标题，页面内部与停靠面板纹丝不动 —— 现由每个视图自实现的 `retranslate()` 逐级重翻译（只动静态文案，绝不触碰谱线/峰表等运行期数据）。离屏残留扫描（隔离 `QSettings` 语言键 + 每组独立进程）四组组合**全部为 0**。
2. **全链路 UTF-8** — 同一份产物在中文(GBK)/日文(CP932)/英文(CP1252) Windows 上行为一致：文本 I/O 全部显式编码、**读取用户文件用 `utf-8-sig`（免疫 BOM）**、面向 Excel 的 CSV 带 BOM、入口强制 UTF-8 stdio 并给子进程留 `PYTHONUTF8=1`；新增静态守卫 `scripts/check_utf8_encoding.py`（含自测，当前 0 违规）。
3. **素材改进** — 启动图与横幅右下角的角标已从像素层修正（启动图仍为 480×270 的 `splash-screen.png`）。

**v2.0.0（2026-09-23/24，当前工作版本）—— 精修引擎大改**（按 `docs/精修改进实施手册-v3-分步可执行.md` 的 W00–W30 推进）：

1. **评价指标修正确**（此前 Rexp/GOF 是错的）：`Rexp` 的分母原配了单位权/归一化权重，
   实测 **2-1 偏小 130 倍、GOF 给出 920（标准定义应为 ~10）**。现统一为**统计权**
   （`stat_weights=poisson` 默认开），`Rwp/Rexp/Rp/χ²/GOF` 同源；单位权时界面显示
   **「不可解读」**而不是给一个漂亮假数字。`Rb` 正名为 **`Rp`**（轮廓 R，真 Bragg R 另行实现）。
2. **正向模型物理正确**：峰形改**面积归一**（旧实现面积 ∝ FWHM、η 改变面积 47%、
   Caglioti 参数被拟合到 −0.0021 而真值 0.012）；背景 Chebyshev **默认开启**；
   新增**观测峰种子化起点**（Caglioti 反解，作为额外候选）、**分阶段释放**
   （W27，5 阶段热启动）与 **Le Bail 级流水线**（W26，2 阶段）。
3. **峰位物理**：新增**样品位移** `Δ2θ=−2s·cosθ/R`、**低角不对称**（split-PV 面积守恒）、
   **每相整体温度因子 B**（`exp(−2B·s²)`，默认开）、**全晶胞参数模式**（含"峰表↔晶胞
   一致性守卫"）、**Kα2 双线检测**（形状无关判据，命中即在结果区提示）。
4. **参考库数据修复（库 0.5.1 → 0.5.2）**：修掉 `_calc_d_spacing_from_hkl` 漏掉的
   三斜归一化因子（**六方/三方晶胞此前全算错**：ZnO(101) 31.26°→36.25°）+
   按各自晶胞重索引库峰表 hkl（512 条错标修正）→ **106/106 条峰表与晶胞自洽**。
5. **定量语义**：新增 **质量分数** `W_p ∝ S_p·(ZMV)_p`（原先只是相对强度归一），
   并用 `fit_params["weight_basis"]`（`mass`/`relative`）标明口径。
   实测 2-1 由 66/34 → **45.8/54.2**（真值 50/50）。
6. **诚实失败诊断**：分段轮廓 R + **Durbin-Watson**（区分"白噪声"与"模型不完备"）
   → 直接给出可读建议（查整体 B / 峰宽 / 位移 / 不对称 / 背景 / 是否缺相）。

> 基准（`docs/基准报告-精修-v2.0.0.md`，8 试样真值对账，受限可比口径）：
> wR **24.5%–35.0%**；定量合计绝对偏差 1-1/1-2 **0.00 pp**、3-1 **2.94 pp**、
> 2-1 **8.43 pp**、4-1 **21.4 pp**；7 试样结果已归档，7-1（七相）因大峰表 × 抛光
> 评估次数过多未跑完（如实记录在报告内）。

**v2.1.0（2026-09-24，当前工作版本）—— 质量与诊断大版本**（代码评估 P0–P3 全落地 + v2.1-A~E）：

1. **项目保存/加载修复**（P0-1）：`.pxrd` 项目文件完整序列化精修结果，保存/打开/另存为/MCP 全链路可用。
2. **元素周期表补齐 118 元素**（P1-2）、**FoM 特异性强度加权**（P1-3）、**测试套件入库 + CI**（P2-4）、**语言菜单对齐实有翻译**（P2-5）、死代码清理与版本收口（P3）。
3. **抛光预算自适应**（v2.1-A）：按峰数自适应，7-1（七相）可完整跑完。
4. **服务层诊断结构化 + i18n**（v2.1-B）：诊断以 `{code, params}` 产出，UI 按界面语言渲染，英/日界面无中文残留。
5. **结构回填检索增强 + 降级可见**（v2.1-C）：元素集宽松匹配找回固溶体/非整比相（NCM 实测命中），定量降级原因界面明示。
6. **真实 Bragg R**（v2.1-D）：按反射积分强度对账，`Rb` 恢复本义，报告新增 Bragg R 行。
7. **Kα2 建模（opt-in）**（v2.1-E）：模型加 Kα2 伴峰（解析 Δ2θ、强度比 0.5），合成数据强度比回收 0.5±0.05。
8. 全量 **13 试样**基准：`docs/基准报告-精修-v2.1.0.md`。

核心设计哲学：

- **无需 Python 环境** — 安装包内置完整 Python 3.10 + PySide6 + pymatgen + scipy，目标机器开箱即用。
- **程序与数据库彻底分离** — 从 **v0.10.0 起主程序（安装包 / 便携包）不再内置任何数据库**，三个数据库各自独立打包、独立下载、独立挂载。v0.14.0 起无机物库默认发布**瘦身索引式**（362 MB，不再内嵌 CIF），CIF 由本地 `cod/cif` 目录或 COD 在线接口按需提供。
- **算法可控 + 结果可复现** — 预处理/拟合的每一步参数可保存、可回放，项目文件 (`.polyxrd` JSON) 全序列化。
- **UI 与算法分层** — MVVM 架构，`services/` 层是纯算法、不依赖 Qt，可独立单元测试。

---

## ✨ 功能清单

### ① 数据处理流水线
| 功能 | 说明 |
|---|---|
| 数据加载 | `.xrdml` (PANalytical), `.raw` (Bruker), `.txt/.csv`, `.prf` (GSAS)，支持拖放打开，批量合并 |
| 波长 | Cu Kα 默认 / Mo Co Cr Fe Ag W Au Ga Mn Ni Kα 可选 |
| 背景扣除 | SNIP (4 种) / Sonneveld-Visser / Polynomial (2-10 阶) / DWT 小波 |
| 平滑 | Savitzky-Golay / FFT 低通 / Whittaker-Eilers |
| Kα2 剥离 | Rachinger（前向递归，Δ2θ 随角度变化）/ pseudo-Voigt |
| 峰搜索 | 2 阶导数 + PV 拟合，SNR ≥ 2 自动阈值；重叠峰簇联合拟合 |
| 峰拟合 | Pseudo-Voigt / Pearson VII / Split-PV，LMFit 解算器，RWP & χ² |
| 仪器校准 | 标准样品外标校准（`services/calibration.py`） |
| 谱图格式互转 | 菜单「文件 ▸ 谱图格式转换」：8 种格式互转，含 `.mdi` / `.raw`(RAW2) 读写（`services/pattern_convert.py`） |

### ② 物相分析
- 多物相定性检索：**d-I 峰匹配 + Hanawalt 复合 + FoM 打分 + 化学式/元素过滤 + 矿物关键词** → Top-N 候选
- **候选检索约束（M09 / v1.0.1）**：密度区间 `density_range`、名称/化学式**模糊直搜** `find_phases_direct`、综合约束过滤 `apply_restraints`、搜索预设存取；`name_pattern` 通配符大小写已修正
- **四类元素过滤语义**：必有 (`must_have`，全部命中) / 含有 (`must`，至少一个) / 可能 (`maybe`，仅放宽允许池) / 没有 (`exclude`)。未勾选元素默认并入"没有"形成闭环；LIGHT_ELEMENTS (O/C/H/N/S) 支持一键"设为含有"
- **FoM 加权互斥匹配**：参考峰与实验峰一一对应贪心匹配（避免密集相被高估）+ 强峰加权 + 特异性项 + 强度余弦
- 交互式元素过滤器（118 种元素周期表选择器）
- 多物相联合拟合：生成计算谱 → 与实验谱最小二乘 → 各相 **质量分数 (%)**
- 组合选择：候选峰位掩码分支定界，联合覆盖最大 + 纯金属 ≤20% 硬约束；**同化学式多型按峰位差异择优**（`phase_structure_resolver.py`）

### ③ 晶相与晶体学
- **结构精修（引擎能力分层）**：
  - **真 Rietveld**（结构自由度：坐标/占位/ADP + `S·ZMV` 定量）→ **GSAS-II / FullProf / MAUD**；
  - **内置引擎** = **免结构全谱拟合（Le Bail 级，快）**：用 CIF `|F|²` 参考峰 + 每相各向同性晶胞缩放
    + March-Dollase 织构 + Chebyshev 背景 + 统计权，无需安装外部程序即可给出可用的 wR/Rp；
    它**不精修原子坐标/占位/ADP**，因此其 wt% 为**相对定量**而非严格质量分数。
  - 顺序/自动/手动三种精修策略对以上引擎通用。
  - ⚠️ 指标口径：v1.1.2 起 `Rwp/Rexp/GOF` 一律基于**统计权**（`stat_weights="poisson"`）。
    显式改用单位权（`"none"`）时 `Rexp/GOF` 无物理意义，界面会显示"不可解读"。
- 内置引擎 `_refine_builtin`：median 背景 + Caglioti U/V/W 2θ 依赖峰宽 + 多起点最小二乘 + wR 直选 + 稀疏抛光；**每相各向同性晶胞缩放自由度** + **March-Dollase 织构修正**
- **Le Bail 晶胞参数精修**：仅精修 a/b/c/α/β/γ，无需原子占位，适用于未知结构的晶胞测定
- **指标化（M15 / v1.0.1）**：内置立方 / 四方 / 六方三系指标化（`services/indexing.py`，验收：立方 Si → a≈5.43 Å）；外部 Treor / Dicvol 留接口
- **3D 晶体结构可视化（M17 / v1.0.1）**：CIF 浏览器内嵌 3D 晶胞 + 原子球视图，自动按空间群**展开非对称单元**（`services/structure_viz.py`）
- 结构模拟：从空间群/原子占位 → 计算 XRD 图谱 (Lorentz-Polarization 校正 + B 因子)
- hkl 指标化 (d→hkl)，230 种空间群标准化 (spglib)
- 基于 **PDF2-2004** 的空间群（72.8%）与晶胞（81.8%）映射，命中相可直接作精修起始结构
- **谱合成内核窗口化（M26 / v1.0.1）**：`spectrum_from_refs` 峰距截断（默认 100×FWHM），7251 点 × ~3000 峰单次评估 **1467 ms → 270 ms（5.4×）**，wR 等效差 < 0.05 个百分点
- **外部精修程序集成（M25）**：FullProf 自动生成 `.dat/.pcr` → fp2k 批处理 → 解析 `.sum` 回写 Rwp/Rexp/Rp/GoF² 与各相 R_Bragg/晶胞/含量；GSAS-II / MAUD 一键"导出 + 拉起 GUI"

### ④ 项目 & 报告
- `.polyxrd` 项目保存/打开/另存为（JSON 格式参数 + 图谱全归档）
- 导出：峰列表 CSV / PNG+SVG 图像 / 多物相报告 PDF / 批量报告 / 选中物相 CIF
- 脚本化接口（`services/scripting.py`）

### ⑤ 界面 & 多语言
- PySide6 (Qt6) + PyQtGraph 双画布（主图 + 残差图），支持可停靠面板
- 主谱与残差条 5:1 分栏、X 轴双向同步；绘图 X 轴自适应（滚轮以光标为中心缩放、左键拖拽平移）
- **简体中文 / English / 日本語** 三语言切换，切换无需重启；语言菜单中简体中文显示为 **「简体中文」**，并**预留「繁體中文」(zh_TW)** 槽位（补 `translations/zh_TW.py` 即启用）。**v1.1.1 起英/日界面全量补全** —— 三语翻译键集对齐到 **901 × 3**（双向差集为空），覆盖视图控件 / ViewModel 状态与错误提示 / 报告正文 / 服务层诊断日志 / 103 个元素名，并新增 **zh_CN 回退链**（缺键不再漏出裸键名）。**且切换语言会整页重翻译**（页面内部 + 停靠面板 + 工具栏/菜单/动作提示；只重设静态文案，不动运行期数据），持久化语言在**下次启动**即生效（此前只对菜单生效、页面仍是中文）
- **全链路 UTF-8，跨语言 Windows 不乱码** —— 所有文本 I/O 显式指定编码；读取用户文件（仪器导出 / Excel 导出的 CSV / 峰表）用 `utf-8-sig` 免疫 BOM；面向 Excel/WPS 的 CSV 带 BOM；启动即把 stdio 与子进程环境切到 UTF-8，并由 `scripts/check_utf8_encoding.py` 静态守护
- 白天/深色主题，Fusion 风格，HiDPI 适配；纵坐标线性 / log / sqrt 切换
- 交互式元素周期表（双击选择，带原子量与特征波长）
- **单实例运行**：重复双击不会开出多个窗口，而是把已在运行的窗口切到前台
- **数据库管理对话框**：三个槽位各自显示「已挂载/未挂载」、记录数、体积，并直接标明该槽位对应哪个下载包

### ⑥ 三库外挂检索服务
| 库 | 规模 | 作用 |
|---|---|---|
| COD 无机物库 | 71,199 物相 | 预计算 d-I 峰 + 预截断强峰列 + Hanawalt 预筛，**主检索库**，速度最快。**v0.14.0 起默认发布瘦身索引式**（362 MB，`COD_inorganics_index.sqlite`）：`cod_atomic_sites` 31.1 万行原子位点完整保留（精修初始模型不受影响），CIF 原文由本地 `cod/cif` 目录按需读取，缺失时自动回退 COD 在线接口下载。完整内嵌版（1.19 GB, `COD_inorganics.sqlite`）仍可导入，两者数据逐行一致 |
| COD 全库索引 | 113,223 条目 | COD 全量 CIF 索引（432 MB，不内嵌 CIF），用于「COD 全库」与「内置+全库合并」两个检索源 |
| PDF2-2004 库 | 163,834 物相 | ICDD PDF-2 2004，自带空间群与晶胞，用于与商品库对照 |

- 路径优先级：**GUI 导入的持久化路径 (`~/.polyxrd/user_db_paths.json`) > 默认位置（存在才用）> `~/.polyxrd/cif_db/` 兜底**
- 导入时自动**校验库类型**：三库表名有重合（COD 无机物与 PDF2 都叫 `phases`），选错槽位会提示而非静默失败
- 导入后立即生效，**无需重启**；物相分析面板的「数据库源」下拉同步刷新，未挂载的源自动置灰
- 三个库完全独立，可只装其中一个；一个都不装也能用内置的 **106 种参考物相**

---

## 🏗️ 代码结构

```
PolyXRD/
├── src/polyxrd/                # 主源代码 (分层包架构)
│   ├── main.py                 # 程序入口 (PySide6 QApplication)
│   ├── config.py               # AppConfig: 版本/路径/UI 语言持久化
│   ├── appstate.py             # 全局状态 (当前项目/图谱)
│   ├── i18n/                   # 多语言翻译 (zh_CN / en_US / ja_JP)
│   ├── mcp_server/             # MCP 服务端 (供外部智能体调用)
│   ├── resources/              # 图标 / 周期表数据 / 样式表 / 内置物相库
│   ├── models/                 # 数据模型
│   │   ├── xrd_data.py             # 图谱数据 + 实验元数据
│   │   ├── experiment.py           # 实验信息 / 会话文档
│   │   ├── phase.py / peak.py / fom.py / rir.py
│   │   ├── search_options.py       # ★ 检索约束/预设 (M09)
│   │   └── refinement.py / refinement_options.py
│   ├── viewmodels/             # MVVM 视图模型层 (main_vm / data_vm / phase_vm / refinement_vm)
│   ├── utils/                  # 工具函数 (resources / formula_parser / math_utils / file_utils / mpl_font)
│   ├── services/               # 核心算法服务 (无 UI, 可独立单元测试)
│   │   ├── instance_guard.py       # ★ 单实例守卫 (kill-safe, 内核命名互斥量)
│   │   ├── startup_diag.py         # ★ 启动诊断 (文件占用探测 + Restart Manager 反查)
│   │   ├── data_io.py / data_loader.py / data_processor.py
│   │   ├── raw_processing.py       # 原始数据流水线
│   │   ├── data_preprocessor.py    # 背景扣除 / 平滑 / Kα2 剥离
│   │   ├── background.py           # 背景估计 (SNIP / 多项式 / 控制点插值)
│   │   ├── peak_detection.py / peak_finder.py / peak_manager.py
│   │   ├── peak_fitter.py          # 单峰拟合内核
│   │   ├── peak_fitting.py         # 峰拟合 (PV/PVII/Split-PV, LMFit)
│   │   ├── calibration.py          # 仪器校准
│   │   ├── phase_identifier.py     # 多物相检索 + 联合拟合
│   │   ├── phase_structure_resolver.py # 检索结果 → 初始结构 (同质多象按峰位择优)
│   │   ├── phase_display.py        # 峰-物相归属 (双向, 一峰只归一相)
│   │   ├── phase_cif.py            # CIF 解析 / 对称展开 (expand_sites_by_symmetry)
│   │   ├── phase_cif_export.py     # 物相 CIF 导出
│   │   ├── search_restraints.py    # ★ M09 候选检索约束 (密度/名称/化学式/预设)
│   │   ├── indexing.py             # ★ M15 指标化 (立方/四方/六方)
│   │   ├── structure_viz.py        # ★ M17 3D 结构数据 (晶胞 + 原子球)
│   │   ├── foam.py                 # FoM 打分 + 置信度分档
│   │   ├── multiphase.py           # 多相迭代识别
│   │   ├── cod_local.py            # COD 本地库 / 索引构建 / CIF 兜底链
│   │   ├── cod_searcher.py         # COD 在线检索 + CIF 抓取
│   │   ├── cif_database.py         # COD 无机物库 SQLite 服务
│   │   ├── pdf2_database.py        # PDF2-2004 库服务 (固定宽度卡片记录)
│   │   ├── db_import.py            # 外挂数据库识别/校验/挂载 (Qt-free)
│   │   ├── user_database.py        # 用户自建物相库
│   │   ├── rietveld_refiner.py     # ★ Rietveld / Le Bail 精修 (GSAS-II / powerxrd / 内置)
│   │   ├── maud_par_builder.py     # ★ MAUD 批处理输入生成
│   │   ├── refinement_templates.py # 精修预设模板管理
│   │   ├── external_tools.py       # ★ 外部精修程序注册表 + 启动器 (M25)
│   │   ├── profile_fitting.py      # 全谱拟合 (PV/PVII)
│   │   ├── structure_simulator.py  # 计算 XRD 图谱 (Lorentz-Polarization + B 因子)
│   │   ├── pattern_convert.py      # ★ 谱图 8 格式互转
│   │   ├── rir.py / crystallite.py # RIR 半定量 / 微晶尺寸-微观应变
│   │   ├── report.py / project_service.py / export_service.py
│   │   └── scripting.py            # 脚本化接口
│   └── views/                  # UI 视图层 (PySide6)
│       ├── main_window.py          # 主窗口 / 菜单 / 工具栏 / 拖放
│       ├── data_view.py            # 数据视图
│       ├── phase_view.py           # 物相检索视图
│       ├── refinement_view.py      # ★ Rietveld 精修视图
│       ├── refinement_wizard.py    # 精修向导 (快速版 + 分步版)
│       ├── batch_refinement_dialog.py  # 批量精修
│       ├── format_convert_dialog.py    # 谱图格式转换
│       ├── report_view.py          # 报告视图
│       ├── theme.py                # 白天/深色主题
│       └── widgets/                # 自定义控件
│           ├── database_dialog.py        # 外挂数据库管理 (三槽位)
│           ├── element_periodic_table.py # 元素周期表
│           ├── element_filter_dialog.py  # 元素过滤器
│           ├── pattern_display.py        # 图谱画布
│           ├── plot_widget.py            # 绘图控件
│           ├── y_scale.py                # 纵坐标 log / sqrt 切换
│           ├── peak_table.py             # 峰表
│           ├── peak_match_table.py       # 峰匹配表
│           ├── structure_view.py         # ★ M17 3D 结构视图
│           ├── external_engines_group.py # ★ 外部精修引擎配置面板
│           └── busy_indicator.py         # ★ 长任务忙碌提示 + 防重入闸门
│
├── scripts/                    # 交付性构建脚本
│   ├── PolyXRD-Setup.iss           # Inno Setup 安装脚本
│   ├── verify_release.ps1          # 发布产物校验 + 各库独立包生成 + SHA-256
│   ├── _verify_release_py.py       # ★ v1.0.1 起主用: Python 版产物校验 (逐字节对账)
│   ├── check_utf8_encoding.py      # ★ v1.1.1: 文本 I/O 编码静态守卫 (带 --selftest)
│   ├── _release_v101.py            # ★ 建 Release + curl 流式上传 (内置 PDF2/Portable 禁传自检)
│   ├── _askpass.py                 # 非交互 git 认证辅助
│   ├── _pyinst_collect.py / _build_finish.py / _portable_and_version.py  # 构建链各步
│   ├── build_inorg_index_db.py     # 从完整内嵌版派生瘦身索引库
│   ├── regenerate_reference_db_peaks.py  # 内置参考库峰表重算
│   ├── dedup_reference_db.py       # 内置参考库同名条目去重
│   ├── migrate_inorg_formula.py    # 无机库 formula 修复迁移 (v0.13.2)
│   ├── repair_inorg_cell.py        # 无机库 cell_* 列错位修复 (v0.13.2)
│   ├── gsas2_bridge.py             # GSAS-II 调用桥
│   ├── create_github_release_v*.ps1  # 历史 Release 模板 (保留备查)
│   └── upload_release_assets.ps1   # 已废弃 (旧盘符路径, 仅留占位)
│
├── docs/                       # 文档
│   ├── CHANGELOG.md                # ★ 完整版本变更记录 (v0.3.0 → v1.1.1)
│   ├── HANDOVER-v0.9.7.md          # ★ 交接文档 (重装系统必读)
│   ├── 外挂数据库使用说明.md        # ★ 外挂库下载/导入/排错
│   ├── 路线图-v0.15.0.md            # 路线图与模块规格
│   ├── 物相分析路线图与模块拆分.md  # M01–M20 模块规格
│   ├── 算法内部原理.md              # 算法说明
│   ├── 精修算法改进与MAUD引擎接入方案.md
│   ├── 精修改进方案-v2-四阶段.md      # ★ 结构精修改进方案 v2 (P0–P3; M0–M4 已落地)
│   ├── 精修改进实施手册-v3-分步可执行.md  # ★ 分步施工图 (W00–W30; 文末有进度快照)
│   ├── 基准报告-精修-v2.0.0.md        # ★ 2.0.0 精修基准 (8 试样真值对账)
│   ├── 基准报告-精修-v2.1.0.md        # ★ 2.1.0 精修基准 (全量 13 试样, 含 Bragg R)
│   ├── 参考库hkl修复报告-v1.1.2.txt   # ★ 库 0.5.1→0.5.2 的 hkl 重索引记录
│   ├── MAUD-2.999x与3.04版本差异分析.md / MAUD批处理侦察报告.md
│   ├── 参考库峰表重算报告-v0.15.2.txt
│   ├── COD检索召回率优化方案.md     # 检索优化记录
│   ├── PDF2-2004对接说明.md         # PDF2 库对接细节
│   ├── 基准报告-v0.9.11.md          # 检索/精修基准数据
│   ├── DESIGN-phase-analysis-v2.md  # 物相分析 v2 设计
│   ├── 验收清单-v0.11.0.md          # 人工验收项
│   ├── 5分钟上手_4-1样例.md         # 快速上手
│   └── manual/                      # ★ 中文手册 (HTML / PPTX / PDF)
│
├── cod_data/                   # 数据库目录 (SQLite 不入库; v0.14.0 起三库统一于此)
│   ├── COD_inorganics_index.sqlite  # COD 无机物库·瘦身索引式 (71,199 物相, 362 MB) ← 运行时默认
│   ├── COD_inorganics.sqlite        # COD 无机物库·完整内嵌版 (71,199 物相, 1.19 GB, 内嵌 CIF)
│   ├── cod_index.sqlite             # COD 全库索引 (113,223 条目, 432 MB)
│   └── PDF2_2004.sqlite             # PDF2-2004 库 (163,834 物相)
├── cod/                        # COD 原始 CIF 归档 (重建索引用, 不入库)
│
├── build.bat                   # ★ 一键构建: 图标 → PyInstaller → ISCC → 便携包 → 数据库包 → 校验
├── build_icon.py               # 品牌化应用图标生成 (512→7 档 ICO)
├── run_dev.bat                 # ★ 源码一键启动 (人工验收用, 永远跑最新 src/)
├── PolyXRD.spec                # PyInstaller 打包配置 (onedir / PySide6 + pymatgen + scipy)
├── pyproject.toml              # Python 项目配置 / 依赖版本
├── requirements.txt            # 运行依赖
├── app.manifest                # Windows 应用程序清单 (DPI)
├── LICENSE                     # ★ 双许可条款 (英文: 学术免费 / 商业需单独授权)
├── LICENSE-CN                  # ★ 双许可条款 (中文, 与 LICENSE 对应)
├── .gitignore                  # 本仓库忽略规则 (测试/数据库/构建产物)
└── README.md                   # 本文件
```

---

## 🚀 使用方法

### 方式 A · 普通用户 (推荐, 无需 Python)

```
① 下载 PolyXRD-Setup-v1.0.1.exe (Windows x64)
   ↓
② 安装 (默认 C:\Program Files\PolyXRD\) 后直接运行 PolyXRD.exe
   ↓
③ 按需下载数据库包 —— 各库独立，需要哪个下哪个
   ③-a PolyXRD-v1.0.1-Databases-COD-inorg-index.zip   130.8 MB  →  COD_inorganics_index.sqlite  (日常推荐, 瘦身索引式)
   ③-b PolyXRD-v1.0.1-Databases-COD-full-index.zip    193.1 MB  →  cod_index.sqlite              (COD 全库/合并检索)
   解压到任意目录（必须真正解压到磁盘，不要直接在压缩包里打开）
   ↓
④ 启动 PolyXRD → 菜单「数据库 ▸ 外挂数据库管理…」
   对话框每个槽位上都写着「下载包：… → 解压出 …」，照对上即可，在该行点「导入…」
   → 立即生效，无需重启
   ↓
⑤ 开始使用! 参考 docs/5分钟上手_4-1样例.md
```

> **v1.0.1 发布口径**：Release 仅提供 **Setup 安装包 + 两个 COD 索引库包**。
> 便捷版（Portable）与 PDF2-2004 包**不随 Release 分发**（后者为 ICDD 版权库），
> 需要时请联系作者。

> **瘦身无机库说明**：索引式无机库不含内嵌 CIF。本机若有 COD 原始
> `cod/cif/` 归档（四级分片目录）则直接按需读取；没有时会自动回退到 COD
> 官网接口按编号下载 CIF 并缓存（需要联网）。若希望完全离线且单文件自包含，
> 可改用完整内嵌版 `COD_inorganics.sqlite`（1.19 GB），两者数据一致。

> **关于 PDF2-2004 库**：该库为 ICDD 商品数据库，**受版权保护，本仓库不分发、Release 不提供下载**。
> 持有正版授权的用户可自行准备 `PDF2_2004.sqlite` 并在「外挂数据库管理…」中作为 PDF2 槽位导入；
> 未授权时该槽位留空即可，其余功能不受影响（详见 [docs/外挂数据库使用说明.md](docs/外挂数据库使用说明.md)）。

> 一个库都不装也能用：程序内置 **106 种**常见参考物相。
> 详细说明与排错见 [docs/外挂数据库使用说明.md](docs/外挂数据库使用说明.md)。

### 方式 B · 开发者 / 二次开发 (源码运行)

```bash
# 1. 克隆仓库
git clone https://github.com/PolyXRD/PolyXRD.git
cd PolyXRD

# 2. 创建虚拟环境 (Python 3.10+)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动应用
python -m polyxrd.main

# 5. 跑测试
python -m pytest -q
```

> 测试规模：**1016 项收集 / 1014 通过 / 2 跳过 / 0 失败**（启动稳健性修复 v1.0.2 起的基线，v1.1.1 追加用例后重测）。
> v1.1.1（国际化补全 + 整页重翻译）另跑针对性回归：数据库对话框 / 精修日志 / 纵坐标 / busy 闸门 / 向导 MAUD **全部通过**。

#### 一键源码启动（人工验收用）

仓库根目录的 `run_dev.bat` 已封装好 PYTHONPATH，双击即可：

```bat
run_dev.bat
```

它直接跑仓库里的 `src/`，**永远是最新代码**，不必等 PyInstaller 构建完成，
适合功能验收 / 手测。打包版与源码版的差异只在分发方式，业务代码同源。
验收项与逐步操作见 [docs/验收清单-v0.11.0.md](docs/验收清单-v0.11.0.md)。

### 构建发布产物

```bat
:: 改 build.bat 顶部的 set APPVER=1.0.1 后:
build.bat
```

`build.bat` 会依次完成：生成图标 → PyInstaller 打包 → **自检 dist 内无业务数据库** →
Inno Setup 编译安装包 → 打便携包 → 生成三个独立数据库包 → 计算 SHA-256。

> **注意**：v0.10.0 起默认**不**打包任何数据库。旧的 `POLYXRD_NO_COD_DB` /
> `POLYXRD_NO_INORG_DB` 环境变量语义**已作废**；如需把库内嵌进二进制，改用 `POLYXRD_WITH_DB=1`。
>
> 仅校验 / 重新生成发布产物（不重新构建 exe）：
> ```powershell
> pwsh -NoProfile -File scripts\verify_release.ps1 -Version 1.0.1
> ```

### 5 分钟快速上手 (工作流示例)

```
① 文件 → 打开 → 载入一个 .xrdml / .txt 样品 (或直接拖放文件到窗口)
② 预处理面板: SNIP-40 扣背景 → SG w=11 p=3 平滑 → Max 归一化
③ 峰检测: 自动阈值 → 搜索
④ 物相检索: 勾选「COD 无机物库」→ 必有元素 [Mg, Al, O] → 搜索
   → Top 候选: MgAl₂O₄ Spinel ✅
⑤ Rietveld 精修: 选中共存相 → 精修向导 → 内置引擎 → 顺序策略
   → 精修完成, 查看 wR 与残差图
⑥ 需要时: CIF 浏览器看 3D 晶胞 / 指标化求晶胞参数 / 导出报告 (CSV/PDF)
```

### 启动 / 关闭异常排查

| 现象 | 处理 |
|---|---|
| **双击没有任何反应** | PolyXRD 是**单实例**程序：若已有实例在跑，双击会**把已有窗口拉到前台**（窗口被最小化或被挡住时会闪任务栏提示）。若任务管理器里有 `PolyXRD.exe` 却找不到窗口（幽灵实例），直接结束它；新版遇到这种情况会**照常启动**，不会再被挡住 |
| **关掉后进程还在**（任务管理器里仍能看到 `PolyXRD.exe`） | 新版在窗口关闭后进程**必定退出**（事件循环结束后有 5 秒硬退出兜底）。旧版遇到请手动结束进程 |
| **想确诊"为什么打不开"** | 命令行执行 `PolyXRD.exe --diagnose` —— 不起界面，直接生成报告（`%USERPROFILE%\.polyxrd\logs\diagnose-*.txt`），并用 Windows Restart Manager 指明**是哪个进程占用了程序文件**（这类文件占用正是"必须重启电脑"最典型的成因） |
| **查启动 / 崩溃日志** | `%USERPROFILE%\.polyxrd\logs\`：`startup-YYYY-MM-DD.log`（启动流水，每行带 `[pid=]`，出现 `shown visible=True` 才算真起来）、`crash-*.log`（Python 异常）、`startup-failure-*.log`（含占用进程诊断）、`faulthandler-*.log`（**原生崩溃**时自动落盘各线程 Python 调用栈） |
| **个别 Win11 机器上启动图一闪就退**（事件查看器指向 `Qt6Widgets.dll`） | 先**更新显卡驱动**（现场实证：2023-06-15 版 Intel Iris Xe 驱动 + Qt 6.11 触发 `window.show()` 内原生崩溃）。仍复现时用保守渲染模式：命令行 `PolyXRD.exe --safe-render`，或先 `set POLYXRD_SAFE_RENDER=1` 再双击（软件 GL + 关深色模式 + 关 DPI 缩放，用于二分定位） |

> 启动稳健性设计（2026-09-22 起）：**单实例守卫用内核命名互斥量实现** —— 上一个实例
> 无论正常退出还是被任务管理器强杀，都不会影响下一次启动；守卫本身"拿不准就放行"，
> 绝不因为残留状态把用户挡在门外。

---

## 🙏 开源致谢

PolyXRD 基于以下高质量开源项目构建，感谢各位维护者及贡献者社区：

| 项目 | 用途 | 许可证 |
|---|---|---|
| [Python 3.10](https://www.python.org/) | 运行时 | PSF |
| [PySide6 (Qt 6)](https://wiki.qt.io/Qt_for_Python) | GUI 框架 & 图形栈 | LGPL v3 / GPL v2 |
| [PyInstaller](https://pyinstaller.org/) | 独立二进制打包 | GPL v2 (Bootloader 例外) |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Windows 安装程序构建 | Inno Setup License |
| [pymatgen](https://pymatgen.org/) | 晶体学结构处理 / CIF / 对称性 | MIT |
| [spglib](https://spglib.github.io/spglib/) | 空间群识别 / 结构标准化 | BSD-3 |
| [scipy](https://scipy.org/) | 线性代数 / 最小二乘 / 统计模型 | BSD-3 |
| [NumPy](https://numpy.org/) | 多维数组 & 数值基础 | BSD-3 |
| [pandas](https://pandas.pydata.org/) | 表格数据处理 | BSD-3 |
| [Matplotlib](https://matplotlib.org/) | 静态 2D 绘图 & 报告图 | PSF-based |
| [PyQtGraph](https://www.pyqtgraph.org/) | 交互式 XRD 主图 / 残差图 | MIT |
| [LMFIT](https://lmfit.github.io/lmfit-py/) | 非线性最小二乘 (L-BFGS-B 等) | BSD-3 |
| [GSAS-II](https://gsas-ii.net/) | ★ Rietveld 结构精修引擎之一 (GSASIIscriptable API) | Free for academic/non-commercial |
| [powerxrd](https://github.com/andrewrgarcia/powerxrd/) | XRD 峰形模型 & 轻量 Rietveld 辅助 | MIT |
| [platformdirs](https://github.com/platformdirs/platformdirs) | 跨平台用户数据路径 | MIT |
| [Crystallography Open Database](https://www.crystallography.net/cod/) | 无机物相数据源 (71,199 / 113,223 条目, 独立外挂包) | CC BY / Public Domain 混合 |

> ICDD PDF-2 2004 为商业数据库，PolyXRD 不随附、不转发，需用户自行取得授权后以外部库方式挂载。

---

## 📦 Release

当前最新版本：**v1.0.1**（2026-09-22）→ [👉 前往 Release 下载](https://github.com/PolyXRD/PolyXRD/releases/tag/v1.0.1)

> **待发布**：**v1.1.1**（2026-09-22/23）—— 界面国际化补全（英/日全量覆盖，三语键集 **901×3** 对齐；
> 切换语言整页重翻译 + 持久化语言启动即生效），
> 代码已收口、版本号已统一到 1.1.1；**二进制产物暂未重建**（Release 上仍是 v1.0.1）。

### v1.0.1 主要变化

**首个 1.0 系列版本：主路线图 M01–M25 全部交付，全量回归 993 项收集 / 991 通过 / 2 跳过。**

- **M09 候选检索与约束** — 新增密度约束 `density_range`、名称/化学式模糊直搜
  `find_phases_direct`、综合约束过滤 `apply_restraints`、搜索预设存取；
  修复 `name_pattern` 通配符大小写失效（`*corundum*` 曾命中不了 "Corundum"）
- **M15 指标化**（原 P3 项补齐）— 内置立方 / 四方 / 六方指标化
  （验收：立方 Si → a≈5.43 Å）；外部 Treor / Dicvol 留接口
- **M17 晶体结构可视化**（原 P3 项补齐）— CIF 浏览器新增 3D 晶胞 + 原子球视图
  （自动按空间群展开非对称单元）
- **精修引擎提速 5.4×（M26）** — 谱合成内核峰距截断窗口化（7251 点 × ~3000 峰
  单次评估 **1467 ms → 270 ms**），wR 等效差 < 0.05 个百分点
- **修复大峰表组合卡死** — `_cif_reference_peaks` 改为 `atomic_sites` 直构，
  不再对已展开的全胞位点做 CIF 二次对称展开
- **承接 v0.15.2** — Rwp/Rexp/Rb/GOF 标准 R 因子组、March-Dollase 织构修正、
  对称展开向量化（4-1 wR 52.7% → 19.69%）、谱图 8 格式互转、
  内置参考库重算（0.5.1，106 条）
- **版本号** 0.15.3 → **1.0.1**

### 发布附件 (v1.0.1)

| 附件 | 大小 | 说明 |
|---|---|---|
| **PolyXRD-Setup-v1.0.1.exe** | 246.3 MB | Windows 独立安装包（内置 Python/Qt6/全部依赖，不含任何数据库） |
| **PolyXRD-v1.0.1-Databases-COD-inorg-index.zip** | 130.8 MB | COD 无机物库·瘦身索引式（71,199 物相 + 31.1 万原子位点，不内嵌 CIF，主检索库，推荐） |
| **PolyXRD-v1.0.1-Databases-COD-full-index.zip** | 193.1 MB | COD 全库索引外挂包（113,223 条目，不内嵌 CIF） |
| **Source code (.zip / .tar.gz)** | — | 完整源码快照 |

> **v1.0.1 起发布口径**：Release 只提供 **Setup 安装包 + 两个 COD 索引库包**。
> 便捷版（Portable）自 v0.11.0 起不随 Release 发布（按需联系作者获取）；
> `…-Databases-PDF2.zip` **不在 Release 中提供** —— PDF2-2004 为 ICDD 版权数据库，
> 仓库仅提供挂载能力，分发包由用户依授权自行准备。

SHA-256 校验值（体积单位为资源管理器口径 = 1,048,576 字节）：

```
3ac4fc3a9fc4402bbb7c7164166cc261aed98deb245df0bd0276e1d09ffb024e  PolyXRD-Setup-v1.0.1.exe                        246.3 MB
b6097d83916afee2a9bcbdfc3e9ad33e630e2aaa0fadd87706f413efab9ef144  PolyXRD-v1.0.1-Databases-COD-inorg-index.zip    130.8 MB
ed33680c4b5f2c45e38b84fba24ce6c6159e94f5ba95d15910c49003f2db2709  PolyXRD-v1.0.1-Databases-COD-full-index.zip     193.1 MB
```

> 完整清单（含未发布的 Portable / PDF2 包）见本地 `SHA256-v1.0.1.txt`。
> 下载数据库包后建议核对 SHA-256，尤其是大文件传输中断导致 SQLite 尾部截断的情况
> —— 截断的库能被 SQLite 打开，但读到尾部记录才会报错。

### v0.15.0 主要变化

- **绘图 X 轴自适应交互（M22）** — 绘图默认收缩至数据实际范围；滚轮以光标为中心
  缩放（±15%/格），左键拖拽平移（与峰位点击兼容，<3px 判定点击），工具栏 Home
  重置回数据全览
- **物相列表交互重构（M23）** — 主窗口物相树默认空、跟随物相分析页勾选实时刷新；
  右键可导出选中物相 CIF / 查看详情；勾选集随项目持久化保存/恢复
- **精修页布局重构（M24）** — 主谱与残差条 5:1 上下分栏、X 轴双向同步；日志面板
  移入左栏；右栏新增「已勾选物相」列表（右键导出 CIF）与「外部精修程序」容器；
  窗口布局版本升到 v3（旧布局自动丢弃）
- **外部精修引擎接入（M25）** — 精修页右栏新增 GSAS-II / MAUD / FullProf 三行
  配置面板（状态灯/路径/浏览/检测/启动，路径持久化于 `~/.polyxrd/external_tools.json`）：
  - **FullProf**：自动生成 `.dat/.pcr` → fp2k 批处理精修 → 解析 `.sum` 回写
    Rwp/Rexp/Rp/GoF² 与各相 R_Bragg/晶胞/含量；两遍标度自动校准 + 限位编号
    自动发现 + 保守模式（W 扫描）三级兜底
  - **GSAS-II / MAUD**：一键导出实验谱 + 物相 CIF 到工作目录并拉起各自 GUI
    （"导出+拉起" 语义）
- **新增单测** `tests/test_v015_fullprof.py`（dat/pcr 生成器纯函数 + 解析器样例文本）
- **版本号** 0.14.0 → 0.15.0

### v0.14.0 主要变化

- **COD 无机物库默认改为瘦身索引式（`COD_inorganics_index.sqlite`，362 MB）** —
  与 COD 全库索引同形态：不内嵌 CIF，`cod_atomic_sites` 31.1 万行原子位点完整保留，
  峰表/晶胞/化学式与完整版逐行一致；CIF 由本地 `cod/cif` 目录按需读取，
  缺失时自动回退 COD 官网接口下载。完整内嵌版（1.19 GB）仍可导入，作为回退
- **发布包改名** — `Databases-COD-inorg.zip` → `Databases-COD-inorg-index.zip`（内容改发瘦身版）、
  `Databases-COD-full.zip` → `Databases-COD-full-index.zip`（内容不变）
- **数据修复随包生效** — v0.13.2 的无机库修复（formula 被空间群覆盖 541 条、
  `cell_*` 列错位 31,634 行）已包含在两个索引包中
- **新增 `scripts/build_inorg_index_db.py`** — 从完整内嵌版派生瘦身索引库（默认 dry-run，
  四象限审计保证零信息损失）
- **版本号** 0.13.2 → 0.14.0

### v0.13.2 主要变化

- **COD 无机库数据修复** — `phases.formula` 被空间群符号覆盖（609 条检出，修复 541 条）
  + `cell_*` 列与内嵌 CIF 错位（31,634 行重写，含 denormal 垃圾/NULL/倍频错误），
  此前 Zincite (ZnO) 等物相在元素过滤下会被误杀"隐身"
- **编号前缀检索修复** — `97-9004178` / `96-101-1097` 两种官方编号写法在
  `search_structures` 与 `search_cod_phases` 两条路径上均可正确解析（旧代码两处静默失效）
- **索引空库门槛** — `<50 MB` 的占位/幽灵 `cod_index.sqlite` 不再被当作有效全库
- **路径解析支持 `cod_data/` 统一布局** — 三库（含 cod_index.sqlite）统一放 `cod_data/`
- **启动稳定性** — v0.13.1 的 PNG 图标/启动图规避方案延续

### v0.11.0 主要变化

- **COD 结构精修链路打通** — CIF 覆盖 + 5 级回退（本地目录 → 全库索引 → 无机库内嵌 → tar → COD 在线 REST）
- **COD 无机物库升级为 v2 结构（本次发布）** — phases 表内嵌 gzip CIF 全文（71,156/71,199 = 99.94%）
  + `cod_atomic_sites` 子集表（31.1 万行原子位点）：**只挂无机物库一个库即可做 Rietveld 结构精修**
  - 背景：无机库与 COD 全库索引的编号体系并不重合（全库仅覆盖约 1/3 的无机相编号），
    旧版"只挂无机库"时几乎拿不到结构数据
- **引擎端到端** — GSAS-II（engine=auto 自动选引擎 + wt% 定量）与 MAUD3 全链路接入；
  引擎下拉统一为 auto / gsas2 / maud / builtin / powerxrd
- **精修算法** — R-A1 统计权重（目标函数与 wR 自洽）、R-A4 Chebyshev 背景抛光（均为 opt-in）
- **两套精修向导并存** — 快速版（单页）+ 分步版（数据→物相→参数→预览→执行，含模板/CIF 导入/COD 检索），
  分步向导结果自动回灌主窗口精修页；工具栏按钮点主体=快速版、右侧小箭头=选路径
- **版本号** 0.10.0 → 0.11.0

### v0.10.0 主要变化

- **数据库彻底外挂化** — 安装包与便携包**不再内置任何数据库**，改为三个独立下载包，按需取用
  - 便携包体积随之从 661.5 MB 降到 **380.7 MB（−42%）**
- **新增 GUI 数据库管理入口** — 菜单「数据库 ▸ 外挂数据库管理…」，三个槽位独立挂载/卸载，导入后热生效
  - 导入时校验库类型（COD 无机物与 PDF2 表名同为 `phases`，靠列签名区分），选错槽位会明确提示
- **新增 PDF2-2004 外挂库** — 163,834 物相，自带空间群（72.8%）与晶胞（81.8%），用于与商品库对照
- **版本号** 0.9.11 → 0.10.0

### v0.9.11 主要变化

- **COD 检索提速** — 新增预截断强峰列，检索耗时 **22.5 s → 8.8 s**
- **FoM 改加权互斥匹配** — 参考峰与实验峰一一对应（避免密集相被高估）+ 强峰加权 + 特异性项 + 强度余弦
- **COD 候选排序重做** — `0.3 × Hanawalt 复合 + 0.7 × (1 − FoM)`，基准 Top-1 12%→14% / Top-5 22%→25% / Top-10 24%→27%
- **元素过滤四语义定稿** — 必有 / 含有 / 可能 / 没有，未勾选默认并入"没有"；LIGHT_ELEMENTS 一键设为含有

---

## 📝 版本兼容性 & License

| PolyXRD | COD 无机物库 | COD 全库索引 | PDF2-2004 |
|---|---|---|---|
| **1.0.1** | `…-Databases-COD-inorg-index.zip`（瘦身索引式, 默认; 内嵌版仍可导入） | `…-Databases-COD-full-index.zip` | 用户自行准备（ICDD 授权，仓库不分发） |
| 0.14.0 – 0.15.x | 同上 | 同上 | 同上 |
| 0.11.0–0.13.2 | `…-Databases-COD-inorg.zip`（v2, 内嵌 CIF） | `…-Databases-COD-full.zip` | 用户自行准备（ICDD 授权，仓库不分发） |
| 0.10.0 | `…-Databases-COD-inorg.zip`（v1, 仅 d-I 峰） | `…-Databases-COD-full.zip` | 用户自行准备（ICDD 授权，仓库不分发） |
| 0.9.10 及以前 | 内嵌或 `PolyXRD_COD_Inorganics_v0.9.x.zip` | 内嵌或 `PolyXRD_COD_Full_v0.9.x.zip` | 不支持 |

### 版权与许可 · Copyright & License

Copyright (c) 2026 PolyXRD Team.

This software is free for academic research and education.
Commercial use is prohibited without a separate written license from the copyright holder.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

版权所有 (c) 2026 PolyXRD Team。

本软件可供学术研究与教学免费使用。
未经版权持有人单独书面许可，禁止用于商业用途。
软件按原样提供，不提供任何担保。

完整条款见 [`LICENSE`](LICENSE)（英文）与 [`LICENSE-CN`](LICENSE-CN)（中文）；商业授权联系：sshztx@outlook.com。
使用时请同时遵守上游 PySide6 (LGPL/GPL)、pymatgen、COD 等第三方许可证条款。

---

<div align="right">
  <i>PolyXRD Team · 2025 — 2026 · 文档版本 2.1.0 (2026-09-24) · 联系：sshztx@outlook.com</i>
</div>
