"""Frontend pure-JS checks run with Node (skipped when node is not installed): the in-browser WAV encoder
that replaced MediaRecorder (WebKitGTK, used by the wallpaper window, has no MediaRecorder)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
NODE = shutil.which("node")

SCRIPT = """
import { encodeWav, downsample } from "./voice.mjs";
const rate = 48000, n = rate / 2;                       // 0.5 s of a 440 Hz tone
const pcm = new Float32Array(n);
for (let i = 0; i < n; i++) pcm[i] = 0.5 * Math.sin(2 * Math.PI * 440 * i / rate);
pcm[0] = 2; pcm[1] = -2;                                // clipping must saturate, not wrap
const buf = encodeWav(pcm, rate, 16000);
const v = new DataView(buf);
const s = (o, l) => String.fromCharCode(...new Uint8Array(buf, o, l));
console.log(JSON.stringify({
  len: buf.byteLength, riff: s(0, 4), wave: s(8, 4), fmt: s(12, 4), data: s(36, 4),
  riffSize: v.getUint32(4, true), pcmFmt: v.getUint16(20, true), ch: v.getUint16(22, true),
  rate: v.getUint32(24, true), byteRate: v.getUint32(28, true), bits: v.getUint16(34, true),
  dataSize: v.getUint32(40, true), first: v.getInt16(44, true),
  same: downsample(pcm, 16000, 16000) === pcm,
}));
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_wav_encoder_header_and_length(tmp_path):
    shutil.copy(FRONTEND / "voice.js", tmp_path / "voice.mjs")
    (tmp_path / "t.mjs").write_text(SCRIPT)
    out = subprocess.run([NODE, "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    samples = 8000  # 0.5 s at 16 kHz
    assert (r["riff"], r["wave"], r["fmt"], r["data"]) == ("RIFF", "WAVE", "fmt ", "data")
    assert r["len"] == 44 + samples * 2 and r["dataSize"] == samples * 2 and r["riffSize"] == 36 + samples * 2
    assert (r["pcmFmt"], r["ch"], r["rate"], r["byteRate"], r["bits"]) == (1, 1, 16000, 32000, 16)
    assert 0 < r["first"] <= 32767  # averaged (2, -2, ...) window stays in range
    assert r["same"] is True


INSERT_SCRIPT = """
import { insertAtCursor as f } from "./voice.mjs";
console.log(JSON.stringify([
  f("", null, null, " hello "),                 // empty box
  f("open", null, null, "the file"),            // no caret yet: append with a space
  f("open  now", 5, 5, "it"),                   // caret between spaces: no extra spaces
  f("copy to", 4, 4, "this"),                   // caret glued to words: spaces both sides
  f("say WORD here", 4, 8, "text"),             // replaces the selection
  f("keep", 2, 2, "   "),                        // empty transcription: untouched
]));
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_insert_at_cursor(tmp_path):
    shutil.copy(FRONTEND / "voice.js", tmp_path / "voice.mjs")
    (tmp_path / "t.mjs").write_text(INSERT_SCRIPT)
    out = subprocess.run([NODE, "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert r[0] == {"value": "hello", "caret": 5}
    assert r[1] == {"value": "open the file", "caret": 13}
    assert r[2] == {"value": "open it now", "caret": 7}
    assert r[3] == {"value": "copy this to", "caret": 9}
    assert r[4] == {"value": "say text here", "caret": 8}
    assert r[5] == {"value": "keep", "caret": 2}
