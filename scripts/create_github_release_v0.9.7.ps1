param()
$ErrorActionPreference = 'Stop'
Set-Location 'd:\TEMP\PolyXRD'

$owner     = 'PolyXRD'
$repo      = 'PolyXRD'
$tag       = 'v0.9.7'
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

# ---------------- 2. Body ----------------
$body = @"
## PolyXRD v0.9.7

发布日期：2026-09-07 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（三大 Sprint + GUI 增强 + 打包修复）

- **Sprint 1 识别增强**
  - M05 峰搜索：灵敏度参数、二阶导隐藏肩峰检测、Kα1/Kα2 双峰合并
  - M06 峰管理：手动增删改峰、区域排除、残差峰、相对强度重标定
  - M08 仪器校正：零点偏移、BB 样品位移（反射/透射）、Δ2θ 直方图众数、内标校正
  - M10 搜索匹配：增强 FoM（乘性口径）、三强峰预检、Δ2θ 自适应窗口、峰型匹配
  - M11 多相迭代：识别→残差→再识别，min_round_matches=2 抑制单峰噪声相
  - 修复 3 处算法缺陷：FoM 强度数组未随 2θ 排序、加性强度惩罚抹平区分度（改乘性）、
    同结构判定单向覆盖误判（改双向 ≥70%，曾误删 LiFePO4）
- **Sprint 2 定量**
  - M03 原始处理：SG 平滑、Kα2 Rachinger 剥离（逐点前向递归）、分辨率插值
  - M07 轮廓拟合：Pseudo-Voigt、重叠簇联合最小二乘、Rwp/χ²/R² 优度
  - M13 RIR 半定量：I/Icor 相对定量 + 内标绝对定量
  - M14 Rietveld 增强：March-Dollase 择优取向、DoC 结晶度、内标绝对 wt%
- **Sprint 3 产品化**
  - M01 多格式导入（多列自动列序）、M02 元数据/多谱会话、M04 背景（SNIP/多项式/控制点样条）
  - M12 用户库（pymatgen CIF→参考峰导入）、M16 Scherrer 晶粒尺寸
  - M18 报告导出（SVG/HTML/CSV/CIF）、M19 批处理脚本管线
  - M20 GUI：重置原始数据 (Ctrl+R)、Kα2 剥离真实调用、峰检测 F2
- **打包修复**
  - ICU 加载修复：PySide6 ≥6.7 不再自带 ICU 导致 exe 启动报
    "DLL load failed while importing QtCore"，现已 bundle ICU 运行时
  - Inno 6.7.3 无中文 isl 适配（应用内中/英/日三语言不受影响）
- **版本**：0.9.0 → 0.9.7；全量回归 182 项测试通过

### 📦 Release 附件

| 文件名 | 大小 | SHA256 |
|---|---|---|
| PolyXRD-Setup-v0.9.7.exe | 93.8 MB | DBB4606D D69F0113 4DB87D4F 85B8CA4C 82F4193E 28B7B540 768F6FCF D03074F1 |
| PolyXRD-v0.9.7-Portable.zip | 464.5 MB | CFC46EC2 81DB1346 615BCEA0 9B952470 B020BF43 47688358 3A3A67F4 47BE0597 |
| PolyXRD_COD_Inorganics_v0.9.0.zip | 75.8 MB | （数据库未变更，沿用 v0.9.0 附件） |
| PolyXRD_COD_Full_v0.9.0.zip | 179.2 MB | （数据库未变更，沿用 v0.9.0 附件） |

### ⚠️ 兼容性

| PolyXRD | COD 无机物库外挂包 | COD 全库外挂包 |
|---|---|---|
| 0.9.7 | PolyXRD_COD_Inorganics_v0.9.0 | PolyXRD_COD_Full_v0.9.0 |

数据库结构自 v0.9.0 未变更，直接复用 v0.9.0 的两个数据库附件即可。
"@

# ---------------- 3. Check if release already exists ----------------
$existing = $null
try {
  $existing = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers -Method Get -ErrorAction Stop
  Write-Host "Release ALREADY EXISTS: id=$($existing.id) url=$($existing.html_url)"
} catch {
  Write-Host "Release does not exist yet; creating..."
  $create = @{
    tag_name               = $tag
    target_commitish       = 'main'
    name                   = "PolyXRD v0.9.7"
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
  @{ File = (Join-Path $release_dir 'PolyXRD-Setup-v0.9.7.exe');          Name = 'PolyXRD-Setup-v0.9.7.exe';          CT = 'application/vnd.microsoft.portable-executable' },
  @{ File = (Join-Path $release_dir 'PolyXRD-v0.9.7-Portable.zip');       Name = 'PolyXRD-v0.9.7-Portable.zip';       CT = 'application/zip' }
)
foreach ($a in $assets) {
  $name = [Uri]::EscapeDataString($a.Name)
  # Delete same-named asset if already present (idempotent)
  try {
    $old = Invoke-RestMethod -Uri "$baseURL/releases/$releaseId/assets" -Headers $headers -Method Get -ErrorAction Stop
    foreach ($o in $old) {
      if ($o.name -eq $a.Name) {
        Write-Host "Deleting existing asset: $($o.name)"
        Invoke-RestMethod -Uri "$baseURL/releases/assets/$($o.id)" -Headers $headers -Method Delete | Out-Null
      }
    }
  } catch { }
  Write-Host "Uploading $($a.Name) ..."
  $uri = "$uploadURL?name=$name"
  Invoke-RestMethod -Uri $uri -Headers $headers -Method Post -InFile $a.File -ContentType $a.CT | Out-Null
  Write-Host "  done."
}

Write-Host ""
Write-Host "RELEASE v0.9.7 COMPLETE: $($existing.html_url)"
