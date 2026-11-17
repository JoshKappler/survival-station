#!/bin/zsh
# Brings up Ollama, Kiwix (:8081) and the hub (:8080) if not already running, then opens the hub.
ROOT="${0:A:h:h}"
LOGS="$ROOT/logs"; mkdir -p "$LOGS"
MODEL="${STATION_MODEL:-$(cat "$ROOT/bin-mac/model" 2>/dev/null)}"
up() { nc -z 127.0.0.1 "$1" 2>/dev/null; }
wait_up() { for i in {1..60}; do up "$1" && return 0; sleep 0.5; done; return 1; }

up 11434 || open -ga Ollama

zims=(); for z in "$ROOT"/zim/*.zim(N); do [[ -e $z.aria2 ]] || zims+=("$z"); done  # skip ones still downloading
if ! up 8081 && (( ${#zims} )); then
  nohup arch -x86_64 "$ROOT"/bin-mac/kiwix-tools_*/kiwix-serve --address=127.0.0.1 --port=8081 "${zims[@]}" >>"$LOGS/kiwix.log" 2>&1 &
fi

if ! up 8080; then
  PY=/opt/homebrew/bin/python3; [[ -x $PY ]] || PY=/usr/bin/python3
  ASSISTANT_DEFAULT_MODEL="$MODEL" MAPS_PUBLIC_BASE_URL=http://localhost:8080/maps \
    nohup "$PY" "$ROOT/app/survival-assistant.py" >>"$LOGS/hub.log" 2>&1 &
fi

wait_up 8080
wait_up 11434 && [[ -n $MODEL ]] && curl -s localhost:11434/api/generate -d "{\"model\":\"$MODEL\"}" >/dev/null &
if [[ -d "/Applications/Google Chrome.app" ]]; then
  open -na "Google Chrome" --args --app=http://localhost:8080/ --new-window
else
  open http://localhost:8080/
fi
