# Robust download + verify helper for the Survival library.
# Dot-source this: . C:\Survival\_dl.ps1
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 2>$null
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$global:UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
$global:ARIA = (Get-Command aria2c -ErrorAction SilentlyContinue).Source

function Test-PDF($path){
  if(-not (Test-Path $path)){ return $false }
  $len = (Get-Item $path).Length
  if($len -lt 20480){ return $false }
  try {
    $fs = [System.IO.File]::OpenRead($path)
    $buf = New-Object byte[] 5
    [void]$fs.Read($buf,0,5)
    $fs.Close()
    return ((-join ($buf | ForEach-Object {[char]$_})) -eq '%PDF-')
  } catch { return $false }
}

# Download a URL to dest. Tries aria2c first, then Invoke-WebRequest. Verifies PDF if .pdf.
function Get-File($url, $dest, [switch]$IsPdf){
  if((Test-Path $dest) -and ($IsPdf)){ if(Test-PDF $dest){ Write-Output "  SKIP (already valid): $(Split-Path $dest -Leaf)"; return $true } }
  $dir = Split-Path $dest -Parent
  if(-not (Test-Path $dir)){ New-Item -ItemType Directory -Force $dir | Out-Null }
  $ok = $false
  # Attempt 1: aria2c
  if($global:ARIA){
    & $global:ARIA --quiet=true --allow-overwrite=true --auto-file-renaming=false --check-certificate=false `
      --max-tries=3 --retry-wait=2 --connect-timeout=30 --timeout=60 --max-connection-per-server=4 --split=4 `
      -U $global:UA -d $dir -o (Split-Path $dest -Leaf) $url 2>$null
    if($IsPdf){ $ok = Test-PDF $dest } else { $ok = (Test-Path $dest) -and ((Get-Item $dest).Length -gt 0) }
  }
  # Attempt 2: Invoke-WebRequest
  if(-not $ok){
    try {
      Invoke-WebRequest -Uri $url -OutFile $dest -UserAgent $global:UA -TimeoutSec 120 -MaximumRedirection 6 -ErrorAction Stop
      if($IsPdf){ $ok = Test-PDF $dest } else { $ok = (Test-Path $dest) -and ((Get-Item $dest).Length -gt 0) }
    } catch { $ok = $false }
  }
  if($ok){ Write-Output ("  OK  {0,8:N0}KB  {1}" -f ((Get-Item $dest).Length/1KB), (Split-Path $dest -Leaf)) }
  else { if(Test-Path $dest){ Remove-Item $dest -Force -ErrorAction SilentlyContinue }; Write-Output "  FAIL: $(Split-Path $dest -Leaf)  <- $url" }
  return $ok
}

# Download from archive.org item, resolving filename if not supplied (largest PDF).
function Get-IA($id, $dest, $fname=$null){
  if((Test-Path $dest) -and (Test-PDF $dest)){ Write-Output "  SKIP (valid): $(Split-Path $dest -Leaf)"; return $true }
  if(-not $fname){
    try {
      $m = Invoke-RestMethod -Uri "https://archive.org/metadata/$id" -UserAgent $global:UA -TimeoutSec 40
      $p = $m.files | Where-Object { $_.name -match '\.pdf$' } | Sort-Object {[int64]$_.size} -Descending | Select-Object -First 1
      $fname = $p.name
    } catch { Write-Output "  META FAIL $id"; return $false }
  }
  if(-not $fname){ Write-Output "  NO PDF in $id"; return $false }
  $enc = ($fname -split '/' | ForEach-Object {[uri]::EscapeDataString($_)}) -join '/'
  $url = "https://archive.org/download/$id/$enc"
  return (Get-File $url $dest -IsPdf)
}
Write-Output "Helpers loaded. aria2c: $global:ARIA"
