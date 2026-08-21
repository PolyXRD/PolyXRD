@echo off
chcp 65001 >nul
title PolyXRD 测试运行器
echo ========================================
echo   PolyXRD 单元测试
echo ========================================
echo.

cd /d "%~dp0"

REM 检查虚拟环境
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
    set PIP=venv\Scripts\pip.exe
) else (
    set PYTHON=python
    set PIP=pip
)

REM 确保pytest已安装
"%PYTHON%" -c "import pytest" >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 安装pytest...
    "%PIP%" install pytest>=7.0 pytest-cov>=4.0
)

echo.
echo [信息] 运行单元测试...
echo.

"%PYTHON%" -m pytest tests/ -v --tb=short

echo.
if %errorlevel% equ 0 (
    echo [完成] 所有测试通过！
) else (
    echo [警告] 部分测试失败，请查看上方输出
)

echo.
pause
