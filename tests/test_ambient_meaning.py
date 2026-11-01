"""Talk mode: speech long after KURAMA spoke counts as for KURAMA when it greets it or clearly MEANS an action
(stt.log 08:08: 'Hello buddy', 'Hello, how are you?' were the owner, dropped as room talk)."""
import pytest

from jarvis.api import turns
from jarvis.core import semantic, templates

GREET = {"en": "Hello! What can I do for you?"}


@pytest.fixture
def meaning(monkeypatch):
    st = {"greet": set(), "ack": set(), "top": 0.6, "chat": 0.6}
    monkeypatch.setattr(semantic, "ensure_ready", lambda *a, **k: True)
    monkeypatch.setattr(templates, "small_talk", lambda t: GREET if t.strip(" .?!").lower() in st["greet"]
                        else {"en": "👍"} if t.strip(" .!").lower() in st["ack"] else None)
    monkeypatch.setattr(semantic, "scores", lambda t: [("power", st["top"]), (semantic.CHAT, st["chat"])])
    return st


@pytest.mark.parametrize("text", ["Hello buddy", "Hello, how are you?", "Hello Namaste, My name is Darshano"])
def test_greeting_kurama_is_for_kurama(meaning, text):
    meaning["greet"] |= {"hello buddy", "hello, how are you", "hello how are you", "hello namaste"}
    assert turns.addressed(text)


@pytest.mark.parametrize("text", ["Hello, shut down the laptop.", "bro shutdown laptop now", "laptop band karo"])
def test_a_clear_action_is_for_kurama(meaning, text):
    meaning.update(top=0.88, chat=0.64)
    assert turns._means_it(text)


@pytest.mark.parametrize("text", ["okay", "The middle of the middle is number 18.", "yeah he told me he will come tomorrow"])
def test_acks_and_room_talk_stay_ignored(meaning, text):
    meaning["ack"].add("okay")
    meaning.update(top=0.69, chat=0.58)
    assert not turns._means_it(text)
