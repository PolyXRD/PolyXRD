"""
PolyXRD - X射线衍射仪数据分析软件
========================================
设计规范文档 v1.0

本文件定义了 PolyXRD 软件的完整设计方案，供AI自动编码使用。
"""

# ============================================================================
# 第一部分：技术选型与依赖
# ============================================================================

TECH_STACK = {
    "语言": "Python 3.11+",
    "UI框架": "PySide6 (Qt for Python)",
    "绘图": "matplotlib (嵌入Qt) + pyqtgraph (实时交互绘图)",
    "Rietveld精修": "GSAS-II (GSASIIscriptable API)",
    "物相识别": "pymatgen + powerxrd",
    "峰拟合": "lmfit + scipy.optimize",
    "信号处理": "numpy + scipy",
    "数据分析": "pandas",
    "晶体结构": "pymatgen (Structure, Lattice)",
    "PDF数据库": "本地CIF文件 + COD开放数据库",
    "打包": "PyInstaller",
    "测试": "pytest",
    "代码规范": "ruff + black + mypy",
}

# 依赖清单（requirements.txt）
DEPENDENCIES = """
# === 核心依赖 ===
numpy>=1.24.0,<2.0.0
scipy>=1.10.0
pandas>=2.0.0
matplotlib>=3.7.0
PySide6>=6.5.0
pyqtgraph>=0.13.0

# === 科学计算 ===
pymatgen>=2024.1.26
lmfit>=1.3.0

# === XRD分析 ===
powerxrd>=2.3.0

# === Rietveld精修 ===
# GSAS-II 需要从源码安装: pip install GSAS-II
# GSAS-II 是美国阿贡国家实验室开发的开源软件
# GitHub: https://github.com/AdvancedPhotonSource/GSAS-II

# === 工具 ===
Pillow>=9.0.0
platformdirs>=3.0.0
"""


# ============================================================================
# 第二部分：项目目录结构
# ============================================================================

PROJECT_STRUCTURE = """
PolyXRD/
├── pyproject.toml                 # 项目配置
├── requirements.txt               # 依赖清单
├── README.md
├── LICENSE
│
├── src/
│   ├── main.py                    # 程序入口
│   ├── polyxrd/
│   │   ├── __init__.py
│   │   ├── app.py                 # QApplication 初始化
│   │   ├── config.py              # 全局配置
│   │   │
│   │   ├── models/                # 数据模型层 (MVVM - Model)
│   │   │   ├── __init__.py
│   │   │   ├── xrd_data.py        # XRD实验数据模型
│   │   │   ├── phase.py           # 物相模型
│   │   │   ├── structure.py       # 晶体结构模型
│   │   │   ├── refinement.py      # 精修结果模型
│   │   │   └── analysis_result.py # 分析结果模型
│   │   │
│   │   ├── services/              # 业务逻辑层
│   │   │   ├── __init__.py
│   │   │   ├── data_loader.py     # 数据加载服务
│   │   │   ├── data_processor.py  # 数据预处理服务
│   │   │   ├── peak_finder.py     # 峰识别服务
│   │   │   ├── peak_fitter.py     # 峰拟合服务
│   │   │   ├── phase_identifier.py # 物相识别服务
│   │   │   ├── rietveld_refiner.py # Rietveld精修服务
│   │   │   ├── structure_simulator.py # 结构模拟服务
│   │   │   └── export_service.py  # 导出服务
│   │   │
│   │   ├── viewmodels/            # ViewModel层
│   │   │   ├── __init__.py
│   │   │   ├── main_vm.py
│   │   │   ├── data_vm.py
│   │   │   ├── phase_vm.py
│   │   │   ├── refinement_vm.py
│   │   │   └── report_vm.py
│   │   │
│   │   ├── views/                 # 视图层 (MVVM - View)
│   │   │   ├── __init__.py
│   │   │   ├── main_window.py     # 主窗口
│   │   │   ├── data_view.py       # 数据视图
│   │   │   ├── phase_view.py      # 物相分析视图
│   │   │   ├── refinement_view.py # 精修视图
│   │   │   ├── report_view.py     # 报告视图
│   │   │   └── widgets/           # 可复用控件
│   │   │       ├── __init__.py
│   │   │       ├── plot_widget.py
│   │   │       ├── peak_table.py
│   │   │       └── parameter_editor.py
│   │   │
│   │   └── utils/                 # 工具函数
│   │       ├── __init__.py
│   │       ├── file_utils.py
│   │       ├── math_utils.py
│   │       └── validators.py
│   │
│   └── resources/
│       ├── icons/
│       ├── styles/
│       └── templates/
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # pytest fixtures
│   ├── data/                      # 测试数据
│   │   ├── sample.xy              # 示例XRD数据
│   │   ├── sample.dat
│   │   └── test_structures/       # 测试用CIF文件
│   ├── test_models/
│   │   ├── test_xrd_data.py
│   │   └── test_phase.py
│   ├── test_services/
│   │   ├── test_data_loader.py
│   │   ├── test_data_processor.py
│   │   ├── test_peak_finder.py
│   │   ├── test_peak_fitter.py
│   │   ├── test_phase_identifier.py
│   │   └── test_rietveld_refiner.py
│   └── test_integration/
│       └── test_full_workflow.py
│
└── docs/
    ├── architecture.md
    ├── api_reference.md
    └── user_guide.md
"""


# ============================================================================
# 第三部分：模块功能规格
# ============================================================================

MODULE_SPECS = {
    # ------------------------------------------------------------------------
    # 3.1 数据模型层 (models)
    # ------------------------------------------------------------------------
    "models.xrd_data": {
        "职责": "封装XRD实验数据，包括2θ数组、强度数组、元数据",
        "核心类": "XRDData",
        "属性": {
            "two_theta": "np.ndarray - 2θ角度数组（单位：度）",
            "intensity": "np.ndarray - 衍射强度数组",
            "wavelength": "float - X射线波长（单位：Å），默认Cu Kα=1.5406",
            "xray_source": "str - X射线源标识（'Cu Ka', 'Mo Ka', 'Co Ka'等）",
            "file_path": "str - 数据文件路径",
            "timestamp": "datetime - 测量时间",
            "instrument": "str - 仪器型号",
            "metadata": "dict - 其他元数据",
        },
        "方法": {
            "get_d_spacing()": "将2θ转换为d-spacing（布拉格定律）",
            "plot(ax)": "在给定matplotlib轴上绘制XRD曲线",
            "export_csv(path)": "导出为CSV文件",
            "clone()": "深拷贝数据",
        },
        "验证规则": [
            "two_theta 和 intensity 长度必须相同",
            "two_theta 范围必须在 0-180 度之间",
            "intensity 必须非负（或允许少量负值背景）",
            "wavelength 必须在 0.1-10 Å 范围内",
        ],
        "测试方法": "用已知的标准数据（如Si粉、Al2O3）验证d-spacing计算正确性",
    },

    "models.phase": {
        "职责": "表示一个物相及其衍射特征",
        "核心类": "Phase",
        "属性": {
            "name": "str - 物相名称",
            "formula": "str - 化学式",
            "cif_path": "str - CIF文件路径",
            "lattice_params": "dict - 晶格参数 {a, b, c, alpha, beta, gamma}",
            "space_group": "str - 空间群符号",
            "peaks": "List[Peak] - 衍射峰列表",
            "weight_fraction": "float - 质量分数（Rietveld结果）",
            "match_score": "float - 匹配度评分 (0-100)",
        },
        "验证规则": [
            "晶格参数必须为正数",
            "空间群必须是合法的空间群符号",
            "峰的hkl索引必须对应",
        ],
    },

    "models.peak": {
        "职责": "表示一个衍射峰",
        "核心类": "Peak",
        "属性": {
            "two_theta": "float - 峰位2θ",
            "d_spacing": "float - d-spacing",
            "intensity": "float - 峰强度",
            "fwhm": "float - 半高宽",
            "hkl": "tuple - Miller指数 (h, k, l)",
            "phase": "str - 所属物相",
        },
    },

    "models.refinement": {
        "职责": "封装Rietveld精修结果",
        "核心类": "RefinementResult",
        "属性": {
            "wR": "float - Rwp（加权轮廓R因子）",
            "R_exp": "float - 期望R因子",
            "GOF": "float - 优度因子 (Goodness of Fit)",
            "chi_sq": "float - 卡方值",
            "parameters": "dict - 精修后的参数",
            "phases": "List[Phase] - 精修后的物相列表",
            "converged": "bool - 是否收敛",
            "residual_plot": "tuple - 残差数据 (x, y)",
        },
        "验证规则": [
            "Rwp 一般应 < 10%（良好收敛 < 5%）",
            "GOF 应接近 1.0（通常 0.8-2.0）",
            "权重分数之和应接近1.0（多相分析）",
        ],
    },

    # ------------------------------------------------------------------------
    # 3.2 业务逻辑层 (services)
    # ------------------------------------------------------------------------

    "services.data_loader": {
        "职责": "加载各种格式的XRD数据文件",
        "支持格式": [
            ".xy - 两列文本格式（2θ, Intensity）",
            ".dat - 通用文本格式（带可选头）",
            ".xrdml - Panalytical XML格式",
            ".raw - Bruker RAW格式",
            ".brml - Bruker BRML格式",
            ".csv - CSV格式",
            ".txt - 通用文本",
        ],
        "核心类": "DataLoader",
        "方法": {
            "load(file_path, **kwargs)": "加载指定格式文件，返回XRDData",
            "detect_format(file_path)": "自动检测文件格式",
            "list_supported_formats()": "返回支持的格式列表",
        },
        "输入规格": {
            "file_path": "str - 文件的绝对路径",
            "kwargs": {
                "skip_rows": "int - 跳过的头行数（.xy/.dat格式）",
                "delimiter": "str - 列分隔符",
                "two_theta_col": "int - 2θ所在列索引（从0开始）",
                "intensity_col": "int - 强度所在列索引",
                "wavelength": "float - X射线波长覆盖",
            },
        },
        "输出规格": {
            "返回": "XRDData 实例",
            "异常": {
                "FileNotFoundError": "文件不存在",
                "FormatNotSupportedError": "不支持的文件格式",
                "DataFormatError": "数据格式错误（如列数不足）",
            },
        },
        "测试规范": [
            "必须包含每个支持格式的测试用例",
            "必须测试边界情况：空文件、单峰数据、大范围数据",
            "必须与标准数据验证：Si粉、Al2O3、石英等",
            "测试数据精度到小数点后4位",
        ],
    },

    "services.data_processor": {
        "职责": "XRD数据预处理：背景扣除、平滑、Kα2剥离、归一化",
        "核心类": "DataProcessor",
        "方法": {
            "subtract_background(data, method='snip', **kwargs)": "背景扣除",
            "smooth(data, method='savgol', window=11, polyorder=3)": "平滑处理",
            "strip_kalpha2(data)": "Kα2峰剥离",
            "normalize(data, method='minmax')": "数据归一化",
            "remove_baseline(data, baseline_type='linear')": "基线去除",
            "crop(data, two_theta_range)": "裁剪2θ范围",
        },
        "背景扣除方法": {
            "snip": "SNIP算法（最常用）",
            "als": "不对称最小二乘法",
            "polyfit": "多项式拟合",
            "median": "中值滤波",
            "manual": "手动基线点",
        },
        "输入输出": {
            "输入": "XRDData 实例",
            "输出": "处理后的 XRDData 实例（保持不可变性，返回新实例）",
        },
        "测试规范": [
            "背景扣除后数据应无系统性负值（除背景本身）",
            "平滑不改变峰位位置（峰位偏移 < 0.01° 2θ）",
            "Kα2剥离后峰形对称性改善",
            "使用powerxrd库的参考实现进行交叉验证",
        ],
    },

    "services.peak_finder": {
        "职责": "自动识别XRD图谱中的衍射峰",
        "核心类": "PeakFinder",
        "方法": {
            "find_peaks(data, **kwargs)": "自动检测峰位",
            "set_threshold(threshold)": "设置检测阈值",
            "set_min_distance(min_dist)": "设置峰间最小距离",
        },
        "算法参数": {
            "method": "'scipy_find_peaks' | 'powerxrd_emission_lines' | 'custom'",
            "height": "float - 最小峰高（相对于最大强度的百分比）",
            "prominence": "float - 峰的突出度",
            "distance": "int - 峰间最小数据点数",
            "width": "int/tuple - 峰宽度范围",
        },
        "输出": {
            "返回": "List[Peak] - 检测到的峰列表",
        },
        "测试规范": [
            "对标准Si粉数据：识别的峰位偏差 < 0.05° 2θ",
            "对Al2O3数据：所有12个主要峰都应被识别",
            "假阳性率 < 5%（随机噪声中不应产生伪峰）",
            "峰应按2θ从小到大排序",
        ],
    },

    "services.peak_fitter": {
        "职责": "对检测到的峰进行精修拟合",
        "核心类": "PeakFitter",
        "方法": {
            "fit_peak(data, peak, model='voigt')": "拟合单个峰",
            "fit_multiple_peaks(data, peaks, model='voigt')": "多峰同时拟合",
            "get_fit_report()": "获取拟合报告",
        },
        "支持的峰形模型": {
            "gaussian": "高斯函数",
            "lorentzian": "洛伦兹函数",
            "voigt": "Voigt函数（卷积）",
            "pseudo_voigt": "伪Voigt（线性组合，更快）",
            "gaussian_with_tail": "带尾部的高斯",
            "emg": "指数修正高斯（EMG）",
        },
        "拟合参数": {
            "amplitude": "峰振幅",
            "center": "峰位2θ",
            "sigma": "高斯标准差",
            "gamma": "洛伦兹半高宽参数",
            "fwhm": "半高宽",
        },
        "测试规范": [
            "使用lmfit库进行非线性最小二乘拟合",
            "对合成数据（已知参数）：参数恢复误差 < 1%",
            "拟合R² > 0.99",
            "物理约束：所有参数有合理的上下界",
            "支持用户自定义初始参数",
        ],
    },

    "services.phase_identifier": {
        "职责": "通过搜索匹配进行物相识别",
        "核心类": "PhaseIdentifier",
        "方法": {
            "identify(data, elements=None, **kwargs)": "自动识别物相",
            "search_candidates(data, phase_db, top_n=5)": "搜索候选物相",
            "calculate_match_score(experimental_peak, reference_peak)": "计算匹配度",
            "auto_mix(candidates, data)": "多相混合分析",
        },
        "识别策略": {
            "strategy_peak_match": "基于峰位匹配（传统方法）",
            "strategy_full_pattern": "全谱匹配",
            "strategy_ml": "机器学习辅助（autoXRD）",
            "strategy_hybrid": "混合策略（推荐）",
        },
        "数据库": {
            "local_cif": "本地CIF文件库",
            "cod": "COD开放数据库（通过pymatgen访问）",
            "materials_project": "Materials Project数据库",
        },
        "匹配评分": {
            "峰位匹配度": "基于2θ偏差的评分",
            "强度匹配度": "基于相对强度的评分",
            "综合评分": "加权组合",
        },
        "测试规范": [
            "对单一物相样品（如Si粉）：正确识别率 > 95%",
            "对多相混合样品（如α-Fe + Fe3O4）：正确识别所有相",
            "排除已知元素以外的物相",
            "提供至少Top-5候选及置信度",
        ],
    },

    "services.rietveld_refiner": {
        "职责": "执行Rietveld结构精修",
        "核心类": "RietveldRefiner",
        "方法": {
            "setup(data, phases, instrument_params)": "设置精修参数",
            "refine(**kwargs)": "执行Rietveld精修",
            "refine_phase_fractions()": "精修物相含量",
            "refine_lattice_params()": "精修晶格参数",
            "refine_atomic_params()": "精修原子位置和热参数",
            "get_result()": "获取精修结果",
            "get_evolution()": "获取参数演化历史",
        },
        "精修引擎": {
            "gsas2": "GSAS-II（推荐，功能最完整）",
            "powerxrd_mvr": "powerxrd MVR（最小化Rietveld）",
        },
        "精修策略": {
            "sequential": "顺序精修（背景→标度→晶格→原子）",
            "auto": "自动精修（AI策略选择）",
            "manual": "用户手动控制每一步",
        },
        "可精修参数": [
            "背景系数（多项式系数）",
            "标度因子",
            "晶格参数 (a, b, c, alpha, beta, gamma)",
            "原子位置 (x, y, z)",
            "热振动参数 (Uiso)",
            "占有率",
            "原子散射因子",
            "峰形参数 (U, V, W, X, Y)",
            "样品位移",
            "零误差",
        ],
        "测试规范": [
            "使用GSAS-II官方教程数据（PBSO4）：Rwp < 5%",
            "晶格参数偏差 < 0.01 Å",
            "原子位置偏差 < 0.001",
            "物相含量偏差 < 1 wt%",
            "精修结果可重现（多次运行结果一致）",
        ],
        "依赖": [
            "GSAS-II (GSASIIscriptable)",
            "pymatgen (CIF解析)",
        ],
    },

    "services.structure_simulator": {
        "职责": "从晶体结构模拟XRD图谱",
        "核心类": "StructureSimulator",
        "方法": {
            "simulate(structure, wavelength, two_theta_range)": "模拟XRD图谱",
            "compare_patterns(simulated, experimental)": "比较模拟与实验图谱",
            "generate_reference_peaks(structure)": "生成参考峰列表",
        },
        "依赖": [
            "pymatgen (XRDCalculator)",
        ],
        "测试规范": [
            "模拟Si粉XRD与标准PDF卡片峰位偏差 < 0.02°",
            "支持Cu Kα, Mo Kα, Co Kα等常用光源",
            "可选择是否考虑Kα2",
        ],
    },

    "services.export_service": {
        "职责": "导出分析结果为各种格式",
        "核心类": "ExportService",
        "方法": {
            "export_rietveld_result(result, path, format)": "导出Rietveld结果",
            "export_phase_report(phases, path)": "导出物相分析报告",
            "export_plot(figure, path, dpi)": "导出图谱",
            "export_cif(structure, path)": "导出CIF文件",
        },
        "支持格式": {
            "rietveld": [".gpx (GSAS-II项目)", ".cif", ".txt (参数报告)", ".csv"],
            "report": [".pdf", ".docx", ".html", ".md"],
            "plot": [".png", ".pdf", ".svg", ".eps", ".tiff"],
        },
    },

    # ------------------------------------------------------------------------
    # 3.3 ViewModel层 (viewmodels)
    # ------------------------------------------------------------------------

    "viewmodels.main_vm": {
        "职责": "主窗口ViewModel，协调所有子ViewModel",
        "核心类": "MainViewModel",
        "属性": {
            "current_data": "XRDData - 当前加载的数据",
            "current_phases": "List[Phase] - 当前识别的物相",
            "current_refinement": "RefinementResult - 当前精修结果",
            "is_busy": "bool - 是否正在执行任务",
            "status_message": "str - 状态栏消息",
        },
        "方法": {
            "load_file(path)": "加载文件",
            "start_identification()": "开始物相识别",
            "start_refinement()": "开始Rietveld精修",
            "export_result(path)": "导出结果",
        },
        "信号": {
            "data_changed": "数据变更",
            "phase_identified": "物相识别完成",
            "refinement_completed": "精修完成",
            "error_occurred(msg)": "错误发生",
            "status_changed(msg)": "状态变更",
            "progress_changed(percent)": "进度变更",
        },
    },

    "viewmodels.data_vm": {
        "职责": "数据管理ViewModel",
        "功能": [
            "文件加载/保存",
            "数据预处理操作",
            "多图谱叠加对比",
        ],
    },

    "viewmodels.phase_vm": {
        "职责": "物相分析ViewModel",
        "功能": [
            "物相识别",
            "候选物相列表显示",
            "匹配度可视化",
            "物相手动选择/排除",
        ],
    },

    "viewmodels.refinement_vm": {
        "职责": "Rietveld精修ViewModel",
        "功能": [
            "精修参数编辑",
            "精修过程控制",
            "收敛诊断",
            "参数演化显示",
            "结果对比",
        ],
    },

    "viewmodels.report_vm": {
        "职责": "报告生成ViewModel",
        "功能": [
            "报告模板选择",
            "结果填充",
            "导出为多种格式",
        ],
    },

    # ------------------------------------------------------------------------
    # 3.4 视图层 (views)
    # ------------------------------------------------------------------------

    "views.main_window": {
        "职责": "主应用窗口",
        "布局": {
            "菜单栏": ["文件", "数据处理", "物相分析", "结构精修", "报告", "视图", "帮助"],
            "工具栏": ["打开", "保存", "数据处理", "物相识别", "Rietveld精修", "导出"],
            "中央区域": "多标签页（数据/物相/精修/报告）",
            "停靠窗口": ["参数面板", "物相列表", "精修日志"],
            "状态栏": "显示当前操作状态和进度",
        },
        "尺寸": {
            "默认": "1280 x 800",
            "最小": "1024 x 700",
            "自适应": "支持高DPI缩放",
        },
    },

    "views.data_view": {
        "职责": "数据显示和处理视图",
        "组件": [
            "交互式绘图区（matplotlib/pyqtgraph嵌入）",
            "数据列表面板",
            "处理工具条",
            "峰标注层",
        ],
        "交互功能": [
            "缩放/平移",
            "点击选择峰",
            "框选区域",
            "多图谱叠加",
            "自定义背景点选择",
        ],
    },

    "views.phase_view": {
        "职责": "物相分析视图",
        "组件": [
            "物相识别结果列表（含匹配度）",
            "参考峰与实验峰对照图",
            "元素过滤面板",
            "物相数据库浏览器",
        ],
    },

    "views.refinement_view": {
        "职责": "Rietveld精修视图",
        "组件": [
            "精修参数编辑器",
            "精修进度显示",
            "收敛诊断图（Rwp演化、GOF演化）",
            "精修前后对比图",
            "残差图",
            "物相含量饼图",
        ],
    },

    "views.report_view": {
        "职责": "报告预览和导出视图",
        "组件": [
            "报告预览区",
            "模板选择器",
            "导出按钮组",
        ],
    },

    # ------------------------------------------------------------------------
    # 3.5 可复用控件 (views.widgets)
    # ------------------------------------------------------------------------

    "views.widgets.plot_widget": {
        "职责": "封装matplotlib的可交互绘图控件",
        "功能": [
            "绘制单个/多个XRD图谱",
            "添加/删除峰标注",
            "交互式背景点选择",
            "峰拟合曲线叠加",
            "残差曲线显示",
            "参考峰垂直标线",
            "缩放/平移/框选",
            "主题切换（浅色/深色）",
            "导出为图片",
        ],
        "依赖": ["matplotlib", "PySide6"],
    },

    "views.widgets.peak_table": {
        "职责": "显示检测到的峰列表",
        "列": ["编号", "2θ", "d(Å)", "强度", "FWHM", "hkl", "物相", "操作"],
        "功能": ["排序", "筛选", "选择", "编辑", "删除", "导出CSV"],
    },

    "views.widgets.parameter_editor": {
        "职责": "精修参数编辑器",
        "功能": [
            "分类显示参数（背景/晶格/原子/峰形）",
            "勾选精修/固定",
            "设置参数范围约束",
            "参数值实时验证",
            "参数分组管理",
        ],
    },
}


# ============================================================================
# 第四部分：数据流与接口规范
# ============================================================================

DATA_FLOW = {
    "主流程": [
        "1. 用户打开数据文件 → DataLoader.load() → XRDData",
        "2. 数据预处理 → DataLoader → DataProcessor → XRDData",
        "3. 峰检测 → PeakFinder.find_peaks() → List[Peak]",
        "4. 峰拟合 → PeakFitter.fit_multiple_peaks() → List[Peak] (精修)",
        "5. 物相识别 → PhaseIdentifier.identify() → List[Phase] (候选)",
        "6. 用户确认物相 → Phase列表 (选定)",
        "7. Rietveld精修 → RietveldRefiner.refine() → RefinementResult",
        "8. 结果展示 + 导出 → ExportService → 报告/图片/CIF",
    ],
    "并发处理": {
        "规则": "所有耗时操作（精修、大规模搜索）必须在QThreadPool中执行",
        "进度": "通过信号机制实时通知UI进度",
        "取消": "支持用户取消正在进行的操作",
    },
    "错误处理": {
        "规则": "所有服务层方法必须捕获异常并返回有意义的错误信息",
        "UI": "通过error_occurred信号显示错误对话框",
        "日志": "所有错误同时写入日志文件",
    },
}


# ============================================================================
# 第五部分：测试规范
# ============================================================================

TEST_SPEC = {
    "单元测试": {
        "覆盖率要求": "核心服务层 ≥ 90%",
        "测试框架": "pytest",
        "Mock策略": "服务间依赖使用Mock对象",
        "测试数据": "tests/data/ 目录下放置标准数据",
    },
    "集成测试": {
        "全流程测试": "从数据加载到报告生成的完整流程",
        "使用真实数据": "包含Si粉、Al2O3、石英等标准样品",
        "验证标准": "结果与文献/仪器软件一致",
    },
    "性能测试": {
        "数据加载": "10MB数据文件加载时间 < 2秒",
        "峰识别": "1000个数据点的峰识别 < 1秒",
        "物相搜索": "候选物相搜索 < 10秒（本地CIF库）",
        "Rietveld精修": "单相冲速精修 < 30秒",
    },
    "标准测试数据集": [
        {
            "样品": "Si粉 (NIST SRM 640e)",
            "2θ范围": "10-90°",
            "验证指标": "晶格参数 a = 5.431 Å",
            "来源": "NIST标准参考数据",
        },
        {
            "样品": "Al2O3 (刚玉)",
            "2θ范围": "10-90°",
            "验证指标": "主要峰位与PDF卡片对照",
        },
        {
            "样品": "α-Fe (铁素体)",
            "2θ范围": "40-100°",
            "验证指标": "晶格参数 a = 2.866 Å",
        },
        {
            "样品": "混合相 (CaCO3 + SiO2)",
            "2θ范围": "10-80°",
            "验证指标": "各相含量偏差 < 5%",
        },
    ],
}


# ============================================================================
# 第六部分：实施路线图
# ============================================================================

IMPLEMENTATION_ROADMAP = {
    "阶段1_基础框架": {
        "优先级": "最高",
        "预计工时": "5天",
        "任务列表": [
            "1.1 搭建项目骨架（目录结构、pyproject.toml、requirements.txt）",
            "1.2 实现 models 层所有数据模型",
            "1.3 实现 config.py 全局配置",
            "1.4 搭建 PySide6 主窗口框架",
            "1.5 实现 plot_widget.py 基础绘图控件",
            "1.6 编写 models 层单元测试",
        ],
        "验收标准": [
            "项目可 pip install",
            "python -m polyxrd 可启动空白主窗口",
            "所有模型单元测试通过",
        ],
    },
    "阶段2_数据处理": {
        "优先级": "高",
        "预计工时": "7天",
        "任务列表": [
            "2.1 实现 DataLoader（支持 .xy 和 .dat 格式）",
            "2.2 实现 DataProcessor（背景扣除、平滑、归一化）",
            "2.3 实现 PeakFinder（scipy find_peaks 封装）",
            "2.4 实现 PeakFitter（lmfit 多峰拟合）",
            "2.5 编写 data_loader, data_processor, peak_finder, peak_fitter 的单元测试",
            "2.6 在 plot_widget 中集成数据加载和峰显示",
        ],
        "验收标准": [
            "可加载 Si 粉 .xy 数据并正确显示",
            "峰识别结果与标准卡片偏差 < 0.05°",
            "峰拟合 R² > 0.99",
        ],
    },
    "阶段3_物相分析": {
        "优先级": "高",
        "预计工时": "7天",
        "任务列表": [
            "3.1 准备本地 CIF 数据库（常见物相 CIF 文件）",
            "3.2 实现 StructureSimulator（pymatgen XRDCalculator 封装）",
            "3.3 实现 PhaseIdentifier（峰位匹配算法）",
            "3.4 实现 phase_view.py 物相分析视图",
            "3.5 编写 phase_identifier 和 structure_simulator 测试",
        ],
        "验收标准": [
            "单相样品正确识别率 > 95%",
            "多相混合物可识别所有主要相",
            "提供 Top-5 候选及置信度",
        ],
    },
    "阶段4_Rietveld精修": {
        "优先级": "核心",
        "预计工时": "14天",
        "任务列表": [
            "4.1 集成 GSAS-II (GSASIIscriptable)",
            "4.2 实现 RietveldRefiner（封装 GSAS-II 精修流程）",
            "4.3 实现顺序精修策略",
            "4.4 实现 refine 参数编辑器 UI",
            "4.5 实现精修结果可视化（对比图、残差图）",
            "4.6 编写 rietveld_refiner 测试（使用 GSAS-II 教程数据）",
        ],
        "验收标准": [
            "PBSO4 数据 Rwp < 5%",
            "晶格参数偏差 < 0.01 Å",
            "精修过程可中断",
            "参数演化历史可查看",
        ],
    },
    "阶段5_报告与导出": {
        "优先级": "中",
        "预计工时": "5天",
        "任务列表": [
            "5.1 实现 ExportService",
            "5.2 实现 report_view.py",
            "5.3 实现图谱导出（高质量PNG/PDF/SVG）",
            "5.4 实现精修报告生成",
        ],
        "验收标准": [
            "导出图片分辨率 ≥ 300 dpi",
            "报告包含所有关键参数",
            "CIF 文件与标准软件兼容",
        ],
    },
    "阶段6_完善与优化": {
        "优先级": "中",
        "预计工时": "7天",
        "任务列表": [
            "6.1 实现更多数据格式支持（.xrdml, .raw）",
            "6.2 添加键盘快捷键",
            "6.3 实现撤销/重做",
            "6.4 深色/浅色主题切换",
            "6.5 性能优化（大数据处理）",
            "6.6 PyInstaller 打包测试",
        ],
        "验收标准": [
            "所有支持格式均可正确加载",
            "UI 响应流畅（大数据加载无卡顿）",
            "打包后的 exe 可独立运行",
        ],
    },
}


# ============================================================================
# 第七部分：可复用的开源库映射
# ============================================================================

REUSABLE_LIBRARIES = {
    "数据加载": {
        "powerxrd": "https://github.com/andrewrgarcia/powerxrd (背景扣除、峰检测)",
        "cryspy": "https://github.com/Tomoki-YAMASHITA/CrySPY (XRD数据处理参考)",
    },
    "结构模拟": {
        "pymatgen": "https://github.com/materialsproject/pymatgen (XRDCalculator)",
    },
    "峰拟合": {
        "lmfit": "https://github.com/lmfit/lmfit-py (非线性最小二乘)",
        "scipy.optimize": "scipy 内置 (curve_fit)",
    },
    "物相识别": {
        "pymatgen": "XRD模式比较",
        "autoXRD": "https://github.com/njszym/XRD-AutoAnalyzer (深度学习辅助)",
        "XMatcher": "https://arxiv.org/abs/2607.17162 (搜索匹配框架)",
    },
    "Rietveld精修": {
        "GSAS-II": "https://github.com/AdvancedPhotonSource/GSAS-II (金标准)",
        "powerxrd": "MVR最小Rietveld实现",
        "Spotlight": "https://github.com/lanl/spotlight (自动化优化)",
    },
    "晶体结构": {
        "pymatgen": "Structure, Lattice, CIF解析",
        "PyXRD": "https://github.com/qzhu2017/PyXtal (晶体结构生成)",
    },
    "文件格式": {
        "XRD-FileConventor": "https://github.com/ANDYPENG09/XRD-FileConventor (格式转换参考)",
    },
    "绘图": {
        "matplotlib": "标准绘图库",
        "pyqtgraph": "Qt高性能交互式绘图",
    },
}


# ============================================================================
# 附录A：关键接口详细签名
# ============================================================================

INTERFACE_SPECS = {
    "DataLoader.load": {
        "signature": "def load(self, file_path: str, **kwargs) -> XRDData",
        "args": {
            "file_path": "str - 数据文件绝对路径",
            "skip_rows": "int - 跳过头行数 (默认0)",
            "delimiter": "str - 分隔符 (默认None=空白)",
            "two_theta_col": "int - 2θ列索引 (默认0)",
            "intensity_col": "int - 强度列索引 (默认1)",
            "wavelength": "float - X射线波长 (默认1.5406)",
            "auto_detect": "bool - 自动检测格式 (默认True)",
        },
        "returns": "XRDData - 包含2θ数组、强度数组和元数据",
        "raises": [
            "FileNotFoundError",
            "ValueError - 当数据列不足时",
            "NotImplementedError - 格式不支持",
        ],
        "example": '''
loader = DataLoader()
data = loader.load("sample.xy")
print(f"Loaded {len(data.two_theta)} data points")
print(f"2θ range: {data.two_theta[0]:.2f} - {data.two_theta[-1]:.2f}")
''',
    },

    "DataProcessor.subtract_background": {
        "signature": "def subtract_background(self, data: XRDData, method: str = 'snip', **kwargs) -> XRDData",
        "args": {
            "method": "'snip' | 'als' | 'polyfit' | 'median'",
            "snip_kwargs": {"niter": "int (默认40)", "degree": "int (默认2)"},
            "als_kwargs": {"lam": "float (默认1e6)", "p": "float (默认0.01)", "maxiter": "int (默认50)"},
            "polyfit_kwargs": {"degree": "int (默认3)"},
            "median_kwargs": {"window": "int (默认50)"},
        },
        "returns": "XRDData - 背景扣除后的新XRDData实例",
        "example": '''
processor = DataProcessor()
bg_removed = processor.subtract_background(data, method='snip', niter=40)
''',
    },

    "PeakFinder.find_peaks": {
        "signature": "def find_peaks(self, data: XRDData, height: float = 0.1, distance: int = 5, prominence: float = 0.05) -> List[Peak]",
        "args": {
            "data": "XRDData - 输入数据",
            "height": "float - 最小峰高（相对最大强度的比例）",
            "distance": "int - 峰间最小数据点数",
            "prominence": "float - 峰突出度",
        },
        "returns": "List[Peak] - 检测到的峰列表（按2θ排序）",
        "example": '''
finder = PeakFinder()
peaks = finder.find_peaks(bg_removed, height=0.1, distance=5)
for p in peaks:
    print(f"2θ={p.two_theta:.3f}, d={p.d_spacing:.3f}Å, I={p.intensity:.1f}")
''',
    },

    "PeakFitter.fit_multiple_peaks": {
        "signature": "def fit_multiple_peaks(self, data: XRDData, peaks: List[Peak], model: str = 'voigt', **kwargs) -> FitResult",
        "args": {
            "data": "XRDData - 输入数据",
            "peaks": "List[Peak] - 待拟合的峰列表",
            "model": "'gaussian' | 'lorentzian' | 'voigt' | 'pseudo_voigt'",
            "bounds": "dict - 参数边界约束",
        },
        "returns": "FitResult 包含 fitted_peaks, r_squared, residuals",
        "example": '''
fitter = PeakFitter()
result = fitter.fit_multiple_peaks(bg_removed, peaks, model='voigt')
print(f"R² = {result.r_squared:.4f}")
for p in result.fitted_peaks:
    print(f"2θ={p.two_theta:.4f}, FWHM={p.fwhm:.4f}")
''',
    },

    "PhaseIdentifier.identify": {
        "signature": "def identify(self, data: XRDData, elements: List[str] = None, top_n: int = 5, **kwargs) -> List[Phase]",
        "args": {
            "data": "XRDData - 输入数据",
            "elements": "List[str] - 已知元素列表 (如 ['Si', 'O'])",
            "top_n": "int - 返回候选数量",
            "strategy": "'peak_match' | 'full_pattern' | 'hybrid'",
        },
        "returns": "List[Phase] - 候选物相列表（按匹配度排序）",
        "example": '''
identifier = PhaseIdentifier(cif_db_path="./cif_database")
candidates = identifier.identify(data, elements=['Si', 'O'], top_n=5)
for phase in candidates:
    print(f"{phase.name}: 匹配度={phase.match_score:.1f}%")
''',
    },

    "RietveldRefiner.refine": {
        "signature": "def refine(self, data: XRDData, phases: List[Phase], **kwargs) -> RefinementResult",
        "args": {
            "data": "XRDData - 实验数据",
            "phases": "List[Phase] - 待精修物相列表",
            "strategy": "'sequential' | 'auto' | 'manual'",
            "refine_params": "dict - 要精修的参数组",
            "max_cycles": "int - 最大精修循环次数 (默认20)",
            "progress_callback": "callable - 进度回调函数",
        },
        "returns": "RefinementResult - 精修结果",
        "raises": [
            "RuntimeError - GSAS-II 未安装",
            "ConvergenceError - 精修不收敛",
        ],
        "example": '''
refiner = RietveldRefiner(engine='gsas2')
result = refiner.refine(data, selected_phases, strategy='sequential')
print(f"Rwp = {result.wR:.2f}%")
print(f"GOF = {result.GOF:.3f}")
''',
    },
}


# ============================================================================
# 附录B：验证数据集规格
# ============================================================================

VALIDATION_DATASETS = {
    "si_powder": {
        "description": "硅粉标准样品 (NIST SRM 640e)",
        "file_format": ".xy",
        "two_theta_range": "10-90°",
        "wavelength": "1.5406 Å (Cu Kα)",
        "expected_peaks": [
            {"hkl": "111", "2θ": 28.443, "d": 3.135},
            {"hkl": "220", "2θ": 47.306, "d": 1.920},
            {"hkl": "311", "2θ": 56.124, "d": 1.637},
            {"hkl": "400", "2θ": 69.137, "d": 1.357},
            {"hkl": "331", "2θ": 76.395, "d": 1.246},
            {"hkl": "422", "2θ": 88.045, "d": 1.082},
        ],
        "lattice_param": {"a": 5.431},
    },
    "al2o3": {
        "description": "氧化铝 (刚玉)",
        "file_format": ".xy",
        "two_theta_range": "10-90°",
        "expected_peaks": [
            {"hkl": "012", "2θ": 25.58},
            {"hkl": "104", "2θ": 35.16},
            {"hkl": "110", "2θ": 37.78},
            {"hkl": "113", "2θ": 43.36},
            {"hkl": "024", "2θ": 52.56},
            {"hkl": "116", "2θ": 57.52},
            {"hkl": "124", "2θ": 66.52},
            {"hkl": "220", "2θ": 68.20},
        ],
    },
    "alpha_fe": {
        "description": "α-铁 (体心立方)",
        "file_format": ".xy",
        "two_theta_range": "40-100°",
        "expected_peaks": [
            {"hkl": "110", "2θ": 44.68},
            {"hkl": "200", "2θ": 64.98},
            {"hkl": "211", "2θ": 82.38},
        ],
        "lattice_param": {"a": 2.866},
    },
}


# ============================================================================
# 附录C：代码规范
# ============================================================================

CODE_STANDARDS = {
    "Python版本": "3.11+",
    "代码风格": "PEP 8 (black格式化, 88字符行宽)",
    "类型注解": "必须（mypy strict检查）",
    "命名规范": {
        "文件/模块": "snake_case",
        "类名": "PascalCase",
        "函数/方法": "snake_case",
        "常量": "UPPER_SNAKE_CASE",
        "Qt方法": "CamelCase (Qt约定)",
        "私有方法": "_leading_underscore",
    },
    "文档": {
        "模块文档": "每个模块必须有docstring",
        "公共函数": "必须有完整docstring（参数、返回值、异常、示例）",
        "复杂算法": "必须有算法说明和参考文献",
    },
    "测试": {
        "框架": "pytest + pytest-qt (PySide6测试)",
        "fixture": "conftest.py 中定义共享fixture",
        "数据": "测试数据存放在 tests/data/",
    },
    "提交规范": "Conventional Commits",
}

# ============================================================================
# 附录D：安全与合规
# ============================================================================

SECURITY_NOTES = {
    "数据安全": "不收集用户数据，所有计算在本地完成",
    "开源许可": "GSAS-II 需注意其许可协议（非商业免费）",
    "第三方依赖": "所有依赖应为开源许可兼容",
}
