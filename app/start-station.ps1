<#
  Survival Station - MASTER LAUNCHER
  --------------------------------------------------------------------------
  Purpose: bring the whole offline station up with ONE click and open the
           friendly dashboard. Safe to run many times (idempotent): it will
           not double-start a service whose port is already listening, and it
           will not disturb anything already running (Ollama, downloads, etc).

  It will:
    (a) make sure Ollama is running (start it with survival-friendly env vars
        if it is not);
    (b) start each service launcher (assistant / kiwix / maps) in its own
        hidden background process, but only if its port is not already up;
    (c) show a calm "Starting..." splash;
    (d) wait (up to ~60s) for the services, then open the dashboard in Edge
        "app" mode (falls back to the default browser if Edge is missing).

  Everything is best-effort: the dashboard opens even if a service is slow,
  so the user is never left staring at a blank screen.

  Log file: C:\Survival\logs\station.log
#>

# ----- never abort the whole launcher on a single error -------------------
$ErrorActionPreference = 'Continue'

# ----- paths & constants --------------------------------------------------
$Root        = 'C:\Survival'
$AppDir      = Join-Path $Root 'app'
$BinDir      = Join-Path $Root 'bin'
$LogDir      = Join-Path $Root 'logs'
$LogFile     = Join-Path $LogDir 'station.log'
$Dashboard   = Join-Path $AppDir 'dashboard.html'
$Splash      = Join-Path $AppDir 'splash.html'
$DashboardUri = 'file:///C:/Survival/app/dashboard.html'

# Set to $true ONLY if the assistant is the WEB assistant on :8080.
# (A native-app assistant has no port to wait for; leave this $true is fine
#  because we treat 8080 as best-effort and never block on it.)
$WebAssistant = $true

# Service definitions: name, launcher script, port to check.
$Services = @(
  @{ Name = 'Assistant';    Script = (Join-Path $AppDir 'start-assistant.ps1'); Port = 8080 }
  @{ Name = 'Encyclopedia'; Script = (Join-Path $BinDir 'start-kiwix.ps1');     Port = 8081 }
  @{ Name = 'Maps';         Script = (Join-Path $BinDir 'start-maps.ps1');      Port = 8082 }
)

# ----- logging ------------------------------------------------------------
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
function Log([string]$msg) {
  $line = ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
  try { Add-Content -Path $LogFile -Value $line -Encoding utf8 } catch {}
}

Log '======================================================'
Log 'Survival Station launcher starting.'

# ----- helper: is a TCP port listening on localhost? ----------------------
# Fast, no external tools, works fully offline.
function Test-Port([int]$Port) {
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
    $ok  = $iar.AsyncWaitHandle.WaitOne(400)   # 400ms is plenty for localhost
    if ($ok -and $client.Connected) { $client.EndConnect($iar); return $true }
    return $false
  } catch { return $false }
  finally { $client.Close() }
}

# ----- locate Ollama ------------------------------------------------------
function Find-Ollama {
  $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
    'C:\Program Files\Ollama\ollama.exe',
    'C:\Program Files (x86)\Ollama\ollama.exe'
  )
  foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  return $null
}

# ----- locate Edge --------------------------------------------------------
function Find-Edge {
  $cmd = Get-Command msedge.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $candidates = @(
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
  )
  foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  return $null
}

# ----- (a) ensure Ollama is running --------------------------------------
$ollamaPort = 11434
if (Test-Port $ollamaPort) {
  Log 'Ollama already running on 11434 - leaving it alone.'
} else {
  $ollamaExe = Find-Ollama
  if ($ollamaExe) {
    Log "Starting Ollama: $ollamaExe (serve)"
    # Survival-friendly limits: keep memory small, one model, stay warm 30 min.
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    $env:OLLAMA_NUM_PARALLEL      = '1'
    $env:OLLAMA_KEEP_ALIVE        = '30m'
    # OLLAMA_HOST left default (127.0.0.1:11434) -> localhost only.
    try {
      Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden
      Log 'Ollama serve launched (hidden).'
    } catch { Log "ERROR starting Ollama: $($_.Exception.Message)" }
  } else {
    Log 'WARNING: Ollama executable not found. Assistant may not answer until installed.'
  }
}

# ----- (b) start each service if its port is not already listening --------
foreach ($svc in $Services) {
  $name = $svc.Name; $script = $svc.Script; $port = $svc.Port

  if (Test-Port $port) {
    Log "$name already listening on $port - not starting again."
    continue
  }
  if (-not (Test-Path $script)) {
    Log "NOTE: launcher for $name not found yet ($script). Skipping (another agent may add it later)."
    continue
  }

  Log "Starting $name via $script (hidden) ..."
  try {
    Start-Process -FilePath 'powershell.exe' `
      -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File', $script) `
      -WindowStyle Hidden
    Log "$name launch requested."
  } catch {
    Log "ERROR starting $name : $($_.Exception.Message)"
  }
}

# ----- (c) show the calm splash ------------------------------------------
# Try to open the splash in the default browser; if that fails, just print.
$splashShown = $false
if (Test-Path $Splash) {
  try {
    Start-Process ('file:///' + ($Splash -replace '\\','/'))
    $splashShown = $true
    Log 'Splash shown in browser.'
  } catch { Log "Could not open splash in browser: $($_.Exception.Message)" }
}
if (-not $splashShown) {
  Write-Host ''
  Write-Host '   Starting your Survival Station...' -ForegroundColor Green
  Write-Host '   Please wait - your main screen will open shortly.' -ForegroundColor Green
  Write-Host ''
}

# ----- (d) poll the service ports (best-effort, ~60s) --------------------
# We wait for the core services. The assistant (8080) is included only if it
# is the web assistant, and even then it is best-effort - we never block the
# dashboard on it.
$wanted = @(
  @{ Name = 'Encyclopedia'; Port = 8081 }
  @{ Name = 'Maps';         Port = 8082 }
)
# Always confirm Ollama too (it powers the assistant).
$wanted = @(@{ Name = 'Ollama'; Port = 11434 }) + $wanted
if ($WebAssistant) { $wanted += @{ Name = 'Assistant'; Port = 8080 } }

$deadline = (Get-Date).AddSeconds(60)
Log 'Waiting up to ~60s for services to come online...'
do {
  $allUp = $true
  $status = foreach ($w in $wanted) {
    $up = Test-Port $w.Port
    if (-not $up) { $allUp = $false }
    '{0}:{1}' -f $w.Name, ($(if ($up) { 'UP' } else { 'wait' }))
  }
  Log ('Status -> ' + ($status -join '  '))
  if ($allUp) { break }
  Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if ($allUp) { Log 'All watched services are UP.' }
else        { Log 'Timeout reached - opening dashboard anyway (services may still be starting).' }

# ----- open the dashboard in Edge app mode (fallback: default browser) ---
$edge = Find-Edge
$opened = $false
if ($edge) {
  Log "Opening dashboard in Edge app mode: $edge"
  try {
    Start-Process -FilePath $edge -ArgumentList @(
      ('--app=' + $DashboardUri),
      '--start-maximized'
    )
    $opened = $true
  } catch { Log "ERROR launching Edge app mode: $($_.Exception.Message)" }
}
if (-not $opened) {
  Log 'Edge not available - opening dashboard in default browser.'
  try {
    Start-Process $DashboardUri
    $opened = $true
  } catch {
    Log "ERROR opening dashboard in default browser: $($_.Exception.Message)"
    # Last-ditch: open the local file path directly.
    try { Start-Process $Dashboard; $opened = $true } catch {}
  }
}

if ($opened) { Log 'Dashboard opened. Launcher done.' }
else         { Log 'Could not open the dashboard by any method.' }
Log '------------------------------------------------------'
