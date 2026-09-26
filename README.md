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

核心设计哲学：

- **无需 Python 环境** — 安装包内置完整 Python 3.10 + PySide6 + pymatgen + scipy，目标机器开箱即用。
- **程序与数据库彻底分离** — 主程序（安装包 / 便携包）不内置任何数据库，三个数据库各自独立打包、独立下载、独立挂载。无机物库默认发布**瘦身索引式**（362 MB，不内嵌 CIF），CIF 由本地 `cod/cif` 目录或 COD 在线接口按需提供。
- **算法可控 + 结果可复现** — 预处理/拟合的每一步参数可保存、可回放，项目文件 (`.polyxrd` JSON) 全序列化。
- **UI 与算法分层** — MVVM 架构，`services/` 层是纯算法、不依赖 Qt，可独立单元测试。

> 📋 **版本变更记录**：见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。
> 🏗️ **代码结构与分层说明**：见 [docs/代码结构说明.md](docs/代码结构说明.md)。

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
- **候选检索约束（M09）**：密度区间 `density_range`、名称/化学式**模糊直搜** `find_phases_direct`、综合约束过滤 `apply_restraints`、搜索预设存取
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
  - ⚠️ 指标口径：`Rwp/Rexp/GOF` 一律基于**统计权**（`stat_weights="poisson"`）。
    显式改用单位权（`"none"`）时 `Rexp/GOF` 无物理意义，界面会显示"不可解读"。
- **Le Bail 晶胞参数精修**：仅精修 a/b/c/α/β/γ，无需原子占位，适用于未知结构的晶胞测定
- **指标化（M15）**：内置立方 / 四方 / 六方三系指标化（`services/indexing.py`，验收：立方 Si → a≈5.43 Å）；外部 Treor / Dicvol 留接口
- **3D 晶体结构可视化（M17）**：CIF 浏览器内嵌 3D 晶胞 + 原子球视图，自动按空间群**展开非对称单元**（`services/structure_viz.py`）
- 结构模拟：从空间群/原子占位 → 计算 XRD 图谱 (Lorentz-Polarization 校正 + B 因子)
- hkl 指标化 (d→hkl)，230 种空间群标准化 (spglib)
- 基于 **PDF2-2004** 的空间群（72.8%）与晶胞（81.8%）映射，命中相可直接作精修起始结构
- **外部精修程序集成（M25）**：FullProf 自动生成 `.dat/.pcr` → fp2k 批处理 → 解析 `.sum` 回写 Rwp/Rexp/Rp/GoF² 与各相 R_Bragg/晶胞/含量；GSAS-II / MAUD 一键"导出 + 拉起 GUI"

### ④ 项目 & 报告
- `.polyxrd` 项目保存/打开/另存为（JSON 格式参数 + 图谱全归档）
- 导出：峰列表 CSV / PNG+SVG 图像 / 多物相报告 PDF / 批量报告 / 选中物相 CIF
- 脚本化接口（`services/scripting.py`）

### ⑤ 界面 & 多语言
- PySide6 (Qt6) + PyQtGraph 双画布（主图 + 残差图），支持可停靠面板
- 主谱与残差条 5:1 分栏、X 轴双向同步；绘图 X 轴自适应（滚轮以光标为中心缩放、左键拖拽平移）
- **简体中文 / English / 日本語** 三语言切换，切换无需重启；**切换语言整页重翻译**（页面内部 + 停靠面板 + 工具栏/菜单/动作提示；只重设静态文案，不动运行期数据），三语翻译键集全量对齐
- **全链路 UTF-8，跨语言 Windows 不乱码** —— 所有文本 I/O 显式指定编码；读取用户文件用 `utf-8-sig` 免疫 BOM；由 `scripts/check_utf8_encoding.py` 静态守护
- 白天/深色主题，Fusion 风格，HiDPI 适配；纵坐标线性 / log / sqrt 切换
- 交互式元素周期表（双击选择，带原子量与特征波长）
- **单实例运行**：重复双击不会开出多个窗口，而是把已在运行的窗口切到前台
- **数据库管理对话框**：三个槽位各自显示「已挂载/未挂载」、记录数、体积，并直接标明该槽位对应哪个下载包

### ⑥ 三库外挂检索服务
| 库 | 规模 | 作用 |
|---|---|---|
| COD 无机物库 | 71,199 物相 | 预计算 d-I 峰 + 预截断强峰列 + Hanawalt 预筛，**主检索库**，速度最快。默认发布**瘦身索引式**（362 MB，`COD_inorganics_index.sqlite`）：原子位点完整保留，CIF 由本地 `cod/cif` 目录按需读取，缺失时自动回退 COD 在线接口下载。完整内嵌版（1.19 GB）仍可导入，两者数据逐行一致 |
| COD 全库索引 | 113,223 条目 | COD 全量 CIF 索引（432 MB，不内嵌 CIF），用于「COD 全库」与「内置+全库合并」两个检索源 |
| PDF2-2004 库 | 163,834 物相 | ICDD PDF-2 2004，自带空间群与晶胞，用于与商品库对照 |

- 路径优先级：**GUI 导入的持久化路径 (`~/.polyxrd/user_db_paths.json`) > 默认位置（存在才用）> `~/.polyxrd/cif_db/` 兜底**
- 导入时自动**校验库类型**：三库表名有重合（COD 无机物与 PDF2 都叫 `phases`），选错槽位会提示而非静默失败
- 导入后立即生效，**无需重启**；物相分析面板的「数据库源」下拉同步刷新，未挂载的源自动置灰
- 三个库完全独立，可只装其中一个；一个都不装也能用内置的 **106 种参考物相**

---

## 🚀 使用方法

### 方式 A · 普通用户 (推荐, 无需 Python)

```
① 下载 PolyXRD-Setup-vX.Y.Z.exe (Windows x64)
   ↓
② 安装 (默认 C:\Program Files\PolyXRD\) 后直接运行 PolyXRD.exe
   ↓
③ 按需下载数据库包 —— 各库独立，需要哪个下哪个
   解压到任意目录（必须真正解压到磁盘，不要直接在压缩包里打开）
   ↓
④ 启动 PolyXRD → 菜单「数据库 ▸ 外挂数据库管理…」
   对话框每个槽位上都写着「下载包：… → 解压出 …」，照对上即可，在该行点「导入…」
   → 立即生效，无需重启
   ↓
⑤ 开始使用! 参考 docs/5分钟上手_4-1样例.md
```

> **发布口径**：Release 仅提供 **Setup 安装包 + 两个 COD 索引库包**。
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

#### 一键源码启动（人工验收用）

仓库根目录的 `run_dev.bat` 已封装好 PYTHONPATH，双击即可：

```bat
run_dev.bat
```

它直接跑仓库里的 `src/`，**永远是最新代码**，不必等 PyInstaller 构建完成，
适合功能验收 / 手测。打包版与源码版的差异只在分发方式，业务代码同源。

### 构建发布产物

```bat
:: 改 build.bat 顶部的 set APPVER= 后:
build.bat
```

`build.bat` 会依次完成：生成图标 → PyInstaller 打包 → **自检 dist 内无业务数据库** →
Inno Setup 编译安装包 → 打便携包 → 生成三个独立数据库包 → 计算 SHA-256。

> **注意**：默认**不**打包任何数据库。如需把库内嵌进二进制，用 `POLYXRD_WITH_DB=1`。
>
> 仅校验 / 重新生成发布产物（不重新构建 exe）：
> ```powershell
> pwsh -NoProfile -File scripts\verify_release.ps1 -Version X.Y.Z
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

> 启动稳健性设计：**单实例守卫用内核命名互斥量实现** —— 上一个实例
> 无论正常退出还是被任务管理器强杀，都不会影响下一次启动；守卫本身"拿不准就放行"，
> 绝不因为残留状态把用户挡在门外。

---

## 🙏 开源致谢

PolyXRD 基于众多高质量开源项目构建 —— Python / PySide6 (Qt6) / PyInstaller / Inno Setup / pymatgen / spglib / scipy / NumPy / pandas / Matplotlib / PyQtGraph / LMFIT / GSAS-II / powerxrd / platformdirs 及 [Crystallography Open Database](https://www.crystallography.net/cod/)（无机物相数据源），感谢各上游项目的维护者与贡献者社区（ICDD PDF-2 2004 为商业数据库，不随附、不转发，需用户自行取得授权）。

---

## 📦 Release

最新版本与全部变更记录见 [docs/CHANGELOG.md](docs/CHANGELOG.md)；二进制产物（Setup 安装包 + 两个 COD 索引库包）前往 [👉 Releases 页面](https://github.com/PolyXRD/PolyXRD/releases) 下载。SHA-256 校验值随 Release 附件发布，下载数据库包后建议核对（截断的库能被 SQLite 打开，但读到尾部记录才会报错）。

---

## 📝 版本兼容性 & License

| PolyXRD | COD 无机物库 | COD 全库索引 | PDF2-2004 |
|---|---|---|---|
| **2.x / 1.x（当前）** | `…-Databases-COD-inorg-index.zip`（瘦身索引式, 默认; 内嵌版仍可导入） | `…-Databases-COD-full-index.zip` | 用户自行准备（ICDD 授权，仓库不分发） |
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
  <i>PolyXRD Team · 2025 — 2026 · 文档版本 2.2.0 (2026-09-26) · 联系：sshztx@outlook.com</i>
</div>
