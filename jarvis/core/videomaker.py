"""Short videos, free: scenes of (picture + spoken line + caption) joined by ffmpeg into one MP4.

- 'make a short video about the Himalayas': ONE fast LLM call writes 4-6 scenes (narration + picture prompt).
- 'make a video with this script: ...': the user's sentences are the scenes (0 tokens).
- 'make a video from the pictures in ~/Pictures/trip': a slideshow of those pictures (0 tokens).
Pictures: Pollinations (free); voice: edge-tts; caption drawn with Pillow; ffmpeg at low priority (nice).
Saved in data/outputs/videos/ (plays in the workspace).
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from jarvis.core import config

MAX_SCENES = 8
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def size_for(text: str) -> tuple[int, int]:
    return (720, 1280) if re.search(r"\b(?:reel|reels|short|shorts|tiktok|vertical|story|portrait|phone)\b", text, re.I) \
        else (1280, 720)


def plan(topic: str) -> list[dict]:
    """One small call: [{'say': ..., 'picture': ...}] (4-6 scenes)."""
    from jarvis.core import llm
    reply = llm.chat([{"role": "system", "content":
                       "Write a short narrated video as JSON only: {\"title\": str, \"scenes\": [{\"say\": one or two short "
                       "spoken sentences, \"picture\": a vivid English image prompt for that moment}]}. 4 to 6 scenes, "
                       "simple words, true facts, total under 120 words of narration."},
                      {"role": "user", "content": topic[:500]}], tier="fast", purpose="video_plan", max_tokens=700)
    m = re.search(r"\{.*\}", reply.text or "", re.S)
    if not m:
        raise ValueError("the plan didn't come back")
    d = json.loads(m.group(0))
    scenes = [s for s in d.get("scenes", []) if s.get("say") and s.get("picture")][:MAX_SCENES]
    if not scenes:
        raise ValueError("the plan had no scenes")
    return scenes


def script_scenes(script: str, topic: str = "") -> list[dict]:
    """The user's own words: one scene per sentence (two short ones together), picture = that sentence."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?।])\s+|\n+", script) if len(s.strip()) > 2]
    scenes, cur = [], ""
    for s in sents:
        cur = f"{cur} {s}".strip()
        if len(cur) > 60 or s is sents[-1]:
            scenes.append({"say": cur, "picture": f"{cur} {topic}".strip()})
            cur = ""
    return scenes[:MAX_SCENES]


def _caption(img_path: Path, text: str, size: tuple[int, int]) -> None:
    """Fit the picture to the frame and draw the line at the bottom (Pillow)."""
    import textwrap

    from PIL import Image, ImageDraw, ImageFont, ImageOps
    img = ImageOps.fit(Image.open(img_path).convert("RGB"), size)
    if text:
        d = ImageDraw.Draw(img, "RGBA")
        w, h = size
        try:
            f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(22, w // 34))
        except OSError:
            f = ImageFont.load_default()
        lines = textwrap.wrap(text, 34 if w < h else 52)[:3]
        lh = max(28, w // 26)
        top = h - lh * len(lines) - 50
        d.rectangle((0, top - 20, w, h), fill=(0, 0, 0, 150))
        for i, ln in enumerate(lines):
            d.text((w / 2, top + i * lh + lh / 2), ln, fill=(255, 255, 255), font=f, anchor="mm")
    img.save(img_path, quality=92)


def _ffmpeg(args: list[str]) -> None:
    cmd = (["nice", "-n", "10"] if shutil.which("nice") else []) + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError((r.stderr or "ffmpeg failed").strip().splitlines()[-1][:200])


def render(scenes: list[dict], title: str, size: tuple[int, int], progress=lambda _: None,
           pictures: list[Path] | None = None, silent_s: float = 3.5) -> Path:
    """scenes [{'say', 'picture'}] (or pictures given) -> MP4."""
    from jarvis.core import audiomaker, tts
    from jarvis.tools.general import generate_image as gi
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg isn't installed (sudo apt install ffmpeg)")
    out_dir = config.OUTPUTS_DIR / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'video'}.mp4"
    with tempfile.TemporaryDirectory(prefix="kurama-video-") as tmp:
        t = Path(tmp)
        parts = []
        for i, sc in enumerate(scenes):
            progress(f"scene {i + 1} of {len(scenes)}")
            img = t / f"s{i}.jpg"
            if pictures:
                shutil.copy(pictures[i], img)
            else:
                img.write_bytes(gi.fetch_image(gi.styled(sc["picture"]), *size, exact=True))
            _caption(img, sc.get("say", ""), size)
            clip = t / f"s{i}.mp4"
            if sc.get("say"):
                voice = tts.voice_for(audiomaker.voice_lang(sc["say"]))
                mp3 = t / f"s{i}.mp3"

                async def speak(text=sc["say"], path=mp3, v=voice):
                    with open(path, "wb") as f:
                        async for chunk in tts.edge_synth(text, v):
                            f.write(chunk)
                asyncio.run(speak())
                _ffmpeg(["-loop", "1", "-i", str(img), "-i", str(mp3), "-af", "apad=pad_dur=0.6", "-shortest",
                         "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-r", "24", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "128k", "-ar", "44100", str(clip)])
            else:
                _ffmpeg(["-loop", "1", "-i", str(img), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(silent_s),
                         "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-r", "24", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-shortest", str(clip)])
            parts.append(clip)
        progress("joining the scenes")
        lst = t / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])
    return out


def folder_pictures(folder: str) -> list[Path]:
    from jarvis.core.paths import smart_path
    p = Path(folder).expanduser()
    if not p.is_dir():
        p = smart_path(folder, want="dir") or p
    if not p.is_dir():
        return []
    return sorted(x for x in p.iterdir() if x.suffix.lower() in IMG_EXT)[:40]
