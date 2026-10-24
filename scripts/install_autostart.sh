#!/usr/bin/env bash
# Start KURAMA on login (no sudo):
#   - workers  -> ~/.config/systemd/user/jarvis-workers.service (enabled + started now)
#   - voice    -> ~/.config/autostart/jarvis.desktop (starts with your desktop session: needs DISPLAY + audio)
# Options: --no-voice, --no-workers. Undo with scripts/uninstall_autostart.sh
set -eu
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOICE=1; WORKERS=1
for a in "$@"; do
  case "$a" in --no-voice) VOICE=0 ;; --no-workers) WORKERS=0 ;; *) echo "unknown option $a" >&2; exit 2 ;; esac
done
[ -x "$DIR/venv/bin/python" ] || { echo "create the venv first (see README)" >&2; exit 1; }
chmod +x "$DIR/scripts/jarvis-start.sh"

if [ "$WORKERS" = 1 ]; then
  mkdir -p "$HOME/.config/systemd/user"
  sed "s|@JARVIS_DIR@|$DIR|g" "$DIR/packaging/jarvis-workers.service" > "$HOME/.config/systemd/user/jarvis-workers.service"
  systemctl --user daemon-reload
  systemctl --user enable --now jarvis-workers.service
  echo "workers: enabled (systemctl --user status jarvis-workers)"
fi
if [ "$VOICE" = 1 ]; then
  mkdir -p "$HOME/.config/autostart"
  sed "s|@JARVIS_DIR@|$DIR|g" "$DIR/packaging/jarvis.desktop" > "$HOME/.config/autostart/jarvis.desktop"
  echo "voice: starts at next login (log: $DIR/data/logs/voice.log)"
fi
