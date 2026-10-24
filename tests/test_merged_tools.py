"""Step 0 cleanup: merged tools dispatch to the old helpers, retired names still work (mocked)."""
from jarvis.core import registry, safety
from jarvis.tools.general import audio as audio_mod
from jarvis.tools.general import clipboard as clip_mod
from jarvis.tools.general import jobs as jobs_mod
from jarvis.tools.general import window as win_mod
from jarvis.tools.interactive import git_change as gc_mod

RETIRED = ("volume", "mute_audio", "mic_mute", "read_clipboard", "write_clipboard", "clipboard_history", "list_jobs",
           "job_result", "cancel_job", "resume_job", "list_skills", "use_skill", "delete_skill", "list_schedules",
           "cancel_schedule", "git_status", "git_log", "git_diff_summary", "git_commit", "git_branch", "precommit_gate",
           "repo_hygiene", "secrets_audit", "focus_app", "list_windows", "snap_window", "auto_theme",
           "convert_currency", "find_and_send", "playlist", "focus_timer")


def test_retired_names_are_aliases_not_tools():
    for old in RETIRED:
        assert registry.get(old) is None, old  # the LLM never sees them
        new, _ = registry.resolve(old, {})
        assert registry.get(new) is not None, (old, new)
    for gone in ("add_docstrings", "benchmark_table", "read_aloud", "n8n_trigger", "news_headlines"):
        assert registry.get(gone) is None and registry.resolve(gone, {})[0] == gone
    assert registry.resolve("job_result", {"job_id": 7}) == ("jobs", {"job": "7", "action": "result"})
    assert registry.resolve("git_branch", {"name": "dev", "action": "create"})[1]["action"] == "new_branch"
    assert registry.resolve("snap_window", {"position": "left"}) == ("window", {"action": "left", "name": ""})
    assert registry.resolve("convert_currency", {"amount": 5, "from_currency": "usd"})[1] == {"expression": "5 usd to NPR"}


def test_audio_routes_to_the_right_helper(monkeypatch):
    seen = []
    monkeypatch.setattr(audio_mod, "volume", lambda a, lvl, s: seen.append(("vol", a, lvl)) or "ok")
    monkeypatch.setattr(audio_mod, "mute_audio", lambda a: seen.append(("spk", a)) or "ok")
    monkeypatch.setattr(audio_mod, "mic_mute", lambda a: seen.append(("mic", a)) or "ok")
    audio_mod.audio("set", level=40)
    audio_mod.audio("mute")
    audio_mod.audio("mute", target="mic")
    assert audio_mod.audio("up", target="mic").startswith("error")
    assert safety.execute("volume", {"action": "down"}).ok and safety.execute("mic_mute", {"action": "unmute"}).ok
    assert seen == [("vol", "set", 40), ("spk", "mute"), ("mic", "mute"), ("vol", "down", None), ("mic", "unmute")]


def test_clipboard_jobs_window_dispatch(monkeypatch):
    monkeypatch.setattr(clip_mod, "write_clipboard", lambda t: f"copied {t}")
    monkeypatch.setattr(clip_mod, "read_clipboard", lambda n: "on the clipboard")
    assert clip_mod.clipboard("write", text="hi") == "copied hi" and clip_mod.clipboard() == "on the clipboard"
    monkeypatch.setattr(jobs_mod, "job_result", lambda i: f"job {i}")
    assert jobs_mod.jobs("result", "#12") == "job 12" and jobs_mod.jobs("result", "x").startswith("error")
    monkeypatch.setattr(win_mod, "snap_window", lambda p, w: f"{p}:{w}")
    assert win_mod.window("left", "code") == "left:code" and win_mod.window("focus").startswith("error")


def test_git_change_asks_first_and_maps_branch(monkeypatch):
    calls = []
    monkeypatch.setattr(gc_mod, "git_branch", lambda n, a, r: calls.append((n, a)) or "ok")
    assert "declined" in safety.execute("git_branch", {"name": "dev"}, confirm=lambda p: False).output.lower()
    assert safety.execute("git_branch", {"name": "dev", "action": "create"}, confirm=lambda p: True).ok
    assert calls == [("dev", "create")]


def test_skills_delete_asks(monkeypatch):
    from jarvis.tools.general import skills as sk
    monkeypatch.setattr(sk, "delete_skill", lambda n: f"deleted {n}")
    out = safety.execute("skills", {"action": "delete", "name": "x"}, confirm=lambda p: False).output
    assert "nothing was deleted" in out
    assert safety.execute("delete_skill", {"name": "x"}, confirm=lambda p: True).output == "deleted x"
