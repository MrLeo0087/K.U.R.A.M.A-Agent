#!/bin/bash
# Adds "Send to phone" to the Files app's right-click menu (Scripts > Send to phone): the selected files / folders
# go to your KURAMA Telegram chat (folders as a zip). Run once; KURAMA must be running.
set -e
dir="$HOME/.local/share/nautilus/scripts"
mkdir -p "$dir"
cat > "$dir/Send to phone" <<'SH'
#!/bin/bash
# KURAMA: send the selected files / folders to Telegram
python3 - <<'PY'
import json, os, urllib.request
paths = [p for p in os.environ.get("NAUTILUS_SCRIPT_SELECTED_FILE_PATHS", "").splitlines() if p.strip()]
if paths:
    req = urllib.request.Request("http://127.0.0.1:8000/api/v1/phone/send", json.dumps({"paths": paths}).encode(),
                                 {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        os.system(f"notify-send 'KURAMA is not running' 'Start KURAMA, then send again.'")
PY
SH
chmod +x "$dir/Send to phone"
echo "Done: right-click a file in Files -> Scripts -> Send to phone"
