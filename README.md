# 🏕 Survival Station

A **fully-offline, single-purpose "survival appliance" PC** for a non-technical user. It runs with **no internet** (designed for a Faraday cage on solar power) and provides a friendly AI assistant, a searchable offline encyclopedia, offline maps, and a curated reference library — all reachable from one desktop icon.

This repository holds the **buildable definition** of the appliance: scripts, the dashboard, the assistant app, the map viewer, docs, and the data **manifest**. The bulk content (Wikipedia/encyclopedias ~85 GB, map tiles ~1.75 GB, AI models) is **not** in git — it's reproducible (see *Rebuilding the data*) and backed up to external media.

---

## What the end user does
1. Power on the PC.
2. Double-click **“🏕 Survival Station — START HERE.”** (It also auto-starts at login.)
3. The dashboard opens with big buttons: Assistant · Encyclopedia · Maps · Library · Medical · Food & Foraging · Repair/Power/Radio · Help.

> ⚠️ **Safety:** For eating wild plants/mushrooms or for medical decisions, never trust the AI or one source alone — cross-check the guides, and when unsure, don't. The assistant is hard-prompted to refuse to declare anything safe to eat.

---

## Services & ports (all bound to localhost)
| Service | Port | Launcher | Notes |
|---|---|---|---|
| Ollama (AI engine) | 11434 | (auto) | low-RAM env: 1 model loaded |
| Survival Assistant | 8080 | `app/start-assistant.ps1` | stdlib-only Python web chat + vision + Kiwix-grounded references |
| Encyclopedia (Kiwix) | 8081 | `bin/start-kiwix.ps1` | serves all ZIMs; full-text search |
| Maps | 8082 | `bin/start-maps.ps1` | pure-PowerShell PMTiles server + MapLibre viewer |

**Master launcher:** `app/start-station.ps1` (started by the desktop icon and the `SurvivalStation` logon scheduled task) brings up all services then opens `app/dashboard.html` in Edge app-mode.

## AI models (Ollama)
- **`gemma3:4b`** — default, multimodal (text **and** images), fast. Best everyday model + plant/photo ID.
- **`llama3.1:8b`** — smarter, slower; for harder questions.
- **`moondream`** — small, fast vision model.

## Repository layout
```
app/    dashboard.html, splash.html, survival-assistant.py, start-*.ps1, icons/
bin/    start-kiwix.ps1, start-maps.ps1, maps-server.ps1, pmtiles-lib.ps1, extract-us-pmtiles.ps1
maps/   viewer/ (vendored MapLibre + fonts/sprites)        [us.pmtiles excluded]
library/ index.html + curated public-domain PDFs/HTML (manuals, medical, food, comms, tech, reference)
docs/   user-guide.html, quick-start, quick-card
zim/    downloads.aria2.txt, manifest.csv                  [*.zim excluded]
```

## Rebuilding the data (excluded from git)
On a machine with internet:
- **Encyclopedias (~85 GB):** `aria2c -i zim/downloads.aria2.txt --dir=./zim` then `bin/start-kiwix.ps1`
- **US map (~1.75 GB):** `powershell -File bin/extract-us-pmtiles.ps1` (range-extracts the US from the Protomaps planet build)
- **Models:** `ollama pull gemma3:4b; ollama pull llama3.1:8b; ollama pull moondream`
- **Library PDFs:** included in this repo under `library/`.

## Maintenance & notes
- **Back up the full `C:\Survival` (~87 GB) to external media** — once offline it's irreplaceable.
- Power (AC): screen blanks after 10 min; system never sleeps (servers stay live).
- **Build history:** Built 2026-06-05. Windows **Smart App Control** was *enforcing* during the build, which is why the assistant and map server are dependency-free (signed/stdlib-only) rather than Open WebUI / prebuilt tile-server binaries. SAC was later disabled; the lean stack was kept for reliability.
- Everything is localhost-only with **no internet/telemetry at runtime** (audited).
- WikiHow is no longer distributed by Kiwix; practical how-to is covered by iFixit, the zimgit prepper packs, Wikibooks, the Stack Exchange Q&A sites, and the library manuals.

*Generated with Claude Code.*
