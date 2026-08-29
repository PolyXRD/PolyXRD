@echo off
chcp 65001 >nul
title PolyXRD Launcher
echo ========================================
echo   PolyXRD - XRD Analysis Software
echo ========================================
echo.

cd /d "%~dp0"

REM Use venv Python
set PYTHON=venv\Scripts\python.exe
if not exist "%PYTHON%" (
    echo [Error] venv not found. Please run setup_env.bat first.
    pause
    exit /b 1
)

echo [Info] Installing missing packages (if any)...
"%PYTHON%" "%~dp0start_polyxrd.py"

if %errorlevel% neq 0 (
    echo.
    echo [Error] Application exited with code %errorlevel%
    pause
)
