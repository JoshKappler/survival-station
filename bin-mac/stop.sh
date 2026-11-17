#!/bin/zsh
# Stops Kiwix and the hub, and unloads the model from memory. Ollama itself keeps running.
pkill -f 'kiwix-serve --address=127.0.0.1 --port=8081'
for m in $(ollama ps 2>/dev/null | awk 'NR>1{print $1}'); do ollama stop "$m"; done
pkill -f 'app/survival-assistant.py'
