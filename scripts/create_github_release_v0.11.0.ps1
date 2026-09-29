# PolyXRD v0.11.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v0.11.0.ps1
#
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**。
#   v0.11.0 用户要求: **Portable.zip 不随 Release 发布** (仅本地自用)。
#   本脚本只上传 3 个附件: Setup.exe / COD-inorg.zip / COD-full.zip。
#   底部有 $BANNED 守卫与上传后自检。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'D:/Project/XRD/PolyXRD'

# PortableGit on PATH (pwsh 7 环境默认没有 git; GCM 内部也要定位 git.exe)
$gitBin = 'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin'
if (Test-Path $gitBin) { $env:PATH = "$gitBin;$env:PATH" }

$owner   = 'PolyXRD'
$repo    = 'PolyXRD'
$tag     = 'v0.11.0'
$version = '0.11.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'D:/Project/XRD/PolyXRD\installer_output'

# ---- Token: 优先从临时文件读, 否则 git credential fill ----
$tokenFile = 'D:/Project/XRD/PolyXRD\.gcm_out_tmp'
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
  'User-Agent'           = 'PolyXRD-release-script/1.1'
}

# ---- Release notes ----
$body = @"
## PolyXRD v$version

发布日期：2026-09-15 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v0.10.0 → v0.11.0）

- **COD 结构精修链路打通**（0.11.0 重点）
  - CIF 覆盖 + 5 级回退：本地目录 → 全库索引 → **无机物库内嵌 CIF** → 原始 tar → COD 在线 REST
  - **COD 无机物库内嵌 CIF**（本次发布的库为 v2 结构）：phases 表新增 cif_gz 列
    （71,199 相全部内嵌 gzip CIF 全文）+ cod_atomic_sites 子集表（31 万行原子位点）
    —— **只挂无机物库一个库即可做 Rietveld 结构精修**，不再强依赖全库索引
  - GSAS-II 引擎端到端：engine=auto 自动选引擎（全相有 CIF 且 GSAS-II 可用 → 真
    Rietveld + wt% 定量），不可用时回退内置引擎并记录原因
  - MAUD3 引擎端到端：xye 去 # 头 / CIF 剥 :H 后缀 / wR 百分号换算 / par 相定量解析回写 wt%+晶胞
- **精修算法**
  - R-A1 统计权重（目标函数与 wR 自洽，opt-in）
  - R-A4 Chebyshev 多项式背景抛光（opt-in）
  - get_phase Level-0 回退：索引外无机库编号从 CIF 重建条目 + 三级原子位点回退
- **两套精修向导并存**（GUI）
  - 快速版：单页参数对话框（原样保留）
  - 分步版：数据 → 物相 → 参数 → 预览 → 执行，含模板管理 / CIF 导入 / COD 在线检索
  - 菜单「结构精修」两项目可选；工具栏按钮点主体=快速版、右侧小箭头=选路径
  - 分步向导自带精修执行，结果自动回灌主窗口精修页
- **引擎下拉统一**：auto / gsas2 / maud / builtin / powerxrd 四处 UI 与状态接口一致
- **安装体验**：run_dev.bat 双击闪退修复（cmd 块内裸括号解析问题）+ 启动图未绑定崩溃修复
- 单元测试 **745+ 项全部通过**

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | Windows 独立安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**） |
| PolyXRD-v$version-Databases-COD-inorg.zip | COD 无机物库外挂包 v2（71,199 物相，**内嵌 CIF 全文 + 原子位点**，主检索库，推荐） |
| PolyXRD-v$version-Databases-COD-full.zip | COD 全库索引外挂包（113,223 条目 + 513 万原子位点） |

> **Portable 免安装包不再随 Release 发布**（本版起改为按需提供）。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，仓库只提供挂载能力，分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装后启动
2. 按需下载数据库包，解压到磁盘任意目录
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 对应槽位点「导入…」→ 立即生效

> 一个库都不装也能用：程序内置 118 种常见参考物相。
> 只装无机物库（v2）即可做日常检索**与 Rietveld 结构精修**；全库索引用于 COD 全库/合并检索。
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

# ---- 上传: 用 curl.exe (Win10+ 自带, 流式稳定) ----
$existingAssets = @()
try { $existingAssets = Invoke-RestMethod -Uri "$baseURL/releases/$releaseId/assets" -Headers $headers } catch {}

# ★ PDF2 守卫 + Portable 守卫
$BANNED = 'PDF2|Portable'
function Assert-NotBanned([string]$s) {
  if ($s -match $BANNED) {
    throw "拒绝上传: '$s' 命中禁用关键字 '$BANNED' (PDF2 受 ICDD 版权保护; Portable 本版不发布)。"
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
      '-H', "User-Agent: PolyXRD-upload/2.1",
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

# ---- Final summary + 政策自检 ----
Write-Host "=== FINAL RELEASE INFO ==="
$f = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers
Write-Host "Release : $($f.html_url)"
foreach ($a in $f.assets) { Write-Host ("  " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url) }

$leaked = @($f.assets | Where-Object { $_.name -match $BANNED })
if ($leaked.Count -gt 0) {
  throw "严重: Release 上出现违禁附件 -> $($leaked.name -join ', ')"
}
Write-Host "政策自检: Release 附件中无 PDF2 / Portable ✔"
Write-Host "=== DONE ==="
