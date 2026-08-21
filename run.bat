@echo off
chcp 65001 >nul
title PolyXRD 启动器
echo ========================================
echo   PolyXRD - X射线衍射分析软件
echo ========================================
echo.

cd /d "%~dp0"

REM 检查虚拟环境
if exist "venv\Scripts\python.exe" (
    echo [信息] 使用虚拟环境
    set PYTHON=venv\Scripts\python.exe
) else (
    echo [警告] 虚拟环境不存在，使用系统Python
    set PYTHON=python
)

REM 检查Python
"%PYTHON%" --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到Python！
    echo 请先运行 install.bat 或手动安装Python 3.11+
    pause
    exit /b 1
)

echo.
echo [信息] 启动 PolyXRD...
echo.

"%PYTHON%" -m polyxrd.main

if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出 (错误码: %errorlevel%)
    echo 请检查日志或运行测试
    pause
)
