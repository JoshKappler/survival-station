<#
  Survival Station - STOP helper  (reliable + visible)
  --------------------------------------------------------------------------
  Stops the local service processes (the Hub on :8080, the Encyclopedia on
  :8081, and the Maps server on :8082), closes the Survival Station browser
  window, and shows a clear confirmation so you KNOW it worked. It leaves the
  Ollama AI engine alone and never touches downloads. Safe to run any time.

  Why this needed fixing: the Maps server runs on Windows' kernel HTTP service,
  so port 8082 is "owned" by the System process (PID 4). The old script tried
  to stop PID 4 (which silently fails - you can't), so Maps never stopped and
  nothing visible happened. This version stops the right processes and tells you.
#>
$ErrorActionPreference = 'Continue'
$LogFile = 'C:\Survival\logs\station.log'
function Log([string]$m){ try { Add-Content -Path $LogFile -Value ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) -Encoding utf8 } catch {} }
Log 'Stop helper invoked.'

$stopped = New-Object System.Collections.Generic.List[string]

# 1) Close the Survival Station browser window (Chrome or Edge opened with --app on the Hub).
try {
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'app=http://localhost:8080' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Log "Closed browser window (PID $($_.ProcessId))." }
} catch {}

# 2) Stop the Hub (:8080, python) and Encyclopedia (:8081, kiwix-serve) by port owner.
foreach ($port in 8080, 8081) {
  try {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
      $procId = [int]$c.OwningProcess
      if ($procId -le 4) { continue }   # never touch System/Idle
      $pr = Get-Process -Id $procId -ErrorAction SilentlyContinue
      if ($pr) {
        $nm = $pr.ProcessName
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        $stopped.Add($nm) | Out-Null
        Log "Stopped $nm on port $port (PID $procId)."
      }
    }
  } catch {}
}

# 3) Stop the Maps server (:8082). Its port is owned by System (kernel HTTP),
#    so stop the PowerShell process that hosts maps-server.ps1 instead.
try {
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'maps-server\.ps1' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped.Add('maps') | Out-Null; Log "Stopped maps-server (PID $($_.ProcessId))." }
} catch {}

# 4) Tell the user, clearly, with an auto-closing message box.
if ($stopped.Count -gt 0) {
  $msg = "Survival Station stopped."
} else {
  $msg = "Survival Station was not running."
}
Log $msg
try {
  $body = "$msg`n`nTo start it again, double-click the green`n'Survival Station - START HERE' icon on the desktop."
  (New-Object -ComObject WScript.Shell).Popup($body, 7, 'Survival Station', 0x40) | Out-Null
} catch {
  Write-Host $msg -ForegroundColor Green
  Start-Sleep -Seconds 2
}
