"""'free RAM' offers to close windowless idle apps (asks first); /clear ram | storage | kurama clean that."""
import pytest

from jarvis.core import cleanup, safety, slash


@pytest.mark.parametrize("text,target", [("/clear ram", "ram"), ("/clear RAM", "ram"), ("/clear kurama storage", "kurama"),
                                         ("/clear KURAMA", "kurama"), ("/clear storage", "storage")])
def test_clear_with_a_target_cleans_it(text, target):
    cmd, arg, _ = slash.lookup(text)
    assert slash.tool_call(cmd, arg) == ("cleanup", "system", {"action": target})


@pytest.mark.parametrize("text", ["/clear", "/clear yes"])
def test_plain_clear_keeps_its_old_meaning(text):
    cmd, arg, _ = slash.lookup(text)
    assert slash.tool_call(cmd, arg)[0] == "_cmd"


class FakeProc:
    def __init__(self, pid):
        self.pid, self.stopped = pid, False

    def terminate(self):
        self.stopped = True


@pytest.mark.parametrize("answer", [True, False])
def test_idle_background_apps_close_only_after_yes(monkeypatch, answer):
    import psutil
    monkeypatch.setattr(cleanup, "idle_background", lambda: [("ollama", [4242], 2_100_000_000), ("python3", [4343], 300_000_000)])
    made = {}
    monkeypatch.setattr(psutil, "Process", lambda pid: made.setdefault(pid, FakeProc(pid)))
    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout=3: (procs, []))
    asked = []
    tok = safety._CTX.set({"confirm": lambda p: asked.append(p) or answer})
    try:
        out = cleanup.close_idle_background()
    finally:
        safety._CTX.reset(tok)
    assert asked and "ollama 2.1 GB" in asked[0] and "Close them" in asked[0]
    assert (bool(made) and all(p.stopped for p in made.values())) == answer and (out.startswith("Closed 2") if answer else "Left" in out)


def test_nothing_idle_means_no_question(monkeypatch):
    monkeypatch.setattr(cleanup, "idle_background", lambda: [])
    assert cleanup.close_idle_background() == ""


def test_never_guesses_without_seeing_windows(monkeypatch):
    monkeypatch.setattr(cleanup, "_window_pids", lambda: set())
    assert cleanup.idle_background() == []


@pytest.mark.parametrize("text,target", [("/clear ram", "ram"), ("/clear kurama storage", "kurama"), ("/clear KURAMA", "kurama")])
def test_clear_targets_through_the_fast_path(text, target):
    from jarvis.core import fastpath
    it = fastpath.slash_intent(text)
    assert (it.tool, it.args) == ("cleanup", {"action": target})


@pytest.mark.parametrize("text", ["/clear KURAMA", "/clear kurama", "/clear Kurama storage"])
def test_clear_kurama_survives_name_stripping(text):
    from jarvis.core import fastpath
    it = fastpath._match(text)
    assert (it.tool, it.args) == ("cleanup", {"action": "kurama"})
