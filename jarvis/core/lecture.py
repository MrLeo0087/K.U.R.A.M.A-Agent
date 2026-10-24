"""Lecture recorder: record a class (the microphone, or the laptop's own sound for an online class), then turn it
into a transcript saved in ~/Notes/Lectures (a background job; Groq Whisper uses the audio quota, not chat tokens).

Recording: ffmpeg from PulseAudio, mono 16 kHz Opus at 24 kbit/s (~11 MB per hour), at most LECTURE_MAX_MIN.
Transcribing: 10-minute chunks -> Whisper -> one Markdown file with a [mm:ss] mark per chunk. A summary is only made
when you ask for it ("summarize my lecture", ~1-2k tokens).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from jarvis.core import config, store

CHUNK_S = 600


def rec_dir() -> Path:
    d = Path(config.DATA_DIR) / "lectures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state() -> dict:
    return json.loads(store.kv_get("lecture_rec") or "{}")


def recording() -> bool:
    st = state()
    return bool(st.get("pid")) and Path(f"/proc/{st['pid']}").exists()


def source(where: str) -> str:
    if where == "laptop":  # the sound the laptop plays (online class): the default speaker's monitor
        sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{sink}.monitor" if sink else "default"
    return "default"


def start(title: str = "", where: str = "mic") -> str:
    if recording():
        st = state()
        return f"Already recording '{st['title']}' for {int((time.time() - st['start']) / 60)} min."
    title = (title or f"Lecture {time.strftime('%d %b %H:%M')}").strip()[:60]
    path = rec_dir() / f"{time.strftime('%Y%m%d-%H%M')}-{''.join(c if c.isalnum() else '-' for c in title)[:40]}.ogg"
    args = ["ffmpeg", "-loglevel", "error", "-f", "pulse", "-i", source(where), "-ac", "1", "-ar", "16000",
            "-c:a", "libopus", "-b:a", "24k", "-t", str(config.LECTURE_MAX_MIN * 60), str(path)]
    try:
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             start_new_session=True)
    except OSError as e:
        return f"error: couldn't start recording ({e})"
    time.sleep(0.8)
    if p.poll() is not None:
        return f"error: recording failed: {(p.stderr.read() or b'').decode()[-200:]}"
    store.kv_set("lecture_rec", json.dumps({"pid": p.pid, "path": str(path), "title": title, "start": time.time(),
                                            "where": where}))
    what = "the laptop's sound" if where == "laptop" else "the microphone"
    return f"Recording '{title}' from {what}. Say 'stop the recording' when the class ends and I'll write it down."


def stop() -> str:
    st = state()
    if not st.get("pid"):
        return "Nothing is being recorded."
    try:
        os.kill(st["pid"], signal.SIGINT)  # ffmpeg finishes the file cleanly
        for _ in range(50):
            if not Path(f"/proc/{st['pid']}").exists():
                break
            time.sleep(0.1)
    except ProcessLookupError:
        pass
    store.kv_set("lecture_rec", "")
    path = Path(st["path"])
    if not path.exists() or path.stat().st_size < 2000:
        return "The recording is empty (was the microphone muted?)."
    mins = int((time.time() - st["start"]) / 60)
    from jarvis.core import jobs
    job = jobs.get_manager().submit(f"transcribe: {st['title']}", "lecture",
                                    lambda ctx: transcribe(ctx, path, st["title"]), request=st["title"])
    return f"Stopped after {mins} min. I'm writing the transcript in the background (job #{job.id}); I'll tell you " \
           f"when it's in your notes."


def chunks(path: Path, tmp: Path) -> list[Path]:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "segment",
                    "-segment_time", str(CHUNK_S), str(tmp / "part%03d.wav")], check=True, timeout=600)
    return sorted(tmp.glob("part*.wav"))


def transcribe(ctx, path: Path, title: str) -> str:
    from jarvis.core import notes, stt

    lines = [f"# {title}", f"Recorded {time.strftime('%A %d %B %Y', time.localtime(path.stat().st_mtime))}", ""]
    with tempfile.TemporaryDirectory() as td:
        parts = chunks(path, Path(td))
        for i, part in enumerate(parts):
            ctx.check()
            ctx.progress(f"part {i + 1} of {len(parts)}")
            try:
                text = stt.transcribe(part.read_bytes(), config.LECTURE_LANG or None).text.strip()
            except Exception as e:
                text = f"(this part could not be transcribed: {type(e).__name__})"
            m, s = divmod(i * CHUNK_S, 60)
            lines.append(f"[{m:02d}:{s:02d}] {text}\n")
    out = notes.root() / "Lectures" / f"{path.stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    ctx.set_output(out)
    return str(out)


def latest_transcript() -> Path | None:
    from jarvis.core import notes
    d = notes.root() / "Lectures"
    files = sorted(d.glob("*.md"), key=lambda f: f.stat().st_mtime) if d.is_dir() else []
    return files[-1] if files else None


SUMMARY_PROMPT = ("Summarize this lecture transcript for a student: the main topics, key definitions and formulas, "
                  "and anything the teacher said is important for the exam. Plain text with short paragraphs.")


def summarize() -> str:
    f = latest_transcript()
    if f is None:
        return "No lecture transcript yet."
    from jarvis.core import llm
    text = f.read_text(errors="replace")[:24000]
    reply = str(llm.chat([{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": text}],
                         tier="fast", purpose="lecture_summary", max_tokens=900, temperature=0.2))
    out = f.with_name(f.stem + " - summary.md")
    out.write_text(f"# Summary: {f.stem}\n\n{reply}\n")
    return f"{reply}\n\n(Saved as {out})"
