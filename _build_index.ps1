# Builds C:\Survival\library\index.html by scanning the folders.
$ProgressPreference='SilentlyContinue'
Add-Type -AssemblyName System.Web
$root = "C:\Survival\library"

function Test-PDF($path){
  if(-not (Test-Path $path)){ return $false }
  if((Get-Item $path).Length -lt 20480){ return $false }
  try { $fs=[IO.File]::OpenRead($path); $b=New-Object byte[] 5; [void]$fs.Read($b,0,5); $fs.Close()
    return ((-join ($b|%{[char]$_})) -eq '%PDF-') } catch { return $false }
}

# Plain-language descriptions keyed by exact filename.
$desc = @{
 # manuals
 'FM-21-76-US-Army-Survival-Manual.pdf'='The classic US Army Survival Manual. The single best all-round survival book: water, fire, food, shelter, first aid, navigation, signaling. Includes the Universal Edibility Test for plants.'
 'FM-3-05-70-Survival-2002.pdf'='The updated US Army Survival field manual (2002). A more recent companion to FM 21-76 with the same life-saving survival skills.'
 'SH-21-76-Ranger-Handbook-2011.pdf'='US Army Ranger Handbook. Field craft, patrolling, movement, planning, and survival fundamentals in a compact form.'
 'FM-4-25-11-First-Aid.pdf'='US Army First Aid manual. Clear, illustrated steps for bleeding, breathing, broken bones, burns, shock, and more.'
 'FM-21-11-First-Aid-for-Soldiers.pdf'='First Aid for Soldiers (1943). A simple, time-tested first-aid handbook covering the basics of emergency care.'
 'FM-21-10-Field-Hygiene-and-Sanitation.pdf'='Field Hygiene & Sanitation. How to stay healthy without modern plumbing: safe water, waste disposal, food safety, pest control.'
 'FM-21-76-1-Survival-Evasion-and-Recovery.pdf'='Survival, Evasion & Recovery. Quick-reference survival procedures, signaling, and finding your way back to safety.'
 # medical
 'Where-There-Is-No-Doctor.pdf'='Where There Is No Doctor. The world-famous village health handbook: diagnosing and treating illness and injury when no doctor is available.'
 'Where-There-Is-No-Dentist.pdf'='Where There Is No Dentist. How to care for teeth and gums and handle dental pain and infection without a dentist.'
 'Hesperian-First-Aid-Quick-Guide.pdf'='Hesperian First Aid quick guide. A short, plain-language reference for the most common first-aid emergencies.'
 # food-foraging
 'USDA-Complete-Guide-to-Home-Canning-2015.pdf'='USDA Complete Guide to Home Canning. The authoritative guide to safely canning and preserving food for long-term storage.'
 'Common-Weeds-of-the-United-States-USDA.pdf'='Common Weeds of the United States (USDA). Detailed drawings to help identify common plants - many edible, some harmful.'
 'Common-Edible-Mushrooms-Christensen.pdf'='Common Edible Mushrooms. An illustrated introduction to recognizing edible mushrooms. READ THE SAFETY WARNING FIRST.'
 'TM-10-420-Emergency-Food-and-Poisonous-Plants.pdf'='Emergency Food Plants & Poisonous Plants. A military guide to which wild plants you can eat and which can hurt you.'
 # shelter-skills
 'Camping-and-Woodcraft-Kephart-1910.pdf'='Camping and Woodcraft (Kephart). A timeless wilderness-living classic: camp craft, shelter, fire, cooking, tools, and gear.'
 'Knots-Splices-and-Rope-Work.html'='Knots, Splices and Rope Work. A complete classic guide to the most useful knots, lashings, and splices - vital for shelter and securing loads.'
 # land-nav (added by the maps agent; included if present & valid)
 'FM_3-25.26_Map_Reading_and_Land_Navigation_2001.pdf'='Map Reading & Land Navigation (US Army). How to read maps, use a compass, and find your way overland.'
 'TC_3-25.26_Map_Reading_and_Land_Navigation_2013_Part1.pdf'='Map Reading & Land Navigation, updated edition (Part 1). Map and compass skills for finding your way.'
 'TC_3-25.26_Map_Reading_and_Land_Navigation_2013_Part2.pdf'='Map Reading & Land Navigation, updated edition (Part 2). Continued map and compass skills.'
 'USGS_Topographic_Map_Symbols.pdf'='USGS Topographic Map Symbols. A key to the symbols used on topographic maps.'
 'USGS_How_to_Read_a_Topographic_Map_ActivitySheet.pdf'='USGS - How to Read a Topographic Map. A simple one-page introduction to topographic maps.'
 'USGS_Finding_Your_Way_With_Map_and_Compass_FS035-01.pdf'='USGS - Finding Your Way With Map and Compass. A short guide to using a map and compass together to navigate.'
 # tech-power
 'NEETS-Module-01-Matter-Energy-and-DC.pdf'='Basic Electricity (Navy NEETS 1). Introduction to electricity, energy, and direct current - start here to understand power.'
 'NEETS-Module-04-Conductors-Wiring-and-Schematics.pdf'='Wiring & Schematics (Navy NEETS 4). Electrical conductors, wiring techniques, and how to read circuit diagrams.'
 'NEETS-Module-05-Generators-and-Motors.pdf'='Generators & Motors (Navy NEETS 5). How electric generators and motors work - useful for power systems.'
 'NEETS-Module-19-Technicians-Handbook.pdf'='Technician''s Handbook (Navy NEETS 19). Handy electrical/electronic reference tables, formulas, and data.'
 'Photovoltaic-Solar-Systems-Guide-DTIC.pdf'='Photovoltaic (Solar) Systems guide. How solar panels and battery systems work, are sized, and are maintained - this PC runs on solar.'
 'TM-5-295-Water-Supply-and-Purification.pdf'='Water Supply & Water Purification (US Army). In-depth guide to finding, moving, storing, and purifying water.'
 'Safe-Water-Sanitation-and-Latrines.html'='Safe Water, Sanitation & Latrines. Plain-language how-to: make water safe to drink, build a latrine, handwashing, and well-water basics.'
 # comms
 'FM-24-18-Radio-Communications-Techniques.pdf'='Radio Communications Techniques (US Army). How to set up and operate radios, antennas, and field communications.'
 'FM-24-19-Radio-Operators-Handbook.pdf'='Radio Operator''s Handbook. Practical guide for operating radios and running communications in the field.'
 'MCRP-3-40-3C-Antenna-Handbook.pdf'='Antenna Handbook (USMC). How to build and use effective antennas to extend your radio range.'
 'NEETS-Module-10-Wave-Propagation-and-Antennas.pdf'='Wave Propagation & Antennas (Navy NEETS 10). How radio waves travel and how antennas work.'
 'Radio-Morse-NATO-Frequencies-Reference.html'='Communications Quick Reference. Morse code, NATO phonetic alphabet, NOAA weather frequencies, and FRS/GMRS/MURS/CB channels - all on one page.'
 # reference
 'FEMA-Are-You-Ready.pdf'='FEMA "Are You Ready?" The full in-depth US guide to preparing for and surviving disasters of every kind.'
 'Emergency-Preparedness-Checklists.html'='Emergency Preparedness Checklists. Plain-language supply lists and household plans (Ready.gov / FEMA / CDC themes).'
 'Units-and-Measures-Conversion.html'='Units & Measures Conversion Sheet. Quick conversions for cooking, building, medicine, and water - plus water-disinfection amounts.'
 'Signaling-and-SOS-Reference.html'='Signaling & SOS Reference. How to call for help and be found: SOS, whistle/mirror signals, and ground-to-air codes.'
 'Seasonal-Planting-Calendar.html'='Seasonal Planting Calendar. When to plant what, calorie-priority crops, and basic seed-saving for growing your own food.'
 # safety readmes
 'READ-ME-SAFETY.txt'='SAFETY - READ THIS FIRST.'
}

# Friendly human titles shown as the clickable link text (href still uses the real filename).
$title = @{
 'FM-21-76-US-Army-Survival-Manual.pdf'='US Army Survival Manual (FM 21-76)'
 'FM-3-05-70-Survival-2002.pdf'='US Army Survival (FM 3-05.70, 2002)'
 'SH-21-76-Ranger-Handbook-2011.pdf'='US Army Ranger Handbook'
 'FM-4-25-11-First-Aid.pdf'='US Army First Aid (FM 4-25.11)'
 'FM-21-11-First-Aid-for-Soldiers.pdf'='First Aid for Soldiers (FM 21-11)'
 'FM-21-10-Field-Hygiene-and-Sanitation.pdf'='Field Hygiene & Sanitation (FM 21-10)'
 'FM-21-76-1-Survival-Evasion-and-Recovery.pdf'='Survival, Evasion & Recovery (FM 21-76-1)'
 'Where-There-Is-No-Doctor.pdf'='Where There Is No Doctor'
 'Where-There-Is-No-Dentist.pdf'='Where There Is No Dentist'
 'Hesperian-First-Aid-Quick-Guide.pdf'='Hesperian First Aid Quick Guide'
 'USDA-Complete-Guide-to-Home-Canning-2015.pdf'='USDA Complete Guide to Home Canning'
 'Common-Weeds-of-the-United-States-USDA.pdf'='Common Weeds of the United States (USDA)'
 'Common-Edible-Mushrooms-Christensen.pdf'='Common Edible Mushrooms'
 'TM-10-420-Emergency-Food-and-Poisonous-Plants.pdf'='Emergency Food & Poisonous Plants (TM 10-420)'
 'Camping-and-Woodcraft-Kephart-1910.pdf'='Camping and Woodcraft (Kephart)'
 'Knots-Splices-and-Rope-Work.html'='Knots, Splices and Rope Work'
 'FM_3-25.26_Map_Reading_and_Land_Navigation_2001.pdf'='Map Reading & Land Navigation (FM 3-25.26)'
 'TC_3-25.26_Map_Reading_and_Land_Navigation_2013_Part1.pdf'='Map Reading & Land Navigation 2013 (Part 1)'
 'TC_3-25.26_Map_Reading_and_Land_Navigation_2013_Part2.pdf'='Map Reading & Land Navigation 2013 (Part 2)'
 'USGS_Topographic_Map_Symbols.pdf'='USGS Topographic Map Symbols'
 'USGS_How_to_Read_a_Topographic_Map_ActivitySheet.pdf'='How to Read a Topographic Map (USGS)'
 'USGS_Finding_Your_Way_With_Map_and_Compass_FS035-01.pdf'='Finding Your Way With Map & Compass (USGS)'
 'NEETS-Module-01-Matter-Energy-and-DC.pdf'='Basic Electricity - Matter, Energy & DC (NEETS 1)'
 'NEETS-Module-04-Conductors-Wiring-and-Schematics.pdf'='Wiring & Schematics (NEETS 4)'
 'NEETS-Module-05-Generators-and-Motors.pdf'='Generators & Motors (NEETS 5)'
 'NEETS-Module-19-Technicians-Handbook.pdf'='Technician''s Handbook (NEETS 19)'
 'Photovoltaic-Solar-Systems-Guide-DTIC.pdf'='Solar (Photovoltaic) Systems Guide'
 'TM-5-295-Water-Supply-and-Purification.pdf'='Water Supply & Purification (TM 5-295)'
 'Safe-Water-Sanitation-and-Latrines.html'='Safe Water, Sanitation & Latrines'
 'FM-24-18-Radio-Communications-Techniques.pdf'='Radio Communications Techniques (FM 24-18)'
 'FM-24-19-Radio-Operators-Handbook.pdf'='Radio Operator''s Handbook (FM 24-19)'
 'MCRP-3-40-3C-Antenna-Handbook.pdf'='Antenna Handbook (MCRP 3-40.3C)'
 'NEETS-Module-10-Wave-Propagation-and-Antennas.pdf'='Wave Propagation & Antennas (NEETS 10)'
 'Radio-Morse-NATO-Frequencies-Reference.html'='Morse, NATO Phonetic & Radio Frequencies'
 'FEMA-Are-You-Ready.pdf'='FEMA - Are You Ready? (full guide)'
 'Emergency-Preparedness-Checklists.html'='Emergency Preparedness Checklists'
 'Units-and-Measures-Conversion.html'='Units & Measures Conversion Sheet'
 'Signaling-and-SOS-Reference.html'='Signaling & SOS Reference'
 'Seasonal-Planting-Calendar.html'='Seasonal Planting Calendar'
 'READ-ME-SAFETY.txt'='*** SAFETY - READ THIS FIRST ***'
}

# Category display config (order, heading, blurb, icon)
$cats = [ordered]@{
 'manuals'        = @('Survival Manuals','Start here. Complete, trusted guides that cover almost everything - especially the US Army Survival Manual.')
 'medical'        = @('Medical & First Aid','How to help a sick or injured person when no doctor is near. Read the safety note first, then find the problem in the books.')
 'food-foraging'  = @('Food & Foraging','Finding, identifying, growing, and preserving food. WARNING: never eat a wild plant or mushroom on a single source - read the safety note.')
 'shelter-skills' = @('Shelter, Knots & Field Skills','Staying warm, dry, and safe outdoors: shelter, fire, knots, woodcraft, and finding your way.')
 'tech-power'     = @('Power, Water & Tech','Keeping electricity and water going: solar and batteries, basic wiring, and making water safe.')
 'comms'          = @('Communications','Radios, antennas, Morse code, and the charts you need to call for help and get information.')
 'reference'      = @('Emergency Reference','Preparedness checklists, conversions, signaling, planting, and the full FEMA readiness guide.')
}

$sb = New-Object System.Text.StringBuilder
[void]$sb.Append(@'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Survival Reference Library</title>
<style>
  body{font-family:Georgia,'Times New Roman',serif;background:#f4efe2;color:#1a1a1a;margin:0;padding:0;font-size:20px;line-height:1.5;}
  .wrap{max-width:1000px;margin:0 auto;padding:24px;}
  header{background:#7a2d00;color:#fff;padding:28px 24px;border-radius:0 0 12px 12px;}
  header h1{margin:0;font-size:42px;}
  header p{margin:10px 0 0;font-size:21px;line-height:1.45;}
  .toc{background:#fff;border:2px solid #c8b89a;border-radius:10px;padding:16px 20px;margin:24px 0;}
  .toc h2{margin:0 0 8px;font-size:22px;color:#7a2d00;}
  .toc a{display:inline-block;margin:5px 14px 5px 0;font-size:19px;color:#0a3d62;text-decoration:none;font-weight:bold;}
  .toc a:hover{text-decoration:underline;}
  section{background:#fff;border:2px solid #c8b89a;border-radius:10px;padding:8px 22px 18px;margin:22px 0;}
  section h2{font-size:30px;color:#7a2d00;border-bottom:3px solid #e0b97d;padding-bottom:8px;margin-bottom:4px;}
  .blurb{font-size:18px;color:#444;font-style:italic;margin:6px 0 14px;}
  ul.docs{list-style:none;padding:0;margin:0;}
  ul.docs li{margin:0 0 16px;padding:14px 16px;background:#faf7ef;border:1px solid #e3d8c0;border-radius:8px;}
  ul.docs li a{font-size:23px;color:#0a3d62;font-weight:bold;text-decoration:none;}
  ul.docs li a:hover{text-decoration:underline;}
  .d{display:block;margin-top:5px;font-size:18px;color:#222;line-height:1.45;}
  .meta{font-size:15px;color:#777;}
  .safety{background:#fdecea;border:2px solid #c0392b;border-radius:8px;}
  .safety a{color:#c0392b !important;}
  footer{text-align:center;color:#666;font-size:15px;margin:30px 0;}
  .count{font-size:16px;color:#7a2d00;font-weight:normal;}
</style>
</head>
<body>
<header>
  <h1>&#127794; Survival Reference Library</h1>
  <p>Everything here works without the internet. Take a breath - you have good, trusted guides for staying healthy, fed, warm, powered, and connected. Click any title to open it. When something matters, check more than one book, and start with the basics.</p>
</header>
<div class="wrap">
'@)

# Build TOC
[void]$sb.Append('<div class="toc"><h2>Jump to a section</h2>')
foreach($c in $cats.Keys){
  $validCount = 0
  Get-ChildItem (Join-Path $root $c) -File -ErrorAction SilentlyContinue | ForEach-Object {
    if($_.Name -eq 'index.html'){ return }
    if($_.Extension -eq '.pdf' -and -not (Test-PDF $_.FullName)){ return }
    $validCount++
  }
  [void]$sb.Append(('<a href="#{0}">{1} ({2})</a>' -f $c, $cats[$c][0], $validCount))
}
[void]$sb.Append('</div>')

$grandCount = 0; $grandBytes = 0
foreach($c in $cats.Keys){
  $dir = Join-Path $root $c
  if(-not (Test-Path $dir)){ continue }
  $files = Get-ChildItem $dir -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'index.html' } | Sort-Object @{e={$_.Extension -eq '.txt'}}, Name
  # filter invalid pdfs
  $files = $files | Where-Object { -not ($_.Extension -eq '.pdf' -and -not (Test-PDF $_.FullName)) }
  $secCount = ($files | Measure-Object).Count
  [void]$sb.Append(('<section id="{0}"><h2>{1} <span class="count">&mdash; {2} item(s)</span></h2><p class="blurb">{3}</p><ul class="docs">' -f $c, $cats[$c][0], $secCount, $cats[$c][1]))
  foreach($f in $files){
    $grandCount++; $grandBytes += $f.Length
    $name = $f.Name
    $d = $desc[$name]; if(-not $d){ $d = ($name -replace '\.(pdf|html|txt)$','' -replace '[-_]',' ') }
    $linktext = $title[$name]; if(-not $linktext){ $linktext = ($name -replace '\.(pdf|html|txt)$','' -replace '[-_]',' ') }
    $rel = "$c/$([uri]::EscapeDataString($name))"
    $kb = [math]::Round($f.Length/1KB)
    $size = if($kb -ge 1024){ "{0:N1} MB" -f ($kb/1024) } else { "$kb KB" }
    $type = $f.Extension.TrimStart('.').ToUpper()
    $liClass = if($name -like 'READ-ME-SAFETY*'){' class="safety"'} else {''}
    [void]$sb.Append(('<li{0}><a href="{1}">{2}</a><span class="d">{3}</span><span class="meta">file: {4} &middot; {5} &middot; {6}</span></li>' -f $liClass, $rel, [System.Web.HttpUtility]::HtmlEncode($linktext), [System.Web.HttpUtility]::HtmlEncode($d), [System.Web.HttpUtility]::HtmlEncode($name), $type, $size))
  }
  [void]$sb.Append('</ul></section>')
}

$totMB = [math]::Round($grandBytes/1MB,1)
[void]$sb.Append(('<footer>{0} documents in this library &middot; about {1} MB total &middot; works fully offline.<br>When in doubt, stay calm, check more than one source, and do the basics first.</footer></div></body></html>' -f $grandCount, $totMB))

Add-Type -AssemblyName System.Web
[System.IO.File]::WriteAllText((Join-Path $root 'index.html'), $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
Write-Output "index.html written: $grandCount documents, $totMB MB"
