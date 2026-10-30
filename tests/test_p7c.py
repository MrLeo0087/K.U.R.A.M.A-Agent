"""P7c: file tools, Telegram sharing, dependent plans, "search" opens results, tone, toolsmith via the agent."""
import re
import threading
import time
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from jarvis.core import agent, config, fastpath, llm, notify, planner, registry, safety, toolsmith
from jarvis.tools.general import _files


class Responder(BaseChatModel):
    fn: Any = None
    model_id: str = "fake"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, tool_choice=None, **kw):
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], tool_choice=tool_choice)

    def _generate(self, messages, stop=None, run_manager=None, **kw: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.fn(messages, kw))])


@pytest.fixture
def respond(monkeypatch):
    def install(fn):
        monkeypatch.setattr(llm, "model_for", lambda m: Responder(model_id=m, fn=fn))
    return install


def names(kw):
    return [t["function"]["name"] for t in kw.get("tools") or []]


def human(messages):
    return next(m.content for m in reversed(messages) if isinstance(m, HumanMessage))


def tc(name, args, i="c1"):
    return AIMessage(content="", tool_calls=[{"id": i, "name": name, "args": args}])


@pytest.fixture
def roots(tmp_path, monkeypatch):
    safe = tmp_path / "projects"
    safe.mkdir()
    monkeypatch.setattr(config, "FILE_SAFE_ROOTS", (safe,))
    monkeypatch.setattr(config, "SHARE_ROOTS", (tmp_path,))
    return safe


@pytest.fixture
def tg(monkeypatch):
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(notify, "telegram_call",
                        lambda method, payload=None, timeout=None, files=None: sent.append(
                            (method, payload, {k: v[0] for k, v in (files or {}).items()}, time.monotonic())) or {})
    return sent


def ex(name, args, answers=(True,), ctx=None):
    asked, it = [], iter(answers)
    res = safety.execute(name, args, confirm=lambda p: asked.append(p) or next(it, False), ctx=ctx)
    return res, asked


# --- file tools ---
def test_make_folder_safe_root_and_outside(roots, tmp_path):
    res, asked = ex("make_folder", {"path": str(roots / "demo")})
    assert res.ok and (roots / "demo").is_dir() and asked == []
    res, asked = ex("make_folder", {"path": str(tmp_path / "out")}, answers=(False,))
    assert res.ok and (tmp_path / "out").is_dir() and asked == []  # creating never asks (owner: Downloads asked)
    res, _ = ex("make_folder", {"path": "/etc/jarvis"})
    assert not res.ok and "refusing" in res.output


def test_write_file_new_overwrite_and_parents(roots):
    f = roots / "demo" / "main.py"
    res, asked = ex("write_file", {"path": str(f), "content": "print('hello')\n"})
    assert res.ok and f.read_text() == "print('hello')\n" and asked == []
    res, asked = ex("write_file", {"path": str(f), "content": "x"}, answers=(False,))  # one yes/no box, no loop
    assert "declined" in res.output and len(asked) == 1 and f.read_text().startswith("print")
    res, asked = ex("write_file", {"path": str(f), "content": "x", "overwrite": True}, answers=(False,))
    assert "declined" in res.output and len(asked) == 1
    res, asked = ex("write_file", {"path": str(f), "content": "x", "overwrite": True}, answers=(True,))
    assert res.ok and f.read_text() == "x"


def test_move_copy_trash_confirm(roots, monkeypatch):
    a = roots / "a.txt"
    a.write_text("A")
    res, asked = ex("copy_path", {"source": str(a), "destination": str(roots / "b.txt")})
    assert res.ok and (roots / "b.txt").read_text() == "A" and len(asked) == 1
    res, _ = ex("move_path", {"source": str(roots / "b.txt"), "destination": str(roots / "sub" / "c.txt")})
    assert res.ok and (roots / "sub" / "c.txt").exists() and not (roots / "b.txt").exists()
    res, _ = ex("move_path", {"source": str(a), "destination": str(roots / "sub" / "c.txt")})
    assert "already exists" in res.output
    trashed = []
    monkeypatch.setattr(_files, "trash", trashed.append)
    res, asked = ex("delete_to_trash", {"path": str(a)}, answers=(False,))
    assert not res.ok and trashed == []
    res, _ = ex("delete_to_trash", {"path": str(a)})
    assert res.ok and trashed == [a]
    assert registry.safety_of(registry.get("delete_to_trash")) == "confirm"
    assert len(registry.schemas_for(["files"])) <= 6


# --- telegram ---
def test_send_file_path_checks_and_multipart(roots, tmp_path, tg, monkeypatch):
    doc = tmp_path / "report.pdf"
    doc.write_bytes(b"%PDF-1.4 x")
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG x")
    assert "only send files" in ex("send_file_telegram", {"path": "/etc/hostname"})[0].output
    assert "doesn't exist" in ex("send_file_telegram", {"path": str(tmp_path / "nope.pdf")})[0].output
    res, asked = ex("send_file_telegram", {"path": str(doc)}, answers=(False,))
    assert asked == []  # safe now: it only sends to the owner's own chat, no yes/no
    res, _ = ex("send_file_telegram", {"path": str(doc), "caption": "here"})
    assert res.ok and tg[-1][:3] == ("sendDocument", {"chat_id": "42", "caption": "here"}, {"document": "report.pdf"})
    ex("send_file_telegram", {"path": str(img)})
    assert tg[-1][0] == "sendPhoto" and tg[-1][2] == {"photo": "pic.png"}
    monkeypatch.setattr(config, "TELEGRAM_FILE_MAX_MB", 0)  # too big for Telegram -> upload + link (not an error)
    monkeypatch.setattr("jarvis.core.cloudshare.share", lambda p: "https://gofile.io/d/XYZ")
    out = ex("send_file_telegram", {"path": str(doc)})[0].output
    assert "gofile.io/d/XYZ" in out and "Download link" in out


def test_telegram_call_sends_multipart(monkeypatch):
    seen = {}

    class Client:
        def post(self, url, **kw):
            seen.update(kw)
            return type("R", (), {"json": lambda self: {"ok": True, "result": {}}, "status_code": 200})()
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(notify, "_http", lambda: Client())
    notify.telegram_call("sendDocument", {"chat_id": 42}, files={"document": ("a.txt", b"hi")})
    assert seen["data"] == {"chat_id": "42"} and "document" in seen["files"] and "json" not in seen


def test_send_message_telegram(tg):
    res, asked = ex("send_message_telegram", {"text": "A poem"})
    assert res.ok and tg[0][:2] == ("sendMessage", {"chat_id": "42", "text": "A poem",
                                                    "disable_web_page_preview": True})
    assert registry.safety_of(registry.get("send_message_telegram")) == "safe" and asked == []  # own chat only


def test_telegram_routing():
    from jarvis.core import router
    assert "telegram" in router.rule_groups("send /home/leo/x.pdf to telegram")
    assert "telegram" in router.rule_groups("यो फोनमा पठाउ")


# --- planner dependencies ---
def test_dependency_rules_and_chains():
    tasks = planner.add_dependencies([{"text": "create a folder demo", "kind": "quick"},
                                      {"text": "make main.py in it", "kind": "quick"},
                                      {"text": "what's the weather in Pokhara", "kind": "quick"}])
    assert tasks[1]["depends_on"] == [0] and "depends_on" not in tasks[2]
    assert planner.chains(tasks) == [[0, 1], [2]]
    assert planner.chains([{"text": "a"}, {"text": "b"}]) == [[0], [1]]


def test_result_tail_is_not_a_task():
    text = "Can you search for recent Barcelona football match in Google and give me the result."
    assert not planner.is_multi(text)
    buggy = [{"text": "search Google for recent Barcelona football match", "kind": "quick"},
             {"text": "give me the result", "kind": "quick"}]
    merged = planner.merge_tails(buggy)
    assert merged == [{"text": "search Google for recent Barcelona football match and give me the result",
                       "kind": "quick"}]
    assert planner.merge_tails([{"text": "write a poem"}, {"text": "and tell me"},
                                {"text": "send it to telegram", "depends_on": [1]}])[1]["depends_on"] == [0]


def test_barcelona_answer_is_about_barcelona_only(respond, monkeypatch):
    """Real repro: the trailing 'give me the result' used to run alone and answer from the previous turn."""
    ws = registry.get("web_search")
    monkeypatch.setattr(ws, "func", lambda query, **k: f"1. Barcelona 3-1 Sevilla (query: {query})")

    def fn(messages, kw):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="Barcelona beat Sevilla 3-1.")
        if "web_search" in names(kw):
            return tc("web_search", {"query": "recent Barcelona football match"})
        return AIMessage(content="Carimnity is a band.")  # what the old lone 'give me the result' said
    respond(fn)
    bot = agent.Agent()
    bot.history = [HumanMessage(content="search Carimnity"), AIMessage(content="Carimnity is a band.")]
    ans = bot.run("Can you search for recent Barcelona football match in Google and give me the result.")
    assert "Barcelona" in ans and "Carimnity" not in ans
    assert len(bot.last["plan"]["tasks"]) == 1


def test_folder_then_file_runs_in_order(respond, roots, monkeypatch):
    demo = roots / "jarvis_demo"
    monkeypatch.setattr(planner, "decompose", lambda text: [
        {"text": f"create a folder {demo}", "kind": "quick"},
        {"text": "make a file called main.py in it that prints hello", "kind": "quick"}])

    def fn(messages, kw):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(content=last.content + ".")
        h = human(messages)
        if "make_folder" in names(kw) and h.startswith("create a folder"):
            return tc("make_folder", {"path": str(demo)})
        if "write_file" in names(kw) and "main.py" in h:
            m = re.search(r"Created folder (\S+)", h)
            assert m, f"the previous step result was not passed on: {h!r}"
            return tc("write_file", {"path": m.group(1).rstrip(".)") + "/main.py", "content": "print('hello')\n"})
        return AIMessage(content="?")
    respond(fn)
    bot = agent.Agent(confirm=lambda p: True)
    ans = bot.run(f"create a folder {demo} and then make a file called main.py in it that prints hello")
    assert (demo / "main.py").read_text() == "print('hello')\n"
    assert bot.last["chain"] == [0, 1] and "Created folder" in ans and "main.py" in ans


def test_poem_then_send_in_order_and_independent_task_parallel(respond, tg, monkeypatch):
    order = []
    monkeypatch.setattr(planner, "decompose", lambda text: [
        {"text": "write a short poem about Nepal", "kind": "quick"},
        {"text": "send it to Telegram", "kind": "quick"}])

    def fn(messages, kw):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(content="I sent it to your Telegram.")
        h = human(messages)
        if h.startswith("write a short poem"):
            order.append(("poem", time.monotonic()))
            return AIMessage(content="Mountains rise in morning light, Nepal shines so bright.")
        if "send_message_telegram" in names(kw):
            poem = h.split("use it: ", 1)[1].rstrip(")")
            return tc("send_message_telegram", {"text": poem})
        return AIMessage(content="?")
    respond(fn)
    bot = agent.Agent(confirm=lambda p: True)
    ans = bot.run("write a short poem about Nepal and send it to telegram")
    assert tg and tg[0][1]["text"].startswith("Mountains rise") and order[0][1] < tg[0][3]
    assert ans.startswith("Mountains rise") and ans.endswith("I sent it to your Telegram.")


def test_independent_and_chain_mix_runs_concurrently(respond, monkeypatch):
    for name in ("slow_a", "slow_b"):
        def f(name=name) -> str:
            time.sleep(0.4)
            return f"{name} ok"
        f.__name__ = name
        registry.tool(group="testslow2", description=f"slow {name}")(f)
    from jarvis.core import router
    monkeypatch.setattr(router, "route", lambda text, log_it=True: router.Route(["testslow2"], "rules"))
    monkeypatch.setattr(planner, "plan", lambda text: planner.Plan(
        [{"text": "do a", "kind": "quick"}, {"text": "do b", "kind": "quick"},
         {"text": "then do a again with it", "kind": "quick", "depends_on": [1]}], "llm"))
    threads = set()

    def fn(messages, kw):
        threads.add(threading.get_ident())
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=f"Done {messages[-1].name}.")
        which = "slow_a" if " a" in human(messages).split("\n")[0] else "slow_b"
        return tc(which, {}, which)
    respond(fn)
    t0 = time.monotonic()
    ans = agent.Agent().run("x")
    dt = time.monotonic() - t0
    assert ans == "Done slow_a. Done slow_b. Done slow_a."
    assert dt < 1.1, f"independent task did not run alongside the chain ({dt:.2f}s)"  # 2 sequential + 1 parallel
    for name in ("slow_a", "slow_b"):
        registry.REGISTRY.tools.pop(name, None)


# --- "search" opens the results page (fast path, 0 tokens) ---
@pytest.mark.parametrize("text,url", [
    ("search Barcelona match", "https://www.google.com/search?q=Barcelona+match"),
    ("search Barcelona match on Google", "https://www.google.com/search?q=Barcelona+match"),
    ("google nepal earthquake", "https://www.google.com/search?q=nepal+earthquake"),
    ("search on YouTube for lofi music", "https://www.youtube.com/results?search_query=lofi+music"),
    ("search wikipedia for Mount Everest", "https://en.wikipedia.org/w/index.php?search=Mount+Everest"),
    ("google ma nepal news search gara", "https://www.google.com/search?q=nepal+news"),
    ("nepal news google pe search karo", "https://www.google.com/search?q=nepal+news"),
    ("youtube ma lofi music search gara", "https://www.youtube.com/results?search_query=lofi+music"),
])
def test_search_opens_results(text, url, monkeypatch):
    from jarvis.tools.general import open_url
    opened = []
    monkeypatch.setattr(open_url, "_open", opened.append)
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM")))
    res = fastpath.try_answer(text, lang="en")
    assert res and opened == [url] and res.answer.startswith("Sure, opening ")


@pytest.mark.parametrize("text", [
    "Can you search for recent Barcelona football match in Google and give me the result.",
    "what is the latest news in Nepal", "search for who is the PM of Nepal", "tell me about Mount Everest",
    "search my files for todo", "google pe nepal news search karke batao"])
def test_search_for_an_answer_is_not_fastpath(text):
    assert fastpath.match(text) is None or fastpath.match(text).name != "search"


def test_search_template_nepali():
    i = fastpath.match("google ma nepal news search gara")
    assert fastpath.render(i, True, "opened x", "ne") == "हुन्छ, Google मा nepal news को नतिजा खोल्दैछु।"


# --- toolsmith reachable through request_tools (wallpaper acceptance case) ---
def test_unknown_task_routes_to_toolsmith_with_consent(respond, monkeypatch):
    from jarvis.core import router
    assert router.rule_groups("change mouse speed") == []  # no tool for this yet
    monkeypatch.setattr(toolsmith, "DRY_RUN_CMDS", True)
    code = ("from jarvis_helpers import run_cmd\ndef run(arg):\n    return run_cmd(['gsettings', 'set', "
            "'org.gnome.desktop.background', 'picture-uri', 'file://' + arg])\n")
    gen = []
    monkeypatch.setattr(toolsmith, "generate", lambda task, feedback="": gen.append(task) or toolsmith.ToolSpec(
        possible=True, reason="", reusable=True, name="mouse_speed", summary="Changes the mouse speed.",
        needs=["system"], arg_hint="image path", arg="/usr/share/backgrounds/a.jpg", code=code))

    def fn(messages, kw):
        last = messages[-1]
        if isinstance(last, ToolMessage) and last.name == "make_tool":
            return AIMessage(content="Done, mouse speed changed.")
        if "make_tool" in names(kw):
            return tc("make_tool", {"task": "change mouse speed"}, "c2")
        if "request_tools" in names(kw):
            return tc("request_tools", {"groups": ["toolsmith"], "reason": "no mouse tool"})
        return AIMessage(content="?")
    respond(fn)
    asked = []
    bot = agent.Agent(confirm=lambda p: asked.append(p) or True)
    assert bot.run("change mouse speed") == "Done, mouse speed changed."
    assert asked[0] == toolsmith.CONSENT["en"] and "gsettings set" in asked[1] and len(gen) == 1
    assert toolsmith.load_meta("mouse_speed")["sensitive"]
    toolsmith.delete("mouse_speed")


def test_refusal_with_tools_bound_retries_with_meta(respond, monkeypatch):
    seen = []

    def fn(messages, kw):
        seen.append(names(kw))
        if isinstance(messages[-1], SystemMessage):
            return AIMessage(content="Okay.")
        return AIMessage(content="I can't do that.")
    respond(fn)
    from jarvis.core import router
    monkeypatch.setattr(router, "route", lambda text, log_it=True: router.Route(["display"], "rules"))
    agent.Agent().run("set dark mode")
    assert len(seen) == 2 and seen[1] == ["request_tools", "make_tool"] and "toolsmith" in meta_hint()


def meta_hint():
    from jarvis.core import meta
    return meta.HINT


# --- tone ---
def test_tone_prompt_is_warm_and_short():
    text = agent.SYSTEM_PROMPT + agent.SCREEN_SUFFIX + agent.VOICE_SUFFIX.format(lang="Nepali (Devanagari script)")
    assert len(text) / 4 < 250
    assert "warm" in agent.SYSTEM_PROMPT and "jargon" in agent.SYSTEM_PROMPT


def test_dropped_leading_slash_is_restored_from_the_request(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FILE_SAFE_ROOTS", (tmp_path,))
    rel = str(tmp_path / "demo").lstrip("/")
    res, asked = ex("make_folder", {"path": rel}, ctx={"user_text": "make the folder",
                                                       "request": f"create a folder {tmp_path}/demo, then a file"})
    assert res.ok and (tmp_path / "demo").is_dir() and asked == []
    res, _ = ex("write_file", {"path": rel + "/main.py", "content": "x"},
                ctx={"user_text": "make main.py in it", "request": f"create a folder {tmp_path}/demo, then main.py"})
    assert res.ok and (tmp_path / "demo" / "main.py").exists()


def test_curly_apostrophe_refusal_detected():
    from jarvis.core import meta
    assert meta.looks_like_refusal("I’m sorry, I don’t have the ability to change your wallpaper.")


def test_new_names_are_literal_and_rename_stays_in_place(roots, tmp_path, monkeypatch):
    """'Create new folder here' made ~/new_folder resolve to an existing 'new' folder elsewhere; a rename's bare new
    name must stay in the same folder; renaming never asks, moving does."""
    (roots / "new").mkdir()
    res, asked = ex("make_folder", {"path": str(roots / "new_folder")})
    assert res.ok and (roots / "new_folder").is_dir() and asked == []
    (roots / "test").mkdir()
    res, asked = ex("move_path", {"source": str(roots / "test"), "destination": "test2", "rename": True})
    assert res.ok and (roots / "test2").is_dir() and not (roots / "test").exists() and asked == []
    (roots / "report.pdf").write_text("x")
    res, _ = ex("move_path", {"source": str(roots / "report.pdf"), "destination": "final", "rename": True})
    assert (roots / "final.pdf").exists()  # the extension is kept
    (roots / "dest").mkdir()
    res, asked = ex("move_path", {"source": str(roots / "final.pdf"), "destination": str(roots / "dest")}, answers=(False,))
    assert "declined" in res.output and len(asked) == 1 and (roots / "final.pdf").exists()


def test_open_in_vscode_and_pasted_path_is_this(roots, monkeypatch):
    from jarvis.core import safety
    from jarvis.tools.general import _sys, open_path
    ran = []
    monkeypatch.setattr(_sys, "run", lambda argv, **k: ran.append(argv) or "")
    assert open_path.open_path(str(roots), "vscode").startswith("Opened") and ran[-1] == ["code", str(roots)]
    tok = safety._CTX.set({"user_text": f"{roots}\nopen this folder in vs code"})
    try:
        assert "Opened" in open_path.open_path("this folder", "vscode") and ran[-1] == ["code", str(roots)]
    finally:
        safety._CTX.reset(tok)
