"""LangGraph agent: route -> llm (only the routed groups' schemas) -> tools -> llm ... -> answer.

Fast tier by default; smart tier when more than one group is routed or the router flags
reasoning. History is the last config.HISTORY_TURNS turns plus a rolling summary (fast tier).
`run()` returns the answer; `stream()` yields text deltas (for TTS) as the model writes them.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Iterator, TypedDict

from jarvis.core import config, llm, registry, router, safety, store

log = logging.getLogger("jarvis.agent")

LANG_NAMES = {"en": "English", "ne": "Nepali (Devanagari script)", "hi": "Hindi (Devanagari script)"}

SYSTEM_PROMPT = (
    "You are Jarvis, a concise, friendly assistant on the user's Ubuntu laptop. "
    "Reply in 1-2 short sentences unless asked for more detail. "
    "Answer in the user's language (English, Hindi or Nepali). "
    "Plain text only: no markdown, lists or emojis, since replies may be spoken aloud. "
    "Use a tool only when needed to answer or act, and never invent tool results. "
    "If a tool is declined or fails, say so briefly. If you do not know something, say so."
)
VOICE_SUFFIX = " Your reply is spoken: keep it to 1-2 short sentences. The user spoke {lang}; reply in {lang}."
SUMMARY_SUFFIX = " Earlier conversation (summary): {summary}"
SUMMARY_PROMPT = (
    "Update the running summary of a chat between a user and the assistant Jarvis. "
    "Keep facts, decisions and user preferences; drop small talk. Under 60 words, plain text."
)
NO_ANSWER = "Sorry, I don't have an answer for that."
TOO_MANY_ROUNDS = "Sorry, that took too many steps; please try a simpler request."


class AgentState(TypedDict, total=False):
    user_text: str
    messages: list[dict]
    groups: list[str]
    tools: list[dict]
    tier: str
    rounds: int
    pending: list[dict]
    answer: str
    stream: bool
    mode: str


class Agent:
    def __init__(self, confirm: Callable[[str], bool] | None = None, summarize_async: bool = True):
        self.confirm = confirm  # overrides safety.get_confirm(mode) when set
        self.summarize_async = summarize_async
        self.history: list[dict] = []
        self.summary = ""
        self._overflow: list[dict] = []
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._graph: Any = None
        self.last: dict = {}

    # --- graph ---
    def _build(self) -> Any:
        from langgraph.graph import END, START, StateGraph  # lazy: keeps `import jarvis` light

        g = StateGraph(AgentState)
        g.add_node("route", self._route_node)
        g.add_node("llm", self._llm_node)
        g.add_node("tools", self._tools_node)
        g.add_edge(START, "route")
        g.add_edge("route", "llm")
        g.add_conditional_edges("llm", lambda s: "tools" if s.get("pending") else END,
                                {"tools": "tools", END: END})
        g.add_edge("tools", "llm")
        return g.compile()

    @property
    def graph(self) -> Any:
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    def _route_node(self, state: AgentState) -> dict:
        r = router.route(state["user_text"])
        schemas = registry.schemas_for(r.groups) if r.groups else []
        tier = "smart" if (len(r.groups) > 1 or r.reasoning) else "fast"
        self.last.update(route=r, tier=tier, tools_sent=[s["function"]["name"] for s in schemas])
        return {"groups": r.groups, "tools": schemas, "tier": tier, "rounds": 0, "pending": []}

    def _llm_node(self, state: AgentState) -> dict:
        tools = state.get("tools") or None
        rounds = state.get("rounds", 0)
        last_round = rounds >= config.AGENT_MAX_TOOL_ROUNDS
        kw: dict[str, Any] = {"tier": state.get("tier", "fast"), "tools": tools,
                              "purpose": f"agent_{state.get('mode', 'text')}",
                              "max_tokens": config.AGENT_MAX_TOKENS}
        if tools and last_round:
            kw["tool_choice"] = "none"
        msgs = state["messages"]
        try:
            reply = self._chat(msgs, kw, state.get("stream", False))
        except llm.LLMError as e:
            if not tools or "tool" not in str(e).lower() or kw.get("tool_choice") == "none":
                raise
            log.warning("tool call generation failed, retrying without tools: %s", e)
            reply = self._chat(msgs, {**kw, "tool_choice": "none"}, state.get("stream", False))
        calls = [] if last_round else list(reply.tool_calls)
        if calls:
            msg: dict = {"role": "assistant", "tool_calls": [
                {"id": tc.get("id") or f"call_{rounds}_{i}", "type": "function",
                 "function": {"name": tc.get("name", ""), "arguments": tc.get("arguments") or "{}"}}
                for i, tc in enumerate(calls)]}
            if reply.text:
                msg["content"] = reply.text
            return {"messages": msgs + [msg], "pending": msg["tool_calls"]}
        answer = reply.text.strip() or (TOO_MANY_ROUNDS if reply.tool_calls else NO_ANSWER)
        return {"messages": msgs + [{"role": "assistant", "content": answer}], "pending": [],
                "answer": answer}

    def _chat(self, msgs: list[dict], kw: dict, stream: bool) -> llm.Reply:
        if not stream:
            return llm.chat(msgs, **kw)
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        gen = llm.chat(msgs, stream=True, **kw)
        parts: list[str] = []
        while True:
            if self._abort.is_set():  # consumer went away (barge-in): stop generating
                gen.close()
                return llm.Reply("".join(parts), "", [])
            try:
                delta = next(gen)
            except StopIteration as stop:
                return stop.value or llm.Reply("".join(parts), "", [])
            parts.append(delta)
            writer(delta)

    def _tools_node(self, state: AgentState) -> dict:
        allowed = {s["function"]["name"] for s in state.get("tools") or []}
        confirm = self.confirm or safety.get_confirm(state.get("mode", "text"))
        out: list[dict] = []
        for tc in state.get("pending") or []:
            name, args = tc["function"]["name"], tc["function"]["arguments"]
            if name not in allowed:
                content = f"error: tool {name!r} is not available for this request"
                store.log_tool(name, args, False, 0, safety="unknown", error="not routed",
                               outcome="error", result=content)
                ok = False
            else:
                res = safety.execute(name, args, confirm=confirm)
                content, ok = res.output, res.ok
            self.last.setdefault("tools", []).append({"name": name, "ok": ok})
            out.append({"role": "tool", "tool_call_id": tc["id"], "content": content})
        return {"messages": state["messages"] + out, "pending": [],
                "rounds": state.get("rounds", 0) + 1}

    # --- history ---
    def _messages(self, user_text: str, mode: str, lang: str | None) -> list[dict]:
        system = SYSTEM_PROMPT
        if mode == "voice":
            system += VOICE_SUFFIX.format(lang=LANG_NAMES.get(lang or "en", "English"))
        with self._lock:
            if self.summary:
                system += SUMMARY_SUFFIX.format(summary=self.summary)
            recent = self.history[-2 * config.HISTORY_TURNS:]
        return [{"role": "system", "content": system}, *recent,
                {"role": "user", "content": user_text}]

    def _remember(self, user_text: str, answer: str) -> None:
        batch: list[dict] = []
        with self._lock:
            self.history += [{"role": "user", "content": user_text},
                             {"role": "assistant", "content": answer}]
            while len(self.history) > 2 * config.HISTORY_TURNS:
                self._overflow += self.history[:2]
                self.history = self.history[2:]
            if len(self._overflow) >= 2 * config.AGENT_SUMMARY_BATCH_TURNS:
                batch, self._overflow = self._overflow, []
        if batch:
            if self.summarize_async:
                threading.Thread(target=self._summarize, args=(batch,), name="summary",
                                 daemon=True).start()
            else:
                self._summarize(batch)

    def _summarize(self, turns: list[dict]) -> None:
        transcript = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in turns)
        msgs = [{"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": f"Current summary: {self.summary or 'none'}\n\n"
                                            f"New turns:\n{transcript}"}]
        try:
            text = str(llm.chat(msgs, tier="fast", purpose="summary", max_tokens=300)).strip()
        except llm.LLMError as e:
            log.warning("summary failed: %s", e)
            return
        if text:
            with self._lock:
                self.summary = text[:600]

    # --- public API ---
    def _state(self, user_text: str, mode: str, lang: str | None, stream: bool) -> AgentState:
        self.last = {"tools": [], "t0": time.monotonic()}
        return {"user_text": user_text, "messages": self._messages(user_text, mode, lang),
                "stream": stream, "mode": mode, "rounds": 0, "pending": []}

    @staticmethod
    def _config() -> dict:
        return {"recursion_limit": 2 * config.AGENT_MAX_TOOL_ROUNDS + 6}

    def run(self, user_text: str, mode: str = "text", lang: str | None = None) -> str:
        final = self.graph.invoke(self._state(user_text, mode, lang, False), self._config())
        answer = final.get("answer") or NO_ANSWER
        self._remember(user_text, answer)
        return answer

    def stream(self, user_text: str, mode: str = "text", lang: str | None = None) -> Iterator[str]:
        """Yield answer text deltas. Tool rounds (and confirmations) happen before the first one."""
        state = self._state(user_text, mode, lang, True)
        self._abort.clear()
        parts: list[str] = []
        final: dict | None = None
        try:
            for kind, chunk in self.graph.stream(state, self._config(),
                                                 stream_mode=["custom", "values"]):
                if kind == "custom":
                    parts.append(chunk)
                    yield chunk
                else:
                    final = chunk
            answer = (final or {}).get("answer") or ""
            if answer and not parts:  # nothing streamed (fallback text): emit it whole
                parts.append(answer)
                yield answer
        finally:
            if final is None or not final.get("answer"):
                self._abort.set()  # stopped early (barge-in / error): tell the graph thread to quit
                if parts:
                    self._remember(user_text, "".join(parts).strip())
        if final and final.get("answer"):
            self._remember(user_text, final["answer"])


_default: Agent | None = None


def get_agent() -> Agent:
    global _default
    if _default is None:
        _default = Agent()
    return _default


def run(user_text: str, mode: str = "text", lang: str | None = None) -> str:
    return get_agent().run(user_text, mode=mode, lang=lang)


def stream(user_text: str, mode: str = "text", lang: str | None = None) -> Iterator[str]:
    return get_agent().stream(user_text, mode=mode, lang=lang)
