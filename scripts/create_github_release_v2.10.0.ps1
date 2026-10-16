# PolyXRD v2.10.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v2.10.0.ps1
#
# ★ 本版上传 3 个附件:
#   SHA256-v2.10.0.txt                    (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v2.10.0.exe             正式发布版安装包 —— 带注册机制
#   PolyXRD-v2.10.0-Internal-Portable.zip 内部评估版便携包 —— 无注册机制
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
$tag     = 'v2.10.0'
$version = '2.10.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'D:/Project/XRD/PolyXRD/installer_output/2.10.0'

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
## PolyXRD v2.10.0

发布日期：2026-10-17 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v2.9.0 → v2.10.0，注册机制 + 双版本分发）

自本版起按**两种二进制变体**分发，注册相关的界面与行为由**构建期**决定、运行时不可切换：

| 变体 | 产物 | 注册机制 | 状态栏最右侧 |
|---|---|---|---|
| **正式发布版**（release） | Inno Setup 安装包 | ✅ 每次启动检查注册；未注册弹出版权提示（选「确定」仍可正常使用，选「输入注册码」即刻注册）；帮助菜单提供「输入注册码」 | `未注册` / 注册后显示 **`已注册：<单位部门名称>`** |
| **内部评估版**（internal） | 便携 ZIP | ❌ 完全不含注册界面、不弹任何提示 | 固定显示 **`内部评估版本`** |

**注册机制要点**

- 注册码格式 `PXRD1-XXXX-XXXX-…`，载荷为 `UTF8(单位部门名称) + 0x00 + HMAC-SHA256(…)[:8]`，整体 Base32 编码。
- **纯离线校验**：软件端重新计算 HMAC 即可验真，并**还原出单位部门名称**用于展示 —— 不联网、不需要机器码，同一单位多台电脑通用。
- **防手改**：注册状态以明文 JSON 存于 `%APPDATA%\PolyXRD\Registration\PolyXRD.json`，每次启动都用注册码重新算一遍单位名来兜底，直接改文件伪造「已注册」无效。
- 未注册时的提示文案：`本软件未注册，版权所有，禁止用于商业用途。如需注册请联系 sshztx@outlook.com`。
- 安全级别为**离线混淆级**（密钥随软件分发，可被逆向提取），定位是"告知版权 + 自助注册"而非强反盗版。

**如何获得注册码**：把贵单位/部门名称发至 `sshztx@outlook.com`，收到注册码后在软件里点 **帮助 ▸ 输入注册码…** 粘贴即可。

本版**无检索/精修算法改动**，物相检索基准与 v2.9.0 一致（A 级 top10 36/48 · MRR 0.407；B 级 top20 26/48）。

### 📊 测试与验收

- 全量回归 **1336 passed / 6 skipped**（基线 1284，新增 **51 项**注册机制单元测试，零回退）。
- 变体静态指纹：release 包不含 flavor 模块、internal 包含 —— 无"内部版静默变成正式版"风险。
- 动态行为（外部枚举窗口实测）：release 未注册 → 弹窗出现；写入注册码后重启 → 弹窗消失；internal 在清掉注册状态的前提下启动 → 无弹窗。
- 二进制四轮验收：SHA-256 独立重算一致（Setup `8e4800fd…b73a6`）/ 静默安装 `VERSION.txt=2.10.0` / 启动日志 `MainWindow OK` + `shown visible=True` / 冻结 GUI 冒烟无崩溃日志。

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | **正式发布版** Windows 安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**），带注册机制 |
| PolyXRD-v$version-Internal-Portable.zip | **内部评估版**便携包（解压即用，无注册机制，状态栏显示 `内部评估版本`）；仅供内部自用，请勿对外分发 |
| SHA256-v$version.txt | 上述两个产物的 SHA-256 校验值 |

> **COD 库可挂载之前的版本**：本版未改动任何数据库读取格式，两个 COD 索引库（COD 无机物库 + COD 全库索引）与程序**兼容且未变更** —— 直接沿用 [v2.5.0 Release](https://github.com/PolyXRD/PolyXRD/releases/tag/v2.5.0)（或更早版本）里的同名库包即可。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，本仓库只提供挂载能力，分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装（约 5 分钟，1.2 万个文件解压属正常；安装位置可选）
2. （可选）从 v2.5.0 Release 下载需要的 COD 索引库包并解压
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 对应槽位「导入…」→ 立即生效，无需重启
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
