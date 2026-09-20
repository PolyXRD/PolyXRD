# PolyXRD 版本变更记录（CHANGELOG）

> 覆盖范围：**v0.8.21（首次提交 / 首个 Beta）→ v0.15.1**
> 生成日期：2026-09-20 ｜ 生成方式：回溯 git 提交历史 + GitHub Release 正文 + 项目工作记忆（`.workbuddy/memory/`）
> 联系：sshztx@outlook.com

## 图例说明

| 标记 | 含义 |
|---|---|
| 🟢 GitHub Release | 已挂到 https://github.com/PolyXRD/PolyXRD/releases |
| 🟡 仅本地发布 | 本地打包发布，未上 GitHub Release |
| 形态 | **Setup** = Inno Setup 安装包；**Portable** = 免安装 zip；**库包** = 外挂数据库 zip |

## 版本速览表

| 版本 | 日期 | 主题 | 发布形态 | GitHub Release |
|---|---|---|---|---|
| **v0.15.1** | 2026-09-20 | 外部精修程序 MAUD 默认改走官方 `maud.bat`（优先于 java.exe） | 待打包 | ⬜ |
| **v0.15.0** | 2026-09-20 | M22–M25：图谱交互 / 物相列表重构 / 精修页布局 / GSAS-II・MAUD・FullProf 外部精修集成 + 中文手册 | Setup + 2 库包 + SHA | 🟢 |
| v0.14.0 | 2026-09-19 | 无机库默认改瘦身索引式 + 发布包改「索引版」命名 + 含 v0.13.2 数据修复 | Setup + Portable + 2 库包 + SHA | 🟢 |
| v0.13.2 | 2026-09-18 | 无机库 `formula` 被空间群覆盖 + `cell_*` 列错位的数据修复 | Setup + Portable + 库包 | 🟡 |
| v0.13.1 | 2026-09-18 | 启动崩溃修复（图标/启动图改走 PNG）+ 安装目录守卫 + 启动/崩溃日志 | Setup + Portable + 3 库包 | 🟡 |
| v0.13.0 | 2026-09-17 | 精修前置 CIF 自动匹配 + 向导物相页 v2 | Setup + Portable | 🟡 |
| v0.12.0 | 2026-09-16 | 纵坐标 log/sqrt 切换 + 元素「必有」置末 + 精修向导默认勾选与过程日志 | 源码/本地构建 | 🟡 |
| v0.11.0 | 2026-09-15 | COD 结构精修链路打通（CIF 五级回退 + 无机库内嵌 CIF v2 + GSAS-II/MAUD 端到端） | Setup + 2 库包 | 🟢 |
| v0.10.0 | 2026-09-11 | 数据库彻底外挂化 + GUI 外挂数据库管理入口 + PDF2 挂载能力 | Setup + Portable + 2 库包 | 🟢 |
| v0.9.10 | 2026-09-09 | 品牌化应用图标 + 高精度寻峰引擎 + 物相分析 v2 展示层 | Setup + Portable + 2 库包 | 🟢 |
| v0.9.7 | 2026-09-07 | M20 GUI 交互增强（含 M19 系列） | Setup + Portable | 🟢 |
| v0.9.0 | 2026-08-29 | 识别准确率跃升（命中率 45.1%→68.6%）+ Rietveld wR 引擎重写 | Setup + 2 库包 | 🟢 |
| v0.8.23 | 2026-08-24 | 内置 MCP Server（18 个工具，AI 可无 GUI 调用全流程） | Setup | 🟢 |
| v0.8.22 | 2026-08-21 | 品牌视觉升级 + Rietveld 精修文档修正 | Setup | 🟢 |
| v0.8.21 | 2026-08-21 | 首个正式 Beta：程序与数据库分离分发 | Setup + 库包 | 🟢 |

---

## v0.15.1（2026-09-20）

**主题**：外部精修程序 MAUD 默认启动方式改为官方 `maud.bat`

### 修复/调整

- **MAUD 默认走 `maud.bat`**：精修页右下「外部精修程序」MAUD 行的自动探测改为优先返回
  `<MAUD根>/maud.bat`（`C:\MAUD3\maud.bat` / `C:\MAUD2\maud.bat`，与用户双击启动行为一致），
  无 bat 才回退自带 `jdk/bin/java.exe` 拼装 java 命令。
- **`resolve_maud_root` 三形态识别**：用户配置路径支持 `maud.bat` / 安装根目录 / `jdk\bin\java.exe`，统一解析回根目录。
- **路径校验放宽**：`ToolSpec.validate` 认 `maud.bat` 与含 `maud.bat` 的根目录；「浏览…」文件过滤器加 `*.bat`。
- 涉及 `services/external_tools.py`、`services/launchers/maud_launcher.py`、`views/widgets/external_engines_group.py`。

---

## v0.15.0（2026-09-20）

**主题**：路线图 M22–M25 四模块落地 + 首个中文使用手册
**版本收口**：`13e2f03`（config / pyproject / `__init__` / build.bat 四处同步）

### 主要更新

- **M22 图谱交互**：横坐标自适应缩放，支持滚轮缩放与拖动平移
- **M23 物相列表重构**：改为勾选驱动（勾选即参与叠加显示与精修）；右键导出物相 CIF；勾选集合随项目持久化
- **M24 精修页布局重构**：残差细条与主图 X 轴同步、精修日志移至左栏、已勾选物相区与外部程序容器独立分区
- **M25 外部精修程序集成**（本版重点）
  - GSAS-II / MAUD / FullProf 三引擎一键启动；路径自动探测 + 手动指定（`external_tools.json` 持久化）；精修页外部程序面板带状态灯（绿=可用）
  - **FullProf（fp2k 8.20）批处理精修端到端**：`.dat`/`.pcr` 自动生成、两遍标度自校准、fp2k SYMBOLIC 限位编号自动发现（不再手工填 Limit 编号）、保守模式 W 扫描兜底、`.sum`/`.out` 解析回写
  - MAUD 检测修复：返回 `jdk/bin/java.exe`，GUI 启动路径解析正确（三引擎状态灯全绿）
- **中文手册**：`docs/manual/` 交付《使用手册》（15 页 PDF / 14 页 PPTX）与《快速入门》（6 页 PDF / 8 页 PPTX），含界面截图与 Rietveld 原理
- 精修 GUI 决议：快速精修与多步精修向导保持两条独立路径

### 产物

| 文件 | 体积 |
|---|---|
| PolyXRD-Setup-v0.15.0.exe | 247.7 MiB |
| PolyXRD-v0.15.0-Portable.zip | 387.7 MiB（本地，不上 Release） |
| PolyXRD-v0.15.0-Databases-COD-inorg-index.zip | **986.5 MiB（v0.15.0 Release 实为完整内嵌版，属打包回归）** |
| PolyXRD-v0.15.0-Databases-COD-full-index.zip | 205.9 MiB |
| PolyXRD-v0.15.0-Databases-PDF2.zip | 58.9 MiB（本地归档，永不发布） |
| SHA256-v0.15.0.txt | 五产物校验和 |

### ⚠️ 本版已知问题

1. **无机库包体积回归**：v0.14.0 起发布包的定义是「瘦身索引式」（`db_import.PKG_FILENAME['cod_inorganics'] = COD_inorganics_index.sqlite`，130.8 MiB），但 v0.15.0 的 `verify_release.ps1` 源路径仍指向完整内嵌版 `COD_inorganics.sqlite`（1.19 GB，其中内嵌 CIF 占 830 MB），导致再次打出 986.5 MiB 的包。
   **已修正**（`scripts/verify_release.ps1` 源文件与包内文件名对齐 `pkg_suffix` / `PKG_FILENAME`），本地已重打包为 **134.1 MiB** 的瘦身版；发布页附件待替换。
2. 内置精修引擎不含原子坐标，wR 50%~90% 属设计使然（发布级结果须走 GSAS-II / MAUD / FullProf）。

---

## v0.14.0（2026-09-19）

**主题**：数据库形态收敛——无机库默认瘦身索引式

- **COD 无机物库默认改为瘦身索引式**（`COD_inorganics_index.sqlite`，362 MB）：与全库索引同形态，不内嵌 CIF；`cod_atomic_sites` 31.1 万行原子位点完整保留；峰表 / 晶胞 / 化学式与完整版逐行一致。CIF 由本地 `cod/cif` 目录按需读取，本地缺失时回退 COD 官网接口（需联网）。完整内嵌版（1.19 GB）仍可导入
- **发布包改名**：`Databases-COD-inorg.zip` → `Databases-COD-inorg-index.zip`（内容改发瘦身版）；`Databases-COD-full.zip` → `Databases-COD-full-index.zip`（内容不变）
- **包含 v0.13.2 数据修复**：`formula` 被空间群覆盖（541 条）+ `cell_*` 列错位（31,634 行）
- 新增 `scripts/build_inorg_index_db.py`（瘦身库构建，默认 dry-run，零信息损失审计）

产物：Setup 247.6 MiB / Portable 379.3 MiB / inorg-index 包 **130.8 MiB** / full-index 包 193.1 MiB

---

## v0.13.2（2026-09-18）🟡

**主题**：无机库字段级数据修复（有缺陷数据的使用者必须升级数据库包）

- `phases.formula` 被空间群值覆盖（609 条）修复
- `cell_*` 晶胞列错位（31,634 行）修复——迁移脚本 `scripts/migrate_inorg_formula.py` / `scripts/repair_inorg_cell.py`，均为幂等
- 「编号前缀搜索」两处静默失效修复
- ⚠️ 经验：**库数据改动后必须同步「双库外挂 zip」**，否则装机用户拿不到修复

---

## v0.13.1（2026-09-18）🟡

**主题**：双击打不开（启动原生崩溃）修复

- 运行时图标 / 启动图**一律改走 PNG**（Qt6 PNG 解码器内建于 Qt6Gui，实测加载 0 个 imageformats 插件；jpg→2、ico→2）。触发条件：启动早期用 QIcon/QPixmap 从文件解码 + 之后 `window.show()` → 原生崩溃（0xC0000409 / 0xC0000005），日志停在 `MainWindow OK` 无 `shown`
- 新增启动 / 崩溃日志（`~/.polyxrd/logs/startup-*.log`、crash 日志）+ 异常钩子
- `cod_local` 安装目录守卫：不再在安装目录里创建/捡到幻影空索引（空索引会遮蔽真实库）
- 病灶最终未定位，PNG 为实测有效的**规避**

---

## v0.13.0（2026-09-17）🟡

**主题**：精修前置 CIF 自动匹配 + 向导物相页 v2

- 精修前置 CIF 自动匹配（物相 → CIF 自动定位）
- 分步精修向导「物相页 v2」：上=CIF 候选列表，下=已选初始结构；库中缺失时自动从 COD 下载
- MAUD 3 引擎集成延续（v0.11.0 起）

---

## v0.12.0（2026-09-16）🟡

**主题**：图谱纵坐标模式 + 向导默认策略 + 精修过程日志

- 纵坐标 log / sqrt 切换（`views/widgets/y_scale.py`）：左键点 Y 轴竖条循环、右键菜单选择；谱图标一律用技术记号 `Intensity (log)` / `(sqrt)`，不本地化
- 元素四态顺序调整：『必有』置末（单击循环 无→含有→可能→没有→必有）
- 精修页「按精修向导的方式（推荐）」复选框默认勾选 + 底部精修过程日志面板（流式回吐）

---

## v0.11.0（2026-09-15）🟢

**主题**：COD 结构精修链路打通（本仓库的"精修里程碑"）

- **CIF 覆盖 + 五级回退**：本地 `cod/cif` 目录 → 全库索引 BLOB → 无机库内嵌 CIF → 原始 tar → COD 在线 REST
- **COD 无机物库 v2 结构**：`phases` 新增 `cif_gz` 列（71,199 相中 71,156 = 99.94% 内嵌 gzip CIF 全文）+ `cod_atomic_sites` 31.1 万行原子位点 → **只挂无机物库一个库即可做 Rietveld 结构精修**
- GSAS-II 引擎端到端：`engine=auto` 自动选引擎（全相有 CIF 且 GSAS-II 可用 → 真 Rietveld + wt% 定量），不可用则回退内置引擎并记录原因
- MAUD3 引擎端到端：xye 去 `#` 头 / CIF 剥 `:H` 后缀 / wR 百分号换算 / par 相定量解析回写 wt% 与晶胞
- 精修算法：R-A1 统计权重（目标函数与 wR 自洽）、R-A4 Chebyshev 多项式背景抛光（均 opt-in）
- **两套精修向导并存**：快速版（单页对话框）+ 分步版（数据→物相→参数→预览→执行，含模板管理 / CIF 导入 / COD 在线检索）
- 引擎下拉统一：`auto / gsas2 / maud / builtin / powerxrd` 四处 UI 与状态接口一致
- 安装体验：`run_dev.bat` 双击闪退修复 + 启动图未绑定崩溃修复
- 单元测试 745+ 项通过

产物：Setup + `Databases-COD-inorg.zip`（v2 内嵌式）+ `Databases-COD-full.zip`；**Portable 自本版起不再随 Release 发布**

---

## v0.10.0（2026-09-11）🟢

**主题**：数据库彻底外挂化

- 安装包与便携包**不再内置任何数据库**，改为独立下载包按需取用；便携包 661.5 MB → 380 MB（约 −42%）
- 新增 GUI 入口「数据库 ▸ 外挂数据库管理…」：槽位独立挂载/卸载、导入后热生效；导入时按列签名校验库类型（COD 无机物与 PDF2 表名同为 `phases`，靠 signature / excludes 区分）
- 新增 **PDF2-2004 挂载能力**（163,834 物相，自带空间群 72.8% / 晶胞 81.8%）——ICDD 商业库，**仓库不分发、Release 不提供**
- 检索质量与速度（含 0.9.11 内容）：FoM 改加权互斥匹配；COD 候选排序重做（0.3×Hanawalt 复合 + 0.7×(1−FoM)），基准 Top-1 12%→14% / Top-5 22%→25% / Top-10 24%→27%；检索耗时 22.5 s → 8.8 s；元素过滤四语义（必有/含有/可能/没有）定稿
- 界面：工具栏布局修复（不再被挤进 » 溢出区）；物相分析棒区逐行相标 + 未解释残差峰标注；matplotlib 中文不再 tofu；长耗时操作加忙碌提示与防重入
- 单元测试 545 项通过

---

## v0.9.10（2026-09-09）🟢

- **品牌化应用图标**：圆角方形 + 深蓝对角渐变 + 白色晶胞六边形与 XRD 衍射曲线；多分辨率 ICO 七档 + 512×512 @2x PNG（旧版为纯黑占位方块）
- 数据文件菜单：打开新数据自动清空旧结果 + 显式「清除数据」（0.9.9）
- **高精度寻峰引擎重设计**（0.9.9）：自适应背景扣除 → 分区噪声 σ(MAD) → 亚步长峰位内插 → 重叠簇联合 pseudo-Voigt 拟合。真实 ZnO 试样：旧引擎 15 峰（锁 0.02° 网格）→ 新引擎 35 峰，正确解析 Kα1/Kα2 双峰
- 物相分析 v2 展示层（0.9.8）：多相同图叠加分相着色、峰归属表（2θ 升序、点击行联动定位）
- 双 COD 数据库内置；单元测试 316 项通过

产物：Setup 252 MB / Portable 661 MB / 库包 94 MB + 206 MB

---

## v0.9.7（2026-09-07）🟢

- M20 GUI 交互增强系列（M19–M20 阶段成果），版本号升至 0.9.7
- 转交文档 `docs/HANDOVER-v0.9.7.md`

---

## v0.9.0（2026-08-29）🟢

**主题**：识别准确率跃升 + Rietveld wR 引擎重写

- **识别准确率**：物相识别命中率 45.1% → **68.6%**（13 个工业试样）；含量定量命中率 9.1% → 31.8%
  - 纯金属干扰抑制（FoM 惩罚 ×1.5 + 组合重排比例 ≤20%）
  - 多物相组合策略：must/maybe 自动扩展 exclude、同化学式去重、`build_refinement_combination` 启发式
- **Rietveld wR 引擎优化**（`_refine_builtin` v1→v8）：`bg_method=median` 替换 SNIP（直接降 5~6 pt）、Caglioti U-V-W 2θ 依赖峰宽替换固定 FWHM、多起点 `least_squares` + 显式 wR 选优 + ≈135 点稀疏邻域抛光
  - 验收：4-1 四相样 wR 64.74% < 65%；2-1 ZnO/CaCO₃ 50/50 wR 51.46% < 55%
- 双 COD 数据库外挂支持：无机物库 71,199 物相（zip 75.8 MB）、全库索引 113,223 条 CIF + 5.1M 原子位点（zip 179.2 MB），运行时可热切换
- 交付物：Inno Setup 脚本 + 7z SFX 自解压安装程序；文档新增转交报告与开源致谢清单
- 单元测试 95 项通过（含 3 项 wR 专项验收）

---

## v0.8.23（2026-08-24）🟢

- **内置 MCP Server**（`python -m polyxrd.mcp_server`，stdio 传输）：18 个工具覆盖全流程——数据装载、预处理（SNIP/ALS/平滑/Kα2/归一化）、寻峰与拟合、物相鉴定、COD 检索（含在线）、CIF 模拟、Rietveld 精修（GSAS-II / powerxrd / builtin）、导出与项目管理、会话状态
- 使 Claude / GPT 等 MCP 客户端无需 GUI 即可驱动 XRD 分析

## v0.8.22（2026-08-21）🟢

- 品牌视觉升级（图标基于 crystal-mark 重新生成）+ README 中 Rietveld 精修说明修正

## v0.8.21（2026-08-21）🟢 — 首个正式 Beta

- **程序与数据库分离发布**：主程序 240.9 MB（内置 Python 3.10 / PySide6 / pymatgen / scipy / numpy / pandas / matplotlib / pyqtgraph / lmfit），COD 无机物库独立外挂包 91.9 MB（71,199 物相）
- 外部数据库导入接口（菜单 + 一键 bat 脚本），三重路径优先级：用户导入路径 > `%LOCALAPPDATA%\PolyXRD\databases\` > 程序内置 `cod_data/`
- `set_cod_db_path()` + `reload_cod_db()` 热切换，无需重启
- 品牌合规：数据库统一命名为「COD 无机物库 20260821 版本」

---

## 附录 A · 外挂数据库包演进

| 版本 | 无机物库包 | 全库索引包 | 形态说明 |
|---|---|---|---|
| v0.8.21 | 91.9 MiB（解压 258.6 MB） | — | 仅峰表/晶胞/化学式，无 CIF |
| v0.9.0 | 75.8 MiB | 179.2 MiB | 双库外挂、热切换 |
| v0.9.10 | 94 MiB | 206 MiB | 名称改为 `PolyXRD_COD_*_v0.9.10.zip` |
| v0.10.0 | — | — | 数据库彻底外挂化；命名改 `PolyXRD-v{ver}-Databases-*` |
| v0.11.0 | 内嵌 gzip CIF 全文（v2 结构） | 同前 | 单库即可 Rietveld |
| v0.13.1 | 980.6 MiB | 205.9 MiB | 完整内嵌版 |
| v0.13.2 | 982.1 MiB | — | 修数据后重打 |
| v0.14.0 | **130.8 MiB**（瘦身索引式） | 193.1 MiB | 命名改 `-index` 后缀；CIF 走 `cod/cif` 或 REST |
| v0.15.0 | 986.5 MiB（**回归** → 已修：134.1 MiB） | 205.9 MiB | 命名单一真源 = `db_import.DBKind.pkg_suffix` |

**结构事实（2026-09-20 实测）**：完整内嵌版 `COD_inorganics.sqlite` 1,194 MB，其中 `cif_gz` 830.2 MB（70%）、`peaks_d/i` 206.7 MB、`peaks_top_*` 64.6 MB、原子位点 ~10 MB；因 `cif_gz` 已 gzip，zip 仅能压掉 17%。瘦身版 `COD_inorganics_index.sqlite` 362 MB（`cif_gz` 全空），zip 后 134.1 MiB。

**取舍**：瘦身包体积小 7 倍，但 CIF 依赖外部 `cod/cif` 目录或联网 COD REST；完整包自包含但近 1 GB。

## 附录 B · 发布红线与约定

1. **PDF2-2004 永不上传**（ICDD 版权库）：仓库只提供挂载能力，DB Manager 中显示「请确认已获得正版授权」
2. **Portable 免安装包自 v0.11.0 起不随 Release 发布**（按需提供）
3. **每个 EXE 发布前必须双击人工验收**（自动启动检查不可替代）
4. 版本号收口点（5 处，`build.bat` 顶部 `set APPVER=` 为唯一改动入口）：`build.bat` / `config.app_version` / `src/polyxrd/__init__.py` / `pyproject.toml` / `scripts/PolyXRD-Setup.iss`
5. 数据库文件（sqlite / tar.xz）与 `tests/` 不入 git
6. commit message 采用「更新代码修正: …」风格

## 附录 C · 已知遗留

| 项 | 状态 |
|---|---|
| PySide6 体积裁剪（dist 983.5 MiB，PySide6 独占 641 MiB：WebEngine 196 / resources 102 / translations 60 / qml 30） | 待办 |
| 启动路径图片解码崩溃的**最终病灶** | 未定位（PNG 规避有效） |
| 内置精修引擎 wR 偏高（无原子坐标） | 设计使然，需发布级结果请用外部引擎 |
| M15 索引优化 / M17 3D 可视化 | 降级 P3，可延后或跳过 |
