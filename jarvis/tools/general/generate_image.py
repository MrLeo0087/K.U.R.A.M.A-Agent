"""generate_image: make an image from a text prompt (the user's image workers, then Pollinations) as a background job (safe).

Default look: cinematic vector art, high contrast; a style the user names replaces it.

The picture is saved under data/outputs/images/ and shows up in the UI workspace when the job finishes.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

from jarvis.core import config
from jarvis.core.registry import tool

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"
_STYLE_WORDS = re.compile(
    r"\b(?:style|styled|realistic|photo\w*|watercolou?r|oil|acrylic|sketch\w*|pencil|ink|anime|manga|cartoon\w*|"
    r"pixel|3d|render\w*|clay|lego|cyberpunk|steampunk|vintage|retro|minimal\w*|abstract|surreal\w*|comic|"
    r"painting|painted|drawing|line art|flat|isometric|low poly|neon|noir|black and white|monochrome|pastel|"
    r"fantasy art|concept art|vector|cinematic|ghibli|disney|pixar|impressionis\w*|charcoal|digital art)\b", re.I)


def styled(prompt: str) -> str:
    """The user's own style wins; otherwise add the default cinematic vector look."""
    return prompt if _STYLE_WORDS.search(prompt) else f"{prompt}, {config.IMAGE_DEFAULT_STYLE}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "image"


def _get(client, api: str, prompt: str, width: int, height: int):
    if api == "pollinations":
        return client.get(POLLINATIONS.format(prompt=quote(prompt)),
                          params={"width": width, "height": height, "nologo": "true", "private": "true"})
    return client.get(api, params={"prompt": prompt})


def fetch_image(prompt: str, width: int, height: int) -> bytes:
    """Try each service in config.IMAGE_APIS until one returns a picture (patched in tests: no network)."""
    import httpx  # lazy

    errors = []
    with httpx.Client(timeout=config.IMAGE_TIMEOUT_S, follow_redirects=True) as client:
        for api in config.IMAGE_APIS:
            try:
                r = _get(client, api.strip(), prompt, width, height)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and r.content:
                    return r.content
                errors.append(f"{r.status_code}")
            except httpx.HTTPError as e:
                errors.append(type(e).__name__)
    raise RuntimeError(f"no image service answered ({', '.join(errors)})")


@tool(group="image", safety="safe",
      description="Generate a picture from a text description (free); runs in the background, shows in the workspace.")
def generate_image(prompt: str, width: int = 1024, height: int = 768) -> str:
    """Create an image.

    Args:
        prompt: What the picture should show, in English; include a style only if the user asked for one.
        width: Pixels, 256 to 1536.
        height: Pixels, 256 to 1536.
    """
    from jarvis.core import jobs

    prompt = (prompt or "").strip()
    if not prompt:
        return "error: tell me what the picture should show"
    w, h = (max(256, min(int(v or 768), 1536)) for v in (width, height))

    def job(ctx):
        ctx.progress("drawing")
        data = fetch_image(styled(prompt), w, h)
        out = config.OUTPUTS_DIR / "images"
        out.mkdir(parents=True, exist_ok=True)
        ext = "png" if data[:4] == b"\x89PNG" else "jpg"
        path = out / f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(prompt)}.{ext}"
        path.write_bytes(data)
        return str(path)

    j = jobs.get_manager().submit(f"image: {prompt[:40]}", "image", job, prompt)
    return f"I'm making your picture now (job #{j.id}). It will appear in the workspace in a few seconds."
