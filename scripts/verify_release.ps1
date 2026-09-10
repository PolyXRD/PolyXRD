# PolyXRD 发布产物校验 / 收尾 (v0.10.0+)
# ==========================================
# 用法:  pwsh -NoProfile -File scripts\verify_release.ps1 -Version 0.10.0
#
# 做三件事:
#   1. 校验便携包 zip 可读、含 PolyXRD.exe、且**不含**任何业务数据库
#   2. 生成「外挂数据库包」并对账 (条目数 + 解压后字节必须等于源文件之和)
#   3. 打印三个产物的 SHA-256 到 installer_output\SHA256-v<ver>.txt
#
# 为什么把"含不含 .sqlite"当成断言: 0.10.0 的核心约束就是数据库外挂,
# 一旦 spec 的 datas 被谁改回去, 便携包会悄悄胖 700 MB —— 必须让构建自己喊出来。

param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$SkipHash
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$outDir   = Join-Path $Root 'installer_output'
$portable = Join-Path $outDir "PolyXRD-v$Version-Portable.zip"
$dbZip    = Join-Path $outDir "PolyXRD-v$Version-Databases.zip"
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

# ── 2. 外挂数据库包 ──────────────────────────────────────────
Write-Output '[2/3] 外挂数据库包'
$sources = @()
foreach ($rel in 'cod_index.sqlite', 'cod_data\COD_inorganics.sqlite', 'cod_data\PDF2_2004.sqlite') {
    $p = Join-Path $Root $rel
    if (Test-Path -LiteralPath $p) {
        $sources += $p
        Write-Output ('      源 ' + $rel + '  ' + (MiB (Get-Item -LiteralPath $p).Length))
    } else {
        Write-Output ('      [跳过] 缺少 ' + $rel)
    }
}

if ($sources.Count -eq 0) {
    Fail '没有任何数据库文件可打包'
} else {
    if (Test-Path -LiteralPath $dbZip) { Remove-Item -LiteralPath $dbZip -Force }
    $t0 = Get-Date
    Compress-Archive -LiteralPath $sources -DestinationPath $dbZip -Force
    Write-Output ('      生成 ' + (MiB (Get-Item -LiteralPath $dbZip).Length) +
                  ' / 耗时 ' + [int]((Get-Date) - $t0).TotalSeconds + ' s')

    # 对账: 解压后总字节必须与源文件之和逐字节相等
    $zip = [System.IO.Compression.ZipFile]::OpenRead($dbZip)
    try {
        $sum     = ($zip.Entries | Measure-Object -Property Length -Sum).Sum
        $names   = @($zip.Entries | ForEach-Object { $_.FullName })
        $nEntry  = $zip.Entries.Count
    } finally { $zip.Dispose() }
    $srcSum = ($sources | ForEach-Object { (Get-Item -LiteralPath $_).Length } | Measure-Object -Sum).Sum

    Write-Output ('      条目 ' + $nEntry + ' ; 解压后 ' + $sum + ' B ; 源合计 ' + $srcSum + ' B')
    if ($nEntry -ne $sources.Count) { Fail "包内条目数 $nEntry 与源文件数 $($sources.Count) 不符" }
    if ($sum -ne $srcSum)            { Fail "解压后字节 $sum 与源合计 $srcSum 不符 (打包可能被截断)" }
    if ($nEntry -eq $sources.Count -and $sum -eq $srcSum) {
        Write-Output '      OK: 条目数与字节数逐项对账通过'
    }
    Write-Output ('      内含: ' + ($names -join ', '))
}

# ── 3. SHA-256 ───────────────────────────────────────────────
Write-Output '[3/3] SHA-256'
if ($SkipHash) {
    Write-Output '      (已跳过)'
} else {
    $hashFile = Join-Path $outDir "SHA256-v$Version.txt"
    $lines = @("PolyXRD v$Version 发布产物校验值 (SHA-256)",
               '生成时间: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),
               '单位说明: MB = 1,048,576 字节 (资源管理器口径)',
               '')
    foreach ($f in @(
        (Join-Path $outDir "PolyXRD-Setup-v$Version.exe"),
        $portable, $dbZip)) {
        if (-not (Test-Path -LiteralPath $f)) { continue }
        $item = Get-Item -LiteralPath $f
        $h = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower()
        Write-Output ('      ' + $item.Name.PadRight(38) + (MiB $item.Length).PadLeft(12) + '  ' + $h)
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
