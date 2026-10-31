"""Owner's 01:00 traces: a too-big folder lists what's inside (and 'send X' finds X there); VS Code + a folder."""
from pathlib import Path

from jarvis.core import config, focus


def test_too_big_folder_lists_its_contents_and_becomes_here(tmp_path, monkeypatch):
    from jarvis.tools.general import send_file_telegram as s
    big, small = tmp_path / "Videos", tmp_path / "Notes"
    big.mkdir(); small.mkdir()
    (big / "a.bin").write_bytes(b"x" * 4000)
    (small / "n.txt").write_text("hello")
    monkeypatch.setattr(config, "TELEGRAM_FILE_MAX_MB", 0.001)  # ~1 KB limit for the test
    msg = s._inside(tmp_path, [big / "a.bin", small / "n.txt"])
    assert "Notes" in msg and "Videos" in msg and "Which one should I send?" in msg
    assert focus.cwd() == tmp_path  # "send Notes" now means tmp_path/Notes


def test_vscode_as_target_with_the_folder_in_text_opens_that_folder():
    from jarvis.tools.core.apps import _open
    name, args = _open({"target": "vscode", "how": "folder", "text": "/media/leo/Project1/Tara"})
    assert name == "open_path" and args == {"path": "/media/leo/Project1/Tara", "app": "vscode"}


def test_unoffered_real_tool_is_found_for_the_retry():
    from jarvis.core import agent, registry
    registry.REGISTRY._ensure()
    t = agent.Agent._unoffered_tool("Tool call validation failed: attempted to call tool 'clipboard' which was not in "
                                    "request.tools", [registry.REGISTRY.tools["apps"]] if "apps" in registry.REGISTRY.tools else [object()])
    assert t is not None and t.name == "clipboard"
