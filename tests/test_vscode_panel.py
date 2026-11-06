"""The KURAMA Coder panel's own page script must be valid JavaScript (11-07: a '\\n' inside the page's template
literal broke the whole script: the panel showed only its title)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node isn't installed")
def test_the_panel_page_script_parses(tmp_path):
    js = tmp_path / "page.js"
    code = (
        "const m = require('module'); const orig = m.prototype.require;"
        "m.prototype.require = function (n) { return n === 'vscode' ? {} : orig.apply(this, arguments); };"
        f"const src = require('fs').readFileSync({str(ROOT / 'vscode_ext' / 'coder.js')!r}, 'utf8');"
        "const page = new Function('require','module','exports', src + '; return page;')(require, {exports:{}}, {})();"
        f"require('fs').writeFileSync({str(js)!r}, page.split('<script>')[1].split('</script>')[0]);"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True)
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
