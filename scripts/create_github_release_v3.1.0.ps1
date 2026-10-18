# PolyXRD v3.1.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v3.1.0.ps1
#
# ★ 本版上传 3 个附件:
#   SHA256-v3.1.0.txt                    (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v3.1.0.exe             正式发布版安装包 —— 带注册机制
#   PolyXRD-v3.1.0-Internal-Portable.zip 内部评估版便携包 —— 无注册机制
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
$tag     = 'v3.1.0'
$version = '3.1.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$inst    = 'D:/Project/XRD/PolyXRD/installer_output/3.1.0'

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
## PolyXRD v3.1.0

发布日期：2026-10-18 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v3.0.0 → v3.1.0）

#### 一、XinMatch 格式数据库支持（新增）

Data source 下拉新增第 7 项「XinMatch 格式库」：可直接挂载第三方
`entries` / `peaks` / `elements` / `element_combo` 四表结构的库文件，**无需转换**。
实测库：`cod_inorganics.db`（745.6 MB，71,206 条目 / 6,214,072 条峰）、
`cod_full.db`（112,734 条目 / 10,979,059 条峰）、`cod_full_curated.db`（94,553 条目）。

- 新增 `services/xinmatch_db.py` 只读适配器：`probe()` 判别 + `XinMatchDatabase`
  （`is_ready` / `stats` / `entry_peaks` / `get_phase` / `search_by_d_peaks`）。
- 新增 `PhaseIdentifier.identify_with_xinmatch`，候选走**同一个** `_rank_candidates`
  FoM 排序；Hanawalt 打分原子（`_match_positions` / `_dedupe_by_tol` /
  `_interval_hit`）直接复用 `cif_database`，不写第二套实现。
- **性能**：没有走"在 `peaks.d` 上做 SQL 区间扫描"这条直觉路 —— 该库 d 轴极密，
  ±0.02 Å 窗口约 2.5 万条峰，20 个测量峰 `UNION ALL + GROUP BY` 实测 **9 s**，
  比现有链路还慢。改为一次性建「每相最强 12 峰」紧凑索引（3.4 MB float32，
  缓存到 `~/.polyxrd/cache/xinmatch_<hash>.npz`，键 = 路径 + size + mtime）：
  建索引 3.2 s，之后**每次检索 0.37~0.57 s**（现有 COD 无机库链路 0.8~5.5 s）。
- **口径一致性**：单测里造同数据的 PolyXRD `phases` 库，两个实现对 14 个度量字段
  逐项比对（`abs=1e-12`）且排序完全一致；真样本 2-1 / 2-2 / 3-1 排名与
  COD 无机库链路逐项相同。
- **能力边界（如实告知）**：该库不含 CIF，条目只有晶胞没有原子坐标 ——
  可检索 / 核对，**不能直接进 Rietveld 精修**；UI 提示与三语文案均已写明。

#### 二、任意位置挂载（新增）

「数据库 ▸ 外挂数据库管理…」新增「**任意位置挂载（推荐）**」分组：
**挂载数据库文件…** / **挂载文件夹…**。

- 库文件放哪个文件夹都行，不必再搬进程序目录；路径持久化到
  `~/.polyxrd/user_db_paths.json`，下次启动自动加载。
- 指到文件夹时自动把该目录下所有合格库**一次全挂上**（只扫本层）；自动跳过
  `.bak` 备份文件（`cod_inorganics.bak-….db` 后缀仍是 `.db`，此前会被误认）；
  同类多份按优先序挑（默认 `cod_inorganics.db`，而不是体积更大的 `cod_full.db`）。
- `DBKind` 新增 `extra_tables` / `preferred_names` 两个判别维度：半成品库
  （有 `entries` 无 `peaks`）拒绝挂载；支持"无默认位置"的槽位（未挂载时显示
  中性「未挂载」而不是红色「未找到」）。

#### 三、全量代码 review 落地（P0 六项 + P1 两项）

按审阅报告逐项改代码，每项都有前后实测：

| 项 | 问题 | 实测改善 |
|---|---|---|
| P0-1 | `_snip_background` 把"像素半窗 w"当成"数值阈值"算 | 峰心背景 898 → **103.8**（真值 100），扣背景后峰高保真 2.2% → **99.5%**；顺带 31.6× 加速 |
| P0-2 | `_gaussian_smooth` 未归一 + 窗长取全长 | 常数谱 100 → 459.21 修为 **100.000** |
| P0-3 | `strip_ka_alpha2` 移位方向反了 + 写死 Cu Kα2 | 卫星峰 520 → **15.2**，主峰 1020 → 1015，无负强度 |
| P0-4 | 4 条检索链只读 `config` 默认波长，不读 `data.wavelength` | 五靶（Cu/Co/Fe/Cr/Mo）**全部 Top-1**（回退旧行为时 Co/Fe/Cr/Mo 连前 5 都进不去） |
| P0-5 | GUI 预处理下拉 `label↔key` 错位 → 9 个入口 100% 抛错 | `currentData()` 取值，离屏冒烟 9/9 被服务层接受 |
| P0-6 | `indexing._index_ab` 四方/六方量纲错 | 7 组参数化用例 Top-1 且 10/10 |
| P1-2 | 精修向导新增「快速档」 | 1.97 s → **0.34 s**（5.8×），wR 完全相同 |
| P1-3 | 谱合成截断未透传 | 75.2 → **20.8 ms**（3.6×） |

> P0-1 ~ P0-6 修的是**会造成错误结果**的缺陷（不是性能问题）：背景扣除算错量级、
> 平滑把常谱抬到 4.6 倍、Kα2 剥离移错方向、非 Cu 靶检索全错、预处理入口全崩、
> 四方/六方晶格参数错。建议升级。

### 🧪 测试与验收

- 全量回归 **1475 passed / 6 skipped / 0 failed**（`CODEBUDDY_SAFE_DELETE_ENABLED=0`）。
- 本轮新增 42 项：`tests/test_xinmatch_db.py` 34 项（探测 / 索引缓存自愈 /
  任意位置挂载 / 配置往返 / **双实现口径逐字段比对**）+ 对话框任意位置挂载 3 项
  + 数据源下拉 4 项 + 上一轮 56 项（波长 17 / 性能档 6 / 预处理 25 / 指标化 8）。
- `ruff check src/` 全绿。
- 二进制四轮验收：SHA-256 独立重算一致 / 静默安装后 `VERSION.txt=3.1.0` /
  启动日志 `MainWindow OK` + `shown visible=True` / 冻结 GUI 冒烟无崩溃日志 /
  两个变体的注册行为与静态指纹逐一对照。

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v$version.exe | **正式发布版** Windows 安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**），带注册机制 |
| PolyXRD-v$version-Internal-Portable.zip | **内部评估版**便携包（解压即用，无注册机制，状态栏显示 `内部评估版本`）；仅供内部自用，请勿对外分发 |
| SHA256-v$version.txt | 上述两个产物的 SHA-256 校验值 |

> **注册机制与 v2.10.0 相同**：正式发布版每次启动检查注册状态，未注册弹出版权提示
> （选「确定」仍可正常使用，选「输入注册码」即刻注册）；注册码纯离线校验、
> 可还原单位名称，同一单位多台电脑通用。索取注册码：`sshztx@outlook.com`。
> **COD 库可直接沿用旧版**：本版未改动任何既有数据库读取格式，两个 COD 索引库
> （COD 无机物库 + COD 全库索引）与程序兼容且未变更 —— 直接沿用
> [v2.5.0 Release](https://github.com/PolyXRD/PolyXRD/releases/tag/v2.5.0)
> （或更早版本）里的同名库包即可。
> **XinMatch 格式库也不在附件中**：第三方库文件请自行准备，本版只提供挂载能力；
> 挂载入口「数据库 ▸ 外挂数据库管理… ▸ 任意位置挂载」。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，本仓库只提供挂载能力，
> 分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装（约 5 分钟，1.2 万个文件解压属正常；安装位置可选）
2. （可选）从 v2.5.0 Release 下载需要的 COD 索引库包并解压
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 用「任意位置挂载」直接指向库文件或所在文件夹
   （也可以按原方式「导入…」到对应槽位）→ 立即生效，无需重启
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
