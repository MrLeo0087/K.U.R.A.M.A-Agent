"""make_audio: text -> MP3 (edge-tts, free) from the selection, a file, a web page, the newest workspace document or typed words (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="image", safety="safe", description="Turn text into an MP3 (spoken, English/Nepali/Hindi): the highlighted "
      "text, a txt/md/pdf file, a web page link, the newest workspace document ('last'), or given words. Background job.")
def make_audio(source: str = "selection", text: str = "") -> str:
    """Text to audio.

    Args:
        source: 'selection', 'last' (newest workspace document), a URL, a file path, or 'text' (use `text`).
        text: The words to speak when source is 'text'.
    """
    from jarvis.core import audiomaker, jobs

    src = text if source == "text" else source
    try:  # the selection must be read now, while the user's app still has it
        body, title = audiomaker.text_of(src)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"I couldn't read it: {type(e).__name__}: {str(e)[:120]}"
    mins = audiomaker.minutes(body)

    def job(ctx):
        ctx.progress("speaking")
        p = audiomaker.make(body, title)
        ctx.progress(f"» Your audio is ready ({max(1, round(mins))} min). It's in the workspace.")
        return str(p)

    j = jobs.get_manager().submit(f"audio: {title[:40]}", "audio", job, title)
    return f"Making the audio now (about {max(1, round(mins))} min of speech, job #{j.id}). It will appear in the workspace."
