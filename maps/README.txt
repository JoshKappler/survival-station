OFFLINE UNITED STATES MAP  --  C:\Survival\maps
=====================================================

WHAT THIS IS
  A fully offline, zoomable map of the United States that runs in your web
  browser. No internet is needed once it is set up. Everything it uses is
  stored on this computer.

HOW TO OPEN IT
  Easiest way:  on the main "Survival Station" screen, click the MAPS button.
  Or open this address in a web browser:   http://localhost:8082

  If it is not running, start it by running this file:
      C:\Survival\bin\start-maps.ps1
  (Right-click it and choose "Run with PowerShell", or it starts automatically
   with the rest of the station.)

USING THE MAP
  - Scroll the mouse wheel (or use the + / - buttons) to zoom in and out.
  - Click and drag to move around.
  - The bar at the bottom-left shows the scale (miles and kilometers).
  - The button at the top-right can make the map full screen.

WHAT YOU CAN SEE
  States, counties, cities and towns, roads and highways, water (rivers,
  lakes, coastlines), parks and land features, with place-name labels.

ZOOM LIMIT
  The map is detailed down to ZOOM LEVEL 15 everywhere in the lower 48
  states: every named street, trail, park and building outline. It opens on
  the San Francisco Bay Area. It has no house numbers and no turn-by-turn
  directions. For careful navigation, also use the printed guides in:
  C:\Survival\library\shelter-skills\

HOW IT WORKS (for whoever maintains this)
  - The map data is a single file: C:\Survival\maps\us.pmtiles  (Protomaps
    PMTiles vector tiles to zoom 15, about 19 GB, extracted from the
    OpenStreetMap-based Protomaps planet build for the continental US
    bounding box).
  - It is served by a small PowerShell web server (no extra programs needed,
    works under Windows Smart App Control):  C:\Survival\bin\maps-server.ps1
    It serves on http://127.0.0.1:8082 and supports HTTP range requests so the
    browser reads only the map tiles it needs.
  - The viewer is MapLibre GL JS with the Protomaps "light" basemap style.
    ALL web assets (map library, fonts, icons, style) are stored locally in
    C:\Survival\maps\viewer -- nothing is loaded from the internet at runtime.

  Data attribution: (c) OpenStreetMap contributors; Protomaps. Open data.
