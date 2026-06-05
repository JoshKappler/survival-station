# start-kiwix.ps1 -- Idempotent kiwix-serve launcher for C:\Survival
# Serves all COMPLETED ZIM files in C:\Survival\zim over http://127.0.0.1:8081
# A ZIM is "complete" when no matching .zim.aria2 control file exists alongside it.
# Safe to re-run: kills any prior kiwix-serve on port 8081 before relaunching.
# Auto-serves new ZIMs on each restart because it rebuilds library.xml each time.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$KiwixDir    = "C:\Survival\bin\kiwix-tools"
$KiwixServe  = "$KiwixDir\kiwix-serve.exe"
$KiwixManage = "$KiwixDir\kiwix-manage.exe"
$ZimDir      = "C:\Survival\zim"
$LibraryXml  = "$ZimDir\library.xml"
$Port        = 8081
$Address     = "127.0.0.1"

# 0. Sanity checks
if (-not (Test-Path $KiwixServe))  { Write-Error "kiwix-serve.exe not found at $KiwixServe";  exit 1 }
if (-not (Test-Path $KiwixManage)) { Write-Error "kiwix-manage.exe not found at $KiwixManage"; exit 1 }
if (-not (Test-Path $ZimDir))      { New-Item -ItemType Directory -Force -Path $ZimDir | Out-Null }

# 1. Kill any existing kiwix-serve on port 8081
Write-Host "[kiwix] Checking for existing kiwix-serve on port $Port..."
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $pidList = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pidList) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "[kiwix] Stopping existing process: $($proc.Name) (PID $procId)"
            Stop-Process -Id $procId -Force
        }
    }
    Start-Sleep -Milliseconds 800
} else {
    Write-Host "[kiwix] Port $Port is free."
}

# 2. Discover completed ZIM files
# Completed = .zim file exists AND no .zim.aria2 sidecar file alongside it
Write-Host "[kiwix] Scanning for completed ZIM files in $ZimDir ..."
$allZims = Get-ChildItem -Path $ZimDir -Filter "*.zim" -File -ErrorAction SilentlyContinue
$completedZims = @()
foreach ($zim in $allZims) {
    $aria2File = "$($zim.FullName).aria2"
    if (-not (Test-Path $aria2File)) {
        $completedZims += $zim.FullName
        Write-Host "  [OK]   $($zim.Name)"
    } else {
        Write-Host "  [SKIP] $($zim.Name)  (still downloading - .aria2 present)"
    }
}
Write-Host "[kiwix] Found $($completedZims.Count) completed ZIM(s)."

# 3. Rebuild library.xml
Write-Host "[kiwix] Rebuilding library.xml ..."

# Always start fresh so removed/replaced ZIMs do not linger
if (Test-Path $LibraryXml) { Remove-Item $LibraryXml -Force }

if ($completedZims.Count -eq 0) {
    Write-Host "[kiwix] No completed ZIMs yet -- starting with empty catalog."
    # Write a minimal valid library XML so kiwix-serve starts cleanly
    Set-Content -Path $LibraryXml -Encoding UTF8 `
        -Value '<?xml version="1.0" encoding="UTF-8"?><library version="20110515"></library>'
} else {
    # kiwix-manage creates the file on first "add" if it does not exist
    foreach ($zimPath in $completedZims) {
        Write-Host "  Adding: $(Split-Path $zimPath -Leaf)"
        $result = & $KiwixManage $LibraryXml add $zimPath 2>&1
        $result | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "kiwix-manage returned exit code $LASTEXITCODE for $zimPath -- skipping"
        }
    }
}

if (-not (Test-Path $LibraryXml)) {
    Write-Error "library.xml was not created. Cannot start kiwix-serve."
    exit 1
}
Write-Host "[kiwix] library.xml written: $LibraryXml"

# 4. Launch kiwix-serve
Write-Host "[kiwix] Launching kiwix-serve on http://$Address`:$Port ..."
$proc = Start-Process `
    -FilePath $KiwixServe `
    -ArgumentList "--port", $Port, "--address", $Address, "--library", $LibraryXml `
    -PassThru `
    -WindowStyle Hidden

Start-Sleep -Seconds 2

if ($proc.HasExited) {
    Write-Error "[kiwix] kiwix-serve exited immediately (exit code $($proc.ExitCode)). Check library.xml."
    exit 1
}

Write-Host "[kiwix] kiwix-serve started (PID $($proc.Id))."
Write-Host "[kiwix] Catalog: http://$Address`:$Port"
Write-Host "[kiwix] Books served: $($completedZims.Count)"
Write-Host "[kiwix] Re-run this script after downloads complete to add new ZIMs automatically."
