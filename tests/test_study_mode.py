"""Plan 11-09 phase 7: Study mode answers about the highlight in its page's context (paragraph, heading, a page
summary made once), one call; notes per document and day, a glossary of terms; follow-ups know the thread; its
requests are understood by meaning; answers stay whole in its chat."""
import pytest

from jarvis import agents
from jarvis.core import browsertab, config, fastpath, llm, semantic, store, studymode, workspace

CTX = {"text": "chain rule", "paragraph": "Backprop uses the chain rule layer by layer.", "heading": "How it works",
       "title": "Backpropagation", "url": "https://en.wikipedia.org/wiki/Backpropagation", "page": "x " * 400,
       "source": "browser"}


@pytest.fixture
def study(monkeypatch, tmp_path):
    kv, calls = {}, []
    monkeypatch.setattr(store, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(studymode, "ROOT", tmp_path)
    monkeypatch.setattr(studymode, "context", lambda: dict(CTX))
    studymode._threads.clear()

    def chat(msgs, **k):
        calls.append((k.get("purpose"), msgs[-1]["content"]))
        text = "summary of the page" if k.get("purpose") == "study_page_summary" else "**chain rule** - multiply the derivatives."
        return type("R", (), {"text": text})()
    monkeypatch.setattr(llm, "chat", chat)
    return calls


def test_an_answer_carries_the_page_context_and_is_saved_only_when_asked(study, tmp_path):
    out = studymode.answer("meaning")
    prompt = study[-1][1]
    assert "chain rule" in out and "Saved" not in out and not list(tmp_path.glob("notes/*/*.md"))  # (11-10: not asked)
    assert "Saved to your notes" in studymode.answer("save")
    for part in ("Page: Backpropagation", "summary of the page", "Section: How it works", "layer by layer",
                 'Selected text:\n"""\nchain rule'):
        assert part in prompt, part
    assert (tmp_path / "glossary.md").read_text().startswith("- **chain rule** — multiply the derivatives.")
    assert list(tmp_path.glob("notes/*/backpropagation.md"))


def test_the_page_is_summarized_once(study):
    studymode.answer("explain")
    studymode.answer("simpler")
    assert [p for p, _ in study].count("study_page_summary") == 1
    assert "Earlier in this study session" in study[-1][1]  # 'simpler' knows the last answer


def test_nothing_selected_says_how(study, monkeypatch):
    monkeypatch.setattr(studymode, "context", lambda: {**CTX, "text": "", "page": ""})
    assert studymode.answer("explain").startswith("Select the text first")


def test_the_browser_sends_paragraph_heading_and_page():
    browsertab.put_selection("chain rule", "https://x/a", "A", paragraph="para", heading="Head", page="the page text")
    c = browsertab.selection_context()
    assert (c["paragraph"], c["heading"], c["page"]) == ("para", "Head", "the page text")


def test_study_answers_stay_whole_in_its_chat(monkeypatch):
    monkeypatch.setattr(agents, "current", lambda: "study")
    text = "\n".join(f"line {i} about the chain rule" for i in range(6))
    assert workspace.to_workspace("t", text)[0] == text


def test_study_requests_by_meaning(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    monkeypatch.setattr(agents, "current", lambda: "study")
    monkeypatch.setattr(studymode, "context", lambda: dict(CTX))
    semantic._tables.clear()
    try:
        for text, task in (("save this", "save"), ("explain this", "explain"), ("what does this mean", "meaning"), ("simpler", "simpler"),
                           ("in nepali", "nepali"), ("summarize this page", "page_summary"), ("quiz me", "quiz"),
                           ("tell me more", "more"), ("how does this relate to backprop", "ask")):
            it = fastpath.match(text)
            assert it is not None and it.tool == "study" and it.args["task"] == task, text
        for text, tool in (("volume up", "volume"), ("open youtube", "open_url"), ("what time is it", "get_time")):
            assert fastpath.match(text).tool == tool, text
    finally:
        semantic._tables.clear()
