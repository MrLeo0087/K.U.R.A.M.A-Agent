"""Voice test (v2 phase 2): the same real requests, SPOKEN (edge-tts, Indian + US English voices) with room noise
added, through KURAMA's speech recognition and its zero-token shortcuts. Measures what the microphone path loses.
Costs Groq Whisper requests (free tier: 20 a minute, so it is paced). Run by hand:

    venv/bin/python -m tests.eval.voice_eval            # ~30 requests x 2 voices, ~4 min
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from tests.eval import harness

VOICES = ("en-IN-PrabhatNeural", "en-US-GuyNeural")
NOISE = 0.03  # pink noise level mixed in (a fan / a quiet room)


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def wer(ref: str, hyp: str) -> float:
    """Word error rate (0 = perfect)."""
    r, h = _words(ref), _words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def speak(text: str, voice: str, out: Path) -> bytes:
    import edge_tts
    mp3 = out.with_suffix(".mp3")
    asyncio.run(edge_tts.Communicate(text, voice).save(str(mp3)))
    flt = (f"[0:a]aresample=16000,pan=mono|c0=c0[s];anoisesrc=color=pink:amplitude={NOISE}:sample_rate=16000[n];"
           "[s][n]amix=inputs=2:duration=first[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-filter_complex", flt, "-map", "[o]",
                    "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(out)], check=True)
    return out.read_bytes()


def main() -> int:
    from jarvis.core import config, fastpath, stt
    harness._isolated_store()
    config.FASTPATH = True
    picks = [c for c in harness.load() if c["expect"] not in ("clarify",) and c["text"].isascii()
             and 2 <= len(c["text"].split()) <= 12][:30]
    tmp = Path(tempfile.mkdtemp(prefix="kurama-voice-"))
    rows, t0 = [], time.monotonic()
    for c in picks:
        for v in VOICES:
            heard = stt.transcribe(speak(c["text"], v, tmp / f"{c['id']}-{v}.wav")).text
            it = fastpath.match(heard)
            same = fastpath.match(c["text"])  # what the typed text gives: the voice path should give the same
            got, want = (harness.intent_of(it.tool, it.args) if it else None), (harness.intent_of(same.tool, same.args) if same else None)
            rows.append({"id": c["id"], "voice": v, "text": c["text"], "heard": heard, "wer": round(wer(c["text"], heard), 2),
                         "same_action": got == want})
            print(f"  {'✓' if got == want else '✗'} {v[6:12]} wer {rows[-1]['wer']:.2f}  {c['text'][:40]!r} -> {heard[:40]!r}", flush=True)
            time.sleep(3.2)  # Whisper free tier: 20 requests/minute
    n = len(rows)
    card = {"when": time.strftime("%Y-%m-%d %H:%M"), "clips": n, "wer_avg": round(sum(r["wer"] for r in rows) / n, 3),
            "same_action": sum(r["same_action"] for r in rows) / n, "rows": rows}
    harness.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (harness.OUT_DIR / f"voice-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))
    print(f"\nVoice: {n} clips in {time.monotonic() - t0:.0f} s · word error {card['wer_avg']:.0%} · "
          f"same action as typed: {card['same_action']:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
