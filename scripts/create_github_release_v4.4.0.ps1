# PolyXRD v4.4.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v4.4.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v4.4.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v4.4.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v4.4.0-Portable.zip  正式发布版便携包 —— 解压即用
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**;
#   数据库包也不在本仓库上传 (v4.4.0 政策) —— $BANNED 同时拦截 'PDF2' 与 'Databases-'。
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
$tag     = 'v4.4.0'
$version = '4.4.0'
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
## PolyXRD v4.4.0

发布日期：2026-10-27 ｜ 联系：sshztx@outlook.com

### 一、精修向导：重建「从检索库找结构」面板（polyDB 后端）

v4.2.0 下线旧 COD sqlite 运行时后，向导里的结构检索一度整块移除（v4.2.1 删掉了
"输什么都弹不可用"的死 UI）。本版用 **polyDB** 把它重建起来，页签排在第一位：

- **文本查相**：化学式 / 矿物名 / 空间群 / 编号（`TiO2`、`Rutile`、`P 42/m n m`、`1011097`），
  与 MCP 工具共用 `PolyDatabase.search_entries` 口径。
- **按最强峰找**：取当前图谱（限精修 2θ 范围）最强 8 条峰做 Hanawalt d-I 匹配，
  排序键与主界面物相识别完全一致。
- 加入的物相**自带晶胞与原子位点**，可直接进精修；位点经空间群展开成全胞
  （避免高对称相精修假峰），参考峰按 d→2θ 换算并按窗口裁剪。
- 库解析优先级：数据库管理里当前选中的库 > COD 无机库 > COD 全库；未挂载时给明确提示而非报错。
- 无衍射数据时"按最强峰找"置灰；峰检测失败退化为"原始谱图强点"，不会静默无响应。

### 二、旧库配置一次性清理

v4.2.0 之后旧配置会留成"幽灵"：`~/.polyxrd/user_db_paths.json` 里的
`cod_db_path` / `cod_index_db_path` / `cod_svn_path`，以及 `db_mounts.json` 里
`kind` 属于已删除引擎（`cod_inorganics` / `cod_index` / `xinmatch` / `cod_local` /
`cod_full`）的条目
——后者会被挂载列表**静默丢弃**，表现为"我明明加过库，列表里没有"。

启动时若检测到残留，弹一次性提示并提供：

- **清理旧配置**：只删配置项，**绝不删除任何库文件**；旧路径若其实是一份 polyDB 目录，
  顺手重新挂载回去。
- **稍后再说**：按版本记住，不重复打扰（升级后会再问一次）。

### 三、本版同批完成的独立验收整改（15 项）

发布前做了独立验收，报告 `docs/验收报告-v4.4.0.md` 的 24 条结论逐条核实并修复，
其中影响实际使用的：

- **启动不再假死**：旧库路径体积统计改为有上限遍历（3000 条目，超出标"≥"）。
  旧 `cod_svn_path` 可达数十万文件，原实现实测 37,445 条目耗时 2.53 s 且近似线性。
- **位点不再错**：空间群缺失或符号无法识别时，检索库条目**只给晶胞、不给位点**
  （原实现会把 CIF 的非对称单位当全胞用，正是 v4.1.1 假峰 bug 的同款）。真实库
  555/77,500 条（0.72%）命中该分支；加入这类物相时状态行会明确提示。
- **配置不再被写坏**：配置文件改原子写（tmp + 替换），读出失败（损坏/非 UTF-8）
  时绝不回写；悬空/失效的检索源指针一并清理。
- 其余：按峰检索与主界面排序口径对齐（main_peak_topk）、晶胞上限 200→1000 Å
  （COD 实测最长 c=475.98 Å）、NaN/±inf 峰过滤、参考库句柄随窗口关闭释放、
  空结果提示按入口区分、"加入所选物相"未选中时置灰、无密度显示 `--`
  而非"密度 0.000"、清理对话框明细行支持英/日界面（此前固定显示中文）。

### 四、其他

- 三语（简中/英/日）新增 32 个界面文案键（向导检索库 17 + 旧配置清理 15），
  键集 **1058/1058/1058** 完全对齐（v4.3.0 为 1026）。
- 无算法改动：物相检索打分口径、精修引擎、报告生成与 v4.3.0 一致。

### 五、发布后第二轮独立复核（7 项缺陷已修）

发布后又做了一次不采信文档结论的独立复核（逐条回代码与产物重验），挖出并修掉
7 项仍属实的缺陷，其中 3 项是实测复现的真 bug：

- **清理报"已清理"却没落盘**：老版本写下的挂载项可能没有 `id`，旧实现只在 `id`
  非空时登记待删集合，却用"集合非空"判断是否写回 —— 界面报清理成功，配置文件
  原封不动，重启后旧条目还在。
- **纯悬空检索源指针永不被清**：`mounts` 为空、`active` 指向不存在的挂载项时，
  盘点打 0 条、清理返回空，指针一直留着。
- **实测强度混入坏值直接抛异常**：按峰检索对强度列无保护，遇到非数值直接
  `ValueError`；改为逐元素过滤，坏强度**连 d 一起丢弃**（只丢强度会让 d/I 错位，
  进而把主峰判定锚到别的峰上）。
- **位点展开的降级路径**：`expand_sites_by_symmetry` 新增 `strict` 形参 ——
  脏位点 / 病态输入保险丝 / 非有限坐标 / 超上限四条路径不再"原样返回非对称单位"
  （那正是 v4.1.1 假峰事故的同款）。顺带堵住 `float("NaN")` 生成 NaN 假位点的口子。
  真实库随机抽样 400 条：399 正常展开、1 条空空间群、0 条展不开、0 异常。
- **句柄释放**：宿主对话框改为 `closeEvent` + `done` 两条都转发（子控件收不到
  `closeEvent`）；重新解析检索库前先关旧句柄。
- 另修：体积下限为 0 时不再显示 `≥0.0 MB`；参考峰补 `NaN/inf` 过滤。

回归：全量 **1764 passed / 6 skipped / 0 failed**。

### 📦 附件（3 个）

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v4.4.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.4.0-Portable.zip` | 便携包 = **内部评估版**，内置 COD-Inorg |
| `SHA256-v4.4.0.txt` | 以上两个程序产物的 SHA-256 |

> 数据库不在本仓库/本 Release 发布；扩展库见
> [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases)。
> PDF2-2004 为 ICDD 版权库，永不随包/随 Release 分发。

### 🔧 升级提示

从 v4.3.0 覆盖安装/解压即可，配置无需迁移；首次启动若检测到旧库配置残留，
会弹一次清理提示（不清理也不影响使用）。
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
