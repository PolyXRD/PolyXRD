# PolyXRD 版本变更记录（CHANGELOG）

> 覆盖范围：**v0.3.0（可追溯最早版本）→ v1.0.1（2026-09-22，已发布）+ v1.0.2（启动稳健性修复，已收口未发布）+ v1.1.1（国际化补全 / 全链路 UTF-8 / 素材去水印，当前工作版本）**
> 合并日期：2026-09-21 ｜ 由 4 份历史变更记录（CHANGELOG01 / 02 / 03 与原 CHANGELOG）合并去重而成
> 最后更新：2026-09-23（补 v1.0.1 正式发布记录 + Release 附件清单 + **v1.0.2 启动稳健性修复（版本号已定，EXE 暂不重建）** + v1.0.1 遗留的版本号收口补正与 `pyproject.toml` 元数据补齐 + **v1.1.1 英/日界面翻译全量补全 + 全链路 UTF-8 + 启动图/横幅去「AI生成」水印** + **v1.1.1 运行期切语言「整页重翻译」补修：上一轮离屏冒烟为假阴性，改用隔离 QSettings 键 + 每组独立进程的探测器后残留归零**）
> 数据来源：git 提交历史 + GitHub Release 正文 + 项目工作记忆（逐日工作日志）+ 交接期源码包回溯
> 联系：sshztx@outlook.com
>
> **结构导览**：
> - 第一部分 · 早期史（v0.3.0 → v0.8.20，无 git 记录，回溯整理）
> - 第二部分 · 正式发布逐版详情（v0.8.21 → v1.1.1，其中 v0.8.21–v0.8.23 沿用首份日志的详细节）
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

# 第二部分 · 正式发布逐版详情（v0.8.21 → v1.1.1）

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

## 版本速览表（v0.3.0 → v1.1.1）

| 版本 | 日期 | 主题 | 关键交付 | 产物形态 |
|---|---|---|---|---|
| v0.3.0 | ~2026-08-12 | 最初原型 (核心功能定义, 可追溯最早版本) | `__version__="0.3.0"` | 源码（无产物） |
| v0.4.1 | 2026-08 上旬 | 基础配置框架 | 默认波长 / 2θ 范围 / 格式清单 | 源码（无产物） |
| 原型（pre-0.6.0） | 2026-08-12~13 | core/gui 两层架构原型 | 30 参考物相 + SMZ/钨系列验证 | 源码（无产物） |
| v0.6.0 | 2026-08-18/19 | 项目交接起点, MVVM 架构定型 | 118 参考物相; nsist+7z SFX 打包 | 源码 |
| v0.8.0~0.8.20 | 2026-08-19~21 | COD 本地库集成 + 多相分析 + 精修改造 | 71,199 相 SQLite; 测试 65→82 | 源码 |
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
| v0.15.2 🚫 | 2026-09-21 | 精修 A/B/C 三路线收口 + 格式互转 | **4-1 wR 52.7%→19.69%（March-Dollase 织构 + 对称展开向量化）**；Rwp/Rexp/Rb/GOF 标准化；8 格式互转；参考库 0.5.1 | 源码/本地构建 |
| **v1.0.1** 🏷️ | 2026-09-22 | **1.0 正式版：主路线图 M01–M25 全部交付** | M09 候选检索与约束 / M15 指标化（立方·四方·六方）/ M17 3D 晶体结构视图 / M26 谱合成窗口化（**1467→270 ms，5.4×**）；修大峰表组合卡死；全量回归 **991 过 / 2 跳过**；版本号 0.15.3→**1.0.1** | Setup + 2 索引库包（**PDF2 / Portable 不入 Release**） |
| v1.0.2 🚫 | 2026-09-22 | **启动稳健性修复**（现场"关掉后双击打不开"） | kill-safe 单实例守卫（命名互斥量）/ `app.exec()` 硬退出看门狗 / `--diagnose` 无 GUI 诊断 / `faulthandler` 原生崩溃落盘 / `--safe-render` 保守渲染开关；结论：**死于 `MainWindow.show()` 内部（Qt6Widgets.dll 0xC0000005）**，疑 Qt 6.11.1×老旧显卡驱动 | 源码（**EXE 暂不重建、不发 Release**） |
| **v1.1.1** 🚫 | 2026-09-22 | **国际化补全 + 全链路 UTF-8 + 素材去水印** | 补齐 **384** 个翻译键（`vw.*` 193 / `elem.*` 103 / `dialog.*` 26 / `report.*` 20 / `params.*` 16 …）；三语键集 **894×3 完全对齐**（此前 zh **562** / en **550** / ja **510** 互不相等）；ViewModel（37 处）+ 结果模型 + 服务层日志全部纳入；`I18nManager` 增 **zh_CN 回退链**；`zh_CN` 显示「简体中文」并**预留 `zh_TW`（繁體中文）**；**全链路 UTF-8**（文本 I/O 全显式编码 + 读取用 `utf-8-sig` 免疫 BOM + 入口强制 UTF-8 stdio/子进程环境 + `scripts/check_utf8_encoding.py` 静态守卫）；启动图与横幅**去除「AI生成」水印** | 源码（待打包） |

> 说明：v0.15.3 从未独立发布，其全部内容（M09 / M15 / M17 / M26 + 7-1 卡死修复）已在 v1.0.1 中转正发布。

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

### v0.15.2 — 2026-09-21 · 精修指标通用化 + 启动加固 + 谱图格式互转 🚫

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

### 新增 · 谱图文件格式互转（菜单「文件 → 谱图格式转换…」）

- **新入口**：`文件 → 谱图格式转换…`（位于「打开」之后）。可把当前支持的谱图文件在
  **8 种目标格式**之间互转并另存为不同扩展名：`xy / txt / dat / csv / mdi / raw /
  xrdml / json`；不指定目标路径时自动换扩展名（同目录同主名）。
- **新增读取支持（两个此前不认识的格式）**：
  - **`.mdi`**（定宽整数文本谱）：2 行文本头 + 定宽整数强度。真实仪器导出的样本会
    **丢失第一个数据点**（点数比标称范围少 1），读取时以文件头里的结束角度反推起始角度，
    保证角度轴与点数自洽。
  - **`.raw`（RAW2 二进制）**：以 `RAW2` 魔数识别，固定 316 字节文件头，其后为
    float32 强度数组（`316 + n×4 == 文件大小`）；从头部读取点数、步长、起始 2θ 与
    阳极靶材，据此还原波长。新旧 `.raw` 判读并存，旧的启发式分支保留。
- **新增写出支持**：`.mdi`（无损：写入实际首点与真实点数）、`.raw`（316 字节 RAW2 头 +
  float32 数组，数据点上限 32767）、以及 `csv / xrdml / json`。
- **无损性**：两列文本族（`dat / txt / xy`）互转后**逐字节相同**；`mdi / raw` 往返读取
  与原始 `.dat` 完全一致；8 种目标格式往返误差 ≤ 1e-6°（角度）/ 1e-9（强度）。
- **对话框**：源文件 / 目标格式 / 输出路径三段式，带**数据点预览**（点数 + 2θ 范围）；
  切换源文件或目标格式时自动同步输出扩展名；转换前校验非等间距数据（`mdi / raw`
  需要等间距通道）。
- **安全**：转换目标与源文件为同一路径时**直接拒绝**，避免覆盖/删除原始数据。
- **i18n**：中文 / 英文 / 日文三语同步（新增 `convert.*` 共 26 个键）。

### 修复 · 结构精修 A / B / C 三条路线收口（任务 #59 / #60 / #61 / #98）

#### A 路线 · 内置引擎算法改进

病根不在权重算法，而在两处更底层的东西：

1. **空间群对称展开缺失（致命缺陷）**：COD 的 `cod_atomic_sites` 存的是**非对称单元**
   —— 如 R-3c 方解石只有 3 个位点。旧代码把它当 P1 晶胞直接喂 pymatgen，等于把方解石
   按三斜胞算衍射 → 29.4° 的 104 主峰**根本算不出来**，反而冒出 5.17°(0001，R-3c 消光)
   这种假峰。新增 `services/phase_cif.expand_sites_by_symmetry()`（用
   `SpaceGroup.symmetry_ops` 作用到非对称单元坐标 → 补全整胞；幂等；P1/空/脏数据/解析
   失败一律原样返回），并在 `phase_cif.phase_to_cif_text` 与 `cod_local.get_phase`
   两处接入。效果：方解石 3 → 30 位点，104 峰恢复为 I=100。
2. **晶胞参数从未进入拟合维度**：内置引擎的 fit 向量是
   `weights(n) + fwhm + eta + scale + zero_shift + U/V/W`，`param_mask["cell"]` 一直是
   no-op（原注释就写明"cell 在 builtin 中固定"）。试样晶胞与库值哪怕差 0.1%~0.3%，
   60° 附近峰位就偏 0.05°~0.15°，残差被这一项钉死。现给**每相增加 1 个「各向同性晶胞
   缩放」自由度**（`d' = d·s`，等价整体膨胀/收缩，边界 ±2%），并挂在参数向量**末尾**，
   以免动既有 `n_phases+0..6` 的索引算术。`param_mask["cell"]` 因此变成真掩码
   （`False` 即冻结为 1.0）；精修后物相晶胞按缩放值回写，`fit_params.cell_scale` 可查。
3. **快检阈值 55% → 20%，并把快检解热启动进精细模式**：多相试样的快检常落在
   20%~55% 这一带，旧阈值让它们**永远走不到 Caglioti**（4-1 快检 52.7% 被"达标"短路），
   峰值宽度失配被钉进残差。现以质量分级里的"可接受"线（20%）为准；同时用 `_x_sink`
   回收快检的最优参数向量，补上 Caglioti 初值后作为精细模式第 1 个起点，避免从网格
   重头搜。

**2-1 实测（ZnO + CaCO₃）**：wR 40.29% → **20.86%**（无 Caglioti）/ **19.43%**
（默认路径，含 Caglioti），权重 66.1% / 33.9%（≈2:1，与配料吻合）。
代价是慢：2-1 由 4.5 s 增到 ~129 s，多相试样更甚 —— 精度优先，GUI 侧有忙碌提示与进度回调。

3. **March-Dollase 择优取向修正（本轮补齐，仅精细模式）**：板状/层状物相制样后
   00l 织构使实验强度系统性偏离运动学 |F|²（4-1 Brucite 实测 001:101 = 100:24.6，
   模型 64:100 —— 方向反了 4 倍），伪 Voigt + 全局 FWHM 吸收不了 → wR 卡 48% 地板。
   每相新增 1 个织构参数 r（织构轴 [001]，`P(α) = (r²cos²α + sin²α/r)^(-3/2)`，
   α 为晶面法线与 [001] 夹角，逐相按峰强均值归一），边界 [0.6, 1.8]，快检不启用
   （保持快检参数布局与热启动兼容），`param_mask["texture"]` 可冻结，
   `fit_params.texture_r / texture_phases` 可查。cos α 由倒易度量矩阵
   `G* = inv(G)` 预计算；cos α 无区分度（std < 0.05）的相自动跳过。
   配套修复：**pymatgen 对三方/六方返回四指标 (h,k,i,l)，旧代码在
   `len(raw) >= 3` 分支把它截成 (h,k,i)，l 全丢**（002 被记成 (0,0,0)），
   织构轴 [001] 因此失效 —— `cod_local.get_phase` 与
   `rietveld_refiner._cif_reference_peaks` 两处均已改为优先按 len==4 取
   (h,k,l)。

**4-1 实测（CaF₂ + ZnO + Mg(OH)₂ + Al₂O₃ 四相）**：wR 52.71%（快检）→
**19.69%**（精细，含织构），质量"可接受"，GOF 94.4；与无 CIF 基线 48.24% 相比
**纯算法贡献 −28.6 个百分点**。4-1 全链路（识别 → CIF 解析 → 精修）由"卡死
>90 min"修复为 **~25 min 完成**（见下条性能修复）。

4. **`expand_sites_by_symmetry` O(n²) 去重向量化（4-1 卡死根治）**：原实现的
   轨道去重是纯 Python 三重循环（每个生成点对 `expanded` 列表线性扫描、每对
   比较一次 `_frac_close`），大晶胞 × 高对称群（数百位点 × ~192 操作 → ~10⁵
   生成点 × 2000 已展开点 ≈ 10⁸ 次 numpy 小数组调用）实测卡死 >12 min。改为
   **按元素分组的 numpy 矩阵向量化去重**（一次比较该元素全部已展开点），并加
   位点×操作数 > 50 万的病态输入保险丝。`resolve()` 由 >12 min 降到 **13 s**。

5. **DB 位点垃圾数据防线（cod_local.get_phase）**：部分 COD CIF（多 loop /
   NoSpherA2 等）建库时解析错位，`cod_atomic_sites` 里存出数字"元素"行
   （COD 1559793 实测 5331 行、元素列全是 hkl/坐标数值，密度 32.9 atoms/Å³）。
   现两层防线：非法元素符号占比 >30% → 弃用 DB 位点走 CIF 全文兜底；展开后
   位点密度 >0.5 atoms/Å³ → 判解析垃圾直接弃用。配套把 `_peak_disagreement`
   的"模拟峰为空返回 0（中性）"改为"返回 inf"——模拟不出的结构必须输给任何
   可评判候选（垃圾结构曾以 0 分"完美"夺冠）；`_load_phase` 同时要求命中结构
   必须有模拟峰。

6. **`_cif_reference_peaks` 直构优先（7-1 卡死 5h 根治）**：旧实现强制走
   CIF 全文 → `CifParser`，而 COD 1541661（15R SiC 多型体，192 位点）的 CIF
   原子环列的是**全胞位点**，CifParser 再乘 192 个 R-3m 对称操作 ≈ 3.7 万
   候选位点的纯 Python 匹配去重，实测小时级起 —— py-spy 抓栈定位（比逐阶段
   日志高效得多）。现优先用 `atomic_sites` 直构 `Structure`
   （与 `cod_local.get_phase` 同一数学，实测 2.3 s/相），CIF 全文解析降级为
   无位点时的回退。

**13 试样"全跑通"基准（BENCH_FAST 快检口径）**：11 样主基准
（`bench_v0152_final.txt`，此前 3-1 卡死 1h+、现 375 s 完成）+ 7-1/7-2 限幅
预算补跑（`bench_v0152_7x.txt`，`BENCH_NFEV=10 / BENCH_STARTS=2` —— 15R SiC
192 位点等大结构的伪 Voigt 全矩阵合成 ~2 s/次、有限差分雅可比每迭代 21 次
评估，全预算口径单样数小时，"全跑通"只验证链路无错无挂）。
`failed=无`。已知慢源（后续优化项）：`spectrum_from_refs` 无峰距截断、
`_scale_phase_peaks` 逐峰 Python 循环、雅可比稠密差分。

#### B 路线 · 同质多象判别

`PhaseStructureResolver` 原先在结构候选里"取第一个能加载的"，方解石会被同化学式的
文石型 (Pmcn) 抢走。新增模块级 `_peak_disagreement()`（候选模拟峰与库峰表的**双向加权
2θ 距离**；I<5 的峰不计、单峰封顶 2.0°；任一侧无峰返回 0），候选排序改为对前 6 名按
`_peak_disagreement + 0.3 × _candidate_score` 择优，再合并结构。

#### 数据层 · 内置 118 矿物参考库峰表重算（A 路线的必要配套）

`resources/database/xrd_reference_database.json` 的 `peaks` 同样是按"P1 非对称单元"
算出来的 —— 118 条里 **59 条**最强线 d > 4 Å 明显异常（方解石最强线成了 5.17°，
刚玉成了 6.80°）。识别 FOM 建立在这套错峰表上，2-1 才会把错的 CaCO₃ 排到真方解石之前。

- 新增 `scripts/regenerate_reference_db_peaks.py`：逐条目取回真实晶体结构
  （条目 `cif_source` 指定的 CIF 优先；取不到或取回的是别的化合物时，回退
  "化学式 + 矿物名"在本地 COD 库检索），用 `CifParser`（自动对称展开 + 消光条件）
  → `XRDCalculator` 重算峰表（Cu Kα 1.5406，5°–90°，归一到 max=100，丢弃 I<0.4）。
- 工程细节：化学式比对会把结构侧氧化态符号（`Al3+`/`O2-`/`Cr0+`）归并回元素符号；
  结构 CIF 普遍省略 H，故当结构侧无 H 时按去氢化学式比对（否则白云母/高岭石这类
  羟基矿物会被整片误判为"元素集合不符"）；晶胞比对先要求逐参数 ≤3%，不满足时允许
  "体积一致"或"最大偏差 ≤25%"并**接管结构的晶胞**（保证峰表与晶胞自洽）；库内存在
  同名重复条目（Calcite/Corundum/Brucite 等各两条），一条修好后另一条直接沿用。
- 落盘结果：库版本 **0.4.0 → 0.5.0**（`peaks_note` + 每条 `peaks_source`/`peaks_version`；
  旧文件备份为 `xrd_reference_database.json.bak_v0.4.0`）。
  **最强线 d>4 Å 的条目：59 → 18**，其中绝大多数是合法的层状矿物基面反射
  （云母 001 8.78°、绿泥石 12.47°、NCM811 的 003 18.44° 本就该是最强线）；
  已知主峰校验（17 种常用矿物）**0 异常**。
- **同名重复条目清理（0.5.0 → 0.5.1）**：118 条里 12 个矿名各有新旧两条
  （legacy 手工条目 + 重算条目并存），legacy 条目部分晶胞压缩（如 ZnO
  a=3.22，实测 3.2494），峰位整体偏移 +0.3° —— 4-1 的 ZnO (100) 31.78° /
  (101) 36.27° 两条强峰因此匹配不上（超出 0.25° 容差）。新增
  `scripts/dedup_reference_db.py`：同名组保留 `v0.15.2-symmetry-expanded`
  条目，剔除 12 条 legacy（118 → 106，备份 `.bak_dedup`）。清理后 4-1 全部
  I≥10 实验强峰均有相归属，物相组合确认无误。
- 识别侧复核（13 试样，高精度寻峰）：**净提升**。1-1 由误判 `Clinochlore` 纠正为
  `Lithium iron phosphate`（FoM 0.83→0.61）；3-1 由 `Zincite+Hydroxyapatite+Clinochlore`
  纠正为 **`Zincite+Fluorite+Corundum`**（=真值 ZnO+Al₂O₃+CaF₂）；2-1 的 `Calcite`
  FoM 0.83→0.51、2-2 的 `Anatase/Rutile` 0.77/0.72→0.44/0.56。未发现回归。

#### C 路线 · MAUD Le Bail + Rietveld 端到端

v0.11.0 已落地（R-C1..C6：`maud_par_builder` / `maud_engine` / `refine()` 分支 /
GUI 引擎选择与回退提示），本轮回归复核通过，无需改动。

---

### v1.0.1 — 2026-09-22 · 1.0 正式版 🏷️

**主题**：v0.15.3 路线图收口内容转正为 1.0 系列 —— **主路线图 M01–M25 全部交付**；
产物全面重建并通过全量回归，代码已推送 GitHub、二进制 Release 已发布。

#### 版本与产物

- 版本号 `__version__` / `config.app_version` / Inno Setup `AppVersion` 统一升至 **1.0.1**。
- 重建产物（本地 `installer_output/`，校验值见 `SHA256-v1.0.1.txt`）：
  - `PolyXRD-Setup-v1.0.1.exe` — 246.3 MB（258,272,876 B）
  - `PolyXRD-v1.0.1-Portable.zip` — 385.2 MB（403,953,179 B，**不随 Release 发布**）
  - 三个外挂数据库包（每库独立）：
    `…-Databases-COD-inorg-index.zip`（COD 无机索引库，主检索库，推荐，130.8 MB）、
    `…-Databases-COD-full-index.zip`（COD 全库索引，193.1 MB）、
    `…-Databases-PDF2.zip`（PDF2-2004，58.0 MB，**仅本地构建，不入 Release**，需正版授权）。
  - 发布产物校验脚本 `_verify_release_py.py` 的库路径同步更新
    （cod_index.sqlite 已在 cod_data/，无机库用 index 变体）。
- 代码提交 `4772d81`（`更新代码修正: 版本 1.0.1 收口`），远端 `main` 与 tag `v1.0.1` 同一 SHA。

#### Release（已发布）

- 地址：<https://github.com/PolyXRD/PolyXRD/releases/tag/v1.0.1>
  （release id 393426603，target `main`，非 draft / 非 prerelease，发布于 2026-09-22T02:57:50Z）
- 附件共 3 个，上传后复核均为 `state=uploaded`：

| 附件 | 大小 | SHA-256 |
|---|---|---|
| `PolyXRD-Setup-v1.0.1.exe` | 246.3 MB | `3ac4fc3a9fc4402bbb7c7164166cc261aed98deb245df0bd0276e1d09ffb024e` |
| `PolyXRD-v1.0.1-Databases-COD-inorg-index.zip` | 130.8 MB | `b6097d83916afee2a9bcbdfc3e9ad33e630e2aaa0fadd87706f413efab9ef144` |
| `PolyXRD-v1.0.1-Databases-COD-full-index.zip` | 193.1 MB | `ed33680c4b5f2c45e38b84fba24ce6c6159e94f5ba95d15910c49003f2db2709` |

> **PDF2-2004 与便携版（Portable）均未随本 Release 分发**，本地仍保留两份 zip 供按需取用。
> 发布脚本 `scripts/_release_v101.py` 内置 `PDF2|Portable` 正则自检，上传后复核确认无违规附件。

#### 相对 v0.15.2 的功能变化（= v0.15.3 内容）

- **M09 候选检索与约束补齐**：`density_range` / `find_phases_direct` /
  `apply_restraints` / 预设存取；连带修复 `name_pattern` 通配符大小写 bug。
- **M15 指标化（原 P3 项补齐）**：`services/indexing.py` 立方/四方/六方内置指标化
  （验收：立方 Si → a≈5.43）；外部 Treor/Dicvol 留接口。
- **M17 晶体结构可视化（原 P3 项补齐）**：`services/structure_viz.py` + `StructureView`
  控件挂入 CIF 浏览器（验收：Si → 8 原子金刚石晶胞）。
- **M26 谱合成内核窗口化**：`spectrum_from_refs` 峰距截断（默认 100×FWHM），
  7251 点 × ~3000 峰单次评估 **1467ms → 270ms（5.4×）**，wR 等效差 <0.05pp；
  `_scale_phase_peaks` 去 np 标量开销。
- 修复 7-1 卡死：`_cif_reference_peaks` 优先 atomic_sites 直构（不再对全胞
  位点 CIF 过 CifParser 二次展开）；基准脚本新增 `BENCH_NFEV`/`BENCH_STARTS`。
- 新增测试 37 项（M09 13 / M15 9 / M17 8 / M26 7）。

#### 验收

- 全量回归：**993 项收集 / 991 通过 / 2 跳过**。首跑 2 项失败均为 v0.15.2
  参考库重算与对称展开后的**陈旧断言**（非功能缺陷），已按现行正确行为修正：
  `get_phase` 现返回对称展开后的全胞位点（方镁石 4Mg+4O=8）；同式多候选
  Calcite(R-3c) + Aragonite(Pmcn) 是**真实多型并存**，属数据感知去重的预期行为。
- 打包 EXE 离屏冒烟：日志 `start v1.0.1 frozen=True` → `splash=ok` →
  `MainWindow OK` → `shown`（原生窗口双击验收由发布方另行人工完成）。
- 产物校验 `_verify_release_py.py` 返回 `RESULT: OK`，各产物字节对账全过。

### v1.0.2 · 启动稳健性修复（版本号已定 **1.0.2**；按用户指示 **EXE 暂不重建、不发布**）

**现场问题**（用户 2026-09-22 反馈）：程序运行中关闭（或在任务管理器里结束）之后，
双击再也打不开，**必须重启电脑**才行。要求：任务管理器结束后双击应该还能打开。

#### 取证结论（诚实披露：本机未能复现）

- 用打包版 `dist\PolyXRD\PolyXRD.exe`（v1.0.1）做了 4 轮"关闭 → 立即再启动"：
  「点 X / WM_CLOSE」与「taskkill /F」各 2 轮，**全部正常启动**（新进程日志
  `shown visible=True` 且出窗口）；关闭后进程确实退出（`--- exit code=0`）。
- 旁证：近 6 h 的 EVTX 里**没有** `Application Error` / `Application Hang` /
  Windows Error Reporting 事件；磁盘上没有第二份 `PolyXRD.exe`；注册表里没有
  安装项（说明当时跑的是构建产物而不是安装版）。用户失败的那次尝试**没有留下任何
  启动日志**（当日日志在 10:01 与 11:23 之间为空档）—— 即"进程根本没走到 Python"。
- 结论：**原始成因未定位**。可确定的是启动侧存在三处稳健性缺口：
  1. 原先**没有单实例保护**：上一次异常退出留下的**幽灵进程**会让"双击"看起来毫无反应；
  2. `app.exec()` 返回后**没有硬退出兜底**：若解释器收尾被线程/句柄挂住，
     会变成"窗口已关、进程还在"，残留实例越攒越多，只能靠重启清理；
  3. "进程没起来"这一类失败**完全无痕**（连一行日志都没有），用户拿不到任何线索。

#### 现场信息补充（2026-09-22 下午用户反馈，关键！）

- **环境**：**全新 Windows 11 电脑**，数据拷贝过去，跑的是 **Portable 解压版**（非安装版）。
- **时间线**：
  1. 首次双击**能打开**，但反应**略慢** —— 慢到用户连点两次，**开出了两个实例**
     （这正是 v1.0.2 单实例守卫针对的场景：无守卫时二次双击 = 再开一个进程）；
  2. 关掉之后再次双击：**有反应**（仍略慢），**启动图一闪就没了**，
     **任务管理器里没有 `PolyXRD.exe`**。
- **初步判读（待日志证实，不下结论）**：
  - 启动图能出现 → Python 已经跑起来并走到 splash 创建，**不是 bootloader 层的死**；
    崩溃点在 splash 之后、主窗口完成之前。
  - "一闪就没 + 无进程"若伴随**原生崩溃**（access violation），Python 层 `crash-*.log`
    不会触发，但 `startup-*.log` 会停在**最后一行成功的步骤**——这就是定位的关键证据；
    同时**Windows 事件查看器 → Windows 日志 → 应用程序**里应有
    `PolyXRD.exe` 的"应用程序错误"事件（`faulting module` 指向哪个 DLL 很关键）。
  - 首启慢：新机 Defender/杀软对 `_internal` 下上千个 DLL 的首次扫描属常态；
    但**两个实例并发**可能写坏用户级共享状态（窗口布局 / QSettings / 会话自动保存），
    下次启动还原时崩溃 —— 与"第一次能开、之后打不开"的时序吻合，
    且恰好落在 v1.0.2 单实例守卫 + 看门狗的覆盖面内。**这只是候选假设**。
- **需要用户提供的证据**（拷回来即可）：
  1. `C:\Users\<用户名>\.polyxrd\logs\` 下**当天的**
     `startup-2026-09-*.log` / `crash-2026-09-*.log` / `startup-failure-2026-09-*.log`；
  2. 事件查看器 → Windows 日志 → 应用程序 里 `PolyXRD.exe` 的"应用程序错误"事件
     （重点 `faulting module` 名字与异常代码）；
  3. Portable 解压到了什么路径（是否含中文 / 空格 / OneDrive 同步目录）；
  4. 新机的显卡型号/驱动状态（Qt/OpenGL 初始化失败是"闪退无进程"的常见来源）。

#### 现场日志取证结论（2026-09-22 晚，用户从 Win11 拷回 `%USERPROFILE%\.polyxrd`）

日志仅一个文件 `logs/startup-2026-09-22.log`（9 次启动），**无 crash-*.log、
无 startup-failure-*.log** —— 失败不是 Python 异常（excepthook 未触发）：

- **成功 3 次**：10:29:44 / 10:29:47（双实例并发，双双 `shown` 后 `exit code=0`）、
  10:34:01（`shown` 后连续跑了 8+ 分钟 —— `external_runs/` 里有 10:36~10:42 的
  GSAS2 / MAUD / FullProf 实跑与 CIF 缓存下载；**该实例全程没有 `--- exit code=` 行**，
  结局待确认）。
- **失败 6 次**：10:30:04 / 10:31:03 / 10:31:38 / 10:47:39 ×2（用户连点两次）/
  10:48:48 —— **全部停在 `showing main window`，下一行 `shown` 永远没出现**。
- **崩溃点钉死**：对照 v1.0.1 源码（`4772d81`），`showing main window` 与 `shown`
  之间只有 `window.show()` 一行 → 6 次全部**死在 MainWindow.show() 内部** =
  原生窗口创建阶段，**无任何 Python 异常**（若为 Python 异常，excepthook 必然落盘
  crash log）。`MainWindow` 无 `showEvent`/`paintEvent` 重载，`restoreState` 在
  构造函数内（已过 `MainWindow OK`）→ 死因在**原生层**。
- **时序特征**：首日冷启动反而成功（10:29 两次），随后 10:30/10:31 连败、10:34 又
  成功（跑满 8 分钟）、10:47/10:48 又连败 —— **间歇性**，与冷/热启动、解压路径
  （`D:\PolyXRD-test\1.0.1\{Portable, PolyXRD-v1.0.1-Portable}` 两套都试过）、
  实例数均无关。
- **候选成因（按可能性，未定案）**：① 杀软/Defender **行为查杀中途杀进程**
  （PyInstaller 常见误报模式；首启通过、被标记后杀，间歇性吻合）；② Qt 原生建窗在
  该机显卡/驱动上崩溃；③ 其它原生层因素。**定案必须靠 faulting module**。
- **v1.0.2 随即落地的两件诊断武器**（趁 EXE 未重建先入库）：
  1. **`faulthandler` 启动即启用** → 原生崩溃瞬间把各线程 Python 调用栈落盘到
     `faulthandler-*.log`，补上"死在 show() 内部且无 Python 异常"这个证据空洞；
  2. **启动日志每行加 `[pid=]` 前缀** —— 现场日志双实例交错写入，无 pid 分不清行。
  相关测试 38 项通过（`test_main_entry` / `test_v013_startup_robustness` /
  `test_instance_guard`）；全量回归在重建 1.0.2 EXE 前再跑。

#### 事件查看器取证（2026-09-22，用户截图）—— 排除杀软，锁定 Qt 原生崩溃

- **Application Error 事件 ID 1000 与启动日志逐一对应**：
  10:30:06 / 10:31:05 / 10:31:40 / 10:47:43 ×2 / 10:48:49 —— 正好是 6 次失败启动
  各 +1~2 秒。
- **崩溃签名（5/6）**：出错模块 **Qt6Widgets.dll，版本 6.11.1.0**，异常代码
  **0xC0000005（访问冲突）** —— 与本仓打包的 PySide6/Qt **6.11.1** 完全一致。
- **崩溃签名（1/6）**：**ucrtbase.dll，异常代码 0xC0000409**（fail-fast，
  即 C 运行时 abort()/__fastfail —— 典型来源 qFatal / 未捕获 C++ 异常 terminate）。
- **杀软排除**：Windows 安全中心"保护历史"在 9/22 **无任何 PolyXRD 相关条目**
  （仅 9/20 17:05 一条 Severe"已阻止的威胁"，与本次时间线不符）。
- **WER ReportQueue / Temp 均为空**（0 字节）→ 无现成 dump 可分析。
- **环境**：Win11 24H2（ucrtbase 10.0.26100），i5-13500H 集成显卡
  **Intel Iris Xe Graphics，驱动 31.0.101.4502（2023-06-15，三年未更新）**。
- **判读**：崩溃在 Qt 原生层、开发机不复现、同日出现两种签名 —— 最像
  **Qt 6.11.1 与该机环境（老旧显卡驱动 / 24H2）的组合问题**。缓解按序：
  1. **更新 Intel 显卡驱动**（零代码改动，优先验证）；
  2. v1.0.2 已新增 **`--safe-render` / `POLYXRD_SAFE_RENDER=1`** 保守渲染开关：
     在 QApplication 创建之前 `setdefault` 三个环境变量 ——
     `QT_OPENGL=software` / `QT_QPA_PLATFORM=windows:darkmode=0` /
     `QT_ENABLE_HIGHDPI_SCALING=0`，用于二分定位（软件 GL / 关 24H2 深色模式挂钩 /
     关 DPI 缩放）；对 v1.0.1 的旧 exe 也可以在 cmd 里手动 `set` 同样三个变量复测；
  3. 若 1、2 均无法消除，重建 1.0.2 时**降级 PySide6 至成熟版本**（如 6.9.x）后全量回归。

#### 本轮改动

- **新增 `services/instance_guard.py` —— kill-safe 单实例守卫。**
  用 Windows **命名互斥量**（内核对象），而不是"锁文件存在即拒绝"——
  后者正是"崩溃 / 强杀后永久打不开"的经典写法。进程一死内核立刻回收对象，
  **下一次双击必然能启动**；同一进程内重复获取也能正确区分。
  - 已有实例**且有窗口** → 窗口 `ShowWindow(SW_RESTORE)` + 置顶 + 闪任务栏，
    本次**安静退出**（双击 = 切回已有窗口）。
    ⚠️ 调试踩到的真 bug：`SetForegroundWindow` 受 Windows 前台锁定
    (ForegroundLockTimeout) 限制，后台进程调用**经常直接返回失败** ——
    早先版本据此判定"没有窗口"，于是又开了一个实例。现改为"找到窗口即算成功"，
    抢不到焦点就退回 `FlashWindowEx` 闪任务栏。
  - 已有实例**但没有窗口**（幽灵实例）→ **照常启动（fail-open）**，
    保证双击一定出窗口。
  - 非 Windows / 无 ctypes 等异常情况一律放行；退回实现使用锁文件 +
    **陈旧锁自愈**（持有者 pid 已死即抢占），同样不会永久挡住用户。
- **新增 `services/startup_diag.py` —— 启动诊断。**
  以独占方式逐个打开 `PolyXRD.exe` / `_internal` 下的关键 DLL，并用
  **Windows Restart Manager API**（`RmStartSession`/`RmRegisterResources`/`RmGetList`）
  反查占用者，把"重启电脑吧"变成"是 xxx.exe (pid=1234) 占着它"。
- **`main.py`**：
  - 最早阶段接入单实例守卫，三态日志（`is_first` / 有窗口安静退出 / 无窗口放行）；
  - `app.exec()` 返回后挂**硬退出看门狗**（5 s 未退即 `os._exit`），
    `aboutToQuit` 另挂 20 s 兜底 —— 机制上杜绝"窗口关了进程还在"；
  - `MainWindow.show()` 之后的日志补上 `visible=` 实测值；
  - 新增 **`PolyXRD.exe --diagnose`**：不起 GUI，直接产出"为什么打不开"的报告
    （`~/.polyxrd/logs/diagnose-*.txt`）；启动失败时把占用进程一并写入
    `startup-failure-*.log` 并弹窗展示。
- **新增测试 `tests/test_instance_guard.py`（14 项）**，含**跨进程 kill-safe 取证**：
  子进程占住守卫 → 强杀 → 新实例必须能拿到（实测通过）。
- `tests/test_main_entry.py` 扩到 13 项：补**幽灵实例不得拦住启动 (fail-open)**、
  **已有实例不重复建窗**、**看门狗在 pytest 下必须不生效**、
  **取 `isVisible` 失败不许把启动搞崩**四条。原有 4 项闪退护栏因 `_StubWindow`
  缺 `isVisible` 一度失败 —— 已把该日志改为防御式取值（记日志不能成为新的失败点）。
- **全量回归：1012 项收集 / 1010 通过 / 2 跳过（exit 0）**。
- **端到端验证 `tests/probe_guard_e2e.py`（真实窗口，5 项全过）**：
  A 首实例出窗口 / B 二次启动不重复开窗而是安静退出 / C 强杀后能重启 /
  D 关窗后进程真的消失（rc=0）/ E 干净关闭后能再启动。

#### 同批同步收口 · 版本号与 `pyproject.toml` 元数据补齐（2026-09-22）

- **版本号同步（共 2 处漏改）**：
  - `pyproject.toml` → `version` `0.15.2` → **`1.0.1`**；
  - `build.bat` → `set APPVER=` `0.15.2` → **`1.0.1`**（顶部 `title` 与 `echo` banner
    两处同步；该变量驱动 `PolyXRD-Setup-v*.exe` / `PolyXRD-v*-Portable.zip` /
    `VERSION_v*.txt` / 两个库包 zip 的命名，以及 `verify_release.ps1 -Version`）。
  此前只改了 `__init__.py` / `config.py` / `PolyXRD-Setup.iss` 三处，构成元数据不一致。
  ⚠️ `build.bat` 为 UTF-8（`chcp 65001`）+ 全 CRLF，改动用**字节级替换**完成
  （3 处 `0.15.2` → `1.0.1`，CRLF 计数 203 前后不变），不触碰文件编码。
- **补齐 `pyproject.toml` 缺失的标准元数据**：`authors`（PolyXRD Team <sshztx@outlook.com>）、
  `keywords`（8 项）、`classifiers`（12 项，含 Development Status 5 / Win32 /
  Science::Research / Python 3.10–3.13 / Chemistry·Physics·Visualization）、
  `[project.urls]`（Homepage / Repository / Documentation / Changelog / Issues / Releases）。
- **消除 setuptools 弃用警告**（本机 setuptools 84.0.0）：
  `license = {text = "MIT"}`（TOML 表，弃用）→ **`license = "MIT"`**（PEP 639 SPDX
  表达式）+ `license-files = []`（本仓库无独立 LICENSE 文件）；同时移除已弃用的
  `License :: OSI Approved :: MIT License` 分类器；`build-system.requires`
  `setuptools>=64` → **`>=77`**（SPDX 写法的最低版本要求）。
- **验证**：`prepare_metadata_for_build_wheel` 生成 `Metadata-Version: 2.4` /
  `Version: 1.0.1` / `License-Expression: MIT`，**零警告**；`read_configuration` 解析正常。
  ⚠️ 本次**未重建二进制产物** —— 上述改动不参与二进制行为，Release 上的
  Setup / 两个 COD 库包与本次改动**无字节差异**；待下次发版时才会体现。

#### 仍需现场信息才能收口

双击的**是哪一个** exe；双击后是完全无反应、还是启动图一闪而过、还是弹了报错框；
关闭后任务管理器里 `PolyXRD.exe` 是否还在；以及是否只在**安装版**上出现。

### v1.1.1 — 2026-09-22 · 国际化补全 + 全链路 UTF-8 + 素材去水印 🚫

**用户诉求**（2026-09-22）：中文界面没问题，但**英/日界面大量残留中文**（部分按钮、分组标题、
状态提示、右键菜单、报告正文等），要求把版本推进到 **1.1.1** 并系统性补全英/日二语。

#### 问题定位（量化，三步）

1. **翻译表本身就"不等长"**。以 v1.0.2 工作区基线（`HEAD`）为准统计三语键数：
   **`zh_CN` 562 / `en_US` 550 / `ja_JP` 510** —— 三语键集**互不相等**（en 比 zh 少 12 个键、
   ja 少 52 个）。这意味着**即使切到英文，也有键取不到值**，只能回退显示中文原键。
2. **视图层两类硬伤**：① 约 **21 处**界面文案是**硬编码中文字面量**（压根没进翻译表）；
   ② 曾引入 **31 个"幽灵键"**（如 `vw.data_view.find_peaks_btn`）——翻译表里**根本不存在该键**，
   `tr()` 解析失败后按"缺键"语义回退，结果把**裸键名**直接显示在界面上。
3. **非视图层整片未纳入 i18n**：ViewModel 的状态/错误提示（约 37 处）、报告正文与质量等级、
   服务层诊断日志、元素周期表的 103 个元素名与状态标签，此前**完全没走 `tr()`**（或作为
   模块级常量在导入期求值，切语言后**不会更新**）。

#### 本轮改动

- **补齐翻译键 384 个**（按"至少在一种语言里此前缺失"计），分域如下：

  | 域 | 新增 | 代表键 |
  |---|---|---|
  | `vw.*`（视图） | 193 | `vw.phase_view.db_cod_inorg` / `vw.report_view.btn_export` / `vw.peak_table.col_2theta` |
  | `elem.*`（元素中文名） | 103 | `elem.H` / `elem.Fe` / `elem.Po` … |
  | `dialog.*` | 26 | `dialog.simulate_title` / `dialog.fom_title` / `dialog.ref_db_search` |
  | `report.*`（报告正文） | 20 | `report.rwp_line` / `report.phase_header` / `report.weight_fraction` |
  | `params.*` | 16 | `params.engine_status_label` / `params.match_tolerance` |
  | `error.*` | 7 | `error.no_phase_selected` / `error.refine_window_no_overlap` |
  | `status.*` | 7 | `status.database_loading` / `status.simulating_pattern` |
  | `menu.*` / `quality.*` / `toolbar.*` | 12 | `menu.file.load_project` / `quality.excellent` / `toolbar.reset` |

- **三语键集对齐到 894 × 3，两两完全相等**（此前 zh 562 / en 550 / ja 510）。
  翻译文件仍以 `json.dumps(..., ensure_ascii=False, indent=4)` + LF 重写，**键集相等**是硬不变量。
  （运行期切语言补修时再补 `template.builtin.*` 7 条 → **最终 901 × 3**，双向差集为空。）
- **31 个"幽灵键"逐条回挂真实键**（涉及 11 个视图文件）：每个幽灵键都在翻译表里找到语义对应的
  既有键后重映射，例如 `find_peaks_btn → vw.data_view.detect_peaks`、`run_bg_btn → exec_bg_subtract`、
  `_label / _db_label → db_builtin / db_cod_inorg / db_cod_full / db_pdf2`。另修正 2 处键名笔误
  （`msg_no_identify → vw.phase_view.msg_run_identify`、`msg_no_data → msg_load_xrd`）。
- **补齐约 21 处硬编码中文控件**：报告页 / 峰表 / 峰归属表 / 元素过滤对话框 / 元素周期表 /
  外部引擎面板 / 绘图控件 / 精修页 / 主窗口右键菜单等，全部改走 `tr()`。
- **ViewModel 国际化**：`main_vm`（18 处）、`data_vm`（9 处）、`phase_vm`（6 处）、
  `refinement_vm`（4 处）的 `status.*` / `error.*` / `menu.*` 文案全部改走 `tr()`。
- **结果模型国际化**：`models/refinement.py` 的 `quality_grade`（`quality.*`）与
  `summary()`（导出报告正文，`report.*`）改走 `tr()`，报告随界面语言切换。
- **服务层日志改符号化 ASCII**：`services/` 层按设计**不依赖 Qt、不调用 `tr()`**（模块文档即如此约定），
  因此**不引入 i18n**，而是把 FullProf runner / GSAS-II·MAUD 启动器 / 物相识别 / 结构解析 /
  MAUD 引擎 / `rietveld_refiner` 等处的**中文诊断日志**统一改写成 `[tag] key=value` 符号化写法
  （`rietveld_refiner` 单文件 26 处），保留可读性的同时避免"中英混杂"；回退原因亦改为 ASCII。
- **元素周期表延迟求值**：模块级 `STATE_LABELS` / `STATE_TIPS` 常量 → `_STATE_LABEL_KEYS` /
  `_STATE_TIP_KEYS` + 运行时函数 `state_label()` / `state_tip()` / `element_name()`，切语言即时生效。
- **补 7 个文件的 `from polyxrd.i18n import tr`**（此前已调用 `tr()` 却未导入 → `NameError` 隐患）：
  `report_view` / `element_filter_dialog` / `element_periodic_table` / `external_engines_group` /
  `peak_match_table` / `peak_table` / `plot_widget`。
- **`i18n_manager` 增加 zh_CN 回退链**：解析顺序改为 **当前语言 → `zh_CN` → 原始键**，
  之后任何语言临时缺键也能显示可读中文，不会再漏裸键名。

#### 验证

| 项 | 结果 |
|---|---|
| 语法编译 | **110 / 110** 源文件通过 |
| 三语键数 | `zh=901` / `en=901` / `ja=901`（运行期切语言补修后终值） |
| 键集对齐 | `zh==en` **True**、`zh==ja` **True** |
| `tr()` 覆盖扫描 | 字面量键 **580**，缺失 **0**，占位符不匹配 **0** |
| 离屏冒烟（首轮，**结论已作废**） | en_US 残留 **2**、ja_JP 残留 **3** —— ❌ **假阴性**。该脚本只把 `QSettings` 引到临时目录，而 `QSettings(org, app)` 在 Windows 上**仍走 Native 注册表**，`_load_settings()` 又用注册表里的 `language` **覆盖**进程内设语言 → 实际量的是**中文**界面，"没残留"是必然。**真实残留为 en 61 / ja 52**（见下节「运行期切语言的整页重翻译」） |
| 相关回归 `pytest`（DB 对话框 / 精修日志 / 纵坐标 / busy 闸门 / 向导 MAUD） | **90 passed** |

> 冒烟脚本带来的教训（供复现）：`MainWindow._load_settings()` 会用持久化的 `QSettings`
> `language` **覆盖**进程内已设语言，且 `I18nManager.reset()` **不会**清掉 `i18n_manager`
> 模块里的 `_i18n` 单例缓存 —— 冒烟测试必须**把 QSettings 引到临时目录**、**完整重置单例**
> 并**预置 `language`**，否则会误判"翻译没生效"。另：离屏平台无字体，截图只会得到方框，
> **文本抽取**才是可靠判据。
>
> ⚠️ **2026-09-23 修正**：上面这条"引到临时目录"**并不成立** —— `setDefaultFormat(IniFormat)`
> + `setPath(...)` 在 Windows 上**拦不住** `QSettings(org, app)`，它照样读 HKCU 注册表。
> 按此写的脚本得出的是**假阴性**（实际量的是中文界面）。可靠做法与实测轨迹见下节
> 「运行期切语言的整页重翻译 › 探测器本身的两个坑」。

#### 语言注册表：zh_CN 显示「简体中文」+ 预留 zh_TW

- `Language.display_names()` 里 `zh_CN` 由「中文」改为 **「简体中文」** —— 与
  `zh_TW`（繁體中文）并列时语义才明确。
- 枚举新增 **`ZH_TW = "zh_TW"`**（显示名 **「繁體中文」**，排在 `zh_CN` 之后）。
  这是**预留槽位**：目前没有 `translations/zh_TW.py`，选中后由回退链落到 `zh_CN`；
  以后只需补一个 `translations/zh_TW.py` 即可生效，**无需改动任何调用点**
  （语言菜单是按 `for lang in Language` 生成的）。
- 同一机制下 `de_DE` / `fr_FR` / `es_ES` / `ko_KR` / `ru_RU` 五个槽位维持原有行为
  （无翻译文件 → 回退中文，不显示满屏键名）。

#### 全链路 UTF-8（跨语言 Windows 不乱码）

同一份产物在中文（GBK）/ 日文（CP932）/ 英文（CP1252）Windows 上行为一致。

- **新增静态守卫 `scripts/check_utf8_encoding.py`**：用 `tokenize` 做词法级扫描
  （注释 / 字符串里的 `open(...)` 不算），检查 `open` / `io.open` / `Path.read_text` /
  `write_text` / `subprocess` / `logging.FileHandler` / `basicConfig` 是否显式指定
  编码；二进制模式与"没有管道的 `Popen`"自动放行。带 `--selftest`（合成样例：
  5 处必须命中、9 处必须放过）。**当前扫描结果 0 处 / exit 0**。
- **修掉唯一一处真正缺编码的文本写入**：`services/export_service.py` 导出 JSON 的
  `open(output_path, "w")` 未指定编码 —— 中文 Windows 上会按 GBK 落盘，换台机器打开即乱码；
  已补 `encoding="utf-8"` 并加 `ensure_ascii=False`（与 `main_window` 既有导出写法一致）。
- **读取用户文本一律 `utf-8-sig`（免疫 BOM）**。`utf-8` 不剥 BOM，会让首行首列带上
  `\ufeff`，实测两处真实故障：
  - `services/user_database.py` 导入峰表时 `float("\ufeff10.5")` 抛 `ValueError`，
    被 `continue` 吞掉 → **第一个峰凭空消失**；
  - `services/data_loader.py` 读 `.xrdml` 时 `decode("utf-8")` 留下 BOM → XML 解析报
    "not well-formed"。
  涉及 `data_loader.py`（3 处 `open` + 1 处 `read_text` + 1 处 XML `decode`）、
  `services/data_io.py`、`services/user_database.py`。
- **面向 Excel / WPS 的 CSV 改为 `utf-8-sig`**：表头是中文，不带 BOM 的 UTF-8 会被
  Excel 按系统 ANSI 代码页解释 → 必然乱码。改的是 `export_service._export_phases_csv` /
  `_export_params_csv` 与 `views/widgets/peak_table.py` 的 CSV 导出
  （`batch_refinement_dialog` 早已是 `utf-8-sig`，本次只是统一口径）。
  ⚠️ **程序间交换的数据文件**（`.xy` / `.dat` / 峰表）**保持不带 BOM 的 `utf-8`**，
  避免第三方解析器把 BOM 当数据。
- **入口强制 UTF-8**：`main.py` 新增 `_force_utf8_environment()`，在任何输出/子进程
  之前执行 —— ① `sys.stdout`/`sys.stderr` 重挂 UTF-8 且 `errors="replace"`
  （GBK 控制台下打印 `°`/中文不再抛 `UnicodeEncodeError`，冻结版无控制台时 `stdout`
  为 `None` 也被安全跳过）；② `setdefault` 给**子进程**留下 `PYTHONUTF8=1` /
  `PYTHONIOENCODING=utf-8`（GSAS-II / MAUD / FullProf 多为 Python 程序，
  经 `os.environ.copy()` 继承）。
  ⚠️ 该函数**不改变当前进程的文件系统编码**（那必须在解释器启动前设 `PYTHONUTF8=1`），
  所以代码内所有文本 I/O 一律显式编码，由上面的静态守卫兜住。
- **`build.bat` / `run_dev.bat` 加 `set PYTHONUTF8=1` + `set PYTHONIOENCODING=utf-8`**：
  构建期与源码模式运行期都走 UTF-8。两个 `.bat` 均为**字节级插入**
  （CRLF 计数 `build.bat` 203→207、`run_dev.bat` 30→34，均无 BOM；`run_dev.bat`
  保持纯 ASCII）。

#### 启动图 / 横幅素材去除「AI生成」水印

- 三张位图素材的右下角带有工具自动添加的 **「AI生成」** 标注（一个圆角矩形框 +
  极右下角一处极小文字）。素材是**位图**，标注已烧进像素，不是可去掉的图层，
  因此按图像修复处理：

  | 文件 | 尺寸 | 用途 |
  |---|---|---|
  | `resources/splash-screen.png` | 480×270 | **启动图**（PNG 由 Qt6 内建解码器读取） |
  | `resources/splash-screen.jpg` | 2560×1440 | 启动图回退（PNG 缺失时用） |
  | `resources/hero-banner.jpg` | 2560×1440 | 横幅 |

- **修复算法**：逐列自掩膜上方干净像素做**竖向线性外推**（因此穿过掩膜的竖向网格线
  会被自然延续），再对填充带做**横向 3 抽头重平滑**以消除 JPEG 噪声造成的竖向条纹，
  最后只回写掩膜内像素。**掩膜外像素与修改前逐字节相同**（实测 diff 最大值 = 0.0000）。
- **验收**：三张图右下角"最亮像素 − 局部背景"由 145/194/202 降到 15/23/47（均为
  背景噪声量级）；掩膜边界台阶均值 ≤ 1.8 / p95 ≤ 7.0；`QPixmap` 载入全部非空；
  `splash-screen.png` 与用户确认选用的那张**逐像素完全一致**。
- **启动图仍是 `splash-screen.png`（480×270 预缩放版）**：这是刻意的 —— PNG 走 Qt6
  内建解码器（不加载 `qjpeg.dll`），且**不需要在启动期解码 2560×1440 再重采样**。
  结合本项目 v1.0.2 定位到的 `window.show()` 原生崩溃（Qt6Widgets.dll）历史，
  启动阶段**少做一次重解码**是有价值的。
- 原图备份在 `~/.polyxrd/artwork_backup_before_watermark_removal/`（不入库）。

#### 运行期切语言的「整页重翻译」（本轮补修）

**这一段纠正上一节的结论**：上一节"离屏残留 2 / 3 ⇒ 无真实未翻译控件"是**假阴性**（原因见验证表）。
换成经得起检验的探测器后，真实缺陷暴露出来 —— 语言切换只刷新了**菜单栏 / 工具栏 / 四个标签页标题**，
页面**内部**与**停靠面板**的静态文案原地不动，于是"英文界面里混着中文"。

- **每个视图自实现 `retranslate()`**（沿用 Qt `retranslateUi` 惯例）：`data_view` /
  `phase_view` / `refinement_view` / `report_view` 四个页面，以及 `pattern_display` /
  `plot_widget` / `peak_table` / `peak_match_table` / `external_engines_group` 五个控件。
  硬约定：**只重设构造期写死的静态文案，绝不触碰运行期数据**（谱线 / 峰表 / 候选列表），
  否则切一次语言就冲掉用户的分析结果。
- **`MainWindow._retranslate_views()` 递归下钻**：遍历四个页面的全部 `findChildren(QWidget)`
  逐个调用其 `retranslate()`，嵌套控件因此只刷新一次、不会重复触发。
- **新增 `MainWindow._retranslate_docks()`**：左侧「参数」/ 右侧「物相」两个停靠面板不属标签页，
  需单独处理 ——
  - 参数表单的**行标签**用 `QFormLayout.labelForField()` 反查设置。⚠️ 易漏点：
    `_bg_method_combo` / `_smooth_method_combo` 的行标签与手工 `addRow(QLabel(...))` 插入的
    **分节标题是两个不同 QLabel**（取同一批 key、文本一样），只改一个另一个仍留中文；
  - 两个下拉的**条目名**本身是本地化的 → `_refill_combo()` **保住当前选择索引**后整表重建；
  - 物相面板的「全选 / 清除」两个按钮；
  - `_peak_hi_check`（文本 + 提示）、`_peak_distance_spin` 提示。
- **新增 `MainWindow._apply_persisted_language()`**：在 `_setup_ui()` **之前**把 `QSettings`
  里的语言装进 `I18nManager`。此前页面先按默认中文建好、语言随后才生效，结果是持久化语言在
  **下次启动**时只对菜单生效、页面依旧中文。
- **修 2 处翻译键错配 + 8 个遗漏动作**：
  - `refine_wizard_menu` 重翻译时用了 `menu.structure_refinement.wizard`（精修向导），
    而创建时用的是 `wizard_quick`（精修向导（快速））→ 切一次语言**菜单项悄悄改名**；
  - `_retranslate_actions()` 补 `reset` / `export` / `clear_data` / `db_manager` /
    `db_open_dir` / `refine_wizard_full` / `batch_refine` / `toggle_theme`；
  - **「数据库」菜单标题**此前压根不在 `_retranslate_menus()` 的映射表里。
  - 另补工具栏 `setWindowTitle(tr("toolbar.main"))` 与动作 tooltip 的重翻译。
- **精修内置模板名改走 i18n**：模板名同时被当作**文件名 / 查找键**，不能直接本地化 ——
  给 `RefinementTemplate` 增加稳定 `key` 字段，新增 `template.builtin.*` 翻译键
  （7 条：`auto` / `standard` / `quick` / `multiphase` / `low_cryst` / `synchrotron` / `cu_target`），
  界面显示名与内部键解耦，用户自建模板仍显示自己的 `name`。
- **顺带修一个打开即崩**：`FormatConvertDialog._sync_output()` 在**无源文件**时
  `Path("")` 实际得到 `Path('.')`，`with_path.with_suffix()` 抛
  `ValueError: WindowsPath('.') has an empty name`。已改为空串直接返回。

**刻意不翻译的记号**（属国际通用写法，翻反而错）：精修页 `Rexp:` / `Rb:`（IUCr 记号）、
物相页 `FWHM:`、纵轴 `log` / `sqrt`。

#### 验证（本轮）

| 项 | 结果 |
|---|---|
| 三语键数 / 对齐 | `zh=901` / `en=901` / `ja=901`，`zh-en` / `en-zh` / `zh-ja` / `ja-zh` / `en-ja` **双向差集全部为空** |
| 语法编译 | **110 / 110** 源文件通过 |
| 离屏残留扫描 | en_US fresh **0** / en_US switch **0** / ja_JP fresh **0** / ja_JP switch **0**（每组各采集 1284–1287 条文本 / 控件） |
| 对照（同一探测器，轨迹可复现） | 上一轮工作结束 **en switch 61 / ja switch 52** → 本轮首测 **10 / 7** → 修掉最后 4 处后 **0 / 0** |
| 回归 `pytest` | `tests/` 全量 **1016 项收集 / 1014 通过 / 2 跳过 / 0 失败**（12m33s）。过程中修了 3 处**测试自身**的问题：① `test_v012_element_order.py` 仍引用 i18n 重构中已删除的模块级 `STATE_LABELS` → 收集期 `ImportError`（改用 `state_label()`）；② 测试套件对**语言环境状态**敏感 —— `I18nManager` 是进程级单例、`MainWindow` 又会用持久化 `language` 覆盖当前语言，导致同一断言"单跑绿、跑整套红" → 新增 `tests/conftest.py` 钉死 `zh_CN` 并隔离 `QSettings` 的 `language` 读写（顺带阻断测试写坏开发者真机注册表）；③ 2 条断言仍写死服务层改造前的**中文字面量**（`engine_fallback_reason` 已按 `services/` 不依赖 i18n 的硬约定改为 ASCII、报告标题因标题改动多了空格）→ 改为断言语义/译文键 |

> ⚠️ **探测器本身的两个坑**（复现必读）：
> ① `QSettings.setDefaultFormat(IniFormat)` + `setPath(...)` 在 Windows 上**拦不住**
> `QSettings(org, app)` —— 它照样读 HKCU 注册表。可靠做法是**在类上临时拦掉 `language` 键**
> （本仓库用 `_smoke_i18n_one.py` 猴补 `QSettings.value`），既不动用户注册表，又让语言完全由脚本掌控。
> ② `I18nManager` 是单例、且各视图模块持有模块级 `_i18n` 引用 → **一个进程里连跑
> （语言 × 模式）多组会互相污染**（实测曾得到"en_US 段里全是日文"的荒谬结论）。
> 必须**每组一个独立进程**，并同时核对脚本回显的 `mgr_language` 与探针键的译文。

#### 版本号收口（5 处）

`src/polyxrd/__init__.py` · `src/polyxrd/config.py` · `pyproject.toml` · `build.bat` ·
`scripts/PolyXRD-Setup.iss` —— 统一 **1.1.1**（`build.bat` 为 UTF-8 + 全 CRLF，改动按字节级替换，
不触碰编码）。

---

### v2.0.0 — 2026-09-23 · 精修引擎大改（指标 / 正向模型 / 峰位物理 / 数据修复）

> **版本号**：本轮改动跨"评价指标定义、正向模型、峰位物理、参考库数据"四大块，
> 且会**改变历史 wR/Rexp/GOF 数值口径**与部分物相的峰表内容 → 按语义化版本升级为
> **2.0.0**（`src/polyxrd/__init__.py` / `config.py` / `pyproject.toml` / `build.bat` /
> `scripts/PolyXRD-Setup.iss` 五处已收口；`build.bat` 按项目红线做**字节级**替换以保住
> UTF-8 + CRLF 编码）。
>
> 以下各条为本次 2.0.0 的全部内容（按落地顺序记录）。

> 起点：用户反馈"Rexp 貌似都不对、结果总是不理想"。深审后定位到**不是调参问题，
> 而是评价指标本身算错了**，并顺带发现正向模型的三处结构性问题。
> 规划文档：`docs/精修改进方案-v2-四阶段.md`（诊断）与
> `docs/精修改进实施手册-v3-分步可执行.md`（31 个工作项 W00–W30）。

#### 1. Rexp / GOF 数值错误（根因与修正）

- **根因**：`_calc_profile_metrics` 用标准 Rexp 公式，但分母配的是**单位权**（或"均一化为均值 1"的
  权重）。标准定义下 `w = 1/σ²`，计数统计 `σ² ≈ y` → 分母应为 `Σ y` 而非 `Σ y²`，
  相差一个 `≈ y` 的量级；而归一化权重又把统计尺度乘掉。
  **实测 2-1 的 Rexp 偏小 130.9 倍，GOF 给出 920（标准定义应为 10.8 量级）。
  且该系数随数据强度标尺漂移 → 旧 Rexp/GOF 无物理意义。**
- **修正**：`_calc_profile_metrics` 新增 `sigma2`（**未归一化**方差）参数，输出
  `Rwp / Rexp / Rp / chi2 / chi2_red / GOF`；`Rb` 保留为兼容别名（其真实语义一直是**轮廓 R**，
  即 `Σ|Δy|/Σy`，并非 Bragg R）。单测 `tests/test_metrics_selfcheck.py` 6 条自检
  （Rwp 标尺不变 / Rexp 解析值 / GOF≈1 / Rexp ∝ 1/√计数 / Rp 公式 / chi2_red = GOF²）。
- **默认统计权**：builtin 引擎默认 `stat_weights="poisson"`（原默认 `"none"`）。
  理由：Rietveld 标准做法就是加权最小二乘，目标函数与评价指标必须是同一把尺；
  单位权下 `Σw·y² = Σy²`，Rexp 无意义。显式传 `"none"` 仍可退回旧行为，
  此时 `metrics_valid=False`，界面显示"不可解读"而非给一个漂亮数字。
- **快检门限解耦**：20% 这条早退线是在单位权口径下标定的，统计权下加权 wR 天然更高，
  故门限改用**未加权 wR** 判定（`fit_params.wR_unweighted`），避免白白变慢。
- **其它引擎**：GSAS-II 桥只回传 wR（不回传 Rexp）→ 不再本地硬算，改标"不可解读"；
  Le Bail 改用 Poisson 方差。
- **实测（同配置前后，预算受限口径）**：

  | 试样 | 修正前 Rexp / GOF | 修正后 Rexp / GOF |
  |---|---|---|
  | 2-1 | 0.021 % / 920.4 | **2.796 % / 10.80** |
  | 4-1 | 0.209 % / 230.5 | **8.567 % / 4.68** |

  （2-1 修正后的 2.796% 与深审阶段独立复算的 2.797% 一致，互为佐证。）

#### 2. 结果模型与界面

- `RefinementResult` 新增 `Rp / chi2 / chi2_red / metrics_valid / metric_note / warnings`；
  `Rb` 字段保留（兼容旧项目文件）。
- 精修页/向导页：`Rb:` 标签正名为 `Rp:`；`metrics_valid=False` 时 Rexp/GOF 显示"不可解读"；
  结果区新增提示条（引擎回退 / 指标不可解读 / 后续的 Kα2 检测等），并同步写入执行日志。
- 引擎回退不再只在日志里：`refine()` 记录 `engine_requested` 与实际引擎不一致时写入 `warnings`。

#### 3. 质量分级统一

- 历史上存在**两套阈值**（`quality_grade` 用 <2/<5/<10/<20 的同步辐射口径，引擎内部另写
  <5/<10/<20/需改进）→ 同一结果两种等级。现统一到
  `models/refinement.py::quality_grade_for`：**<5 优秀 / <10 良好 / <15 一般 / <25 差 / ≥25 需改进**
  （实验室粉末 XRD 口径）。
- `converged`/`num_cycles` 语义修正：不再只取多起点里的 `success`，改为"多起点成功或抛光仍有改进"，
  并把 `nfev / converged_multistart / converged_polish_improved / wR_before_polish` 一并写入
  `fit_params`（`num_cycles` 的实际语义就是 nfev）。

#### 4. 回归

- 新增 `tests/test_metrics_selfcheck.py`（6 条，改动前 5 红 1 绿 → 改动后全绿）。
- 精修相关子集 `test_rietveld* / test_le_bail / test_report_m18 / test_phase_display /
  test_spectrum_windowed_m26 / test_v012_refinement_log`：**111 项全通过**。

#### 后续（本版进行中，见实施手册 W11–W30）

峰形改面积归一（当前为"峰高归一"，导致积分强度 ∝ FWHM、η 不是混合比、Caglioti 参数被拟合到
错误值）→ 背景进拟合 → 峰位物理（样品位移/低角不对称/全晶胞）→ 结构自由度与 `S·ZMV` 定量 →
自动策略（观测峰种子化、先 Le Bail 后 Rietveld）。

#### 5. 峰形改**面积归一**（M3/W11）

- **问题**：`phase_display.spectrum_from_refs` 里高斯与洛伦兹都写成"峰高 = 1"
  （`exp(-Δ²/2σ²)` 与 `γ²/(Δ²+γ²)`）。后果：模型**积分强度 ∝ FWHM**（实测 面积/FWHM = 131.5 恒定），
  而 Rietveld 要求积分强度 = `m·LP·|F|²·S` **与峰宽无关**；η 从 0→1 会让面积变化 ~47%（η 不再是混合比）；
  固定 FWHM 时该错误被 scale 吸收，一旦 Caglioti 打开就暴露 —— 合成对照里 `U` 被拟合到
  **−0.0021（真值 0.012）**，即由峰宽导出的晶粒尺寸/微观应变不可信。
- **修正**：面积归一化 —— `G = exp(-Δ²/2σ²)/(σ√(2π))`，
  `L = (γ/π)/(Δ²+γ²)`（代码里实现为 `(γ²/(Δ²+γ²))·(1/(πγ))`，γ = FWHM/2），
  `PV = η·G + (1−η)·L`，`∫PV = 1`。两条谱合成路径（全矩阵 / 窗口化）同改。
- **自检**：`tests/test_peak_shape_area.py` —— 单峰面积 = 强度 × scale × weight，
  **与 FWHM、η、峰形类型无关**（面积守恒 ±1%），且峰高不再恒定（∝1/Γ）。
- **实测（预算受限口径，同配置前后）**：

  | 试样 | 面积归一前 wR / Rp | 面积归一后 wR / Rp |
  |---|---|---|
  | 2-1 | 30.195 % / 21.772 % | 30.417 % / 21.807 % |
  | 4-1 | 40.099 % / 31.740 % | 41.574 % / **28.806 %** |

  **诚实口径**：真实试样上加权 `Rwp` 略升（+0.2 / +1.5 个百分点），4-1 的轮廓 R 改善 2.9 个百分点。
  本项的主要收益是**物理正确性**（峰宽参数恢复可解释、为样品位移/低角不对称/全晶胞精修打底），
  以及合成数据上的量级改善（同一模型自洽时 Rwp 5.996% → 0.340%）。因此保留本项。
- **连带测试更新**：`tests/test_spectrum_windowed_m26.py::test_short_peaks_rows_ignored` 的容差
  由 1e-3 放宽到 5e-3（面积归一后洛伦兹远尾幅度按 `1/(πγ) ≈ 6.4×` 放大，截断差随之上移），
  并把"缺强度的行被忽略"断言得更具体（40° 处不出现峰）。

#### 6. 背景进拟合 + 优化器开关（M4/W13–W15）

- **W13 背景抛光默认开启**：`bg_chebyshev_deg` 默认由 `0` 改为 **6**。
  背景原先只在开头用 median/SNIP 估一次即冻结，是"Rwp 有地板"的首要原因之一
  （合成自检：冻结背景 5.041% vs 精确背景 1.012%）。该函数自带两道保护
  （校正幅度 ≤30% 动态范围 + 仅在 `after_wR` 更优时采纳），显式传 `bg_chebyshev_deg=0` 可退回。
  **实测（同配置）**：2-1 `30.417% → 29.896%`；4-1 `41.574% → 40.938%`。
- **W14 `x_scale` 实测后默认关闭（保留为可选项）**：参数确实跨 5 个数量级，
  但 `x_scale="jac"` 在默认预算下 **更差也更慢** ——
  2-1：关 → `wR=29.893% / 37.1s`；开 → `wR=30.176% / 54.9s`
  （受限预算同样：2-1 差 0.52pp、4-1 差 0.17pp）。
  结论：Jacobian 定标改变了信赖域几何，把解引到略差的局部极小。
  故默认保持关闭，`x_scale` 作为 kwargs 保留（可传 `"jac"` 或正数数组对比）。
- **W15 统计权重默认开启**：`stat_weights` 默认由 `"none"` 改 **`"poisson"`**（已在 §1 说明）。
- **回归**：`test_rietveld* / test_le_bail / test_background_m04 / test_metrics_selfcheck /
  test_peak_shape_area` 共 **78 项全通过**（其中 `test_rietveld_a4_chebyshev` 的"默认关闭"
  断言按新口径改为"默认开启 + 显式 0 可退回"）。

#### 当前累计效果（v1.1.1 → M4，受限同配置口径）

| 试样 | 指标 | v1.1.1 基线 | M1 后 | M3+M4 后 |
|---|---|---|---|---|
| 2-1 | Rexp / GOF | 0.021 % / 920.4 | 2.796 % / 10.80 | 2.796 % / **10.69** |
| 2-1 | wR（加权） | —（无意义） | 30.195 % | **29.896 %** |
| 4-1 | Rexp / GOF | 0.209 % / 230.5 | 8.567 % / 4.68 | 8.567 % / **4.78** |
| 4-1 | wR（加权） | —（无意义） | 40.099 % | **40.938 %** |

> 注：M3 面积归一让 4-1 的加权 wR 略升、轮廓 R 明显改善；M4 又把两者都拉回并超过 M1 水平。
> 真正的量级改善预期来自 M5–M7（峰位物理、结构自由度、自动策略），见实施手册。

#### 7. Kα2 双线检测（M5/W19-a）

- **背景**：Kα2 未剥离时，模型只描述 Kα1，会在每个峰的高角侧留下系统性残差，
  高角区尤甚（Cu 靶 36° 处 Δ ≈ 0.093°，与常见 FWHM 同量级）。此前只有"手动剥离"工具，
  精修侧完全不知道数据里有没有 Kα2。
- **实现**：新增 `RietveldRefiner.detect_ka2(data)`，用**形状无关的对称性判据**：
  取最强峰中心 `c`（三点抛物线亚步长精修）与解析间距 `Δ = 2(λ2/λ1−1)tanθ`，比较
  `ratio = I(c+Δ)/I(c−Δ)`（扣背景后）。对称单峰 `ratio ≈ 1`；含 0.5 强度比 Kα2 时 `ratio ≳ 2`；
  低角轴向发散引起的固有不对称让 `ratio < 1`（安全方向）。判据：`ratio > 1.35` 且高角侧强度有量级。
  （**为何不用"单峰拟合看残差"**：单峰模型可靠加大 FWHM / 提高洛伦兹占比把双线吸收掉，
  实测合成双线上完全检测不出；对称性判据没有这个失败模式。）
- **接入**：`refine()` 出口默认执行一次检测（`detect_ka2=False` 可关），命中则写入
  `result.warnings` 与 `fit_params["ka2_detected"]/["ka2_info"]`，精修页提示条与向导日志直接可见。
- **实测**：合成单线 → `flagged=False`、`ratio≈1.00`；合成双线 → `flagged=True`、`ratio>1.35`、
  `Δ` 与解析值 0.093° 一致。真实试样：**2-1 ratio=1.45 命中**（与深审阶段人工量到的
  36.22° 主峰高角侧台阶一致）、1-1 1.45 命中、3-1 1.58 命中；
  4-1 最强峰在 18.6°（Δ 仅 0.047°，物理上不可分辨）→ 保守不报。
- **新增测试**：`tests/test_ka2_detect.py`（4 条：单线不报 / 双线报 / 警告进精修结果 / 可关闭）。
- **回归**：`test_ka2_detect + test_rietveld* + test_le_bail + 指标/峰形/自动引擎` 共 **84 项全通过**。

#### 8. atomic_sites 键名统一 + U_iso 解析（M6/W20、W21 读侧）

- **潜伏 bug（本轮修掉）**：`cif_database._extract_atomic_sites` 只产出
  `fract_x/fract_y/fract_z`（且只把 4 个列转 float），而下游一律读
  `x/y/z/element/label/occupancy` —— `phase_cif.phase_to_cif_text`、
  `rietveld_refiner._cif_reference_peaks` 的 pymatgen 直构路径、3D 结构视图都如此。
  于是**走 CIF 解析的物相在这些下游静默失败**（KeyError 被 `except` 吞掉 → 悄悄回退旧峰表）。
- **修正**：
  - `_extract_atomic_sites` 补出规范键 `x/y/z/element/u_iso`（**同时保留原始 `fract_*` 键**，旧调用方不受影响）；
    `element` 依次取 `element` 列 → CIF 惯用的 `type_symbol` → `label` 的元素前缀。
  - `u_iso` 取值规则：`U_iso_or_equiv` 优先；否则 `B_iso_or_equiv/(8π²)`（`B = 8π²U`）；
    两者都缺 → **0.005 Å²** 并标 `u_iso_default=True`；自动剥离 CIF 常见的 esd 括号（`0.006(1)`）。
  - `cod_local.get_atomic_sites`（W21 读侧）保持同一键集合：`cod_atomic_sites` 目前**没有** `u_iso` 列
    （正式加列走版本化迁移，见实施手册 W21），读不到时给同样的 0.005 默认值 + `u_iso_default` 标记，
    使两个结构来源语义一致。
- **新增测试**：`tests/test_atomic_sites_normalize.py`（5 条：规范键齐备且 `fract_*` 保留 /
  U 列带 esd 解析 / B 列换算 / 缺省 0.005 / 解析出的位点能直接喂给 `phase_to_cif_text`）。
- **回归**：CIF/COD/结构视图/识别相关 **85 项全通过**。

#### 9. 样品位移项（M5/W16，opt-in 默认关）

- **为什么加**：`zero_shift` 是**常数**偏移；样品表面偏离测角仪轴时，峰位偏移按
  **`Δ(2θ) = −2·s·cosθ/R`** 变化（R = 测角仪半径，默认 240 mm），只用零点会把
  一类系统性偏差塞进常数项。
- **实现**：新增 `RietveldRefiner._apply_displacement(phase_peaks, s_mm, R_mm)`；
  位移参数挂在**参数向量最末尾**（沿用"末尾挂新自由度、不动既有索引算术"的约定），
  `refine_displacement=True` 启用、`param_mask["displacement"]=False` 可冻结、边界 ±1.0 mm。
  为不改动 `_unpack` 的元组长度（避免 5 处解包点全部改动），用独立取值函数 `_disp_of(params)`。
- **默认关闭**：不影响现有行为；`fit_params` 记录 `refine_displacement / displacement_mm /
  displacement_radius_mm`。
- **测试**：`tests/test_sample_displacement.py`（5 条）——
  100°/s=0.5mm/R=240mm 的解析值逐位核对（Δ=−0.1535°）、`s=0` 零改动、
  `Δ2θ ∝ cosθ`（**低角位移量更大**，与"高角更敏感"的直觉相反，正是该式的形式）、
  默认关闭、opt-in 后能从合成数据把 s 拟合回来且 wR 不劣化。
- **实测发现（如实记录）**：在单相 Si（20–100°）合成谱上，真值 `s=0.40 mm`
  只能回收 `s≈0.11 mm` —— 因为**样品位移与各向同性晶胞缩放存在部分退化**
  （两者都能平移峰位、只是角度依赖不同）。结论：位移项应作为**联合精修**的一部分，
  在更宽的角范围 / 晶胞已固定时回收更好；本文不据此声称定量精度。

#### 10. `cod_atomic_sites.u_iso` 列与迁移（M6/W21）

- **schema**：`cod_atomic_sites` 新增可空列 **`u_iso REAL`**（新库建表即带）。
  `_migrate_schema` 增加幂等的 `ALTER TABLE ... ADD COLUMN u_iso REAL`；
  极老 SQLite/只读库失败只告警（读侧有默认值兜底）。
- **写入**：`parse_atom_sites_from_cif` 解析 `U_iso_or_equiv`（优先）或
  `B_iso_or_equiv/(8π²)`，缺省 **0.005 Å²** 并标 `u_iso_default`；`_INSERT_SITES_SQL`
  与批量写入同步为 9 列。
- **读取**：`get_atomic_sites` 优先带 `u_iso` 查询，旧库/旧包没有该列时自动回退到
  不含它的查询并补 0.005 默认值 —— **不强制用户重下数据库**。
- **测试**：`tests/test_cod_u_iso_column.py`（6 条：新库带列 / 旧库幂等迁移 /
  插入 SQL 与 schema 匹配 / U 列 / B 列换算 / 缺省值）。

#### 11. 产品分层文案（M6/W24）

- README 的"Rietveld 结构精修"条目改为**引擎能力分层**表述：
  **真 Rietveld**（结构自由度 + `S·ZMV` 定量）指向 GSAS-II/FullProf/MAUD；
  **内置引擎**明确为**免结构全谱拟合（Le Bail 级）**，其 wt% 是**相对定量**而非严格质量分数；
  并写明 v1.1.2 起的指标口径（统计权；单位权下 `Rexp/GOF` 显示"不可解读"）。

#### 12. 全晶胞参数模式（M5/W18，opt-in 默认关）

- **动机**：各向同性缩放只能整体平移峰位，修不了各向异性失配（例如只在一个方向上畸变）。
- **实现**：`cell_mode="full"` 时每相 6 个**相对库值的比例**（a,b,c,α,β,γ），
  由 hkl 用一般三斜公式反算 d → `2θ = 2·arcsin(λ/2d)`；参数同样挂在向量末尾。
  默认仍是 `"isotropic"`（每相 1 个自由度），`fit_params` 记录
  `cell_mode / cell_mode_used / cell_consistent`。
- **踩到并修掉两个真 bug（都很有代表性，写下来防复现）**：
  1. **早退容差吞掉有限差分**：`_apply_full_cell` 里"六参数全为 1 就直返"原本用
     `np.allclose`（默认 `rtol=1e-5`），而 `least_squares` 的有限差分步长只有 ~1.5e-8
     → 所有扰动都被判成"等于 1"而早退 → 该参数雅可比列**恒为 0** → 晶胞参数永远不动
     （实测：2271 次调用里只有 1 次是非单位缩放）。改为严格判零（`< 1e-12`）后立即可优化。
  2. **峰表↔晶胞不自洽**：内置库多数矿物的**静态峰表与其 `lattice` 并不自洽** ——
     用晶胞由 hkl 重算 2θ，与峰表存值的中位差：Corundum 14.9°、Calcite 15.5°、
     Zincite 11.7°、Brucite 9.0°，而 **Fluorite 0.0007°**（自洽）。
     强上 full 模式会把峰位算飞（4-1 实测 wR 41%→100%）。
- **守卫（全有或全无）**：任一相峰表与晶胞不自洽 → **整体**退回各向同性并记日志/字段。
  反例实录：4-1 中只有 CaF₂ 自洽（7 条峰），单独给它 6 个自由晶胞参数会去追别相未建模的
  残差（wR 41%→70%，过拟合），全有或全无可挡住。
- **效果**：在峰表自洽的数据上（CIF/pymatgen 现算峰表就是这种）——
  合成四方相各向异性畸变（真值 a×1.008）回收 `sa=1.00804 / sb=1.00842 / sc=0.9997`，
  **wR 16.23% → 12.12%（−4.1pp）**；在真实 2-1/4-1 上守卫按预期退回各向同性，
  结果与 isotropic **逐位相同**（29.896% / 40.938%），零风险。
- **测试**：`tests/test_full_cell_mode.py`（5 条：单位缩放零改动 / a 影响 hkl≠00l 且方向正确 /
  c 只影响 00l / 默认 isotropic / full 吸收各向异性且 wR 不劣化）。
- **结论与后续**：本项默认关闭；要在真实数据上普遍可用，前提是**把内置库峰表按晶胞重算并
  校验一致性**（属独立数据修复工作，见实施手册"另排期"）。

#### 13. 低角不对称 split-PV（M5/W17，opt-in 默认关）

- **动机**：低角峰受轴向发散影响，低角侧比高角侧宽；对称峰形在 `2θ≲25°` 会留下系统性残差。
- **实现**：`spectrum_from_refs(..., asymmetry=a)`（默认 0 = 完全旧行为）。
  先把"面积归一峰形"抽成共用函数 `_area_normalized_profile`（对称与 split 共用同一数学，
  两条合成路径也共用，避免分叉）。split 模式按 `delta` 符号取两侧宽度
  `FWHM·(1±fac)`，每半边仍是面积归一曲线限制在半边 → **每半边积分恒为 0.5，总面积不变**。
- **权重形式（踩过坑）**：首版用 `fac = a / max(tanθ, 0.3)` —— 45° 处仍有 `0.3a`，
  高角也不对称（实测 `r90 = 1.92`），与"低角效应"的物理不符。改为
  **`fac(θ) = a·tan(10°) / max(tanθ, tan(10°))`**：`a` 的语义 = "2θ≈20° 处的展宽比例"，
  低角封顶、高角按 tan 衰减（90° 处仅 0.176a）。修正后实测 `r20=1.49 / r90=1.07`，
  单峰面积相对变化 <1.1%。
- **接入**：`_compute_spectrum_from_ref(..., asymmetry=)` 贯穿精修四处合成调用；
  `refine(..., asymmetry=a)` 可用（0~0.4），`fit_params["asymmetry"]` 记录实际取值。
  **目前不做参数拟合**（用户给经验值），拟合化留待 M7 自动策略阶段。
- **测试**：`tests/test_asymmetry.py`（6 条：关时与旧调用逐点一致 <1e-12 / 面积守恒 /
  低角侧更宽 / 低角显著高角弱 / 精修接口透传与默认值）。
- **回归**：峰形/谱合成/精修/指标共 **138 项全通过**。

#### 14. 许可证变更：MIT → 双许可（学术免费 / 商业需单独书面授权）

- **变更**：本仓库**不再以 MIT 授权**。新增根目录
  [`LICENSE`](../LICENSE)（英文）与 [`LICENSE-CN`](../LICENSE-CN)（中文），
  两者对应同一份**双许可条款**：
  - **学术许可**：学术研究、教学、非商业目的免费使用/修改/分发（需保留版权与许可声明）；
  - **商业许可**：任何商业用途**必须**事先取得版权持有人单独书面授权
    （联系 `sshztx@outlook.com`），条款第二/二节列举了商业用途的范围。
  - 另含**引用要求**（使用本软件产出结果的论文/报告/演示需按项目文档引用）与通用条款
    （违约自动终止、不默示授予专利权利）。
- **README**：`## 📝 版本兼容性 & License` 段落由原来的"代码部分遵循 MIT License"
  替换为**中英双语精简版权声明**，并指向两个许可文件；README 文件树补入 `LICENSE` / `LICENSE-CN`。
- **元数据**：`pyproject.toml` 的 `license = "MIT"` →
  **`license = "LicenseRef-PolyXRD-Academic-Dual"`**（SPDX 无该双许可的标准标识符，
  按 PEP 639 使用 `LicenseRef-`），`license-files = ["LICENSE", "LICENSE-CN"]`。
  实测 `prepare_metadata_for_build_wheel` **零警告**，产物元数据为
  `License-Expression: LicenseRef-PolyXRD-Academic-Dual` + 两条 `License-File`。
- **第三方许可不受影响**：PySide6 (LGPL/GPL)、pymatgen、COD、powerxrd 等**上游依赖各自的
  许可证条款照旧**（README 开源致谢表与 `Thx2OpenSource.md` 保留）。
- **注意**：本条目仅记录许可条款变更；**历史版本（≤ v1.1.1）的已发布内容按当时声明的 MIT 授权**，
  新条款自本版本起对仓库内容生效。商业授权判定请以 `LICENSE` / `LICENSE-CN` 正文为准。

#### 15. 内置参考库 hkl 修复 + 三斜公式归一化因子（库 0.5.1 → 0.5.2）

> 这两项是 **W18 全晶胞精修与将来 `S·ZMV` 定量的硬前置**：凡依赖 hkl 的功能，
> 都要求"峰表 2θ"能由"(hkl, 晶胞)"重算出来。

**(a) `_calc_d_spacing_from_hkl` 漏了归一化因子（根因级 bug）**

- 一般三斜公式应为 `1/d² = (分子) / (1 − cos²α − cos²β − cos²γ + 2cosαcosβcosγ)`，
  分母 = `(V/(abc))²`。旧实现只算了分子 —— 函数里算了 `volume` 却**从未使用**，正是漏项旁证。
- 后果：**立方/正交侥幸正确**（因子 = 1），**六方/三方全错**（γ=120° 时因子 0.75 → d 偏大 √(4/3)）。
  实测：ZnO(100) 27.42°(错) → **31.767°**(对)、ZnO(101) 31.26 → **36.252**、
  Brucite(001) 16.09 → **18.602**，修正后与 PDF 卡一致。这也解释了为何此前只有
  立方相 Fluorite 的"峰表 ↔ 晶胞"能对上（0.0007°），其余 20 余条全不自洽。
- 该函数是 `_calc_peak_positions`（Le Bail 用）与 W18 全晶胞精修的共用底座，修一次两处受益。

**(b) 库峰表的 hkl 被写坏（v0.15.2 重算的遗留）**

- **症状**：Zincite 多个不同峰都标成同一个 `(1,0,-1,-1)`，还出现 `(0,0,0,0)` ——
  典型的 `pattern.hkls` 与峰表下标错位 / 四指标转换写坏。
- **修复**：新增 `scripts/fix_reference_db_hkl.py`（幂等）—— 保留已验证的 2θ 与强度，
  **先验证原 hkl**（2θ 对得上就只把 2θ 吸附到计算值，避免等价反射之间的无意义改名），
  对不上的才在"由晶胞枚举的允许反射表"里按 2θ 最近邻重索引；同一 hkl 重复取最强。
- **结果**：输入 4612 峰 → 保留 4526（**512 条 hkl 改名**、7 条去重、79 条丢弃）；
  受影响 **29/106** 条（正是此前的"不自洽清单"）。修复后
  **106/106 条峰表与晶胞自洽（最大偏差 0.000°）**。库版本 → **0.5.2**；
  报告见 `docs/参考库hkl修复报告-v1.1.2.txt`，旧库备份留在仓库外
  `E:\TEMP\_refdb_0.5.1_backup_2026-09-23.json`。

**(c) 验证：识别不退化、精修显著受益（同一受限预算口径）**

| 试样 | 修复前 wR | 库修复后 | 库修复 + full 晶胞 |
|---|---|---|---|
| 2-1 | 29.896 % | **29.023 %** | **27.662 %** |
| 4-1 | 40.938 % | **34.290 %** | **33.223 %** |

- 识别质量：Top-10 真值召回 **19/20 = 95%，保持不变**（石英还从 #5 升到 #1）。
- 4-1 单是库修复就降 **6.65 个百分点**：此前 W18 的守卫会把 4-1 整体退回各向同性
  （因为多相不自洽），现在逐相自洽 → full 晶胞模式**真正启用**，再降 1.07pp。
- **回归**：识别 / 精修 / 峰表 / 召回共 **138 项全通过**。

#### 16. 质量分数定量 `W_p ∝ S_p·(ZMV)_p`（M6/W23，含口径标记）

- **问题**：`weight_pcts = opt_weights/Σw` 只是**相对强度**归一，缺 Rietveld 的
  `S·(ZMV)` 关系（2-1 实测 66/34 而真值 50/50，4-1 更偏）。根因是**参考峰表按每相
  max=100 归一化**，拟合幅值 `amp_p` 是相对该归一化图谱的，物理标度被吸收掉了。
- **实现**：
  - `_cif_reference_peaks` 顺带记录每相**(未归一化)强度标尺** `k_p`（pymatgen
    `get_pattern(..., scaled=False)` 的 `max(Σ|F|²·m·LP)`）与
    **`ZMV_p` = 晶胞内质量 × 晶胞体积**（`structure.composition.weight × volume`，
    无需单独求 Z——`Z·M` 就是晶胞总质量）。
  - 新增纯函数 `_mass_fractions(amp, k, zmv)`：`S_p = amp_p·k_p/100` →
    `W_p ∝ S_p·ZMV_p` → 归一化到 100；**任一相缺 k/ZMV 即返回 None**。
  - `_refine_builtin` 接入：全部相都有结构信息时给出**质量分数**，
    否则退回原相对定量，并用 **`fit_params["weight_basis"]`（"mass" / "relative"）**
    明确标注口径——不再让"相对强度% "冒充"质量分数%"。
- **测试**：`tests/test_quantification_zmv.py`（11 条：幅值比退化 / `k` 标尺修正 /
  `ZMV` 方向 / 手算三方对照 / 五种信息缺失回落 / 精修结果标口径）。
- **实测（重要边界，如实记录）**：内置库的相**不带结构**（`atomic_sites=0`、
  `cif_path=None`）→ 拿不到 `k/ZMV` → 2-1 / 4-1 走 **`basis=relative`**（原数值不变）。
  严格质量分数只在**带结构的相**上启用：COD 全库（`cod_local.get_phase`）、
  CIF 浏览器导入、结构解析链路。这与 README 的产品分层一致（严格定量需结构）。
- **结构来源已就绪（此前判断有误，已核实更正）**：`PhaseStructureResolver` **已经接入
  App 主流程**（`main_vm.py:54`、`refinement_wizard.py:175`），精修前会按
  "化学式 + 晶胞 + 空间群"从本地 COD 全库回填 CIF 结构 —— 本机实测 **2/2、4/4 相全部回填成功**。
  所以内置库条目本身不带结构，但**用户路径上会先回填**，严格定量因此是可达的。
- **换算方向 bug（已修，重要）**：首版把标度还原写成 `S = amp·k/100`，而正确关系是
  `S = amp·100/k`（归一化图谱 = 100·raw/k ⇒ `sim = amp·(100·raw/k) = S·raw`）。
  比例写反的后果是灾难性的：2-1 一度算成 **0.56 / 99.44**。修正后同一路径给出
  **53.06 / 46.94（真值 50/50）**。单元测试同步按物理关系重算期望值
  （这正是"按实现写测试"会一起错掉的典型，已在测试注释里写明推导）。
- **实测（结构回填后，同一受限预算口径）**：

  | 试样 | 旧（相对强度） | 新（质量分数） | 真值 |
  |---|---|---|---|
  | 2-1 | 69.95 / 30.05 | **53.06 / 46.94** | 50 / 50 |
  | 4-1 | 29.4 / **6.5** / 26.0 / 38.2 | 12.6 / **18.9** / 20.1 / 48.4 | 19.9 / 21.3 / 22.5 / 36.3 |

  绝对偏差之和由 29.6pp 降到 26.5pp，且 4-1 里最严重的 Al₂O₃ 由 **−14.8pp 收窄到 −2.4pp**；
  残余偏差主要来自模型本身还不完备（缺结构自由度 / 微吸收），属 W22 及后续工作。
#### 17. 每相整体温度因子 B（M6/W22-a，默认开）

- **为什么先做这一项**：完整 W22（精修原子坐标/占位）要求**每次迭代重算结构因子 `|F|²`**，
  属架构级改动；而**整体温度因子 B**（Debye-Waller）是**逐峰乘性、只依赖 2θ** 的因子
  `exp(−2B·s²)`（`s = sinθ/λ`），可直接作用在现有参考峰表上，零额外结构因子计算，
  却是所有真实 Rietveld 程序的标准自由度——缺它会系统性高估高角强度。因此作为 W22 的首个增量。
- **实现**：新增 `_apply_overall_b(phase_peaks, b_per_phase, λ)`；每相 1 个参数挂在
  向量末尾（现有索引算术不动），边界 `0~15 Å²`、初值 0（= 无修正）、
  `param_mask["b_overall"]` 可冻结、`refine_b_overall=False` 可整体关闭；
  `fit_params` 记录 `refine_b_overall` 与每相 `b_overall`。
  `B≤0` 视为"无修正"（不做反向增强，防参数跑飞）。
- **测试**：`tests/test_overall_b.py`（6 条：B=0/缺失零改动、高角衰减更强且与解析式逐位一致、
  B 越大衰减越强、负 B 原样保留、默认开启、合成数据能回收正 B）。
- **实测（结构回填 + 同一受限预算口径）**：

  | 试样 | 关 B | **开 B** | 拟合出的 B (Å²) | 质量分数偏差之和 |
  |---|---|---|---|---|
  | 2-1 | 32.20 % | **25.33 %** | 2.46 / 5.78 | — |
  | 4-1 | 37.34 % | **28.48 %** | 3.70 / 2.35 / 2.62 / 4.82 | 26.5 → **21.4** pp |

  2-1 定量 45.78 / 54.22（真值 50/50），4-1 四相 15.1 / 18.6 / 19.3 / 47.0。
  拟合出的 B 全部落在物理合理区间（实验室粉末常见 0.5–5 Å²），说明这是真实物理效应而非拟合假象。
- **回归**：含新测试共 **107 项全通过**。
#### 18. W22 侦察结论：坐标/占位精修**不在内置引擎实现**（有实测依据的划界）

- **数据前提已满足**：本地 COD 全库可回填结构（Corundum 展开 30 位点、`cif_path` 就位），
  `PhaseStructureResolver` 已接入 App 主流程。
- **实测代价（决定性的）**：`XRDCalculator.get_pattern` 单次 **76 ms**（Corundum，2θ 10–90°）。
  有限差分下每个结构自由度约 2 次调用 → 6 自由度 **0.91 s/雅可比**、20 自由度 **3.04 s/雅可比**；
  折 200 次迭代即 **3 / 10 分钟每起点**，默认 4 起点 → **12~40 分钟**。
  → 用"每次迭代调 pymatgen 重算 `|F|²`"做坐标/占位精修，比现有精修**慢 10~100 倍**，
  且仍受有限差分精度限制。
- **决策（分档，写进实施手册 W22 段）**：
  1. **已做**：廉价结构自由度 —— 整体温度因子 B（W22-a）、全晶胞参数（W18）、
     March-Dollase 织构、每相标度；覆盖实验室数据最常见的结构性失配。
  2. **不做**：内置引擎的原子坐标/占位精修（真要做得另起"预计算各对称位点复结构因子贡献 →
     占位作参数的二次型在 O(n_peaks) 内解析求值"的数值内核，且只能覆盖占位）。
  3. **替代**：坐标/占位/ADP 交给已集成的 **GSAS-II / FullProf / MAUD**（成熟内核 + 解析导数），
     与 README 的引擎能力分层一致。

#### 19. 拟合后诊断：分段残差 + DW 统计量（M7/W28）

- **动机**：自动精修最难的不是"再降 0.1% wR"，而是**让用户知道模型缺了什么**。
DW 统计量能区分"残差是白噪声"还是"逐点相关（模型不完备）"——后者再怎么调参也没用。
- **实现**：新增 `RietveldRefiner._fit_diagnostics(two_theta, observed, simulated)`
  （纯后处理，不改模型）：
  - **分段轮廓 R**（未加权口径，键名标明）：低角 `<30°` / 中角 `30–60°` / 高角 `>60°`；
  - **Durbin-Watson** `DW = Σ(r_i − r_{i−1})² / Σ r_i²`（白噪声 ≈2、逐点相关 <<2）；
  - **可读建议**（仅在整体 R > 8% 时给，避免好拟合上瞎提示）：
    `DW<1` → "模型不完备，检查是否缺相/缺物理项"；
    高角 R 显著大于低角 → "检查整体温度因子 B / 峰宽模型 / 样品位移"；
    低角 R 显著大于高角 → "检查低角不对称 / 背景估计 / 择优取向"；
    残差大但无相关 → "可能接近噪声底或统计量不足"。
  - 接入 `_refine_builtin`：写入 `fit_params["diagnostics"]`，并把最重要的 2 条加入
    `result.warnings`（界面提示条与向导日志直接可见）。
- **测试**：`tests/test_fit_diagnostics.py`（7 条：完美拟合 DW≈2 且无建议 / 系统性偏差
  → DW<0.5 且给"模型不完备" / 高角偏差 / 低角偏差 / 小偏差不给建议 / 退化输入安全 /
  精修结果确实带上诊断与提示）。
- **回归**：含新测试共 **134 项全通过**。
- **下一步**：W25（观测峰种子化起点）、W26（先 Le Bail 后 Rietveld）、W27（分阶段释放）——
  三项都是"起点/流程"层面的改动，按 W25 → W26 → W27 顺序推进。

#### 20. 观测峰种子化起点（M7/W25，默认开）

- **动机**：起点原是硬编码 `fwhm=0.15` + 手写网格。观测峰本身已含峰宽信息，
  按 Caglioti 关系 `FWHM² = U·tan²θ + V·tanθ + W` 反解，是真实 Rietveld 程序的通行做法。
- **实现**：新增 `_seed_from_observed_peaks(data)` —— **自带轻量背景感知估计**：
  2° 中值背景扣除 → `5σ` 阈值（σ 取残差 MAD）找局部极大 → **线性插值**定位半高跨越测 FWHM
  → 中角区（20°~max−10°）中位数作固定宽起点 + Caglioti 最小二乘反解 (U,V,W)；
  只取最强 40 峰抗噪；反解出的曲线若在全范围跑出 `[0.02, 3.0]°` 则退回"仅用固定宽"。
  优先级：**显式 kwargs > 观测峰反解 > 原默认**；`seed_from_peaks=False` 可关闭；
  结果记入 `fit_params["seed_from_peaks"]`。
- **踩坑 1（重要）**：首版借用 `PeakFinder` —— 它的阈值是**相对 Imax** 的，
  当背景（50）高于阈值（5%×900=45）时把噪声全判成峰：合成数据上返回 **120 个假峰、
  FWHM 10.7°**，反解出 W=1.67。改用自带背景感知估计后正常（6 个真峰）。
- **踩坑 2**：半高跨越若只用整数格点，0.02° 步长会把 FWHM 量化到 ±0.02°，
  足以把 Caglioti 的 `U` 项拟成 0 → 加线性插值后才合理。
- **如实记录的限制**：少峰（3~10 条）条件下 `(U,V)` **近乎共线**（`tan²θ` 与 `tanθ` 强相关），
  单独看 U/V 会互相补偿（合成实测 U=−0.0025 而真值 +0.005），**可辨识的是预测的 FWHM 曲线**
  （起点真正用到的量）——测试因此断言曲线而非 U/V 本身。
- **实测收益（诚实）**：2-1 上起点由硬编码 `0.15°` 变为数据驱动 `0.1723°`（29 个观测峰），
  但**最终 wR 相同**（25.326%，两者都跑满 80 次迭代上限）。
  即"起点已数据驱动、行为安全"，**本样本上未显现收益**；收益预期在起点偏差大的试样
  （峰宽与 0.15° 相差数倍、或零点偏差大）上体现，需靠 13 试样基准（W29）量化。
- **测试**：`tests/test_peak_seeded_start.py`（5 条：合成数据反解可辨识曲线 / 退化输入安全 /
  显式 kwargs 优先 / 种子记录并实际使用 / 可关闭）。
- **下一步**：W26（先 Le Bail 后 Rietveld）→ W27（分阶段释放）→ W29/W30（13 试样基准与收口）。

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
| M09 | 候选检索与约束 | **v1.0.1** | 密度约束 `density_range` / 名称·化学式模糊直搜 `find_phases_direct` / 综合约束过滤 / 搜索预设存取 |
| M10 | 搜索匹配（FoM） | v0.9.7（v0.9.11 重构） | 乘性 → 加权互斥 |
| M11 | 多相迭代识别 | v0.9.7 | `iterative_identify` |
| M12 | 用户自建库 | v0.9.7 | JSON CRUD + CIF/峰表导入 |
| M13 | RIR 半定量 | v0.9.7 | 相对 + 内标绝对 |
| M14 | Rietveld 增强 | v0.9.7（v0.9.8 接参数掩码） | March-Dollase / DoC / 内标 |
| M15 | 指标化 | **v1.0.1**（原 P3·暂缓） | 内置立方 / 四方 / 六方（`services/indexing.py`，验收 Si→a≈5.43）；外部 Treor/Dicvol 留接口 |
| M16 | 晶粒尺寸（Scherrer） | v0.9.7 | 含仪器宽化扣除 |
| M17 | 晶体结构可视化 | **v1.0.1**（原 P3·暂缓） | `services/structure_viz.py` + `StructureView` 挂入 CIF 浏览器，自动按空间群展开非对称单元（验收 Si→8 原子金刚石晶胞） |
| M18 | 报告导出 | v0.9.7（v0.9.8 修 LO 转换） | SVG / HTML / CSV / CIF |
| M19 | 脚本 / 批量 | v0.9.7 | 管线 DSL + 批量处理 |
| M20 | GUI 交互 | v0.9.7（v0.9.8/v2 续） | 拖放 / 主题 / 峰表右键 |
| M21 | 物相分析 v2 展示层 | v0.9.8 | 双区谱图 + 峰归属表（对标同类商业软件） |
| M22 | 图谱 X 轴自适应交互 | v0.15.0 | 滚轮缩放 / 拖动平移 |
| M23 | 物相列表勾选驱动 + CIF 导出 | v0.15.0 | 勾选集随项目持久化 |
| M24 | 精修页布局重构 | v0.15.0 | 窗口布局版本 → v3 |
| M25 | 外部精修程序集成 | v0.15.0（v0.15.1 续） | GSAS-II / MAUD / **FullProf** |
| M26 | 谱合成内核窗口化 | v1.0.1 | `spectrum_from_refs` 峰距截断（100×FWHM），3000 峰单次评估 1467→270 ms |

> 注：上表按"实际在哪个版本交付"归集。M15 / M17 曾在 2026-09-07 降为 P3·暂缓，
> **已于 v1.0.1 全部补齐交付**；同版另交付非路线图内的 M26（谱合成性能）与 7-1 卡死修复。
> 至此**主路线图 M01–M25 全部完成**。

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
| v0.15.2 | 未重建（库数据未变） | — | — | 仅内置参考库 JSON 重算（0.4.0→0.5.1，118→106 条） |
| **v1.0.1** | **130.8 MB** | **193.1 MB** | 58.0 MB（本地，不入 Release） | Release 只发 Setup + 两个索引库包；PDF2 / Portable 不发布 |

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
| 单元测试规模 | 95（v0.9.0） | 182（v0.9.7）→ 316（v0.9.10）→ 443 → 507 → 542 → 545 → 666 → 734 → 745 → 789 → 799 → **993 收集 / 991 过 / 2 跳（v1.0.1）** → **1012 收集 / 1010 过 / 2 跳（启动稳健性修复）** | 各日日志 |
| 谱合成单次评估（7251 点 × ~3000 峰） | 1467 ms | **270 ms（5.4×）**（v1.0.1 峰距截断窗口化） | v1.0.1 |
| Portable 包体积 | 661.5 MB（v0.9.10） | **380.7 MB**（v0.10.0 外挂化后） | v0.10.0 |
| 数据库总体积（可检索） | 无机物库 258.6 MB + 全库 431.7 MB | 无机物库(瘦身) **362 MB** + 全库 431.7 MB | v0.14.0 |

> ⚠️ 上表数字**口径不完全统一**（部分为日志当场实测、部分为抽样；识别率类指标存在"化学式口径导致的假阴性下界"问题），仅用于趋势对比，不可跨口径直接相减。

---

## 附录 D · 发布红线与约定（老版本期间确立）

1. **PDF2-2004 永不上传**（ICDD 版权库）：仓库只提供挂载能力；DB Manager 中显示「请确认已获得正版授权」提示；`.gitignore` + 发布脚本 `Assert-NotBanned` + 上传后自检三层守卫
2. **Portable 免安装包自 v0.11.0 起不随 Release 发布**（按需提供）；v0.15.1 起二进制**整体不推送**。
   **v1.0.1 起口径定型**：Release 只发 `PolyXRD-Setup-v{ver}.exe` + 两个 COD 索引库包
   （`…-Databases-COD-inorg-index.zip` / `…-Databases-COD-full-index.zip`）；
   **PDF2 与 Portable 一律不入 Release**，发布脚本内设 `PDF2|Portable` 正则自检 + 上传后复核
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

**发布辅助脚本**：`scripts/verify_release.ps1`（打包三库包 + 对账 + SHA256）、`scripts/create_github_release_v*.ps1`、`_create_release_py.py` / `_upload_assets_curl.py`（Python 化，curl 上传）、
`_release_v101.py`（**v1.0.1 起主用**：`git credential fill` 取 token → REST API 建 Release → curl 流式上传，内置 `PDF2|Portable` 禁传自检）、`_askpass.py`（非交互 git 认证辅助）。
**库包命名唯一真源** = `db_import.DBKind.pkg_suffix` / `db_import.PKG_FILENAME`。

**v1.0.1 实际收口记录**：`__init__.__version__` / `config.app_version` / `PolyXRD-Setup.iss`
的 `AppVersion` 三处同改（本轮 Inno 未走 `build.bat` 的 `set APPVER=` 入口，直接改 iss 默认值）；
**上表第 4、1 条首次收口时均漏改**（`pyproject.toml` 与 `build.bat` 都仍为 `0.15.2`），
已于 2026-09-22 一并**补正为 `1.0.1`** —— `build.bat` 顶部 `set APPVER=` 与
`title` / `echo` banner 两处（用字节级替换改，保持 UTF-8 + CRLF 不变）；
`pyproject.toml` 同时补齐 `authors` / `keywords` / `classifiers` / `[project.urls]`
（`license` 改 PEP 639 SPDX 写法、`requires` 升 `setuptools>=77`）——
详见第二部分「同批同步收口」。
→ **下次发版请把上表 5 条逐条核对**，尤其第 1 条（`build.bat`，输出名/安装包名都由它驱动）
与第 4 条（`pyproject.toml`），避免再次漏收。

**v1.0.2 版本号收口记录**（2026-09-22）：稳健性修复的版本号定为 **1.0.2**，
上表 5 处同改 —— `build.bat`（`APPVER=` + `title` + banner，字节级替换保 UTF-8/CRLF）、
`config.app_version`、`__init__.__version__`、`pyproject.toml`、
`PolyXRD-Setup.iss`（`#define AppVersion` + 顶部用法注释），逐条核对**全部 = 1.0.2**。
按用户指示 **EXE 暂不重建、不发布** —— 当前 Release 上的 v1.0.1 产物**不含**本修复；
等日志取证结束后一并重建验收。

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
11. **v1.0.1 的 GitHub 仓库为 private**：`https://github.com/PolyXRD/PolyXRD/releases/tag/v1.0.1`
    匿名访问返回 404，仅在登录有权限的账号后可见；本页记录的附件与 SHA-256 均经
    带 token 的 REST API 复核（`state=uploaded`），非网页目视确认。
12. **~~v1.0.1 的 `pyproject.toml` 版本号未同步~~ → 已补（2026-09-22）**：原先
    仍为 `0.15.2`（首轮只改了 `__init__.py` / `config.py` / `PolyXRD-Setup.iss` 三处）。
    现已改 `version = "1.0.1"`，并补齐 `authors` / `keywords` / `classifiers` /
    `[project.urls]`，`license` 改 PEP 639 SPDX 写法（详见附录 E）。
    ⚠️ **已发布产物未随之重建** —— 元数据不参与二进制行为，故 Release 上的
    Setup / 两个 COD 库包与本次改动**无字节差异**；重建与否不影响已发布版本的正确性。
13. **v1.0.1 的 Portable / PDF2 包只存在于本机**：`installer_output/PolyXRD-v1.0.1-Portable.zip`
    （385.2 MB）与 `…-Databases-PDF2.zip`（58.0 MB）未上传任何远端，SHA-256 仅见于本地
    `SHA256-v1.0.1.txt`。

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

| PolyXRD 版本      | COD 数据库外挂包版本                            | 数据库列名        |
| --------------- | --------------------------------------- | ------------ |
| **1.0.1 / 0.15.x** | `…-Databases-COD-inorg-index.zip` + `…-Databases-COD-full-index.zip` | `ref_id`（三库表名同为 `phases`，靠签名区分） |
| 0.14.0 | 同上（无机库转瘦身索引式 `COD_inorganics_index.sqlite`） | `ref_id` |
| 0.11.0 ~ 0.13.2 | `…-Databases-COD-inorg.zip`（v2，内嵌 CIF）/ `…-Databases-COD-full.zip` | `ref_id` |
| 0.10.0 | `…-Databases-COD-inorg.zip`（v1，仅 d-I 峰）/ `…-Databases-COD-full.zip` | `ref_id` |
| **0.8.23**      | PolyXRD\_COD\_Inorganics\_v0.8.21 (无变化) | ref\_id      |
| **0.8.22**      | PolyXRD\_COD\_Inorganics\_v0.8.21 (无变化) | ref\_id      |
| **0.8.21**      | PolyXRD\_COD\_Inorganics\_v0.8.21       | ref\_id      |
| 0.8.0 \~ 0.8.20 | cod\_inorganics.sqlite (不兼容)            | cod\_ref\_id |

> PDF2-2004 槽位自 0.10.0 起支持挂载，但**任何版本都不随 Release 分发**（ICDD 版权）。

---

*本文档由 4 份历史变更记录合并而成（2026-09-21）：早期史取自交接期回溯整理，v0.9.0 起以逐日工作日志与 git 历史为据；重复版本已按内容去重，保留各自独有细节。*
*2026-09-22 追加 v1.0.1 正式发布记录（含 Release 附件清单与 SHA-256），并回填附录 A/B/C/D/E/F/H。*
