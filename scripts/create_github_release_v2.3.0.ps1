# PolyXRD v2.3.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v2.3.0.ps1
#
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**。
#   本脚本只上传 4 个附件: Setup.exe / Portable.zip / COD-inorg-index.zip / COD-full-index.zip。
#   底部有 $BANNED 守卫, 任何含 PDF2 的路径一旦混进来会直接抛错终止。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'D:/Project/XRD/PolyXRD'

# PortableGit on PATH (pwsh 7 环境默认没有 git; GCM 内部也要定位 git.exe)
$gitBin = 'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin'
if (Test-Path $gitBin) { $env:PATH = "$gitBin;$env:PATH" }

$owner   = 'PolyXRD'
$repo    = 'PolyXRD'
$tag     = 'v2.3.0'
$version = '2.3.0'
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
## PolyXRD v2.3.0

发布日期：2026-09-30 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v2.1.0 → v2.3.0，物相检索/组合精度大版本）

- **检索排序 FoM 链改进**（S08–S12）：强度加权 FoM + 高斯陡峭核 + 强漏检 ×2 罚分；
  S14c 可观测性下限默认启用（运动学弱线 I_ref/Imax<0.1 不计漏检）
- **组合选择覆盖毯坍缩**（S14b）：新增强度加权自解释率，密集弱线相
  "少量弱线沾强观测峰、主线全落空"的覆盖毯形态被重罚；
  覆盖向量引入 s* 尺度一致性因子
- **内建库 0.5.2 → 0.5.3**：修复 4 个坏条目
  Cristobalite（β 型错挂 → α 相主线 21.99°）/ NCM 811（坏超胞 400 幻影线 → 层状 R-3m 19 条）/
  Boehmite（引用 CIF 本身是错相 → γ-AlOOH）/ Albite（错误晶胞 → P-1 low-albite）
- **13 试样基准实证**（S19 全量复跑，详见 docs/基准报告-物相检索与精修-v2.3.md）：

| 指标 | v2.3.0 前 | v2.3.0 |
|---|---|---|
| 检索 B 级 top10 | 73% | **86%**（MISS 8→4） |
| 检索 A 级 top10 / MISS | 92% / 0 | 92% / 0（零回归） |
| 组合相级命中 | 59.2% | **85.7%** |
| 组合试样级完全命中 | 3/13 | **8/13** |
| 精修 7-1 wR / 耗时 | 40.81% / 772 s | **38.47% / 342 s** |

- **版本号单源化**：config / mcp_server 版本改由包 `__version__` 取值
- 结构回填 100%（49/49）；全链路 13 试样路线验收零崩溃

### 📦 Release 附件

| 文件名 | 大小 | 说明 |
|---|---|---|
| PolyXRD-Setup-v$version.exe | 241.1 MB | Windows 独立安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**） |
| PolyXRD-v$version-Portable.zip | 368.9 MB | 免安装便携包（解压即用，**不含任何数据库**） |
| PolyXRD-v$version-Databases-COD-inorg-index.zip | 134.1 MB | COD 无机物精简索引库（主检索库，推荐） |
| PolyXRD-v$version-Databases-COD-full-index.zip | 205.9 MB | COD 全库索引库 |

> **PDF2-2004 不在附件中**：ICDD 版权数据库，仓库只提供挂载能力，分发包由用户依授权自行准备。
> SHA-256 校验值见仓库 `installer_output/SHA256-v2.3.0.txt`（Release 工作流同步核对）。

### 🚀 快速开始

1. 下载 Setup 安装（或 Portable 解压即用）
2. 下载数据库包并解压到磁盘任意目录
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 对应槽位「导入…」→ 立即生效

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
    # v2.3.0 修正: 用调用运算符直接传参 (pwsh 7 原生引号处理正确);
    # 旧 Start-Process -ArgumentList 不给含空格参数加引号 -> "Could not resolve host: Bearer"
    $curlArgs = @(
      '-sS','-X','POST',
      '-H', "Authorization: Bearer $token",
      '-H', "Accept: application/vnd.github+json",
      '-H', "User-Agent: PolyXRD-upload/2.0",
      '-H', "Content-Type: $contentType",
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

# 小→大, 先失败先暴露
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Databases-COD-inorg-index.zip") -AssetName "PolyXRD-v$version-Databases-COD-inorg-index.zip" -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Databases-COD-full-index.zip")  -AssetName "PolyXRD-v$version-Databases-COD-full-index.zip"  -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-Setup-v$version.exe")                     -AssetName "PolyXRD-Setup-v$version.exe"                     -ContentType 'application/vnd.microsoft.portable-executable'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-v$version-Portable.zip")                  -AssetName "PolyXRD-v$version-Portable.zip"                  -ContentType 'application/zip'

# ---- Final summary + 政策自检 ----
Write-Host "=== FINAL RELEASE INFO ==="
$f = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers
Write-Host "Release : $($f.html_url)"
Write-Host "Tag     : $($f.tag_name) @ $($f.target_commitish)"
foreach ($a in $f.assets) { Write-Host ("  " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url) }

$leaked = @($f.assets | Where-Object { $_.name -match $BANNED })
if ($leaked.Count -gt 0) {
  throw "严重: Release 上出现 PDF2 附件 -> $($leaked.name -join ', ')"
}
Write-Host "政策自检: Release 附件中无 PDF2 OK"
Write-Host "=== DONE ==="
