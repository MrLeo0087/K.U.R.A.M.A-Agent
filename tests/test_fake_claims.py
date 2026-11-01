"""A tool-less answer that reports something done ("All links have been cleared", "Path is now in your clipboard")
is caught in every grammatical form and retried with the tools the turn already had (traces 2026-10-29..11-01)."""
import pytest
from langchain_core.messages import AIMessage, SystemMessage

from jarvis.core import agent, meta, router


@pytest.mark.parametrize("answer", [
    "All links have been cleared from your store.",                       # f8ac97af102e "clear link store"
    "Your link store is now empty. Let me know if you’d like to add new links or anything else.",
    "The folder path is now in your clipboard.",                          # 2d0721bd1d50 "Copy the path."
    "Added to your list. Let me know if you need anything else.",
    "Chat cleared.",
    "Sure, I've cleared the screen.",
    "I’m writing “yes” into `~/Downloads/main.txt` right now.",
    "Saved the URL https://www.youtube.com/watch?v=eQVB-7QakTA as “night melody song”.",
    "Edited test.py with a simple Python script that converts dollars.",
    "Updated the selected code to use a dictionary for user ages.",
    "Got it. The link is saved as \"notion\".",
    "Your reminder was set for 9 pm.",
    "ok i have removed the gemini link",
])
def test_done_claims_in_any_form_need_a_tool(answer):
    assert meta.needs_tool(answer)


@pytest.mark.parametrize("answer", [
    "A decorator is a function that wraps another function to modify its behaviour.",
    "Please paste the paragraph you’d like summarized.",
    "I need the URL of the page you want to store as “notion.”",
    "Open a terminal, go to the folder and run python3 test.py.",
    "A list is created with square brackets.",
    "The file is saved when you press Ctrl+S.",
    "Python was created by Guido van Rossum.",
    "The object is created using the class.",
    "Here is the completed search method.",
    "Take a short break and rest; you deserve it.",
    "Narayan Chaulagain (Dad): 9848334818",
    "100 ksm = 100 000 m.",
])
def test_explanations_and_questions_are_not_claims(answer):
    assert not meta.needs_tool(answer)


@pytest.fixture
def respond(monkeypatch):
    from jarvis.core import llm

    def install(fn):
        def chat(messages, stream=False, **kw):
            msg = fn(messages, kw)
            return llm.Reply(msg.content, "", [], message=msg)
        monkeypatch.setattr(llm, "chat", chat)
    return install


@pytest.mark.parametrize("text,claim", [
    ("clear link store", "All links have been cleared from your store."),
    ("Copy the path.", "The folder path is now in your clipboard."),
    ("bro delete gemini link frm link store", "Done, gemini link removed from your store."),
])
def test_fake_claim_is_retried_with_the_same_tools(respond, monkeypatch, text, claim):
    seen = []

    def fn(messages, kw):
        seen.append([getattr(t, "name", None) or t.get("function", {}).get("name") for t in kw.get("tools") or []])
        return AIMessage(content="Okay." if isinstance(messages[-1], SystemMessage) else claim)
    respond(fn)
    monkeypatch.setattr(router, "route", lambda t, log_it=True: router.Route(["links"], "semantic"))
    agent.Agent().run(text)
    assert len(seen) == 2 and seen[0] and seen[1][:len(seen[0])] == seen[0] and "request_tools" in seen[1]
