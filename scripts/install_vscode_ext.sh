#!/usr/bin/env bash
# Build vscode_ext/ into a .vsix and install it into VS Code (then: Ctrl+Shift+P -> "Reload Window" in each window).
# Run again after changing the extension. Uninstall: code --uninstall-extension kurama.kurama-editor-link
set -euo pipefail
cd "$(dirname "$0")/.."
command -v code >/dev/null || { echo "VS Code's 'code' command is missing" >&2; exit 1; }
OUT="data/kurama-editor-link.vsix"
python3 - "$OUT" <<'PY'
import json, sys, zipfile
from pathlib import Path
out, src = Path(sys.argv[1]), Path("vscode_ext")
pkg = json.loads((src / "package.json").read_text())
ident = f'{pkg["publisher"]}.{pkg["name"]}'
manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{pkg["name"]}" Version="{pkg["version"]}" Publisher="{pkg["publisher"]}"/>
    <DisplayName>{pkg["displayName"]}</DisplayName>
    <Description xml:space="preserve">{pkg["description"]}</Description>
    <Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg["engines"]["vscode"]}"/></Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets>
</PackageManifest>"""
types = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension=".json" ContentType="application/json"/><Default Extension=".js" ContentType="application/javascript"/><Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>"""
out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", types)
    z.writestr("extension.vsixmanifest", manifest)
    for f in ("package.json", "extension.js"):
        z.write(src / f, f"extension/{f}")
print(f"built {out} ({ident} {pkg['version']})")
PY
code --install-extension "$OUT" --force
# also into every named VS Code profile (a window of a project tied to a profile, e.g. "Claude-1", only loads the
# extensions of THAT profile: the default-profile install never ran there, 11-06)
python3 - <<'PY' | while IFS= read -r prof; do code --profile "$prof" --install-extension "$OUT" --force; done
import json, os
p = os.path.expanduser("~/.config/Code/User/globalStorage/storage.json")
try:
    for x in json.load(open(p)).get("userDataProfiles") or []:
        if not str(x.get("location", "")).startswith("builtin"):
            print(x.get("name"))
except (OSError, ValueError):
    pass
PY
echo "Installed. In each VS Code window: Ctrl+Shift+P -> Reload Window."
