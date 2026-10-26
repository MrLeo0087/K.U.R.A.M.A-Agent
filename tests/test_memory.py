"""P7 Memory/RAG: chunking, incremental index, hybrid search, idle unload, ask context cap + cache,
session recall, profile capture/injection/decay, token usage, daily digest + worker, fast path,
routing. All mocked: fake deterministic embeddings, tmp dirs, no network."""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timedelta

import numpy as np
import pytest

from jarvis.core import (agent, config, digest, episodes, fastpath, llm, memory, profile, registry, router,
                         store, usage)


# --------------------------------------------------------------------------- fixtures
class FakeModel:
    """Deterministic bag-of-words hashing 'embedding' (64-d)."""
    dim = 64

    def __init__(self):
        self.calls = 0
        self.texts = 0

    def embed(self, texts):
        self.calls += 1
        for t in texts:
            self.texts += 1
            v = np.zeros(self.dim, dtype=np.float32)
            for w in re.findall(r"[a-z]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
            yield v


@pytest.fixture
def fake_model():
    return FakeModel()


@pytest.fixture
def idx(tmp_path, fake_model, monkeypatch):
    monkeypatch.setattr(config, "EMBED_MODEL", "fake-model")
    index = memory.Index(tmp_path / "mem.db", embedder=memory.Embedder(factory=lambda: fake_model, idle_s=0))
    memory.set_index(index)
    yield index
    memory.set_index(None)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def make_repo(root):
    write(root / "bot" / "telegram_bot.py",
          '"""Telegram bot."""\n\n\ndef skip_stale(updates, started):\n'
          '    """Ignore telegram messages older than the start time (stale messages)."""\n'
          '    return [u for u in updates if u["date"] >= started]\n')
    write(root / "core" / "fastpath.py",
          "def try_answer(text):\n    \"\"\"Zero-token fast path: regex intents answer without the LLM.\"\"\"\n"
          "    return None\n")
    write(root / "README.md", "# Demo\n\nWeather tool uses Open-Meteo. Volume control uses pactl.\n")
    write(root / "venv" / "lib" / "junk.py", "def telegram(): pass\n")  # excluded dir
    write(root / "data" / "x.md", "telegram data\n")  # excluded dir
    write(root / ".git" / "config.md", "telegram\n")  # hidden dir
    (root / "big.txt").write_text("x" * (config.MEMORY_MAX_FILE_BYTES + 10))  # too big
    (root / "image.png").write_bytes(b"\x89PNG\0\0")  # wrong type


# --------------------------------------------------------------------------- chunking
def test_chunk_lines_overlap_and_line_ranges():
    lines = [f"line {i:03d} " + "word " * 10 for i in range(60)]
    chunks = memory.chunk_lines(lines, size=300, overlap=100)
    assert len(chunks) > 3
    assert all(len(c.text) <= 300 for c in chunks)
    assert chunks[0].start == 1 and chunks[-1].end == 60
    for a, b in zip(chunks, chunks[1:]):
        assert b.start <= a.end  # overlapping lines
        assert b.start > a.start  # progress


def test_chunk_lines_hard_splits_a_huge_line():
    chunks = memory.chunk_lines(["y" * 2000], size=800, overlap=100)
    assert len(chunks) >= 3 and all(c.start == c.end == 1 for c in chunks)


def test_chunk_python_prefers_def_and_class_boundaries():
    funcs = "\n\n".join(f"def f{i}(x):\n" + "".join(f"    y{j} = x + {j}  # pad pad pad pad\n" for j in range(12))
                        + "    return x\n" for i in range(4))
    src = "import os\n\n\n" + funcs + "\n\n@decorator\nclass Big:\n" + "".join(
        f"    def m{i}(self):\n" + "".join(f"        z = {j}  # padding padding padding\n" for j in range(10))
        + "        return 1\n\n" for i in range(5))
    chunks = memory.chunk_python(src, size=800)
    lines = src.splitlines()
    starts = {lines[c.start - 1].strip().split("(")[0] for c in chunks}
    assert any(s.startswith("def f") for s in starts)
    assert any(s.startswith("def m") or s == "@decorator" for s in starts)  # class split at methods
    for c in chunks:
        first = lines[c.start - 1].strip()
        assert first.startswith(("def ", "import", "@", "class ", "#")) or first == "", first
    assert chunks[-1].end == len(lines)


def test_chunk_python_syntax_error_falls_back():
    chunks = memory.chunk_python("def broken(:\n    pass\n" * 3)
    assert chunks and chunks[0].start == 1


def test_notebook_text_keeps_cells_drops_outputs():
    import json
    nb = {"cells": [{"cell_type": "markdown", "source": ["# Title\n", "intro"]},
                    {"cell_type": "code", "source": "print(1)", "outputs": [{"text": "SECRET OUTPUT"}]}]}
    text = memory.notebook_text(json.dumps(nb))
    assert "# Title" in text and "print(1)" in text and "SECRET OUTPUT" not in text


# --------------------------------------------------------------------------- indexing
def test_index_excludes_and_incremental_reindex(tmp_path, idx, fake_model):
    root = tmp_path / "repo"
    make_repo(root)
    st = idx.index_path(root)
    assert st["files"] == 3 and st["indexed"] == 3 and st["embedded"] == st["chunks_total"] > 0
    paths = {r["path"] for r in idx._q("SELECT path FROM chunks")}
    assert not any("venv" in p or "data/" in p or ".git" in p or "big" in p for p in paths)
    assert all(p.startswith("repo/") for p in paths)

    texts_before = fake_model.texts
    st2 = idx.index_path(root)  # nothing changed
    assert st2["indexed"] == 0 and st2["unchanged"] == 3 and st2["embedded"] == 0
    assert fake_model.texts == texts_before

    readme = root / "README.md"
    os.utime(readme, (time.time() + 5, time.time() + 5))  # mtime only: same hash -> unchanged
    assert idx.index_path(root)["indexed"] == 0

    write(readme, "# Demo\n\nNow about dragons and castles.\n")
    st3 = idx.index_path(root)
    assert st3["indexed"] == 1 and st3["embedded"] >= 1
    assert idx.search("dragons castles", k=1)[0].path == "repo/README.md"

    (root / "core" / "fastpath.py").unlink()
    st4 = idx.index_path(root)
    assert st4["deleted"] == 1
    assert not idx._q("SELECT 1 FROM chunks WHERE path LIKE '%fastpath%'")
    assert not idx._q("SELECT 1 FROM chunks_fts WHERE chunks_fts MATCH 'regex'")
    n_vec = idx._q("SELECT COUNT(*) FROM vectors")[0][0]
    assert n_vec == idx.count_chunks()


def test_model_change_reembeds(tmp_path, idx, monkeypatch, fake_model):
    make_repo(tmp_path / "r")
    idx.index_path(tmp_path / "r")
    monkeypatch.setattr(config, "EMBED_MODEL", "other-model")
    st = idx.index_path(tmp_path / "r")
    assert st["indexed"] == 0 and st["embedded"] == idx.count_chunks()


def test_embedding_failure_keeps_bm25(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("offline")
    index = memory.Index(tmp_path / "m.db", embedder=memory.Embedder(factory=boom, idle_s=0))
    make_repo(tmp_path / "r")
    st = index.index_path(tmp_path / "r")
    assert st["embedded"] == 0 and st["chunks_total"] > 0
    assert index.search("telegram stale", k=1)[0].path.endswith("telegram_bot.py")
    index.close()


# --------------------------------------------------------------------------- search
def test_hybrid_search_ranking_and_rrf(tmp_path, idx):
    make_repo(tmp_path / "repo")
    idx.index_path(tmp_path / "repo")
    hits = idx.search("telegram stale messages", k=3)
    assert hits[0].path == "repo/bot/telegram_bot.py"
    assert set(hits[0].sources) == {"bm25", "vector"}
    assert hits[0].score >= max(h.score for h in hits)
    assert idx.search("open meteo weather", k=1)[0].path == "repo/README.md"
    assert memory.fts_query("how does the fast path work?") == '"fast" OR "path" OR "work"'


def test_search_knowledge_output_is_compact(tmp_path, idx):
    from jarvis.tools.general.search_knowledge import search_knowledge
    for i in range(8):
        write(tmp_path / "n" / f"note{i}.md", ("telegram bot notes " * 30 + "\n") * 4)
    write(tmp_path / "n" / "a.py", "def telegram():\n    return 'x'\n")
    idx.index_path(tmp_path / "n")
    out = search_knowledge("telegram notes", k=5)
    assert len(out) <= config.KNOWLEDGE_MAX_CHARS
    lines = out.splitlines()
    assert len(lines) == 5 and all(re.match(r"n/\S+:\d+-\d+: ", ln) for ln in lines)


def test_search_knowledge_empty_index_starts_job(idx, monkeypatch):
    from jarvis.tools.general import search_knowledge as sk
    started = []
    monkeypatch.setattr(memory, "start_index_job", lambda path=None, lang="en": started.append(path) or
                        type("J", (), {"id": 7, "title": "index x"})())
    out = sk.search_knowledge("anything")
    assert "job #7" in out and started == [None]


# --------------------------------------------------------------------------- idle unload
def test_embedder_lazy_load_and_idle_unload(fake_model):
    emb = memory.Embedder(factory=lambda: fake_model, idle_s=0.15)
    dropped = []
    emb.unload_hooks.append(lambda: dropped.append(1))
    assert not emb.loaded
    vecs = emb.embed(["hello world"])
    assert emb.loaded and emb.loads == 1
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0)
    deadline = time.time() + 3
    while emb.loaded and time.time() < deadline:
        time.sleep(0.05)
    assert not emb.loaded and dropped
    emb.embed(["again"])
    assert emb.loads == 2
    emb.unload()


# --------------------------------------------------------------------------- ask_knowledge
def test_ask_knowledge_context_cap_and_cache(tmp_path, idx, monkeypatch):
    from jarvis.tools.general.ask_knowledge import ask_knowledge
    for i in range(6):
        write(tmp_path / "k" / f"f{i}.md", f"fast path doc {i}\n" + ("the fast path uses regex intents. " * 40))
    idx.index_path(tmp_path / "k")
    sent = []

    def fake_chat(msgs, **kw):
        sent.append((msgs, kw))
        return llm.Reply("It uses regex intents (k/f0.md:1-3).", "fake")
    monkeypatch.setattr(llm, "chat", fake_chat)
    out = ask_knowledge("How does the fast path work?")
    assert "regex" in out and len(sent) == 1
    msgs, kw = sent[0]
    ctx = msgs[1]["content"].split("Context:\n", 1)[1].split("\n\nQuestion:")[0]
    assert len(ctx) <= config.ASK_CONTEXT_CHARS
    assert ctx.count("[k/") <= config.ASK_K
    assert kw["tier"] == "fast"
    # cache: same question (different case/punctuation) costs no LLM call
    assert ask_knowledge("how does the fast path work") == out and len(sent) == 1
    # a reindex that changes files clears the cache
    write(tmp_path / "k" / "f0.md", "changed content about fast path")
    idx.index_path(tmp_path / "k")
    ask_knowledge("how does the fast path work?")
    assert len(sent) == 2


# --------------------------------------------------------------------------- sessions / episodic
def _fake_agent_llm(monkeypatch, text="ok"):
    calls = []

    def fake_chat(msgs, **kw):
        calls.append((msgs, kw))
        return llm.Reply(text, "fake", message=None)
    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


def test_agent_persists_session_messages_and_summary(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "PROFILE_LLM_EXTRACT", False)
    bot = agent.Agent(summarize_async=False, use_planner=False, channel="text")
    bot.run("what time is it")  # fast path: no LLM
    sid = bot.session_id
    assert sid and store.session_get(sid)["turns"] == 1
    msgs = store.session_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    _fake_agent_llm(monkeypatch, "User asked about the time and telegram bots.")
    bot._summarize([])
    assert "telegram" in store.session_get(sid)["summary"]
    assert "telegram" in episodes.recall("today")


def test_session_idle_gap_starts_fresh_session(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "PROFILE_LLM_EXTRACT", False)
    bot = agent.Agent(summarize_async=False, use_planner=False)
    bot.run("what time is it")
    first = bot.session_id
    bot.summary = "old context"
    bot._last_turn -= config.SESSION_IDLE_S + 10
    bot.run("what time is it")
    assert bot.session_id != first and bot.summary == ""


def test_recall_session_last_yesterday_and_search():
    from jarvis.tools.general.recall_session import recall_session
    y = (datetime.now() - timedelta(days=1)).replace(hour=20, minute=0).timestamp()
    old = store.session_start("voice", ts=y)
    store.session_update(old, summary="Discussed the Telegram bot and stale messages.")
    store.session_touch(old)
    store._exec("UPDATE sessions SET end=? WHERE id=?", (y + 60, old))
    store.add_message("user", "how do I fix stale telegram updates", session=old)
    store._exec("UPDATE messages SET ts=? WHERE session=?", (y + 5, old))
    store.session_start("text")  # current session
    assert "Telegram" in recall_session("yesterday")
    assert "Telegram" in recall_session("last")
    hit = recall_session("stale telegram")
    assert "telegram" in hit.lower() and len(hit) <= config.SESSION_RECALL_MAX_CHARS
    assert "couldn't find" in recall_session("zebras")
    assert episodes.parse_day("2026-10-01")[2].startswith("Thu")


# --------------------------------------------------------------------------- profile (tiered memory)
def test_profile_capture_replaces_and_skips_questions_and_secrets():
    assert profile.capture_and_save("My favourite editor is VS Code") == [("favorite_editor", "VS Code")]
    profile.capture_and_save("my editor is Neovim")
    assert store.profile_get("favorite_editor") == "Neovim"  # replaced, not appended
    profile.capture_and_save("I love tea")
    profile.capture_and_save("I hate tea")
    assert store.profile_get("likes_tea") == "hates tea"
    assert profile.capture("what is my name?") == []
    assert profile.capture("my wifi password is hunter2") == []
    assert profile.capture("my code is broken") == []
    assert profile.capture("mero naam Ram ho") == [("name", "Ram")]
    assert profile.capture("ma Nepalgunj ma baschu") == [("home_city", "Nepalgunj")]
    assert dict(profile.capture("my name is Leo and I live in Pokhara")) == {"name": "Leo", "home_city": "Pokhara"}


def test_profile_injection_is_token_gated(monkeypatch):
    profile.capture_and_save("my name is Leo and I live in Nepalgunj")
    profile.capture_and_save("I speak Nepali and Hindi")
    profile.capture_and_save("My favourite editor is VS Code")
    assert profile.context_line("open youtube") == ""  # not personal -> nothing
    assert profile.context_line("tell me a joke") == ""
    line = profile.context_line("what's the weather like near my home?")
    assert line == "User: lives in Nepalgunj."
    assert profile.estimate_tokens(line) <= 60 and len(line) <= config.PROFILE_INJECT_MAX_CHARS + 1
    many = profile.context_line("what do you know about me")
    assert many.count(";") <= config.PROFILE_INJECT_MAX - 1
    day = datetime.now().strftime("%Y-%m-%d")
    assert int(store.kv_get(f"profile_inject_tokens:{day}")) > 0
    # the agent adds it to the system prompt only on personal turns
    bot = agent.Agent()
    bot.last = {}
    assert "User:" not in bot._messages("open youtube", "text", None)[0].content
    sys_msg = bot._messages("what's my name?", "text", None)[0].content
    assert "User: name Leo" in sys_msg and bot.last["profile_tokens"] <= 60


def test_profile_decay_and_prune(monkeypatch):
    monkeypatch.setattr(config, "PROFILE_MAX", 4)
    profile.save("name", "Leo")
    for i in range(6):
        profile.save(f"fact_{i}", f"value {i}")
    facts = {f["key"] for f in store.profile_all()}
    assert len(facts) == 4 and "name" in facts
    now = time.time()
    fresh = {"hits": 5, "last_used": now}
    stale = {"hits": 5, "last_used": now - 90 * 86400}
    unused = {"hits": 0, "last_used": now}
    assert profile.importance(fresh, now) > profile.importance(unused, now) > profile.importance(stale, now)


def test_profile_personalises_weather_home_and_forget(monkeypatch):
    assert profile.home_place() == config.HOME_PLACE
    profile.capture_and_save("I live in Nepalgunj")
    assert profile.home_place() == "Nepalgunj"
    from jarvis.tools.general.forget import forget
    from jarvis.tools.general.recall import recall
    assert "Nepalgunj" in recall(which="profile")
    assert "forgot" in forget(fact="that I live in Nepalgunj")
    assert store.profile_get("home_city") is None


def test_end_session_extracts_once(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    calls = []
    monkeypatch.setattr(profile, "extract_llm", lambda text: calls.append(text) or [])
    bot = agent.Agent(summarize_async=False, use_planner=False)
    bot.run("what time is it")
    bot.end_session()
    assert calls == []  # nothing personal and no summary -> no LLM call
    bot.run("what time is it")
    bot.summary = "User is building KURAMA and prefers short answers."
    bot.end_session()
    bot.end_session()
    assert calls == ["User is building KURAMA and prefers short answers."]


# --------------------------------------------------------------------------- token usage
def test_token_usage_aggregation(monkeypatch):
    f, s = config.LLM_FAST, config.LLM_DEFAULT
    store.log_llm(f, "agent_text", 200, 50, 300, True)
    store.log_llm(f, "summary", 100, 20, 200, True)
    store.log_llm(s, "job3:section", 1000, 500, 900, True)
    store.log_llm(s, "agent_text", 0, 0, 100, False, "429")
    store.log_llm("whisper-large-v3-turbo", "stt", 0, 0, 400, True, audio_s=4.5)
    store.log_routing("what time is it", ["general"], "fastpath", 1)
    store.log_routing("weather", ["weather"], "fastpath", 1)
    s_ = usage.summary("today")
    assert s_["tokens"] == 1870 and s_["calls"] == 3
    assert s_["models"][s]["errors"] == 1
    assert s_["purposes"]["jobs"] == 1500 and s_["purposes"]["agent_text"] == 250
    assert s_["fastpath_hits"] == 2 and s_["tokens_saved_est"] == 2 * config.FASTPATH_TOKENS_SAVED_EST
    assert s_["stt"] == {"calls": 1, "audio_s": 4.5}
    assert s_["budget_pct_today"][s] == round(100 * 1500 / config.DAILY_TOKEN_BUDGET[s], 1)
    from jarvis.tools.general.token_usage import token_usage
    out = token_usage("today")
    first = out.splitlines()[0]
    assert first.startswith("Today you used 1,870 tokens in 3 LLM calls") and "fast path" in first
    assert "$0.00" in out and "config.MODEL_PRICES is empty" in out and "4 s of audio" in out
    monkeypatch.setattr(config, "MODEL_PRICES", {s: {"in": 1.0, "out": 2.0}})
    assert "$0.0020" in usage.report("today")
    assert usage.bounds("week")[2] == "the last 7 days"


# --------------------------------------------------------------------------- digest + worker
def test_digest_template_zero_llm(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("digest must not call the LLM"))
    monkeypatch.setattr(digest, "git_activity", lambda t0, t1, roots=None: [
        {"repo": "KURAMA", "commits": 3, "last": "P7 memory"}])
    sid = store.session_start("voice")
    store.add_message("user", "write an essay about Nepal mountains", session=sid)
    store.session_touch(sid)
    store.session_update(sid, summary="Essay about Nepal mountains; weather in Pokhara.")
    jid = store.job_insert("essay on Nepal", "write")
    store.job_update(jid, status="done", finished=time.time(), output_path="data/outputs/essay.md")
    store.alert_add("RAM high", "92%", "warning")
    store.note_add("wifi password is on the fridge")
    store.log_llm(config.LLM_FAST, "agent_text", 100, 20, 100, True)
    text = digest.build_digest("today", weather_fn=lambda p: "Kathmandu, Nepal: 18°C, feels like 17°C, clear sky.")
    first = text.splitlines()[0]
    assert first.startswith("Today: 1 conversation, 1 job done, 1 alert, 3 commits, 120 tokens")
    for part in ("nepal", "essay on Nepal", "data/outputs/essay.md", "RAM high", "wifi password",
                 "KURAMA 3 commits", "18°C and clear sky in Kathmandu"):
        assert part.lower() in text.lower(), part


def test_digest_llm_polish_is_optional(monkeypatch):
    monkeypatch.setattr(digest, "git_activity", lambda *a, **k: [])
    calls = _fake_agent_llm(monkeypatch, "Polished digest.")
    assert digest.build_digest("today", use_llm=True, with_weather=False) == "Polished digest."
    assert len(calls) == 1 and calls[0][1]["tier"] == "fast"


def test_daily_digest_worker_sends_once_per_day(monkeypatch):
    from jarvis.workers import daily_digest as dd
    sent = []
    monkeypatch.setattr(dd.notify, "notify", lambda title, text, **k: sent.append((title, text)))
    monkeypatch.setattr(dd.digest, "build_digest", lambda date, now=None: f"digest {now:%d}")
    monkeypatch.setattr(config, "DIGEST_TIME", "21:00")
    clock = {"now": datetime(2026, 10, 23, 20, 59)}
    w = dd.DailyDigest(now=lambda: clock["now"])
    w.tick()
    assert sent == []
    clock["now"] = datetime(2026, 10, 23, 21, 1)
    w.tick()
    w.tick()
    assert sent == [("Daily digest", "digest 23")]
    w2 = dd.DailyDigest(now=lambda: clock["now"])  # restart: still once
    w2.tick()
    assert len(sent) == 1
    clock["now"] = datetime(2026, 10, 24, 21, 30)
    w.tick()
    assert len(sent) == 2


def test_daily_digest_tool(monkeypatch):
    monkeypatch.setattr(digest, "git_activity", lambda *a, **k: [])
    monkeypatch.setattr(config, "GREETING_WEATHER", False)
    from jarvis.tools.general.daily_digest import daily_digest
    monkeypatch.setattr(digest, "_weather", lambda fn: "")
    assert daily_digest("yesterday").startswith("Yesterday: 0 conversations")


# --------------------------------------------------------------------------- fast path + routing
@pytest.mark.parametrize("text,intent,args", [
    ("give me my daily digest", "digest", {"date": "today"}),
    ("KURAMA, how many tokens did I use today?", "tokens", {"period": "today"}),
    ("how many tokens did I use this week", "tokens", {"period": "week"}),
    ("what did we talk about yesterday", "session", {"query": "yesterday"}),
    ("what did we discuss", "session", {"query": "last"}),
    ("what do you know about me", "about_me", {"which": "profile"}),
    ("my name is Leo", "name", {"key": "name", "value": "Leo"}),
    ("call me Boss", "name", {"key": "name", "value": "Boss"}),
])
def test_fastpath_p7_matches(text, intent, args):
    m = fastpath.match(text)
    assert m is not None and m.name == intent and m.args == args


@pytest.mark.parametrize("text", ["my name is not important", "call me back later", "what is my name"])
def test_fastpath_p7_non_matches(text):
    m = fastpath.match(text)
    assert m is None or m.name != "name"


def test_fastpath_p7_answers_zero_tokens(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("fast path must not call the LLM"))
    res = fastpath.try_answer("my name is Leo", lang="en")
    assert res.answer.startswith("Nice to meet you, Leo") and store.profile_get("name") == "Leo"
    assert "name Leo" in fastpath.try_answer("what do you know about me", lang="en").answer
    store.log_llm(config.LLM_FAST, "agent_text", 10, 5, 1, True)
    voice = fastpath.try_answer("how many tokens did I use today", lang="en", mode="voice").answer
    text = fastpath.try_answer("how many tokens did I use today", lang="en").answer
    assert "\n" not in voice and "workspace" in text and text.split(";")[0] == voice.split(";")[0]
    assert "earlier conversations" in fastpath.try_answer("what did we talk about last time", lang="en").answer \
        or fastpath.match("what did we talk about last time").name == "session"


def test_routing_knowledge_and_usage_groups():
    registry.discover()
    assert {"index_folder", "search_knowledge", "ask_knowledge"} <= {
        t.name for t in registry.schemas_for(["knowledge"])}
    for g in ("knowledge", "memory", "usage"):
        assert 0 < len(registry.schemas_for([g])) <= 5, g
    assert "knowledge" in router.rule_groups("how does the fast path work in my code")
    assert "knowledge" in router.rule_groups("search my notes for the wifi setup")
    assert "knowledge" in router.rule_groups("where did I configure telegram in this repo")
    assert router.rule_groups("how many tokens did I use")[0] == "usage"
    assert "memory" in router.rule_groups("what did we talk about yesterday")
    assert "files" not in router.rule_groups("what does my code do with telegram")


# --------------------------------------------------------------------------- RAM rules (8 GB laptop)
def test_vectors_float16_streamed_in_blocks(tmp_path, idx, fake_model):
    make_repo(tmp_path / "repo")
    idx.index_path(tmp_path / "repo")
    assert idx.vec_dtype() == "float16"
    blob = idx._q("SELECT vec FROM vectors LIMIT 1")[0][0]
    assert len(blob) == FakeModel.dim * 2
    qv = idx.embedder.embed(["telegram stale messages"], query=True)[0]
    full = idx.scan_vectors(qv, 3)
    assert idx.scan_vectors(qv, 3, block=1) == full  # block-streamed top-n == one-shot
    assert not hasattr(idx, "_mat")  # no vector matrix kept between searches


def test_no_heavy_imports_at_startup_or_in_digest_worker():
    import subprocess
    import sys
    code = ("import sys; import jarvis.core.agent, jarvis.core.memory, jarvis.workers.daily_digest, jarvis.core.digest;"
            "bad=[m for m in ('fastembed','onnxruntime','numpy') if m in sys.modules];"
            "print(bad)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(config.ROOT), timeout=60)
    assert out.stdout.strip() == "[]", out.stderr[-500:]
    code2 = ("import sys; import jarvis.workers.daily_digest, jarvis.core.digest;"
             "print([m for m in ('langchain_core','jarvis.core.llm','jarvis.core.registry','fastembed') if m in sys.modules])")
    out2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True, cwd=str(config.ROOT), timeout=60)
    assert out2.stdout.strip() == "[]", out2.stderr[-500:]
