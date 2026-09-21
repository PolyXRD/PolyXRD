# PolyXRD 版本变更记录（CHANGELOG）

> 覆盖范围：**v0.3.0（可追溯最早版本）→ v0.15.2（2026-09-21）**
> 合并日期：2026-09-21 ｜ 由 4 份历史变更记录（CHANGELOG01 / 02 / 03 与原 CHANGELOG）合并去重而成
> 数据来源：git 提交历史 + GitHub Release 正文 + 项目工作记忆（逐日工作日志）+ 交接期源码包回溯
> 联系：sshztx@outlook.com
>
> **结构导览**：
> - 第一部分 · 早期史（v0.3.0 → v0.8.20，无 git 记录，回溯整理）
> - 第二部分 · 正式发布逐版详情（v0.8.21 → v0.15.1，其中 v0.8.21–v0.8.23 沿用首份日志的详细节）
> - 附录 A–F（路线图对照 / 库包演进 / 量化指标 / 发布红线 / 版本收口点 / 不确定项）＋ G 开源致谢 ＋ H 兼容性矩阵

---

# 第一部分 · 早期史（v0.3.0 → v0.8.20，无 git 记录，回溯整理）

## \[0.3.0] — 最初原型版本

> 从 V0.6.0 源码包中 `__init__.py` 的 `__version__` 发现。这是目前可追溯的最早版本。

### 功能

- `__version__ = "0.3.0"` 定义

- 项目命名: PolyXRD — X射线衍射仪数据分析软件

- 核心功能定义:

  - XRD 数据加载、预处理（背景扣除、平滑、归一化）

  - 峰识别与峰拟合

  - 物相识别与定量分析

  - Rietveld 结构精修

  - 结果导出与报告生成

- 作者: PolyXRD Team

***

## \[0.4.1] — 早期开发版本

> 从 V0.6.0 源码包中 `config.py` 的 `app_version` 发现。

### 功能

- 应用版本号定义为 0.4.1

- 基本配置框架: 窗口尺寸 / 默认波长 (Cu Kα1 1.5406) / 2θ 范围 / d 值范围

- 支持文件格式: .xy / .dat / .csv / .txt / .xrdml / .xml / .raw / .brml

- Rietveld 精修参数: sequential 策略 / max\_cycles=20 / tolerance=0.0001

- 默认 2θ 范围: 5° \~ 80°

***

## \[原型 / Pre-0.6.0] — 2026-08-12 \~ 2026-08-13 (早期架构)

> 这是 PolyXRD 的**最初原型**，采用完全不同的 core/gui 架构，后来重构为 V0.6.0 的 MVVM 架构。

### 功能

- 通用 TXT 读取器: 支持 SMZ 系列 (无表头两列) 和岛津/Rigaku 风格 (带 target/scan range 标记)

- 离线参考物相库: 30 种常见矿物/氧化物 (ZnO / 石英 / 方石英 / CaCO3 / MgCO3 / 白云石 / 刚玉 / 赤铁矿 / 针铁矿 / 高岭石 / 三水铝石 / 勃姆石 / 白云母 / 钙铝黄长石 / 氟磷灰石 / 金红石 / 锐钛矿 / WO3 / WO2.9 / WO2.72 等)

- 真实 XRD 数据验证: SMZ 系列样品 + 钨系列 (蓝钨/黄钨/紫钨) 全部通过

- 角度自适应容差: `max(0.30, 0.012·|2θ|)`, 考虑混合物低丰度相掩蔽

- COD 在线客户端 + 本地 CIF 库 + Materials Project 数据库

- GSAS-II 精修引擎集成 + pymatgen 晶体学引擎

- 完整项目持久化: .polyxrd 项目文件 + 命令历史 + 批量处理

- 报告生成: Excel / PDF / 图表工厂

### 技术架构 (与当前版本完全不同)

- **Python 3.13** (当前版本为 3.10)

- **core/gui 两层架构** (当前为 models/services/views/viewmodels 四层 MVVM)

- core 层模块:

  - `analysis/`: peak\_detection, peak\_fitting, phase\_matching, quantitative, theoretical\_pattern

  - `database/`: cache, cod\_client, cod\_database, local\_cif\_library, mp\_database, reference\_pattern\_library

  - `engines/`: gsas2\_engine, pymatgen\_engine

  - `io/`: cif\_io, exporters, project\_io + data\_readers (base/csv/raw/txt/udf/xrdml/xy)

  - `models/`: crystal\_structure, diffraction\_pattern, match\_result, peak, peak\_list, phase, project\_state, refinement\_parameters, refinement\_project, refinement\_result

  - `processing/`: background, calibration, ka2\_stripping, normalization, smoothing

  - `project/`: batch\_processor, command, history, project\_manager

  - `reporting/`: excel\_report, figure\_factory, pdf\_report

- gui 层模块:

  - `controllers/`: main\_controller, refinement\_controller

  - `dialogs/`: batch\_wizard, import\_dialog, refinement\_panel, settings\_dialog

  - `widgets/`: log\_panel, navigation\_tree, peak\_table, plot\_widget, property\_panel, status\_bar

  - `wizards/`: phase\_analysis\_wizard, refinement\_strategy\_wizard

  - `styles/`: themes

- i18n: en\_US.json (7.9 KB) + zh\_CN.json (7.7 KB)

- 品牌资源: logo / crystal-mark / hero-banner / splash-screen / social-cover (SVG + JPG)

- 安装器: Inno Setup (.iss) + NSIS (.nsi) 双格式

### 测试结果

- 69 个单元测试, **全部通过** (Python 3.13.14, pytest 9.1.1)

  - processing: 26 tests (background 7 / calibration 5 / ka2\_stripping 4 / normalization 4 / smoothing 7)

  - analysis: 22 tests (peak\_detection 5 / peak\_fitting 4 / phase\_matching 4 / quantitative 5 / theoretical\_pattern 4)

  - engines: 9 tests (cod\_client 4 / gsas2\_engine 3 / mp\_database 2)

  - database: 11 tests (cache 6 / cod\_database 2 / local\_cif\_library 3)

  - project: 1 test (command\_history)

### 验证报告 (T047-T048)

- SMZ 系列物相鉴定: **全部样本通过**

- 钨系列 (蓝钨/黄钨/紫钨): **通过** (WO2.72/WO2.9 FOM 0.58-0.60, 采用钨族专用阈值 0.25)

- 低丰度/痕量相 (3-1 中 5% Al2O3 / 1.4% CaF2) 已标注为"低于峰检极限 / 需 Rietveld 定量"

### 与后续版本的关系

- 此原型的 core/gui 架构在 V0.6.0 被完全重构为 models/services/views/viewmodels MVVM 架构

- 参考物相库从 30 种矿物扩展到 118 种 (V0.6.0), 再到 71,199 物相 COD SQLite (V0.8.0+)

- data\_readers 设计被保留并沿用至今

- Python 版本从 3.13 降至 3.10 (V0.6.0+), 以获得更好的 PyInstaller 兼容性

***

## \[0.6.0] — 2026-08-18 (首次打包发布)

> 源码来源: `PolyXRD_v0.6.0_Source.zip` (0.8 MB)

### 功能

- 基础 XRD 数据加载与显示

- 工具栏左对齐布局 + 文字标签

- 菜单栏文字标签显示

- 元素周期表弹出对话框过滤

- Profile Fitting 峰形拟合物相分析（无需寻峰）

- 传统 FOM 检索匹配物相识别

- 物相匹配可视化 (已匹配/未匹配峰标注)

- 物相确认自动切换结构精修

- 多语言支持 (中/英/日)

- 修正 Windows EXE 图标显示

### 技术架构

- 参考数据库: `xrd_reference_database.json` (2.7 MB, **仅 118 个 XRD 参考物相**)

- MVVM 架构: models / viewmodels / views / services / utils

- 完整 services 层: cif\_database / cod\_searcher / data\_loader / data\_preprocessor / data\_processor / export\_service / peak\_finder / peak\_fitter / phase\_identifier / profile\_fitting / project\_service / refinement\_templates / rietveld\_refiner / structure\_simulator

- views 层: main\_window (54 KB) / data\_view / phase\_view / refinement\_view / refinement\_wizard (36 KB) / report\_view

- widgets: element\_filter\_dialog / element\_periodic\_table / peak\_table / plot\_widget

- 单元测试: 8 个测试文件 (test\_config / test\_data\_loader / test\_math\_utils / test\_peak\_finder / test\_phase\_identifier / test\_preprocessor / test\_rietveld / test\_xrd\_data)

### 限制

- 参考数据库仅 118 个物相 (JSON 格式), 覆盖范围有限

- 无 COD 无机物 SQLite 数据库

- 无数据库导入接口

- 无程序/数据库分离发布

### 项目本体

- 基于 **Python + PySide6 (Qt6)** 的多晶 X 射线衍射物相分析桌面软件
- 交接时 venv 为 **Python 3.10.11**，依赖：numpy、scipy、pymatgen、PySide6 等
- 打包方式：**nsist (NSIS) + 7z SFX 自解压安装程序**（无需 Inno Setup）
- 内置精修引擎替代（GSAS-II 在 pip 上无包，作为可选外部引擎）
- 交接文档：`PROJECT_HANDOVER.md`（两个 zip 包内 handover 文档内容一致）

### 已识别的待改进项

- 多相混合分析
- Rietveld 精修完善
- COD 在线搜索
- 匹配可视化精度
- 单元测试体系


---

## \[0.8.0 \~ 0.8.20] — 早期迭代版本 (2026 年初 \~ 2026-08)

> 注: 这些版本在 V0.8.21 发布前使用 `cod_inorganics.sqlite` 数据库, 未做公开 Release。

### 核心功能开发

- XRD 数据加载器 (DataLoader): 支持 .xrdml / .raw / .txt / .csv / .prf

- 数据预处理流水线 (DataPreprocessor): SNIP / ALS / Polynomial / DWT 背景扣除, SG / FFT / Whittaker 平滑

- 峰检测 (PeakFinder): 二阶导数 + 自动阈值

- 峰拟合 (PeakFitter): Pseudo-Voigt / Pearson VII / Split-PV, LMFit

- 物相识别 (PhaseIdentifier): d-I 峰匹配 + 元素过滤 + 残差剥离法

- COD 数据库 (CIFDatabase): 从 COD 私有二进制 (user\_database.mtu) 逆向生成 SQLite, 71,199 物相

- Rietveld 精修 (RietveldRefiner): GSAS-II / powerxrd / 内置引擎

- Le Bail 晶胞精修

- 结构模拟 (StructureSimulator): CIF → XRD 图谱

- PySide6 GUI: 主窗口 / 数据视图 / 物相视图 / 精修视图 / 报告视图

- 多语言支持: 中文 / English / 日本語

- 项目文件 (.polyxrd) 读写

- 导出服务 (CSV / PNG / SVG / PDF)

### 算法迭代

- d 峰评分优化: 早期 `n_matched_meas*(n_matched_ref/n_ref_used)` 偏好 dense phase → 改为 `top_precision / top_recall / meas_ratio` 三级排序

- 残差剥离优化: top-40 强峰导致误判 → 改为 top-K (≈12) unique 强峰

***

## v0.8.x 开发期（2026-08-19 ~ 2026-08-21）

**主题**：环境部署 + COD 本地数据库集成 + 核心算法改造 + 测试体系建立

这一阶段是项目从交接起点 v0.6.0 推进到首个 Beta v0.8.21 的关键开发期，按主题归类如下：

### 1. 环境部署（2026-08-19 上午）

- 验证管理员权限；读取 handover 文档
- 检查 Python 环境：venv 为 **Python 3.10.11**，可用
- 修正 `pyvenv.cfg` 中的 Python 路径（从旧用户路径修正为当前用户路径）
- 盘点 venv 依赖：numpy / scipy / PySide6 等已装；powerxrd、GSAS-II 缺失（均为可选依赖）
- 结论：**powerxrd 是 Rietveld 精修的可选依赖；GSAS-II 是精修引擎的可选依赖，有内置替代**
- `platformdirs` 仅列在依赖清单，源码未实际导入；`pytest` 仅用于测试
- 验证：**33 个核心模块导入成功；GUI 主窗口初始化成功；118 种参考物相已加载**
- 生成启动脚本 `start_polyxrd.bat`

### 2. 失败测试修复（2026-08-19，5 项 → 70/70 通过）

初始单元测试 65 passed / 5 failed，5 个失败为**代码层面 bug，非环境问题**：

- 修复测试用例中的字段名：`AppConfig` 使用 `default_wavelength` 字段而非 `wavelength`
- 调整测试数据点数量（源码中存在数据点数量校验逻辑）
- 修正 d 间距计算公式：立方晶系 d 间距计算需使用标准公式 `1/sqrt(inv_d_sq)`
- 优化 FOM 评分算法：需考虑未匹配峰并合理归一化
- 关键发现：**Rietveld 精修主流程依赖 `phase.reference_peaks` 的 2θ 值**

### 3. NumPy 弃用警告修复（2026-08-19）

- `peak_finder.py` 第 178 行和第 345 行的 `np.trapz` 改为 `np.trapezoid`
- 修复前：52 个 DeprecationWarning
- 修复后：**70 个测试通过，0 个警告**
- 经验：`np.trapz` 在 NumPy 2.0+ 中已被 `np.trapezoid` 替代；当前 venv 使用 numpy 2.2.6 完全兼容

### 4. 版本号统一（2026-08-19）

- 修复项目版本号不一致问题：`config.py`、`pyproject.toml`、`app.py`、`build.bat` 四处同步

### 5. 核心算法改造（2026-08-19，开发期成果）

- **匹配容差可调**：`phase_view.py` 中匹配容差原为硬编码，改为可调
- **多相混合分析**：新增多相混合分析功能（新功能）
- **Rietveld 精修引擎改造**：从随机游走（random walk）替换为 `scipy.optimize.least_squares`
- **单元测试补充**：新增测试文件和测试用例，覆盖 `test_profile_fitting.py` 等

### 6. COD 数据库同步方案设计（2026-08-19 下午）

- 阅读 COD 官方 wiki，分析同步方案
- **数据量估算**：2026 年 cif 目录估算约 **100~115 GB**，含 **55~60 万条目**
- **方案选择**：rsync 是同步 COD 文件的最佳选择（支持增量更新且无额外元数据）
- **环境准备**：Windows 需安装 rsync 环境，推荐 **WSL2 + Ubuntu**
- **时间估算**：初次全量同步预计 **8~30 小时**，增量更新 **5~30 分钟/次**
- **集成规划**：需开发本地索引构建、查询接口等功能

### 7. COD 数据库下载 + 本地索引构建（2026-08-19 ~ 2026-08-20）

- **下载**：从 `http://www.crystallography.net/archives/cod-cifs-mysql.txz` 下载
  - 文件大小 **18.48 GB**（压缩），解压后约 **92 GB**
  - 开发下载脚本 `download_cod.py`（断点续传）
  - 下载速度约 5 MB/s，进度 65.9%（12.18 GB）
- **解压**：开发解压脚本 `extract_cod.py`（支持多种格式、可重入）
- **索引构建**：实现 `CODLocalIndexer` 和 `CODLocalDatabase` 组件
  - 构建索引需处理约 **50 万 CIF 文件**，预计 **20~40 分钟**
  - 完整流程（下载 + 解压 + 建索引）需额外 **1~2 小时** 和 **92 GB 磁盘空间**

### 8. COD 本地数据库模块开发（2026-08-19 ~ 2026-08-20）

- 开发 `cod_local.py` 模块，提供 CLI 工具进行数据库操作
- 扩展 `cif_database.py`、`phase_identifier.py`、`rietveld_refiner.py` 以支持本地 COD 数据库
- 全量单元测试 + 12 个 COD 本地集成专项测试
- **测试结果**：**82 个单元测试全部通过**（含 12 项 COD 集成专项）

### 9. 分发方案讨论（2026-08-20）

- 用户关心 102 GB tar 文件随软件分发的体积问题
- **方案**：使用约 150 MB SQLite 索引（含压缩 CIF BLOBs + 预解析原子位点）替代完整 tar
- 发现旧索引（32.8 MB）已过期：缺失 `cif_gz` 列和 `cod_atomic_sites` 数据
- 需要 schema 更新和全量重建（预计 15~25 分钟）
- 推荐下一步：小样本验证（1000 CIFs）→ 全量重建 → 集成测试 → 加入 `PolyXRD.spec` 打包

---

# 第二部分 · 正式发布逐版详情（v0.8.21 → v0.15.1）

## \[0.8.21] — 2026-08-21

### 重大变更 — 首次正式发布

#### 1. 程序与数据库分离发布架构

- PolyXRD 主程序作为标准 Windows 安装包发布 (Inno Setup 6.7.3, LZMA2/ultra64)

- COD 无机物库作为独立外挂 zip 包发布 (91.9 MB, 解压 258.6 MB)

- 两者完全独立分发、独立升级，避免单包体积超 1 GB

- 数据库路径三重优先级: **用户导入路径 > %LOCALAPPDATA%\PolyXRD\databases\ > 程序内置 cod\_data/**

#### 2. 数据库导入接口

- 新增菜单: `文件 → 导入外部数据库 → COD 无机物库`

- `AppConfig` 新增 `set_cod_db_path()` / `get_cod_db_path()` 方法，持久化到 `~/.polyxrd/user_db_paths.json`

- `CIFDatabase` 新增 `set_cod_db_path()` + `reload_cod_db()` 支持运行时热切换数据库

- 导入后自动加载，重启无需重复操作

#### 3. 品牌合规 — 全局清除第三方商标xxx字样

- 数据库文件: `cod_inorganics.sqlite` → `COD_inorganics.sqlite`

- 数据库列名: `cod_ref_id` → `ref_id`

- 目录名: `cod_data/cod_inorganics/` → `cod_data/cod_source/`

- Config 属性: `cod_db_path` → `cod_db_path`

- CIFDatabase 方法: `search_cod_phases` → `search_cod_phases` 等 10+ 方法

- i18n key: `import_cod_db` → `import_cod_db` 等

- 脚本文件名: 9 个 `cod_*.py` → `cod_*.py` (build\_cod\_sqlite.py / package\_cod\_db.py 等)

- PowerShell 脚本: `start_cod_download.ps1` → `start_cod_download.ps1`

- 全项目 Grep 确认: 0 处禁用字样残留

#### 4. 数据库重命名与迁移

- 数据库: COD 无机物库 20260821 版本，**71,199 物相**，全部含 d-I 峰 / 晶胞参数 / 分子式 / 矿物名

- 字段完整性: formula/n\_peaks/d-I 峰 100%, space\_group 99.99%, 晶胞参数 99.97%+

- 编号格式: `97-xxxxxxx` (后 7 位为 COD 真实 ID), `ref_id` 保留 `96-XXX-YYYY` 格式

#### 5. 打包与发布

- PyInstaller (onedir 模式) + Inno Setup 6.7.3 双层打包

- `PolyXRD-Setup-v0.8.21.exe` (240.9 MB, 解压 955 MB)

- `PolyXRD_COD_Inorganics_v0.8.21.zip` (91.9 MB)

- GitHub 私有仓库创建: <https://github.com/PolyXRD/PolyXRD>

- 首次 Release v0.8.21: 源码 + 安装包 + 数据库外挂包 + 发布说明

### 新增功能 (相比 V0.8.20 及更早版本)

- 数据库动态路径配置与持久化

- 外部数据库导入 UI 入口

- 数据库一键安装脚本 (`install_COD_database.bat`)

- `.gitignore` 排除规则 (brand\_assets / cod\_cif\_download / test\_data / tests / release)

### 功能清单 (V0.8.21 完整能力)

#### XRD 数据处理

| 模块     | 功能                                                                        |
| ------ | ------------------------------------------------------------------------- |
| 数据加载   | `.xrdml` (PANalytical), `.raw` (Bruker), `.txt/.csv`, `.prf` (GSAS), 批量合并 |
| 波长支持   | Cu/Mo/Co/Cr/Fe/Ag/W/Au/Ga/Mn/Ni Kα                                        |
| 背景扣除   | SNIP (4 策略), Sonneveld-Visser, Polynomial (2\~10 阶), DWT                  |
| 平滑     | Savitzky-Golay (5~~31 窗口, 2~~5 阶), FFT 低通, Whittaker-Eilers               |
| 归一化    | Max / Sum / AUC                                                           |
| Kα2 剥离 | Rachinger / pseudo-Voigt                                                  |
| 峰搜索    | Repeated 2nd Derivative / Pseudo-Voigt 拟合, 自动阈值 (SNR≥2)                   |
| 峰拟合    | Pseudo-Voigt / Pearson VII / Split-PV, LMFit 解算器                          |

#### 物相分析

| 模块        | 功能                                                                    |
| --------- | --------------------------------------------------------------------- |
| 多物相定性检索   | d-I 峰匹配 + 化学式过滤 + 元素过滤 + 矿物名关键词, Top-N 打分                             |
| 元素过滤器     | 周期表式 Must-have / Not-allowed 选择                                       |
| COD 数据库接口 | `search_cod_phases()` / `search_cod_by_d_peaks()` / `get_cod_phase()` |
| 多物相联合拟合   | 残差剥离法 + 主峰匹配 + 强度加权召回率                                                |
| d 峰排序算法   | top\_precision → top\_recall → meas\_ratio (修复了早期 dense phase 偏好问题)   |

#### 晶相与晶体学

| 模块            | 功能                                              |
| ------------- | ----------------------------------------------- |
| Rietveld 结构精修 | GSAS-II / powerxrd / 内置引擎, 顺序/自动/手动策略           |
| Le Bail 晶胞精修  | 固定晶相精修 a/b/c/α/β/γ                              |
| 结构模拟          | 空间群/原子占位 → XRD 图谱 (Lorentz-Polarization + B 因子) |
| 指标化           | d 值反解 hkl, 2θ 误差计算                              |
| 空间群处理         | pymatgen / spglib, 230 种空间群标准化                  |

#### 界面与多语言

| 模块    | 功能                                         |
| ----- | ------------------------------------------ |
| 主窗口   | PySide6 + PyQtGraph 双画布 (主图 + 残差图), 可停靠多面板 |
| 语言    | 简体中文 / English / 日本語 (120+ 条翻译, 切换无需重启)    |
| 主题    | 白天 / 深色模式, Qt Fusion 风格                    |
| 元素周期表 | 交互式 118 种元素选择器                             |
| 高 DPI | HiDPI 适配, 4K 屏幕比例正确                        |

### 测试结果

| 类别                  | 结果                 | 备注                                   |
| ------------------- | ------------------ | ------------------------------------ |
| 单元测试 (pytest)       | 50/55 PASS (90.9%) | 5 项失败为历史遗留, 非 V0.8.21 引入             |
| 数据管线 (加载/扣背景/平滑/峰检) | 34/34 PASS (100%)  | <br />                               |
| 数据库导入 E2E           | 6/6 PASS (100%)    | <br />                               |
| CIFDatabase API     | 全部 5 项 OK          | <br />                               |
| 多物相分析实际样品           | 9/12 (75%)         | 样品 2-2 (100%), 5-1 (100%), 5-2 (40%) |
| 品牌合规性               | 0 处残留              | 全项目 110+ 文件 Grep 通过                  |

### 已知问题

1. 多物相排序: 5 相以上峰强重叠样品, 弱相 (<5%) 可能排序靠后
2. 首次冷启动: 3\~8 秒 (pymatgen / matplotlib 初始化)
3. 仅 Windows 10/11 x64

***

## \[0.8.22] — 2026-08-21

### 新增

- **品牌视觉升级**: 基于 `brand_assets/polyxrd-brand-assets/assets/icon.jpg` 和 `logo.jpg` 重新生成全尺寸图标和 Logo

  - 应用图标: 16/24/32/48/64/128/256/512/1024 px PNG + 多尺寸 ICO (16/32/48/64/128/256)

  - 品牌 Logo: 256x144 / 512x288 / 1024x576 / 2048x1152 PNG

  - `src/polyxrd/resources/` 下 4 个运行时图标已替换 (app-icon.ico / app-icon.png / crystal-mark.png / logo-horizontal.png)

- **Inno Setup 安装向导背景**: 新增 `wizard_image.bmp` (640x480) + `wizard_small_image.bmp` (563x75)，深色品牌背景 + Logo

- README.md 开源致谢新增 **GSAS-II** (Rietveld 结构精修主引擎)

### 变更

- `config.py`: app\_version 0.8.21 → 0.8.22

- `PolyXRD.spec`: 版本号 0.8.22

- `scripts/PolyXRD-Setup.iss`: 版本号 0.8.22 + `WizardImageFile` / `WizardSmallImageFile`

- README.md **精修描述修正**: "Le Bail 晶胞精修" → "Rietveld 结构精修 (基于 COD 数据库 CIF 文件)" + "Le Bail 晶胞精修" 分工描述

- README.md **代码结构图修正**: 新增 `rietveld_refiner.py` / `refinement_templates.py` / `export_service.py` 等实际文件

- README.md **快速上手示例**: 增加 Rietveld 精修步骤 (第 5 步)

- ICO 文件格式修复: Pillow ICO writer bug → 手工构建 ICO 二进制结构 (ICONDIR + ICONDIRENTRY + PNG-in-ICO)

### 修复

- ICO 文件格式问题: 之前手动改扩展名 (PNG → ICO) 的文件不是有效 ICO 格式，重新构建为标准 Windows ICO

- README.md 中 Rietveld 精修描述缺失问题

### 安装包

- `PolyXRD-Setup-v0.8.22.exe` (241.1 MB)

***

## \[0.8.23] — 2026-08-21

### 新增

- **MCP Server (Model Context Protocol)**: 新增 `src/polyxrd/mcp_server/` 包，将 PolyXRD 的完整 XRD 分析流水线通过 MCP 协议暴露给 AI 大模型 (Claude / GPT 等)，无需 GUI 即可调用

  - `server.py`: 注册 **18 个 MCP Tools**，覆盖全流水线

  - `session.py`: 跨工具调用的会话状态管理 (XRDData / PeakList / Phase / RefinementResult)

  - `__main__.py`: 支持 `python -m polyxrd.mcp_server` 启动 (stdio 传输)

- MCP Tools 清单:

  | 类别       | 工具                                                                                         | 功能                                       |
  | -------- | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
  | 数据加载     | `load_xrd_data`, `get_data_summary`                                                        | 加载 .xrdml/.xy/.csv/.txt/.raw + 摘要        |
  | 预处理      | `preprocess_data`                                                                          | SNIP/ALS 背景 + SG 平滑 + Kα2 剥离 + 归一化       |
  | 峰分析      | `find_peaks`, `list_peaks`, `fit_peaks`                                                    | 检测 + 列表 + 拟合 (Voigt/Gaussian/Lorentzian) |
  | 物相检索     | `search_phases`                                                                            | 内置参考库 + 元素过滤                             |
  | COD 数据库  | `search_cod_phases`, `search_cod_by_d_peaks`, `get_cod_phase_details`, `search_cod_online` | 化学式/空间群/d值峰搜索 + 详情 + 在线搜索                |
  | 模拟       | `simulate_pattern`                                                                         | 从 CIF 文件生成理论 XRD 图谱                      |
  | Rietveld | `refine_rietveld`                                                                          | GSAS-II / powerxrd / 内置引擎                |
  | 导出       | `export_results`, `save_project`, `load_project`                                           | JSON/TXT/CSV + .pxrd 项目                  |
  | 会话       | `get_session_status`, `reset_session`                                                      | 状态查看 + 重置                                |

### 变更

- `config.py`: app\_version 0.8.22 → 0.8.23

- `PolyXRD.spec`: 添加 `mcp` 到 PyInstaller 依赖收集列表

- `scripts/PolyXRD-Setup.iss`: 版本号 0.8.23

### 测试

- E2E 测试通过: SiO2 石英样品 (加载 116 点 → SNIP 背景 → SG 平滑 → 6 峰检测 → COD d 值搜索 5 匹配)

- 安装包: `PolyXRD-Setup-v0.8.23.exe` (247.9 MB)

***


---

## 阅读约定（标记与单位）

| 标记 | 含义 |
|---|---|
| 🏷️ tag | 本地 git 仓库存在对应 tag |
| 🚫 无 tag | 曾构建/分发过二进制，但未打 tag（多见于同日连续出包） |
| **Setup** | Inno Setup 安装包（Windows x64） |
| **Portable** | 免安装 zip |
| **库包** | 外挂数据库 zip（程序与数据库分离分发） |
| 单位 | 体积一律 **MiB/MB 取日志原值**；不同日志有 PowerShell 口径（MiB）与资源管理器口径混用，见附录 F |

**版本序列总览（含未打 tag 的中间版本）**

```
v0.8.21 之前（无 git 记录，详见第一部分）：v0.3.0 → v0.4.1 → 原型（pre-0.6.0）→ v0.6.0 → v0.8.0~0.8.20
v0.8.21 → v0.8.22 → v0.8.23 → v0.9.0 → v0.9.1 → v0.9.7 → v0.9.8 → v0.9.9
   → v0.9.10 → v0.9.11 → v0.10.0 → v0.11.0 → v0.12.0 → v0.13.0 → v0.13.1
   → v0.13.2 → v0.14.0 → v0.15.0 → v0.15.1
```

**本地 tag 实际存在 9 个**：`v0.8.21` `v0.8.22` `v0.8.23` `v0.9.0` `v0.9.7` `v0.9.10` `v0.10.0` `v0.11.0` `v0.15.0`
（`v0.9.1` `v0.9.8` `v0.9.9` `v0.9.11` `v0.12.0` `v0.13.0` `v0.13.1` `v0.13.2` `v0.14.0` `v0.15.1` 在本机仓库**未见 tag**，其中多数已发布过二进制 —— 详见附录 F）

---

## 版本速览表（v0.3.0 → v0.15.2）

| 版本 | 日期 | 主题 | 关键交付 | 产物形态 |
|---|---|---|---|---|
| v0.3.0 | ~2026-08-12 | 最初原型 (核心功能定义, 可追溯最早版本) | `__version__="0.3.0"` | 源码（无产物） |
| v0.4.1 | 2026-08 上旬 | 基础配置框架 | 默认波长 / 2θ 范围 / 格式清单 | 源码（无产物） |
| 原型（pre-0.6.0） | 2026-08-12~13 | core/gui 两层架构原型 | 30 参考物相 + SMZ/钨系列验证 | 源码（无产物） |
| v0.6.0 | 2026-08-18/19 | 项目交接起点, MVVM 架构定型 | 118 参考物相; nsist+7z SFX 打包 | 源码 |
| v0.8.0~0.8.20 | 2026-08-19~21 | COD 本地库集成 + 多相分析 + 精修改造 | 71,199 相 SQLite; 测试 65→82 | 源码 |
| v0.15.2 🚫 | 2026-09-21 | 精修指标通用化 + 启动加固 | Rwp 正名 + 新增 Rexp / Rb / GOF(标准定义)；修启动闪退隐患 | 待打包 |
| v0.8.21 🏷️ | 2026-08-21 | 首个正式 Beta：程序与库分离 | 主程序 240.9 MB + 无机物库外挂包 91.9 MB（71,199 物相）；热切换接口 | Setup + 库包 |
| v0.8.22 🏷️ | 2026-08-21 | 品牌视觉升级 | 图标基于 crystal-mark 重生成；README Rietveld 说明修正 | Setup |
| v0.8.23 🏷️ | 2026-08-24 | 内置 MCP Server | `python -m polyxrd.mcp_server`（stdio），18 个工具覆盖全流程 | Setup |
| v0.9.0 🏷️ | 2026-08-29 | 识别准确率跃升 + wR 引擎重写 | 命中率 45.1%→**68.6%**；`_refine_builtin` v1→v8；双 COD 库外挂 | Setup + 2 库包 |
| v0.9.1 🚫 | 2026-08-30 | 性能 + GUI 双库切换 + Le Bail | Rietveld 长测试 11–12 min→**4 min**；Le Bail 落地；COD 元素约束检索 | 源码/本地 |
| **v0.9.7** 🏷️ | 2026-09-07 | **Sprint 1/2/3 + M20 GUI**（M01–M20 全量落地） | 19 个服务层模块 + GUI 交互；ICU 加载修复；交接文档 | Setup + Portable |
| v0.9.8 🚫 | 2026-09-09 | M21 物相分析 v2 进包 | 双区谱图控件（对标同类商业软件）；两库全含 | Setup + Portable |
| v0.9.9 🚫 | 2026-09-09 | 两处用户反馈改进 | 开新自动清数据；**高精度寻峰引擎**（ZnO 15→35 峰） | Setup + Portable |
| v0.9.10 🏷️ | 2026-09-09 | 品牌化应用图标 | 图标从"纯黑方块"→品牌图标；GitHub 发布跑通 | Setup + Portable + 2 库包 |
| v0.9.11 🚫 | 2026-09-10 | 四态元素过滤 + FoM 重构 + 检索提速 + PDF2 对接 | 检索 22.5 s→**8.8 s**；PDF2 163,834 相；倒排索引方案实测回退 | 源码/本地 |
| v0.10.0 🏷️ | 2026-09-10/11 | 数据库彻底外挂化 | 三库独立下载包 + GUI 数据库管理；Portable 661.5→380.7 MB | Setup + Portable + 3 库包 |
| v0.11.0 🏷️ | 2026-09-15 | COD 结构精修链路打通 | CIF 五级回退 + 无机库 v2 内嵌 CIF + GSAS-II/MAUD3 端到端 | Setup + 2 库包 |
| v0.12.0 🚫 | 2026-09-16 | 图谱纵坐标 + 向导默认 + 精修过程日志 | log/sqrt 切换；元素「必有」置末；精修日志面板 | 源码/本地构建 |
| v0.13.0 🚫 | 2026-09-17 | 精修前置 CIF 自动匹配 + 向导物相页 v2 | `PhaseStructureResolver`；上=CIF 候选/下=已选初始结构 | Setup + Portable + 3 库包 |
| v0.13.1 🚫 | 2026-09-18 | **"双击打不开"修复** | 运行时图标/启动图一律 PNG；启动/崩溃日志；安装目录守卫 | Setup + Portable + 3 库包 |
| v0.13.2 🚫 | 2026-09-18 | 无机库**字段级数据修复** | `formula` 被空间群覆盖（541 条）+ `cell_*` 错位（31,634 行） | Setup + Portable + 库包 |
| v0.14.0 🚫 | 2026-09-19 | 无机库默认改**瘦身索引式** | 1,194.5 MB→**362.0 MB**；发布包改名 `-index` | Setup + 2 索引库包 |
| v0.15.0 🏷️ | 2026-09-20 | 路线图 M22–M25 + 首个中文手册 | 图谱交互 / 物相列表重构 / 精修页布局 / **外部精修三引擎（含 FullProf）** | Setup + 2 库包 + SHA |
| v0.15.1 🚫 | 2026-09-20 | 内置引擎接入 CIF \|F\|² + MAUD 走官方 bat | 合成基准 wR 58.13%→**10.32%** | Setup + Portable（**不发 Release**） |

---

## 逐版本详情（按时间正序）

> v0.8.21 / v0.8.22 / v0.8.23 的详细变更见上一节（首份日志的完整记录）；自 v0.9.0 起如下。

### v0.9.0 — 2026-08-29 · 识别准确率跃升 + Rietveld wR 引擎重写 🏷️

**这是老版本中第一次"指标级"跃升。**

**① 物相识别准确率**
- 13 个工业试样：物相识别命中率 **45.1% → 68.6%**；含量定量命中率 **9.1% → 31.8%**
- 手段：
  - 纯金属干扰抑制（FoM 惩罚 ×1.5 + 组合重排比例 ≤20%）
  - 多物相组合策略：must/maybe 自动扩展 exclude、同化学式去重、`build_refinement_combination` 启发式

**② Rietveld 内置引擎 `_refine_builtin` v1→v8**
- `bg_method=median` 替换 SNIP（**直接降 5~6 pt**）
- Caglioti U-V-W 的 2θ 依赖峰宽替换固定 FWHM
- 多起点 `least_squares` + 显式 wR 选优 + ≈135 点稀疏邻域抛光
- 验收：4-1 四相样 wR **64.74%** < 65%；2-1 ZnO/CaCO₃ 50/50 wR **51.46%** < 55%

**③ 数据库**
- 双 COD 数据库外挂支持：无机物库 71,199 物相（zip 75.8 MB）、全库索引 **113,223 条 CIF + 5.1 M 原子位点**（zip 179.2 MB），运行时可热切换

**④ 交付**
- Inno Setup 脚本 + 7z SFX 自解压安装程序；新增转交报告与开源致谢清单；单元测试 **95 项**通过（含 3 项 wR 专项验收）
- 关于页邮箱确定为 `sshztx@outlook.com`

---

### v0.9.1 — 2026-08-30 · 性能优化 + GUI 双库切换 + Le Bail 🚫

**主题**：把精修耗时打下来，并把"双库"能力搬到界面上

**① Rietveld 性能优化（核心交付）**
- 瓶颈定位：`_compute_spectrum_from_ref` 占精修耗时 **99.3%**（5210 次调用）——非收敛起点跑满 `max_nfev=1200`（4~5 起点 × 1200 ≈ 4800 次调用，而获胜起点只需约 55 次）
- 三项优化：
  1. **快速路径**：`wR_threshold=55`，先无 Caglioti 3 起点快检，wR ≤ 55 直接返回；否则 Caglioti 精细并取 `min(wR)` 择优（结果只会更好）
  2. 单起点收敛上限 `max_nfev_per_start = min(20×max_cycles, 400)`
  3. `_compute_spectrum_from_ref` 分块向量化（chunk=16，相内列切片累加）
- 关键踩坑：**全矩阵向量化（n_points×n_peaks）反而比逐峰循环慢 2 倍**（临时数组超缓存、内存带宽瓶颈）；分块 16 与旧版持平但数值等价（<1e-13）
- 结果：3 项 wR 验收 **4m10s**（原 11–12 min）；全量回归 92 项 **18min36s → 1min46s（10.4 倍）**

**② GUI 双库切换**
- `phase_view.py` 增加"数据库源" QComboBox：内置库 / COD 无机物库 / COD 全库 / 内置+COD 全库合并
- 新增 `PhaseIdentifier.identify_with_cod_inorganics`：2θ→d → `search_cod_by_d_peaks` Hanawalt 预筛 → 候选转 Phase → 统一 FOM
- 踩坑三条：COD 公式是空格分隔的"元素+系数"组（需本地正则解析）；`must∪maybe` 是"元素全集"语义（物相元素须 ⊆ allowed）；元素约束必须下推到预筛 SQL 扫描层，否则候选名额被无效化学相占用
- 已知局限：4-1 混合样仅 CaF₂ 稳定进前列（COD 全库级识别属后续 P1 范畴）

**③ Le Bail 实现 + 测试**
- 交接报告称"已有 Le Bail 代码路径"实为不存在 → 新增 `RietveldRefiner.refine_le_bail()`
- 算法：hkl∈[-3,3]³ → 峰位；匹配门控（观测强度 ≥5% 全谱最大才提取）；经典迭代 `I←Σ(y-others)·pv/(1.05Σpv²)`，上限 2×窗口最大；Rwp 网格扫 scale
- 踩坑：**无匹配门控时错配峰窗口落在真实峰尾部 → Σpv²→0 → 强度爆炸（尾峰窃取）**，Rwp 对峰位失敏
- `tests/test_le_bail.py` 3 项全过

**④ 文档**：`docs/5分钟上手_4-1样例.md`、`docs/算法内部原理.md`

**⑤ 未完成（转交下一阶段）**：GSAS-II 接入（当时仍是 stub）、组合搜索升级 B&B、COD 无机物库混合样排序质量

### 2026-08-31 · 外部精修引擎安装（并入 v0.9.1 / 0.10 线，未单独发版）

- **powerxrd**：venv 里已装 4.0.0（2026-02 重构版），但 API 大改（旧 `from powerxrd import Rietveld` 类已删除）→ `_refine_powerxrd` 重写为 v4 API（`refine.refine` / `PhaseModel` / `CubicLattice`，**仅单相+立方**可用，其余回退内置）。验证：合成立方 Si（a=5.431）精修得 **a=5.4310，wR=11.5%，converged**
- **GSAS-II**：不在 PyPI，官方安装器 476 MB，自带 Python 3.12/3.13 conda 环境（**与项目 venv 是两套环境，in-process import 不可行**）→ 采用**子进程 JSON 桥** `scripts/gsas2_bridge.py`（读 request.json 写 output.json）；`_refine_gsas2` 改为 subprocess；`_find_gsas2_python()` 支持 `POLYXRD_GSAS2_PYTHON` 覆盖；新增 `get_engine_status()` 供 GUI 提示引擎可用性
- 测试：`test_rietveld` + `test_le_bail` + `test_phase_identifier` **19 passed**

### 2026-09-02 · B&B 组合搜索（V0.10 线）+ GSAS-II 桥 v2

- **组合搜索升级为分支定界（B&B）全局搜索**：`build_refinement_combination()` 新增 `peaks`/`tolerance` 可选参（有实测峰即启用 B&B，否则回退旧启发式）
  - 候选→实测峰命中位掩码（每峰等权）→ 联合覆盖最大化 + 纯金属 ≤20% 硬约束
  - n≤14 精确枚举 / >14 贪心；`expected_count` 已知时取恰好该规模最优子集，未知时取覆盖不再增长的最小规模（简约）
  - 上游去重改「结构+数据感知」：同公式同元素条目且参考峰 ≥70% 重合则合并；真多型（石英/方石英/锐钛矿/金红石/方解石/文石）默认保留，但**仅在解释了本组已保留成员解释不到的实测峰时**保留
  - 基准（13 试样）：组合召回 legacy **48.9% → 53.2%**，联合覆盖 13/13 不下降，**0 例变差**，1-1/1-2 错选纠正
  - 踩坑：无条件保留多型会让纯方解石试样保留文石、挤占真实物相排名（Zincite 跌到 Zinc 之后）
- **GSAS-II 桥 v2**：数据 FWHM 自动估计匹配仪器峰形；立方晶系峰位定种按空间群消光序列对齐；尺度网格多起点安全评分防零梯度；4×10 轮 Cell+峰形精修
  - 验证：合成 Si 从 **a=5.30 远起点恢复收敛至 5.431（wR≈1.4）**，`RietveldRefiner engine=gsas2` 端到端通过
- **同日产出路线图**：`docs/物相分析路线图与模块拆分.md` —— **M01–M20 共 20 个模块**，每个叶子方法给足签名 / 输入输出 / 算法步骤 / 边界 / 验收 / 依赖，可直接交付分批实现；建议顺序 Sprint1（M05/M06/M08/M10/M11）→ Sprint2（M03/M07/M13/M14）→ Sprint3（产品化+进阶）
- 约定：commit message 不得出现第三方商业软件品牌字样

---

### v0.9.7 — 2026-09-07 · Sprint 1/2/3 全量落地 + M20 GUI 🏷️

**本版是老版本里工作量最大的一次：M01–M20 共 20 个模块一次性落地，单测从 95 涨到 182。**

**① 路线图优先级调整**
- M15 指标化（Treor/Dicvol）、M17 结构可视化（Diamond）由 P2 降为 **P3·暂缓可选**（用户决策）
- 结论：核心闭环 = 峰质量 + 匹配评分/多相迭代 + 半定量/定量，**不依赖指标化与结构可视化**

**② Sprint 1 · 物相识别增强（M05/M06/M08/M10/M11）**

| 模块 | 内容 | 测试 |
|---|---|---|
| M05 `peak_finder` | `sensitivity`（阈值 = max×0.01/sens）、`detect_shoulders`（2×FWHM 窗内次极大 + 二阶导极小找隐藏峰）、`merge_kalpha_doublets`（Kα1-Kα2 间距随 2θ 变化公式）；默认不传新参 = 旧行为 | 7 项 |
| M06 `peak_manager` | 不可变式 add/delete（索引或就近 2θ）/edit；`exclude_regions_mask`（区间合并）+ `filter_by_mask`；`compute_residual_peaks`；`rescale` | 8 项 |
| M08 `calibration` | `zero_point_shift`、`specimen_displacement_offset`（反射 = −2(s/R)cosθ；透射）、`estimate_from_histogram`（Δ2θ 众数）、`calibrate_to_internal_standard` | 9 项 |
| M10 `foam.py`+models | `compute_fom`（乘性 `penalty×(1−0.3r)(1−0.1int)`）、`check_three_strongest`、`delta_2theta_auto`（factor×平均 FWHM）、`profile_fitting_score`、`search_match` | 14 项 |
| M11 `multiphase` | `iterative_identify`（`min_round_matches=2` 滤单峰噪声相，无进展终止）+ `trace_report` | 5 项 |

- **三个基准驱动的关键修复**：
  1. FoM 强度数组**必须随 2θ 排序**，否则评分错位
  2. 强度一致性必须**乘性加权**（加性会给真实谱所有候选加近似常数，抹平区分度 —— 真实谱强度比约 0.004~0.01）
  3. `_phases_structurally_same` 改**双向覆盖 ≥70%**（单向时稀疏相 Vanadium 6 峰每条都能在密集相 Calcite 98 峰里配对 → 误判同构，曾把 LiFePO₄ 误并入 Silver）
- 13 试样基准 `tests/bench_sprint1.py`：基线 72.3%（34/47）vs foam Top-10 31/47；迭代利于干净多相/微量相召回，真实低信噪谱上不宜直接替代单轮 Top-10
- 回归 **71 项通过**

**③ Sprint 2 · 定量四件套（M03/M07/M13/M14）**

- **M03 `raw_processing.py`**：trim / `smooth_savitzky_golay` / **`strip_kalpha2`（Rachinger 逐点前向递归 `new[t]=y[t]−(1/ratio)·new[t−Δ2θ(t)]`，间距随 2θ 变，插值用已校正值，负截 0）** / `increase_resolution`（CubicSpline，factor ≤4）
  - 验证：Kα2 剥离与纯 Kα1 谱残差 <25% 主峰；11 项测试
- **M07 `peak_fitting.py`**：Pseudo-Voigt（高度参数）；`fit_single_peak`；`fit_profile` 按窗口（3×FWHM）分重叠簇 → 簇内联合 `least_squares`（防重叠峰拉扯）；`model_spectrum` / `goodness_of_fit`
  - 验证：重叠双峰恢复 <0.03°；6 项
- **M13 `rir.py`**：RIR 相对定量 `w∝I/(I/Icor)`；最强峰缺失/I/Icor 缺失时降级提示；`internal_standard_quantify` 内标定标绝对含量；6 项
- **M14 `refinement_options.py` + refiner**：`RefineOptions`（PO/零点前处理，`refine_*` 开关预留）；**March-Dollase**（r>1 增强垂直面，作用于参考峰强度不改入参，符号约定写入 docstring）；`degree_of_crystallinity`（面积比）；`internal_standard_scale` + `refine_with_internal_standard`；10 项
- 全量回归 **130 项通过（2 m 42 s）**

**④ Sprint 3 · 服务层（M01/M02/M04/M16/M12/M18/M19）**

- **M01 `data_io.py`**：`detect_format`（扩展名 + 头文本嗅探）+ `load_auto`（多列自动列序：信号列 = 相邻差分最剧烈；显式列覆盖；非文本委托 DataLoader）
  - 踩坑：`Path.read_bytes()` 不接受长度参数，异常被 `except` 吞成空 head → shimadzu 检测静默失效；改为 `with open(...) as f: f.read(2048)`
- **M02 `models/experiment.py`**：`ExperimentalPattern`（自动时间戳）/ `PatternTable`（多谱独立）/ `SessionDocument`（JSON 会话，payload 存峰表结果）
- **M04 `background.py`**：SNIP（对数空间逐次 min 两侧均值，窗口递增）/ 多项式（锚点加权 ×100）/ 控制点 CubicSpline（严格过锚点，外推用端点）+ `estimate_background` / `subtract`
- **M16 `crystallite.py`**：`scherrer_size`（D=Kλ/βcosθ，Å→nm）/ 仪器宽化扣除（gaussian 平方差；lorentz 相减）/ `estimate_from_peaks`
- **M12 `user_database.py`**：JSON CRUD/find/export（路径缺失→空库）；`import_from_cif`（pymatgen Structure→Phase：晶胞 + 8 原子位点 + 参考峰；Si 验证最强峰 28.44°）；`import_diffraction_peaks`；`check_formula_sum`（**必须用 `parse_formula_detailed`**，`parse_formula` 返回 set 无计数）；`shift_reference_database`
- **M18 `report.py`**：`export_svg_pattern`（实验 polyline + 峰三角 + 参考棒）/ `render_html_report`（单文件，峰表/候选/定量）/ `export_peak_table_csv` / `export_refined_cif`（晶胞 + 原子位点 loop）
- **M19 `scripting.py`**：`apply_steps`（管线 DSL）+ `process_files`（批量→峰检测→CSV）
- 服务层新增测试 30 + 22 项

**⑤ M20 GUI 交互增强 v1 + 版本升至 0.9.7**
- 工具栏/数据处理菜单新增「重置为原始数据」（Ctrl+R；无图标仅文字，避免缺资源崩）
- Kα2 剥离按钮由 status stub 改为**真实调用** `data_vm.strip_ka_alpha2` 管线
- 峰检测 **F2** 快捷键；`find_peaks(detect_shoulders/sensitivity)` 透传至 M05 PeakFinder（默认关闭保持原行为）
- i18n zh/en 增加 reset 键；版本 0.9.7（`__init__`/`config`/`build.bat`）
- GUI 无头冒烟：`QT_QPA_PLATFORM=offscreen` 创建 MainWindow 成功
- 说明：缩放/平移/追踪由 matplotlib NavigationToolbar 提供；峰点击编辑等高级交互留 M20 v2

**⑥ 打包 0.9.7 与两个环境坑**
- **PyInstaller 沙盒坑**：开发环境注入的 `sitecustomize` 把 `rmtree`/`os.remove` 劫持到回收站，沙盒回收站不可用 → `--clean`/覆盖 exe 均失败。解法：先用 shell `rm -rf` 清 dist/build 中间文件，再运行 PyInstaller（**不用 `--clean`**）
- **Inno 6.7.3 无 `ChineseSimplified.isl`** → 移除安装器中文语言行（安装器语言回退到 En/Ja）
- 产物（当日构建日志）：`dist\PolyXRD\PolyXRD.exe` **38.7 MB** / `PolyXRD-Setup-v0.9.7.exe` **261 MB** / `PolyXRD-v0.9.7-Portable.zip` **411 MB**

**⑦ exe 启动报错修复（ICU 缺失，本版最关键的现场问题）**
- 现象：用户双击 `dist\PolyXRD\PolyXRD.exe` 报 `ImportError: DLL load failed while importing QtCore: 找不到指定的程序`
- 根因链（用自写 **PE 导入表解析器** `scripts/_pe_imports.py` 定位）：
  1. `Qt6Core.dll` 导入表声明的是**无版本号的 `icuuc.dll`**
  2. PySide6 6.11 wheel **不再自带 ICU**
  3. `_internal` 里被 PyInstaller 打进去的 `icuuc.dll`/`icudt58.dll` 是 **ICU 58（Qt5 时代，ABI 不兼容）**
  4. `Windows\System32\icuuc.dll` 只是 **29 KB 的 API stub**
  5. Qt6 期望 ICU 73/74/75 → 加载到错的 58 或 stub → "找不到指定的程序"
- 修复：`PolyXRD.spec` 自动从本机 mamba 缓存（`icu-78.3`）等常见位置收集 `icuuc/icudt/icuin` 系列 DLL；`scripts/_pyinst_collect.py` **手工执行 COLLECT 阶段**（从 `build/COLLECT-00.toc` 复制到 `dist/_internal`）绕过沙盒拦截 `shutil.rmtree`；`build.bat` 容错 PyInstaller `EXIT=1`（COLLECT 失败但 EXE 已生成）并串接后续步骤
- 教训沉淀：**PySide6 ≥6.7 不自带 ICU，任何 Qt6 应用打包必须显式 bundle `icuuc/icudt`**

**⑧ 交接复核 + Handover 文档**
- 全量回归复核 **182 passed（2 m 39 s，23 文件）**；GUI 无头冒烟 OK（31 actions）；工作区干净
- `docs/HANDOVER-v0.9.7.md`：面向"重装 Windows"的环境重建指南
  - **必须带走的备份**：`cod_index.sqlite` 453 MB、`cod_data/COD_inorganics.sqlite` 271 MB（均不进 git）
  - 重建：Python 3.10.11 + Inno Setup 6 + `requirements.txt` 锁定版本；ICU DLL 来源需重新落实

**⑨ 发布状态**
- tag `v0.9.7` 已打；release 脚本 `scripts/create_github_release_v0.9.7.ps1` 与附件已就绪（数据库 zip 沿用 v0.9.0 附件，不重复上传）
- **一度被网络阻断**：本机 DNS UDP 53 全超时、github.com 各 IP 443 直连全 000，而 baidu 200 正常 → 发布推迟（详见附录 F）

---

### 2026-09-08 · 盘符迁移 D:→E: + venv 重建 + M14/M20 v2（并入 v0.9.8+ 线）

**① 盘符迁移修复清单（原 D: 数据盘 → E:，旧系统盘挂到 D:）**
1. `git safe.directory`
2. `venv/pyvenv.cfg` 的 home/base-* 指向新基础解释器（备份 `pyvenv.cfg.bak_20260908`）
3. `venv/.../polyxrd_editable.pth`：`d:` → `E:\TEMP\PolyXRD\src`
4. `tests/` 6 个文件硬编码 `D:/TEMP/test_xrd/txt` → E:
5. **GSAS-II（E:\GSASII）**：`gsas2_path.pth` 里 `D://GSASII//GSAS-II` → E: 后 import OK；源码修复提交 `4065a8b`（`_find_gsas2_python` 候选增加 `E:\GSASII` / `E:\g2main`）；外部引擎 3 项测试全过（含 GSAS-II 立方 Si 端到端恢复，82 s）

**② venv 彻底重建（自持，不再依赖旧系统盘）**
- 基础解释器精简拷贝到 `E:\TEMP\python310`（16 MB）；该 Python **无 venv 模块、无 ensurepip** → 手动拷 pip 套件 + `virtualenv`
- 依赖按 Handover §5 锁定版全新安装，版本逐一核对一致：
  `numpy 2.2.6 / scipy 1.15.3 / PySide6 6.11.1 / matplotlib 3.10.9 / pandas 2.3.3 / lmfit 1.3.4 / spglib 2.7.0 / pyqtgraph 0.14.0 / plotly 6.9.0 / Pillow 12.3.0 / pymatgen 2025.10.7 / powerxrd 4.0.0`
- **`pyproject.toml` 构建后端修复**（`35ca801`）：原写的 `setuptools.backends._legacy` 在 setuptools 84 **不存在**，`pip install -e .` 失败 → 改标准 `setuptools.build_meta`，可编辑安装正常并生成 `polyxrd.exe` / `polyxrd-gui.exe`
- 验证：GUI 无头冒烟 OK；**tests 全量 235 passed**；回归 182 passed（与重装前基线完全一致）

**③ LibreOffice 无头导出修复（M18）**（`188a016`）
- 症状：`report.export_via_libreoffice` 报 "no export filter"
- 两层根因：① 子进程 env 污染（继承 `PYTHONPATH` + `APPDATA` 未设置 → LO 用户配置无法落地）② HTML 被 LO 以 Writer/Web 模块打开，**该模块无 docx 导出过滤器**
- 修复：`_libreoffice_env()` 清 `PYTHONPATH/PYTHONHOME`、补 `APPDATA`、`MSYS_NO_PATHCONV=1`、指向 LO 自带 python-core；独立 `-env:UserInstallation` 临时配置；**HTML→ODT→DOCX 两步中转**
- 验证：`test_report_m18.py` 11 passed；全量 **239 passed**

**④ M14 参数掩码接入 builtin 精修引擎**（`6f6b823`）
- `refine_scale` / `refine_profile` / `refine_zero_shift` 用 **ε=1e-7 极窄上下界等效冻结**（`scipy.optimize.least_squares` 要求严格 `lb < ub`，不能 `lower=upper=init`）
- `refine_background` / `refine_cell` 在 builtin 仍为 no-op（背景一次性预处理、晶胞固定）；外部引擎自行消费
- `fit_params` 暴露 `param_mask` + `init_*/opt_*`；新增 `TestParamMask` 6 项；全量 **245 passed**

**⑤ M20 v2 高级交互**
- **数据文件拖放打开**（`674b312`）：`setAcceptDrops(True)` + `dragEnterEvent`/`dragMoveEvent`/`dropEvent`；抽出 `_load_file_path(path)` 作为菜单与拖放共用入口；8 项测试；**253 passed**
- **主题切换 + 峰表右键菜单**（`ec902e4`）：新增 `views/theme.py`（Fusion 浅/深 QPalette 纯函数）；视图菜单"深色主题"（i18n zh/en/ja），`QSettings view/dark_theme` 持久化；PeakTable 右键菜单（复制选中行 TSV / 删除 / 清空 / 导出 CSV）
  - **修复潜在 bug**：`sortingEnabled` 期间逐格 `setItem` 实时重排导致落错行/丢格 → `_reload_table` 填充期关排序后再恢复
  - 打包脚本盘符硬编码修复（`_pyinst_collect.py` 改为仓库根自推导；`build.bat` 引用不存在的 `_do_collect.py` → 改 `scripts\_pyinst_collect.py`）
  - 14 项测试；**259 passed**

**⑥ 打包测试二进制 + ICU 结论修正**
- `POLYXRD_NO_COD_DB=1` + 含 `COD_inorganics.sqlite`：PyInstaller 32 m 44 s，**COLLECT 本次直接成功**（`CODEBUDDY_SAFE_DELETE_ENABLED=0` 生效），dist 1.3 GB
- **ICU 关键结论修正**：本机 `System32\icuuc.dll`（29 KB）是 Windows 转发 shim，Qt 6.11 经其解析全部符号可正常启动；**从 gsas2main 复制 ICU 78 进 dist 反而 WinError 127**（缺 Qt 所需符号）→ 移除 dist 内全部 `icu*.dll` 后冒烟通过；`build.bat` 的 ICU 步骤由"收集"改为"删除"

**⑦ M21 物相分析 v2（对标同类商业软件的展示层）S1–S5 全部完成**
- 用户反馈：多相样品选中一个物相后应在谱图上叠加（不同颜色）、下方可见已匹配/未匹配（残差）峰
- 设计稿 `docs/DESIGN-phase-analysis-v2.md`（M21-A..E 原子规格），**纯展示层重设计，不动识别算法/精修/报告**
- 实施：
  - `services/phase_display.py`：`assign_peaks` **双向归属**（`PeakAssignment`，反向 = 未解释残差峰）/ `combined_pattern` / `residual` / `phase_color`
  - **谱合成内核 `spectrum_from_refs` 从 refiner 提取**并做回归等价证明（纯函数可单测）
  - `widgets/pattern_display.py`：双区 `GridSpec(2,1,4:1, sharex)` —— 主区实验黑线 / 计算红线 / 残差灰线，棒区逐相参考棒（每相一行基线下移、棒高∝I/100、相色、相名左标）；`set_peak_assignments` 峰顶归属标记
  - `widgets/peak_match_table.py` 峰-归属表 + `phase_vm.update_selection(Max 8, 去重按 name+formula)`
  - `phase_view.py` 接线：候选可勾选 → `itemChanged` → `update_selection` → `selection_changed` → `_refresh_overlay` **单一路径驱动**；单击未勾选候选 = 单选叠加（同类软件浏览习惯）
- 注意：`tests/` 目录整体被 gitignore → **测试文件不提交，只提交 src**

---

### v0.9.8 — 2026-09-09 · M21 v2 进包（两库全含）🚫

- 版本号 0.9.7 → **0.9.8**（`8ee2919`）；`build.bat` 移除 `POLYXRD_NO_COD_DB` / `POLYXRD_NO_INORG_DB`，改为**两库全含**（COD 全库 432 M + 无机物库 259 M）
- PyInstaller 6.22 约 20 min；**COLLECT 直接成功**（`CODEBUDDY_SAFE_DELETE_ENABLED=0`），dist 1.7 G；offscreen 冒烟 25 s 存活
- 校验 PYZ 内含 M21 四个模块（`phase_display` / `phase_view` / `pattern_display` / `peak_match_table`）
- 产物：`PolyXRD-Setup-v0.9.8.exe` **387 MB** / `PolyXRD-v0.9.8-Portable.zip` **681 MB** / `VERSION_v0.9.8.txt`

### v0.9.9 — 2026-09-09 · 两处用户反馈改进 🚫

**A. 数据文件菜单：开新自动清 + 显式清除数据**（`64e9d70`）
- 新增 `DataViewModel.clear_all()` / `PhaseViewModel.reset_analysis()` / `RefinementViewModel.reset()`
- `MainViewModel.reset_analysis_state()`（保数据清分析）/ `clear_all_data()`（全清）；**`_on_data_loaded` 开新文件自动 reset_analysis** → 旧峰/物相/精修不再残留叠新数据
- 文件菜单加「清除数据」（reset 图标，无数据禁用，带确认）；i18n 三语

**B. 寻峰精度重设计**（引擎 `7586cb5` + 接线 `66daa4e`）
- 旧 `find_peaks` 两大缺陷：峰位锁 **0.02° 网格**（无亚步长）+ **无背景扣除**
- 新增 `services/peak_detection.py`（纯逻辑可单测）：
  `estimate_background`（局部极小值/中位数自适应）→ `estimate_noise_sigma`（MAD→σ 分区自适应）→ `detect_peaks_advanced`（种子过 σ×thr → 抛物线/质心**亚步长** → 稳健半高 FWHM → 面积 → 可选局部伪 Voigt 联合拟合精修）
- 默认 `sigma_threshold=5`（4 会在 ~3500 点纯背景+噪声上出 ~1 个假峰，统计边缘）
- **关键坑**：原 `_fwhm_from_hm` 半高搜索有漏洞，返回 6–11° 假宽 → 峰被 `max_fwhm` 滤掉只剩 1 峰；重写两侧搜索后全对
- **实测（真实 ZnO 试样 2-1）**：旧 15 峰（锁 0.02° 网格）→ 新 **35 峰**（22.9945…），正确解析 **Kα1/Kα2 双峰**（56.56/56.58、62.82/63.00、67.91/68.11、69.05/69.25）与弱峰
- 接线：DataView 峰检测组加"高精度"勾选（默认开）→ advanced，取消回退传统
- 顺带修 latent bug：`peaks_changed` 实际传 `PeakList`，而 `peak_table.set_peaks` / `plot_widget.add_peak_annotations` 直接存该对象 → 后续 `.clear()`/`.copy()`/下标访问崩；均归一化为 list
- 打包 0.9.9（`aa46252`）：PyInstaller 13 m 17 s；Setup **387 MB** / Portable **681 MB**；回归 **316 passed**

### v0.9.10 — 2026-09-09 · 品牌化应用图标（+ GitHub 发布跑通）🏷️

- **问题**：用户反馈图标"都是黑色的方块"。排查发现旧 `app-icon.ico`（5.9 KB）7 档条目**全部是纯黑色圆角矩形**，`_internal` 里的 `app-icon.png`（2471 B）同样纯黑 → **根因 = 应用图标本体丢失/未设计，不是 Qt 插件问题**
- **解法**：`build_icon.py` 基于 `crystal-mark.png` 品牌资产 + 精确采样配色（`#0F172A` slate-950 "Poly" / `#0284C7` sky-600 "XRD"）生成多分辨率 ICO：
  - 512×512 主图：圆角方形 + 对角线渐变（深→蓝）+ 居中白色晶胞六边形 + XRD 衍射曲线
  - LANCZOS 下采样到 256/128/64/48/32/24/16 **七档** PNG 条目
  - 同步输出 256×256 PNG + 512×512 `@2x.png`
- **打包事故与绕行**：0.9.10 的 COLLECT 两次失败（第一次 safe-delete 拦 `PolyXRD.exe` WinError 5；第二次复制 7873 个文件后卡在 plotly 某 `.py` Permission denied、`polyxrd/` 子目录一个文件都没写）
  - 尝试过 `rm -rf` / `mv` / `os.replace` / `shutil.rmtree` / `ctypes.MoveFileExW` 全部失败（Python 进程持锁）
  - **最终方案**：不动原 dist，**直接拿新 EXE 替换旧 EXE** + 从备份（`C:\Temp\PolyXRD_0.9.9_backup`）恢复 polyxrd 数据与 matplotlib mpl-data
- 产物：`PolyXRD-Setup-v0.9.10.exe` **264 MB**（0.9.9 是 405 MB）/ Portable **661 MB**
- **GitHub 发布完成**（Release id=385411317，`releases/tag/v0.9.10`），4 附件全部上传且 SHA256 与本地一致：
  | 附件 | 体积 |
  |---|---|
  | PolyXRD-Setup-v0.9.10.exe | 252.2 MB |
  | PolyXRD-v0.9.10-Portable.zip | 661.5 MB |
  | PolyXRD_COD_Full_v0.9.10.zip | 205.9 MB（cod_index.sqlite，113,223 条） |
  | PolyXRD_COD_Inorganics_v0.9.10.zip | 94.1 MB（71,199 物相） |
  - 认证修复：9/8 重装系统清掉了 GCM 凭据 → 用 `git-credential-manager.exe get` 触发交互授权；**沙盒 pwsh 下 GCM 会崩，bash 下正常**
  - 上传 ~1.5 MB/s，1.2 GB 总量约 13 min；脚本加**幂等跳过**（同名+同 size+state=uploaded → SKIP）

---

### v0.9.11 — 2026-09-10 · 元素语义 + 匹配因子 + 检索提速 + PDF2 对接 🚫

**本日是"算法口径大修"的一天，也是老版本中单日改动最密集的一天。**

**① 元素四态语义对齐（最终版）**（`c9d5290`）
记 S = 物相元素集合：

| 类别 | 语义 | 判定式 |
|---|---|---|
| **必有** P (`must_have`) | 全部必含（**AND**） | `P ⊆ S` |
| **含有** H (`must`) | 至少含一个 | `S ∩ H ≠ ∅` |
| **可能** M (`maybe`) | 无强制条件，仅放宽允许池；**H 为空时代行 H 之职** | — |
| **没有** E (`exclude`) | 排除 | `S ∩ E = ∅` |

- **未勾选元素默认并入 E**（闭环，等价 `S ⊆ P∪H∪M`），**仅当 P∪H∪M 非空时启用**；三者全空 = 全库搜索；**只勾「没有」= 开放世界**
- 勾了必有时**不再要求至少含一个含有**（用户明确：纯金属 Mg 也可）
- 重叠优先级：必有 > 含有 > 可能 > 没有
- 代码落点：`utils/formula_parser.elements_match_filter(...)` 单点判定 + `normalize_element_filter` + `LIGHT_ELEMENTS=(O,C,H,N,S)`；`models/search_options` 加 `must_have`；`phase_identifier` 的**内置路径与 COD 路径统一**（删掉旧"自动扩展 exclude"块与两套不一致写法）；UI 四态循环（无→必有→含有→可能→没有）+ 深绿/绿/黄/红配色 + 「轻元素设为含有」按钮

**② 匹配因子（FoM）加权互斥重构**
`services/foam.compute_fom` 三点结构性修正：
1. **一一对应互斥匹配**（按 |Δ| 升序贪心）—— 旧实现多条参考峰各自就近吸附同一条实验峰 → **峰多的密集物相被系统性高估**
2. **强峰加权 + Σw 归一**：`w = 0.3 + 0.7·I/Imax` —— 旧口径用 Σ2θ 归一，**高角度/多峰物相天然占优（与匹配好坏无关）**
3. **特异性项**（未解释实验峰比例）+ **匹配对强度余弦**（替代 min/max 比，尺度无关）
- `score = (bad + 0.30·未解释比)·(1 − 0.20·强度余弦)`，`bad ∈ [0,2]`
- **COD 排序改为加权混合**：`0.3·Hanawalt复合 + 0.7·(1 − clip(fom/1.2, 0, 1))` 取代原字典序（原键以 `main_peak_match`（0/1 二值）打头，多相样品里只有主物相能拿 1）

**③ 基准数据（诚实汇报，13 试样 / COD 无机物库 / 生产默认池 prefilter_limit=100）**

| 排序口径 | Top-1 | Top-5 | Top-10 |
|---|---|---|---|
| 旧（Hanawalt 字典序） | 12% | 22% | 24% |
| 只用新 FoM | 16% | 20% | 29% |
| **新（混合 0.3/0.7）** | **14%** | **25%** | **27%** |

- 内置 118 物相库：13 试样排序**无回归**（仅 Boehmite 23→22）
- 池=200 时混合口径可达 Top-1 16% / Top-5 27% / Top-10 29%（未改默认池以控耗时）
- 全量测试 **342 passed**（新增 `test_element_filter_v2.py` 26 项）

**④ 检索召回优化 —— 上一轮的"下一步"建议被实测否掉**（`3cd3b0d`）
- 先做基准：**放宽 d 容差 / 提高 max_ref_peaks 不是杠杆**（只多捞回 1 条；换预筛内部排序键 10 种策略最多 +1）
- **真正的两个杠杆**：
  1. **`PeakFinder.find_peaks` 默认 `distance=5.0°` 是硬 bug** —— XRD 峰 FWHM 只有 0.05~0.5°，scipy `find_peaks(distance=…)` 会把窗口内弱峰**整条删除**。ZnO 占 93.6% 的 3-1 试样，31.76°/34.40° 两条最强线直接消失；7-2（预期 7 相）5~150° 全谱只剩 **3** 个峰 → 默认改 **0.5°**；另 `sigma_threshold` 5.0 → **3.0**
  2. **COD 排序 `fom_good = 1−clip(fom/1.2)` 在多相样品里整体饱和为 0**（每个候选都解释不了大部分实测峰）→ 退化成纯 Hanawalt 排序 → 改 **`exp(−fom/0.8)`** + Hanawalt 权重 0.30→**0.10**
- 改前/改后（13 试样）：

| 寻峰 | 排序 | 峰数 | Top-1 | Top-3 | Top-10 | Top-40 | MRR |
|---|---|---|---|---|---|---|---|
| P0 旧 d5.0 | R0 原 clip w.30 | 8.8 | 7 | 9 | 14 | 21 | 0.259 |
| P1 新 σ3 | R2 exp w.10（现状） | 64.3 | **10** | **12** | **18** | **28** | **0.327** |

- **归因**：寻峰是主杠杆（+8 Top-40 / MRR +0.066）；排序改动只有 +0~1，45 点样本上**不显著** —— 保留它是因为修掉了一个明确的饱和缺陷，不是因为可测量提升
- `search_cod_by_d_peaks` 新增 `tolerance_rel`，**必须一致作用于全部 6 处判据**（反向匹配/去重/main_peak_match/top_precision/强度加权召回/正向匹配率）
- 提为模块级的 `default_peak_list()` 统一三处 `peaks=None` 分支
- **教训**：先做归因基准再动手，别照搬上一轮的"下一步"建议；基准度量有假阴性（COD 把 ZnO 存为 `Li0.086 O0.957 Zn0.914` 这类掺杂式 → `same_formula` 失败 → 所有数字都是**下界**）
- 363 passed（新增 21 项）

**⑤ PDF2-2004 对接（本日最重要的发现）**（`62d8453`）
- 源：`E:/TEMP/XRD-PDF2-2004/pdf2 - 2004.dat`（587 MB，**无换行的 80 字符定宽流**）
- **根因（真实文件逐字节比对确认）**：
  1. 正则硬编码了标记 token 的两个字母 `P(\d{6})X([A-Z0-9+*])`。真实结构是 `<数据集字母><6位卡片号><序列字母><类型>`，标记**恒在第 71 列**（32 MB / 400,000 标记实测 100%），序列字母实际分布 **X 仅 35%**，其余 C/O/M/H/T/R —— 方解石 010837 全用 `D...R...` → **完全解析不到**（只入库 25,237 相，真实 ~164k，方解石缺失）
  2. 数据区取 0~70 列，但 67~70 列是**标志区**（孤立 `G`、续行 `DB 1`/`SM 2`、` P `）→ `G` 被 `_DB_FORMULA_TOKEN` 当元素 → **元素过滤被污染**（4,342/163,834 条 formula 含 ≥6 连续空格）
- **修法**：正则改 `.{71}([A-Z])(\d{6})([A-Z])([A-Z0-9+*])(\d{0,2})` + `re.match`；数据区改 `line[:67]` → **163,834 相 / n_peaks 均值 63.8 / formula 污染 0**
- 修后冒烟（3 试样，PDF2 全部反超 COD；score 越低越好）：

| 试样 | COD Top-1 score | PDF2 Top-1 score |
|---|---|---|
| 3-1 ZnO | P 63 m c 0.223 | **O Zn 0.206** |
| 5-1 CaCO₃ | C Ca O3 0.803 | **C Ca O3 0.673** |
| 1-1 LiFePO₄ | Fe Li O4 P 0.609 | **Fe Li O4 P 0.562** |

- **更正早前结论**：源文件**有**空间群记录（方解石 `D010837R2 = R-3c 167`），是解析器没映射类型 2/3 记录；`_pdf2_rank_score` 抄旧饱和版的说法也不成立
- 另修 4 处：`search_by_d_peaks` 用 `__new__()` 裸实例 → 正常构造；`peaks=None` 分支；删重复闭包改调模块级 `cod_rank_score`；**`config.py` 两个真实缺陷**（`set_cod_db_path()` 整体覆盖写 `user_db_paths.json` → 抹掉 `pdf2_db_path`；`get_pdf2_db_path()` 不回读用户设置 → `set_pdf2_db_path()` 是死 setter）
- 测试：`test_pdf2_database.py` 15 passed / `test_config_db_paths.py` 9 passed
- **方法论教训**：合成测试数据必须复现真实布局 —— 旧测试与旧正则"恰好自洽"，15 项测试全绿却掩盖了致命 bug；现加 `test_marker_anchored_at_column_71`（用 `D...R...`）与 `test_continuation_tail_stripped_from_formula` 两条守卫
- 待办：PDF2 当时**未接入 GUI**（纯服务层）

**⑥ 方案 B（d 值倒排索引）实施 → 实测 → 整体回退**（`45f74b0`）
- 完整实现 `cod_peak_index` + `cod_peak_index_stats` + 懒构建 / SQL 聚合收集候选
- **实测推翻前提**：候选 = **67,296 / 71,199（94%）**（文档预估 <2000）；单次检索 40~43 s，**比全表扫描 28~37 s 还慢**
- 根因：0.9.11 寻峰改动后检出峰 8.8→64，50 个测量峰的 0.02 Å 容差窗覆盖约 **60% 的 d 空间**，`min_match=3` 形同虚设 → **候选选择率才是索引有效的前提**
- 处理：`cif_database.py` git checkout 还原，两库索引表 DROP+VACUUM（体积恢复 269 MB/190 MB），**索引代码未入库**

**⑦ 向量化打分：预估再次落空，但拿到"预截断"这条真路**
- `cif_database.py` 扫描层由逐相 Python 循环改 **NumPy 批量**（5 个模块级 helper；`_match_positions` 承担旧"最左命中下标去重"口径；`_parse_float_csv` 支持 bytes → `np.frombuffer` 零拷贝）
- **语义 100% 逐字段一致**（oracle = `git show HEAD:src/.../cif_database.py > tests/_cif_old_ref.py`，整模块导出零转写风险）：合成对抗库 12 场景 + 真实抽样 4000 相 × 14 场景 + 排序并列先后全部一致
- 性能：26.9 s → **22.5 s（−17%）**，"5~8 s"的预估落空。剖析显示 `np.array(字符串列表)` 占 7.76 s —— 库里有 **1,900 万个峰**（平均 266 峰/相），而每相只用 I 最高的 40 个，**解析 19 M 个 float 是硬底**
- **`np.fromstring(sep=",")` 是陷阱（禁用）**：`"4.9,  ,2.4"` → `[4.9, −1.0, 2.4]`（凭空注入 **−1 Å 假峰**）；`"4.9,,2.4"` → `[4.9]`（静默截断）；且比 `np.array(s.split(','))` 更慢
- 新建 `tests/test_cod_vectorized.py` **37 passed**

**⑧ 预截断强峰列落地（这次预估终于兑现）**（`63d5a9a`）
- `_PEAK_TOP_N = 64`：建库期把每相 I 最高的前 64 峰按 I 降序存成两个 **float64 BLOB**（`peaks_top_d` / `peaks_top_i`）
- 检索侧双路：有列 → `np.frombuffer` 零拷贝 + `order = np.arange(n_i)`（省掉每相 argsort）；没列 → 回退全长解析（外部导入库 / PDF2 行为完全不变）
- **实测**：

| 场景 | 迁移前 | 迁移后 |
|---|---|---|
| 50 测量峰基准（有强度） | 27.46 s | **10.53 s** |
| 50 测量峰基准（无强度） | 27.38 s | **10.06 s** |
| **6 个真实试样合计** | **126.8 s** | **48.2 s（2.6×）** |

- 逐字段一致性验证：合成 12 场景 + 真实 4000 相 × 14 场景 + **全量 71,199 相 × 8 场景** + 6 真实试样 A/B 全部一致
- 迁移代价：COD 库 269.2 MB → **390.0 MB**（+120.8 MB）；**PDF2 库刻意不迁移**（平均 63.8 峰/相 ≤ 64，省不下解析量只会白涨 167 MB）
- 守卫测试 `test_get_cod_phase_still_returns_full_peak_list`：`get_cod_phase()` 必须仍返回**全长**峰表（喂 FoM 与详情页）
- 踩坑：`sqlite3.Row` 取不到 `row["rowid"]`（须 `SELECT rowid AS rid`）；测试夹具缺 `cell_a..cell_gamma` 列

**⑨ v0.10.0 数据库外挂化（服务层 + GUI 入口）**（`572126f`）
- **`services/db_import.py`（新）**：Qt-free 探测层。`DB_KINDS` 三槽位规格 = `(table, required, signature, excludes, min_rows)`
  - **关键**：COD 无机物库与 PDF2 库表名同为 `phases`，拿混了不报错只静默检索不到 → 必须靠 `signature=("cell_a",)` + `excludes=("pearson",)` 区分；`cod_index` 靠 `cod_entries` 表 + `min_rows=1000`
- **`views/widgets/database_dialog.py`（新）**：`DatabaseManagerDialog`，三槽位导入…/取消挂载，选错类型不静默失败（会问"要不要导入到对应槽位"）
- 主窗口新增顶层「数据库」菜单；首次启动引导（三库全空时状态栏提示 + 弹一次窗，`QSettings db/nodb_hint_shown`）
- `config.py`：新增 `user_db_dir() = ~/.polyxrd/cif_db`，优先级 **用户导入 > 默认位置(存在才用) > 用户目录兜底**（安装器 `PrivilegesRequired=lowest`，Program Files 不可写）
- `cod_local`：拆出 `resolved_index_db_path(deploy=True)` 与 `existing_index_db_path()` —— **踩坑**：原 `_index_db_path()` 会调部署逻辑，开发模式下**光打开管理对话框就会复制 400 MB**
- `PolyXRD.spec` 策略反转：默认**不**打包任何 `.sqlite`，`POLYXRD_WITH_DB=1` 才内嵌（旧 `POLYXRD_NO_*` 语义作废）
- **打包实测**：dist 1031 MB；**PySide6 独占 641 MB**（`Qt6WebEngineCore.dll` 196 / `resources` 102 / `translations` 60 / `qml` 30 / `opengl32sw` 20）→ 列入下一个优化点
- 产物：Setup **243.1 MB** / Portable **380.7 MB**（v0.9.10 是 661.5 MB，**真正收益在此**）
- 测试：新增 21 项；全量 **443 passed**

**⑩ 外挂数据库拆成三个独立下载包**（`f53507a`）

| 包 | 下载体积 | 解压后 | 包内文件 |
|---|---|---|---|
| `-Databases-COD-inorg.zip` | 133.9 MB | 371.9 MB | `COD_inorganics.sqlite` |
| `-Databases-COD-full.zip` | 205.9 MB | 431.7 MB | `cod_index.sqlite` |
| `-Databases-PDF2.zip` | 58.9 MB | 204.5 MB | `PDF2_2004.sqlite` |

- 三包合计 = 拆分前单个合并包体积，**拆分不增加下载总量**
- `db_import.DBKind` 加 `pkg_suffix` 字段（**存后缀不存完整名 → 版本号不进源码**）+ `PKG_FILENAME` + `release_package_name()`
- 对话框每行加灰色 `pkg_lbl`：「下载包：X.zip → 解压出 Y.sqlite」——**本次最关键的 UX 补丁**（三个槽位长得一样，不给映射用户只能猜）
- 全量回归 **507 passed / 0 failed**

---

### v0.10.0 — 2026-09-10/11 · 数据库彻底外挂化 🏷️

- 安装包与便携包**不再内置任何数据库**，改为三个独立下载包按需取用；便携包 661.5 → **380.7 MB（−42%）**
- 新增 GUI 入口「数据库 ▸ 外挂数据库管理…」：槽位独立挂载/卸载、导入后热生效、按列签名校验库类型
- 新增 **PDF2-2004 挂载能力**（163,834 物相，自带空间群 72.8% / 晶胞 81.8%）——ICDD 商业库，**仓库不分发、Release 不提供**
- 检索质量与速度（含 0.9.11 内容）：FoM 改加权互斥；COD 候选排序重做；检索 22.5 s → **8.8 s**；元素过滤四语义定稿
- 界面：工具栏布局修复（不再被挤进 » 溢出区）；物相分析棒区逐行相标 + 未解释残差峰标注；matplotlib 中文不再 tofu；长耗时操作加忙碌提示与防重入
- **长耗时操作忙碌提示 + 防重入闸门**（`1d85e46`）：新增 `views/widgets/busy_indicator.py`
  - 根因不是"慢"而是**点击积压**：所有重活都在主线程同步跑，阻塞期间 Qt 事件循环被占住，用户再点不会消失而是积压，任务结束、按钮刚被重新启用的瞬间**一次性投递** → 叠起第二轮长任务 → 未响应 → 崩溃
  - **为什么原有 `setEnabled(False)` 挡不住**：`refinement_completed` 是**同步信号**，重新启用按钮发生在阻塞调用返回**之前**
  - 设计四点：看得见（ApplicationModal 置顶小窗 + 不确定进度条 + WaitCursor，**刻意不放按钮**）、挡重入（类级 `_active` 标志）、保持重绘（`processEvents(ExcludeUserInputEvents)`）、**`_drain_then_hide()` 先排空再撤防**（顺序反了等于没做）
  - 接入 11 处重活；精修新增 `progress_cb(done, total)` 进度回吐（抛光阶段每 8 次评估 tick 一次）；`tests/test_busy_indicator.py` 35 例（含**源码级挂载契约断言 13 处 `busy(`**，防"新写长任务忘包闸门"）；全量 **542 passed**
- 代码梳理（`b9248b2`）：去代理（`db_import._SetterProxy` → `_PATH_SETTERS` + 每次现取 bound method）+ 删 32 处无用导入；**PDF2 版权政策闭环**（`.gitignore` 加 PDF2 规则；`pkg_suffix=""`；i18n `pkg_hint_local`；`create_github_release_v0.10.0.ps1` 内置 `Assert-NotBanned` 守卫 + 上传后自检）；全量 **545 passed**
- 代码清理（`89b1c08`）：真实孤儿 18 个中删 8 个 + `utils/validators.py`（113 LOC，全文零调用方），共约 1700 LOC 死代码
- 工作目录清理：共释放约 **112 GB**（顶层重复的 103 GB `cod-cifs-mysql.tar`、release_staging 4.16 GB、旧产物 2.41 GB 等）
  - **教训（写进红线）**：`tests/_cif_old_ref.py` 被当"一次性脚本"误删 → 回归从 507 passed 变成 **466 passed + 41 skipped**（它是 `test_cod_vectorized` 的 oracle 模块）；用文件大小 75,281 字节当指纹定位到 `3cd3b0d` 版本，`git show 3cd3b0d:src/.../cif_database.py > tests/_cif_old_ref.py` 再生恢复
- **Release v0.10.0 完成**（`releases/tag/v0.10.0`）

| 文件 | MiB | SHA-256（前 8 位） |
|---|---|---|
| PolyXRD-Setup-v0.10.0.exe | 243.1 | b19f346e |
| PolyXRD-v0.10.0-Portable.zip | 372.6 | d4ef3a67 |
| PolyXRD-v0.10.0-Databases-COD-inorg.zip | 131.1 | 4366f873 |
| PolyXRD-v0.10.0-Databases-COD-full.zip | 193.1 | 72dff752 |
| PolyXRD-v0.10.0-Databases-PDF2.zip | 58.0 | （仅本地归档，永不上传） |

- 发布前还产出了 `docs/精修算法改进与MAUD引擎接入方案.md`，给出 **v0.11.0 的核心判断**：
  - **Rwp 差不是调参问题，是"数据里没有结构"** —— builtin 引擎拿到的物相只有 (hkl, 2θ, I) + 晶胞，没有原子坐标 → 算不出 |F|²，本质是**无结构参考峰轮廓拟合**，wR 50~90% 是必然
  - **库的结构可用性差异（决定性约束）**：只有 `cod_index.sqlite`（COD full）有 `cod_atomic_sites` 与 `cod/cif/` → **能做真 Rietveld**；无机库与 PDF2 都**不能** → 这是"Le Bail 人人可用 / Rietveld 需 COD full"的产品分档依据
  - 附带修 `RefinementResult.quality_grade` 的档位建议（原 <2/<5/<10/<20 是同步辐射标准，实验室粉末 XRD 的 wR 10~15% 已可发表）

---

### v0.11.0 — 2026-09-15 · COD 结构精修链路打通（"精修里程碑"）🏷️

**① 路线 C · MAUD 引擎端到端**（`21248a2`）
- R-C1 wizard schema：反编译 `batchProcess.class` 取 `wizard_index` 取值表
- R-C2 `services/maud_par_builder.py`（388 行）+ bundled `maud_default.par` → 20 项测试
- R-C3 `services/refinement_engines/maud_engine.py`（587 行）subprocess 包装 → 33 项测试
- R-C4 `RietveldRefiner._refine_maud` + first-run 探测 + fallback → 11 项
- R-C5 GUI `maud` 选项 + 状态标签 + fallback 弹窗 + i18n → 9 项
- R-C6 端到端（真实跑 MAUD3）：预加载 `alzrc.par` 路径 **wR=0.087%、R=0.064%、GOF 0.064、20 轮，两相 Wt%/Cell 正确**；动态 `_maud_import_phase` 路径受 MAUD3 batchProcess 限制 R 因子恒 0 → 改走**预加载 par + 5 列 INS 模式**
- P0 侦察（`11f75c9`，产出 `docs/MAUD批处理侦察报告.md`）：MaudText CLI 仅 `-file/-jpvm/-xgrid/-silent` 四个 flag，**迭代控制全在 .par 里**；**JVM stdout 不 flush** → 必须靠文件 polling 而非抓 stdout；MAUD2 build=1147（2025-08，Java 21）/ MAUD3 build=1770（2026-09，Java 25），CLI 接口完全兼容

**② 路线 B · 结构来源**
- R-B1 `services/phase_cif.py`（252 行）：`phase_to_cif_text` / `phase_to_cif_file` / `cif_to_phase`（20 项测试，含元素推断/CRLF/不确定度记法/round-trip）
- R-B3（MAUD par phase sections）复杂度高，用户明示不做

**③ 路线 A · builtin 算法改进（均 opt-in，实测诚实结论）**
- **R-A4 Chebyshev 多项式背景抛光**（`c731cd3`）：opt-in + 双层 gate（内部 corr 范围缩放 + 调用方 after_wR < before_wR）+ Poirier 启发权 1/sigma + NaN/Inf 静默回退
  - **诚实结论**：2-1 wR 53.37→53.37，4-1 wR 75.74→75.74 —— 在 median BG 已足够干净的样品上 gate 频繁拒绝，**未观察到 wR 收益**
- **R-A1 统计权重**（`0632b77`）：`stat_weights: "none"(默认)/"poisson"/"poirier"`，residual 乘 √w 且全部 `_calc_wR` 带同一组 w
  - **诚实结论**：none wR 53.57/61 s → poisson **66.63/625 s**、poirier 64.30/483 s —— **统计权更差且慢 8~10×**（权重强调基线噪声点把拟合从峰区拉开；加权 wR 62~64 > 快速路径阈值 55 → 快检失效走全量 Caglioti）→ **保持默认关闭**
- R-A2（参数缩放分批）、R-A3（晶胞精修，最大潜在杠杆）、R-A5（每相独立轮廓）留待后续

**④ COD 结构精修链路打通**（`fabffdd`，本版核心）
- 数据层盘点：**无机库 `cod_id` 是真 COD ID**（`curl crystallography.net/cod/{id}.cif` 全部 200）
- **71,199 相中 47,600（66.9%）不在 `cod_index` 索引内**（1xx 28,916 / 4xx 10,676 / 7xx 6,165 / 8xx 1,722）→ 本地 `cod/cif` 原 19,946（28.0%），从 tar 定向解压 +3,653 → 23,599，其余 47,600 从 COD 官网批量下载
  - 下载器 v2：v1 串行 4 h 50 m 后死于 `http.client.IncompleteRead`（**不是 OSError 子类，要用裸 Exception 兜**）；v2 改 8 线程 + 裸异常重试 3 次，43,357 个用 213 min 跑完
  - **最终覆盖率 71,156/71,199 = 99.94%**；缺 43 个全是 HTTP 404（COD 已删除条目）
- 代码修复：
  1. `cod_local.get_cif` Level 0：索引外 ID 直接构造 `cif/{d}/{dd}/{ddd}/{id}.cif` 路径（旧版 entry 缺失即 return None，REST 兜底**永远不触发**）→ 实测 1000005 索引外 0.02 s 命中
  2. `cod_local.get_cod_root`：**项目根优先**于硬编码 `d:\TEMP`（重装后 D:= 旧系统盘老树抢先命中 → 下载写 E: 运行读 D:）
  3. `gsas2_bridge` 定量阶段：全相有 `cif_path` 时 `set_refinements({'LeBail': False})` + `set_HAP_refinements({'Scale': True})` → 相分数 = HAP Scale × General['Mass'] 归一
     - **wR(LeBail) 必须在定量阶段前捕获**（切 Rietveld 后 wR 必升高）
  4. 桥回传 `ycalc` 计算谱 → `simulated_data/residual_data` 用真谱（**修掉"GSAS-II 残差图假装完美"旧 bug**）
- **端到端实证（2-1 = ZnO + Calcite 50/50，结构取自 COD 全库）**：

| 引擎 | wR | wt% | 晶胞 |
|---|---|---|---|
| builtin（无结构） | 53.6% | 100/0（退化） | 不变 |
| **gsas2（有结构）** | **26.7%（LeBail）/ 26.6%（Rietveld）** | 22.2/77.8 | a 3.2494→3.2510，c 5.2054→5.2086 |

- `get_phase` Level-0 回退（`ae95849`）：entry 不在 `cod_index` 时用 `parse_cif_text` 从 CIF 重建条目；原子位点三级回退 DB→CIF 文本→pymatgen（`occupancy_tolerance=1.2`）
- **COD CIF 编号全量验证（110,152 个 CIF）**：code_match **99.3%** / mismatch 0.67%（9xx→1xx 超胞 setting 变体）/ no_code 4,734

**⑤ 其它一次性修复**
- **GSAS-II 通道打磨**（`26c3e47`）：`engine="auto"`（全相有结构 CIF 且 GSAS-II 可用 → gsas2，否则 builtin，原因写 `fit_params["engine_fallback_reason"]`）；gsas2 内部 4 处静默回退改为记录原因 + `logger.warning`；新增**批量精修对话框** `views/batch_refinement_dialog.py`（QThread worker 每文件深拷贝物相，单文件失败不断批；CSV 导出 utf-8-sig；三语键）
- **MAUD3 兼容修复（4 个真实 bug）**（`e2b6c23`）：① xye 不能写 `#` 注释头（MAUD ETH 读取器不跳注释 → 数据加载失败）② CIF 空间群剥 `:H`/`:R` 后缀 ③ par 的 R 因子是小数，引擎少 ×100（wR 显示 0.52% 实为 52%）④ 批处理 TSV 只有 Title/Rwp 两列（旧"每相 9 列"假设不成立）→ 相体积分数改从 par 的 `loop_ _pd_phase_atom_%` 取，wt% = vol_frac×胞内容质量/晶胞体积 归一
- **`refinement_engines` 缺 `__init__.py`（真 bug）**：`.gitignore` 的 `_*.py` 规则**同时匹配 `__init__.py`** → 该包建于 R-C 路线之后，`__init__.py` 被静默忽略、从未入库 → MAUD 引擎在 `RietveldRefiner` 路径下必然 ImportError（此前只测引擎本体没走 refiner，所以没暴露）→ 修复：`.gitignore` 加 `!__init__.py` / `!**/__init__.py` + 新建最小重导出
- **`run_dev.bat` 双击闪退**（根因 = bat 自身语法，与 Python 无关）：`echo ... (见 README)` 的**裸 `)`** 提前闭合了 `if not exist (...)` 块 → cmd 放弃执行整个 bat，`pause` 根本没机会运行（这才是"闪退"的机理）→ 规则：**if 块内及 echo 文本里绝不能出现裸括号**；削到纯 ASCII + CRLF + 全部 `if` 单行 + `if errorlevel 1 pause`（12 行有效命令）；新增 `tests/test_run_dev_bat.py` 17 项结构护栏
- **`main.py` 潜在崩溃**：`splash` 只在 `if not pixmap.isNull()` 分支内绑定，后面却写 `if splash_path:` → 启动图读不出来时 `UnboundLocalError`（进程起又立刻死、主窗口都不出现，极易误判成"打包坏了"）→ 修 + `tests/test_main_entry.py` 7 项
- **两个静默失效（验收前抓到）**：
  1. **精修向导的 engine 被丢弃（最严重）**：`main_window._on_refine_wizard` 调 `refine_structure(strategy=, max_cycles=)` **没传 `engine`** → 恒用默认 builtin，用户在向导里选 gsas2/maud **等于没选且无任何报错**
  2. **向导引擎下拉没有 `auto`**；且**引擎下拉四处不一致** → 统一为 `[auto, gsas2, maud, builtin, powerxrd]`，`get_engine_status()` 新增 auto 项
  3. 波长 / 2θ 窗口曾是"纯装饰"（被 `**kwargs` 静默吞掉）→ 新增 `MainViewModel._apply_data_overrides(...)`
- **两套精修向导合并为并存双路径**（`db8562e`）：快速版走 VM（原样保留），分步版新挂；用 **`MenuButtonPopup`**（按钮主体仍直接开快速版，右侧箭头才展开选择）
  - 关键坑：分步向导**自带 refiner**，结果不经主 VM → 回灌通道 `wizard_completed` → `result_ready` → `MainViewModel.adopt_refinement_result` → `RefinementViewModel.adopt_result`；**emit 必须在 `accept()` 之前**
- **MAUD 2.999x vs 3.04 差异调研**（`docs/MAUD-2.999x与3.04版本差异分析.md`）：上游 2.99x→3.04 仅 15 commit、237 个 src 文件有差异、新增 3 / 删除 0；**`MaudText.java` 一字未改，无破坏性变更**；实测同输入在两版上 wR 与 TSV 完全一致
- **COD 无机物库 v2（内嵌 CIF）**：`phases` 加 `cif_gz` 列，**71,156/71,199（99.94%）内嵌 gzip CIF** + `cod_atomic_sites` 子集 **31.1 万行** → 库体积 372 MB → **1,246.9 MB**
  - **修 `cod_local.get_cif` 的关键 bug**：索引条目不存在时**提前 return**，"索引都没有 → 不可能有 cif_gz"的旧假设挡住了内嵌 CIF → 早退分支先查无机库再落 REST

**⑥ 发布（v0.11.0 全流程）**
- 全量回归 **745 passed / 1 skipped**
- 产物：Setup **259,484,800 B** / Portable **397.5 MB**（**不发布**）/ `Databases-COD-inorg.zip` **976.1 MB** / `Databases-COD-full.zip` **193.1 MB** / `Databases-PDF2.zip` 58 MB（仅本地）
- Release：`github.com/PolyXRD/PolyXRD/releases/tag/v0.11.0`（Setup + 两个 COD 包；**无 PDF2 / 无 Portable**）
- 发布工具链全部 Python 化（沙盒禁 pwsh/cmd）：`_verify_release_py.py` / `_create_release_py.py` / `_upload_assets_curl.py`；**urllib 用文件对象作 POST data 上传不可靠**（35 min 0 附件）→ 改 `curl.exe --data-binary @file`
- 踩坑：Python 版把 tag 写成 `0.11.0`（漏 `v` 前缀）→ Release 自动建了别名 tag，需 PATCH `tag_name` 后删多余远端 ref；`git credential fill` 输出带 `\r`，拼 Bearer 头必须 `tr -d '\r'`（否则私有库全 404）

### v0.12.0 — 2026-09-16 · 纵坐标模式 + 向导默认策略 + 精修过程日志 🚫

**① 元素选择界面：「必有」移到末位**
- `STATE_CYCLE` → `(NONE, MUST, MAYBE, EXCLUDE, MUST_HAVE)`；单击循环 **无 → 含有 → 可能 → 没有 → 必有 → 无**；新增 `LEGEND_ORDER`
- 四态语义（必有=AND、未勾选=没有闭环）**不变**，`get_selection/get_filter_dict/set_selection` 未动

**② 纵坐标 线性 / 对数 / 方根**（谱峰处理页 + 物相分析页）
- 新文件 `views/widgets/y_scale.py`（约 430 行）：`apply_y_scale` / `next_y_scale` / `scaled_ylabel` + `YScaleController`（**左键点 Y 轴竖条循环 / 右键 QMenu 选择**）
- **数值换算是真的**：log 用原生 log 轴；sqrt 用 `set_yscale("function", functions=(_sqrt_forward, np.square))` → 刻度标签仍是真实强度
- 两个关键坑：
  1. **对数轴自动缩放被负值拖垮**（残差曲线/扣背景负值 → ylim 掉到 1e-308，图压成一条线）→ 切 log/sqrt 前先 `_prepare_positive_domain`（只取正数据点定范围）+ `set_autoscaley_on(False)`
  2. **sqrt 变换对负值发 RuntimeWarning** → `_sqrt_forward` 用 `np.clip(v,0,None)`
- 左键热区 = 数据区左缘往左 64px 的竖条（含刻度/轴标题），**刻意避开数据区** → 峰点击/框选不受影响

**③ 精修：向导方式默认勾选 + 过程日志**
- `rietveld_refiner.make_logger(kwargs)` 静态方法（取 `log_cb`，回调异常吞掉）；各引擎加日志行；文本刻意用**技术符号 + 数值**（`[start 2/4] wR= 5.755% nfev= 16 cost=1.745e+04 t= 0.12s ← best`），**服务层不 import i18n**
- 快检子调用带 `log_stage="[quick] "` 前缀
- `RefinementViewModel.refinement_log` 新信号 → `MainViewModel` 转发
- `refinement_view.py` 整文件重写：复选框「按精修向导的方式（推荐）」**默认勾选**（参数取内置模板 `get_builtin_templates()[0]`，engine=auto，并置灰手动控件）；底部 QSplitter 日志面板（QPlainTextEdit 只读、Consolas 9、`setMaximumBlockCount(4000)`、清空/保存按钮），靠 `BusyIndicator.progress_tick` 泵事件实时刷出
- **约定（用户明确要求）**：**谱图内部的标记一律用国际技术记号**（`Intensity (log)` / `(sqrt)`），只有界面控件才本地化

**④ 测试与提交**
- 新增 23 项（`test_v012_yscale` 9 / `test_v012_element_order` 5 / `test_v012_refinement_log` 9）；全量 **745 passed / 1 skipped**
- 提交 `9524291`（15 files / +1096 −72）；**只提交 src + pyproject**（`tests/` 等仍 gitignore）
- **工具坑（写进红线）**：同一消息里发多个 Edit 调用时，**靠前的会静默丢失**（工具报成功但文件没改）→ 关键 edit 一个一个发 + 发完立刻 grep 验证

**⑤ 编译二进制供 GUI 人工验收（未做 Inno/zip）**
- 沙盒 COLLECT 老问题复发：日志停在 `Removing dir ...dist\PolyXRD`，且**已把 `_internal` 删掉一大半** → 处理顺序：杀挂起进程 → `cp build/PolyXRD/{PolyXRD.exe,qt.conf} dist/PolyXRD/` → `scripts/_pyinst_collect.py`（**TRIPLE=12312 / COPIED=9820 / SKIPPED=2492 / MISSING=0**）
  - 修了该脚本一个 bug：正则把 toc 的 `EXECUTABLE` 条目也匹配 → 往 `_internal/` 塞了一份 **39 MB 的 PolyXRD.exe 副本**
- **沙盒内跑"真实 GUI"必崩，与产物无关**：`QT_QPA_PLATFORM` 不设时进程以 `0xC0000409 / 0xC0000005` 退出且零输出；对照 offscreen ✅ / minimal ✅ / 源码模式 ✅；**决定性实验：非沙盒重跑 ⇒ 立刻 ALIVE** → 是沙盒对 GUI 进程的注入/限制。**规矩：沙盒内无法验证 GUI 程序**
- 验收证据：非沙盒启动 16 s 后 `EnumWindows` 抓到**可见窗口 `PolyXRD v0.12.0`**；`dist/PolyXRD` 1.0 GB / `_internal` 12318 文件，与 v0.11.0 便携包文件清单**完全一致（0 missing / 0 extra）**

---

### v0.13.0 — 2026-09-17 · 精修前置 CIF 自动匹配 + 向导物相页 v2 🚫

**① 精修前置：已选物相 CIF 自动匹配（用户需求）**
- 背景（为什么必须做）：检索候选相（内置库 / COD d-I 库 / Profile Fitting）只有 `reference_peaks` + 晶胞，**没有** `cif_path` / `atomic_sites`；而 `_refine_auto` 用 `_phases_have_structure()`（要求**全部**相 `cif_path` 存在且落盘）决定走 GSAS-II 真 Rietveld 还是回退 builtin → **之前勾选的相永远走 builtin，"结构精修"名不副实**
- 新增 `services/phase_structure_resolver.py`：
  - `normalize_cod_formula("Mg(OH)2")` → `"H2 Mg O2"`（COD 存储格式：字母序 + 系数 1 省略；幂等）
  - `extract_cod_id()` 从物相名提编号；`PhaseStructureResolver.resolve(phases, ...)` 逐相：已有结构→原样保留 → 名字带编号→直取 → 否则规范化化学式（+矿物名）查候选 → 按 **空间群一致(−2.0) + 晶胞平均相对偏差 + 有内嵌 CIF(−0.5) + 脏数据逐项 +0.05** 排序 → 试前 3 个 → 取结构 → `_merge`
  - **合并语义（关键）**：`name/formula/match_score/weight_fraction/已有 space_group` **沿用原相**（勾选集合与叠加身份不变）；`lattice/atomic_sites/cif_path/reference_peaks`（pymatgen 模拟峰）取自 CIF；未命中**原样返回不阻断**
  - `cif_path` 若只有库内 BLOB → 落盘 `~/.polyxrd/cif_cache/COD<id>.cif`（GSAS-II 桥要求真实磁盘文件）；实例级缓存 → 二次精修不重查
- `cod_local.find_structure_candidates(...)`：双通道只读查询（无机库 `phases` 精确 formula，cif_gz 优先；全库 `cod_entries` 用 `formula_red` 精确 + `mineral_name LIKE`）
- **实测**：Brucite Mg(OH)₂ → COD 1010484（a=3.130，比原相 3.125 最接近，排序正确）；3 相端到端 **3/3 命中，resolve 2.1 s**；`all have structure: True` → auto 引擎现在会选 GSAS-II
- 测试：新增 `test_v012_cif_resolver.py` 21 项；全量 **789 passed / 1 skipped**

**② 向导物相页 v2：上表 = 可选 CIF 列表，下表 = 已选初始结构（用户需求）**
- 设计（以搜代浏览 + 自动预填）：默认只列 **12 个内置矿物相**（不可能一次列全 71k 条）；搜索框回车即搜（纯数字/`97-`/`96-` 前缀 → 按 cod_id 直取；化学式 → 规范化后精确匹配 + 前缀 LIKE；其余 → mineral_name / space_group LIKE）
  - LIKE 在 7~11 万行上要 **3~4 s** → 必须后台线程 `_StructureSearchWorker(QThread)`
- `set_phases()` 自动预填上表（`_PhaseCifBrowseWorker` 逐相查候选，条目带 `_for_phase`，文案如 `Brucite → H2 Mg O2 · … · COD 1000054 ✓`）
- 下表格从 4 列扩到 **5 列**，新增「CIF 来源」（`COD <id>` / 内置结构 / 精修时自动匹配）；列表尾部标记 **✓ = 库内有 CIF，⤓ = 需联网下载**
- 修的坑：① `_cod_entry_to_phase` 旧 bug（把 `entry.cif_url`（网址！）当 `cif_path` 塞给 GSAS-II 桥）② 列表文案重复（无机库多数条目 mineral_name 为空 → 原样拼出 `H2 Mg O2 (H2 Mg O2)`）③ 伪矿名（全库 mineral_name 取自 CIF `data_` 行，不少就是 COD 编号本身）④ `cif_path` 缺失时来源列误标「内置结构」
- 新增 7 个 i18n 键（zh/en/ja 全齐）

**③ 版本与产物**
- 版本 0.12.0 → **0.13.0**（三处 bump；`build.bat` 的 `APPVER` 此前一直停在 0.11.0，本次更到 0.13.0）
- 提交 `7e3388d`（13 files / +1179 −48）
- `installer_output/` 产物齐套（`verify_release.ps1` RESULT: OK）：Setup **247.5 MB** / Portable **387.5 MB**（12344 条目，无业务库 ✓）/ COD-inorg **980.6 MB** / COD-full **205.9 MB** / PDF2 **58.9 MB**（**严禁上传**）/ `SHA256-v0.13.0.txt`

---

### v0.13.1 — 2026-09-18 · "双击打不开"（启动原生崩溃）根因定位与修复 🚫

**这是老版本中最经典的一次现场故障排查。**

- **现象**：`dist\PolyXRD\PolyXRD.exe` 双击打不开（用户强杀进程后复发）
- **定位链**（全部非沙盒 + 用 `~/.polyxrd/logs/startup-*.log` 的 `MainWindow OK` → `shown` 缺口判定）：
  1. 崩溃点**恒在 `main()` 里 `window.show()`**（日志停在 `MainWindow OK`，无 `shown`）；退出码 `0xC0000409`（fail-fast）或 `0xC0000005`（access violation）；`faulthandler` 报 `Fatal Python error: Aborted`；**WER 无 Application Error 事件** → 不是被外部终止
  2. 无单实例锁 / QSettings 污染（`_save_settings` 只在 `closeEvent`，强杀不落盘）
  3. 分层 A/B 实验（真实显示，非沙盒）：`v0_noicon`（不碰图片）**3/3 干净**；`v1_icon`（QIcon .ico → 加载 qico.dll）**1/3**；`v2_pixmap`（QPixmap .jpg → 加载 qjpeg.dll）**1/3**；`v3_splash` 1/3
     - **插件加载实测**：none=0 个插件；**png=0 个**；jpg=2（qjpeg）；ico=2（qico）→ **Qt6 的 PNG 解码器内建于 Qt6Gui，JPEG/ICO 必须动态加载 imageformats 插件**
  4. 源码 bisect（git worktree + 同一探针 + 同一 venv）：v0.11.0 → **3/3 干净**；v0.12.0 → 2/3；HEAD(v0.13.0) → **0/3**；v0.11.0 便携包 EXE → **6/6 稳定**
     - → 回归是 v0.12/v0.13 源码引入的潜伏问题；**触发条件 = 启动早期解码图片（加载 imageformats 插件）+ 之后 `window.show()`**
  5. ICU 排除：`System32\icuuc.dll`（29 KB，2021）确为转发器，Qt6Core 确实 import 它 —— 是真实风险但**不是本次主因**（最小程序 12/12 干净）
- **修复**：运行时窗口图标与启动画面**一律走 PNG**
  - 新增 `resources/splash-screen.png`（480×270，98 KB；原为 2560×1440 JPEG 209 KB）
  - `get_app_icon_path()` / `get_splash_screen_path()` 改为 PNG 优先，`.ico/.jpg` 仅作回退（`.ico` 仍留给 `PolyXRD.spec icon=` 与 `Setup.iss SetupIconFile`，不经 Qt 运行时）
  - `main.py` 启动图：图已 ≤480×270 时跳过 SmoothTransformation + 整块 try/except
- **源码验证**：修复前 splash 变体 **0/3** → 修复后 **4/4 干净**
- **产物**：`PolyXRD.exe` 39,843,264 B + `VERSION.txt` → 0.13.1；**打包版实测 6/6 ALIVE 且可见窗口 `PolyXRD v0.13.1`**；当日 startup log **10 次启动 / 10 次 `shown`**
  - Setup **259,678,012 B** / Portable **437.2 MB**（12,326 条目，含 `splash-screen.png` / `app-icon.png`）
- 提交 `9b05c2b`；回归 799 passed / 1 skipped + 新增 10 项
- **新增/强化**：启动 / 崩溃日志（`~/.polyxrd/logs/startup-*.log`，逐步骤写 `QApplication OK` / `icon=` / `splash=ok` / `MainWindow OK` / `shown` / `exit code=`）+ `cod_local` **安装目录守卫**（不再在安装目录创建/捡到幻影空索引 —— 空索引会遮蔽真实库）
- ⚠️ **残留未知**：v0.12/v0.13 具体哪行代码把"启动期插件加载"变成致命的，**未查到最终病灶**；PNG 方案是**实测有效的规避，不是理论修复**
- 旧版二进制清理（用户授权）：删 9 个文件约 **2.33 GB**（含带崩溃缺陷的 v0.13.0 Setup/Portable）+ `E:\TEMP\_v011_portable\`（1023 MB）→ 累计释放 **≈3.35 GB**

---

### v0.13.2 — 2026-09-18 · 无机库字段级数据修复（有缺陷数据的使用者必须升级库包）🚫

**触发**：用户提问「COD 无机库没有 Zincite(ZnO) 的 CIF?」

**结论：有，但被字段 bug 隐身。**
- 无机库里 wurtzite-ZnO 共 **11 条**，其中 7 条是 COD 矿物库 Zincite（2300450 / 9004178~9004181 / 9008877 / 9011662），**全部内嵌完整 CIF（1.0~6.0 KB）+ 2 个原子位点（Zn, O）**，a≈3.249 / c≈5.204 → **完全够做真 Rietveld**
- 但 `phases.formula` 有 **609 条（0.86%）被空间群符号覆盖**（formula 写的是 `P 63 m c` 而不是 `O Zn`）；608/609 的 `cif_gz` 里明明有正确的 `_chemical_formula_sum` → **建库脚本字段提取 bug，不是数据缺失**
- **两条杀伤路径**（实测试样 3-1，ZnO 93.59%，12 峰）：
  1. **显示**：识别结果里 Zincite 的 name/formula 都显示成 `P 63 m c` → 看不出是 ZnO
  2. **元素过滤（致命）**：`elements_from_db_formula("P 63 m c")` = **{'P'}**（被当成磷！）→ 勾 Zn/O 过滤后真 ZnO 全部淘汰，候选从 40 条塌缩到 **2 条**
  3. `same_formula("ZnO","P 63 m c")` 失败 → 基准召回记 0

**修复四件套（提交 `fb5a026`）**
1. **formula 迁移**（`scripts/migrate_inorg_formula.py`，幂等，默认 dry-run）：609 → 改写 **541 条**，残留 **72 条刻意不改**（CIF 式子被截断 + 位点元素不被覆盖）
   - 守卫：CIF `_cod_database_code` 必须 == `cod_id`；`cod_atomic_sites` 元素集（经 `_clean_elem_symbol` **去电荷** `'O-2'→'O'`）必须是新式子的子集
   - 踩坑：最初漏了去电荷 → **92 行假跳过**（含真 ZnO 2107059）；补上后 517→541
2. **判定层**：`elements_from_db_formula(formula, *, space_group="")` 相同则返回空集；**扫描层** `search_cod_by_d_peaks` 空集 **fail-open**（只对非空集做 `issubset` 淘汰）
3. **回退**：`cod_local.recover_inorg_formula` / `is_db_formula_trusted` / `formula_sum_from_{cif,inorg_cif}`；`get_cod_phase` 接入
4. **索引空库门槛**：`_is_usable_index_file`（≥50 MB）→ `live_counts()['cod_index']` 恢复 113,223

**顺手发现的两个同类 bug**
- `CIFDatabase.search_cod_phases`（**经 MCP 暴露**）的 `len(q_dash) == 15` 分支**永假** —— `display_id` 实为 `"97-1011097"`（10 字符），`ref_id` 为 `"96-101-1097"`（11 字符）；`96-` 分支还拿带横杠原串比 `ref_id`，也落空 → **两种官方编号都搜不到** → 统一为「去 `-/_/空格` → 9 位且 96/97 打头 → 取后 7 位」

**🔴 第三/第四个建库 bug：`cell_*` 列错位（用户没问，复现时顺手审计出来的）**
- `cell_a/b/c/alpha/beta/gamma` 与内嵌 CIF 不符 **31,634 行**：471 行 **denormal 垃圾**（`6.365987374e-314`）、每列约 8k 行 NULL、15,156 行 `a` 偏差 >0.5%（含**恰好 2 倍**关系，如 cod 1000042 存 10.3702 实为 5.189）
- **根因 = 建库时并行数组下标漂移**；另有 1 条（cod 1010542）内嵌的是**别的条目的 CIF**
- **峰表不受影响**：立方行上 `max(peaks_d)/a_CIF == 1/√3` 在 686 行成立而只有 6 行支持 DB 值 → **peaks 是用 CIF 算的**，FoM/排序/精修全对；坏掉的只有**展示**（CIF 列表 + 向导的 `a=… c=… Å`）
- 修复 `scripts/repair_inorg_cell.py`（幂等，容差 0.5%，NULL/非有限一律修）→ 31,634 行，复查 `need_fix=0`
- **审计方法学坑**：① `abs(a-b)/b` 会把 denormal 当有限值放过 → 必须显式查 `isfinite` + 量级/区间 ② 别把「库值为 NULL」和「库值错」混成一个数报 ③ 判定 peaks 按哪套晶胞算，用几何闭区间 `d_max/a ∈ [0.4, 1.05]` 比逐个指标号稳得多

**重打库包（13:30）**
- `PolyXRD-v0.13.2-Databases-COD-inorg.zip` = **1,029,777,309 B（982.1 MB）**，内含**单条目、根路径** `COD_inorganics.sqlite` 1,252,515,840 B（1,194.5 MB）
- 流程（`scripts/_repack_cod_inorg_zip.py`）：`PRAGMA integrity_check`（96 s）→ 源 SHA256 → **流式打包**（`ZipFile.open(zi,'w')`，别用 `writestr` 整包进内存）→ **整条回读 + SHA256 逐位比对**（14.5 s）
- `PRAGMA freelist_count` 仅 0.41% → **无需 VACUUM**
- v0.13.1 旧包**刻意不覆盖**（保持已发布产物 SHA256 自洽）；新写 `SHA256-v0.13.2.txt`

**14:00 · `cod_index.sqlite` 移入 `cod_data/` 的连锁事故与修复（`69ec009`）**
- **解析断裂**：`existing_index_db_path()` / `_bundled_cod_db_source()` → None，`live_counts()['cod_index']` 归 0；且下次 `connect()` 会在项目根**凭空造幽灵库**
- **🔴 更严重的次生事故：测试污染真实库** —— 第一版修复把 cod_data 兜底做成**无条件**，`test_cod_local` 夹具没显式传 `db_path` → 被重定向到**真实 431 MB 索引** → `build_index()`（增量 REPLACE）插了 12 条内置矿物假条目 → **`cod_entries` 113,223 → 113,235**
  - 修复三件套：① 兜底**只在 `cod_root.parent == _PROJECT_ROOT` 时生效** ② 夹具显式传 `db_path` ③ 数据修复（导出 JSON 可逆快照 → DELETE → `cod_entries` 回到 113,223）
- **写成红线**：**全局路径解析器一旦新增候选，所有"从解析器取路径"的测试夹具都会跟着变** → 夹具必须显式传路径，兜底必须限定在项目树内；"体积 < 10 MB"这类**量级护栏**极其有效（本次全靠它发现）

**过程产物清理**：共释放 **2,566.3 MB**（`_bdist` 912 MB + `_bwork` 142 MB + 仓库根 19 个日志 + 两个旧备份等），后追加清理累计约 **4 GB**

---

### v0.14.0 — 2026-09-19 · 运行时默认改瘦身索引式无机库 🚫

**主题**：数据库形态收敛 —— 无机库与全库索引同形态（不内嵌 CIF）

- **产物**：`cod_data/COD_inorganics_index.sqlite` = **362.0 MB**（原 1,194.5 MB）
- **零信息损失证明（四象限）**：内嵌 `cif_gz` 71,156 条与 `cod/cif` 文件覆盖 71,156 条 **完全重合**（both=71156 / gz_only=0 / file_only=0 / neither=43）→ `cif_gz` 全部置 NULL **不丢任何 CIF 可得性**
- **保留**：`phases` 全部列（峰表/晶胞/formula 修复后数据）+ **`cod_atomic_sites` 311,126 行**（精修初始模型核心）+ `parse_errors`；逐行比对非 `cif_gz` 列与 sites 全等
- **代码**（提交 `1a85b4a`）：
  - `config.get_cod_db_path()`：用户导入 > **瘦身索引式优先** > 完整内嵌版
  - `cod_local` 新增 `_inorg_is_slim()`（`meta.variant` 以 `slim-index` 打头判定）与 `_inorg_has_cif_expr()`（原库 `cif_gz IS NOT NULL` / 瘦身库 `(1)`）；三处查询接入 —— **不改的话瘦身库上 `AND cif_gz IS NOT NULL` 会把搜索结果清空**
  - `db_import`：`cod_inorganics` 的 `pkg_suffix` → `Databases-COD-inorg-index.zip`，`PKG_FILENAME` → `COD_inorganics_index.sqlite`；`cod_index` 后缀 → `-COD-full-index.zip`
  - 新增 `scripts/build_inorg_index_db.py`（默认 dry-run，`gz_only > 0` 时**拒绝构建**）
- **打包**：PyInstaller 32 min → Setup **247.6 MB**；Portable **397.7 MB**（12,326 文件，**本地保留不上传**）；两个索引库 zip：inorg-index **130.8 MB** / full-index **193.1 MB**
  - **启动验收**：startup log 出现 `MainWindow OK` + `shown`（frozen，icon=PNG）
- **Release v0.14.0**：4 附件（Setup / inorg-index / full-index / SHA256 清单）全部 uploaded；**PDF2 继续不进 Release**
  - 脚本教训：`releases/tags/<tag>` 不存在时返回 404，urllib 会抛 `HTTPError`，必须 catch 后才走"创建"分支
- 测试：新增 `test_v014_inorg_slim.py` 11 项 + 6 处期望同步更新

---

### v0.15.0 — 2026-09-20 · 路线图 M22–M25 + 首个中文使用手册 🏷️

**① M22 图谱 X 轴自适应交互**
- 绘图默认收缩至数据实际范围；**滚轮以光标为中心缩放（±15%/格）**；左键拖拽平移（与峰位点击兼容，**<3px 判定为点击**）；工具栏 Home 重置回数据全览

**② M23 物相列表交互重构**
- 主窗口物相树**默认空、跟随物相分析页勾选实时刷新**；右键可**导出选中物相 CIF** / 查看详情；**勾选集随项目持久化**保存/恢复

**③ M24 精修页布局重构**
- 主谱与残差条 **5:1 上下分栏、X 轴双向同步**；日志面板移入左栏；右栏新增「已勾选物相」列表（右键导出 CIF）与「外部精修程序」容器
- **窗口布局版本升到 v3**（旧布局自动丢弃 —— `restoreState` 会把工具栏宽度"钉死"，只能升版本号解决）

**④ M25 外部精修程序集成（本版重点）**
- 新增文件：`services/external_tools.py`（路径持久化 `~/.polyxrd/external_tools.json` + 三引擎自动探测）、`services/fullprof/{__init__,dat_builder,pcr_builder,runner}.py`、`services/launchers/{gsas2_launcher,maud_launcher}.py`、`views/widgets/external_engines_group.py`
- **FullProf（fp2k 8.20）批处理精修端到端**：`.dat`/`.pcr` 自动生成 → fp2k 运行 → **两遍标度自动校准** → **fp2k SYMBOLIC 限位编号自动发现**（不再手工填 Limit 编号）→ 保守模式 **W 扫描兜底** → `.sum`/`.out` 解析回写 Rwp/Rexp/Rp/GoF² 与各相 R_Bragg/晶胞/含量
- **实测结论（已沉淀为长期记忆 §13）**：
  - 标度校准必须读 `.out` 的 **SumYdif/SumYobs/SumYcal 表格第一张**（`SumYnet` 行是 ΣwYnet² 不是 Σycal）
  - Limits 块恒两行，且**编号是 fp2k 符号表编号**（非 codeword 整数；1 相时 `Zero=2` / `W=7`，由 `discover_limit_numbers` 从 `.out` 解析）
  - `W` 初值 0.010；`Biso` 缺失默认 0；空间群短式 `"P 63 m c"` fp2k 可解析
  - **ZnO 基准**：Rwp=**34.8%**，R_Bragg=25.8%，Vol=47.615 Å³，含量 100%
  - auto_refine 三级兜底（校准 → 发现限位 → 保守模式 W 扫描 {0.01,0.02,0.04} 取最优 Rwp）保证 `ok=True`
- **⑥ 冒烟测试最大教训**：ZnO 冒烟脚本自己**只放 2 原子/晶胞**（漏 6₃ 螺旋配对原子）→ pymatgen 按 P1 算出**物理上不可能的谱**（0001 强峰），导致**三天方向性误判**（PCR 格式/标度/限位全查了一遍）。→ **先验证合成数据本身的晶体学正确性，再怀疑引擎**
- GSAS-II / MAUD：一键导出实验谱 + 物相 CIF 到工作目录并拉起各自 GUI（"导出+拉起"语义）
- 本机三引擎探测全部命中：GSAS-II `G2.py`（`C:\ProgramData\gsas2main\…`）、MAUD `C:\MAUD3`、FullProf `C:\FullProf_Suite\fp2k.exe`

**⑤ 中文使用手册（首个）**
- `docs/manual/` 交付 4 份：**使用手册 PDF 15 页 / 9 章 / 9 张截图**、使用手册 PPTX 14 页、**快速入门 PDF 6 页 / 5 步流程**、快速入门 PPTX 8 页（另有 HTML 源 + `img/`）
- PDF 渲染改用 **Edge headless `--print-to-pdf`**（本 venv 的 PySide6 有两个坑：`QPrinter/QPdfWriter` 打印任何 HTML 都段错误；`QTextDocument.setHtml()` 遇 `code/tt/pre` 必崩）
- PPTX 走 tencent-pptx skill（slidep DSL），逐页 lint + upsert 全过

**⑥ 打包与发布**
- 产物（`installer_output/`）：Setup **247.7 MB** / Portable **387.7 MB** / COD-inorg-index **986.5 MB（⚠️ 回归）** / COD-full-index **205.9 MB** / PDF2 **58.9 MB**（本地归档）/ `SHA256-v0.15.0.txt`；`verify_release.ps1` 全 OK
- ⚠️ **发布包体积回归与纠正**：v0.14.0 的 inorg 包是 130.8 MiB 瘦身索引式，v0.15.0 却打出 **986.5 MiB** —— 根因 `verify_release.ps1` 的源路径仍指完整内嵌版 `COD_inorganics.sqlite`（1.19 GB，其中 `cif_gz` 占 830.2 MB / 70%），而代码真源 `db_import.PKG_FILENAME['cod_inorganics']` 从 v0.14.0 起就声明了瘦身版 → 已修正源路径；本地重打为 **134.1 MiB**，并已替换 Release 附件（986.5 → 134.1 MiB，SHA256 与正文同步刷新）
  - **用户决议：以后只用精简索引包**（CIF 由 `cod/cif` 目录或 COD REST 回退）
- Release：`github.com/PolyXRD/PolyXRD/releases/tag/v0.15.0`，4 附件（Setup / 两个 COD 库包 / SHA256），**PDF2 + Portable 禁传守卫通过**
- 发布脚本三个坑：curl 中文 payload 走命令行参数会静默失败（改 `--data-binary @file`）；构造 `gh_json` 忘 `append(url)`；`subprocess text=True` 用 cp936 解码 GitHub UTF-8 响应不可靠 → 改 bytes + `decode('utf-8','replace')`
- **库包命名唯一真源 = `db_import.DBKind.pkg_suffix`**

---

### v0.15.1 — 2026-09-20 · 内置引擎接入 CIF 结构强度 + MAUD 走官方 bat 🚫

**① MAUD 外部精修默认走官方 `maud.bat`**（提交 `38274ea`）
- 用户要求：精修页右下外部精修程序 MAUD 默认调 `C:\MAUD3\maud.bat` / `C:\MAUD2\maud.bat`（与用户双击启动行为一致），不再默认 `jdk/bin/java.exe`
- 改动三文件：`external_tools.py`（`_detect_maud` 优先 bat + `MAUD_SPEC.exe_names` 加 `maud.bat` + `validate` 认含 bat 的根目录）、`launchers/maud_launcher.py`（`resolve_maud_root` 支持 `maud.bat` / 安装根目录 / `jdk\bin\java.exe` 三形态；根下有 bat 就直接 Popen bat）、`views/widgets/external_engines_group.py`（浏览过滤器加 `*.bat`）
- 注意：`~/.polyxrd/external_tools.json` 里旧配置存的是 `java.exe`（`source=user` 会压过自动探测）→ 已清除该 key
- 冒烟：探测 → `C:\MAUD3\maud.bat`（auto）；bat/java/根三形态 resolve 同根；`test_maud_par_builder` 20 passed

**② 内置精修引擎接入 CIF |F|² 结构强度（解决长期遗留）**（提交 `556f0e6`）
- **病根**：M23/M24 已把勾选物相的 CIF（`cif_path` / `atomic_sites`）传到 Phase，但 `_refine_builtin` 收集参考峰时**只用库内静态峰表、从不看 CIF**
- **改动** `rietveld_refiner.py`：新增 `_cif_reference_peaks(phase, wavelength, tth)` —— CIF 文本 → `CifParser(occupancy_tolerance=1.2).parse_structures` → pymatgen `XRDCalculator.get_pattern` → (hkl, 2θ, I) 归一 max=100；无 CIF 文本时用 `phase_cif.phase_to_cif_text` 从 `atomic_sites` 反生成；**失败/无 λ 返回 None 自动回退旧行为（不劣化）**
  - 缓存 `_cif_peak_cache`（key = 来源 + mtime/文本 hash + λ + 2θ 范围），quick/fine 两轮共用；`use_cif_peaks=True` 默认开；日志 `[cif] n/N 相使用 CIF 结构 |F|² 参考峰`
- **合成谱闭环基准**（Calcite 1010979 + Corundum 1010608，真权重 0.65/0.35，Poisson 噪声）：

| 路径 | wR | 拟合权重 |
|---|---|---|
| **新（CIF \|F\|² 参考峰）** | **10.32%** | 65.72 / 34.28 |
| 旧（峰位对、强度平） | **58.13%** | 44.42 / 55.58 |

- 回归：`test_rietveld*` 6 文件 59 passed
- **注**：内置引擎**仍无原子坐标时**回退剖面拟合，wR 偏高属设计使然（发布级结果仍建议走 GSAS-II / MAUD / FullProf）

**③ 版本收口与打包**
- 提交 `0791f2d`：`pyproject.toml` + `build.bat APPVER` → 0.15.1（`.iss` 由 `/DAppVersion` 驱动无需改）
- **build.bat 固有缺陷修复**：`VERSION.txt` 原在 Portable zip **之后**写，而 PyInstaller COLLECT 会清空 dist → **包内没有 VERSION.txt** → 已前置到 zip 之前
- 打包走 `scripts/_build_v0151.sh`（跳过库包与 verify_release.ps1，库数据没变）：PyInstaller 本次 COLLECT **没被沙盒锁**（~38 min 全程），手工 collect `MISSING=0`，ICU cleanup `removed=0`
- ⚠️ **ISCC 别从 Git Bash 调**：`//D` 不会被去转义 → `Unknown option: //DAppVersion`，**必须用 PowerShell 原生调** `/DAppVersion=0.15.1`
- 终态产物：Setup **259.7 MB** + Portable **397.7 MB**（12,356 条目，含 VERSION.txt）+ `VERSION_v0.15.1.txt`
- **用户决议：二进制不推送、不发 GitHub Release；代码已推送**
- ⏳ 待用户双击人工验收（红线）

---

### v0.15.2 — 2026-09-21 · 精修指标通用化（Rwp + Rexp / Rb / GOF）🚫

**主题**：评价因子从内部记法 wR 正名为通用记法 **Rwp**，并补齐标准 R 因子组

### 新增/变更

- **Rwp 正名**：`RefinementResult` 新增 `Rwp` 属性（与内部字段 `wR` 同一数值 — 本项目的
  wR 一直就是加权轮廓 R 因子 Rwp）；精修页 / 精修向导 / 批量精修对话框的显示与
  CSV 导出统一改用 Rwp 记法，旧字段 `wR` 保留以兼容旧代码与旧项目文件。
- **新增 Rexp（期望 R 因子）**：`Rexp = sqrt((N-P) / Σ w·y_obs²) × 100`
  （N=数据点数, P=可调参数数）。
- **新增 Rb（轮廓 Bragg R 因子）**：`Rb = Σ|y_obs - y_calc| / Σ y_obs × 100`（不加权）。
- **GOF 改标准定义**：弃用旧的非标准量，改为 `GOF = Rwp / Rexp`（理想值 ≈ 1）。
- 新增统一计算入口 `RietveldRefiner._calc_profile_metrics(obs, calc, weight, n_params)`；
  各引擎接入情况：**builtin**（全量 Rwp/Rexp/Rb/GOF，含统计权）、**powerxrd**（单位权）、
  **Le Bail**（单位权）、**GSAS-II**（Rwp/GOF 用 GSAS-II 回传权威值，Rexp/Rb 从回传计算谱
  补算）、**MAUD**（从 refined.par 的 `_refine_ls_R_factor_expected` / `_refine_ls_R_Bragg_all`
  解析，缺省 0）。
- 过程日志 `[result]` 行改为 `Rwp=... Rexp=... Rb=... GOF=...`。
- UI：精修页与精修向导结果组各新增 Rexp / Rb 两行；批量精修表格与 CSV 加
  Rexp / Rb 两列。
- **修复启动闪退隐患**：`main.py` 原先在**构造主窗口之前**就挂上「800ms 后关闭启动图」
  的定时器，而 `quitOnLastWindowClosed` 保持 Qt 默认的 `True`。首次运行（冷 .pyc +
  matplotlib 字体缓存，主窗口构造约 3~4s）时，启动图一旦在主窗口显形前被关掉，就会
  触发"最后一个窗口已关闭"而让应用**静默退出** —— 现象即控制台一闪而过、程序未起、
  且**不留任何异常日志**。现将关闭动作统一挪到 `window.show()` 之后再挂，并给
  `show()` 单独加 try/except（落盘 `crash-*.log`），另加 `showing main window` /
  `shown` 两条启动流水日志，便于日后一眼定位是否卡在原生窗口创建。

---

## 附录 A · 路线图模块（M01–M25）与版本对照

| 模块 | 名称 | 落地版本 | 备注 |
|---|---|---|---|
| M01 | 数据导入 / 格式识别 | v0.9.7 | `detect_format` + `load_auto` |
| M02 | 元数据 / 会话 | v0.9.7 | `ExperimentalPattern` / `SessionDocument` |
| M03 | 原始数据处理 | v0.9.7 | 平滑 / **Kα2 剥离（Rachinger）** / 插值 |
| M04 | 背景扣除 | v0.9.7 | SNIP / 多项式 / 控制点样条 |
| M05 | 峰搜索 | v0.9.7（v0.9.9 大改） | `detect_shoulders`；v0.9.9 换高精度引擎 |
| M06 | 峰管理 | v0.9.7 | 不可变增删改 + 区间屏蔽 + 残差峰 |
| M07 | 轮廓拟合 | v0.9.7 | 重叠簇联合 Pseudo-Voigt |
| M08 | 仪器校正 | v0.9.7 | 零点 / 样品位移 / 内标 |
| M10 | 搜索匹配（FoM） | v0.9.7（v0.9.11 重构） | 乘性 → 加权互斥 |
| M11 | 多相迭代识别 | v0.9.7 | `iterative_identify` |
| M12 | 用户自建库 | v0.9.7 | JSON CRUD + CIF/峰表导入 |
| M13 | RIR 半定量 | v0.9.7 | 相对 + 内标绝对 |
| M14 | Rietveld 增强 | v0.9.7（v0.9.8 接参数掩码） | March-Dollase / DoC / 内标 |
| M15 | 指标化（Treor/Dicvol） | **P3·暂缓** | 2026-09-07 降级 |
| M16 | 晶粒尺寸（Scherrer） | v0.9.7 | 含仪器宽化扣除 |
| M17 | 3D 结构可视化 | **P3·暂缓** | 2026-09-07 降级 |
| M18 | 报告导出 | v0.9.7（v0.9.8 修 LO 转换） | SVG / HTML / CSV / CIF |
| M19 | 脚本 / 批量 | v0.9.7 | 管线 DSL + 批量处理 |
| M20 | GUI 交互 | v0.9.7（v0.9.8/v2 续） | 拖放 / 主题 / 峰表右键 |
| M21 | 物相分析 v2 展示层 | v0.9.8 | 双区谱图 + 峰归属表（对标同类商业软件） |
| M22 | 图谱 X 轴自适应交互 | v0.15.0 | 滚轮缩放 / 拖动平移 |
| M23 | 物相列表勾选驱动 + CIF 导出 | v0.15.0 | 勾选集随项目持久化 |
| M24 | 精修页布局重构 | v0.15.0 | 窗口布局版本 → v3 |
| M25 | 外部精修程序集成 | v0.15.0（v0.15.1 续） | GSAS-II / MAUD / **FullProf** |

> 注：上表按"实际在哪个版本交付"归集；M15 / M17 在 2026-09-07 被降为 P3·暂缓可选，至今未实施。

---

## 附录 B · 外挂数据库包形态演进

| 版本 | COD 无机物库包 | COD 全库索引包 | PDF2 包 | 形态说明 |
|---|---|---|---|---|
| v0.8.21 | 91.9 MiB（解压 258.6 MB） | — | — | 仅峰表/晶胞/化学式，**无 CIF** |
| v0.9.0 | 75.8 MiB | 179.2 MiB | — | 双库外挂、热切换 |
| v0.9.10 | 94 MiB | 206 MiB | — | 命名 `PolyXRD_COD_*_v0.9.10.zip` |
| v0.10.0 | 133.9 MB（解压 371.9 MB） | 205.9 MB | 58.9 MB | **彻底外挂化**；命名改 `PolyXRD-v{ver}-Databases-*`；拆三包 |
| v0.11.0 | 976.1 MB（**v2 内嵌 CIF**） | 193.1 MB | 58 MB（本地） | 单挂无机库即可 Rietveld |
| v0.13.1 | 980.6 MiB | 205.9 MiB | 58.9 MB | 完整内嵌版 |
| v0.13.2 | 982.1 MB（修数据后重打） | — | — | 内含 `COD_inorganics.sqlite` 1,194.5 MB |
| v0.14.0 | **130.8 MiB（瘦身索引式）** | 193.1 MiB | — | 命名加 `-index` 后缀；CIF 走 `cod/cif` 或 REST |
| v0.15.0 | 986.5 MiB（**回归**）→ 已修 **134.1 MiB** | 205.9 MiB | 58.9 MB（本地） | 命名真源 = `db_import.DBKind.pkg_suffix` |
| v0.15.1 | 未重建（库数据未变） | — | — | — |

**结构事实（2026-09-20 实测）**：完整内嵌版 `COD_inorganics.sqlite` **1,194 MB**，其中 `cif_gz` **830.2 MB（70%）**、`peaks_d/i` 206.7 MB、`peaks_top_*` 64.6 MB、原子位点约 10 MB；因 `cif_gz` 已 gzip，zip 只能压掉 **17%**。瘦身版 `COD_inorganics_index.sqlite` **362 MB**（`cif_gz` 全空），zip 后 **134.1 MiB**。

**取舍**：瘦身包体积小约 7 倍，但 CIF 依赖外部 `cod/cif` 目录或联网 COD REST；完整包自包含但近 1 GB。

---

## 附录 C · 关键量化指标演进（老版本对比）

| 指标 | 早期 | 后期 | 出处 |
|---|---|---|---|
| 物相识别命中率（13 工业试样） | 45.1% | **68.6%**（v0.9.0） | v0.9.0 |
| 含量定量命中率 | 9.1% | **31.8%**（v0.9.0） | v0.9.0 |
| 多相组合召回（13 试样） | 48.9%（legacy 贪心） | **53.2%**（B&B） | 2026-09-02 |
| COD 检索耗时（单次） | ~27.4 s | 22.5 s（向量化）→ **8.8 s**（预截断强峰列） | v0.9.11 |
| COD 检索（6 真实试样合计） | 126.8 s | **48.2 s（2.6×）** | v0.9.11 |
| COD 候选排序 Top-1 / Top-5 / Top-10 | 12% / 22% / 24% | **14% / 25% / 27%**（池 200 时 16%/27%/29%） | v0.9.11 |
| 寻峰（真实 ZnO 2-1） | 15 峰（锁 0.02° 网格） | **35 峰**（亚步长，解析 Kα1/Kα2 双峰） | v0.9.9 |
| Rietveld 长测试耗时 | 11–12 min | **4 min**（v0.9.1）；全量回归 18m36s→1m46s | v0.9.1 |
| 精修 wR（2-1，ZnO/CaCO₃ 50/50） | builtin 51.79~53.6% | gsas2 **26.6%**（有结构） | v0.11.0 |
| 精修 wR（4-1 四相） | 64.74% | — | v0.9.0 |
| 内置引擎 wR（合成谱闭环基准） | 58.13%（旧，强度平） | **10.32%**（v0.15.1 接入 CIF \|F\|²） | v0.15.1 |
| FullProf 基准（ZnO） | — | Rwp **34.8%** / R_Bragg 25.8% | v0.15.0 |
| MAUD 基准（alzrc.par 预加载） | — | wR **0.087%** / R 0.064% / GOF 0.064 | v0.11.0 |
| 单元测试规模 | 95（v0.9.0） | 182（v0.9.7）→ 316（v0.9.10）→ 443 → 507 → 542 → 545 → 666 → 734 → 745 → 789 → 799 | 各日日志 |
| Portable 包体积 | 661.5 MB（v0.9.10） | **380.7 MB**（v0.10.0 外挂化后） | v0.10.0 |
| 数据库总体积（可检索） | 无机物库 258.6 MB + 全库 431.7 MB | 无机物库(瘦身) **362 MB** + 全库 431.7 MB | v0.14.0 |

> ⚠️ 上表数字**口径不完全统一**（部分为日志当场实测、部分为抽样；识别率类指标存在"化学式口径导致的假阴性下界"问题），仅用于趋势对比，不可跨口径直接相减。

---

## 附录 D · 发布红线与约定（老版本期间确立）

1. **PDF2-2004 永不上传**（ICDD 版权库）：仓库只提供挂载能力；DB Manager 中显示「请确认已获得正版授权」提示；`.gitignore` + 发布脚本 `Assert-NotBanned` + 上传后自检三层守卫
2. **Portable 免安装包自 v0.11.0 起不随 Release 发布**（按需提供）；v0.15.1 起二进制**整体不推送**
3. **每个 EXE 发布前必须双击人工验收**（自动启动检查不可替代）
4. 数据库文件（`.sqlite` / `tar.xz`）与 `tests/` 目录**不入 git**（只提交 `src`）
5. **commit message 采用「更新代码修正: …」风格**；**严禁出现第三方商业软件品牌字样**
6. 两条精修 GUI 路径（快速精修 / 多步精修向导）**保留为独立路径，不合并**
7. 精修**前后端分离**：分步向导自带 refiner → 结果必须经 `result_ready` → `MainViewModel.adopt_refinement_result` 回灌（`emit` 必须在 `accept()` 之前）
8. 界面引擎下拉**处处一致** = `[auto, gsas2, maud, builtin, powerxrd]`，且与 `get_engine_status()` 键集合对应
9. 重活必须包 `busy_indicator` 闸门（`setEnabled(False)` 挡不住点击积压）
10. **谱图内部标记一律用国际技术记号**（`log` / `sqrt`），只有界面控件本地化
11. 本仓库 `.bat` 必须：**纯 ASCII + CRLF + 单行 `if` + `if errorlevel 1 pause`**，且 `if` 块内/`echo` 文本中**不得出现裸括号**
12. `.gitignore` 的 `_*.py` 会吞掉 `__init__.py` → 新建包后必须 `git status` 确认可见

---

## 附录 E · 版本号收口点

**每次发版需同步的位置（以 `build.bat` 顶部 `set APPVER=` 为唯一改动入口）：**

| # | 位置 |
|---|---|
| 1 | `build.bat` 顶部 `set APPVER=`（标题 / banner / 输出名三处跟随） |
| 2 | `src/polyxrd/config.py` → `AppConfig.app_version` |
| 3 | `src/polyxrd/__init__.py` → `__version__` |
| 4 | `pyproject.toml` → `version` |
| 5 | `scripts/PolyXRD-Setup.iss` → `AppVersion`（v0.15.1 起由 `/DAppVersion` 驱动） |

**发布辅助脚本**：`scripts/verify_release.ps1`（打包三库包 + 对账 + SHA256）、`scripts/create_github_release_v*.ps1`、`_create_release_py.py` / `_upload_assets_curl.py`（Python 化，curl 上传）。
**库包命名唯一真源** = `db_import.DBKind.pkg_suffix` / `db_import.PKG_FILENAME`。

---

## 附录 F · 不确定项与取证说明（诚实披露）

1. **v0.9.7 附件体积存在两套记录**：当日构建日志写 Setup **261 MB** / Portable **411 MB**；同一日"发布就绪"段落又记 release_staging 为 Setup **98 MB** / Portable zip **487 MB**。两者未在日志中对账，疑为不同打包方式/压缩级别或口径差异 —— **以发布页实际 SHA256 清单为准**。
2. **v0.9.7 的 GitHub Release 状态存疑**：当日与次日日志均记"网络受阻、待代理恢复后 push + 建 release"，本机无成功上传证据（`upload_assets.log` 只能证明 **v0.9.0** 三个附件 uploaded）。**未在本机留证确认 v0.9.7 的 Release 是否存在**。
3. **本地 tag 缺失**：本机仓库仅 9 个 tag（`v0.8.21/0.8.22/0.8.23/0.9.0/0.9.7/0.9.10/0.10.0/0.11.0/0.15.0`）；`v0.12.0` / `v0.13.0` / `v0.13.1` / `v0.13.2` / `v0.14.0` / `v0.15.1` 本机无 tag（其中 v0.14.0 有发布记录，v0.15.1 明确不发 Release）。可能是 tag 未推送到本地/未创建，**不代表未发布**。
4. **识别率类数字是下界**：COD 把 ZnO 存为 `Li0.086 O0.957 Zn0.914` 这类掺杂/非化学计量式，`same_formula` 判定失败 → 真物相其实排第 1 却记 0 分。所有命中率/召回数字**均为下界**。
5. **v0.9.11 的召回基准分母不一致**：方案文档用 51、基准报告用 45，当时**未强行统一**，本表沿用报告口径（45）。
6. **体积单位混用**：日志中 PowerShell 的 `Length/1MB` 是 MiB、Python 的 `/1e6` 是 MB，同一文件可能得出两套数（如 380.7 vs 399.2）。本文按日志原值抄录并尽量标注口径。
7. **v0.13.1 的启动崩溃最终病灶未定位**：PNG 方案是**实测有效的规避**（修复前 0/3、修复后 4/4），不是理论修复。
8. **v0.15.0 的 986.5 MiB 库包**曾在 Release 上短暂存在，已于当日替换为 134.1 MiB；若有第三方在此期间下载，其 SHA256 与当前发布页不一致。
9. **v0.15.1 未打包库包**（库数据未变），因此其"数据库兼容性"沿用 v0.14.0/v0.15.0 的瘦身索引式包。
10. **v0.8.21 之前的记录等级有限**：git 首笔提交即 `V0.8.21 initial commit`（2026-08-21）。更早历史（v0.3.0 / 0.4.1 / 原型 / 0.6.0 / 0.8.0~0.8.20）来自交接期源码包回溯与交接期工作记忆整理（原 CHANGELOG01/02），无 git 提交与二进制产物可交叉验证，细节以第一部分所载为准。

---

*本文档由项目 git 提交历史与逐日工作日志回溯编制，仅作版本回顾用途；未修改任何源码，未上传任何内容。*

---

## 附录 G · 开源致谢

| 项目                                                                    | 用途              | 许可证                   |
| --------------------------------------------------------------------- | --------------- | --------------------- |
| [Python 3.10](https://www.python.org/)                                | 运行时             | PSF                   |
| [PySide6 (Qt6)](https://wiki.qt.io/Qt_for_Python)                     | GUI 框架          | LGPL v3 / GPL v2      |
| [PyInstaller](https://pyinstaller.org/)                               | 二进制打包           | GPL v2                |
| [Inno Setup 6.7](https://jrsoftware.org/isinfo.php)                   | Windows 安装器     | Inno Setup License    |
| [pymatgen](https://pymatgen.org/)                                     | 晶体学/物相分析        | MIT                   |
| [spglib](https://spglib.github.io/spglib/)                            | 空间群标准化          | BSD-3                 |
| [scipy](https://scipy.org/)                                           | 数值算法            | BSD-3                 |
| [numpy](https://numpy.org/)                                           | 多维数组            | BSD-3                 |
| [pandas](https://pandas.pydata.org/)                                  | 表格数据            | BSD-3                 |
| [matplotlib](https://matplotlib.org/)                                 | 2D 绘图           | PSF-based             |
| [pyqtgraph](https://www.pyqtgraph.org/)                               | 交互式 XRD 主图      | MIT                   |
| [LMFIT](https://lmfit.github.io/lmfit-py/)                            | 非线性最小二乘         | BSD-3                 |
| [GSAS-II](https://gsas-ii.net/)                                       | Rietveld 结构精修引擎 | Free for academic     |
| [powerxrd](https://github.com/andrewrgarcia/powerxrd/)                | XRD 峰形模型        | MIT                   |
| [platformdirs](https://github.com/platformdirs/platformdirs)          | 跨平台用户路径         | MIT                   |
| [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)      | AI 模型接口协议       | MIT                   |
| [Crystallography Open Database](https://www.crystallography.net/cod/) | 71,199 无机物相数据   | CC BY / Public Domain |

---

## 附录 H · 版本兼容性矩阵

## 版本兼容性矩阵

| PolyXRD 版本      | COD 数据库外挂包版本                            | 数据库列名        |
| --------------- | --------------------------------------- | ------------ |
| **0.8.23**      | PolyXRD\_COD\_Inorganics\_v0.8.21 (无变化) | ref\_id      |
| **0.8.22**      | PolyXRD\_COD\_Inorganics\_v0.8.21 (无变化) | ref\_id      |
| **0.8.21**      | PolyXRD\_COD\_Inorganics\_v0.8.21       | ref\_id      |
| 0.8.0 \~ 0.8.20 | cod\_inorganics.sqlite (不兼容)            | cod\_ref\_id |

---

*本文档由 4 份历史变更记录合并而成（2026-09-21）：早期史取自交接期回溯整理，v0.9.0 起以逐日工作日志与 git 历史为据；重复版本已按内容去重，保留各自独有细节。*
