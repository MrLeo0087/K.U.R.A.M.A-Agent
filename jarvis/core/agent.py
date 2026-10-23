"""LangGraph agent on LangChain messages: route -> llm (model.bind_tools with only the routed
groups' tools) -> tools (our own node: safety confirm/blocked + logging) -> llm ... -> answer.

Fast tier by default; smart tier when more than one group is routed or the router flags
reasoning. History is the last config.HISTORY_TURNS turns plus a rolling summary (fast tier).
`run()` returns the answer; `stream()` yields text deltas (for TTS) as the model writes them.

Multitasking (P3b-2): a plan node runs first. One quick task -> the path above, unchanged.
Several tasks -> LangGraph Send fan-out: each quick task runs the route->llm->tools subgraph
concurrently (own state), each long task is submitted to the JobManager and returns at once; a
join node composes ONE reply without an LLM call. History is updated once, at the end.
"""
from __future__ import annotations

import logging
import operator
import threading
import time
from typing import Annotated, Any, Callable, Iterator, TypedDict

from langchain_core.messages import (AIMessage, BaseMessage, HumanMessage, SystemMessage,
                                     ToolMessage)

from jarvis.core import config, jobs, llm, planner, registry, router, safety, store

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
VOICE_SUFFIX = (" Your reply is spoken aloud: plain sentences, no markdown or lists. Default to 1-2 short "
                "sentences; if the user asks to explain or for detail, give up to 6 sentences. "
                "The user spoke {lang}; reply in {lang}.")
SUMMARY_SUFFIX = " Earlier conversation (summary): {summary}"
SUMMARY_PROMPT = (
    "Update the running summary of a chat between a user and the assistant Jarvis. "
    "Keep facts, decisions and user preferences; drop small talk. Under 60 words, plain text."
)
NO_ANSWER = "Sorry, I don't have an answer for that."
TOO_MANY_ROUNDS = "Sorry, that took too many steps; please try a simpler request."
JOB_STARTED = {
    "write": {"en": 'I\'m writing "{title}" in the background (job #{id}); I\'ll tell you when it\'s done.',
              "hi": 'मैं "{title}" बैकग्राउंड में लिख रहा हूँ (जॉब #{id}); पूरा होने पर बताऊँगा।',
              "ne": 'म "{title}" पृष्ठभूमिमा लेख्दैछु (काम #{id}); सकिएपछि भन्छु।'},
    "scan": {"en": 'I\'m working on "{title}" in the background (job #{id}); I\'ll tell you when it\'s done.',
             "hi": 'मैं "{title}" पर बैकग्राउंड में काम कर रहा हूँ (जॉब #{id}); पूरा होने पर बताऊँगा।',
             "ne": 'म "{title}" मा पृष्ठभूमिमा काम गर्दैछु (काम #{id}); सकिएपछि भन्छु।'},
}
TASK_FAILED = "Sorry, I couldn't do that part: {text}."


class AgentState(TypedDict, total=False):
    user_text: str
    messages: list[BaseMessage]
    groups: list[str]
    tools: list[Any]  # LangChain tools of the routed groups
    tier: str
    rounds: int
    pending: list[dict]
    answer: str
    stream: bool
    mode: str
    lang: str | None
    tasks: list[dict]  # planner output: [{"text", "kind": quick|long}]
    task: dict  # one fanned-out task (Send payload)
    idx: int
    results: Annotated[list, operator.add]  # fan-out results, merged by the join node


def job_started_text(job_id: int, title: str, kind: str, lang: str | None) -> str:
    tpl = JOB_STARTED["scan" if kind == "scan" else "write"]
    return tpl.get(lang or "en", tpl["en"]).format(id=job_id, title=title)


class Agent:
    def __init__(self, confirm: Callable[[str], bool] | None = None, summarize_async: bool = True,
                 use_planner: bool = True):
        self.confirm = confirm  # overrides safety.get_confirm(mode) when set
        self.summarize_async = summarize_async
        self.use_planner = use_planner
        self._task_graph: Any = None
        self.history: list[BaseMessage] = []
        self.summary = ""
        self._overflow: list[BaseMessage] = []
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._graph: Any = None
        self.last: dict = {}

    # --- graph ---
    def _build(self, planned: bool | None = None) -> Any:
        from langgraph.graph import END, START, StateGraph  # lazy: keeps `import jarvis` light

        planned = self.use_planner if planned is None else planned
        g = StateGraph(AgentState)
        g.add_node("route", self._route_node)
        g.add_node("llm", self._llm_node)
        g.add_node("tools", self._tools_node)
        g.add_edge("route", "llm")
        g.add_conditional_edges("llm", lambda s: "tools" if s.get("pending") else END,
                                {"tools": "tools", END: END})
        g.add_edge("tools", "llm")
        if not planned:
            g.add_edge(START, "route")
            return g.compile()
        g.add_node("plan", self._plan_node)
        g.add_node("quick", self._quick_node)
        g.add_node("long", self._long_node)
        g.add_node("join", self._join_node)
        g.add_edge(START, "plan")
        g.add_conditional_edges("plan", self._after_plan, ["route", "quick", "long"])
        g.add_edge("quick", "join")
        g.add_edge("long", "join")
        g.add_edge("join", END)
        return g.compile()

    @property
    def task_graph(self) -> Any:
        """The single-task route->llm->tools graph run by each fanned-out quick task."""
        if self._task_graph is None:
            self._task_graph = self._build(planned=False)
        return self._task_graph

    # --- planning / fan-out ---
    def _plan_node(self, state: AgentState) -> dict:
        t0 = time.monotonic()
        p = planner.plan(state["user_text"])
        self.last["plan"] = {"method": p.method, "tasks": p.tasks,
                             "ms": int((time.monotonic() - t0) * 1000)}
        return {"tasks": p.tasks}

    @staticmethod
    def _after_plan(state: AgentState) -> Any:
        from langgraph.types import Send

        tasks = state.get("tasks") or []
        if len(tasks) <= 1 and (not tasks or tasks[0]["kind"] == "quick"):
            return "route"  # normal single request: unchanged path
        base = {"mode": state.get("mode", "text"), "lang": state.get("lang"),
                "user_text": state["user_text"]}
        return [Send("long" if t["kind"] == "long" else "quick", {**base, "task": t, "idx": i})
                for i, t in enumerate(tasks)]

    def _quick_node(self, state: AgentState) -> dict:
        t, mode = state["task"], state.get("mode", "text")
        sub: AgentState = {"user_text": t["text"], "messages": self._messages(t["text"], mode, state.get("lang")),
                           "stream": False, "mode": mode, "rounds": 0, "pending": []}
        try:
            final = self.task_graph.invoke(sub, self._config())
            answer = final.get("answer") or NO_ANSWER
        except llm.LLMError as e:
            log.warning("quick task failed: %s", e)
            answer = TASK_FAILED.format(text=t["text"])
        return {"results": [{"idx": state.get("idx", 0), "kind": "quick", "text": t["text"],
                             "answer": answer}]}

    def _long_node(self, state: AgentState) -> dict:
        t = state["task"]
        lang = state.get("lang") or planner.detect_lang(t["text"])
        try:
            job = jobs.start_task(t["text"], lang=lang)
        except Exception as e:
            log.exception("could not start job")
            return {"results": [{"idx": state.get("idx", 0), "kind": "quick", "text": t["text"],
                                 "answer": TASK_FAILED.format(text=t["text"]), "error": str(e)}]}
        return {"results": [{"idx": state.get("idx", 0), "kind": "long", "text": t["text"],
                             "job_id": job.id, "title": job.title, "job_kind": job.kind}]}

    def _join_node(self, state: AgentState) -> dict:
        lang = state.get("lang") or planner.detect_lang(state["user_text"])
        results = sorted(state.get("results") or [], key=lambda r: r.get("idx", 0))
        quick = [r["answer"].strip() for r in results if r["kind"] == "quick" and r.get("answer")]
        longs = [job_started_text(r["job_id"], r["title"], r.get("job_kind", "write"), lang)
                 for r in results if r["kind"] == "long"]
        self.last["jobs"] = [r["job_id"] for r in results if r["kind"] == "long"]
        return {"answer": " ".join(quick + longs).strip() or NO_ANSWER}

    def warm(self) -> None:
        """Pay import/compile/model-setup costs now (startup), not on the first turn."""
        from langgraph.config import get_stream_writer  # noqa: F401  (imported by stream turns)

        _ = self.graph
        registry.groups()
        router.rule_groups("warm up")
        llm.warm()

    @property
    def graph(self) -> Any:
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    def _route_node(self, state: AgentState) -> dict:
        r = router.route(state["user_text"])
        tools = registry.schemas_for(r.groups) if r.groups else []
        tier = "smart" if (len(r.groups) > 1 or r.reasoning) else "fast"
        if tier == "fast" and not tools and state.get("mode") == "voice":
            tier = "voice"  # plain spoken chat: lowest time-to-first-token model
        self.last.update(route=r, tier=tier, tools_sent=[t.name for t in tools])
        return {"groups": r.groups, "tools": tools, "tier": tier, "rounds": 0, "pending": []}

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
        ai = reply.message or AIMessage(content=reply.text)
        calls = [] if last_round else list(ai.tool_calls)
        bad = [] if last_round else list(getattr(ai, "invalid_tool_calls", None) or [])
        if calls or bad:
            calls = [{**tc, "id": tc.get("id") or f"call_{rounds}_{i}"} for i, tc in enumerate(calls)]
            bad = [{**tc, "id": tc.get("id") or f"bad_{rounds}_{i}"} for i, tc in enumerate(bad)]
            msg = AIMessage(content=reply.text, tool_calls=calls, invalid_tool_calls=bad)
            return {"messages": msgs + [msg], "pending": calls + bad}
        answer = reply.text.strip() or (TOO_MANY_ROUNDS if ai.tool_calls else NO_ANSWER)
        return {"messages": msgs + [AIMessage(content=answer)], "pending": [], "answer": answer}

    def _chat(self, msgs: list[BaseMessage], kw: dict, stream: bool) -> llm.Reply:
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
        allowed = {t.name for t in state.get("tools") or []}
        confirm = self.confirm or safety.get_confirm(state.get("mode", "text"))
        out: list[BaseMessage] = []
        for tc in state.get("pending") or []:
            name, args = tc.get("name") or "", tc.get("args")
            if name not in allowed:
                content = f"error: tool {name!r} is not available for this request"
                store.log_tool(name, args, False, 0, safety="unknown", error="not routed",
                               outcome="error", result=content)
                ok = False
            else:
                res = safety.execute(name, args, confirm=confirm)
                content, ok = res.output, res.ok
            self.last.setdefault("tools", []).append({"name": name, "ok": ok})
            out.append(ToolMessage(content=content, tool_call_id=tc["id"], name=name))
        return {"messages": state["messages"] + out, "pending": [],
                "rounds": state.get("rounds", 0) + 1}

    # --- history ---
    def _messages(self, user_text: str, mode: str, lang: str | None) -> list[BaseMessage]:
        system = SYSTEM_PROMPT
        if mode == "voice":
            system += VOICE_SUFFIX.format(lang=LANG_NAMES.get(lang or "en", "English"))
        with self._lock:
            if self.summary:
                system += SUMMARY_SUFFIX.format(summary=self.summary)
            recent = self.history[-2 * config.HISTORY_TURNS:]
        return [SystemMessage(content=system), *recent, HumanMessage(content=user_text)]

    def _remember(self, user_text: str, answer: str) -> None:
        batch: list[BaseMessage] = []
        with self._lock:
            self.history += [HumanMessage(content=user_text), AIMessage(content=answer)]
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

    def _summarize(self, turns: list[BaseMessage]) -> None:
        names = {"human": "user", "ai": "assistant"}
        transcript = "\n".join(f"{names.get(m.type, m.type)}: {str(m.content)[:400]}" for m in turns)
        msgs = [SystemMessage(content=SUMMARY_PROMPT),
                HumanMessage(content=f"Current summary: {self.summary or 'none'}\n\n"
                                     f"New turns:\n{transcript}")]
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
                "stream": stream, "mode": mode, "lang": lang, "rounds": 0, "pending": []}

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


def warm() -> None:
    get_agent().warm()


def run(user_text: str, mode: str = "text", lang: str | None = None) -> str:
    return get_agent().run(user_text, mode=mode, lang=lang)


def stream(user_text: str, mode: str = "text", lang: str | None = None) -> Iterator[str]:
    return get_agent().stream(user_text, mode=mode, lang=lang)
