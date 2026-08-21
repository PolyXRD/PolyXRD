@echo off
chcp 65001 >nul
title PolyXRD 一键安装脚本
echo ========================================
echo   PolyXRD 一键环境设置
echo ========================================
echo.

cd /d "%~dp0"

REM 检查 Python
set PYTHON_EXE=c:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到 Python，尝试使用系统 Python...
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 未检测到任何 Python 安装
        echo 请先安装 Python 3.11+: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set PYTHON_EXE=python
)

echo [信息] 使用 Python:
"%PYTHON_EXE%" --version
echo.

REM 创建虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [信息] 创建虚拟环境...
    "%PYTHON_EXE%" -m venv venv
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
) else (
    echo [信息] 虚拟环境已存在
)

REM 激活虚拟环境
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [错误] 虚拟环境激活失败
    pause
    exit /b 1
)

echo.
echo [信息] 升级 pip...
python -m pip install --upgrade pip
echo.

echo [信息] 安装核心依赖...
pip install numpy>=1.24 scipy>=1.10 matplotlib>=3.7 pandas>=2.0.0 Pillow>=9.0.0 platformdirs>=3.0.0
if %errorlevel% neq 0 (
    echo [警告] 部分核心依赖安装失败
)

echo.
echo [信息] 安装 PySide6 (GUI)...
pip install PySide6>=6.5
if %errorlevel% neq 0 (
    echo [警告] PySide6 安装失败，请手动安装
)

echo.
echo [信息] 安装科学计算依赖...
pip install pymatgen>=2024.1.1
pip install lmfit>=1.3
pip install powerxrd>=1.0

echo.
echo [信息] 安装可选依赖...
pip install pyqtgraph>=0.13.0
pip install GSAS-II>=5.0
if %errorlevel% neq 0 (
    echo [警告] GSAS-II 安装失败（可选，将使用内置引擎）
)

echo.
echo [信息] 安装 PolyXRD (开发模式)...
pip install -e .
if %errorlevel% neq 0 (
    echo [错误] PolyXRD 安装失败
    pause
    exit /b 1
)

echo.
echo [信息] 安装测试依赖...
pip install pytest>=7.0 pytest-cov>=4.0

echo.
echo ========================================
echo   验证安装
echo ========================================
echo.

python -c "import numpy; print(f'  numpy: {numpy.__version__}')" 2>nul || echo "  numpy: 未安装"
python -c "import scipy; print(f'  scipy: {scipy.__version__}')" 2>nul || echo "  scipy: 未安装"
python -c "import matplotlib; print(f'  matplotlib: {matplotlib.__version__}')" 2>nul || echo "  matplotlib: 未安装"
python -c "import PySide6; print(f'  PySide6: {PySide6.__version__}')" 2>nul || echo "  PySide6: 未安装"
python -c "import pandas; print(f'  pandas: {pandas.__version__}')" 2>nul || echo "  pandas: 未安装"
python -c "import pymatgen; print(f'  pymatgen: {pymatgen.__version__}')" 2>nul || echo "  pymatgen: 未安装 (可选)"
python -c "import lmfit; print(f'  lmfit: {lmfit.__version__}')" 2>nul || echo "  lmfit: 未安装 (可选)"
python -c "import polyxrd; print(f'  polyxrd: OK')" 2>nul || echo "  polyxrd: 错误"

echo.
echo ========================================
echo   环境设置完成！
echo.
echo   运行应用:
echo     venv\Scripts\python -m polyxrd.main
echo.
echo   运行测试:
echo     venv\Scripts\python -m pytest tests/ -v
echo ========================================
echo.
pause
