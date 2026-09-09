# PolyXRD v0.9.10 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: pwsh -NoProfile -File scripts/create_github_release_v0.9.10.ps1
param()
$ErrorActionPreference = 'Stop'
Set-Location 'E:\TEMP\PolyXRD'

# PortableGit on PATH (pwsh 7 环境默认没有 git; GCM 内部也要定位 git.exe)
$gitBin = 'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin'
$env:PATH = "$gitBin;$env:PATH"

$owner = 'PolyXRD'
$repo  = 'PolyXRD'
$tag   = 'v0.9.10'
$baseURL = "https://api.github.com/repos/$owner/$repo"

# ---- Token: 优先从临时文件读 (由外部 GCM 预取), 否则 git credential fill ----
$tokenFile = 'E:\TEMP\PolyXRD\.gcm_out_tmp'
$token = $null
if (Test-Path $tokenFile) {
  foreach ($line in Get-Content $tokenFile) {
    if ($line -match '^password=(.+)$') { $token = $Matches[1].Trim(); break }
  }
}
if (-not $token) {
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
}
Write-Host "token acquired (len=$($token.Length))"

$headers = @{
  'Authorization'        = "Bearer $token"
  'Accept'               = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent'           = 'PolyXRD-release-script/1.0'
}

# ---- Release notes ----
$body = @"
## PolyXRD v0.9.10

发布日期：2026-09-09 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v0.9.8 → v0.9.10）

- **品牌化应用图标修复**（0.9.10 重点）
  - 旧版本图标为纯黑占位方块；本版基于品牌资产重新设计：
    圆角方形 + 深蓝对角渐变 (#0F172A → #0284C7) + 白色晶胞六边形与 XRD 衍射曲线
  - 多分辨率 ICO（16/24/32/48/64/128/256 七档）+ 512×512 @2x PNG
  - 桌面快捷方式 / 任务栏 / 窗口标题栏 / EXE 文件属性全部生效
- **数据文件菜单：开新自动清 + 显式清除**（0.9.9）
  - 打开新数据自动清空旧峰/物相/精修结果，不再残留叠加
  - 文件菜单新增「清除数据」显式入口（带确认对话框）
- **高精度寻峰引擎重设计**（0.9.9）
  - 自适应背景扣除（局部极小值基线）→ 分区自适应噪声 σ (MAD)
  - 亚步长峰位（抛物线/质心内插）→ 重叠簇联合 pseudo-Voigt 拟合精修
  - 真实 ZnO 试样实测：旧引擎 15 峰（锁 0.02° 网格）→ 新引擎 35 峰亚步长定位，
    正确解析 Kα1/Kα2 双峰（56.56/56.58、62.82/63.00、67.91/68.11、69.05/69.25）
  - 数据处理页/参数面板新增「高精度」开关（默认开启，可回退传统算法）
- **物相分析 v2 展示层**（0.9.8）
  - 多相同图叠加（分相着色，参考 Match! 交互）、未解释残差峰标注
  - 峰归属表：2θ 升序、相色块、点击行主区联动定位
- **双 COD 数据库内置**：安装包与便携版均内置 COD 全库 + COD 无机物库，离线可用
- 单元测试：316/316 通过

### 📦 Release 附件

| 文件名 | 大小 | SHA256 |
|---|---|---|
| PolyXRD-Setup-v0.9.10.exe | 252 MB | 9fd29282 df9be3f3 58cda1e1 dd019ee4 3e133b15 ae408f8b 848629b5 4b92e5d6 |
| PolyXRD-v0.9.10-Portable.zip | 661 MB | 1fbb8538 a533ecc6 4bfbd4dc 919906a8 433c4d84 8e59e938 5e5270cc 592cc5f5 |
| PolyXRD_COD_Inorganics_v0.9.10.zip | 94 MB | e37e8736 35505303 9f2c07be d14085b7 622b07d4 a2eaf274 4535b04b 8d659b97 |
| PolyXRD_COD_Full_v0.9.10.zip | 206 MB | 7c1c6073 44480dc6 1f5e5446 06803eeb d8e2307e 5f1f5f32 18aab822 6f58c71e |

- **Setup / Portable**：均已内置双 COD 库，开箱即用
- **COD 无机物库 / COD 全库外挂包**：供独立分发或手动挂载（老版本 PolyXRD ≥0.9.0 亦可用）

### ⚠️ 兼容性

| PolyXRD | COD 无机物库外挂包 | COD 全库外挂包 |
|---|---|---|
| 0.9.10（含 0.9.0+） | PolyXRD_COD_Inorganics_v0.9.10 | PolyXRD_COD_Full_v0.9.10 |
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
    name                   = "PolyXRD v0.9.10"
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

# ---- If release existed, update body to latest notes ----
try {
  $patch = @{ body = $body; name = "PolyXRD v0.9.10" } | ConvertTo-Json
  Invoke-RestMethod -Uri "$baseURL/releases/$releaseId" -Headers $headers -Method Patch -Body ([System.Text.Encoding]::UTF8.GetBytes($patch)) -ContentType 'application/json' | Out-Null
  Write-Host "release body refreshed"
} catch { Write-Host "WARN: body patch failed: $($_.Exception.Message)" }

# ---- Upload assets (smallest first, retry w/ backoff) ----
Add-Type -AssemblyName System.Net.Http
$hch = New-Object System.Net.Http.SocketsHttpHandler
$hch.PooledConnectionLifetime = [TimeSpan]::FromMinutes(10)
$hch.MaxConnectionsPerServer = 4
$client = New-Object System.Net.Http.HttpClient($hch)
$client.Timeout = [TimeSpan]::FromMinutes(60)
$client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $token)
$client.DefaultRequestHeaders.Add('User-Agent','PolyXRD-upload/1.0')

$existingAssets = @()
try { $existingAssets = Invoke-RestMethod -Uri "$baseURL/releases/$releaseId/assets" -Headers $headers } catch {}

function Upload-Asset([string]$filePath, [string]$assetName, [string]$contentType, [int]$retries = 6) {
  # 幂等: 已存在同名且同大小的 uploaded 资产 → 跳过
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
  for ($i=1; $i -le $retries; $i++) {
    try {
      $sw = [System.Diagnostics.Stopwatch]::StartNew()
      $fs = [System.IO.File]::OpenRead($filePath)
      try {
        $content = New-Object System.Net.Http.StreamContent($fs)
        $content.Headers.ContentType = New-Object System.Net.Http.Headers.MediaTypeHeaderValue($contentType)
        $content.Headers.ContentLength = $size
        $resp = $client.PostAsync($uri, $content).Result
        $respBody = $resp.Content.ReadAsStringAsync().Result
        if (-not $resp.IsSuccessStatusCode) {
          Write-Host ("  retry $i/$retries HTTP $($resp.StatusCode): " + $respBody.Substring(0, [Math]::Min(300,$respBody.Length)))
          $resp.Dispose(); Start-Sleep -Seconds (5*[Math]::Min($i,6)); continue
        }
        $resp.Dispose()
        $up = $respBody | ConvertFrom-Json
        $sw.Stop()
        $mbps = [math]::Round(($size/1MB)/$sw.Elapsed.TotalSeconds, 2)
        Write-Host ("  OK in $([math]::Round($sw.Elapsed.TotalSeconds,1))s ($mbps MB/s) -> $($up.browser_download_url)")
        return $up
      } finally { $fs.Dispose() }
    } catch {
      Write-Host ("  retry $i/$retries ERR: " + $_.Exception.Message)
      Start-Sleep -Seconds (6*[Math]::Min($i,6))
    }
  }
  throw "FAILED upload $assetName after $retries tries"
}

$rel = 'E:\TEMP\PolyXRD\release_staging'
$inst = 'E:\TEMP\PolyXRD\installer_output'

Upload-Asset -FilePath (Join-Path $rel  'PolyXRD_COD_Inorganics_v0.9.10.zip') -AssetName 'PolyXRD_COD_Inorganics_v0.9.10.zip' -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $rel  'PolyXRD_COD_Full_v0.9.10.zip')       -AssetName 'PolyXRD_COD_Full_v0.9.10.zip'       -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $inst 'PolyXRD-Setup-v0.9.10.exe')          -AssetName 'PolyXRD-Setup-v0.9.10.exe'          -ContentType 'application/vnd.microsoft.portable-executable'
Upload-Asset -FilePath (Join-Path $inst 'PolyXRD-v0.9.10-Portable.zip')       -AssetName 'PolyXRD-v0.9.10-Portable.zip'       -ContentType 'application/zip'

# ---- Final summary ----
Write-Host "=== FINAL RELEASE INFO ==="
$f = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers
Write-Host "Release : $($f.html_url)"
foreach ($a in $f.assets) { Write-Host ("  " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url) }
Write-Host "=== DONE ==="