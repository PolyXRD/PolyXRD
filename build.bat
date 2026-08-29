@echo off
chcp 65001 >nul
title PolyXRD v0.9.0 打包构建器
echo ========================================
echo   PolyXRD v0.9.0 打包为独立安装包
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

echo [信息] 使用 Python: %PYTHON%

"%PYTHON%" -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 安装 PyInstaller...
    "%PIP%" install pyinstaller>=6.0
)

echo.
echo [步骤 1/4] PyInstaller 打包独立可执行文件 (不含 COD 全库/无机物库)...
echo.

REM 主程序默认不打包两个独立数据库 (数据库单独以附件分发)
set POLYXRD_NO_COD_DB=1
set POLYXRD_NO_INORG_DB=1
"%PYTHON%" -m PyInstaller PolyXRD.spec --noconfirm --clean

if %errorlevel% neq 0 (
    echo.
    echo [错误] PyInstaller 打包失败！
    pause
    exit /b 1
)

echo.
echo [步骤 2/4] 创建 Inno Setup 安装程序或 7z 自解压...
echo.

if not exist "installer_output" mkdir installer_output

REM 优先 Inno Setup (更专业, 支持卸载/快捷方式/版本信息)
where iscc >nul 2>&1
set USE_ISSCC=%errorlevel%
if "%USE_ISSCC%"=="0" (
    echo [信息] 使用 Inno Setup 编译安装程序
    iscc /DAppVersion=0.9.0 /O"installer_output" /F"PolyXRD-Setup-v0.9.0" scripts\PolyXRD-Setup.iss
) else (
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=0.9.0 /O"installer_output" /F"PolyXRD-Setup-v0.9.0" scripts\PolyXRD-Setup.iss
    ) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
        "C:\Program Files\Inno Setup 6\ISCC.exe" /DAppVersion=0.9.0 /O"installer_output" /F"PolyXRD-Setup-v0.9.0" scripts\PolyXRD-Setup.iss
    ) else (
        REM 回退：7z SFX
        where 7z >nul 2>&1
        if %errorlevel% equ 0 (
            7z a -t7z -mx=9 -sfx installer_output\PolyXRD-Setup-v0.9.0.exe "dist\PolyXRD\*" -y
        ) else if exist "C:\Program Files\7-Zip\7z.exe" (
            "C:\Program Files\7-Zip\7z.exe" a -t7z -mx=9 -sfx installer_output\PolyXRD-Setup-v0.9.0.exe "dist\PolyXRD\*" -y
        ) else (
            echo [警告] 未找到 Inno Setup 或 7z，跳过安装程序
        )
    )
)

echo.
echo [步骤 3/4] 创建便携压缩包 (ZIP)...
echo.

powershell -Command "Compress-Archive -Path 'dist\PolyXRD\*' -DestinationPath 'installer_output\PolyXRD-v0.9.0-Portable.zip' -Force"

if %errorlevel% neq 0 (
    echo [警告] ZIP压缩失败，尝试备用方法...
    powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::CreateFromDirectory('dist\PolyXRD', 'installer_output\PolyXRD-v0.9.0-Portable.zip')"
)

echo.
echo [步骤 4/4] 创建版本信息文件...
echo.

powershell -Command "$ver = @'
PolyXRD v0.9.0 Release
Build Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Databases (独立分发, 未内置):
  - COD 无机物库: PolyXRD_COD_Inorganics_v0.9.0.zip (71,199 物相)
  - COD 全库:     PolyXRD_COD_Full_v0.9.0.zip       (113,223 条目)
Features:
  - 双 COD 数据库按需挂载
  - FOM 传统 Search/Match + 多物相组合策略
  - 纯金属抑制 + auto-exclude 元素过滤
  - Rietveld (builtin/GSAS-II/powerxrd) - wR 优化: bg_method=median + Caglioti UVW
  - 全谱拟合、峰形拟合、Le Bail 框架
  - 中/英/日三语言界面，PySide6 + PyQtGraph 双画布
  - 项目保存 (.polyxrd) + PDF/CSV/PNG/SVG 报告
Contact: sshztx@outlook.com
'@; $ver | Out-File -FilePath 'dist\PolyXRD\VERSION.txt' -Encoding UTF8; Copy-Item 'dist\PolyXRD\VERSION.txt' 'installer_output\VERSION_v0.9.0.txt' -ErrorAction SilentlyContinue"

echo.
echo ========================================
echo   PolyXRD v0.9.0 打包完成！
echo ========================================
echo.
echo 输出文件 (installer_output\):
echo   独立安装程序:   installer_output\PolyXRD-Setup-v0.9.0.exe
echo   便携压缩包:     installer_output\PolyXRD-v0.9.0-Portable.zip
echo.

if exist "dist\PolyXRD\PolyXRD.exe" (
    for %%A in ("dist\PolyXRD\PolyXRD.exe") do echo   PolyXRD.exe:         %%~zA 字节
)
if exist "installer_output\PolyXRD-Setup-v0.9.0.exe" (
    for %%A in ("installer_output\PolyXRD-Setup-v0.9.0.exe") do echo   Setup.exe:           %%~zA 字节
)
if exist "installer_output\PolyXRD-v0.9.0-Portable.zip" (
    for %%A in ("installer_output\PolyXRD-v0.9.0-Portable.zip") do echo   Portable.zip:        %%~zA 字节
)

echo.
pause