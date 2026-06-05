# maps-server.ps1 -- Pure-PowerShell static HTTP server for the offline US map.
# Serves C:\Survival\maps over http://127.0.0.1:8082 with full HTTP Range support
# (required so the pmtiles.js protocol can do client-side byte-range reads of
# us.pmtiles). Uses System.Net.HttpListener (in-process .NET) so it runs under
# Windows Smart App Control with no external/unsigned binaries.
#
# Routes:
#   /                -> viewer/index.html
#   /<path>          -> file under C:\Survival\maps (viewer assets, style, fonts, sprite)
#   /us.pmtiles      -> the PMTiles archive (Range-served)
#
# CORS is permissive for localhost so the browser pmtiles protocol works.
# This script blocks (runs the listener loop); launch it via start-maps.ps1.

param(
    [int]$Port = 8082,
    [string]$Root = "C:\Survival\maps\viewer",   # web root = viewer (self-contained, relative asset paths)
    [string]$Address = "127.0.0.1"
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path $Root).Path
# The PMTiles archive lives one level up in C:\Survival\maps and is exposed at /us.pmtiles
$PMTilesPath = Join-Path (Split-Path $Root) "us.pmtiles"

$mime = @{
    ".html"="text/html; charset=utf-8"; ".htm"="text/html; charset=utf-8";
    ".js"="application/javascript; charset=utf-8"; ".mjs"="application/javascript; charset=utf-8";
    ".css"="text/css; charset=utf-8"; ".json"="application/json; charset=utf-8";
    ".pmtiles"="application/octet-stream"; ".pbf"="application/x-protobuf";
    ".png"="image/png"; ".jpg"="image/jpeg"; ".jpeg"="image/jpeg"; ".webp"="image/webp";
    ".svg"="image/svg+xml"; ".ico"="image/x-icon"; ".txt"="text/plain; charset=utf-8";
    ".woff"="font/woff"; ".woff2"="font/woff2"; ".map"="application/json"
}

function Get-Mime([string]$path) {
    $ext = [System.IO.Path]::GetExtension($path).ToLower()
    if ($mime.ContainsKey($ext)) { return $mime[$ext] }
    return "application/octet-stream"
}

$listener = New-Object System.Net.HttpListener
$prefix = "http://$Address`:$Port/"
$listener.Prefixes.Add($prefix)
try {
    $listener.Start()
} catch {
    Write-Error "Failed to bind $prefix : $($_.Exception.Message)"
    exit 1
}
Write-Host "[maps] Serving $Root at $prefix (HTTP Range enabled). Ctrl+C to stop."

while ($listener.IsListening) {
    $ctx = $null
    try { $ctx = $listener.GetContext() } catch { break }
    if ($null -eq $ctx) { continue }
    $req = $ctx.Request
    $res = $ctx.Response
    try {
        # CORS (localhost only context, but permissive headers keep the browser happy)
        $res.Headers["Access-Control-Allow-Origin"] = "*"
        $res.Headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        $res.Headers["Access-Control-Allow-Headers"] = "Range, If-Match, If-None-Match"
        $res.Headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Range, Accept-Ranges, ETag"
        $res.Headers["Accept-Ranges"] = "bytes"

        if ($req.HttpMethod -eq "OPTIONS") {
            $res.StatusCode = 204
            $res.Close()
            continue
        }

        # resolve path
        $rel = [System.Uri]::UnescapeDataString($req.Url.AbsolutePath)
        if ($rel -eq "/" -or $rel -eq "") { $rel = "/index.html" }

        # Special route: the large PMTiles archive lives outside the web root.
        if ($rel -eq "/us.pmtiles") {
            $full = $PMTilesPath
        } else {
            $relTrim = $rel.TrimStart("/")
            $full = [System.IO.Path]::GetFullPath((Join-Path $Root $relTrim))
            # path traversal guard (only enforced for in-root files)
            if (-not $full.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
                $res.StatusCode = 403; $res.Close(); continue
            }
        }
        if (-not (Test-Path $full -PathType Leaf)) {
            $res.StatusCode = 404
            $bytes = [System.Text.Encoding]::UTF8.GetBytes("404 Not Found: $rel")
            $res.OutputStream.Write($bytes,0,$bytes.Length)
            $res.Close(); continue
        }

        $res.Headers["Content-Type"] = Get-Mime $full
        $fi = New-Object System.IO.FileInfo($full)
        $total = $fi.Length
        # weak etag from size+mtime
        $etag = '"' + ("{0:x}-{1:x}" -f $total, $fi.LastWriteTimeUtc.Ticks) + '"'
        $res.Headers["ETag"] = $etag

        $rangeHeader = $req.Headers["Range"]
        $fs = [System.IO.File]::Open($full, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        try {
            if ($rangeHeader -and $rangeHeader -match "bytes=(\d*)-(\d*)") {
                $startS = $Matches[1]; $endS = $Matches[2]
                if ($startS -eq "" -and $endS -ne "") {
                    # suffix range: last N bytes
                    $len = [long]$endS
                    if ($len -gt $total) { $len = $total }
                    $start = $total - $len
                    $end = $total - 1
                } else {
                    $start = [long]$startS
                    if ($endS -eq "") { $end = $total - 1 } else { $end = [long]$endS }
                }
                if ($start -ge $total -or $start -lt 0) {
                    $res.StatusCode = 416
                    $res.Headers["Content-Range"] = "bytes */$total"
                    $res.Close(); continue
                }
                if ($end -ge $total) { $end = $total - 1 }
                $count = $end - $start + 1
                $res.StatusCode = 206
                $res.Headers["Content-Range"] = "bytes $start-$end/$total"
                $res.ContentLength64 = $count
                if ($req.HttpMethod -ne "HEAD") {
                    $fs.Seek($start, [System.IO.SeekOrigin]::Begin) | Out-Null
                    $buf = New-Object byte[] 65536
                    $remaining = $count
                    while ($remaining -gt 0) {
                        $toRead = [int][math]::Min($buf.Length, $remaining)
                        $n = $fs.Read($buf, 0, $toRead)
                        if ($n -le 0) { break }
                        $res.OutputStream.Write($buf, 0, $n)
                        $remaining -= $n
                    }
                }
            } else {
                $res.StatusCode = 200
                $res.ContentLength64 = $total
                if ($req.HttpMethod -ne "HEAD") {
                    $buf = New-Object byte[] 65536
                    while (($n = $fs.Read($buf, 0, $buf.Length)) -gt 0) {
                        $res.OutputStream.Write($buf, 0, $n)
                    }
                }
            }
        } finally {
            $fs.Close()
        }
        $res.Close()
    } catch {
        try {
            if ($_.Exception -isnot [System.Net.HttpListenerException]) {
                $res.StatusCode = 500
            }
            $res.Close()
        } catch {}
    }
}
