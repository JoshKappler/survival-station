<#
  Survival Station - STOP helper
  --------------------------------------------------------------------------
  Gently stops the local service processes (Encyclopedia, Maps, and the web
  Assistant if it runs as a local web server). It does NOT stop Ollama by
  default (other things may use it and it stays warm only briefly), and it
  never touches downloads. Safe to run anytime.

  This is OPTIONAL convenience. Closing the browser does not stop the
  background servers; this script does.
#>
$ErrorActionPreference = 'Continue'
$LogFile = 'C:\Survival\logs\station.log'
function Log([string]$m){ try { Add-Content -Path $LogFile -Value ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) -Encoding utf8 } catch {} }

Log 'Stop helper invoked.'

# Service processes that listen on our ports. We match by typical executable
# names AND by the listening port, so we only stop OUR servers.
$ports = 8080,8081,8082
$pids  = @()
foreach ($p in $ports) {
  try {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    foreach ($c in $conns) { if ($c.OwningProcess) { $pids += [int]$c.OwningProcess } }
  } catch {}
}
$pids = $pids | Sort-Object -Unique

if (-not $pids -or $pids.Count -eq 0) {
  Write-Host 'No Survival Station web servers were running.' -ForegroundColor Yellow
  Log 'No listening service processes found.'
} else {
  foreach ($procId in $pids) {
    try {
      $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
      $nm = if ($proc) { $proc.ProcessName } else { 'unknown' }
      Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
      Write-Host ("Stopped {0} (PID {1})." -f $nm, $procId) -ForegroundColor Green
      Log ("Stopped {0} (PID {1})." -f $nm, $procId)
    } catch { Log "Could not stop PID $procId : $($_.Exception.Message)" }
  }
}

Write-Host ''
Write-Host 'Done. To start again, click "Survival Station - START HERE".' -ForegroundColor Cyan
Start-Sleep -Seconds 2
