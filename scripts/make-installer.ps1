Set-Location 'd:\TEMP\PolyXRD'
$ErrorActionPreference = 'Stop'

$Z7      = 'C:\Program Files\7-Zip\7z.exe'
$SFXMOD  = 'C:\Program Files\7-Zip\7z.sfx'
$rel     = 'd:\TEMP\PolyXRD\release_staging'
$stgSrc  = Join-Path $rel '_sfx_src'
$outExe  = Join-Path $rel 'PolyXRD-Setup-v0.9.0.exe'
$archive = Join-Path $rel '_PolyXRD-App-full.7z'
$cfg     = Join-Path $rel '_sfx_cfg.txt'

if (-not (Test-Path (Join-Path $rel 'PolyXRD_COD_Inorganics_v0.9.0.zip'))) { throw 'COD inorganics zip missing' }
if (-not (Test-Path (Join-Path $rel 'PolyXRD_COD_Full_v0.9.0.zip')))       { throw 'COD full zip missing' }

# Clean previous stgSrc
if (Test-Path $stgSrc) { Remove-Item -Recurse -Force $stgSrc }
New-Item -ItemType Directory -Force -Path $stgSrc | Out-Null

# Copy app files (dist\PolyXRD)
Copy-Item -Recurse -Force "dist\PolyXRD" (Join-Path $stgSrc "PolyXRD")
Write-Host ("Copied app, total MB=" + [math]::Round((Get-ChildItem -Recurse (Join-Path $stgSrc "PolyXRD") | Measure-Object Length -Sum).Sum/1MB,1))

# Copy setup_actions.bat as autorun (must be top-level inside archive)
Copy-Item -Force "scripts\setup_actions.bat" (Join-Path $stgSrc "setup_actions.bat")

# Create 7z archive (mx=9 max compression, solid, multithreaded)
if (Test-Path $archive) { Remove-Item -Force $archive }
Push-Location $stgSrc
  Write-Host "Creating 7z archive (this may take 3-10 min)..."
& $Z7 a -t7z -m0=lzma2:d1024m -mx=9 -mmt=8 -mfb=64 -md=256m -ms=on $archive 'PolyXRD\*' 'setup_actions.bat'
  $ec = $LASTEXITCODE
Pop-Location
Write-Host ("Archive exit=" + $ec)
if ($ec -ne 0 -or -not (Test-Path $archive)) {
  throw "7z archive creation failed (exit=$ec). Abort."
}
Write-Host ("Archive size=" + [math]::Round((Get-Item $archive).Length/1MB,1) + " MB")

# Write SFX config (UTF-8 without BOM recommended by 7z; use UTF-8)
@'
;!@Install@!UTF-8!
Title="PolyXRD v0.9.0 安装程序 (Setup)"
BeginPrompt="是否安装 PolyXRD v0.9.0 多晶X射线衍射物相分析工具?`r`nInstall PolyXRD v0.9.0?"
CancelPrompt="是否取消安装 PolyXRD v0.9.0?"
ExtractDialogText="正在解压 PolyXRD v0.9.0,请稍候...`r`nExtracting PolyXRD v0.9.0..."
ExtractTitle="PolyXRD v0.9.0 Installation"
ExtractPathText="选择安装文件夹 / Select install folder:"
ExtractPath="%ProgramFiles%\PolyXRD"
OverwriteMode="2"
RunProgram="setup_actions.bat"
FinishMessage="PolyXRD v0.9.0 安装完成! 请在开始菜单或桌面双击 PolyXRD 启动。"
;!@InstallEnd@!
'@ | Set-Content -Encoding utf8 $cfg

# Build the .exe via concatenation: sfx_mod + cfg + archive  (bytes only)
if (Test-Path $outExe) { Remove-Item -Force $outExe }
$sfxB  = [System.IO.File]::ReadAllBytes($SFXMOD)
$cfgB  = [System.IO.File]::ReadAllBytes($cfg)
$arcB  = [System.IO.File]::ReadAllBytes($archive)
$total = $sfxB.Length + $cfgB.Length + $arcB.Length
Write-Host ("Writing SFX EXE, total=" + [math]::Round($total/1MB,1) + " MB ...")
$fs = [System.IO.File]::Open($outExe, [System.IO.FileMode]::Create)
try {
  $fs.Write($sfxB, 0, $sfxB.Length)
  $fs.Write($cfgB, 0, $cfgB.Length)
  $fs.Write($arcB, 0, $arcB.Length)
} finally {
  $fs.Dispose()
}
Write-Host ("SFX EXE built: " + [math]::Round((Get-Item $outExe).Length/1MB,1) + " MB -> " + $outExe)

# Summary + SHA256
Write-Host "`n============= RELEASE OUTPUTS ============="
Get-ChildItem $rel -File | Where-Object { $_.Name -like 'PolyXRD*' -and ($_.Extension -in '.exe','.zip') } |
  ForEach-Object {
    [PSCustomObject]@{
      Name   = $_.Name
      MB     = [math]::Round($_.Length/1MB, 1)
      SHA256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
  } | Format-Table -AutoSize -Wrap
