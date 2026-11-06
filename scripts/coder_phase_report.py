"""Send a coding-agent phase report to the owner's Telegram (Claude Code section): `python scripts/coder_phase_report.py
"title" report.md`. Used while the coding agent is built phase by phase."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis.core import notify  # noqa: E402

title, body = sys.argv[1], Path(sys.argv[2]).read_text(encoding="utf-8")
print(notify.notify(title, body, source="claude_code", desktop=False, telegram=True))
