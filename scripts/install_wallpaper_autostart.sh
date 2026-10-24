#!/usr/bin/env bash
# KURAMA wallpaper at login, with no delay: ~/.local/bin/kurama-autostart (waits for the project drive) +
# ~/.config/autostart/kurama-wallpaper.desktop. No sudo. Undo: rm both files.
set -eu
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.config/autostart"
sed "s|@KURAMA_DIR@|$DIR|g" "$DIR/scripts/kurama-autostart.sh" > "$HOME/.local/bin/kurama-autostart"
chmod +x "$HOME/.local/bin/kurama-autostart"
cat > "$HOME/.config/autostart/kurama-wallpaper.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=KURAMA wallpaper
Comment=KURAMA live wallpaper + background workers (Telegram, reminders, alerts)
Exec=$HOME/.local/bin/kurama-autostart
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Phase=Applications
NoDisplay=false
Terminal=false
DESK
echo "KURAMA wallpaper starts at login (no delay)."
if ! grep -q "$(findmnt -n -o UUID -T "$DIR" 2>/dev/null || echo none)" /etc/fstab 2>/dev/null; then
  echo "Note: $DIR is on a drive that is not mounted at boot. To mount it at boot, run once:"
  echo "  echo 'UUID=$(findmnt -n -o UUID -T "$DIR") $(findmnt -n -o TARGET -T "$DIR") $(findmnt -n -o FSTYPE -T "$DIR") defaults,nofail,x-gvfs-show 0 2' | sudo tee -a /etc/fstab"
fi
