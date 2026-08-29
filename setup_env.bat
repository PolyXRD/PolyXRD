@echo off
chcp 65001 >nul
title PolyXRD Environment Setup
echo ========================================
echo   PolyXRD - Environment Setup
echo ========================================
echo.

cd /d "%~dp0"

REM Use PowerShell 7 if available, otherwise Windows PowerShell
set PWSH="C:\Program Files\PowerShell\7\pwsh.exe"
if exist %PWSH% (
    echo [Info] Using PowerShell 7
    %PWSH% -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1"
) else (
    echo [Info] Using Windows PowerShell
    powershell -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1"
)

echo.
pause
