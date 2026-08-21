@echo off
REM =============================================================
REM  PolyXRD - COD 无机物数据库外挂包 V0.8.21
REM  一键安装脚本: 将 COD_inorganics.sqlite 复制到用户数据目录
REM  并在 PolyXRD 配置中注册该路径
REM =============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
title PolyXRD COD 数据库导入向导 V0.8.21

echo.
echo =============================================================
echo   PolyXRD - COD 无机物数据库外挂包 V0.8.21 导入向导
echo =============================================================
echo.

REM --- 1. Find COD_inorganics.sqlite next to this bat ---
set "SCRIPT_DIR=%~dp0"
set "DB_SRC=%SCRIPT_DIR%COD_inorganics.sqlite"
if not exist "%DB_SRC%" (
    echo [ERROR] 找不到 COD_inorganics.sqlite, 请确认本脚本与数据库文件在同一目录
    echo.
    pause
    exit /b 1
)
for %%I in ("%DB_SRC%") do set DB_SIZE_MB=%%~zI
set /a DB_SIZE_MB=%DB_SIZE_MB:~0,-6%
echo [OK] 找到数据库文件: COD_inorganics.sqlite (%DB_SIZE_MB% MB)

REM --- 2. Determine target install directory ---
set "TARGET_DIR=%LOCALAPPDATA%\PolyXRD\databases"
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%" 2>nul
set "DB_DST=%TARGET_DIR%\COD_inorganics.sqlite"

echo.
echo [信息] 目标安装目录: %TARGET_DIR%
set /p CONFIRM="确认安装? [Y/n] (默认Y): "
if /i not "%CONFIRM%"=="" if /i not "%CONFIRM%"=="Y" (
    echo 用户取消.
    exit /b 0
)

REM --- 3. Copy ---
echo.
echo [1/2] 复制数据库文件到用户目录...
copy /Y /B "%DB_SRC%" "%DB_DST%" >nul
if errorlevel 1 (
    echo [ERROR] 复制失败,请检查磁盘空间或权限.
    pause
    exit /b 1
)
echo       完成.

REM --- 4. Update PolyXRD config in HKCU ---
echo [2/2] 注册数据库路径到 PolyXRD 配置...
reg add "HKCU\Software\PolyXRD" /v "cod_db_path" /t REG_SZ /d "%DB_DST%" /f >nul 2>&1
echo       完成.

echo.
echo =============================================================
echo   导入成功! 您现在可以:
echo     1. 启动 PolyXRD
echo     2. 菜单: 文件 -^> 导入外部数据库 -^> COD 无机物库
echo        或直接使用 "物相检索" 功能, 程序会自动加载.
echo =============================================================
echo.
pause
endlocal
exit /b 0
