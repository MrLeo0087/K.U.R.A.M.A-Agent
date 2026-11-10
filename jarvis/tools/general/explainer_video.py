"""explainer_video: an educational explainer video ("how transformers work") from a topic, your script and/or your
recorded voiceover: slides whose points appear while it's spoken, captions, progress bar; 16:9 or 9:16 reel; free,
background job (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="image", safety="safe",
      description="Make an explainer / educational video (slides + narration + captions) about a topic like 'how "
                  "transformers work': from the topic (AI writes it), from the user's script (their exact words), "
                  "and/or from their own recorded voiceover file; youtube (16:9) or reel (9:16). Background job.")
def explainer_video(topic: str = "", script: str = "", voiceover: str = "",
                    format: Literal["youtube", "reel"] = "youtube") -> str:
    """Explainer video.

    Args:
        topic: What it explains (also the title).
        script: The user's own narration (kept word for word).
        voiceover: Path of the user's recorded voice (mp3 / wav / m4a / ogg); it becomes the soundtrack.
        format: youtube = 1920x1080, reel = 1080x1920 (Instagram / Shorts).
    """
    from pathlib import Path

    from jarvis.core import explainer, jobs
    t = topic.strip().strip("\"'")
    if t and not voiceover and Path(t).expanduser().suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".opus",
                                                                       ".aac", ".flac") and Path(t).expanduser().is_file():
        voiceover, topic = t, ""  # '/reel ~/voice.mp3': the voiceover itself
    elif len(t.split()) > 25 and not script:
        script, topic = t, " ".join(t.split()[:6])  # a long text is the script (its first words name the video)
    if not (topic.strip() or script.strip() or voiceover.strip()):
        return "What should the video explain? Give a topic, your script, or your voiceover file."
    title = (topic or script or voiceover)[:40]

    def job(ctx):
        p = explainer.make(topic, script, voiceover, format, ctx.progress)
        ctx.progress(f"» Your explainer video is ready: {p.name} (in the workspace; say 'send it to telegram').")
        return str(p)

    j = jobs.get_manager().submit(f"explainer video: {title}", "video", job, topic or script[:200] or voiceover)
    return (f"Making the explainer video now (job #{j.id}): {'your voice' if voiceover else 'a narrated voice'}, "
            f"{'9:16 reel' if format == 'reel' else '16:9'}. It takes 1-3 minutes; watch it in Progress.")
