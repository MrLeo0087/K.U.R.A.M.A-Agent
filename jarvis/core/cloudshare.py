"""Share a big file by uploading it to a free host and returning ONE download link (no account, no API key).

Used when a file/folder is too big for Telegram's 50 MB bot limit: instead of splitting into parts (a pain to
rebuild on a phone), KURAMA uploads the zip once and sends a single link the user taps to download the whole thing.

Primary host: gofile.io (free, no account, handles multi-GB files; links can expire). Because the file leaves
the laptop to a public host, the link is unguessable but anyone who has it can download — fine for sharing your
own files, not for secrets. All uploads are logged.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

TIMEOUT = 600  # big uploads take a while


class ShareError(RuntimeError):
    pass


def _gofile_server() -> str:
    r = requests.get("https://api.gofile.io/servers", timeout=30)
    r.raise_for_status()
    data = r.json()
    servers = (data.get("data") or {}).get("servers") or []
    if not servers:
        raise ShareError("gofile has no upload server available right now")
    return servers[0]["name"]


def upload_gofile(path: str) -> str:
    """Upload one file to gofile.io; returns the public download-page URL."""
    server = _gofile_server()
    url = f"https://{server}.gofile.io/contents/uploadfile"
    import os
    with open(path, "rb") as fh:
        r = requests.post(url, files={"file": (os.path.basename(path), fh)}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise ShareError(f"gofile upload rejected: {str(data)[:150]}")
    page = (data.get("data") or {}).get("downloadPage")
    if not page:
        raise ShareError("gofile didn't return a download link")
    return page


def share(path: str) -> str:
    """Upload a file to a free host and return a download link. Raises ShareError if it couldn't."""
    import os
    size_mb = os.path.getsize(path) / (1024 * 1024)
    log.info("cloud share: uploading %s (%.0f MB)", os.path.basename(path), size_mb)
    try:
        link = upload_gofile(path)
    except Exception as e:
        log.warning("gofile upload failed: %s", e)
        raise ShareError(f"the upload host didn't work ({str(e)[:120]})") from e
    log.info("cloud share: %s -> %s", os.path.basename(path), link)
    return link
