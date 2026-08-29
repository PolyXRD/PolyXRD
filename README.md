<div align="center">
  <img src="src/polyxrd/resources/app-icon.png" alt="PolyXRD Logo" width="120" />
  <h1>PolyXRD</h1>
  <p>
    <b>多晶 X 射线衍射 (XRD) 图谱综合分析套件</b>
    <br />
    峰检测 &nbsp;·&nbsp; 多物相定性检索 &nbsp;·&nbsp; Rietveld 结构精修 &nbsp;·&nbsp; Le Bail 晶胞精修 &nbsp;·&nbsp; 全谱拟合 &nbsp;·&nbsp; 双 COD 数据库接入
  </p>
  <p>
    <a href="https://github.com/PolyXRD/PolyXRD/releases/tag/v0.9.0"><img src="https://img.shields.io/badge/Release-v0.9.0-blue?style=flat-square" /></a>
    &nbsp;
    <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-lightgrey?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Python-3.10-yellow?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/UI-PySide6%20(Qt6)-41cd52?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Tests-95%2F95%20%E2%88%9A-brightgreen?style=flat-square" />
  </p>
</div>

---

## 📖 项目说明

**PolyXRD** 是一个面向材料学 / 化学 / 晶体学研究者的 **多晶 X 射线衍射 (XRD) 图谱综合分析桌面软件**。它把"**加载原始 XRD 数据 → 预处理 → 峰检测 → 多物相定性检索 → Rietveld 结构精修 → 晶胞精修 → 全谱拟合 → 出报告**"整条工作流集成在一个统一的、带 **中文/英文/日文** 三语言界面的 PySide6 (Qt6) 桌面应用里。

核心设计哲学：
- **无需 Python 环境** — 一键安装包 (`PolyXRD-Setup-v0.9.0.exe`) 内置完整 Python 3.10 + PySide6 + pymatgen + scipy，目标机器开箱即用。
- **程序与数据库分离发布** — 主程序安装包独立 (~240MB)；双 COD 数据库按需外挂：**COD 无机物库 (71,199 物相, ≈92 MB zip)** 与 **COD 全库 (113,223 条目, ≈160 MB zip)**，支持运行时热切换 (`set_cod_db_path` + `reload_cod_db`)。
- **算法可控 + 结果可复现** — 预处理/拟合的每一步参数可保存、可回放，项目文件 (`.polyxrd` JSON) 全序列化。

---

## ✨ 功能清单

### ① 数据处理流水线
| 功能 | 说明 |
|---|---|
| 数据加载 | `.xrdml` (PANalytical), `.raw` (Bruker), `.txt/.csv`, `.prf` (GSAS), 批量合并 |
| 波长 | Cu Kα 默认 / Mo Co Cr Fe Ag W Au Ga Mn Ni Kα 可选 |
| 背景扣除 | SNIP (4 种) / Sonneveld-Visser / Polynomial (2-10 阶) / DWT 小波 |
| 平滑 | Savitzky-Golay / FFT 低通 / Whittaker-Eilers |
| Kα2 剥离 | Rachinger / pseudo-Voigt |
| 峰搜索 | 2 阶导数 + PV 拟合, SNR ≥ 2 自动阈值 |
| 峰拟合 | Pseudo-Voigt / Pearson VII / Split-PV, LMFit 解算器, RWP & χ² |

### ② 物相分析
- 多物相定性检索：**d-I 峰匹配 + 化学式过滤 + 元素过滤 + 矿物关键词** → Top-N 候选
- 交互式元素过滤器（118 种元素周期表选择器）
- 多物相联合拟合：生成计算谱 → 与实验谱最小二乘 → 各相 **质量分数 (%)**

### ③ 晶相与晶体学
- **Rietveld 结构精修**：基于 COD 数据库 CIF 文件（原子占位 / 空间群 / 晶胞参数），支持 GSAS-II / powerxrd / 内置引擎，顺序/自动/手动三种精修策略，全谱拟合原子坐标与热参数
- **Le Bail 晶胞参数精修**：仅精修 a/b/c/α/β/γ，无需原子占位，适用于未知结构的晶胞测定
- 结构模拟：从空间群/原子占位 → 计算 XRD 图谱 (Lorentz-Polarization 校正 + B 因子)
- hkl 指标化 (d→hkl)，230 种空间群标准化 (spglib)

### ④ 项目 & 报告
- `.polyxrd` 项目保存/打开/另存为（JSON 格式参数 + 图谱全归档）
- 导出：峰列表 CSV / PNG+SVG 图像 / 多物相报告 PDF / 批量报告

### ⑤ 界面 & 多语言
- PySide6 (Qt6) + PyQtGraph 双画布（主图 + 残差图），支持可停靠面板
- **简体中文 / English / 日本語** 三语言切换（120+ 条翻译，切换无需重启）
- 白天/深色主题，Fusion 风格，HiDPI 适配
- 交互式元素周期表（双击选择，带原子量与特征波长）

### ⑥ COD 无机物库服务
- **独立外挂包发布**：71,199 无机物相，含 **d-I 峰、晶胞参数、分子式、矿物名**
- 线程安全的 SQLite 只读连接，支持运行时**热切换**数据库（`set_cod_db_path` + `reload_cod_db`）
- 三重路径优先级：**用户导入持久化路径 > %LOCALAPPDATA%/PolyXRD/databases > 程序内置 cod_data/**

---

## 🏗️ 代码结构

```
PolyXRD/
├── src/polyxrd/                # 主源代码 (分层包架构)
│   ├── main.py                 # 程序入口 (PySide6 QApplication)
│   ├── config.py               # AppConfig: 版本/路径/UI 语言持久化
│   ├── appstate.py             # 全局状态 (当前项目/图谱)
│   ├── i18n/                   # 多语言翻译 (zh_CN / en_US / ja_JP)
│   ├── resources/              # 图标 / 周期表数据 / 样式表
│   ├── models/                 # 数据模型
│   │   ├── xrd_data.py           # XRD 图谱数据模型
│   │   ├── phase.py              # 物相模型 (含晶胞参数)
│   │   ├── peak.py               # 峰模型
│   │   └── refinement.py         # Rietveld 精修结果模型
│   ├── viewmodels/             # MVVM 视图模型层
│   │   ├── main_vm.py            # 主窗口视图模型
│   │   ├── data_vm.py            # 数据视图模型
│   │   ├── phase_vm.py           # 物相检索视图模型
│   │   └── refinement_vm.py      # ★ Rietveld 精修视图模型
│   ├── utils/                  # 工具函数
│   │   ├── resources.py          # 资源路径解析
│   │   ├── formula_parser.py     # 化学式解析
│   │   ├── math_utils.py         # 数学工具
│   │   └── validators.py         # 输入校验
│   ├── services/               # 核心算法服务 (无 UI, 可独立单元测试)
│   │   ├── data_loader.py          # 多格式 XRD 加载 (xrdml/raw/txt/csv/prf)
│   │   ├── data_preprocessor.py    # 背景扣除 / 平滑 / Kα2 剥离
│   │   ├── peak_finder.py          # 峰检测 (2 阶导数 + 自动阈值)
│   │   ├── peak_fitter.py          # 峰拟合 (PV/PVII/Split-PV, LMFit)
│   │   ├── phase_identifier.py     # 多物相检索 + 联合拟合
│   │   ├── cod_searcher.py         # COD 在线检索 + CIF 抓取
│   │   ├── cif_database.py         # COD 无机物库 SQLite 服务 (71,199 物相)
│   │   ├── rietveld_refiner.py     # ★ Rietveld 结构精修 (GSAS-II / powerxrd / 内置)
│   │   ├── refinement_templates.py # Rietveld 精修预设模板管理
│   │   ├── profile_fitting.py      # 全谱拟合 (PV/PVII)
│   │   ├── structure_simulator.py  # 计算 XRD 图谱 (Lorentz-Polarization + B 因子)
│   │   ├── project_service.py      # .polyxrd 项目读写
│   │   └── export_service.py       # CSV/PNG/SVG/PDF 报告导出
│   └── views/                  # UI 视图层 (PySide6)
│       ├── main_window.py          # 主窗口 / 菜单 / 工具栏
│       ├── data_view.py            # 数据视图
│       ├── phase_view.py           # 物相检索视图
│       ├── refinement_view.py      # ★ Rietveld 精修视图
│       ├── refinement_wizard.py    # 精修向导 (逐步引导)
│       ├── report_view.py          # 报告视图
│       ├── widgets/                # 自定义控件: 周期表 / 元素选择器 / 画布 / 峰表
│
├── scripts/                    # 交付性构建脚本 (8 个, 不含调试/临时)
│   ├── build_cod_sqlite.py         # COD CIF → SQLite 数据库构建
│   ├── package_cod_db.py           # 数据库打包为独立发布包
│   ├── download_cif_fill_cell.py   # COD CIF 批量下载 (阶段 1)
│   ├── download_cif_pass2.py       # COD CIF 批量下载 (阶段 2)
│   ├── PolyXRD-Setup.iss           # Inno Setup 安装脚本
│   └── cod_db_install_windows.bat  # 用户侧数据库一键导入脚本
│
├── docs/                       # 文档
│   ├── V0.8.21-Release-Notes.md   # ★ V0.8.21 最终发布报告
│   ├── V0.8.21测试报告.md         # 单元测试 & E2E 测试报告 (中文)
│   └── 多物相分析测试报告.md       # 3 个实际样品多物相分析记录
│
├── cod_data/                   # COD 数据库目录 (本地仅存小脚本,SQLite/原始数据忽略)
│   ├── start_cod_download.ps1     # CIF 下载启动脚本 (PowerShell)
│   └── README.md                  # COD 数据获取说明
│
├── PolyXRD.spec                # PyInstaller 打包配置 (onedir / PySide6 + pymatgen + scipy)
├── pyproject.toml              # Python 项目配置 / 依赖版本
├── app.manifest                # Windows 应用程序清单 (DPI)
├── .gitignore                  # 本仓库忽略规则 (测试/数据库/构建产物)
└── README.md                   # 本文件
```

---

## 🚀 使用方法

### 方式 A · 普通用户 (推荐, 无需 Python)
```
① 下载  PolyXRD-Setup-v0.9.0.exe  (~240 MB, Windows x64)
   ↓
② 双击安装 → 默认目录 C:\Program Files\PolyXRD\  → 完成
   ↓
③ (按需下载数据库外挂包, 至少选一)
   ③-a PolyXRD_COD_Inorganics_v0.9.0.zip  (~92 MB, 71,199 物相, 日常使用推荐)
        解压 → 双击 install_COD_database.bat → Y → 完成
        或: 启动 PolyXRD → 文件 → 导入外部数据库 → COD 无机物库 → 选择 COD_inorganics.sqlite
   ③-b PolyXRD_COD_Full_v0.9.0.zip        (~160 MB, 113,223 条 CIF 索引, 高级研究)
        解压 → 在设置 → 数据库挂载 → 选择 cod_index.sqlite → 热切换
   ↓
④ 开始使用! 参考 "5 分钟快速上手" 下方示例
```

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
pip install -r requirements.txt          # 或
pip install -e .                         # 若有 pyproject 构建配置

# 4. 启动应用
python -m polyxrd.main

# 5. (可选) 构建独立安装包
pip install pyinstaller
set POLYXRD_NO_COD_DB=1
set POLYXRD_NO_INORG_DB=1
pyinstaller --clean PolyXRD.spec        # → dist/PolyXRD/
# 然后用 Inno Setup 编译 scripts/PolyXRD-Setup.iss 得到 PolyXRD-Setup-v0.9.0.exe
# 或使用 build.bat
```

### 5 分钟快速上手 (工作流示例)
```
① 文件 → 打开 → 载入一个 .xrdml / .txt 样品
② 预处理面板: SNIP-40 扣背景 → SG w=11 p=3 平滑 → Max 归一化
③ 峰检测: 自动阈值 → 搜索
④ 物相检索: 勾 "COD 无机物库" → 必须元素 [Mg, Al, O] → 搜索
   → Top 候选: MgAl₂O₄ Spinel ✅
⑤ Rietveld 精修: 选中共存相 → 精修向导 → GSAS-II 引擎 → 顺序策略
   → 精修完成, RWP ≈ 5.2% ✅
⑥ 导出: 文件 → 保存项目 (.polyxrd) 或 导出报告 (CSV/PDF)
```

---

## 🙏 开源致谢

PolyXRD 基于以下高质量开源项目构建，感谢各位维护者及贡献者社区：

| 项目 | 用途 | 许可证 |
|---|---|---|
| [Python 3.10](https://www.python.org/) | 运行时 | PSF |
| [PySide6 (Qt 6)](https://wiki.qt.io/Qt_for_Python) | GUI 框架 & 图形栈 | LGPL v3 / GPL v2 |
| [PyInstaller 6.22](https://pyinstaller.org/) | 独立二进制打包 | GPL v2 (Bootloader 例外) |
| [Inno Setup 6.7](https://jrsoftware.org/isinfo.php) | Windows 安装程序构建 | Inno Setup License |
| [pymatgen](https://pymatgen.org/) | 晶体学结构处理 / CIF / 对称性 | MIT |
| [spglib](https://spglib.github.io/spglib/) | 空间群识别 / 结构标准化 | BSD-3 |
| [scipy](https://scipy.org/) | 线性代数 / 最小二乘 / 统计模型 | BSD-3 |
| [NumPy](https://numpy.org/) | 多维数组 & 数值基础 | BSD-3 |
| [pandas](https://pandas.pydata.org/) | 表格数据处理 | BSD-3 |
| [Matplotlib](https://matplotlib.org/) | 静态 2D 绘图 & 报告图 | PSF-based |
| [PyQtGraph](https://www.pyqtgraph.org/) | 交互式 XRD 主图 / 残差图 | MIT |
| [LMFIT](https://lmfit.github.io/lmfit-py/) | 非线性最小二乘 (L-BFGS-B 等) | BSD-3 |
| [GSAS-II](https://gsas-ii.net/) | ★ Rietveld 结构精修主引擎 (GSASIIscriptable API) | Free for academic/non-commercial |
| [powerxrd](https://github.com/andrewrgarcia/powerxrd/) | XRD 峰形模型 & 轻量 Rietveld 辅助 | MIT |
| [platformdirs](https://github.com/platformdirs/platformdirs) | 跨平台用户数据路径 | MIT |
| [Crystallography Open Database](https://www.crystallography.net/cod/) | 无机物相数据源 (71,199 entries, 独立外挂包) | CC BY / Public Domain 混合 |

---

## 📦 Release

当前最新版本：**V0.9.0**（2026-08-29）→ [👉 前往 Release 下载](https://github.com/PolyXRD/PolyXRD/releases/tag/v0.9.0)

V0.9.0 相对于 V0.8.21 的主要更新：
- **版本号**：0.8.21 → 0.9.0
- **联系邮箱**：`sshztx@outlook.com`（三语言关于页统一更新）
- **双 COD 数据库**：COD 无机物库 (71,199 物相) + COD 全库 (113,223 条目) 同时支持，可运行时热切换
- **识别准确率大幅提升**：物相识别命中率 45.1% → 68.6%，含量定量命中率 9.1% → 31.8%
  - 纯金属干扰抑制（FOM 惩罚 ×1.5 + 组合重排比例 ≤20%）
  - 多物相组合策略（must/maybe 自动扩展 exclude、同化学式去重、`build_refinement_combination`）
- **Rietveld wR 引擎优化**：内置引擎 `_refine_builtin` 整体迭代 v1→v8
  - `bg_method=median` 替换 `snip`（直接降 5-6pt wR）
  - Caglioti U-V-W 2θ 依赖峰宽（替换单固定 FWHM）
  - 多起点 least_squares → 显式 wR 选优 + ≈135 点稀疏邻域 wR 抛光
  - 验收：4-1 四相样 wR 64.74% < 65%；2-1 ZnO/CaCO3 50/50 样 wR 51.46% < 55%；两次独立精修锌含量差 < 35%
- **全单元测试**：95/95 通过（含 3 项 wR 专项验收）

| 附件 | 预估大小 | 说明 |
|---|---|---|
| **PolyXRD-Setup-v0.9.0.exe** | ~240 MB | Windows 独立安装包 (内置 Python/Qt6/全部依赖；默认不内置两个数据库，独立外挂包) |
| **PolyXRD_COD_Inorganics_v0.9.0.zip** | ~92 MB | COD 无机物数据库外挂包 (71,199 物相，预计算 d-I 峰) |
| **PolyXRD_COD_Full_v0.9.0.zip** | ~160 MB | COD 全库 SQLite 外挂包 (113,223 条 CIF 索引，5.1M 原子位点 gzip) |
| **Source code (.zip / .tar.gz)** | — | 完整源码快照 |

SHA256 校验（构建后填充）：
```
（待发布后补）
```

---

## 📝 版本兼容性 & License

| PolyXRD | 匹配 COD 无机物库外挂包 | 匹配 COD 全库外挂包 |
|---|---|---|
| **0.9.0** | `PolyXRD_COD_Inorganics_v0.9.0` (表列名 `ref_id`) | `PolyXRD_COD_Full_v0.9.0` (schema_version=1.0) |
| 0.8.21 | `PolyXRD_COD_Inorganics_v0.8.21` | — |

代码部分遵循 **MIT License**（除非子模块另行声明）。使用时请同时遵守上游 PySide6 (LGPL/GPL)、pymatgen、COD 的许可证条款。

---

<div align="right">
  <i>PolyXRD Team · 2025 — 2026 · 文档版本 0.9.0 (2026-08-29) · 联系：sshztx@outlook.com</i>
</div>
