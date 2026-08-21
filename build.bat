@echo off
chcp 65001 >nul
title PolyXRD v0.4.1 打包构建器
echo ========================================
echo   PolyXRD v0.4.1 打包为独立安装包
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
echo [步骤 1/4] PyInstaller 打包独立可执行文件...
echo.

REM 使用spec文件打包 (已包含所有配置)
"%PYTHON%" -m PyInstaller PolyXRD.spec --noconfirm --clean

if %errorlevel% neq 0 (
    echo.
    echo [错误] PyInstaller 打包失败！
    pause
    exit /b 1
)

echo.
echo [步骤 2/4] 创建自解压安装程序 (7z SFX)...
echo.

if not exist "installer_output" mkdir installer_output

where 7z >nul 2>&1
if %errorlevel% equ 0 (
    7z a -t7z -mx=9 -sfx installer_output\PolyXRD_Setup_0.4.1.exe "dist\PolyXRD\*" -y
) else (
    if exist "C:\Program Files\7-Zip\7z.exe" (
        "C:\Program Files\7-Zip\7z.exe" a -t7z -mx=9 -sfx installer_output\PolyXRD_Setup_0.4.1.exe "dist\PolyXRD\*" -y
    ) else (
        echo [警告] 7z 未找到，跳过自解压安装程序创建
    )
)

echo.
echo [步骤 3/4] 创建便携压缩包 (ZIP)...
echo.

powershell -Command "Compress-Archive -Path 'dist\PolyXRD\*' -DestinationPath 'PolyXRD_0.4.1_Portable.zip' -Force"

if %errorlevel% neq 0 (
    echo [警告] ZIP压缩失败，尝试备用方法...
    powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::CreateFromDirectory('dist\PolyXRD', 'PolyXRD_0.4.1_Portable.zip')"
)

echo.
echo [步骤 4/4] 创建版本信息文件...
echo.

powershell -Command "
\$ver = @'
PolyXRD v0.4.1 Release
Build Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Database: 95 XRD reference phases (Cu Ka 1.5406 A)
Features:
  - Offline XRD reference database
  - FOM-based phase identification
  - Theoretical XRD pattern simulation
  - Project save/load (.pxrd format)
  - Rietveld structure refinement
  - Updated About dialog with contact info
'@
\$ver | Out-File -FilePath 'dist\PolyXRD\VERSION.txt' -Encoding UTF8
Copy-Item 'dist\PolyXRD\VERSION.txt' 'installer_output\VERSION_0.4.1.txt' -ErrorAction SilentlyContinue
"

echo.
echo ========================================
echo   PolyXRD v0.4.1 打包完成！
echo ========================================
echo.
echo 输出文件:
echo   独立可执行文件:  dist\PolyXRD\PolyXRD.exe
echo   自解压安装程序:  installer_output\PolyXRD_Setup_0.4.1.exe
echo   便携压缩包:     PolyXRD_0.4.1_Portable.zip
echo.

if exist "dist\PolyXRD\PolyXRD.exe" (
    for %%A in ("dist\PolyXRD\PolyXRD.exe") do echo   PolyXRD.exe: %%~zA 字节
)
if exist "installer_output\PolyXRD_Setup_0.4.1.exe" (
    for %%A in ("installer_output\PolyXRD_Setup_0.4.1.exe") do echo   Setup.exe:  %%~zA 字节
)
if exist "PolyXRD_0.4.1_Portable.zip" (
    for %%A in ("PolyXRD_0.4.1_Portable.zip") do echo   Portable.zip: %%~zA 字节
)

echo.
pause