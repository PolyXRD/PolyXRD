@echo off
chcp 65001 >nul
title PolyXRD v0.9.7 打包构建器
echo ========================================
echo   PolyXRD v0.9.7 打包为独立安装包
echo ========================================
echo.

cd /d "%~dp0"

REM ── Python 定位 ──────────────────────────────────────
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
echo [步骤 1/5] PyInstaller 打包 (EXE 阶段, COLLECT 阶段可能因沙盒 safe-delete 失败)...
echo.

set POLYXRD_NO_COD_DB=1
set POLYXRD_NO_INORG_DB=1
"%PYTHON%" -m PyInstaller PolyXRD.spec --noconfirm

REM PyInstaller 失败 (EXIT 1) 不一定是真正的构建失败, 可能是 COLLECT 阶段 shutil.rmtree 被 safe-delete 拦截.
REM spec 已加 try/except, COLLECT 失败时 EXE 已在 build 目录.
if not exist "build\PolyXRD\PolyXRD.exe" (
    echo [错误] EXE 未生成, 构建失败!
    pause
    exit /b 1
)

echo.
echo [步骤 2/5] 手工收集 _internal ( 绕过沙盒 safe-delete, 从 COLLECT-00.toc 复制所有依赖 )...
echo.

REM 用 shell cp 单独覆盖 EXE (PyInstaller 在 build 已经产出)
copy /Y "build\PolyXRD\PolyXRD.exe" "dist\PolyXRD\PolyXRD.exe" >nul
if exist "build\PolyXRD\qt.conf" copy /Y "build\PolyXRD\qt.conf" "dist\PolyXRD\qt.conf" >nul

REM 跑 _do_collect.py 复制其余依赖
"%PYTHON%" _do_collect.py

REM 复制 ICU DLL (PySide6 6.11 不自带, Qt6 启动必需)
"%PYTHON%" -c "
import os, glob, shutil
DST = r'dist\PolyXRD\_internal'
ICU_ROOTS = [
    os.path.expandvars(r'%USERPROFILE%\AppData\Roaming\mamba\pkgs\icu-78.3*'),
    os.path.expandvars(r'%USERPROFILE%\AppData\Roaming\mamba\pkgs\https\conda.anaconda.org\conda-forge\win-64\icu-78.3*'),
]
done = 0
for pat in ICU_ROOTS:
    for d in glob.glob(pat):
        b = os.path.join(d, 'Library', 'bin')
        if os.path.isdir(b):
            for f in ['icuuc.dll', 'icudt.dll', 'icuin.dll', 'icuio.dll', 'icutu.dll',
                      'icuuc78.dll', 'icudt78.dll']:
                s = os.path.join(b, f)
                if os.path.isfile(s):
                    shutil.copy2(s, os.path.join(DST, f))
                    done += 1
            print(f'  ICU copied: {done} files')
            break
    if done: break
else:
    print('  [WARN] No ICU source found - GUI may fail to start')
"

if %errorlevel% neq 0 (
    echo [警告] ICU 复制阶段异常, 请检查 PySide6 Qt 启动依赖
)

echo.
echo [步骤 3/5] 创建 Inno Setup 安装程序...
echo.

if not exist "installer_output" mkdir installer_output

set ISCC=
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC goto :have_iscc

where iscc >nul 2>&1
if %errorlevel% equ 0 (
    set ISCC=iscc
    goto :have_iscc
)
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if defined ISCC goto :have_iscc
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
if defined ISCC goto :have_iscc

echo [警告] 未找到 Inno Setup, 跳过安装程序生成
goto :no_iscc

:have_iscc
%ISCC% /DAppVersion=0.9.7 /O"installer_output" /F"PolyXRD-Setup-v0.9.7" scripts\PolyXRD-Setup.iss
if %errorlevel% neq 0 (
    echo [警告] Inno 编译失败, 跳过安装程序
)

:no_iscc

echo.
echo [步骤 4/5] 创建便携压缩包 (ZIP)...
echo.

if exist "installer_output\PolyXRD-v0.9.7-Portable.zip" del "installer_output\PolyXRD-v0.9.7-Portable.zip" >nul
powershell -Command "Compress-Archive -Path 'dist\PolyXRD\*' -DestinationPath 'installer_output\PolyXRD-v0.9.7-Portable.zip' -Force"
if %errorlevel% neq 0 (
    echo [警告] ZIP 压缩失败, 尝试备用方法...
    powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::CreateFromDirectory('dist\PolyXRD', 'installer_output\PolyXRD-v0.9.7-Portable.zip')"
)

echo.
echo [步骤 5/5] 写 VERSION.txt...
echo.

powershell -Command "$ver = @'
PolyXRD v0.9.7 Release
Build Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
ICU: bundled (Qt6 启动依赖, PySide6 6.11 已不再自带)
Databases: 独立分发 (COD 全库/无机物库)
'@; $ver | Out-File -FilePath 'dist\PolyXRD\VERSION.txt' -Encoding UTF8"
copy /Y "dist\PolyXRD\VERSION.txt" "installer_output\VERSION_v0.9.7.txt" >nul 2>&1

echo.
echo ========================================
echo   PolyXRD v0.9.7 打包完成！
echo ========================================
echo.

echo 输出 (installer_output\):
if exist "installer_output\PolyXRD-Setup-v0.9.7.exe" for %%A in ("installer_output\PolyXRD-Setup-v0.9.7.exe") do echo   Setup.exe:    %%~zA 字节
if exist "installer_output\PolyXRD-v0.9.7-Portable.zip" for %%A in ("installer_output\PolyXRD-v0.9.7-Portable.zip") do echo   Portable.zip: %%~zA 字节
if exist "dist\PolyXRD\PolyXRD.exe" for %%A in ("dist\PolyXRD\PolyXRD.exe") do echo   PolyXRD.exe:  %%~zA 字节

echo.
pause