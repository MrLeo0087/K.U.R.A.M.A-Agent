"""Text -> MP3 with edge-tts (free, 0 tokens): the highlighted text, a file (txt/md/pdf), a web page, the newest
workspace document, or words typed after 'make an audio of:'. English / Nepali / Hindi voice by the text's script.
Saved in data/outputs/audio/ (plays in the workspace; Phone button sends it to Telegram)."""
from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime
from pathlib import Path

from jarvis.core import config

MAX_CHARS = 60_000  # ~1 hour of speech
CHUNK = 2500


def text_of(source: str) -> tuple[str, str]:
    """(text, title) for 'selection' | 'last' | a URL | a file path | plain text."""
    src = (source or "").strip()
    if src == "selection":
        from jarvis.core import rewrite
        g = rewrite.grab()
        if isinstance(g, str):
            raise ValueError("Highlight the text you want as audio, then ask again.")
        return g.text, "selection"
    if src == "last":
        from jarvis.core import workspace
        p = workspace.latest()
        newest = max((x for x in config.OUTPUTS_DIR.rglob("*") if x.suffix in (".md", ".txt") and x.is_file()),
                     key=lambda x: x.stat().st_mtime, default=None) if config.OUTPUTS_DIR.is_dir() else None
        p = max((x for x in (p, newest) if x), key=lambda x: x.stat().st_mtime, default=None)
        if p is None:
            raise ValueError("There's no document in the workspace yet.")
        return p.read_text(errors="replace"), p.stem
    if re.match(r"https?://", src):
        from jarvis.tools.general import _web
        from jarvis.tools.general.read_webpage import fetch
        ctype, body = fetch(src)
        title, text = _web.html_to_text(body) if "html" in ctype else ("", body)
        return text, title or src.rsplit("/", 1)[-1]
    if src.startswith(("/", "~")) or re.search(r"\.(?:txt|md|pdf)$", src, re.I):
        p = Path(src).expanduser()
        if not p.is_file():
            from jarvis.core.paths import smart_path
            p = smart_path(src, want="file") or p
        if not p.is_file():
            raise ValueError(f"I can't find {src}.")
        if p.suffix.lower() == ".pdf":
            out = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=120)
            return out.stdout, p.stem
        return p.read_text(errors="replace"), p.stem
    return src, src[:40]


def make(text: str, title: str, lang: str | None = None) -> Path:
    from jarvis.core import tts
    from jarvis.core.planner import detect_lang
    clean = tts.clean_for_speech(re.sub(r"```.*?```", " ", text, flags=re.S))[:MAX_CHARS].strip()
    if len(clean) < 2:
        raise ValueError("There's no readable text in it.")
    lang = lang or detect_lang(clean[:2000])
    if lang in ("ne", "hi"):  # same script: count each language's everyday words
        ne = len(re.findall(r"(?<!\S)(?:छ|छन्|छु|हो|हुँ|थियो|भयो|मेरो|तपाईं|गर्नु|गर्छ|हुन्छ|र|पनि|यो|त्यो|म)(?=[\s।,.!?]|$)", clean))
        hi = len(re.findall(r"(?<!\S)(?:है|हैं|था|थी|मैं|मेरा|का|की|के|नहीं|और|भी|यह|वह|आप)(?=[\s।,.!?]|$)", clean))
        lang = "ne" if ne > hi else "hi" if hi > ne else lang
    voice = tts.voice_for(lang if lang in ("ne", "hi") else "en")
    out = config.OUTPUTS_DIR / "audio"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'audio'}.mp3"
    parts, cur = [], ""
    for s in re.split(r"(?<=[.!?।])\s+", clean):  # whole sentences per request, MP3 frames simply concatenate
        if len(cur) + len(s) > CHUNK and cur:
            parts.append(cur)
            cur = ""
        cur += s + " "
    if cur.strip():
        parts.append(cur)

    async def run():
        with open(path, "wb") as f:
            for part in parts:
                async for chunk in tts.edge_synth(part, voice):
                    f.write(chunk)
    asyncio.run(run())
    return path


def minutes(text: str) -> float:
    return len(text.split()) / 150  # ~150 spoken words a minute
