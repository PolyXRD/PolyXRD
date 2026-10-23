# PolyXRD v4.0.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v4.0.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v4.0.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v4.0.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v4.0.0-Portable.zip  正式发布版便携包 —— 解压即用
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**。
#   底部有 $BANNED 守卫, 任何含 PDF2 的路径一旦混进来会直接抛错终止。
# ★ 数据库**不在本仓库上传/发布** (政策 2026-10-23):
#   本脚本只传程序 3 附件; 两个 polyDB 库包统一在独立仓库
#   https://github.com/PolyXRD/PolyXRD-DataBase 的 Releases 分发。
#   PDF2 守卫仍对任何误加附件生效。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'D:/Project/XRD/PolyXRD'

# PortableGit on PATH (pwsh 7 环境默认没有 git; GCM 内部也要定位 git.exe)
$gitBin = 'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin'
if (Test-Path $gitBin) { $env:PATH = "$gitBin;$env:PATH" }

$owner   = 'PolyXRD'
$repo    = 'PolyXRD'
$tag     = 'v4.0.0'
$version = '4.0.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'D:/Project/XRD/PolyXRD/installer_output'

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
## PolyXRD v4.0.0

发布日期：2026-10-23 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v3.2.0 → v4.0.0）

本版是**外挂物相库的格式换代**：用自研 `polyDB` 列存格式取代 sqlite 索引库，
并顺手修掉一轮全面代码评估发现的缺陷。

#### 一、polyDB：更小、更快、候选剪枝可证

`.polyDB` = 目录容器（`meta.json` + `index.sqlite` + 列存峰矩阵 + d 分箱位图倒排 +
元素位图 + 原子位点侧车）。只读 mmap、零启动解析，检索链从不写库。

| 指标 | 旧 sqlite 无机库 | polyDB 无机库 | 变化 |
|---|---|---|---|
| 相数 / 体积 | 71,199 / 1,194.5 MB | **77,500 / 89.9 MB** | 体积 13.9× 更小、相数更多 |
| 检索耗时 | 6.3~11 s | **0.5~0.7 s** | 12~14× |
| 全库 52.1 万相检索 | 25 s | **1.9~2.3 s** | ~11× |

- **准确性**：13 个基准试样 × 全库暴力打分逐条比对，`search` 的 top-100 **完全等于**
  无剪枝暴力结果；同时修掉了旧候选剪枝"上界不成立"缺陷（曾使 5-1 试样丢 3 个物相）。
- **列表式多库挂载**：一行 = 一个已挂载库，同类型可挂多份（内置盘 + 移动硬盘、
  自裁子集、同事导出的库），任意文件夹指过去即用；「设为当前」显式决定检索源。

#### 二、全量代码评估修复（1 项 P0 + 8 项 P1 + 一批 P2，全部带回归测试）

- **P0**：CI 静态门禁曾被新增类属性打破（RUF012）→ 已修，门禁全绿。
- **P1**：默认寻峰误跑联合拟合（7001 点/25 峰 **14.2 s → 11 ms**）；
  Savitzky-Golay/median 窗口越界崩溃；moving 平均端点掉 45%；
  显式库路径污染实例导致**切库后静默查错库**；PDF2 覆盖率每次刷新全表聚合
  （0.23 s → 0.014 s）；MAUD 临时目录泄漏；CIF 缓存目录不可写时静默丢结构。
- **P2**：欧式小数被当千位分隔（**10× 静默误差**）、SVG 导出 NaN/退化轴、
  i18n 缺失键、模板名路径穿越、GSAS-II 桥丢弃 stderr、相对容差口径分叉 等。

详见仓库 `docs/代码评估-v4.0.0.md` 与 `docs/CHANGELOG.md` §\[4.0.0]。

### 🧪 测试与验收

- 全量回归 **1567 passed / 6 skipped / 1 failed**（唯一失败为构建机 LibreOffice
  容器环境的 HTML→docx 限制，改动前即失败，非代码回归）；`ruff` 门禁全绿。
- polyDB 剪枝正确性：COD-Inorg 13 试样、COD-Full 3 试样 top-100 与全量暴力**逐条一致**。
- 发布冒烟（离屏）：挂载 → 体检 → 检索（Inorg 0.5~0.7 s / Full 1.9~2.3 s）→
  精修 → 导出 CSV/JSON/TXT → 项目存取，全链路 PASS。

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | **正式发布版** Windows 安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**），带注册机制 |
| PolyXRD-v$version-Portable.zip | **正式发布版**便携包（解压即用，同样不含数据库） |
| SHA256-v$version.txt | 上述产物与两个 polyDB 库包的 SHA-256 校验值 |

> **数据库不在本仓库/本 Release 发布**：两个 polyDB 库包统一在独立仓库
> [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase/releases) 的 Releases 分发
> （当前 tag `20261021`：COD-Inorg 48.1 MB / 77,500 相、COD-Full 710.3 MB / 521,361 相）。
> 解压后在「数据库 ▸ 外挂数据库管理… ▸ 挂载文件夹…」指过去即可，**无需重启**。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，本仓库只提供挂载能力。
> **旧 sqlite 库仍受支持**：v4 保留对 COD 无机物 / COD 全库索引 / PDF2 /
> XinMatch 四类旧格式的挂载与检索（`db_import` 兼容路径未改动）。

### 🚀 快速开始

1. 下载 Setup 安装（安装位置可选；如被 SmartScreen 拦，选「更多信息 → 仍要运行」）
2. 按需下载 polyDB 库包并解压到任意目录（必须真正解压到磁盘，不要在压缩包里直接打开）
3. 菜单「数据库 ▸ 外挂数据库管理…」→「挂载文件夹…」指向解压目录 → 选中行「设为当前」
4. 菜单「帮助 ▸ 输入注册码…」完成注册（未注册亦可正常使用，只是每次启动会提示）

> 一个库都不装也能用：程序内置常见参考物相，其余功能不受影响。
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

# 小 → 大: SHA256 → Setup → 便携包 (先失败先暴露)
Upload-Asset -FilePath (Join-Path $inst "SHA256-v$version.txt")           -AssetName "SHA256-v$version.txt"           -ContentType 'text/plain'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-Setup-v$version.exe")    -AssetName "PolyXRD-Setup-v$version.exe"    -ContentType 'application/vnd.microsoft.portable-executable'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Portable.zip") -AssetName "PolyXRD-v$version-Portable.zip" -ContentType 'application/zip'

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
