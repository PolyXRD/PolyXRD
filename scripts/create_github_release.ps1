param()
$ErrorActionPreference = 'Stop'
Set-Location 'd:\TEMP\PolyXRD'

$owner     = 'PolyXRD'
$repo      = 'PolyXRD'
$tag       = 'v0.9.0'
$baseURL   = "https://api.github.com/repos/$owner/$repo"
$release_dir = 'd:\TEMP\PolyXRD\release_staging'

# Token from GCM
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
$headers = @{
  'Authorization' = "Bearer $token"
  'Accept'        = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent'    = 'PolyXRD-release-script/1.0'
}

# ---------------- 1. Optional check tag (no fail; if create-release fails GitHub reports error) ----------------
try {
  $r = Invoke-RestMethod -Uri "$baseURL/git/ref/tags/$tag" -Headers $headers -Method Get -ErrorAction Stop
  Write-Host "Tag exists on GitHub: sha=$($r.object.sha)"
} catch {
  Write-Host "WARNING: could not verify tag via git/ref endpoint: $($_.Exception.Message). Will try to create release anyway (GitHub auto-creates annotated tag from pushed commit)."
}

# ---------------- 2. Body ----------------
$body = @"
## PolyXRD v0.9.0

发布日期：2026-08-29 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新

- **版本号**：0.8.21 → 0.9.0（关于页、__init__.py、config.py、pyproject.toml、MCP Server、安装脚本、README 等所有版本号位置同步更新）
- **关于页联系邮箱**：统一更新为 sshztx@outlook.com（zh_CN / en_US / ja_JP 三语言）
- **双 COD 数据库外挂支持**
  - COD 无机物库：71,199 物相（zip 75.8 MB）
  - COD 全库索引：113,223 条 CIF + 5.1M 原子位点 gzip（zip 179.2 MB）
  - 运行时可热切换挂载，两个库同时交付、按需下载
- **识别准确率大幅提升**
  - 物相识别命中率：45.1% → 68.6%（13 个工业试样）
  - 含量定量命中率：9.1% → 31.8%
  - 纯金属干扰抑制：FOM 惩罚 ×1.5 + 组合重排比例 ≤20%
  - 多物相组合策略：must/maybe 自动扩展 exclude、同化学式去重、build_refinement_combination 启发式
- **Rietveld wR 引擎优化**（_refine_builtin v1→v8）
  - bg_method=median 替换 snip（直接降 5-6pt wR）
  - Caglioti U-V-W 2θ 依赖峰宽替换单固定 FWHM
  - 多起点 least_squares → 显式 wR 选优 + ≈135 点稀疏邻域 wR 抛光
  - 验收：4-1 四相样 wR 64.74% < 65%；2-1 ZnO/CaCO₃ 50/50 wR 51.46% < 55%；两次独立精修 Zn 含量差 < 35%
- **交付物**：Inno Setup 脚本 + 7z SFX 自解压安装程序（231.5 MB），自动创建「开始菜单/桌面快捷方式、卸载入口」
- **文档**：新增 handover-20260829.md 转交报告，新增 Thx2OpenSource.md 开源致谢清单，README 重写安装方法章节

### 📦 Release 附件

| 文件名 | 大小 | SHA256 |
|---|---|---|
| PolyXRD-Setup-v0.9.0.exe | 231.5 MB | DDC9AEB9 E9EFF8A5 5B9F5687 A147AD61 8EA892B7 0FB21228 A344375D 904239D5 |
| PolyXRD_COD_Inorganics_v0.9.0.zip | 75.8 MB | 79CF22F6 12A6631D 8D9C6A14 688064D8 21F960D4 B4A3A5A5 B8937CC3 C4EC6A88 |
| PolyXRD_COD_Full_v0.9.0.zip | 179.2 MB | 3C6B5287 02731C1E CD2EBB6E AD41E253 7E9ED589 C717E4D0 ADF848EC F2D8577D |

### ⚠️ 兼容性

| PolyXRD | COD 无机物库外挂包 | COD 全库外挂包 |
|---|---|---|
| 0.9.0 | PolyXRD_COD_Inorganics_v0.9.0 | PolyXRD_COD_Full_v0.9.0 |

单元测试：95/95 通过（含 3 项 wR 专项验收）
"@

# ---------------- 3. Check if release already exists ----------------
$existing = $null
try {
  $existing = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers -Method Get -ErrorAction Stop
  Write-Host "Release ALREADY EXISTS: id=$($existing.id) url=$($existing.html_url)"
} catch {
  # 404: create new
  Write-Host "Release does not exist yet; creating..."
  $create = @{
    tag_name               = $tag
    target_commitish       = 'main'
    name                   = "PolyXRD v0.9.0"
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

# ---------------- 4. Upload assets ----------------
$assets = @(
  @{ File = (Join-Path $release_dir 'PolyXRD_COD_Inorganics_v0.9.0.zip'); Name = 'PolyXRD_COD_Inorganics_v0.9.0.zip'; CT = 'application/zip' },
  @{ File = (Join-Path $release_dir 'PolyXRD_COD_Full_v0.9.0.zip');       Name = 'PolyXRD_COD_Full_v0.9.0.zip';       CT = 'application/zip' },
  @{ File = (Join-Path $release_dir 'PolyXRD-Setup-v0.9.0.exe');          Name = 'PolyXRD-Setup-v0.9.0.exe';          CT = 'application/vnd.microsoft.portable-executable' }
)
foreach ($a in $assets) {
  $name = [Uri]::EscapeDataString($a.Name)
  # Delete same-named asset if already present (idempotent)
  try {
    $old = Invoke-RestMethod -Uri "$baseURL/releases/$releaseId/assets" -Headers $headers -Method Get -ErrorAction Stop
    foreach ($o in $old) {
      if ($o.name -eq $a.Name) {
        Write-Host "  Deleting existing asset '$($a.Name)' id=$($o.id) ..."
        Invoke-RestMethod -Uri "$baseURL/releases/assets/$($o.id)" -Headers $headers -Method Delete -ErrorAction Stop | Out-Null
      }
    }
  } catch {}
  Write-Host "Uploading $($a.Name) ..."
  $fi = Get-Item $a.File
  $size = $fi.Length
  Write-Host ("  size=" + [math]::Round($size/1MB,1) + " MB")
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $bytes = [System.IO.File]::ReadAllBytes($a.File)
  $h2 = $headers.Clone()
  $h2['Content-Type'] = $a.CT
  $h2['Content-Length'] = $size.ToString()
  $up = Invoke-RestMethod -Uri "$($uploadURL)?name=$name&label=$name" -Headers $h2 -Method Post -Body $bytes
  $sw.Stop()
  Write-Host ("  done in " + [math]::Round($sw.Elapsed.TotalSeconds,1) + "s, size_downloaded=" + [math]::Round($up.size/1MB,1) + " MB, url=$($up.browser_download_url)")
}

# ---------------- 5. Refresh release info ----------------
$final = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers -Method Get
Write-Host "=== FINAL RELEASE INFO ==="
Write-Host "id      : $($final.id)"
Write-Host "tag     : $($final.tag_name)"
Write-Host "name    : $($final.name)"
Write-Host "html_url: $($final.html_url)"
Write-Host "assets  :"
foreach ($a in $final.assets) {
  Write-Host ("  - " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url)
}
Write-Host "=== DONE ==="
