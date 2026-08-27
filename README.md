# Survival Station

An air-gapped, solar-powered AI survival computer built for a non-technical user: a local AI assistant, a searchable offline encyclopedia, offline US maps, and a reference library, all behind one desktop icon and no internet. This repo holds the code and manifests; the ~85 GB of content stays out of git and rebuilds from the scripts here.

## How it works

- One Python file, standard library only, serves the whole station on localhost:8080: chat with `llama3.1:8b` through local Ollama, one search box across the library (SQLite FTS5) and the encyclopedias (live Kiwix), ten authored how-to guides, and a built-in EPUB reader.
- Kiwix serves 35 ZIM archives on :8081, about 85 GB: full English Wikipedia (48 GB, no images), medical wikis, Wikibooks, iFixit, and 19 Stack Exchange sites, all full-text searchable.
- Maps are a PMTiles server written in pure PowerShell on :8082 with a vendored MapLibre viewer. A range-request extractor pulls a 1.75 GB US tile pyramid straight out of the Protomaps planet build without downloading the whole planet.
- The desktop icon runs one idempotent launcher: it starts Ollama pinned to a single loaded model, brings up any server whose port isn't listening, and opens the dashboard in Edge app mode.
- Everything binds to 127.0.0.1 with nothing to pip-install. Windows Smart App Control was enforcing during the build, so the stack is signed binaries and stdlib scripts only.
- The assistant's system prompt bans it from ever calling a wild plant or mushroom safe to eat; the curated library (Army field manuals, Where There Is No Doctor, radio and solar handbooks) is there to cross-check.

## Rebuilding the data

The ZIMs, the map, and the model are excluded from git. On a machine with internet:

```
aria2c -i zim/downloads.aria2.txt --dir=./zim
powershell -File bin/extract-us-pmtiles.ps1
ollama pull llama3.1:8b
```
