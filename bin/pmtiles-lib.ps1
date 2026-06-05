# pmtiles-lib.ps1 -- Pure-PowerShell PMTiles v3 reader/extractor primitives.
# No external/unsigned binaries: runs under Windows Smart App Control.
# Implements the subset of the PMTiles v3 spec needed to extract a bbox sub-pyramid
# (zoom 0..maxzoom) from a remote clustered archive via HTTP range requests, and
# write a new valid clustered single-tier PMTiles archive locally.
#
# Format reference: https://github.com/protomaps/PMTiles spec/v3/spec.md
# Algorithms (zxyToTileId Hilbert curve, directory (de)serialization) are ports of
# the official pmtiles JS reference implementation (pmtiles@4.4.1).
#
# NOTE: this library intentionally does NOT set StrictMode -- it is dot-sourced into
# callers that manage their own strictness. (Forcing StrictMode here broke callers
# that rely on lenient property/array semantics.)

# ---------------------------------------------------------------------------
# Compression (internal dirs/metadata + tiles use gzip in Protomaps builds).
# ---------------------------------------------------------------------------
function Expand-Gzip {
    param([byte[]]$Bytes)
    if ($null -eq $Bytes -or $Bytes.Length -eq 0) { return ,([byte[]]@()) }
    # gzip magic 1f 8b -> decompress; otherwise assume already raw.
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0x1f -and $Bytes[1] -eq 0x8b) {
        $ms  = New-Object System.IO.MemoryStream(,$Bytes)
        $gz  = New-Object System.IO.Compression.GZipStream($ms, [System.IO.Compression.CompressionMode]::Decompress)
        $out = New-Object System.IO.MemoryStream
        $buf = New-Object byte[] 65536
        while (($n = $gz.Read($buf, 0, $buf.Length)) -gt 0) { $out.Write($buf, 0, $n) }
        $gz.Dispose(); $ms.Dispose()
        $res = $out.ToArray(); $out.Dispose()
        return ,$res
    }
    return ,$Bytes
}

function Compress-Gzip {
    param([byte[]]$Bytes)
    $out = New-Object System.IO.MemoryStream
    $gz  = New-Object System.IO.Compression.GZipStream($out, [System.IO.Compression.CompressionMode]::Compress)
    if ($Bytes.Length -gt 0) { $gz.Write($Bytes, 0, $Bytes.Length) }
    $gz.Dispose()
    $res = $out.ToArray(); $out.Dispose()
    return ,$res
}

# ---------------------------------------------------------------------------
# Varint (LEB128 unsigned) reader/writer over a byte buffer with a cursor.
# Cursor is a 1-element array [int] so callers can advance it by reference.
# ---------------------------------------------------------------------------
function Read-Varint {
    # $Pos is passed by [ref] to a single [int] so the cursor advances across calls.
    param([byte[]]$Buf, [ref]$Pos)
    [uint64]$result = 0
    [int]$shift = 0
    [int]$p = $Pos.Value
    while ($true) {
        $b = $Buf[$p]; $p++
        $result = $result -bor ([uint64]($b -band 0x7F) -shl $shift)
        if (($b -band 0x80) -eq 0) { break }
        $shift += 7
    }
    $Pos.Value = $p
    return $result
}

function Write-Varint {
    param([System.IO.MemoryStream]$Stream, [uint64]$Value)
    do {
        $b = [byte]($Value -band 0x7F)
        $Value = $Value -shr 7
        if ($Value -ne 0) { $b = $b -bor 0x80 }
        $Stream.WriteByte($b)
    } while ($Value -ne 0)
}

# ---------------------------------------------------------------------------
# Header (127 bytes). Returns a hashtable of fields (offsets/lengths as [uint64]).
# ---------------------------------------------------------------------------
function Read-PMTHeader {
    param([byte[]]$Buf)  # at least first 127 bytes
    if ($Buf.Length -lt 127) { throw "Header buffer too small" }
    $magic = [System.Text.Encoding]::ASCII.GetString($Buf, 0, 7)
    if ($magic -ne "PMTiles") { throw "Bad magic '$magic' (not a PMTiles archive)" }
    $ver = $Buf[7]
    if ($ver -ne 3) { throw "PMTiles spec version $ver unsupported (need 3)" }
    function _u64([byte[]]$b, [int]$o) { return [System.BitConverter]::ToUInt64($b, $o) }
    function _i32([byte[]]$b, [int]$o) { return [System.BitConverter]::ToInt32($b, $o) }
    return @{
        SpecVersion        = $ver
        RootDirOffset      = _u64 $Buf 8
        RootDirLength      = _u64 $Buf 16
        MetadataOffset     = _u64 $Buf 24
        MetadataLength     = _u64 $Buf 32
        LeafDirOffset      = _u64 $Buf 40
        LeafDirLength      = _u64 $Buf 48
        TileDataOffset     = _u64 $Buf 56
        TileDataLength     = _u64 $Buf 64
        NumAddressedTiles  = _u64 $Buf 72
        NumTileEntries     = _u64 $Buf 80
        NumTileContents    = _u64 $Buf 88
        Clustered          = ($Buf[96] -eq 1)
        InternalCompression= $Buf[97]
        TileCompression    = $Buf[98]
        TileType           = $Buf[99]
        MinZoom            = $Buf[100]
        MaxZoom            = $Buf[101]
        MinLon             = (_i32 $Buf 102) / 1e7
        MinLat             = (_i32 $Buf 106) / 1e7
        MaxLon             = (_i32 $Buf 110) / 1e7
        MaxLat             = (_i32 $Buf 114) / 1e7
        CenterZoom         = $Buf[118]
        CenterLon          = (_i32 $Buf 119) / 1e7
        CenterLat          = (_i32 $Buf 123) / 1e7
    }
}

# Build a 127-byte header from a hashtable spec (writer side).
function Write-PMTHeader {
    param([hashtable]$H)
    $b = New-Object byte[] 127
    [System.Text.Encoding]::ASCII.GetBytes("PMTiles").CopyTo($b, 0)
    $b[7] = 3
    function _pu64([byte[]]$dst, [int]$o, [uint64]$v) { [System.BitConverter]::GetBytes([uint64]$v).CopyTo($dst, $o) }
    function _pi32([byte[]]$dst, [int]$o, [int]$v)    { [System.BitConverter]::GetBytes([int]$v).CopyTo($dst, $o) }
    _pu64 $b 8  $H.RootDirOffset
    _pu64 $b 16 $H.RootDirLength
    _pu64 $b 24 $H.MetadataOffset
    _pu64 $b 32 $H.MetadataLength
    _pu64 $b 40 $H.LeafDirOffset
    _pu64 $b 48 $H.LeafDirLength
    _pu64 $b 56 $H.TileDataOffset
    _pu64 $b 64 $H.TileDataLength
    _pu64 $b 72 $H.NumAddressedTiles
    _pu64 $b 80 $H.NumTileEntries
    _pu64 $b 88 $H.NumTileContents
    $b[96]  = [byte]($(if ($H.Clustered) { 1 } else { 0 }))
    $b[97]  = [byte]$H.InternalCompression
    $b[98]  = [byte]$H.TileCompression
    $b[99]  = [byte]$H.TileType
    $b[100] = [byte]$H.MinZoom
    $b[101] = [byte]$H.MaxZoom
    _pi32 $b 102 ([int][math]::Round($H.MinLon * 1e7))
    _pi32 $b 106 ([int][math]::Round($H.MinLat * 1e7))
    _pi32 $b 110 ([int][math]::Round($H.MaxLon * 1e7))
    _pi32 $b 114 ([int][math]::Round($H.MaxLat * 1e7))
    $b[118] = [byte]$H.CenterZoom
    _pi32 $b 119 ([int][math]::Round($H.CenterLon * 1e7))
    _pi32 $b 123 ([int][math]::Round($H.CenterLat * 1e7))
    return ,$b
}

# ---------------------------------------------------------------------------
# Directory (de)serialization. Entry = PSCustomObject TileId/Offset/Length/RunLength.
# Input bytes are the DECOMPRESSED directory blob.
# ---------------------------------------------------------------------------
function Read-Directory {
    param([byte[]]$Buf)  # decompressed
    [int]$posVal = 0
    $pos = [ref]$posVal
    $count = [int](Read-Varint $Buf $pos)
    $entries = New-Object 'System.Collections.Generic.List[object]'
    # tile ids (delta)
    $lastId = [uint64]0
    $ids = New-Object 'uint64[]' $count
    for ($i = 0; $i -lt $count; $i++) {
        $delta = Read-Varint $Buf $pos
        $lastId = $lastId + $delta
        $ids[$i] = $lastId
    }
    $runs = New-Object 'uint64[]' $count
    for ($i = 0; $i -lt $count; $i++) { $runs[$i] = Read-Varint $Buf $pos }
    $lens = New-Object 'uint64[]' $count
    for ($i = 0; $i -lt $count; $i++) { $lens[$i] = Read-Varint $Buf $pos }
    $offs = New-Object 'uint64[]' $count
    for ($i = 0; $i -lt $count; $i++) {
        $v = Read-Varint $Buf $pos
        if ($v -eq 0 -and $i -gt 0) {
            $offs[$i] = $offs[$i-1] + $lens[$i-1]
        } else {
            $offs[$i] = $v - 1
        }
    }
    for ($i = 0; $i -lt $count; $i++) {
        $entries.Add([PSCustomObject]@{
            TileId    = $ids[$i]
            RunLength = $runs[$i]
            Length    = $lens[$i]
            Offset    = $offs[$i]
        })
    }
    return $entries
}

# Serialize a list of entries (already sorted ascending by TileId) into the
# columnar varint format, then return RAW (uncompressed) bytes.
function Write-DirectoryRaw {
    param($Entries)  # IList of objects with TileId/RunLength/Length/Offset
    $ms = New-Object System.IO.MemoryStream
    $n  = $Entries.Count
    Write-Varint $ms ([uint64]$n)
    # tile id deltas
    $last = [uint64]0
    foreach ($e in $Entries) {
        Write-Varint $ms ([uint64]($e.TileId - $last))
        $last = [uint64]$e.TileId
    }
    foreach ($e in $Entries) { Write-Varint $ms ([uint64]$e.RunLength) }
    foreach ($e in $Entries) { Write-Varint $ms ([uint64]$e.Length) }
    # offsets with clustered delta encoding
    for ($i = 0; $i -lt $n; $i++) {
        $e = $Entries[$i]
        if ($i -gt 0 -and $Entries[$i-1].Offset + $Entries[$i-1].Length -eq $e.Offset -and $e.Offset -ne 0) {
            Write-Varint $ms ([uint64]0)
        } else {
            Write-Varint $ms ([uint64]($e.Offset + 1))
        }
    }
    $res = $ms.ToArray(); $ms.Dispose()
    return ,$res
}

# ---------------------------------------------------------------------------
# Hilbert curve tile id <-> z/x/y  (port of pmtiles JS reference).
# ---------------------------------------------------------------------------
function Get-TileId {
    param([int]$Z, [int]$X, [int]$Y)
    if ($Z -gt 26) { throw "zoom > 26 unsupported" }
    # acc = sum over levels below z of 4^k = ((1<<z)*(1<<z)-1)/3
    [uint64]$n = ([uint64](([uint64]1 -shl $Z) * ([uint64]1 -shl $Z)) - 1) / 3
    $rx = 0; $ry = 0
    [uint64]$d = 0
    $tx = $X; $ty = $Y
    $s = [int]([math]::Pow(2, $Z)) / 2
    while ($s -gt 0) {
        $rx = if (($tx -band $s) -gt 0) { 1 } else { 0 }
        $ry = if (($ty -band $s) -gt 0) { 1 } else { 0 }
        $d += [uint64]($s) * [uint64]($s) * [uint64]((3 * $rx) -bxor $ry)
        # rotate
        if ($ry -eq 0) {
            if ($rx -eq 1) {
                $tx = $s - 1 - $tx
                $ty = $s - 1 - $ty
            }
            $tmp = $tx; $tx = $ty; $ty = $tmp
        }
        $s = [int]($s / 2)
    }
    return $n + $d
}

# ---------------------------------------------------------------------------
# HTTP range fetch (returns byte[]). Retries a few times for resiliency.
# ---------------------------------------------------------------------------
function Get-HttpRange {
    param([string]$Url, [long]$Start, [long]$Length, [int]$Retries = 5)
    $end = $Start + $Length - 1
    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        try {
            $req = [System.Net.HttpWebRequest]::Create($Url)
            $req.Method = "GET"
            $req.AddRange($Start, $end)
            $req.Timeout = 120000
            $req.ReadWriteTimeout = 120000
            $req.UserAgent = "pmtiles-ps/1.0"
            $resp = $req.GetResponse()
            $stream = $resp.GetResponseStream()
            $out = New-Object System.IO.MemoryStream
            $buf = New-Object byte[] 65536
            while (($r = $stream.Read($buf, 0, $buf.Length)) -gt 0) { $out.Write($buf, 0, $r) }
            $stream.Close(); $resp.Close()
            $data = $out.ToArray(); $out.Dispose()
            if ($data.Length -ne $Length) {
                throw "short read: got $($data.Length) expected $Length"
            }
            return ,$data
        } catch {
            if ($attempt -eq $Retries) { throw }
            Start-Sleep -Seconds ([math]::Min(15, $attempt * 3))
        }
    }
}
