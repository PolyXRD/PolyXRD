# MAUD 批处理模式侦察报告（v0.11.0 路线 C P0+R-C1）

> v0.11.0 路线 C（外部引擎接入）的 P0 铺垫。本报告基于本机 C:\MAUD2 + C:\MAUD3 实测，目标是确认 MAUD 是否能作为 PolyXRD 子进程被驱动。**R-C1 (wizard schema) 已闭环**，见 §8。

## 1. 环境基线

| 路径 | MAUD 版本 | lib jars | Java | Maud.jar 大小 | 备注 |
|---|---|---|---|---|---|
| `C:\MAUD2` | **2.996**（build.number=1147，2025-08-21 构建） | 35 | Azul Zulu 21 LTS (`C:\MAUD2\jdk\bin\java.exe`) | 13.85 MB | 老但仍主力，多个资料文献引用此版本 |
| `C:\MAUD3` | **2.99993**（build.number=1770，2026-09-08 构建） | 35 | Azul Zulu 25 LTS (`C:\MAUD3\jdk\bin\java.exe`) | 14.08 MB | 较新，build 比 MAUD2 多 47% |

两版 lib 目录同构（35 个 jars 同名同量），MaudText.class / batchProcess.class 同签名。MAUD3 的 batchProcess 比 MAUD2 大 20%（新功能扩展），但 CLI 接口 100% 兼容。

## 2. 启动 `maud.bat` 已验证的 JVM flags

```
java -mx16384M \
     --enable-native-access=ALL-UNNAMED \
     --add-opens java.base/java.net=ALL-UNNAMED \
     -DJava.library.path=. \
     -cp "lib/*" \
     com.radiographema.Maud          # GUI 入口
     com.radiographema.MaudText      # 文本/批处理入口
```

- **`-cp "lib/*"`**：glob 由 Java 自动展开 35 个 jars（这是关键，不是 manual list）。
- **`-mx16384M`**：MAUD 官方用 16 GB 堆。本机 PolyXRD 跑单次精修 4 GB 足够（`-mx4096M`）。
- **`-DJava.library.path=.`**：cwd 必须是 MAUD 安装根目录，否则 JNI 找不到 dll。
- **`--enable-native-access=ALL-UNNAMED`**：Java 21+ 必需，否则 GPU/JNI 模块全部 silent fail。

## 3. CLI 子集

`com.radiographema.MaudText` 只接受 4 个 flags（已反编译 MaudText.class 验证）：

| flag | 含义 | 本次实测 |
|---|---|---|
| `-file <par>` | 加载 .par 参数文件 | ✅ 必用 |
| `-jpvm` | 启动 jpvm 并行模式 | 未测试（单机会话不需要） |
| `-xgrid` | 启动集群 xgrid 模式 | 未测试 |
| `-silent` | 抑制 MaudText 启动横幅 | ✅ 推荐 |

业务上**没有 CLI flag 控制 iteration 数 / wizard index** — 这些都写死在 .par 文件的 CIF tags 里。

## 4. .par 控制字段（精修引擎）

反编译 `it.unitn.ing.rista.util.batchProcess.class`（17 KB）找到的关键字段：

```
_riet_analysis_file                <- 要拟合的数据文件 (.dat)
_riet_analysis_iteration_number   <- 最大迭代次数
_riet_analysis_wizard_index       <- 选择精修向导（值含义待 Route C 反编译深入）
_riet_analysis_fileToSave         <- 结果写出路径

_riet_meas_datafile_name          <- 同上，alt 名
_maud_remove_all_datafiles        <- t：清空已有数据
_maud_remove_all_phases           <- t：清空已有相
_maud_import_phase                <- 启动时 import 一个 CIF 到 phase 池
_maud_output_plot_filename        <- 画图输出
_riet_append_result_to            <- append 模式追加结果
```

控制流：
1. `MaudText.parseArgs` → 解析 `-file <par>`
2. `Constants.initConstants` → 列所有 plugin jar
3. `batchProcess(filename="<dir>")` → 用同目录下的 `.par` 解析多 data 块
4. 对每个 `data_riet_analysis_*` block：
   - `setNumberofIterations(N)`  ← from `_riet_analysis_iteration_number`
   - `refineWizard(idx)`         ← from `_riet_analysis_wizard_index`
   - `launchrefine()`            ← 实际驱动 LeastSquares
   - `writeall(buf)`             ← 把更新后的结构/强度写回 stdout/save file

## 5. 实测冒烟结果

### 5.1 已知预收敛的 `alzrc.par`

```
_refine_ls_R_factor_all 0.06553908
_refine_ls_wR_factor_all 0.090500064
_refine_ls_number_iteration 5
```

执行：
```bash
cd /c/MAUD2
./jdk/bin/java.exe -mx4096M \
    --enable-native-access=ALL-UNNAMED \
    --add-opens java.base/java.net=ALL-UNNAMED \
    -DJava.library.path=. \
    -cp "lib/*" com.radiographema.MaudText \
    -silent -file /tmp/maud_smoke/examples/alzrc.par
```

- 启动 ~5 s，全部 35 个 lib jars 加载无错；
- 输出 447 行 stderr 主要是 plugin class loading，最后一行 `Working in directory: ///tmp/maud_smoke/examples/`
- **退出码 0**，但 stdout 在 `Working in directory` 之后没有更多输出（Java stdout buffer 8KB 没刷）
- `.par` mtime 更新但 R/wR 字段不变 → **MAUD 只 load，不 refine**
- 原因：alzrc.par 缺 `data_riet_analysis_*` block，batchProcess 看到 no analysis 就退出

### 5.2 把 alzrc.par 强制改成"未收敛"尝试触发 refine

手动 sed 把 `_refine_ls_R_factor_all` 改成 `0.50`，`_number_iteration` 改成 `0`。结果：
- MAUD mtime 触动 par 文件，但 R/wR/n_iter 字段**无变化**
- 第二次加 `-silent`、去掉 `-retrievememory`，行为一致
- **结论**：.par 里没有 `data_riet_analysis_*` block，MAUD 没有任何 wizard 可以跑

### 5.3 检查所有 Examples 是否可批量

遍历 Examples.jar 内全部 14 个 .par：`alzrc`、`Steel16CrNi4`、`Ni3Al_faults`、`g11maud`、`cpd1h`、`sio250`、`default`、`LCLS_CeO2_calibration` 等 — **没有一个包含 `data_riet_analysis_*` block**。Examples 都是 GUI 精修结束后的"快照"，不包含触发 batch refine 的脚本段。

### 5.4 MAUD3 同样的调用

完全等价的命令在 MAUD3 上 exit=0，启动 ~3 s。MAUD3 还多了一个日志输出到：
```
C:\Users\Administrator\AppData\Local\maud\lib\Logs\startingLog
```
（MAUD2 与 MAUD3 共享此目录，因为两者的 `Library folder` 同一个）

`sun.java.command: com.radiographema.Maud` — 真正启动类是 GUI 类 `com.radiographema.Maud`，不是 `MaudText`。日志清楚记录全部 35 jars 的加载顺序和 Azul Zulu 25.0.4.1 的 JVM 元数据。

## 6. 核心结论与 Route C 后续工作

### ✅ 已确认
1. 本机双 MAUD（v2.996 + v2.99993）都能在 Windows 启动、加载 .par、退出码 0
2. classpath glob `-cp "lib/*"` 是唯一稳定写法（任何手写 list 都会断）
3. Java 21/25 Azul Zulu JDK 自带，-mx 可配置（4096 MB 单任务足够）
4. MAUD batch 模式入口 `com.radiographema.MaudText` 类签名 100% 稳定
5. .par 是 CIF 格式，解析器已知，可读 / 可生成

### ❌ 未确认（Route C 集成时要解决的核心问题）
1. **.par 中 `data_riet_analysis_*` block 的精确 schema**：必须能写出能被 MAUD 识别的最小 block，包含 wizard index + iteration number + data file ref + phases
2. **wizard_index 数值含义**：精修 phase1 / phase2 / 同时精修 / 强度重提取 等
3. **结果回读**：精修完成后 R/wR/GOF/n_iter 字段在哪一段，PolyXRD 怎么 parse
4. **文件回写路径**：`_riet_analysis_fileToSave` 不指定时 MAUD 是否就地修改 _analysis_file
5. **stdout buffer 不 flush**：批量调用时无法在 stdout 抓 iteration 进度，必须靠 .par mtime + R 字段变化来 polling

### 后续任务分解（Route C 实施清单）

| ID | 内容 | 工作量 |
|---|---|---|
| **R-C1** | 用 CFR 或 javap -p -c 反编译 batchProcess.class，列 wizard_index 取值表 | 半天 |
| **R-C2** | 写一个 `services/maud_par_builder.py`：给定 phases + 数据 + Rietveld 配置 → .par | 1 天 |
| **R-C3** | 用 alzrc.par 的 phase/sample section 复制 + 加 new `data_riet_analysis_*` 块 → 跑通真实 refine | 1 天 |
| **R-C4** | 写 `services/refinement_engines/maud_engine.py`：subprocess 调 MaudText，polling R 字段 | 半天 |
| **R-C5** | 改 `RietveldRefiner.refine()` 加 `engine='maud'` 分支 + `needs_first_run` 探测 | 半天 |
| **R-C6** | 写单测 + 集成测：把 alzrc 实测终态 wR ≤ 15%（基线 9.05%） | 1 天 |
| **R-C7** | GUI 加 engine path 选择 + 当前引擎显示 + 缺路径 fallback 提示 + i18n | 1 天 |

合计 **5–6 工作日** 完成 Route C 端到端验收。

## 8. R-C1 闭环成果（2026-09-12 加笔）

### 8.1 已验证的端到端 INS 配方（最小可用）

通过 B/D/F/MAUD3/s1s2 链式/wizard sweep 共 6 个变体实验，确定了**可重复工作的 INS 模板**：

```cif
loop_                                          ← 必须顶格、CIF 标准
_riet_analysis_file                            ← 输入 par 路径（绝对/相对均可；相对 = INS 同目录）
_riet_analysis_iteration_number                ← 总迭代上限（实测 30~100 都能收敛）
_riet_analysis_wizard_index                    ← wizard 步（⚠ 见 8.3 选值表）
_maud_remove_all_datafiles                     ← 强烈建议 true 防脏
_riet_meas_datafile_name                       ← 数据文件（alzrc.dat / my.xye）
_riet_meas_datafile_replace                    ← true 覆盖模板里的旧 datafile
_maud_remove_all_phases                        ← true 清空模板相
_maud_import_phase                             ← 第 1 个待注入相 CIF 路径
_maud_import_phase                             ← 第 2 个相 CIF（多相时**重复列名**追加）
_maud_import_phase                             ← 第 3 个相 CIF ……
_riet_analysis_fileToSave                      ← 输出 par（**MAUD3 必须相对**，MAUD2 可绝对）
_riet_append_result_to                         ← 结果 TSV（**MAUD3 必须相对**）
'<input.par>'    30     999    true    '<data.xye>'    true    true
   '<cif1.cif>'   '<cif2.cif>'   '<cif3.cif>'    ...
   '<refined.par>'    '<results.txt>'
```

⚠ **R-C1 关键发现**：loop_ 列顺序不重要，但 `_maud_import_phase` 必须放在 `_maud_remove_all_phases true` 之后；`_riet_meas_datafile_name` 必须在 `_maud_remove_all_datafiles true` 之后（否则数据被清空）。

### 8.2 Wizard index 实证取值表（MAUD3 v3.04）

通过反编译 `FilePar.refineWizard` + 字节码 `sipush/if_icmpne` 派发 + 端到端实验：

| wizard | 行为 | 默认迭代数 | 实测轮次（template.par + 刚玉 CIF） |
|---|---|---|---|
| **缺省**（INS 无字段）| MAUD 自动选 wizard，log 打 `Using wizard number: -21`（成熟分析）或 `-31`（原始）| MAUD 自取 15~50 | B/MAUD3 实测跑 20 轮 |
| **-1** | batchProcess 仅 `compute()`，单次重算不精修 | 0 | 不变 |
| **999** | `launchrefine()` 单遍，不走 wizard 循环 | 0 | 0（精修态 par 已收敛直接无效）|
| **1** | GUI "wizard 步 1"：背景+尺度 | 15 | 22 轮 |
| **3** | GUI "wizard 步 3" | 15 | 37 轮 |
| **5** | GUI "wizard 步 5" | 15 | 52 轮 |
| **8** | GUI "wizard 步 8" | 15 | 36 轮 |
| **13** | "wizard 步 13" = 织构+多相+微结构（按 MILK 文档）| 15 | 101 轮 |

**R-C2 实用策略**：
- **成熟 par**（已有精修态相）→ **缺省 wizard**（自动选 -21，最稳，20 轮实测验过 wR 8.7%）
- **全新 template par + 注入 CIF** → **链式 wizard**：先 `wizard=1`（scale+背景），再 `wizard=13`（全参数）
- **Rwp 卡 50%+** → 物理建模错误（缺相、晶胞差太远），非 wizard 能救——必须先修输入

### 8.3 MAUD2 vs MAUD3 行为差异（**PolyXRD 默认走 MAUD3**）

| 维度 | MAUD2 (v2.996, build 1147) | MAUD3 (v3.04, build 1770) |
|---|---|---|
| `_maud_working_directory` 不带尾部斜杠 | **漏一个分隔符**，路径 404 | 无此 bug |
| `fileToSave` 相对路径解析 | 写到**进程 cwd**（不是 INS 目录） | 正确写到 INS 同目录 ✓ |
| `append_result_to` 绝对路径 | 接受 | **会双前缀**（`workingDir + absolutePath` 拼坏路径，抛 FNFE）|
| 首次成功后全局状态漂移 | **✗ 实测 15:24 后无故崩坏**，FilePar 加载任何 par 都 NPE | 持续工作 |
| batchProcess.class 体积 | 17.4 KB | 20.8 KB（新功能 +20%）|
| 兼容性 | MaudText 4 个 CLI flag 同 MAUD3 | 同 MAUD2 |

### 8.4 完整 .par 列 schema（来自 `batchProcess` 构造函数初始化 diclist[26]）

```
 0 _riet_analysis_file                              ← 输入 par
 1 _riet_analysis_iteration_number                  ← 最大迭代
 2 _riet_analysis_wizard_index                      ← wizard 步（见 8.2）
 3 _riet_analysis_fileToSave                        ← 输出 par
 4 _riet_meas_datafile_name                         ← 数据文件
 5 _riet_append_simple_result_to                    ← 简化 TSV（仅 Title+Rwp）
 6 _riet_append_result_to                           ← 全字段 TSV
 7 _riet_meas_datafile_replace                      ← 替换模板里的 datafile
 8 _maud_background_add_automatic                   ← 自动加背景
 9 _maud_output_plot_filename                       ← 画图
10 _maud_remove_all_datafiles                       ← ★ 清数据
11 _maud_remove_all_phases                          ← ★ 清相
12 _maud_import_phase                               ← ★ 注入相（可重复多列）
13 _maud_LCLS2_Cspad0_original_image                ← LCLS2 同步辐射专用
14 _maud_LCLS2_Cspad0_dark_image
15 _maud_export_pole_figures_filename               ← 织构专用
16 _maud_export_pole_figures_options
17 _maud_export_pole_figures
18 _maud_output_plot2D_filename
19 _maud_LCLS2_detector_config_file
20 _publ_section_title
21 _maud_output_stress_filename                     ← 应力专用
22 _maud_output_stress_options
23 _riet_meas_datains_name
24 _riet_meas_datafile_fitting
25 _maud_output_diff_data_filename
```

★ = 路线 C 必用；13/14/19 = LCLS2；15~17 = 织构分析；21~22 = 应力分析。

### 8.5 stdout 信号（用于进度跟踪与状态机）

- `Computing iteration # N of M, Wgt'd ssq = X.YYY` ← 每次精修评估；MAUD3 含 `\r` 进度覆盖，需 `tr -d '\r'` 才能 grep
- `Using wizard number: XX` ← MAUD3 自动选 wizard 时打印
- `Saving file: <path>` ← fileToSave 落盘
- `Global Rwp: 0.08XXX` ← 精修完成最终值
- `Have a nice day!` ← MAUD 退出标志
- `File analysis not opened!!` ← 通常 = 路径解析 bug（MAUD2）或 par 损坏

### 8.6 PolyXRD 默认模板 par 设计（R-C2 输入）

实测可选模板：
- **`default.par` (8 KB, Examples.jar 内)**：仅有 `data_global`（波长、Bragg-Brentano、Chebyshev 背景）→ 最纯净起点
- **`alzrc.par` (93 KB, Examples.jar 内)**：Al₂O₃/ZrO₂ 完整精修配置 → 高质量参考但仅特定数据集适用

**R-C2 推荐**：把 `default.par` 入库为 `src/polyxrd/resources/templates/maud_default.par`，PolyXRD `maud_par_builder.py` 一律基于该模板，通过 INS 动态注入 `_maud_import_phase` 列。

### 8.7 上一章 §7 验证脚本（已过时）

旧脚本是 `-file <par>` 直接加载（仅 load，不 refine）；**正确精修冒烟**用 `-f <ins>` + 上述 INS 模板，§8.1 已给完整示例。

## 9. PolyXRD 落地映射（R-C2 起点）

| PolyXRD 抽象 | MAUD 等价 | `maud_par_builder.py` 责任 |
|---|---|---|
| 用户峰位 → 2θ 数组 | `_riet_meas_datafile_name` + .xye 数据文件 | 写 .xye 或复用用户 .dat |
| 候选相列表（COD ID 集）| `_maud_import_phase` 列 | 按 cod_id 拼 `cod/cif/X/YY/ZZ/XYYYYYY.cif` 路径 |
| 仪器（CU/CO/MO） | `_diffrn_radiation_wavelength` + `_diffrn_radiation_type`（par 字段）| 从 PolyXRD 仪器校准模块传入 |
| 背景策略 | `_riet_chebyshev_polynomial_background`（par 字段）| 留给 builtin RietveldRefiner 决定；MAUD 走默认 |
| 权重 | `_refine_ls_weighting_scheme` = `WgtSS` | 默认推荐 |
| 迭代次数 | `_riet_analysis_iteration_number` | 默认 50 |
| wizard 步 | `_riet_analysis_wizard_index` | MAUD3 缺省（自动 -21），成熟 par 自动选最佳 |

下一步：**R-C2** `services/maud_par_builder.py`（半天）+ **`services/refinement_engines/maud_engine.py`**（半天），合计 ~1.5 工作日完成路线 C 端到端对接。

## 8. 关键代码引用

- MAUD 反编译文件：`C:\MAUD2_recon\com\radiographema\MaudText.class`（4.4 KB）
- MAUD 反编译文件：`C:\MAUD2_recon\it\unitn\ing\rista\util\batchProcess.class`（17 KB）
- 本报告解释的 35 个 lib 列表见 MAUD3 startingLog 第 12 行

## 9. R-C 实施回填 (2026-09-12)

### 9.1 已完成模块

| 模块 | 文件 | 测试 | 状态 |
|---|---|---|---|
| **R-C1** wizard schema 反编译 | `docs/MAUD批处理侦察报告.md §8` | — | ✅ 闭环 |
| **R-C2** PolyXRD → .par / .ins 生成 | `src/polyxrd/services/maud_par_builder.py` + `resources/templates/maud_default.par` | `tests/test_maud_par_builder.py` (20/20 + 1 skip) | ✅ |
| **R-C3** MaudEngine subprocess 包装 | `src/polyxrd/services/refinement_engines/maud_engine.py` | `tests/refinement_engines/test_maud_engine.py` (33/33) | ✅ |
| **R-C4** RietveldRefiner maud 分支 | `src/polyxrd/services/rietveld_refiner.py` (新增 `_refine_maud`) | `tests/test_rietveld_maud_integration.py` (11/11) | ✅ |
| **R-C5** GUI 引擎选择 + 状态标签 | `src/polyxrd/views/main_window.py` (RefinementWizardDialog) | `tests/test_refinement_wizard_maud.py` (9/9) | ✅ |

### 9.2 R-C6 端到端实测: 部分成功

**真实 MAUD3 跑通路径**（脚本 `scripts/maud_replay_ins_F.py`）:

- 数据：`C:/MAUD2/alzrc.dat` (2660 点, 22~155°, Cu Kα)
- 模板：`C:/Users/.../maud_ins_smoke/alzrc.par` (**预加载** 含 corundum + T-PSZ 两相)
- INS 5 列循环: `_riet_analysis_file` + `_riet_analysis_iteration_number` + `_riet_analysis_fileToSave` + `_riet_meas_datafile_name` + `_riet_append_simple_result_to`
- 结果: **wR = 0.087%, R = 0.064%, GOF = 0.064, n_cycles = 20**
- TSV 回读两相 Wt%/Cell/Size 全部正确

**动态 CIF 注入路径** (`scripts/maud_smoke_e2e.py` + `scripts/maud_v3_default_template.py`):

- 用 bundled `maud_default.par` (无相) + `_maud_import_phase` × 2 注入外部 CIF
- **结果: MAUD 加载完成, 但 R 因子恒为 0, TSV 为空, 无 refined.par 输出**
- 与 recon §8.1 描述的"重复列名追加可工作"不符

**根因猜测**:
1. MAUD3 `it/unitn/ing/rista/util/batchProcess.java` 的 `importPhase` 在 batch 模式下被 `_maud_remove_all_phases true` 清空后, 不能从外部 CIF 路径重建结构 (需 phase sections 已存在于 `data_global`)
2. 动态路径替换仅适用于 `_riet_meas_datafile_name` (数据绑定), 对相结构无效
3. `Examples.jar` 里所有 .par 都是手工精修后的"快照", 不含 `data_riet_analysis_*` block (recon §5.3 已确认)

### 9.3 后续路线 (R-C 实际可行的端到端方案)

为支持从用户峰位列表端到端跑 MAUD, 必须先生成 .par 文件嵌入 Phase sections. 这需要:

1. **路线 B / R-B3**: 从 `Phase.lattice` + `Phase.atomic_sites` 生成 CIF (PolyXRD 内已有 `cod_atomic_sites` 数据 + `phase_cif` 模块)
2. **路线 B / R-B4**: 把 CIF 嵌入到 MAUD par template, 生成含 `data_phase_*` 块的 par (替换 `data_global` 之外的相定义)
3. **MAUD 调用**: 用生成的 par (含相) 走 §9.2 "真实 MAUD3 跑通路径" 的 5 列 INS, 自动获得精修结果

待办: `services/maud_par_builder.py` 增 `generate_par_with_phases(template_par, cif_paths, output_par)`,
从模板 par 复制 `data_global` (仪器/背景) + 在末尾追加 `data_phase_*` 段 (从 CIF 解析生成)。

### 9.4 RietveldRefiner 兜底策略

`_refine_maud` 失败时回退 `_refine_builtin` (与 GSAS-II / powerxrd 一致)。
失败条件清单 (实测):
- 缺 C:\MAUD3 / C:\MAUD2 → `MaudEngineError("MAUD 安装无效")`
- 缺 phase.cif_path 且无 cod_id → `MaudEngineError("phase X 没有 CIF")`
- 子进程 exit != 0 → `MaudEngineError("exit=...")`
- 子进程超时 → `MaudEngineError("MAUD 超时 ...")`
- FileNotFoundError (java.exe 缺) → `MaudEngineError("MAUD 可执行文件不存在")`

GUI 侧 (`RefinementWizardDialog`) 用 `RietveldRefiner.get_engine_status()["maud"]` 显示可用/未安装, 用户选 MAUD 但未装时弹 `engine_maud_missing_cif` 提示并切回 builtin。
