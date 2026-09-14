# MAUD 2.99x 系列 与 3.04 差异分析

> 目的：判断从 2.99x 迁到 3.x 是否会影响 PolyXRD 的 MAUD 批处理接入
> （`services/refinement_engines/maud_engine.py`、`services/maud_par_builder.py`）
> 以及独立的 MAUD3-MCP 包。
>
> 数据来源：上游 `https://github.com/luttero/maud`（默认分支 `version3`），
> 对 `v2.99997`（2.x 最后一版）与 `v3.04`（当前）做了全量源码 diff。
> 本地比对树：`E:\TEMP\_maud_cmp\s299997`（v2.99997）、`E:\TEMP\_maud_cmp\s304`（v3.04）。
>
> 日期：2026-09-14

---

## 1. 结论速览

| # | 结论 | 对我们 |
|---|---|---|
| 1 | `MaudText.java`（批处理 CLI 入口）**一字未改** | 调用方式无需变动 |
| 2 | 2.99993（本机 `C:\MAUD2`）与 3.04（本机 `C:\MAUD3`）对同一输入给出**完全一致**的结果（wR=69.9%、TSV 相同） | 单线 Bragg-Brentano 实验室数据链路**无回归** |
| 3 | `.xye` 读取器（ETH 三列）未改，仍**不跳过 `#` 注释行** | 我们"写 xye 不带表头"的做法必须保留 |
| 4 | `.par` 中我们依赖的两处（`loop_ _pd_phase_atom_%` 相分数、晶格）解析未变 | 结果抽取无需改动 |
| 5 | 我们的 par 模板无 `equalTo` 绑定、无 `always(2)` 状态字段 | 参数绑定重写 / `checkIntegrity` 行为变化**均不影响我们** |
| 6 | 3.x 新增的批处理能力可被我们直接利用 | 见 §6 建议 |

**一句话**：3.0 是 2.999x 的**功能延续 + 内核改写**，不是数据库格式革命；对我们的批处理接入**无破坏性变更**，且提供了 2 个值得利用的新关键字。

---

## 2. 版本时间线

上游 tag 序列（`git tag`）：
`v2.998 → v2.999 → v2.9992 … v2.9999 → v2.99991 → v2.99993 → v2.99997 → v3.0 → v3.01 → v3.02 → v3.03 → v3.04`

| 版本 | 日期 | 代号 | 主要内容 |
|---|---|---|---|
| 2.99993 | 2025-08-20 | "Extinction" | 消光/动力学修正模型插件化；新增 Sabine 消光模型。**本机 `C:\MAUD2` 即此版** |
| 2.99994 | 2025-08-28 | "Smithsonite" | LumaCAM→GSAS 导出；批处理新关键字 `_maud_export_lumaCAM_to_GSAS_datafile`、`_pd_meas_dataset_number` |
| 2.99997 | 2026-08-05 | "End of life" | 最后一个 2.x；标准函数织构模型改用 HWHM；权重重算修正；批处理启动修正 |
| **3.0** | 2026-08-27 | **"Hippo scattering"** | 第二代 Angle-Energy maps 拟合；**DiffaX 层模型**；内核大改 |
| 3.01 | 2026-08-28 | — | EWIMV bug 修复 |
| 3.02 | 2026-08-31 | — | Hippo wizard 自动剔除无用 bank；`equalTo` 支持绑定到**多个**参数；批处理新增选项 |
| 3.03 | 2026-09-04 | — | 菜单助记符统一；lumacam→gda 导出修复 |
| 3.04 | 2026-09-08 | — | 极图窗口支持旋转。**本机 `C:\MAUD3` 即此版** |

> 注意：2.99x 与 3.x 之间**只隔了 15 个 commit**（2026-08-05 → 2026-09-08）。
> 3.0 是对 2.99997 的直接续写，2.99997 的 readme 里已明写"will be the last version 2.x
> before version 3.0 that will follow shortly"。

---

## 3. 差异规模

`diff -r s299997/src s304/src`：

- **237** 个源文件内容有差异
- **新增 3 个文件**：
  - `it/unitn/ing/rista/diffr/sizestrain/PrasadLeleDhcpFaultingModel.java`
  - `org/diffax/`（新包）
  - `files/data.sfc`
- **删除 0 个文件**
- 若剔除纯 `printStackTrace()` / 注释噪声，实质改动集中在约 40 个文件

实质改动量 Top 10（已剔除噪声行）：

| 实质行数 | 文件 |
|---:|---|
| 14203 | `diffr/sizestrain/DiffaXLayerModel.java` |
| 1078 | `diffr/DataFileSet.java` |
| 765 | `diffr/DiffrDataFile.java` |
| 332 | `diffr/sfm/StructureFactorArbitraryModel.java` |
| 305 | `diffr/instbroad/AngleEnergyMapInstrumentBroadening.java` |
| 255 | `diffr/sfm/StructureFactorStandardModel.java` |
| 248 | `diffr/PseudoVoigt2DPeak.java` |
| 209 | `diffr/Parameter.java` |
| 194 | `util/Angles.java` |
| 182 | `util/FluorescenceLine.java` |

---

## 4. 分类改动明细

### A. 结构因子计算（"Hippo scattering" 的核心）

`StructureFactorStandardModel.computeStructureFactors` **被重写并改为 `static`**：

- `fhkl` 维度由 `double[hkln]` → **`double[hkln][nlines]`**（按辐射线数展开）
- 引入数据集级散射因子缓存 `dataset.getScatteringFactor(phase)`
- 旧实现原样保留为 `computeStructureFactors_old(...)`
- 移除一处误调用 `adataset.storeComputedStructureFactors(phase, fhkl)`
  （源码原文注释：`// l removed as in error`）

`StructureFactorArbitraryModel` 同源改写（+332 实质行）。

**影响**：多辐射线 / 多 bank 数据（Hippo、TOF）的结构因子正确性大幅改善；
单线实验室 XRD 数值等价（已由我们的实测佐证）。

### B. 峰形 / 仪器展宽 —— 与我们"绝对 wR 偏高"直接相关

| 改动 | 旧 | 新 |
|---|---|---|
| 展宽查询 API | `double[][] getInstrumentalBroadeningAt(x, f)` | `Vector<double[]> getInstrumentBroadeningAt(x, f)`（{hwhm, eta}） |
| 最小 HWHM 常量 | `minimumHWHMvalue` 定义在 `InstrumentBroadeningPVCaglioti`，且每次 `update` 时执行 `minimumHWHMvalue *= 4.0*minimumHWHMvalue` | 上移到基类 `InstrumentBroadening`，**该平方放大逻辑被删除**；新增 pref `instrBroadening.minimumHWHM`（默认 1e-4） |
| `PseudoVoigtPeak.getHwhmEtaFromIntegralBeta` | 入参 `double[] broadInst` | 入参 `Vector<double[]> broadInst` |
| 能量色散 / d 间距基 | `if (energyDispersive \|\| dspacingbase) nrad = 1;` | **该特例被移除** |

`InstrumentBroadening.getInstrumentalBroadeningAt` 的签名替换属于**插件 API 破坏性变更**——
但 PolyXRD 不写 MAUD 插件，不受影响。

> 这一块是唯一可能改变我们数值结果的区域。实测同一输入 2.99993 与 3.04 结果完全一致，
> 说明在"单线 Cu Kα + Bragg-Brentano + PV Caglioti"这一默认路径上两条代码等价。
> 我们 MAUD 绝对 wR≈52% 的问题仍然归因于**默认仪器/峰形参数与真实仪器不匹配**，不是版本差异。

### C. 参数绑定 `equalTo` 重写（3.02 起）

```java
// 旧 (2.99997)
String tempBound;  String ratio;  Parameter refParameter1;
par.setEqualTo(refPar, ratio, constant);
value = refValue * ratio + constant;

// 新 (3.04)
Vector<String> tempBound;  Vector<String> ratio;  Vector<Parameter> refParameter_v;
par.setConstant(constant);
for (i) par.addBound(refPar_i, ratio_i);
value = constant + Σ( ratio_i × refValue_i );
```

- 单一绑定时**数值语义等价**
- 新增能力：一个参数可绑定到**多个**参数之和（3.02 版本说明原文：
  "It is possible to bound a parameter with the equalTo to a series of more parameters"）
- 牵连面：`Parameter` / `XRDcat` / `Phase` / `AtomSite` / `AtomScatterer` /
  `DataFileSet` / `Instrument` / `MultDiffrDataFile` 等所有 `setField` 重载
- `FilePar.java` 中注册 `boundList` 的循环同步改为遍历 `refparameterVector`

**对我们的影响：无。** 我们的 par 模板（`resources/templates/maud_default.par`）
不含任何 `equalTo` 绑定，只写 `#min/#max` 约束。该改动仅在我们将来需要生成
"晶格参数相互绑定"的分析文件时才需要关注。

### D. 批处理 `batchProcess.java` —— 与我们最相关

#### D.1 新增 ins 关键字（diclist index 28/29/30）

| 关键字 | 作用 | 实现 |
|---|---|---|
| `_maud_output_sum_data_filename` | 导出**求和后**的实验/拟合数据 | 新增 `exportSummedExperimentalData()`，按 dataset 写 `<name><i>.xye`（2θ, I_obs, I_calc） |
| `_maud_output_plot_keep_scale` | 1D 出图沿用上次坐标范围 | 读 pref `plot_batch.xmin/xmax/intensity_min/intensity_max` |
| `_maud_output_plot2D_keep_scale` | 2D 出图沿用上次强度范围 | 读 pref `plot2D_batch.intensity_min/max` |

#### D.2 新增 wizard index 哨兵值 `-999`

```java
if (wizardindex == -999) { // in the batch file need to be -998
  // do nothing  —— 只加载 / 只导出，不做精修
} else if (wizardindex == 999) { ... }
```

即"只加载分析文件 + 执行导出，跳过一切计算"。源码注释提示写成 **-998**。

#### D.3 工作目录解析重写（**行为变化**）

```java
// 旧：无条件用 ins 所在目录覆盖
token = workingDirectory + item.thestring;
analysis.setDirectory(newfolderandname[0]);
workingDirectory = newfolderandname[0];

// 新：引入 workingDirectorySet 标志 + 相对/绝对路径区分
token = item.thestring;
if (!workingDirectorySet) {
  if (newfolderandname[0].length() > 0) {
    if (newfolderandname[0].startsWith("/")) workingDirectory = newfolderandname[0];
    else workingDirectory += newfolderandname[0];
  }
  analysis.setDirectory(workingDirectory);
} else {
  analysis.setDirectory(workingDirectory + newfolderandname[0]);
}
```

多分析文件 + 相对路径场景下行为与旧版不同。

#### D.4 其他

- 加载 par / CIF 由 `catch (IOException)` 改为 **`catch (Exception)`**，且批处理多处补 `printStackTrace()` → 更健壮，原本被静默吞掉的失败现在可见
- `plotAndExportPng(name, xmin, xmax, ymin, ymax)` / `plot2DandExportPng(name, ymin, ymax)` 增加显式坐标范围参数
- `BatchFileDialog`（GUI）新增：拖拽/浏览多个分析文件、"从上一分析生成 N 个"、2D 图导出、保持比例复选框

### E. 精修行为变化（可复现性提醒）

`FilePar.checkIntegrity()`：

```java
// 旧：把 "always" 状态静默降级为 1（等于自动纠正）
if (getTextureFactorsExtractionStatusI() == 2)
  setTextureFactorsExtractionStatus(1);
...（共 6 处）

// 新：只提示，不再自动改
if (getTextureFactorsExtractionStatusI() == 2)
  tmp.append("Attention: texture factors extraction set to always! ...");
```

被影响的 6 个状态：texture factors extraction / texture computation /
positions extraction / background interpolation / structure factor
extraction-computation。

**含义**：某个在 2.99x 下会被自动降级的分析文件，在 3.04 下会**保持 always 并照此执行**。
→ 若跨版本打开旧分析文件，结果可能与之前不同。

另：`updateDataFilePlot(true)` → `updateDataFilePlot(false)`（精修后不再强制重绘图）。
"Sample missing" 检查被移除。

> 对我们的影响：我们的模板不含 `always(2)` 字段（已核对），不受影响。

### F. 数据读取

- `ETHThreeColumnDataFile.java`：**只多了一行 `e.printStackTrace()`** →
  **不跳过 `#` 注释行的行为未变**。这是我们当初必须给 `.xye` 去掉表头的原因，仍然成立。
- 绝大多数 `diffr/data/*.java` 都是 3 行 stack-trace 级改动；
  实质改动仅：`BerkeleyDataFile`、`GSASDataFile`、`GSASNewDataFile`、
  `LoskoDataFile`、`DubnaDataFile`、`xyDataFile`、`MBinDataFile`。
- `DataFileSet` 新增公开能力：`getMaximumRangeAndMinimumStep()`、`getSummedData(...)`、
  `getTotalIntensityAndFitForActiveSpectra()`、`removeUnusedBanks()`、
  `getPatternsForPhase()`、Chebyshev 多项式背景等。
- `DiffrDataFile` 新增：`isPeakInsideRange()`、`isDspaceInsideRange()`、
  `getPositionFromDspace()`、`getBroadFactorHWHM()/Eta()`、`shrinkRange()` 等。

### G. 其他

- **JDK 升级到 Java 25 (LTS)**；`HTTPClient/URI.java` 重写（+56 行）
- `util/Angles.java`（+194 实质行）—— 角度转换
- `util/FluorescenceLine.java`（+182）—— 荧光
- `diffr/Texture.java`（+174）、`rta/HarmonicTexture.java`、`MEMLTexture.java`
- `diffr/Instrument.java`（+141）
- `awt/TexturePlot.java`（+147）—— 3.04 的极图旋转
- `AngleEnergyMap*` 系列 —— 第二代角度-能量二维图拟合（3.0 主打，作者自述"未完全调试完"）

---

## 5. 对 PolyXRD / MAUD3-MCP 的逐条影响判定

| 我们的组件 | 是否受影响 | 说明 |
|---|---|---|
| `maud_engine.py` 子进程调用 | 否 | `MaudText.java` 未变；`-f run.ins` 解析逻辑不变 |
| `maud_par_builder.py` 生成的 ins | 否 | 我们只写 `_riet_analysis_file` / `_iteration_number` / `_wizard_index` / `_fileToSave` / `_append_result_to`，全为裸文件名 + `cwd=work_dir`，落在新版 `workingDirectorySet=false` 分支，行为与旧版一致 |
| `.xye` 写入（去表头） | 必须保留 | ETH 读取器仍不处理 `#` |
| `_parse_par_phases`（相分数） | 否 | `loop_ _pd_phase_atom_%` 语义未变 |
| `_parse_par_rfactors` | 否 | par 仍存小数形式 R |
| par 模板（2.99x 时代产物） | 否 | 无 `equalTo`、无 `always(2)`；已在 3.04 实测加载正常 |
| MAUD3-MCP（独立包） | 否 | 复用同一套 ins/par 逻辑 |

**唯一需要留意的风险点**：若将来把 ins 里的路径写成子目录相对路径（如 `sub/run.par`），
新旧版的工作目录拼接规则不同，需重新验证。

---

## 6. 可立即利用的 3.x 新能力（建议）

1. **`_maud_output_sum_data_filename`**
   一次批处理即可导出"所有分段求和后"的实验/拟合曲线，省掉我们自己在 Python 侧
   合并多段数据的代码。可用于"多段扫描合并 + 拟合对比图"场景。

2. **wizard index `-999`（ins 中写 `-998`）**
   只加载分析文件、执行导出、不做精修 → 适合"仅解析已有 par"或"仅重绘导出图"的轻量任务，
   也方便我们做 par 往返（round-trip）测试而不浪费时间在迭代上。

3. **`removeUnusedBanks()` / Hippo wizard 自动剔除无用 bank**（3.02）
   若将来接入多 bank TOF 数据，可直接借用。

---

## 7. 复现方法

```bash
# 上游源码全量对比（blobless + sparse 稀疏检出，避免 API 限流）
cd /e/TEMP/_maud_cmp
git clone --depth 1 --branch v2.99997 --filter=blob:none --sparse https://github.com/luttero/maud.git s299997
git clone --depth 1 --branch v3.04    --filter=blob:none --sparse https://github.com/luttero/maud.git s304
(cd s299997 && git sparse-checkout set src)
(cd s304    && git sparse-checkout set src)
diff -rq s299997/src s304/src        # → 237 差异文件
```

> 注意：`git sparse-checkout set <path>` 会作用于**当前所在仓库**。
> 若目标目录的 `.git` 不健全，git 会回退到父仓库，**误改外层项目的稀疏检出配置**，
> 导致外层工作树文件"消失"（`git status` 不报错，因为带 skip-worktree 标记）。
> 恢复：在外层仓库执行 `git sparse-checkout disable`。
> 克隆务必**串行**执行，并行克隆会互相踩 `.git` 锁。

本机版本核对：

```bash
# C:\MAUD2\lib\Maud.jar → 版本串 2.99993
# C:\MAUD3\lib\Maud.jar → 版本串 3.04
# 或看 lib\Help.jar 内 help/readme.txt 的 "Maud Version notes" 首条
```
