#!/usr/bin/env bash
# KURAMA live wallpaper: a native GTK + WebKit window (scripts/kurama_wallpaper.py) that stays BEHIND all
# windows, on every workspace, out of the taskbar/alt-tab, and pauses itself while a maximized window covers it.
#   scripts/kurama-wallpaper.sh            start (also starts the API server if it isn't running)
#   scripts/kurama-wallpaper.sh --window   open it as a normal window instead (testing)
#   scripts/kurama-wallpaper.sh stop       close the wallpaper (the API keeps running)
# Reach it with Super+D (show desktop); the chat is clickable.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${JARVIS_API_PORT:-8000}"
URL="${KURAMA_UI_URL:-http://127.0.0.1:${PORT}/?lowpower=0&wallpaper=1}"
PY=/usr/bin/python3
SCRIPT="scripts/kurama_wallpaper.py"

if [[ "${1:-}" == "stop" ]]; then
  pkill -f -- "python3 [^ ]*kurama_[w]allpaper.py" 2>/dev/null && echo "wallpaper closed" || echo "not running"
  # put your real wallpaper back on the GNOME desktop (the running wallpaper shows a dashboard snapshot there)
  REAL="$HOME/.local/share/kurama/real-wallpaper.json"
  if [[ -f "$REAL" ]] && command -v gsettings >/dev/null; then
    "$PY" -c 'import json,subprocess,sys
d = json.load(open(sys.argv[1]))
for k in ("picture-uri", "picture-uri-dark", "picture-options"):
    if d.get(k): subprocess.run(["gsettings", "set", "org.gnome.desktop.background", k, d[k]])' "$REAL" && echo "desktop wallpaper restored"
  fi
  exit 0
fi

[[ -x "$PY" ]] || { echo "need the system python3 at $PY"; exit 1; }
"$PY" -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')" 2>/dev/null \
  || { echo "need GTK WebKit: sudo apt install python3-gi gir1.2-webkit2-4.1 (optional: gir1.2-wnck-3.0)"; exit 1; }
command -v curl >/dev/null || { echo "need curl: sudo apt install curl"; exit 1; }

WINDOW=""
[[ "${1:-}" == "--window" ]] && WINDOW="--window"
if [[ -z "$WINDOW" ]] && pgrep -f -- "python3 [^ ]*kurama_[w]allpaper.py" >/dev/null; then
  echo "KURAMA wallpaper is already running (stop: scripts/kurama-wallpaper.sh stop)"; exit 0
fi

# 1) the GTK wallpaper window first: it shows the last dashboard snapshot at once and retries the page every
#    second until the API answers, so the desktop never shows anything else
mkdir -p data/logs
[[ -f data/logs/wallpaper.log && $(stat -c %s data/logs/wallpaper.log) -gt 1048576 ]] && mv -f data/logs/wallpaper.log data/logs/wallpaper.log.1
# a frozen window exits with code 1 after logging its stacks (hang_guard, data/logs/hang.log), and a crash exits with
# 1 too: start it again (at most 20 times; 2 s apart). A normal stop (pkill: 143) or a clean exit ends the loop.
run_window() {
  for _ in $(seq 20); do
    "$PY" "$SCRIPT" --url "$URL" $WINDOW >> data/logs/wallpaper.log 2>&1
    code=$?
    [[ $code -eq 1 && ! -f "$HOME/.local/share/kurama/off" ]] || break
    echo "$(date '+%F %T') window exited with code 1 (frozen or crashed): starting it again" >> data/logs/wallpaper.log
    sleep 2
  done
}
run_window </dev/null >/dev/null 2>&1 &
disown

# 2) API server in parallel (skip if already up)
if ! curl -fs "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
  nohup venv/bin/python -m jarvis.server --port "$PORT" >> data/logs/server.log 2>&1 &
fi
echo "KURAMA wallpaper is running${WINDOW:+ (window mode)} (stop: scripts/kurama-wallpaper.sh stop)"
