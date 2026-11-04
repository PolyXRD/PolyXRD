# PolyXRD v5.1.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v5.1.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v5.1.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v5.1.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v5.1.0-Portable.zip  便携包 —— 内部评估版变体
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
$tag     = 'v5.1.0'
$version = '5.1.0'
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
## PolyXRD v5.1.0

发布日期：2026-11-04 ｜ 联系：sshztx@outlook.com

一句话：**精修引擎从"峰位对"推进到"强度与定量对"**。

v5.0.0 解决的是"算得出、算得稳"（Rietveld/Le Bail 引擎能从零跑通多相精修），
v5.1 这一版处理的是"算得对"—— 七件欠账全部来自真实试样的定量偏差，每一件都有
A/B 实验与基准报告对应章节，没有一件是"顺手改的"。

### 一、修掉一个静默给错数的 bug：Kα2 波长比

`ka2_wavelength` 默认 `ratio_of_ka1=0.99937` → λ2 = 1.53959 Å，**比 Kα1 还短**；
正确值 1.00249（Cu Kα2 = 1.54439 Å）。后果是双线模型的伴峰被放到主峰**左侧**约半
间距处，方向与量级全错 —— 3-1 的 `U·tan²θ` 失控（u=0.182）就是在给这条错侧伴线
当替身。

- 修复后：**3-1 Rwp 25.73 → 9.93（−15.8 pp）**、2-1 21.30 → 14.20
- 同步落地 **Kα2 存在性自动判别**（`refinement.detect_ka2_doublet`）：用高角区镜像
  位对称性排除洛伦兹拖尾与多重峰误配；判无 → 关双线建模（u/v 回到物理可解读），
  判不了 → 维持现状，显式 True/False 永远优先

### 二、样品展宽可辨识性（`size` → `sizec`，`inst.X/Y` 钉住）

4 例秩亏的真实根因不是"参数没接通"，而是 `D→∞` 处 `dβ/dD ∝ 1/D²` 使差分列归零
（2-2 的 size 停在 99988、3-1 双双停在 100000），第二层才是 `X ↔ 4ε`、`Y ↔ Kλ/D`
逐字共线。

- `{p}.size` 改为洛伦兹系数 `{p}.sizec`（0 是正常点）、stage 5 钉住 `inst.X/Y`、
  起点播种 500 nm → **4 例秩全满、`RANK_DEFICIENT` 全清**

### 三、择优取向自动选择

按"方向 × r"网格的投影收益择优，并把判据钉在定量上：实验里 (001)/0.8 把 7-1 的
Rwp 压低 1.9 pp（20.70→18.79），却让 Σ|Δwt| 从 26.18 涨到 26.91、Gibbsite 更偏
（43.16→41.60）—— **判据不动**，不为 Rwp 牺牲定量。

### 四、每相整体温度因子 B（模型落地，默认冻结）

新增 `PhaseSpec.b_overall`（参数 `{p}.bovr`，峰强乘 `exp(−B/2d²)`）。复评结论：
4 例 A/B Rwp 全降 0.09~1.07 pp，但定量 **2 好 2 坏**（2-1 Σ|Δwt| 0.96→6.04、
7-1 33.35→37.60，Goethite 直接把 B 吃到上界 15 Å²）→ **维持 opt-in**
（`refine_b_overall=True`）。真正的前置是系统性强度误差，B 只能排在末端。

### 五、Wyckoff 轨道归并（结构精修 stage 6 真正可用）

- 位点按空间群轨道归并（同元素 + 同占位 + 能被某条操作从同一代表点生成），
  记住"用哪条操作把代表点搬过去"→ 代表点一动整条轨道跟着动：刚玉 30→2、
  萤石 12→2、尖晶石 56→3
- 稳定子锁轴：`P = mean(R_stab)` 是到不变子空间的正交投影，`P·e_a = 0` 的轴钉死并
  标"特殊位置锁定"
- 顺带修掉**缓存键缺位点**：`ensure_table()` / `_make_design_key()` 原来只按
  `cell_key()` 命中，改坐标后反射表仍返旧缓存 → **stage 6 在 LM 内部完全是空的**
- 验收：合成刚玉 **Rwp 37.87% → 11.75%**（GOF 1.09），Al z 回收 0.3520（真值
  0.3521），参数册 **150 → 10**；真实 4-1 逐位一致

### 六、替代设置空间群符号导致的胞参失约束

COD 里针铁矿写 `P b n m`（Pnma 的轴置换）、吉布斯石写 `P 1 21/n 1`（P2₁/n 全设置），
两者都不在 pymatgen 规范符号表里 → 解析不出晶系 → **该相 6 个胞参全放开**。
7-1 的针铁矿因此把 β 从 90° 跑到 **130.8°**，峰位全错、定量塌到 1.04 wt%（真值 9.98）。

- 修法：规范表失手后用清洗过的原写法直接构造 `SpaceGroup`（能正确处理替代设置，
  并按原写法缓存）；`resolve_space_group_symbol` 语义**不放宽**（它返回可回写的
  规范符号，硬猜更糟）
- 顺手加固单斜唯一轴：由"写死 b 唯一轴"改为"按输入晶胞里离 90° 最远的那个角"判
- 结果：7-1 Σ|Δwt| **33.35 → 26.19**，Goethite 1.04 → **9.17 wt%**

### 七、缺氢结构条目自动择优（检索侧）

COD 的氢氧化物 / 含水矿物条目常只列重原子 —— `formula` 写 `Al H3 O3`，CIF 原子环
里只有 Al/O。H 只有约 1 个电子，峰位与相对强度几乎不变，于是缺氢条目在检索阶段
与含氢条目**打分并列**，产品就选中了缺氢那条；进 Rietveld 后该相基面强线被算低、
定量系统性偏低（7-1 的 Gibbsite 43.16 vs 真值 54.90）。

- 检索折叠阶段改为：同成分同空间群（按**国际表编号**判，`P n m a` ≡ `P b n m`）的
  候选组内，优先用"位点元素齐全"的条目当代表 —— **只换内容、不动位置**，所以
  top-N 相集合与检索指标完全不受影响（有分数护栏 95%，不为完整度牺牲匹配质量）
- 结果（13 试样整体验证）：**11 个试样 Rwp 逐位不变**、5-3 中性、7-1
  **Rwp 20.70 → 16.83**、Σ|Δwt| **26.19 → 20.87**，七相全部朝真值动
- 检索基准逐位不变（Top-1 13/49、Top-3 33/49、Top-10 47/49、MRR 0.498）

### 八、测试与质量

- 全量回归 **2348 passed / 5 skipped / 0 failed**（v4.7.0 基线 1904）
- v5 精修引擎新增 302 条用例（`tests/refinement/` 五套）+ 本轮新增
  `tests/test_site_completeness.py` 23 条
- 13 试样三引擎对拍（空载机）：refinement 中位数 Rwp **17.46%**、最优 **7/13**；
  `auto` 已改为 refinement → 失败回退 builtin

### 九、已知边界（都在 `docs/待办清单.md` 里挂着，不是"以后再说"）

- **整体温度因子 B 仍默认冻结**：见第四节，定量上还没有净收益
- **GSAS-II 侧 ≥5 相会撞 300 s 超时**：这是既有问题（不是本版引入），会回落到
  Le Bail 结果，不崩
- **5-3 的定量重排（Σ|Δwt| 52 pp 量级）未解**：该试样没有配比真值，只能看趋势、
  判不了方向 —— 需要已知配比试样才能继续
- **组内全缺氢时无解**（如 Biotite 的固溶体条目）：需要"补氢"或用户自带结构
- ⚠️ **启动期 `window.show()` 的间歇性原生崩溃（P0-1）仍未修**：与算法无关，
  排查记录见 `docs/待办清单.md`；遇到请把 `%USERPROFILE%\.polyxrd\logs` 整个目录反馈过来

### 📦 附件（3 个）

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v5.1.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `PolyXRD-v5.1.0-Portable.zip` | 便携包 = **内部评估版**，内置 COD-Inorg |
| `SHA256-v5.1.0.txt` | 以上两个程序产物的 SHA-256 |

> 数据库不在本仓库 / 本 Release 发布；扩展库见
> [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases)。
> PDF2-2004 为 ICDD 版权库，**永不**随包 / 随 Release 分发。

### 🔧 升级提示

- 从 v4.7.0 覆盖安装 / 解压即可，配置与外挂库挂载（`db_mounts.json`）无需迁移
- **Kα2 修复会改变精修数值**：v5.1 的 Rwp 与 v4.x 不可直接横向比较（旧口径的 Rwp
  被错误伴峰系统性抬高了）
- 检索结果可能换条目：氢氧化物 / 含水矿物现在优先取"元素齐全"的那条（如
  Gibbsite 从 1011081 换成含 H 的 9003874），峰位几乎不变、定量更准
- 若你此前手工把某个缺氢条目录进了项目文件，打开后仍按你保存的结构精修，不会被偷换
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
