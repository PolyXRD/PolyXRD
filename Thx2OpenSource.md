# PolyXRD 依赖清单

## 核心晶体学库

| 包名 | GitHub 仓库 | 用途 | 版本要求 |
|---|---|---|---|
| **pymatgen** | https://github.com/materialsproject/pymatgen | CIF 解析、晶体结构分析、XRD 峰模拟 | ≥2024.1.1 |
| **spglib** | https://github.com/spglib/spglib | 空间群识别、对称性分析 | ≥2.0 |
| **powerxrd** | https://github.com/andrewrgarcia/powerxrd | 轻量级 Rietveld 精修引擎 | ≥1.0 |
| **GSAS-II** | https://github.com/AdvancedPhotonSource/GSAS-II | 专业 Rietveld 精修引擎（懒加载，未安装时回退内置引擎） | — |
| **COD** | http://www.crystallography.net/cod/ | 开放晶体学数据库，113K 条 CIF 结构已索引到本地（CC0 开放数据） | — |

## 科学计算

| 包名 | GitHub 仓库 | 用途 | 版本要求 |
|---|---|---|---|
| **numpy** | https://github.com/numpy/numpy | 数组运算、数学函数 | ≥1.24 |
| **scipy** | https://github.com/scipy/scipy | 插值、优化、信号处理 | ≥1.10 |
| **pandas** | https://github.com/pandas-dev/pandas | 数据表操作、CSV/Excel 导入导出 | ≥2.0.0 |

## 数据拟合

| 包名 | GitHub 仓库 | 用途 | 版本要求 |
|---|---|---|---|
| **lmfit** | https://github.com/lmfit/lmfit-py | 非线性最小二乘拟合（峰形精修） | ≥1.3 |

## GUI / 可视化

| 包名 | GitHub 仓库 | 用途 | 版本要求 |
|---|---|---|---|
| **PySide6** | https://code.qt.io/cgit/pyside/pyside-setup.git/ | Qt6 GUI 框架（LGPL 开源） | ≥6.5 |
| **matplotlib** | https://github.com/matplotlib/matplotlib | 2D 绘图（XRD 谱图） | ≥3.7 |
| **pyqtgraph** | https://github.com/pyqtgraph/pyqtgraph | 高性能实时绘图 | ≥0.13.0 |
| **plotly** | https://github.com/plotly/plotly.py | 交互式 3D 图表 | ≥5.0 |
| **Pillow** | https://github.com/python-pillow/Pillow | 图像处理 | ≥9.0.0 |

## 工具类

| 包名 | GitHub 仓库 | 用途 | 版本要求 |
|---|---|---|---|
| **platformdirs** | https://github.com/tox-dev/platformdirs | 跨平台用户目录定位 | ≥3.0.0 |

## 构建 / 开发工具

| 包名 | GitHub 仓库 | 用途 | 版本要求 |
|---|---|---|---|
| **pytest** | https://github.com/pytest-dev/pytest | 单元测试框架 | ≥7.0 |
| **pytest-cov** | https://github.com/pytest-dev/pytest-cov | 测试覆盖率 | ≥4.0 |
| **pyinstaller** | https://github.com/pyinstaller/pyinstaller | Python → Windows exe 打包 | ≥6.0 |
| **setuptools** | https://github.com/pypa/setuptools | 构建后端 | ≥64 |
| **InnoSetup** | https://github.com/jrsoftware/issrc | Windows 安装程序制作工具 | — |
