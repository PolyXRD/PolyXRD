# PolyXRD 发布产物校验 / 收尾 (v0.10.0+)
# ==========================================
# 用法:  pwsh -NoProfile -File scripts\verify_release.ps1 -Version 0.10.0
#
# 做三件事:
#   1. 校验便携包 zip 可读、含 PolyXRD.exe、且**不含**任何业务数据库
#   2. 生成三个**独立**的外挂数据库包 (每个包一个库) 并逐包对账
#      (条目数 + 解压后字节必须等于源文件), 同时删掉旧的合并包
#   3. 打印所有产物的 SHA-256 到 installer_output\SHA256-v<ver>.txt
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
    [switch]$SkipHash
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
    [pscustomobject]@{ Name = 'COD-inorg-index'; Src = 'cod_data\COD_inorganics.sqlite'; File = 'COD_inorganics.sqlite' },
    [pscustomobject]@{ Name = 'COD-full-index';  Src = 'cod_data\cod_index.sqlite';      File = 'cod_index.sqlite' },
    [pscustomobject]@{ Name = 'PDF2';            Src = 'cod_data\PDF2_2004.sqlite';       File = 'PDF2_2004.sqlite' }
)

# ── 1. 便携包校验 ────────────────────────────────────────────
Write-Output "[1/3] 便携包校验: $([IO.Path]::GetFileName($portable))"
if (-not (Test-Path -LiteralPath $portable)) {
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
                ($bannedNames -contains $n) -or
                (($n -like '*.sqlite' -or $n -like '*.sqlite3' -or $n -like '*.db') -and
                 $_.FullName -notlike "*$allowedSqlite")
            }
            if ($bad) {
                foreach ($b in $bad) { Fail ("包内不应存在的数据库: " + $b.FullName) }
            } else {
                Write-Output '      OK: 未发现业务数据库 (符合 0.10.0 外挂策略)'
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

if ($builtPkgs.Count -eq 0) { Fail '没有生成任何数据库包' }

# ── 3. SHA-256 ───────────────────────────────────────────────
Write-Output '[3/3] SHA-256'
if ($SkipHash) {
    Write-Output '      (已跳过)'
} else {
    $hashFile = Join-Path $outDir "SHA256-v$Version.txt"
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
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
