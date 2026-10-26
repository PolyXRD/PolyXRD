# PolyXRD v4.3.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v4.3.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v4.3.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v4.3.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v4.3.0-Portable.zip  正式发布版便携包 —— 解压即用
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**;
#   数据库包也不在本仓库上传 (v4.3.0 政策) —— $BANNED 同时拦截 'PDF2' 与 'Databases-'。
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
$tag     = 'v4.3.0'
$version = '4.3.0'
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
## PolyXRD v4.3.0

发布日期：2026-10-27 ｜ 联系：sshztx@outlook.com

### polyDB d 峰检索回到 MCP（v4.2.1 遗留项）

UI 侧的物相识别自 v4.0.0 起就用 polyDB d 峰检索；本版把 MCP 工具面补齐。

#### 新增 MCP 工具 `search_phases_by_d_peaks`

按实测 d 值 / 强度做 Hanawalt 检索，底层为 polyDB 位图倒排预筛 + 精确打分：

- 参数：`d_values, intensities, tolerance, tolerance_rel, min_match, limit,
  elements, max_ref_peaks, main_peak_topk`
- 与 UI 物相识别、PDF2 / 用户库共用 `phase_search` 打分口径
- `elements=["Si","O"]` 走 polyDB 元素位图白名单
- 返回 `mounted / n_results / matches / query`，match 含 `cod_id`、`display_id`、
  `ref_id`、`formula`、`mineral_name`、`space_group`、`n_peaks` 与全部 Hanawalt 统计

#### 旧名 `search_cod_by_d_peaks` 恢复功能

保留旧签名 `(d_values, intensities, tolerance, min_match, limit)`，内部转调 polyDB；
不再返回 `deprecated`。旧 MCP 客户端无需改动。

#### 健壮性

无 polyDB → `mounted:false` + 提示；布局损坏 → `mounted:true` + `error`；
非法 d 值/强度长度不一致/未知元素/非法选项 → JSON 错误，不抛异常。

#### 兼容性与范围

- 纯 MCP/服务层新增能力；UI 与精修算法无行为改动。
- 在线 COD d 峰检索不支持（COD 官方无接口），在线结构检索继续用 `search_cod_online`。

### 📦 附件（3 个）

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v4.3.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.3.0-Portable.zip` | 便携包 = **内部评估版**，内置 COD-Inorg |
| `SHA256-v4.3.0.txt` | 以上两个程序产物的 SHA-256 |

> 数据库不在本仓库/本 Release 发布；扩展库见
> [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases)。
> PDF2-2004 为 ICDD 版权库，永不随包/随 Release 分发。

### 🔧 升级提示

从 v4.2.1 覆盖安装/解压即可，配置无需迁移；MCP 旧工具名继续可用。
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
$BANNED = 'PDF2|Databases-'
function Assert-NotBanned([string]$s) {
  if ($s -match $BANNED) {
    throw "拒绝上传: '$s' 命中禁用关键字 '$BANNED' —— PDF2 受版权保护; 数据库包自 v4.3.0 起不在本仓库发布。"
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
Write-Host "政策自检: Release 附件中无 PDF2 / 数据库包 OK"
Write-Host "=== DONE ==="
