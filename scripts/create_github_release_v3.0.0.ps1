# PolyXRD v3.0.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v3.0.0.ps1
#
# ★ 本版上传 3 个附件:
#   SHA256-v3.0.0.txt                    (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v3.0.0.exe             正式发布版安装包 —— 带注册机制
#   PolyXRD-v3.0.0-Internal-Portable.zip 内部评估版便携包 —— 无注册机制
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
$tag     = 'v3.0.0'
$version = '3.0.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'D:/Project/XRD/PolyXRD/installer_output/3.0.0'

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
## PolyXRD v3.0.0

发布日期：2026-10-17 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v2.10.0 → v3.0.0，新增 WPSM 全谱拟合检索）

本版引入一条**全新的排序判据**：不再只看提取出来的峰位/峰强，而是拿整条观测谱与
候选相的理论谱做一次受限最小二乘拟合，用拟合优度复核排名。

**WPSM = Whole Pattern Search Match（全谱拟合检索）**，算法位于独立服务
`src/polyxrd/services/wpsm.py`，纯算法、不碰 UI：

- **理论谱合成**：d–I 峰表 → pseudo-Voigt 连续谱，含 **Kα1/Kα2 双线**
  （I(α2)/I(α1)=0.5）、**Caglioti 峰宽模型** `H²=U·tan²θ+V·tanθ+W`、逐峰按
  FWHM 倍数截断（12×）向量化累加。
- **受限最小二乘**：一次解出 **10 个参数** —— 强度标度、**零点位移**、
  峰宽 U/V/W（或单一 FWHM）、混合比 η、**二次背景三项**、
  **全局相对晶胞缩放 Δ**（signature ∝ tanθ，故与常数型零点位移**可辨识分离**）。
- **统计判据**：**Poisson 加权** Rwp / Rexp / GOF，`FoM = exp(−Rwp/σ)`，σ=0.25。
- **两阶段工程路径**：既有峰表检索先出 top-100 候选 → 再逐候选全谱精排。

**默认关闭，排序行为零改变**：`_WPSM_WEIGHT = 0.0`。是否开启、与峰表 FoM 的
混合权重都在代码里显式给参（`wpsm_weight` / `wpsm_prescreen` / `wpsm_sigma`），
GUI 不提供开关。默认路径根本不会 import WPSM 模块（有单测强保证）。

### 📊 为什么默认关闭：13 试样实测（B 级，49 个真值相）

| 变体 | top1 | top3 | top10 | MRR | MISS |
|---|---|---|---|---|---|
| 峰表 FoM 基线（v2.10.0 口径） | 13/49 | 33 | 45 | 0.490 | 2 |
| 纯 WPSM（替换排序） | 13/49 | 26 | 42 | 0.454 | 3 |
| rank 域混合 w≈0.45 | 13/49 | 33 | **46** | **0.494** | 2 |

- **零调参即与调了 5 个版本的峰表 FoM 在 top1 上打平（13/49）** —— 全谱信息通道
  确实带来了峰表法没有的信号（峰形、背底、重叠、宽化四类信息）。
- **但深排名输**（top3 26 vs 33）：全局 Rwp 度量的是"整条谱有多少没被解释"，
  因而被**相丰度**主导。实测 3-1：主相 Rwp 37%，而 1.4% 的 Corundum 81.5%、
  0.6% 的 Fluorite 81.8% —— 微量相被结构性埋掉。
- 两个"直觉修正"均被实测否决：只在候选自身峰位局部窗口内计分（更差，
  Corundum 名次 7→76 ）、以及按候选自身局部信号归一（无增益）。丰度偏置是
  **单相全谱拟合**这个范式的边界，不是计分域的 bug。
- **性价比**：混合排序换来 +1/49 top10 与 MRR +0.004，代价约 **45 秒/样本**
  （预筛 100）。对比 v2.7.0 只改一个常数就拿 +1 的做法，不成立 —— 故本版
  **只落基础设施，不接 GUI、不改默认**。

完整评估（含 11 项可迁移性逐项判定、消融原始数据、设计稿↔实现 5 处偏离、
遗留清单）见仓库 `docs/v3.0.0-WPSM-全谱拟合检索评估与落地方案.md`。

### 🧪 测试与验收

- 全量回归 **1377 passed / 6 skipped**（v2.10.0 基线 1336，新增 **41 项** WPSM
  单元测试，零回归）。
- 单测覆盖：判据解析解（`y=[10,40] → Rwp=√0.4`）、FoM 单调性与边界、
  Kα2 强度比严格 0.5 与高角侧向、退化安全（无反射/全零谱/网格越界/求解器异常
  一律返回 `fom=0` 且外抛为空）、参数恢复、排序行为、集成钩子默认关闭。
- 正确性（无噪声合成谱注入已知值）：scale **+0.9%**、H(45°) **−0.5%**、
  shift 0.10→**0.102**、η 0.60→**0.580**、Δ 0.002→**0.00206**，
  Rwp 1.90%、GOF 1.02；Kα2 展开与精修引擎**逐位一致**（maxΔ=0）。
- 收敛性：`max_nfev` 60→1000 结果逐位一致；`cutoff_fwhm=12` 与全窗结果一致但快 3.5×。
- 二进制四轮验收：SHA-256 独立重算一致（Setup `010fb609…f408c9`）/
  静默安装后 `VERSION.txt=3.0.0` / 启动日志 `MainWindow OK` + `shown visible=True` /
  冻结 GUI 冒烟无崩溃日志。

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | **正式发布版** Windows 安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**），带注册机制 |
| PolyXRD-v$version-Internal-Portable.zip | **内部评估版**便携包（解压即用，无注册机制，状态栏显示 `内部评估版本`）；仅供内部自用，请勿对外分发 |
| SHA256-v$version.txt | 上述两个产物的 SHA-256 校验值 |

> **注册机制与 v2.10.0 相同**：正式发布版每次启动检查注册状态，未注册弹出版权提示
> （选「确定」仍可正常使用，选「输入注册码」即刻注册）；注册码纯离线校验、
> 可还原单位名称，同一单位多台电脑通用。索取注册码：`sshztx@outlook.com`。
> **COD 库可直接沿用旧版**：本版未改动任何数据库读取格式，两个 COD 索引库
> （COD 无机物库 + COD 全库索引）与程序兼容且未变更 —— 直接沿用
> [v2.5.0 Release](https://github.com/PolyXRD/PolyXRD/releases/tag/v2.5.0)
> （或更早版本）里的同名库包即可。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，本仓库只提供挂载能力，
> 分发包由用户依授权自行准备。

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
