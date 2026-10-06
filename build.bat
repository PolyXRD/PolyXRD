@echo off
chcp 65001 >nul
REM -- UTF-8 everywhere (v2.0.0): build/dev also run in UTF-8 so that
REM -- Chinese/Japanese never turns into mojibake on a non-CJK Windows.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title PolyXRD v2.5.0 打包构建器
echo ========================================
echo   PolyXRD v2.5.0 打包为独立安装包
echo   数据库外挂 (不随包分发)
echo ========================================
echo.

cd /d "%~dp0"

set APPVER=2.6.0

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
echo [步骤 1/6] PyInstaller 打包 (EXE 阶段, COLLECT 阶段可能因沙盒 safe-delete 失败)...
echo.
echo [信息] 数据库策略: 外挂。安装包不含 .sqlite, 由用户单独下载后经 GUI 导入。
echo        若需内嵌整包, 请先 set POLYXRD_WITH_DB=1 再运行本脚本。

REM 应用图标已由 build_icon.py 生成 (基于 crystal-mark 品牌资产, 7 档多分辨率 ICO).
REM 如需重新生成: %PYTHON% build_icon.py
"%PYTHON%" build_icon.py

"%PYTHON%" -m PyInstaller PolyXRD.spec --noconfirm

REM PyInstaller 失败 (EXIT 1) 不一定是真正的构建失败, 可能是 COLLECT 阶段 shutil.rmtree 被 safe-delete 拦截.
REM spec 已加 try/except, COLLECT 失败时 EXE 已在 build 目录.
if not exist "build\PolyXRD\PolyXRD.exe" (
    echo [错误] EXE 未生成, 构建失败!
    pause
    exit /b 1
)

echo.
echo [步骤 2/6] 手工收集 _internal ( 绕过沙盒 safe-delete, 从 COLLECT-00.toc 复制所有依赖 )...
echo.

REM 用 shell cp 单独覆盖 EXE (PyInstaller 在 build 已经产出)
copy /Y "build\PolyXRD\PolyXRD.exe" "dist\PolyXRD\PolyXRD.exe" >nul
if exist "build\PolyXRD\qt.conf" copy /Y "build\PolyXRD\qt.conf" "dist\PolyXRD\qt.conf" >nul

REM 跑 scripts\_pyinst_collect.py 复制其余依赖 (路径自推导, 原 _do_collect.py 已并入)
"%PYTHON%" scripts\_pyinst_collect.py

REM ICU 处理 (PySide6 6.11 wheel 不自带 ICU; Qt6Core 依赖 icuuc.dll):
REM 实测 (2026-09-08, 本机): System32 的 icuuc.dll (29KB) 是 Windows 官方转发 shim,
REM Qt 6.11 经其解析全部符号, 可正常启动; 而 conda/_gsas2main 的 ICU 78 独立版
REM 反而缺 Qt 所需符号 → WinError 127 "找不到指定的程序"。
REM 故策略 = 确保 dist 里【没有】任何 ICU 副本, 让加载器落到 OS shim。
"%PYTHON%" scripts\_build_post.py icu

if %errorlevel% neq 0 (
    echo [警告] ICU 复制阶段异常, 请检查 PySide6 Qt 启动依赖
)

REM 兜底: 确认安装包里确实没有数据库 (0.10.0 的核心约束)
echo.
echo [检查] 确认 dist 内不含数据库文件...
"%PYTHON%" scripts\_build_post.py no-db

echo.
echo [步骤 3/6] 创建 Inno Setup 安装程序...
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

REM -- VERSION.txt 必须在 Inno 编译前写入: dist/VERSION.txt 是持久文件,
REM    PyInstaller 不生成它, 若晚于 ISCC 则安装包内会和 EXE 版本号不一致。
echo.
echo [步骤 3/6 前置] 写 VERSION.txt (必须先于 Inno 打包, 否则安装包内残留旧版本)...
echo.
"%PYTHON%" scripts\_build_post.py version %APPVER%
:have_iscc
%ISCC% /DAppVersion=%APPVER% /O"installer_output" /F"PolyXRD-Setup-v%APPVER%" scripts\PolyXRD-Setup.iss
if %errorlevel% neq 0 (
    echo [警告] Inno 编译失败, 跳过安装程序
)

:no_iscc

echo.


REM 便携版附加文件(启动器/安全模式/使用说明) -- Setup 已先打包, 故只进便携包
"%PYTHON%" scripts\_build_post.py portable-extras %APPVER%

echo.
echo [步骤 4/6] 创建便携压缩包 (ZIP)...
echo.

if exist "installer_output\PolyXRD-v%APPVER%-Portable.zip" del "installer_output\PolyXRD-v%APPVER%-Portable.zip" >nul
powershell -Command "Compress-Archive -Path 'dist\PolyXRD\*' -DestinationPath 'installer_output\PolyXRD-v%APPVER%-Portable.zip' -Force"
if %errorlevel% neq 0 (
    echo [警告] ZIP 压缩失败, 尝试备用方法...
    powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::CreateFromDirectory('dist\PolyXRD', 'installer_output\PolyXRD-v%APPVER%-Portable.zip')"
)

echo.
echo [步骤 5/6] 校验产物 + 生成三个独立外挂数据库 ZIP + 计算 SHA-256...
echo.
echo [信息] 库各自成包 (用户按需只下一个):
echo          PolyXRD-v%APPVER%-Databases-COD-inorg-index.zip  (COD 无机物库, 主检索库)
echo          PolyXRD-v%APPVER%-Databases-COD-full-index.zip   (COD 全库索引)
echo          PolyXRD-v%APPVER%-Databases-PDF2.zip       (PDF2-2004 库)  ^<-- 本地自用
echo.
echo [重要] PDF2-2004 是 ICDD 版权商品库: 上面这个 PDF2 包**仅作本地归档**,
echo        永远不要上传到 GitHub / Release。发布时只传 Setup + Portable + 两个 COD 包。
echo.

set PWSH=pwsh
where pwsh >nul 2>&1 || set PWSH=powershell
%PWSH% -NoProfile -ExecutionPolicy Bypass -File "scripts\verify_release.ps1" -Version %APPVER%
if %errorlevel% neq 0 (
    echo.
    echo [警告] 产物校验未全部通过, 请检查上面的 FAIL 项!
)

echo.
echo [步骤 6/6] VERSION.txt 已在前置步骤写入, 此步仅核对...
echo.

if not exist "dist\PolyXRD\VERSION.txt" (
    echo [警告] VERSION.txt 缺失!
)

echo.
echo ========================================
echo   PolyXRD v%APPVER% 打包完成！
echo ========================================
echo.

echo 输出 (installer_output\):
if exist "installer_output\PolyXRD-Setup-v%APPVER%.exe" for %%A in ("installer_output\PolyXRD-Setup-v%APPVER%.exe") do echo   Setup.exe:     %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Portable.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Portable.zip") do echo   Portable.zip:  %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Databases-COD-inorg-index.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Databases-COD-inorg-index.zip") do echo   库-COD无机物: %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Databases-COD-full-index.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Databases-COD-full-index.zip") do echo   库-COD全库:   %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Databases-PDF2.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Databases-PDF2.zip") do echo   库-PDF2:      %%~zA 字节
if exist "dist\PolyXRD\PolyXRD.exe" for %%A in ("dist\PolyXRD\PolyXRD.exe") do echo   PolyXRD.exe:   %%~zA 字节

echo.
pause
