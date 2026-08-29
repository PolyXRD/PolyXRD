# PolyXRD 项目交接文档

> **生成时间**: 2026-08-18  
> **当前版本**: v0.6.0  
> **项目路径**: `C:\Users\Administrator\Desktop\WorkSpace\Trae\PolyXRD`  
> **Python 版本**: 3.10.11  
> **PySide6 版本**: Qt6

---

## 一、快速开始（新电脑上恢复项目）

### 步骤 1：复制项目文件

将整个 `PolyXRD` 文件夹复制到新电脑任意位置。**完整复制即可**，包括 `src/`、`venv/`、`build.bat`、`run.bat` 等。

> ⚠️ **注意**: `venv/` 中的虚拟环境包含 Windows 特定的二进制文件，跨电脑（尤其跨 CPU 架构）有时会出问题。如果 `venv` 无法直接使用，按下方步骤 2 重建。

### 步骤 2：环境重建（如 venv 不可用）

```powershell
# 1. 安装 Python 3.10+ (从 https://www.python.org 下载)
#    安装时勾选 "Add to PATH"

# 2. 打开 PowerShell，进入项目目录
cd PolyXRD

# 3. 创建虚拟环境
python -m venv venv

# 4. 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 5. 安装依赖 (从 requirements.txt 或 pyproject.toml)
pip install -e .
# 或者：
pip install PySide6 matplotlib numpy scipy pymatgen lmfit pyqtgraph pandas spglib plotly

# 6. 运行程序
python src/polyxrd/main.py
```

### 步骤 3：打包发布版

```powershell
# 方式 A: 使用批处理
build.bat

# 方式 B: 手动 PyInstaller
.\venv\Scripts\python.exe -m PyInstaller PolyXRD.spec --noconfirm --clean
# 产物: dist/PolyXRD/PolyXRD.exe
```

### 步骤 4：在新会话中恢复上下文

打开 Trae（或 TraeCode），将此 MD 文件的全部内容粘贴到新会话中，让 AI 助手读取作为上下文。然后直接说"继续开发 PolyXRD 项目"即可。

---

## 二、项目概述

**PolyXRD** 是一款基于 Python + PySide6 (Qt) 的 X 射线衍射（XRD）分析桌面软件，支持：

- XRD 数据加载与可视化
- 背景扣除、平滑、Kα2 剥离等预处理
- 自动峰检测
- **物相识别**（两种方法）：
  - **Profile Fitting**（峰形拟合，推荐）：无需寻峰，直接基于曲线形貌匹配
  - **传统 Search/Match**：基于 FOM 算法的峰位匹配
- 元素周期表三态过滤（必须/可能/不含）
- Rietveld 结构精修
- 多语言支持（中文/英文/日文）

---

## 三、技术架构

```
polyxrd/
├── main.py                  # 程序入口
├── config.py                # 全局配置
├── i18n/                    # 国际化
│   ├── i18n_manager.py
│   └── translations/        # zh_CN.py, en_US.py, ja_JP.py
├── models/                  # 数据模型
│   ├── xrd_data.py          # XRDData (two_theta, intensity)
│   ├── peak.py              # Peak, PeakList
│   └── phase.py             # Phase, PhaseMatchResult
├── services/                # 业务逻辑
│   ├── peak_finder.py       # 峰检测
│   ├── phase_identifier.py  # 传统 FOM 物相识别
│   ├── profile_fitting.py   # Profile Fitting 物相识别 ★
│   ├── project_service.py   # 项目保存/加载
│   └── structure_simulator.py
├── utils/                   # 工具函数
│   ├── resources.py         # 资源路径解析
│   └── formula_parser.py    # 化学式解析
├── viewmodels/              # MVVM 模式 ViewModel
│   ├── main_vm.py           # MainViewModel (协调各 VM)
│   ├── phase_vm.py          # PhaseViewModel
│   └── refinement_vm.py
├── views/                   # UI 视图
│   ├── main_window.py       # 主窗口 (菜单栏/工具栏/标签页)
│   ├── data_view.py         # 数据视图
│   ├── phase_view.py        # 物相分析视图 ★
│   ├── refinement_view.py   # 结构精修视图
│   ├── report_view.py       # 报告视图
│   └── widgets/             # 可复用组件
│       ├── plot_widget.py           # matplotlib 绘图控件 ★
│       ├── element_periodic_table.py # 元素周期表控件
│       └── element_filter_dialog.py  # 元素过滤对话框 ★
└── resources/               # 静态资源
    ├── icons/               # SVG 图标
    ├── database/            # XRD 参考数据库 (JSON)
    ├── app-icon.ico         # 应用图标 (多尺寸)
    └── splash-screen.jpg    # 启动画面
```

### 设计模式

- **MVVM**: View ↔ ViewModel 通过 Signal/Slot 通信，ViewModel 调用 Service 层
- **Singleton**: ProfileFittingService、PhaseIdentifier 等在 PhaseViewModel 中实例化一次
- **Service Layer**: 所有核心算法（峰检测、物相识别、Profile Fitting）封装为独立 Service 类

---

## 四、最近完成的修改（v0.6.0）

### 4.1 工具栏左对齐 ✅

**文件**: `views/main_window.py`

**改动**:
```python
def _setup_toolbar(self) -> None:
    toolbar = QToolBar(tr("toolbar.main"))
    toolbar.setIconSize(QSize(24, 24))
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toolbar.setFloatable(False)
    toolbar.setMovable(False)          # 新增: 禁止拖动
    toolbar.setContentsMargins(0,0,0,0)  # 新增: 去除内边距
    self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
    # ... 添加按钮 ...
    # 末尾添加 Expanding spacer:
    spacer = QWidget()
    spacer.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    spacer.setMinimumWidth(0)
    toolbar.addWidget(spacer)
    # 强制左对齐:
    toolbar_layout = toolbar.layout()
    if toolbar_layout:
        toolbar_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
```

### 4.2 菜单栏文字标签 ✅

**问题**: 之前给菜单的 `menuAction()` 设置了图标，导致文字被隐藏。

**修复**: 在 `_setup_phase_menu()` 等方法中，移除对菜单 action 的 `_set_action_icon()` 调用。

### 4.3 Profile Fitting 峰形拟合 ✅

**核心文件**: `services/profile_fitting.py`

**算法流程**:
1. 从实验数据自动估计背景线（滚动最小值法）
2. 对数据库中每个物相，生成理论 XRD 图谱（Gaussian 峰形模拟）
3. 计算 Pearson 相关系数衡量曲线形貌相似度
4. 计算 R 因子评估数值偏差
5. 综合评分 = 相关系数 × 100（越接近 100% 越好）

**使用方法**:
```python
from polyxrd.services.profile_fitting import ProfileFittingService

pf = ProfileFittingService()
results = pf.identify(
    data=xrd_data,
    element_filter={"must": ["Si"], "exclude": ["Fe"]},
    top_n=5,
    fwhm=0.15,
)
# 每个 result: .phase, .score (%), .r_factor, .method="profile_fitting"
```

### 4.4 元素周期表 → 弹出对话框 ✅

**新文件**: `views/widgets/element_filter_dialog.py`

**改动**: 原来的内联元素周期表挤占谱图空间，改为"按钮+弹窗"模式：
- PhaseView 中放置"元素过滤(周期表)"按钮
- 点击弹出 `ElementFilterDialog` 对话框
- 对话框内包含完整的 `ElementPeriodicTable` + 图例 + 实时摘要
- 选择确认后，过滤条件传入识别方法

### 4.5 物相匹配可视化 ✅

**文件**: `views/phase_view.py` 中的 `_on_candidate_clicked()` 和 `_add_match_annotations()`

**功能**: 点击候选物相后，在谱图上显示：
- **绿色实线** = 已匹配峰（实验中存在的峰）
- **红色虚线** = 未匹配峰（参考峰在实验中找不到）
- 标注 hkl 和 2θ 值
- 右上角图例显示匹配/未匹配统计

### 4.6 物相确认 → 自动切换精修 ✅

**流程**:
1. 用户点击"选中物相 →"按钮
2. 弹出确认对话框（询问是否切换到结构精修）
3. 确认后:
   - `PhaseView.phase_confirmed` 信号发射
   - `MainWindow._on_phase_confirmed()` 接收
   - 自动切换到结构精修标签页
   - 状态栏显示"已确认物相: xxx，切换到结构精修"

### 4.7 EXE 图标修复 ✅

**问题**: `app-icon.ico` 只有 232 字节，缺少多尺寸，Windows 显示黑方块。

**修复**: 使用 Pillow 重新生成 6 种尺寸（16/32/48/64/128/256）的 ICO 文件。

```python
from PIL import Image
img = Image.open("app-icon.png")
icon_sizes = [(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)]
icons = [img.resize(s, Image.LANCZOS) for s in icon_sizes]
icons[-1].save("app-icon.ico", format="ICO", append_images=icons[:-1])
```

---

## 五、PhaseMatchResult 数据模型

两种方法使用统一的 `PhaseMatchResult`，通过 `method` 字段区分：

```python
@dataclass
class PhaseMatchResult:
    phase: Phase
    score: float              # Profile Fitting: 0-100 (越高越好)
                              # FOM: 越低越好
    matched_peaks: int = 0
    total_peaks: int = 0
    confidence: str = ""
    r_factor: float = 0.0     # Profile Fitting 专用
    method: str = "fom"       # "fom" 或 "profile_fitting"
    
    @property
    def score_display(self) -> str:
        if self.method == "profile_fitting":
            return f"{self.score:.1f}%"    # 百分比
        else:
            return f"{self.score:.3f}"    # FOM 值
```

---

## 六、物相数据库

- 路径: `resources/database/xrd_reference_database.json`
- 物相数: **118 种**（Cu Kα = 1.5406 Å）
- 每个物相包含: 名称、化学式、元素列表、参考峰 (2θ, d, hkl, 相对强度)

---

## 七、关键依赖

| 包 | 用途 |
|---|---|
| PySide6 | Qt GUI 框架 |
| matplotlib | XRD 绘图 |
| numpy | 数值计算 |
| scipy | 峰检测、背景估计 |
| pymatgen | 晶体结构处理 |
| lmfit | 最小二乘拟合 |
| pyqtgraph | 高性能绘图（可选） |
| pandas | 数据处理 |
| spglib | 空间群操作 |
| PyInstaller | 打包为 EXE |

---

## 八、已验证的测试场景

所有以下测试均已通过：

| # | 测试项 | 结果 |
|---|--------|------|
| 1 | 工具栏左对齐 + 文字标签 | ✅ |
| 2 | 菜单栏 7 项中文标签 | ✅ |
| 3 | Profile Fitting UI (按钮/FWHM/周期表) | ✅ |
| 4 | Profile Fitting 算法 (α-Quartz 匹配 88.6%) | ✅ |
| 5 | 元素过滤 (单元素 + 组合) | ✅ |
| 6 | 传统 FOM Search/Match | ✅ |
| 7 | PhaseMatchResult 模型区分 | ✅ |
| 8 | 周期表三态交互 | ✅ |
| 9 | 数据库元素完整性 (118/118) | ✅ |
| 10 | ElementFilterDialog 创建 | ✅ |
| 11 | phase_confirmed 信号连接 | ✅ |
| 12 | PlotWidget.set_info_text | ✅ |
| 13 | PyInstaller 打包 (34.8 MB) | ✅ |

---

## 九、已知待改进项

1. **匹配可视化精度**: 当前峰匹配使用 0.2° 容差，可根据数据分辨率调整
2. **多相混合分析**: `_on_auto_mix()` 尚未实现（GUI 按钮已占位）
3. **Rietveld 精修完善**: 精修视图已有框架，需进一步完善参数面板
4. **COD 在线搜索**: 已有对话框框架，需要对接 COD API
5. **单元测试**: 目前以手动验证为主，建议补充 pytest 单元测试

---

## 十、在新环境中快速恢复上下文的方法

### 方法 A：将本文件粘贴为上下文

1. 在 Trae 新会话中，将**本 MD 文件的全部内容**复制粘贴到对话框
2. 追加一句："请读取以上项目交接文档，分析当前项目状态，然后继续开发 PolyXRD"
3. AI 助手会基于此文档恢复全部上下文

### 方法 B：让 AI 读取此文件

```
请读取 C:/path/to/PROJECT_HANDOVER.md 文件
然后分析 PolyXRD 项目当前状态并继续开发
```

### 方法 C：快速提问清单

如果需要快速定位：
- "PolyXRD 项目用了什么架构模式？"
- "Profile Fitting 算法在哪里实现？"
- "物相确认后怎么切换到精修页面？"
- "工具栏左对齐是怎么实现的？"

---

## 附录：关键文件索引

| 文件 | 说明 |
|------|------|
| [main_window.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/views/main_window.py) | 主窗口，含工具栏/菜单/标签页 |
| [phase_view.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/views/phase_view.py) | 物相分析视图（主要修改） |
| [plot_widget.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/views/widgets/plot_widget.py) | matplotlib 绘图控件 |
| [element_filter_dialog.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/views/widgets/element_filter_dialog.py) | 元素过滤对话框（新建） |
| [element_periodic_table.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/views/widgets/element_periodic_table.py) | 元素周期表控件 |
| [profile_fitting.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/services/profile_fitting.py) | Profile Fitting 算法（新建） |
| [phase_identifier.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/services/phase_identifier.py) | 传统 FOM 物相识别 |
| [phase.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/models/phase.py) | Phase/PhaseMatchResult 模型 |
| [phase_vm.py](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/viewmodels/phase_vm.py) | 物相分析 ViewModel |
| [i18n 三语](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/i18n/translations) | 国际化翻译文件 |
| [PolyXRD.spec](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/PolyXRD.spec) | PyInstaller 打包配置 |
| [build.bat](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/build.bat) | 一键打包脚本 |
| [app-icon.ico](file:///C:/Users/Administrator/Desktop/WorkSpace/Trae/PolyXRD/src/polyxrd/resources/app-icon.ico) | 应用图标（已修复） |

---

**祝开发顺利！** 🎉