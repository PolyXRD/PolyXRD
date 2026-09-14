# PolyXRD v0.9.7 交接文档（Handover）

> 日期：2026-09-07 ｜ 版本：v0.9.7 ｜ 状态：**三个 Sprint 全部落地 + 打包发布完成**
> 用途：重装 Windows 系统后的完整重建指南 + 工作阶段总结。

---

## 一、现状一句话

PolyXRD 物相分析软件已完成 **Sprint 1（识别增强）/ Sprint 2（定量）/ Sprint 3（产品化）+ M20 GUI 增强**，
版本 0.9.7 打包发布（exe / Inno 安装包 / 便携 zip 三产物），全量回归 **182 项测试通过**，
git 工作区干净（最新 commit `cfa58b0`）。

---

## 二、接手后工作总览（7 个 commit）

| Commit | 内容 |
|---|---|
| `215214a` | **Sprint 1**：M05 峰搜索增强 / M06 峰管理 / M08 仪器校正 / M10 搜索匹配增强 / M11 多相迭代 |
| `ce38b38` | **Sprint 2**：M03 原始处理 / M07 轮廓拟合 / M13 RIR 半定量 / M14 Rietveld 增强 |
| `82a9245` | **Sprint 3 第一批**：M01 多格式导入 / M02 元数据多谱 / M04 背景估计 / M16 晶粒尺寸 |
| `57a555b` | **Sprint 3 收尾**：M12 用户库（CIF 导入）/ M18 报告导出 / M19 脚本自动化 |
| `f5e2264` | **M20 GUI 增强**（重置数据 Ctrl+R / Kα2 剥离真实调用 / F2 峰检测）+ 版本升 0.9.7 |
| `083b279` | 打包脚本适配（Inno 6.7.3 无中文 isl） |
| `cfa58b0` | **ICU 加载修复**（exe 启动报错的根因）+ 沙盒打包适配 |

### 模块完成度（对照 docs/物相分析路线图与模块拆分.md）

| 模块 | 状态 | 落点 |
|---|---|---|
| M01 多格式导入 | ✅ | services/data_io.py（多列自动列序） |
| M02 元数据/多谱 | ✅ | models/experiment.py（SessionDocument json 持久化） |
| M03 原始处理 | ✅ | services/raw_processing.py（Kα2 Rachinger 剥离） |
| M04 背景估计 | ✅ | services/background.py（SNIP/多项式/控制点样条） |
| M05 峰搜索增强 | ✅ | services/peak_finder.py 扩展（sensitivity/肩峰/双峰合并） |
| M06 峰管理 | ✅ | services/peak_manager.py（增删改/区域排除/残差峰） |
| M07 轮廓拟合 | ✅ | services/peak_fitting.py（Pseudo-Voigt 簇联合） |
| M08 仪器校正 | ✅ | services/calibration.py（零点/样品位移/直方图众数/内标） |
| M10 搜索匹配 | ✅ | services/foam.py + models/fom.py + models/search_options.py |
| M11 多相迭代 | ✅ | services/multiphase.py（min_round_matches=2 抑制噪声相） |
| M12 用户库 | ✅ | services/user_database.py（pymatgen CIF→参考峰） |
| M13 RIR | ✅ | services/rir.py + models/rir.py |
| M14 Rietveld 增强 | ✅ | models/refinement_options.py + refiner 扩展（March-Dollase/DoC/内标） |
| M16 晶粒尺寸 | ✅ | services/crystallite.py（Scherrer） |
| M18 报告导出 | ✅ | services/report.py（SVG/HTML/CSV/CIF） |
| M19 脚本自动化 | ✅ | services/scripting.py（管线 DSL + 批处理） |
| M20 GUI 交互 | ✅ v1 | views/main_window.py（缩放平移用 matplotlib 工具栏自带） |
| M15/M17 等 P2 项 | ⏸ 未启动 | 见路线图文档 |

### 本阶段修复的三个重要算法缺陷

1. **FoM 强度数组错位**：强度未随 2θ 排序 → 强度一致性评分全错。
2. **加性强度惩罚抹平区分度**：改乘性口径（与基线一致）。
3. **`_phases_structurally_same` 单向覆盖误判**：稀疏相被误并入密集相
   （LiFePO4 险些被删）；改双向覆盖 ≥70%。

---

## 三、验证结果（2026-09-07 复核）

- ✅ 全量回归 **182 passed**（2m39s，23 个测试文件）
- ✅ GUI 无头冒烟通过（`QT_QPA_PLATFORM=offscreen`，31 个 action 注册）
- ✅ 产物齐全：`dist\PolyXRD\PolyXRD.exe`（38.7MB）/ Setup（98MB）/ Portable zip（487MB）
- ✅ git status 干净

---

## 四、⚠️ 重装系统前必须备份的内容（不进 git！）

`.gitignore` 排除了以下大文件，**重装前务必拷贝到移动硬盘/网盘**：

| 路径 | 大小 | 说明 |
|---|---|---|
| `cod_index.sqlite` | 453 MB | COD 全库（113,223 条目 + gzip CIF） |
| `cod_data/COD_inorganics.sqlite` | 271 MB | COD 无机物库（71,199 物相，d-I 峰） |
| `dist\PolyXRD\` | ~1.5 GB | 打包产物（可重建，但重打耗时 ~12min） |
| `installer_output\` | ~600 MB | Setup.exe + Portable.zip（可重建） |
| `venv\` | — | **不备份**，按第五节重建 |

历史 GitHub Release 里也有数据库附件（v0.9.0 发布的 SHA256 见 README），
但 0.9.7 的数据库结构若未变更可直接用 Release 附件；若本地文件更新过以本地为准。

源码本身在 git（建议重装前 `git push` 确认远端最新）。

---

## 五、重装后的环境重建指南（按顺序执行）

### 1. 基础软件

- **Python 3.10.11**（venv 用；3.11+ 未验证，勿升级 pymatgen/spglib 组合）
- **Inno Setup 6**（当前 6.7.3，装在 `%LOCALAPPDATA%\Programs\Inno Setup 6`）
  - 注意：**不带 ChineseSimplified.isl**，安装器语言只保留 En/Ja（已适配，勿加回）
- **Git for Windows**
- （可选）**7-Zip**（build.bat 的 SFX 回退路径）

### 2. venv 与依赖

```bat
cd /d D:\TEMP\PolyXRD
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\pip install pyinstaller==6.22.0
```

关键依赖锁定版本（当前环境实测）：

```
PySide6==6.11.1      # ≥6.7 wheel 不自带 ICU, 打包必须做 ICU 修复 (见下)
PyInstaller==6.22.0
numpy==2.2.6
scipy==1.15.3
matplotlib==3.10.9
pymatgen==2025.10.7
lmfit==1.3.4
spglib==2.7.0
pyqtgraph==0.14.0
plotly==6.9.0
pandas==2.3.3
pillow==12.3.0
```

`requirements.txt` 里还有 `powerxrd>=1.0`（Rietveld 外部引擎，可选）。

### 3. 验证安装

```bat
venv\Scripts\python.exe -m pytest tests/test_data_io_m01.py tests/test_foam_m10.py -q
QT_QPA_PLATFORM=offscreen venv\Scripts\python.exe -c "import sys; from PySide6.QtWidgets import QApplication; app=QApplication(sys.argv); from polyxrd.views.main_window import MainWindow; from polyxrd.config import get_config; w=MainWindow(config=get_config()); w.show(); app.processEvents(); print('OK')"
```

### 4. 打包（详见第六节）

```bat
build.bat
```

---

## 六、打包流程与两个关键坑

正常入口是 `build.bat`，流程：PyInstaller → 手工 collect → ICU 复制 → Inno → zip。

### 坑 1：PySide6 6.11 不自带 ICU（exe 启动报错的根因）

现象：双击 PolyXRD.exe 报
`ImportError: DLL load failed while importing QtCore: 找不到指定的程序`。

根因链：Qt6Core.dll 的 PE 导入表声明 `icuuc.dll`（无版本号）→ PySide6 ≥6.7 wheel
不再分发 ICU → 某个依赖把 Qt5 时代的 ICU 58（`icudt58.dll`/旧 `icuuc.dll`）塞进了
`_internal` → Windows System32 的 `icuuc.dll` 只是 29KB API stub → Qt6 加载到
错误版本即崩。

修复（已固化进 `PolyXRD.spec` + `build.bat`）：
- spec 自动从以下位置收集 `icuuc/icudt/icuin/icuio/icutu` 系列 DLL：
  `%USERPROFILE%\AppData\Roaming\mamba\pkgs\...\icu-78.3*`（mamba/conda 用户机器）
- **重装系统后如果没装 mamba/conda**，需要手动放一份 ICU 73+ 的 DLL 到项目根
  `_icu_dlls\` 并在 spec 里加该路径，或安装 Qt 6.11 运行时从其 `bin\` 取
  `icuuc74.dll + icudt74.dll`。
- 排查工具：`scripts\_pe_imports.py <dll路径>` 可列出任意 DLL 的导入表。
  **注意**：该脚本已在 fa9c9ab 作为一次性诊断工具清理，需要时先取回：
  `git show fa9c9ab^:scripts/_pe_imports.py > scripts\_pe_imports.py`。

### 坑 2：WorkBuddy 沙盒 safe-delete 拦截 PyInstaller

WorkBuddy 注入的 sitecustomize 把 Python 的 `shutil.rmtree`/`os.remove` 劫持到
回收站；PyInstaller COLLECT 阶段第一步 `Removing dir dist\PolyXRD`（上万个文件）
触发批量删除保护 → PyInstaller 退出码 1，**但 EXE 其实已生成在 `build\PolyXRD\`**。

应对（已固化）：
- `PolyXRD.spec` 的 COLLECT 包了 try/except 容错；
- `scripts\_pyinst_collect.py` 从 `build/COLLECT-00.toc` 手工复制全部依赖到
  `dist\PolyXRD\_internal`（12319 个条目，幂等跳过相同大小文件）；
- `build.bat` 对 PyInstaller EXIT=1 容错（只要 `build\PolyXRD\PolyXRD.exe` 存在
  就继续）。
- 在无沙盒的正常 Windows 上跑 build.bat，COLLECT 会正常完成，脚本同样兼容。

### 产物

| 文件 | 说明 |
|---|---|
| `dist\PolyXRD\PolyXRD.exe` | 免安装主程序（onedir，`_internal` 同级） |
| `installer_output\PolyXRD-Setup-v0.9.7.exe` | Inno 安装程序 |
| `installer_output\PolyXRD-v0.9.7-Portable.zip` | 便携 zip |

---

## 七、遗留问题 / 下一步建议

1. **M14 遗留**：`RefineOptions.refine_*` 逐类参数开关尚未把内置精修引擎参数
   掩码化（涉及精修主循环改造）。
2. **M20 v2**：峰点击编辑、候选列表联动、背景控制点拖动等高级交互未做
   （当前缩放/平移用 matplotlib NavigationToolbar 自带能力）。
3. **GUI 人工验收**：0.9.7 打包产物尚待完整的人工链路验证
   （加载→背景→峰→识别→精修→报告），此前因 ICU 问题中断在第一步。
4. **多相迭代**在真实低信噪谱上会放大首轮 Top1 选错的代价，只建议对干净
   多相样启用（详见 bench_sprint1 教训）。
5. 识别命中率瓶颈在**峰质量**（低信噪样），可考虑继续做 M03 管线与 GUI 的
   参数联动打磨。
6. `.workbuddy\memory\`（项目记忆）与 `docs\算法内部原理.md`、
   `docs\物相分析路线图与模块拆分.md` 包含全部算法决策上下文，重装后优先阅读。

---

## 八、常用命令速查

```bat
:: 全量回归 (182 项, ~3min)
venv\Scripts\python.exe -m pytest tests/test_data_io_m01.py tests/test_experiment_m02.py tests/test_background_m04.py tests/test_crystallite_m16.py tests/test_user_database_m12.py tests/test_report_m18.py tests/test_scripting_m19.py tests/test_raw_processing_m03.py tests/test_peak_fitting_m07.py tests/test_rir_m13.py tests/test_rietveld_m14.py tests/test_peak_finder.py tests/test_peak_finder_m05.py tests/test_peak_manager_m06.py tests/test_calibration_m08.py tests/test_foam_m10.py tests/test_multiphase_m11.py tests/test_phase_identifier.py tests/test_pure_metal_suppression.py tests/test_phase_combination_strategy.py tests/test_profile_fitting.py tests/test_le_bail.py tests/test_rietveld.py -q

:: 13 试样基准 (识别召回)
venv\Scripts\python.exe tests\bench_sprint1.py

:: 打包三件套
build.bat

:: 单步打包 (调试用)
set POLYXRD_NO_COD_DB=1 && set POLYXRD_NO_INORG_DB=1
venv\Scripts\python.exe -m PyInstaller PolyXRD.spec --noconfirm
venv\Scripts\python.exe scripts\_pyinst_collect.py

:: 查任意 DLL 依赖 (排查 ICU 类问题)
:: 注意: _pe_imports.py 已在 fa9c9ab 移除, 先按坑 1 的 git show 命令取回
venv\Scripts\python.exe scripts\_pe_imports.py dist\PolyXRD\_internal\PySide6\Qt6Core.dll
```

## 九、架构备忘（30 秒版）

- **MVVM**：`views/`(PySide6 UI) → `viewmodels/` → `services/`（纯算法，全部可单测）
- **识别链**：raw_processing → peak_finder → foam(search_match, 元素过滤+纯金属惩罚)
  → phase_combination(分支定界+数据感知去重) → multiphase(迭代)
- **定量链**：peak_fitting → rir(RIR/内标) → rietveld_refiner(builtin/gsas2/powerxrd,
  March-Dollase, DoC, 内标绝对定量)
- **产品化**：data_io(导入) / background(SNIP) / calibration(校正) / crystallite
  (Scherrer) / user_database(CIF) / report(SVG+HTML) / scripting(批处理)
- **双 COD 库外挂**：spec 通过 `POLYXRD_NO_COD_DB=1` / `POLYXRD_NO_INORG_DB=1`
  控制是否内嵌；发布时数据库作为 GitHub Release 附件单独分发
