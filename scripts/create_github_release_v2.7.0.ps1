# PolyXRD v2.7.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v2.7.0.ps1
#
# ★ 本版只上传 2 个附件: Setup.exe + SHA256-v2.7.0.txt
#   理由: 两个 COD 索引库与程序兼容且未变更, 沿用 v2.6.0 Release 的同一份即可;
#         便携包 Portable 本次不随 Release 分发。
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
$tag     = 'v2.7.0'
$version = '2.7.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'D:/Project/XRD/PolyXRD/installer_output'

# ---- Token: git credential fill (direct pipe; do NOT use [Diagnostics.Process]::Start,
#      it is blocked by the sandbox security policy) ----
$secInput = "protocol=https`nhost=github.com`n`n"
$raw = $secInput | git.exe credential fill
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
## PolyXRD v2.7.0

发布日期：2026-10-07 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v2.6.0 → v2.7.0，物相检索 FoM 判据解耦 + 数据驱动标定）

- **FoM 漏检项解耦（C-1）**：把原 `bad` 拆成「位置偏差 `position_dev`」与「漏检惩罚 `miss_penalty`」
  两个独立分量（`bad = bad_pos + _FOM_MISS_WEIGHT * bad_miss`）。默认权重 = 1.0，
  **数值与 v2.6.0 完全一致、零功能性回退**；同时为新标定留出独立调节旋钮。
- **可观测字段**：`FoMResult` 新增 `position_dev / miss_penalty / spec_penalty`
  三个带默认值字段（向后兼容），单候选 FoM 分解在诊断与消融时如实上报。
- **特异性权重数据驱动标定（核心收益）**：`_FOM_SPEC_WEIGHT` 由 `0.30` 调到 `0.50`
  （13 试样消融最优点）。效果：**检索 B 级 top10 命中 44 → 45/49（92%）**，
  MRR 0.488 → 0.490；A 级与组合相级/试样级**零回退**（组合仍 45/49 · 10/13）。
- **消融仪落地**：新增 `bench_fom_ablation.py`（kwargs + foam 常量双通道打补丁、自动还原）
  与 `diag_recall_breakdown.py`（逐候选 FoM 分解）；把 5 个看起来有戏但被数据否决的假设
  （尺度感知 / min_visible_frac / 漏检权重下调 / PFSM 重排 / pfsm_1.0）全部留档，避免重踩。
- **回归守卫**：新增 `test_fom_v270_criteria.py`（15 用例），覆盖解耦数值等价性、
  权重单调递减、三分项上报、常量提升、锁定的调优值等。
- **全量回归 1272 passed / 6 skipped / 0 failed**（回归期间严格只读不写，杜绝行号错位假失败）。

### 📊 测试与稳健性

- 检索基准（13 试样，top_n=20）：A 级 top10 47/49、MRR 0.499；B 级 top10 **45/49**、MRR 0.490。
- 组合基准（top_n=12）：组合相级 **45/49**、试样级完全 **10/13**（与 v2.6.0 持平）。
- 二进制稳健性验收：SHA-256 重算一致 / 静默安装（VERSION.txt=2.7.0）/
  启动日志 MainWindow OK + shown visible=True / 冻结 GUI 冒烟。
- ⚠️ 诚实说明：3 个失败样本（5-2b Muscovite、7-1 Kaolinite、7-2 Hornblende+Zircon）
  本轮仍未攻破，已记入计划文档，下一步方向＝组合阶段打假阳性 / 与参考峰数无关的置信度项 / 扩样本。

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | Windows 独立安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**） |
| SHA256-v$version.txt | 上述安装包的 SHA-256 校验值 |

> **COD 库可挂载之前的版本**：本版未改动任何数据库读取格式，两个 COD 索引库
> （COD 无机物库 + COD 全库索引）与程序**兼容且未变更** —— 直接沿用
> [v2.6.0 Release](https://github.com/PolyXRD/PolyXRD/releases/tag/v2.6.0)（或更早版本）里的
> 同名库包即可，导入后与本版完全兼容，无需重新下载。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，本仓库只提供挂载能力，分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装（约 5 分钟，1.2 万个文件解压属正常）
2. （可选）从 v2.6.0 Release 下载需要的 COD 索引库包并解压
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 对应槽位「导入…」→ 立即生效，无需重启

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

# 小 → 大: 先上传 SHA256, 再上传 Setup (先失败先暴露)
Upload-Asset -FilePath (Join-Path $inst "SHA256-v$version.txt")       -AssetName "SHA256-v$version.txt"       -ContentType 'text/plain'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-Setup-v$version.exe") -AssetName "PolyXRD-Setup-v$version.exe" -ContentType 'application/vnd.microsoft.portable-executable'

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
