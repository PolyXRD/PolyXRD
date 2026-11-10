# PolyXRD v5.3.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v5.3.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v5.3.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v5.3.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v5.3.0-Portable.zip  便携包 —— 内部评估版变体
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
$tag     = 'v5.3.0'
$version = '5.3.0'
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
> 日期：2026-11-10 ｜ 基线：`v5.2.0`（tag `v5.2.0` @ `53b9785`）
> 定位：**让 Rwp 全面追上参考实现，并给"这个 wt% 能不能用"一个量化边界**
> 联系人：sshztx@outlook.com

---

## 一句话

v5.2 把"强度对"做完（SR + 微吸收）；v5.3 解决**峰形还剩的那两类不对称**（各向异性
展宽、低角拖尾），同时把多相定量从"给一个点值"改成"**给一个能站得住的区间**"。
7 组 MAUD 对标基准上，Rwp 均值 **11.66% → 10.91%**（参考实现 11.23%），**首次整体反超**。

---

## 一、各向异性展宽（P0-B″，默认开）

真实晶粒不是各向同性的球：片状（黏土、氢氧化物）沿 c 轴薄、针状沿 c 轴长，同一相
不同 (hkl) 的峰宽本来就不同。此前只用一个 Caglioti 展宽（尺寸 + 应变各一个数），
拟合器只能把所有峰"平均"拓开 —— 结果是**主峰偏宽、弱峰偏窄**，残差里那一条条
同向的锯齿就是它。

本版引入球谐形式的各向异性宽度：

```text
FWHM_hkl = FWHM_iso · (1 + c2·P₂(cosφ) + c4·P₄(cosφ))
cosφ = 峰法向与 c* 轴的余弦        （反射表已带 cos_phi_c）
```

* `c2 > 0` → 00l 更宽（沿 c 薄的片状晶粒）；`c2 < 0` → hk0 更宽（针状）；
* 只改**宽度**，峰面积由积分守恒保留，因此**不动定量**；
* 两段式热启动：先各向同性收敛，再放开 P₂/P₄ —— 直接从零开始放开会在 S7 上
  把晶胞和宽度一起带偏（实测 9.14 → 两段式 8.98 那类差别）。

**收益（7 组，`sub=3`、`maxc=20`、stage 6）**

| 试样 | 旧默认 | **出厂默认** | 与参考实现比 |
|---|---:|---:|---|
| S1 | 14.93 | **14.12** | 仍差 |
| S2 | 8.09 | **7.98** | 仍差 |
| S3 | 10.65 | **9.94** | 反超 |
| S4b | 9.38 | **9.21** | 反超 |
| S5b | 12.67 | **11.76** | 反超 |
| S6b | 9.62 | **8.98** | 反超 |
| S7 | 16.24 | **14.36** | 仍差（差距 4.9 → 3.1 pp） |
| **均值** | **11.66** | **10.91** | 参考实现 11.23 → **反超 0.32 pp** |

代价：多相样本约 **2~2.4×** 时间（S6b 222 s → 534 s）。要快就用 `fast` 档（仍不做 aniso）。

## 二、低角拖尾（P0-C，opt-in）

轴向发散与样品透明会在**主峰左侧**留下一块慢衰减的尾巴，它的形状不是"峰更宽"，
split-PV 只能改左右宽度、改不了这种峰心外侧的肩。本版按面积守恒把它拆成两项：

```text
主峰 (1−t)·PV   +   t·洛伦兹（左移 0.25·FWHM，宽 3.2×）
```

实测 5/7 组改善（S6b −0.30、S2 −0.10），但对 S3/S7 轻微变差（+0.04/+0.11）——
所以**保持 opt-in**，参数 `inst.tail`，默认 0 时逐位等于 v5.2 的数。

## 三、定量不再给"假的小数位"（P0-E′）

两个相峰重叠严重时，它们的份额可以**此消彼长而 Rwp 几乎不动** —— 这时报"白云石
32.47%"是表面精度。本版加两条同时成立的判据：

1. 该相最强**独立**线（不压在别人线上的那条）净积分占全谱 **< 15%**；
2. 把该相 wt% 推 10 pp，Rwp 只变 **< 0.2 pp**（即 Δwt/ΔRwp > 50 pp/%）。

命中即报 `PHASE_NEAR_DEGENERATE`，并把该相 wt% 折算成**区间**（界面显示 `[lo, hi]`
并带 tooltip）。区间宽度按"Rwp 摆动 0.2 pp 折算的份额摆动"给，下限 0.5 pp。

## 四、两条新的"结果可信度"护栏

* **`PO_DISABLED_SUSPECT`（P0-J）**：用户关掉择优取向，却有某相的最强线出现
  > 30% 的系统性强度缺口 —— 关择优这个动作本身把定量带偏了，提示里直接点名该相。
* **弱相晶胞冻结（`WEAK_PHASE_CELL_SHARE`）**：含量过低的相晶胞参数不可辨识
  （它的峰全被主相盖住），继续放开只会让胞参跑到物理荒唐值，再通过 `M/V`
  污染 wt%。现按份额阈值冻结晶胞自由度。

## 五、逐相颗粒半径（P0-G）+ 反推半径的诚实边界

微吸收 τ 的自变量是 `(μ_j − μ̄)·R_j`，而混合样各相粒度可差一个量级
（IUCr CPD：刚玉 28 µm vs 锌矿 1.4 µm）。本版：

* **GUI 可按相输入**（`parse_grain_radii`，支持中英文逗号/分号；留空 = 用全局缺省），
  与历史的单一 `grain_radius_um` 完全兼容（全相同值时逐位等价）；
* **"反推等效半径"只做诊断展示**，绝不写回 wt% —— 因为 τ 不进拟合向量，反推是
  病态问题。诊断给三样东西：当前搬动量 `Δwt`、每 µm 的敏感度、以及
  **表内最多能搬多少**（`delta_wt_at_limit_pp`）。
* 表内域约束：Brindley 表只覆盖 `|(μ−μ̄)·R| ≤ 0.5`，越界 τ 被截成常数。
  旧实现二分到 50 µm，会把"常数段上的任意点"当成解（cpd4 的磁铁矿 5.4 µm 就撞表）。
  现在逐相收在 `R ≤ 0.5/|μ−μ̄|`，域内无解就明确说"达不到"。

## 六、四项基准实验（本版一并收口）

| 实验 | 结论 |
|---|---|
| **S1 全分辨率 `sub=1`** | 5751 点 13.988% vs 1917 点 14.125%，**ΔRwp 0.136 pp**；逐相 wt% 最大差 0.24 pp ⇒ 降档采样本组安全 |
| **cpd4 微吸收标定** | 表内均匀半径下界 **20.06 pp**（单一半径无解）；逐相 `[22.8, 5.0, 25.1] µm` → **5.88 pp**，三组均未撞表端点 |
| **S6b 白云石分歧** | 用白云石自身强线（104 窗口内占 86%）反推 **13.1 wt%**；我们的 11.3 在区间内，参考实现的高值需要这些线**高出观测 43%** |
| **P0-1 启动 AV 基线** | 冻结版 40 次启动（保守 20 + 默认 20）**40/40 成功**，均值 3.7 s；AV 在开发机不复现，实验台与判据已交付给目标机 |

> cpd4 那条要读清楚：**5.88 pp 是"3 参数拟合 3 个数"**，证明表内存在可行解，
> 不构成预测能力（同谱标定、同谱验收）。要变成可用标定，需要第二张同体系谱
> 或 SEM / 激光粒度的独立测值。

## 七、质量

| 项 | 结果 |
|---|---|
| 全量回归 | **2717 passed / 4 skipped / 0 failed / 998 s** |
| 新增守护 | 近简并 4 条、各向异性/拖尾 9 条、v5.5 守卫、MAUD 7 组门限 CI、反推半径 9 条 |
| 缓存正确性 | 结构指纹进缓存键、参考库按 `(mtime_ns, size)` 失效、空间群缓存 LRU 上限、hkl 缓存返回副本 |

## 八、已知边界（都要看）

* **Rwp 与定量是两笔账**：aniso 让 Rwp 均值降 0.75 pp，但与参考实现 C 的定量
  MAD 从 3.57 升到 3.84（主要 S4b）。定量真值的权威裁判仍是 IUCr 称量样
  （**1.90 pp**），第三方只是代理基准。
* **速度**：出厂默认（aniso 两段式）对多相样本 2~2.4×；`fast` 档不做 aniso。
* **微吸收的颗粒半径仍必须由用户实测给出**：给错比不给更糟。
* **S5b 氟磷灰石分歧未结**（参考实现 13.33 vs 我们 20.88）。
* **P0-1 启动期 AV 仍未修复**：本版只把"能否定位"做完（`context:` 探针 +
  `first-paint` 里程碑 + `scripts/diagnose_startup_log.py`）。遇到启动崩溃请把
  `%USERPROFILE%\.polyxrd\logs` 整个目录反馈过来。

## 九、附件

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v5.3.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `PolyXRD-v5.3.0-Portable.zip` | 便携包 = 内部评估版，内置 COD-Inorg |
| `SHA256-v5.3.0.txt` | 以上两个制品的 SHA-256 |

> 数据库不在本仓库 / 本 Release 发布；扩展库见 PolyXRD-DataBase 的 Releases。
> PDF2-2004 为 ICDD 版权库，**永不**随包 / 随 Release 分发。

## 十、升级提示

* 从 v5.2.0 覆盖安装 / 解压即可，配置无需迁移。
* **本版默认开启各向异性展宽**，因此 Rwp 会变化（多数变好）；要复现 v5.2 的数值，
  把 refined_options 里的 aniso 关掉即可（`aniso_c2/aniso_c4 = 0` 时逐位一致）。
* 若你手工设过微吸收颗粒半径：本版起支持**逐相**输入，单一值照旧有效。
* 多相定量若看到 `[区间]` 而不是点值，说明该相被判为近简并 —— 那不是精度问题，
  是数据没约束住它，别拿这个数做版本间比较。
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
