# =====================================================================
#  Survival Assistant launcher
# ---------------------------------------------------------------------
#  Starts the friendly, fully-offline chat assistant (with photo input)
#  at:   http://127.0.0.1:8080
#
#  Powered by the local Ollama server (http://localhost:11434), which
#  must already be running. Default model: gemma4:26b-a4b-it-qat (text).
#
#  WHY THIS DESIGN:
#  This machine has Windows "Smart App Control" turned ON. That security
#  feature blocks unsigned program files, which prevented Open WebUI and
#  AnythingLLM from running (their compiled pieces are unsigned). So the
#  assistant is a small, dependency-free Python web app that uses ONLY the
#  signed Python standard library — which Smart App Control allows — and
#  talks to the (signed, allowed) Ollama engine. Everything stays on this
#  computer; no internet is used.
#
#  Binds to localhost only. No admin rights required. No telemetry.
# =====================================================================

$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host '   Starting your Survival Assistant ...'       -ForegroundColor Cyan
Write-Host '   (a calm, offline helper with photo input)'  -ForegroundColor Cyan
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host ''

# --- Refresh PATH from Machine + User ---------------------------------
$machinePath = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
$userPath    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
$env:Path    = $machinePath + ';' + $userPath

# --- Locate the signed Python 3.11 (Smart App Control allows it) -------
$pythonExe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
if (-not (Test-Path $pythonExe)) {
    # Fall back to whatever 'python' resolves to on PATH.
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $pythonExe = $cmd.Source }
}
if (-not (Test-Path $pythonExe)) {
    Write-Host 'ERROR: Python 3.11 was not found.' -ForegroundColor Red
    Write-Host 'The assistant cannot start. Please contact your installer.' -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

$appScript = 'C:\Survival\app\survival-assistant.py'
if (-not (Test-Path $appScript)) {
    Write-Host "ERROR: assistant program not found at $appScript" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

# --- Environment: point at local Ollama; privacy/offline by default ----
$env:OLLAMA_BASE_URL          = 'http://localhost:11434'
$env:ASSISTANT_HOST           = '127.0.0.1'
$env:ASSISTANT_PORT           = '8080'
$env:ASSISTANT_DEFAULT_MODEL  = 'gemma4:26b-a4b-it-qat'

# Privacy / no-phone-home (belt and suspenders; the app makes no outbound
# calls anyway except to the local Ollama).
$env:ANONYMIZED_TELEMETRY     = 'False'
$env:DO_NOT_TRACK             = 'true'
$env:SCARF_NO_ANALYTICS       = 'true'

# --- Launch -----------------------------------------------------------
Write-Host 'Open your web browser to:  http://127.0.0.1:8080' -ForegroundColor Green
Write-Host '(Leave this window open while you use the assistant.)' -ForegroundColor Green
Write-Host 'Tip: the first answer can take a minute on this computer. That is normal.' -ForegroundColor DarkGray
Write-Host ''

& $pythonExe $appScript
