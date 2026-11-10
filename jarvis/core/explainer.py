"""Explainer videos (plan 11-09 phase 9; owner: "I make videos like how transformers work, how AI works: make the
video from my script and voiceover"). Free, CPU, background job.

Input, any of:
  - a topic only        -> one AI call writes a ~1-minute script AND its scenes
  - your script         -> one small AI call cuts it into scenes (your exact words are kept as the narration)
  - your voiceover file -> Whisper (Groq, free) turns it into text with timings, then scenes as above; your own voice
                           is the soundtrack, each scene shown while you say it
Each scene: a title + 2-4 short points that appear one by one while it is spoken, a progress bar, captions of the
narration at the bottom (burned in, so they show on Instagram / YouTube Shorts too). Voice when you give none:
edge-tts (free). Format: 16:9 (YouTube) or 9:16 (reel / short). Saved in data/outputs/videos/.
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

FPS = 30
MAX_SCENES = 12
BG_TOP, BG_BOTTOM = (11, 18, 38), (24, 36, 72)
ACCENT = (255, 177, 92)
TEXT = (238, 242, 255)
SUB = (170, 182, 214)
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

_SCENES_SYS = ("You turn a narration into explainer-video scenes. Return JSON only: {\"scenes\": [{\"title\": short "
               "slide title (max 6 words), \"points\": [2-4 very short key points, max 7 words each], \"say\": the "
               "EXACT narration sentences for this scene, copied word for word}]}. Keep every sentence of the "
               "narration, in order, each in exactly one scene; 3-12 scenes.")
_WRITE_SYS = ("Write a clear, friendly ~150-word explainer narration for a short educational video (for students), "
              "then cut it into scenes. Return JSON only: {\"scenes\": [{\"title\": max 6 words, \"points\": [2-4 key "
              "points, max 7 words each], \"say\": 1-3 narration sentences}]}, 5-8 scenes, the first a hook, the last "
              "a one-line recap.")


def size_for(fmt: str) -> tuple[int, int]:
    return (1080, 1920) if fmt in ("reel", "short", "vertical", "9:16") else (1920, 1080)


def _json(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        sc = json.loads(m.group(0)).get("scenes") if m else None
    except ValueError:
        sc = None
    out = []
    for s in sc or []:
        if isinstance(s, dict) and str(s.get("say") or "").strip():
            out.append({"title": str(s.get("title") or "")[:60],
                        "points": [str(p)[:60] for p in (s.get("points") or []) if str(p).strip()][:4],
                        "say": str(s["say"]).strip()})
    return out[:MAX_SCENES]


def scenes_from(topic: str = "", script: str = "") -> list[dict]:
    from jarvis.core import llm
    if script.strip():
        r = llm.chat([{"role": "system", "content": _SCENES_SYS},
                      {"role": "user", "content": f"Topic: {topic}\n\nNarration:\n{script.strip()[:6000]}"}],
                     tier="fast", purpose="video_scenes", max_tokens=1600)
    else:
        r = llm.chat([{"role": "system", "content": _WRITE_SYS}, {"role": "user", "content": f"Topic: {topic}"}],
                     tier="smart", purpose="video_script", max_tokens=1600)
    sc = _json(r.text or "")
    if not sc and script.strip():  # the AI failed: one scene per 2 sentences, titles from their first words
        sents = re.split(r"(?<=[.!?])\s+", script.strip())
        sc = [{"title": " ".join(" ".join(sents[i:i + 2]).split()[:5]), "points": [], "say": " ".join(sents[i:i + 2])}
              for i in range(0, len(sents), 2)][:MAX_SCENES]
    return sc


def transcribe_voiceover(path: Path) -> tuple[str, list[dict]]:
    """(full text, segments [{start, end, text}]) of your recorded voice (Groq Whisper, free)."""
    from jarvis.core import llm
    with tempfile.TemporaryDirectory() as d:
        mp3 = Path(d) / "v.mp3"  # small upload (the free API takes up to 25 MB)
        _ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(mp3)])
        r = llm.get_client().audio.transcriptions.create(model=config.STT_FALLBACK, file=("v.mp3", mp3.read_bytes()),
                                                         response_format="verbose_json", temperature=0.0)
    segs = [{"start": float(s["start"] if isinstance(s, dict) else s.start), "end": float(s["end"] if isinstance(s, dict) else s.end),
             "text": str(s["text"] if isinstance(s, dict) else s.text).strip()} for s in (getattr(r, "segments", None) or [])]
    return str(getattr(r, "text", "") or " ".join(s["text"] for s in segs)), segs


def _ffmpeg(args: list[str], timeout: float = 900) -> None:
    cmd = (["nice", "-n", "10"] if shutil.which("nice") else []) + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError((r.stderr or "ffmpeg failed").strip().splitlines()[-1][:200])


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=30).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _font(path: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def slide(size: tuple[int, int], title: str, points: list[str], shown: int, n: int, total: int, label: str = ""):
    """One frame: gradient background, scene title, the first `shown` points, progress bar (scene n of total)."""
    from PIL import Image, ImageDraw
    w, h = size
    img = Image.new("RGB", size, BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(h):  # vertical gradient
        k = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * k) for i in range(3)))
    vertical = h > w
    pad = int(w * (0.08 if vertical else 0.07))
    tf = _font(FONT_BOLD, int(w * (0.088 if vertical else 0.048)))
    pf = _font(FONT, int(w * (0.058 if vertical else 0.03)))
    y = int(h * (0.22 if vertical else 0.14))
    if label:
        d.text((pad, y - int(h * 0.05)), label.upper(), font=_font(FONT_BOLD, int(w * (0.03 if vertical else 0.018))),
               fill=ACCENT)
    for line in _wrap(d, title, tf, w - 2 * pad)[:3]:
        d.text((pad, y), line, font=tf, fill=TEXT)
        y += int(tf.size * 1.2)
    d.rectangle((pad, y + 10, pad + int(w * 0.12), y + 16), fill=ACCENT)
    y += int(h * (0.06 if vertical else 0.08))
    for p in points[:shown]:
        lines = _wrap(d, p, pf, w - 2 * pad - int(pf.size * 1.6))
        r = int(pf.size * 0.22)
        cy = y + pf.size // 2 + 2
        d.ellipse((pad, cy - r, pad + 2 * r, cy + r), fill=ACCENT)
        for ln in lines[:3]:
            d.text((pad + int(pf.size * 1.3), y), ln, font=pf, fill=TEXT)
            y += int(pf.size * 1.3)
        y += int(pf.size * 0.6)
    bar_y = h - int(h * 0.02)  # progress: scene n of total
    d.rectangle((0, bar_y, w, h), fill=(30, 44, 86))
    d.rectangle((0, bar_y, int(w * n / max(1, total)), h), fill=ACCENT)
    return img


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _captions(say: str, start: float, dur: float, max_words: int) -> list[tuple[float, float, str]]:
    """The narration cut into short caption chunks, timed by their share of the words."""
    words = say.split()
    if not words:
        return []
    chunks = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    per = dur / len(words)
    out, t = [], start
    for c in chunks:
        d = per * len(c.split())
        out.append((t, t + d, c))
        t += d
    return out


async def _speak(text: str, path: Path, voice: str) -> None:
    from jarvis.core import tts
    with open(path, "wb") as f:
        async for chunk in tts.edge_synth(text, voice):
            f.write(chunk)


def render(scenes: list[dict], title: str, fmt: str = "youtube", voiceover: Path | None = None,
           segments: list[dict] | None = None, progress=lambda _: None) -> Path:
    """scenes [{title, points, say}] -> MP4 (slides + voice + burned captions)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg isn't installed (sudo apt install ffmpeg)")
    size = size_for(fmt)
    out_dir = config.OUTPUTS_DIR / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'explainer'}.mp4"
    from jarvis.core import audiomaker, tts
    with tempfile.TemporaryDirectory(prefix="kurama-explainer-") as tmp:
        t = Path(tmp)
        # 1. the soundtrack and each scene's time on screen
        if voiceover is not None:
            total_s = _duration(voiceover)
            durs = _durations_from_voice(scenes, segments or [], total_s)
            audio = voiceover
        else:
            mp3s = []
            for i, sc in enumerate(scenes):
                progress(f"voice {i + 1}/{len(scenes)}")
                mp3 = t / f"v{i}.mp3"
                asyncio.run(_speak(sc["say"], mp3, tts.voice_for(audiomaker.voice_lang(sc["say"]))))
                mp3s.append(mp3)
            durs = [_duration(m) + 0.5 for m in mp3s]
            lst = t / "a.txt"
            for i, m in enumerate(mp3s):  # each scene's voice + a short pause
                _ffmpeg(["-i", str(m), "-af", "apad=pad_dur=0.5", "-ar", "44100", "-ac", "2", str(t / f"p{i}.wav")])
            lst.write_text("".join(f"file '{t / f'p{i}.wav'}'\n" for i in range(len(mp3s))))
            audio = t / "voice.wav"
            _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(audio)])
        # 2. the slides: the points appear one by one while the scene is spoken
        frames, srt, clock = [], [], 0.0
        for i, sc in enumerate(scenes):
            progress(f"slides {i + 1}/{len(scenes)}")
            pts = sc.get("points") or []
            stages = len(pts) + 1
            for k in range(stages):
                img = t / f"s{i}_{k}.png"
                slide(size, sc.get("title") or title, pts, k, i + 1, len(scenes),
                      label=title if i == 0 else f"{i + 1} / {len(scenes)}").save(img)
                frames.append((img, durs[i] / stages))
            srt += _captions(sc["say"], clock, durs[i], 6 if size[1] > size[0] else 10)
            clock += durs[i]
        lst = t / "v.txt"
        lst.write_text("".join(f"file '{f}'\nduration {d:.3f}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n")
        sub = t / "captions.srt"
        sub.write_text("".join(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{txt}\n\n" for n, (a, b, txt) in enumerate(srt, 1)),
                       encoding="utf-8")
        progress("joining video, voice and captions")
        fs = 13 if size[1] > size[0] else 18
        style = (f"FontName=DejaVu Sans,FontSize={fs},PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,"
                 f"BorderStyle=3,Outline=1,Shadow=0,MarginV={60 if size[1] > size[0] else 40},Alignment=2")
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
                 "-vf", f"fps={FPS},format=yuv420p,subtitles={sub}:force_style='{style}'",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "160k",
                 "-shortest", "-movflags", "+faststart", str(out)])
    return out


def _durations_from_voice(scenes: list[dict], segments: list[dict], total_s: float) -> list[float]:
    """Each scene's time = while you say its words: matched to Whisper's timed segments by the share of words
    (your exact words were kept per scene); without segments, by the share of words of the whole voiceover."""
    words = [max(1, len(s["say"].split())) for s in scenes]
    if not segments:
        return [total_s * w / sum(words) for w in words]
    seg_words = []  # every word with its time, spread evenly inside its segment
    for s in segments:
        ws = s["text"].split()
        for j, _ in enumerate(ws):
            seg_words.append(s["start"] + (s["end"] - s["start"]) * j / max(1, len(ws)))
    if not seg_words:
        return [total_s * w / sum(words) for w in words]
    bounds, acc = [], 0
    for w in words:
        acc += w
        idx = min(len(seg_words) - 1, round(acc * len(seg_words) / sum(words)) - 1)
        bounds.append(seg_words[idx] if acc < sum(words) else total_s)
    out, prev = [], 0.0
    for b in bounds:
        out.append(max(1.0, b - prev))
        prev = b
    return out


def make(topic: str = "", script: str = "", voiceover: str = "", fmt: str = "youtube", progress=lambda _: None) -> Path:
    """The whole job: scenes (from topic / script / your voice) -> rendered MP4."""
    vo = Path(voiceover).expanduser() if voiceover.strip() else None
    segments: list[dict] = []
    if vo is not None:
        if not vo.is_file():
            raise RuntimeError(f"the voiceover file {vo} doesn't exist")
        progress("listening to your voiceover")
        text, segments = transcribe_voiceover(vo)
        script = script or text
    progress("planning the scenes")
    scenes = scenes_from(topic, script)
    if not scenes:
        raise RuntimeError("couldn't make the scenes (the AI gave nothing); try again in a minute")
    return render(scenes, topic or scenes[0]["title"], fmt, vo, segments, progress)
