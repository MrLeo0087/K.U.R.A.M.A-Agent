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

# power switch that costs nothing while KURAMA is off: Super+K and a "KURAMA" app icon (pin it to the dock)
mkdir -p "$HOME/.local/share/kurama" "$HOME/.local/share/applications"
cp "$DIR/scripts/kurama.svg" "$HOME/.local/share/kurama/kurama.svg"
cat > "$HOME/.local/bin/kurama-power" <<PWR
#!/usr/bin/env bash
[[ -x "$DIR/scripts/kurama-power.sh" ]] && exec "$DIR/scripts/kurama-power.sh" "\${1:-toggle}"
notify-send KURAMA "The KURAMA drive is not mounted." 2>/dev/null
PWR
chmod +x "$HOME/.local/bin/kurama-power"
cat > "$HOME/.local/share/applications/kurama.desktop" <<APP
[Desktop Entry]
Type=Application
Name=KURAMA
Comment=Turn KURAMA on or off (Super+K)
Exec=$HOME/.local/bin/kurama-power toggle
Icon=$HOME/.local/share/kurama/kurama.svg
Terminal=false
Categories=Utility;
Actions=on;off;
[Desktop Action on]
Name=Turn on
Exec=$HOME/.local/bin/kurama-power on
[Desktop Action off]
Name=Turn off
Exec=$HOME/.local/bin/kurama-power off
APP
if command -v gsettings >/dev/null; then
  MK=org.gnome.settings-daemon.plugins.media-keys
  KP=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/kurama-power/
  LIST=$(gsettings get $MK custom-keybindings)
  if [[ "$LIST" != *"$KP"* ]]; then  # add ours, keep every existing shortcut
    if [[ "$LIST" == "@as []" || "$LIST" == "[]" ]]; then LIST="['$KP']"; else LIST="${LIST%]}, '$KP']"; fi
    gsettings set $MK custom-keybindings "$LIST"
  fi
  gsettings set $MK.custom-keybinding:$KP name "KURAMA on/off"
  gsettings set $MK.custom-keybinding:$KP command "$HOME/.local/bin/kurama-power toggle"
  gsettings set $MK.custom-keybinding:$KP binding "<Super>k"
  echo "Power switch: Super+K, or the KURAMA app icon."
fi
if ! grep -q "$(findmnt -n -o UUID -T "$DIR" 2>/dev/null || echo none)" /etc/fstab 2>/dev/null; then
  echo "Note: $DIR is on a drive that is not mounted at boot. To mount it at boot, run once:"
  echo "  echo 'UUID=$(findmnt -n -o UUID -T "$DIR") $(findmnt -n -o TARGET -T "$DIR") $(findmnt -n -o FSTYPE -T "$DIR") defaults,nofail,x-gvfs-show 0 2' | sudo tee -a /etc/fstab"
fi
