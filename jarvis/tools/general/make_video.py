"""make_video: a short narrated video (pictures + voice + captions) about a topic, from the user's script, or a
slideshow of a folder's pictures; ffmpeg, free; background job (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="image", safety="safe", description="Make a short video (MP4): about a topic (AI writes 4-6 narrated "
      "scenes), from the user's own script, or a slideshow of the pictures in a folder. Background job, free.")
def make_video(topic: str = "", script: str = "", folder: str = "", vertical: bool = False) -> str:
    """Short video.

    Args:
        topic: What the video is about (the AI writes the scenes; one small call).
        script: The user's own narration (each sentence becomes a scene; no AI).
        folder: A folder of pictures for a slideshow (no AI).
        vertical: 720x1280 for reels/shorts; default 1280x720.
    """
    from jarvis.core import jobs, videomaker

    words = " ".join((topic, script))
    size = (720, 1280) if vertical else videomaker.size_for(words)
    if folder:
        pics = videomaker.folder_pictures(folder)
        if not pics:
            return f"I found no pictures in {folder}."
        scenes = [{"say": "", "picture": ""} for _ in pics]
    elif script.strip():
        scenes, pics = videomaker.script_scenes(script, topic), None
    elif topic.strip():
        scenes, pics = None, None
    else:
        return "What should the video be about? Or give me the script or a folder of pictures."
    title = (topic or folder or script)[:40]

    def job(ctx):
        sc = scenes
        if sc is None:
            ctx.progress("writing the scenes")
            sc = videomaker.plan(topic)
        p = videomaker.render(sc, title, size, ctx.progress, pictures=pics)
        ctx.progress(f"» Your video is ready ({len(sc)} scenes). It's in the workspace.")
        return str(p)

    j = jobs.get_manager().submit(f"video: {title}", "video", job, words or folder)
    what = f"a slideshow of {len(pics)} pictures" if folder else "your video"
    return f"Making {what} now (job #{j.id}); it takes a minute or two. It will appear in the workspace."
