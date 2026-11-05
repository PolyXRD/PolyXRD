<div align="center">
  <img src="src/polyxrd/resources/app-icon.png" alt="PolyXRD Logo" width="120" />
  <h1>PolyXRD</h1>
  <p>
    <b>多晶 X 射线衍射 (XRD) 图谱综合分析套件</b>
    <br />
    峰检测 &nbsp;·&nbsp; 多物相定性检索 &nbsp;·&nbsp; Rietveld 结构精修 &nbsp;·&nbsp; Le Bail 晶胞精修 &nbsp;·&nbsp; 指标化 &nbsp;·&nbsp; 3D 结构可视化 &nbsp;·&nbsp; 内置 COD 无机物库 (polyDB) + 多库外挂检索
  </p>
  <p>
    <a href="https://github.com/PolyXRD/PolyXRD/releases"><img src="https://img.shields.io/badge/Release-v5.2.0-blue?style=flat-square" /></a>
    &nbsp;
    <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-lightgrey?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/UI-PySide6%20(Qt6)-41cd52?style=flat-square" />
    &nbsp;
    <img src="https://img.shields.io/badge/Tests-2348%20passed-brightgreen?style=flat-square" />
  </p>
  <p><i>🌐 English documentation: [README-EN.md](README-EN.md)</i></p>
</div>

---

## 📖 项目说明

**PolyXRD** 是一个面向材料学 / 化学 / 晶体学研究者的 **多晶 X 射线衍射 (XRD) 图谱综合分析桌面软件**。它把"**加载原始 XRD 数据 → 预处理 → 峰检测 → 多物相定性检索 → Rietveld 结构精修 → 晶胞精修 → 全谱拟合 → 出报告**"整条工作流集成在一个统一的、带 **中文/英文/日文** 三语言界面的 PySide6 (Qt6) 桌面应用里。

核心设计哲学：

- **无需 Python 环境** — 安装包内置完整 Python 3.10 + PySide6 + pymatgen + scipy，目标机器开箱即用。
- **开箱即检索 + 其余库外挂** — **v4.1.0 起便携包/安装包内置默认库 `COD-Inorg` polyDB**（77,500 相，解压即用，无需任何下载或挂载）；可选扩展库（COD 全库等）与**库构建工具、格式规范**统一在独立仓库 [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase) 维护并分发。PDF2-2004 为 ICDD 版权库，永不随包分发。
- **算法可控 + 结果可复现** — 预处理/拟合的每一步参数可保存、可回放，项目文件 (`.polyxrd` JSON) 全序列化。
- **UI 与算法分层** — MVVM 架构，`services/` 层是纯算法、不依赖 Qt，可独立单元测试。

> 📋 **版本变更记录**：见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。
> ✅ **v5.2.0 发布检查清单（构建/产物/验收记录）**：见 [docs/发布检查清单-v5.2.0.md](docs/发布检查清单-v5.2.0.md)。
> 🏗️ **v5.1.0 发布检查清单（收口未单独发布，内容已并入 v5.2.0）**：见 [docs/发布检查清单-v5.1.0.md](docs/发布检查清单-v5.1.0.md)。
> ✅ **v4.7.0 发布检查清单（构建/产物/验收记录）**：见 [docs/发布检查清单-v4.7.0.md](docs/发布检查清单-v4.7.0.md)。
> ⏳ **v4.4.0 发布检查清单（构建/产物/验收记录，待发布）**：见 [docs/发布检查清单-v4.4.0.md](docs/发布检查清单-v4.4.0.md)。
> ✅ **v4.3.0 发布检查清单**：见 [docs/发布检查清单-v4.3.0.md](docs/发布检查清单-v4.3.0.md)。
> ✅ **v4.2.0 发布检查清单（构建/产物/验收记录）**：见 [docs/发布检查清单-v4.2.0.md](docs/发布检查清单-v4.2.0.md)。
> ✅ v4.1.1 发布检查清单：见 [docs/发布检查清单-v4.1.1.md](docs/发布检查清单-v4.1.1.md)。
> ✅ v4.1.0 发布检查清单：见 [docs/发布检查清单-v4.1.0.md](docs/发布检查清单-v4.1.0.md)。
> ✅ v4.0.0 发布检查清单：见 [docs/发布检查清单-v4.0.0.md](docs/发布检查清单-v4.0.0.md)。
> 🏗️ **代码结构与分层说明**：见 [docs/代码结构说明.md](docs/代码结构说明.md)。
> ✅ **v4.2 结构清理（旧 COD sqlite 运行时退役）已执行完毕**：设计依据 [docs/v4.2-结构清理方案.md](docs/v4.2-结构清理方案.md)，执行记录/验收数据 [docs/下一步执行计划-v4.2.md](docs/下一步执行计划-v4.2.md)。

---

## 🆕 最新版本 v5.2.0（2026-11-05）

**在"算得对"之后补上"强度也对"** —— v5.1 把峰位、展宽、择优取向、结构精修全部做对，
v5.2 处理剩下的两类**系统性强度误差**，并把"定量结果不可信"从"看了也不知道"变成
"界面上明写着"（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §v5.2 与
[docs/RELEASE-NOTES-v5.2.0.md](docs/RELEASE-NOTES-v5.2.0.md)）：

| # | 件 | 关键结果 |
|---|---|---|
| 1 | **表面粗糙度 SR**（opt-in） | 三模型（Sidey / Suortti / Sparks），乘子进前向模型（随 2θ 变化，标度吸收不掉）。4 例 A/B 的 s 全部收敛到 ~0 → 维持 opt-in |
| 2 | **微吸收 MA**（opt-in） | Brindley τ 只进 Hill–Howard 定量、**不进拟合向量**（逐相常数会被标度吸收）。A/B 实测 Rwp 逐位不变，这是接线正确性的硬检查。**R 必须实测给出**，给错比不给更糟 |
| 3 | **μ 表换 NIST 逐元素** | H…U（Z=1…92）8.000 keV 列，**不按 Z 外推**（L 边有 2.5 倍断崖）。顺带修 Fe 325→306、Mg 47→40.6 等六处抄录偏差 |
| 4 | **误差棒含 τ 传播** | `W = S·f/ΣS·f` 的闭式传播在微吸收下失效（τ 又依赖 W）→ 改数值雅可比；R→0 退化回闭式，差 1e-9 |
| 5 | **定量份额"判别峰守卫"** | 大胞相自带独立峰宽参数，能把失配整块摊平 → 给不存在的相 15.6 wt% 而 Rwp 还变好。新增 `PHASE_UNSUPPORTED` / `PHASE_FRACTION_UNVERIFIABLE` 两个码，**只报不自动删相** |
| 6 | **诊断"选谁上界面"** | 原来按字母序截前 4 条，三条噪声提示占满前三、把"这份 wt% 能不能用"挤掉。现在同级内结论类码优先，第 5 条起全量写进执行日志 |
| 7 | **内置矿物库 R-3c 坐标修复** | 方解石/刚玉 O 位少 `z=1/4` → 展开 48 位点（应 30），多相定量全错。修后与 pymatgen 逐峰 **0.0% 差**，主峰回到文献位 |
| 8 | **GSAS-II 桥三修** | 超时按相数自适应；新增样品位移与择优取向入口；**GOF 不再是 0**（2-1 实测 15.727，此前恒 0.00） |
| 9 | **PDF2-2004 重打包为 polyDB** | 旧 sqlite 通道（214 MB）退役 → polyDB **154 MB**、163,834 相，与 COD 两变体共用同一套 reader / 预筛 / 打分 |

- **三引擎对拍（13 试样，空载机）**：refinement 中位数 Rwp **17.46%**、最优 **7/13**。
- **测试**：全量 **2567 passed / 4 skipped / 0 failed**。
- **本版同时包含 v5.1 的全部七件**（v5.1.0 收口后未单独发布）。

---

## 上一版 v4.7.0（2026-10-31 · 已发布）

**序贯多相鉴定：确认一相 → 剩余峰再检索 → 再确认**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.7.0 与 [docs/序贯多相鉴定-v4.7.0.md](docs/序贯多相鉴定-v4.7.0.md)）：

- **候选列表确认即推进**：选中一行点「确认并继续检索」或直接双击 → 该相已解释的峰从问题里移除 → 自动对剩余未解释峰再检索 → 给出下一相候选。循环到没有峰可取相为止，每一相都由用户确认。
- **强度残差账本**（`services/sequential.py`，参考 XinMatch `core/search/sequential.py` 的思路按本项目模型重写）：按 count 空间最小二乘拟合每相比例因子，逐峰扣减 `I_obs − Σ scale·r`；残差降到自身强度 5% 以下才算"已解释"，只解释了一部分的峰带着剩余强度进入下一轮（重叠峰是真实物理）。弱于最强峰 1% 的线不参与检索也不计入覆盖率。
- **状态条 + 撤销**：`已确认 2 相 ｜ 剩余 12/25 峰 ｜ 已解释 84.3% 强度`；「撤销上一相」弹掉最后一相并按归还后的剩余峰重检索（撤到 0 相回到整谱检索）。已确认相留在谱图叠加里，不会因为新一轮残差检索被打回原形。
- **不换库**：数据源全程透传，首轮用外挂库则后续轮次都用同一份库；新候选自动剔除已确认相（`db_id` 优先判重）。
- **测试**：新增 `tests/test_sequential_phase.py` 22 例（账本/状态机/VM/视图四层），真实 3-1 试样冒烟通过（Zincite 82.6% → Hornblende +1.6% → 撤销精确回退）；全量回归 **1904 passed / 5 skipped / 0 failed**。
- **同时包含 v4.6.0**：外挂库不限数量/多种类型、选中即用于全部检索入口（详见下一节）。

| 产物 | 体积 | SHA-256（前 16 位） | 说明 |
|---|---|---|---|
| `PolyXRD-Setup-v4.7.0.exe` | 288.3 MB | `c7865dbff2258c2c…` | 正式版安装包（带注册），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.7.0-Portable.zip` | 430.7 MB | `f5e8d85ef1f227bc…` | 便携包（**内部评估版**），内置 COD-Inorg |
| `SHA256-v4.7.0.txt` | — | — | 以上两个产物的 SHA-256 |

> 已发布：[Release v4.7.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.7.0)（3 附件，不含数据库）。

---

## v4.6.0（2026-10-31 · 随 v4.7.0 一并发布，无独立安装包）

**外挂数据库：不限数量、多种类型、选中即用于检索**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.6.0 与 [docs/外挂数据库-多库挂载与选中检索-v4.6.0.md](docs/外挂数据库-多库挂载与选中检索-v4.6.0.md)）：

- **挂载类型注册表化**：内置 polyDB / PDF2 / 用户库降级为"种子类型"，新格式通过 `register_kind()` 接入后，自动判别、探测、列表展示与检索分发全部自动接上——**不再需要改源码里的 if/elif**。
- **不限数量**：同一类型可挂任意多份（内置盘 + 移动硬盘 + 自裁子集 + 同事导出的库），列表/下拉/持久化都没有上限；一次挂 60 份库的多库压力测试通过。
- **polyDB 元数据 + 重命名**：管理对话框显示数据集 / 变体 / 格式版本 / 构建日期；用户自加库可重命名；内置项的名字由类型/变体决定，不允许改。
- **选中即用于全部入口**：传统检索、快速识别、标记峰再匹配、**残差峰再检索**、**Profile Fitting**、**工具栏/菜单「识别」**、精修向导「检索库」与 **MCP** 全部跟随当前数据源。外挂库做 Profile Fitting 时先按该库 d-I 预筛 200 个候选，再做全谱拟合重排（52 万相逐相穷举不可行）。
- **修掉两个"选了却不是它"的 bug**：工具栏「识别」此前忽略数据源下拉、静默跑内置 118 相库；残差追查此前写死 `builtin`。另外，路径存在但库损坏时不再静默返回空候选，而是报"所选数据库无法用于检索"。
- **测试**：全量回归 **1881 passed / 5 skipped / 0 failed**；真实 3 份 polyDB 冒烟（挂载 → 选中 → 传统检索 / Profile Fitting → MCP 选库）全绿，见 `tools/smoke_v460_mounts.py`。

---

## 上一版 v4.5.0（2026-10-29 · 已发布）

**装机可靠性修复 + 元素限定错位（P0）** —— 全部来自 4.4.0 实机使用的现场反馈，无算法口径改动（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.5.0）：

- **装在 `Program Files` 下普通用户起不来（已修）**：`get_config()` 会对安装目录内不存在的 `cod_data/cif_db` 无条件 `mkdir`，普通用户无写权限 → `PermissionError` 抛在 `QApplication` 之前，窗口都出不来。现改为「项目内目录存在才用，否则降到 `~/.polyxrd/cif_db`」+ 目录创建一律容错；版本号也不再为打一行启动日志去提前触发配置单例。
- **PDF2 外挂库在只读目录/单文件拷贝下读不出（已修）**：只读打开改用转义后的 `file:` URI（路径含空格/`#` 时不再被截断），WAL 模式下自动降级 `immutable=1`；建库收尾改回 `journal_mode=DELETE`，**产物自包含单文件**。附带 `PDF2Database.close()` 与 `last_error`，打开失败不再静默返回 0 条。
- **元素限定后检不出物相（P0，已修）**：`polydb.ELEMENTS` 漏了 **Rh（Z=45）**，导致 Rh 之后所有元素位图平面整体错位一位 —— 查 W 实际读的是 Ta 的位图。**所有 Z≥45 的元素**（W/Ta/Pb/稀土/U…）的元素限定都受影响。补表后恢复；库文件无需重建（建库端一直正确）。
- **启动诊断不再误导**：区分「共享冲突」/「无写权限」/「本进程自映射」，不再把程序自己的 exe 报成"被占用，占用进程 = 自己"。
- **测试**：全量 **1776 passed / 7 skipped / 0 failed**；新增元素表守卫 54 例（跨周期 46 个 Z 锚点）、只读 SQLite 12 例。

---

## 上一版 v4.4.0（2026-10-27）

**精修向导重建「从检索库找结构」+ 旧库配置一次性清理** —— 兑现 v4.2 遗留的 P4.2/P4.3（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.4.0 与 [docs/RELEASE-NOTES-v4.4.0.md](docs/RELEASE-NOTES-v4.4.0.md)）：

- **向导新增首个页签「检索库（polyDB）」**：可输化学式 / 矿物名 / 空间群 / 编号查，也可**按当前图谱最强峰**做 Hanawalt d-I 匹配；加入的物相自带晶胞与原子位点，位点按空间群展开成全胞，可直接进精修。
- **旧库配置一次性清理**：启动时检测 `user_db_paths.json` 里的旧 `cod_*` 键与 `db_mounts.json` 里已删除引擎的条目，一键清理——**只删配置、不删任何库文件**；旧路径若其实是 polyDB 目录会顺手挂回。
- **i18n**：三语各新增 32 个界面文案键（键集 1058/1058/1058 对齐）。
- **无算法改动**：检索打分口径、精修引擎、报告生成与 v4.3.0 一致；MCP 工具面仍 21 个。
- **测试**：全量 **1764 passed / 6 skipped / 0 failed**；向导检索库面板 53 例、旧配置清理 37 例（其中 16 例是发布后第二轮独立复核补的钉子）。

| 产物 | 体积 | SHA-256（前 16 位） | 说明 |
|---|---|---|---|
| `PolyXRD-Setup-v4.4.0.exe` | 288.3 MB | `b25d973fbb8a26ec…` | 正式版安装包（带注册），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.4.0-Portable.zip` | 430.7 MB | `98c3f111a6d43e8e…` | 便携包（**内部评估版**），内置 COD-Inorg |
| `SHA256-v4.4.0.txt` | — | — | 以上两个产物的 SHA-256 |

> 已发布：[Release v4.4.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.4.0)（3 附件，不含数据库）。

---

## 上一版 v4.3.0（2026-10-27 · 已发布）

**polyDB d 峰检索回到 MCP** —— 兑现 v4.2.1 遗留项（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.3.0 与 [docs/RELEASE-NOTES-v4.3.0.md](docs/RELEASE-NOTES-v4.3.0.md)）：

- **新增 MCP 工具 `search_phases_by_d_peaks`**：按实测 d 值 / 强度做 Hanawalt 检索，支持 `tolerance`/`tolerance_rel`/`min_match`/`limit`/`elements`/`max_ref_peaks`，底层为 polyDB 位图倒排 + 精确打分。
- **旧名 `search_cod_by_d_peaks` 恢复功能**：保留旧签名转调 polyDB，不再返回 `deprecated`；补 `display_id`/`ref_id` 兼容字段与 `mounted` 状态。
- **同一套算法**：与 UI 物相识别、PDF2/用户库 d 峰检索共用 `phase_search` 打分口径；无挂载/损坏库/非法输入一律返回 JSON 错误而非抛异常。
- **测试**：新增 v4.3.0 MCP d 峰回归（真实库石英检索、元素过滤、无挂载/异常路径），MCP 工具数 20 → 21。

| 产物 | 体积 | SHA-256（前 16 位） | 说明 |
|---|---|---|---|
| `PolyXRD-Setup-v4.3.0.exe` | 286.8 MB | `59c62ce98970…` | 正式版安装包（带注册），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.3.0-Portable.zip` | 428.1 MB | `cb1ad1b6eed7…` | 便携包（**内部评估版**），内置 COD-Inorg |
| `SHA256-v4.3.0.txt` | — | — | 以上两个产物的 SHA-256 |

👉 **已发布**：[Release v4.3.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.3.0)（3 附件，不含数据库）。

---

## 上一版 v4.2.1（2026-10-26 · 已发布）

**v4.2.0 验收修复版** —— 4 项 P1 兼容/UX 修复 + 文档事实修正 + 构建/验收加固（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.2.1 与 [docs/验收报告-v4.2.0.md](docs/验收报告-v4.2.0.md)）：

- **MCP 旧名兼容恢复**：`search_cod_phases` 支持 `97-1011097`/`96-101-1097` 编号并回填 `ref_id`/`display_id`；`SiO2` 等化学式先规范化（→`O2 Si`）、空间群忽略空格（`Fd-3m`）；`get_cod_phase_details(cod_id)` 保留旧参数名；`search_cod_online` 网络异常返回 JSON 且 `timeout` 生效。
- **精修向导死 UI 清理**：删除已下线的 CIF 搜索框/按钮与死链路、三语死键；内置 12 矿物 + 外部 CIF 导入、COD 在线搜索、polyDB/PDF2/用户库候选结构补齐均保留。
- **文档修正**：基线 commit、tag/HEAD、净减行数、import 耗时、无改动表述等 10 项事实错误全部改正；设计与执行计划状态回填。
- **构建/验收加固**：`verify_release.ps1` 修复 `-SkipBundledDb` 参数缺失、SHA 时间稳定、新增 `-ExpectedFlavor`/`-CheckDistVersion` 硬校验 dist flavor/版本；internal 构建后自动清理 flavor marker；补 MCP/fail-open/启动日志/golden 测试。

| 产物 | 体积 | SHA-256（前 16 位） | 说明 |
|---|---|---|---|
| `PolyXRD-Setup-v4.2.1.exe` | 286.8 MB | `22ca6501cf39…` | 正式版安装包（带注册），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.2.1-Portable.zip` | 428.1 MB | `8a6bbc6ba756…` | 便携包（**内部评估版**），内置 COD-Inorg |
| `SHA256-v4.2.1.txt` | — | — | 以上两个产物的 SHA-256 |

👉 **已发布**：[Release v4.2.1](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.2.1)（3 附件，不含数据库）。

---

## 上一版 v4.2.0（2026-10-26 · 已发布）

**结构清理：旧 COD sqlite 运行时退役**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.2.0 与 [docs/RELEASE-NOTES-v4.2.0.md](docs/RELEASE-NOTES-v4.2.0.md)）：

- **旧运行时删除**：`services/cif_database.py`（2,421 行）与 `services/cod_local.py`（2,410 行）删除，`config` 的 `cod_db_path`/`cod_index_db_path`/`cod_svn_path` 字段与 6 个 getter/setter 一并移除。运行期只保留 **polyDB + PDF2 + 用户自建库**。
- **抽出三个纯模块**：`cif_utils`（CIF 解析/位点/元素判定）、`phase_search`（Hanawalt 打分 + 预筛）、`cif_minerals`（12 种内置矿物库）。三者不 import `sqlite3`/`PySide6`、不读配置路径（AST 断言），可直接单测。
- **行为零漂移**：`phase_search` 有搬迁**前**录制的 71 KB golden（12 用例，0 mismatch）；polyDB 检索基准与 v4.1.2 **逐样本等价**（13 试样候选 ids/names/名次全同，top1 9/49·top10 16·MRR 0.213，96.0 s vs 96.6 s）。
- **MCP 工具面**：新增 `search_phases_polydb` / `get_phase_details`；`search_cod_phases` / `get_cod_phase_details` 降级为转调别名（旧客户端不用改）；`search_cod_by_d_peaks` 返回 deprecated 提示（d 峰检索 2026-Q4 在 polyDB 上重建）。
- **测试收敛**：删 9 个旧库专用测试、迁 3 个，总数 1809 → **1628**；新增静态守卫 `tests/test_v42_structure.py` 防旧模块复活。12 个旧库维护脚本归档到 `tools/legacy_sqlite/`。

| 产物 | 体积 | SHA-256（前 16 位） | 说明 |
|---|---|---|---|
| `PolyXRD-Setup-v4.2.0.exe` | 288.3 MB | `e46bfa79b53c47b4…` | 正式版安装包（带注册），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.2.0-Portable.zip` | 430.7 MB | `7d9e504d7dda8c42…` | 便携包（**内部评估版**），内置 COD-Inorg |
| `SHA256-v4.2.0.txt` | — | — | 以上两个产物的 SHA-256 |

👉 **已发布**：[Release v4.2.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.2.0)（3 附件，不含数据库；远端 digest 与本地清单逐件一致）。

> 上一版 v4.1.2（开箱即检索 / 默认库发现优先级 / 旧库迁移提示 / 纯客户端小包验收）详见 [CHANGELOG §4.1.2](docs/CHANGELOG.md)。

---

## 更早版本 v4.1.1（2026-10-24 · 已发布）

**hotfix：默认库精修正确性 + 干净安装外部引擎 + 构建可复现 + 发布政策收口**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.1.1 与 [docs/代码评估-v4.1.0.md](docs/代码评估-v4.1.0.md)）：

- **修复默认库精修模拟峰错误（P1）**：polyDB 侧车存的是**非对称单位**位点，v4.1.0 当全胞直构 → 高对称相出现假峰。v4.1.1 在出口按空间群展开（幂等）并在精修侧兜底；Corundum 实测由「6.8°/100% 假峰」恢复为 **57.49/43.34/35.14** 真主峰。
- **干净安装也能用 GSAS-II / MAUD（P1）**：只有内置 polyDB、没有 CIF 文件时，resolver 现从原子位点反生成 CIF 落盘并回填 `cif_path`（实测 1.3 ms → 4 ms，`structure match 1/1`）；CIF 导出同样支持位点回退。
- **构建可复现（P0）**：`scripts/_build_post.py` 曾被 `.gitignore` 吞掉、从未入库（fresh clone 构建必丢内置库/VERSION/便携 extras）；现已强制入库 + 守卫测试，并把 bundle/db-layout/version/portable-extras/验收全部改为**硬失败**。
- **发布政策收口**：主仓库 Release **只发程序 3 附件**（Setup + Portable + SHA256），**不再上传数据库包**；默认库已内置，扩展库统一在 [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase) 的 Releases 分发。
- **文档勘误**：内置库相数统一为 **77,500**（与内置库 `meta.json` 一致）；README-EN 同步到 v4.1.1。

| 产物 | 体积 | SHA-256（前 16 位） | 说明 |
|---|---|---|---|
| `PolyXRD-Setup-v4.1.1.exe` | 286.8 MB | `8a57d36f339b…` | 正式版安装包（带注册），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.1.1-Portable.zip` | 428.2 MB | `257909776e54…` | 便携包（**内部评估版**：状态栏红字「内部评估版本」），内置 COD-Inorg |
| `SHA256-v4.1.1.txt` | — | — | 以上两个产物的 SHA-256 |

👉 **已发布**：[Release v4.1.1](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.1.1)（3 附件，不含数据库；远端 digest 与本地清单逐件一致）。

> PDF2-2004 为 ICDD 版权库，永不出现在 Release 里；两个 polyDB 库包在 [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases) 分发。

---

## 上一版 v4.1.0（2026-10-23 · 已发布）

**COD-Inorg 成为唯一内置默认库 + 旧格式运行期代码全部删除**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.1.0）：

- **开箱即检索**：便携包与安装包**内置** `COD-Inorg-20261021.polyDB`（77,500 相 / 86 MiB，8 个分段文件），
  解压/安装后直接检索，不再需要先下载库包再挂载。`POLYXRD_NO_BUNDLE_DB=1` 可退化为"纯客户端小包"。
- **旧格式运行期代码删除**：`DB_KINDS` 只剩 `pdf2`；`cod_inorganics` / `cod_index` / `xinmatch` 三个旧槽位与
  `services/xinmatch_db.py` 一并移除，`phase_identifier` 的 6 个旧入口删除 —— 检索统一走 `identify_with_polydb`。
- **内部评估版标识**：状态栏最右端用**红色加粗**字显示「内部评估版本」（`#d32f2f` + `font-weight: bold`，
  挂在控件自身 stylesheet 上，换主题不掉色）。
- **回归**：全量 **1565 passed / 6 skipped**（8m20s）。

| 产物 | 体积 | SHA-256（前 16 位） | 说明 |
|---|---|---|---|
| `PolyXRD-Setup-v4.1.0.exe` | 288.3 MiB | `d3ae6891c42442fc…` | 正式版安装包（带注册），**内置 COD-Inorg 库**；不含便携版辅助文件 |
| `PolyXRD-v4.1.0-Portable.zip` | 430.7 MiB | `fa6be55174df08f7…` | 便携包（**内部评估版**：状态栏红字「内部评估版本」），内置 COD-Inorg 库 |
| `SHA256-v4.1.0.txt` | — | — | 程序产物的 SHA-256（数据库包自 v4.1.1 起不在主仓库发布） |

👉 **已发布**：[Release v4.1.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.1.0)

> PDF2-2004 为 ICDD 版权库，永不出现在 Release 里；COD-Full 等扩展库在 [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase) 的 Releases 分发。

---

## 上一版 v4.0.0（2026-10-23 · 已发布）

**自研外挂物相库格式 polyDB —— 更小、更快、候选剪枝可证**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §4.0.0 与 [docs/外挂库格式规范-polyDB-v4.md](docs/外挂库格式规范-polyDB-v4.md)）：

- **新格式**：`.polyDB` 目录容器 = `meta.json` + `index.sqlite` + 列存二进制（`peaks_d.f32` / `peaks_i.u16`）+ d 分箱位图倒排（`bins.u8`）+ 元素位图（`elem.u8`）+ 位点侧车（`sites.bin` / `sites_off.i64`）。全程只读 mmap 打开、零启动解析，检索链**从不写库**。
- **两个实测库**：`COD-Inorg-20261021.polyDB` **77,500 相 / 89.9 MB**（旧 sqlite 无机库 1,194.5 MB / 71,199 相 → 体积 **13.9×** 更小、相数还更多）；`COD-Full-20261021.polyDB` **521,361 相 / 1,107.7 MB**。
- **速度**：COD-Inorg 端到端检索 **0.5~0.7 s/样本**（旧 sqlite 链路 6.3~11 s）；COD-Full **约 2 s**（同条件下全量暴力打分 45~53 s）。
- **准确性**：13 个基准试样 × 全库暴力打分逐条比对，`search` 的 top-100 **完全等于**无剪枝暴力结果 —— 覆盖了「5-1 试样曾掉 3 个物相」的旧剪枝缺陷回归。
- **列表式外挂库管理**：一行 = 一个已挂载的库，**同类型可挂多份**（内置盘一份 + 移动硬盘一份 / 自裁子集 / 同事导出的库），任意文件夹指过去即可；「设为当前」显式决定用哪一行检索；老的四类配置槽位**零迁移**自动出现在列表里。
- **检索链路显式路径**：`polydb` / `cod_inorganics` / `cod_index` / `pdf2` / `xinmatch` 均可传 `db_path`，同类型多份库各查各的；顺带修掉「显式路径污染实例状态 → 切库后仍在查旧库」的串库缺陷。
- **同步完成一轮全量代码评估**（9 项 P0/P1 + 一批 P2，全部带回归测试）：默认寻峰误走联合拟合（14.2 s → 11 ms）、savgol/median 窗口越界崩溃、moving 平均端点掉 45%、欧式小数被当千位分隔（10× 静默误差）、PDF2 覆盖率每次重算（0.23 s → 缓存后 0.014 s）、SVG 导出的 NaN/退化轴、i18n 缺失键无回退、MAUD 临时目录泄漏、CIF 缓存目录不可写时静默丢结构等。

> 📦 数据库仍为外挂，不随分发；PDF2-2004 为 ICDD 版权库，永不出现在 Release 里。

👉 **已发布**：[Release v4.0.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.1.2) —— 3 个附件（Setup 249.1 MB / Portable 389.0 MB / SHA256）已上传并核验（远端 digest 与本地逐件一致）；**数据库不在本仓库发布**，统一由 [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase) 仓库的 Releases 分发。
> 完整构建/产物/验收记录：[docs/发布检查清单-v4.0.0.md](docs/发布检查清单-v4.0.0.md)。

| 产物 | 体积 | SHA-256（前 16 位） |
|---|---|---|
| `PolyXRD-Setup-v4.0.0.exe`（正式版安装包，带注册，不含数据库） | 249.1 MB | `b467e8d747bebee9…` |
| `PolyXRD-v4.0.0-Portable.zip`（正式版便携包，解压即用） | 389.0 MB | `9c4e99e9bcad84c7…` |
| `PolyXRD-v4.0.0-Databases-COD-inorg-polyDB.zip`（无机物库 77,500 相；**本地归档，未随 Release 发布**） | 48.1 MB | `d9e57d11ced3082e…` |
| `PolyXRD-v4.0.0-Databases-COD-full-polyDB.zip`（全库 521,361 相；**本地归档，未随 Release 发布**） | 710.3 MB | `191246b7ee2bcc10…` |

> 完整校验值见 `SHA256-v4.0.0.txt`（构建时生成，发布前已逐件复核）。
> 发布验收：全量回归 1567 passed / 6 skipped / 1 failed（唯一失败为本机 LibreOffice 环境限制，
> 改动前即失败）；便携包解压 13,151 文件无业务数据库、离屏启动 `shown visible=True`、crash 日志 0；
> 两个 polyDB 库 `polydb_verify` 全绿；功能冒烟 10/10。

## 📚 上一版 v3.2.0（2026-10-20）

**大库可用性修复：让 20~30 GB 级的外挂物相库真正能用**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §3.2.0 与 [docs/3COD数据库验收报告-20261020.md](docs/3COD数据库验收报告-20261020.md)）：

- **修掉「挂了库却用不上」**：全库索引的路径解析一度只认"索引就在 COD 目录旁边"，**从不看**用户导入的路径 —— 「外挂数据库管理…」显示已挂载，检索却还在读旧库、或恒定判为不可用。现在读路径优先用户导入，写路径（重建索引）则明确不认，避免把外挂库当自家索引写。
- **检索改用只读连接**：旧实现每次查询都以**可写**方式打开索引并跑一遍建表/迁移 DDL。在 28 GB 的库上，`is_ready()` 要 **65 s** 且返回 False，`stats()` 直接报 `database is locked`。修后分别是 **0.013 s / 0.125 s**，连接复用且异常不再泄漏（"第一次超时、第二次报锁"的根因）。
- **建索引进度反馈**：百万相级的外挂库首次挂载要建 5~10 min 的强峰索引，此前界面只有一句静态提示、看起来像死机。现在按 **清点相数 → 建强峰索引 → 读元数据** 三阶段在状态栏实时报进度。
- **实机复测**（3COD-Full，28.17 GiB / 195.9 万相）：`identify_with_cod_local` 8~13 s，top1 与真值一致；库文件 size/mtime **零变化**。
- **一个使用提醒**：库不是越大越好。实测把 118.6 万相的库挂成 COD 无机物库后，4-1 试样的 CaF₂ 从第 2 名掉出 top20 —— 这是候选池放大 16.7× 的**排序稀释**，不是检索缺陷。日常用与体系规模匹配的库，超大库留给"怀疑含罕见相"的兜底。

> 📦 数据库仍为外挂，不随分发；PDF2-2004 为 ICDD 版权库，永不出现在 Release 里。

👉 [下载 v3.2.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v3.2.0)（正式版安装包 + 内部评估版便携包 + SHA256）

## 📚 v3.1.0（2026-10-18）

**XinMatch 格式库支持 + 任意位置挂载 + 全量 review 修正**（详见 [docs/CHANGELOG.md](docs/CHANGELOG.md) §3.1.0 与 [docs/code-review-2026-10-18.md](docs/code-review-2026-10-18.md)）：

- **XinMatch 格式库**：Data source 下拉新增第 7 项，可直接挂载第三方 `entries` / `peaks` / `elements` / `element_combo` 四表结构的库文件（实测 71,206 / 112,734 条目），**无需转换**。检索口径与 COD 无机物库逐项一致 —— 同一套 Hanawalt 度量 + 同一套 FOM 排序；单测用同数据造 PolyXRD `phases` 库做双实现比对，14 个度量字段（`abs=1e-12`）与排序完全一致。
- **速度**：没有照直觉在 `peaks.d` 上做 SQL 区间扫描 —— 该库 d 轴极密，±0.02 Å 窗口约 2.5 万条峰，20 个测量峰实测 **9 s**，比现有链路还慢。改为一次建「每相最强 12 峰」索引（约 3 秒，缓存到 `~/.polyxrd/cache/`，键 = 路径 + size + mtime），之后**每次检索 0.37~0.57 s**（COD 无机库链路 0.8~5.5 s）。
- **能力边界**：该库不含 CIF，候选只有晶胞没有原子坐标 —— 可检索 / 核对，**不能直接进结构精修**（UI 提示与三语文案已写明）。
- **任意位置挂载**：库文件放哪个文件夹都行，不必再搬进程序目录。「外挂数据库管理…」新增「挂载数据库文件…」「挂载文件夹…」，后者会把该目录下所有合格的库**一次全挂上**（只扫本层，`.bak` 备份自动跳过，同类多份按优先序挑）。
- **修掉 6 个会出错结果的缺陷**（本轮全量 review 的 P0 项，每项都有前后实测）：背景扣除把"像素半窗 w"当数值阈值算（峰心背景 898 → **103.8**，真值 100；扣背景后峰高保真 2.2% → **99.5%**）；高斯平滑未归一（常数谱 100 → 459.21 修为 **100.000**）；Kα2 剥离移位方向反了（卫星峰 520 → **15.2**）；4 条检索链不读数据自身波长（Co/Fe/Cr/Mo 靶原先连前 5 都进不去，现**全部 Top-1**）；GUI 预处理下拉 label↔key 错位致 9 个入口全抛错；四方/六方指标化量纲错。另加精修向导「快速档」（1.97 s → **0.34 s**，wR 不变）。

> 📦 数据库仍为外挂，不随分发；PDF2-2004 为 ICDD 版权库，永不出现在 Release 里。

👉 [下载 v3.1.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v3.1.0)（正式版安装包 + 内部评估版便携包 + SHA256）

**上一版 v3.0.0**（WPSM 全谱拟合检索，默认关闭）：👉 [下载 v3.0.0](https://github.com/PolyXRD/PolyXRD/releases/tag/v3.0.0)

---

## 🔑 注册与授权

**用户怎么注册**（正式发布版）

1. 把贵单位/部门的名称发给 `sshztx@outlook.com`；
2. 收到注册码后在软件里点菜单 **帮助 ▸ 输入注册码…** 粘贴并确定；
3. 注册成功后主窗口底部**状态栏最右侧**会常驻显示 `已注册：<单位部门名称>`，此后启动不再提示。

未注册时每次启动会弹出提示框：**「本软件未注册，版权所有，禁止用于商业用途。如需注册请联系 sshztx@outlook.com」** —— 点「确定」可继续正常使用（仅提示，不限功能），点「输入注册码」则直接注册。

**开发方怎么签发**（不随软件分发）

```bash
python scripts/make_reg_code.py "某某大学材料学院"        # 单个
python scripts/make_reg_code.py -f units.txt             # 批量（每行一个单位名）
python scripts/make_reg_code.py --verify PXRD1-XXXX-...  # 校验并回显单位名
```

**安全级别**：离线混淆级 —— 密钥随软件分发、可被逆向提取，定位是「告知版权 + 自助注册」，而非强反盗版。同一注册码可在同一单位的多台电脑使用（不绑机器码、不需要联网）。需要按机器/按应用强绑定时请联系作者。

**内部评估版**：`scripts/set_build_flavor.py internal` 之后再打包即可产出；该变体不含任何注册 UI，状态栏显示 `内部评估版本`，仅供内部自用，**请勿对外分发**。

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
  - **内置引擎 `builtin`（GUI 短路径默认）** = **免结构全谱拟合（Le Bail 级，快）**：用 CIF `|F|²` 参考峰 + 每相各向同性晶胞缩放
    + March-Dollase 织构 + Chebyshev 背景 + 统计权，无需安装外部程序即可给出可用的 wR/Rp；
    它**不精修原子坐标/占位/ADP**，因此其 wt% 为**相对定量**而非严格质量分数。
  - **v5.0.0 新引擎 `polyxrd.refinement`（已接入 GUI，引擎下拉选 `refinement`）**：自带完整前向模型 —— Cromer–Mann 散射因子、
    `I ∝ m|F|²·LP/V²` 强度口径、Kα2 双线分离、TCH 峰形合成、晶粒/应变展宽、`w=1/max(y,1)` 泊松权；
    解算走**变量投影**（标度 + 背景每轮闭式最小二乘）+ 分阶段协议（峰位 → 峰形 → 择优 → 样品展宽 → 结构），
    逐段回滚 + 提前收敛；定量用 Hill–Howard **密度口径**（`W ∝ S·M_cell/V`）并带标度误差传播；
    自带 GSAS-II 口径的四元诊断（秩亏 / 条件数 / 参数相关 / 残差峰无对应反射），
    并按空间群自动约束胞参（常量用固定、`b=a` 这类跟随关系进约束表）。
    真实试样验收见 [docs/基准报告-精修-v5.0.0.md](docs/基准报告-精修-v5.0.0.md)：
    四相试样定量合计绝对偏差 **7.16 pp**（存量引擎 21.40 pp），两相 50/50 标样 **±2.00 pp**。
    ⚠️ 该引擎按**结构因子**算强度，因此**每个相都必须带原子位点**。检索直通场景（内置矿物表 / PDF2 /
    部分用户库条目只有参考峰）会**自动补齐位点**：按 化学式 + 空间群 + 晶胞 三道门到 polyDB 找同一条目，
    取其全胞位点（`services/structure_augment.py`，日志 `[cif] <相>: 补齐位点 ← polyDB COD xxx`）。
    仍补不上的相才回退内置引擎，并在结果区给出「引擎回退」诊断（不会静默换引擎）。
    实测 2-1 两相直通：Rwp 21.12%、wt% 47.99/52.01（真值 50/50）。
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

### ⑥ 外挂检索服务（polyDB / COD / PDF2 / XinMatch，列表式挂载）
| 库 | 规模 | 作用 |
|---|---|---|
| COD 无机物库 | 71,199 物相 | 预计算 d-I 峰 + 预截断强峰列 + Hanawalt 预筛，**主检索库**，速度最快。默认发布**瘦身索引式**（362 MB，`COD_inorganics_index.sqlite`）：原子位点完整保留，CIF 由本地 `cod/cif` 目录按需读取，缺失时自动回退 COD 在线接口下载。完整内嵌版（1.19 GB）仍可导入，两者数据逐行一致 |
| COD 全库索引 | 113,223 条目 | COD 全量 CIF 索引（432 MB，不内嵌 CIF），用于「COD 全库」与「内置+全库合并」两个检索源 |
| PDF2-2004 库 | 163,834 物相 | ICDD PDF-2 2004，自带空间群与晶胞，用于与商品库对照 |
| XinMatch 格式库 | 自备（71,206 / 112,734 条目） | **第三方格式兼容**：直接挂载 `entries`/`peaks`/`elements`/`element_combo` 四表的库文件，无需转换。检索口径与 COD 无机物库逐项一致（同一套 Hanawalt 度量 + 同一套 FOM 排序），首次检索自动建强峰索引（约 3 秒，之后每次 ~0.4 秒）。该库**不含 CIF**：候选只有晶胞没有原子坐标，可用于检索与核对，不能直接进结构精修 |
| polyDB 外挂库（v4.0.0） | 自备（实测 77,500 / 521,361 相） | PolyXRD 自有列存格式：`meta.json` + `index.sqlite` + 峰矩阵 + d 分箱位图 + 元素位图 + 位点侧车。**只读 mmap、零启动解析**，检索时只解候选行；命中相带非对称单位位点，可直接进精修。目录容器放任意路径，挂载即用 |

- **任意位置挂载**（v3.1.0）：库文件放在哪个文件夹都行，不必搬进程序目录 —— 在「外挂数据库管理…」里点「挂载数据库文件…」直接指过去即可，路径记进 `~/.polyxrd/user_db_paths.json`，下次启动自动加载；点「挂载文件夹…」时会自动把该目录下所有合格的库**一次全挂上**（只扫本层，`.bak` 备份文件会被跳过）
- 路径优先级：**GUI 挂载的持久化路径 (`~/.polyxrd/user_db_paths.json`) > 默认位置（存在才用）> `~/.polyxrd/cif_db/` 兜底**
- 导入时自动**校验库类型**：COD 无机物与 PDF2 都叫 `phases` 表，选错槽位会提示而非静默失败；XinMatch 格式库按"四表齐全 + 特征列"判别，半成品库（只有 `entries` 没有 `peaks`）会被拒绝
- 导入后立即生效，**无需重启**；物相分析面板的「数据库源」下拉同步刷新，未挂载的源自动置灰
- 各库完全独立，可只装其中一个；默认库 COD-Inorg **已内置**（77,500 相），另有内置 **106 种参考物相**兜底
- **数据库从哪下载**（v4.1.1）：程序仓库与 Release **只发程序（3 附件）**；默认库 COD-Inorg **已内置**，无需下载；扩展库（COD 全库等）统一在 [PolyXRD-DataBase 的 Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases) 发布（当前 tag `20261021`，以该仓库页面为准），构建工具与格式规范也在这个仓库。

---

## 🚀 使用方法

### 方式 A · 普通用户 (推荐, 无需 Python)

```
① 下载 PolyXRD-Setup-vX.Y.Z.exe (Windows x64) 或 Portable 便携包（解压即用）
   ↓
② 安装 (默认 C:\Program Files\PolyXRD\) 后直接运行 PolyXRD.exe
   ↓
③ 按需下载数据库包 —— 到 PolyXRD-DataBase 仓库的 Releases 下载（各库独立）
   https://github.com/PolyXRD/PolyXRD-DataBase/releases
   解压到任意目录（必须真正解压到磁盘，不要直接在压缩包里打开）
   ↓
④ 启动 PolyXRD → 菜单「数据库 ▸ 外挂数据库管理…」→「挂载文件夹…」指向解压出的
   `.polyDB` 目录 → 选中该行点「设为当前」
   → 立即生效，无需重启
   ↓
⑤ 开始使用!
```

> **发布口径**（v4.1.1，已发布）：本仓库 Release **恒 3 附件** = **Setup 安装包（286.8 MB）+ Portable 便携包（428.2 MB）+ SHA256**，
> **不含任何数据库**。数据库统一在 [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase) 仓库的 Releases 分发：
> COD-Inorg（48.1 MB / 77,500 相）与 COD-Full（710.3 MB / 521,361 相）。
> PDF2-2004 为 ICDD 版权库，**任何仓库都不分发**，需要时自行准备库文件。

> **polyDB 库说明**：`.polyDB` 是**目录容器**（列存峰矩阵 + 位图倒排 + 原子位点侧车），
> 下载后解压即用、离线可跑，原子位点在库内（命中相可直接进精修），不依赖 `cod/cif` 目录
> 或联网取 CIF。旧 sqlite 库（瘦身索引式 / 完整内嵌版 / PDF2 / XinMatch）仍可照旧挂载。

> **关于 PDF2-2004 库**：该库为 ICDD 商品数据库，**受版权保护，本仓库不分发、Release 不提供下载**。
> 持有正版授权的用户可自行准备 `PDF2_2004.sqlite` 并在「外挂数据库管理…」中作为 PDF2 槽位导入；
> 未授权时该槽位留空即可，其余功能不受影响。

> 内置 COD-Inorg 默认库（77,500 相）开箱即可检索；另有 **106 种**常见参考物相兜底。
> 详细说明与排错见上方各段落（外挂数据库管理对话框各槽位已自带说明）。

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
Inno Setup 编译安装包 → 打便携包 → **本地**生成并校验两个 polyDB 库包（对外发布在 PolyXRD-DataBase 仓库，不在本仓库 Release）→ 计算 SHA-256。

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

最新版本与全部变更记录见 [docs/CHANGELOG.md](docs/CHANGELOG.md)；**程序产物**（Setup 安装包 + Portable + SHA256）前往 [👉 Releases 页面](https://github.com/PolyXRD/PolyXRD/releases/tag/v4.0.0) 下载。**数据库产物统一在独立仓库** [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases) 发布（本仓库 Release 不含数据库）。SHA-256 校验值随各自 Release 发布，下载后建议核对。

---

## 📝 版本兼容性 & License

| PolyXRD | COD 无机物库 | COD 全库 / 扩展库 | PDF2-2004 |
|---|---|---|---|
| **4.1.x（当前）** | **内置** `COD-Inorg-20261021.polyDB`（开箱即检索）；扩展库 `COD-Inorg` / `COD-Full` 的 polyDB 在 PolyXRD-DataBase 仓库分发 | `COD-Full-<日期>.polyDB`（外挂，PolyXRD-DataBase 发布） | 用户自行准备（ICDD 授权，仓库不分发） |
| 4.0.x | polyDB 外挂（Inorg / Full，均在 PolyXRD-DataBase 发布）；旧 sqlite 索引库仍可挂载（兼容保留） | 同左，或旧 `…-Databases-COD-full-index.zip` | 用户自行准备（ICDD 授权，仓库不分发） |
| 3.2.x 及更早 | `…-Databases-COD-inorg-index.zip`（瘦身索引式，旧 sqlite） | `…-Databases-COD-full-index.zip` | 用户自行准备（ICDD 授权，仓库不分发） |
| 2.x / 1.x | `…-Databases-COD-inorg-index.zip`（瘦身索引式, 默认; 内嵌版仍可导入） | `…-Databases-COD-full-index.zip` | 用户自行准备（ICDD 授权，仓库不分发） |
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
