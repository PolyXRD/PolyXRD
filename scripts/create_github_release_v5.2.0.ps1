# PolyXRD v5.2.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v5.2.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v5.2.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v5.2.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v5.2.0-Portable.zip  便携包 —— 内部评估版变体
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
$tag     = 'v5.2.0'
$version = '5.2.0'
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
## PolyXRD v5.2.0

发布日期：2026-11-05 ｜ 联系：sshztx@outlook.com

一句话：**在"算得对"之后补上"强度也对"** —— v5.1 把峰位、展宽、择优取向、结构精修
全部做对，v5.2 处理剩下两类**系统性强度误差**，并顺手把"定量结果不可信"从"看了也
不知道"变成"界面上明写着"。

> 本版**包含 v5.1 的全部七件欠账**（v5.1.0 未单独发布），下文第十节列出清单。

### 一、表面粗糙度与微吸收：两类误差，接线方式必须相反

这两类系统性误差都会让强度整体偏，但**参数依赖关系相反**，处理错了就白做：

- **表面粗糙度 SR**（`refinement/intensity.py`，三个模型：Sidey 单参数默认 /
  Suortti 双参数 / Sparks 线性；Pitschke 有意不实现）。它随 2θ 变化 → **不能被标度
  吸收** → 进前向模型（乘子贯通 `design_matrix` / `phase_pattern` / `synthesize`），
  参数 `inst.rough` 可精修。
- **微吸收 MA**（Brindley τ，Hill & Howard 表形式，只用 2θ=90° 列；τ(0)=1 精确、
  越界截断并置 `clamped`）。逐相约一常数 → **会被标度吸收** → 只进 Hill–Howard
  定量（`W ∝ S·f/τ`），3 轮 μ̄↔W 不动点迭代。**对 Rwp 逐位无影响**（A/B 实测 4 例
  全部相同，这是接线正确性的硬检查）。

两者默认 **opt-in**：SR 的 s 在 4 个真实试样上全部收敛到 ~0（Rwp 变化 ≤0.02 pp），
MA 的颗粒半径 R 给错会直接把定量打坏（R=10 µm 让 2-1 的 Σ|Δwt| 从 0.96 涨到 6.16），
**R 必须由用户实测给出**，不能猜。

### 二、μ 表换成 NIST 逐元素数据，覆盖 H…U

运行期不依赖 xraylib / periodictable（本机都没有），内置 Cu Kα 质量衰减系数表。
v5.2 扩到 **Z=1…92 全覆盖**，逐元素取自 NIST *X-Ray Mass Attenuation Coefficients*
（Hubbell & Seltzer）Table 3 的 `8.000 keV` 列 —— **不是按 Z 拟合外推**：这张表在
L 边附近有 2.5 倍断崖（Sm 440 → Tb 313 → Ho **127**），外推必错。

顺带修正旧表的两处抄录偏差（以 NIST 为准）：Fe 325→**306**、Mg 47.0→**40.6**；
其余 Z≤30 元素变动 ≤4.5%。

### 三、定量误差棒含 τ 传播

`fraction_sigmas` 原来只按 `W = S·f/ΣS·f` 的闭式传播，微吸收开启时 `f` 实际是
`f/τ` 而 **τ 又依赖 W**（`μ̄ = Σ W·μ` 的闭环）。闭式导数要展开 `dτ/dx` 再解线性
方程组，容易在截断区出错 → 改为对 S 做**数值雅可比**（不动点迭代是 S 的确定函数，
n 次重解，n≤7 可忽略）。R→0 时数值解退化回闭式，测试以此自证（差 1e-9）。

### 四、相标度相关诊断 `SCALE_CORRELATED`

两相峰重叠严重时两相标度**此消彼长而 Rwp 几乎不变**，此时 wt% 的小数位只是表面
精度。`|ρ|>0.95` 且两相均 >1% 时报 warn。这条判据无法从 Rwp 或各自 σ 推出，是多相
定量"不可分辨"的唯一拦截点。

### 五、定量份额的"判别峰守卫"（P2-10）

两相 Rietveld 会给一个**根本不存在**的相非零份额，而且 Rwp 还真的变好 —— 大胞相
自带独立峰宽参数，能把样品展宽造成的失配整块摊平，于是 χ² 单调下降而份额无物理
意义。`audit()` 新增第 12 条规则，两个码：

| 码 | 触发 | 含义 |
|---|---|---|
| `PHASE_UNSUPPORTED` | 有唯一强线，却一条都没出现在实测里 | 硬证据：该相很可能不存在 |
| `PHASE_FRACTION_UNVERIFIABLE` | 一条唯一强线都没有（全压在别的相线上） | 软证据：wt% 由峰宽/背景自由度决定，数据没约束它 |

实测（`test_xrd/WO3` 两条谱）：WO3 + W20O58 给出 15.63 / 9.35 wt%、Rwp 降 3.0 pp，
但 W20O58 最强判别线 24.66° 在两条谱上都是主峰 24.34° 的单调衰减尾巴 —— 现在两条
谱都报 `PHASE_FRACTION_UNVERIFIABLE`。守卫**只报不自动删相**：删相不可逆，而且
"该线在扫描窗口外"与"该相真的不存在"在数值上无法区分。

### 六、诊断"选谁上界面"（P2-11）

界面只挂 4 条诊断，而此前"谁进前 4"由 `(severity, code)` 决定 —— 同级内**纯按
字母**。实测四相拟合里三条"改了也看不出"的提示占满前三，把"这份 wt% 能不能用"
挤到第 4；再多一条就静默丢了。现在：

- 同级内**结论类码优先**（秩亏 / 相未检出 / 相无支撑 / 份额不可验证 / 参数撞界 /
  标度强相关 / 微吸收截断），error 仍整体压 warn
- 第 5 条起**全量写进执行日志**（此前这些 findings 在界面、日志、导出里都看不到）

### 七、内置矿物库 R-3c 坐标修复（P2-9）

方解石 / 刚玉的 O 位少 `z=1/4`，对称展开出 48 个位点（应 30），GUI 走内置库时多相
定量全错。修复后展开位点数正确，与两套独立实现（自研 `build_reflections` vs
pymatgen `XRDCalculator`）逐峰 **0.0% 差**；主峰回到文献位（方解石 104@29.39°、
刚玉最强峰从误置的 104 恢复为 113@43.41°）。

### 八、GSAS-II 桥三处修复

- **子进程超时按相数自适应** `max(300, 120·n)`（5 相 = 600 s），显式 ≤0 = 不限时
- **新增 `sample_displace`（BB 几何 `DisplaceX`）与 `pref_ori`（March–Dollase hkl+r）
  两个 request 字段**，服务层把前处理产物的择优方向自动透传
- **GOF 不再是 0**：桥此前在 main() 硬编码 `"GOF": None`，诊断表整列恒 0。现从
  `Covariance['data']['Rvals']` 取真实 GOF/Nobs/Nvar —— 端到端实证 2-1 GOF
  **15.727**（此前 0.00），`metrics_valid=True`，wt 无回归

### 九、PDF2-2004 重打包为 polyDB，旧 sqlite 通道删除

ICDD PDF-2 2004 原以自建 sqlite 挂载（214 MB），是 v4.0 之后唯一残留的旧格式通道。
现按 polyDB 规范重打包为 **154 MB**（−28%）、163,834 相 / 10,445,852 峰，解析器拆成
纯函数 `services/pdf2_scan.py`。它现在是 polyDB 的第三个变体（`variant="pdf2-2004"`），
与 COD 两个变体共用同一套 reader / 位图倒排预筛 / Hanawalt 打分；历史项目文件的
`db_source="pdf2"` 由别名继续有效。

> PDF2-2004 为 ICDD 版权商品库，**永不**随包或随 Release 分发；本版仅涉及**读取
> 格式**的变化。已挂载旧 sqlite 的用户请重新挂载新目录。

### 十、本版同时包含 v5.1 的全部七件

| # | 件 | 关键结果 |
|---|---|---|
| 1 | **Kα2 波长比 bug + 双线存在性判别** | λ2 默认 `0.99937`（比 Kα1 还短）→ 正确 `1.00249`；伴峰此前被放到主峰**左侧**。修后 3-1 Rwp **25.73→9.93** |
| 2 | **样品展宽可辨识性** | `{p}.size` 改洛伦兹系数 `{p}.sizec`、stage 5 钉住 `inst.X/Y`、起点播种 500 nm → 4 例秩亏全清 |
| 3 | **择优取向自动选择** | 方向 × r 网格按投影收益择优；判据不为 Rwp 牺牲定量 |
| 4 | **每相整体温度因子 B** | 模型落地（`{p}.bovr`），默认**冻结**（定量 2 好 2 坏） |
| 5 | **Wyckoff 轨道归并** | 位点按轨道归并 + 稳定子锁轴 → stage 6 真正可用；合成刚玉 Rwp **37.87%→11.75%** |
| 6 | **替代设置空间群符号** | `P b n m` / `P 1 21/n 1` 解析失败导致胞参全放开 → 7-1 针铁矿 β 跑到 130.8°；修后 Σ\|Δwt\| **33.35→26.19** |
| 7 | **缺氢结构条目自动择优** | 检索折叠阶段优先取"位点元素齐全"的条目，**只换内容不动位置**；7-1 Rwp **20.70→16.83**，检索指标逐位不变 |

### 十一、启动期崩溃的观测探针（P0-1，未修）

启动期 `window.show()` 的间歇性原生 AV **仍未修复**，但本版把"能不能定位"这件事做完
了：启动日志新增 `context:` 一行（管理员 / 远程会话 / cif_db 存在且可写 / OpenGL /
QPA / DPI 缩放）+ 首帧探针（`showing → shown → ui-tick0 → first-paint → settled`），
配 `scripts/diagnose_startup_log.py` 按 pid 归并、按里程碑反推崩溃阶段并按 context
分组统计。遇到崩溃请把 `%USERPROFILE%\.polyxrd\logs` 整个目录反馈过来 —— 有了这几项
才可能区分 A/B 组。

### 十二、测试与质量

- 全量回归 **2567 passed / 4 skipped / 0 failed**（531 s）
- 13 试样三引擎对拍：refinement 中位数 Rwp **17.46%**、最优 7/13
- 新增守护：判别峰守卫 24 条、GSAS-II 桥接线 17 条、R-3c 位点 5 条、启动日志判读
  16 条、构建 flavor 9 条、位点完整性 23 条

### 十三、已知边界

- **5-3 的多相精修偏慢**（5 相 fast 档 ≈ 185 s）：profile 显示 91% 时间在数值雅可比
  × 全量重建设计矩阵，`area_normalized_profile` 被调 11.5 万次。**不是择优取向的
  锅**（自动选择本身只花 0.4 s）。优化方向已写进 `docs/待办清单.md`，未在本版做。
- **整体温度因子 B 仍默认冻结**：定量上没有净收益
- **微吸收的颗粒半径必须由用户实测给出**：给错比不给更糟
- **快档（fast）的 wt% 不要拿来做版本对比**：细晶 / 层状 / 多相混合物上，
  `inst.x/y/z` 会三参数同时撞界且 ρ=−1.00，份额的小数位没有意义
- ⚠️ **启动期 AV（P0-1）未修**，见第十一节

### 📦 附件（3 个）

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v5.2.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `PolyXRD-v5.2.0-Portable.zip` | 便携包 = **内部评估版**，内置 COD-Inorg |
| `SHA256-v5.2.0.txt` | 以上两个程序产物的 SHA-256 |

> 数据库不在本仓库 / 本 Release 发布；扩展库见
> [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases)。
> PDF2-2004 为 ICDD 版权库，**永不**随包 / 随 Release 分发。

### 🔧 升级提示

- 从 v4.7.0 覆盖安装 / 解压即可，配置无需迁移
- **v5.1 的 Kα2 修复会改变精修数值**：本版 Rwp 与 v4.x 不可直接横向比较（旧口径的
  Rwp 被错误伴峰系统性抬高了）
- **若你挂载过 `PDF2_2004.sqlite`**：该格式已废弃，请改挂 `PDF2-2004.polyDB/` 目录
- **若你手工设过微吸收参数**：v5.2 起 μ 表按 NIST 逐元素取值，Fe/Mg 的 μ 分别下降
  6% / 14%，同一 R 算出的 τ 会略有不同
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
