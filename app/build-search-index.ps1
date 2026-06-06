<#
  build-search-index.ps1  --  Rebuild the offline search index.
  Run this after you add new books or manuals to C:\Survival\library so the
  Survival Station search box can find them. Safe to run any time.
#>
$ErrorActionPreference = 'Continue'
Write-Host ''
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host '   Rebuilding the Survival Station search index' -ForegroundColor Cyan
Write-Host '   (reads your books & manuals - this can take a few minutes)' -ForegroundColor Cyan
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host ''

$pythonExe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
if (-not (Test-Path $pythonExe)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $pythonExe = $cmd.Source }
}
if (-not (Test-Path $pythonExe)) {
    Write-Host 'ERROR: Python 3.11 was not found.' -ForegroundColor Red
    Read-Host 'Press Enter to close'; exit 1
}

& $pythonExe 'C:\Survival\app\build-search-index.py'

Write-Host ''
Write-Host 'Search index rebuilt. You can close this window.' -ForegroundColor Green
Start-Sleep -Seconds 3
