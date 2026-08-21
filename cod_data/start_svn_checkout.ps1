# COD SVN checkout launcher
# Only checks out the cif/ subdirectory (530k CIF files), skipping hkl/, mysql/, html/
# Uses Start-Process to launch an independent svn.exe so it survives terminal exit

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path "$PSScriptRoot\.."
$svn = "$projectRoot\tools\sliksvn\extracted\PFiles\bin\svn.exe"
$dest = "$projectRoot\cod_data\cod_svn\cif"
$log = "$projectRoot\cod_data\checkout.log"
$errLog = "$projectRoot\cod_data\checkout.err.log"
$pidFile = "$projectRoot\cod_data\svn.pid"

# Prevent duplicate launches: if pid file exists and process is still running, exit
if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($oldPid) {
        try {
            $running = Get-Process -Id ([int]$oldPid) -ErrorAction Stop
            if ($running) {
                Write-Host "SVN checkout already running PID=$oldPid, exit"
                exit 0
            }
        } catch {
            Remove-Item $pidFile -ErrorAction SilentlyContinue
        }
    }
}

# Launch independent svn process with logs redirected, fully detached from parent terminal
$argList = @(
    "co",
    "--trust-server-cert",
    "--non-interactive",
    "svn://www.crystallography.net/cod/cif",
    $dest
)

$proc = Start-Process -FilePath $svn -ArgumentList $argList -RedirectStandardOutput $log -RedirectStandardError $errLog -WindowStyle Hidden -PassThru

$proc.Id | Out-File $pidFile -Encoding ascii
Write-Host "SVN checkout started"
Write-Host "PID: $($proc.Id)"
Write-Host "Destination: $dest"
Write-Host "stdout log: $log"
Write-Host "stderr log: $errLog"
Write-Host "pid file: $pidFile"
