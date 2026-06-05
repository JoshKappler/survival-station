# extract-us-pmtiles.ps1
# Pure-PowerShell PMTiles extractor: builds a US sub-pyramid (z0..MaxZoom) from a
# remote clustered Protomaps planet build via HTTP range requests, writing a valid
# clustered single/two-tier PMTiles archive at the output path.
#
# Runs under Windows Smart App Control (no unsigned binaries). Long-running: intended
# to be launched in the background. Writes progress to a log and a .progress json so a
# separate process can report status. Output is written to <Out>.partial then renamed.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File extract-us-pmtiles.ps1 `
#       -SourceUrl https://build.protomaps.com/20260604.pmtiles `
#       -Out C:\Survival\maps\us.pmtiles `
#       -MinLon -125.0 -MinLat 24.0 -MaxLon -66.5 -MaxLat 49.5 -MaxZoom 12

param(
    [Parameter(Mandatory=$true)][string]$SourceUrl,
    [Parameter(Mandatory=$true)][string]$Out,
    [double]$MinLon = -125.0,
    [double]$MinLat = 24.0,
    [double]$MaxLon = -66.5,
    [double]$MaxLat = 49.5,
    [int]$MaxZoom = 12,
    [int]$CoalesceGap = 1048576   # bytes: merge tile reads within this gap into one request
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"
. "C:\Survival\bin\pmtiles-lib.ps1"

$logPath  = [System.IO.Path]::ChangeExtension($Out, ".extract.log")
$progPath = "$Out.progress.json"
$partial  = "$Out.partial"

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}
function Progress($state, $extra) {
    $obj = @{ state=$state; time=(Get-Date -Format "s") } + $extra
    ($obj | ConvertTo-Json -Compress) | Set-Content -Path $progPath -Encoding UTF8
}

New-Item -ItemType Directory -Force (Split-Path $Out) | Out-Null
Set-Content -Path $logPath -Value "" -Encoding UTF8
Log "=== Extract start ==="
Log "Source=$SourceUrl"
Log "Out=$Out  bbox=[$MinLon,$MinLat,$MaxLon,$MaxLat]  maxZoom=$MaxZoom"
Progress "starting" @{ maxZoom=$MaxZoom }

# ---- slippy tile range math ----
function LonToX([double]$lon,[int]$z){ [int][math]::Floor((($lon+180)/360)*[math]::Pow(2,$z)) }
function LatToY([double]$lat,[int]$z){
    $r=$lat*[math]::PI/180
    $y=[int][math]::Floor((1-([math]::Log([math]::Tan($r)+1/[math]::Cos($r))/[math]::PI))/2*[math]::Pow(2,$z))
    return $y
}

# ---- 1. header + root directory ----
Log "Fetching header + root dir (16384 bytes)..."
$head = Get-HttpRange -Url $SourceUrl -Start 0 -Length 16384
$H = Read-PMTHeader $head
Log ("Header OK: clustered={0} IC={1} TC={2} TT={3} maxZoom={4} numAddressed={5}" -f $H.Clustered,$H.InternalCompression,$H.TileCompression,$H.TileType,$H.MaxZoom,$H.NumAddressedTiles)
if (-not $H.Clustered) { throw "Source is not clustered; extraction requires a clustered archive." }
if ($H.InternalCompression -ne 2) { Log "WARN: internal compression != gzip ($($H.InternalCompression))" }
if ($MaxZoom -gt $H.MaxZoom) { $MaxZoom = $H.MaxZoom; Log "Clamped MaxZoom to source max $($H.MaxZoom)" }

$rootComp = New-Object byte[] ([int]$H.RootDirLength)
[Array]::Copy($head, [int]$H.RootDirOffset, $rootComp, 0, [int]$H.RootDirLength)
$root = Read-Directory (Expand-Gzip $rootComp)
Log ("Root dir: {0} entries" -f $root.Count)

# Fetch metadata blob (keep as-is, gzip'd) to copy into output.
Log "Fetching metadata..."
$metaComp = Get-HttpRange -Url $SourceUrl -Start ([long]$H.MetadataOffset) -Length ([long]$H.MetadataLength)
Log ("Metadata: {0} bytes" -f $metaComp.Length)

# ---- 2. compute needed tile ids per zoom (bbox sub-pyramid) ----
Log "Computing needed tile ids for z0..$MaxZoom ..."
# Store as a sorted set of tile ids. Use a generic List then sort+unique.
$needed = New-Object 'System.Collections.Generic.List[uint64]'
for ($z=0; $z -le $MaxZoom; $z++) {
    $x0=LonToX $MinLon $z; $x1=LonToX $MaxLon $z
    $y0=LatToY $MaxLat $z; $y1=LatToY $MinLat $z
    if ($x0 -gt $x1){$t=$x0;$x0=$x1;$x1=$t}
    if ($y0 -gt $y1){$t=$y0;$y0=$y1;$y1=$t}
    $maxIdx=[int][math]::Pow(2,$z)-1
    if($x0 -lt 0){$x0=0}; if($y0 -lt 0){$y0=0}
    if($x1 -gt $maxIdx){$x1=$maxIdx}; if($y1 -gt $maxIdx){$y1=$maxIdx}
    for ($x=$x0; $x -le $x1; $x++) {
        for ($y=$y0; $y -le $y1; $y++) {
            $needed.Add((Get-TileId $z $x $y))
        }
    }
}
$arr = $needed.ToArray()
[Array]::Sort($arr)
# unique
$uniq = New-Object 'System.Collections.Generic.List[uint64]'
$prev = [uint64]::MaxValue
foreach ($id in $arr) { if ($id -ne $prev) { $uniq.Add($id); $prev=$id } }
Log ("Needed tile ids: {0} (unique)" -f $uniq.Count)
Progress "resolving" @{ neededTiles=$uniq.Count; maxZoom=$MaxZoom }

# ---- 3. resolve tile ids -> source (offset,length) via leaf dirs ----
# Root entries are leaf pointers (RL=0) sorted by TileId. The leaf at index i covers
# tile ids [root[i].TileId, root[i+1].TileId). For tiles whose id >= last leaf TileId,
# the last leaf covers them. We bucket needed ids by leaf, fetch each needed leaf once.
Log "Bucketing needed ids by leaf directory..."
$rootIds = New-Object 'uint64[]' $root.Count
for ($i=0; $i -lt $root.Count; $i++){ $rootIds[$i]=$root[$i].TileId }

function Find-LeafIndex([uint64]$id) {
    # largest index with rootIds[index] <= id
    $lo=0; $hi=$rootIds.Length-1; $ans=0
    while ($lo -le $hi) {
        $mid=[int](($lo+$hi)/2)
        if ($rootIds[$mid] -le $id) { $ans=$mid; $lo=$mid+1 } else { $hi=$mid-1 }
    }
    return $ans
}

# group needed ids -> leaf index
$byLeaf = @{}
foreach ($id in $uniq) {
    $li = Find-LeafIndex $id
    if (-not $byLeaf.ContainsKey($li)) { $byLeaf[$li] = New-Object 'System.Collections.Generic.List[uint64]' }
    $byLeaf[$li].Add($id)
}
Log ("Leaves to fetch: {0}" -f $byLeaf.Keys.Count)

# Resolve needed tile ids to source (offset,length) using a TWO-POINTER MERGE per
# leaf (both the needed-id list and the leaf entries are sorted ascending). Results
# go into PARALLEL PRIMITIVE ARRAYS (no per-tile PSCustomObject -> ~100x faster).
# Because leaves are processed in ascending index order and ids within each leaf are
# ascending, the resolved arrays come out globally sorted by TileId (clustered order).
$capacity   = $uniq.Count
$resTileId  = New-Object 'uint64[]' $capacity
$resSrcOff  = New-Object 'long[]'   $capacity
$resLen     = New-Object 'int[]'    $capacity
$resCount   = 0

$leafKeys = $byLeaf.Keys | Sort-Object
$leafDone = 0
foreach ($li in $leafKeys) {
    $entry = $root[$li]
    $leafOff = [long]$H.LeafDirOffset + [long]$entry.Offset
    $leafComp = Get-HttpRange -Url $SourceUrl -Start $leafOff -Length ([long]$entry.Length)
    $leaf = Read-Directory (Expand-Gzip $leafComp)
    $lc = $leaf.Count
    # snapshot leaf columns into typed arrays for fast indexed access
    $lId = New-Object 'uint64[]' $lc
    $lRun= New-Object 'uint64[]' $lc
    $lLen= New-Object 'int[]'    $lc
    $lOff= New-Object 'long[]'   $lc
    for ($k=0; $k -lt $lc; $k++){ $e=$leaf[$k]; $lId[$k]=$e.TileId; $lRun[$k]=$e.RunLength; $lLen[$k]=[int]$e.Length; $lOff[$k]=[long]$e.Offset }

    $ids = $byLeaf[$li]
    $ni  = $ids.Count
    $p = 0          # pointer into leaf entries
    $tdOff = [long]$H.TileDataOffset
    for ($q=0; $q -lt $ni; $q++) {
        $id = $ids[$q]
        # advance leaf pointer until entry covers or passes id
        while ($p -lt $lc -and ($lId[$p] + [uint64]([math]::Max(1,$lRun[$p]))) -le $id) { $p++ }
        if ($p -ge $lc) { break }
        if ($id -ge $lId[$p]) {
            $run = $lRun[$p]
            if ($run -gt 0 -and $id -lt ($lId[$p] + $run)) {
                # tile exists in this RL>0 entry (entries share one source blob)
                $resTileId[$resCount] = $id
                $resSrcOff[$resCount] = $tdOff + $lOff[$p]
                $resLen[$resCount]    = $lLen[$p]
                $resCount++
            }
            # if run==0 (nested leaf) we skip -- not expected at 2-tier; ids fall through
        }
        # id < lId[$p]  => no tile (ocean/empty), skip
    }
    $leafDone++
    Log ("  leaf {0}/{1} done; resolved tiles so far {2}" -f $leafDone,$leafKeys.Count,$resCount)
    Progress "resolving" @{ neededTiles=$uniq.Count; leavesDone=$leafDone; leavesTotal=$leafKeys.Count; resolvedTiles=$resCount; maxZoom=$MaxZoom }
}
Log ("Resolved {0} existing tiles (of {1} candidate ids)" -f $resCount, $uniq.Count)
if ($resCount -eq 0) { throw "No tiles resolved -- aborting." }

# ---- 4. fetch tile blobs (coalesced) and write tile data, dedupe by source offset ----
# IMPORTANT: a clustered+deduplicated source can have a HIGHER TileId point to a LOWER
# SrcOffset (a shared blob). So SrcOffsets are NOT monotonic in TileId order. We must:
#   (a) dedupe blobs by SrcOffset (a blob may be referenced by many tiles),
#   (b) SORT the unique blobs by SrcOffset for sequential coalesced reads,
#   (c) record each blob's OUT offset keyed by its SrcOffset, so the (TileId-ordered)
#       directory can look up the correct out offset.
Log "Fetching tile blobs (coalesced ranges)..."

# (a) unique blobs by SrcOffset -> length
$blobLenOf = New-Object 'System.Collections.Generic.Dictionary[long,int]'
for ($t=0; $t -lt $resCount; $t++) {
    if (-not $blobLenOf.ContainsKey($resSrcOff[$t])) {
        $blobLenOf[$resSrcOff[$t]] = $resLen[$t]
    }
}
$uCount = $blobLenOf.Count
Log ("Unique source blobs: {0}" -f $uCount)

# (b) sorted unique offsets ascending
$uOffsets = New-Object 'long[]' $uCount
$blobLenOf.Keys.CopyTo($uOffsets, 0)
[Array]::Sort($uOffsets)

# (c) map SrcOffset -> out offset (filled as we write)
$blobOutOf = New-Object 'System.Collections.Generic.Dictionary[long,long]'

$outFs = [System.IO.File]::Open($partial + ".tiledata", [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
[long]$outPos = 0
$nBlobs = $uCount
$i = 0
$fetchedBytes = 0L
$lastLogPct = -1
while ($i -lt $nBlobs) {
    $runStart = $uOffsets[$i]
    $runEnd   = $runStart + $blobLenOf[$uOffsets[$i]]   # exclusive
    $j = $i + 1
    while ($j -lt $nBlobs) {
        $nextStart = $uOffsets[$j]
        if ($nextStart - $runEnd -le $CoalesceGap) {
            $ne = $nextStart + $blobLenOf[$uOffsets[$j]]
            if ($ne -gt $runEnd) { $runEnd = $ne }
            $j++
        } else { break }
    }
    $runLen = $runEnd - $runStart
    $chunk = Get-HttpRange -Url $SourceUrl -Start $runStart -Length $runLen
    $fetchedBytes += $runLen
    for ($k=$i; $k -lt $j; $k++) {
        $off = $uOffsets[$k]
        $len = $blobLenOf[$off]
        $rel = [int]($off - $runStart)
        $outFs.Write($chunk, $rel, $len)
        $blobOutOf[$off] = $outPos
        $outPos += $len
    }
    $i = $j
    $pct = [int]([math]::Floor(100.0*$i/$nBlobs))
    if ($pct -ne $lastLogPct) {
        $lastLogPct = $pct
        Log ("  tiles written {0}/{1} ({2}%)  outBytes={3}  fetched={4}MB" -f $i,$nBlobs,$pct,$outPos,[math]::Round($fetchedBytes/1MB,0))
        Progress "downloading" @{ blobsDone=$i; blobsTotal=$nBlobs; outBytes=$outPos; fetchedMB=[math]::Round($fetchedBytes/1MB,0); maxZoom=$MaxZoom }
    }
}
$outFs.Close()
Log ("Tile data written: {0} bytes ({1} GB), fetched {2} GB over the wire" -f $outPos,[math]::Round($outPos/1GB,2),[math]::Round($fetchedBytes/1GB,2))

# ---- 5. build output directory entries (ascending TileId) ----
Log "Building output directory..."
$entries = New-Object 'System.Collections.Generic.List[object]'
for ($t=0; $t -lt $resCount; $t++) {
    $entries.Add([PSCustomObject]@{
        TileId    = $resTileId[$t]
        RunLength = [uint64]1
        Length    = [uint64]$resLen[$t]
        Offset    = [uint64]$blobOutOf[$resSrcOff[$t]]
    })
}

# Decide directory layout: try single root dir; if compressed > 16257 bytes, split into leaves.
$rootRawOut = Write-DirectoryRaw $entries
$rootGzOut  = Compress-Gzip $rootRawOut
Log ("Single-tier root dir compressed size: {0} bytes (limit 16257)" -f $rootGzOut.Length)

$useLeaves = $rootGzOut.Length -gt 16257
$leafSection = New-Object System.IO.MemoryStream
$rootEntriesOut = $entries
if ($useLeaves) {
    Log "Root too large -> building leaf directories."
    # Partition entries into leaves of N entries each so each leaf compresses < 16257
    # and the resulting root (pointers) also fits. Choose chunk size adaptively.
    $chunkSize = 5500
    while ($true) {
        $leafPtrs = New-Object 'System.Collections.Generic.List[object]'
        $leafSection = New-Object System.IO.MemoryStream
        for ($s=0; $s -lt $entries.Count; $s += $chunkSize) {
            $cnt = [math]::Min($chunkSize, $entries.Count - $s)
            $slice = New-Object 'System.Collections.Generic.List[object]'
            for ($q=0; $q -lt $cnt; $q++){ $slice.Add($entries[$s+$q]) }
            $leafRaw = Write-DirectoryRaw $slice
            $leafGz  = Compress-Gzip $leafRaw
            $leafOffset = $leafSection.Position
            $leafSection.Write($leafGz, 0, $leafGz.Length)
            $leafPtrs.Add([PSCustomObject]@{
                TileId    = [uint64]$slice[0].TileId
                RunLength = [uint64]0
                Length    = [uint64]$leafGz.Length
                Offset    = [uint64]$leafOffset
            })
        }
        $rootRawOut = Write-DirectoryRaw $leafPtrs
        $rootGzOut  = Compress-Gzip $rootRawOut
        Log ("  chunkSize={0} -> {1} leaves, root ptr dir {2} bytes" -f $chunkSize,$leafPtrs.Count,$rootGzOut.Length)
        if ($rootGzOut.Length -le 16257) { break }
        $chunkSize = [int]($chunkSize * 1.7)
        if ($chunkSize -gt $entries.Count) { throw "Cannot fit root directory even as single leaf set." }
    }
} else {
    Log "Single-tier directory fits in root."
}
$leafBytes = $leafSection.ToArray()
$leafSection.Dispose()

# ---- 6. assemble final file: header(127) + rootDir + metadata + leafDirs + tileData ----
Log "Assembling final PMTiles file..."
[long]$rootOffset = 127
[long]$metaOffset = $rootOffset + $rootGzOut.Length
[long]$leafOffsetSection = $metaOffset + $metaComp.Length
[long]$tileOffsetSection = $leafOffsetSection + $leafBytes.Length

$numAddressed = [uint64]$entries.Count
$numEntries   = [uint64]$entries.Count   # all RL=1
$numContents  = [uint64]$uCount          # unique source blobs

# center: middle of bbox
$cLon = ($MinLon + $MaxLon)/2.0
$cLat = ($MinLat + $MaxLat)/2.0

$OH = @{
    RootDirOffset       = [uint64]$rootOffset
    RootDirLength       = [uint64]$rootGzOut.Length
    MetadataOffset      = [uint64]$metaOffset
    MetadataLength      = [uint64]$metaComp.Length
    LeafDirOffset       = [uint64]$leafOffsetSection
    LeafDirLength       = [uint64]$leafBytes.Length
    TileDataOffset      = [uint64]$tileOffsetSection
    TileDataLength      = [uint64]$outPos
    NumAddressedTiles   = $numAddressed
    NumTileEntries      = $numEntries
    NumTileContents     = $numContents
    # Not strictly "clustered": we deduplicate shared blobs and order tile data by
    # source offset, so directory offsets (in TileId order) are not monotonic. The
    # MapLibre/pmtiles.js reader reconstructs offsets directly from the directory and
    # reads this correctly. (Set false to be spec-honest.)
    Clustered           = $false
    InternalCompression = 2   # gzip
    TileCompression     = [int]$H.TileCompression
    TileType            = [int]$H.TileType
    MinZoom             = 0
    MaxZoom             = [int]$MaxZoom
    MinLon              = $MinLon
    MinLat              = $MinLat
    MaxLon              = $MaxLon
    MaxLat              = $MaxLat
    CenterZoom          = [int]([math]::Min(5,$MaxZoom))
    CenterLon           = $cLon
    CenterLat           = $cLat
}
$hdrBytes = Write-PMTHeader $OH

$final = [System.IO.File]::Open($partial, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
$final.Write($hdrBytes, 0, $hdrBytes.Length)
$final.Write($rootGzOut, 0, $rootGzOut.Length)
$final.Write($metaComp, 0, $metaComp.Length)
if ($leafBytes.Length -gt 0) { $final.Write($leafBytes, 0, $leafBytes.Length) }
# stream tile data from temp file
$td = [System.IO.File]::OpenRead($partial + ".tiledata")
$buf = New-Object byte[] 1048576
while (($n = $td.Read($buf,0,$buf.Length)) -gt 0) { $final.Write($buf,0,$n) }
$td.Close()
$final.Close()
Remove-Item ($partial + ".tiledata") -Force

# rename into place
if (Test-Path $Out) { Remove-Item $Out -Force }
Rename-Item $partial (Split-Path $Out -Leaf)
$finalSize = (Get-Item $Out).Length
Log ("DONE. Output {0}  size {1} bytes ({2} GB)" -f $Out, $finalSize, [math]::Round($finalSize/1GB,2))
Progress "done" @{ outBytes=$finalSize; tiles=$entries.Count; maxZoom=$MaxZoom; sizeGB=[math]::Round($finalSize/1GB,2) }
Write-Output "EXTRACT_COMPLETE size=$finalSize tiles=$($entries.Count)"
