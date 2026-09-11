# PolyXRD v0.10.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v0.10.0.ps1
#
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**。
#   本脚本只上传 4 个附件: Setup.exe / Portable.zip / COD-inorg.zip / COD-full.zip。
#   底部有 $BANNED 守卫, 任何含 PDF2 的路径一旦混进来会直接抛错终止。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'E:\TEMP\PolyXRD'

# PortableGit on PATH (pwsh 7 环境默认没有 git; GCM 内部也要定位 git.exe)
$gitBin = 'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin'
if (Test-Path $gitBin) { $env:PATH = "$gitBin;$env:PATH" }

$owner   = 'PolyXRD'
$repo    = 'PolyXRD'
$tag     = 'v0.10.0'
$version = '0.10.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'E:\TEMP\PolyXRD\installer_output'

# ---- Token: 优先从临时文件读, 否则 git credential fill ----
$tokenFile = 'E:\TEMP\PolyXRD\.gcm_out_tmp'
$token = $null
if (Test-Path $tokenFile) {
  foreach ($line in Get-Content $tokenFile) {
    if ($line -match '^password=(.+)$') { $token = $Matches[1].Trim(); break }
  }
}
if (-not $token) {
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
}
Write-Host "token acquired (len=$($token.Length))"

$headers = @{
  'Authorization'        = "Bearer $token"
  'Accept'               = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent'           = 'PolyXRD-release-script/1.0'
}

# ---- Release notes ----
$body = @"
## PolyXRD v$version

发布日期：2026-09-11 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v0.9.10 → v0.10.0）

- **数据库彻底外挂化**（0.10.0 重点）
  - 安装包与便携包**不再内置任何数据库**，改为独立下载包，按需取用
  - 便携包体积 661.5 MB → 380 MB（约 −42%）
- **新增 GUI 数据库管理入口** — 菜单「数据库 ▸ 外挂数据库管理…」
  - 槽位独立挂载/卸载，导入后**热生效**，无需重启
  - 导入时校验库类型（COD 无机物与 PDF2 表名同为 phases，靠列签名区分），选错槽位明确提示
- **新增 PDF2-2004 挂载能力** — 163,834 物相，自带空间群（72.8%）与晶胞（81.8%）
  - ⚠️ 该库为 **ICDD 商业数据库，本仓库不分发、Release 不提供下载**；
    持正版授权用户可自行准备 PDF2_2004.sqlite 并在管理对话框中导入
- **检索质量与速度**（0.9.11）
  - FoM 改**加权互斥匹配**：参考峰与实验峰一一对应（避免密集相被高估）+ 强峰加权 + 特异性项 + 强度余弦
  - COD 候选排序重做 0.3 × Hanawalt 复合 + 0.7 × (1 − FoM)
    基准 Top-1 12%→14% / Top-5 22%→25% / Top-10 24%→27%
  - 新增预截断强峰列，COD 检索耗时 **22.5 s → 8.8 s**
  - 元素过滤四语义定稿：必有 / 含有 / 可能 / 没有
- **界面修复**
  - 主工具栏布局修复（此前窗口变窄保存状态后，快捷按钮会被挤进 » 溢出区）
  - 物相分析棒区改为**逐行相标**（颜色与卡片一致、行高一致），未解释残差峰单独标注
  - matplotlib 图内中文字体自动选择（不再出现方框 tofu）
  - 长耗时操作（寻峰/拟合/检索/精修）新增忙碌提示与防重入
- 单元测试 **545 项全部通过**

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | Windows 独立安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**） |
| PolyXRD-v$version-Portable.zip | 免安装便携包（解压即用，**不含任何数据库**） |
| PolyXRD-v$version-Databases-COD-inorg.zip | COD 无机物库外挂包（71,199 物相，主检索库，推荐） |
| PolyXRD-v$version-Databases-COD-full.zip | COD 全库索引外挂包（113,223 条目） |

> **PDF2-2004 不在附件中**：ICDD 版权数据库，仓库只提供挂载能力，分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 或 Portable，安装/解压后启动
2. 按需下载数据库包，解压到磁盘任意目录
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 对应槽位点「导入…」→ 立即生效

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

# ---- 上传: 用 curl.exe 而不是 .NET HttpClient ----
# curl 优势: Windows 10+ 自带; 不依赖 Add-Type (沙盒里 .NET 反射常被拦);
# 处理大文件流式稳定; --data-binary "@path" 跨平台一致。

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
  # 兜底: C:\Windows\System32\curl.exe
  $fallback = 'C:\Windows\System32\curl.exe'
  if (Test-Path $fallback) { $curlExe = $fallback } else { throw 'curl.exe 不存在; 无法上传附件' }
}

function Upload-Asset([string]$filePath, [string]$assetName, [string]$contentType, [int]$retries = 6) {
  Assert-NotBanned $filePath
  Assert-NotBanned $assetName
  if (-not (Test-Path $filePath)) { throw "附件不存在: $filePath" }
  $fi = Get-Item $filePath
  $size = $fi.Length
  foreach ($o in $existingAssets) { if ($o.name -eq $assetName) {
    if ($o.state -eq 'uploaded' -and $o.size -eq $size) {
      Write-Host "SKIP $assetName (already uploaded, size match)"
      return $o
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
    $args = @(
      '-sS','-X','POST',
      '-H', "Authorization: Bearer $token",
      '-H', "Accept: application/vnd.github+json",
      '-H', "User-Agent: PolyXRD-upload/2.0",
      '-H', "Content-Type: $contentType",
      '--data-binary', "@`"$filePath`"",
      $uri
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $curlExe -ArgumentList $args -NoNewWindow -Wait -PassThru -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
    $sw.Stop()
    if ($proc.ExitCode -eq 0 -and (Test-Path $tmpOut)) {
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
      Write-Host ("    retry ${i}/$retries curl exit=$($proc.ExitCode): " + ($errMsg -replace "`n",' '))
    }
    Start-Sleep -Seconds (5*[Math]::Min($i,6))
  }
  throw "FAILED upload $assetName after $retries tries"
}

# 小→大, 先失败先暴露
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Databases-COD-inorg.zip") -AssetName "PolyXRD-v$version-Databases-COD-inorg.zip" -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Databases-COD-full.zip")  -AssetName "PolyXRD-v$version-Databases-COD-full.zip"  -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-Setup-v$version.exe")               -AssetName "PolyXRD-Setup-v$version.exe"               -ContentType 'application/vnd.microsoft.portable-executable'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Portable.zip")            -AssetName "PolyXRD-v$version-Portable.zip"            -ContentType 'application/zip'

# ---- Final summary + 政策自检 ----
Write-Host "=== FINAL RELEASE INFO ==="
$f = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers
Write-Host "Release : $($f.html_url)"
foreach ($a in $f.assets) { Write-Host ("  " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url) }

$leaked = @($f.assets | Where-Object { $_.name -match $BANNED })
if ($leaked.Count -gt 0) {
  throw "严重: Release 上出现 PDF2 附件 -> $($leaked.name -join ', ')"
}
Write-Host "政策自检: Release 附件中无 PDF2 ✔"
Write-Host "=== DONE ==="
