"""generate_image: make an image from a text prompt (the user's image workers, then Pollinations) as a background job (safe).

Default look: cinematic vector art, high contrast; a style the user names replaces it.

The picture is saved under data/outputs/images/ and shows up in the UI workspace when the job finishes.
"""
from __future__ import annotations

import re
import time
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


# size words -> (width, height): 'phone wallpaper', 'square logo', 'youtube thumbnail'...
SIZES = ((r"\b(?:phone|mobile|iphone|android)\s+(?:wallpaper|background|screen)|\b(?:portrait|vertical|story|reel|tiktok)\b", (1080, 1920)),
         (r"\b(?:square|instagram\s+post|profile\s+(?:pic|picture|photo)|dp|avatar|logo|icon|sticker)\b", (1024, 1024)),
         (r"\b(?:thumbnail|banner|youtube\s+cover|cover\s+image|landscape|wide)\b", (1280, 720)),
         (r"\b(?:poster|flyer|book\s+cover|a4)\b", (1024, 1448)),
         (r"\b(?:desktop\s+)?wallpaper\b|\bdesktop\s+background\b|\b4k\b|\bfull\s*hd\b", (1920, 1080)))
LAST_KEY = "image_last"  # the last prompt + seed, for 'same picture but at night' / 'another version'


def size_for(prompt: str) -> tuple[int, int] | None:
    return next((wh for rx, wh in SIZES if re.search(rx, prompt, re.I)), None)


def _get(client, api: str, prompt: str, width: int, height: int, seed: int | None = None, enhance: bool = False):
    if api == "pollinations":
        params = {"width": width, "height": height, "nologo": "true", "private": "true"}
        if seed is not None:
            params["seed"] = seed
        if enhance:
            params["enhance"] = "true"
        return client.get(POLLINATIONS.format(prompt=quote(prompt)), params=params)
    return client.get(api, params={"prompt": prompt})


def fetch_image(prompt: str, width: int, height: int, seed: int | None = None, enhance: bool = False,
                exact: bool = False) -> bytes:
    """Try each service in config.IMAGE_APIS until one returns a picture (patched in tests: no network).
    exact=True (a size, seed or variation was asked): Pollinations first, it's the one that obeys them."""
    import httpx  # lazy

    errors = []
    apis = list(config.IMAGE_APIS)
    if exact and "pollinations" in apis:
        apis.remove("pollinations")
        apis.insert(0, "pollinations")
    with httpx.Client(timeout=config.IMAGE_TIMEOUT_S, follow_redirects=True) as client:
        for api in apis:
            try:
                r = _get(client, api.strip(), prompt, width, height, seed, enhance)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and r.content:
                    return r.content
                errors.append(f"{r.status_code}")
            except httpx.HTTPError as e:
                errors.append(type(e).__name__)
    raise RuntimeError(f"no image service answered ({', '.join(errors)})")


@tool(group="image", safety="safe",
      description="Generate pictures from a text description (free; 1-4 versions, any size, or a change of the last "
                  "picture); runs in the background, shows in the workspace.")
def generate_image(prompt: str, set_as_wallpaper: bool = False, send_to_telegram: bool = False, width: int = 0,
                   height: int = 0, count: int = 1, change_last: bool = False, detailed: bool = False) -> str:
    """Create images.

    Args:
        prompt: What the picture should show, in English; include a style only if the user asked for one. With
            change_last: only the change ('at night', 'more colorful').
        set_as_wallpaper: True when the user also wants it as the desktop wallpaper (done when the image is ready).
        send_to_telegram: True when the user also wants the picture on Telegram/phone (sent when it's ready).
        width: Pixels, 256 to 1920 (0 = from the words: phone wallpaper, square logo, thumbnail... or 1024x768).
        height: Pixels, 256 to 1920.
        count: How many different versions (1-4).
        change_last: True for 'the same picture but ...' / 'another version' (uses the last picture's prompt).
        detailed: True when the user wants more detail / a better picture (the service improves the prompt).
    """
    import json
    import random

    from jarvis.core import jobs, store

    prompt = (prompt or "").strip()
    last = {}
    try:
        last = json.loads(store.kv_get(LAST_KEY) or "{}")
    except ValueError:
        pass
    seed = None
    if change_last:
        if not last.get("prompt"):
            return "error: I haven't made a picture yet; tell me what it should show"
        if re.fullmatch(r"(?:another|a\s+new|a\s+different|one\s+more)(?:\s+(?:version|one|variation|try))?|again", prompt, re.I) or not prompt:
            prompt = last["prompt"]
        else:  # same composition (same seed), with the change
            prompt, seed = f"{last['prompt']}, {prompt}", last.get("seed")
        width, height = width or last.get("w", 0), height or last.get("h", 0)
    if not prompt:
        return "error: tell me what the picture should show"
    asked = size_for(prompt)
    dw, dh = (1920, 1080) if set_as_wallpaper else asked or (1024, 768)
    w, h = max(256, min(int(width or dw), 1920)), max(256, min(int(height or dh), 1920))
    n = max(1, min(int(count or 1), 4))
    exact = bool(asked or width or height or n > 1 or change_last or detailed)
    seeds = [seed if seed is not None and i == 0 else random.randint(1, 10 ** 6) for i in range(n)]
    store.kv_set(LAST_KEY, json.dumps({"prompt": prompt, "seed": seeds[0], "w": w, "h": h, "at": time.time()}))

    def make(sd):
        def job(ctx):
            ctx.progress("drawing")
            data = fetch_image(styled(prompt), w, h, seed=sd, enhance=detailed, exact=exact)
            out = config.OUTPUTS_DIR / "images"
            out.mkdir(parents=True, exist_ok=True)
            ext = "png" if data[:4] == b"\x89PNG" else "jpg"
            path = out / f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(prompt)}{'-' + str(sd) if n > 1 else ''}.{ext}"
            path.write_bytes(data)
            if set_as_wallpaper:
                from jarvis.tools.general import set_wallpaper
                ctx.progress("setting wallpaper")
                set_wallpaper.apply(path)
            return str(path)
        return job

    ids = []
    for i, sd in enumerate(seeds):
        title = f"{'wallpaper' if set_as_wallpaper else 'image'}: {prompt[:40]}" + (f" ({i + 1}/{n})" if n > 1 else "")
        j = jobs.get_manager().submit(title, "image", make(sd), prompt)
        ids.append(j.id)
        if send_to_telegram:
            jobs.then_send(j.id)
    what = f"{n} versions" if n > 1 else "your picture"
    size = f" ({w}x{h})" if asked or width else ""
    jid = ", ".join(f"#{x}" for x in ids)
    if send_to_telegram:
        extra = " and set it as your wallpaper" if set_as_wallpaper else ""
        return f"I'm making {what}{size} now (job {jid}); I'll send it to your Telegram{extra} as soon as it's ready."
    if set_as_wallpaper:
        return f"I'm making your picture now (job {jid}) and will set it as your wallpaper as soon as it's ready."
    return f"I'm making {what}{size} now (job {jid}). It will appear in the workspace in a few seconds."


def last_recent(within_s: float = 1800) -> bool:
    """A picture was made in the last half hour ('make it at night' then means that picture)."""
    import json

    from jarvis.core import store
    try:
        return time.time() - float(json.loads(store.kv_get(LAST_KEY) or "{}").get("at", 0)) < within_s
    except (ValueError, TypeError):
        return False
