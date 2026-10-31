# PolyXRD v4.7.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v4.7.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v4.7.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v4.7.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v4.7.0-Portable.zip  便携包 —— 内部评估版变体
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**;
#   数据库包也不在本仓库上传 (政策 2026-10-23) —— $BANNED 同时拦截 'PDF2' 与 'Databases-'。
#   底部有 $BANNED 守卫, 任何含 PDF2 的路径一旦混进来会直接抛错终止。
# ★ 数据库**不在本仓库上传/发布**:
#   本脚本只传程序 3 附件; polyDB 库包统一在独立仓库
#   https://github.com/PolyXRD/PolyXRD-DataBase 的 Releases 分发。
#   PDF2 守卫仍对任何误加附件生效。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'D:/Project/XRD/PolyXRD'

# git.exe 定位 (v4.5.0 起): 不硬编码某个 PortableGit 版本目录, 按候选列表探测,
# 并把 `git` 自身能否解析也算命中, 避免 PortableGit 升级后失效。
$gitCandidates = @(
  'C:\Users\Administrator\.workbuddy\binaries\PortableGit\current\mingw64\bin',
  'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.3.0\mingw64\bin',
  'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin',
  'C:\Program Files\Git\cmd'
)
$gitBin = $gitCandidates | Where-Object { Test-Path (Join-Path $_ 'git.exe') } | Select-Object -First 1
if (-not $gitBin) {
  $g = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
  if ($g) { $gitBin = Split-Path $g -Parent }
}
if ($gitBin) { $env:PATH = "$gitBin;$env:PATH"; Write-Host "git found at $gitBin" }
else { throw 'git.exe 未找到: 无法读取凭据' }

$owner   = 'PolyXRD'
$repo    = 'PolyXRD'
$tag     = 'v4.7.0'
$version = '4.7.0'
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
$body = @'
## PolyXRD v4.7.0

发布日期：2026-10-31 ｜ 联系：sshztx@outlook.com

本版把 **v4.6.0（外挂库多库挂载）** 与 **v4.7.0（序贯多相鉴定）** 合并发布 ——
两个版本此前只提交了代码、没有单独出包。核心是一条交互逻辑的重写：

> **以前**：一次检索给出一个排名列表，用户自己记住"我已经确认了哪几相"。
> **现在**：确认一相 → 该相已解释的峰从问题里移除 → 对剩下的峰再检索 → 用户再确认。

外挂库侧同步修掉两个"选了却不是它"的 bug —— 之前工具栏「识别」静默跑内置 118 相库，
残差追查写死 `builtin`，用户在下拉里选的库根本没被用上。

### 一、序贯多相鉴定：确认一相 → 剩余峰再检索 → 再确认

**交互**

- 候选列表选中一行 → 点「**确认并继续检索**」或**直接双击该行**
- 该相在谱图叠加里**保持勾选**（不会被下一轮残差检索打回原形）
- 自动对剩余未解释峰再检索 → 给出下一相候选，已确认相自动从候选里剔除
- 状态条实时显示：`已确认 2 相 ｜ 剩余 12/25 峰 ｜ 已解释 84.3% 强度`
- 「**撤销上一相**」弹掉最后一相并按归还后的剩余峰重检索（撤到 0 相回到整谱检索）

**判定口径**（`services/sequential.py`，GUI 无关）

- **强度残差账本**：保存**原始**实测峰表（永不修改），按确认顺序逐层重算
  - 逐相峰配对：容差内按 |Δ2θ| 贪心一对一，避免叠峰被重复计权
  - count 空间最小二乘比例因子 `scale = Σ(I_res·r)/Σ(r²)`，`r = I_ref/I_ref,max`
  - 逐峰残差 `I_obs − Σ scale·r`
- **"已解释"判据**：残差降到**自身强度** 5% 以下（带 `0.2% × 最强峰` 绝对下限）。
  只解释了一部分的峰**带着剩余强度进入下一轮** —— 重叠峰是真实物理，不是舍入误差
- **低强度截断**：弱于最强峰 1% 的线既不参与检索也不计入覆盖率分母，
  否则两相确认完之后几十个噪声峰仍会"剩下"，第三轮去匹配噪声
- **状态是纯函数**：`(原始峰, 相序列)` 决定一切；撤销 = pop + 整层重算，不残留增量状态
- **判重**：`db_id` 优先，其次 `(name, formula, space_group)`
- **不换库**：数据源全程透传，首轮用外挂库则后续轮次同库，绝不退回内置库

**增量提示**：第 2 相起，若某相新增覆盖率 `< 1%`，状态栏提示"几乎未解释新峰，
可能是重复条目或假相，可撤销" —— 残差是减法，不会自我校验，这条提示是唯一的兜底。

**与旧「仅对未解释峰再搜索」的关系**：旧右键动作**保留**（向后兼容），它按
`assign_peaks` 的**峰位归属**判定残余，不做强度扣减、不维护相序列。新路径是它的严格加强版。

### 二、外挂数据库：不限数量、多种类型、选中即用于检索

- **挂载类型注册表化**：内置 polyDB / PDF2 / 用户库降级为"种子类型"，新格式通过
  `register_kind()` 接入后，判别 / 探测 / 列表展示 / 检索分发全部自动接上 —— **不再需要改源码里的 if/elif**
- **不限数量**：同一类型可挂任意多份（内置盘 + 移动硬盘 + 自裁子集 + 同事导出的库），
  列表 / 下拉 / 持久化都没有上限；一次挂 60 份库的多库压力测试通过
- **polyDB 元数据 + 重命名**：管理对话框显示数据集 / 变体 / 格式版本 / 构建日期；
  用户自加库可重命名；内置项名字由类型 / 变体决定，不允许改
- **选中即用于全部入口**：传统检索、快速识别、标记峰再匹配、残差峰再检索、Profile Fitting、
  工具栏 / 菜单「识别」、精修向导「检索库」与 MCP 全部跟随当前数据源
- **外挂库的 Profile Fitting**：先按该库 d-I 预筛 200 个候选，再做全谱拟合重排
  （52 万相逐相穷举不可行）
- **修掉两个"选了却不是它"的 bug**：工具栏「识别」此前忽略数据源下拉、静默跑内置 118 相库；
  残差追查此前写死 `builtin`
- **库损坏不再静默**：路径存在但库损坏时报"所选数据库无法用于检索"，不再返回空候选

### 三、测试与质量

- 全量回归 **1904 passed / 5 skipped / 0 failed**
- `ruff check src/ --select F821,F601,RUF012` 全绿
- 新增 `tests/test_sequential_phase.py` **22 例**（账本 / 状态机 / VM / 视图四层）：
  两相链式解释、部分解释保留残差、低强度忽略、容差边界、幂等、撤销回到上一状态、
  中间相移除后重算、`db_id` 判重、VM 只把残差峰交给引擎 / 剔除已确认相 / 撤到 0 相回到整谱、
  视图状态条与"序贯中刷新候选不清勾选"
- 真实试样冒烟（`test_xrd/xy/3-1.xy`）：Zincite 82.6% → 剩余 15/25 峰 → Hornblende +1.6%
  → 撤销精确回退到 1 相 / 82.6%
- 多库冒烟：3 份真实 polyDB 挂载 → 选中 → 传统检索 / Profile Fitting → MCP 选库

### 四、已知边界

- **单参考线的相会"吞掉"叠峰**：比例因子在单峰上按最小二乘必然能拟合到该峰全高，
  于是叠峰被第一相完全解释、第二相在那里再配不上。这是参考实现的同一算法特性
  （真实数据里 scale 由多条线共同约束，很少触发）；需要时用「撤销上一相」换相，
  或改用峰位口径的旧动作
- **序贯进度不写进项目文件**：`.pxrd` 只存 `selected_phases` 与最近候选，
  重新打开后从整谱检索重新开始
- **整谱检索 / 标记峰检索 / Profile Fitting 会重置账本**：换了峰集合或候选口径，
  旧的已确认相不再可比 —— 有意为之，状态条会立即归零
- ⚠️ **仍有一个未闭环的启动期问题**：个别机器上 `window.show()` 会**间歇性**原生崩溃
  （splash 之后没有主窗口，日志里是 access violation）。本版未涉及该路径；排查记录见仓库
  `docs/待办清单.md` 的 P0-1。若你遇到，请把 `%USERPROFILE%\.polyxrd\logs` 整个目录反馈过来

### 📦 附件（3 个）

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v4.7.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.7.0-Portable.zip` | 便携包 = **内部评估版**，内置 COD-Inorg |
| `SHA256-v4.7.0.txt` | 以上两个程序产物的 SHA-256 |

> 数据库不在本仓库 / 本 Release 发布；扩展库见
> [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases)。
> PDF2-2004 为 ICDD 版权库，**永不**随包 / 随 Release 分发。

### 🔧 升级提示

- 从 v4.5.0 覆盖安装 / 解压即可，配置无需迁移；已挂载的外挂库（`db_mounts.json`）保持有效
- 同一份 polyDB 挂多份也可以（用于对比不同构建日期的库），列表不会去重误删
- 序贯多相鉴定对**单相样品**的体验与旧版一致：确认唯一一相后状态条直接显示"无剩余待解释峰"
'@

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
