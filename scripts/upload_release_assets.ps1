param()
$ErrorActionPreference = 'Stop'
Set-Location 'd:\TEMP\PolyXRD'

$owner     = 'PolyXRD'
$repo      = 'PolyXRD'
$tag       = 'v0.9.0'
$baseURL   = "https://api.github.com/repos/$owner/$repo"
$release_dir = 'd:\TEMP\PolyXRD\release_staging'

# ---- Get GitHub token from GCM ----
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'git.exe'; $psi.Arguments = 'credential fill'
$psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.UseShellExecute = $false
$p = [System.Diagnostics.Process]::Start($psi)
$enc = [System.Text.Encoding]::UTF8.GetBytes("protocol=https`nhost=github.com`n`n")
$p.StandardInput.BaseStream.Write($enc,0,$enc.Length)
$p.StandardInput.Close()
$raw = $p.StandardOutput.ReadToEnd()
$p.WaitForExit(15000) | Out-Null
$kv = @{}; ($raw -split "`n") | ForEach-Object { if($_ -match '^(.*?)=(.*)$') { $kv[$Matches[1]] = $Matches[2] } }
$token = $kv['password']
if (-not $token) { throw 'No GitHub token' }
$headers = @{
  'Authorization'     = "Bearer $token"
  'Accept'            = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
}

# ---- Find release ----
$r = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers -Method Get
$releaseId = $r.id
$uploadBase = $r.upload_url -replace '\{.*\}$',''
Write-Host "Release id=$releaseId upload_base=$uploadBase"

# ---- List existing assets to delete same-name ones (idempotent) ----
$existingAssets = Invoke-RestMethod -Uri "$baseURL/releases/$releaseId/assets" -Headers $headers

# ---- HttpClient setup (persistent connections, larger timeout) ----
Add-Type -AssemblyName System.Net.Http
$hch = New-Object System.Net.Http.SocketsHttpHandler
$hch.PooledConnectionLifetime = [TimeSpan]::FromMinutes(10)
$hch.PooledConnectionIdleTimeout = [TimeSpan]::FromMinutes(5)
$hch.MaxConnectionsPerServer = 4
$client = New-Object System.Net.Http.HttpClient($hch)
$client.Timeout = [TimeSpan]::FromMinutes(60)
$client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $token)
$client.DefaultRequestHeaders.Accept.Clear()
$client.DefaultRequestHeaders.Accept.Add((New-Object System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("application/vnd.github+json")))
$client.DefaultRequestHeaders.Add('User-Agent','PolyXRD-upload/1.0')

function Upload-Asset([string]$filePath, [string]$assetName, [string]$contentType, [int]$retries = 6) {
  # Remove existing same-name
  foreach ($o in $existingAssets) { if ($o.name -eq $assetName) {
    Write-Host "  del existing asset id=$($o.id) ..."
    Invoke-RestMethod -Uri "$baseURL/releases/assets/$($o.id)" -Headers $headers -Method Delete | Out-Null
  }}
  $fi = Get-Item $filePath
  $size = $fi.Length
  Write-Host "Uploading $assetName ($([math]::Round($size/1MB,1)) MB)..."
  $name = [Uri]::EscapeDataString($assetName)
  $uri = "$uploadBase`?name=$name"
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
          Write-Host ("  retry $i/$retries HTTP $($resp.StatusCode): " + $respBody.Substring(0, [Math]::Min(400,$respBody.Length)))
          $resp.Dispose()
          Start-Sleep -Seconds (5*[Math]::Min($i,6))
          continue
        }
        $resp.Dispose()
        $up = $respBody | ConvertFrom-Json
        $sw.Stop()
        $mbps = [math]::Round(($size/1MB)/$sw.Elapsed.TotalSeconds, 2)
        Write-Host ("  OK $assetName uploaded in $([math]::Round($sw.Elapsed.TotalSeconds,1))s ($mbps MB/s) size=$([math]::Round($up.size/1MB,1))MB url=$($up.browser_download_url)")
        return $up
      } finally {
        $fs.Dispose()
      }
    } catch {
      Write-Host ("  retry $i/$retries ERR: " + $_.Exception.Message)
      Start-Sleep -Seconds (6*[Math]::Min($i,6))
    }
  }
  throw "FAILED upload $assetName after $retries tries"
}

# --- Upload order: smallest to largest to fail-fast ---
Upload-Asset -FilePath (Join-Path $release_dir 'PolyXRD_COD_Inorganics_v0.9.0.zip') -AssetName 'PolyXRD_COD_Inorganics_v0.9.0.zip' -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $release_dir 'PolyXRD_COD_Full_v0.9.0.zip')       -AssetName 'PolyXRD_COD_Full_v0.9.0.zip'       -ContentType 'application/zip'
Upload-Asset -FilePath (Join-Path $release_dir 'PolyXRD-Setup-v0.9.0.exe')          -AssetName 'PolyXRD-Setup-v0.9.0.exe'          -ContentType 'application/octet-stream'

# --- Final summary ---
Write-Host "=== FINAL ==="
$f = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers
Write-Host "Release : $($f.html_url)"
foreach ($a in $f.assets) { Write-Host ("  " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url) }
Write-Host "DONE"
