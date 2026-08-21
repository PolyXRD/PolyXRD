@echo off
chcp 65001 >nul
echo ========================================
echo   PolyXRD 环境设置脚本
echo ========================================
echo.

REM 检查Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到Python。请先安装Python 3.11+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [信息] 检测到Python版本:
python --version
echo.

REM 创建虚拟环境
if not exist "venv" (
    echo [信息] 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 升级pip
python -m pip install --upgrade pip

REM 安装依赖
echo [信息] 安装项目依赖...
pip install -e .
pip install pytest pytest-cov

echo.
echo ========================================
echo   环境设置完成！
echo   运行: venv\Scripts\python -m polyxrd.main
echo ========================================
pause