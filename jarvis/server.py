"""`python -m jarvis.server [--port 8000] [--host 127.0.0.1] [--no-warm]` -> http://127.0.0.1:8000

Thin shim kept for old commands/autostart entries: it runs the KURAMA API (jarvis/api, FastAPI,
/api/v1/*, docs at /docs) which also serves the KURAMA holographic UI (frontend/) at /.
"""
from __future__ import annotations

import sys
import threading
import time


def lean_malloc(every_s: int = 120) -> None:
    """glibc gives each busy thread its own malloc arena (up to 8 per core), each keeping its freed memory:
    cap them at 2 and hand free heap back to the OS every 2 minutes. Same speed, lower idle RSS."""
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        libc.mallopt(-8, 2)  # M_ARENA_MAX
    except (OSError, AttributeError):
        return

    def trim() -> None:
        while True:
            time.sleep(every_s)
            libc.malloc_trim(0)

    threading.Thread(target=trim, name="jarvis-trim", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    from jarvis.core.privacy import harden

    lean_malloc()  # before the server starts its threads

    harden()  # data/ files private to this user
    from jarvis.api.app import main as api_main

    return api_main(argv, prog="python -m jarvis.server")


if __name__ == "__main__":
    sys.exit(main())
