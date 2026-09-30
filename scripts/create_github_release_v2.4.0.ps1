# PolyXRD v2.4.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v2.4.0.ps1
#
# ★ 本版只上传 2 个附件: Setup.exe + SHA256-v2.4.0.txt
#   理由: 两个 COD 索引库与程序兼容且未变更, 沿用 v2.3.0 Release 的同一份即可;
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
$tag     = 'v2.4.0'
$version = '2.4.0'
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
## PolyXRD v2.4.0

发布日期：2026-09-30 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v2.3.0 → v2.4.0，检索排序链路定稿 + 工程门禁补齐）

本版改动由外部评估提出，经独立复核 + 13 试样扫参标定后定稿
（完整复核记录见仓库 `docs/代码评估与改进-v2.3.0.md` §9）。

- **B-4 PO（择优取向）感知检索评分 — 默认启用**：对极密集峰表相（≥80 条参考峰，
  如 Muscovite 267 / Hornblende 211）在检索阶段做 March-Dollase `r` 网格搜索
  （织构轴 [001]），且仅当 `r≠1.0` 的 FoM 比 `r=1.0` 好 > 10% 时才采用。
  → **回收 B 级 5-2 / 5-2b Muscovite 两个 MISS**。
- **B-3 局部 MAD 噪声幅度下限 — 默认关闭**：按 2θ 局部窗口 MAD×k 过滤噪声峰对
  FoM 特异性项的贡献。13 试样 A/B 标尺复核实测为净负（单独启用仅 B 级 top10 +1、
  MISS 零变化，却退化 7-2 Clinochlore 与 5-1 Cristobalite），故默认关闭；
  代码与参数 `fom_local_mad_k` 保留，供噪声谱按需开启。
- **`rietveld_refiner._hkl_angle`**：六方/三方四指标 (h,k,i,l) 自动截前 3 维，
  修 `(4,)·(3,)` 维度不匹配。

### 🛠 工程与维护性

- **CI ruff 静态门禁落地**：`pyproject` 加 `[tool.ruff.lint] select = ["F821","F601","RUF012"]`，
  CI 新增 `Ruff static gate` 步骤；`RietveldRefiner._MASK_ALL_ON` 加 `ClassVar[dict]`（RUF012）。
- **MCP 工具面冒烟测试**：新增 21 用例覆盖 18 个 MCP 工具的快乐/错误路径，
  工具覆盖率 **11% → 67%**。
- 新增 B-3 单测 10 用例；清理无占位符 f-string；README / README-EN 死链清理。

### 📊 13 试样基准实证

| 指标 | v2.3.0 | v2.4.0 |
|---|---|---|
| 检索 A 级 top10 / MISS | 92% / 0 | **96% / 0** |
| 检索 B 级 MISS / top3 | 4 / 63% | **2 / 67%** |
| 检索 MRR（A / B） | 0.491 / 0.478 | **0.498 / 0.487** |
| 组合相级命中 / 试样级完全命中 | 85.7% / 8 of 13 | 85.7% / 8 of 13 |

核心回归 **415 passed / 6 skipped / 0 failed**；无功能性回退。
残余 B 级 MISS 仅 7-2 Hornblende + Zircon（少峰相 / 择优取向物理极限）。

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | Windows 独立安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**） |
| SHA256-v$version.txt | 上述安装包的 SHA-256 校验值 |

> **本版只发 Setup**：两个 COD 索引库与程序**兼容且未变更**，沿用
> [v2.3.0 Release](https://github.com/PolyXRD/PolyXRD/releases/tag/v2.3.0) 的同一份即可，
> 导入后与本版完全兼容；便携包 Portable 本次不随 Release 分发。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，本仓库只提供挂载能力，分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装
2. （首次使用）从 v2.3.0 Release 下载需要的 COD 索引库包并解压
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
    # 用调用运算符直接传参 (pwsh 7 原生引号处理正确);
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
