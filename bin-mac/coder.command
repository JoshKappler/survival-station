#!/bin/zsh
# Opened by the hub's "Fix this computer" tile.
cd ~
echo "Offline coding agent: Claude Code on the local model. /exit to quit."
echo "If it misbehaves, the backup is: ~/survival-station/bin-mac/codex-local"
echo
exec "${0:A:h}/claude-local"
