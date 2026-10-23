"""`python -m jarvis.server [--port 8000] [--host 127.0.0.1] [--no-warm]` -> http://127.0.0.1:8000

Thin shim kept for old commands/autostart entries: it runs the Jarvis API (jarvis/api, FastAPI,
/api/v1/*, docs at /docs) which also serves the KURAMA holographic UI (frontend/) at /.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from jarvis.core.privacy import harden

    harden()  # data/ files private to this user
    from jarvis.api.app import main as api_main

    return api_main(argv, prog="python -m jarvis.server")


if __name__ == "__main__":
    sys.exit(main())
