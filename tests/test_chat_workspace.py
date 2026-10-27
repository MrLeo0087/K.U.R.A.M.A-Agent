"""Long answers never fill the chat: one short line there, the full text in the workspace (owner's rule)."""
from jarvis.core import config, fastpath, workspace

NEWS = """Latest news:
1. Top officials from Mecca pact countries to meet Iranian officials in Tehran (The Jerusalem Post, 41 min ago)
2. Lula Wins Brazil Presidential Election in Surprise Comeback (Bloomberg.com, 50 min ago)
3. Big News Stories Overnight - Monday, October 26, 2026 (Go Local Prov, 1 h ago)
4. KGW Top Stories: 11 p.m., Sunday October 25, 2026 (KGW, 1 h ago)
5. Video. Latest news bulletin | October 26th, 2026 - Morning (Euronews, 1 h ago)"""


def test_rule():
    assert workspace.too_long(NEWS)
    assert not workspace.too_long("It's 1:15 PM.") and not workspace.too_long("Done.\nSaved it.")
    assert workspace.too_long("x " * 300)
    assert workspace.short_line(NEWS) == "I found latest news (5 items). It's in the workspace."
    ballon = ("The 2026 Ballon d’Or top‑10 men’s rankings are (source: Sporting News, 27 Oct 2026):\n"
              + "\n".join(f"{i}. Player {i}" for i in range(1, 11)))
    assert workspace.short_line(ballon) == "I found the 2026 Ballon d’Or top‑10 men’s rankings (10 items). It's in the workspace."
    prose = "Nepal is a country in South Asia. It has eight of the ten highest mountains. " * 8
    line = workspace.short_line(prose)
    assert line.startswith("Nepal is a country in South Asia.") and line.endswith("The full answer is in the workspace.")
    assert len(line) < 300


def test_to_workspace_saves_the_full_text(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    line, path = workspace.to_workspace("latest news", NEWS)
    assert line == "I found latest news (5 items). It's in the workspace." and path.parent.name == "answers"
    assert "Lula Wins" in path.read_text()
    assert workspace.to_workspace("time", "It's 1:15 PM.") == ("It's 1:15 PM.", None)


def test_fastpath_news_goes_to_the_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    from jarvis.core import live, safety
    monkeypatch.setattr(safety, "execute", lambda *a, **k: safety.ToolResult(True, NEWS) if hasattr(safety, "ToolResult")
                        else type("R", (), {"ok": True, "output": NEWS, "error": ""})())
    res = fastpath.try_answer("latest news")
    assert res.answer.endswith("in the workspace.") and res.workspace and "Lula" not in res.answer
    tg = fastpath.try_answer("latest news", ctx={"channel": "telegram"})  # the phone has no workspace
    assert "Lula" in tg.answer


def test_llm_answers_too(monkeypatch, tmp_path):
    """turns.py: a long LLM reply is replaced by its short line in the 'done' event."""
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    from jarvis.api import turns
    from jarvis.api.settings import Settings

    class Ag:
        last = {"tier": "fast"}

        def stream(self, text, mode="text", lang=None):
            yield from (NEWS[:200], NEWS[200:])

    eng = turns.Engine(Settings())
    eng._agent = Ag()
    monkeypatch.setattr(eng, "agent", lambda: Ag())
    events = []
    t = type("T", (), {"closed": False, "confirm_ids": [], "push": lambda self, e: events.append(e)})()
    eng.run_turn(t, "latest news", "text", "en")
    done = next(e for e in events if e and e.get("type") == "done")
    assert done["text"] == "I found latest news (5 items). It's in the workspace." and done["workspace"]
