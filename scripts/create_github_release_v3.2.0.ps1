# PolyXRD v3.2.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v3.2.0.ps1'
#
# ★ 本版上传 3 个附件:
#   SHA256-v3.2.0.txt                    (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v3.2.0.exe             正式发布版安装包 —— 带注册机制
#   PolyXRD-v3.2.0-Internal-Portable.zip 内部评估版便携包 —— 无注册机制
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**。
#   底部有 $BANNED 守卫, 任何含 PDF2 的路径一旦混进来会直接抛错终止。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'D:/Project/XRD/PolyXRD'

# PortableGit on PATH (pwsh 7 环境默认没有 git; GCM 内部也要定位 git.exe)
$gitBin = 'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin'
if (Test-Path $gitBin) { $env:PATH = "$gitBin;$env:PATH" }

$owner   = 'PolyXRD'
$repo    = 'PolyXRD'
$tag     = 'v3.2.0'
$version = '3.2.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'D:/Project/XRD/PolyXRD/installer_output/3.2.0'

# ---- Token: git credential fill ----
$secInput = "protocol=https`nhost=github.com`n`n"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'git.exe'; $psi.Arguments = 'credential fill'
$psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.UseShellExecute = $false
$p = [System.Diagnostics.Process]::Start($psi)
$enc = [System.Text.Encoding]::UTF8.GetBytes($secInput)
$p.StandardInput.BaseStream.Write($enc,0,$enc.Length)
$p.StandardInput.Close()
$raw = $p.StandardOutput.ReadToEnd()
$p.WaitForExit(15000) | Out-Null
$kv = @{}
($raw -split "`n") | ForEach-Object { if($_ -match '^(.*?)=(.*)$') { $kv[$Matches[1]] = $Matches[2] } }
$token = $kv['password']
if (-not $token) { throw 'Failed to read GitHub token via git credential fill' }
Write-Host "token acquired (len=$($token.Length))"

$headers = @{
  'Authorization'        = "Bearer $token"
  'Accept'               = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent'           = 'PolyXRD-release-script/1.0'
}

# ---- Release notes ----
$body = @"
## PolyXRD v3.2.0

发布日期：2026-10-20 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v3.1.0 → v3.2.0）

本版是**大库可用性修复**：让 20~30 GB 级的外挂物相库真正能用。
起因是对两套 3COD 合并库（COD + PCOD + TCOD）的验收 —— 库本身零缺陷，
问题全在软件侧。

#### 一、用户导入的全库索引被静默忽略（修复）

`CODLocalDatabase()` 解析索引路径时，`cod_root` 分支直接假定"索引就在
COD 目录旁边"，**从不读**用户导入的路径。后果是「数据库 ▸ 外挂数据库管理…」
显示已挂载，检索却仍走旧库、或恒定判定为不可用。两种常见布局都被绕过：

| 布局 | 修前实际用的库 | 修后 |
|---|---|---|
| `<程序>/cod` | `<程序>/cod_data/cod_index.sqlite`（旧库） | 用户挂载的那个 ✅ |
| `<库目录>/COD` | `<库目录>/cod_index.sqlite`（**不存在**） | 用户挂载的那个 ✅ |

> ⚠️ 写路径（重建索引）**不认**用户挂载的库，避免把外挂库当自家索引写入。

#### 二、检索改用只读连接（修复 + 提速）

旧实现每次查询都以**可写**模式打开索引并跑一遍建表/迁移 DDL。71k 相的小库
上感觉不到，在 28 GB 的库上代价极大，还有写坏用户库的风险：

| 操作 | 修前 | 修后 |
|---|---|---|
| `is_ready()` | **65 s**，且返回 False | **0.013 s**，True |
| `stats()` | 抛 `database is locked` | 0.125 s，读出 195.9 万条 |
| 连续 5 轮状态查询 | — | 0.69 s |

同时修掉"连接泄漏自锁"：`is_ready()` 异常时不再把一条写连接一直挂在实例上，
这就是"第一次超时返回 False、第二次直接报锁"的根源。

#### 三、外挂库建索引进度反馈（新增）

XinMatch 格式库首次挂载要建「每相最强 12 峰」紧凑索引：小库 3 s，
百万相级的库要 **5~10 min**。此前这段时间界面只有一句静态提示，看起来像死机。
现在按 **清点相数 → 建强峰索引 → 读元数据** 三阶段在状态栏实时报进度。

#### 四、报告更正

上一版验收报告曾判定「零峰相会进索引建空项」，复核后确认**判断有误**：
索引由 `GROUP BY peaks` 生成，天然只含有峰的相（Inorg 1,185,866 = phases 行数、
Full 1,944,023 = 有峰相数），无需改码。1,786 条零峰条目只存在于 `entries` 表。

### 🧪 测试与验收

- 全量回归 **1489 passed / 6 skipped / 0 failed**；`ruff check src/` 全绿。
- 本轮新增 14 项单测：只读连接不改文件（字节/大小/mtime）、只读拒写、
  缺文件不造幽灵库、连接复用、`close()` 幂等、损坏库反复探测不自锁、
  两种路径布局下用户库优先、进度三阶段顺序与 100% 上报、回调异常不影响检索。
- 3COD-Full（28.17 GiB / 195.9 万相）实机复测：`identify_with_cod_local`
  8~13 s，top1 与真值一致；库文件 size/mtime 零变化。
- 二进制四轮验收：SHA-256 独立重算一致 / 静默安装后 `VERSION.txt=3.2.0` /
  启动日志 `MainWindow OK` + `shown visible=True` / 冻结 GUI 冒烟无崩溃日志 /
  两个变体的注册行为与静态指纹逐一对照。

### 📌 使用建议：库不是越大越好

实测把 3COD-Inorg（118.6 万相）挂成 COD 无机物库后，4-1 试样的 CaF₂
从第 2 名掉出 top20 —— 候选池放大 16.7× 带来的**排序稀释**，不是检索缺陷。
日常检索建议用与待测体系规模匹配的库；超大库留给"怀疑含罕见相"的兜底场景。

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | **正式发布版** Windows 安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**），带注册机制 |
| PolyXRD-v$version-Internal-Portable.zip | **内部评估版**便携包（解压即用，无注册机制，状态栏显示 ``内部评估版本``）；仅供内部自用，请勿对外分发 |
| SHA256-v$version.txt | 上述两个产物的 SHA-256 校验值 |

> **注册机制与 v2.10.0 相同**：正式发布版每次启动检查注册状态，未注册弹出版权提示
> （选「确定」仍可正常使用，选「输入注册码」即刻注册）；注册码纯离线校验、
> 可还原单位名称，同一单位多台电脑通用。索取注册码：``sshztx@outlook.com``。
> **COD 库可直接沿用旧版**：本版未改动数据库读取格式，两个 COD 索引库与程序兼容 ——
> 直接沿用 [v2.5.0 Release](https://github.com/PolyXRD/PolyXRD/releases/tag/v2.5.0)
> （或更早版本）里的同名库包即可。
> **XinMatch 格式库也不在附件中**：第三方库文件请自行准备，本版只提供挂载能力；
> 挂载入口「数据库 ▸ 外挂数据库管理… ▸ 任意位置挂载」。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，本仓库只提供挂载能力，
> 分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装（约 5 分钟，1.2 万个文件解压属正常；安装位置可选）
2. （可选）从 v2.5.0 Release 下载需要的 COD 索引库包并解压
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 用「任意位置挂载」直接指向库文件或所在文件夹
   → 立即生效，无需重启
4. 菜单「帮助 ▸ 输入注册码…」完成注册（未注册亦可正常使用，只是每次启动会提示）

> 一个库都不装也能用：程序内置 118 种常见参考物相。
"@

# ---- Idempotent: find or create release ----
$existing = $null
try {
  $existing = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers -Method Get -ErrorAction Stop
  Write-Host "Release ALREADY EXISTS: id=$($existing.id) url=$($existing.html_url)"
} catch {
  Write-Host "Release does not exist; creating..."
  $create = @{
    tag_name               = $tag
    target_commitish       = 'main'
    name                   = "PolyXRD v$version"
    body                   = $body
    draft                  = $false
    prerelease             = $false
    make_latest            = 'true'
    generate_release_notes = $false
  } | ConvertTo-Json -Depth 5
  $existing = Invoke-RestMethod -Uri "$baseURL/releases" -Headers $headers -Method Post -Body ([System.Text.Encoding]::UTF8.GetBytes($create)) -ContentType 'application/json'
  Write-Host "CREATED release id=$($existing.id) url=$($existing.html_url)"
}
$releaseId = $existing.id
$uploadURL = $existing.upload_url -replace '\{.*\}$',''

# ---- Refresh body ----
try {
  $patch = @{ body = $body; name = "PolyXRD v$version" } | ConvertTo-Json
  Invoke-RestMethod -Uri "$baseURL/releases/$releaseId" -Headers $headers -Method Patch -Body ([System.Text.Encoding]::UTF8.GetBytes($patch)) -ContentType 'application/json' | Out-Null
  Write-Host "release body refreshed"
} catch { Write-Host "WARN: body patch failed: $($_.Exception.Message)" }

$existingAssets = @()
try { $existingAssets = Invoke-RestMethod -Uri "$baseURL/releases/$releaseId/assets" -Headers $headers } catch {}

# ★ PDF2 守卫: 附件路径/名称中一旦出现 PDF2 立即终止
$BANNED = 'PDF2'
function Assert-NotBanned([string]$s) {
  if ($s -match $BANNED) {
    throw "拒绝上传: '$s' 命中禁用关键字 '$BANNED' —— PDF2-2004 受 ICDD 版权保护, 永不发布。"
  }
}

$curlExe = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
if (-not $curlExe) {
  $fallback = 'C:\Windows\System32\curl.exe'
  if (Test-Path $fallback) { $curlExe = $fallback } else { throw 'curl.exe 不存在; 无法上传附件' }
}

function Upload-Asset([string]$filePath, [string]$assetName, [string]$contentType, [int]$retries = 6) {
  Assert-NotBanned $filePath
  Assert-NotBanned $assetName
  if (-not (Test-Path $filePath)) { throw "附件不存在: $filePath" }
  $fi = Get-Item $filePath
  $size = $fi.Length
  # ★ 用 digest(sha256) 而非 size 判定是否可跳过
  $localHash = 'sha256:' + (Get-FileHash -Algorithm SHA256 -Path $filePath).Hash.ToLower()
  foreach ($o in $existingAssets) { if ($o.name -eq $assetName) {
    if ($o.state -eq 'uploaded' -and $o.size -eq $size -and $o.digest -eq $localHash) {
      Write-Host "SKIP $assetName (already uploaded, size+digest match)"
      return $o
    }
    if ($o.state -eq 'uploaded' -and $o.digest -ne $localHash) {
      Write-Host ("  stale: remote digest=" + $o.digest + " local=" + $localHash + " -> replace")
    }
    Write-Host "  del existing asset id=$($o.id) ..."
    Invoke-RestMethod -Uri "$baseURL/releases/assets/$($o.id)" -Headers $headers -Method Delete | Out-Null
  }}
  Write-Host "Uploading $assetName ($([math]::Round($size/1MB,1)) MB)..."
  $name = [Uri]::EscapeDataString($assetName)
  $uri = "$uploadURL`?name=$name"
  $tmpOut = Join-Path $env:TEMP "poly_curl_$assetName.out"
  $tmpErr = Join-Path $env:TEMP "poly_curl_$assetName.err"
  for ($i=1; $i -le $retries; $i++) {
    if (Test-Path $tmpOut) { Remove-Item $tmpOut -Force -ErrorAction SilentlyContinue }
    if (Test-Path $tmpErr) { Remove-Item $tmpErr -Force -ErrorAction SilentlyContinue }
    $curlArgs = @(
      '-sS','-X','POST',
      '-H', "Authorization: Bearer $token",
      '-H', "Accept: application/vnd.github.com/vnd.github+json",
      '-H', "User-Agent: PolyXRD-upload/2.0",
      '-H', "Content-Type: $contentType",
      '-H', 'Expect:',
      '--data-binary', "@$filePath",
      $uri
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & $curlExe @curlArgs 1> $tmpOut 2> $tmpErr
    $procExit = $LASTEXITCODE
    $sw.Stop()
    if ($procExit -eq 0 -and (Test-Path $tmpOut)) {
      try {
        $up = Get-Content $tmpOut -Raw | ConvertFrom-Json
        if ($up.browser_download_url) {
          $mbps = [math]::Round(($size/1MB)/$sw.Elapsed.TotalSeconds, 2)
          Write-Host ("  OK in $([math]::Round($sw.Elapsed.TotalSeconds,1))s ($mbps MB/s) -> $($up.browser_download_url)")
          return $up
        }
      } catch {
        Write-Host "    retry ${i}: bad JSON response"
      }
    } else {
      $errMsg = if (Test-Path $tmpErr) { (Get-Content $tmpErr -Raw -ErrorAction SilentlyContinue) } else { '' }
      Write-Host ("    retry ${i}/${retries} curl exit=${procExit}: " + ($errMsg -replace "`n",' '))
    }
    Start-Sleep -Seconds (5*[Math]::Min($i,6))
  }
  throw "FAILED upload $assetName after $retries tries"
}

# 小 → 大: SHA256 → Setup → 内部便携包 (先失败先暴露)
Upload-Asset -FilePath (Join-Path $inst "SHA256-v$version.txt")                  -AssetName "SHA256-v$version.txt"                  -ContentType 'text/plain'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-Setup-v$version.exe")           -AssetName "PolyXRD-Setup-v$version.exe"           -ContentType 'application/vnd.microsoft.portable-executable'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Internal-Portable.zip") -AssetName "PolyXRD-v$version-Internal-Portable.zip" -ContentType 'application/zip'

# ---- Final summary + 政策自检 ----
Write-Host "=== FINAL RELEASE INFO ==="
$f = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers
Write-Host "Release : $($f.html_url)"
Write-Host "Tag     : $($f.tag_name) @ $($f.target_commitish)"
Write-Host "Draft   : $($f.draft) / Prerelease: $($f.prerelease)"
foreach ($a in $f.assets) { Write-Host ("  " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url) }

$leaked = @($f.assets | Where-Object { $_.name -match $BANNED })
if ($leaked.Count -gt 0) {
  throw "严重: Release 上出现 PDF2 附件 -> $($leaked.name -join ', ')"
}
Write-Host "政策自检: Release 附件中无 PDF2 OK"
Write-Host "=== DONE ==="
