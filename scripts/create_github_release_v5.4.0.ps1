# PolyXRD v5.4.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v5.4.0.ps1'
#
# ★ 本版上传 2 个附件 (与历次发布口径一致, 但按 2026-11-10 决策不传 Portable):
#   SHA256-v5.4.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v5.4.0.exe     正式发布版安装包 —— 带注册机制
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**;
#   数据库包也不在本仓库上传 (政策 2026-10-23) —— $BANNED 同时拦截 'PDF2' 与 'Databases-'。
#   底部有 $BANNED 守卫, 任何含 PDF2 的路径一旦混进来会直接抛错终止。
# ★ 数据库**不在本仓库上传/发布**:
#   本脚本只传程序 2 附件; polyDB 库包统一在独立仓库
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
$tag     = 'v5.4.0'
$version = '5.4.0'
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
> 日期：2026-11-11 ｜ 基线：`v5.3.0`（tag `v5.3.0` @ `4bfee5b`）
> 定位：**谱图操作工具行换成彩色图标（参照 XinRefinement 的程序化绘制方案）**
> 联系人：sshztx@outlook.com

---

## 一句话

v5.4.0 是一次**纯 UI 层**的体验升级：把谱图区原来「添加峰 / 重置 / 导出」三个文字按钮，
换成一条**零素材、程序化绘制**的彩色图标工具行，并把 matplotlib 导航条的 8 个默认动作也按
品牌色重新着色。功能口径不变，回归零漂移。

---

## 一、为什么换成彩色图标

此前谱图上方是一排**文字按钮**，在 HiDPI 屏上偏小、和 matplotlib 自带的导航条风格割裂。
本版参照 XinRefinement 的做法，全部改用 **QPainter 在 32×32 设计坐标上程序化绘制** 的
矢量图标，导出多尺寸位图 —— **不依赖任何图片素材**，缩放永远清晰。

## 二、新增谱图操作行（9 个彩色图标）

`views/widgets/plot_toolbar.PlotToolBar`，紧贴谱图上方，5 组用分隔线隔开，模式工具
（框选 / 十字线）单选、可再次点击取消：

| 图标 | 动作 | 实现 |
|---|---|---|
| 复位 | `reset_view`（等效原 home） | `PlotWidget.reset_view` |
| 横向框选 | X 轴区间缩放 | 橡皮筋框选 → `zoom_scale` |
| 纵向框选 | Y 轴区间缩放 | `zoom_scale` + `_scale_y_to_view` |
| 区域框选 | 矩形区域缩放 | `Rectangle2D` 框选 |
| 左移 | 视图向左平移 | `pan_x` |
| 右移 | 视图向右平移 | `pan_x` |
| 放大 | 以光标为中心放大 | `zoom_scale` |
| 缩小 | 以光标为中心缩小 | `zoom_scale` |
| 十字线 | 跟随读数 | 两条 `axhline`/`axvline` + `cursorInfo` |

> 图标绘制：`views/widgets/plot_icons.plot_icon(name, size)`，颜色常量含**青色放大镜**、
> **红色十字线**，与 XinRefinement 源码一致。

## 三、matplotlib 导航条着色

`views/widgets/toolbar_icons.colorize_nav_toolbar(toolbar)`：把 mpl 默认按钮的 SVG
（home / save_figure 等 8 个动作）按品牌色重新着色 + 浅色圆角底衬。QtSvg 或资源缺失时
**静默回退**原图标，不影响功能。

## 四、接线变化

* `home` 图标 → `reset_view`；`save` 图标 → 自定义保存对话框（`_on_export`）。
* 原「添加峰 / 重置 / 导出」三个文字按钮 **移除**，导出入口统一收进导航条 save 图标。
* 模式工具（框选 / 十字线）优先于 matplotlib 的默认鼠标行为。

---

## 五、i18n 与测试

* 三语（zh/en/ja）新增 `vw.plot_widget.tool_*` 共 9 个键 + 3 个导航条/提示键。
* 新增 `tests/test_v54_plot_toolbar.py`（**11 条**）；相关回归 **72 项通过**；`ruff` 门禁全过。
* 全量回归 = v5.3.0 基线 2717 + 新增 11 = **2728 passed / 4 skipped / 0 failed**（算法口径无变化）。

## 六、附件

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v5.4.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `SHA256-v5.4.0.txt` | 上述安装包的 SHA-256 |

> 按 2026-11-10 决策，**本版不随附 Portable 便携包**（本地 `installer_output/` 仍保留）。
> 数据库不在本仓库 / 本 Release 发布；PDF2-2004 为 ICDD 版权库，**永不**随包 / 随 Release 分发。

## 七、升级提示

* 从 v5.3.0 覆盖安装 / 解压即可，配置无需迁移。
* 谱图操作全部收进彩色图标工具行 + 导航条，旧文字按钮入口已移除；若找不到「导出」，
  请用导航条右侧的保存图标。
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

# 小 → 大: SHA256 → Setup (先失败先暴露). 本版不传 Portable (2026-11-10 决策).
Upload-Asset -FilePath (Join-Path $inst "SHA256-v$version.txt")        -AssetName "SHA256-v$version.txt"        -ContentType 'text/plain'
Upload-Asset -FilePath (Join-Path $inst "PolyXRD-Setup-v$version.exe") -AssetName "PolyXRD-Setup-v$version.exe" -ContentType 'application/vnd.microsoft.portable-executable'

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
