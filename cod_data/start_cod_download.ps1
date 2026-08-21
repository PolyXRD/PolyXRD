# COD inorganics reference database downloader (asynchronous BITS)
# BITS service survives PowerShell exit and resumes on network drops

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path "$PSScriptRoot\.."
$destDir = "$projectRoot\cod_data\downloads"
$dest = "$destDir\COD-Inorganics_20260602.zip"
$statusFile = "$destDir\bits_status.json"

New-Item -ItemType Directory -Force -Path $destDir | Out-Null

$url = "https://www.crystalimpact.com/download/match/refdb/COD-Inorganics_20260602.zip"

# Clean up any previous failed BITS job with same name
Get-BitsTransfer -Name "CodInorganicsDownload" -ErrorAction SilentlyContinue | Remove-BitsTransfer

Write-Host "Starting asynchronous BITS download..."
Write-Host "URL: $url"
Write-Host "Destination: $dest"

# Asynchronous BITS transfer: returns immediately, job persists in BITS service
$job = Start-BitsTransfer -Source $url -Destination $dest -DisplayName "CodInorganicsDownload" -Asynchronous -Priority Foreground -ErrorAction Stop

# Persist job info to a status file so we can query progress later
$status = @{
    JobId = $job.JobId
    DisplayName = $job.DisplayName
    BytesTotal = $job.BytesTotal
    BytesTransferred = $job.BytesTransferred
    State = $job.JobState.ToString()
    Destination = $dest
}
$status | ConvertTo-Json | Out-File $statusFile -Encoding utf8

Write-Host "BITS job started (async)"
Write-Host "JobId: $($job.JobId)"
Write-Host "Initial state: $($job.JobState)"
Write-Host "Status file: $statusFile"
Write-Host "Monitor with: Get-BitsTransfer -Name CodInorganicsDownload"
