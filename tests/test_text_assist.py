import pytest

from jarvis.core import assist, fastpath, rewrite


@pytest.fixture
def desk(monkeypatch):
    st = {"pasted": None, "sel": "teh cat sat"}
    monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab(st["sel"], 7, False, False, "Doc"))
    monkeypatch.setattr(rewrite, "grab_cursor", lambda: rewrite.Grab("", 7, False, False, "main.py - KURAMA - VS Code"))
    monkeypatch.setattr(rewrite, "put", lambda g, new: st.__setitem__("pasted", new))
    monkeypatch.setattr(rewrite, "_xclip", lambda a, text=None: "")
    calls = []

    def llm(system, user, smart, max_tokens, purpose):
        calls.append((purpose, smart))
        return {"assist_code_fix": "    def add(a, b):\n    return a + b"}.get(purpose, f"[{purpose}]")
    monkeypatch.setattr(assist, "_llm", llm)
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: None)
    return st, calls


def test_read_actions_leave_the_selection(desk):
    st, calls = desk
    st["sel"] = "The committee deferred its decision indefinitely."
    assert assist.run("explain", "what does this mean") == "[assist_explain]" and st["pasted"] is None
    st["sel"] = "ubiquitous"
    assert assist.run("explain", "what does this mean") == "[assist_meaning]"  # one word -> dictionary meaning
    assert assist.run("translate", "translate this into nepali", "ne").startswith("[assist_translate]")
    assert st["pasted"] is None
    assert assist.run("meaning", text="serendipity") == "[assist_meaning]"


def test_write_actions(desk, tmp_path, monkeypatch):
    st, calls = desk
    assert "Wrote" in assist.run("write", "write a calculator function here")
    st["sel"] = "i is happy"
    assist.run("translate", "translate this to english and replace it", "en", replace=True)
    assert st["pasted"] == "[assist_translate]"


def test_code_improve_waits_for_yes_then_replaces_only_the_selection(desk, tmp_path, monkeypatch):
    st, calls = desk
    monkeypatch.setattr(assist.config, "OUTPUTS_DIR", tmp_path / "out")
    monkeypatch.setattr(assist.config, "DATA_DIR", str(tmp_path / "data"))
    f = tmp_path / "calc.py"
    old = "    def add(a,b):\n        return a+b"
    f.write_text("class C:\n" + old + "\n\nprint(1)\n")
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f)
    st["sel"] = old
    msg = assist.run("improve", "make this code better and replace it")
    assert msg == "Improving the selected code in calc.py…" and st["pasted"] is None  # nothing changes yet
    import time
    for _ in range(50):
        if assist.pending_code_active():
            break
        time.sleep(0.05)
    assert assist.pending_code_active()
    assert fastpath.match("yes replace it").args == {"action": "apply_code"}
    out = assist.apply_pending_code()
    assert out == "Replaced in calc.py."
    text = f.read_text()
    assert text.startswith("class C:\n    def add(a, b):") and text.endswith("print(1)\n")  # only the selection
    assert not assist.pending_code_active()


def test_routing():
    def a(t):
        i = fastpath.match(t)
        return i and (i.tool, i.args.get("action"))
    assert a("what does this mean") == ("text_assist", "explain")
    assert a("what is the meaning of this word in nepali") == ("text_assist", "meaning")
    assert a("translate this paragraph into hindi") == ("text_assist", "translate")
    assert a("what does this function do") == ("text_assist", "code")
    assert a("optimize this code") == ("text_assist", "improve")
    assert a("write a calculator class in python here") == ("text_assist", "write")
    assert a("explain main.py") == ("text_assist", "explain_file")
    assert fastpath.match("explain quantum physics") is None and fastpath.match("what is the meaning of life") is None
    assert a("explain this error") == ("fix_error", "explain")


def test_more_free_phrasings():
    def a(t):
        i = fastpath.match(t)
        return i and (i.tool, i.args.get("action"), i.args.get("text", ""))
    assert a("Can you tell me the meaning of this sentence or paragraph?") == ("text_assist", "explain", "")
    assert a("What is the meaning of this whole paragraph?") == ("text_assist", "explain", "")
    assert a("Translate this whole paragraph in Nepali.") == ("text_assist", "translate", "")  # the selection
    assert a("Can you modify this much line of the code and make it more better and detailed?")[1] == "improve"


def test_long_answers_go_to_the_workspace():
    long = "This function adds numbers. It loops over the list. " + "Then it returns.\n    total = a + b;\n" * 40
    assert fastpath._needs_workspace(long)
    head = fastpath._speakable_head(long, "en")
    assert head.startswith("This function adds numbers.") and "workspace" in head and "total =" not in head
    assert assist._short("● test.py - KURAMA - Claude-1 - Visual Studio Code") == "test.py"


def test_code_instruction_is_cleaned_and_kept_short(desk, monkeypatch):
    st, calls = desk
    assert assist.clean_instruction("Zarpis actually make this selected part of the code more better and detailed "
                                    "and replace it.") == "make this selected part of the code more better and detailed"
    assert assist.clean_instruction("replace it") == "fix and improve this code"
    replies = ["x = 1\n" * 200, "def add(a, b):\n    return a + b"]
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: replies.pop(0))
    assert assist.improve_code("def add(a,b):\n    return a+b", "make it better") == "def add(a, b):\n    return a + b"


def test_selected_now_reruns_the_request(desk, monkeypatch):
    st, calls = desk
    monkeypatch.setattr(rewrite, "grab", lambda: "I couldn't see any highlighted text in 'Doc'.")
    assert "highlighted" in assist.run("translate", "translate this into nepali", "ne")
    assert assist.retry_active()
    for s in ("done", "I selected it", "I select the text.", "it's selected now"):
        assert fastpath.match(s).args == {"action": "retry"}, s
    monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab("hello", 7, False, False, "Doc"))
    assert fastpath.match("done").args == {"action": "retry"}
    assert assist.run("retry").startswith("[assist_translate]") and not assist.retry_active()
    assert fastpath.match("I selected the text") is None or fastpath.match("I selected the text").args != {"action": "retry"}


CALC = """def calculator():
    \"\"\"Simple command-line calculator.\"\"\"
    while True:
        expr = input("> ")
        try:
            result = eval(expr, {"__builtins__": None}, {})
            print(f"Result: {result}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    calculator()
"""


def _wait_pending():
    import time
    for _ in range(60):
        if assist.pending_code_active():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("on_disk", [True, False])
def test_selection_starting_after_the_spaces_keeps_the_indentation(desk, tmp_path, monkeypatch, on_disk):
    """Real bug: the selection began at 'try:' (VS Code selection after the indentation) and the new code came
    back at the wrong levels."""
    st, calls = desk
    monkeypatch.setattr(assist.config, "OUTPUTS_DIR", tmp_path / "out")
    monkeypatch.setattr(assist.config, "DATA_DIR", str(tmp_path / "data"))
    f = tmp_path / "test.py"
    f.write_text(CALC)
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f if on_disk else None)
    sel = CALC[CALC.index("try:"): CALC.index('{e}")') + len('{e}")')]
    st["sel"] = sel
    seen = {}

    def llm(system, user, smart, max_tokens, purpose):
        seen["user"] = user
        return ("```python\ntry:\n    # no built-ins: only plain arithmetic\n    result = eval(expr, {\"__builtins__\": {}}, {})\n"
                "    print(f\"Result: {result}\")\nexcept Exception as err:\n    print(f\"Error: {err}\")\n```")
    monkeypatch.setattr(assist, "_llm", llm)
    assist.run("improve", "replace this code with better and detailed code")
    assert _wait_pending()
    assert "Selected code (5 lines):\ntry:\n    result = eval" in seen["user"]  # the model saw it at level 0
    if on_disk:
        assert fastpath.match("Yes, you can replace.").args == {"action": "apply_code"}
        assert assist.apply_pending_code() == "Replaced in test.py."
        text = f.read_text()
        assert ("        try:\n            # no built-ins: only plain arithmetic\n            result = eval(expr"
                in text and "        except Exception as err:\n            print(f\"Error: {err}\")\n\n\nif" in text)
        compile(text, "test.py", "exec")
    else:  # pasted over the selection: the line's own spaces are already there, so the first line has none
        monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab(sel, 7, False, False, "Doc"))
        assert assist.apply_pending_code() == "Replaced. Ctrl+Z undoes it."
        assert st["pasted"].startswith("try:\n            # no built-ins") and "\n        except Exception" in st["pasted"]


def test_answers_while_a_code_change_waits(monkeypatch):
    import time
    monkeypatch.setattr(assist.config, "FASTPATH", True)
    assist._pending.update(old="x", new="y", expires=time.time() + 60)
    try:
        for s in ("yes", "Yes, you can replace.", "Replace the code with new code.", "ok replace it", "go ahead",
                  "yeah do it", "replace", "please replace", "haan"):
            assert fastpath.match(s).args == {"action": "apply_code"}, s
        for s in ("no", "No, keep the old one", "no don't"):
            assert fastpath.match(s).args == {"action": "cancel_code"}, s
        for s in ("Replace this selected code with the more good version.", "yes but make it shorter"):
            assert fastpath.match(s).args.get("action") == "improve", s
    finally:
        assist._pending.clear()


def test_misheard_code_requests():
    i = fastpath.match("Can you replace this code from the better end detail coat?")
    assert i and i.args["action"] == "improve" and "better and detailed code" in i.args["request"]
