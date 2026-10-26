# PolyXRD 发布产物校验 / 收尾 (v0.10.0+)
# ==========================================
# 用法:  pwsh -NoProfile -File scripts\verify_release.ps1 -Version 0.10.0
#
# 做三件事:
#   1. 校验便携包 zip 可读、含 PolyXRD.exe、且**不含**任何业务数据库
#   2. 生成**独立**的外挂数据库包并逐包对账:
#        · v4.0.0 起优先打 **polyDB** 两个包 (COD-Inorg / COD-Full) —— 自研列存格式,
#          体积小 13.9×、检索快 12~14×, 见 docs/代码评估-v4.0.0.md;
#        · 找不到 polyDB 目录时退回旧的 sqlite 三包逻辑 (兼容老机器/老流程);
#      PDF2-2004 为 ICDD 版权库, 任何情况下都**不**进 Release 上传清单。
#   3. 打印所有产物的 SHA-256 到 installer_output\SHA256-v<ver>.txt
#
# ★ 政策：**数据库不在本仓库上传/发布**。默认**不**生成数据库包（-PackDbPackages
#   仅用于本地归档/对账）；对外分发统一在独立仓库
#   https://github.com/PolyXRD/PolyXRD-DataBase 的 Releases。主仓库 Release 恒 3 附件。
# ★ v4.1.1：新增 Setup 存在性/版本/新鲜度校验（此前 ISCC 失败会拿旧 Setup 算 SHA），
#   并支持 -SkipSetup / -SkipPortable 由 flavor 决定（不再靠"文件不存在"自证跳过）。
#
# 为什么把"含不含 .sqlite"当成断言: 0.10.0 的核心约束就是数据库外挂,
# 一旦 spec 的 datas 被谁改回去, 便携包会悄悄胖 700 MB —— 必须让构建自己喊出来。
#
# 为什么三个库各自成包: 用户往往只需要其中一个 (多数人只要无机物库)。
# 合并成一个 400 MB 的包等于强迫所有人下满全部三个; 拆开后各取所需,
# 且与 GUI 的三个独立挂载槽位一一对应, 不会出现"下了整包不知道要不要全挂"。

param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    # polyDB 库所在目录; 默认取仓库同级 PolyXRD-DataBase\polydb
    [string]$PolyDbRoot = '',
    [switch]$SkipHash,
    # v4.1.0: Setup(正式安装包) 与便携包是**两个不同变体**的两个产物, 由两次
    #   独立构建分别产出。release 那次构建里便携包尚不存在, 属正常 —— 用
    #   -SkipPortable 跳过该项, 不要误报 FAIL。
    [switch]$SkipPortable,
    # release 构建只需要校验本变体产物；internal 构建校验便携包
    [switch]$SkipSetup,
    # v4.1.1: 默认不生成数据库包（政策：数据库不在本仓库发布）；
    #   需要本地归档/对账时显式加本开关。
    [switch]$PackDbPackages,
    # v4.1.2: 纯客户端小包（POLYXRD_NO_BUNDLE_DB=1）没有内置库
    [switch]$SkipBundledDb,
    # v4.2.1: 构建后核对 dist flavor / VERSION.txt，防止变体串味
    [ValidateSet('', 'release', 'internal')][string]$ExpectedFlavor = '',
    [switch]$CheckDistVersion
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$outDir   = Join-Path $Root 'installer_output'
$portable = Join-Path $outDir "PolyXRD-v$Version-Portable.zip"
$fail     = 0

function MiB([long]$bytes) { '{0:N1} MB' -f ($bytes / 1MB) }

function Fail([string]$msg) {
    Write-Output "  [FAIL] $msg"
    $script:fail++
}

# pymatgen 自带的对称性数据表, 是依赖的一部分, 不算业务数据库
$allowedSqlite = 'pymatgen/symmetry/symm_data_magnetic.sqlite'
# 业务数据库文件名 —— 出现在包里就是构建策略被改坏了
$bannedNames = @('cod_index.sqlite', 'COD_inorganics.sqlite', 'PDF2_2004.sqlite')

# 槽位 → (源文件, 包名后缀, 包内文件名)。后缀必须与
# polyxrd/services/db_import.py 的 DBKind.pkg_suffix 保持一致。
$dbKinds = @(
    # v0.14.0 起发布包改发瘦身索引式无机库 (无内嵌 CIF, CIF 走 cod/cif 目录或 COD REST 回退);
    # 源文件与包内文件名必须与 db_import.PKG_FILENAME 一致 —— 别再用完整内嵌版
    # COD_inorganics.sqlite (1.19 GB, CIF 内嵌占 830 MB)。
    [pscustomobject]@{ Name = 'COD-inorg-index'; Src = 'cod_data\COD_inorganics_index.sqlite'; File = 'COD_inorganics_index.sqlite' },
    [pscustomobject]@{ Name = 'COD-full-index';  Src = 'cod_data\cod_index.sqlite';           File = 'cod_index.sqlite' },
    [pscustomobject]@{ Name = 'PDF2';            Src = 'cod_data\PDF2_2004.sqlite';           File = 'PDF2_2004.sqlite' }
)

# v4.1.1: 政策默认不生成数据库包（含旧 sqlite 兼容包）；本地归档才显式打开。
if (-not $PackDbPackages) { $dbKinds = @() }

# ── 1a. Setup 校验（v4.1.1 新增）────────────────────────────
$setup = Join-Path $outDir "PolyXRD-Setup-v$Version.exe"
Write-Output "[1a/3] Setup 校验: $([IO.Path]::GetFileName($setup))"
if ($SkipSetup) {
    Write-Output '      (本次为 internal 构建, Setup 由 release 变体那次构建产出 —— 本次跳过)'
} elseif (-not (Test-Path -LiteralPath $setup)) {
    Fail 'Setup 不存在（release 构建必须产出正式安装包）'
} else {
    $setupItem = Get-Item -LiteralPath $setup
    Write-Output ('      体积 ' + (MiB $setupItem.Length))
    $vi = $setupItem.VersionInfo
    if ($vi.FileVersion -notlike "$Version*") {
        Fail ("Setup FileVersion=$($vi.FileVersion) 与版本 $Version 不一致")
    } else {
        Write-Output ("      OK: FileVersion=$($vi.FileVersion), ProductVersion=$($vi.ProductVersion)")
    }
    $distExe = Join-Path $Root 'dist\PolyXRD\PolyXRD.exe'
    if (Test-Path -LiteralPath $distExe) {
        if ($setupItem.LastWriteTime -lt (Get-Item -LiteralPath $distExe).LastWriteTime) {
            # 两次独立构建（release Setup / internal Portable）先后会刷新 dist，
            # 因此 mtime 只作提示，不硬失败；ISCC 失败已在 build.bat 里硬失败。
            Write-Output '      [提示] Setup mtime 早于当前 dist EXE（两次构建的先后关系），新鲜度按版本号判定'
        } else {
            Write-Output '      OK: Setup 晚于本次 dist EXE（不是旧包）'
        }
    }
}

# ── 1a2. dist 版本与 flavor（v4.2.1）────────────────────────
$distExe = Join-Path $Root 'dist\PolyXRD\PolyXRD.exe'
if ($CheckDistVersion) {
    $verFile = Join-Path $Root 'dist\PolyXRD\VERSION.txt'
    Write-Output "[1a2/3] dist VERSION.txt 校验"
    if (-not (Test-Path -LiteralPath $verFile)) {
        Fail 'dist/PolyXRD/VERSION.txt 不存在'
    } else {
        $vt = Get-Content -LiteralPath $verFile -Raw
        if ($vt -notmatch "Version\s*:\s*$([regex]::Escape($Version))") {
            Fail "dist/VERSION.txt 版本号与 $Version 不一致"
        } else {
            Write-Output '      OK: VERSION.txt 版本号一致'
        }
    }
}
if ($ExpectedFlavor -ne '') {
    Write-Output "[1a3/3] dist EXE flavor 校验 (期望 $ExpectedFlavor)"
    if (-not (Test-Path -LiteralPath $distExe)) {
        Fail 'dist/PolyXRD/PolyXRD.exe 不存在，无法校验 flavor'
    } else {
        $py = Join-Path $Root 'venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }
        $code = @'
import sys
from pathlib import Path
sys.path.insert(0, r"scripts")
from verify_installer import flavor_of_exe
print(flavor_of_exe(Path(sys.argv[1])))
'@
        $flavor = (& $py -c $code $distExe 2>$null | Select-Object -Last 1).Trim()
        if ($flavor -ne $ExpectedFlavor) {
            Fail "dist EXE flavor=$flavor != 期望 $ExpectedFlavor"
        } else {
            Write-Output "      OK: dist EXE flavor=$flavor"
        }
    }
}

# ── 1. 便携包校验 ────────────────────────────────────────────
Write-Output "[1b/3] 便携包校验: $([IO.Path]::GetFileName($portable))"
if ($SkipPortable) {
    Write-Output '      (本次为 release 构建, 便携包由 internal 变体那次构建产出 —— 本次跳过)'
} elseif (-not (Test-Path -LiteralPath $portable)) {
    Fail '便携包不存在'
} else {
    Write-Output ('      体积 ' + (MiB (Get-Item -LiteralPath $portable).Length))
    try {
        $zip = [System.IO.Compression.ZipFile]::OpenRead($portable)
        try {
            $entries = $zip.Entries
            Write-Output ('      条目数 ' + $entries.Count)
            if (-not ($entries | Where-Object { $_.FullName -eq 'PolyXRD.exe' })) {
                Fail '包内缺少 PolyXRD.exe'
            }
            $bad = $entries | Where-Object {
                $n = $_.Name
                $rel = $_.FullName.Replace('\', '/')
                # v4.1.0: 便携包**内置**默认库 COD-Inorg polyDB —— 解压即可检索。
                # 只允许 databases/<*.polyDB>/ 这一处（polyDB 自身含 index.sqlite，
                # 属于库的正常分段文件，不是"漏进去的业务库"）。
                $isBundledPolyDB = $rel -like 'databases/*.polyDB/*'
                if (-not $isBundledPolyDB) {
                    ($bannedNames -contains $n) -or
                    ($rel -like '*.polyDB*') -or
                    (($n -like '*.sqlite' -or $n -like '*.sqlite3' -or $n -like '*.db') -and
                     $rel -notlike "*$allowedSqlite")
                }
            }
            if ($bad) {
                foreach ($b in $bad) { Fail ("包内不应存在的数据库: " + $b.FullName) }
            } else {
                Write-Output '      OK: 数据库仅位于 databases\<*.polyDB>\ (v4.1.0 内置默认库)'
            }
            if ($SkipBundledDb) {
                Write-Output '      (POLYXRD_NO_BUNDLE_DB：纯客户端小包，跳过内置库校验)'
            } else {
                # 内置库完整性: 每个 databases/*.polyDB/ 的 8 个分段都要齐
                # ⚠ 条目名分隔符不可信: Compress-Archive(.NET Framework) 写出的 zip 里
                #   ZipArchiveEntry.FullName 用的是**反斜杠**，Python zipfile 读出来却是
                #   正斜杠 —— 所以一律先归一化再比对，别直接拼 '/xxx' 去比。
                $segments = @('meta.json', 'index.sqlite', 'peaks_d.f32', 'peaks_i.u16',
                              'bins.u8', 'elem.u8', 'sites.bin', 'sites_off.i64')
                $norm = @{}
                foreach ($e in $entries) { $norm[$e.FullName.Replace('\', '/')] = $e.Length }
                $metaNames = @($norm.Keys |
                    Where-Object { $_ -like 'databases/*.polyDB/meta.json' })
                if ($metaNames.Count -eq 0) {
                    Fail '便携包内没有 databases\*.polyDB\meta.json —— 解压后无法直接检索'
                }
                foreach ($metaName in $metaNames) {
                    $libDir = ($metaName -replace '/meta\.json$', '')
                    $lib = Split-Path $libDir -Leaf
                    foreach ($seg in $segments) {
                        if (-not $norm.ContainsKey("$libDir/$seg")) {
                            Fail ("内置 polyDB 缺少分段文件: $libDir/$seg")
                        }
                    }
                    Write-Output ('      内置库 ' + $lib + ' 8/8 分段文件齐全')
                }
            }
        } finally { $zip.Dispose() }
    } catch {
        Fail ('zip 无法读取: ' + $_.Exception.Message)
    }
}

# ── 2. 三个独立外挂数据库包 ──────────────────────────────────
Write-Output '[2/3] 外挂数据库包 (每个库独立成包)'

# 清理历史产物: 合并版大包与旧后缀, 避免发布页出现两套互相矛盾的下载项
foreach ($stale in @(
    (Join-Path $outDir "PolyXRD-v$Version-Databases.zip"),
    (Join-Path $outDir "PolyXRD-v$Version-Databases-fixed.zip"))) {
    if (Test-Path -LiteralPath $stale) {
        Remove-Item -LiteralPath $stale -Force
        Write-Output ('      已删除旧合并包 ' + [IO.Path]::GetFileName($stale))
    }
}

$builtPkgs = @()

# ── 2a. polyDB (v4.0.0 起的发布形态) ─────────────────────────
# 每个 .polyDB 是**目录容器**, 所以包内是多文件; 对账口径 = 文件数 + 解压字节
# + 必需段齐全, 不比单个条目。
$polyBuilt = $false
$polyRoot = if ($PolyDbRoot) { $PolyDbRoot } else {
    Join-Path (Split-Path -Parent $Root) 'PolyXRD-DataBase\polydb'
}
if (-not $PackDbPackages) {
    Write-Output '      (v4.1.1 政策: 数据库包不上传主仓库, 默认不打包; 本地归档请加 -PackDbPackages)'
} elseif (Test-Path -LiteralPath $polyRoot) {
    Write-Output ('      polyDB 根目录: ' + $polyRoot)
    foreach ($pk in @(
        [pscustomobject]@{ Name = 'COD-inorg-polyDB'; Glob = 'COD-Inorg-*.polyDB' },
        [pscustomobject]@{ Name = 'COD-full-polyDB';  Glob = 'COD-Full-*.polyDB' }
    )) {
        $dirs = @(Get-ChildItem -LiteralPath $polyRoot -Directory -Filter $pk.Glob -ErrorAction SilentlyContinue |
                  Sort-Object Name -Descending)
        if ($dirs.Count -eq 0) {
            Write-Output ('      [跳过] 未找到 ' + $pk.Glob + ' (' + $polyRoot + ')')
            continue
        }
        $src = $dirs[0].FullName
        $pkg = Join-Path $outDir ("PolyXRD-v$Version-Databases-" + $pk.Name + '.zip')
        if (Test-Path -LiteralPath $pkg) { Remove-Item -LiteralPath $pkg -Force }  # 幂等: CreateFromDirectory 不覆盖
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $src, $pkg, [System.IO.Compression.CompressionLevel]::Optimal, $true)
        $zipSize = (Get-Item -LiteralPath $pkg).Length
        $srcFiles = @(Get-ChildItem -LiteralPath $src -Recurse -File)
        $srcBytes = ($srcFiles | Measure-Object -Property Length -Sum).Sum
        Write-Output ('      ' + [IO.Path]::GetFileName($pkg).PadRight(46) +
                      (MiB $zipSize).PadLeft(12) + '  (源 ' + (MiB $srcBytes) + ')')

        $zip = [System.IO.Compression.ZipFile]::OpenRead($pkg)
        try {
            $fileEntries = @($zip.Entries | Where-Object { $_.Name -ne '' })
            $zipBytes = ($fileEntries | Measure-Object -Property Length -Sum).Sum
            $names = @($fileEntries | ForEach-Object { $_.Name })
        } finally { $zip.Dispose() }

        $need = @('meta.json', 'index.sqlite', 'peaks_d.f32', 'peaks_i.u16',
                  'bins.u8', 'elem.u8', 'sites.bin', 'sites_off.i64')
        $missing = @($need | Where-Object { $names -notcontains $_ })
        if ($fileEntries.Count -ne $srcFiles.Count) {
            Fail "$($pk.Name): 包内文件数 $($fileEntries.Count) != 源 $($srcFiles.Count)"
        } elseif ($zipBytes -ne $srcBytes) {
            Fail "$($pk.Name): 解压后 $zipBytes B != 源 $srcBytes B (打包被截断?)"
        } elseif ($missing.Count -gt 0) {
            Fail "$($pk.Name): 缺必需段 $($missing -join ',')"
        } else {
            Write-Output ('            OK: ' + $fileEntries.Count + ' 个文件 / 字节对账通过 / 必需段齐全')
            $builtPkgs += $pkg
            $polyBuilt = $true
        }
    }
}
if ($polyBuilt) {
    Write-Output '      (polyDB 已生成 -> 本次不再打旧的 sqlite 索引包)'
    $dbKinds = @()
}

foreach ($k in $dbKinds) {
    $src = Join-Path $Root $k.Src
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Output ('      [跳过] 缺少源文件 ' + $k.Src)
        continue
    }
    $pkg = Join-Path $outDir "PolyXRD-v$Version-Databases-$($k.Name).zip"
    $t0 = Get-Date
    Compress-Archive -LiteralPath $src -DestinationPath $pkg -Force
    $zipSize = (Get-Item -LiteralPath $pkg).Length
    $srcSize = (Get-Item -LiteralPath $src).Length
    Write-Output ('      ' + [IO.Path]::GetFileName($pkg).PadRight(38) +
                  (MiB $zipSize).PadLeft(12) + '  (源 ' + (MiB $srcSize) + ')')

    # 对账: 必须恰好 1 个条目、名字正确、解压字节等于源字节
    $zip = [System.IO.Compression.ZipFile]::OpenRead($pkg)
    try {
        $cnt   = $zip.Entries.Count
        $inner = @($zip.Entries | ForEach-Object { $_.Name })
        $sum   = ($zip.Entries | Measure-Object -Property Length -Sum).Sum
    } finally { $zip.Dispose() }

    if ($cnt -ne 1)          { Fail "$($k.Name): 包内条目数 $cnt != 1" }
    if ($inner[0] -ne $k.File) { Fail "$($k.Name): 包内文件 '$($inner[0])' != 期望 '$($k.File)'" }
    if ($sum -ne $srcSize)   { Fail "$($k.Name): 解压后 $sum B != 源 $srcSize B (打包被截断?)" }
    if ($cnt -eq 1 -and $inner[0] -eq $k.File -and $sum -eq $srcSize) {
        Write-Output ('            OK: 1 个条目 / ' + $inner[0] + ' / 字节对账通过')
        $builtPkgs += $pkg
    }
}

if ($PackDbPackages -and $builtPkgs.Count -eq 0) { Fail '没有生成任何数据库包' }
if ($polyBuilt) {
    Write-Output '      注意: 库包仅本地生成/校验; 对外发布在 PolyXRD-DataBase 仓库的 Releases (本仓库 Release 不含数据库)。'
}

# ── 3. SHA-256 ───────────────────────────────────────────────
Write-Output '[3/3] SHA-256'
if ($SkipHash) {
    Write-Output '      (已跳过)'
} else {
    $hashFile = Join-Path $outDir "SHA256-v$Version.txt"
    # v4.2.1: 时间戳取产物 mtime 而非当前时间 —— 发布后重复校验不会改写
    # SHA 文件（v4.2.0 曾因重新生成时间行导致本地 digest 与远端漂移）。
    $mtimes = @(
        @((Join-Path $outDir "PolyXRD-Setup-v$Version.exe"), $portable) |
            Where-Object { Test-Path -LiteralPath $_ } |
            ForEach-Object { (Get-Item -LiteralPath $_).LastWriteTime }
    )
    $stamp = if ($mtimes.Count -gt 0) {
        ($mtimes | Sort-Object | Select-Object -Last 1).ToString('yyyy-MM-dd HH:mm:ss')
    } else {
        (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    }
    $lines = @(
        "PolyXRD v$Version 发布产物校验值 (SHA-256)",
        "生成时间: $stamp",
        '单位说明: MB = 1,048,576 字节 (资源管理器口径)',
        ''
    )
    $targets = @((Join-Path $outDir "PolyXRD-Setup-v$Version.exe"), $portable) + $builtPkgs
    foreach ($f in $targets) {
        if (-not (Test-Path -LiteralPath $f)) { continue }
        $item = Get-Item -LiteralPath $f
        $h = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower()
        Write-Output ('      ' + $item.Name.PadRight(42) + (MiB $item.Length).PadLeft(12) + '  ' + $h)
        $lines += "$h  $($item.Name)"
        $lines += ('#   size = {0:N0} bytes ({1})' -f $item.Length, (MiB $item.Length))
    }
    $lines | Out-File -LiteralPath $hashFile -Encoding utf8
    Write-Output ('      写入 ' + $hashFile)
}

Write-Output ''
if ($fail -gt 0) {
    Write-Output "RESULT: FAIL ($fail 项)"
    exit 1
}
Write-Output 'RESULT: OK'
