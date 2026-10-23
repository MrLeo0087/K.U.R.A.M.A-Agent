"""`python -m jarvis` -> terminal text chat (`--voice` / `--wake` -> voice loop)."""
from jarvis.core.privacy import harden

harden()  # before anything creates files under data/

from jarvis.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
