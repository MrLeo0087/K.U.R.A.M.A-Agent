"""create: make things: a picture (optionally as the wallpaper or sent to Telegram), a long document/essay
(background job), speech audio, a chart, a diagram, a short video (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "image": Act("generate_image", lambda a: {"prompt": a.get("what"), "send_to_telegram": a.get("telegram", False),
                                              "set_as_wallpaper": a.get("wallpaper", False)}),
    "document": Act("write_document", lambda a: {"request": a.get("what")}),
    "audio": Act("make_audio", lambda a: {"text": a.get("what", "")}),
    "chart": Act("make_chart", lambda a: {"request": a.get("what", "")}),
    "diagram": Act("make_diagram", lambda a: {"target": a.get("what", "")}),
    "video": Act("make_video", lambda a: {"topic": a.get("what")}),
}


@tool(group="core", safety="safe",
      description="Make something: image (picture; can also set it as wallpaper or send it to Telegram), document "
                  "(essay, article, report: runs in the background), audio (speech from text or the selection), chart "
                  "(e.g. of my spending), diagram, video.")
def create(action: Literal["image", "document", "audio", "chart", "diagram", "video"], what: str = "",
           telegram: bool = False, wallpaper: bool = False) -> str:
    """Create.

    Args:
        action: image, document, audio, chart, diagram, video.
        what: Description: the picture / the document request / the text to speak / the chart wanted.
        telegram: image: also send it to Telegram when ready.
        wallpaper: image: also set it as the wallpaper.
    """
    return run(TABLE, {"action": action, "what": what, "telegram": telegram, "wallpaper": wallpaper})
