# 精修算法改进与 MAUD 引擎接入方案

> 版本: 讨论稿 v1 · 2026-09-11
> 目标发布: **PolyXRD v0.11.0**（已定；0.10.0 系列作为改动前的基线冻结）
> 状态: **待评审**（未动代码）
> 触发问题: "每次精修的 Rwp 都很差" + "能否接入 MAUD3（用户自行安装，程序内指定路径）"

---

## 0. 一页结论

**Rwp 差不是调参问题，是"数据里没有结构"这个前提没被满足。**

当前默认精修引擎 `builtin` 拿到的物相**只有"参考峰 (hkl, 2θ, I) + 晶胞"**，没有原子坐标，
因此它既算不出结构因子 |F|²，也无法精修晶胞 —— 它做的事实际上是**无结构的参考峰轮廓拟合**。
在这种输入下 wR 落在 50~90% 是**必然**，不是 bug。（证据见 §1）

由此得出三条必须同时推进的路线：

| 路线 | 内容 | 解决什么 | 能否独立见效 |
|---|---|---|---|
| **A** | 内置引擎"能修的都修上" | 权重自洽、晶胞可修、背景/峰形/位移解析化 | 能，但天花板约 15~25% |
| **B** | 补齐结构来源（原子坐标 + U_iso + CIF 导出） | 让"真 Rietveld"在数据上成为可能 | 不能单独见效，是 C 的前提 |
| **C** | MAUD 外部引擎（Le Bail / Rietveld） | 一步拿到"正确实现"的精修结果 | **能，且是最快见效的一条** |

**关键判断：MAUD 的 Le Bail 不需要结构就能给出很好的 wR。**
所以路线 C 可以**先于** B 落地，先给用户一条立刻可用的"好 wR"通道（目标 ≤15%）；
而**带含量的真 Rietveld** 必须等 B 完成结构注入。

建议顺序：`P0 侦察 → C1/C2（MAUD Le Bail 打通）+ A1/A2（内置引擎止血）→ B1/B2 → C3–C6 → C7 + A3–A6`

---

## 1. 问题定位：证据链

### 1.1 内置引擎到底在拟合什么

| 环节 | 现状 | 证据 | 后果 |
|---|---|---|---|
| 物相数据结构 | `Phase` **有** `atomic_sites` 字段 | `models/phase.py:80` | 字段在，但没人填 |
| 内置参考库 | `database/xrd_reference_database.json` 只有 peaks+lattice；`_build_phases_from_db` **完全不读 atomic_sites** | `services/phase_identifier.py:132-165` | 全部物相无结构 |
| 强度来源 | 只用预存 `reference_peaks=[(hkl,2θ,I)]` 叠加峰形 | `services/rietveld_refiner.py:558-563, 977-998` | 不重算 f(s)/LP/B/占位 |
| 晶胞 | `_param_mask["cell"]` **无消费方**，`refine_cell` 是 no-op | `models/refinement_options.py:23-25`（自述）、`rietveld_refiner.py:707-709` | 晶格失配 100% 变残差 |
| 背景 | 中值滤波**一次性**扣完即冻结 | `rietveld_refiner.py:539, 551, 958-960` | 低角基线误差永久化成残差 |
| 目标函数 | `residual = y_exp − simulated`，**无任何权重** | `rietveld_refiner.py:552, 724-731` | 强峰主导，弱峰/高角被忽略 |
| wR 定义 | `_calc_wR` 默认 `weight=None→全 1`，且算在**未扣背景**的全强度上 | `rietveld_refiner.py:1142-1161` vs `:758/:863` | **目标函数与评价指标不是同一个量** |
| 峰形 | `η·gauss + (1−η)·lorentz`，两支**各自未面积归一** | `services/phase_display.py:242-246` | η 不是真实混合比，改 η 会改积分强度 |
| Caglioti | 仅 `FWHM²=U·tan²θ+V·tanθ+W` | `phase_display.py:204-207` | 无 1/cosθ 分离、无 Finger 轴向发散 |
| 不对称 | 无 | — | 低角峰形系统性错 |
| 样品位移 | 只有刚性 `zero_shift` | `rietveld_refiner.py:726, 753` | 高角峰位偏移无法拟合 |
| 参数缩放 | `least_squares(method="trf")` **未传 `x_scale`** | `rietveld_refiner.py:742-747` | 参数跨 5 个数量级，轮廓参数收敛极差 |
| 定量 | `weight_fraction = opt_weights/Σ·100` | `rietveld_refiner.py:859-860` | 相对强度归一，非真实质量分数 |

### 1.2 三条外部/内部引擎路径都没给出"正确答案"

| 引擎 | 实际做的事 | 证据 |
|---|---|---|
| `builtin` | 无结构参考峰轮廓拟合（上述） | — |
| `gsas2` | 子进程调桥，但桥内**写死 `set LeBail True`** → 只做 Le Bail 晶胞，不跑强度 | `scripts/gsas2_bridge.py:257` |
| `powerxrd` | 仅单相立方，只修 `a+scale+bkg_intercept`，`\|F\|²=100` 硬编码 | `rietveld_refiner.py:363, 377-391` |

另外两个必须修的行为问题：

- **静默回退**：`refine()` 把任何引擎的**任意异常**吞掉并换成 builtin
  （`rietveld_refiner.py:99-103`）。用户选了 MAUD/GSAS-II，实际跑的是 builtin，却没有任何提示。
- **GSAS-II 的 `simulated_data` 回传的是观测谱**（`rietveld_refiner.py:217`），
  残差图会显示成"完美拟合"。

### 1.3 数据侧的根本约束（这一条决定了 B 路线必须做）

| 数据库 | 大小 | 有 d-I 峰 | 有原子坐标 | 有原始 CIF | 能否做真 Rietveld |
|---|---|---|---|---|---|
| `cod_data/COD_inorganics.sqlite`（71,199 相，**主推**） | 390 MB | ✅ `peaks_d/peaks_i` | ❌ | ❌ | **不能** |
| `cod_data/PDF2_2004.sqlite`（163,834 相） | 215 MB | ✅ | ❌ | ❌ | **不能** |
| `cod_index.sqlite`（113,223 条目，COD full） | 453 MB | ✅ | ✅ `cod_atomic_sites` | ✅ `cod/cif/` 真实 CIF | **能** |
| 内置参考库 | — | ✅ | ❌ | ❌ | **不能** |

> 即：**只有挂了 COD full 包（`cod_index.sqlite` + `cod/cif/`）的机器才有结构可用。**
> 这是"必须提示用户下 COD full"的产品决策依据，也说明为什么 A 路线只能做"止血"。

---

## 2. 实测基线（本次亲测 + 历史报告）

真值取自 `E:/TEMP/test_xrd/txt/物相结果+wt%.txt`。

| 试样 | 真值 (wt%) | 现测 wR | GOF | 现测 wt% | 定量偏差 |
|---|---|---|---|---|---|
| 2-1 | ZnO 50 / CaCO₃ 50 | **51.79%** | 1.90 | 60.66 / 39.34 | +10.7 / −10.7 |
| 4-1 | ZnO 19.94 / Al₂O₃ 21.27 / CaF₂ 22.53 / Mg(OH)₂ 36.26 | **64.74%** | 2.28 | 32.65 / **1.07** / **3.08** / 63.20 | +12.7 / **−20.2** / **−19.5** / +26.9 |

历史 13 样报告（`PolyXRD_测试报告.txt:199-295`）：

```
wR = 85.82%  GOF=2.1156  很差        wR = 51.63%  GOF=1.1583  很差
wR = 61.84%  GOF=0.7986  很差        wR = 87.93%  GOF=3.0977  很差
wR = 58.06%  GOF=2.1294  很差        wR = 87.56%  GOF=2.0822  很差
wR = 64.59%  GOF=3.0433  很差
```

**基线归档：13 样 wR ∈ [51.6%, 87.9%]，全部评为"很差"；仅 7/13 完成精修。**

> 顺带修一个标尺问题：`RefinementResult.quality_grade`（`models/refinement.py:45-57`）
> 用 <2/优秀、<5/良好、<10/一般、<20/差 的分档 —— 这是**同步辐射/PXRD 标准**。
> 实验室粉末 XRD 的 wR 10~15% 已是可发表结果。该分档建议改为 <5/优秀、<10/良好、<15/一般、<25/差。

---

## 3. 路线 A｜内置引擎改进（不依赖结构）

> 目标：wR 52~65% → **15~25%**；4-1 的 Al₂O₃/CaF₂ 不再被压到 1~3%。

### A1 目标函数与 wR 自洽（P0，收益最大）

- **路径**：`services/rietveld_refiner.py` `_refine_builtin` / `_calc_wR`
- **算法**：改成 Rietveld 标准统计权重 `w_i = 1/σ_i²`，σ_i² 取 `Poisson: σ_i² = max(y_i,1)`
  或 `Poirier: σ_i² = y_i + (bkg_i)²`（可配置，默认 Poirier）；
  wR 与目标函数**必须用同一组权重、同一区间、同一 y 基准**（统一为"含背景全强度"）
- **签名**：`_calc_wR(y_obs, y_calc, weights=None, y_bkg=None) -> float`（新增 `y_bkg`）
- **边界**：`Σw·y² == 0` → 返回 `inf` 而非除零；负强度裁剪在算权重**之前**完成
- **验收**：合成数据（已知真解）wR < 1%；同一组输入下 `wR` 与 `sqrt(2·χ²/Σw y²)` 一致

### A2 参数缩放与分批收敛（P0）

- **算法**：① 每个参数按初值量级归一（`x_scale` 逐参数传入 `least_squares`）；
  ② 分层释放：`scale+background` → `+profile` → `+cell` → `+zero_shift`，
  每层收敛后再放开下一层（当前是 8 维一次性硬上）
- **边界**：任一参数初值为 0 → 缩放因子回退到该参数的绝对步长
- **验收**：同一初值下 A2 的最终 wR 严格 ≤ A1；迭代次数下降 ≥30%

### A3 晶胞精修（P0，当前完全缺失）

- **依据**：`reference_peaks` 带 hkl，`Phase.lattice` 有 a/b/c/α/β/γ
  → **可以反算出任意晶胞的 2θ_calc**，所以晶胞精修在本数据模型下**是可行的**
- **算法**：六参数（或按晶系约束到 1~4 个）`d(hkl)` → `2θ_calc` → 峰位重排；
  加**样品位移项** `Δ2θ = −2s·cosθ/R`（与 zero_shift 分离，否则高角信息被零点吸收）
- **边界**：hkl 缺失的物相 → 该物相冻结晶胞并在 `result.warnings` 记录
- **验收**：合成数据晶胞还原误差 < 0.05%；3-1 试样 Al₂O₃ 的 a 收敛到文献 ±0.02 Å

### A4 峰形与背景解析化（P1）

- **峰形**：Pseudo-Voigt 改为**面积归一**定义 `PV = η·L(Γ) + (1−η)·G(Γ)`，两支同一 Γ；
  新增 Caglioti 的 `1/cosθ` 项与低角**不对称**（split-PV 或 Finger 简化式）
- **背景**：Chebyshev 多项式（阶数 4~8，可调）或 B-spline，**与结构联合精修**；
  保留现有 `_estimate_background` 作为初值，不再冻结
- **验收**：4-1 试样 wR 再降 ≥5 个百分点；低角（2θ<20°）残差不再有系统性鼓包

### A5 每相独立轮廓 + 择优取向在线精修（P2）

- 每相独立 `scale / FWHM / η / 晶胞`；March-Dollase `r` 与方向进入参数向量
  （现在只在入口乘一次参考峰强度，`rietveld_refiner.py:69-72`）
- **验收**：5-2/7-2 这类含片状矿物（白云母/高岭土）的试样 wR 改善 ≥8 个百分点

### A6 定量语义修正（P1）

- 当前 `weight_fraction` 是相对强度权重归一，**不是质量分数**
- 改为 `W_p ∝ S_p·(ZMV)_p`（Rietveld 标准：`S` 相标度、`Z` 晶胞式量数、`M` 式量、`V` 晶胞体积）
- **验收**：2-1 定量回到 50±5%

---

## 4. 路线 B｜补齐结构来源（真 Rietveld 的前提）

### B1 `atomic_sites` 增补 `u_iso` / `b_iso`（P0）

- **现状**：`services/cif_database.py:2249` `_extract_atomic_sites` 只取
  `label / element / x / y / z / occupancy`，**丢掉 `U_iso` / `B_iso`**
- **动作**：① 解析器补 `U_iso`（CIF 里可能是 `_atom_site_U_iso_or_equiv` 或 `_atom_site_B_iso_or_equiv`，
  两者换算 `B = 8π²U`）；② `cod_atomic_sites` 表加 `u_iso` 列（**需要重建索引，走版本化迁移**）
- **边界**：CIF 无 ADP → 默认 `U_iso = 0.005 Å²` 并在 warnings 标注
- **验收**：解析 100 个已知 CIF，`B_iso` 与 pymatgen 读数逐条一致

### B2 Phase → CIF 导出器（P0，MAUD/GSAS-II 都要用）

- **新增**：`services/cif_writer.py`，`write_cif(phase: Phase, path: Path, wavelength: float) -> Path`
- **必须包含**：`_cell_length_*` / `_cell_angle_*` / `_symmetry_space_group_name_H-M` /
  `_atom_site_*`（含 `U_iso_or_equiv`、`occupancy`）/ `_chemical_formula_sum`
- **边界**：`space_group` 为空 → 写 P1 并**同时展开对称操作**（否则原子数残缺）；
  坐标缺失 → 抛 `CifWriterError`，由调用方降级到 Le Bail
- **验收**：导出的 CIF 能被 pymatgen 与 MAUD 各自读回，原子数与占位一致

### B3 从 COD full 注入结构（P1）

- 检索命中 `cod_id` 后，若挂了 `cod_index.sqlite`，用 `cod_atomic_sites` + `lattice` 组装带结构 `Phase`；
  原始 CIF 可从 `cod/cif/<相对路径>` 直接取（`cod_index.sqlite:cod_entries.file`）
- **边界**：未挂 COD full → 明确提示"该库不含结构，无法做 Rietveld，已改用 Le Bail"
- **验收**：从 COD full 取 20 个命中相，全部能生成带原子坐标的 `Phase`

### B4 用户 CIF 导入（P2）

- 复用已有 `_on_import_cif` 通道，落到 `services/user_database.py`，带上结构

---

## 5. 路线 C｜MAUD 外部引擎接入（用户指定路径，不集成）

### 5.1 本机实测（已确认的事实）

| 项 | 实测结果 |
|---|---|
| 安装位置 | `C:\MAUD3`、`C:\MAUD2`、`E:\Maud` 三份并存 |
| 运行方式 | Java 应用，**自带 JDK**：`<MAUD>\jdk\bin\java.exe`（无需外部 JRE） |
| 启动脚本 | `<MAUD>\maud.bat` → `jdk\bin\java -mx16384M ... -cp lib/* com.radiographema.Maud` |
| 批处理主类 | **`com.radiographema.MaudText` 确实存在于 `lib/Maud.jar`**（已用 zip 中央目录核实） |
| 批处理实现类 | `it/unitn/ing/rista/util/batchProcess.class` |
| 批处理指令词表 | 从 class 常量提取到 **30+ 个 `_riet_*` / `_maud_*` 关键字**（见 §5.3） |
| `.par` 分析文件 | **纯文本 CIF 语法**（`Examples.jar` 内 `examples/alzrc.par` 已读） |
| 参考质量佐证 | `alzrc.par` 里 `_refine_ls_wR_factor_all 0.0905` → **wR = 9.05%**，且用 `_pd_proc_ls_weight_scheme sqrt` / `_refine_ls_weighting_scheme WgtSS` 统计加权 |
| 自带示例 | `Examples.jar` 内有 12 个 `.par` + 2 个 `.dat`（如 `alzrc.par`/`alzrc.dat`） |

### 5.2 运作机理（决定架构）

MAUD 批处理 = **"跑一个 `.ins` 指令文件"**，而不是命令行传参：

```
<MAUD>\jdk\bin\java.exe -cp "<MAUD>\lib\*" com.radiographema.MaudText -f <work>\job.ins
```

`.ins` 是 CIF 语法的表格（来自 MAUD 官方文档 + MILK 教程，已核实字段名）：

```
_maud_working_directory 'C:/…/polyxrd_maud/run1/'

loop_
_riet_analysis_file            # 输入 .par 模板（含物相/仪器/背景定义）
_riet_analysis_iteration_number # 迭代次数
_riet_analysis_wizard_index     # MAUD 向导编号（决定"放开哪些参数"）
_riet_analysis_fileToSave       # 输出 .par（含精修结果）
_riet_meas_datafile_name        # 实测数据文件
_riet_append_simple_result_to   # 结果追写（TSV）
'alzrc_start.par'  7  13  'alzrc_out.par'  'sample.dat'  'results.txt'
```

- **结果读取**：`_riet_append_simple_result_to` 指定的 TSV，**第 1 行表头、第 2 列就是 Rwp**；
  更结构化的读取则解析输出 `.par` 的 `_refine_ls_wR_factor_all` / `_refine_ls_goodness_of_fit_all`
- **必须先交互启动一次**：MAUD 首次运行要在 GUI 里创建数据库与偏好文件夹，否则批处理会失败
  → **产品上必须提示用户"第一次请先双击一次 maud.bat"**
- **先例**：LANL 的 **MILK**（`github.com/lanl/MILK`，IUCrJ 2023）就是"Python 驱动 MAUD 批处理"的
  参考实现：解析 `.par` → 改参数（free/fix/set_val）→ 写回 → 调 `MaudText` → 读结果。
  **建议我们实现其最小子集（约 300 行），而不是依赖 MILK**（MILK 需 conda 环境且绑定 MAUD 2.998）

### 5.3 已提取的批处理关键字（可直接用作能力清单）

| 关键字 | 用途 |
|---|---|
| `_riet_analysis_file` / `_riet_analysis_fileToSave` | 输入/输出分析文件 |
| `_riet_analysis_iteration_number` / `_riet_analysis_wizard_index` | 迭代数 / 释放哪组参数 |
| `_riet_meas_datafile_name` / `_riet_meas_datains_name` | 载入实测数据 |
| `_riet_meas_datafile_replace` / `_riet_meas_datafile_fitting` | 替换/启用数据集 |
| `_maud_remove_all_datafiles` / `_maud_remove_all_phases` | 清空后用模板重建 |
| `_maud_import_phase` | 导入物相（CIF / .par） |
| `_maud_background_add_automatic` | 自动背景 |
| `_maud_working_directory` | 工作目录 |
| `_riet_append_simple_result_to` / `_riet_append_result_to` | 结果 TSV（**Rwp 在第 2 列**） |
| `_maud_output_plot_filename` / `_maud_output_diff_data_filename` | 导出拟合谱/残差 |
| `_maud_export_lumaCAM_to_GSAS_datafile` | 导出 GSAS 格式数据 |
| `_publ_section_title` | 标题字段 |

> 注意到 `_maud_import_phase` 与 `_maud_remove_all_phases` 同时存在 —— 说明
> **可以从一个"空模板 `.par`"出发，在批处理里逐个导入我们的 CIF**。
> 这条路径能绕开"预先把 `.par` 做对"的难题，是本方案的首选路线。

### 5.4 原子级规格

#### C1 引擎发现与路径配置（P0）

- **新增**：`services/maud_engine.py`
  - `find_maud_home() -> Optional[Path]`
    优先级：`POLYXRD_MAUD_HOME` 环境变量 → `~/.polyxrd/engines.json` 的 `maud_home`
    → 常见目录 `C:\MAUD3`、`C:\MAUD2`、`D:\MAUD3`、`E:\Maud`、`%LOCALAPPDATA%\Maud`
  - **用户可指定文件夹（含 `lib\Maud.jar`）或直接指定 `Maud.jar`**（两种都接受，正合用户要求）
  - `resolve_java(home) -> Path`：优先 `<home>\jdk\bin\java.exe`；不存在则回退系统 `java`
  - `maud_status() -> dict`：`{available, home, java, version, libs_ok, needs_first_run}`；
    `needs_first_run` 判定 = 偏好目录（MAUD 用户目录）不存在
- **持久化**：`~/.polyxrd/engines.json`，复用 `AppConfig` 既有的 `user_db_paths.json` 模式
- **边界**：路径存在但不是 MAUD（无 `lib/Maud.jar`）→ `available=False` 并给出原因文案
- **验收**：三份本机安装都能被自动识别；`POLYXRD_MAUD_HOME` 指向错误目录时状态为 False 且不抛异常

#### C2 数据文件与 CIF 落盘（P0）

- **动作**：把 `XRDData` 与各 `Phase` 落到 `work_dir`：实测谱 + 每相 CIF（用 B2）
- **格式不确定项**：MAUD 对数据文件扩展名有识别逻辑，我们的 `.txt` 未必被认
  → **P0 侦察项 S2**：确定 `.dat` / `.xye` / `.UDF` / `.gsas` 哪种最稳，必要时生成 MAUD 专用 `.dat`
- **边界**：无结构的物相 → 走 Le Bail（不需要 CIF），但要在 GUI 明确告知"本次为 Le Bail，不含占位/ADP"

#### C3 `.par` 模板与参数开关映射（P0/P1）

- **Le Bail 通道（不需要结构，先落地）**：生成一个"空模板 `.par`"，
  批处理里 `_maud_remove_all_phases` → `_maud_import_phase`（我们的 CIF）→
  `_maud_background_add_automatic` → 设定 `_riet_analysis_wizard_index` 与迭代数
- **参数映射（把 `RefineOptions` 翻成 MAUD 语义）**：

  | PolyXRD | MAUD |
  |---|---|
  | `refine_cell` | 晶胞参数的自由/固定 |
  | `refine_background` | 背景多项式系数自由/固定 |
  | `refine_profile` | 尺寸-应变 / Caglioti 参数自由/固定 |
  | `refine_zero_shift` | 零点偏移自由/固定 |
  | `preferred_orientation{r,d}` | March-Dollase 取向模型 |
  | `max_cycles` | `_riet_analysis_iteration_number` |

- **P0 侦察项 S3**：确定**哪一个 wizard index 对应"背景 + 晶胞 + 轮廓 + 零点"这组释放策略**。
  MAUD 向导编号随版本变动（文档示例里 13 = 纹理分析），必须在**本机三份安装**上各测一次并落表
- **实现选择**：参数开关优先通过 **编辑 `.par` 文本**（MILK 的做法，可控且可测试）实现，
  而不是依赖 wizard index 的黑盒语义
- **验收**：同一个 `.par` 模板 + 不同开关，MAUD 输出 `.par` 里被释放参数的 `_refine_ls_*` 状态与预期一致

#### C4 调用与结果解析（P0）

- **新增**：`services/maud_runner.py`
  - `run_batch(home: Path, ins_file: Path, work_dir: Path, timeout: int) -> MaudRun`
  - 子进程调用：`cwd=work_dir`，`env` 保留 `JAVA_HOME` 指向自带 jdk；
    强制 UTF-8 输出；`timeout` 到点 `kill`
  - **严禁** `shell=True`；参数走 list 形式，路径含空格也必须安全（本机 `C:\MAUD3` 无空格，但用户机器可能有）
- **结果解析**：`parse_results_tsv(path) -> list[MaudResult]`（第 2 列为 Rwp）
  + `parse_par_result(path) -> dict` 读 `_refine_ls_wR_factor_all` /
  `_refine_ls_goodness_of_fit_all` / 各相晶胞与含量
- **边界**：MAUD 返回码非 0 / 未生成输出文件 / 结果 TSV 行数不符 → 抛 `MaudRunError`
  **带 stdout+stderr 尾部 200 行**（这是最容易踩的坑：Java 抛异常时返回码可能仍是 0）
- **验收**：用 `Examples.jar` 里的 `alzrc.par`+`alzrc.dat` 跑通一次，读到的 Rwp 与 `.par` 头部记录一致

#### C5 结果映射回 `RefinementResult`（P0）

- Rwp/GOF → `wR`/`GOF`；精修后晶胞 → `Phase.lattice`；各相含量 → `Phase.weight_fraction`
- 拟合谱 + 观测谱 → `simulated_data` / `observed_data`（供残差图）→ 依赖 `_maud_output_*` 关键字
- **验收**：GUI 精修页显示的 wR/晶胞/含量与 MAUD 输出 `.par` 逐项一致

#### C6 GUI：外部引擎设置在程序内指定（P0）

- **新增**：`views/widgets/engine_dialog.py` `EngineManagerDialog`
  （结构对齐既有的 `DatabaseManagerDialog`，`services/db_import.py` 的 `slot_states()` 模式可直接照搬）
  - 一行 `MAUD`：状态徽标 + 路径输入框 + 「浏览文件夹…」/「浏览 Maud.jar…」+ 「测试运行」
  - 提示文案：**"首次使用请先双击一次 `<MAUD>\maud.bat` 完成初始化"**
- **入口**：`refine_menu` 增加 `engines…` 动作（`main_window.py:866-881` 邻域）
- **引擎下拉**：`refinement_view.py:73` 的 `["builtin","gsas2","powerxrd"]` 增加 `"maud"`；
  不可用时置灰并给出原因（tooltip）
- **i18n**：`busy.*` 的既有模式照搬到 `engine.*`，三语言齐全（zh_CN / en_US / ja_JP）
- **验收**：offscreen 测试覆盖"未配置 → 可选但置灰"、"配置后 → 可选"、"路径失效 → 回到置灰"

#### C7 真 Rietveld 通道（P1，依赖 B）

- 有结构时：导入带 ADP/占位的 CIF → 释放原子坐标/ADP → 走完整 Rietveld
- 附带产出：**择优取向/织构、微晶尺寸-微应变、定量（含非晶内标）**
- **验收**：2-1 定量 50±5%；4-1 四相各自在真值 ±8% 内；wR ≤ 10% / ≤ 15%

---

## 6. 统一引擎接口重构（E1–E2）

现状是 `engines` 字典 + 三份不同的返回结构（`rietveld_refiner.py:88-92`），加第四个引擎要动的面很大。
建议先做一次小重构：

- **E1** `services/engines/base.py`
  - `@dataclass RefineRequest{data, phases, options, strategy, max_cycles, wavelength, work_dir, progress_cb}`
  - `class RefinementEngine(Protocol){ name; display_name; status() -> EngineStatus; refine(req) -> RefinementResult }`
  - `EngineStatus{available, path, version, note, needs_setup}`
- **E2 去掉静默回退**
  - `RefinementResult` 增加 `engine_requested` / `engine_used` / `warnings: list[str]`
  - 回退发生时**必须**在 `warnings` 里写明原因，并在 GUI 顶部弹一条非模态提示
  - **验收**：新增测试 `test_engine_no_silent_fallback.py`，故意让外部引擎抛异常，
    断言 `engine_used == "builtin"` 且 `warnings` 非空

---

## 7. 验收标准与基准工具

### 7.1 目标值

| 阶段 | 2-1 wR | 4-1 wR | 13 样中位数 wR | 2-1 定量 | 4-1 定量 |
|---|---|---|---|---|---|
| 现状基线 | 51.8% | 64.7% | ~62% | 60.7/39.3 | 32.7/1.1/3.1/63.2 |
| **A 完成** | ≤25% | ≤30% | ≤28% | 50±7% | ±12% |
| **C2 完成（MAUD Le Bail）** | ≤12% | ≤18% | ≤15% | 不适用（无结构） | 不适用 |
| **B+C7 完成（真 Rietveld）** | ≤10% | ≤15% | ≤12% | 50±5% | ±8% |

### 7.2 基准工具（新增）

- **`tests/bench_refine_wr.py`**（按项目惯例，`bench_*` 不入库的临时基准也要能一键重跑）
  - ⚠️ 该脚本随 `fa9c9ab` 的 `tests/bench_*.py` 批量清理一并删除，且从未入库、不可取回。
    需要时按下述规格重建（骨架与 `docs/基准报告-v0.9.11.md` 文末「重写指引」同构）。
  - 遍历 `E:/TEMP/test_xrd/txt/` 13 样 × 引擎集合（builtin / gsas2 / maud）
  - 输出 Markdown 表：`试样 | 引擎 | wR | GOF | 耗时 | 各相 wt% | 与真值偏差`
  - 真值从 `物相结果+wt%.txt` 解析
- **回归断言**：`tests/test_rietveld_engine_opt.py` 现有的 `wR<55` / `wR<65`
  **随阶段推进逐次收紧**（≤25 → ≤12），让"改进"有防回退保护

---

## 8. 风险与开放问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| **R1** MAUD 批处理命令行/`-f` 参数在 MAUD 3 上未验证 | C 路线整体不成立 | **P0 侦察 S1**，半天内出结论；失败则退回 GSAS-II Le Bail |
| **R2** wizard index 语义随版本变 | C3 参数映射不可靠 | 改为**编辑 `.par` 文本**释放参数，不依赖 index |
| **R3** MAUD 首次必须交互启动 | 用户"跑不起来" | GUI 显式提示 + `needs_first_run` 状态检测 |
| **R4** 主推库（COD inorganics / PDF2）无原子坐标 | 真 Rietveld 对多数用户不可用 | 产品上明确分档：Le Bail（人人可用） vs Rietveld（需 COD full）；并在物相检索页提示 |
| **R5** `cod_atomic_sites` 加 `u_iso` 需重建索引 | 用户已下载的 COD full 包要重下 | 走版本化：新列可空，旧包读到 NULL 时用默认 U_iso；**不强制重下** |
| **R6** Kα2 是否已剥离未知 | 若数据含 Kα2 而模型只用 Kα1，wR 会被"冤枉"地抬高 | **P0 侦察 S4**：抽查 13 样的数据特征；MAUD 可直接建模 Kα1/Kα2 双线 |
| **R7** Java 子进程吃内存（`-mx16384M`） | 低配机 OOM | 我们自己传 `-mx` 并用较小值（如 2048M），不沿用 `maud.bat` 的 16G |
| **R8** 非晶相（3-2 含 29.47% 非晶玻璃） | 定量必然偏低 | 走内标法（已有 `refine_with_internal_standard`）或 MAUD 的非晶模型，单独一件 |

### 待用户决策

1. **优先级**：是"先要一个能用的好 wR"（押 C2 MAUD Le Bail，最快），还是"先把内置引擎修到不吃亏"（押 A）？
   → 我建议 **C2 + A1/A2 并行**，前者见效、后者保底（用户不装 MAUD 时不能退化成 60%）。
2. **MAUD 是否作为默认引擎**？建议：装了就是默认，没装回落 builtin，并**明确显示"当前引擎"**。
3. **是否接受"真 Rietveld 需要 COD full"这个门槛**？（决定 B 路线是否值得投入）
4. **版本号**：~~这批改动量大，是否走 0.11.0（而非 0.10.1）？~~
   → **已定：走 0.11.0。** 0.10.0 系列在本方案动代码之前冻结并打 tag `v0.10.0` 存档，
   后续本方案的全部改动进入 0.11.0，不再回填 0.10.x。

---

## 9. 建议执行顺序

| 阶段 | 内容 | 产出 | 预估 |
|---|---|---|---|
| **P0 侦察** | S1 批处理跑通；S2 数据格式；S3 wizard/参数释放；S4 Kα2 抽查；S5 权限与偏好目录 | `docs/MAUD批处理侦察报告.md` | 0.5–1 天 |
| **Sprint 1** | A1 + A2 + E1/E2 | 内置引擎止血（wR 52~65% → 35~45%），回退不再静默 | — |
| **Sprint 2** | C1 + C4 + C5 + C6 | **MAUD Le Bail 端到端可用**，GUI 可指定路径，wR ≤15% | — |
| **Sprint 3** | A3 + A4 + A6 | 晶胞/背景/峰形/定量语义修正 | — |
| **Sprint 4** | B1 + B2 + B3 | 结构来源打通 + CIF 导出器 | — |
| **Sprint 5** | C3 + C7 | 真 Rietveld（含量定量 + ADP + 取向） | — |
| **Sprint 6** | A5 + 13 样全量基准 + 文档 | `基准报告-精修.md` | — |

---

## 附录 A｜本机 MAUD 环境实测记录

```
C:\MAUD3\  C:\MAUD2\  E:\Maud\
  ├─ maud.bat          jdk\bin\java -mx16384M --enable-native-access=ALL-UNNAMED ...
  │                     -DJava.library.path=. -cp lib/* com.radiographema.Maud
  ├─ jdk\bin\java.exe  自带 JDK（无需外部 JRE）
  ├─ lib\  Maud.jar(3178 类) / Examples.jar / xraylib.jar / colt.jar / commons-math.jar ...
  └─ mtex\ plugins\ licenses\ Readme.txt

lib/Maud.jar 关键类
  com/radiographema/Maud.class            交互主类（含 -textonly / -film / -simple / -file 开关）
  com/radiographema/MaudText.class        ★ 批处理主类
  it/unitn/ing/rista/util/batchProcess.class  ★ 批处理实现（30+ 个 _riet_*/_maud_* 关键字）
  it/unitn/ing/rista/models/BatchDataModel.class
  com/radiographema/tools/QuantitativeTextureAnalysis.class

Examples.jar 内可用示例
  examples/alzrc.par (92,851 B) + alzrc.dat      ← 首选冒烟用例
  examples/default.par, cpd1h.par, Ni3Al_faults.par, Steel16CrNi4.par, sio250.par, y2o3.par ...

alzrc.par 头部（佐证 MAUD 是统计加权真 Rietveld）
  _refine_ls_R_factor_all       0.06553908
  _refine_ls_wR_factor_all      0.090500064
  _refine_ls_goodness_of_fit_all 0.06368748
  _pd_proc_ls_weight_scheme     sqrt
  _refine_ls_weighting_scheme   WgtSS
  _computing_refinement_algorithm 'Marqardt Least Squares'
```

## 附录 B｜P0 侦察清单（必须先做，结论决定后续设计）

| 编号 | 问题 | 判定方法 | 若失败 |
|---|---|---|---|
| **S1** | `com.radiographema.MaudText -f job.ins` 能否无头运行？ | 用 `alzrc.par`+`alzrc.dat` 生成最小 `.ins` 实跑，看是否产出输出 `.par` | 改试 `-batch` / 无参传 `.ins`；再不行退回 GSAS-II Le Bail |
| **S2** | 哪些数据文件格式被自动识别？`.txt` 行不行？ | 分别用 `.dat`/`.xye`/`.UDF`/`.txt` 各跑一次 | 生成 MAUD 专用 `.dat`（补头部） |
| **S3** | "背景+晶胞+轮廓+零点"对应哪个 wizard index / 哪些 `.par` 参数？ | 在 GUI 里导出对照，或直接编辑 `.par` 后跑批处理对比输出 | 全面改为编辑 `.par` 文本释放参数 |
| **S4** | 13 样数据是否含 Kα2 双线？ | 看 1-1/2-1 的峰位间距与 FWHM 随 2θ 变化 | 在引擎里建模 Kα2，或提示用户先剥离 |
| **S5** | MAUD 偏好目录在哪、是否需要一次交互启动？在只读安装目录下会怎样？ | 观察首次运行生成物；测只读场景 | 让用户把 MAUD 装在可写目录，或指定可写偏好目录 |

---

## 附录 C｜不做什么（明确划界）

- ❌ 不把 MAUD / JDK 打进安装包（体积 + 许可）——只做路径对接，符合"用户自行安装"的要求
- ❌ 不引入 MILK 作为依赖（需 conda 环境、绑定 MAUD 2.998）——只借鉴其 `.par` 编辑思路
- ❌ 不追求"一次点击全自动出好结果"——精修需要人判断参数释放策略，
  我们的目标是"**给出正确默认 + 可见的中间过程**"，而非黑盒
