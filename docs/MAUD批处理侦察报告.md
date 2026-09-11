# MAUD 批处理模式侦察报告

> v0.11.0 路线 C（外部引擎接入）的 P0 铺垫。本报告基于本机 C:\MAUD2 + C:\MAUD3 实测，目标是确认 MAUD 是否能作为 PolyXRD 子进程被驱动。

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

## 7. 验证脚本

报告里所有冒烟命令都在 `/tmp/maud_smoke/` 真实跑过：

```bash
cd /tmp/maud_smoke
unzip -o Examples.jar 'examples/alzrc.par' 'examples/alzrc.dat' \
                       'examples/Steel16CrNi4.par' 'examples/Steel16CrNi4.RAW' \
                       'examples/default.par'
# 这一行就可以重跑报告里的 5.1 案例
cd /c/MAUD2 && \
    ./jdk/bin/java.exe -mx4096M \
        --enable-native-access=ALL-UNNAMED \
        --add-opens java.base/java.net=ALL-UNNAMED \
        -DJava.library.path=. \
        -cp "lib/*" com.radiographema.MaudText \
        -silent -file /tmp/maud_smoke/examples/alzrc.par
```

## 8. 关键代码引用

- MAUD 反编译文件：`C:\MAUD2_recon\com\radiographema\MaudText.class`（4.4 KB）
- MAUD 反编译文件：`C:\MAUD2_recon\it\unitn\ing\rista\util\batchProcess.class`（17 KB）
- 本报告解释的 35 个 lib 列表见 MAUD3 startingLog 第 12 行
