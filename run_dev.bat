@echo off
REM ===================================================================
REM  PolyXRD 源码启动 (人工验收用, 非打包版)
REM  直接跑仓库里的 src/, 永远是当前代码, 无需等 PyInstaller 构建。
REM  用法: 双击本文件, 或在终端执行 run_dev.bat
REM ===================================================================
setlocal
cd /d "%~dp0"

set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [错误] 找不到虚拟环境: %PY%
    echo        请先重建 venv (见 README / handover 文档)
    pause
    exit /b 1
)

REM 让 polyxrd 包可被导入 (editable 安装时其实已生效, 这里双保险)
set "PYTHONPATH=%~dp0src"

echo [PolyXRD] 源码模式启动...
echo [PolyXRD] 解释器: %PY%
"%PY%" -m polyxrd.main
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [PolyXRD] 退出码 %RC% - 若为崩溃, 上方回溯即原因
    pause
)
endlocal
exit /b %RC%
