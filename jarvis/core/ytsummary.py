"""A YouTube video in two minutes (plan 11-09 phase 9): its subtitles (yt-dlp, free, no download of the video) ->
one AI call -> the main points + timestamps to jump to. The video open in the browser when no link is given.
Cached per video. ~3-5k tokens for a long lecture (the transcript is merged into 1-minute lines, at most
YT_MAX_CHARS)."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from jarvis.core import config

MAX_CHARS = 16000
_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})")


def video_id(url: str) -> str:
    m = _ID.search(url or "")
    return m.group(1) if m else ""


def _vtt_lines(vtt: str) -> list[tuple[int, str]]:
    """[(seconds, text)] from a WebVTT file; YouTube's rolling auto-captions repeat lines: each is kept once."""
    out, last = [], ""
    for block in re.split(r"\n\s*\n", vtt):
        m = re.search(r"(\d+):(\d\d):(\d\d)\.\d+\s+-->", block)
        if not m:
            continue
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        text = " ".join(ln for ln in block.splitlines()[1:] if "-->" not in ln)
        text = re.sub(r"<[^>]+>", "", text).strip()
        for piece in [p.strip() for p in text.split("  ") if p.strip()] or []:
            if piece and piece != last and not last.endswith(piece):
                out.append((secs, piece))
                last = piece
    return out


def transcript(url: str) -> tuple[str, str]:
    """(title, '[m:ss] text' lines merged per minute), or ('', '') when the video has no subtitles."""
    from jarvis.core.music import _ytdlp
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([_ytdlp(), "--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs",
                            "en.*,en,hi,ne", "--sub-format", "vtt", "--print", "title", "--no-simulate",
                            "-o", f"{d}/%(id)s.%(ext)s", url], capture_output=True, text=True, timeout=90)
        title = (r.stdout or "").strip().splitlines()[0] if r.stdout.strip() else ""
        subs = sorted(Path(d).glob("*.vtt"), key=lambda p: (".en" not in p.name, len(p.name)))
        if not subs:
            return title, ""
        lines = _vtt_lines(subs[0].read_text(encoding="utf-8", errors="replace"))
    merged: dict[int, list[str]] = {}
    for secs, text in lines:
        merged.setdefault(secs // 60, []).append(text)
    rows = [f"[{m}:00] {' '.join(t)}" for m, t in sorted(merged.items())]
    text = "\n".join(rows)
    if len(text) > MAX_CHARS:  # a long lecture: every minute kept, each minute shortened evenly
        per = max(80, MAX_CHARS // max(1, len(rows)))
        text = "\n".join(r[:per] for r in rows)
    return title, text


def summarize(url: str = "") -> str:
    if not url:
        from jarvis.core import browsertab
        tab = browsertab.get()
        url = tab[0] if tab and video_id(tab[0]) else ""
    vid = video_id(url)
    if not vid:
        return "Open the YouTube video in the browser (or give me its link), then ask again."
    from jarvis.core import store
    key = f"ytsum:{vid}"
    if hit := store.kv_get(key):
        return hit
    try:
        title, text = transcript(f"https://www.youtube.com/watch?v={vid}")
    except (OSError, subprocess.SubprocessError) as e:
        return f"error: couldn't read the video ({str(e)[:100]})."
    if not text:
        return f"“{title or vid}” has no subtitles, so I can't summarize it without watching (no captions on YouTube)."
    from jarvis.core import llm
    try:
        r = llm.chat([{"role": "system", "content": "Summarize this YouTube video from its transcript for a student "
                       "who has 2 minutes: first one line on what it is about, then 5-7 bullet points of the main "
                       "ideas, then 'Jump to:' with 4-6 timestamps (m:ss — what starts there). Plain English, no intro."},
                      {"role": "user", "content": f"Title: {title}\n\nTranscript:\n{text}"}],
                     tier="fast", purpose="youtube_summary", max_tokens=700)
        out = (r.text or "").strip()
    except Exception as e:  # noqa: BLE001
        return f"error: the AI didn't answer ({str(e)[:100]})."
    if not out:
        return "error: the AI gave an empty summary."
    out = f"▶️ {title}\n{out}\n(https://youtu.be/{vid})"
    store.kv_set(key, out)
    return out


def jump_url(vid: str, mmss: str) -> str:
    m = re.match(r"(?:(\d+):)?(\d+):(\d\d)", mmss)
    secs = (int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m else 0
    return f"https://youtu.be/{vid}?t={secs}"
