# PolyXRD 版本更新日志 (CHANGELOG)

> 项目地址: https://github.com/PolyXRD/PolyXRD (Private)
> 文档维护: PolyXRD Team
> 起始版本: V0.3.0 (最初原型)
> 当前版本: V0.8.23

---

## [0.8.23] — 2026-08-21

### 新增
- **MCP Server (Model Context Protocol)**: 新增 `src/polyxrd/mcp_server/` 包，将 PolyXRD 的完整 XRD 分析流水线通过 MCP 协议暴露给 AI 大模型 (Claude / GPT / TraeCode 等)，无需 GUI 即可调用
  - `server.py`: 注册 **18 个 MCP Tools**，覆盖全流水线
  - `session.py`: 跨工具调用的会话状态管理 (XRDData / PeakList / Phase / RefinementResult)
  - `__main__.py`: 支持 `python -m polyxrd.mcp_server` 启动 (stdio 传输)
- MCP Tools 清单:
  | 类别 | 工具 | 功能 |
  |---|---|---|
  | 数据加载 | `load_xrd_data`, `get_data_summary` | 加载 .xrdml/.xy/.csv/.txt/.raw + 摘要 |
  | 预处理 | `preprocess_data` | SNIP/ALS 背景 + SG 平滑 + Kα2 剥离 + 归一化 |
  | 峰分析 | `find_peaks`, `list_peaks`, `fit_peaks` | 检测 + 列表 + 拟合 (Voigt/Gaussian/Lorentzian) |
  | 物相检索 | `search_phases` | 内置参考库 + 元素过滤 |
  | COD 数据库 | `search_cod_phases`, `search_cod_by_d_peaks`, `get_cod_phase_details`, `search_cod_online` | 化学式/空间群/d值峰搜索 + 详情 + 在线搜索 |
  | 模拟 | `simulate_pattern` | 从 CIF 文件生成理论 XRD 图谱 |
  | Rietveld | `refine_rietveld` | GSAS-II / powerxrd / 内置引擎 |
  | 导出 | `export_results`, `save_project`, `load_project` | JSON/TXT/CSV + .pxrd 项目 |
  | 会话 | `get_session_status`, `reset_session` | 状态查看 + 重置 |

### 变更
- `config.py`: app_version 0.8.22 → 0.8.23
- `PolyXRD.spec`: 添加 `mcp` 到 PyInstaller 依赖收集列表
- `scripts/PolyXRD-Setup.iss`: 版本号 0.8.23

### 测试
- E2E 测试通过: SiO2 石英样品 (加载 116 点 → SNIP 背景 → SG 平滑 → 6 峰检测 → COD d 值搜索 5 匹配)
- 安装包: `PolyXRD-Setup-v0.8.23.exe` (247.9 MB)

---

## [0.8.22] — 2026-08-21

### 新增
- **品牌视觉升级**: 基于 `brand_assets/polyxrd-brand-assets/assets/icon.jpg` 和 `logo.jpg` 重新生成全尺寸图标和 Logo
  - 应用图标: 16/24/32/48/64/128/256/512/1024 px PNG + 多尺寸 ICO (16/32/48/64/128/256)
  - 品牌 Logo: 256x144 / 512x288 / 1024x576 / 2048x1152 PNG
  - `src/polyxrd/resources/` 下 4 个运行时图标已替换 (app-icon.ico / app-icon.png / crystal-mark.png / logo-horizontal.png)
- **Inno Setup 安装向导背景**: 新增 `wizard_image.bmp` (640x480) + `wizard_small_image.bmp` (563x75)，深色品牌背景 + Logo
- README.md 开源致谢新增 **GSAS-II** (Rietveld 结构精修主引擎)

### 变更
- `config.py`: app_version 0.8.21 → 0.8.22
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

---

## [0.8.21] — 2026-08-21

### 重大变更 — 首次正式发布

#### 1. 程序与数据库分离发布架构
- PolyXRD 主程序作为标准 Windows 安装包发布 (Inno Setup 6.7.3, LZMA2/ultra64)
- COD 无机物库作为独立外挂 zip 包发布 (91.9 MB, 解压 258.6 MB)
- 两者完全独立分发、独立升级，避免单包体积超 1 GB
- 数据库路径三重优先级: **用户导入路径 > %LOCALAPPDATA%\PolyXRD\databases\ > 程序内置 cod_data/**

#### 2. 数据库导入接口
- 新增菜单: `文件 → 导入外部数据库 → COD 无机物库`
- `AppConfig` 新增 `set_cod_db_path()` / `get_cod_db_path()` 方法，持久化到 `~/.polyxrd/user_db_paths.json`
- `CIFDatabase` 新增 `set_cod_db_path()` + `reload_cod_db()` 支持运行时热切换数据库
- 导入后自动加载，重启无需重复操作

#### 3. 品牌合规 — 全局清除第三方商标字样
- 数据库文件: `match_inorganics.sqlite` → `COD_inorganics.sqlite`
- 数据库列名: `match_ref_id` → `ref_id`
- 目录名: `cod_data/match_inorganics/` → `cod_data/cod_source/`
- Config 属性: `match_db_path` → `cod_db_path`
- CIFDatabase 方法: `search_match_phases` → `search_cod_phases` 等 10+ 方法
- i18n key: `import_match_db` → `import_cod_db` 等
- 脚本文件名: 9 个 `match_*.py` → `cod_*.py` (build_cod_sqlite.py / package_cod_db.py 等)
- PowerShell 脚本: `start_match_download.ps1` → `start_cod_download.ps1`
- 全项目 Grep 确认: 0 处禁用字样残留

#### 4. 数据库重命名与迁移
- 数据库: COD 无机物库 20260821 版本，**71,199 物相**，全部含 d-I 峰 / 晶胞参数 / 分子式 / 矿物名
- 字段完整性: formula/n_peaks/d-I 峰 100%, space_group 99.99%, 晶胞参数 99.97%+
- 编号格式: `97-xxxxxxx` (后 7 位为 COD 真实 ID), `ref_id` 保留 `96-XXX-YYYY` 格式

#### 5. 打包与发布
- PyInstaller (onedir 模式) + Inno Setup 6.7.3 双层打包
- `PolyXRD-Setup-v0.8.21.exe` (240.9 MB, 解压 955 MB)
- `PolyXRD_COD_Inorganics_v0.8.21.zip` (91.9 MB)
- GitHub 私有仓库创建: https://github.com/PolyXRD/PolyXRD
- 首次 Release v0.8.21: 源码 + 安装包 + 数据库外挂包 + 发布说明

### 新增功能 (相比 V0.8.20 及更早版本)
- 数据库动态路径配置与持久化
- 外部数据库导入 UI 入口
- 数据库一键安装脚本 (`install_COD_database.bat`)
- `.gitignore` 排除规则 (brand_assets / cod_cif_download / test_data / tests / release)

### 功能清单 (V0.8.21 完整能力)

#### XRD 数据处理
| 模块 | 功能 |
|---|---|
| 数据加载 | `.xrdml` (PANalytical), `.raw` (Bruker), `.txt/.csv`, `.prf` (GSAS), 批量合并 |
| 波长支持 | Cu/Mo/Co/Cr/Fe/Ag/W/Au/Ga/Mn/Ni Kα |
| 背景扣除 | SNIP (4 策略), Sonneveld-Visser, Polynomial (2~10 阶), DWT |
| 平滑 | Savitzky-Golay (5~31 窗口, 2~5 阶), FFT 低通, Whittaker-Eilers |
| 归一化 | Max / Sum / AUC |
| Kα2 剥离 | Rachinger / pseudo-Voigt |
| 峰搜索 | Repeated 2nd Derivative / Pseudo-Voigt 拟合, 自动阈值 (SNR≥2) |
| 峰拟合 | Pseudo-Voigt / Pearson VII / Split-PV, LMFit 解算器 |

#### 物相分析
| 模块 | 功能 |
|---|---|
| 多物相定性检索 | d-I 峰匹配 + 化学式过滤 + 元素过滤 + 矿物名关键词, Top-N 打分 |
| 元素过滤器 | 周期表式 Must-have / Not-allowed 选择 |
| COD 数据库接口 | `search_cod_phases()` / `search_cod_by_d_peaks()` / `get_cod_phase()` |
| 多物相联合拟合 | 残差剥离法 + 主峰匹配 + 强度加权召回率 |
| d 峰排序算法 | top_precision → top_recall → meas_ratio (修复了早期 dense phase 偏好问题) |

#### 晶相与晶体学
| 模块 | 功能 |
|---|---|
| Rietveld 结构精修 | GSAS-II / powerxrd / 内置引擎, 顺序/自动/手动策略 |
| Le Bail 晶胞精修 | 固定晶相精修 a/b/c/α/β/γ |
| 结构模拟 | 空间群/原子占位 → XRD 图谱 (Lorentz-Polarization + B 因子) |
| 指标化 | d 值反解 hkl, 2θ 误差计算 |
| 空间群处理 | pymatgen / spglib, 230 种空间群标准化 |

#### 界面与多语言
| 模块 | 功能 |
|---|---|
| 主窗口 | PySide6 + PyQtGraph 双画布 (主图 + 残差图), 可停靠多面板 |
| 语言 | 简体中文 / English / 日本語 (120+ 条翻译, 切换无需重启) |
| 主题 | 白天 / 深色模式, Qt Fusion 风格 |
| 元素周期表 | 交互式 118 种元素选择器 |
| 高 DPI | HiDPI 适配, 4K 屏幕比例正确 |

### 测试结果
| 类别 | 结果 | 备注 |
|---|---|---|
| 单元测试 (pytest) | 50/55 PASS (90.9%) | 5 项失败为历史遗留, 非 V0.8.21 引入 |
| 数据管线 (加载/扣背景/平滑/峰检) | 34/34 PASS (100%) | |
| 数据库导入 E2E | 6/6 PASS (100%) | |
| CIFDatabase API | 全部 5 项 OK | |
| 多物相分析实际样品 | 9/12 (75%) | 样品 2-2 (100%), 5-1 (100%), 5-2 (40%) |
| 品牌合规性 | 0 处残留 | 全项目 110+ 文件 Grep 通过 |

### 已知问题
1. 多物相排序: 5 相以上峰强重叠样品, 弱相 (<5%) 可能排序靠后
2. 首次冷启动: 3~8 秒 (pymatgen / matplotlib 初始化)
3. 仅 Windows 10/11 x64

---

## [0.8.0 ~ 0.8.20] — 早期迭代版本 (2026 年初 ~ 2026-08)

> 注: 这些版本在 V0.8.21 发布前使用 `match_inorganics.sqlite` 数据库, 未做公开 Release。

### 核心功能开发
- XRD 数据加载器 (DataLoader): 支持 .xrdml / .raw / .txt / .csv / .prf
- 数据预处理流水线 (DataPreprocessor): SNIP / ALS / Polynomial / DWT 背景扣除, SG / FFT / Whittaker 平滑
- 峰检测 (PeakFinder): 二阶导数 + 自动阈值
- 峰拟合 (PeakFitter): Pseudo-Voigt / Pearson VII / Split-PV, LMFit
- 物相识别 (PhaseIdentifier): d-I 峰匹配 + 元素过滤 + 残差剥离法
- COD 数据库 (CIFDatabase): 从 COD 私有二进制 (user_database.mtu) 逆向生成 SQLite, 71,199 物相
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

---

## [0.6.0] — 2026-08-18 (首次打包发布)

> 源码来源: `D:\TraeSolo\PolyXRD_v0.6.0_Source.zip` (0.8 MB)

### 功能
- 基础 XRD 数据加载与显示
- 工具栏左对齐布局 + 文字标签
- 菜单栏文字标签显示
- 元素周期表弹出对话框过滤
- Profile Fitting 峰形拟合物相分析（无需寻峰）
- 传统 Search/Match (FOM) 物相识别
- 物相匹配可视化 (已匹配/未匹配峰标注)
- 物相确认自动切换结构精修
- 多语言支持 (中/英/日)
- 修正 Windows EXE 图标显示

### 技术架构
- 参考数据库: `xrd_reference_database.json` (2.7 MB, **仅 118 个 XRD 参考物相**)
- MVVM 架构: models / viewmodels / views / services / utils
- 完整 services 层: cif_database / cod_searcher / data_loader / data_preprocessor / data_processor / export_service / peak_finder / peak_fitter / phase_identifier / profile_fitting / project_service / refinement_templates / rietveld_refiner / structure_simulator
- views 层: main_window (54 KB) / data_view / phase_view / refinement_view / refinement_wizard (36 KB) / report_view
- widgets: element_filter_dialog / element_periodic_table / peak_table / plot_widget
- 单元测试: 8 个测试文件 (test_config / test_data_loader / test_math_utils / test_peak_finder / test_phase_identifier / test_preprocessor / test_rietveld / test_xrd_data)

### 限制
- 参考数据库仅 118 个物相 (JSON 格式), 覆盖范围有限
- 无 COD 无机物 SQLite 数据库
- 无数据库导入接口
- 无程序/数据库分离发布

---

## [原型 / Pre-0.6.0] — 2026-08-12 ~ 2026-08-13 (WorkBuddy 早期架构)

> 源码位置: `D:\WorkBuddy\XRD\polyxrd`
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
  - `analysis/`: peak_detection, peak_fitting, phase_matching, quantitative, theoretical_pattern
  - `database/`: cache, cod_client, cod_database, local_cif_library, mp_database, reference_pattern_library
  - `engines/`: gsas2_engine, pymatgen_engine
  - `io/`: cif_io, exporters, project_io + data_readers (base/csv/raw/txt/udf/xrdml/xy)
  - `models/`: crystal_structure, diffraction_pattern, match_result, peak, peak_list, phase, project_state, refinement_parameters, refinement_project, refinement_result
  - `processing/`: background, calibration, ka2_stripping, normalization, smoothing
  - `project/`: batch_processor, command, history, project_manager
  - `reporting/`: excel_report, figure_factory, pdf_report
- gui 层模块:
  - `controllers/`: main_controller, refinement_controller
  - `dialogs/`: batch_wizard, import_dialog, refinement_panel, settings_dialog
  - `widgets/`: log_panel, navigation_tree, peak_table, plot_widget, property_panel, status_bar
  - `wizards/`: phase_analysis_wizard, refinement_strategy_wizard
  - `styles/`: themes
- i18n: en_US.json (7.9 KB) + zh_CN.json (7.7 KB)
- 品牌资源: logo / crystal-mark / hero-banner / splash-screen / social-cover (SVG + JPG)
- 安装器: Inno Setup (.iss) + NSIS (.nsi) 双格式

### 测试结果
- 69 个单元测试, **全部通过** (Python 3.13.14, pytest 9.1.1)
  - processing: 26 tests (background 7 / calibration 5 / ka2_stripping 4 / normalization 4 / smoothing 7)
  - analysis: 22 tests (peak_detection 5 / peak_fitting 4 / phase_matching 4 / quantitative 5 / theoretical_pattern 4)
  - engines: 9 tests (cod_client 4 / gsas2_engine 3 / mp_database 2)
  - database: 11 tests (cache 6 / cod_database 2 / local_cif_library 3)
  - project: 1 test (command_history)

### 验证报告 (T047-T048)
- SMZ 系列物相鉴定: **全部样本通过**
- 钨系列 (蓝钨/黄钨/紫钨): **通过** (WO2.72/WO2.9 FOM 0.58-0.60, 采用钨族专用阈值 0.25)
- 低丰度/痕量相 (3-1 中 5% Al2O3 / 1.4% CaF2) 已标注为"低于峰检极限 / 需 Rietveld 定量"

### 与后续版本的关系
- 此原型的 core/gui 架构在 V0.6.0 被完全重构为 models/services/views/viewmodels MVVM 架构
- 参考物相库从 30 种矿物扩展到 118 种 (V0.6.0), 再到 71,199 物相 COD SQLite (V0.8.0+)
- data_readers 设计被保留并沿用至今
- Python 版本从 3.13 降至 3.10 (V0.6.0+), 以获得更好的 PyInstaller 兼容性

---

## [0.4.1] — 早期开发版本

> 从 V0.6.0 源码包中 `config.py` 的 `app_version` 发现。

### 功能
- 应用版本号定义为 0.4.1
- 基本配置框架: 窗口尺寸 / 默认波长 (Cu Kα1 1.5406) / 2θ 范围 / d 值范围
- 支持文件格式: .xy / .dat / .csv / .txt / .xrdml / .xml / .raw / .brml
- Rietveld 精修参数: sequential 策略 / max_cycles=20 / tolerance=0.0001
- 默认 2θ 范围: 5° ~ 80°

---

## [0.3.0] — 最初原型版本

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

---

## 开源致谢

| 项目 | 用途 | 许可证 |
|---|---|---|
| [Python 3.10](https://www.python.org/) | 运行时 | PSF |
| [PySide6 (Qt6)](https://wiki.qt.io/Qt_for_Python) | GUI 框架 | LGPL v3 / GPL v2 |
| [PyInstaller](https://pyinstaller.org/) | 二进制打包 | GPL v2 |
| [Inno Setup 6.7](https://jrsoftware.org/isinfo.php) | Windows 安装器 | Inno Setup License |
| [pymatgen](https://pymatgen.org/) | 晶体学/物相分析 | MIT |
| [spglib](https://spglib.github.io/spglib/) | 空间群标准化 | BSD-3 |
| [scipy](https://scipy.org/) | 数值算法 | BSD-3 |
| [numpy](https://numpy.org/) | 多维数组 | BSD-3 |
| [pandas](https://pandas.pydata.org/) | 表格数据 | BSD-3 |
| [matplotlib](https://matplotlib.org/) | 2D 绘图 | PSF-based |
| [pyqtgraph](https://www.pyqtgraph.org/) | 交互式 XRD 主图 | MIT |
| [LMFIT](https://lmfit.github.io/lmfit-py/) | 非线性最小二乘 | BSD-3 |
| [GSAS-II](https://gsas-ii.net/) | Rietveld 结构精修引擎 | Free for academic |
| [powerxrd](https://github.com/andrewrgarcia/powerxrd/) | XRD 峰形模型 | MIT |
| [platformdirs](https://github.com/platformdirs/platformdirs) | 跨平台用户路径 | MIT |
| [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) | AI 模型接口协议 | MIT |
| [Crystallography Open Database](https://www.crystallography.net/cod/) | 71,199 无机物相数据 | CC BY / Public Domain |

---

## 版本兼容性矩阵

| PolyXRD 版本 | COD 数据库外挂包版本 | 数据库列名 |
|---|---|---|
| **0.8.23** | PolyXRD_COD_Inorganics_v0.8.21 (无变化) | ref_id |
| **0.8.22** | PolyXRD_COD_Inorganics_v0.8.21 (无变化) | ref_id |
| **0.8.21** | PolyXRD_COD_Inorganics_v0.8.21 | ref_id |
| 0.8.0 ~ 0.8.20 | match_inorganics.sqlite (不兼容) | match_ref_id |

---

*本文档最后更新: 2026-09-21 · PolyXRD Team*
