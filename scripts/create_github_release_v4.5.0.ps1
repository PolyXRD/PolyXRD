# PolyXRD v4.5.0 GitHub Release 创建 + 附件上传 (幂等可重跑)
# 用法: & 'scripts\create_github_release_v4.5.0.ps1'
#
# ★ 本版上传 3 个附件 (与历次发布口径一致):
#   SHA256-v4.5.0.txt            (先传小的, 先失败先暴露)
#   PolyXRD-Setup-v4.5.0.exe     正式发布版安装包 —— 带注册机制
#   PolyXRD-v4.5.0-Portable.zip  正式发布版便携包 —— 解压即用
# ★ 硬性政策: PDF2-2004 是 ICDD 版权商品库, **永不随 Release 分发**;
#   数据库包也不在本仓库上传 (v4.5.0 政策) —— $BANNED 同时拦截 'PDF2' 与 'Databases-'。
#   底部有 $BANNED 守卫, 任何含 PDF2 的路径一旦混进来会直接抛错终止。
# ★ 数据库**不在本仓库上传/发布** (政策 2026-10-23):
#   本脚本只传程序 3 附件; 两个 polyDB 库包统一在独立仓库
#   https://github.com/PolyXRD/PolyXRD-DataBase 的 Releases 分发。
#   PDF2 守卫仍对任何误加附件生效。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'D:/Project/XRD/PolyXRD'

# git.exe 定位 (v4.5.0 修): 原先硬编码 PortableGit 1.2.0 的路径, 升级到 1.3.0 后
# 该目录不存在 -> `git credential fill` 起不来 -> 报 "An error occurred trying to start
# process 'git.exe'"。改为按候选列表探测, 并把 `git` 自身能否解析也算命中, 避免下次
# PortableGit 再升版本又失效。
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
$tag     = 'v4.5.0'
$version = '4.5.0'
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
## PolyXRD v4.5.0

发布日期：2026-10-29 ｜ 联系：sshztx@outlook.com

本版是**装机可靠性修复合集**：全部改动来自 v4.4.0 实机安装后的现场反馈——
装到 `Program Files` 下普通用户起不来、PDF2 外挂库读不出、氧化钨样品"检不出物相"。
**无检索/精修算法口径改动**，FoM 与打分逻辑与 v4.4.0 逐字一致。

### 一、装在只读安装目录（`Program Files`）下普通用户起不来

`get_config()` 对 `cif_db_path` / `export_dir` / `log_dir` 无条件 `mkdir`，而 frozen 后
`_PROJECT_ROOT` 就是**安装根**、安装包并不含 `cod_data` → 目录建不出 → `PermissionError(5)`。
调用点在 `main.py` 取版本号那一行，**早于 `QApplication`**，所以窗口都出不来（只有崩溃日志）。

- `cif_db_path` 默认值改为 `_default_cif_db_dir()`：项目内 `cod_data/cif_db` **存在才用**，
  否则落到 `~/.polyxrd/cif_db`（与 `user_db_dir()` 同一落点）
- 三处目录创建收敛到 `_ensure_dir()`，任何 `OSError` 静默吞掉 —— 建不出目录只降级，不拦启动
- 启动日志的版本号改用 `polyxrd.__version__` 常量，不再为打一行日志提前触发配置单例

> 开发机从未暴露：那里的 `cod_data/cif_db` 一直存在，`mkdir(exist_ok=True)` 对已存在目录
> 直接返回、**不校验写权限**。判据是"干净机器 + Program Files + 非管理员"。

### 二、启动诊断不再把「无写权限」和「自己映射自己」报成「被占用」

`startup_diag.lock_status` 用 `open(path, "r+b")` 探占用，于是：① 只读目录下的 exe/dll 被
判成"被占用"；② 它探测的正是**当前进程自己的映像**，Restart Manager 必然返回自己的 pid
—— v4.4.0 现场日志里"占用进程 PolyXRD pid=5740"中的 5740 就是它自己。结论一路指向
"重启电脑"，而真实原因是权限。

- 占用判定拆三态：`winerror=32`（真共享冲突）/ 所在目录不可写（权限不足）/ 目录可写仍失败（被映射）
- 报告新增 `install dir writable` 与「无写权限的文件」清单；自映射单独标注为正常
- 诊断模块保持 Qt-free、可单测

### 三、PDF2 外挂库在只读目录 / 单文件拷贝下读不出

两个独立成因，现象都是 `unable to open database file`（"文件明明在"）：

1. `sqlite3.connect(f"file:{path}?mode=ro")` 把裸 Windows 路径拼进 URI —— 路径含空格/`#`/`?`
   时被当分隔符截断。改用 `Path.as_uri()`。
2. `PRAGMA journal_mode=WAL` **写进库头**且持久化，此后只读打开必须在同目录建 `-shm`；
   装到 `Program Files`、放只读介质、或只拷了那一个 `.sqlite` 就必然失败。打开失败自动降级
   官方 URI 参数 `immutable=1`。

- 新增 `services/sqlite_ro.py`：`readonly_uri()` + `connect_readonly()`（URI 转义 +
  WAL 只读降级 + 连接后立刻 `PRAGMA user_version` 探活，不让错误拖到首次查询）
- `PDF2Database._get_conn` 与 `db_import.inspect_db_file` 统一改用它
- `PDF2DatabaseBuilder.build()` 收尾加 `PRAGMA journal_mode=DELETE` → **新产物自包含单文件**，
  库旁不再常驻 `-wal` / `-shm`
- `PDF2Database` 新增 `close()`（幂等）与 `last_error`：打不开时留原因，不再静默返回 0 条

> 已有库已就地转换：全库 214,454,272 B 中**只有 4 字节变化**（库头 18/19 读写版本 2,2→1,1；
> 27/95 change counter 7→8），phases 163,834 条与内容指纹、meta 全部不变。
> 实测（`icacls` 拒绝写入的目录、各放一份单文件）：老代码打开 WAL 库失败，新代码正常。

### 四、元素限定后检不出物相（P0）

`polydb.ELEMENTS` 元组**漏了 Rh（Z=45）**，而建库端 `tools/build_polydb.py` 的表是完整的。
`Z_OF` 由 `enumerate(ELEMENTS)` 生成，漏一个元素既不报错也没有重复值，只是 Rh 之后
所有元素下标整体前移一位 → 读端读到错误的 `elem.u8` 位图平面：

| 查询元素 | 实际读到的位图 | 后果 |
| --- | --- | --- |
| W（读端算成 73） | Ta | 返回的全是 Ta-O 相 |
| Ta | Hf | 同族邻元素 |
| Pb | Tl | 同族邻元素 |
| U | Pa | 同族邻元素 |
| Rh | 不存在 | 直接空结果 |

**Z≥45 的元素全部受影响**，而 W / Ta / Pb / 稀土 / U 正是 XRD 最常打交道的重原子。
实测修复前 `_element_mask(['W','O'])` 的 470 条命中里 WO3（row 15857）、W18O49（row 1158）
全部 `in_mask=False` —— 这是"氧化钨样品检不出物相"的直接原因之一。

- `ELEMENTS` 补 `Rh`（Ru 之后），`Z_OF` 恢复 Rh=45 / Ta=73 / W=74 / Pb=82 / U=92
- **库文件无需重建**（建库端一直正确），只改读端一行
- 新增守卫 `tests/test_polydb_elements.py`（54 例：跨周期 46 个 Z 锚点、Rh 位序、
  `Z_OF` 覆盖 1..118、位图语义 4 项）。此前**没有任何测试碰过元素位图**，这是它能活到发布的原因

### 五、其他

- 新增 `tests/test_sqlite_ro.py`（12 例）：URI 转义（空格 / `#`）、行工厂、缺失文件、
  非数据库文件、WAL 只读降级、`close()` 幂等、建库产物非 WAL。
- 无算法改动：物相检索打分口径、精修引擎、报告生成与 v4.4.0 一致；三语界面键集不变。
- 回归：全量 **1830 passed / 7 skipped / 0 failed**，`ruff check src` 全绿。

### 📦 附件（3 个）

| 附件 | 内容 |
|---|---|
| `PolyXRD-Setup-v4.5.0.exe` | 正式版安装包（带注册机制），内置 COD-Inorg 默认库 |
| `PolyXRD-v4.5.0-Portable.zip` | 便携包 = **内部评估版**，内置 COD-Inorg |
| `SHA256-v4.5.0.txt` | 以上两个程序产物的 SHA-256 |

> 数据库不在本仓库/本 Release 发布；扩展库见
> [PolyXRD-DataBase Releases](https://github.com/PolyXRD/PolyXRD-DataBase/releases)。
> PDF2-2004 为 ICDD 版权库，永不随包/随 Release 分发。

### 🔧 升级提示

- **从 v4.4.0 装到 `Program Files` 的用户**：启动不再因"配置目录建不出"而失败，可先不用管理员权限直接覆盖安装试一次；若仍只见 splash 不见窗口，那是另一个已知问题（见文末 ⚠️），把日志发过来即可，不用反复重装。
- 从 v4.3.0/v4.4.0 覆盖安装/解压，配置无需迁移。
- 若仍在使用旧的 `PDF2_2004.sqlite`（库头是 WAL 模式），本版可直接只读打开，
  **不必**手工转换；想要库旁不出现 `-wal`/`-shm`，可用数据库管理里的重建功能重新生成一份。
- ⚠️ **仍有一个未闭环的启动期问题**：个别机器上 `window.show()` 会**间歇性**原生崩溃
  （表现为 splash 之后没有主窗口，日志里是 access violation）。本版修掉的是"装到
  `Program Files` 后配置目录建不出 → 必崩"这条路径；那条间歇性崩溃仍在跟踪中，
  排查记录见仓库 `docs/待办清单.md` 的 P0-1。若你遇到，请把
  `%USERPROFILE%\.polyxrd\logs` 整个目录反馈过来。
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
