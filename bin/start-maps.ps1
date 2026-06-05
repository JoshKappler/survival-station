# start-maps.ps1 -- Launches the OFFLINE United States map at http://localhost:8082
#
# Fully local at runtime: a pure-PowerShell static HTTP server (System.Net.HttpListener,
# no external/unsigned binaries -- works under Windows Smart App Control) serves the
# vendored MapLibre GL viewer and the us.pmtiles vector archive (read client-side via
# HTTP range requests). No internet and no CDNs are used once running.
#
# Safe to re-run: stops any prior maps server on the port before relaunching.
# This launcher does NOT reboot, modify the firewall, or touch anything outside C:\Survival.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Port       = 8082
$Address     = "127.0.0.1"
$BinDir      = "C:\Survival\bin"
$ServerScript= "$BinDir\maps-server.ps1"
$MapsDir     = "C:\Survival\maps"
$ViewerIndex = "$MapsDir\viewer\index.html"
$PMTiles     = "$MapsDir\us.pmtiles"
$Url         = "http://$Address`:$Port/"

Write-Host ""
Write-Host "========================================================"
Write-Host "  Offline United States Map"
Write-Host "========================================================"

# 0. Sanity checks
if (-not (Test-Path $ServerScript)) { Write-Error "Server script not found: $ServerScript"; exit 1 }
if (-not (Test-Path $ViewerIndex))  { Write-Error "Viewer not found: $ViewerIndex"; exit 1 }

# 1. Report map data status (the viewer still loads and shows a friendly message if absent)
if (Test-Path $PMTiles) {
    $sz = [math]::Round((Get-Item $PMTiles).Length / 1GB, 2)
    Write-Host "[maps] Map archive: us.pmtiles present ($sz GB)."
} elseif (Test-Path "$PMTiles.partial") {
    Write-Host "[maps] Map archive is still downloading (us.pmtiles.partial present)."
    Write-Host "[maps] The map will work once it finishes; re-open the page then."
} else {
    Write-Host "[maps] WARNING: us.pmtiles not found yet. The viewer will load but show 'archive not ready'."
}

# 2. Stop any prior maps server on this port
Write-Host "[maps] Checking for an existing server on port $Port..."
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $pids = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        # Only stop our own server processes (powershell running maps-server.ps1),
        # never an unrelated process that happens to share the port owner id.
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        if ($cim -and $cim.CommandLine -and $cim.CommandLine -match 'maps-server\.ps1') {
            Write-Host "[maps] Stopping previous server (PID $procId)."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
    # also catch any maps-server.ps1 not currently bound
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'maps-server\.ps1' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 800
} else {
    Write-Host "[maps] Port $Port is free."
}

# 3. Launch the server (hidden, detached) using the signed Windows PowerShell host
Write-Host "[maps] Starting map server on $Url ..."
$proc = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-WindowStyle","Hidden","-File",$ServerScript,"-Port",$Port `
    -PassThru -WindowStyle Hidden

# 4. Wait for it to come up
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 400
    try {
        $r = Invoke-WebRequest -Uri "$Url" -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}

if ($ready) {
    Write-Host "[maps] Server is up."
    Write-Host ""
    Write-Host "  Open this address in your web browser:"
    Write-Host "      $Url"
    Write-Host ""
    # Open the default browser for the (non-technical) user.
    try { Start-Process $Url | Out-Null } catch { }
    Write-Host "[maps] (A browser window should open automatically.)"
} else {
    Write-Warning "[maps] Server did not respond on $Url within the timeout."
    Write-Warning "[maps] You can still try opening $Url manually."
}

Write-Host "[maps] To stop the map later, use the 'Stop Survival Station' desktop shortcut."
Write-Host "========================================================"
