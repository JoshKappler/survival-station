# Survival Station

An air-gapped, solar-powered AI survival computer built for a non-technical user: a local AI assistant, a searchable offline encyclopedia, offline US maps, and a reference library, all behind one desktop icon and no internet. This repo holds the code and manifests; the content (about 90 GB of encyclopedias, a 19 GB map and the models) stays out of git and rebuilds from the scripts here.

## How it works

- One Python file, standard library only, serves the whole station on localhost:8080: chat through local Ollama (default `gemma4:26b-a4b-it-qat`, with `gpt-oss:20b` and `qwen3.8:27b` in the model picker), one search box across the library (SQLite FTS5) and the encyclopedias (live Kiwix), ten authored how-to guides, and a built-in EPUB reader.
- Kiwix serves 35 ZIM archives on :8081, about 90 GB: full English Wikipedia (48 GB, no images), medical wikis, Wikibooks, iFixit, and 19 Stack Exchange sites, all full-text searchable.
- Maps are a PMTiles server written in pure PowerShell on :8082 with a vendored MapLibre viewer. `maps/us.pmtiles` covers the lower 48 states at full street detail (zoom 15, 19 GB), cut from the Protomaps planet build with the `pmtiles` CLI. The pure-PowerShell extractor in `bin/` still works where unsigned binaries are blocked.
- The desktop icon runs one idempotent launcher: it starts Ollama pinned to a single loaded model, brings up any server whose port isn't listening, and opens the dashboard in a Chrome app window with its own profile, falling back to Edge, then the default browser.
- Everything binds to 127.0.0.1 with nothing to pip-install. Windows Smart App Control was enforcing during the build, so the stack is signed binaries and stdlib scripts only.
- The assistant's system prompt bans it from ever calling a wild plant or mushroom safe to eat; the curated library (Army field manuals, Where There Is No Doctor, radio and solar handbooks) is there to cross-check.

## Rebuilding the data

The ZIMs, the map, and the model are excluded from git. On a machine with internet:

```
aria2c -i zim/downloads.aria2.txt --dir=./zim
bin/pmtiles.exe extract https://build.protomaps.com/20261117.pmtiles maps/us.pmtiles --bbox=-125.0,24.0,-66.5,49.5 --maxzoom=15
ollama pull gemma4:26b-a4b-it-qat; ollama pull gpt-oss:20b; ollama pull qwen3.8:27b
```

## On a Mac

The same hub runs on Apple Silicon from `bin-mac/`. Kiwix and the map are served from the hub process and a native Kiwix build, with no PowerShell.

- `bin-mac/start.sh` starts Ollama, Kiwix on :8081 and the hub on :8080, then opens the hub in a Chrome app window. `bin-mac/make-desktop-app.sh` puts a `Survival Station.app` icon on the Desktop that runs it.
- The hub serves the map viewer at `/maps/` and reads `maps/california.pmtiles` with range requests.
- `bin-mac/model` names the one model used for both chat and coding (`gemma4:26b`).
- `bin-mac/claude-local` runs Claude Code against local Ollama with its own config dir, and `bin-mac/codex-local` is the Codex backup. The hub's "Fix this computer" tile opens the first in Terminal.

Rebuilding the data on a Mac (Kiwix ships only an Intel Mac build, so it runs under Rosetta):

```
aria2c -i zim/downloads-mac.txt -d zim -c -j 4
curl -sL https://download.kiwix.org/release/kiwix-tools/kiwix-tools_macos-x86_64-3.8.2.tar.gz | tar xz -C bin-mac
pmtiles extract https://build.protomaps.com/20261117.pmtiles maps/california.pmtiles --bbox=-124.48,32.53,-114.13,42.01 --maxzoom=15
ollama pull gemma4:26b
```
