<#
  download-wikipedia.ps1 -- Resumable download of the FULL illustrated Wikipedia
  ------------------------------------------------------------------------------
  Downloads wikipedia_en_all_maxi (full articles + images, ~115 GB) into
  C:\Survival\zim using aria2c. Safe to re-run: aria2c's .aria2 control file
  lets it resume exactly where it left off, and start-kiwix.ps1 ignores the
  half-finished file (it skips any .zim that still has a .zim.aria2 sidecar)
  until the download completes.

  On successful completion it re-runs start-kiwix.ps1 so the Encyclopedia and
  the Hub search immediately begin serving the illustrated copy (with images).

  Log: C:\Survival\logs\wikipedia-download.log
#>
$ErrorActionPreference = 'Continue'

$Url = 'https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_maxi_2026-02.zim'
$Dir = 'C:\Survival\zim'
$Out = 'wikipedia_en_all_maxi_2026-02.zim'
$Log = 'C:\Survival\logs\wikipedia-download.log'

if (-not (Test-Path 'C:\Survival\logs')) { New-Item -ItemType Directory -Force -Path 'C:\Survival\logs' | Out-Null }

$aria = (Get-Command aria2c.exe -ErrorAction SilentlyContinue).Source
if (-not $aria) {
  Add-Content -Path $Log -Value ('{0}  ERROR: aria2c.exe not found on PATH.' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
  exit 1
}

Add-Content -Path $Log -Value ('{0}  ==== Wikipedia (maxi) download starting ====' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

# -c resume; 16 connections; do not pre-allocate the full 115 GB up front;
# write aria2's own progress/summary into the same log every 30s.
& $aria '-c' '-x16' '-s16' '-k1M' '--file-allocation=none' `
        '--summary-interval=30' '--log-level=notice' "--log=$Log" `
        '--max-tries=0' '--retry-wait=15' `
        '-d' $Dir '-o' $Out $Url
$code = $LASTEXITCODE

$target = Join-Path $Dir $Out
$ctrl   = $target + '.aria2'
if ($code -eq 0 -and (Test-Path $target) -and -not (Test-Path $ctrl)) {
  Add-Content -Path $Log -Value ('{0}  Download COMPLETE. Refreshing Kiwix catalog...' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
  & 'C:\Survival\bin\start-kiwix.ps1'
  Add-Content -Path $Log -Value ('{0}  Kiwix refreshed; illustrated Wikipedia now served.' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
} else {
  Add-Content -Path $Log -Value ('{0}  aria2c exited with code {1} (will resume on next run if incomplete).' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $code)
}
exit $code
