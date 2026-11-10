@echo off
chcp 65001 >nul
REM -- UTF-8 everywhere (v2.0.0): build/dev also run in UTF-8 so that
REM -- Chinese/Japanese never turns into mojibake on a non-CJK Windows.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM APPVER 是版本号唯一真源（标题 / banner / 输出名 / 安装包名都跟随）
set APPVER=5.4.0

title PolyXRD v%APPVER% 打包构建器
echo ========================================
echo   PolyXRD v%APPVER% 打包为独立安装包
echo   内置 COD-Inorg 库 + 其余库外挂
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

REM -- 构建变体 flavor (v2.10.0) -----------------------------------------
REM   release  (默认) = 正式发布版: 启用注册机制, 未注册时每次启动提示版权信息
REM   internal        = 内部评估版: 不含任何注册 UI/提示, 状态栏右端显示「内部评估版本」
REM flavor 以 src/polyxrd/_build_flavor.py 的形式在 PyInstaller 之前烧入包中,
REM 运行时不可切换; 该文件被 .gitignore 的 _*.py 规则覆盖, 永不入库。
if "%POLYXRD_FLAVOR%"=="" set POLYXRD_FLAVOR=release
"%PYTHON%" scripts\set_build_flavor.py %POLYXRD_FLAVOR%
if errorlevel 1 (
    echo [错误] 构建变体设置失败!
    pause
    exit /b 1
)
"%PYTHON%" scripts\set_build_flavor.py show

"%PYTHON%" -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 安装 PyInstaller...
    "%PIP%" install pyinstaller>=6.0
)

echo.
echo [步骤 1/6] PyInstaller 打包 (EXE 阶段, COLLECT 阶段可能因沙盒 safe-delete 失败)...
echo.
if defined POLYXRD_NO_BUNDLE_DB (
    echo [信息] POLYXRD_NO_BUNDLE_DB=1: 纯客户端小包, 不内置默认库; 验收自动加 -SkipBundledDb
) else (
    echo [信息] 数据库策略: v4.1.0 起内置默认库 COD-Inorg, polyDB ~86 MB。
    echo        COD-Full 仍为外挂可选包; PDF2-2004 因版权永不随包分发。
)

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

REM v4.1.0: 默认库内置 —— 把 COD-Inorg polyDB 复制进 dist\PolyXRD\databases
REM (只要是无机物库; 解压即可检索, 无需先下载外挂库)。跳过用 set POLYXRD_NO_BUNDLE_DB=1
if defined POLYXRD_NO_BUNDLE_DB goto :skip_bundle_db
echo.
echo [步骤 2.5/6] 内置默认库 COD-Inorg (polyDB) 复制到 dist\PolyXRD\databases ...
echo.
"%PYTHON%" scripts\_build_post.py bundle-polydb
if %errorlevel% neq 0 (
    echo [错误] 内置默认库复制失败, 构建中止!
    pause
    exit /b 1
)

REM 兜底: 断言库布局正确 (只允许 databases\<*.polyDB>\ 的 8 个分段文件)
echo.
echo [检查] 数据库布局 (内置 polyDB + 无意外库文件)...
"%PYTHON%" scripts\_build_post.py db-layout
if %errorlevel% neq 0 (
    echo [错误] 内置库布局检查未通过, 构建中止!
    pause
    exit /b 1
)

:skip_bundle_db

echo.
echo [步骤 3/6] 创建 Inno Setup 安装程序...
echo.

if not exist "installer_output" mkdir installer_output

REM -- VERSION.txt 必须在 Inno 编译前写入: dist/VERSION.txt 是持久文件,
REM    PyInstaller 不生成它, 若晚于 ISCC 则安装包内会和 EXE 版本号不一致。
REM    ⚠ 必须放在 ISCC 探测 / goto 之前, 否则会被 goto :have_iscc / :no_iscc 跳过。
echo.
echo [步骤 3/6 前置] 写 VERSION.txt (必须先于 Inno 打包, 否则安装包内残留旧版本)...
echo.
"%PYTHON%" scripts\_build_post.py version %APPVER%
if %errorlevel% neq 0 (
    echo [错误] VERSION.txt 写入失败, 构建中止!
    pause
    exit /b 1
)

REM -- flavor 门禁 (v4.1.0 修复) ------------------------------------------------
REM   Setup 与便携包是**两个不同变体**的两个产物, 却落在同一批次输出目录:
REM     · 正式安装包 必须是 release 变体(启用注册机制, 无「内部评估版本」红字)
REM     · 便携包     必须是 internal 变体(状态栏红色加粗「内部评估版本」)
REM   flavor 是**烧进包里**的、不可事后修改, 所以两者必须由两次独立构建分别产出,
REM   且每次**只产自己那一个**。否则后一次构建会用同名文件覆盖前一次的产物,
REM   两个变体的产物无法区分(同名), 发布时极易装错/发错。
REM   本次修复还顺带解决了首版 Setup 把**便携版专属文件**(启动 PolyXRD.bat /
REM   安全模式启动.bat / 便携版使用说明.txt)一起打进安装根目录的问题 ——
REM   根因是 portable-extras 与打包步骤无条件执行, 顺序一换就串味。
REM v4.1.1: release 分支显式清掉可能残留的便携版专属文件
REM (dist 未被完全清空时, 上次 internal 构建的三件套会串进 Setup)
if /i not "%POLYXRD_FLAVOR%"=="internal" (
    del /q "dist\PolyXRD\启动 PolyXRD.bat" 2>nul
    del /q "dist\PolyXRD\安全模式启动.bat" 2>nul
    del /q "dist\PolyXRD\便携版使用说明.txt" 2>nul
)
if /i "%POLYXRD_FLAVOR%"=="internal" goto :skip_iscc
echo [flavor] release 变体: 编译正式安装包 (Setup)...
echo.

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
%ISCC% /DAppVersion=%APPVER% /O"installer_output" /F"PolyXRD-Setup-v%APPVER%" scripts\PolyXRD-Setup.iss
if %errorlevel% equ 0 goto :iscc_ok
echo [错误] Inno 编译失败!
if /i not "%POLYXRD_FLAVOR%"=="internal" (
    pause
    exit /b 1
)
goto :no_iscc

:iscc_ok
goto :skip_iscc

:no_iscc
if /i not "%POLYXRD_FLAVOR%"=="internal" (
    echo [错误] release 构建需要 Inno Setup, 但未找到 —— 构建中止!
    pause
    exit /b 1
)
:skip_iscc
echo.


REM 便携版附加文件(启动器/安全模式/使用说明) -- 只进便携包, 不进 Setup。
REM release 构建**不**做这一步: 便携包必须是 internal 变体(见上方 flavor 门禁),
REM 且这三个文件本就不该出现在正式安装包里。
if /i not "%POLYXRD_FLAVOR%"=="internal" goto :skip_portable
echo [flavor] internal 变体: 生成便携包附加文件 + 便携压缩包...
echo.
"%PYTHON%" scripts\_build_post.py portable-extras %APPVER%
if %errorlevel% neq 0 (
    echo [错误] 便携版附加文件生成失败, 构建中止!
    pause
    exit /b 1
)

echo.
echo [步骤 4/6] 创建便携压缩包 (ZIP)...
echo.

if exist "installer_output\PolyXRD-v%APPVER%-Portable.zip" del "installer_output\PolyXRD-v%APPVER%-Portable.zip" >nul
REM v4.4.0: $ProgressPreference 必须关掉。本项目的构建是**无控制台**跑的
REM (stdout 重定向到日志文件), Compress-Archive 的进度条会去读控制台输出缓冲区,
REM 拿不到就抛 "Win32 internal error Access is denied 0x5"; 这是非终止错误,
REM PowerShell 仍以 0 退出 -> 下面的 errorlevel 兜底也不触发 -> 便携包根本没生成,
REM 直到 verify_release 才报 "便携包不存在" (2026-10-27 实测踩到)。
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Compress-Archive -Path 'dist\PolyXRD\*' -DestinationPath 'installer_output\PolyXRD-v%APPVER%-Portable.zip' -Force"
if %errorlevel% neq 0 (
    echo [警告] ZIP 压缩失败, 尝试备用方法...
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::CreateFromDirectory('dist\PolyXRD', 'installer_output\PolyXRD-v%APPVER%-Portable.zip')"
)
if not exist "installer_output\PolyXRD-v%APPVER%-Portable.zip" (
    echo [错误] 便携压缩包未生成, 构建中止!
    pause
    exit /b 1
)

:skip_portable

echo.
echo [步骤 5/6] 校验产物 + 计算 SHA-256 (数据库包默认不打包)...
echo.
echo [政策] 主仓库 Release 只发程序 (Setup + Portable + SHA256), 不上传任何数据库包。
echo        默认库 COD-Inorg 已内置在安装包/便携包内; 扩展库 (COD-Full 等) 由独立仓库
echo        https://github.com/PolyXRD/PolyXRD-DataBase 的 Releases 分发。
echo        本步骤默认不生成/校验外挂数据库包 (本地归档请手工加 -PackDbPackages)。
echo.
echo [重要] PDF2-2004 是 ICDD 版权商品库: 永远不要上传到 GitHub / Release。
echo.

set PWSH=pwsh
where pwsh >nul 2>&1 || set PWSH=powershell
REM v4.1.1: 验收口径由 flavor 决定 (release -> Setup; internal -> Portable),
REM 不再用"文件是否存在"自证跳过 (zip 生成失败也会被跳过并误报 OK)。
set VERIFY_EXTRA=
if /i "%POLYXRD_FLAVOR%"=="internal" set VERIFY_EXTRA=-SkipSetup
if /i not "%POLYXRD_FLAVOR%"=="internal" set VERIFY_EXTRA=-SkipPortable
if defined POLYXRD_NO_BUNDLE_DB set VERIFY_EXTRA=%VERIFY_EXTRA% -SkipBundledDb
%PWSH% -NoProfile -ExecutionPolicy Bypass -File "scripts\verify_release.ps1" -Version %APPVER% %VERIFY_EXTRA% -ExpectedFlavor %POLYXRD_FLAVOR% -CheckDistVersion
if %errorlevel% neq 0 (
    echo.
    echo [错误] 发布产物校验未通过; 见上方 FAIL 项; 构建中止!
    pause
    exit /b 1
)

REM v4.2.1: internal 构建结束后清掉 flavor marker，避免源码树/测试被误判为内部版
if /i "%POLYXRD_FLAVOR%"=="internal" if exist "src\polyxrd\_build_flavor.py" del /q "src\polyxrd\_build_flavor.py"

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
echo   (本次构建 flavor: %POLYXRD_FLAVOR%)
if exist "installer_output\PolyXRD-Setup-v%APPVER%.exe" for %%A in ("installer_output\PolyXRD-Setup-v%APPVER%.exe") do echo   Setup.exe:     %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Portable.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Portable.zip") do echo   Portable.zip:  %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Databases-COD-inorg-polyDB.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Databases-COD-inorg-polyDB.zip") do echo   库-COD无机物(polyDB): %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Databases-COD-full-polyDB.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Databases-COD-full-polyDB.zip") do echo   库-COD全库(polyDB):   %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Databases-COD-inorg-index.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Databases-COD-inorg-index.zip") do echo   库-COD无机物(旧sqlite): %%~zA 字节
if exist "installer_output\PolyXRD-v%APPVER%-Databases-COD-full-index.zip" for %%A in ("installer_output\PolyXRD-v%APPVER%-Databases-COD-full-index.zip") do echo   库-COD全库(旧sqlite):   %%~zA 字节
if exist "installer_output\SHA256-v%APPVER%.txt" echo   SHA256.txt:    installer_output\SHA256-v%APPVER%.txt
if exist "dist\PolyXRD\PolyXRD.exe" for %%A in ("dist\PolyXRD\PolyXRD.exe") do echo   PolyXRD.exe:   %%~zA 字节

echo.
pause
