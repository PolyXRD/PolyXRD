<div align="center">
  <img src="src/polyxrd/resources/app-icon.png" alt="PolyXRD Logo" width="120" />
  <h1>PolyXRD</h1>
  <p>
    <b>多晶 X 射线衍射 (XRD) 图谱综合分析套件</b>
    <br />
    峰检测 &nbsp;·&nbsp; 多物相定性检索 &nbsp;·&nbsp; 晶胞精修 (Le Bail) &nbsp;·&nbsp; 全谱拟合 &nbsp;·&nbsp; COD 无机物库接入
  </p>
  <p>
    <a href="https://github.com/PolyXRD/PolyXRD/releases/tag/v0.8.21"><img src="https://img.shields.io/badge/Release-v0.8.21-blue?style=flat-square" /></a>
    &nbsp;
    <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-lightgrey?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Python-3.10-yellow?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/UI-PySide6%20(Qt6)-41cd52?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Tests-50%2F55%20%E2%88%9A%20(90.9%25)-brightgreen?style=flat-square" />
  </p>
</div>

---

## 📖 项目说明

**PolyXRD** 是一个面向材料学 / 化学 / 晶体学研究者的 **多晶 X 射线衍射 (XRD) 图谱综合分析桌面软件**。它把"**加载原始 XRD 数据 → 预处理 → 峰检测 → 多物相定性检索 → 晶胞精修 → 全谱拟合 → 出报告**"整条工作流集成在一个统一的、带 **中文/英文/日文** 三语言界面的 PySide6 (Qt6) 桌面应用里。

核心设计哲学：
- **无需 Python 环境** — 一键安装包 (`PolyXRD-Setup-v0.8.21.exe`) 内置完整 Python 3.10 + PySide6 + pymatgen + scipy，目标机器开箱即用。
- **程序与数据库分离发布** — 主程序安装包仅 ~241 MB；71,199 物相的 COD 无机物库以独立外挂包 (92 MB zip) 分发，用户按需导入，支持运行时切换。
- **算法可控 + 结果可复现** — 预处理/拟合的每一步参数可保存、可回放，项目文件 (`.polyxrd` JSON) 全序列化。

---

## 🛣️ 开发计划 (Roadmap)

| 版本 | 目标状态 | 时间 | 主要内容 |
|---|---|---|---|
| **V 0.8.x** (当前) | **可投入使用的 Beta** | 2026 Q3 | 独立安装包 + COD 无机物库外挂 + 预处理 / 物相检索 / Le Bail / 多相联合拟合完整闭环 |
| V 0.9.x | 精修增强 Beta | 2026 Q4 | 引入 Rietveld 全谱精修 (GSAS-II / FullProf 后端)、择优取向校正、微应变 & 晶粒尺寸 (W-H) |
| V 1.0.0 | 正式版 GA | 2027 Q1 | 批处理流水线、用户物相库 (自建 SQlite)、自动化导出 PDF 报告、插件式算法扩展 |
| V 1.1+ | 多平台 & 云端 | 2027 Q2 | macOS / Linux 原生包、CIF 在线自动下载 (COD API 直连)、结果共享 (导出 .polyxrd 给同事回放) |

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
- **Le Bail 晶胞参数精修**：固定物相 → 精修 a/b/c/α/β/γ
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
│   ├── models/                 # 数据模型: XRD 图谱、物相、峰、项目文件
│   ├── services/               # 核心算法服务 (无 UI, 可独立单元测试)
│   │   ├── data_loader.py          # 多格式 XRD 加载
│   │   ├── preprocessor.py         # 背景/平滑/归一化/Kα2 剥离
│   │   ├── peak_detector.py        # 峰检测 & 峰拟合
│   │   ├── phase_identifier.py     # 多物相检索 + 联合拟合
│   │   ├── cif_database.py         # COD 无机物库服务 (71,199 物相)
│   │   ├── le_bail_refiner.py      # Le Bail 晶胞精修
│   │   ├── profile_fitting.py      # 全谱拟合 (PV/PVII)
│   │   ├── structure_simulator.py  # 计算 XRD 图谱
│   │   ├── project_service.py      # .polyxrd 读写
│   │   └── exporter.py             # CSV/PNG/PDF 报告导出
│   └── views/                  # UI 视图层 (PySide6)
│       ├── main_window.py          # 主窗口 / 菜单 / 工具栏
│       ├── panels/                 # 可停靠面板: 预处理 / 峰检测 / 物相检索 / 精修
│       ├── widgets/                # 自定义控件: 周期表 / 元素选择器 / 2θ 画布
│       └── dialogs/                # 对话框: 导入数据库 / 导出 / 批处理
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
① 下载  PolyXRD-Setup-v0.8.21.exe  (241 MB, Windows x64)
   ↓
② 双击安装 → 默认目录 C:\Program Files\PolyXRD\  → 完成
   ↓
③ 下载  PolyXRD_COD_Inorganics_v0.8.21.zip  (92 MB)
   解压 → 双击 install_COD_database.bat → Y → 完成
   或: 启动 PolyXRD → 文件 → 导入外部数据库 → COD 无机物库 → 选择 COD_inorganics.sqlite
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
pyinstaller --clean PolyXRD.spec        # → dist/PolyXRD/
# 然后用 Inno Setup 编译 scripts/PolyXRD-Setup.iss 得到 PolyXRD-Setup.exe
```

### 5 分钟快速上手 (工作流示例)
```
① 文件 → 打开 → 载入一个 .xrdml / .txt 样品
② 预处理面板: SNIP-40 扣背景 → SG w=11 p=3 平滑 → Max 归一化
③ 峰检测: 自动阈值 → 搜索
④ 物相检索: 勾 "COD 无机物库" → 必须元素 [Mg, Al, O] → 搜索
   → Top 候选: MgAl₂O₄ Spinel ✅
⑤ 导出: 文件 → 保存项目 (.polyxrd) 或 导出报告 (CSV/PDF)
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
| [powerxrd](https://github.com/andrewrgarcia/powerxrd/) | XRD 峰形模型辅助 | MIT |
| [platformdirs](https://github.com/platformdirs/platformdirs) | 跨平台用户数据路径 | MIT |
| [Crystallography Open Database](https://www.crystallography.net/cod/) | 无机物相数据源 (71,199 entries, 独立外挂包) | CC BY / Public Domain 混合 |

---

## 📦 Release

当前最新版本：**V0.8.21**（2026-08-21）→ [👉 前往 Release 下载](https://github.com/PolyXRD/PolyXRD/releases/tag/v0.8.21)

| 附件 | 大小 | 说明 |
|---|---|---|
| **PolyXRD-Setup-v0.8.21.exe** | 241 MB | Windows 独立安装包 (内置 Python/Qt6/全部依赖) |
| **PolyXRD_COD_Inorganics_v0.8.21.zip** | 92 MB | COD 无机物数据库外挂包 (71,199 物相) |
| **Source code (.zip / .tar.gz)** | — | 完整源码快照 |

SHA256 校验：
```
26E12644 A66F30BC AF513DD7 F67F3093 A2D914A6 6991D6B7 9271377F AE3A0CC2  PolyXRD-Setup-v0.8.21.exe
0220A89D 00626069 AB112E24 BB1B92B5 6AB81F3F 6C458F7F D452F4D3 BF2A0DA3  PolyXRD_COD_Inorganics_v0.8.21.zip
```

---

## 📝 版本兼容性 & License

| PolyXRD | 匹配 COD 无机物库外挂包 |
|---|---|
| **0.8.21** | `PolyXRD_COD_Inorganics_v0.8.21` (表列名 `ref_id`) |

代码部分遵循 **MIT License**（除非子模块另行声明）。使用时请同时遵守上游 PySide6 (LGPL/GPL)、pymatgen、COD 的许可证条款。

---

<div align="right">
  <i>PolyXRD Team · 2025 — 2026 · 文档版本 0.8.21 (2026-08-21)</i>
</div>
